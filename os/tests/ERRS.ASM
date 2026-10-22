; ERRS.COM (test_kernel t_errs): X17 and X20's path forms (a missing directory with a
; bad last name, a trailing \, two \s, . and .., an invalid drive, a long path, an
; empty name, devices) through each path call.  Each line: fn, the name(s), ok or
; the error.  test_kernel holds GRiD MS-DOS 3.30's answers
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
tests   dw 4300h, p0, 0, 0000h
        dw 4300h, p1, 0, 0000h
        dw 4300h, p2, 0, 0000h
        dw 4300h, p3, 0, 0000h
        dw 4300h, p4, 0, 0000h
        dw 4300h, p5, 0, 0000h
        dw 4300h, p6, 0, 0000h
        dw 4300h, p7, 0, 0000h
        dw 4300h, p8, 0, 0000h
        dw 4300h, p9, 0, 0000h
        dw 4300h, p10, 0, 0000h
        dw 4300h, p11, 0, 0000h
        dw 4300h, p12, 0, 0000h
        dw 4300h, p13, 0, 0000h
        dw 4300h, p14, 0, 0000h
        dw 4300h, p15, 0, 0000h
        dw 4300h, p16, 0, 0000h
        dw 4300h, p17, 0, 0000h
        dw 4300h, p18, 0, 0000h
        dw 4300h, p19, 0, 0000h
        dw 4300h, p20, 0, 0000h
        dw 4300h, p21, 0, 0000h
        dw 4300h, p22, 0, 0000h
        dw 4300h, p23, 0, 0000h
        dw 4300h, p24, 0, 0000h
        dw 4300h, p25, 0, 0000h
        dw 4300h, p26, 0, 0000h
        dw 4300h, p27, 0, 0000h
        dw 4300h, p28, 0, 0000h
        dw 4300h, p29, 0, 0000h
        dw 4300h, p30, 0, 0000h
        dw 4E00h, p0, 0, 0016h
        dw 4E00h, p1, 0, 0016h
        dw 4E00h, p2, 0, 0016h
        dw 4E00h, p3, 0, 0016h
        dw 4E00h, p4, 0, 0016h
        dw 4E00h, p5, 0, 0016h
        dw 4E00h, p6, 0, 0016h
        dw 4E00h, p7, 0, 0016h
        dw 4E00h, p8, 0, 0016h
        dw 4E00h, p9, 0, 0016h
        dw 4E00h, p10, 0, 0016h
        dw 4E00h, p11, 0, 0016h
        dw 4E00h, p31, 0, 0016h
        dw 4E00h, p12, 0, 0016h
        dw 4E00h, p13, 0, 0016h
        dw 4E00h, p32, 0, 0016h
        dw 4E00h, p15, 0, 0016h
        dw 4E00h, p16, 0, 0016h
        dw 4E00h, p17, 0, 0016h
        dw 4E00h, p18, 0, 0016h
        dw 4E00h, p19, 0, 0016h
        dw 4E00h, p20, 0, 0016h
        dw 4E00h, p21, 0, 0016h
        dw 4E00h, p22, 0, 0016h
        dw 4E00h, p23, 0, 0016h
        dw 4E00h, p24, 0, 0016h
        dw 4E00h, p27, 0, 0016h
        dw 4E00h, p28, 0, 0016h
        dw 4E00h, p29, 0, 0016h
        dw 4E00h, p30, 0, 0016h
        dw 3D00h, p0, 0, 0000h
        dw 3D00h, p1, 0, 0000h
        dw 3D00h, p2, 0, 0000h
        dw 3D00h, p3, 0, 0000h
        dw 3D00h, p4, 0, 0000h
        dw 3D00h, p5, 0, 0000h
        dw 3D00h, p6, 0, 0000h
        dw 3D00h, p7, 0, 0000h
        dw 3D00h, p8, 0, 0000h
        dw 3D00h, p9, 0, 0000h
        dw 3D00h, p10, 0, 0000h
        dw 3D00h, p11, 0, 0000h
        dw 3D00h, p12, 0, 0000h
        dw 3D00h, p13, 0, 0000h
        dw 3D00h, p14, 0, 0000h
        dw 3D00h, p15, 0, 0000h
        dw 3D00h, p16, 0, 0000h
        dw 3D00h, p17, 0, 0000h
        dw 3D00h, p18, 0, 0000h
        dw 3D00h, p19, 0, 0000h
        dw 3D00h, p20, 0, 0000h
        dw 3D00h, p23, 0, 0000h
        dw 3D00h, p24, 0, 0000h
        dw 3D00h, p33, 0, 0000h
        dw 3D00h, p25, 0, 0000h
        dw 3D00h, p26, 0, 0000h
        dw 3D00h, p27, 0, 0000h
        dw 3D00h, p28, 0, 0000h
        dw 3D00h, p29, 0, 0000h
        dw 3D00h, p30, 0, 0000h
        dw 3B00h, p0, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p1, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p2, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p3, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p4, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p5, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p6, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p7, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p8, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p9, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p10, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p35, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p11, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p31, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p12, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p13, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p14, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p32, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p15, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p16, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p17, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p18, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p19, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p20, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p21, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p36, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p37, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p22, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p23, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p24, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p33, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p25, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p26, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p27, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p28, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p29, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 3B00h, p30, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 5600h, p0, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p1, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p2, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p3, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p4, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p5, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p6, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p7, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p8, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p9, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p10, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p11, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p31, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p12, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p13, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p32, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p15, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p16, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p17, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p18, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p19, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p20, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p21, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p22, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p23, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p24, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p25, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p26, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p27, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p28, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p29, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p30, p38, 0000h
        dw 5600h, p38, p27, 0000h
        dw 5600h, p27, p0, 0000h
        dw 5600h, p0, p27, 0000h
        dw 5600h, p27, p1, 0000h
        dw 5600h, p1, p27, 0000h
        dw 5600h, p27, p2, 0000h
        dw 5600h, p2, p27, 0000h
        dw 5600h, p27, p3, 0000h
        dw 5600h, p3, p27, 0000h
        dw 5600h, p27, p4, 0000h
        dw 5600h, p4, p27, 0000h
        dw 5600h, p27, p5, 0000h
        dw 5600h, p5, p27, 0000h
        dw 5600h, p27, p6, 0000h
        dw 5600h, p6, p27, 0000h
        dw 5600h, p27, p7, 0000h
        dw 5600h, p7, p27, 0000h
        dw 5600h, p27, p8, 0000h
        dw 5600h, p8, p27, 0000h
        dw 5600h, p27, p9, 0000h
        dw 5600h, p9, p27, 0000h
        dw 5600h, p27, p10, 0000h
        dw 5600h, p10, p27, 0000h
        dw 5600h, p27, p11, 0000h
        dw 5600h, p11, p27, 0000h
        dw 5600h, p27, p31, 0000h
        dw 5600h, p31, p27, 0000h
        dw 5600h, p27, p12, 0000h
        dw 5600h, p12, p27, 0000h
        dw 5600h, p27, p13, 0000h
        dw 5600h, p13, p27, 0000h
        dw 5600h, p27, p14, 0000h
        dw 5600h, p27, p32, 0000h
        dw 5600h, p32, p27, 0000h
        dw 5600h, p27, p15, 0000h
        dw 5600h, p15, p27, 0000h
        dw 5600h, p27, p16, 0000h
        dw 5600h, p16, p27, 0000h
        dw 5600h, p27, p17, 0000h
        dw 5600h, p17, p27, 0000h
        dw 5600h, p27, p18, 0000h
        dw 5600h, p18, p27, 0000h
        dw 5600h, p27, p19, 0000h
        dw 5600h, p19, p27, 0000h
        dw 5600h, p27, p20, 0000h
        dw 5600h, p20, p27, 0000h
        dw 5600h, p27, p21, 0000h
        dw 5600h, p21, p27, 0000h
        dw 5600h, p27, p23, 0000h
        dw 5600h, p23, p27, 0000h
        dw 5600h, p27, p24, 0000h
        dw 5600h, p24, p27, 0000h
        dw 5600h, p25, p27, 0000h
        dw 5600h, p27, p26, 0000h
        dw 5600h, p26, p27, 0000h
        dw 5600h, p27, p27, 0000h
        dw 5600h, p27, p27, 0000h
        dw 5600h, p27, p28, 0000h
        dw 5600h, p28, p27, 0000h
        dw 5600h, p27, p29, 0000h
        dw 5600h, p29, p27, 0000h
        dw 5600h, p27, p30, 0000h
        dw 5600h, p30, p27, 0000h
        dw 4300h, p39, 0, 0000h
        dw 4100h, p39, 0, 0000h
        dw 3900h, p39, 0, 0000h
        dw 3A00h, p39, 0, 0000h
        dw 5600h, p39, p38, 0000h
        dw 5600h, p27, p39, 0000h
        dw 4300h, p40, 0, 0000h
        dw 4100h, p40, 0, 0000h
        dw 3900h, p40, 0, 0000h
        dw 3A00h, p40, 0, 0000h
        dw 5600h, p40, p38, 0000h
        dw 5600h, p27, p40, 0000h
        dw 4300h, p41, 0, 0000h
        dw 4100h, p41, 0, 0000h
        dw 3900h, p41, 0, 0000h
        dw 3A00h, p41, 0, 0000h
        dw 5600h, p41, p38, 0000h
        dw 5600h, p27, p41, 0000h
        dw 4300h, p26, 0, 0000h
        dw 4100h, p26, 0, 0000h
        dw 3900h, p26, 0, 0000h
        dw 3A00h, p26, 0, 0000h
        dw 5600h, p26, p38, 0000h
        dw 5600h, p27, p26, 0000h
        dw 4300h, p42, 0, 0000h
        dw 4100h, p42, 0, 0000h
        dw 3900h, p42, 0, 0000h
        dw 3A00h, p42, 0, 0000h
        dw 5600h, p42, p38, 0000h
        dw 5600h, p27, p42, 0000h
        dw 3A00h, p34, 0, 0000h
        dw 3A00h, p32, 0, 0000h
        dw 3B00h, p29, 0, 0000h
        dw 3A00h, p31, 0, 0000h
        dw 3A00h, p43, 0, 0000h
        dw 3A00h, p44, 0, 0000h
        dw 3A00h, p12, 0, 0000h
        dw 3B00h, p34, 0, 0000h
        dw 5B00h, p0, 0, 0000h
        dw 5B00h, p1, 0, 0000h
        dw 5B00h, p2, 0, 0000h
        dw 5B00h, p3, 0, 0000h
        dw 5B00h, p4, 0, 0000h
        dw 5B00h, p5, 0, 0000h
        dw 5B00h, p6, 0, 0000h
        dw 5B00h, p7, 0, 0000h
        dw 5B00h, p8, 0, 0000h
        dw 5B00h, p9, 0, 0000h
        dw 5B00h, p10, 0, 0000h
        dw 5B00h, p11, 0, 0000h
        dw 5B00h, p31, 0, 0000h
        dw 5B00h, p12, 0, 0000h
        dw 5B00h, p13, 0, 0000h
        dw 5B00h, p14, 0, 0000h
        dw 5B00h, p32, 0, 0000h
        dw 5B00h, p15, 0, 0000h
        dw 5B00h, p16, 0, 0000h
        dw 5B00h, p17, 0, 0000h
        dw 5B00h, p18, 0, 0000h
        dw 5B00h, p19, 0, 0000h
        dw 5B00h, p20, 0, 0000h
        dw 5B00h, p23, 0, 0000h
        dw 5B00h, p24, 0, 0000h
        dw 5B00h, p33, 0, 0000h
        dw 5B00h, p25, 0, 0000h
        dw 5B00h, p26, 0, 0000h
        dw 5B00h, p30, 0, 0000h
        dw 3C00h, p0, 0, 0000h
        dw 3C00h, p1, 0, 0000h
        dw 3C00h, p2, 0, 0000h
        dw 3C00h, p3, 0, 0000h
        dw 3C00h, p4, 0, 0000h
        dw 3C00h, p5, 0, 0000h
        dw 3C00h, p6, 0, 0000h
        dw 3C00h, p7, 0, 0000h
        dw 3C00h, p8, 0, 0000h
        dw 3C00h, p9, 0, 0000h
        dw 3C00h, p10, 0, 0000h
        dw 3C00h, p11, 0, 0000h
        dw 3C00h, p31, 0, 0000h
        dw 3C00h, p12, 0, 0000h
        dw 3C00h, p13, 0, 0000h
        dw 3C00h, p14, 0, 0000h
        dw 3C00h, p32, 0, 0000h
        dw 3C00h, p15, 0, 0000h
        dw 3C00h, p16, 0, 0000h
        dw 3C00h, p17, 0, 0000h
        dw 3C00h, p18, 0, 0000h
        dw 3C00h, p19, 0, 0000h
        dw 3C00h, p20, 0, 0000h
        dw 3C00h, p23, 0, 0000h
        dw 3C00h, p24, 0, 0000h
        dw 3C00h, p33, 0, 0000h
        dw 3C00h, p25, 0, 0000h
        dw 3C00h, p26, 0, 0000h
        dw 3C00h, p30, 0, 0000h
        dw 3900h, p0, 0, 0000h
        dw 3900h, p1, 0, 0000h
        dw 3900h, p2, 0, 0000h
        dw 3900h, p3, 0, 0000h
        dw 3900h, p4, 0, 0000h
        dw 3900h, p5, 0, 0000h
        dw 3900h, p6, 0, 0000h
        dw 3900h, p7, 0, 0000h
        dw 3900h, p8, 0, 0000h
        dw 3900h, p9, 0, 0000h
        dw 3900h, p10, 0, 0000h
        dw 3900h, p11, 0, 0000h
        dw 3900h, p31, 0, 0000h
        dw 3900h, p12, 0, 0000h
        dw 3900h, p13, 0, 0000h
        dw 3900h, p14, 0, 0000h
        dw 3900h, p32, 0, 0000h
        dw 3900h, p15, 0, 0000h
        dw 3900h, p16, 0, 0000h
        dw 3900h, p17, 0, 0000h
        dw 3900h, p18, 0, 0000h
        dw 3900h, p19, 0, 0000h
        dw 3900h, p20, 0, 0000h
        dw 3900h, p21, 0, 0000h
        dw 3900h, p22, 0, 0000h
        dw 3900h, p23, 0, 0000h
        dw 3900h, p24, 0, 0000h
        dw 3900h, p25, 0, 0000h
        dw 3900h, p26, 0, 0000h
        dw 3900h, p30, 0, 0000h
        dw 3A00h, p0, 0, 0000h
        dw 3A00h, p1, 0, 0000h
        dw 3A00h, p2, 0, 0000h
        dw 3A00h, p3, 0, 0000h
        dw 3A00h, p4, 0, 0000h
        dw 3A00h, p5, 0, 0000h
        dw 3A00h, p6, 0, 0000h
        dw 3A00h, p7, 0, 0000h
        dw 3A00h, p8, 0, 0000h
        dw 3A00h, p9, 0, 0000h
        dw 3A00h, p10, 0, 0000h
        dw 3A00h, p11, 0, 0000h
        dw 3A00h, p31, 0, 0000h
        dw 3A00h, p12, 0, 0000h
        dw 3A00h, p13, 0, 0000h
        dw 3A00h, p14, 0, 0000h
        dw 3A00h, p32, 0, 0000h
        dw 3A00h, p15, 0, 0000h
        dw 3A00h, p16, 0, 0000h
        dw 3A00h, p17, 0, 0000h
        dw 3A00h, p18, 0, 0000h
        dw 3A00h, p19, 0, 0000h
        dw 3A00h, p20, 0, 0000h
        dw 3A00h, p21, 0, 0000h
        dw 3A00h, p22, 0, 0000h
        dw 3A00h, p23, 0, 0000h
        dw 3A00h, p24, 0, 0000h
        dw 3A00h, p25, 0, 0000h
        dw 3A00h, p26, 0, 0000h
        dw 3A00h, p27, 0, 0000h
        dw 3A00h, p28, 0, 0000h
        dw 3A00h, p29, 0, 0000h
        dw 3A00h, p30, 0, 0000h
        dw 4100h, p0, 0, 0000h
        dw 4100h, p1, 0, 0000h
        dw 4100h, p2, 0, 0000h
        dw 4100h, p3, 0, 0000h
        dw 4100h, p4, 0, 0000h
        dw 4100h, p5, 0, 0000h
        dw 4100h, p6, 0, 0000h
        dw 4100h, p7, 0, 0000h
        dw 4100h, p8, 0, 0000h
        dw 4100h, p9, 0, 0000h
        dw 4100h, p10, 0, 0000h
        dw 4100h, p11, 0, 0000h
        dw 4100h, p12, 0, 0000h
        dw 4100h, p14, 0, 0000h
        dw 4100h, p15, 0, 0000h
        dw 4100h, p16, 0, 0000h
        dw 4100h, p17, 0, 0000h
        dw 4100h, p18, 0, 0000h
        dw 4100h, p19, 0, 0000h
        dw 4100h, p20, 0, 0000h
        dw 4100h, p21, 0, 0000h
        dw 4100h, p22, 0, 0000h
        dw 4100h, p23, 0, 0000h
        dw 4100h, p24, 0, 0000h
        dw 4100h, p25, 0, 0000h
        dw 4100h, p26, 0, 0000h
        dw 4100h, p30, 0, 0000h
        dw 0
