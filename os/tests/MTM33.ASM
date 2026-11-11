; MTM33.COM - for test_mt.py: each task's own INT 33h state (KMT's
; mt_i33).
;   MTM33 MODE FILE
;   F  INT 33h reset, an event handler of its own (every event), the
;      pointer on, then keys through DOS (AH=08h, where it can be switched
;      from) until "q": FILE gets "cccc xxxx yyyy", its handler's calls
;      and the position (03h)
;   B  as F, the position set to (200, 96) first, and FILE written at
;      once too (before the keys)
;   H  reset, an event handler of its own, swapped for itself (14h), FILE
;      written (as F), and ends without taking the handler away
;   X  runs MTM33 H as a child (EXEC, its FILE H.TXT), then waits for "q"
;      as F (no reset nor handler of its own: its calls 0) and writes FILE
;   T  reset, the position set to (200, 96), then for 18 ticks an INT 1Ch
;      handler of its own asks for the position (03h, with the timer's
;      interrupt in service): FILE gets "nnnn kkkk xxxx", the handler's
;      calls, how many of them were given (200, 96), and the position's
;      x its own code is given then
;   G  sets mode 40h, waits 18 ticks (to be sent behind meanwhile), resets
;      the mouse, writes FILE as F (its ranges: mode 40h's), then waits for
;      "q" and ends
;   D  stays resident as another INT 33h driver (not chaining): it counts
;      AX=1 up and AX=2 down, in the word before its handler, and its
;      AX=2 calls in the word before that
;   J  stays resident as a hook on INT 33h that jumps on (JMP FAR) to the
;      one there before
;   P  reset, the pointer on, 36 ticks (a click given meanwhile, or later,
;      while it polls), then polls 03h without a pause until the left
;      button is down, then until it is up (TM5000G polls 03h too, less
;      hard): FILE gets "x y x y p r", where it was down,
;      where up, and the left button's presses and releases (05h, 06h)
;   R  as P, but polls 06h (the left button's releases) until one comes:
;      FILE gets "n x y", how many and where the last was
; nasm -f bin -o MTM33.COM MTM33.ASM
cpu 286
org 100h
%include "MTLIB.INC"
        mov     sp, stk_top
        mov     si, 81h
        call    blanks
        lodsb
        and     al, 0DFh
        mov     [mode], al
        call    blanks
        mov     di, fname
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        stosb
        jmp     .n
.ne:    mov     byte [di], 0
        mov     ah, 4Ah                 ; only what it needs (X's child)
        mov     bx, (the_end - $$ + 100h + 15) / 16
        int     21h
        push    cs
        pop     es
        cmp     byte [mode], 'X'
        je      .x
        cmp     byte [mode], 'D'
        je      .d
        cmp     byte [mode], 'J'
        je      .j
        cmp     byte [mode], 'P'
        je      .pp
        cmp     byte [mode], 'R'
        je      .pp
        cmp     byte [mode], 'G'
        jne     .r0
        mov     ax, 0040h               ; G: mode 40h, a while, then the reset
        int     10h
        call    w18
        xor     ax, ax
        int     33h
        call    rec
        jmp     .k
.d:     mov     ax, 2533h               ; D: INT 33h its own, resident
        mov     dx, d33
        int     21h
        mov     dx, (the_end - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
.j:     HOOK    33h, jold, j33   ; J: a hook on INT 33h, resident
        mov     dx, (the_end - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
.r0:    xor     ax, ax                  ; reset
        int     33h
        cmp     byte [mode], 'T'
        je      .pos
        mov     ax, 0Ch                 ; its event handler: every event
        mov     cx, 7Fh
        mov     dx, hand
        int     33h
        cmp     byte [mode], 'H'
        jne     .nh
        mov     ax, 14h                 ; H: swapped for itself
        mov     cx, 7Fh
        mov     dx, hand
        int     33h
        call    rec
        jmp     .end
.nh:    cmp     byte [mode], 'B'
        jne     .on
.pos:   mov     ax, 4                   ; B, T: the position (200, 96)
        mov     cx, 200
        mov     dx, 96
        int     33h
        cmp     byte [mode], 'T'
        je      .t
.on:    mov     ax, 1                   ; the pointer on
        int     33h
        cmp     byte [mode], 'B'
        jne     .k
        call    rec                     ; B: FILE now
.k:     mov     ah, 8                   ; keys until "q"
        int     21h
        cmp     al, 'q'
        jne     .k
        call    rec
.end:   mov     ax, 4C00h
        int     21h
.x:     mov     dx, child               ; X: MTM33 H, as a child
        mov     bx, pblk
        mov     [pblk + 4], cs
        mov     [pblk + 8], cs
        mov     [pblk + 12], cs
        mov     ax, 4B00h
        int     21h
        push    cs
        pop     es
        mov     word [cnt], 0
        jmp     .k
.pp:    xor     ax, ax                  ; P: reset, on, a while, then polls
        int     33h
        mov     ax, 1
        int     33h
        call    w18
        call    w18
        cmp     byte [mode], 'R'
        je      .r1
        mov     di, pv
.p1:    mov     ax, 3
        int     33h
        test    bl, 1
        jz      .p1
        xchg    ax, cx
        stosw
        xchg    ax, dx
        stosw
.p2:    mov     ax, 3
        int     33h
        test    bl, 1
        jnz     .p2
        xchg    ax, cx
        stosw
        xchg    ax, dx
        stosw
        mov     ax, 5
        xor     bx, bx
        int     33h
        xchg    ax, bx
        stosw
        mov     ax, 6
        xor     bx, bx
        int     33h
        xchg    ax, bx
        stosw
        mov     si, pv
        mov     di, out_
        mov     bp, 6
.pw:    lodsw
        call    hex4
        mov     al, ' '
        stosb
        dec     bp
        jnz     .pw
        dec     di
        call    wout
        jmp     .end
.r1:    mov     ax, 6                   ; R: 06h only, till a release
        xor     bx, bx
        int     33h
        or      bx, bx
        jz      .r1
        xchg    ax, bx
        mov     bx, cx
        mov     cx, dx
        call    rec3
        jmp     .end
.t:     HOOK    1Ch, o1c, h1c   ; T: its INT 1Ch handler
        call    w18
        UNHOOK  1Ch, o1c
        push    cs
        pop     es
        mov     ax, 3
        int     33h
        mov     ax, [t_n]
        mov     bx, [t_k]
        call    rec3
        jmp     .end

; FILE: the handler's calls, then the position (03h)
rec:    mov     ax, 3
        int     33h
        mov     ax, [cnt]
        mov     bx, cx
        mov     cx, dx
; FILE: AX, BX, CX as "aaaa bbbb cccc" (ES = CS)
rec3:   push    cx
        push    bx
        mov     di, out_
        call    hex4
        mov     al, ' '
        stosb
        pop     ax
        call    hex4
        mov     al, ' '
        stosb
        pop     ax
        call    hex4
; FILE: out_ to DI
wout:   mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .x
        xchg    bx, ax
        mov     ah, 40h
        mov     cx, di
        mov     dx, out_
        sub     cx, dx
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret

; 18 ticks, with HLT.  AX, DX changed
        TICKS   w18, 18

; D's INT 33h: show count (AX=1 up, AX=2 down), and AX=2's calls
d2cnt   dw      0
dcnt    dw      0
d33:    cmp     ax, 1
        jne     .h
        inc     word [cs:dcnt]
        iret
.h:     cmp     ax, 2
        jne     .r
        dec     word [cs:dcnt]
        inc     word [cs:d2cnt]
.r:     iret

; J's INT 33h: on to the one before, the caller's frame as it is
j33:    jmp     far [cs:jold]
jold    dd      0

; the event handler: counts its calls
hand:   inc     word [cs:cnt]
        retf

; T's INT 1Ch handler: asks for the position; counts the answers (200, 96)
h1c:    inc     word [cs:t_n]
        pusha
        mov     ax, 3
        int     33h
        cmp     cx, 200
        jne     .n
        cmp     dx, 96
        jne     .n
        inc     word [cs:t_k]
.n:     popa
        jmp     far [cs:o1c]

        BLANKS

; AX as 4 hex digits at DI
        HEX4

child   db      'MTM33.COM', 0
        EXECBLK pblk
tail    db      8, ' h h.txt', 0Dh
mode    db      0
cnt     dw      0
t_n     dw      0
t_k     dw      0
o1c     dd      0
pv      times   6 dw 0
out_    times   32 db 0
fname   times   80 db 0
        times   256 db 0
stk_top:
the_end:
