; FONTPACK.INC - Lodefont (FONT.INC) packed at build time, and its unpacker.
; Packed, each glyph is a word, bit r set where row r differs from the row
; before (0 before the first), then those rows: 753 bytes for 1,536.
;
; Included without FONTPACK_NAME: only the FONT_UNPACK macro (DS:SI the
; packed glyphs, ES:DI FONT_BYTES of room: unpacked there; AX, BX, CX, DX,
; SI and DI changed).  Included with FONTPACK_NAME defined: the packed
; glyphs here, under that label (LODE.ASM's font_z, SYSTEM.ASM's
; builtin_font), and FONTPACK_NAME undefined again.
%ifndef FONTPACK_MAC
%define FONTPACK_MAC
%macro FONT_UNPACK 0
        mov     dx, FONT_BYTES / 16
%%g:    lodsw
        xchg    ax, bx                  ; BX = the glyph's rows that change
        mov     al, 0
        mov     cx, 16
%%r:    shr     bx, 1
        jnc     %%s
        lodsb
%%s:    stosb
        loop    %%r
        dec     dx
        jnz     %%g
%endmacro
%endif

%ifdef FONTPACK_NAME
%macro db 16
%assign fz_m 0
%assign fz_p 0
%assign fz_i 0
%rep 16
%if %1 != fz_p
%assign fz_m fz_m | (1 << fz_i)
%endif
%assign fz_p %1
%assign fz_i fz_i + 1
%rotate 1
%endrep
        dw      fz_m
%assign fz_p 0
%rep 16
%if %1 != fz_p
        db      %1
%endif
%assign fz_p %1
%rotate 1
%endrep
%endmacro
%define font FONTPACK_NAME
%include "FONT.INC"
%undef font
%unmacro db 16
%undef FONTPACK_NAME
%endif
