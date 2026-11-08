; WPDRSTE.COM (test_kernel t_wpfail): E.TXT made, 600 bytes written (A), a key, INT 21h
; 0Dh (Z), a key, 600 more (B), closed (C); its own INT 24h answers Fail.  Each "x+" or "x-n"
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, ename
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
        mov     [h], ax
        mov     dl, 'A'
        call    wr
        mov     ah, 8
        int     21h
        mov     ah, 0Dh
        int     21h
        mov     dl, 'Z'
        call    st
        mov     ah, 8
        int     21h
        mov     dl, 'B'
        call    wr
        mov     bx, [h]
        mov     ah, 3Eh
        int     21h
        mov     dl, 'C'
        call    st
.x:     mov     ax, 4C00h
        int     21h
wr:     push    dx
        mov     bx, [h]
        mov     cx, 600
        mov     dx, data
        mov     ah, 40h
        int     21h
        pop     dx
st:     pushf
        push    ax
        mov     ah, 2
        int     21h
        pop     ax
        popf
        mov     dl, '+'
        jnc     .o
        mov     dl, '-'
        add     al, '0'
        push    ax
        mov     ah, 2
        mov     dl, '-'
        int     21h
        pop     ax
        mov     dl, al
.o:     mov     ah, 2
        int     21h
        mov     dl, ' '
        int     21h
        ret
h24:    mov     al, 3
        iret
name    db 'K.TXT', 0
ename   db 'E.TXT', 0
h       dw 0
data    times 600 db 'w'
