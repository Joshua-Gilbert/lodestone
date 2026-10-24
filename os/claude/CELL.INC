; =====================================================================
;  CELL.INC - one character cell on the GRiD's 640x400 screen (mode 40h:
;  4 banks, 80 bytes a line; a cell is 8x16, so row r of cells starts at
;  r * 320 in every bank).  The font (`font`, TERMINUS.INC then
;  GLYPHS.INC) is CS-relative.  CLAUDE.COM (TERMCELL.INC) and resident
;  Claude's console (RCON.ASM, in EMS) both draw with it.
; =====================================================================

%ifndef GLYPH_END
%define GLYPH_END 0A1h                  ; (the first code with no glyph)
%endif

; One character cell.  AL = char, AH = attribute (1 inverse, 2 underline),
; DI = row * 320 + column, ES = VSEG.  Destroys AX only.
cell:   push    bx
        push    cx
        xor     cl, cl
        test    ah, 1
        jz      .a
        mov     cl, 0FFh
.a:     mov     ch, ah
        cmp     al, 20h
        jae     .b
        mov     al, 20h
.b:     cmp     al, GLYPH_END
        jb      .c
        mov     al, '?'
.c:     sub     al, 20h
        xor     ah, ah
        shl     ax, 4
        add     ax, font
        mov     bx, ax
%assign r 0
%rep 16
        mov     al, [cs:bx + r]
        xor     al, cl
        mov     [es:di + (r & 3) * 2000h + (r >> 2) * 80], al
%assign r r + 1
%endrep
        test    ch, 2
        jz      .d
        mov     al, 0FFh
        xor     al, cl
        mov     [es:di + 4000h + 240], al       ; glyph row 14
.d:     pop     cx
        pop     bx
        ret
