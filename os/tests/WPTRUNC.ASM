; WPTRUNC.COM (test_kernel t_wpfail): K.TXT opened, cut at 100 bytes (a write
; of 0 bytes there), closed; its own INT 24h answers Fail.  Status: "T+"/"T-"
; for the cut, "C+"/"C-" for the close
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
        mov     dx, 100
        mov     ax, 4200h
        int     21h
        mov     bx, [h]
        xor     cx, cx
        mov     ah, 40h
        int     21h
        mov     dl, 'T'
        call    st
        mov     bx, [h]
        mov     ah, 3Eh
        int     21h
        mov     dl, 'C'
        call    st
.x:     mov     ax, 4C00h
        int     21h
st:     pushf
        mov     ah, 2
        int     21h
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
