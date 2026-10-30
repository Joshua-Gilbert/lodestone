; =====================================================================
;  CELL.INC - one character cell on the GRiD's 640x400 screen (mode 40h:
;  4 banks, 80 bytes a line; a cell is 8x16, so row r of cells starts at
;  r * 320 in every bank).  The font (`font`, TERMINUS.INC then
;  GLYPHS.INC) is CS-relative.  CLAUDE.COM (TERMCELL.INC) and resident
;  Claude's console (RCON.ASM, in EMS) both draw with it; the terminal
;  window (apps/TERM.ASM) too, with its own font: CELL_FSEG the font's
;  segment register (CELL_FDS defined: DS's, with no prefix, which NASM
;  writes even for ds:), CELL_FONT its offset, CELL_FIRST its first code
;  (none below it drawn: a space), GLYPH_END the first code with no glyph
;  ('?'; 100h: every code has one).  CLAUDE.ASM's, RCON.ASM's and TERM.ASM's
;  EVEN lists name its labels: code that moves them stops those builds.
; =====================================================================

%ifndef GLYPH_END
%define GLYPH_END 0A1h                  ; (the first code with no glyph)
%endif
%ifndef CELL_FSEG
%define CELL_FSEG cs
%endif
%ifndef CELL_FONT
%define CELL_FONT font
%endif
%ifndef CELL_FIRST
%define CELL_FIRST 20h
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
%if CELL_FIRST > 0
        cmp     al, CELL_FIRST
        jae     .b
        mov     al, 20h
.b:
%endif
%if GLYPH_END < 100h
        cmp     al, GLYPH_END
        jb      .c
        mov     al, '?'
.c:
%endif
%if CELL_FIRST > 0
        sub     al, CELL_FIRST
%endif
        xor     ah, ah
        shl     ax, 4
        add     ax, CELL_FONT
        mov     bx, ax
%assign r 0
%rep 16
%ifdef CELL_FDS
        mov     al, [bx + r]
%else
        mov     al, [CELL_FSEG:bx + r]
%endif
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
