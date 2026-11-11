; WPDSLOT.COM (test_kernel t_wpfail): SUB\NEW.TXT created (SUB full: its directory grows)
org 100h
        mov     dx, name
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h
name    db 'SUB\NEW.TXT', 0
