; WPAPPK.COM (test_kernel t_wpfail): K.TXT opened, 600 bytes appended (a
; cluster taken), closed; its own INT 24h answers Fail.  Status: "W+"/"W-"
; for the write, "C+"/"C-" for the close
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
        mov     bx, [h]
        mov     cx, 600
        mov     dx, data
        mov     ah, 40h
        int     21h
        mov     dl, 'W'
        call    st
        mov     bx, [h]
        mov     ah, 3Eh
        int     21h
        mov     dl, 'C'
        call    st
.x:     mov     ax, 4C00h
        int     21h
st:     pushf
        push    ax
        mov     ah, 2
        int     21h
        pop     ax
        popf
        mov     dl, '+'
        jnc     .o
        mov     dl, '-'
.o:     mov     ah, 2
        int     21h
        mov     dl, ' '
        int     21h
        ret
h24:    mov     al, 3
        iret
name    db 'K.TXT', 0
h       dw 0
data    times 600 db 'w'
