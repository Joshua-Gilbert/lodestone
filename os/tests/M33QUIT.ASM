; M33QUIT.COM - a "move the mouse to quit" program: its INT 33h event
; handler ends the program (tests/test_apps.py, t_mouse)
        org     100h
        cpu     286
        mov     ax, 0
        int     33h
        mov     ax, 0Ch
        mov     cx, 1Fh
        push    cs
        pop     es
        mov     dx, handler
        int     33h
        mov     ah, 0                   ; (the test moves the mouse)
        int     16h
        mov     ax, 4C00h
        int     21h
handler:
        mov     ax, 4C01h               ; ends inside the handler
        int     21h
