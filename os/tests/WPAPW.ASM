; WPAPW.COM (test_kernel t_wpfail, test_hd): K.TXT opened, 600 bytes appended, closed;
; its own INT 24h answers Fail
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, name
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     bx, ax
        push    ax
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        pop     bx
        mov     cx, 600
        mov     dx, 100h
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h
h24:    mov     al, 3
        iret
name    db 'K.TXT', 0
