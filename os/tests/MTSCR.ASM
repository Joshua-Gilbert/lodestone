; MTSCR.COM - for test_mt.py: a task's screen (KMT's INT 10h, M4a).
;   MTSCR MODE [FILE]
;   P  prints a script through INT 10h and DOS, using every call KMT does
;      itself for a task in the background: mode 3; on page 1, 30 lines
;      through the teletype and DOS, scrolling it with the attribute of the
;      cell under the cursor, and 09h there; then on page 0 DOS's console,
;      the teletype with CR, LF, BS and BEL, the cursor, 09h and 0Ah, 13h's
;      four kinds, 06h and 07h, the cursor's shape, the colour select, and
;      what 03h, 08h and 0Fh answer; and the 1520's odd cases: windows
;      the wrong way round after the clamps, page 8 (BH, and shown), 09h
;      run on past the 32 KB round to page 0, 03h's CX for page 11, 08h on
;      page 8, 0Ch and
;      0Dh in a text mode, and the AX that 00h, 05h, 0Bh and 0Dh give back;
;      an EMS page of its own in window 2, signed, checked at the end ("S+":
;      nothing written past the task's 32 KB).  Then waits for a key
;      (AH=08h), and ends
;   C  as P in mode 1 (40 columns); M  as P after a mode set of 83h (mode 2,
;      on the 1520)
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
;   W  waits for a key, then writes a word into B800h itself (no mode set),
;      FILE "W"; waits for a key
;   K  half a second, then MT_SCREEN (INT 21h F0h AL=1Ch), FILE "K"; ends
;   R  an 'R' in 70h at row 0, column 60, through INT 10h 13h called from
;      D800:0000 (test_mt puts INT 10h / RETF there: a ROM's code), FILE
;      "R"; waits for a key
;   B  mode 3, then page 7 shown with pages 1180h long (40:4Ch set so): from
;      7A80h, its rows 9 on past the 32 KB.  Rows 0-11 written with 09h; the
;      whole page scrolled up 1 and down 2 and a window partly past the end
;      blanked (KMT's bound test: the BIOS's way, a cell at a time); rows
;      3-5 up 1 (at once); the teletype on rows 2 and 24, its scroll; then
;      page 0 and 1000h back.  An EMS page of its own in window 2, signed,
;      checked at the end (as P's).  FILE "B+" ("B-": its signature gone,
;      "B?": no page); waits for a key.  In front only (it sets 40:4Ch
;      itself): with another task there, shadowed, as test_mt runs it
;   E  for the 1520: 40:4Eh (the page shown's start, which KMT's INT 10h
;      trusts) against 40:62h x 40:4Ch after a mode set (3, 1, then 3, each
;      with page 8 shown before it) and after 05h for pages 1-8 and 0: a line
;      each (40:49h, 62h, the two; '=', '!' if they differ, '?' if 49h or
;      62h isn't the mode or page asked for), 21, then 4E+ (all '='), 4E-
;      (a '!') or 4E? (a '?': the calls never reached the BIOS, as in a
;      terminal window or behind; run it full screen, in front); FILE "E+",
;      "E-" or "E?"; waits for a key
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
        mov     word [pmode], 0001h
        cmp     al, 'C'
        je      m_p
        mov     word [pmode], 0083h
        cmp     al, 'M'
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
        cmp     al, 'W'
        je      m_w
        cmp     al, 'K'
        je      m_k
        cmp     al, 'R'
        je      m_r
        cmp     al, 'B'
        je      m_b
        cmp     al, 'E'
        je      m_e
        jmp     fin

; ---- P: the script ----
m_p:    mov     ah, 43h                 ; an EMS page of its own in window 2,
        mov     bx, 1                   ;  signed (a window the wrong way round
        int     67h                     ;  blanks on past the 32 KB on the
        or      ah, ah                  ;  1520: MT's emulation stops there)
        jnz     .ne
        mov     [hnd], dx
        mov     ax, 4402h
        xor     bx, bx
        int     67h
        or      ah, ah
        jnz     .ne
        mov     byte [sig], 1
        push    0E800h
        pop     es
        mov     word [es:0], 'SI'
        mov     word [es:2], 'G!'
.ne:    mov     ax, [pmode]
        int     10h
        mov     [ax0], ax
        mov     ax, 0600h               ; windows the wrong way round after the
        mov     bh, 1Fh                 ;  clamps, which the BIOS runs on with:
        mov     cx, 1900h               ;  its top row below its bottom one
        mov     dx, 184Fh               ;  ("clear below the cursor", on the
        int     10h                     ;  last line), its left column right of
        mov     ax, 0601h               ;  its right one
        mov     bh, 2Eh
        mov     cx, 000Ah
        mov     dx, 1805h
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
        mov     ah, 1                   ; the cursor's shape (page 8's cursor
        mov     cx, 0D0Eh               ;  too, 40:60h: the teletype below
        int     10h                     ;  moves it on, to 0D0Fh)
        mov     ax, 0941h               ; page 8 (its cursor is 40:60h, the
        mov     bx, 0807h               ;  cursor's shape: page 0's row 0Dh,
        mov     cx, 1                   ;  column 0Eh, kept from here on, were
        int     10h                     ;  it written; its page is past 32 KB)
        mov     ax, 0508h               ; page 8 shown: the teletype's cursor
        int     10h                     ;  40:60h then, its character past the
        mov     [ax5], ax               ;  32 KB in 80 columns
        mov     ax, 0E7Ah
        mov     bx, 7
        int     10h
        mov     ax, 0500h
        int     10h
        mov     ah, 0Bh                 ; the colour select
        xor     bh, bh
        mov     bl, 5
        int     10h
        mov     [axb], ax
        mov     ax, 0D55h               ; 0Dh in a text mode
        xor     cx, cx
        xor     dx, dx
        int     10h
        mov     [axd], ax
        mov     ax, 0C55h               ; 0Ch, the same
        xor     cx, cx
        xor     dx, dx
        int     10h
        mov     [axc], ax
        mov     ah, 2                   ; 09h from page 7's start, 4810h of
        mov     bh, 7                   ;  them: past the 32 KB not written,
        xor     dx, dx                  ;  but on round 16 bits as the 1520's
        int     10h                     ;  DI goes, so in 80 columns page 0's
        mov     ax, 0957h               ;  first 16 cells
        mov     bx, 0717h
        mov     cx, 4810h
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
        mov     ah, 3                   ; (page 11: no cursor, CX the shape all
        mov     bh, 0Bh                 ;  the same)
        xor     cx, cx
        int     10h
        mov     [cx3], cx
        mov     ah, 8                   ; (page 8: past the 32 KB in 80 columns)
        mov     bh, 8
        int     10h
        mov     [ax8], ax
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
        mov     dx, 1400h               ; the AX that 00h, 05h, 0Bh, 0Dh gave
        call    curto
        mov     ax, [ax0]
        call    hexw
        mov     ax, [ax5]
        call    hexw
        mov     ax, [axb]
        call    hexw
        mov     ax, [axd]
        call    hexw
        mov     dx, 1500h               ; 03h's CX for page 11, 0Ch's AX, the
        call    curto                   ;  signed page in window 2
        mov     ax, [cx3]
        call    hexw
        mov     ax, [axc]
        call    hexw
        mov     ax, [ax8]
        call    hexw
        mov     al, 'S'
        call    tty1
        mov     al, '?'
        cmp     byte [sig], 0
        je      .sg
        mov     al, '-'
        push    0E800h
        pop     es
        cmp     word [es:0], 'SI'
        jne     .sg
        cmp     word [es:2], 'G!'
        jne     .sg
        mov     al, '+'
.sg:    call    tty1
        cmp     byte [sig], 0
        je      .sf
        mov     ah, 45h
        mov     dx, [hnd]
        int     67h
.sf:    mov     dx, 0246h
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

; ---- W: a key, then the screen written itself, no mode set ----
m_w:    mov     ah, 8
        int     21h
        push    0B800h
        pop     es
        mov     word [es:160 * 3 + 20], 4E57h   ; 'W' in 4Eh, row 3
        mov     al, 'W'
        call    wfile
        jmp     key

; ---- K: MT_SCREEN, half a second on ----
m_k:    push    40h
        pop     es
        mov     ax, [es:6Ch]
.w:     mov     dx, [es:6Ch]
        sub     dx, ax
        cmp     dx, 9
        jb      .w
        mov     ax, 0F01Ch
        int     21h
        mov     al, 'K'
        call    wfile
        jmp     fin

; ---- R: a ROM's INT 10h ----
m_r:    push    cs
        pop     es
        mov     ax, 1300h
        mov     bx, 0070h
        mov     cx, 1
        mov     dx, 003Ch
        mov     bp, s_r
        call    far [romv]
        mov     al, 'R'
        call    wfile
        jmp     key

; ---- B: a page across the 32 KB's end ----
m_b:    call    esig                    ; (an EMS page of its own past the 32 KB)
        mov     ax, 0003h
        int     10h
        mov     si, s_b
        call    ttys
        push    40h
        pop     es
        mov     word [es:4Ch], 1180h    ; (05h multiplies by it: 7A80h)
        mov     ax, 0507h
        int     10h
        xor     dx, dx                  ; rows 0-11: 80 of 'a' on, in 10h on
.r:     mov     ah, 2
        mov     bh, 7
        int     10h
        mov     al, dh
        add     al, 'a'
        mov     ah, 9
        mov     bl, dh
        add     bl, 10h
        mov     cx, 80
        int     10h
        inc     dh
        cmp     dh, 12
        jb      .r
        mov     ax, 0601h               ; the page up 1, 1Fh
        mov     bh, 1Fh
        xor     cx, cx
        mov     dx, 184Fh
        int     10h
        mov     ax, 0702h               ; down 2, 2Eh
        mov     bh, 2Eh
        xor     cx, cx
        mov     dx, 184Fh
        int     10h
        mov     ax, 0600h               ; rows 6-10 blank, 4Eh
        mov     bh, 4Eh
        mov     cx, 0600h
        mov     dx, 0A4Fh
        int     10h
        mov     ax, 0601h               ; rows 3-5 up 1, 5Bh (inside: at once)
        mov     bh, 5Bh
        mov     cx, 0300h
        mov     dx, 054Fh
        int     10h
        mov     ah, 2                   ; the teletype on row 2, and on 24
        mov     bh, 7                   ;  (past the end) with its scroll
        mov     dx, 0205h
        int     10h
        mov     si, s_b2
        call    ttys
        mov     ah, 2
        mov     bh, 7
        mov     dx, 1800h
        int     10h
        mov     si, s_b3
        call    ttys
        mov     ax, 0500h
        int     10h
        push    40h
        pop     es
        mov     word [es:4Ch], 1000h
        call    echk
        mov     byte [out_], 'B'
        mov     [out_ + 1], al
        mov     cx, 2
        call    wbuf
        jmp     key

; an EMS page of its own in window 2 (E800h, just past a task's 32 KB in
; the frame: MT's emulation must stop short of it), signed
esig:   mov     ah, 43h
        mov     bx, 1
        int     67h
        or      ah, ah
        jnz     .x
        mov     [hnd], dx
        mov     ax, 4402h
        xor     bx, bx
        int     67h
        or      ah, ah
        jnz     .x
        mov     byte [sig], 1
        push    es
        push    0E800h
        pop     es
        mov     word [es:0], 'SI'
        mov     word [es:2], 'G!'
        pop     es
.x:     ret
; AL: '+' esig's page signed still, '-' not, '?' none; the page freed
echk:   mov     al, '?'
        cmp     byte [sig], 0
        je      .x
        mov     al, '-'
        push    es
        push    0E800h
        pop     es
        cmp     word [es:0], 'SI'
        jne     .f
        cmp     word [es:2], 'G!'
        jne     .f
        mov     al, '+'
.f:     pop     es
        push    ax
        mov     ah, 45h
        mov     dx, [hnd]
        int     67h
        pop     ax
.x:     ret

; ---- E: 40:4Eh against 40:62h x 40:4Ch ----
m_e:    mov     di, tab
        mov     ax, 0508h               ; (page 8 shown before each mode set:
        int     10h                     ;  40:4Eh 0 after it all the same)
        mov     ax, 0003h
        call    epages
        mov     ax, 0001h
        call    epages
        mov     ax, 0003h
        mov     [emode], al
        int     10h
        xor     bl, bl
        call    erec
        mov     si, s_e
        call    ttys
        mov     si, tab
.p:     cmp     si, di
        jae     .v
        lodsw                           ; the mode and page asked for
        xchg    ax, dx
        lodsw                           ; the mode and page noted
        mov     cl, '='
        cmp     ax, dx
        je      .m
        mov     cl, '?'                 ; (not as asked: the BIOS never had
.m:     push    ax                      ;  the call, as in a terminal window)
        call    hexb2
        mov     al, ' '
        call    tty1
        pop     ax
        mov     al, ah
        call    hexb2
        mov     al, ' '
        call    tty1
        lodsw                           ; 40:4Eh, then 40:62h x 40:4Ch
        call    hexw
        lodsw
        push    ax
        call    hexw
        pop     ax
        cmp     cl, '='
        jne     .q
        cmp     ax, [si - 4]
        je      .q
        mov     cl, '!'
.q:     cmp     cl, '='                 ; (4E? for any '?', else 4E- for any
        je      .w                      ;  '!')
        mov     al, '?'
        cmp     cl, al
        je      .s
        cmp     [eok], al
        je      .w
        mov     al, '-'
.s:     mov     [eok], al
.w:     mov     al, cl
        call    tty1
        mov     al, 13
        call    tty1
        mov     al, 10
        call    tty1
        jmp     .p
.v:     mov     al, '4'
        call    tty1
        mov     al, 'E'
        call    tty1
        mov     al, [eok]
        call    tty1
        mov     di, out_
        mov     al, 'E'
        stosb
        mov     al, [eok]
        stosb
        mov     cx, 2
        call    wbuf
        jmp     key

epages: mov     [emode], al             ; mode AX, then 05h for pages 1-8 and
        int     10h                     ;  0, each noted at DI; page 8 shown
        xor     bl, bl                  ;  again at the end
        call    erec
        mov     cx, 1
.n:     push    cx
        mov     al, cl
        cmp     al, 9
        jb      .p
        xor     al, al
.p:     push    ax
        mov     ah, 5
        int     10h
        pop     bx
        call    erec
        pop     cx
        inc     cx
        cmp     cx, 10
        jb      .n
        mov     ax, 0508h
        int     10h
        ret
erec:   push    es                      ; at DI: the mode and page asked for
        push    40h                     ;  ([emode], BL), 40:49h, 62h, 4Eh,
        pop     es                      ;  and 62h x 4Ch
        mov     al, [emode]
        mov     ah, bl
        mov     [di], ax
        mov     al, [es:49h]
        mov     ah, [es:62h]
        mov     [di + 2], ax
        mov     ax, [es:4Eh]
        mov     [di + 4], ax
        mov     al, [es:62h]
        xor     ah, ah
        mul     word [es:4Ch]
        mov     [di + 6], ax
        add     di, 8
        pop     es
        ret

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

tty1:   mov     ah, 0Eh                 ; AL through the teletype
        mov     bx, 7
        int     10h
        ret
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
s_r     db      'R'
s_b     db      'a page across the 32 KB', 39, 's end', 0
s_b2    db      'fast', 0
s_b3    db      'tty', 13, 10, 0
s_e     db      'md pg 4Eh  62h*4Ch', 13, 10, 0
eok     db      '+'
emode   db      0
tab     times   21 * 8 db 0
romv    dw      0, 0D800h
mode    db      0
pmode   dw      0003h
ax0     dw      0
ax5     dw      0
axb     dw      0
axd     dw      0
axc     dw      0
ax8     dw      0
cx3     dw      0
hnd     dw      0
sig     db      0
fnm     dw      0
o1c     dd      0
out_    times 8 db 0
        times   512 db 0
stk_top:
