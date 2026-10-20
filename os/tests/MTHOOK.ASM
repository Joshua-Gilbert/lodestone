; MTHOOK.COM - for test_mt.py: programs hooking INT 08h, each way.
;   MTHOOK      a TSR: AH=35h for the old vector, AH=25h for its own (a
;               handler that does STI and chains with PUSHF / CALL FAR);
;               and INT 62h, a service that does STI and waits 2 ticks
;               (code outside its caller's memory, on the caller's stack)
;   MTHOOK X    a TSR: the old vector read from the vector table itself,
;               its own set with AH=25h
;   MTHOOK Y    the vector table written itself, for 5 ticks; then AH=25h
;               with the vector it read there; it ends
;   MTHOOK Z    AH=35h for the old vector, the vector table written itself
;               for 5 ticks, then what AH=35h gave written back there; it
;               ends
; (With multitasking on, AH=25h and 35h for INT 08h are MT's: a handler
; set so goes inside mt_tick, not ahead of it.)  The old vector it chains
; to is at its PSP:0102h.
; nasm -f bin -o MTHOOK.COM MTHOOK.ASM
cpu 286
org 100h
        jmp     init
old     dd      0
h:      sti
        pushf
        call    far [cs:old]
        iret
h62:    sti                             ; INT 62h: 2 ticks here
        push    ds
        push    ax
        push    40h
        pop     ds
        push    bx
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
        xor     bx, bx
        mov     es, bx
        cmp     al, 'X'
        je      tx
        cmp     al, 'Y'
        je      ty
        cmp     al, 'Z'
        je      tz
        mov     ax, 3508h               ; (MTHOOK)
        int     21h
        mov     [old], bx
        mov     [old + 2], es
        mov     ax, 2508h
        mov     dx, h
        int     21h
        mov     ax, 2562h
        mov     dx, h62
        int     21h
stay:   mov     dx, (init - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
tx:     call    rdvec                   ; (X)
        mov     ax, 2508h
        mov     dx, h
        int     21h
        jmp     stay
ty:     call    rdvec                   ; (Y)
        call    wrhook
        call    wait5
        push    ds
        mov     ax, 2508h
        lds     dx, [old]
        int     21h
        pop     ds
        jmp     quit
tz:     mov     ax, 3508h               ; (Z)
        int     21h
        mov     [old], bx
        mov     [old + 2], es
        xor     bx, bx
        mov     es, bx
        call    wrhook
        call    wait5
        cli
        mov     ax, [old]
        mov     [es:8 * 4], ax
        mov     ax, [old + 2]
        mov     [es:8 * 4 + 2], ax
        sti
quit:   mov     ax, 4C00h
        int     21h

rdvec:  mov     ax, [es:8 * 4]          ; ES = 0
        mov     [old], ax
        mov     ax, [es:8 * 4 + 2]
        mov     [old + 2], ax
        ret
wrhook: cli                             ; ES = 0
        mov     word [es:8 * 4], h
        mov     [es:8 * 4 + 2], cs
        sti
        ret
wait5:  push    es
        push    40h
        pop     es
        mov     bx, [es:6Ch]
.w:     mov     ax, [es:6Ch]
        sub     ax, bx
        cmp     ax, 5
        jb      .w
        pop     es
        ret
