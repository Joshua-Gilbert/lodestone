; MTPUB.COM - for test_mt.py: a screen published for a terminal window
; (T5b, MT_PUB).  MTPUB FILE: it shrinks to its own size (4Ah), then its
; descriptor (25 x 80 cells, a font of its own for codes 20h-47h, a table
; for Copy) is published: "P c aaaa" (CF, AX) to FILE; then keys through
; DOS (AH=08h) till "q", each writing a line to FILE (appended):
;   c  row 23's cell 10 the next glyph (21h-2Fh, round): "C gg"
;   k  the cursor hidden, or shown again (PBF_NOCUR): "K ff" (PB_FLAGS)
;   u  the cursor to row 5, column 3: "U"; d  back to row 23, column 0: "D"
;   n  PBF_SHOWN off, "MTPUB: pages" printed: "N"; s  on again: "S"
;   g  PBF_SHOWN off, mode 40h, B800h's first 256 bytes a pattern, a key,
;      mode 3, PBF_SHOWN on: "G"
;   w  withdrawn (0:0): "W c aaaa"; p  published again: "P c aaaa"
;   b  refused ones, then one taken: "B c aaaa ..." for ES:DI 0:400h,
;      PB_VER 0, PB_COLS 0, 81, PB_ROWS 0, 26, PB_FIRST 21h, PB_GEND 3Fh,
;      PB_CELLS 0:0, PB_FONT 0:0, PB_XLAT at FFC0h (past its segment's
;      end), PB_XLAT across the end of its task's memory, CL 1 (a task's
;      call), CL 2; then PB_XLAT the 128 bytes at that end's last 8
;      paragraphs (taken); then its own descriptor again: "c aaaa" (all
;      on one line, each a copy of its descriptor with one field changed)
;   x  EXEC of MTPUB C FILE (a child: "Y", ends): "X c aaaa"
;   y  EXEC of MTPUB D FILE (a child that publishes its own: "Z c aaaa",
;      ends): "X c aaaa"
;   r  PB_ROWS 20, or 25 again: "R rr"
;   t  36 ticks computing (no call made: it never waits), row 22's cell 0
;      the next glyph (21h-2Fh, round) at each: "T"
;   q  "Q", and ends (its screen still published: its end withdraws it)
; Each change adds 1 to PB_CHG.  Cell (r, c): glyph 20h + (r * 7 + c) mod
; 40, attribute (c / 8) and 3; row 24's first six 05h, F0h, 80h, 81h, 47h,
; 20h (below its first code, past its end, the table's 'A', its 0, the
; last glyph, the first).  Glyph g's row r: (g * 13 + r * 29) and FFh
; nasm -f bin -i ../src/ -o MTPUB.COM MTPUB.ASM
cpu 286
org 100h
%include "MTAPI.INC"
NCOL    equ 80
NROW    equ 25
FIRST   equ 20h
GEND    equ 48h
        mov     sp, stk_top
        mov     ah, 4Ah                 ; only what it needs
        mov     bx, (the_end - $$ + 100h + 15) / 16
        int     21h
        mov     si, 81h
        call    blanks
        mov     byte [mode], 0
        mov     al, [si]
        and     al, 0DFh
        cmp     byte [si + 1], ' '
        jne     .f
        cmp     al, 'C'
        je      .m
        cmp     al, 'D'
        jne     .f
.m:     mov     [mode], al
        add     si, 2
        call    blanks
.f:     mov     di, fname
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        stosb
        jmp     .n
.ne:    mov     byte [di], 0
        call    build
        cmp     byte [mode], 'C'
        jne     .nc
        mov     al, 'Y'                 ; C: its line, and ends
        call    put1
        jmp     .end
.nc:    mov     al, 'P'
        cmp     byte [mode], 'D'
        jne     .pub
        mov     al, 'Z'                 ; D: its own published, its line,
        call    pub                     ;  and ends
        jmp     .end
.pub:   call    pub
.k:     mov     ah, 8                   ; the keys
        int     21h
        mov     bx, keys
.kl:    cmp     byte [bx], 0
        je      .k
        cmp     al, [bx]
        je      .kx
        add     bx, 3
        jmp     .kl
.kx:    call    [bx + 1]
        jmp     .k
.end:   mov     ax, 4C00h
        int     21h

keys    db      'c'
        dw      k_c
        db      'k'
        dw      k_k
        db      'u'
        dw      k_u
        db      'd'
        dw      k_d
        db      'n'
        dw      k_n
        db      's'
        dw      k_s
        db      'g'
        dw      k_g
        db      'w'
        dw      k_w
        db      'p'
        dw      k_p
        db      'b'
        dw      k_b
        db      'x'
        dw      k_x
        db      'y'
        dw      k_y
        db      'r'
        dw      k_r
        db      't'
        dw      k_t
        db      'q'
        dw      k_q
        db      0

k_c:    mov     al, [cells + (23 * NCOL + 10) * 2]
        inc     al
        cmp     al, 2Fh
        jbe     .s
        mov     al, 21h
.s:     mov     [cells + (23 * NCOL + 10) * 2], al
        push    ax
        call    chg
        mov     di, out_
        mov     al, 'C'
        stosb
        mov     al, ' '
        stosb
        pop     ax
        call    hex2
        jmp     wout
k_k:    xor     byte [desc + PB_FLAGS], PBF_NOCUR
        call    chg
        mov     di, out_
        mov     al, 'K'
        stosb
        mov     al, ' '
        stosb
        mov     al, [desc + PB_FLAGS]
        call    hex2
        jmp     wout
k_r:    xor     byte [desc + PB_ROWS], 25 ^ 20
        call    chg
        mov     di, out_
        mov     al, 'R'
        stosb
        mov     al, ' '
        stosb
        mov     al, [desc + PB_ROWS]
        call    hex2
        jmp     wout
k_t:    push    es
        push    40h
        pop     es
        mov     cx, 36
.w:     mov     ax, [es:6Ch]
.s:     cmp     ax, [es:6Ch]            ; (the BIOS's tick count: read, no call)
        je      .s
        mov     al, [cells + 22 * NCOL * 2]
        inc     al
        cmp     al, 2Fh
        jbe     .g
        mov     al, 21h
.g:     mov     [cells + 22 * NCOL * 2], al
        call    chg
        loop    .w
        pop     es
        mov     al, 'T'
        jmp     put1
k_u:    mov     word [desc + PB_CUR], 0503h
        mov     al, 'U'
        jmp     short chg1
k_d:    mov     word [desc + PB_CUR], 1700h
        mov     al, 'D'
        jmp     short chg1
k_n:    and     byte [desc + PB_FLAGS], ~PBF_SHOWN
        mov     ah, 9
        mov     dx, s_pages
        int     21h
        mov     al, 'N'
        jmp     short chg1
k_s:    or      byte [desc + PB_FLAGS], PBF_SHOWN
        mov     al, 'S'
chg1:   call    chg
        jmp     put1
k_g:    and     byte [desc + PB_FLAGS], ~PBF_SHOWN
        call    chg
        mov     ax, 40h
        int     10h
        push    es
        push    0B800h
        pop     es
        xor     di, di
        mov     cx, 256
.p:     mov     ax, di                  ; DI's byte: (DI * 5) XOR (DI >> 8)
        mov     dx, ax
        shl     ax, 2
        add     ax, dx
        xor     al, dh
        stosb
        loop    .p
        pop     es
        mov     ah, 8
        int     21h
        mov     ax, 3
        int     10h
        or      byte [desc + PB_FLAGS], PBF_SHOWN
        mov     al, 'G'
        jmp     chg1
k_w:    xor     di, di
        mov     es, di
        call    mtpub
        push    ds
        pop     es
        mov     al, 'W'
        jmp     short res1
k_p:    mov     al, 'P'
        jmp     pub
k_q:    mov     al, 'Q'
        call    put1
        mov     ax, 4C00h
        int     21h

; its descriptor published: "L c aaaa" (L in AL)
pub:    push    ax
        mov     di, desc
        call    mtpub
        pop     ax
res1:   mov     di, out_
        stosb
        call    res
        jmp     wout

; MT_PUB, CL = 0, ES:DI -> CF, AX as " c aaaa" at out_'s DI... (see res)
mtpub:  mov     cl, 0
mtpubc: mov     ax, 0F000h + MT_PUB
        stc
        int     21h
        pushf
        pop     word [rfl]
        mov     [r_ax], ax
        ret
; " c aaaa" at DI from rfl, rax
res:    mov     al, ' '
        stosb
        mov     al, [rfl]
        and     al, 1
        add     al, '0'
        stosb
        mov     al, ' '
        stosb
        mov     ax, [r_ax]
        jmp     hex4

; b: each a copy of its descriptor with one field changed
k_b:    mov     di, out_
        mov     al, 'B'
        stosb
        mov     [optr], di
        xor     ax, ax                  ; ES:DI 0:400h
        mov     es, ax
        mov     di, 400h
        call    mtpub
        push    ds
        pop     es
        call    rec
        mov     bx, PB_VER
        xor     ax, ax
        call    bad1
        mov     bx, PB_COLS
        xor     ax, ax
        call    bad1
        mov     bx, PB_COLS
        mov     al, 81
        call    bad1
        mov     bx, PB_ROWS
        xor     ax, ax
        call    bad1
        mov     bx, PB_ROWS
        mov     al, 26
        call    bad1
        mov     bx, PB_FIRST
        mov     al, 21h
        call    bad1
        mov     bx, PB_GEND
        mov     al, 3Fh
        call    bad1
        call    copy                    ; PB_CELLS 0:0
        xor     ax, ax
        mov     [bad + PB_CELLS], ax
        mov     [bad + PB_CELLS + 2], ax
        call    badp
        call    copy                    ; PB_FONT 0:0
        xor     ax, ax
        mov     [bad + PB_FONT], ax
        mov     [bad + PB_FONT + 2], ax
        call    badp
        call    copy                    ; PB_XLAT at FFC0h
        mov     word [bad + PB_XLAT], 0FFC0h
        mov     [bad + PB_XLAT + 2], cs
        call    badp
        call    rend                    ; PB_XLAT across its memory's end
        sub     ax, 8
        call    copy
        mov     word [bad + PB_XLAT], 70h
        mov     [bad + PB_XLAT + 2], ax
        call    badp
        mov     di, desc                ; CL 1, CL 2 from a task
        mov     cl, 1
        call    mtpubc
        call    rec
        mov     di, desc
        mov     cl, 2
        call    mtpubc
        call    rec
        call    rend                    ; PB_XLAT its memory's last 128 bytes
        sub     ax, 8
        call    copy
        mov     word [bad + PB_XLAT], 0
        mov     [bad + PB_XLAT + 2], ax
        call    badp
        mov     di, desc                ; its own again
        call    mtpub
        call    rec
        mov     di, [optr]
        jmp     wout
; BX = a byte field, AL its value: in a copy, published
bad1:   push    ax
        call    copy
        pop     ax
        mov     [bad + bx], al
badp:   mov     di, bad
        call    mtpub
; the result to the line (optr)
rec:    mov     di, [optr]
        call    res
        mov     [optr], di
        ret
copy:   push    si
        push    di
        push    cx
        mov     si, desc
        mov     di, bad
        mov     cx, PB_SIZE
        rep     movsb
        pop     cx
        pop     di
        pop     si
        ret
; AX = the paragraph past its task's memory (the arena's 'Z' block's end)
rend:   push    es
        mov     ax, cs
        dec     ax
.l:     mov     es, ax
        inc     ax
        add     ax, [es:3]
        cmp     byte [es:0], 'Z'
        jne     .l
        pop     es
        ret

; x, y: EXEC of MTPUB C FILE, D FILE
k_x:    mov     al, 'C'
        jmp     short k_y.e
k_y:    mov     al, 'D'
.e:     mov     di, tail + 1            ; the child's tail: " C FILE", CR
        mov     byte [di], ' '
        mov     [di + 1], al
        mov     byte [di + 2], ' '
        add     di, 3
        mov     si, fname
        call    cpz
        mov     byte [di], 13
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
        pushf
        pop     word [rfl]
        mov     [r_ax], ax
        mov     di, out_
        mov     al, 'X'
        stosb
        call    res
        jmp     wout

; the descriptor, cells, font and table
build:  mov     word [desc + PB_VER], 1 | (PBF_SHOWN << 8)
        mov     word [desc + PB_COLS], NCOL | (NROW << 8)
        mov     word [desc + PB_CELLS], cells
        mov     [desc + PB_CELLS + 2], cs
        mov     word [desc + PB_FONT], font
        mov     [desc + PB_FONT + 2], cs
        mov     word [desc + PB_FIRST], FIRST | (GEND << 8)
        mov     word [desc + PB_CUR], 1700h
        mov     word [desc + PB_CHG], 0
        mov     word [desc + PB_XLAT], xtab
        mov     [desc + PB_XLAT + 2], cs
        mov     di, cells
        xor     dx, dx                  ; DH the row, DL the column
.c:     mov     al, dh
        mov     ah, 7
        mul     ah
        add     al, dl
        adc     ah, 0
        mov     bl, 40
        div     bl
        mov     al, ah
        add     al, FIRST
        mov     ah, dl
        shr     ah, 3
        and     ah, 3
        stosw
        inc     dl
        cmp     dl, NCOL
        jb      .c
        xor     dl, dl
        inc     dh
        cmp     dh, NROW
        jb      .c
        mov     si, row24
        mov     di, cells + 24 * NCOL * 2
        mov     cx, 6
.r0:    lodsb
        stosb
        inc     di
        loop    .r0
        mov     di, font                ; glyph g's row r: g * 13 + r * 29
        mov     bl, FIRST
.g:     xor     cx, cx
.gr:    mov     al, bl
        mov     ah, 13
        mul     ah
        push    ax
        mov     al, cl
        mov     ah, 29
        mul     ah
        pop     dx
        add     al, dl
        stosb
        inc     cx
        cmp     cx, 16
        jb      .gr
        inc     bl
        cmp     bl, GEND
        jb      .g
        mov     di, xtab
        xor     ax, ax
        mov     cx, 64
        rep     stosw
        mov     byte [xtab], 'A'
        ret

; a change: PB_CHG + 1
chg:    inc     word [desc + PB_CHG]
        ret

; FILE gets "L" (L in AL)
put1:   mov     di, out_
        stosb
; FILE: out_ to DI, a CR LF after it, at its end (made if it isn't there)
wout:   mov     ax, 0A0Dh
        stosw
        mov     ax, 3D02h
        mov     dx, fname
        int     21h
        jnc     .o
        mov     ah, 3Ch
        xor     cx, cx
        int     21h
        jc      .x
.o:     xchg    bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        mov     ah, 40h
        mov     cx, di
        mov     dx, out_
        sub     cx, dx
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret

; the 0-ended string at SI to DI (its 0 not copied)
cpz:    lodsb
        or      al, al
        jz      .x
        stosb
        jmp     cpz
.x:     ret

blanks: lodsb
        cmp     al, ' '
        je      blanks
        dec     si
        ret

; AL, AX as 2, 4 hex digits at DI
hex2:   mov     ah, al
        mov     cx, 2
        jmp     short hex4.h
hex4:   mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .s
        add     al, 7
.s:     stosb
        pop     ax
        loop    .h
        ret

child   db      'MTPUB.COM', 0
s_pages db      'MTPUB: pages', 13, 10, '$'
row24   db      05h, 0F0h, 80h, 81h, GEND - 1, FIRST
pblk    dw      0, tail, 0, 5Ch, 0, 6Ch, 0
mode    db      0
rfl     dw      0
r_ax    dw      0
optr    dw      0
desc    times   PB_SIZE db 0
bad     times   PB_SIZE db 0
tail    times   100 db 0
out_    times   200 db 0
fname   times   80 db 0
xtab    times   128 db 0
font    times   (GEND - FIRST) * 16 db 0
cells   times   NCOL * NROW * 2 db 0
        times   512 db 0
stk_top:
the_end:
