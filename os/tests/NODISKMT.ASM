; NODISKMT.COM (test_mt t_nodisk): about 2 s of ticks, then OPEN B:X.TXT (no INT 24h of its own),
; its answer to A:RES.TXT ("ok" or the error in hex), then ends with 0
org 100h
        xor     ax, ax
        mov     es, ax
        mov     bx, [es:46Ch]
        add     bx, 36
.w:     mov     ah, 0Bh                 ; (a DOS call: somewhere to be switched)
        int     21h
        mov     ax, [es:46Ch]
        cmp     ax, bx
        jb      .w
        mov     ax, 3D00h
        mov     dx, nb
        int     21h
        mov     byte [res], 'o'
        mov     byte [res+1], 'k'
        jnc     .wr
        mov     cl, al
        shr     al, 4
        call    hx
        mov     [res], al
        mov     al, cl
        and     al, 0Fh
        call    hx
        mov     [res+1], al
.wr:    mov     ah, 3Ch
        xor     cx, cx
        mov     dx, nr
        int     21h
        mov     bx, ax
        mov     ah, 40h
        mov     cx, 2
        mov     dx, res
        int     21h
        mov     ah, 3Eh
        int     21h
        mov     ax, 4C00h
        int     21h
hx:     add     al, '0'
        cmp     al, '9'
        jbe     .x
        add     al, 7
.x:     ret
nb      db 'B:X.TXT', 0
nr      db 'A:RES.TXT', 0
res     db '??'
