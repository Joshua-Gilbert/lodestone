; BUSY.COM - three seconds of work with no keyboard calls (it watches the
; BIOS's tick count at 40:6Ch), then "BUSY: done".
cpu 286
org 100h
        push    40h
        pop     es
        mov     bx, [es:6Ch]
.w:     mov     ax, [es:6Ch]
        sub     ax, bx
        cmp     ax, 55
        jb      .w
        mov     dx, s_done
        mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h
s_done  db      'BUSY: done', 13, 10, '$'
