; =====================================================================
;  TERMCELL.INC - drawing character cells on the GRiD's 640x400 screen
;  (mode 40h: 4 banks, 80 bytes a line; a cell is 8x16, so row r of
;  cells starts at r * 320 in every bank).  The font is CS-relative.
; =====================================================================

%include "CELL.INC"                     ; cell: one character cell

; =====================================================================
;  Term: the screen Claude Code draws on the Pi, rows 0-23, kept in a
;  shadow (TROWS x 80 words: glyph, attribute) in [shadseg] so it can be
;  redrawn after a DOS program (RUN) or on CODE-R without the Pi.
;  CELLS (Pi -> GRiD 4Bh): flags (bit 0 clear, bit 1 cursor hidden),
;  cursor row, cursor column, then operations:
;    run    row, col, len (bit 7: attribute follows), [attr], glyphs
;    fill   row | 80h, col, len, [attr], one glyph
;    scroll FEh, top, bottom, n: rows top..bottom up by n
;  A malformed operation ends the frame (the Pi's next ones repaint).
; =====================================================================
TROWS   equ 24

; DS:SI -> CELLS payload, CX = its length
term_cells:
        cmp     cx, 3
        jb      .r
        push    es
        mov     ax, VSEG
        mov     es, ax
        call    cur_off
        mov     bx, si
        add     bx, cx                  ; BX = end of the payload
        lodsb
        mov     [t_flags], al
        lodsw
        mov     [t_cur], ax             ; AL = row, AH = column
        test    byte [t_flags], 1
        jz      .op
        call    term_clear
.op:    cmp     si, bx
        jae     .done
        lodsb
        cmp     al, 0FEh
        je      .scroll
        mov     dl, al                  ; DL = row (bit 7: fill)
        cmp     si, bx
        jae     .done
        lodsb
        mov     dh, al                  ; DH = column
        cmp     si, bx
        jae     .done
        lodsb
        xor     ah, ah                  ; AH = attribute
        mov     cl, al
        and     cx, 7Fh                 ; CX = cells
        jz      .done
        test    al, 80h
        jz      .na
        cmp     si, bx
        jae     .done
        mov     ah, [si]
        inc     si
.na:    mov     al, dl
        and     al, 7Fh
        cmp     al, TROWS
        jae     .done
        mov     al, dh
        add     al, cl
        jc      .done
        cmp     al, 80
        ja      .done
        test    dl, 80h
        jnz     .fill
        push    cx                      ; run: CX glyphs follow
        add     cx, si
        cmp     cx, bx
        pop     cx
        ja      .done
.run:   lodsb
        call    put_cell
        inc     dh
        loop    .run
        jmp     .op
.fill:  and     dl, 7Fh
        cmp     si, bx
        jae     .done
        lodsb
.fl:    call    put_cell
        inc     dh
        loop    .fl
        jmp     .op
.scroll:
        lea     ax, [si+3]
        cmp     ax, bx
        ja      .done
        lodsw                           ; AL = top, AH = bottom
        mov     dx, ax
        lodsb
        call    term_scroll
        jmp     .op
.done:  mov     ax, [t_cur]
        test    byte [t_flags], 2
        jnz     .nc
        cmp     al, TROWS
        jae     .nc
        cmp     ah, 80
        jae     .nc
        mov     cl, ah
        xor     ah, ah
        imul    di, ax, 320
        xor     ch, ch
        add     di, cx
        mov     [cur_di], di
        call    cur_xor
        mov     byte [cur_on], 1
.nc:    pop     es
.r:     ret

; AL = glyph, AH = attribute, DL = row, DH = column; ES = VSEG.
; The shadow and the screen.  Keeps everything.
put_cell:
        push    ax
        push    bx
        push    di
        push    es
        mov     bl, dl
        xor     bh, bh
        imul    di, bx, 160
        mov     bl, dh
        shl     bx, 1
        add     di, bx
        mov     es, [shadseg]
        mov     [es:di], ax
        pop     es
        mov     bl, dl
        xor     bh, bh
        imul    di, bx, 320
        mov     bl, dh
        add     di, bx
        call    cell
        pop     di
        pop     bx
        pop     ax
        ret

; DL = top, DH = bottom, AL = n: rows top..bottom up by n, blanks below.
; ES = VSEG.  Keeps SI, BX.
term_scroll:
        cmp     dh, TROWS
        jae     .x
        cmp     dl, dh
        ja      .x
        mov     cl, dh
        sub     cl, dl
        inc     cl                      ; CL = rows in the region
        or      al, al
        jz      .x
        cmp     al, cl
        ja      .x
        pusha
        push    ds
        sub     cl, al                  ; CL = rows that move
        xor     ch, ch
        mov     bl, al
        xor     bh, bh                  ; BX = n
        mov     al, dl
        xor     ah, ah
        mov     bp, ax                  ; BP = top
        ; the screen: in each bank, rows of 320 bytes
        mov     ax, VSEG
        mov     ds, ax
        xor     dx, dx                  ; DX = bank base
.bank:  imul    di, bp, 320
        add     di, dx
        mov     ax, bp
        add     ax, bx
        imul    si, ax, 320
        add     si, dx
        push    cx
        imul    cx, cx, 160
        rep     movsw
        imul    cx, bx, 160
        xor     ax, ax
        rep     stosw
        pop     cx
        add     dx, 2000h
        cmp     dx, 8000h
        jb      .bank
        pop     ds
        ; the shadow: rows of 160 bytes
        push    ds
        mov     es, [shadseg]
        mov     ds, [shadseg]
        imul    di, bp, 160
        mov     ax, bp
        add     ax, bx
        imul    si, ax, 160
        imul    cx, cx, 80
        rep     movsw
        imul    cx, bx, 80
        mov     ax, 0020h
        rep     stosw
        pop     ds
        mov     ax, VSEG
        mov     es, ax
        popa
.x:     ret

; rows 0-23 blank, on the screen and in the shadow.  ES = VSEG.
term_clear:
        pusha
        xor     dx, dx
.b:     mov     di, dx
        mov     cx, TROWS * 320 / 2
        xor     ax, ax
        rep     stosw
        add     dx, 2000h
        cmp     dx, 8000h
        jb      .b
        call    shadow_clear
        popa
        ret

shadow_clear:
        push    es
        push    ax
        push    cx
        push    di
        mov     es, [shadseg]
        xor     di, di
        mov     ax, 0020h
        mov     cx, TROWS * 80
        rep     stosw
        pop     di
        pop     cx
        pop     ax
        pop     es
        ret

; the cursor: glyph rows 14 and 15 of the cell at [cur_di], inverted
cur_xor:
        push    di
        mov     di, [cur_di]
        not     byte [es:di + 4000h + 240]
        not     byte [es:di + 6000h + 240]
        pop     di
        ret

cur_off:
        cmp     byte [cur_on], 0
        je      .x
        call    cur_xor
        mov     byte [cur_on], 0
.x:     ret

; the whole Term screen again from the shadow, the cursor and row 24
term_redraw:
        pusha
        push    es
        mov     ax, VSEG
        mov     es, ax
        xor     di, di                  ; all four banks (term_status draws row 24)
        mov     cx, 8000h / 2
        xor     ax, ax
        rep     stosw
        xor     di, di                  ; screen cell
        xor     si, si                  ; shadow word
        mov     bx, TROWS
.row:   mov     cx, 80
.c:     push    ds
        mov     ds, [cs:shadseg]
        lodsw
        pop     ds
        cmp     ax, 0020h
        je      .s                      ; blank: already
        call    cell
.s:     inc     di
        loop    .c
        add     di, 320 - 80
        dec     bx
        jnz     .row
        cmp     byte [cur_on], 0
        je      .st
        call    cur_xor
.st:    pop     es
        popa
        call    term_status
        ret

; row 24: the title on the left, the link or the keys on the right
term_status:
        pusha
        push    es
        mov     ax, VSEG
        mov     es, ax
        mov     dx, TROWS
        mov     ah, 1
        call    blank_row
        mov     di, TROWS * 320 + 1
        mov     si, title_text
        mov     cx, 48                  ; (the keys take columns 50-78)
        call    draw_strn
        mov     si, s_tkeys
%ifdef WEB_CHECK
        cmp     byte [web_old], 0       ; (CLAUDE /W, an older gridlink on the Pi)
        je      .k
        mov     si, s_webold
.k:
%endif
        cmp     byte [connected], 0
        jne     .r
        mov     si, status_text
.r:     call    strlen
        cmp     cx, 70
        jbe     .w
        mov     cx, 70
.w:     mov     di, TROWS * 320 + 79
        sub     di, cx
        call    draw_strn
        pop     es
        popa
        ret
