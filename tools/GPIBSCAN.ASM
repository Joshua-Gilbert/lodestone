; =====================================================================
;  GPIBSCAN.COM - direct uPD7210 GPIB probe & bus scan        (Lodestone)
;  Build: nasm -f bin -o GPIBSCAN.COM GPIBSCAN.ASM
;
;  GPIBSCAN         detect the 7210, take control of the bus, serial-poll
;                   addresses 0-30 and list who answers
;  GPIBSCAN /ID     ...and also ask each device who it is ("ID?", then
;                   "*IDN?" if it stays silent)
;  GPIBSCAN /F      run even if Driver488 (DRVR488) is loaded
;  GPIBSCAN /W[nn]  watch mode: keep serial-polling one EMPTY address
;                   (default 3) and show GHOST / CLEAN live - power
;                   instruments off one by one to find a ghost talker.
;                   Any key exits.
;  1.5: ID? answers not starting "ID" fall through to *IDN?
;  1.4: answers slower than GHOSTLAT poll loops are treated as ghosts
;  (real instruments answer in 1-2 loops) and are not ID-queried.
;
;  Output goes to the screen and A:\GPIBSCAN.TXT.
;
;  1.1: serial poll follows Driver488 rev 2.6 exactly (flush DIR, RFD
;  holdoff on all data via AUXRA 91h, ISR1 read through a software shadow
;  with the double-read DI/DO quirk, TCS + release holdoff afterwards).
;  Adds a 'ghost byte' control test (listen with no talker addressed),
;  polls every address twice, and logs raw ISR1/ADSR on first answer.
;
;  1.2: never uses TCS (it waits forever if no handshake is in flight -
;  that hung 1.1 after a stray DI flag).  Status byte is taken under RFD
;  holdoff, then TCA (async) + release holdoff.  ISR1 latches and DIR are
;  cleared right before listening.  If the chip ever stops accepting
;  commands it is re-initialised (IFC) and the recovery is counted.
;  Prints a one-line address map at the end.
;
;  1.3: ISR2 (CO) and ISR1 (DI/DO/ERR/END) are *latched and cleared on
;  read* on the real chip, so both are read through software shadows like
;  Driver488 does.  CO is only consumed when a command byte is actually
;  written; 'wait for command idle' peeks without consuming.  1.2 consumed
;  CO in a readiness check, so the next command always timed out.
;  Hardware: uPD7210 at 02E1h, register n at 02E1h + n*400h (IOtech
;  Personal488 / NI PC2A layout, as configured in DRVR488 on the 1520).
;  The Grid is system controller at address 21.  Every bus operation is
;  polled with a BIOS-tick timeout - no fixed delays anywhere.
; =====================================================================
cpu 286
org 100h

BASE    equ 02E1h
R_DIR   equ BASE+0000h      ; r: data in        w: CDOR data out
R_ISR1  equ BASE+0400h      ; r: int status 1   w: IMR1
R_ISR2  equ BASE+0800h      ; r: int status 2   w: IMR2
R_SPSR  equ BASE+0C00h      ; r: serial poll st w: SPMR
R_ADSR  equ BASE+1000h      ; r: address status w: ADMR
R_CPTR  equ BASE+1400h      ; r: cmd pass thru  w: AUXMR
R_ADR0  equ BASE+1800h      ; r: address 0      w: ADR
R_ADR1  equ BASE+1C00h      ; r: address 1      w: EOSR
R_CDOR  equ R_DIR
R_IMR1  equ R_ISR1
R_IMR2  equ R_ISR2
R_SPMR  equ R_SPSR
R_ADMR  equ R_ADSR
R_AUXMR equ R_CPTR
R_ADR   equ R_ADR0

ISR1_DI  equ 01h
ISR1_DO  equ 02h
ISR1_ERR equ 04h
ISR1_END equ 10h
ISR2_CO  equ 08h
ADSR_CIC equ 80h

AUX_PON  equ 00h
AUX_CR   equ 02h
AUX_SEOI equ 06h
AUX_GTS  equ 10h
AUX_TCA  equ 11h
AUX_CIFC equ 16h
AUX_CREN equ 17h
AUX_SIFC equ 1Eh
AUX_SREN equ 1Fh

