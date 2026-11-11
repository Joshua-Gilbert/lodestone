; WPTSR.COM (test_mt t_ends): E.TXT created and 600 bytes written to it,
; then resident (AH=31h) with E.TXT still open: its task's end closes it
;   nasm -f bin -o WPTSR.COM WPTSR.ASM
org 100h
        mov     dx, name
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .r
        mov     bx, ax
        mov     cx, 600
        mov     dx, 100h
        mov     ah, 40h
        int     21h
.r:     mov     dx, 30h                 ; paragraphs to keep
        mov     ax, 3100h
        int     21h
name    db      'E.TXT', 0
