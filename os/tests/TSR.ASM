; TSR.COM - stays resident with 512 bytes (tests/test_apps.py: something
; resident right after the UI block)
;   nasm -f bin -o TSR.COM TSR.ASM
org 100h
        mov     dx, 20h                 ; paragraphs to keep
        mov     ax, 3100h
        int     21h
