; MTHOOK.COM - for test_mt.py: TSRs.
;   MTHOOK      hooks INT 08h the common way: AH=35h for the old vector
;               (kept at its PSP:0102h), AH=25h for its own, a handler
;               that does STI and chains with PUSHF / CALL FAR
;   MTHOOK S    INT 62h instead: a service that does STI and waits 2
;               ticks (code outside its caller's memory, on the caller's
;               stack)
; nasm -f bin -o MTHOOK.COM MTHOOK.ASM
cpu 286
org 100h
%include "MTLIB.INC"
        jmp     init
old     dd      0
h:      sti
        pushf
        call    far [cs:old]
        iret
h62:    sti                             ; INT 62h: 2 ticks here
        push    ds
        push    ax
        push    bx
        push    40h
        pop     ds
        mov     bx, [6Ch]
.w:     mov     ax, [6Ch]
        sub     ax, bx
        cmp     ax, 2
        jb      .w
        pop     bx
        pop     ax
        pop     ds
        iret
init:   mov     si, 81h
.b:     lodsb
        cmp     al, ' '
        je      .b
        and     al, 0DFh
        cmp     al, 'S'
        je      .s
        HOOK    08h, old, h
        jmp     .t
.s:     mov     ax, 2562h
        mov     dx, h62
        int     21h
.t:     mov     dx, (init - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
