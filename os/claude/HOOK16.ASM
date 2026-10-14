; HOOK16.COM - a TSR whose INT 16h hook only passes every call on, as a
; keyboard TSR loaded after CLAUDE /R would sit: INT 16h is then its, and
; resident Claude's stub is further down the chain.  (For CLAUDE.COM: it
; must still find the stub, and turn its hot key off while it runs.)
cpu 286
org 100h
        jmp     init
old16   dd      0
h16:    jmp     far [cs:old16]
init:   mov     ax, 3516h
        int     21h
        mov     [old16], bx
        mov     [old16 + 2], es
        mov     dx, h16
        mov     ax, 2516h
        int     21h
        mov     dx, s_ok
        mov     ah, 9
        int     21h
        mov     dx, (init - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
s_ok    db      'HOOK16 resident: INT 16h passed on', 13, 10, '$'
