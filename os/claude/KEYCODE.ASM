; KEYCODE.COM - shows each key as INT 16h AH=10h returns it (hex AX), so a
; hot key's code on the 1520 can be seen.  Esc twice ends.
cpu 286
org 100h
        mov     dx, s_hi
        mov     ah, 9
        int     21h
.k:     mov     ah, 10h
        int     16h
        cmp     ax, 011Bh
        jne     .p
        cmp     [last], ax
        je      .x
.p:     mov     [last], ax
        mov     cx, 4
        mov     bx, ax
.h:     rol     bx, 4
        mov     dl, bl
        and     dl, 15
        add     dl, '0'
        cmp     dl, '9'
        jbe     .o
        add     dl, 7
.o:     mov     ah, 2
        int     21h
        loop    .h
        mov     dl, ' '
        mov     ah, 2
        int     21h
        jmp     .k
.x:     mov     ax, 4C00h
        int     21h
s_hi    db 'Keys as AH=10h gives them (CODE-\ should be 2B00); Esc twice ends', 13, 10, '$'
last    dw 0
