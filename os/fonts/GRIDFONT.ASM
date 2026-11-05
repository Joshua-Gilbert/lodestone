; GRIDFONT.FNT - GRiD's InteGRiD system font (TC8X16, the 8x16 font built into
; GRID.EXE) as a font file: Lodestone's font until Lodefont.  It is on ROM 2;
; on a floppy, put it in the root of the disk and choose it in System,
; Display (Return switches).  A .FNT is 96 glyphs of 8x16, codes 32-127,
; 16 bytes each, top row first (1,536 bytes).
;   nasm -f bin -o GRIDFONT.FNT GRIDFONT.ASM
%include "GRIDFONT.INC"
