; TSR.COM - stays resident with 512 bytes (tests/test_apps.py: something
; resident right after the UI block)
;   nasm -f bin -o TSR.COM TSR.ASM
;   (-DKEEP=n: n paragraphs; test_apps builds TSRBIG.COM with 400h, 16 KB)
%ifndef KEEP
%define KEEP 20h
%endif
org 100h
        mov     dx, KEEP                ; paragraphs to keep
        mov     ax, 3100h
        int     21h
