; HOLE.COM - leaves 160 free paragraphs (2.5 KB) in memory, below a block
; it keeps, and stays resident.  (For CLAUDE /R: its stub must still go to
; the top of memory; a second INT 21h AH=48h, first fit, would take the
; hole.)
cpu 286
org 100h
        mov     bx, (fin - $$ + 100h + 15) / 16
        mov     ah, 4Ah                 ; ourselves: just this
        int     21h
        mov     bx, 160                 ; the hole-to-be,
        mov     ah, 48h
        int     21h
        jc      .err
        mov     [hole], ax
        mov     bx, 1                   ;  a block above it, kept,
        mov     ah, 48h
        int     21h
        jc      .err
        mov     es, [hole]              ;  and the hole freed
        mov     ah, 49h
        int     21h
        mov     dx, s_ok
        mov     ah, 9
        int     21h
        mov     dx, (fin - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
.err:   mov     dx, s_err
        mov     ah, 9
        int     21h
        mov     ax, 4C01h
        int     21h
hole    dw      0
s_ok    db      'HOLE: 160 paragraphs free, below a block kept', 13, 10, '$'
s_err   db      'HOLE: no memory', 13, 10, '$'
fin:
