; =====================================================================
;  GRIDGPIB.COM - resident GPIB driver for the GRiDCase 1520     (Grid-OS)
;  Build: nasm -f bin -o GRIDGPIB.COM GRIDGPIB.ASM
;
;  GRIDGPIB          install (first free vector 60h-66h), IFC, REN on
;  GRIDGPIB /I:nn    install on INT nn (hex, 60-66)
;  GRIDGPIB /U       unload (bus released, REN off, memory freed)
;  GRIDGPIB /F       install even if Driver488 is loaded (not advised)
;
;  Direct uPD7210 access (base 02E1h, reg n at +n*400h), Grid = system
;  controller at address 21.  Polled, no fixed delays: every call returns
;  as soon as the bus transaction is done, or on timeout.  Built from the
;  GPIBSCAN/GPIBTEST primitives proven on the real bus.
;
;  ---- API: INT nn, AH = function.  CF=1 on error, AX = error code ----
;  BX SI DI BP DS ES are preserved; CX/DX hold results where listed,
;  otherwise their contents are undefined.
;  AH=00 presence   out AX='GG'(4747h) CX=version(0110h) DH=int DL=own addr
;  AH=01 init bus   IFC, REN on                                out AX
;  AH=02 write      BL=addr DS:SI=data CX=len AL bit0=EOI on last byte
;                   out AX, CX=bytes sent
;  AH=03 read       BL=addr ES:DI=buf CX=max AL bit0=stop at LF
;                   out AX, CX=count, DL=end (1 EOI, 2 LF, 4 buffer full -
;                   call again to get the rest, 8 timeout after data)
;  AH=04 query      write DS:SI/CX (EOI) then read ES:DI, DX=max,
;                   AL bit0=stop at LF          out AX, CX=count, DL=end
;  AH=05 ser. poll  BL=addr                  out AL=status byte, AH=error
;  AH=06 clear      BL=addr (SDC) or BL=FFh (DCL, everyone)     out AX
;  AH=07 trigger    BL=addr (GET)                               out AX
;  AH=08 remote     BL=addr, or FFh = just assert REN            out AX
;  AH=09 local      BL=addr (GTL), or FFh = drop REN (all local) out AX
;                   (the next write re-asserts REN automatically)
;  AH=0A timeout    BX=ms per byte (0 = default 2000)  out AX=old ms
;  AH=0B SRQ        out AX=1 if SRQ was asserted since the last call
;  AH=0C stats      out AX=chip recoveries, CX=timeouts, DX=resident bytes
;  AH=0D unload     (internal) out CX=PSP, DX:AX=previous vector
;  Errors: 1 timeout, 2 no listener, 3 not controller/no chip,
;          4 bad function, 5 no data (read timeout), 6 busy (re-entry)
; =====================================================================
cpu 286
org 100h

BASE    equ 02E1h
R_DIR   equ BASE+0000h
R_ISR1  equ BASE+0400h
R_ISR2  equ BASE+0800h
R_SPSR  equ BASE+0C00h
R_ADSR  equ BASE+1000h
R_AUXMR equ BASE+1400h
R_ADR0  equ BASE+1800h
R_ADR1  equ BASE+1C00h
R_CDOR  equ R_DIR
R_IMR1  equ R_ISR1
R_IMR2  equ R_ISR2
R_SPMR  equ R_SPSR
R_ADMR  equ R_ADSR
R_ADR   equ R_ADR0
ISR1_DI  equ 01h
ISR1_DO  equ 02h
ISR1_ERR equ 04h
ISR1_END equ 10h
ISR2_CO  equ 08h
ISR2_SRQ equ 40h
ADSR_CIC equ 80h
AUX_PON  equ 00h
AUX_CR   equ 02h
AUX_FH   equ 03h                ; finish handshake (release RFD holdoff)
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
GTL     equ 01h
SDC     equ 04h
GET     equ 08h
DCL     equ 14h
T_CMD   equ 9                   ; ticks: command byte
T_SPOLL equ 3                   ; ticks: serial poll answer
T_DEF   equ 36                  ; ticks: data byte (2 s)
E_TMO   equ 1
E_NOL   equ 2
E_CIC   equ 3
E_FUNC  equ 4
E_NODATA equ 5
E_BUSY  equ 6

start:  jmp     install

; =====================================================================
;  RESIDENT PART
; =====================================================================
entry:  jmp     short handler
sig     db 'GRIDGPIB'                   ; entry+2: signature for clients
handler:
        cmp     byte [cs:busy], 0
        je      .go
        mov     ax, E_BUSY
        stc
        retf    2
.go:    mov     byte [cs:busy], 1
        sti
        cld
        push    bx
        push    si
        push    di
        push    bp
        push    ds
        push    es
        mov     [cs:c_ds], ds
        push    cs
        pop     ds
        mov     [c_es], es
        mov     [c_si], si
        mov     [c_di], di
        mov     [c_cx], cx
        mov     [c_dx], dx
        mov     [c_bx], bx
        mov     [c_al], al
        mov     byte [err], 0
        mov     bl, ah
        cmp     bl, NFUNC
        jb      .ok
        mov     byte [err], E_FUNC
        mov     ax, E_FUNC
        jmp     .out
.ok:    xor     bh, bh
        shl     bx, 1
        mov     bx, [functab+bx]
        push    bx
        mov     bx, [c_bx]              ; BL = address for everyone
        mov     cx, [c_cx]
        mov     dx, [c_dx]
        ret                             ; -> function, which jumps to .out
.out:   pop     es
        pop     ds
        pop     bp
        pop     di
        pop     si
        pop     bx
        cmp     byte [cs:err], 1        ; CF = (err == 0) ...
        cmc                             ; ... inverted: CF = error
        mov     byte [cs:busy], 0       ; (MOV keeps the flags)
        retf    2
done    equ     handler.out

functab dw f_present, f_init, f_write, f_read, f_query, f_spoll
        dw f_clear, f_trigger, f_remote, f_local, f_timeout, f_srq
        dw f_stats, f_unload
NFUNC   equ ($-functab)/2

; ---- function bodies: return AX (and CX/DX where documented) -------
f_present:
        mov     ax, 4747h
        mov     cx, 0110h
        mov     dh, [intno]
        mov     dl, MYADDR
        jmp     done

f_init: call    bus_init
        jmp     fin_ax

f_write:
        mov     es, [c_ds]
        mov     si, [c_si]
        mov     al, [c_al]
        mov     [eoiflag], al
        call    do_write
        jmp     fin_ax_cx

f_read: mov     es, [c_es]
        mov     di, [c_di]
        mov     al, [c_al]
        mov     [lfstop], al
        call    do_read
        jmp     fin_read

f_query:
        mov     es, [c_ds]
        mov     si, [c_si]
        mov     byte [eoiflag], 1
        call    do_write
        or      ax, ax
        jnz     fin_ax_cx
        mov     es, [c_es]
        mov     di, [c_di]
        mov     cx, [c_dx]
        mov     al, [c_al]
        mov     [lfstop], al
        call    do_read
        jmp     fin_read

f_spoll:
        call    spoll
        jnc     .ok
        mov     ax, E_TMO << 8         ; AL = 0, AH = error
        mov     [err], ah
        jmp     done
.ok:    xor     ah, ah
        jmp     done

f_clear:
        mov     al, DCL
        cmp     bl, 0FFh
        je      uni
        mov     al, SDC
        jmp     short addressed
f_trigger:
        mov     al, GET
        jmp     short addressed
f_remote:
        call    ren_on
        cmp     bl, 0FFh
        je      ok0
        mov     al, 0                   ; just listen-address it
        jmp     short addressed
f_local:
        cmp     bl, 0FFh
        jne     local_one
        mov     dx, R_AUXMR
        mov     al, AUX_CREN
        out     dx, al
        mov     byte [renon], 0
ok0:    xor     ax, ax
        jmp     fin_ax
local_one:
        mov     al, GTL
        ; fall through
; UNL, LAD addr, then command AL (0 = none), UNL
addressed:
        push    ax
        call    ensure_ctrl
        pop     ax
        jc      cmdfail
        push    ax
        mov     al, UNL
        call    send_cmd
        jc      .f
        mov     al, bl
        or      al, 20h
        call    send_cmd
        jc      .f
        pop     ax
        or      al, al
        jz      .n
        push    ax
        call    send_cmd
        jc      .f
        pop     ax
.n:     mov     al, UNL
        call    send_cmd
        jc      cmdfail
        xor     ax, ax
        jmp     fin_ax
.f:     pop     ax
        jmp     cmdfail
; universal command AL (DCL)
uni:    push    ax
        call    ensure_ctrl
        pop     ax
        jc      cmdfail
        call    send_cmd
        jc      cmdfail
        xor     ax, ax
        jmp     fin_ax

f_timeout:
        mov     ax, [tdata]             ; old value in ms
        mov     dx, 55
        mul     dx
        push    ax
        mov     ax, [c_bx]
        or      ax, ax
        jnz     .c
        mov     ax, T_DEF*55
.c:     add     ax, 54
        jnc     .d
        mov     ax, 0FFFFh
.d:     xor     dx, dx
        mov     cx, 55
        div     cx
        cmp     ax, 2
        jae     .s
        mov     ax, 2                   ; at least 2 ticks (55..110 ms)
.s:     mov     [tdata], ax
        pop     ax
        jmp     done

f_srq:  mov     dx, R_ISR2
        in      al, dx
        or      [shadow2], al
        xor     ax, ax
        test    byte [shadow2], ISR2_SRQ
        jz      .n
        inc     ax
        and     byte [shadow2], ~ISR2_SRQ
.n:     jmp     done

f_stats:
        mov     ax, [recov]
        mov     cx, [ntmo]
        mov     dx, res_end - 100h + 100h ; resident bytes incl. PSP
        jmp     done

f_unload:
        mov     cx, cs                  ; .COM: CS = our PSP segment
        mov     ax, [oldvec]
        mov     dx, [oldvec+2]
        jmp     done

cmdfail:
        call    recover
        mov     ax, E_TMO
fin_ax: mov     [err], al
        jmp     done
fin_ax_cx:
        mov     [err], al
        jmp     done
fin_read:
        mov     [err], al
        jmp     done

; =====================================================================
;  Bus operations
; =====================================================================
bus_init:
        mov     byte [shadow1], 0
        mov     byte [shadow2], 0
        call    chip_init
        call    ifc_ren
        mov     dx, R_ADSR
        in      al, dx
        xor     ah, ah
        test    al, ADSR_CIC
        jnz     .ok
        mov     al, E_CIC
        ret
.ok:    xor     al, al
        ret

ifc_ren:
        mov     dx, R_AUXMR
        mov     al, AUX_SIFC
        out     dx, al
        call    wait_tick
        mov     al, AUX_CIFC
        out     dx, al
ren_on: push    ax
        push    dx
        mov     dx, R_AUXMR
        mov     al, AUX_SREN
        out     dx, al
        mov     byte [renon], 1
        pop     dx
        pop     ax
        ret

; write CX bytes from ES:SI to device BL.  AX = error, CX = bytes sent
do_write:
        mov     [count], cx
        mov     word [done_n], 0
        cmp     byte [renon], 0         ; auto-remote after LOCAL ALL
        jne     .r
        call    ren_on
.r:     call    ensure_ctrl
        jc      .cf
        mov     al, UNL
        call    send_cmd
        jc      .cf
        mov     al, 40h+MYADDR          ; MTA
        call    send_cmd
        jc      .cf
        mov     al, bl
        or      al, 20h                 ; LAD
        call    send_cmd
        jc      .cf
        call    wait_co
        jc      .cf
        call    do_gts
.wb:    mov     cx, [count]
        cmp     cx, [done_n]
        je      .sent
        mov     cx, [tdata]
        call    tmo_start
.wdo:   mov     ah, ISR1_DO | ISR1_ERR
        call    isr1_test
        jz      .nodo
        test    al, ISR1_ERR
        jnz     .nol
        jmp     short .put
.nodo:  call    tmo_check
        jnc     .wdo
        jmp     .tmo
