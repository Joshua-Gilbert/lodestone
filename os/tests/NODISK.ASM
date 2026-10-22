; NODISK.COM: calls on drive B with no disk in it.  Our INT 24h records AH (the
; answers allowed, read/write), DI (the error) and answers Fail.  Each line:
; fn, the name, ok or the error, then "crit AH DI" if INT 24h came, else "-".
; test_kernel t_nodisk holds GRiD MS-DOS 3.30's answers
org 100h
        mov     dx, i24
        mov     ax, 2524h
        int     21h
        mov     si, tests
.t:     lodsw
        or      ax, ax
        jz      .done
        mov     bx, ax                  ; function (AH) and AL
        lodsw
        mov     dx, ax                  ; the name (or DL for 36h/47h)
        mov     byte [seen], 0
        push    si
        push    dx
        mov     ah, 9
        mov     dx, s_f
        int     21h
        mov     al, bh
        call    phex
        mov     ah, 2
        mov     dl, ' '
        int     21h
        pop     dx
        push    dx
        cmp     bh, 36h
        je      .nn
        cmp     bh, 47h
        je      .nn
        mov     si, dx
        call    pz
.nn:    pop     dx
        mov     ax, bx
        xor     cx, cx
        cmp     bh, 4Eh
        jne     .c0
        mov     cx, 16h
.c0:
        cmp     bh, 36h
        jne     .n47
        mov     dl, 2                   ; B:
        int     21h
        cmp     ax, 0FFFFh
        jne     .ok
        mov     ax, 0FFh
        stc
        jmp     .res
.n47:   cmp     bh, 47h
        jne     .go
        mov     dl, 2
        mov     si, buf
        int     21h
        jmp     .res
.go:    mov     di, p_y                 ; (RENAME's new name)
        int     21h
.res:   jc      .err
        cmp     bh, 3Dh
        jne     .ok
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
.ok:    mov     ah, 9
        mov     dx, s_ok
        int     21h
        jmp     .cr
.err:   push    ax
        mov     ah, 9
        mov     dx, s_err
        int     21h
        pop     ax
        call    phex
.cr:    cmp     byte [seen], 0
        je      .nc
        mov     ah, 9
        mov     dx, s_crit
        int     21h
        mov     al, [c_ah]
        call    phex
        mov     ah, 2
        mov     dl, ' '
        int     21h
        mov     al, [c_di]
        call    phex
        jmp     .nx
.nc:    mov     ah, 9
        mov     dx, s_none
        int     21h
.nx:    mov     ah, 9
        mov     dx, s_nl
        int     21h
        pop     si
        jmp     .t
.done:  mov     ax, 4C00h
        int     21h
i24:    push    ds
        push    cs
        pop     ds
        inc     byte [seen]
        mov     [c_ah], ah
        mov     ax, di
        mov     [c_di], al
        pop     ds
        mov     al, 3                   ; Fail
        iret
pz:     lodsb
        or      al, al
        jz      .x
        mov     dl, al
        mov     ah, 2
        int     21h
        jmp     pz
.x:     ret
phex:   push    ax
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        int     21h
        ret
seen    db 0
c_ah    db 0
c_di    db 0
s_f     db 'fn $'
s_ok    db ' -> ok$'
s_err   db ' -> err $'
s_crit  db ' crit $'
s_none  db ' -$'
s_nl    db 13, 10, '$'
buf     times 70 db 0
tests   dw 3D00h, p_x, 3C00h, p_x, 4300h, p_x, 4E00h, p_all, 3B00h, p_root, 3900h, p_d, 3A00h, p_d
        dw 4100h, p_x, 5600h, p_x, 3600h, 0, 3D00h, p_x, 0
p_x     db 'B:X.TXT', 0
p_y     db 'B:Y.TXT', 0
p_all   db 'B:*.*', 0
p_root  db 'B:\', 0
p_d     db 'B:\D', 0
