; TERMINUS.FNT - a font file for Grid-OS 0.3: Terminus Bold 16, the font
; Grid-OS used before GRiD's.  Put it in the root of the disk and choose it
; in System, Display (Return switches).  A .FNT is just 96 glyphs of 8x16,
; codes 32-127, 16 bytes each, top row first (1,536 bytes).
;   nasm -f bin -i ../src/ -o TERMINUS.FNT TERMINUS.ASM
%include "TERMINUS.INC"
