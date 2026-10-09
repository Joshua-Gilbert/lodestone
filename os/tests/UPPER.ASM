; UPPER.COM - standard input to standard output in upper case (a filter
; for testing pipes and redirection); exit code = lines seen (max 255)
cpu 286
org 100h
        xor     bp, bp
.r:     xor     bx, bx
        mov     dx, buf
        mov     cx, 512
        mov     ah, 3Fh
        int     21h
        jc      .x
        or      ax, ax
        jz      .x
        mov     cx, ax
        mov     si, buf
.u:     mov     al, [si]
        cmp     al, 10
        jne     .nl
        inc     bp
.nl:    cmp     al, 'a'
        jb      .n
        cmp     al, 'z'
        ja      .n
        sub     byte [si], 20h
.n:     inc     si
        loop    .u
        mov     cx, ax
        mov     cx, si
        sub     cx, buf
        mov     bx, 1
        mov     dx, buf
        mov     ah, 40h
        int     21h
        jmp     .r
.x:     mov     ax, bp
        cmp     ax, 255
        jbe     .e
        mov     al, 255
.e:     mov     ah, 4Ch
        int     21h
buf:
