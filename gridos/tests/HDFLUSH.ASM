; HDFLUSH.COM - for test_hd.py: A:\F.DAT and C:\X.DAT written in turns
; (both drives' FATs changed at once), INT 21h 0Dh, then both closed.
; Prints "flush ok" or "flush failed", then "X closed ok" or "X close
; failed".  (When C:'s FAT can't be written, A:'s must be all the same.)
cpu 286
org 100h
        mov     dx, nf
        call    make
        mov     [hf], ax
        mov     cx, 8
        call    wr
        mov     dx, nx
        call    make
        mov     [hx], ax
        mov     cx, 16
        call    wr
        mov     bx, [hf]
        mov     cx, 16
        call    wr
        mov     ah, 0Dh
        int     21h
        mov     dx, sfl
        cmp     al, 0FFh
        je      .f
        mov     dx, sfo
.f:     call    say
        mov     ah, 3Eh
        mov     bx, [hf]
        int     21h
        mov     ah, 3Eh
        mov     bx, [hx]
        int     21h
        mov     dx, sxo
        jnc     .p
        mov     dx, sxf
.p:     call    say
        mov     ax, 4C00h
        int     21h
make:   mov     ah, 3Ch
        xor     cx, cx
        int     21h
        mov     bx, ax
        jnc     .x
        mov     dx, sno
        call    say
        mov     ax, 4C01h
        int     21h
.x:     ret
wr:     push    cx
        mov     ah, 40h
        mov     cx, 512
        mov     dx, buf
        int     21h
        pop     cx
        loop    wr
        ret
say:    mov     ah, 9
        int     21h
        ret
nf      db 'A:\F.DAT', 0
nx      db 'C:\X.DAT', 0
sfo     db 'flush ok', 13, 10, '$'
sfl     db 'flush failed', 13, 10, '$'
sxo     db 'X closed ok', 13, 10, '$'
sxf     db 'X close failed', 13, 10, '$'
sno     db 'not made', 13, 10, '$'
hf      dw 0
hx      dw 0
buf     times 512 db 'f'
