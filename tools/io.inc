; shared helpers (from GPIBTEST 1.0)
tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret


log_open:
        mov     dx, n_log
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .n
        mov     [fh], ax
.n:     ret

log_close:
        call    flush
        mov     bx, [fh]
        or      bx, bx
        jz      .n
        mov     ah, 3Eh
        int     21h
.n:     ret

puts:   pusha
        mov     ah, 09h
        int     21h
        cmp     word [fh], 0
        je      .r
        mov     si, dx
.l:     lodsb
        cmp     al, '$'
        je      .r
        call    fput
        jmp     .l
.r:     popa
        ret

putc:   pusha
        mov     dl, al
        mov     ah, 02h
        int     21h
        cmp     word [fh], 0
        je      .r
        mov     al, dl
        call    fput
.r:     popa
        ret

fput:   mov     bx, [bufn]
        mov     [fbuf+bx], al
        inc     bx
        mov     [bufn], bx
        cmp     bx, 512
        jb      .r
        call    flush
.r:     ret

flush:  pusha
        mov     cx, [bufn]
        jcxz    .r
        mov     bx, [fh]
        or      bx, bx
        jz      .r
        mov     dx, fbuf
        mov     ah, 40h
        int     21h
        mov     word [bufn], 0
.r:     popa
        ret

commit: call    flush
        pusha
        mov     bx, [fh]
        or      bx, bx
        jz      .r
        mov     ah, 68h
        int     21h
.r:     popa
        ret

crlf:   push    dx
        mov     dx, s_crlf
        call    puts
        pop     dx
        ret

phex8:  push    ax
        shr     al, 4
        call    .n
        pop     ax
        push    ax
        and     al, 0Fh
        call    .n
        pop     ax
        ret
.n:     add     al, '0'
        cmp     al, '9'
        jbe     .o
        add     al, 7
.o:     jmp     putc

pdec2:  push    ax
        cmp     ax, 10
        jae     .n
        mov     al, ' '
        call    putc
.n:     pop     ax
pdec:   pusha
        xor     cx, cx
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     ax
        add     al, '0'
        call    putc
        loop    .p
        popa
        ret

