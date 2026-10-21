; MTSCR.COM - for test_mt.py: a task's screen (KMT's INT 10h, M4a).
;   MTSCR MODE [FILE]
;   P  prints a script through INT 10h and DOS, using every call KMT does
;      itself for a task in the background: mode 3; on page 1, 30 lines
;      through the teletype and DOS, scrolling it with the attribute of the
;      cell under the cursor, and 09h there; then on page 0 DOS's console,
;      the teletype with CR, LF, BS and BEL, the cursor, 09h and 0Ah, 13h's
;      four kinds, 06h and 07h, the cursor's shape, the colour select, and
;      what 03h, 08h and 0Fh answer.  Then waits for a key (AH=08h), and
;      ends
;   L  mode 3, then 120 lines through DOS (AH=09h), then FILE "L"; waits
;      for a key
;   D  mode 3, a line, then a word written into B800h itself; waits for a key
;   G  a line, then mode 6 (graphics) through INT 10h, then FILE "G"; waits
;      for a key
;   Q  as G, but the mode set with interrupts off (so it can't wait to be
;      in front, and is dropped); FILE "Q" and the mode 0Fh gives (2 hex
;      digits); waits for a key
;   I  hooks INT 1Ch, its handler writing '*' at the top right through
;      INT 10h (02h, 09h); waits 6 ticks, unhooks, FILE "I"; waits for a key
; nasm -f bin -o MTSCR.COM MTSCR.ASM
cpu 286
org 100h
        mov     sp, stk_top
        mov     ah, 4Ah                 ; (only its own memory)
        mov     bx, (stk_top - $$ + 100h + 15) / 16
        int     21h
        mov     si, 81h
        call    blanks
        lodsb
        and     al, 0DFh
        mov     [mode], al
        call    blanks
        mov     [fnm], si
        call    word_
        mov     al, [mode]
        cmp     al, 'P'
        je      m_p
        cmp     al, 'L'
        je      m_l
        cmp     al, 'D'
        je      m_d
        cmp     al, 'G'
        je      m_g
        cmp     al, 'Q'
        je      m_g
        cmp     al, 'I'
        je      m_i
        jmp     fin

; ---- P: the script ----
m_p:    mov     ax, 0003h
        int     10h
        mov     ax, 0501h               ; page 1 first (the teletype writes
        int     10h                     ;  and scrolls the page shown): its
        mov     ah, 2                   ;  bottom line in attribute 1Eh, so the
        mov     bh, 1                   ;  teletype's scroll takes it
        mov     dx, 1800h
        int     10h
        mov     ax, 0920h
        mov     bx, 011Eh
        mov     cx, 80
        int     10h
        mov     cx, 30                  ; 30 lines: scrolling, by the BIOS and
.ln:    push    cx                      ;  DOS in turn
        mov     al, cl
        add     al, '@'
        mov     [s_ln + 5], al
        mov     si, s_ln
        test    cl, 1
        jz      .lb
        mov     dx, s_ln
        mov     ah, 9
        int     21h
        jmp     short .le
.lb:    call    ttys
.le:    pop     cx
        loop    .ln
        mov     si, s_pg1
        call    ttys
        mov     ah, 2                   ; 09h on page 1 at its own cursor
        mov     bh, 1
        mov     dx, 0303h
        int     10h
        mov     ax, 0950h
        mov     bx, 015Fh
        mov     cx, 3
        int     10h
        mov     ax, 0500h               ; then page 0: the rest
        int     10h
        mov     dx, s_dos               ; DOS's console (the kernel's INT 10h)
        mov     ah, 9
        int     21h
        mov     dl, 'x'
        mov     ah, 2
        int     21h
        mov     dl, 'y'
        int     21h
        mov     dl, 13
        int     21h
        mov     dl, 10
        int     21h
        mov     si, s_tty               ; the teletype: BS, BEL
        call    ttys
        mov     dx, 050Ah               ; 09h: 20 'A's, attribute 1Fh
        call    curto
        mov     ax, 0941h
        mov     bx, 001Fh
        mov     cx, 20
        int     10h
        mov     dx, 0600h               ; 0Ah: 5 'B's, the attributes kept
        call    curto
        mov     ax, 0A42h
        xor     bx, bx
        mov     cx, 5
        int     10h
        push    cs                      ; 13h, its four kinds
        pop     es
        mov     ax, 1300h
        mov     bx, 002Eh
        mov     cx, s13a_len
        mov     dx, 0700h
        mov     bp, s13a
        int     10h
        mov     ax, 1301h
        mov     bx, 003Fh
        mov     cx, s13b_len
        mov     dx, 0800h
        mov     bp, s13b
        int     10h
        mov     ax, 1302h
        mov     bx, 0007h
        mov     cx, 5
        mov     dx, 0900h
        mov     bp, s13c
        int     10h
        mov     ax, 1303h
        mov     bx, 0007h
        mov     cx, 4
        mov     dx, 0B00h
        mov     bp, s13d
        int     10h
        mov     ax, 0602h               ; 06h: a window up 2, attribute 4Eh
        mov     bh, 4Eh
        mov     cx, 0505h
        mov     dx, 0A28h
        int     10h
        mov     ax, 0701h               ; 07h: rows 12-15 down 1, 2Fh
        mov     bh, 2Fh
        mov     cx, 0C00h
        mov     dx, 0F4Fh
        int     10h
        mov     ax, 0600h               ; 06h, AL 0: a window blank, 17h
        mov     bh, 17h
        mov     cx, 103Ch
        mov     dx, 1246h
        int     10h
        mov     ax, 0605h               ; ... and more lines than it has: the
        mov     bh, 71h                 ;  same
        mov     cx, 1400h
        mov     dx, 1504h
        int     10h
        mov     ah, 1                   ; the cursor's shape
        mov     cx, 0D0Eh
        int     10h
        mov     ah, 0Bh                 ; the colour select
        xor     bh, bh
        mov     bl, 5
        int     10h
        mov     dx, 1300h               ; what 03h, 08h, 0Fh answer
        call    curto
        mov     ah, 3
        xor     bh, bh
        int     10h
        push    cx
        mov     ax, dx
        call    hexw
        pop     ax
        call    hexw
        mov     ah, 3
        mov     bh, 1
        int     10h
        mov     ax, dx
        call    hexw
        mov     dx, 0505h               ; (a cell 06h's window scrolled)
        call    curto
        mov     ah, 8
        xor     bh, bh
        int     10h
        push    ax
        mov     dx, 1310h
        call    curto
        pop     ax
        call    hexw
        mov     ah, 0Fh
        int     10h
        push    bx
        call    hexw
        pop     ax
        mov     al, ah
        call    hexw
        mov     dx, 0246h
        call    curto
        mov     si, s_end
        call    ttys
        jmp     key

; ---- L: lines through DOS ----
m_l:    mov     ax, 0003h
        int     10h
        mov     cx, 120
.l:     push    cx
        mov     dx, s_long
        mov     ah, 9
        int     21h
        pop     cx
        loop    .l
        mov     al, 'L'
        call    wfile
        jmp     key

; ---- D: the screen written itself ----
m_d:    mov     ax, 0003h
        int     10h
        mov     si, s_d
        call    ttys
        push    0B800h
        pop     es
        mov     word [es:160 * 2 + 20], 4E44h   ; 'D' in 4Eh, row 2
        jmp     key

; ---- G, Q: graphics asked for ----
m_g:    mov     si, s_g
        call    ttys
        cmp     byte [mode], 'Q'
        je      .q
        mov     ax, 0006h
        int     10h
        mov     al, 'G'
        call    wfile
        jmp     key
.q:     mov     ax, 0006h
        cli
        int     10h
        sti
        mov     ah, 0Fh
        int     10h
        push    ax
        mov     di, out_
        mov     al, 'Q'
        stosb
        pop     ax
        call    hexb
        mov     cx, 3
        call    wbuf
        jmp     key

; ---- I: INT 1Ch's handler draws ----
m_i:    mov     ax, 351Ch
        int     21h
        mov     [o1c], bx
        mov     [o1c + 2], es
        mov     ax, 251Ch
        mov     dx, h1c
        int     21h
        push    40h
        pop     es
        mov     ax, [es:6Ch]
.w:     mov     dx, [es:6Ch]
        sub     dx, ax
        cmp     dx, 6
        jb      .w
        push    ds
        mov     ax, 251Ch
        lds     dx, [o1c]
        int     21h
        pop     ds
        mov     al, 'I'
        call    wfile
        jmp     key

h1c:    push    ax                      ; INT 1Ch (I): '*' at row 0, column
        push    bx                      ;  79 of the page shown, attribute 70h
        push    cx
        push    dx
        mov     ah, 3
        xor     bh, bh
        int     10h
        push    dx
        mov     ah, 2
        mov     dx, 004Fh
        int     10h
        mov     ax, 092Ah
        mov     bx, 0070h
        mov     cx, 1
        int     10h
        mov     ah, 2
        xor     bh, bh
        pop     dx
        int     10h
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        jmp     far [cs:o1c]

key:    mov     ah, 8
        int     21h
fin:    mov     ax, 4C00h
        int     21h

; FILE: AL, or CX bytes of out_
wfile:  mov     [out_], al
        mov     cx, 1
wbuf:   mov     ah, 3Ch
        push    cx
        xor     cx, cx
        mov     dx, [fnm]
        int     21h
        pop     cx
        jc      .x
        mov     bx, ax
        mov     ah, 40h
        mov     dx, out_
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret

curto:  mov     ah, 2                   ; the cursor to DX (page 0)
        xor     bh, bh
        int     10h
        ret
ttys:   lodsb                           ; SI's text through the teletype (to a
        or      al, al                  ;  NUL or a '$')
        jz      .x
        cmp     al, '$'
        je      .x
        mov     ah, 0Eh
        mov     bx, 0007h
        int     10h
        jmp     ttys
