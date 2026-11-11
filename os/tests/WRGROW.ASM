; WRGROW.COM: C:\README.TXT (21 bytes, one 2 KB cluster) opened read and write, to its end, 1,003 bytes written
; there in one call (to byte 1,024: 491 into its first sector, then its second whole; no cluster to take), this
; handler answering Fail at INT 24h.  Then what the write said (W+ or W-, AX), the position (P) and the size
; (S: 4202h's), and the file closed (test_hd t_fatwrite: the second sector won't take the write)
org 100h
start:
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     ax, 3D02h
        mov     dx, name
        int     21h
        jc      x
        mov     bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        mov     ah, 40h
        mov     cx, 1003
        mov     dx, buf
        int     21h
        mov     dl, '+'
        jnc     .w
        mov     dl, '-'
.w:     push    ax
        push    dx
        mov     dl, 'W'
        call    putc
        pop     dx
        call    putc
        pop     ax
        call    hex4
        mov     ax, 4201h
        xor     cx, cx
        xor     dx, dx
        int     21h
        push    ax
        mov     dl, 'P'
        call    spc
        pop     ax
        call    hex4
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        push    ax
        mov     dl, 'S'
        call    spc
        pop     ax
        call    hex4
        mov     ah, 3Eh
        int     21h
x:      mov     ax, 4C00h
        int     21h
spc:    push    dx
        mov     dl, ' '
        call    putc
        pop     dx
putc:   push    ax
        mov     ah, 2
        int     21h
        pop     ax
        ret
hex4:   mov     cx, 4
.l:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .d
        add     al, 7
.d:     mov     dl, al
        call    putc
        pop     ax
        loop    .l
        ret
h24:    mov     al, 3
        iret
name    db 'C:\README.TXT', 0
buf     times 1003 db 'w'