.put:   mov     ax, [done_n]
        inc     ax
        cmp     ax, [count]
        jne     .noeoi
        test    byte [eoiflag], 1
        jz      .noeoi
        mov     dx, R_AUXMR
        mov     al, AUX_SEOI
        out     dx, al
.noeoi: mov     al, [es:si]
        inc     si
        mov     dx, R_CDOR
        out     dx, al
        inc     word [done_n]
        jmp     .wb
.sent:  mov     cx, [tdata]             ; last byte accepted?
        call    tmo_start
.wl:    mov     ah, ISR1_DO | ISR1_ERR
        call    isr1_test
        jnz     .fin
        call    tmo_check
        jnc     .wl
        jmp     .tmo
.fin:   call    unaddr
        xor     ax, ax
        jmp     .x
.nol:   call    unaddr
        mov     ax, E_NOL
        jmp     .x
.tmo:   inc     word [ntmo]
        call    unaddr
        mov     ax, E_TMO
        jmp     .x
.cf:    call    recover
        mov     ax, E_TMO
.x:     mov     cx, [done_n]
        ret

; read from device BL into ES:DI, max CX.  AX = error, CX = count, DL = end
; 1.1: normal handshake for the bulk of a message (the talker sends the
; next byte while we store this one); RFD holdoff on END (+REOS when
; stopping at LF), and holdoff-on-all is switched on just before the byte
; that fills the buffer.  So when we stop - END, LF, full buffer - nothing
; is in flight and TCA is safe; the talker keeps any rest for the next call.
do_read:
        mov     [count], cx
        mov     word [done_n], 0
        mov     byte [endr], 0
        call    ensure_ctrl
        jc      .cf
        mov     al, UNL
        call    send_cmd
        jc      .cf
        mov     al, 20h+MYADDR          ; MLA
        call    send_cmd
        jc      .cf
        mov     al, bl
        or      al, 40h                 ; TAD
        call    send_cmd
        jc      .cf
        call    wait_co
        jc      .cf
        call    clear_in
        mov     cx, [count]
        or      cx, cx
        jnz     .nz
        jmp     .full
.nz:    mov     al, 92h                 ; AUXRA: RFD holdoff on END
        test    byte [lfstop], 1
        jz      .a
        or      al, 04h                 ; ... and LF (EOS) counts as END
.a:     cmp     cx, 1
        ja      .a2
        or      al, 01h                 ; 1-byte buffer: hold every byte
.a2:    mov     [auxra], al
        mov     dx, R_AUXMR
        out     dx, al
        call    do_gts
.rb:    mov     cx, [tdata]
        call    tmo_start
.wdi:   mov     ah, ISR1_DI
        call    isr1_test
        jnz     .byte
        call    tmo_check
        jnc     .wdi
        inc     word [ntmo]
        mov     byte [endr], 8
        cmp     word [done_n], 0
        jne     .stop
        call    rd_stop
        mov     ax, E_NODATA
        jmp     .x
.byte:  mov     ah, al
        and     byte [shadow1], ~ISR1_END
        ; The byte that will fill the last buffer slot must be held, so
        ; holdoff-on-all is switched on before reading the one before it
        ; (the chip decides on holdoff when it accepts the next byte).
        mov     cx, [done_n]
        add     cx, 2
        cmp     cx, [count]
        jne     .rd
        test    byte [auxra], 01h
        jnz     .rd
        or      byte [auxra], 01h
        mov     al, [auxra]
        mov     dx, R_AUXMR
        out     dx, al
.rd:    mov     dx, R_DIR
        in      al, dx                  ; (completes the handshake unless held)
        stosb
        inc     word [done_n]
        cmp     al, 0Ah
        jne     .ne
        test    byte [lfstop], 1
        jz      .ne
        mov     byte [endr], 2
        jmp     .stop
.ne:    test    ah, ISR1_END
        jz      .ne2
        mov     byte [endr], 1
        jmp     .stop
.ne2:   mov     cx, [done_n]
        cmp     cx, [count]
        jb      .rb                     ; not held: next byte already coming
.full:  mov     byte [endr], 4
.stop:  call    rd_stop
        xor     ax, ax
        jmp     .x
.cf:    call    recover
        mov     ax, E_TMO
.x:     mov     cx, [done_n]
        mov     dl, [endr]
        ret

; end of a read: take control (safe - RFD held), release, normal mode
rd_stop:
        call    cmd_begin
        mov     dx, R_AUXMR
        mov     al, AUX_FH
        out     dx, al
        mov     al, 90h
        out     dx, al
unaddr: call    cmd_begin
        mov     al, UNT
        call    send_cmd
        jc      .r
        mov     al, UNL
        call    send_cmd
        jnc     .x
.r:     call    recover
.x:     ret

; serial poll address BL -> AL = status, CF=1 if nobody answered
spoll:  call    ensure_ctrl
        jc      .fail
        mov     dx, R_AUXMR
        mov     al, 91h                 ; RFD holdoff on all data
        out     dx, al
        mov     al, UNL
        call    send_cmd
        jc      .fail
        mov     al, 20h+MYADDR
        call    send_cmd
        jc      .fail
        mov     al, bl
        or      al, 40h
        call    send_cmd
        jc      .fail
        mov     al, SPE
        call    send_cmd
        jc      .fail
        call    wait_co
        jc      .fail
        call    clear_in
        call    do_gts
        mov     cx, T_SPOLL
        call    tmo_start
.w:     mov     ah, ISR1_DI
        call    isr1_test
        jnz     .got
        call    tmo_check
        jnc     .w
        inc     word [ntmo]
        call    spoll_end
        stc
        ret
.got:   mov     dx, R_DIR
        in      al, dx                  ; status byte (handshake held)
        push    ax
        call    spoll_end
        pop     ax
        clc
        ret
.fail:  call    recover
        stc
        ret

spoll_end:
        call    cmd_begin
        mov     dx, R_AUXMR
        mov     al, AUX_FH
        out     dx, al
        mov     al, 90h
        out     dx, al
        call    wait_co
        jnc     .ok
        call    recover
.ok:    mov     al, SPD
        call    send_cmd
        mov     al, UNT
        call    send_cmd
        ret

; =====================================================================
;  uPD7210 primitives (from GPIBSCAN 1.5 / GPIBTEST 1.0)
; =====================================================================
chip_init:
        mov     dx, R_AUXMR
        mov     al, AUX_CR
        out     dx, al
        mov     al, 28h                 ; ICR: 8 MHz
        out     dx, al
        xor     al, al
        mov     dx, R_IMR1
        out     dx, al
        mov     dx, R_IMR2
        out     dx, al
        mov     dx, R_SPMR
        out     dx, al
        mov     dx, R_ADMR
        mov     al, 31h
        out     dx, al
        mov     dx, R_ADR
        mov     al, MYADDR
        out     dx, al
        mov     al, 0E0h
        out     dx, al
        mov     dx, R_ADR1
        mov     al, 0Ah                 ; EOS = LF
        out     dx, al
        mov     dx, R_AUXMR
        mov     al, 80h
        out     dx, al
        mov     al, 0A0h
        out     dx, al
        mov     al, AUX_PON
        out     dx, al
        ret

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

tmo_start:
        push    ax
        call    tick
        mov     [t_start], ax
        mov     [t_len], cx
        pop     ax
        ret

tmo_check:
        push    ax
        call    tick
        sub     ax, [t_start]
        cmp     ax, [t_len]
        pop     ax
        cmc
        ret

cmd_begin:
        push    ax
        push    dx
        mov     dx, R_ADSR
        in      al, dx
        test    al, 40h
        jz      .x
        and     byte [shadow2], ~ISR2_CO
        mov     dx, R_AUXMR
        mov     al, AUX_TCA
        out     dx, al
.x:     pop     dx
        pop     ax
        ret

do_gts: push    ax
        push    dx
        and     byte [shadow2], ~ISR2_CO
        mov     dx, R_AUXMR
        mov     al, AUX_GTS
        out     dx, al
        pop     dx
        pop     ax
        ret

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

ensure_ctrl:
        push    ax
        push    dx
        call    cmd_begin
        call    wait_co
        jnc     .ok
        call    recover
        call    wait_co
.ok:    pop     dx
        pop     ax
        ret

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

recover:
        push    ax
        push    dx
        inc     word [recov]
        mov     byte [shadow2], 0
        mov     byte [shadow1], 0
        call    chip_init
        call    ifc_ren
        mov     byte [shadow1], 0
        call    wait_co
        pop     dx
        pop     ax
        ret

isr1_test:
        push    dx
        mov     dx, R_ISR1
        cli
        in      al, dx
        test    al, 03h
        jz      .one
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

; ---- resident data ----------------------------------------------------
busy    db 0
err     db 0
shadow1 db 0
shadow2 db 0
eoiflag db 1
lfstop  db 1
endr    db 0
auxra   db 0
renon   db 0
intno   db 0
c_al    db 0
recov   dw 0
ntmo    dw 0
tdata   dw T_DEF
t_start dw 0
t_len   dw 0
count   dw 0
done_n  dw 0
c_ds    dw 0
c_es    dw 0
c_si    dw 0
c_di    dw 0
c_cx    dw 0
c_dx    dw 0
c_bx    dw 0
oldvec  dd 0
res_end:

; =====================================================================
;  TRANSIENT PART (installer) - discarded after install
; =====================================================================
install:
        cld
        mov     dx, s_title
        call    tputs
        call    parse
        ; ---- already installed? ----
        call    findres                 ; AL = int no, ES = seg, or CF
        jc      .notin
        cmp     byte [o_u], 0
        jne     unload
        mov     dx, s_already
        call    tputs
        mov     ax, 4C01h
        int     21h
.notin: cmp     byte [o_u], 0
        je      .inst
        mov     dx, s_notres
        call    tputs
        mov     ax, 4C01h
        int     21h
.inst:  ; ---- Driver488 owns the chip? ----
        mov     dx, n_ieee
        mov     ax, 3D00h
        int     21h
        jc      .nod
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
        mov     dx, s_d488
        call    tputs
        cmp     byte [o_f], 0
        jne     .nod
        mov     ax, 4C02h
        int     21h
.nod:   ; ---- chip present? ----
        call    chip_init
        mov     dx, R_ADR0
        in      al, dx
        and     al, 1Fh
        cmp     al, MYADDR
        je      .chip
        mov     dx, s_nochip
        call    tputs
        mov     ax, 4C03h
        int     21h
.chip:  call    bus_init
        or      al, al
        jz      .cic
        mov     dx, s_nocic
        call    tputs
        mov     ax, 4C03h
        int     21h
.cic:   ; ---- choose the vector ----
        mov     al, [o_int]
        or      al, al
        jnz     .have
        mov     al, 60h
.try:   call    vfree
        jnc     .have
        inc     al
        cmp     al, 67h                 ; 67h is EMS - never
        jb      .try
        mov     dx, s_novec
        call    tputs
        mov     ax, 4C04h
        int     21h
.have:  mov     [intno], al
        mov     ah, 35h
        int     21h
        mov     [oldvec], bx
        mov     [oldvec+2], es
        mov     dx, entry
        mov     ah, 25h
        mov     al, [intno]
        int     21h
        mov     dx, s_ok1
        call    tputs
        mov     al, [intno]
        call    thex8
        mov     dx, s_ok2
        call    tputs
        mov     ax, res_end - 100h + 100h
        call    tdec
        mov     dx, s_ok3
        call    tputs
        ; ---- free the environment, stay resident ----
        mov     es, [2Ch]
        mov     ah, 49h
        int     21h
        mov     dx, res_end + 15
        shr     dx, 4
        mov     ax, 3100h
        int     21h

; vector AL free?  (null, or points at an IRET)  CF=1 if in use
vfree:  push    ax
        push    bx
        push    es
        mov     ah, 35h
        int     21h
        mov     ax, es
        or      ax, bx
        jz      .free
        cmp     byte [es:bx], 0CFh
        je      .free
        stc
        jmp     .x