.x:     ret
hexw:   push    ax                      ; AX as 4 hex digits, then a blank
        mov     al, ah
        call    hexb2
        pop     ax
        call    hexb2
        mov     ax, 0E20h
        mov     bx, 7
        int     10h
        ret
hexb2:  push    ax
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     ah, 0Eh
        mov     bx, 7
        int     10h
        ret
hexb:   push    ax                      ; AL as 2 hex digits at DI
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     stosb
        ret
blanks: lodsb
        cmp     al, ' '
        je      blanks
        dec     si
        ret
word_:  lodsb                           ; to a blank or the end: NUL there
        cmp     al, ' '
        ja      word_
        mov     byte [si - 1], 0
        cmp     al, 0Dh
        jne     .x
        dec     si
.x:     ret

s_dos   db      'DOS: a line', 13, 10, '$'
s_tty   db      'BIOS ab', 8, 'c', 7, 13, 10, 'next', 0
s13a    db      'str0'
s13a_len equ    $ - s13a
s13b    db      'str1 moves', 13, 10, 'on'
s13b_len equ    $ - s13b
s13c    db      's', 4Fh, '2', 5Eh, 13, 10, 'x', 1Ah
s13d    db      'm', 6Ch, 'v', 3Dh
s_pg1   db      'on page one', 13, 10, 'and two', 0
s_ln    db      'line  of the scrolling', 13, 10, '$'
        db      0
s_long  db      'a long listing line, about sixty characters wide....', 13, 10, '$'
s_d     db      'writes the screen itself', 13, 10, 0
s_g     db      'asks for graphics', 13, 10, 0
s_end   db      'end', 0
mode    db      0
fnm     dw      0
o1c     dd      0
out_    times 8 db 0
        times   512 db 0
stk_top:
