; MTCWD.COM - for test_mt.py: MTCWD DIR FILE: change the current directory
; to DIR (INT 21h AH=3Bh), wait for a key (AH=08h: in kbd_get, so other
; tasks run and change theirs), then write the current directory of the
; current drive (AH=47h) to FILE.
; nasm -f bin -o MTCWD.COM MTCWD.ASM
cpu 286
org 100h
        mov     si, 81h
        mov     di, dir
        call    word_
        mov     di, fname
        call    word_
        mov     ah, 3Bh
        mov     dx, dir
        int     21h
        mov     ah, 8
        int     21h
        mov     ah, 47h
        xor     dl, dl
        mov     si, cwdb + 1
        int     21h
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .x
        xchg    bx, ax
        mov     di, cwdb                 ; "\" and the directory
        xor     al, al
        mov     cx, 70
        repne   scasb
        mov     cx, di
        sub     cx, cwdb + 1
        mov     ah, 40h
        mov     dx, cwdb
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

word_:  lodsb                           ; a word of the tail to DI, ASCIIZ
        cmp     al, ' '
        je      word_
        dec     si
.c:     lodsb
        cmp     al, ' '
        jbe     .e
        stosb
        jmp     .c
.e:     dec     si
        mov     byte [di], 0
        ret

dir     times   70 db 0
fname   times   70 db 0
cwdb     db      '\'
        times   70 db 0
