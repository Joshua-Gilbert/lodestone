; KEYIN.COM - for test_claude_window.py: one key read through DOS (INT
; 21h AH=08h: the kernel's console wait, behind in a window MT's
; mt_kwait), its code the exit code
; nasm -f bin -o KEYIN.COM KEYIN.ASM
cpu 286
org 100h
        mov     ah, 8
        int     21h
        mov     ah, 4Ch
        int     21h
