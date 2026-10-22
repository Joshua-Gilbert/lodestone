; NULDIR.COM (test_kernel t_nul): OPEN, CREATE, FIND FIRST, GET ATTRIBUTES
; and CREATE NEW of a device's name after a directory that is there, is a
; file, or isn't there ("IF EXIST DIR\NUL").  Each line: fn, the name, ok
; or the error.  test_kernel holds the answers GRiD MS-DOS 3.30 gives
org 100h
        mov     si, tests
.t:     lodsw                   ; function
        or      ax, ax
        jz      .done
        mov     bx, ax
        lodsw                   ; name 1
        mov     dx, ax
        lodsw                   ; name 2 (ES:DI for 56h)
        mov     di, ax
        lodsw                   ; CX
        mov     [tcx], ax
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
        mov     si, dx
        call    pz
        or      di, di
        jz      .one
        mov     ah, 2
        mov     dl, '>'
        int     21h
        mov     si, di
        call    pz
.one:   pop     dx
        mov     ah, bh
        mov     al, 0
        cmp     ah, 3Dh
        jne     .go
        mov     al, 2                   ; open: read/write
.go:    mov     cx, [tcx]
        push    ds
        pop     es
        int     21h
        jc      .err
        cmp     bh, 3Dh                 ; a handle: close it
        je      .cl
        cmp     bh, 3Ch
        je      .cl
        cmp     bh, 5Bh
        jne     .ok
.cl:    mov     bx, ax
        mov     ah, 3Eh
        int     21h
.ok:    mov     ah, 9
        mov     dx, s_ok
        int     21h
        jmp     .nx
.err:   push    ax
        mov     ah, 9
        mov     dx, s_err
        int     21h
        pop     ax
        call    phex
.nx:    mov     ah, 9
        mov     dx, s_nl
        int     21h
        pop     si
        jmp     .t
.done:  mov     ax, 4C00h
        int     21h
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
        and     al, 15
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        int     21h
        ret
tcx     dw 0
s_f     db 'fn $'
s_ok    db ' -> ok$'
s_err   db ' -> err $'
s_nl    db 13, 10, '$'
; X15: a second dot (A.TXT, B.TXT, A.B\X.TXT and E.F empty are there)
tests   dw 3D00h, p0, 0, 0
        dw 3D00h, p1, 0, 0
        dw 3D00h, p2, 0, 0
        dw 3D00h, p3, 0, 0
        dw 3D00h, p4, 0, 0
        dw 3D00h, p5, 0, 0
        dw 3D00h, p6, 0, 0
        dw 3D00h, p7, 0, 0
        dw 3D00h, p8, 0, 0
        dw 3D00h, p9, 0, 0
        dw 3D00h, p10, 0, 0
        dw 3D00h, p11, 0, 0
        dw 3D00h, p12, 0, 0
        dw 3D00h, p13, 0, 0
        dw 3D00h, p14, 0, 0
        dw 3D00h, p15, 0, 0
        dw 3C00h, p0, 0, 0
        dw 3C00h, p1, 0, 0
        dw 3C00h, p2, 0, 0
        dw 3C00h, p3, 0, 0
        dw 3C00h, p4, 0, 0
        dw 3C00h, p5, 0, 0
        dw 3C00h, p6, 0, 0
        dw 3C00h, p7, 0, 0
        dw 3C00h, p8, 0, 0
        dw 3C00h, p9, 0, 0
        dw 3C00h, p10, 0, 0
        dw 3C00h, p11, 0, 0
        dw 3C00h, p12, 0, 0
        dw 3C00h, p13, 0, 0
        dw 3C00h, p14, 0, 0
        dw 3C00h, p15, 0, 0
        dw 4E00h, p0, 0, 0
        dw 4E00h, p1, 0, 0
        dw 4E00h, p2, 0, 0
        dw 4E00h, p3, 0, 0
        dw 4E00h, p4, 0, 0
        dw 4E00h, p5, 0, 0
        dw 4E00h, p6, 0, 0
        dw 4E00h, p7, 0, 0
        dw 4E00h, p8, 0, 0
        dw 4E00h, p9, 0, 0
        dw 4E00h, p10, 0, 0
        dw 4E00h, p11, 0, 0
        dw 4E00h, p12, 0, 0
        dw 4E00h, p13, 0, 0
        dw 4E00h, p14, 0, 0
        dw 4E00h, p15, 0, 0
        dw 4300h, p0, 0, 0
        dw 4300h, p1, 0, 0
        dw 4300h, p2, 0, 0
        dw 4300h, p3, 0, 0
        dw 4300h, p4, 0, 0
        dw 4300h, p5, 0, 0
        dw 4300h, p6, 0, 0
        dw 4300h, p7, 0, 0
        dw 4300h, p8, 0, 0
        dw 4300h, p9, 0, 0
        dw 4300h, p10, 0, 0
        dw 4300h, p11, 0, 0
        dw 4300h, p12, 0, 0
        dw 4300h, p13, 0, 0
        dw 4300h, p14, 0, 0
        dw 4300h, p15, 0, 0
        dw 5B00h, p0, 0, 0
        dw 5B00h, p1, 0, 0
        dw 5B00h, p2, 0, 0
        dw 5B00h, p3, 0, 0
        dw 5B00h, p4, 0, 0
        dw 5B00h, p5, 0, 0
        dw 5B00h, p6, 0, 0
        dw 5B00h, p7, 0, 0
        dw 5B00h, p8, 0, 0
        dw 5B00h, p9, 0, 0
        dw 5B00h, p10, 0, 0
        dw 5B00h, p11, 0, 0
        dw 5B00h, p12, 0, 0
        dw 5B00h, p13, 0, 0
        dw 5B00h, p14, 0, 0
        dw 5B00h, p15, 0, 0
        dw 0
p0      db 'NOSUCH\NUL', 0
p1      db 'A.B\NUL', 0
p2      db 'A.TXT\NUL', 0
p3      db '\NUL', 0
p4      db 'NUL', 0
p5      db 'A:NUL', 0
p6      db 'A:\NUL', 0
p7      db 'NOSUCH\CON', 0
p8      db 'A.B\CON', 0
p9      db 'A.B\NUL.TXT', 0
p10     db 'NOSUCH\NUL.TXT', 0
p11     db 'NOSUCH\SUB\NUL', 0
p12     db 'A.B\..\NUL', 0
p13     db 'A.B\.\NUL', 0
p14     db 'A.B\NOSUCH\NUL', 0
p15     db 'E.F\NUL', 0