MYADDR  equ 21
UNL     equ 3Fh
UNT     equ 5Fh
SPE     equ 18h
SPD     equ 19h

T_CMD   equ 9                   ; ~0.5 s for command bytes
T_SPOLL equ 3                   ; ~0.15 s for a serial-poll answer
T_DATA  equ 36                  ; ~2 s for data bytes
GHOSTLAT equ 8                  ; answers slower than this = ghost

start:  cld
        call    parse_args
        call    log_open
        mov     dx, s_title
        call    puts

        ; ---- refuse to fight Driver488 ---------------------------------
        mov     dx, n_ieeeout
        mov     ax, 3D00h
        int     21h
        jc      .nodrv
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
        mov     dx, s_drv488
        call    puts
        cmp     byte [opt_f], 0
        jne     .nodrv
        jmp     quit

.nodrv: ; ---- raw register snapshot (read-only) -----------------------
        mov     dx, s_regs
        call    puts
        mov     si, regtab
        mov     cx, 8
.rr:    lodsw
        mov     dx, ax
        in      al, dx
        call    phex8
        mov     al, ' '
        call    putc
        loop    .rr
        call    crlf

        ; ---- reset + init as system controller ------------------------
        call    chip_init
        mov     dx, R_ADR0              ; ADR0 must echo our address
        in      al, dx
        and     al, 1Fh
        cmp     al, MYADDR
        je      .found
        mov     dx, s_nochip
        call    puts
        jmp     quit
.found: mov     dx, s_chip
        call    puts

        mov     dx, R_AUXMR             ; IFC: become controller in charge
        mov     al, AUX_SIFC
        out     dx, al
        call    wait_tick               ; >= 100 us (one tick is plenty)
        mov     al, AUX_CIFC
        out     dx, al
        mov     al, AUX_SREN            ; assert REN
        out     dx, al
        mov     dx, R_ADSR
        in      al, dx
        mov     [adsr], al
        mov     dx, s_cic
        call    puts
        mov     al, [adsr]
        call    phex8
        test    byte [adsr], ADSR_CIC
        jnz     .cicok
        mov     dx, s_notcic
        call    puts
        jmp     release
.cicok: mov     dx, s_cicyes
        call    puts
        call    commit
        cmp     byte [opt_w], 0
        je      .nowatch
        call    watch
        jmp     release
.nowatch:

        ; ---- control test: listen with nobody addressed to talk -------
        call    ghost_test
        call    commit

        ; ---- serial-poll every address (twice) ---------------------------
        mov     dx, s_scan
        call    puts
        xor     bx, bx                  ; BL = address
.sc:    cmp     bl, MYADDR
        je      .scn
        call    spoll                   ; CF=0 -> AL = status byte
        jc      .scn
        mov     [stat], al
        mov     ax, [lat]
        mov     [lat1], ax
        call    spoll                   ; must answer again
        jnc     .twice
        mov     byte [amap+bx], '?'
        mov     dx, s_addr
        call    puts
        mov     al, bl
        xor     ah, ah
        call    pdec2
        mov     dx, s_once
        call    puts
        jmp     .scn
.twice: mov     [stat2], al
        cmp     word [lat1], GHOSTLAT
        ja      .ghostans
        cmp     word [lat], GHOSTLAT
        jbe     .real
.ghostans:
        mov     byte [amap+bx], 'g'
        inc     byte [nghost]
        jmp     .scn
.real:  mov     byte [amap+bx], '#'
        inc     byte [nfound]
        mov     di, [nfound]
        and     di, 0FFh
        mov     [found+di-1], bl
        mov     dx, s_addr
        call    puts
        mov     al, bl
        xor     ah, ah
        call    pdec2
        mov     dx, s_stat
        call    puts
        mov     al, [stat]
        call    phex8
        mov     dx, s_stat2
        call    puts
        mov     al, [stat2]
        call    phex8
        mov     dx, s_lat
        call    puts
        mov     ax, [lat1]
        call    pdec
        mov     al, '/'
        call    putc
        mov     ax, [lat]
        call    pdec
        cmp     byte [rawshown], 0
        jne     .nr
        mov     byte [rawshown], 1
        mov     dx, s_raw
        call    puts
        mov     al, [rawisr1]
        call    phex8
        mov     dx, s_rawads
        call    puts
        mov     al, [rawadsr]
        call    phex8
        mov     dx, s_rawend
        call    puts
