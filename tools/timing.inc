; PIT timing + number printing (GPIBTEST 1.0)
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

