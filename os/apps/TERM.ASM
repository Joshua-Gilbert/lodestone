; =====================================================================
;  TERM.RUN - a terminal window: a DOS program, running as a task behind
;  (MULTITASK=1), shown in a window of the Executive's (T2)
;  python3 mkrun.py apps/TERM.ASM apps/TERM.RUN
;
;  Opened by MT itself (KMT's mt_uwin) when Return or CODE-P starts a text
;  program as a task: the argument is "task count", the task's number and
;  how many tasks that number has had (MT_EXIT's AH), so a number given
;  again isn't taken for it.  The task stays behind (task 0, the UI, is
;  the front task): its screen is the one MT keeps for it (MT_TROWS), and
;  the keys typed here go to it (MT_TKEY).  UI_EVENT gives EV_TICK when
;  it has something to show (MT_TOPEN); the window shows 19 rows and 78
;  columns of its 25 x 80, following its cursor, and closes when it ends.
;
;  Drawn with TERM.FNT (all of code page 437) straight to the screen, by
;  CLAUDE.COM's cell (claude/CELL.INC).  Without TERM.FNT, or with no room
;  for it, the task comes to the front instead, as without windows.
;
;  T5b: a program that publishes its screen (MT_PUB: its own cells and
;  font) is drawn from those instead, with its font, the view following
;  its cursor as if it were a row lower (a status line under it stays in
;  view); no Full screen for it (its window is its screen).
;
;  T5d: what scrolled (the task's screen, or the view) is moved on the
;  screen, not drawn again (scrl); a published screen's font is copied
;  in, every code with a glyph, and drawn the short way (cells .fast).
; =====================================================================
%include "UIAPI.INC"
%include "MTAPI.INC"
%include "WINPOS.INC"
RUN_API equ 9                           ; (EV_CLOSE: its close box)
RUN_FLAGS equ RF_WIN                    ; (a window beside others)
        org     RUN_ORG

VSEG    equ 0B800h
FONT    equ 0                           ; the block (fseg): TERM.FNT's 4,096
SHD     equ 4096                        ;  bytes, the shadow (each cell on the
BUF     equ SHD + 25 * 80 * 2           ;  window as drawn), MT_TROWS's copy,
PFONT   equ BUF + 25 * 80 * 2           ;  a published screen's font (T5d:
BLKLEN  equ PFONT + 256 * 16            ;  all 256 codes, pubset)
NOCELL  equ 0FFFFh                      ; (a shadow cell to draw again)
QLEN    equ 16                          ; keys kept while the task's ring is full

start:  mov     di, arg                 ; "task count"
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, arg
        call    num
        mov     [task], al
        call    num
        mov     [gen], al
        mov     ax, 0F000h + MT_WIN     ; (a window .RUN's session: else MT
        stc                             ;  isn't there, or this was started
        int     21h                     ;  by hand)
        jc      .bad
        mov     ax, 0F000h + MT_TOPEN   ; its EV_TICKs
        mov     cl, [gen]
        call    mtc
        jc      .bad
        mov     bx, (BLKLEN + 15) / 16
        call    UI_ALLOC
        jc      .front
        mov     [fseg], ax
        call    font                    ; TERM.FNT
        jc      .front
        call    name                    ; the title: its program's name
        WIN_STAGGER                     ; (a second one not right over it)
        call    geom
        mov     si, win
        call    UI_WOPEN                ; (w_draw draws the rest)
.loop:  call    UI_EVENT
        cmp     ax, EV_TICK             ; (the events first: UI_DISPATCH would
        je      .tick                   ;  take 12h for Ctrl-R)
        cmp     ax, EV_CLICK
        je      .clk
        cmp     ax, EV_CLOSE
        je      .cls
        cmp     ax, EV_RCLICK
        je      .rcl
        cmp     ax, EV_MOVED            ; (moved or resized: drawn there
        je      .loop                   ;  already, w_draw)
        cmp     ax, EV_SIZE
        je      .loop
        call    key
        jmp     .loop
.clk:   call    click
        jmp     .loop
.rcl:   call    rclick
        jmp     .loop
.cls:   call    close
        jmp     .loop
.tick:  call    tick
        jnc     .loop
        call    UI_WCLOSE               ; it ended
        xor     ax, ax
        ret
.front: call    full                    ; (no window after all: in front)
.bad:   mov     ax, 1
        ret

; its close box (EV_CLOSE): asked in the band, then its task ended
; (MT_KILL, as TASKS.RUN's); the window closes at the tick that sees it
; gone, as at EXIT.  ESC there: as it was, nothing sent to the task
close:  mov     di, askb
        mov     si, s_end
        call    UI_SBSTR
        mov     si, title
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, askb
        call    UI_ASK
        jc      .x
        call    gone                    ; (ended meanwhile, its number maybe
        jc      .x                      ;  another's now: not that one)
        mov     ax, 0F000h + MT_KILL
        call    mtc
.x:     ret

; a decimal number at SI (blanks before it skipped) -> AL
num:    xor     ax, ax
.b:     cmp     byte [si], ' '
        jne     .l
        inc     si
        jmp     .b
.l:     mov     cl, [si]
        sub     cl, '0'
        cmp     cl, 9
        ja      .x
        inc     si
        mov     ah, 10
        mul     ah
        add     al, cl
        jmp     .l
.x:     ret

; TERM.FNT (UI_FINDAPP's) into the block's first 4 KB.  CF if not there
font:   mov     si, s_fnt
        call    UI_FINDAPP              ; SI = its path
        jc      .x
        mov     dx, si
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     bx, ax
        push    ds
        mov     ds, [fseg]
        mov     dx, FONT
        mov     cx, 4097                ; (one more: a longer file isn't it)
        mov     ah, 3Fh
        int     21h
        pop     ds
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
        jc      .x
        cmp     ax, 4096                ; (all of it, or not at all)
        jne     .no
        clc
.x:     ret
.no:    stc
        ret

; the window's title: the task's program's name (MT_LIST's record, read
; into the shadow's room for a moment)
name:   push    es
        mov     es, [fseg]
        mov     di, SHD
        mov     cx, MT_TASKS
        mov     ax, 0F000h + MT_LIST
        int     21h
        mov     si, SHD
        mov     di, title
.r:     jcxz    .x
        mov     al, [es:si+TR_ID]
        cmp     al, [task]
        je      .n
        add     si, MT_REC
        loop    .r
        jmp     short .x
.n:     add     si, TR_NAME
        mov     cx, TR_NAMELEN
.c:     mov     al, [es:si]
        or      al, al
        jz      .x
        mov     [di], al
        inc     si
        inc     di
        loop    .c
.x:     mov     byte [di], 0
        pop     es
        ret

; where the cells go, inside the window as it is now: x0 = the first byte
; column, cols of them, y0 = the first row's pixel row, rows of them (78
; and 19 at most: the core keeps a window on the screen, above the band)
geom:   mov     ax, [win+W_COL]
        inc     ax
        mov     [x0], ax
        mov     ax, [win+W_W]
        sub     ax, 2
        mov     [cols], ax
        mov     ax, [win+W_Y]
        add     ax, W_TOP
        mov     [y0], ax
        mov     ax, [win+W_H]
        sub     ax, W_TOP + 4
        jns     .h
        xor     ax, ax
.h:     shr     ax, 4
        jnz     .r
        inc     ax
.r:     mov     [rows], ax
        ret

; the window's contents (W_DRAW: after it opens, moves, is resized or
; uncovered): everything drawn again at the next look, which is now
w_draw: push    es
        push    ds
        pop     es
        call    geom
        call    unshade
        mov     byte [curon], 0
        call    show
        pop     es
        ret

; every shadow cell to be drawn again
unshade:
        push    es
        push    di
        push    cx
        mov     es, [fseg]
        mov     di, SHD
        mov     cx, 25 * 80
        mov     ax, NOCELL
        rep     stosw
        pop     cx
        pop     di
        pop     es
        ret

; EV_TICK: the task ended (CF), or its screen to show
tick:   call    gone
        jc      .end
        call    flush                   ; the keys kept, if there is room now
        call    show
        clc
.end:   ret

; its task ended (free, or its number given again)?  CF if so
gone:   mov     ax, 0F000h + MT_EXIT
        call    mtc
        jc      .y
        or      al, al
        jz      .y
        cmp     ah, [gen]
        jne     .y
        cmp     cl, [gen]
        je      .y
        clc
        ret
.y:     stc
        ret

; its screen, as MT keeps it, in the window: the view following its
; cursor, only the cells that changed drawn.  Nothing while it is in front
; (full screen), or with its pages gone; a note instead when it is in a
; graphics mode or frozen (it writes the screen itself): a key then brings
; it to the front (T3)
show:   push    es
        mov     es, [fseg]
        mov     di, BUF
        mov     ax, 0F000h + MT_TROWS
        mov     dx, 8000h               ; (T5b: a published screen's cells)
        mov     cx, 25
        call    mtc
        pop     es
        jc      .x
        mov     [tdl], dl               ; (16: its program took the mouse, T4)
        call    pubset
        mov     byte [nrows], 25
        test    dl, 32                  ; (T5b: its cells, its rows in CH)
        jz      .pg
        mov     [nrows], ch
        mov     byte [note], 0
        jmp     short .s
.pg:    test    dl, 8 | 4               ; (in front, or its pages gone)
        jnz     .no
        mov     si, s_ngfx
        test    dl, 2                   ; (nothing copied: a graphics mode)
        jz      .f
        cmp     ch, 4
        jae     .nt
.no:    mov     byte [note], 0          ; (a key then is its own again)
        jmp     .x
.f:     mov     si, s_nfz
        test    dl, 1                   ; (VF_DIRECT: not run behind)
        jnz     .nt
        mov     byte [note], 0
        jmp     short .s
.nt:    call    selclr                  ; (no selection on a note, nor a paste:
        cmp     word [pseg], 0          ;  not typed into what comes after it)
        je      .nn
        push    si
        call    pfree
        pop     si
.nn:    call    mknote
        xor     bx, bx
        mov     cx, 80
.s:     mov     byte [nocur], 1         ; (T5b: FFFFh, no cursor: the view
        cmp     bx, 0FFFFh              ;  where it was)
        je      .h
        test    bh, 80h                 ; (T5d: hidden, where it is told: the
        jz      .v                      ;  view follows it, no mark; Claude
        and     bh, 7Fh                 ;  Code's is hidden)
        jmp     short .w
.v:     mov     byte [nocur], 0
.w:     mov     [cur], bx
.h:     mov     bx, [cur]
        xor     ch, ch
        cmp     cx, [ncols]             ; (its columns changed: its positions
        je      .sc                     ;  no more the selection's)
        call    selclr
.sc:    mov     [ncols], cx
        ; the view: as little moved as keeps the cursor in it (a published
        ; screen's: the row under it too, T5b)
        mov     ax, [top]
        mov     dl, bh                  ; (the cursor's row)
        xor     dh, dh
        cmp     dx, ax
        jae     .t0
        mov     ax, dx
.t0:    test    byte [tdl], 32
        jz      .t1
        inc     dx
        cmp     dl, [nrows]
        jb      .t1
        dec     dx
.t1:    mov     cx, [rows]
        add     cx, ax
        cmp     dx, cx
        jb      .t2
        mov     ax, dx
        sub     ax, [rows]
        inc     ax
.t2:    mov     cl, [nrows]             ; (and none past its last row)
        xor     ch, ch
        sub     cx, [rows]
        jae     .t2a
        xor     cx, cx
.t2a:   cmp     ax, cx
        jbe     .t3
        mov     ax, cx
.t3:    mov     cx, ax
        mov     ax, [left]
        mov     dl, [cur]               ; (its column)
        xor     dh, dh
        cmp     dx, ax
        jae     .l1
        mov     ax, dx
.l1:    mov     bx, [cols]
        add     bx, ax
        cmp     dx, bx
        jb      .l2
        mov     ax, dx
        sub     ax, [cols]
        inc     ax
.l2:    mov     bx, [ncols]
        sub     bx, [cols]
        jae     .l3
        xor     bx, bx
.l3:    cmp     ax, bx
        jbe     .l4
        mov     ax, bx
.l4:    cmp     ax, [left]
        jne     .new
        cmp     cx, [top]
        je      .same
        mov     dx, [sa]                ; (only the rows: what is drawn moves
        cmp     dx, [sb]                ;  with them, scrl; T5d.  Not with a
        jb      .new                    ;  selection: its highlight goes by
        mov     [top], cx               ;  its positions)
        jmp     short .same
.new:   mov     [left], ax
        mov     [top], cx
        call    unshade                 ; (moved: all of it again)
        mov     byte [curon], 0
.same:  cmp     byte [curon], 0         ; the cursor's cell drawn again (its
        je      .d                      ;  mark off)
        mov     ax, [curat]
        push    es
        mov     es, [fseg]
        mov     di, ax
        mov     word [es:di], NOCELL
        pop     es
        mov     byte [curon], 0
.d:     call    scrl
        call    cells
        call    cursor
.x:     ret

; T5d: the window's rows as drawn moved up k (the task scrolled, or the
; view moved down): the shadow's row k (1 to rows - 1) the view's new row
; 0, and of the new rows 1 to rows - 1 - k at least half the shadow's k
; lower (not all: a status line under them may stay, as CLAUDE's).  Those
; rows moved up on the screen and in the shadow, the k below them left
; for cells to draw (as any that differ: cells compares).  Not
; with a selection (it stays on its positions), nor with the window's
; columns past the task's (40)
scrl:   mov     ax, [sa]
        cmp     ax, [sb]
        jb      .x
        mov     ax, [left]
        add     ax, [cols]
        cmp     ax, [ncols]
        ja      .x
        cmp     word [rows], 2
        jb      .x
        mov     ax, [top]               ; (the view's row 0 in MT's copy)
        mul     word [ncols]
        add     ax, [left]
        shl     ax, 1
        add     ax, BUF
        push    ds
        push    es
        push    bp
        mov     [cs:c_at], ax
        mov     ax, [fseg]
        mov     ds, ax
        mov     es, ax
        mov     si, [cs:c_at]           ; (row 0 as drawn: nothing moved)
        mov     di, SHD
        mov     cx, [cs:cols]
        repe    cmpsw
        je      .n
        mov     bp, 1                   ; BP: k
.k:     mov     si, [cs:c_at]
        mov     ax, bp
        mov     dx, 160
        mul     dx
        add     ax, SHD
        mov     di, ax
        mov     cx, [cs:cols]
        repe    cmpsw
        je      .v
.nk:    inc     bp
        cmp     bp, [cs:rows]
        jb      .k
        jmp     .n
.v:     mov     ax, [cs:rows]           ; (the rows below it)
        dec     ax
        sub     ax, bp
        jz      .m
        mov     [cs:r_n], ax
        mov     ax, [cs:ncols]
        shl     ax, 1
        mov     [cs:stride], ax         ; (cells sets it again)
        mov     ax, bp
        mov     dx, 160
        mul     dx
        add     ax, SHD                 ; (AX: the shadow's row i + k, BX:
        mov     bx, [cs:c_at]           ;  the new row i, DX: those alike)
        xor     dx, dx
.vl:    add     ax, 160
        add     bx, [cs:stride]
        mov     si, bx
        mov     di, ax
        mov     cx, [cs:cols]
        repe    cmpsw
        jne     .vn
        inc     dx
.vn:    dec     word [cs:r_n]
        jnz     .vl
        mov     ax, [cs:rows]
        dec     ax
        sub     ax, bp
        shr     ax, 1
        cmp     dx, ax
        jb      .nk
.m:     mov     ax, bp                  ; the shadow: rows k on to 0 on (the
        mov     dx, 160                 ;  k below left as they were, as on
        mul     dx                      ;  the screen)
        push    ax                      ; (k x 160)
        mov     si, ax
        add     si, SHD
        mov     di, SHD
        mov     ax, [cs:rows]
        sub     ax, bp
        mov     cx, 80
        mul     cx
        mov     cx, ax
        rep     movsw
        pop     dx                      ; (DX: k x 160)
        mov     ax, VSEG                ; the screen: in each bank, its lines
        mov     ds, ax                  ;  ((rows - k) x 4 of them) from k x 4
        mov     es, ax                  ;  lines below, the window's columns
        shl     dx, 1                   ; (DX: k x 320, the source's offset)
        mov     ax, [cs:rows]
        sub     ax, bp
        shl     ax, 2
        mov     [cs:r_n], ax
        mov     ax, [cs:y0]
        mov     bx, 20
        push    dx
        mul     bx
        pop     dx
        add     ax, [cs:x0]
        mov     bx, ax                  ; (BX: the window's first cell)
        mov     bp, 4
.b:     mov     di, bx
        mov     ax, [cs:r_n]
.l:     mov     si, di
        add     si, dx
        push    di
        mov     cx, [cs:cols]
        shr     cx, 1
        rep     movsw
        adc     cx, cx
        rep     movsb
        pop     di
        add     di, 80
        dec     ax
        jnz     .l
        add     bx, 2000h
        dec     bp
        jnz     .b
.n:     pop     bp
        pop     es
        pop     ds
.x:     ret

; the window's cells from MT's copy where they differ from the shadow
; (those selected inverse)
cells:  push    ds
        push    es
        push    bp
        mov     ax, [top]               ; (BP: the row's first position, as
        mov     dx, 80                  ;  sa and sb count them)
        mul     dx
        mov     bp, ax
        mov     ax, VSEG
        mov     es, ax
        mov     ax, [rows]
        mov     [cs:r_n], ax
        mov     ax, [cols]
        mov     [cs:c_n], ax
        mov     ax, [ncols]
        shl     ax, 1
        mov     [cs:stride], ax
        mov     ax, [top]               ; (MT's copy: the view's first cell)
        mul     word [ncols]
        add     ax, [left]
        shl     ax, 1
        add     ax, BUF
        mov     si, ax
        mov     bx, SHD
        mov     ax, [y0]                ; (the screen: the window's first cell,
        mov     dx, 20                  ;  y * 20 + byte column, y a multiple
        mul     dx                      ;  of 4)
        add     ax, [x0]
        mov     di, ax
        mov     ax, [left]
        mov     [cs:c_at], ax
        mov     word [cs:cblank], 0720h ; (past its columns: a blank)
        mov     word [cs:cfn], attr
        test    byte [cs:tdl], 32       ; (T5b: a published screen's cells)
        jz      .k
        mov     word [cs:cblank], 0020h
        mov     word [cs:cfn], cnone    ; (its font has every code: pubset)
        mov     ax, [sa]                ; T5d: the short way, with no
        cmp     ax, [sb]                ;  selection and none of the window's
        jb      .k                      ;  columns past its own
        mov     ax, [left]
        add     ax, [cols]
        cmp     ax, [ncols]
        ja      .k
        mov     ds, [cs:fseg]
.frow:  push    si
        push    bx
        push    di
        mov     cx, [cs:c_n]
.fc:    mov     ax, [si]
        cmp     ax, [bx]
        je      .fn
        mov     [bx], ax
        call    cell
.fn:    add     si, 2
        add     bx, 2
        inc     di
        loop    .fc
        pop     di
        pop     bx
        pop     si
        add     si, [cs:stride]
        add     bx, 160
        add     di, 16 * 20
        dec     word [cs:r_n]
        jnz     .frow
        jmp     short .end
.k:     mov     ds, [cs:fseg]
.row:   push    si
        push    bx
        push    di
        mov     cx, [cs:c_n]
        mov     dx, [cs:c_at]           ; (DX: the column in its screen)
.cell:  mov     ax, [cs:cblank]         ; (past its columns: blank)
        cmp     dx, [cs:ncols]
        jae     .v
        mov     ax, [si]
.v:     cmp     ax, [bx]
        je      .nx
        mov     [bx], ax
        call    word [cs:cfn]
        push    dx
        cmp     dx, [cs:ncols]          ; (past its columns: never selected)
        jae     .ns
        add     dx, bp
        cmp     dx, [cs:sa]
        jb      .ns
        cmp     dx, [cs:sb]
        jae     .ns
        xor     ah, 1                   ; (selected)
.ns:    pop     dx
        call    cell                    ; (its font in the block: DS)
.nx:    add     si, 2
        add     bx, 2
        inc     di
        inc     dx
        loop    .cell
        pop     di
        pop     bx
        pop     si
        add     si, [cs:stride]
        add     bx, 160
        add     di, 16 * 20
        add     bp, 80
        dec     word [cs:r_n]
        jnz     .row
.end:   pop     bp
        pop     es
        pop     ds
cnone:  ret

; AX = a cell -> AH = its attribute for cell: inverse (1) when its
; background is brighter than its foreground (70h, 71h: as a monochrome
; screen shows them), underlined (2) for x1h and x9h with a black
; background (the monochrome adapter's); both colours the same, the
; foreground not bright (00h, 77h; not 08h, dark grey): hidden, AL a blank
; of the background's
attr:   push    bx
        mov     bx, ax                  ; (BH: the colours)
        mov     bl, bh
        shr     bl, 4
        and     bx, 0707h               ; BL background, BH foreground
        cmp     bl, bh
        mov     bl, 0
        jb      .u
        ja      .i
        test    ah, 08h                 ; (bright: not hidden)
        jnz     .u
        mov     al, ' '                 ; (hidden)
        or      bh, bh
        jz      .u
.i:     mov     bl, 1
.u:     and     ah, 77h                 ; (bright and blink aside)
        cmp     ah, 1
        jne     .x
        or      bl, 2
.x:     mov     ah, bl
        pop     bx
        ret

; T5b: the font for what MT_TROWS gave (DL 32: a published screen's cells,
; its own font from its descriptor, MT_PUB's; else TERM.FNT): when that
; changes, all of it drawn again, the view from row 0 (then following the
; cursor).  T5d: a published one copied into PFONT (pcopy), so cell finds
; it in the block as TERM.FNT.  All kept but AX, SI, DI
pubset: push    bx
        push    cx
        push    es
        mov     ax, [fseg]              ; AX:SI the font, as cell finds its
        mov     si, FONT                ;  glyphs (code x 16 on), CL its first
        xor     cx, cx                  ;  code, CH its end (TERM.FNT: all)
        test    dl, 32
        jz      .f
        push    dx
        mov     ax, 0F000h + MT_PUB
        mov     cl, 1
        call    mtc
        pop     dx
        mov     ax, [fseg]
        mov     si, FONT
        mov     cx, 0
        jc      .f
        mov     cx, [es:di + PB_FIRST]  ; (PB_FIRST, PB_GEND)
        mov     ax, [es:di + PB_XLAT]
        mov     [pxl], ax
        mov     ax, [es:di + PB_XLAT + 2]
        mov     [pxl + 2], ax
        mov     si, [es:di + PB_FONT]
        mov     ax, [es:di + PB_FONT + 2]
        mov     bl, cl
        xor     bh, bh
        shl     bx, 4
        sub     si, bx                  ; (its first code's glyph first)
.f:     cmp     ax, [pfs + 2]
        jne     .n
        cmp     si, [pfs]
        jne     .n
        cmp     cx, [pfg]
        je      .x
.n:     mov     [pfs + 2], ax
        mov     [pfs], si
        mov     [pfg], cx
        mov     word [cfont], FONT
        jcxz    .t                      ; (TERM.FNT)
        call    pcopy
        mov     word [cfont], PFONT
.t:     mov     word [top], 0           ; (another screen: its view afresh)
        call    unshade
        mov     byte [curon], 0
.x:     pop     es
        pop     cx
        pop     bx
        ret

; T5d: the published font (AX:SI less its first code CL's 16 x CL; CH its
; end) into PFONT, all 256 codes: below its first its blank's (20h), from
; its end on its '?' (as T5b's drawing had them).  All kept
pcopy:  pusha
        push    ds
        push    es
        mov     es, [fseg]
        mov     ds, ax
        mov     di, PFONT
        xor     bx, bx                  ; (BL: the code)
.c:     mov     al, bl
        cmp     al, cl
        jae     .g
        mov     al, 20h
.g:     cmp     al, ch
        jb      .h
        mov     al, '?'
.h:     xor     ah, ah
        shl     ax, 4
        push    si
        push    cx
        add     si, ax
        mov     cx, 8
        rep     movsw
        pop     cx
        pop     si
        inc     bl
        jnz     .c
        pop     es
        pop     ds
        popa
        ret

; the cursor's mark (its cell's bottom two rows inverted), where it is
; when it is in the window
cursor: cmp     byte [note], 0          ; (none on a note, nor hidden: T5b)
        jne     .x
        cmp     byte [nocur], 0
        jne     .x
        mov     al, [cur + 1]           ; its row in the view?
        xor     ah, ah
        sub     ax, [top]
        jb      .x
        cmp     ax, [rows]
        jae     .x
        mov     si, ax                  ; (SI: its row in the window)
        mov     al, [cur]
        xor     ah, ah
        sub     ax, [left]
        jb      .x
        cmp     ax, [cols]
        jae     .x
        mov     bx, ax                  ; (BX: its column in the window)
        mov     ax, si
        mov     cx, 160
        mul     cx
        add     ax, bx
        add     ax, bx
        add     ax, SHD
        mov     [curat], ax             ; (its shadow cell: drawn again first
        mov     ax, si                  ;  next time)
        shl     ax, 4
        add     ax, [y0]
        mov     cx, 20
        mul     cx
        add     ax, [x0]
        add     ax, bx
        mov     di, ax
        push    es
        mov     ax, VSEG
        mov     es, ax
        not     byte [es:di + 4000h + 240]      ; (glyph rows 14 and 15)
        not     byte [es:di + 6000h + 240]
        pop     es
        mov     byte [curon], 1
.x:     ret

; a right click: the menu of what applies (RMENU.INC, Write's): Copy with a
; selection, Paste with something to paste, Full screen but for a published
; screen (T5b: none, with neither of the others: no menu).  The item
; chosen is taken as its key (Full screen's K_NONE)
RM_TXT      equ 4
rclick: mov     al, 0
        mov     dx, [sb]
        cmp     dx, [sa]
        jbe     .m
        mov     al, RM_SEL
.m:     test    byte [tdl], 32
        jnz     .p
        or      al, RM_TXT
        jmp     short .r
.p:     or      al, al
        jnz     .r
        pusha
        mov     al, 2                   ; (what the clipboard holds)
        call    UI_CLIP
        or      cx, cx
        popa
        jz      cursor.x
.r:     mov     si, items
        call    rmenu
        jc      cursor.x

; a key typed in the window: to the task (MT_TKEY), after those kept (and
; a paste's); kept while its ring is full (QLEN at most: a beep past them).
; With a note up, or K_NONE (the menu's Full screen), the task to the front
; instead (full screen); CODE-C with a selection copies it, CODE-V with
; something to paste pastes (T4)
key:    cmp     byte [note], 0
        jne     full
        cmp     ax, K_NONE
        je      full
        cmp     ax, K_CODE_C
        jne     .v
        mov     bx, [sb]
        cmp     bx, [sa]
        ja      copy
.v:     cmp     ax, K_CODE_V
        jne     .t
        push    ax
        mov     al, 2                   ; (what the clipboard holds)
        call    UI_CLIP
        pop     ax
        or      cx, cx
        jnz     paste
.t:     mov     bx, [sb]                ; typing: the selection gone, at once
        cmp     bx, [sa]
        jbe     .s
        push    ax
        call    selclr
        call    show
        pop     ax
.s:     cmp     word [pseg], 0
        jne     .q
        cmp     byte [qn], 0
        jne     .q
        call    send
        jnc     .x
.q:     cmp     byte [qn], QLEN
        jb      .k
        jmp     UI_BEEP
.k:     mov     bl, [qn]
        xor     bh, bh
        shl     bx, 1
        mov     [q + bx], ax
        inc     byte [qn]
.x:     ret

; the task to the front, full screen (a key on a note; the menu's Full
; screen)
full:   mov     byte [note], 0          ; (TERM doesn't run while it's in
        mov     ax, 0F000h + MT_FRONT   ;  front: a key after it's back is its)
        call    mtc
        jnc     .x
        jmp     UI_BEEP                 ; (refused: its window is its screen,
.x:     ret                             ;  T5b)

; the note SI in place of its screen: BUF blank, the note on its first row
mknote: mov     byte [note], 1
        push    es
        mov     es, [fseg]
        mov     di, BUF
        mov     ax, 0720h
        mov     cx, 25 * 80
        rep     stosw
        mov     di, BUF + 2
.c:     lodsb
        or      al, al
        jz      .x
        stosw                           ; (AH: 07h still)
        jmp     .c
.x:     pop     es
        ret

; the keys kept, in turn, while the ring takes them: a paste's first
flush:  call    feed
        jc      .x
        cmp     byte [qn], 0
        je      .x
        mov     ax, [q]
        call    send
        jc      .x
        mov     si, q + 2
        mov     di, q
        mov     cx, QLEN - 1
        push    es
        push    ds
        pop     es
        rep     movsw
        pop     es
        dec     byte [qn]
        jmp     flush
.x:     ret

; key AX to the task: CF if its ring is full (or it is gone)
send:   push    ax
        mov     cx, ax
        mov     ax, 0F000h + MT_TKEY
        call    mtc
        pop     ax
        ret

; MT call AX (AH F0h) for its task: BL = it, CF set first (MTAPI.INC)
mtc:    mov     bl, [task]
        stc
        int     21h
        ret

; ---------------------------------------------------------------------
;  T4: the mouse, select, copy and paste.  A selection is of positions
;  in its screen (row * 80 + column, sa to sb, sb past the last), not in
;  the window, so the view moving keeps it
; ---------------------------------------------------------------------

; a click in the cells: its program's, if it took the mouse (MT_TROWS's
; 16: it reset INT 33h) and Shift isn't held: MT_TMOUSE as the button
; goes down, while it's held, as it's let go; else a selection, from the
; press to where it's let go (as a drag in Write: UI_MOUSE till then)
click:  call    UI_KEYSHIFT
        mov     [kshf], al
        xor     si, si
        call    cellat
        jc      .x
        test    byte [kshf], 3          ; (Shift)
        jnz     .sel
        test    byte [tdl], 16
        jz      .sel
        mov     al, 1                   ; its program's
.p:     call    tmouse
        push    dx
        call    show                    ; (what it draws meanwhile)
        pop     dx
        call    UI_MOUSE
        jc      .u
        test    al, 1
        jz      .u
        mov     si, 1
        call    cellat                  ; (CF: a note up now)
        jc      .u
        mov     al, 1
        jmp     .p
.u:     xor     al, al                  ; (let go there)
        jmp     tmouse
.sel:   push    ax
        call    selclr
        call    show
        pop     ax
        mov     [prs], ax
.d:     call    UI_MOUSE
        jc      .x
        test    al, 1
        jz      .x                      ; (let go)
        mov     si, 1
        call    cellat
        jc      .x
        mov     bx, [prs]
        cmp     ax, bx                  ; (back where it began: none)
        je      .o
        jae     .b
        xchg    ax, bx
.b:     inc     ax                      ; BX to AX: press and end both in it
.o:     cmp     bx, [sa]
        jne     .n
        cmp     ax, [sb]
        je      .d
.n:     call    selclr
        mov     [sa], bx
        mov     [sb], ax
        call    unrows
        call    show
        jmp     .d
.x:     ret

; BX, CX (the mouse's x, y) -> DL its column, DH its row in the task's
; screen, AX = DH * 80 + DL.  CF if it isn't on a cell shown (or a note is
; up); with SI 1 the nearest one shown instead (a drag past the edge)
cellat: cmp     byte [note], 0
        jne     .no
        push    di
        mov     ax, bx
        shr     ax, 3
        sub     ax, [x0]
        mov     di, [cols]
        call    .in
        jc      .o
        add     ax, [left]
        cmp     ax, [ncols]             ; (40 columns: none past them)
        jb      .c
        or      si, si
        stc
        jz      .o
        mov     ax, [ncols]
        dec     ax
.c:     mov     dl, al
        mov     ax, cx
        sub     ax, [y0]
        sar     ax, 4
        mov     di, [rows]
        call    .in
        jc      .o
        add     ax, [top]
        mov     dh, al
        mov     al, 80
        mul     dh
        add     al, dl
        adc     ah, 0
        pop     di
        clc
        ret
.o:     pop     di
.no:    stc
        ret
.in:    or      ax, ax                  ; AX in 0 to DI - 1 (SI 1: made so)
        jns     .p
        xor     ax, ax
        jmp     short .ed
.p:     cmp     ax, di
        jb      .ok
        mov     ax, di
        dec     ax
.ed:    or      si, si
        jnz     .ok
        stc
        ret
.ok:    clc
        ret

; buttons AL at the cell DL, DH to the task's mouse (MT_TMOUSE: x the
; column * 8, * 16 in 40 columns; y the row * 8, as INT 33h's text
; modes).  All kept
tmouse: pusha
        mov     bh, al
        mov     al, dl
        xor     ah, ah
        shl     ax, 3
        cmp     word [ncols], 40
        ja      .w
        shl     ax, 1
.w:     mov     cx, ax
        mov     al, dh
        xor     ah, ah
        shl     ax, 3
        mov     dx, ax
        mov     ax, 0F000h + MT_TMOUSE
        call    mtc
        popa
        ret

; the selection gone (its rows drawn again at the next look).  All kept
selclr: push    ax
        push    bx
        mov     bx, [sa]
        mov     ax, [sb]
        call    unrows
        xor     ax, ax
        mov     [sa], ax
        mov     [sb], ax
        pop     bx
        pop     ax
        ret

; the window's rows that show positions BX to AX - 1 drawn again at the
; next look (their shadow).  All kept
unrows: cmp     ax, bx
        jbe     .x
        pusha
        push    es
        mov     es, [fseg]
        dec     ax
        mov     cl, 80
        div     cl
        mov     ch, al                  ; CH: the last row
        mov     ax, bx
        div     cl
        mov     cl, al                  ; CL: the first
.r:     mov     al, cl
        xor     ah, ah
        sub     ax, [top]
        jb      .n
        cmp     ax, [rows]
        jae     .n
        mov     bx, 160
        mul     bx
        add     ax, SHD
        mov     di, ax
        push    cx
        mov     cx, 80
        mov     ax, NOCELL
        rep     stosw
        pop     cx
.n:     inc     cl
        cmp     cl, ch
        jbe     .r
        pop     es
        popa
.x:     ret

; the selection's text to the clipboard (UI_CLIP): BUF's cells packed in
; place (a byte each, NUL as a blank, each row's trailing blanks dropped,
; an LF between rows: never ahead of what's still to read), then BUF
; fetched again (show)
copy:   mov     ax, [sb]
        dec     ax
        mov     cl, 80
        div     cl
        mov     [crow], ax              ; (the last cell: row, column)
        mov     ax, [sa]
        div     cl
        mov     dx, ax                  ; DL the row, DH its first column
        push    es
        mov     es, [fseg]
        mov     di, BUF
.r:     mov     al, dl
        mul     byte [ncols]
        add     al, dh
        adc     ah, 0
        shl     ax, 1
        add     ax, BUF
        mov     si, ax
        mov     cx, [ncols]             ; its last column
        dec     cx
        cmp     dl, [crow]
        jne     .l
        mov     cl, [crow + 1]
.l:     sub     cl, dh
        xor     ch, ch
        inc     cx
        mov     bp, di                  ; (its blanks back to here)
.c:     mov     al, [es:si]
        test    byte [tdl], 32          ; (T5b: a published screen's code)
        jz      .z
        call    ptext
.z:     or      al, al
        jnz     .s
        mov     al, ' '
.s:     stosb
        add     si, 2
        loop    .c
.t:     cmp     di, bp
        je      .e
        cmp     byte [es:di - 1], ' '
        jne     .e
        dec     di
        jmp     .t
.e:     cmp     dl, [crow]
        je      .put
        mov     al, 10
        stosb
        inc     dl
        xor     dh, dh
        jmp     .r
.put:   mov     cx, di
        mov     di, BUF
        sub     cx, di
        jcxz    .b                      ; (all blank: the clipboard kept)
        mov     al, 0
        call    UI_CLIP
        jnc     .y
.b:     call    UI_BEEP
.y:     pop     es
.x:     jmp     show

; T5b: AL = a published screen's code -> its text: one below its first a
; blank, 80h and up its table's (PB_XLAT; none, or 0 there: '?'), one from
; its end on '?'.  All kept but AL
ptext:  cmp     al, [pfg]
        jae     .h
        mov     al, ' '
        ret
.h:     cmp     al, 80h
        jb      .l
        push    es
        push    bx
        les     bx, [pxl]
        push    ax
        mov     ax, es
        or      ax, bx
        pop     ax
        jz      .q
        sub     al, 80h
        es xlatb
        or      al, al
        jnz     .y
.q:     mov     al, '?'
.y:     pop     bx
        pop     es
        ret
.l:     cmp     al, [pfg + 1]
        jb      .x
        mov     al, '?'
.x:     ret

; the clipboard typed to the task: into a block of its own (UI_ALLOC, as
; it holds 16 KB at most), fed as its ring takes it (feed: at once and at
; each tick); the keys typed meanwhile after it.  A beep if one is going
; on, keys typed before it still wait (they'd come after it), a note is
; up (it would be typed into what comes after it), or with no room
paste:  cmp     word [pseg], 0
        jne     .b
        cmp     byte [qn], 0
        jne     .b
        cmp     byte [note], 0
        jne     .b
        mov     al, 2
        call    UI_CLIP
        jcxz    .x
        mov     [plen], cx
        mov     bx, cx
        add     bx, 15
        shr     bx, 4
        call    UI_ALLOC
        jc      .b
        mov     [pseg], ax
        push    es
        mov     es, ax
        xor     di, di
        mov     cx, [plen]
        mov     al, 1
        call    UI_CLIP
        pop     es
        jc      .f
        mov     [plen], cx
        mov     word [ppos], 0
        call    selclr
        jmp     flush
.f:     call    pfree
.b:     jmp     UI_BEEP
.x:     ret

; the paste's next keys to the task while its ring takes them (a note
; going up ends it: show) -> CF if some are left (the keys typed after it
; wait)
feed:   cmp     word [pseg], 0
        je      .ok
.n:     mov     si, [ppos]
        cmp     si, [plen]
        jae     .end
        push    es
        mov     es, [pseg]
        mov     al, [es:si]
        mov     ah, [es:si - 1]         ; (the one before: CR LF one Return)
        pop     es
        cmp     al, 10
        jne     .cr
        or      si, si
        jz      .ret
        cmp     ah, 13
        je      .sk
.ret:   mov     ax, 1C0Dh               ; (LF, CR: Return)
        jmp     short .k
.cr:    cmp     al, 13
        je      .ret
        mov     ah, 0Fh                 ; (Tab: its scan code; the rest none)
        cmp     al, 9
        je      .k
        xor     ah, ah
.k:     call    send
        jc      .left
.sk:    inc     word [ppos]
        jmp     .n
.end:   call    pfree
.ok:    clc
        ret
.left:  stc
        ret

; the paste's block given back.  All kept but AX
pfree:  push    es
        mov     es, [pseg]
        call    UI_FREE
        pop     es
        mov     word [pseg], 0
        ret

%include "RMENU.INC"

; one character cell (CELL.INC): AL, AH = its attribute, DI = row * 320 +
; column (here: y * 20 + byte column), ES = VSEG; its glyph from DS:0
%define CELL_FSEG ds
%define CELL_FONT [cs:cfont]            ; (TERM.FNT's, or a published screen's
                                        ;  copied: PFONT, T5d)
%define CELL_FIRST 0
%define GLYPH_END 100h
%include "../claude/CELL.INC"

s_fnt       db 'TERM.FNT', 0
s_end       db 'Close: Confirm to end ', 0
s_ngfx      db 'In a graphics mode: a key here shows it (or CODE-Tab)', 0
s_nfz       db 'It writes the screen itself: a key here shows it (FULL= for it)', 0
items       dw s_copy, K_CODE_C, RM_SEL, s_paste, K_CODE_V, RM_CLIP, s_full, K_NONE, RM_TXT, 0
s_copy      db 'Copy           CODE-C', 0
s_paste     db 'Paste          CODE-V', 0
s_full      db 'Full screen    CODE-Tab', 0
win:        dw 0, SCR_TOP, 80, SCR_BAND_Y - SCR_TOP
            dw title, w_draw, WF_MOVE | WF_SIZE | WF_CLOSE
top         dw 0                        ; the view: its screen's first row and
left        dw 0                        ;  column in the window

section .bss
task        resb 1
gen         resb 1
note        resb 1                      ; 1: a note shown, not its screen
curon       resb 1                      ; 1: the cursor's mark is drawn, at
curat       resw 1                      ;  this shadow cell
qn          resb 1
fseg        resw 1
x0          resw 1
cols        resw 1
y0          resw 1
rows        resw 1
ncols       resw 1                      ; its screen's columns (40 or 80)
cur         resw 1                      ; its cursor: column, row
r_n         resw 1
c_n         resw 1
c_at        resw 1
stride      resw 1
q           resw QLEN
tdl         resb 1                      ; MT_TROWS's DL (16: the mouse its)
kshf        resb 1                      ; (a click's shift state)
nrows       resb 1                      ; its screen's rows (25; a published
nocur       resb 1                      ;  one's PB_ROWS), 1: no cursor (T5b)
pfs         resd 1                      ; the font's: where (TERM.FNT's; T5b:
cfont       resw 1                      ;  a published one's), where cell
pfg         resw 1                      ;  finds it (T5d: PFONT for that), its
pxl         resd 1                      ;  first code, its end; PB_XLAT
cblank      resw 1                      ; (cells: past its columns, the
cfn         resw 1                      ;  attribute's routine)
sa          resw 1                      ; the selection: its first position,
sb          resw 1                      ;  the one past its last (T4)
prs         resw 1                      ; (a drag's press)
crow        resw 1                      ; (copy: the last cell's row, column)
pseg        resw 1                      ; a paste: its block (0: none), the
ppos        resw 1                      ;  next byte, how many
plen        resw 1
rm_buf      resw 3                      ; the right click's menu (RMENU.INC)
rm_key      resw 3
arg         resb 16
title       resb 16
askb        resb 40                     ; (close's question)
run_bss_end:
