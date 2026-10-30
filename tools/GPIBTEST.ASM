; =====================================================================
;  GPIBTEST.COM - automated read-only GPIB test & timing       (Lodestone)
;  Build: nasm -f bin -o GPIBTEST.COM GPIBTEST.ASM
;
;  GPIBTEST       scan the bus, identify every instrument, then run a
;                 fixed, READ-ONLY test set on each one and time every
;                 transaction to 0.1 ms.  Nothing is typed, nothing is
;                 changed on any instrument (no settings, no DCL/SDC,
;                 no trigger).  Output: screen + A:\GPIBTEST.TXT
;  GPIBTEST /F    run even if Driver488 (DRVR488) is loaded
;
;  Profiles (chosen from the ID reply):
;   Tek TM5000/11000 ("ID TEK/..."):  ID? x10, SET? x1, serial poll x20
;   Tek meters DM5120/DM5010/DC5009:  + reading (addressed to talk) x10
;   IEEE 488.2 (answers *IDN?):       *IDN? x10, serial poll x20
;   no ID reply:                      serial poll x20
;  Each device is serial-polled before and after; status bit 5 (Tek
;  "error" / 488.2 ESB) set afterwards is reported as a warning.
;
;  Timing: PIT channel 0 is switched from mode 3 to mode 2 (same 18.2 Hz
;  tick, but the counter can be read linearly) and restored on exit.
;  Reads use RFD holdoff on END (AUXRA 96h, LF counts as END) so no byte
;  can be in flight when control is taken back with TCA.
;
;  Bus primitives are GPIBSCAN 1.5's, proven on the GRiDCase 1520.
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
        call    pit_init
        call    stamp
        mov     [tall], ax
        mov     [tall+2], dx

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

        ; ---- test every device found ------------------------------------
        cmp     byte [nfound], 0
        je      release
        mov     dx, s_thdr
        call    puts
        call    commit
        xor     si, si
.dev:   mov     bl, [found+si]
        push    si
        call    test_dev
        call    commit
        pop     si
        inc     si
        mov     ax, si
        cmp     al, [nfound]
        jb      .dev
        call    summary

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
quit:   call    pit_done
        call    d_rearm                 ; (X55: the driver's IMR2, IFC, REN)
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
        mov     di, rbuf
        mov     word [rxcnt], 0
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
.rd:    mov     word [rxcnt], 0
        call    cmd_begin
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
        mov     dx, R_AUXMR
        mov     al, 96h                 ; AUXRA: RFD holdoff on END (LF=END)
        out     dx, al
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
        inc     word [rxcnt]
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
        call    rd_end
        mov     al, UNT
        call    send_cmd
        mov     al, UNL
        call    send_cmd
        clc
        jmp     .x
.fail:  mov     byte [di], '$'
        call    rd_end
        mov     al, UNT
        call    send_cmd
        mov     al, UNL
        call    send_cmd
        stc
.x:     pop     si
        pop     bx
        ret

; read-only: address device BL to talk and read one message (no query)
query_read:
        push    bx
        push    si
        mov     di, rbuf
        jmp     query.rd

; end of a read: TCA is safe (RFD held on END, or nothing arrived),
; then release the holdoff and go back to the normal handshake
rd_end: call    cmd_begin
        push    ax
        push    dx
        mov     dx, R_AUXMR
        mov     al, 03h                 ; release RFD holdoff
        out     dx, al
        mov     al, 90h                 ; AUXRA: normal handshake
        out     dx, al
        pop     dx
        pop     ax
        ret

; =====================================================================
;  Automated test set
; =====================================================================
P_POLL  equ 0
P_488   equ 1
P_TEK   equ 2
P_METER equ 3
REPS    equ 10
SPREPS  equ 20

; test one device, address BL
test_dev:
        mov     dx, s_dhdr
        call    puts
        mov     al, bl
        xor     ah, ah
        call    pdec2
        mov     dx, s_2sp
        call    puts
        ; --- identify: ID? (Tek) then *IDN? (488.2) ---
        mov     byte [prof], P_POLL
        mov     si, q_id
        call    query
        jc      .i2
        cmp     word [rbuf], 'ID'
        jne     .i2
        mov     byte [prof], P_TEK
        mov     si, meters              ; DM5120 / DM5010 / DC5009 ?
.mt:    cmp     byte [si], 0
        je      .idok
        push    si
        mov     di, rbuf+7
        mov     cx, 6
        repe    cmpsb
        pop     si
        je      .ism
        add     si, 6
        jmp     .mt
.ism:   mov     byte [prof], P_METER
        jmp     .idok
.i2:    mov     si, q_idn
        call    query
        jc      .noid
        mov     byte [prof], P_488
.idok:  mov     dx, rbuf
        call    puts
        call    crlf
        jmp     .pre
.noid:  mov     dx, s_noid2
        call    puts
.pre:   call    spoll                   ; status before the tests
        mov     [st_pre], al
        jnc     .t
        mov     byte [st_pre], 0FFh
.t:     cmp     byte [prof], P_488
        jne     .t1
        mov     si, q_idn               ; 488.2: *IDN? x10
        mov     di, l_idn
        mov     cx, REPS
        mov     byte [t_show], 0
        call    run_test
        jmp     .tsp
.t1:    cmp     byte [prof], P_TEK
        jb      .tsp
        mov     si, q_id                ; Tek: ID? x10
        mov     di, l_id
        mov     cx, REPS
        mov     byte [t_show], 0
        call    run_test
        mov     si, q_set               ; Tek: SET? once (all settings)
        mov     di, l_set
        mov     cx, 1
        mov     byte [t_show], 1
        call    run_test
        cmp     byte [prof], P_METER
        jne     .tsp
        xor     si, si                  ; meter: talk-only reading x10
        mov     di, l_read
        mov     cx, REPS
        mov     byte [t_show], 1
        call    run_test
.tsp:   mov     si, 1                   ; everyone: serial poll x20
        mov     di, l_spoll
        mov     cx, SPREPS
        mov     byte [t_show], 0
        call    run_test
        ; --- status afterwards ---
        call    spoll
        jc      .x
        test    al, 20h
        jz      .x
        push    ax
        mov     dx, s_warn
        call    puts
        pop     ax
        call    phex8
        mov     dx, s_warn2
        call    puts
        mov     al, [st_pre]
        call    phex8
        mov     dx, s_warn3
        call    puts
        inc     word [nwarn]
.x:     ret

; run one test.  SI = query (ASCIIZ), 0 = read only, 1 = serial poll;
; CX = repetitions; DI = label; BL = address.  Stops at the first failure.
run_test:
        mov     [t_si], si
        mov     [t_reps], cx
        mov     [t_lbl], di
        xor     ax, ax
        mov     [t_ok], ax
        mov     [t_sum], ax
        mov     [t_sum+2], ax
        mov     [t_max], ax
        mov     [t_max+2], ax
        dec     ax
        mov     [t_min], ax
        mov     [t_min+2], ax
        mov     cx, [t_reps]
.lp:    push    cx
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     si, [t_si]
        cmp     si, 1
        je      .sp
        or      si, si
        jz      .rd
        call    query
        jmp     .done
.rd:    call    query_read
        jmp     .done
.sp:    call    spoll
        mov     [t_st], al
.done:  pushf
        call    stamp
        sub     ax, [t0]
        sbb     dx, [t0+2]
        popf
        pop     cx
        jc      .fail
        inc     word [t_ok]
        inc     word [ntrans]
        add     [t_sum], ax
        adc     [t_sum+2], dx
        add     [t_bus], ax
        adc     [t_bus+2], dx
        cmp     dx, [t_min+2]           ; min
        ja      .nmin
        jb      .smin
        cmp     ax, [t_min]
        jae     .nmin
.smin:  mov     [t_min], ax
        mov     [t_min+2], dx
.nmin:  cmp     dx, [t_max+2]           ; max
        jb      .nmax
        ja      .smax
        cmp     ax, [t_max]
        jbe     .nmax
.smax:  mov     [t_max], ax
        mov     [t_max+2], dx
.nmax:  loop    .lp
        jmp     .rep
.fail:  inc     word [nfail]
        ; ---- report ----
.rep:   mov     dx, s_ind
        call    puts
        mov     dx, [t_lbl]
        call    puts
        mov     ax, [t_ok]
        mov     cl, 2
        call    pdecw
        mov     al, '/'
        call    putc
        mov     ax, [t_reps]
        call    pdec
        cmp     word [t_ok], 0
        jne     .some
        mov     dx, s_failed
        call    puts
        ret
.some:  mov     dx, s_avg
        call    puts
        mov     ax, [t_sum]
        mov     dx, [t_sum+2]
        mov     cx, [t_ok]
        push    bx
        call    ldiv                    ; (remainder in BX - keep address)
        pop     bx
        call    pms
        mov     dx, s_min
        call    puts
        mov     ax, [t_min]
        mov     dx, [t_min+2]
        call    pms
        mov     dx, s_max
        call    puts
        mov     ax, [t_max]
        mov     dx, [t_max+2]
        call    pms
        mov     dx, s_ms
        call    puts
        cmp     word [t_si], 1
        je      .st
        mov     ax, [rxcnt]
        mov     cl, 5
        call    pdecw
        mov     dx, s_bytes
        call    puts
        jmp     .fl
.st:    mov     dx, s_st
        call    puts
        mov     al, [t_st]
        call    phex8
        mov     al, 'h'
        call    putc
.fl:    mov     ax, [t_ok]
        cmp     ax, [t_reps]
        je      .nl
        mov     dx, s_then
        call    puts
.nl:    call    crlf
        cmp     byte [t_show], 0
        je      .x
        mov     dx, s_show
        call    puts
        mov     dx, rbuf
        call    puts
        mov     dx, s_show2
        call    puts
.x:     ret

; --- PIT channel 0: mode 2 while we run, mode 3 again on exit ---------
pit_init:
        mov     byte [pitset], 1
        mov     al, 34h
        jmp     short pitw
pit_done:
        cmp     byte [pitset], 0
        je      pitx
        mov     byte [pitset], 0
        mov     al, 36h
pitw:   cli
        out     43h, al
        xor     al, al
        out     40h, al
        jmp     short $+2
        out     40h, al
        sti
pitx:   ret

; DX:AX = time in PIT counts (1.193 MHz): BIOS tick * 65536 + counter.
; Retries if a tick happens while reading.
stamp:  push    bx
        push    cx
.r:     call    tick
        mov     bx, ax
        cli
        xor     al, al
        out     43h, al                 ; latch counter 0
        jmp     short $+2
        in      al, 40h
        mov     cl, al
        jmp     short $+2
        in      al, 40h
        mov     ch, al
        sti
        nop
        call    tick
        cmp     ax, bx
        jne     .r
        mov     ax, cx
        neg     ax                      ; counts elapsed in this tick
        mov     dx, bx
        pop     cx
        pop     bx
        ret

; DX:AX = DX:AX / CX  (32/16 long division, remainder in BX)
ldiv:   push    si
        mov     si, ax
        mov     ax, dx
        xor     dx, dx
        div     cx
        push    ax
        mov     ax, si
        div     cx
        mov     bx, dx
        pop     dx
        pop     si
        ret

; print DX:AX PIT counts as milliseconds "nnnn.n" (width 7)
pms:    pusha
        mov     cx, 1193
        call    ldiv                    ; DX:AX = ms, BX = remainder
        or      dx, dx
        jz      .ok
        mov     ax, 0FFFFh
.ok:    push    ax
        mov     ax, bx
        mov     bx, 10
        mul     bx
        div     cx                      ; tenths
        mov     bl, al
        pop     ax
        mov     cl, 5
        call    pdecw
        mov     al, '.'
        call    putc
        mov     al, bl
        add     al, '0'
        call    putc
        popa
        ret

; print AX right-aligned in CL columns
pdecw:  pusha
        mov     bx, ax
        mov     ch, 1
        mov     si, 10
.c:     cmp     ax, 10
        jb      .p
        xor     dx, dx
        div     si
        inc     ch
        jmp     .c
.p:     cmp     ch, cl
        jae     .n
        mov     al, ' '
        call    putc
        inc     ch
        jmp     .p
.n:     mov     ax, bx
        call    pdec
        popa
        ret

summary:
        call    stamp
        sub     ax, [tall]
        sbb     dx, [tall+2]
        mov     [tall], ax
        mov     [tall+2], dx
        mov     dx, s_sum1
        call    puts
        mov     al, [nfound]
        xor     ah, ah
        call    pdec
        mov     dx, s_sum2
        call    puts
        mov     ax, [ntrans]
        call    pdec
        mov     dx, s_sum3
        call    puts
        mov     ax, [nfail]
        call    pdec
        mov     dx, s_sum4
        call    puts
        mov     ax, [t_bus]
        mov     dx, [t_bus+2]
        call    pms
        mov     dx, s_sum5
        call    puts
        mov     ax, [tall]
        mov     dx, [tall+2]
        call    pms
        mov     dx, s_sum6
        call    puts
        mov     ax, [recov]
        call    pdec
        mov     dx, s_sum7
        call    puts
        mov     ax, [nwarn]
        call    pdec
        call    crlf
        ret

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
n_log   db 'A:\GPIBTEST.TXT',0
s_title db 'GPIBTEST 1.0 - automated read-only GPIB test (Lodestone)',13,10
        db '======================================================',13,10,'$'
s_drv488 db '** Driver488 (DRVR488) is loaded - it owns the GPIB chip.',13,10
        db '** Boot without it, or use GPIBTEST /F to override.',13,10,'$'
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
s_done  db 13,10,'Bus released (UNL/UNT, REN off). Log: A:\GPIBTEST.TXT',13,10,'$'
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
q_set   db 'SET?',10,0
meters  db 'DM5120DM5010DC5009',0
l_id    db 'ID?       $'
l_idn   db '*IDN?     $'
l_set   db 'SET?      $'
l_read  db 'reading   $'
l_spoll db 'ser.poll  $'
s_thdr  db 13,10,'Read-only test set (times per transaction, ms):',13,10,'$'
s_dhdr  db 13,10,'addr $'
s_2sp   db '  $'
s_noid2 db '(no ID reply - serial poll only)',13,10,'$'
s_ind   db '    $'
s_failed db '  FAILED (no reply)',13,10,'$'
s_avg   db '  avg$'
s_min   db '  min$'
s_max   db '  max$'
s_ms    db ' ms$'
s_bytes db ' B$'
s_st    db '  status $'
s_then  db '  then failed$'
s_show  db '        "$'
s_show2 db '"',13,10,'$'
s_warn  db '    ** status after tests $'
s_warn2 db 'h (before $'
s_warn3 db 'h): error bit set - check the instrument display',13,10,'$'
s_sum1  db 13,10,'Summary: $'
s_sum2  db ' devices, $'
s_sum3  db ' transactions OK, $'
s_sum4  db ' failed',13,10,'Bus time $'
s_sum5  db ' ms, total run $'
s_sum6  db ' ms, chip recoveries $'
s_sum7  db ', warnings $'
prof    db 0
st_pre  db 0
t_show  db 0
t_st    db 0
pitset  db 0
t_si    dw 0
t_reps  dw 0
t_lbl   dw 0
t_ok    dw 0
rxcnt   dw 0
ntrans  dw 0
nfail   dw 0
nwarn   dw 0
t0      dd 0
t_sum   dd 0
t_min   dd 0
t_max   dd 0
t_bus   dd 0
tall    dd 0

rbuf2   times RBUFLEN+2 db 0
fbuf    times 512 db 0
