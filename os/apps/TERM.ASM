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
; =====================================================================
%include "UIAPI.INC"
%include "MTAPI.INC"
%include "WINPOS.INC"
RUN_API equ 8
RUN_FLAGS equ RF_WIN                    ; (a window beside others)
        org     RUN_ORG

VSEG    equ 0B800h
FONT    equ 0                           ; the block (fseg): TERM.FNT's 4,096
SHD     equ 4096                        ;  bytes, the shadow (each cell on the
BUF     equ SHD + 25 * 80 * 2           ;  window as drawn), MT_TROWS's copy
BLKLEN  equ BUF + 25 * 80 * 2
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
        mov     bl, [task]
        mov     cl, [gen]
        stc
        int     21h
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
        mov     byte [wopen], 1
.loop:  call    UI_EVENT
        cmp     ax, EV_TICK             ; (the events first: UI_DISPATCH would
        je      .tick                   ;  take 12h for Ctrl-R)
        cmp     ax, EV_CLICK
        je      .loop
        cmp     ax, EV_RCLICK
        je      .loop
        cmp     ax, EV_MOVED            ; (moved or resized: drawn there
        je      .loop                   ;  already, w_draw)
        cmp     ax, EV_SIZE
        je      .loop
        call    key
        jmp     .loop
.tick:  call    tick
        jnc     .loop
        call    UI_WCLOSE               ; it ended
        xor     ax, ax
        ret
.front: mov     ax, 0F000h + MT_FRONT   ; (no window after all: in front)
        mov     bl, [task]
        stc
        int     21h
.bad:   mov     ax, 1
        ret

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
; column, cols of them, y0 = the first row's pixel row, rows of them
geom:   mov     ax, [win+W_COL]
        inc     ax
        mov     [x0], ax
        mov     ax, [win+W_W]
        sub     ax, 2
        cmp     ax, 80
        jbe     .c
        mov     ax, 80
.c:     mov     [cols], ax
        mov     ax, [win+W_Y]
        add     ax, W_TOP
        mov     [y0], ax
        mov     ax, [win+W_H]
        sub     ax, W_TOP + 4
        jns     .h
        xor     ax, ax
.h:     shr     ax, 4
        jnz     .h1
        inc     ax
.h1:    cmp     ax, 25
        jbe     .r
        mov     ax, 25
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
tick:   mov     ax, 0F000h + MT_EXIT    ; ended (free, or its number given
        mov     bl, [task]              ;  again)?
        stc
        int     21h
        jc      .end
        or      al, al
        jz      .end
        cmp     ah, [gen]
        jne     .end
        cmp     cl, [gen]
        je      .end
        call    flush                   ; the keys kept, if there is room now
        call    show
        clc
        ret
.end:   stc
        ret

; its screen, as MT keeps it, in the window: the view following its
; cursor, only the cells that changed drawn (not while it is in front, or
; in a graphics mode: T3)
show:   push    es
        mov     es, [fseg]
        mov     di, BUF
        mov     ax, 0F000h + MT_TROWS
        mov     bl, [task]
        xor     dx, dx
        mov     cx, 25
        stc
        int     21h
        pop     es
        jc      .x
        test    dl, 8 | 2               ; (in front, or nothing copied)
        jnz     .x
        mov     [cur], bx
        xor     ch, ch
        mov     [ncols], cx
        ; the view: as little moved as keeps the cursor in it
        mov     ax, [top]
        mov     dl, bh                  ; (the cursor's row)
        xor     dh, dh
        cmp     dx, ax
        jae     .t1
        mov     ax, dx
.t1:    mov     cx, [rows]
        add     cx, ax
        cmp     dx, cx
        jb      .t2
        mov     ax, dx
        sub     ax, [rows]
        inc     ax
.t2:    mov     cx, 25                  ; (and none past row 24)
        sub     cx, [rows]
        cmp     ax, cx
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
.d:     call    cells
        call    cursor
.x:     ret

; the window's cells from MT's copy where they differ from the shadow
cells:  push    ds
        push    es
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
        mov     ds, [cs:fseg]
.row:   push    si
        push    bx
        push    di
        mov     cx, [cs:c_n]
        mov     dx, [cs:c_at]           ; (DX: the column in its screen)
.cell:  mov     ax, 0720h               ; (past its columns: blank)
        cmp     dx, [cs:ncols]
        jae     .v
        mov     ax, [si]
.v:     cmp     ax, [bx]
        je      .nx
        mov     [bx], ax
        call    attr
        call    cell
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
        dec     word [cs:r_n]
        jnz     .row
        pop     es
        pop     ds
        ret

; AX = a cell -> AH = its attribute for cell: inverse (1) when its
; background is brighter than its foreground (70h, 71h: as a monochrome
; screen shows them), underlined (2) for x1h and x9h with a black
; background (the monochrome adapter's); both colours the same (00h, 77h):
; hidden, AL a blank of the background's
attr:   push    bx
        mov     bx, ax                  ; (BH: the colours)
        mov     bl, bh
        shr     bl, 4
        and     bx, 0707h               ; BL background, BH foreground
        cmp     bl, bh
        mov     bl, 0
        jb      .u
        ja      .i
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

; the cursor's mark (its cell's bottom two rows inverted), where it is
; when it is in the window
cursor: mov     al, [cur + 1]           ; its row in the view?
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

; a key typed in the window: to the task (MT_TKEY), after those kept; kept
; while its ring is full (QLEN at most: a beep past them)
key:    cmp     byte [qn], 0
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

; the keys kept, in turn, while the ring takes them
flush:  cmp     byte [qn], 0
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
        mov     bl, [task]
        stc
        int     21h
        pop     ax
        ret

; one character cell (CELL.INC): AL, AH = its attribute, DI = row * 320 +
; column (here: y * 20 + byte column), ES = VSEG; its glyph from DS:0
%define CELL_FSEG ds
%define CELL_FONT FONT
%define CELL_FIRST 0
%define GLYPH_END 100h
%include "../claude/CELL.INC"

s_fnt       db 'TERM.FNT', 0
win:        dw 0, SCR_TOP, 80, SCR_BAND_Y - SCR_TOP
            dw title, w_draw, WF_MOVE | WF_SIZE
top         dw 0                        ; the view: its screen's first row and
left        dw 0                        ;  column in the window

section .bss
task        resb 1
gen         resb 1
wopen       resb 1
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
arg         resb 16
title       resb 16
run_bss_end:
