; M33GFX.COM - the graphics pointer, step by step (tests/test_apps.py
; compares each picture with the masks): mode 40h with hot spot (5, 7) at
; three places, mode 6 near a corner, mode 4 with the hot spot.  The
; reset and the shape are asked for with DF set.
        org     100h
        cpu     286
        mov     ax, 0040h
        int     10h
        std
        mov     ax, 0
        int     33h
        call    shape
        cld
        xor     cx, cx
        xor     dx, dx
        call    showat
        mov     cx, 639
        mov     dx, 399
        call    showat
        mov     cx, 333
        mov     dx, 201
        call    showat
        mov     ax, 0006h
        int     10h
        mov     ax, 0
        int     33h
        mov     cx, 630
        mov     dx, 190
        call    showat
        mov     ax, 0004h
        int     10h
        mov     ax, 0
        int     33h
        call    shape
        mov     cx, 101
        mov     dx, 50
        call    showat
        mov     ax, 0003h
        int     10h
        mov     ax, 4C00h
        int     21h

shape:  mov     ax, 9                   ; the arrow, hot spot (5, 7)
        mov     bx, 5
        mov     cx, 7
        push    cs
        pop     es
        mov     dx, arrow
        int     33h
        ret

; the pointer at CX, DX; a key; hidden again
showat: mov     ax, 4
        int     33h
        mov     ax, 1
        int     33h
        mov     ah, 0
        int     16h
        mov     ax, 2
        int     33h
        ret

arrow:  dw 3FFFh, 1FFFh, 0FFFh, 07FFh, 03FFh, 01FFh, 00FFh, 007Fh
        dw 003Fh, 001Fh, 01FFh, 10FFh, 30FFh, 0F87Fh, 0F87Fh, 0FC7Fh
        dw 0000h, 4000h, 6000h, 7000h, 7800h, 7C00h, 7E00h, 7F00h
        dw 7F80h, 7C00h, 6C00h, 4600h, 0600h, 0300h, 0300h, 0000h
