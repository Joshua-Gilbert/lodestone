; =====================================================================
;  SERLINK.COM - the Claude link over a serial line or the modem
;  Build: nasm -f bin -o SERLINK.COM SERLINK.ASM
;
;  For a GRiD without the GPIB cartridge (or as a backup to it): CLAUDE.COM
;  talks to gridlink on the Pi through this driver instead, over
;    - the internal 2400-baud modem on COM1 (Option 331), dialing the Pi's
;      modem through the Grandstream HT802 and Asterisk, or
;    - a null-modem cable on the external serial port, COM2, to a USB
;      serial adapter on the Pi.
;  gridlink runs with --bridge modem or --bridge serial (claude-link's
;  README, docs/serial-link.md).
;
;  SERLINK /D:300          COM1, 2400 baud, dial 300 (the Pi's extension)
;  SERLINK /P:2            COM2, 19200 baud, a cable: no dialing
;  SERLINK /P:2 /B:38400   another speed (300 to 115200)
;  SERLINK /U              unload (the modem hung up first)
;  SERLINK                 already loaded: says how it stands
;  /A:n   the link's GPIB address, as CLAUDE /A: (default 7).  Calls for
;         other addresses (instruments) go on to a GPIB driver it was
;         loaded over (the cartridge's), else fail: no listener (error 2).
;  /I:nn  the vector (hex, 60-66; default 60).  CLAUDE.COM takes the first
;         vector from 60h with 'GRIDGPIB' at entry+2, so on 60h this comes
;         ahead of the kernel's GPIB driver; /U puts that back.
;
;  It answers the GRIDGPIB API (KGPIB.INC, GRIDGPIB.ASM's list) as far as
;  CLAUDE.COM and resident Claude use it, with the bytes on the serial line
;  in place of the bus.  GLP frames (claude-link/PROTOCOL.md) are binary
;  and carry their length (sync 47h, type, seq, ack, length, payload, a
;  2-byte check), so no escaping: a read (03h) hunts for the sync byte and
;  returns one whole frame, with DL = 1 (EOI) at its end.  GPIB addresses
;  are ignored.  Bytes come in on the UART's interrupt (IRQ 4 for COM1, 3
;  for COM2) into a 4 KB ring; the serial poll (05h) says 60h (RQS, and the
;  line complete) while anything waits there, 0Bh latches "something came",
;  and 0Eh gives the count of arrivals into an empty ring, which CLAUDE.COM
;  sleeps on as it does on the cartridge's SRQ interrupt.  Version 1.10:
;  CLAUDE.COM keeps the frame check itself (1.23's AL=2/3 are the kernel
;  driver's).  Writes are polled, a byte at a time; on a modem, a write
;  with the carrier gone fails (error 2), and CLAUDE.COM says the link is
;  lost.
;
;  Not inside a task (Lodestone's multitasking): its memory would go when
;  the task ends.  Under Lodestone run it with Shift-Return (the
;  Executive's own task), or with multitasking off.  COM2 is where a serial
;  mouse goes: with the cable there, there is no mouse till /U.
;
;  Errors: 1 timeout, 2 no carrier, 4 bad function, 5 no data, 6 busy
; =====================================================================
cpu 286
org 100h

start:  jmp     install

RING    equ     4096                    ; the receive ring (a power of two)
RMASK   equ     RING - 1
T_DEF   equ     36                      ; ticks: a byte's timeout (2 s)
FMAX    equ     8192                    ; a longer length is no frame

; ---- RESIDENT PART -------------------------------------------------
entry:  jmp     short handler
sig     db      'GRIDGPIB'              ; entry+2: as clients look for it
        db      'SERLINK'               ; (and which one this is)
handler:
        cmp     ah, 2                   ; 02h-09h for another address: the
        jb      .us                     ;  GPIB driver found under us (the
        cmp     ah, 9                   ;  cartridge's instruments), or none
        ja      .us
        cmp     bl, [cs:addr]
        je      .us
        cmp     byte [cs:chain], 0
        je      .nol
        jmp     far [cs:oldvec]
.nol:   mov     ax, 2                   ; (no listener)
        stc
        retf    2
.us:    cmp     byte [cs:busy], 0
        je      .go
        mov     ax, 6
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
.bad:   mov     byte [err], 4
        mov     ax, 4
        jmp     done
.ok:    xor     bh, bh
        shl     bx, 1
        jmp     [functab + bx]
done:   pop     es
        pop     ds
        pop     bp
        pop     di
        pop     si
        pop     bx
        cmp     byte [cs:err], 1        ; CF = error
        cmc
        mov     byte [cs:busy], 0
        retf    2

functab dw      f_present, f_ok, f_write, f_read, f_query, f_spoll
        dw      f_clear, f_ok, f_ok, f_ok, f_timeout, f_srq
        dw      f_stats, f_unload, f_irq
NFUNC   equ     ($ - functab) / 2

fail:   mov     [err], al               ; AL = the error
        xor     ah, ah
        jmp     done

f_present:
        mov     ax, 4747h
        mov     cx, 0110h               ; (under 1.23: the frame check is CLAUDE's)
        mov     dh, [intno]
        mov     dl, 0
        jmp     done

f_ok:   xor     ax, ax
        jmp     done

; 02h: DS:SI, CX bytes out, a byte at a time as the UART takes them
f_write:
        call    carrier
        jc      .nc
        mov     es, [c_ds]
        mov     si, [c_si]
        mov     cx, [c_cx]
        call    send
        jc      .t
        xor     ax, ax
        mov     cx, [c_cx]
        jmp     done
.t:     inc     word [ntmo]
        mov     al, 1
        jmp     fail
.nc:    mov     al, 2
        jmp     fail

; 03h: one frame, or what fits in CX of it (DL 4: call again for the rest)
f_read: mov     es, [c_es]
        mov     di, [c_di]
        mov     cx, [c_cx]
rd:     xor     bp, bp                  ; (bytes stored)
        jcxz    .full
        cmp     word [left], 0
        jne     .copy
.hunt:  call    getb                    ; the sync byte
        jc      .none
        cmp     al, 47h
        jne     .hunt
        mov     [hdr], al
        mov     si, 1
.h:     call    getb                    ; type, seq, ack, length
        jc      .none
        mov     [hdr + si], al
        inc     si
        cmp     si, 6
        jb      .h
        mov     ax, [hdr + 4]
        cmp     ax, FMAX
        ja      .hunt                   ; (no frame: look again)
        add     ax, 8
        mov     [left], ax
        mov     word [hpos], 0
.copy:  mov     bx, [hpos]
        cmp     bx, 6
        jae     .b
        mov     al, [hdr + bx]
        inc     word [hpos]
        jmp     short .s
.b:     call    getb
        jc      .tmo
.s:     stosb
        inc     bp
        dec     word [left]
        jz      .end
        loop    .copy
.full:  mov     dl, 4
        jmp     short .ret
.end:   mov     dl, 1
.ret:   xor     ax, ax
        mov     cx, bp
        mov     [c_dx], dx
        jmp     done_dx
.tmo:   mov     word [left], 0          ; (the frame is lost: CLAUDE NAKs)
        inc     word [ntmo]
        mov     dl, 8
        jmp     short .ret
.none:  mov     word [left], 0
        or      bp, bp
        jnz     .tmo
        inc     word [ntmo]
        mov     al, 5
        jmp     fail
done_dx:                                ; DX out as well
        mov     dx, [c_dx]
        jmp     done

; 04h: write (DS:SI, CX), then read (ES:DI, DX max)
f_query:
        call    carrier
        jc      f_write.nc
        mov     es, [c_ds]
        mov     si, [c_si]
        mov     cx, [c_cx]
        call    send
        jc      f_write.t
        mov     es, [c_es]
        mov     di, [c_di]
        mov     cx, [c_dx]
        jmp     rd

; 05h: AL = 60h (RQS, the line complete) while anything waits, else 0
f_spoll:
        call    drain
        xor     ax, ax
        mov     bx, [rhead]
        cmp     bx, [rtail]
        jne     .y
        cmp     word [left], 0
        je      .n
.y:     mov     al, 60h
.n:     jmp     done

; 06h: drop what waits (a half-read frame too)
f_clear:
        cli
        mov     ax, [rhead]
        mov     [rtail], ax
        sti
        xor     ax, ax
        mov     [left], ax
        mov     [latch], al
        jmp     done

; 0Ah: BX = ms a byte (0: 2000) -> AX = the old
f_timeout:
        mov     ax, [tdata]
        mov     dx, 55
        mul     dx
        push    ax
        mov     ax, [c_bx]
        or      ax, ax
        jnz     .c
        mov     ax, T_DEF * 55
.c:     add     ax, 54
        jnc     .d
        mov     ax, 0FFFFh
.d:     xor     dx, dx
        mov     cx, 55
        div     cx
        cmp     ax, 2
        jae     .s
        mov     ax, 2
.s:     mov     [tdata], ax
        pop     ax
        jmp     done

; 0Bh: AX = 1 if anything came since the last call
f_srq:  call    drain
        xor     ax, ax
        xchg    al, [latch]
        jmp     done

; 0Ch: AX = overruns, CX = timeouts, DX = resident bytes
f_stats:
        mov     ax, [novr]
        mov     cx, [ntmo]
        mov     dx, res_end
        jmp     done

; 0Dh (SERLINK /U): the UART, its IRQ and the PIC as found -> CX = the
; PSP, DX:AX = the vector found.  Error 6 if the IRQ's vector was taken
; after us
f_unload:
        push    es
        push    0
        pop     es
        mov     bx, [irqvec]
        shl     bx, 2
        cli
        cmp     word [es:bx], isr
        jne     .taken
        mov     ax, cs
        cmp     [es:bx + 2], ax
        jne     .taken
        call    uart_off
        mov     ax, [oldirq]
        mov     [es:bx], ax
        mov     ax, [oldirq + 2]
        mov     [es:bx + 2], ax
        sti
        pop     es
        mov     cx, cs                  ; (.COM: CS = its PSP)
        mov     ax, [oldvec]
        mov     dx, [oldvec + 2]
        mov     [c_dx], dx
        jmp     done_dx
.taken: sti
        pop     es
        mov     al, 6
        jmp     fail

; 0Eh: AX = the IRQ (4 or 3), DX:CX = the count of arrivals into an
; empty ring (compare it with interrupts off, then HLT)
f_irq:  mov     al, [irqno]
        cmp     byte [noirq], 0
        je      .i
        xor     al, al                  ; (polled: no count to sleep on)
.i:     xor     ah, ah
        mov     cx, nsrq
        mov     dx, cs
        mov     [c_dx], dx
        jmp     done_dx

; ---- the resident part's own -----------------------------------------
; CF if a modem's carrier is gone (MSR's DCD)
carrier:
        cmp     byte [modem], 0
        je      .ok
        mov     dx, [base]
        add     dx, 6
        in      al, dx
        test    al, 80h
        jnz     .ok
        stc
        ret
.ok:    clc
        ret

; ES:SI, CX bytes out (CF: the UART never took one)
send:   jcxz    .x
.b:     call    tick
        mov     bx, ax
.w:     mov     dx, [base]
        add     dx, 5
        in      al, dx
        test    al, 20h
        jnz     .go
        call    tick
        sub     ax, bx
        cmp     ax, [tdata]
        jb      .w
        stc
        ret
.go:    mov     dx, [base]
        es lodsb
        out     dx, al
        loop    .b
.x:     clc
        ret

; a byte from the ring -> AL, or CF after the timeout.  BX, CX, DX kept
getb:   push    bx
        push    dx
        call    drain
        mov     bx, [rtail]
        cmp     bx, [rhead]
        jne     .have
        call    tick
        mov     dx, ax
.w:     sti
        call    drain
        mov     bx, [rtail]
        cmp     bx, [rhead]
        jne     .have
        call    tick
        sub     ax, dx
        cmp     ax, [tdata]
        jb      .w
        pop     dx
        pop     bx
        stc
        ret
.have:  mov     al, [ring + bx]
        inc     bx
        and     bx, RMASK
        mov     [rtail], bx
        pop     dx
        pop     bx
        clc
        ret

; AX = the BIOS's tick count (0:46Ch)
tick:   push    ds
        push    0
        pop     ds
        mov     ax, [46Ch]
        pop     ds
        ret

; the UART's interrupt: whatever came, into the ring
isr:    push    ax
        push    bx
        push    dx
        push    ds
        push    cs
        pop     ds
        inc     word [nisr]
.l:     mov     dx, [base]
        add     dx, 2
        in      al, dx                  ; IIR: what is pending
        test    al, 1
        jnz     .eoi
        and     al, 6
        cmp     al, 4
        je      .rx
        mov     dx, [base]              ; line or modem status, or the
        add     dx, 5                   ;  transmitter: read, so it clears
        in      al, dx
        test    al, 2
        jz      .m
        inc     word [novr]
.m:     inc     dx
        in      al, dx
        jmp     .l
.rx:    call    drain
        jmp     .l
.eoi:   mov     al, 20h
        out     20h, al
        pop     ds
        pop     dx
        pop     bx
        pop     ax
        iret

; whatever the UART holds, into the ring (the ISR's; and every wait's and
; poll's, should the port's IRQ never come: polled then).  AX BX DX kept
drain:  push    ax
        push    bx
        push    dx
        pushf
        cli
.l:     mov     dx, [base]
        add     dx, 5
        in      al, dx
        test    al, 2
        jz      .r0
        inc     word [novr]             ; (the UART's own overrun)
.r0:    test    al, 1
        jz      .x
        mov     dx, [base]
        in      al, dx
        mov     bx, [rhead]
        mov     dx, bx
        inc     dx
        and     dx, RMASK
        cmp     dx, [rtail]
        je      .full
        cmp     bx, [rtail]             ; into an empty ring: an "SRQ"
        jne     .st
        inc     word [nsrq]
.st:    mov     [ring + bx], al
        mov     [rhead], dx
        mov     byte [latch], 1
        jmp     .l
.full:  inc     word [novr]
        jmp     .l
.x:     popf
        pop     dx
        pop     bx
        pop     ax
        ret

; the UART and the PIC as they were found (interrupts off)
uart_off:
        mov     dx, [base]
        inc     dx
        xor     al, al
        out     dx, al                  ; IER: none
        inc     dx
        out     dx, al                  ; FCR: the FIFO off
        add     dx, 2
        mov     al, [o_mcr]
        out     dx, al
        dec     dx
        mov     al, 80h
        out     dx, al
        mov     dx, [base]
        mov     al, [o_dll]
        out     dx, al
        inc     dx
        mov     al, [o_dlm]
        out     dx, al
        add     dx, 2
        mov     al, [o_lcr]
        out     dx, al
        mov     dx, [base]
        inc     dx
        mov     al, [o_ier]
        out     dx, al
        in      al, 21h
        mov     ah, [picbit]
        not     ah
        and     al, ah
        or      al, [o_pic]
        out     21h, al
        ret

; ---- resident data ---------------------------------------------------
busy    db      0
err     db      0
c_al    db      0
modem   db      0                       ; 1: dialed out (the carrier counts)
addr    db      7                       ; the link's GPIB address (CLAUDE /A:)
chain   db      0                       ; 1: a GRIDGPIB under us takes the rest
intno   db      60h
irqno   db      4
irqvec  dw      0Ch
picbit  db      10h
o_pic   db      0                       ; (its bit in the PIC's mask, found)
o_lcr   db      0
o_dll   db      0
o_dlm   db      0
o_ier   db      0
o_mcr   db      0
latch   db      0
noirq   db      0                       ; 1: the port's IRQ never came (install's
                                        ;  test): polled, and 0Eh says none
base    dw      3F8h
tdata   dw      T_DEF
c_ds    dw      0
c_es    dw      0
c_si    dw      0
c_di    dw      0
c_cx    dw      0
c_dx    dw      0
c_bx    dw      0
rhead   dw      0
rtail   dw      0
left    dw      0                       ; bytes of the frame still to read
hpos    dw      0
nsrq    dw      0
nisr    dw      0
novr    dw      0
ntmo    dw      0
oldvec  dd      0
oldirq  dd      0
divisor dw      48
hdr     times 6 db 0
        align   2
ring    times RING db 0                 ; (its own room: the installer below
res_end equ     $                       ;  runs while the modem answers into it)

; =====================================================================
;  TRANSIENT PART (the installer) - gone once resident
; =====================================================================
install:
        cld
        mov     dx, s_title
        call    tputs
        call    parse
        call    findres                 ; AL = its vector, ES = its segment
        jc      .notin
        cmp     byte [o_u], 0
        jne     unload
        call    status
        mov     ax, 4C01h
        int     21h
.notin: cmp     byte [o_u], 0
        je      .inst
        mov     dx, s_notres
        jmp     quit1
.inst:  mov     ax, 0F012h              ; not inside a task (Lodestone's
        xor     cx, cx                  ;  multitasking, MT_LIST: AH = ours):
        stc                             ;  its memory would go when it ends
        int     21h
        jc      .t0
        or      ah, ah
        jz      .t0
        mov     dx, s_task
        jmp     quit1
.t0:    ; ---- the port ----
        cmp     byte [o_port], 2
        jne     .p1
        mov     word [base], 2F8h
        mov     byte [irqno], 3
        mov     word [irqvec], 0Bh
        mov     byte [picbit], 08h
        mov     word [divisor], 6       ; 19200
.p1:    cmp     word [o_div], 0
        je      .pd
        mov     ax, [o_div]
        mov     [divisor], ax
.pd:    mov     dx, [base]              ; a UART there?  (its scratch register,
        add     dx, 7                   ;  else LCR: an 8250 has none)
        mov     al, 5Ah
        out     dx, al
        jmp     $ + 2
        in      al, dx
        cmp     al, 5Ah
        je      .u
        mov     dx, [base]
        add     dx, 3
        in      al, dx
        mov     bl, al
        mov     al, 1Bh
        out     dx, al
        jmp     $ + 2
        in      al, dx
        xchg    al, bl
        out     dx, al
        cmp     bl, 1Bh
        je      .u
        mov     dx, s_nouart
        jmp     quit1
.u:     ; ---- the vector ----
        mov     al, [o_int]
        or      al, al
        jnz     .v
        mov     al, 60h
.v:     mov     [intno], al
        mov     ah, 35h
        int     21h
        mov     [oldvec], bx
        mov     [oldvec + 2], es
        lea     di, [bx + 2]            ; a GPIB driver there: the other
        mov     si, sig                 ;  addresses go on to it
        mov     cx, 8
        repe    cmpsb
        jne     .nc
        mov     byte [chain], 1
.nc:    push    cs
        pop     es
        mov     al, [o_addr]
        mov     [addr], al
        ; ---- the UART, as found, then ours ----
        call    uart_on
        call    irqtest
        ; ---- a modem: dial ----
        cmp     byte [o_dial], 0
        je      .nodial
        call    dial
        jnc     .dialed
        cli
        call    uart_off
        call    irq_back
        sti
        mov     ax, 4C02h
        int     21h
.dialed:
        mov     byte [modem], 1
.nodial:
        cli                             ; (what came while dialing: gone)
        mov     ax, [rhead]
        mov     [rtail], ax
        mov     byte [latch], 0
        sti
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
        call    portline
        cmp     byte [chain], 0
        je      .noch
        mov     dx, s_chain
        call    tputs
.noch:  mov     ax, res_end
        call    tdec
        mov     dx, s_ok3
        call    tputs
        mov     es, [2Ch]               ; the environment, then stay
        mov     ah, 49h
        int     21h
        mov     dx, res_end + 15
        shr     dx, 4
        mov     ax, 3100h
        int     21h

quit1:  call    tputs
        mov     ax, 4C01h
        int     21h

; the UART as found kept, then: our speed, 8N1, the FIFO if any (one byte
; to interrupt), DTR, RTS and OUT2 (the IRQ's gate), the receive
; interrupt; our ISR on its IRQ, unmasked
uart_on:
        cli
        mov     dx, [base]
        add     dx, 3
        in      al, dx
        mov     [o_lcr], al
        or      al, 80h
        out     dx, al
        mov     dx, [base]
        in      al, dx
        mov     [o_dll], al
        inc     dx
        in      al, dx
        mov     [o_dlm], al
        add     dx, 2
        mov     al, [o_lcr]
        and     al, 7Fh
        out     dx, al
        mov     dx, [base]
        inc     dx
        in      al, dx
        mov     [o_ier], al
        add     dx, 3
        in      al, dx
        mov     [o_mcr], al
        in      al, 21h
        and     al, [picbit]
        mov     [o_pic], al
        push    es                      ; the IRQ's vector: ours
        push    0
        pop     es
        mov     bx, [irqvec]
        shl     bx, 2
        mov     ax, [es:bx]
        mov     [oldirq], ax
        mov     ax, [es:bx + 2]
        mov     [oldirq + 2], ax
        mov     word [es:bx], isr
        mov     [es:bx + 2], cs
        pop     es
        mov     dx, [base]
        add     dx, 3
        mov     al, 80h
        out     dx, al
        mov     dx, [base]
        mov     ax, [divisor]
        out     dx, al
        inc     dx
        mov     al, ah
        out     dx, al
        add     dx, 2
        mov     al, 03h
        out     dx, al
        dec     dx
        mov     al, 07h                 ; FCR: on, both cleared, 1 byte
        out     dx, al
        add     dx, 2
        mov     al, 0Bh                 ; MCR: DTR, RTS, OUT2
        out     dx, al
        mov     dx, [base]              ; anything stale: read and dropped
        mov     cx, 32
.d:     add     dx, 5
        in      al, dx
        sub     dx, 5
        test    al, 1
        jz      .e
        in      al, dx
        loop    .d
.e:     add     dx, 2
        in      al, dx
        add     dx, 4
        in      al, dx
        mov     dx, [base]
        inc     dx
        mov     al, 01h                 ; IER: data in
        out     dx, al
        in      al, 21h
        mov     ah, [picbit]
        not     ah
        and     al, ah
        out     21h, al
        sti
        ret

; does the port's IRQ come?  The transmitter-empty interrupt for a moment
; (IER bit 1: it is pending at once, the transmitter being idle).  None:
; polled (noirq), said so
irqtest:
        mov     word [nisr], 0
        mov     dx, [base]
        inc     dx
        mov     al, 03h
        out     dx, al
        mov     cx, 2
        call    wticks
        mov     dx, [base]
        inc     dx
        mov     al, 01h
        out     dx, al
        cmp     word [nisr], 0
        jne     .x
        mov     byte [noirq], 1
        mov     dx, s_noirq
        call    tputs
.x:     ret

irq_back:                               ; the IRQ's vector as found
        push    es
        push    0
        pop     es
        mov     bx, [irqvec]
        shl     bx, 2
        mov     ax, [oldirq]
        mov     [es:bx], ax
        mov     ax, [oldirq + 2]
        mov     [es:bx + 2], ax
        pop     es
        ret

; ---- the modem ---------------------------------------------------
; AT, the settings, then ATDT and the number; CF if no CONNECT
dial:   mov     dx, s_modem
        call    tputs
        mov     cx, 10                  ; (DTR up: give it half a second)
        call    wticks
        mov     si, at_at
        mov     bx, 36
        call    atcmd
        jnc     .a
        mov     si, at_at               ; (once more: it may have woken)
        mov     bx, 36
        call    atcmd
        jnc     .a
        mov     dx, s_nomodem
        call    tputs
        stc
        ret
.a:     mov     si, at_set
        mov     bx, 36
        call    atcmd
        mov     si, at_cd               ; (some don't know &C/&D: either way)
        mov     bx, 36
        call    atcmd
        mov     dx, s_dial
        call    tputs
        mov     si, o_num
        call    tputz
        mov     dx, s_crlf
        call    tputs
        mov     si, at_d                ; ATDT and the number
        call    sendz
        mov     si, o_num
        call    sendz
        mov     si, at_cr
        call    sendz
        call    tick
        mov     [t0], ax
        mov     bx, 1100                ; up to a minute for the call
.r:     call    result
        jc      .no
        mov     ax, [line]
        cmp     ax, 'CO'                ; CONNECT
        je      .c
        cmp     ax, 'NO'                ; NO CARRIER, NO DIALTONE, NO ANSWER
        je      .no
        cmp     ax, 'BU'                ; BUSY
        je      .no
        cmp     ax, 'ER'                ; ERROR
        je      .no
        jmp     .r                      ; (an echo, RING: the next line)
.c:
        mov     dx, s_conn
        call    tputs
        mov     dx, line
        call    tputs
        mov     dx, s_crlf
        call    tputs
        clc
        ret
.no:    mov     dx, s_noconn
        call    tputs
        mov     dx, line
        call    tputs
        mov     dx, s_crlf
        call    tputs
        mov     byte [o_mcr], 0         ; (DTR down at uart_off: hung up)
        stc
        ret

; send the AT command at SI (ends 0, with its CR); CF unless OK comes
; within BX ticks (lines before it, the command's echo, skipped)
atcmd:  push    bx
        call    sendz
        pop     bx
        call    tick
        mov     [t0], ax
.l:     call    result
        jc      .x
        cmp     word [line], 'OK'
        je      .x
        cmp     word [line], 'ER'
        jne     .l
        stc
.x:     ret

; the 0-ended string at SI out (polled)
sendz:  push    es
        push    ds
        pop     es
        mov     di, si
        xor     al, al
        mov     cx, 0FFFFh
        repne   scasb
        not     cx
        dec     cx
        call    send
        pop     es
        ret

; the modem's next line (not empty) -> line ($-ended), CF if none by BX
; ticks after t0
result: mov     di, line
.c:     call    drain
        mov     si, [rtail]
        cmp     si, [rhead]
        jne     .g
        call    tick
        sub     ax, [t0]
        cmp     ax, bx
        jb      .c
        mov     byte [di], '$'
        stc
        ret
.g:     call    getb
        cmp     al, 13
        je      .e
        cmp     al, 10
        je      .e
        cmp     di, line + 38
        jae     .c
        mov     [di], al
        inc     di
        jmp     .c
.e:     cmp     di, line
        je      .c                      ; (an empty line: the next)
        mov     byte [di], '$'
        clc
        ret

; wait CX ticks
wticks: call    tick
        mov     bx, ax
.w:     sti
        call    tick
        sub     ax, bx
        cmp     ax, cx
        jb      .w
        ret

; ---- already loaded: how it stands, and unloading ----------------------
; (ES = its segment; its variables are at the same offsets as ours)
status: mov     dx, s_loaded
        call    tputs
        mov     ax, [es:base]
        mov     [base], ax
        mov     al, [es:intno]
        mov     [intno], al
        mov     ax, [es:divisor]
        mov     [divisor], ax
        mov     al, [es:modem]
        mov     [modem], al
        mov     dx, s_ok1
        call    tputs
        mov     al, [intno]
        call    thex8
        mov     dx, s_ok2
        call    tputs
        call    portline
        cmp     byte [modem], 0
        je      .x
        mov     dx, [base]
        add     dx, 6
        in      al, dx
        mov     dx, s_carrier
        test    al, 80h
        jnz     .c
        mov     dx, s_nocarrier
.c:     call    tputs
.x:     mov     dx, s_unhow
        jmp     tputs

unload: mov     [intno], al
        mov     byte [ucall + 1], al    ; (INT nn)
        mov     ax, [es:base]
        mov     [base], ax
        cmp     byte [es:modem], 0
        je      .u
        mov     dx, s_hang
        call    tputs
        call    hangup
.u:     mov     ah, 0Dh
        call    ucall                   ; CX = its PSP, DX:AX = the vector found
        jnc     .go
        mov     dx, s_unirq
        jmp     quit1
.go:    push    cx
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
        mov     dx, s_unl
        jc      quit1
        call    tputs
        mov     ax, 4C00h
        int     21h
ucall:  int     60h
        ret

; hang up: DTR down a second (the modem's &D2); if the carrier stays,
; +++ between two silences, then ATH0
hangup: mov     dx, [base]
        add     dx, 4
        in      al, dx
        and     al, 0FEh
        out     dx, al
        mov     cx, 20
        call    wticks
        mov     dx, [base]
        add     dx, 4
        in      al, dx
        or      al, 01h
        out     dx, al
        mov     dx, [base]
        add     dx, 6
        in      al, dx
        test    al, 80h
        jz      .x
        mov     cx, 22
        call    wticks
        mov     si, at_esc
        push    ds
        pop     es
        mov     cx, 3
        call    send
        mov     cx, 22
        call    wticks
        mov     si, at_h
        call    sendz
        mov     cx, 10
        call    wticks
.x:     ret

; find a loaded copy: CF clear, AL = its vector, ES = its segment
findres:
        mov     al, 60h
.l:     push    ax
        mov     ah, 35h
        int     21h
        lea     di, [bx + 2]
        mov     si, sig
        mov     cx, 15
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

; "COM1, 2400 baud, " from base and divisor
portline:
        mov     dx, s_com1
        cmp     word [base], 3F8h
        je      .p
        mov     dx, s_com2
.p:     call    tputs
        cmp     word [divisor], 1       ; (115200: too big for the word tdec takes)
        jne     .b
        mov     dx, s_115
        call    tputs
        jmp     short .t
.b:     mov     ax, 0C200h              ; 115200 / the divisor
        mov     dx, 1
        div     word [divisor]          ; (under 65536 for divisors over 1)
        call    tdec
.t:     mov     dx, s_baud
        jmp     tputs

; ---- the command line ------------------------------------------------
parse:  mov     si, 81h
.l:     lodsb
        cmp     al, 13
        je      .x
        cmp     al, '/'
        jne     .l
        lodsb
        or      al, 20h
        cmp     al, 'u'
        jne     .p
        mov     byte [o_u], 1
        jmp     .l
.p:     cmp     al, 'p'
        jne     .b
        lodsb                           ; ':'
        lodsb
        cmp     al, '2'
        jne     .l
        mov     byte [o_port], 2
        jmp     .l
.b:     cmp     al, 'b'
        jne     .d
        lodsb                           ; ':'
        call    pdec                    ; DX:AX
        or      dx, dx
        jz      .b16
        mov     word [o_div], 1         ; (115200)
        jmp     .l
.b16:   or      ax, ax
        jz      .l
        mov     bx, ax
        mov     ax, 0C200h
        mov     dx, 1
        cmp     bx, 2                   ; (a quotient that fits a word)
        jb      .l
        div     bx
        mov     [o_div], ax
        jmp     .l
.d:     cmp     al, 'd'
        jne     .a
        lodsb                           ; ':'
        mov     di, o_num
.dc:    lodsb
        cmp     al, ' '
        jbe     .de
        cmp     al, '/'
        je      .de
        cmp     di, o_num + 30
        jae     .dc
        mov     [di], al
        inc     di
        jmp     .dc
.de:    mov     byte [di], 0
        dec     si
        cmp     di, o_num
        je      .l
        mov     byte [o_dial], 1
        jmp     .l
.a:     cmp     al, 'a'
        jne     .i
        lodsb                           ; ':'
        call    pdec
        cmp     ax, 30
        ja      .l
        mov     [o_addr], al
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

; a decimal number at SI -> DX:AX
pdec:   xor     ax, ax
        xor     dx, dx
.n:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .x
        inc     si
        push    bx
        mov     bx, 10                  ; DX:AX * 10
        push    ax
        mov     ax, dx
        mul     bx
        mov     cx, ax
        pop     ax
        mul     bx
        add     dx, cx
        pop     bx
        xor     bh, bh
        add     ax, bx
        adc     dx, 0
        jmp     .n
.x:     ret

hexd:   lodsb
        or      al, 20h
        sub     al, '0'
        cmp     al, 9
        jbe     .ok
        sub     al, 'a' - '0' - 10
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
tputz:  lodsb                           ; (SI: ends 0)
        or      al, al
        jz      .x
        mov     dl, al
        mov     ah, 02h
        int     21h
        jmp     tputz
.x:     ret
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

o_u     db      0
o_port  db      1
o_dial  db      0
o_int   db      0
o_addr  db      7
o_div   dw      0
t0      dw      0
o_num   times 32 db 0
line    times 40 db '$'
at_at   db      'AT', 13, 0
at_set  db      'ATE0V1Q0X4', 13, 0
at_cd   db      'AT&C1&D2', 13, 0
at_d    db      'ATDT', 0
at_cr   db      13, 0
at_esc  db      '+++'
at_h    db      'ATH0', 13, 0
s_title db      'SERLINK 1.0 - the Claude link over a serial line or the modem', 13, 10, '$'
s_notres db     'Not loaded: nothing to unload.', 13, 10, '$'
s_task  db      '** Not inside a task: its memory would go when the task ends.', 13, 10
        db      '** Run it with Shift-Return (the Executive', 39, 's own task).', 13, 10, '$'
s_nouart db     '** No serial port there.', 13, 10, '$'
s_modem db      'Modem: $'
s_noirq db      'The port', 39, 's IRQ never came: polled (slower; fine at 2400 baud).', 13, 10, '$'
s_nomodem db    'no answer to AT.', 13, 10, '$'
s_dial  db      'dialing $'
s_conn  db      'Connected: $'
s_noconn db     '** No connection: $'
s_crlf  db      13, 10, '$'
s_ok1   db      'On INT $'
s_ok2   db      'h, $'
s_ok3   db      ' bytes resident.', 13, 10, '$'
s_chain db      'GPIB instruments through the driver under it, $'
s_com1  db      'COM1, $'
s_com2  db      'COM2, $'
s_115   db      '115200$'
s_baud  db      ' baud, $'
s_loaded db     'Loaded.  $'
s_carrier db    13, 10, 'The modem has a carrier.$'
s_nocarrier db  13, 10, '** The modem has lost its carrier: SERLINK /U, then dial again.$'
s_unhow db      13, 10, 'SERLINK /U unloads it.', 13, 10, '$'
s_hang  db      'Hanging up.', 13, 10, '$'
s_unirq db      '** Another program took the serial port', 39, 's interrupt after SERLINK: unload it first.', 13, 10, '$'
s_unl   db      'Unloaded.', 13, 10, '$'
