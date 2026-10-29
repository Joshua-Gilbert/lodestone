; TSRK.COM - ends staying resident (INT 21h 31h), for CLAUDE's run_back
; (audit3 O17: a RUN's program that keeps memory where CLAUDE's buffers were)
;   TSRK     keeps 64 paragraphs (its PSP and 768 bytes)
;   TSRK B   keeps all it got but 160 paragraphs: no room left for CLAUDE
;   nasm -f bin -o TSRK.COM TSRK.ASM
org 100h
        mov     dx, 64
        cmp     byte [82h], 'B'
        jne     .k
        mov     dx, [2]
        mov     ax, cs
        sub     dx, ax
        sub     dx, 160
.k:     mov     ax, 3100h
        int     21h
