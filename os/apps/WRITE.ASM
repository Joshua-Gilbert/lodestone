; =====================================================================
;  WRITE.RUN - Write, the Lodestone text editor (in the spirit of GRiDWrite)
;  python3 mkrun.py apps/WRITE.ASM apps/WRITE.RUN
;
;  Opened by the Executive for Text, Source, Batch, Settings and Profile
;  files (the argument is the file's whole path), or with CODE-W for a new
;  file.  GRiDWrite's commands, verb first: press the command, make a
;  selection with the cursor keys or the mouse, then confirm with Return.
;
;    CODE-B Begin       restart the selection
;    CODE-D Duplicate   duplicate selected text (then point and confirm)
;    CODE-E Erase       erase selected text
;    CODE-F Find        find specified text
;    CODE-J Jump        move the cursor to a line
;    CODE-M Move        move selected text (then point and confirm)
;    CODE-O Options     automatic indent, tab width
;    CODE-Q Quit        save and exit
;    CODE-S Substitute  substitute specified text
;    CODE-T Transfer    save, write to another file, include a file
;    CODE-U Usage       characters, lines and room left
;    CODE-ESC / ESC     Cancel: exit without saving
;
;  The text lives in a gap buffer in a block of its own (up to 64 KB).
;  Lines end in LF inside; files are read and written with CR LF.  The
;  screen is drawn from a shadow copy, so a key redraws only the rows that
;  changed.
; =====================================================================
%include "UIAPI.INC"
RUN_API equ 4                           ; (as 0.4.3 shipped it)
        org     RUN_ORG

NROWS   equ 19                          ; text rows
TEXT_Y  equ 24
RULE_Y  equ 334
STAT_Y  equ 340
HSTEP   equ 20                          ; horizontal scroll step (columns)
ROWB    equ 160                         ; a row in the shadow: 80 chars, 80 marks
IOB     equ 1024                        ; file I/O chunk
M_EDIT  equ 0                           ; modes
M_SEL   equ 1                           ; making a selection
M_POINT equ 2                           ; pointing to a destination (Move, Duplicate)
M_FOUND equ 3                           ; showing what Find found

start:  mov     di, fname               ; the argument: the file to open
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, redraw
        call    UI_SETREDRAW
        mov     bx, 1000h               ; the text buffer: 64 KB, or what there is
        call    UI_ALLOC
        jnc     .buf
        cmp     bx, 100h                ; (less than 4 KB: not worth it)
        jb      .nomem
        call    UI_ALLOC
        jc      .nomem
.buf:   mov     [bseg], ax
        mov     ax, bx
        cmp     ax, 0FFFh
        jbe     .cap
        mov     ax, 0FFFh
.cap:   mov     cl, 4
        shl     ax, cl
        mov     [cap], ax
        mov     [gap_e], ax
        mov     word [gap_s], 0
        mov     word [nlines], 1
        mov     word [goal], 0FFFFh
        mov     byte [tabw], 8
        cmp     byte [fname], 0
        je      .new
        mov     si, fname
        call    load_file               ; (a file that isn't there: a new one)
        jnc     .new
        cmp     ax, 2
        je      .new
        mov     di, line                ; can't read it: say so and leave
        mov     si, s_cantread
        call    UI_SBSTR
        call    UI_SBERR
        mov     byte [di], 0
        call    redraw
        mov     si, line
        call    UI_MSG
        mov     ax, 1
        ret
.new:   mov     word [changed], 0
        mov     ax, 0
        call    gap_to
        call    center_view
        call    redraw
        call    edit_band
.loop:  call    update
        call    UI_EVENT
        call    do_key
        cmp     byte [quit], 0
        je      .loop
        xor     ax, ax
        ret
.nomem: mov     si, s_nomem
        call    UI_MSG
        mov     ax, 8
        ret

; ---------------------------------------------------------------------
;  the gap buffer (ES = [bseg] inside these)
; ---------------------------------------------------------------------
; -> AX = length of the text
textlen:
        mov     ax, [cap]
        sub     ax, [gap_e]
        add     ax, [gap_s]
        ret

; BX = position -> AL = its character
getc:   push    bx
        push    es
        mov     es, [bseg]
        cmp     bx, [gap_s]
        jb      .l
        add     bx, [gap_e]
        sub     bx, [gap_s]
.l:     mov     al, [es:bx]
        pop     es
        pop     bx
        ret

; ES:DI, CX bytes -> DX = line feeds in it (AX, CX, DI change)
count_lf:
        xor     dx, dx
        jcxz    .x
        mov     al, 10
.l:     repne   scasb
        jne     .x
        inc     dx
        jcxz    .x
        jmp     .l
.x:     ret

; the cursor (the gap) to position AX
gap_to: pusha
        push    ds
        push    es
        mov     es, [bseg]
        cmp     ax, [gap_s]
        je      .x
        jb      .back
        mov     cx, ax                  ; forward: [ge, ge+n) -> [gs, gs+n)
        sub     cx, [gap_s]
        push    cx
        mov     di, [gap_e]
        call    count_lf
        add     [curline], dx
        pop     cx
        mov     si, [gap_e]
        mov     di, [gap_s]
        add     [gap_s], cx
        add     [gap_e], cx
        push    es
        pop     ds
        rep     movsb
        jmp     .x
.back:  mov     cx, [gap_s]                ; back: [p, gs) -> [ge-n, ge)
        sub     cx, ax
        push    cx
        mov     di, ax
        call    count_lf
        sub     [curline], dx
        pop     cx
        mov     si, [gap_s]
        dec     si
        mov     di, [gap_e]
        dec     di
        sub     [gap_s], cx
        sub     [gap_e], cx
        push    es
        pop     ds
        std
        rep     movsb
        cld
.x:     pop     es
        pop     ds
        popa
        ret

; insert AL at the cursor.  CF if the buffer is full
ins_char:
        push    bx
        push    es
        mov     bx, [gap_s]
        cmp     bx, [gap_e]
        jae     .full
        mov     es, [bseg]
        mov     [es:bx], al
        inc     word [gap_s]
        mov     byte [changed], 1
        call    mark_dirty
        cmp     al, 10
        jne     .ok
        inc     word [curline]
        inc     word [nlines]
.ok:    pop     es
        pop     bx
        clc
        ret
.full:  pop     es
        pop     bx
        stc
        ret

; delete the character before the cursor (CF: none)
del_back:
        cmp     word [gap_s], 0
        je      .none
        push    bx
        dec     word [gap_s]
        mov     bx, [gap_s]
        push    es
        mov     es, [bseg]
        mov     al, [es:bx]
        pop     es
        pop     bx
        mov     byte [changed], 1
        call    mark_dirty
        cmp     al, 10
        jne     .ok
        dec     word [curline]
        dec     word [nlines]
.ok:    clc
        ret
.none:  stc
        ret

; delete the character at the cursor (CF: none)
del_fwd:
        mov     ax, [gap_e]
        cmp     ax, [cap]
        jae     .none
        push    bx
        mov     bx, ax
        push    es
        mov     es, [bseg]
        mov     al, [es:bx]
        pop     es
        pop     bx
        inc     word [gap_e]
        mov     byte [changed], 1
        call    mark_dirty
        cmp     al, 10
        jne     .ok
        dec     word [nlines]
.ok:    clc
        ret
.none:  stc
        ret

; a change at the cursor: AL = the character (a line end: every row)
mark_dirty:
        cmp     byte [dirty], 2
        je      .x
        mov     byte [dirty], 1
        cmp     al, 10
        jne     .x
        mov     byte [dirty], 2
.x:     ret

; ---------------------------------------------------------------------
;  lines and columns
; ---------------------------------------------------------------------
; AX = position -> AX = start of its line
line_start:
        push    bx
        mov     bx, ax
.l:     or      bx, bx
        jz      .x
        dec     bx
        push    ax
        call    getc
        cmp     al, 10
        pop     ax
        je      .hit
        jmp     .l
.hit:   inc     bx
.x:     mov     ax, bx
        pop     bx
        ret

; AX = position -> AX = its line's end (the LF, or the end of the text)
line_end:
        push    bx
        push    cx
        mov     bx, ax
        call    textlen
        mov     cx, ax
.l:     cmp     bx, cx
        jae     .x
        call    getc
        cmp     al, 10
        je      .x
        inc     bx
        jmp     .l
.x:     mov     ax, bx
        pop     cx
        pop     bx
        ret

; AX = line start, DX = position on that line -> AX = its display column
disp_col:
        push    bx
        push    cx
        mov     bx, ax
        xor     cx, cx
.l:     cmp     bx, dx
        jae     .x
        call    getc
        inc     bx
        cmp     al, 9
        je      .tab
        inc     cx
        jmp     .l
.tab:   call    next_tab
        jmp     .l
.x:     mov     ax, cx
        pop     cx
        pop     bx
        ret

next_tab:                               ; CX = column -> the next tab stop
        push    ax
        push    dx
        mov     ax, cx
        xor     dx, dx
        push    bx
        mov     bl, [cs:tabw]           ; (DS may be the buffer here)
        xor     bh, bh
        div     bx
        inc     ax
        mul     bx
        pop     bx
        mov     cx, ax
        pop     dx
        pop     ax
        ret

; AX = line start, DX = display column -> AX = the position there (or
; the line's end)
pos_at_col:
        push    bx
        push    cx
        push    si
        mov     bx, ax
        xor     cx, cx
        call    textlen
        mov     si, ax
.l:     cmp     bx, si
        jae     .x
        call    getc
        cmp     al, 10
        je      .x
        push    cx
        cmp     al, 9
        jne     .one
        call    next_tab
        jmp     .w
.one:   inc     cx
.w:     cmp     cx, dx                  ; past the column: this character
        pop     ax
        ja      .x
        inc     bx
        jmp     .l
.x:     mov     ax, bx
        pop     si
        pop     cx
        pop     bx
        ret

; the cursor's display column -> AX
cur_col:
        push    dx
        mov     ax, [gap_s]
        mov     dx, ax
        call    line_start
        call    disp_col
        pop     dx
        ret

; the view: top line near the cursor's, a third of the way down
center_view:
        mov     ax, [gap_s]
        call    line_start
        mov     [top], ax
        mov     ax, [curline]
        mov     [topline], ax
        mov     cx, NROWS / 3
.l:     cmp     word [top], 0
        je      .x
        mov     ax, [top]
        dec     ax
        call    line_start
        mov     [top], ax
        dec     word [topline]
        loop    .l
.x:     mov     word [hs], 0
        ret

; scroll so the cursor shows
fix_view:
        mov     ax, [curline]
        cmp     ax, [topline]
        jae     .below
        mov     ax, [gap_s]                ; above: its line at the top
        call    line_start
        mov     [top], ax
        mov     ax, [curline]
        mov     [topline], ax
        jmp     .h
.below: sub     ax, [topline]
        cmp     ax, NROWS
        jb      .h
        cmp     ax, NROWS * 2
        jae     .far
        sub     ax, NROWS - 1           ; lines to scroll
        mov     cx, ax
.d:     mov     ax, [top]
        call    line_end
        inc     ax
        mov     [top], ax
        inc     word [topline]
        loop    .d
.h:     call    cur_col                 ; and sideways
.hl:    cmp     ax, [hs]
        jae     .hr
        sub     word [hs], HSTEP
        jmp     .hl
.hr:    mov     dx, [hs]
        add     dx, 80
        cmp     ax, dx
        jb      .x
        add     word [hs], HSTEP
        jmp     .hr
.x:     ret
.far:   mov     ax, [gap_s]                ; (a long way: the cursor's line at the
        call    line_start              ;  bottom, the lines before it above)
        mov     [top], ax
        mov     ax, [curline]
        mov     [topline], ax
        mov     cx, NROWS - 1
.fl:    cmp     word [top], 0
        je      .h
        mov     ax, [top]
        dec     ax
        call    line_start
        mov     [top], ax
        dec     word [topline]
        loop    .fl
        jmp     .h

; ---------------------------------------------------------------------
;  the screen
; ---------------------------------------------------------------------
redraw: mov     di, title               ; "Write: NOTES.TXT"
        mov     si, s_wtitle
        call    UI_SBSTR
        mov     si, s_new
        cmp     byte [fname], 0
        je      .t
        mov     si, fname
        call    base_name
.t:     call    UI_SBSTR
        mov     byte [di], 0
        mov     si, title
        call    UI_SCREEN
        mov     dx, RULE_Y
        mov     bx, 0
        mov     cx, 80
        call    UI_DOTS
        push    es                      ; everything must be drawn again
        push    cs
        pop     es
        mov     di, shadow
        mov     cx, NROWS * ROWB
        mov     al, 0FEh
        rep     stosb
        pop     es
        mov     byte [stat_last], 0FFh
        mov     byte [cur_on], 0
        mov     byte [dirty], 2
        jmp     update

; SI = path -> SI = its file name part
base_name:
        push    ax
        mov     ax, si
.l:     cmp     byte [si], 0
        je      .x
        cmp     byte [si], '\'
        je      .s
        cmp     byte [si], ':'
        jne     .n
.s:     lea     ax, [si+1]
.n:     inc     si
        jmp     .l
.x:     mov     si, ax
        pop     ax
        ret

; the selection [sel_a, sel_b) for the mode
sel_range:
        mov     word [sel_a], 0
        mov     word [sel_b], 0
        cmp     byte [mode], M_SEL
        jne     .x
        mov     ax, [anchor]
        mov     dx, [gap_s]
        cmp     ax, dx
        jbe     .o
        xchg    ax, dx
.o:     mov     [sel_a], ax
        mov     [sel_b], dx
        ret
.x:     cmp     byte [mode], M_EDIT     ; Point and Found keep theirs
        je      .e
        mov     ax, [fix_a]
        mov     [sel_a], ax
        mov     ax, [fix_b]
        mov     [sel_b], ax
.e:     ret

; the screen up to date: view, the rows that may have changed, status,
; cursor.  [dirty]: 0 the cursor only moved, 1 its row changed, 2 more
update: call    fix_view                ; (old_top/old_hs: the view last
        mov     ax, [top]               ;  drawn, so PgDn, PgUp and Jump,
        cmp     ax, [old_top]           ;  which move [top] themselves, show)
        jne     .all
        mov     ax, [hs]
        cmp     ax, [old_hs]
        jne     .all
        mov     al, [mode]              ; a selection shows: draw it all
        or      al, [last_mode]
        jnz     .all
        jmp     .some
.all:   mov     byte [dirty], 2
.some:  mov     al, [mode]
        mov     [last_mode], al
        call    sel_range
        call    cursor_off
        cmp     byte [dirty], 2
        je      .full
        mov     ax, [curline]           ; the cursor's row, on its line
        sub     ax, [topline]
        mov     [crow], ax
        call    cur_col
        sub     ax, [hs]
        mov     [ccol], ax
        cmp     byte [dirty], 0
        je      .done
        mov     ax, [gap_s]             ; just that row again
        call    line_start
        mov     [rp], ax
        mov     byte [eof_seen], 0
        mov     bp, [crow]
        call    build_row
        call    put_row
        jmp     .done
.full:  mov     ax, [top]
        mov     [rp], ax
        mov     word [crow], 0FFFFh
        mov     byte [eof_seen], 0
        xor     bp, bp                  ; the row
.row:   call    build_row
        call    put_row
        inc     bp
        cmp     bp, NROWS
        jb      .row
.done:  mov     byte [dirty], 0
        mov     ax, [top]               ; the view now on the screen
        mov     [old_top], ax
        mov     ax, [hs]
        mov     [old_hs], ax
        call    status
        jmp     cursor_on

; build row BP into rowbuf from position [rp]; [rp] moves to the next row.
; Straight through the buffer: the text before the gap, then after it
; (where the two meet is the cursor).
build_row:
        push    es
        push    cs
        pop     es
        mov     di, rowbuf
        mov     cx, 40
        mov     ax, 2020h
        rep     stosw
        mov     cx, 40
        xor     ax, ax
        rep     stosw
        pop     es
        cmp     byte [eof_seen], 0
        jne     .x
        mov     ax, [sel_a]
        sub     ax, [sel_b]
        mov     [hassel], al            ; (0: no selection)
        or      [hassel], ah
        mov     dx, [rp]                ; DX = logical position
        xor     cx, cx                  ; CX = display column
        mov     si, dx
        mov     bx, [gap_s]             ; BX = end of this run
        cmp     dx, bx
        jb      .one
        ja      .after
        call    .atgap                  ; (starting right at the cursor)
        jmp     .phys
.after: mov     bx, [cap]               ; (starting after it: no cursor here)
        mov     byte [seg2], 1
.phys:  add     si, [gap_e]
        sub     si, [gap_s]
        jmp     .go
.one:   mov     byte [seg2], 0
.go:    push    ds
        mov     ds, [cs:bseg]
.c:     cmp     si, bx
        jae     .run_end
        lodsb
        xor     ah, ah                  ; selected?
        cmp     byte [cs:hassel], 0
        je      .ns
        cmp     dx, [cs:sel_a]
        jb      .ns
        cmp     dx, [cs:sel_b]
        jae     .ns
        mov     ah, 0FFh
.ns:    inc     dx
        cmp     al, 10
        je      .lf
        cmp     al, 9
        je      .tab
        call    .put
        inc     cx
        jmp     .c
.tab:   push    cx
        call    next_tab
        mov     di, cx
        pop     cx
        mov     al, ' '
.tl:    call    .put
        inc     cx
        cmp     cx, di
        jb      .tl
        jmp     .c
.run_end:
        cmp     byte [cs:seg2], 0
        jne     .eof                    ; the end of the text
        call    .atgap                  ; the gap: the cursor is here
        mov     si, [cs:gap_e]
        jmp     .c
.lf:    mov     al, ' '                 ; (a selected line end shows as a cell)
        call    .put
        pop     ds
        mov     [rp], dx
.x:     ret
.eof:   pop     ds
        mov     byte [eof_seen], 1
        mov     [rp], dx
        ret
.atgap: mov     [cs:crow], bp
        push    cx
        sub     cx, [cs:hs]
        mov     [cs:ccol], cx
        pop     cx
        mov     bx, [cs:cap]
        mov     byte [cs:seg2], 1
        ret
.put:   push    di                      ; AL, mark AH at column CX - hs
        mov     di, cx
        sub     di, [cs:hs]
        jb      .px
        cmp     di, 80
        jae     .px
        mov     [cs:rowbuf+di], al
        mov     [cs:rowbuf+80+di], ah
.px:    pop     di
        ret

; draw row BP if it differs from the shadow
put_row:
        push    bp
        mov     ax, bp
        mov     dx, ROWB
        mul     dx
        add     ax, shadow
        xchg    di, ax
        mov     si, rowbuf
        mov     cx, ROWB
        call    sync_buf
        je      .x
        mov     ax, bp
        shl     ax, 4
        add     ax, TEXT_Y
        mov     dx, ax
        mov     si, rowbuf
        mov     cx, 80
        xor     bx, bx
        xor     ah, ah
        call    UI_PUTSN
        xor     bx, bx                  ; the selection: runs of marked cells
.r:     cmp     bx, 80
        jae     .x
        cmp     byte [rowbuf+80+bx], 0
        je      .n
        mov     si, bx
.rl:    inc     bx
        cmp     bx, 80
        jae     .inv
        cmp     byte [rowbuf+80+bx], 0
        jne     .rl
.inv:   push    bx
        mov     bp, bx
        sub     bp, si
        mov     bx, si
        mov     cx, 16
        call    UI_INVERT
        pop     bx
        jmp     .r
.n:     inc     bx
        jmp     .r
.x:     pop     bp
        ret

; SI = CX bytes, DI = their shadow -> ZF if the same; else the shadow
; takes them (SI, DI, CX kept)
sync_buf:
        push    es
        push    cs
        pop     es
        pusha
        repe    cmpsb
        popa
        je      .x
        pusha
        rep     movsb
        popa                            ; (ZF stays clear)
.x:     pop     es
        ret

cursor_off:
        cmp     byte [cur_on], 0
        je      .x
        mov     byte [cur_on], 0
        jmp     cursor_xor
.x:     ret

cursor_on:
        cmp     word [crow], NROWS
        jae     .x
        cmp     word [ccol], 80
        jae     .x
        mov     ax, [crow]
        mov     [cur_r], ax
        mov     ax, [ccol]
        mov     [cur_c], ax
        mov     byte [cur_on], 1
        jmp     cursor_xor
.x:     ret

cursor_xor:                             ; invert the cursor's cell
        mov     dx, [cur_r]
        shl     dx, 4
        add     dx, TEXT_Y
        mov     bx, [cur_c]
        mov     cx, 16
        mov     bp, 1
        cmp     byte [ovr], 0
        jne     .x                      ; (overtype: a whole cell)
        add     dx, 8                   ; insert: its lower half.  (GRiD's
        mov     cx, 8                   ;  font fills the cell to its top and
.x:     jmp     UI_INVERT               ;  bottom rows, so a thin bar under
                                        ;  the character joined the letter
                                        ;  below it: l looked like T.)

; the status line: where the cursor is, and how
status: mov     di, stat_new
        mov     si, s_line
        call    UI_SBSTR
        mov     ax, [curline]
        inc     ax
        call    UI_SBU16
        mov     si, s_of
        call    UI_SBSTR
        mov     ax, [nlines]
        call    UI_SBU16
        mov     si, s_col
        call    UI_SBSTR
        call    cur_col
        inc     ax
        call    UI_SBU16
        mov     al, ' '
.pad:   cmp     di, stat_new + 40
        jae     .r
        stosb
        jmp     .pad
.r:     mov     si, s_insert
        cmp     byte [ovr], 0
        je      .i
        mov     si, s_ovr
.i:     call    UI_SBSTR
        mov     si, s_auto
        cmp     byte [autoind], 0
        je      .a
        call    UI_SBSTR
.a:     cmp     byte [changed], 0
        je      .c
        mov     si, s_changed
        call    UI_SBSTR
.c:     mov     byte [di], 0
        mov     si, stat_new            ; the same as last time?
        mov     di, stat_last
        mov     cx, 80
        call    sync_buf
        je      .x
        mov     dx, STAT_Y
        mov     cx, 16
        xor     bx, bx
        mov     bp, 80
        xor     al, al
        call    UI_FILL
        mov     si, stat_new
        mov     bx, 1
        xor     ah, ah
        call    UI_PUTS
.x:     ret

; the band for plain editing
edit_band:
        mov     si, s_eband1
        mov     di, s_eband2
        jmp     UI_BAND

; ---------------------------------------------------------------------
;  keys
; ---------------------------------------------------------------------
do_key: cmp     ax, EV_CLICK
        je      click
        mov     [lastkey], ax
        cmp     byte [mode], M_FOUND    ; after Find: Return finds the next one,
        jne     .m                      ;  anything else is ordinary again
        cmp     ax, K_ENTER
        je      find_next
        mov     byte [mode], M_EDIT
        call    edit_band
        mov     ax, [lastkey]
.m:     mov     si, move_keys           ; cursor keys work in every mode
        call    UI_DISPATCH
        jnc     .x
        cmp     byte [mode], M_EDIT
        je      .edit
        mov     si, sel_keys            ; selecting or pointing
        call    UI_DISPATCH
        jnc     .x
        jmp     UI_BEEP
.edit:  mov     si, edit_keys
        call    UI_DISPATCH
        jnc     .x
        mov     ax, [lastkey]
        cmp     al, ' '                 ; a character: into the text
        jb      .ctl
        cmp     al, 0FFh
        je      .x
        jmp     type_char
.ctl:   cmp     al, 9
        je      type_char
.x:     ret

; a printable character (or a tab) at the cursor
type_char:
        mov     word [goal], 0FFFFh
        cmp     byte [ovr], 0
        je      .ins
        push    ax                      ; overtype: replace (not a line end)
        mov     bx, [gap_s]
        call    textlen
        cmp     bx, ax
        jae     .o
        call    getc
        cmp     al, 10
        je      .o
        call    del_fwd
.o:     pop     ax
.ins:   call    ins_char
        jc      full
        ret

full:   mov     si, s_full
        call    UI_MSG
        ret

k_enter:
        mov     word [goal], 0FFFFh
        mov     al, 10
        call    ins_char
        jc      full
        cmp     byte [autoind], 0
        je      .x
        mov     ax, [gap_s]                ; the previous line's indent
        dec     ax
        call    line_start
        mov     bx, ax
.l:     call    getc
        cmp     al, ' '
        je      .c
        cmp     al, 9
        jne     .x
.c:     push    bx
        call    ins_char
        pop     bx
        jc      full
        inc     bx
        jmp     .l
.x:     ret

k_bksp: mov     word [goal], 0FFFFh
        jmp     del_back
k_del:  mov     word [goal], 0FFFFh
        jmp     del_fwd
k_ins:  call    cursor_off              ; (the old shape off first)
        xor     byte [ovr], 1
        ret

; ---- moving ----------------------------------------------------------
k_left: mov     word [goal], 0FFFFh
        mov     ax, [gap_s]
        or      ax, ax
        jz      .x
        dec     ax
        jmp     gap_to
.x:     ret

k_right:
        mov     word [goal], 0FFFFh
        call    textlen
        cmp     [gap_s], ax
        jae     .x
        mov     ax, [gap_s]
        inc     ax
        jmp     gap_to
.x:     ret

k_home: mov     word [goal], 0FFFFh
        mov     ax, [gap_s]
        call    line_start
        jmp     gap_to

k_end:  mov     word [goal], 0FFFFh
        mov     ax, [gap_s]
        call    line_end
        jmp     gap_to

k_up:   call    set_goal
        mov     ax, [gap_s]
        call    line_start
        or      ax, ax
        jz      .no
        dec     ax
        call    line_start
        mov     dx, [goal]
        call    pos_at_col
        call    gap_to
        clc
        ret
.no:    stc
        ret

k_down: call    set_goal
        mov     ax, [gap_s]
        call    line_end
        push    ax
        call    textlen
        pop     dx
        cmp     dx, ax
        jae     .no
        mov     ax, dx
        inc     ax
        mov     dx, [goal]
        call    pos_at_col
        call    gap_to
        clc
        ret
.no:    stc
        ret

set_goal:
        cmp     word [goal], 0FFFFh
        jne     .x
        call    cur_col
        mov     [goal], ax
.x:     ret

k_pgdn: mov     cx, NROWS - 1           ; a page: the cursor and the view
.l:     push    cx
        call    k_down
        pop     cx
        jc      .x
        mov     ax, [top]
        call    line_end
        push    ax
        call    textlen
        pop     dx
        cmp     dx, ax
        jae     .n
        inc     dx
        mov     [top], dx
        inc     word [topline]
.n:     loop    .l
.x:     ret

k_pgup: mov     cx, NROWS - 1
.l:     push    cx
        call    k_up
        pop     cx
        jc      .x
        mov     ax, [top]
        or      ax, ax
        jz      .n
        dec     ax
        call    line_start
        mov     [top], ax
        dec     word [topline]
.n:     loop    .l
.x:     ret

k_ctop: mov     word [goal], 0FFFFh
        xor     ax, ax
        jmp     gap_to

k_cend: mov     word [goal], 0FFFFh
        call    textlen
        jmp     gap_to

k_wleft:                                ; to the start of the word before
        mov     word [goal], 0FFFFh
        mov     bx, [gap_s]
.sp:    or      bx, bx
        jz      .go
        dec     bx
        call    getc
        call    is_word
        jnc     .sp
.w:     or      bx, bx
        jz      .go
        dec     bx
        call    getc
        call    is_word
        jc      .w
        inc     bx
.go:    mov     ax, bx
        jmp     gap_to

k_wright:                               ; to the start of the next word
        mov     word [goal], 0FFFFh
        call    textlen
        mov     cx, ax
        mov     bx, [gap_s]
.w:     cmp     bx, cx
        jae     .go
        call    getc
        call    is_word
        jnc     .sp
        inc     bx
        jmp     .w
.sp:    cmp     bx, cx
        jae     .go
        call    getc
        call    is_word
        jc      .go
        inc     bx
        jmp     .sp
.go:    mov     ax, bx
        jmp     gap_to

is_word:                                ; AL -> CF if a letter, digit or _
        cmp     al, '_'
        je      .y
        cmp     al, '0'
        jb      .n
        cmp     al, '9'
        jbe     .y
        and     al, 0DFh
        cmp     al, 'A'
        jb      .n
        cmp     al, 'Z'
        jbe     .y
.n:     clc
        ret
.y:     stc
        ret

; a click in the text: the cursor there; on the band: help, or confirm
click:  cmp     cx, SCR_BAND_Y
        jb      .text
        cmp     byte [mode], M_EDIT
        je      k_help
        mov     ax, K_ENTER
        jmp     do_key
.text:  cmp     byte [mode], M_FOUND    ; (a click ends Found, like a key)
        jne     .t1
        mov     byte [mode], M_EDIT
        push    bx
        push    cx
        call    edit_band
        pop     cx
        pop     bx
.t1:    sub     cx, TEXT_Y
        jb      .x
        shr     cx, 4
        cmp     cx, NROWS
        jae     .x
        mov     ax, [top]               ; that row's line: walk down to it
        jcxz    .at
.dn:    push    ax
        call    line_end
        mov     dx, ax
        call    textlen
        cmp     dx, ax
        pop     ax
        jae     .x                      ; (below the text)
        mov     ax, dx
        inc     ax
        loop    .dn
.at:    mov     dx, bx
        shr     dx, 3
        add     dx, [hs]
        call    pos_at_col
        mov     word [goal], 0FFFFh
        jmp     gap_to
.x:     ret

; ---------------------------------------------------------------------
;  the commands
; ---------------------------------------------------------------------
k_help: mov     si, help_keys
        mov     di, s_helptitle
        jmp     UI_HELP

; Erase, Move, Duplicate: make a selection first
k_erase:
        mov     byte [cmd], 'E'
        mov     si, s_erase
        jmp     begin_sel
k_move: mov     byte [cmd], 'M'
        mov     si, s_movesel
        jmp     begin_sel
k_dup:  mov     byte [cmd], 'D'
        mov     si, s_dupsel
begin_sel:
        mov     di, s_selband
        call    UI_BAND
        mov     byte [mode], M_SEL
k_begin:                                ; (CODE-B: the selection starts here)
        mov     ax, [gap_s]
        mov     [anchor], ax
        ret

; Return while selecting or pointing
k_confirm:
        cmp     byte [mode], M_POINT
        je      .point
        call    sel_range               ; a selection: what now?
        mov     ax, [sel_a]
        cmp     ax, [sel_b]
        je      .empty
        mov     [fix_a], ax
        mov     ax, [sel_b]
        mov     [fix_b], ax
        cmp     byte [cmd], 'E'
        je      .erase
        mov     byte [mode], M_POINT    ; Move, Duplicate: where to?
        mov     si, s_movept
        cmp     byte [cmd], 'M'
        je      .p
        mov     si, s_duppt
.p:     mov     di, s_ptband
        jmp     UI_BAND
.empty: jmp     UI_BEEP
.erase: call    erase_range
        jmp     k_cancel_cmd
.point: mov     ax, [gap_s]                ; not inside the selection itself
        cmp     ax, [fix_a]
        jbe     .ok
        cmp     ax, [fix_b]
        jae     .ok
        jmp     UI_BEEP
.ok:    call    copy_range              ; a copy here ...
        jc      .x
        cmp     byte [cmd], 'M'
        jne     .done
        mov     ax, [fix_b]             ; ... and for Move, the original goes
        sub     ax, [fix_a]             ; AX = its length
        mov     cx, [gap_s]                ; the cursor: after the copy
        mov     dx, cx
        sub     dx, ax                  ; DX = where the copy went
        cmp     [fix_a], dx
        jb      .bef
        add     [fix_a], ax             ; (it was after: the copy pushed it on)
        add     [fix_b], ax
        jmp     .del
.bef:   sub     cx, ax                  ; (it was before: the cursor moves back)
.del:   push    cx
        call    erase_range
        pop     ax
        call    gap_to
.done:  call    center_if_needed
.x:     jmp     k_cancel_cmd

; ESC while selecting or pointing: back to editing
k_cancel_cmd:
        mov     byte [mode], M_EDIT
        jmp     edit_band

center_if_needed:
        mov     ax, [curline]           ; (block changes above the view)
        cmp     ax, [topline]
        jb      center_view
        ret

; delete [fix_a, fix_b); the cursor ends at fix_a
erase_range:
        mov     ax, [fix_b]
        call    gap_to
        mov     cx, [fix_b]
        sub     cx, [fix_a]
        jcxz    .x
        push    es
        mov     es, [bseg]
        mov     di, [fix_a]
        push    cx
        call    count_lf
        pop     cx
        pop     es
        sub     [curline], dx
        sub     [nlines], dx
        sub     [gap_s], cx
        mov     byte [changed], 1
        mov     byte [dirty], 2
        mov     ax, [top]               ; the view may have started inside it
        cmp     ax, [gap_s]
        jbe     .x
        call    center_view
.x:     ret

; a copy of [fix_a, fix_b) at the cursor (it is outside that range, so
; the range is in one piece on one side of the gap).  CF if no room
copy_range:
        mov     cx, [fix_b]
        sub     cx, [fix_a]
        mov     ax, [gap_e]
        sub     ax, [gap_s]
        cmp     cx, ax
        ja      .full
        mov     si, [fix_a]
        cmp     si, [gap_s]
        jb      .lo
        add     si, [gap_e]
        sub     si, [gap_s]
.lo:    push    ds
        push    es
        mov     es, [bseg]
        push    si
        push    cx
        mov     di, si
        call    count_lf
        add     [curline], dx
        add     [nlines], dx
        pop     cx
        pop     si
        mov     di, [gap_s]
        add     [gap_s], cx
        mov     byte [changed], 1
        mov     byte [dirty], 2
        push    es
        pop     ds
        rep     movsb
        pop     es
        pop     ds
        clc
        ret
.full:  call    full
        stc
        ret

; ---- Find and Substitute ---------------------------------------------
k_find: mov     si, find_form
        call    UI_FORM
        jc      .x
        cmp     byte [f_text], 0
        je      .x
        mov     ax, [gap_s]                ; from the cursor
        mov     [fpos], ax
        call    find
        jc      .none
        jmp     found
.none:  jmp     not_found
.x:     ret

find_next:
        mov     ax, [gap_s]
        cmp     byte [f_dir], 0
        jne     .b
        inc     ax                      ; (forward: past this one)
        jmp     .f
.b:     or      ax, ax
        jz      not_found
        dec     ax
.f:     mov     [fpos], ax
        call    find
        jc      not_found
found:  mov     [fix_a], ax             ; show it, the cursor at its start
        add     ax, [f_len]
        mov     [fix_b], ax
        mov     ax, [fix_a]
        call    gap_to
        call    center_if_far
        mov     byte [mode], M_FOUND
        mov     si, s_found1
        mov     di, s_found2
        jmp     UI_BAND
not_found:
        mov     byte [mode], M_EDIT
        call    edit_band
        mov     si, s_nomatch
        jmp     UI_MSG

center_if_far:                          ; (a long way off: centre it)
        mov     ax, [curline]
        cmp     ax, [topline]
        jb      center_view
        sub     ax, [topline]
        cmp     ax, NROWS
        jae     center_view
        ret

; f_text from [fpos] (forward, or backward from it) -> AX = where, CF none
find:   mov     si, f_text
        call    UI_STRLEN
        mov     [f_len], cx
        call    textlen
        sub     ax, cx
        jb      .no                     ; (longer than the text)
        mov     [f_last], ax            ; last place it can start
        mov     bx, [fpos]
        cmp     byte [f_dir], 0
        jne     .back
.fw:    cmp     bx, [f_last]
        ja      .no
        call    match
        je      .yes
        inc     bx
        jmp     .fw
.back:  cmp     bx, [f_last]
        jbe     .bl
        mov     bx, [f_last]
.bl:    call    match
        je      .yes
        or      bx, bx
        jz      .no
        dec     bx
        jmp     .bl
.yes:   mov     ax, bx
        clc
        ret
.no:    stc
        ret

; does f_text match at BX?  ZF if so
match:  push    bx
        push    si
        mov     si, f_text
.l:     mov     ah, [si]
        or      ah, ah
        jz      .x                      ; (all of it: ZF set)
        call    getc
        cmp     byte [f_match], 0
        jne     .c
        call    upper
        xchg    al, ah
        call    upper
        xchg    al, ah
.c:     cmp     al, ah
        jne     .x
        inc     si
        inc     bx
        jmp     .l
.x:     pop     si
        pop     bx
        ret

upper:  cmp     al, 'a'
        jb      .x
        cmp     al, 'z'
        ja      .x
        sub     al, 20h
.x:     ret

; Substitute: find, then replace (asking each time if Verification)
k_subst:
        mov     si, subst_form
        call    UI_FORM
        jc      .x
        cmp     byte [f_text], 0
        je      .x
        mov     word [nsubst], 0
        mov     byte [s_all], 0
        mov     ax, [gap_s]
        mov     [fpos], ax
.next:  call    find
        jc      .done
        mov     [fix_a], ax
        add     ax, [f_len]
        mov     [fix_b], ax
        cmp     byte [f_verify], 0      ; 0 = Yes: ask
        jne     .do
        cmp     byte [s_all], 0
        jne     .do
        mov     ax, [fix_a]             ; show it and ask
        call    gap_to
        call    center_if_far
        mov     byte [mode], M_FOUND
        mov     si, s_subq1
        mov     di, s_subq2
        call    UI_BAND
        call    update
.ask:   call    UI_EVENT
        cmp     ax, K_ESC
        je      .stop
        or      al, 20h
        cmp     al, 'y'
        je      .do
        cmp     al, 0Dh | 20h
        je      .do
        cmp     al, 'a'
        je      .all
        cmp     al, 's'                 ; Single: this one, then stop
        je      .single
        cmp     al, 'n'
        jne     .ask
        mov     ax, [fix_a]             ; no: past it
        cmp     byte [f_dir], 0
        jne     .nb
        inc     ax
        jmp     .np
.nb:    or      ax, ax
        jz      .done
        dec     ax
.np:    mov     [fpos], ax
        jmp     .next
.all:   mov     byte [s_all], 1
.do:    call    replace_one
        jc      .done
        jmp     .next
.single:
        call    replace_one
.stop:
.done:  mov     byte [mode], M_EDIT
        call    edit_band
        call    update
        mov     di, line                ; "Number of substitutions: 3"
        mov     si, s_nsubst
        call    UI_SBSTR
        mov     ax, [nsubst]
        call    UI_SBU16
        mov     byte [di], 0
        mov     si, line
        jmp     UI_MSG
.x:     ret

; [fix_a, fix_b) becomes r_text; the search goes on after it (or before)
replace_one:
        mov     si, r_text              ; room for it?  (Else the match would
        call    UI_STRLEN               ;  go and only part of r_text come)
        mov     ax, [fix_b]
        sub     ax, [fix_a]             ; AX = what goes, CX = what comes
        sub     cx, ax
        jbe     .fits
        mov     ax, [gap_e]
        sub     ax, [gap_s]
        cmp     cx, ax
        ja      .full
.fits:  call    erase_range
        mov     si, r_text
.l:     lodsb
        or      al, al
        jz      .d
        call    ins_char
        jc      .full
        jmp     .l
.d:     inc     word [nsubst]
        mov     ax, [gap_s]
        cmp     byte [f_dir], 0
        je      .f
        mov     ax, [fix_a]             ; backward: the next one must end
        sub     ax, [f_len]             ;  before this (not run into the
        jb      .end                    ;  text just put in)
.f:     mov     [fpos], ax
        clc
        ret
.end:   stc
        ret
.full:  call    full
        stc
        ret

; ---- Jump, Options, Usage --------------------------------------------
k_jump: mov     byte [j_text], 0
        mov     si, jump_form
        call    UI_FORM
        jc      .x
        mov     si, j_text
        xor     ax, ax
.n:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .go
        mov     dx, 10
        mul     dx
        xor     bh, bh
        add     ax, bx
        inc     si
        jmp     .n
.go:    or      ax, ax
        jz      .x
        dec     ax                      ; line n starts after n-1 line feeds
        mov     cx, ax
        xor     bx, bx
        call    textlen
        mov     dx, ax
        jcxz    .at
.f:     cmp     bx, dx
        jae     .at
        call    getc
        inc     bx
        cmp     al, 10
        jne     .f
        loop    .f
.at:    mov     ax, bx
        mov     word [goal], 0FFFFh
        call    gap_to
        jmp     center_view
.x:     ret

k_options:
        mov     al, [autoind]           ; the form's choices: 0 = Yes
        xor     al, 1
        mov     [o_auto], al
        mov     al, 0                   ; tab width 8, 4, 2
        cmp     byte [tabw], 4
        jne     .t2
        mov     al, 1
.t2:    cmp     byte [tabw], 2
        jne     .t3
        mov     al, 2
.t3:    mov     [o_tab], al
        mov     si, opt_form
        call    UI_FORM
        jc      .x
        mov     al, [o_auto]
        xor     al, 1
        mov     [autoind], al
        mov     bl, [o_tab]
        xor     bh, bh
        mov     al, [tabws+bx]
        mov     [tabw], al
        jmp     redraw                  ; (tabs may show differently)
.x:     ret

k_usage:
        mov     di, line                ; "1234 characters in 56 lines; room for 60000 more"
        call    textlen
        call    UI_SBU16
        mov     si, s_chars
        call    UI_SBSTR
        mov     ax, [nlines]
        call    UI_SBU16
        mov     si, s_room
        call    UI_SBSTR
        mov     ax, [gap_e]
        sub     ax, [gap_s]
        call    UI_SBU16
        mov     si, s_more
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, line
        jmp     UI_MSG

; ---- Transfer, Quit, Cancel ------------------------------------------
k_transfer:
        mov     di, t_name              ; the form starts with this file
        mov     si, fname
        call    UI_SBSTR
        mov     byte [di], 0
        mov     byte [t_act], 0
.form:  mov     si, xfer_form
        call    UI_FORM
        jc      .x
        cmp     byte [t_name], 0
        je      .form
        cmp     byte [t_act], 2
        je      .inc
        mov     si, t_name
        call    save_as
        jc      .x
        cmp     byte [t_act], 0         ; Save: this is the file now
        jne     .x
        mov     di, fname
        mov     si, t_name
        call    UI_SBSTR
        mov     byte [di], 0
        mov     byte [changed], 0
        jmp     redraw
.inc:   mov     si, t_name              ; Include: the file at the cursor
        call    load_file
        jnc     .x
        jmp     io_error
.x:     ret

k_quit: mov     si, s_quitq
        call    UI_ASK
        jc      .x
        cmp     byte [changed], 0       ; nothing to save
        je      .bye
        cmp     byte [fname], 0
        jne     .save
        call    ask_name                ; a new file: what is it called?
        jc      .x
        mov     si, fname
        call    save_as
        jnc     .bye
        mov     byte [fname], 0         ; (not saved: still a new file, and
        ret                             ;  the next Quit asks again)
.save:  mov     si, fname
        call    save_as
        jc      .x
.bye:   mov     byte [quit], 1
.x:     ret

k_cancel:
        mov     si, s_cancelq
        cmp     byte [changed], 0
        jne     .a
        mov     si, s_cancelq2
.a:     call    UI_ASK
        jc      .x
        mov     byte [quit], 1
.x:     ret

ask_name:                               ; -> fname, CF if cancelled
        mov     byte [t_name], 0
        mov     si, name_form
        call    UI_FORM
        jc      .x
        cmp     byte [t_name], 0
        je      ask_name
        mov     di, fname
        mov     si, t_name
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, fname               ; no extension: .TXT
        call    base_name
.e:     lodsb
        cmp     al, '.'
        je      .ok
        or      al, al
        jnz     .e
        dec     si
        mov     di, si
        mov     si, s_txt
        call    UI_SBSTR
        mov     byte [di], 0
.ok:    clc
.x:     ret

; ---------------------------------------------------------------------
;  files
; ---------------------------------------------------------------------
; read the file SI into the text at the cursor (CR LF -> LF, stops at ^Z).
; CF: AX = DOS error (8: it doesn't fit; what fitted stays)
load_file:
        call    UI_CRITERR
        mov     dx, si
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     [hnd], ax
        mov     byte [pend_cr], 0
.chunk: mov     bx, [hnd]
        mov     dx, iobuf
        mov     cx, IOB
        mov     ah, 3Fh
        int     21h
        jc      .err
        or      ax, ax
        jz      .eof
        mov     cx, ax
        mov     si, iobuf
.b:     lodsb
        cmp     al, 1Ah                 ; ^Z: the end
        je      .eof
        cmp     byte [pend_cr], 0       ; a CR waits: dropped before LF
        je      .nc
        mov     byte [pend_cr], 0
        cmp     al, 10
        je      .put
        push    ax
        mov     al, 13
        call    ins_char
        pop     ax
        jc      .big
.nc:    cmp     al, 13
        jne     .put
        mov     byte [pend_cr], 1
        jmp     .nx
.put:   call    ins_char
        jc      .big
.nx:    loop    .b
        jmp     .chunk
.eof:   cmp     byte [pend_cr], 0
        je      .close
        mov     al, 13
        call    ins_char
        jc      .big                    ; (no room even for that last CR)
.close: mov     bx, [hnd]
        mov     ah, 3Eh
        int     21h
        mov     byte [dirty], 2
        clc
.x:     ret
.big:   mov     ax, 8
.err:   push    ax
        mov     bx, [hnd]
        mov     ah, 3Eh
        int     21h
        pop     ax
        stc
        ret

; write the text to the file SI (LF -> CR LF): first to NAME.$$$ beside
; it, then that takes the name.  CF if it couldn't (and says why)
save_as:
        mov     [sv_name], si
        mov     di, tmpname             ; NAME.$$$
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, tmpname
        call    base_name
.e:     mov     al, [si]
        or      al, al
        jz      .noext
        cmp     al, '.'
        je      .dot
        inc     si
        jmp     .e
.noext: mov     byte [si], '.'
.dot:   lea     di, [si+1]
        mov     si, s_dollar
        cmp     word [di], '$$'         ; (saving to a .$$$ itself: not that)
        jne     .sd
        cmp     byte [di+2], '$'
        jne     .sd
        mov     si, s_dollar1
.sd:    call    UI_SBSTR
        mov     byte [di], 0
        call    UI_CRITERR
        mov     dx, tmpname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      io_error
        mov     [hnd], ax
        mov     di, iobuf               ; the text, a chunk at a time
        xor     bx, bx
        call    textlen
        mov     [tlen], ax
.c:     cmp     bx, [tlen]
        jae     .last
        call    getc
        inc     bx
        cmp     al, 10
        jne     .s
        mov     byte [di], 13
        inc     di
.s:     mov     [di], al
        inc     di
        cmp     di, iobuf + IOB - 2
        jb      .c
        call    flush
        jc      .werr
        jmp     .c
.last:  call    flush
        jc      .werr
        mov     bx, [hnd]
        mov     ah, 3Eh
        int     21h
        jc      .werr2
        mov     dx, [sv_name]           ; the old one goes, the new one takes
        mov     ah, 41h                 ;  its name
        int     21h
        jnc     .ren
        cmp     ax, 2                   ; (not there: a new file)
        jne     .werr2                  ; (read-only, say: it stays as it was)
.ren:   mov     dx, tmpname
        mov     di, [sv_name]
        mov     ah, 56h
        int     21h
        jc      io_error
        clc
        ret
.werr:  push    ax
        mov     bx, [hnd]
        mov     ah, 3Eh
        int     21h
        pop     ax
.werr2: push    ax
        mov     dx, tmpname
        mov     ah, 41h
        int     21h
        pop     ax
        jmp     io_error

flush:  mov     cx, di                  ; iobuf .. DI to the file
        sub     cx, iobuf
        jcxz    .x
        push    bx
        mov     bx, [hnd]
        mov     dx, iobuf
        mov     ah, 40h
        int     21h
        pop     bx
        jc      .e
        cmp     ax, cx
        mov     ax, 39                  ; (short write: the disk is full)
        jne     .e
.x:     mov     di, iobuf
        clc
        ret
.e:     stc
        ret

; AX = DOS error: say so (CF stays set)
io_error:
        mov     di, line
        mov     si, s_ioerr
        call    UI_SBSTR
        call    UI_SBERR
        mov     byte [di], 0
        mov     si, line
        call    UI_MSG
        stc
        ret

; ---------------------------------------------------------------------
;  key tables
; ---------------------------------------------------------------------
move_keys:
        KEY(K_LEFT,   k_left,   0)
        KEY(K_RIGHT,  k_right,  0)
        KEY(K_UP,     k_up,     0)
        KEY(K_DOWN,   k_down,   0)
        KEY(K_HOME,   k_home,   0)
        KEY(K_END,    k_end,    0)
        KEY(K_PGUP,   k_pgup,   0)
        KEY(K_PGDN,   k_pgdn,   0)
        KEY(K_CHOME,  k_ctop,   0)
        KEY(K_CEND,   k_cend,   0)
        KEY(K_CLEFT,  k_wleft,  0)
        KEY(K_CRIGHT, k_wright, 0)
        KEY(K_F1,     k_help,   0)
        KEY(K_CODE_HELP, k_help, 0)
        dw 0

sel_keys:
        KEY(K_ENTER,      k_confirm,    0)
        KEY(K_CODE_ENTER, k_confirm,    0)
        KEY(K_ESC,        k_cancel_cmd, 0)
        KEY(K_CODE_B,     k_begin,      0)
        dw 0

edit_keys:
        KEY(K_ENTER,    k_enter,    0)
        KEY(K_BKSP,     k_bksp,     0)
        KEY(K_DEL,      k_del,      0)
        KEY(K_INS,      k_ins,      0)
        KEY(K_CODE_E,   k_erase,    0)
        KEY(K_CODE_M,   k_move,     0)
        KEY(K_CODE_D,   k_dup,      0)
        KEY(K_CODE_B,   k_erase,    0)  ; (Begin outside a command: Erase)
        KEY(K_CODE_F,   k_find,     0)
        KEY(K_CODE_S,   k_subst,    0)
        KEY(K_CODE_J,   k_jump,     0)
        KEY(K_CODE_O,   k_options,  0)
        KEY(K_CODE_U,   k_usage,    0)
        KEY(K_CODE_T,   k_transfer, 0)
        KEY(K_CODE_Q,   k_quit,     0)
        KEY(K_CODE_ESC, k_cancel,   0)
        KEY(K_ESC,      k_cancel,   0)
        dw 0

help_keys:                              ; (only for the help window)
        KEY(K_NONE, 0, h1)
        KEY(K_NONE, 0, h2)
        KEY(K_NONE, 0, h3)
        KEY(K_NONE, 0, h4)
        KEY(K_NONE, 0, h5)
        KEY(K_NONE, 0, h6)
        KEY(K_NONE, 0, h7)
        KEY(K_NONE, 0, h8)
        KEY(K_NONE, 0, h9)
        KEY(K_NONE, 0, h10)
        KEY(K_NONE, 0, h11)
        KEY(K_NONE, 0, h12)
        KEY(K_NONE, 0, h13)
        KEY(K_NONE, 0, h14)
        KEY(K_NONE, 0, h15)
        dw 0

; ---------------------------------------------------------------------
;  forms
; ---------------------------------------------------------------------
find_form:  dw l_find, s_findp, 62, 11, 3
            dw l_find,  FT_TEXT + (40 << 8), f_text, 40
            dw l_match, FT_CHOICE, f_match, o_match
            dw l_dir,   FT_CHOICE, f_dir, o_dir
subst_form: dw s_subt, s_subp, 62, 13, 5
            dw l_search, FT_TEXT + (40 << 8), f_text, 40
            dw l_replace, FT_TEXT + (40 << 8), r_text, 40
            dw l_match, FT_CHOICE, f_match, o_match
            dw l_dir,   FT_CHOICE, f_dir, o_dir
            dw l_verify, FT_CHOICE, f_verify, o_yesno
jump_form:  dw s_jumpt, s_jumpp, 40, 14, 1
            dw l_jump, FT_TEXT + (8 << 8), j_text, 6
opt_form:   dw s_optt, s_optp, 52, 18, 2
            dw l_auto, FT_CHOICE, o_auto, o_yesno
            dw l_tabw, FT_CHOICE, o_tab, o_tabs
xfer_form:  dw s_xfert, s_xferp, 66, 8, 2
            dw l_do,   FT_CHOICE, t_act, o_xfer
            dw l_file, FT_TEXT + (46 << 8), t_name, 70
name_form:  dw s_namet, s_namep, 60, 8, 1
            dw l_file, FT_TEXT + (40 << 8), t_name, 70

; ---------------------------------------------------------------------
;  strings
; ---------------------------------------------------------------------
s_wtitle    db 'Write: ',0
s_new       db '(new)',0
s_helptitle db 'Write Commands',0
s_eband1    db 'Type, or choose a command (CODE-? lists them)',0
s_eband2    db 'CODE-Q save and quit    ESC cancel',0
s_erase     db 'Erase: Make a selection and confirm',0
s_movesel   db 'Move: Make a selection and confirm',0
s_dupsel    db 'Duplicate: Make a selection and confirm',0
s_selband   db 'Cursor keys or the mouse select   CODE-B begins again   ESC cancels',0
s_movept    db 'Move: Point to destination and confirm',0
s_duppt     db 'Duplicate: Point to destination and confirm',0
s_ptband    db 'Cursor keys or the mouse point   ESC cancels',0
s_found1    db 'Find: Confirm for next occurrence',0
s_found2    db 'Any other key goes on writing',0
s_nomatch   db 'No further matches to text specified',0
s_subq1     db 'Substitute this occurrence of the text?',0
s_subq2     db 'Y yes   N no   S single (then stop)   A all   ESC stop',0
s_nsubst    db 'Number of substitutions: ',0
s_quitq     db 'Quit: Confirm to save and exit',0
s_cancelq   db 'Cancel: Confirm to exit without saving (changed)',0
s_cancelq2  db 'Cancel: Confirm to exit without saving (unchanged)',0
s_full      db 'Out of memory: the text is as long as Write can hold',0
s_nomem     db 'Not enough memory for Write',0
s_cantread  db "Can't read the file: ",0
s_ioerr     db "Can't: ",0
s_chars     db ' characters in ',0
s_room      db ' lines; room for ',0
s_more      db ' more',0
s_line      db 'Line ',0
s_of        db ' of ',0
s_col       db '   Column ',0
s_insert    db 'Insert',0
s_ovr       db 'Overtype',0
s_auto      db '   Indent',0
s_changed   db '   Changed',0
s_txt       db '.TXT',0
s_dollar    db '$$$',0
s_dollar1   db '$$1',0
s_findp     db 'Find: Fill in form and confirm',0
s_subt      db 'Substitute',0
s_subp      db 'Substitute: Fill in form and confirm',0
s_jumpt     db 'Jump',0
s_jumpp     db 'Jump: Fill in form and confirm',0
s_optt      db 'Options',0
s_optp      db 'Options: Fill in form and confirm',0
s_xfert     db 'Transfer',0
s_xferp     db 'Transfer: Fill in form and confirm',0
s_namet     db 'Save as',0
s_namep     db 'Quit: Name the file and confirm',0
l_find      db 'Find',0
l_search    db 'Search for',0
l_replace   db 'Replace with',0
l_match     db 'Match',0
l_dir       db 'Direction',0
l_verify    db 'Verification',0
l_jump      db 'Jump to line',0
l_auto      db 'Automatic indent',0
l_tabw      db 'Tab stops every',0
l_do        db 'Do',0
l_file      db 'File',0
o_match     db 'Independent of case',0,'Exactly',0,0
o_dir       db 'Forward',0,'Backward',0,0
o_yesno     db 'Yes',0,'No',0,0
o_tabs      db '8',0,'4',0,'2',0,0
o_xfer      db 'Save',0,'Write to a file',0,'Include a file',0,0
tabws       db 8, 4, 2
h1          db 'Begin       CODE-B    Restart the selection',0
h2          db 'Duplicate   CODE-D    Duplicate selected text',0
h3          db 'Erase       CODE-E    Erase selected text',0
h4          db 'Find        CODE-F    Find specified text',0
h5          db 'Jump        CODE-J    Move cursor to a line',0
h6          db 'Move        CODE-M    Move selected text',0
h7          db 'Options     CODE-O    Set indent and tab stops',0
h8          db 'Quit        CODE-Q    Exit and save all changes',0
h9          db 'Substitute  CODE-S    Substitute specified text',0
h10         db 'Transfer    CODE-T    Save, write or include files',0
h11         db 'Usage       CODE-U    Show size and room left',0
h12         db 'Cancel      CODE-ESC  Exit without saving (or ESC)',0
h13         db 'Commands: press it, select, then confirm (Return)',0
h14         db 'Arrows, PgUp/PgDn, Ctrl-arrows, Ctrl-Home/End move',0
h15         db 'Ins switches insert/overtype.  Any key closes.',0
f_match     db 0
f_dir       db 0
f_verify    db 0
o_auto      db 1
o_tab       db 0
t_act       db 0
quit        db 0
mode        db M_EDIT
ovr         db 0
autoind     db 0
changed     dw 0

section .bss
bseg        resw 1
cap         resw 1
gap_s       resw 1                      ; the gap: [gap_s, gap_e); the cursor is gap_s
gap_e       resw 1
tlen        resw 1
top         resw 1                      ; first line shown
topline     resw 1
curline     resw 1                      ; (from 0)
nlines      resw 1
goal        resw 1                      ; column for Up/Down (FFFFh: none)
hs          resw 1                      ; first column shown
tabw        resb 1
cmd         resb 1
anchor      resw 1
sel_a       resw 1
sel_b       resw 1
fix_a       resw 1
fix_b       resw 1
lastkey     resw 1
rp          resw 1
crow        resw 1
ccol        resw 1
cur_r       resw 1
cur_c       resw 1
cur_on      resb 1
eof_seen    resb 1
fpos        resw 1
f_len       resw 1
f_last      resw 1
nsubst      resw 1
s_all       resb 1
pend_cr     resb 1
hnd         resw 1
sv_name     resw 1
old_top     resw 1
old_hs      resw 1
dirty       resb 1
last_mode   resb 1
hassel      resb 1
seg2        resb 1
fname       resb 80
tmpname     resb 80
title       resb 96                     ; (UI_SCREEN keeps the pointer)
f_text      resb 42
r_text      resb 42
j_text      resb 8
t_name      resb 72
stat_last   resb 80
shadow      resb NROWS * ROWB
iobuf       resb IOB                    ; a file read or written in one go:
rowbuf      equ iobuf                   ;  these three are never live then
stat_new    equ iobuf + ROWB            ;  (an I/O error is said in line
line        equ iobuf + ROWB + 80       ;  once the file is closed)
        times   -(ROWB + 80 + 96 > IOB) resb 1  ; (line is drawn from after
                                        ;  redraw, which builds rowbuf and
                                        ;  stat_new: it stays past them)
run_bss_end:
