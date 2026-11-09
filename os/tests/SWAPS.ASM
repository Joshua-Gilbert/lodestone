; SWAPS.COM script[/answers] (test_kernel t_swaps): each op of the script
; (the command tail) printed, then + or -, AX in hex; INT 24h prints
; [DI AH] and answers the next digit after '/' (Fail when none is left).
; Ops: o p open B:K.TXT, B:L.TXT; r R read 1; w W write 600; c C close;
; n create B:N.TXT; e b seek to the end, the start; m commit (68h); d INT
; 21h 0Dh; f find B:*.*; g a free space on B:, A:; v 59h.  Anything else
; is a sync: INT 21h AH=30h with BX=5A5Ah, CL the character (the test
; swaps disks there)
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     si, 81h
        mov     di, buf
        mov     cx, 700
        mov     al, 'Q'
        rep     stosb
        ; find '/' answers
        mov     di, 81h
.fa:    mov     al, [di]
        cmp     al, 13
        je      .na
        cmp     al, '/'
        je      .ga
        inc     di
        jmp     .fa
.ga:    mov     byte [di], 13
        inc     di
        mov     [ansp], di
.na:
lp:     lodsb
        cmp     al, 13
        je      done
        cmp     al, ' '
        je      lp
        mov     [op], al
        mov     dl, al
        mov     ah, 2
        int     21h
        mov     al, [op]
        mov     bx, ops
.f:     cmp     byte [bx], 0
        je      sync
        cmp     [bx], al
        je      .g
        add     bx, 3
        jmp     .f
.g:     push    si
        call    [bx+1]
        pop     si
        call    res
        jmp     lp
sync:   push    si
        mov     bx, 5A5Ah
        mov     ah, 30h
        mov     cl, [op]
        int     21h
        pop     si
        mov     dl, ' '
        mov     ah, 2
        int     21h
        jmp     lp
done:   mov     ax, 4C00h
        int     21h
res:    pushf
        push    ax
        mov     dl, '+'
        jnc     .o
        mov     dl, '-'
.o:     mov     ah, 2
        int     21h
        pop     ax
        push    ax
        mov     al, ah
        call    hx
        pop     ax
        call    hx
        mov     dl, ' '
        mov     ah, 2
        int     21h
        popf
        ret
hx:     push    ax
        shr     al, 4
        call    nb
        pop     ax
        and     al, 15
nb:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        int     21h
        ret
ops:    db 'o'
        dw op_o
        db 'p'
        dw op_p
        db 'r'
        dw op_r
        db 'R'
        dw op_R
        db 'w'
        dw op_w
        db 'W'
        dw op_W
        db 'c'
        dw op_c
        db 'C'
        dw op_C
        db 'n'
        dw op_n
        db 'e'
        dw op_e
        db 'b'
        dw op_b
        db 'm'
        dw op_m
        db 'd'
        dw op_d
        db 'f'
        dw op_f
        db 'g'
        dw op_g
        db 'v'
        dw op_v
        db 'a'
        dw op_a
        db 0
op_o:   mov     dx, kname
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     [h1], ax
.x:     ret
op_p:   mov     dx, lname
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     [h2], ax
.x:     ret
op_n:   mov     dx, nname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
        mov     [h1], ax
.x:     ret
op_r:   mov     bx, [h1]
rd:     mov     cx, 1
        mov     dx, rbuf
        mov     ah, 3Fh
        int     21h
        ret
op_R:   mov     bx, [h2]
        jmp     rd
op_w:   mov     bx, [h1]
wr:     mov     cx, 600
        mov     dx, buf
        mov     ah, 40h
        int     21h
        ret
op_W:   mov     bx, [h2]
        jmp     wr
op_c:   mov     bx, [h1]
clz:    mov     ah, 3Eh
        int     21h
        ret
op_C:   mov     bx, [h2]
        jmp     clz
op_e:   mov     ax, 4202h
sk:     mov     bx, [h1]
        xor     cx, cx
        xor     dx, dx
        int     21h
        ret
op_b:   mov     ax, 4200h
        jmp     sk
op_m:   mov     bx, [h1]
        mov     ah, 68h
        int     21h
        ret
op_d:   mov     ah, 0Dh
        int     21h
        clc
        ret
op_f:   mov     dx, wild
        mov     cx, 0
        mov     ah, 4Eh
        int     21h
        ret
op_g:   mov     ah, 36h
        mov     dl, 2
        int     21h
        cmp     ax, 0FFFFh
        cmc
        ret
op_a:   mov     ah, 36h
        mov     dl, 1
        int     21h
        cmp     ax, 0FFFFh
        cmc
        ret
op_v:   mov     ah, 59h
        xor     bx, bx
        int     21h
        clc
        ret
h24:    push    ax
        push    dx
        mov     dl, '['
        mov     ah, 2
        int     21h
        mov     ax, di
        call    hx
        pop     dx
        pop     ax
        push    ax
        mov     al, ah
        call    hx
        mov     dl, ']'
        mov     ah, 2
        int     21h
        pop     ax
        push    si
        mov     si, [cs:ansp]
        mov     al, 3
        or      si, si
        jz      .d
        cs lodsb
        cmp     al, 13
        jne     .s
        dec     si
        mov     al, '3'
.s:     mov     [cs:ansp], si
        sub     al, '0'
.d:     pop     si
        iret
h1      dw 0
h2      dw 0
op      db 0
ansp    dw 0
kname   db 'B:K.TXT', 0
lname   db 'B:L.TXT', 0
nname   db 'B:N.TXT', 0
wild    db 'B:*.*', 0
rbuf    db 0
buf:
