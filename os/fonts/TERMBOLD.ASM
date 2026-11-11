; TERMBOLD.FNT - a font file for Lodestone 0.3, the font Lodestone used
; before GRiD's: glyphs from Terminus Font (Bold 16), modified, so not
; named Terminus (the OFL's Reserved Font Name; its license: OFL.TXT).
; Put it in the root of the disk and choose it in System, Display (Return
; switches).  A .FNT is just 96 glyphs of 8x16,
; codes 32-127, 16 bytes each, top row first (1,536 bytes).
;   nasm -f bin -i ../src/ -o TERMBOLD.FNT TERMBOLD.ASM
%include "TERMINUS.INC"
