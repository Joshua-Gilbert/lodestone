; MHAND.COM - sets an INT 33h event handler (AX=0Ch, every event) that
; counts its calls, reads keys (INT 16h AH=00h) until Esc, then takes it
; off and says "MHAND: n calls".  (For resident Claude: no calls while its
; console is up, and the handler back afterwards.)
cpu 286
org 100h
        xor     ax, ax                  ; the mouse, reset
        int     33h
        mov     ax, 0Ch
        mov     cx, 1Fh
        push    cs
        pop     es
        mov     dx, handler
        int     33h
.k:     mov     ah, 0
        int     16h
        cmp     al, 27
        jne     .k
        mov     ax, 0Ch
        xor     cx, cx
        int     33h
        mov     dx, s_a
        mov     ah, 9
        int     21h
        mov     ax, [calls]
        mov     bx, 10
        xor     cx, cx
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.o:     pop     dx
        add     dl, '0'
        mov     ah, 2
        int     21h
        loop    .o
        mov     dx, s_b
        mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h
handler:
        inc     word [cs:calls]
        retf
calls   dw      0
s_a     db      'MHAND: $'
s_b     db      ' calls', 13, 10, '$'
