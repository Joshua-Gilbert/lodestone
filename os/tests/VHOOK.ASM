; VHOOK.COM - for test_mt.py: stays resident, hooking INT 10h as a driver
; loaded after multitasking does (below A000h): PUSHF / CALL FAR to what
; was there, then IRET.
;   VHOOK T  INT 08h too, chained first (PUSHF / CALL FAR: the BIOS's EOI
;            done, interrupts off), then a digit in 70h at row 0, column 70
;            of the page shown through INT 10h 13h, one more each tick (0-9
;            round): a TSR's clock, its code no task's
; nasm -f bin -o VHOOK.COM VHOOK.ASM
cpu 286
org 100h
%include "MTLIB.INC"
        jmp     init
h10:    pushf
        call    far [cs:o10]
        iret
h08:    pushf
        call    far [cs:o08]
        pusha
        push    es
        inc     byte [cs:tch]
        cmp     byte [cs:tch], '9'
        jbe     .d
        mov     byte [cs:tch], '0'
.d:     push    cs
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
tch     db      '0'
init:   HOOK    10h, o10, h10
        mov     si, 81h
.b:     lodsb
        cmp     al, ' '
        je      .b
        and     al, 0DFh
        cmp     al, 'T'
        jne     .k
        HOOK    08h, o08, h08
.k:     mov     ax, 3100h
        mov     dx, (init - $$ + 100h + 15) / 16
        int     21h
