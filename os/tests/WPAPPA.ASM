; WPAPPA.COM (test_kernel t_wpfail): K.TXT opened and 600 bytes appended (a
; cluster taken, its FAT changed), its own INT 24h answering Abort always: on
; a write-protected disk the write's Abort ends it, and terminate's closes
; (still with this handler) and its flush (the shell's) ask again.  Abort
; there is Fail; else each one terminated again, for ever
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, name
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     bx, ax
        push    bx
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        pop     bx
        mov     cx, 600
        mov     dx, data
        mov     ah, 40h
        int     21h
.x:     mov     ax, 4C00h
        int     21h
h24:    mov     al, 2
        iret
name    db 'K.TXT', 0
data    times 600 db 'w'
