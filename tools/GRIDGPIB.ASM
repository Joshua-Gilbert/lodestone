; =====================================================================
;  GRIDGPIB.COM - resident GPIB driver for the GRiDCase 1520     (Lodestone)
;  Build: nasm -f bin -o GRIDGPIB.COM GRIDGPIB.ASM
;
;  GRIDGPIB          install (first free vector 60h-66h), IFC, REN on
;  GRIDGPIB /I:nn    install on INT nn (hex, 60-66)
;  GRIDGPIB /U       unload (bus released, REN off, memory freed)
;  GRIDGPIB /F       install even if Driver488 is loaded (not advised)
;  GRIDGPIB /N       no SRQ interrupt (IRQ 5): SRQ is only polled, as 1.1
;
;  Direct uPD7210 access (base 02E1h, reg n at +n*400h), Grid = system
;  controller at address 21.  Polled, no fixed delays: every call returns
;  as soon as the bus transaction is done, or on timeout.  Built from the
;  GPIBSCAN/GPIBTEST primitives proven on the real bus.  1.2: SRQ also on
;  IRQ 5 (the GPIB cartridge's E1 jumper; GPIBIRQ 1.0 on the 1520): clients
;  sleep until it.  1.23: the resident part is Lodestone's built-in driver,
;  os/src/KGPIB.INC, included (GPIB_STANDALONE: its islands are what only
;  this driver does): its fast loops (GPIBLOOP's), the frame check (02h
;  AL=3, 03h AL=2), and its merges.  So it answers 0123h as the kernel's
;  does: CLAUDE.COM then leaves the frame check to the driver.
;
;  ---- API: INT nn, AH = function.  CF=1 on error, AX = error code ----
;  BX SI DI BP DS ES are preserved; CX/DX hold results where listed,
;  otherwise their contents are undefined.
;  AH=00 presence   out AX='GG'(4747h) CX=version(0123h) DH=int DL=own addr
;  AH=01 init bus   IFC, REN on                                out AX
;  AH=02 write      BL=addr DS:SI=data CX=len AL bit0=EOI on last byte;
;                   AL=3: then the frame check (Fletcher-16 mod 256, A and
;                   B, A=1 B=0 to start) as two more bytes, EOI with B
;                   out AX, CX=bytes sent
;  AH=03 read       BL=addr ES:DI=buf CX=max AL bit0=stop at LF
;                   out AX, CX=count, DL=end (1 EOI, 2 LF, 4 buffer full -
;                   call again to get the rest, 8 timeout after data);
;                   AL=2: also BX = the frame check of every byte read
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
;  AH=0D unload     (internal) out CX=PSP, DX:AX=previous vector (IRQ 5 off
;                   and INT 0Dh given back first; error 6 if INT 0Dh was
;                   taken after us)
;  AH=0E SRQ IRQ    AL=0 off, 1 on, else ask.  out AX=IRQ in use (5, or 0),
;                   DX:CX=a word +1 at every SRQ interrupt (compare it with
;                   interrupts off, then HLT: an SRQ can't be slept through)
;  Errors: 1 timeout, 2 no listener, 3 not controller/no chip,
;          4 bad function, 5 no data (read timeout), 6 busy (re-entry)
; =====================================================================
cpu 286
org 100h
%define GPIB_STANDALONE

start:  jmp     install

; =====================================================================
;  RESIDENT PART: the kernel's driver (gp_entry: 'GRIDGPIB' at +2, as
;  clients look for it), up to gp_res_end
; =====================================================================
%include "../os/src/KGPIB.INC"
%include "../os/src/EVEN.INC"           ; its hot code even, as in the kernel
        EVEN    gp_cmd_begin, gp_send_cmd, gp_wait_co, gp_wait_co.ok, gp_tick
        EVEN    gp_tmo_start, gp_wait_tick.w, gp_handler.go, gp_isr
        EVEN    gp_fast_write.w, gp_fast_read.w, gp_fast_read.g
                                        ; (a .COM loads on a paragraph and $$
                                        ;  is 100h: the offsets' parity holds)

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
        call    gp_chip_init
        mov     dx, gp_R_ADR0
        in      al, dx
        and     al, 1Fh
        cmp     al, gp_MYADDR
        je      .chip
        mov     dx, s_nochip
        call    tputs
        mov     ax, 4C03h
        int     21h
.chip:  call    gp_bus_init
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
.have:  mov     [gp_intno], al
        mov     ah, 35h
        int     21h
        mov     [gp_oldvec], bx
        mov     [gp_oldvec+2], es
        mov     dx, gp_entry
        mov     ah, 25h
        mov     al, [gp_intno]
        int     21h
        cmp     byte [o_n], 0           ; SRQ on IRQ 5, unless /N
        jne     .noirq
        call    gp_irq_on
.noirq: mov     dx, s_ok1
        call    tputs
        mov     al, [gp_intno]
        call    thex8
        mov     dx, s_ok2
        call    tputs
        cmp     byte [gp_irq], 0
        je      .ni
        mov     dx, s_okirq
        call    tputs
.ni:
        mov     ax, gp_res_end - 100h + 100h
        call    tdec
        mov     dx, s_ok3
        call    tputs
        ; ---- free the environment, stay resident ----
        mov     es, [2Ch]
        mov     ah, 49h
        int     21h
        mov     dx, gp_res_end + 15
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

; find a resident copy: CF=0, AL = vector, ES:BX = gp_entry
findres:
        mov     al, 60h
.l:     push    ax
        mov     ah, 35h
        int     21h
        mov     di, bx
        add     di, 2
        mov     si, gp_sig
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

unload: mov     [gp_intno], al
        mov     ah, [gp_intno]
        mov     byte [ucall+1], ah      ; self-modify: INT nn
        mov     ah, 0Dh
        call    ucall                   ; CX=PSP, DX:AX=old vector
        jnc     .go
        cmp     ax, gp_E_BUSY              ; INT 0Dh taken after us
        jne     .bi                     ; (Lodestone's, in its kernel: no)
        mov     dx, s_unlirq
        jmp     short .bm
.go:
        push    cx
        push    dx
        push    ax
        mov     bl, 0FFh                ; everyone back to local
        mov     ah, 09h
        call    ucall
        pop     ax
        pop     dx
        push    ds
        mov     ds, dx
        mov     dx, ax
        mov     al, [cs:gp_intno]
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
.bi:    mov     dx, s_unlb
        jmp     short .bm
.bad:   mov     dx, s_unlf
.bm:    call    tputs
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
        jne     .nn
        mov     byte [o_f], 1
        jmp     .l
.nn:    cmp     al, 'n'
        jne     .i
        mov     byte [o_n], 1
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
o_n     db 0
o_int   db 0
n_ieee  db 'IEEEOUT',0
s_title db 'GRIDGPIB 1.23 - resident GPIB driver for the GRiDCase 1520 (Lodestone)',13,10,'$'
s_already db 'Already installed.  GRIDGPIB /U unloads it.',13,10,'$'
s_notres db 'Not installed - nothing to unload.',13,10,'$'
s_d488  db '** Driver488 (DRVR488) is loaded and owns the GPIB chip.',13,10
        db '** Reboot without it (or GRIDGPIB /F to force).',13,10,'$'
s_nochip db '** No uPD7210 at 02E1h.',13,10,'$'
s_nocic db '** Not controller in charge after IFC - is the GPIB cable OK?',13,10,'$'
s_novec db '** No free interrupt 60h-66h (use /I:nn).',13,10,'$'
s_ok1   db 'Installed on INT $'
s_ok2   db 'h, bus initialised (IFC, REN), $'
s_okirq db 'SRQ on IRQ 5, $'
s_ok3   db ' bytes resident.',13,10,'$'
s_unl   db 'Unloaded: bus released, REN off, memory freed.',13,10,'$'
s_unlf  db '** Vector restored but memory could not be freed.',13,10,'$'
s_unlb  db '** This driver is built into the system: nothing to unload.',13,10,'$'
s_unlirq db '** Another program took INT 0Dh after GRIDGPIB: unload it first.',13,10,'$'