.free:  clc
.x:     pop     es
        pop     bx
        pop     ax
        ret

; find a resident copy: CF=0, AL = vector, ES:BX = entry
findres:
        mov     al, 60h
.l:     push    ax
        mov     ah, 35h
        int     21h
        mov     di, bx
        add     di, 2
        mov     si, sig
        mov     cx, 8
        repe    cmpsb
        pop     ax
        je      .f
        inc     al
        cmp     al, 67h
        jb      .l
        stc
        ret
.f:     clc
        ret

unload: mov     [intno], al
        mov     ah, [intno]
        mov     byte [ucall+1], ah      ; self-modify: INT nn
        mov     bl, 0FFh                ; everyone back to local
        mov     ah, 09h
        call    ucall
        mov     ah, 0Dh
        call    ucall                   ; CX=PSP, DX:AX=old vector
        push    cx
        push    ds
        mov     ds, dx
        mov     dx, ax
        mov     al, [cs:intno]
        mov     ah, 25h
        int     21h
        pop     ds
        pop     es
        mov     ah, 49h
        int     21h
        jc      .bad
        mov     dx, s_unl
        call    tputs
        mov     ax, 4C00h
        int     21h
.bad:   mov     dx, s_unlf
        call    tputs
        mov     ax, 4C05h
        int     21h
ucall:  int     60h
        ret

parse:  mov     si, 81h
.l:     lodsb
        cmp     al, 13
        je      .x
        cmp     al, '/'
        jne     .l
        lodsb
        or      al, 20h
        cmp     al, 'u'
        jne     .f
        mov     byte [o_u], 1
        jmp     .l
.f:     cmp     al, 'f'
        jne     .i
        mov     byte [o_f], 1
        jmp     .l
.i:     cmp     al, 'i'
        jne     .l
        lodsb                           ; ':'
        call    hexd
        jc      .l
        shl     al, 4
        mov     ah, al
        call    hexd
        jc      .l
        or      al, ah
        cmp     al, 60h
        jb      .l
        cmp     al, 66h
        ja      .l
        mov     [o_int], al
        jmp     .l
.x:     ret
hexd:   lodsb
        or      al, 20h
        sub     al, '0'
        cmp     al, 9
        jbe     .ok
        sub     al, 'a'-'0'-10
        cmp     al, 10
        jb      .bad
        cmp     al, 15
        ja      .bad
.ok:    clc
        ret
.bad:   stc
        ret

tputs:  mov     ah, 09h
        int     21h
        ret
thex8:  push    ax
        shr     al, 4
        call    .n
        pop     ax
        and     al, 0Fh
.n:     add     al, '0'
        cmp     al, '9'
        jbe     .o
        add     al, 7
.o:     mov     dl, al
        mov     ah, 02h
        int     21h
        ret
tdec:   xor     cx, cx
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     dx
        add     dl, '0'
        mov     ah, 02h
        int     21h
        loop    .p
        ret

o_u     db 0
o_f     db 0
o_int   db 0
n_ieee  db 'IEEEOUT',0
s_title db 'GRIDGPIB 1.1 - resident GPIB driver for the GRiDCase 1520 (Grid-OS)',13,10,'$'
s_already db 'Already installed.  GRIDGPIB /U unloads it.',13,10,'$'
s_notres db 'Not installed - nothing to unload.',13,10,'$'
s_d488  db '** Driver488 (DRVR488) is loaded and owns the GPIB chip.',13,10
        db '** Reboot without it (or GRIDGPIB /F to force).',13,10,'$'
s_nochip db '** No uPD7210 at 02E1h.',13,10,'$'
s_nocic db '** Not controller in charge after IFC - is the GPIB cable OK?',13,10,'$'
s_novec db '** No free interrupt 60h-66h (use /I:nn).',13,10,'$'
s_ok1   db 'Installed on INT $'
s_ok2   db 'h, bus initialised (IFC, REN), $'
s_ok3   db ' bytes resident.',13,10,'$'
s_unl   db 'Unloaded: bus released, REN off, memory freed.',13,10,'$'
s_unlf  db '** Vector restored but memory could not be freed.',13,10,'$'
