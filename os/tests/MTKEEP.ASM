; MTKEEP.COM (test_mt t_dkeep): open B:K.TXT, write 600 bytes at its end,
; wait for a key (INT 21h 08h), write 600 more, close; each result (+ or -,
; AX in hex) into A:RES2.TXT.  TWICE (MTKEEP2.COM): a key and 600 more
; before the last ones
org 100h
        mov     ax, 3D02h
        mov     dx, kn
        int     21h
        jc      .e1
        mov     [h], ax
        mov     bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        mov     bx, [h]
        mov     ah, 40h
        mov     cx, 600
        mov     dx, buf
        int     21h
        jc      .e1
%ifdef TWICE
        mov     ah, 08h
        int     21h
        mov     bx, [h]
        mov     ah, 40h
        mov     cx, 600
        mov     dx, buf
        int     21h
        call    rec
%endif
        mov     ah, 08h
        int     21h
        mov     bx, [h]
        mov     ah, 40h
        mov     cx, 600
        mov     dx, buf
        int     21h
        call    rec
        mov     bx, [h]
        mov     ah, 3Eh
        int     21h
        call    rec
        jmp     .wr
.e1:    call    rec
.wr:    mov     ah, 3Ch
        xor     cx, cx
        mov     dx, nr
        int     21h
        mov     bx, ax
        mov     ah, 40h
        mov     cx, [rp]
        sub     cx, res
        mov     dx, res
        int     21h
        mov     ah, 3Eh
        int     21h
        mov     ax, 4C00h
        int     21h
rec:    pushf
        mov     di, [rp]
        mov     byte [di], '+'
        popf
        jnc     .o
        mov     byte [di], '-'
.o:     inc     di
        mov     cx, ax
        mov     al, ch
        call    hb
        mov     al, cl
        call    hb
        mov     byte [di], ' '
        inc     di
        mov     [rp], di
        ret
hb:     push    ax
        shr     al, 4
        call    hx
        pop     ax
        and     al, 15
hx:     add     al, '0'
        cmp     al, '9'
        jbe     .x
        add     al, 7
.x:     mov     [di], al
        inc     di
        ret
h       dw 0
rp      dw res
kn      db 'B:K.TXT', 0
nr      db 'A:RES2.TXT', 0
res     times 40 db 0
buf     times 600 db 'H'
