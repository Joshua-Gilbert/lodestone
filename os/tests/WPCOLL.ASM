; WPCOLL.COM (test_kernel t_wpfail): K.TXT open, 600 bytes appended (A), a
; key (the tab goes on), Z.TXT created (Z: fails, its own INT 24h Fail), a
; key (the tab off), 600 more (B), closed (C).  Each "x+" or "x-n"
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, name
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     [h], ax
        mov     bx, ax
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        mov     dl, 'A'
        call    wr
        mov     ah, 8
        int     21h
        mov     dx, zname
        xor     cx, cx
        mov     ah, 3Ch
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
zname   db 'Z.TXT', 0
h       dw 0
data    times 600 db 'w'
