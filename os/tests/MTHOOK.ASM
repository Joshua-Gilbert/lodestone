; MTHOOK.COM - for test_mt.py: a TSR hooking INT 08h the common way:
; AH=35h for the old vector, AH=25h for its own, a handler that does STI
; and chains with PUSHF / CALL FAR.  (With multitasking on, AH=25h and 35h
; for INT 08h are MT's: the handler goes inside mt_tick, not ahead of it.)
; The old vector it got is at its PSP:0102h.
; nasm -f bin -o MTHOOK.COM MTHOOK.ASM
cpu 286
org 100h
        jmp     init
old     dd      0
h:      sti
        pushf
        call    far [cs:old]
        iret
init:   mov     ax, 3508h
        int     21h
        mov     [old], bx
        mov     [old + 2], es
        mov     ax, 2508h
        mov     dx, h
        int     21h
        mov     dx, (init - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
