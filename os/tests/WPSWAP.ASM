; WPSWAP.COM (test_kernel t_wpfail): K.TXT opened, 600 bytes appended, INT
; 21h 0Dh (the FAT written: K.TXT's entry alone still to go) (A), a key
; (another disk goes in), Z.TXT created ("Z+" or "Z-n"), and the end
; with K.TXT still open (terminate closes it); the shell's INT 24h
org 100h
        mov     dx, name
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     bx, ax
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        mov     cx, 600
        mov     dx, 100h
        mov     ah, 40h
        int     21h
        mov     ah, 0Dh
        int     21h
        mov     dl, 'A'
        mov     ah, 2
        int     21h
        mov     ah, 8
        int     21h
        mov     dx, zname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        mov     dl, 'Z'
        mov     ah, 2
        int     21h
        mov     dl, '+'
        jnc     .o
        add     al, '0'
        push    ax
        mov     dl, '-'
        mov     ah, 2
        int     21h
        pop     dx
.o:     mov     ah, 2
        int     21h
.x:     mov     ax, 4C00h
        int     21h
name    db      'K.TXT', 0
zname   db      'Z.TXT', 0