.nr:    call    crlf
.scn:   inc     bl
        cmp     bl, 31
        jb      .sc
        mov     byte [amap+MYADDR], '*'
        mov     dx, s_map
        call    puts
        mov     dx, amap
        call    puts
        mov     dx, s_recov
        call    puts
        mov     ax, [recov]
        call    pdec
        call    crlf
        mov     dx, s_ghcnt
        call    puts
        mov     al, [nghost]
        xor     ah, ah
        call    pdec
        call    crlf
        mov     dx, s_nfound
        call    puts
        mov     al, [nfound]
        xor     ah, ah
        call    pdec
        mov     dx, s_devs
        call    puts
        call    commit

        ; ---- optional identification -----------------------------------
        cmp     byte [opt_id], 0
        je      release
        cmp     byte [nfound], 0
        je      release
        mov     dx, s_idhdr
        call    puts
        xor     si, si
.id:    mov     bl, [found+si]
        push    si
        mov     dx, s_addr
        call    puts
        mov     al, bl
        xor     ah, ah
        call    pdec2
        mov     dx, s_colon
        call    puts
        mov     byte [rbuf2], '$'
        mov     si, q_id                ; Tektronix TM5000 style
        call    query
        jc      .try2
        cmp     word [rbuf], 'ID'       ; a real Tek answer starts "ID"
        je      .idok
        push    si                      ; something else answered (HP 8753D
        mov     si, rbuf                ; says "0") - keep it, try 488.2
        mov     di, rbuf2
        mov     cx, RBUFLEN+2
        push    es
        push    ds
        pop     es
        rep     movsb
        pop     es
        pop     si
.try2:  mov     si, q_idn               ; IEEE 488.2 style
        call    query
        jnc     .idok
        cmp     byte [rbuf2], '$'
        je      .none
        mov     dx, s_idq
        call    puts
        mov     dx, rbuf2
        call    puts
        mov     dx, s_idq2
        call    puts
        jmp     .idn
.none:  mov     dx, s_noid
        call    puts
        jmp     .idn
.idok:  mov     dx, rbuf
        call    puts
.idn:   call    crlf
        call    commit
        pop     si
        inc     si
        mov     ax, si
        cmp     al, [nfound]
        jb      .id

release:                                ; hand the instruments back
        call    cmd_begin
        mov     al, UNL
        call    send_cmd
        mov     al, UNT
        call    send_cmd
        mov     dx, R_AUXMR
        mov     al, AUX_CREN            ; drop REN -> everyone local
        out     dx, al
        mov     dx, s_done
        call    puts
quit:   call    d_rearm                 ; (the driver's IMR2, IFC, REN)
        call    log_close
        mov     ax, 4C00h
        int     21h

%include "rearm.inc"

; =====================================================================
;  uPD7210 primitives
; =====================================================================
chip_init:
        mov     dx, R_AUXMR
        mov     al, AUX_CR              ; chip reset
        out     dx, al
        mov     al, 28h                 ; ICR: 8 MHz clock (as DRVR488)
        out     dx, al
        xor     al, al
        mov     dx, R_IMR1
        out     dx, al
        mov     dx, R_IMR2
        out     dx, al
        mov     dx, R_SPMR
        out     dx, al
        mov     dx, R_ADMR
        mov     al, 31h                 ; mode 1, TRM1/TRM0 = normal
        out     dx, al
        mov     dx, R_ADR
        mov     al, MYADDR              ; primary address, talk+listen
        out     dx, al
        mov     al, 0E0h                ; ADR1: disabled
        out     dx, al
        mov     dx, R_ADR1
        mov     al, 0Ah                 ; EOS = LF (not enabled by default)
        out     dx, al
        mov     dx, R_AUXMR
        mov     al, 80h                 ; AUXRA: normal handshake
        out     dx, al
        mov     al, 0A0h                ; AUXRB: defaults
        out     dx, al
        mov     al, AUX_PON             ; leave reset state
        out     dx, al
        ret

; wait for the next BIOS tick (>= 0..55 ms)
wait_tick:
        push    ax
        push    bx
        call    tick
        mov     bx, ax
.w:     call    tick
        cmp     ax, bx
        je      .w
        pop     bx
        pop     ax
        ret

tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

; start a timeout of CX ticks
tmo_start:
        push    ax
        call    tick
        mov     [t_start], ax
        mov     [t_len], cx
        pop     ax
        ret

; CF=1 if the timeout has expired
tmo_check:
        push    ax
        call    tick
        sub     ax, [t_start]
        cmp     ax, [t_len]
        pop     ax
        cmc                             ; ax>=len -> NC -> make it CY
        ret

; take control (ATN on).  Only when in standby (ADSR bit 6 set), exactly
; like Driver488; the stale CO is dropped so we wait for a fresh one.
cmd_begin:
        push    ax
        push    dx
        mov     dx, R_ADSR
        in      al, dx
        test    al, 40h
        jz      .x                      ; already active: nothing to do
        and     byte [shadow2], ~ISR2_CO
        mov     dx, R_AUXMR
        mov     al, AUX_TCA
        out     dx, al
.x:     pop     dx
        pop     ax
        ret

; go to standby (ATN off); CO seen so far is stale afterwards
do_gts: push    ax
        push    dx
        and     byte [shadow2], ~ISR2_CO
        mov     dx, R_AUXMR
        mov     al, AUX_GTS
        out     dx, al
        pop     dx
        pop     ax
        ret

; send command byte AL with ATN asserted; CF=1 on timeout.
; Consumes CO from the shadow only when the byte is written.
send_cmd:
        call    wait_co
        jc      .x
        push    dx
        and     byte [shadow2], ~ISR2_CO
        mov     dx, R_CDOR
        out     dx, al
        pop     dx
        clc
.x:     ret

; send_cmd with one recovery attempt
send_cmd_r:
        call    send_cmd
        jnc     .x
        call    recover
        call    send_cmd
.x:     ret

; serial poll address BL -> AL = status, CF=1 if nobody answered.
spoll:  push    bx
        push    cx
        push    dx
        call    ensure_ctrl
        mov     dx, R_AUXMR
        mov     al, 91h                 ; AUXRA: RFD holdoff on all data
        out     dx, al
        mov     al, UNL
        call    send_cmd
        jc      .fail
        mov     al, 20h+MYADDR          ; MLA
        call    send_cmd
        jc      .fail
        mov     al, bl
        or      al, 40h                 ; TAD
        call    send_cmd
        jc      .fail
        mov     al, SPE
        call    send_cmd
        jc      .fail
        call    wait_co
        jc      .fail
        call    clear_in                ; forget any stale DI / DIR byte
        call    do_gts
        mov     word [lat], 0
        mov     cx, T_SPOLL
        call    tmo_start
.w:     inc     word [lat]
        mov     ah, ISR1_DI
        call    isr1_test
        jnz     .got
        call    tmo_check
        jnc     .w
        jmp     .fail
.got:   mov     [rawisr1], al
        mov     dx, R_ADSR
        in      al, dx
        mov     [rawadsr], al
        mov     dx, R_DIR
        in      al, dx                  ; status byte (handshake held)
        mov     [rawdir], al
        call    spoll_end
        mov     al, [rawdir]
        clc
        jmp     .x
.fail:  call    spoll_end
        stc
.x:     pop     dx
        pop     cx
        pop     bx
        ret

; common exit: take control asynchronously (safe: RFD is held, nothing
; can be in flight), release the holdoff, normal handshake, SPD, UNT
spoll_end:
        call    cmd_begin               ; TCA (standby -> active)
        mov     dx, R_AUXMR
        mov     al, 03h                 ; release RFD holdoff
        out     dx, al
        mov     al, 90h                 ; AUXRA: normal handshake
        out     dx, al
        call    wait_co
        jnc     .ok
        call    recover
.ok:    mov     al, SPD
        call    send_cmd
        mov     al, UNT
        call    send_cmd
        ret

; make sure we hold ATN and the chip takes commands; recover if not
ensure_ctrl:
        push    ax
        push    dx
        call    cmd_begin
        call    wait_co
        jnc     .ok
        call    recover
.ok:    pop     dx
        pop     ax
        ret

; clear ISR1 latches (two reads), the software shadow and DIR
clear_in:
        push    ax
        push    dx
        mov     dx, R_ISR1
        in      al, dx
        in      al, dx
        mov     byte [shadow1], 0
        mov     dx, R_DIR
        in      al, dx
        pop     dx
        pop     ax
        ret

; re-initialise the chip and the bus (IFC), count it
recover:
        push    ax
        push    dx
        inc     word [recov]
        mov     byte [shadow2], 0
        mov     byte [shadow1], 0
        call    chip_init
        mov     dx, R_AUXMR
        mov     al, AUX_SIFC
        out     dx, al
        call    wait_tick
        mov     al, AUX_CIFC
        out     dx, al
        mov     al, AUX_SREN
        out     dx, al
        mov     byte [shadow1], 0
        call    wait_co
        pop     dx
        pop     ax
        ret

; Read ISR1 into the software shadow (the register clears on read; when
; DI/DO are set Driver488 reads it a second time and ORs the result).
; AH = bits to test.  Returns AL = shadow before clearing, ZF=0 if any
; tested bit was set (those bits are then removed from the shadow).
isr1_test:
        push    dx
        mov     dx, R_ISR1
        cli
        in      al, dx
        test    al, 03h
        jz      .one
        mov     dx, R_ISR1
        push    ax
        in      al, dx
        pop     dx
        or      al, dl
        mov     dx, R_ISR1
.one:   or      al, [shadow1]
        sti
        test    al, ah
        jz      .none
        push    ax
        not     ah
        and     al, ah
        mov     [shadow1], al
        pop     ax
        or      ah, 0FFh                ; ZF=0
        pop     dx
        ret
.none:  mov     [shadow1], al
        cmp     al, al                  ; ZF=1
        pop     dx
        ret

; control test: make ourselves listener with no talker and watch for data
ghost_test:
        mov     dx, s_ghost
        call    puts
        mov     dx, R_DIR
        in      al, dx
        mov     byte [shadow1], 0
        call    cmd_begin
        mov     al, UNL
        call    send_cmd
        mov     al, UNT
        call    send_cmd
        mov     al, 20h+MYADDR
        call    send_cmd
        call    wait_co
        call    do_gts
        mov     cx, T_SPOLL
        call    tmo_start
.w:     mov     ah, ISR1_DI
        call    isr1_test
        jnz     .ghost
        call    tmo_check
        jnc     .w
        mov     dx, s_clean
        call    puts
        jmp     .x
.ghost: push    ax
        mov     dx, s_ghosty
        call    puts
        pop     ax
        call    phex8
        mov     dx, s_ghostd
        call    puts
        mov     dx, R_DIR
        in      al, dx
        call    phex8
        mov     dx, s_ghosta
        call    puts
        mov     dx, R_ADSR
        in      al, dx
        call    phex8
        mov     dx, s_ghostn
        call    puts
.x:     call    cmd_begin
        mov     al, UNL
        call    send_cmd
        ret

; wait until CO is in the ISR2 shadow (peek - does NOT consume it)
wait_co:
        push    ax
        push    cx
        push    dx
        mov     cx, T_CMD
        call    tmo_start
        mov     dx, R_ISR2
.w:     in      al, dx
        or      [shadow2], al
        test    byte [shadow2], ISR2_CO
        jnz     .ok
        call    tmo_check
        jnc     .w
        stc
        jmp     .x
.ok:    clc
.x:     pop     dx
        pop     cx
        pop     ax
        ret

; query: send ASCIIZ at SI to device BL (EOI on last byte), then read the
; reply into rbuf ('$'-terminated for printing).  CF=1 if no reply.
query:  push    bx
        push    si
        call    cmd_begin
        mov     al, UNL
        call    send_cmd
        jc      .fail
        mov     al, 40h+MYADDR          ; MTA: we talk
        call    send_cmd
        jc      .fail
        mov     al, bl
        or      al, 20h                 ; LAD of the device
        call    send_cmd
        jc      .fail
        call    wait_co
        jc      .fail
        call    do_gts
.wb:    lodsb
        or      al, al
        jz      .sent
        mov     ah, al
        mov     cx, T_DATA
        call    tmo_start
        mov     dx, R_ISR1
.wdo:   push    ax
        mov     ah, ISR1_DO | ISR1_ERR
        call    isr1_test
        mov     dl, al
        pop     ax
        jz      .nodo
        test    dl, ISR1_ERR            ; no listeners
        jnz     .fail
        jmp     .put
.nodo:
        call    tmo_check
        jnc     .wdo
        jmp     .fail
.put:   cmp     byte [si], 0            ; last byte? -> send with EOI
        jne     .noeoi
        mov     dx, R_AUXMR
        mov     al, AUX_SEOI
        out     dx, al
.noeoi: mov     dx, R_CDOR
        mov     al, ah
        out     dx, al
        jmp     .wb
.sent:  mov     cx, T_DATA              ; wait for the last byte to go
        call    tmo_start
        mov     dx, R_ISR1
.wl:    push    ax
        mov     ah, ISR1_DO
        call    isr1_test
        pop     ax
        jnz     .rd
        call    tmo_check
        jnc     .wl
        jmp     .fail
        ; ---- now read the answer ----
.rd:    call    cmd_begin
        mov     al, UNL
        call    send_cmd
        jc      .fail
        mov     al, 20h+MYADDR          ; MLA
        call    send_cmd
        jc      .fail
        mov     al, bl
        or      al, 40h                 ; TAD
        call    send_cmd
        jc      .fail
        call    wait_co
        jc      .fail
        call    clear_in
        call    do_gts
        mov     di, rbuf
.rb:    mov     cx, T_DATA
        call    tmo_start
.wdi:   mov     ah, ISR1_DI
        call    isr1_test
        jnz     .byte
        call    tmo_check
        jnc     .wdi
        cmp     di, rbuf                ; timeout: fail only if nothing came
        je      .fail
        jmp     .eom
.byte:  mov     ah, al                  ; keep END flag
        mov     dx, R_DIR
        in      al, dx
        cmp     al, 20h                 ; keep printable text only
        jb      .ctl
        cmp     al, 7Eh
        ja      .ctl
        cmp     al, '$'
        je      .ctl
        cmp     di, rbuf+RBUFLEN
        jae     .ctl
        stosb
.ctl:   test    ah, ISR1_END
        jnz     .eom
        cmp     al, 0Ah                 ; LF also ends a message
        je      .eom
        jmp     .rb
.eom:   mov     byte [di], '$'
        call    cmd_begin
        mov     al, UNT
        call    send_cmd
        mov     al, UNL
        call    send_cmd
        clc
        jmp     .x
.fail:  call    cmd_begin
        mov     al, UNT
        call    send_cmd
        mov     al, UNL
        call    send_cmd
        stc
.x:     pop     si
        pop     bx
        ret

; =====================================================================
;  Watch mode
; =====================================================================
watch:  mov     dx, s_wat1
        call    puts
        mov     al, [watchad]
        xor     ah, ah
        call    pdec
        mov     dx, s_wat2
        call    puts
        call    commit
.lp:    mov     ah, 01h                 ; key pressed?
        int     16h
        jz      .poll
        xor     ah, ah
        int     16h
        ret
.poll:  mov     bl, [watchad]
        call    spoll
        mov     ah, 0                   ; state: 0 clean, 1 ghost, 2 real
        jc      .st
        mov     [stat], al
        mov     ah, 1
        cmp     word [lat], GHOSTLAT
        ja      .st
        mov     ah, 2
.st:    cmp     ah, [wstate]
        je      .pace
        mov     [wstate], ah
        cmp     ah, 0
        jne     .n0
        mov     dx, s_wcl
        call    puts
        jmp     .beep
.n0:    cmp     ah, 1
        jne     .n1
        mov     dx, s_wgh
        call    puts
        mov     al, [stat]
        call    phex8
        mov     dx, s_wgh2
        call    puts
        mov     ax, [lat]
        call    pdec
        mov     dx, s_wgh3
        call    puts
        jmp     .beep
.n1:    mov     dx, s_wreal
        call    puts
.beep:  mov     ax, 0E07h               ; BEL on every change
        int     10h
        call    commit
.pace:  mov     cx, 4                   ; ~0.2 s between polls
.pw:    call    wait_tick
        loop    .pw
        jmp     .lp

; =====================================================================
;  Arguments / output (screen + A:\GPIBSCAN.TXT)
; =====================================================================
parse_args:
        mov     si, 81h
.l:     lodsb
        cmp     al, 13
        je      .x
        cmp     al, '/'
        jne     .l
        mov     al, [si]
        or      al, 20h
        cmp     al, 'f'
        jne     .i
        mov     byte [opt_f], 1
        jmp     .l
.i:     cmp     al, 'i'
        jne     .w
        mov     byte [opt_id], 1
        jmp     .l
.w:     cmp     al, 'w'
        jne     .l
        mov     byte [opt_w], 1
        inc     si                      ; optional 1-2 digit address
        xor     ah, ah
        mov     al, [si]
        sub     al, '0'
        cmp     al, 9
        ja      .l
        mov     [watchad], al
        inc     si
        mov     al, [si]
        sub     al, '0'
        cmp     al, 9
        ja      .l
        mov     ah, al
        mov     al, [watchad]
        mov     cl, 10
        mul     cl
        add     al, ah
        mov     [watchad], al
        inc     si
        jmp     .l
.x:     ret

log_open:
        mov     dx, n_log
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .n
        mov     [fh], ax
.n:     ret

log_close:
        call    flush
        mov     bx, [fh]
        or      bx, bx
        jz      .n
        mov     ah, 3Eh
        int     21h
.n:     ret

puts:   pusha
        mov     ah, 09h
        int     21h
        cmp     word [fh], 0
        je      .r
        mov     si, dx
.l:     lodsb
        cmp     al, '$'
        je      .r
        call    fput
        jmp     .l
.r:     popa
        ret

putc:   pusha
        mov     dl, al
        mov     ah, 02h
        int     21h
        cmp     word [fh], 0
        je      .r
        mov     al, dl
        call    fput
.r:     popa
        ret

fput:   mov     bx, [bufn]
        mov     [fbuf+bx], al
        inc     bx
        mov     [bufn], bx
        cmp     bx, 512
        jb      .r
        call    flush
.r:     ret

flush:  pusha
        mov     cx, [bufn]
        jcxz    .r
        mov     bx, [fh]
        or      bx, bx
        jz      .r
        mov     dx, fbuf
        mov     ah, 40h
        int     21h
        mov     word [bufn], 0
.r:     popa
        ret

commit: call    flush
        pusha
        mov     bx, [fh]
        or      bx, bx
        jz      .r
        mov     ah, 68h
        int     21h
.r:     popa
        ret

crlf:   push    dx
        mov     dx, s_crlf
        call    puts
        pop     dx
        ret

phex8:  push    ax
        shr     al, 4
        call    .n
        pop     ax
        push    ax
        and     al, 0Fh
        call    .n
        pop     ax
        ret
.n:     add     al, '0'
        cmp     al, '9'
        jbe     .o
        add     al, 7
.o:     jmp     putc

pdec2:  push    ax
        cmp     ax, 10
        jae     .n
        mov     al, ' '
        call    putc
.n:     pop     ax
pdec:   pusha
        xor     cx, cx
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     ax
        add     al, '0'
        call    putc
        loop    .p
        popa
        ret

; =====================================================================
;  Data
; =====================================================================
RBUFLEN equ 70
regtab  dw R_DIR, R_ISR1, R_ISR2, R_SPSR, R_ADSR, R_CPTR, R_ADR0, R_ADR1
q_id    db 'ID?',10,0
q_idn   db '*IDN?',10,0
n_ieeeout db 'IEEEOUT',0
n_log   db 'A:\GPIBSCAN.TXT',0
s_title db 'GPIBSCAN 1.5 - direct uPD7210 GPIB scan (Lodestone)',13,10
        db '==================================================',13,10,'$'
s_drv488 db '** Driver488 (DRVR488) is loaded - it owns the GPIB chip.',13,10
        db '** Boot without it, or use GPIBSCAN /F to override.',13,10,'$'
s_regs  db 'Registers @02E1h DIR ISR1 ISR2 SPSR ADSR CPTR ADR0 ADR1:',13,10,'   $'
s_nochip db '** No uPD7210 answers at 02E1h (address register did not echo).',13,10,'$'
s_chip  db 'uPD7210 found at 02E1h, initialised as system controller (addr 21).',13,10,'$'
s_cic   db 'After IFC: ADSR=$'
s_cicyes db 'h  -> controller in charge',13,10,'$'
s_notcic db 'h  ** not controller in charge - is the cable connected?',13,10,'$'
s_scan  db 13,10,'Serial-polling addresses 0-30 (each twice)...',13,10,'$'
s_ghost db 'Control test (listen, no talker): $'
s_clean db 'clean - no data appears',13,10,'$'
s_ghosty db '** GHOST DATA: ISR1=$'
s_ghostd db 'h DIR=$'
s_ghosta db 'h ADSR=$'
s_once  db ': answered once only (unstable) - ignored',13,10,'$'
s_map   db 13,10,'Map   0123456789012345678901234567890',13,10,'      $'
s_recov db 13,10,'      #=device g=ghost ?=unstable *=Grid .=none   recoveries: $'
s_ghcnt db 'Ghost answers (slow 00h, ignored): $'
s_wat1  db 13,10,'WATCH: polling empty address $'
s_wat2  db ' - power instruments off one at a time. Any key exits.',13,10,'$'
s_wgh   db '  GHOST  status $'
s_wgh2  db 'h after $'
s_wgh3  db ' loops',13,10,'$'
s_wcl   db '  CLEAN  (no answer)',13,10,'$'
s_wreal db '  answer in 1-2 loops: a REAL device is set to this address!',13,10,'$'
s_stat2 db 'h/$'
s_lat   db 'h  loops $'
s_raw   db '   [first answer: ISR1=$'
s_rawads db 'h ADSR=$'
s_rawend db 'h]$'
s_ghostn db 'h',13,10,'   -> data arrives with no talker: expect false positives below',13,10,'$'
s_addr  db '  addr $'
s_stat  db ': present, status $'
s_nfound db 'Found $'
s_devs  db ' device(s).',13,10,'$'
s_idhdr db 13,10,'Identification (ID? then *IDN?):',13,10,'$'
s_colon db ': $'
s_noid  db '(no reply)$'
s_idq   db '(only ID? -> "$'
s_idq2  db '")$'
s_done  db 13,10,'Bus released (UNL/UNT, REN off). Log: A:\GPIBSCAN.TXT',13,10,'$'
s_crlf  db 13,10,'$'
opt_f   db 0
opt_id  db 0
opt_w   db 0
watchad db 3
nghost  db 0
wstate  db 0FFh
nfound  db 0
adsr    db 0
stat    db 0
stat2   db 0
shadow1 db 0
shadow2 db 0
rawisr1 db 0
rawadsr db 0
rawshown db 0
lat     dw 0
recov   dw 0
rawdir  db 0
amap    db '...............................$'
lat1    dw 0
fh      dw 0
bufn    dw 0
t_start dw 0
t_len   dw 0
found   times 32 db 0
rbuf    times RBUFLEN+2 db 0
rbuf2   times RBUFLEN+2 db 0
fbuf    times 512 db 0
