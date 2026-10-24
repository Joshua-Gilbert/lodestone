; TERM.FNT - the terminal window's font (TERM.RUN, with MULTITASK=1): all 256
; codes of code page 437, 8x16, 16 bytes each, top row first (4,096 bytes),
; from Terminus Bold 16 (TERM437.INC, made by tools/mkfnt437.py).
;   nasm -f bin -o TERM.FNT TERM.ASM
%include "TERM437.INC"
