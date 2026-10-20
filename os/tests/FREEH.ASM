; FREEH.COM - for test_mt.py: frees EMS handle N (INT 67h AH=45h), as a
; program that frees a handle not its own might.  FREEH N (decimal)
; nasm -f bin -o FREEH.COM FREEH.ASM
cpu 286
org 100h
        mov     si, 81h
        xor     dx, dx
.b:     lodsb
        cmp     al, ' '
        je      .b
.d:     sub     al, '0'
        cmp     al, 9
        ja      .f
        cbw
        imul    dx, dx, 10
        add     dx, ax
        lodsb
        jmp     .d
.f:     mov     ah, 45h
        int     67h
        mov     ax, 4C00h
        int     21h
