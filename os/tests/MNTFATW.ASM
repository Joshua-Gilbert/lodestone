; MNTFATW.COM (test_kernel t_mount): as DEFRAG or CHKDSK /F on a floppy:
; INT 21h 0Dh, A:'s FAT sector 0 changed through INT 13h (cluster 300
; marked bad), INT 21h 0Dh
org 100h
        mov     ah, 0Dh
        int     21h
        mov     ax, 0201h
        mov     cx, 0002h
        mov     dx, 0000h
        mov     bx, buf
        int     13h
        jc      .x
        or      word [buf+450], 0FF7h
        mov     ax, 0301h
        mov     cx, 0002h
        mov     dx, 0000h
        mov     bx, buf
        int     13h
        mov     ah, 0Dh
        int     21h
.x:     mov     ax, 4C00h
        int     21h
buf:
