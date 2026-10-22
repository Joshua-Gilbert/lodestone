; MTLINE.COM - for test_mt.py: MTLINE FILE: a prompt, a line read with
; INT 21h AH=0Ah (the kernel's line editor: it waits in kbd_get), and the
; line written to FILE.  A line "=n" ends it with exit code n.
; nasm -f bin -o MTLINE.COM MTLINE.ASM
cpu 286
org 100h
        mov     si, 81h                 ; the file's name: the first word
.b:     lodsb
        cmp     al, ' '
        je      .b
        dec     si
        mov     di, fname
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        stosb
        jmp     .n
.ne:    mov     byte [di], 0
        mov     dx, s_pr
        mov     ah, 9
        int     21h
        mov     ah, 0Ah
        mov     dx, line
        int     21h
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .x
        xchg    bx, ax
        mov     ah, 40h
        mov     cl, [line + 1]
        xor     ch, ch
        mov     dx, line + 2
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     xor     ax, ax                  ; a line "=n": exit code n (WAIT)
        mov     si, line + 2
        cmp     byte [si], '='
        jne     .q
        inc     si
.d:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .q
        mov     bh, 10
        mul     bh
        add     al, bl
        inc     si
        jmp     .d
.q:     mov     ah, 4Ch
        int     21h

s_pr    db      13, 10, 'MTLINE> $'
line    db      60, 0
        times   62 db 0
fname   times   80 db 0