p0      db 'NOSUCH\A.TXT', 0
p1      db 'NOSUCH\A.TXT.X', 0
p2      db 'NOSUCH\A|B', 0
p3      db 'NOSUCH\*.TXT', 0
p4      db 'NOSUCH\B|C\A.TXT', 0
p5      db 'NOSUCH\X.Y.Z\A.TXT', 0
p6      db 'SUB\NOSUCH\A.T.X', 0
p7      db 'SUB\', 0
p8      db 'A.TXT\', 0
p9      db 'NOSUCH\', 0
p10     db 'SUB\\X.TXT', 0
p11     db 'SUB\X.TXT\', 0
p12     db '..', 0
p13     db 'SUB\.', 0
p14     db 'SUB\..', 0
p15     db '\..', 0
p16     db '*.*', 0
p17     db 'SUB\*.*', 0
p18     db 'A?.TXT', 0
p19     db 'Q:A.TXT', 0
p20     db 'Q:\', 0
p21     db 'Q:', 0
p22     db '', 0
p23     db 'NUL.X.Y', 0
p24     db '\DEV\NUL.X.Y', 0
p25     db 'SUB\NUL.*', 0
p26     db 'CON', 0
p27     db 'A.TXT', 0
p28     db 'SUB\X.TXT', 0
p29     db 'SUB', 0
p30     db 'NOSUCH.TXT', 0
p31     db '.', 0
p32     db '\.', 0
p33     db '\DEV\NUL', 0
p34     db '\', 0
p35     db '\\A.TXT', 0
p36     db 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', 0
p37     db 'SUB\YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY', 0
p38     db 'Z.TXT', 0
p39     db 'NOSUCH\NUL', 0
p40     db 'SUB\NUL', 0
p41     db 'NUL', 0
p42     db 'SUB\CON', 0
p43     db '\SUB', 0
p44     db '..\SUB', 0
