; MTADLY.COM (test_mt t_dkeep): about 2 s of ticks, then CREATE A:RES.TXT
; and write "ok" (an A: call: A:'s FAT loaded)
org 100h
        xor     ax, ax
        mov     es, ax
        mov     bx, [es:46Ch]
        add     bx, 36
.w:     mov     ah, 0Bh
        int     21h
        mov     ax, [es:46Ch]
        cmp     ax, bx
        jb      .w
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, nr
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
nr      db 'A:RES.TXT', 0
res     db 'ok'
