; M33HSET.COM - sets an INT 33h event handler and ends without a reset
; (as a program that crashes or is stopped would).  M33HVIC.COM, loaded
; next at the same segment by the shell, has a counter at the same place.
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
        mov     ax, 4C00h
        int     21h
        times   200h - ($ - $$) db 0
handler:
        inc     word [cs:hits]
        retf
hits    dw 0
