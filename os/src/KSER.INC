; =====================================================================
;  KSER.INC - the kernel's serial link driver (INT 60h), in place of the
;  GPIB driver (KGPIB.INC) in a kernel built with -dSERIAL: for a GRiD
;  without the GPIB cartridge.  KFLAGS=-dSERIAL sh build.sh (README's
;  Building) makes that kernel, LODEMT.SYS and the ROM images with it.
;
;  The resident part of tools/SERLINK.ASM (docs/serial-link.md), for a
;  null-modem cable to the Pi (gridlink --bridge serial): the GRIDGPIB API
;  as CLAUDE.COM uses it, the GLP frames on the line as they are (a read
;  returns one whole frame, found by its header's length), only the
;  link's address (7) served.  Other addresses (GPIBnn, instruments): no
;  listener.  No dialing: for the modem, SERLINK=OFF and SERLINK.COM /D:.
;
;  Pre-interrupt style, as the GPIB driver before its SRQ interrupt: the
;  UART's received-data interrupt fills a 2 KB ring (the 1520's 16450
;  holds one byte, so polling alone loses them past 2400 baud), but 0Eh
;  says no IRQ: CLAUDE.COM polls (0Bh, the serial poll) instead of sleeping
;  on a count, and multitasking's SRQ wake (T5c) isn't hooked.
;
;  The port is taken at the link's first call, not at start-up: the UI's
;  mouse probe (COM2, then COM1) comes after, and would reprogram it.  Each
;  call checks the port is still ours (its IRQ's vector, the line's speed)
;  and takes it again if a program or the mouse driver changed it.  A
;  serial mouse and the link can't share COM2.
;
;  SERLINK=COM2,19200 in LODE.INI (the default), SERLINK=COM1,2400, or
;  SERLINK=OFF (sl_boot, KSPLASH.INC: function 0Fh).  Signature 'GRIDGPIB'
;  then 'SERKERN' (SERLINK.COM's own is 'SERLINK': it can be loaded over
;  this one, for the modem).  Version 1.10: CLAUDE.COM keeps the frame
;  check.  Errors: 1 timeout, 2 no listener, 3 the link off, 4 bad
;  function, 5 no data, 6 busy.
; =====================================================================
gp_RING    equ 2048                    ; the receive ring (a power of two)
gp_RMASK   equ gp_RING - 1
gp_T_DEF   equ 36                      ; ticks: a byte's timeout (2 s)
gp_FMAX    equ 8192                    ; a longer length is no frame
gp_IRQVEC  equ 0Bh                     ; (for KMT.INC's T5c code, never used
gp_isr     equ sl_isr                  ;  in this build: its hook is left out)

section .bss
sl_busy     resb 1
sl_err      resb 1
sl_c_al     resb 1
sl_latch    resb 1
sl_mine     resb 1              ; 1: the port is set up as ours
sl_hdr      resb 6
            alignb 2
sl_c_ds     resw 1
sl_c_es     resw 1
sl_c_si     resw 1
sl_c_di     resw 1
sl_c_cx     resw 1
sl_c_dx     resw 1
sl_c_bx     resw 1
sl_rhead    resw 1
sl_rtail    resw 1
sl_left     resw 1              ; bytes of the frame still to read
sl_hpos     resw 1
sl_novr     resw 1
sl_ntmo     resw 1
sl_oldirq   resd 1
sl_ring     resb gp_RING
section .text

gp_irq      db  0               ; (KMT.INC's MT_LIST: no SRQ interrupt)
sl_port     db  2               ; 0 off, 1 COM1, 2 COM2 (SERLINK=)
sl_addr     db  7
sl_tdata    dw  gp_T_DEF
sl_div      dw  6               ; 19200 baud
sl_base     dw  2F8h

gp_entry:  jmp     short sl_handler
gp_sig     db 'GRIDGPIB'                ; entry+2: as clients look for it
           db 'SERKERN'
sl_handler:
        cmp     ah, 2                   ; 02h-09h for another address: no
        jb      .us                     ;  listener (GPIBnn, instruments)
        cmp     ah, 9
        ja      .us
        cmp     bl, [cs:sl_addr]
        je      .us
        mov     ax, 2
        stc
        retf    2
.us:    cmp     byte [cs:sl_busy], 0
        je      .go
        mov     ax, 6
        stc
        retf    2
.go:    mov     byte [cs:sl_busy], 1
        sti
        cld
        push    bx
        push    si
        push    di
        push    bp
        push    ds
        push    es
        mov     [cs:sl_c_ds], ds
        push    cs
        pop     ds
        mov     [sl_c_es], es
        mov     [sl_c_si], si
        mov     [sl_c_di], di
        mov     [sl_c_cx], cx
        mov     [sl_c_dx], dx
        mov     [sl_c_bx], bx
        mov     [sl_c_al], al
        mov     byte [sl_err], 0
        mov     bl, ah
        cmp     bl, SL_NFUNC
        jb      .ok
        mov     al, 4
        jmp     sl_fail
.ok:    xor     bh, bh
        shl     bx, 1
        jmp     [sl_functab + bx]
sl_done:
        pop     es
        pop     ds
        pop     bp
        pop     di
        pop     si
        pop     bx
        cmp     byte [cs:sl_err], 1     ; CF = error
        cmc
        mov     byte [cs:sl_busy], 0
        retf    2
sl_done_dx:
        mov     dx, [sl_c_dx]
        jmp     sl_done
sl_fail:
        mov     [sl_err], al
        xor     ah, ah
        jmp     sl_done

sl_functab dw   sl_present, sl_ok, sl_write, sl_read, sl_query, sl_spoll
        dw      sl_clear, sl_ok, sl_ok, sl_ok, sl_timeout, sl_srq
        dw      sl_stats, sl_bad, sl_irqf, sl_config
SL_NFUNC equ    ($ - sl_functab) / 2

sl_present:
        mov     ax, 4747h
        mov     cx, 0110h               ; (under 1.23: the frame check is CLAUDE's)
        mov     dx, 6000h               ; (DH: its vector; DL: none of its own)
        mov     [sl_c_dx], dx
        jmp     sl_done_dx
sl_ok:  xor     ax, ax
        jmp     sl_done
sl_bad: mov     al, 4                   ; (0Dh, SERLINK.COM's unload: built in)
        jmp     sl_fail

; 02h: DS:SI, CX bytes out, a byte at a time
sl_write:
        call    sl_take
        jc      sl_off
        mov     es, [sl_c_ds]
        mov     si, [sl_c_si]
        mov     cx, [sl_c_cx]
        call    sl_send
        jc      sl_wtmo
        xor     ax, ax
        mov     cx, [sl_c_cx]
        jmp     sl_done
sl_wtmo:
        inc     word [sl_ntmo]
        mov     al, 1
        jmp     sl_fail
sl_off: mov     al, 3
        jmp     sl_fail

; 03h: one frame, or what fits in CX of it (DL 4: call again for the rest)
sl_read:
        call    sl_take
        jc      sl_off
        mov     es, [sl_c_es]
        mov     di, [sl_c_di]
        mov     cx, [sl_c_cx]
sl_rd:  xor     bp, bp                  ; (bytes stored)
        jcxz    .full
        cmp     word [sl_left], 0
        jne     .copy
.hunt:  call    sl_getb                 ; the sync byte
        jc      .none
        cmp     al, 47h
        jne     .hunt
        mov     [sl_hdr], al
        mov     si, 1
.h:     call    sl_getb                 ; type, seq, ack, length
        jc      .none
        mov     [sl_hdr + si], al
        inc     si
        cmp     si, 6
        jb      .h
        mov     ax, [sl_hdr + 4]
        cmp     ax, gp_FMAX
        ja      .hunt                   ; (no frame: look again)
        add     ax, 8
        mov     [sl_left], ax
        mov     word [sl_hpos], 0
.copy:  mov     bx, [sl_hpos]
        cmp     bx, 6
        jae     .b
        mov     al, [sl_hdr + bx]
        inc     word [sl_hpos]
        jmp     short .s
.b:     call    sl_getb
        jc      .tmo
.s:     stosb
        inc     bp
        dec     word [sl_left]
        jz      .end
        loop    .copy
.full:  mov     dl, 4
        jmp     short .ret
.end:   mov     dl, 1
.ret:   xor     ax, ax
        mov     cx, bp
        mov     [sl_c_dx], dx
        jmp     sl_done_dx
.tmo:   mov     word [sl_left], 0       ; (the frame is lost: CLAUDE NAKs)
        inc     word [sl_ntmo]
        mov     dl, 8
        jmp     short .ret
.none:  mov     word [sl_left], 0
        or      bp, bp
        jnz     .tmo
        inc     word [sl_ntmo]
        mov     al, 5
        jmp     sl_fail

; 04h: write (DS:SI, CX), then read (ES:DI, DX max)
sl_query:
        call    sl_take
        jc      sl_off
        mov     es, [sl_c_ds]
        mov     si, [sl_c_si]
        mov     cx, [sl_c_cx]
        call    sl_send
        jc      sl_wtmo
        mov     es, [sl_c_es]
        mov     di, [sl_c_di]
        mov     cx, [sl_c_dx]
        jmp     sl_rd

; 05h: AL = 60h (RQS, the line complete) while anything waits, else 0
sl_spoll:
        call    sl_take
        jc      sl_off
        call    sl_drain
        xor     ax, ax
        mov     bx, [sl_rhead]
        cmp     bx, [sl_rtail]
        jne     .y
        cmp     word [sl_left], 0
        je      .n
.y:     mov     al, 60h
.n:     jmp     sl_done

; 06h: drop what waits (a half-read frame too)
sl_clear:
        cli
        mov     ax, [sl_rhead]
        mov     [sl_rtail], ax
        sti
        xor     ax, ax
        mov     [sl_left], ax
        mov     [sl_latch], al
        jmp     sl_done

; 0Ah: BX = ms a byte (0: 2000) -> AX = the old
sl_timeout:
        mov     ax, [sl_tdata]
        mov     dx, 55
        mul     dx
        push    ax
        mov     ax, [sl_c_bx]
        or      ax, ax
        jnz     .c
        mov     ax, gp_T_DEF * 55
.c:     add     ax, 54
        jnc     .d
        mov     ax, 0FFFFh
.d:     xor     dx, dx
        mov     cx, 55
        div     cx
        cmp     ax, 2
        jae     .s
        mov     ax, 2
.s:     mov     [sl_tdata], ax
        pop     ax
        jmp     sl_done

; 0Bh: AX = 1 if anything came since the last call
sl_srq: cmp     byte [sl_mine], 0
        je      .z
        call    sl_drain
.z:     xor     ax, ax
        xchg    al, [sl_latch]
        jmp     sl_done

; 0Ch: AX = overruns, CX = timeouts, DX = 0
sl_stats:
        mov     ax, [sl_novr]
        mov     cx, [sl_ntmo]
        mov     word [sl_c_dx], 0
        jmp     sl_done_dx

; 0Eh: none (pre-interrupt style: the caller polls)
sl_irqf:
        xor     ax, ax
        xor     cx, cx
        mov     [sl_c_dx], ax
        jmp     sl_done_dx

; 0Fh (start-up's SERLINK=): AL = 0 off, 1 COM1, 2 COM2; BX = the
; divisor (115200 / baud; 0: as it is).  Taken at the next call
sl_config:
        mov     al, [sl_c_al]
        cmp     al, 2
        ja      .x
        call    sl_let                  ; (a port we had: back to its owner)
        mov     [sl_port], al
        mov     word [sl_base], 3F8h
        cmp     al, 1
        je      .d
        mov     word [sl_base], 2F8h
.d:     mov     bx, [sl_c_bx]
        or      bx, bx
        jz      .x
        mov     [sl_div], bx
.x:     xor     ax, ax
        jmp     sl_done

; ---- the port ------------------------------------------------------
; CF if the link is off; else the port ours (set up again if anything
; changed it: its IRQ's vector, the line's divisor)
sl_take:
        cmp     byte [sl_port], 0
        jne     .on
        stc
        ret
.on:    push    es
        push    0
        pop     es
        mov     bx, 3 * 4 + 8 * 4       ; (COM2: INT 0Bh)
        cmp     byte [sl_port], 2
        je      .v
        mov     bx, 4 * 4 + 8 * 4       ; (COM1: INT 0Ch)
.v:     cmp     byte [sl_mine], 0
        je      .set
        cmp     word [es:bx], sl_isr
        jne     .set
        mov     ax, cs
        cmp     [es:bx + 2], ax
        jne     .set
        mov     dx, [sl_base]           ; the divisor still ours?
        add     dx, 3
        in      al, dx
        test    al, 80h
        jnz     .set
        cmp     al, 03h
        jne     .set
        pop     es
        clc
        ret
.set:   cli
        cmp     word [es:bx], sl_isr    ; the vector found (not our own)
        jne     .keep
        mov     ax, cs
        cmp     [es:bx + 2], ax
        je      .ours
.keep:  mov     ax, [es:bx]
        mov     [sl_oldirq], ax
        mov     ax, [es:bx + 2]
        mov     [sl_oldirq + 2], ax
        mov     word [es:bx], sl_isr
        mov     [es:bx + 2], cs
.ours:  pop     es
        mov     dx, [sl_base]
        inc     dx
        xor     al, al
        out     dx, al                  ; IER: none, for now
        add     dx, 2
        mov     al, 80h
        out     dx, al                  ; LCR: the divisor
        mov     dx, [sl_base]
        mov     ax, [sl_div]
        out     dx, al
        inc     dx
        mov     al, ah
        out     dx, al
        add     dx, 2
        mov     al, 03h                 ; 8N1
        out     dx, al
        dec     dx
        mov     al, 07h                 ; FCR: the FIFO if any, 1 byte
        out     dx, al
        add     dx, 2
        mov     al, 0Bh                 ; MCR: DTR, RTS, OUT2 (the IRQ's gate)
        out     dx, al
        mov     dx, [sl_base]           ; what was waiting: dropped
        mov     cx, 32
.dr:    add     dx, 5
        in      al, dx
        sub     dx, 5
        test    al, 1
        jz      .de
        in      al, dx
        loop    .dr
.de:    inc     dx
        mov     al, 01h                 ; IER: data in
        out     dx, al
        mov     ah, 08h                 ; the IRQ unmasked (3: 08h, 4: 10h)
        cmp     byte [sl_port], 2
        je      .m
        mov     ah, 10h
.m:     not     ah
        in      al, 21h
        and     al, ah
        out     21h, al
        mov     byte [sl_mine], 1
        mov     ax, [sl_rhead]
        mov     [sl_rtail], ax
        mov     word [sl_left], 0
        sti
        clc
        ret

; the port given back (its IRQ's vector as found, the UART quiet): when
; SERLINK= moves it.  AX kept
sl_let: cmp     byte [sl_mine], 0
        je      .x
        push    ax
        push    es
        push    0
        pop     es
        mov     bx, 3 * 4 + 8 * 4
        cmp     byte [sl_port], 2
        je      .v
        mov     bx, 4 * 4 + 8 * 4
.v:     cli
        cmp     word [es:bx], sl_isr
        jne     .n
        mov     ax, [sl_oldirq]
        mov     [es:bx], ax
        mov     ax, [sl_oldirq + 2]
        mov     [es:bx + 2], ax
.n:     mov     dx, [sl_base]
        inc     dx
        xor     al, al
        out     dx, al
        sti
        mov     byte [sl_mine], 0
        pop     es
        pop     ax
.x:     ret

; ES:SI, CX bytes out (CF: the UART never took one)
sl_send:
        jcxz    .x
.b:     call    sl_tick
        mov     bx, ax
.w:     mov     dx, [sl_base]
        add     dx, 5
        in      al, dx
        test    al, 20h
        jnz     .go
        call    sl_drain                ; (the echo of a modem, say)
        call    sl_tick
        sub     ax, bx
        cmp     ax, [sl_tdata]
        jb      .w
        stc
        ret
.go:    mov     dx, [sl_base]
        es lodsb
        out     dx, al
        loop    .b
.x:     clc
        ret

; a byte from the ring -> AL, or CF after the timeout.  BX, CX, DX kept
sl_getb:
        push    bx
        push    dx
        call    sl_drain
        mov     bx, [sl_rtail]
        cmp     bx, [sl_rhead]
        jne     .have
        call    sl_tick
        mov     dx, ax
.w:     sti
        call    sl_drain
        mov     bx, [sl_rtail]
        cmp     bx, [sl_rhead]
        jne     .have
        call    sl_tick
        sub     ax, dx
        cmp     ax, [sl_tdata]
        jb      .w
        pop     dx
        pop     bx
        stc
        ret
.have:  mov     al, [sl_ring + bx]
        inc     bx
        and     bx, gp_RMASK
        mov     [sl_rtail], bx
        pop     dx
        pop     bx
        clc
        ret

sl_tick:
        push    ds
        push    0
        pop     ds
        mov     ax, [46Ch]
        pop     ds
        ret

; whatever the UART holds, into the ring (the ISR's, and every wait's and
; poll's).  AX BX DX kept; DS = KSEG
sl_drain:
        push    ax
        push    bx
        push    dx
        pushf
        cli
.l:     mov     dx, [sl_base]
        add     dx, 5
        in      al, dx
        test    al, 2
        jz      .r0
        inc     word [sl_novr]          ; (the UART's own overrun)
.r0:    test    al, 1
        jz      .x
        mov     dx, [sl_base]
        in      al, dx
        mov     bx, [sl_rhead]
        mov     dx, bx
        inc     dx
        and     dx, gp_RMASK
        cmp     dx, [sl_rtail]
        je      .full
        mov     [sl_ring + bx], al
        mov     [sl_rhead], dx
        mov     byte [sl_latch], 1
        jmp     .l
.full:  inc     word [sl_novr]
        jmp     .l
.x:     popf
        pop     dx
        pop     bx
        pop     ax
        ret

; the UART's interrupt: what came, into the ring
sl_isr: push    ax
        push    dx
        push    ds
        push    cs
        pop     ds
.l:     mov     dx, [sl_base]
        add     dx, 2
        in      al, dx                  ; IIR: what is pending
        test    al, 1
        jnz     .e
        and     al, 6
        cmp     al, 4
        jne     .o
        call    sl_drain
        jmp     .l
.o:     mov     dx, [sl_base]           ; line or modem status, or the
        add     dx, 5                   ;  transmitter: read, so it clears
        in      al, dx
        inc     dx
        in      al, dx
        jmp     .l
.e:     mov     al, 20h
        out     20h, al
        pop     ds
        pop     dx
        pop     ax
        iret

; ---- start-up ------------------------------------------------------
section ovl
; INT 60h ours (the port is taken at the link's first call)
gpib_init:
        push    es
        push    0
        pop     es
        cli
        mov     word [es:60h*4], gp_entry
        mov     [es:60h*4+2], cs
        sti
        pop     es
        mov     byte [gp_ok], 1
        ret
section .text
