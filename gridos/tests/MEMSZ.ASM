; MEMSZ.COM - prints the memory this program got (PSP:2 - PSP), in KB
;   nasm -f bin -o MEMSZ.COM MEMSZ.ASM
org 100h
        mov     ax, [2]
        mov     bx, cs
        sub     ax, bx          ; paragraphs this program got
        mov     bx, 10
        mul     bx
        mov     cx, 6
.s:     shr     dx, 1
        rcr     ax, 1
        loop    .s              ; tenths of KB
        xor     dx, dx
        div     bx
        push    dx
        call    pnum
        mov     dl, '.'
        mov     ah, 2
        int     21h
        pop     dx
        add     dl, '0'
        mov     ah, 2
        int     21h
        mov     dx, s
        mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h
pnum:   xor     cx, cx
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     dx
        add     dl, '0'
        mov     ah, 2
        int     21h
        loop    .p
        ret
s       db ' KB for programs', 13, 10, '$'
