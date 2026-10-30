; MTGROW.COM - for test_mt.py: a task's region growing on demand (T5a).
;   MTGROW MODE KB FILE
;   MODE S: shrinks itself to its own size first (4Ah), as most .COMs do;
;   K: keeps all it was given; C: a child (EXEC'd by "x"): its line, "C
;   pppp ssss" (its PSP, its block's paragraphs), then ends.  Then keys
;   through DOS (AH=08h) till "q", each writing a line to
;   FILE (appended):
;   1-9  48h of n x 16 KB: "A aaaa c bbbb" (AX: the block or the error,
;        CF, BX)
;   b    48h of KB KB, as 1-9; h  48h FFFFh, as 1-9; p and 4 hex digits
;        (keys): 48h of that many paragraphs, as 1-9
;   s    48h of 20h paragraphs, kept aside: as 1-9; e  49h of it: "E c"
;   f    49h of the last block 1-9, b or m gave: "F c"
;   m    the largest block (48h FFFFh, then that): "M aaaa c bbbb"; none
;        left: "M 0008 1 0000", not asked
;   x    EXEC of MTGROW.COM C 0 FILE: "X c aaaa" (CF, AX)
;   r    a routine copied into the last block, run there for 9 ticks:
;        "R nnnn", its count of rounds
;   v    INT 62h to an IRET in the last block, left so: "V"
;   q    "Q", and ends
; nasm -f bin -o MTGROW.COM MTGROW.ASM
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
        xor     bx, bx                  ; KB, decimal
.d:     lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .de
        cbw
        imul    bx, bx, 10
        add     bx, ax
        jmp     .d
.de:    mov     [kb], bx
        dec     si
        call    blanks
        mov     di, fname
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        stosb
        jmp     .n
.ne:    mov     byte [di], 0
        cmp     byte [mode], 'C'
        jne     .nc
        mov     di, out_                ; C: its line, and ends
        mov     al, 'C'
        stosb
        mov     al, ' '
        stosb
        mov     ax, cs
        call    hex4
        mov     al, ' '
        stosb
        mov     ax, [2]
        mov     bx, cs
        sub     ax, bx
        call    hex4
        call    wout
        mov     ax, 4C00h
        int     21h
.nc:    cmp     byte [mode], 'S'
        jne     .k
        mov     ah, 4Ah                 ; S: only what it needs
        mov     bx, (the_end - $$ + 100h + 15) / 16
        int     21h
.k:     mov     ah, 8                   ; the keys
        int     21h
        cmp     al, 'q'
        je      .q
        cmp     al, '1'
        jb      .k1
        cmp     al, '9'
        ja      .k1
        sub     al, '0'
        xor     ah, ah
        shl     ax, 10                  ; (n x 16 KB: n x 400h paragraphs)
        mov     bx, ax
        jmp     short .al
.k1:    cmp     al, 'b'
        jne     .k2
        mov     bx, [kb]
        shl     bx, 6
        jmp     short .al
.k2:    cmp     al, 'h'
        jne     .kp
        mov     bx, 0FFFFh
.al:    mov     ah, 48h
        int     21h
        mov     cl, 'A'
.rec:   jc      .re
        mov     [last], ax
.re:    call    rec4
        jmp     .k
.kp:    cmp     al, 'p'
        jne     .ks
        xor     bx, bx                  ; 4 hex digits, as keys
        mov     cx, 4
.ph:    push    cx
        push    bx
        mov     ah, 8
        int     21h
        pop     bx
        pop     cx
        sub     al, '0'
        cmp     al, 9
        jbe     .p1
        and     al, 0DFh
        sub     al, 'A' - '0' - 10
.p1:    shl     bx, 4
        or      bl, al
        loop    .ph
        jmp     .al
.ks:    cmp     al, 's'
        jne     .ke
        mov     ah, 48h
        mov     bx, 20h
        int     21h
        jc      .s1
        mov     [small], ax
.s1:    mov     cl, 'A'
        call    rec4
        jmp     .k
.ke:    cmp     al, 'e'
        jne     .k3
        mov     es, [small]
        mov     ah, 49h
        int     21h
        push    cs
        pop     es
        mov     al, 'E'
        call    putcf
        jmp     .k
.k3:    cmp     al, 'm'
        jne     .k4
        mov     ah, 48h
        mov     bx, 0FFFFh
        int     21h
        mov     cl, 'M'
        or      bx, bx                  ; (none left: not asked, AX 8, CF)
        stc
        jz      .rec
        mov     ah, 48h
        int     21h
        jmp     .rec
.k4:    cmp     al, 'f'
        jne     .k5
        mov     es, [last]
        mov     ah, 49h
        int     21h
        push    cs
        pop     es
        mov     al, 'F'
        call    putcf
        jmp     .k
.k5:    cmp     al, 'x'
        jne     .k6
        mov     di, tail + 1            ; the child's tail: " C 0 FILE", CR
        mov     si, s_c0
        call    cpz
        mov     si, fname
        call    cpz
        mov     byte [di], 0Dh
        mov     ax, di
        sub     ax, tail + 1
        mov     [tail], al
        mov     dx, child
        mov     bx, pblk
        mov     [pblk + 4], cs
        mov     [pblk + 8], cs
        mov     [pblk + 12], cs
        mov     ax, 4B00h
        int     21h
        push    cs
        pop     ds
        push    cs
        pop     es
        mov     sp, stk_top
        call    putcfax
        jmp     .k
.k6:    cmp     al, 'r'
        jne     .k7
        mov     es, [last]              ; the routine into the last block,
        xor     di, di                  ;  run there
        mov     si, r_code
        mov     cx, r_len
        cld
        rep     movsb
        push    cs
        pop     es
        mov     word [rfar], 0
        mov     ax, [last]
        mov     [rfar + 2], ax
        call    far [rfar]
        mov     bx, ax
        mov     al, 'R'
        mov     di, out_
        stosb
        mov     al, ' '
        stosb
        mov     ax, bx
        call    hex4
        call    wout
        jmp     .k
.k7:    cmp     al, 'v'
        jne     .k
        mov     es, [last]              ; an IRET there, INT 62h to it
        mov     byte [es:0], 0CFh
        push    cs
        pop     es
        push    ds
        mov     ds, [last]
        xor     dx, dx
        mov     ax, 2562h
        int     21h
        pop     ds
        mov     al, 'V'
        call    put1
        jmp     .k
.q:     mov     al, 'Q'
        call    put1
        mov     ax, 4C00h
        int     21h

; the routine: counts rounds till the BIOS's tick count is 9 on.  -> AX
r_code: push    es
        push    40h
        pop     es
        mov     dx, [es:6Ch]
        add     dx, 9
        xor     cx, cx
.l:     inc     cx
        mov     ax, [es:6Ch]
        sub     ax, dx
        js      .l
        pop     es
        mov     ax, cx
        retf
r_len   equ     $ - r_code

; FILE gets "L aaaa c bbbb" (L in CL, AX, CF, BX)
rec4:   pushf
        push    bx
        push    ax
        mov     di, out_
        mov     al, cl
        stosb
        mov     al, ' '
        stosb
        pop     ax
        call    hex4
        mov     al, ' '
        stosb
        pop     bx
        popf
        mov     al, '0'
        adc     al, 0
        stosb
        mov     al, ' '
        stosb
        mov     ax, bx
        call    hex4
        jmp     short wout
; FILE gets "L c" (L in AL, CF)
putcf:  pushf
        mov     di, out_
        stosb
        mov     al, ' '
        stosb
        popf
        mov     al, '0'
        adc     al, 0
        stosb
        jmp     short wout
; FILE gets "X c aaaa" (CF, AX: EXEC's answer)
putcfax:
        pushf
        mov     bx, ax
        mov     di, out_
        mov     al, 'X'
        stosb
        mov     al, ' '
        stosb
        popf
        mov     al, '0'
        adc     al, 0
        stosb
        mov     al, ' '
        stosb
        mov     ax, bx
        call    hex4
        jmp     short wout
; FILE gets "L" (L in AL)
put1:   mov     di, out_
        stosb
; FILE: out_ to DI, a CR LF after it, at its end (made if it isn't there)
        WOUT

; the 0-ended string at SI to DI (its 0 not copied)
        CPZ

        BLANKS

; AX as 4 hex digits at DI
        HEX4

child   db      'MTGROW.COM', 0
s_c0    db      ' C 0 ', 0
        EXECBLK pblk
mode    db      0
kb      dw      0
last    dw      0
small   dw      0
rfar    dd      0
tail    times   100 db 0
out_    times   32 db 0
fname   times   80 db 0
        times   256 db 0
stk_top:
the_end:
