; WPRNM.COM (test_kernel t_wpfail): K.TXT renamed SUB\K2.TXT, "+" or "-"; its own
; INT 24h answers Fail
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, old
        mov     di, new
        mov     ah, 56h
        int     21h
        mov     dl, '+'
        jnc     .o
        mov     dl, '-'
.o:     mov     ah, 2
        int     21h
        mov     ax, 4C00h
        int     21h
h24:    mov     al, 3
        iret
old     db 'K.TXT', 0
new     db 'SUB\K2.TXT', 0
