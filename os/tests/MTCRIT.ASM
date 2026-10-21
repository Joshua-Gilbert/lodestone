; MTCRIT.COM - for test_mt.py: its own INT 24h handler prompting through DOS
; (AH=09h, then AH=01h for the answer, as INT 24h handlers may), then reads
; ZZ.DAT (test_mt makes its sectors bad).  FILE: "C" and the key that answered.
;   MTCRIT FILE B  the prompt through the BIOS's teletype (INT 10h 0Eh) instead
; nasm -f bin -o MTCRIT.COM MTCRIT.ASM
cpu 286
org 100h
        mov     sp, stk_top
        mov     ah, 4Ah
        mov     bx, (stk_top - $$ + 100h + 15) / 16
        int     21h
        mov     si, 81h
.b:     lodsb
        cmp     al, ' '
        je      .b
        dec     si
        mov     [fnm], si
.w:     lodsb
        cmp     al, ' '
        ja      .w
        mov     byte [si-1], 0
        cmp     al, 0Dh
        je      .o0
.o:     lodsb
        cmp     al, ' '
        je      .o
        and     al, 0DFh
        mov     [opt], al
.o0:
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     ax, 3D00h
        mov     dx, s_zz
        int     21h
        jc      .wr
        mov     bx, ax
        mov     ah, 3Fh
        mov     cx, 512
        mov     dx, buf
        int     21h
        mov     ah, 3Eh
        int     21h
.wr:    mov     ah, 3Ch
        xor     cx, cx
        mov     dx, [fnm]
        int     21h
        jc      .x
        mov     bx, ax
        mov     ah, 40h
        mov     cx, 2
        mov     dx, res
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

h24:    sti
        push    bx
        push    cx
        push    dx
        push    si
        push    ds
        push    cs
        pop     ds
        cmp     byte [opt], 'B'
        je      .b
        mov     dx, s_pr
        mov     ah, 9
        int     21h
        jmp     short .k
.b:     mov     si, s_pr                ; B: through the teletype
.l:     lodsb
        cmp     al, '$'
        je      .k
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     .l
.k:     mov     ah, 1
        int     21h
        mov     [res + 1], al
        pop     ds
        pop     si
        pop     dx
        pop     cx
        pop     bx
        mov     al, 3                   ; Fail
        iret

s_zz    db      'ZZ.DAT', 0
s_pr    db      13, 10, 'CRITPROMPT Abort, Retry, Fail? $'
res     db      'C?'
fnm     dw      0
opt     db      0
buf     times 512 db 0
        times 256 db 0
stk_top:
