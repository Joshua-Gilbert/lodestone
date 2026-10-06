; shared helpers (from GPIBTEST 1.0)
tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret


pit_init:
        mov     byte [pitset], 1
        mov     al, 34h
        jmp     short pitw
pit_done:
        cmp     byte [pitset], 0
        je      pitx
        mov     byte [pitset], 0
        mov     al, 36h
pitw:   cli
        out     43h, al
        xor     al, al
        out     40h, al
        jmp     short $+2
        out     40h, al
        sti
pitx:   ret

; DX:AX = time in PIT counts (1.193 MHz): BIOS tick * 65536 + counter.
; Retries if a tick happens while reading.
stamp:  push    bx
        push    cx
.r:     call    tick
        mov     bx, ax
        cli
        xor     al, al
        out     43h, al                 ; latch counter 0
        jmp     short $+2
        in      al, 40h
        mov     cl, al
        jmp     short $+2
        in      al, 40h
        mov     ch, al
        sti
        nop
        call    tick
        cmp     ax, bx
        jne     .r
        mov     ax, cx
        neg     ax                      ; counts elapsed in this tick
        mov     dx, bx
        pop     cx
        pop     bx
        ret

; DX:AX = DX:AX / CX  (32/16 long division, remainder in BX)
ldiv:   push    si
        mov     si, ax
        mov     ax, dx
        xor     dx, dx
        div     cx
        push    ax
        mov     ax, si
        div     cx
        mov     bx, dx
        pop     dx
        pop     si
        ret

; print DX:AX PIT counts as milliseconds "nnnn.n" (width 7)
pms:    pusha
        mov     cx, 1193
        call    ldiv                    ; DX:AX = ms, BX = remainder
        or      dx, dx
        jz      .ok
        mov     ax, 0FFFFh
.ok:    push    ax
        mov     ax, bx
        mov     bx, 10
        mul     bx
        div     cx                      ; tenths
        mov     bl, al
        pop     ax
        mov     cl, 5
        call    pdecw
        mov     al, '.'
        call    putc
        mov     al, bl
        add     al, '0'
        call    putc
        popa
        ret

; print AX right-aligned in CL columns
pdecw:  pusha
        mov     bx, ax
        mov     ch, 1
        mov     si, 10
.c:     cmp     ax, 10
        jb      .p
        xor     dx, dx
        div     si
        inc     ch
        jmp     .c
.p:     cmp     ch, cl
        jae     .n
        mov     al, ' '
        call    putc
        inc     ch
        jmp     .p
.n:     mov     ax, bx
        call    pdec
        popa
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

