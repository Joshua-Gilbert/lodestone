; VHOOK.COM - for test_mt.py: stays resident, hooking INT 10h as a driver
; loaded after multitasking does (below A000h): PUSHF / CALL FAR to what
; was there, then IRET.
;   VHOOK T  INT 08h too, chained first (PUSHF / CALL FAR: the BIOS's EOI
;            done, interrupts off), then a 'T' in 70h at row 0, column 70
;            of the page shown through INT 10h 13h: a TSR's clock, its
;            code no task's
; nasm -f bin -o VHOOK.COM VHOOK.ASM
cpu 286
org 100h
        jmp     init
h10:    pushf
        call    far [cs:o10]
        iret
h08:    pushf
        call    far [cs:o08]
        pusha
        push    es
        push    cs
        pop     es
        mov     ax, 1300h
        mov     bx, 0070h
        mov     cx, 1
        mov     dx, 0046h
        mov     bp, tch
        int     10h
        pop     es
        popa
        iret
o10     dd      0
o08     dd      0
tch     db      'T'
init:   mov     ax, 3510h
        int     21h
        mov     [o10], bx
        mov     [o10 + 2], es
        mov     ax, 2510h
        mov     dx, h10
        int     21h
        mov     si, 81h
.b:     lodsb
        cmp     al, ' '
        je      .b
        and     al, 0DFh
        cmp     al, 'T'
        jne     .k
        mov     ax, 3508h
        int     21h
        mov     [o08], bx
        mov     [o08 + 2], es
        mov     ax, 2508h
        mov     dx, h08
        int     21h
.k:     mov     ax, 3100h
        mov     dx, (init - $$ + 100h + 15) / 16
        int     21h
