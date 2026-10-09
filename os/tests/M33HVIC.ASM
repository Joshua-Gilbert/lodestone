; M33HVIC.COM - after M33HSET.COM: waits for a key (the test moves the
; mouse meanwhile), then prints how often the old handler's address in
; this program was called: "hits: 0000" when nothing reached it
        org     100h
        cpu     286
        mov     ah, 0
        int     16h
        mov     dx, msg
        mov     ah, 9
        int     21h
        mov     ax, [hits]
        mov     cx, 4
.d:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        int     21h
        pop     ax
        loop    .d
        mov     dx, crlf
        mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h
msg     db 'hits: $'
crlf    db 13, 10, '$'
        times   200h - ($ - $$) db 0
victim:
        inc     word [cs:hits]
        retf
hits    dw 0
