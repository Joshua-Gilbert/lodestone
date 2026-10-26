; KEYIN.COM - for test_claude_window.py and test_mt.py: one key read
; through DOS (INT 21h AH=08h: the kernel's console wait, behind in a
; window MT's mt_kwait), its code the exit code.  With an argument (not
; blanks only: CLAUDE's RUN gives " " for none) it hooks INT 16h first (a
; hook that only goes on, JMP FAR), as CLAUDE's key script does for a RUN,
; and puts it back after
; nasm -f bin -o KEYIN.COM KEYIN.ASM
cpu 286
org 100h
        mov     si, 81h
.s:     lodsb
        cmp     al, ' '
        je      .s
        cmp     al, 0Dh
        je      .r
        mov     byte [hk], 1
        mov     ax, 3516h
        int     21h
        mov     [old], bx
        mov     [old+2], es
        mov     dx, hook
        mov     ax, 2516h
        int     21h
.r:     mov     ah, 8
        int     21h
        push    ax
        cmp     byte [hk], 0
        je      .x
        push    ds
        lds     dx, [old]
        mov     ax, 2516h
        int     21h
        pop     ds
.x:     pop     ax
        mov     ah, 4Ch
        int     21h
hook:   jmp     far [cs:old]
old:    dd      0
hk:     db      0
