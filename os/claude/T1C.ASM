; T1C.COM - a TSR whose INT 1Ch handler looks at the keyboard (INT 16h
; AH=01h) 18 times a second, as some pop-up and clock TSRs do.  The BIOS's
; INT 08h calls INT 1Ch before its EOI, so that INT 16h call comes with the
; timer's IRQ in service.  (For resident Claude: CODE-\ must not bring the
; console up there, where the keyboard's IRQ can't come.)
cpu 286
org 100h
        jmp     init
old1c   dd      0
h1c:    push    ax
        mov     ah, 1
        int     16h
        pop     ax
        jmp     far [cs:old1c]
init:   mov     ax, 351Ch
        int     21h
        mov     [old1c], bx
        mov     [old1c + 2], es
        mov     dx, h1c
        mov     ax, 251Ch
        int     21h
        mov     dx, s_ok
        mov     ah, 9
        int     21h
        mov     dx, (init - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
s_ok    db      'T1C resident: INT 1Ch looks at the keyboard', 13, 10, '$'
