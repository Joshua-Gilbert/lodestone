; ATTR.COM (test_kernel t_attr): CREATE and CREATE NEW with each bit of CX and
; the attribute they leave; a CREATE over a file; a file written or only
; opened (its archive bit); CX's 10h/40h/80h; device names.  Each line: fn,
; the name, CX, ok, attr or the error.  test_kernel holds GRiD MS-DOS 3.30's
org 100h
        mov     si, tests
.t:     lodsw                   ; op: 3Ch, 5Bh, 43h, 3Dh; 1 = open, write, close; 2 = open, close
        or      ax, ax
        jz      .done
        mov     bx, ax
        lodsw
        mov     dx, ax          ; the name
        lodsw
        mov     [tcx], ax
        push    si
        push    dx
        mov     ah, 9
        mov     dx, s_f
        int     21h
        mov     al, bl
        call    phex
        mov     ah, 2
        mov     dl, ' '
        int     21h
        pop     si
        push    si
        call    pz
        mov     ah, 2
        mov     dl, ' '
        int     21h
        mov     ax, [tcx]
        xchg    al, ah
        call    phex
        mov     al, [tcx]
        call    phex
        pop     dx
        mov     cx, [tcx]
        cmp     bl, 2
        jbe     .rw
        mov     ah, bl
        mov     al, 0
        cmp     ah, 3Dh
        jne     .go
        mov     al, 0
.go:    int     21h
        jc      .err
        cmp     bl, 43h
        je      .attr
        mov     cl, [80h + 21]  ; (FIND FIRST: the attribute it found)
        cmp     bl, 4Eh
        je      .attr
        mov     bx, ax          ; a handle: close it
        mov     ah, 3Eh
        int     21h
        jmp     .ok
.rw:    push    bx
        mov     ax, 3D02h
        int     21h
        pop     bx
        jc      .err
        xchg    ax, bx          ; BX = handle, AL = op
        cmp     al, 1
        jne     .cl
        mov     ah, 40h
        mov     cx, 1
        mov     dx, s_byte
        int     21h
.cl:    mov     ah, 3Eh
        int     21h
.ok:    mov     ah, 9
        mov     dx, s_ok
        int     21h
        jmp     .nx
.attr:  push    cx
        mov     ah, 9
        mov     dx, s_attr
        int     21h
        pop     ax
        call    phex
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
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        int     21h
        ret
tcx     dw 0
s_byte  db 'x'
s_f     db 'fn $'
s_ok    db ' -> ok$'
s_attr  db ' -> attr $'
s_err   db ' -> err $'
s_nl    db 13, 10, '$'
tests   dw 03Ch, p0, 0000h
        dw 043h, p0, 0000h
        dw 03Ch, p1, 0001h
        dw 043h, p1, 0000h
        dw 03Ch, p2, 0002h
        dw 043h, p2, 0000h
        dw 03Ch, p3, 0004h
        dw 043h, p3, 0000h
        dw 03Ch, p4, 0006h
        dw 043h, p4, 0000h
        dw 03Ch, p5, 0007h
        dw 043h, p5, 0000h
        dw 03Ch, p6, 0010h
        dw 043h, p6, 0000h
        dw 03Ch, p7, 0020h
        dw 043h, p7, 0000h
        dw 03Ch, p8, 0021h
        dw 043h, p8, 0000h
        dw 03Ch, p9, 0027h
        dw 043h, p9, 0000h
        dw 03Ch, p10, 0040h
        dw 043h, p10, 0000h
        dw 03Ch, p11, 0080h
        dw 043h, p11, 0000h
        dw 03Ch, p12, 0100h
        dw 043h, p12, 0000h
        dw 03Ch, p13, 8000h
        dw 043h, p13, 0000h
        dw 05Bh, p14, 0000h
        dw 043h, p14, 0000h
        dw 05Bh, p15, 0001h
        dw 043h, p15, 0000h
        dw 05Bh, p16, 0010h
        dw 043h, p16, 0000h
        dw 05Bh, p17, 0020h
        dw 043h, p17, 0000h
        dw 05Bh, p18, 0040h
        dw 043h, p18, 0000h
        dw 05Bh, p19, 0080h
        dw 043h, p19, 0000h
        dw 043h, p20, 0000h
        dw 03Ch, p20, 0000h
        dw 043h, p20, 0000h
        dw 043h, p21, 0000h
        dw 03Ch, p21, 0002h
        dw 043h, p21, 0000h
        dw 043h, p22, 0000h
        dw 03Ch, p22, 0002h
        dw 043h, p22, 0000h
        dw 043h, p23, 0000h
        dw 001h, p23, 0000h
        dw 043h, p23, 0000h
        dw 043h, p24, 0000h
        dw 002h, p24, 0000h
        dw 043h, p24, 0000h
        dw 03Ch, p25, 0010h
        dw 05Bh, p20, 0010h
        dw 03Ch, p26, 0010h
        dw 03Ch, p26, 0000h
        dw 05Ah, p27, 0000h
        dw 05Ah, p28, 0001h
        dw 05Ah, p29, 0020h
        dw 05Ah, p30, 0000h
        dw 05Ah, p31, 0000h
        dw 04Eh, p32, 0027h
        dw 05Ah, p33, 0001h
        dw 04Eh, p34, 0027h
        dw 05Ah, p35, 0002h
        dw 05Ah, p36, 0004h
        dw 05Ah, p37, 0027h
        dw 03Ch, p38, 0010h
        dw 03Ch, p39, 0010h
        dw 03Ch, p39, 0040h
        dw 05Bh, p39, 0010h
        dw 03Dh, p40, 0000h
        dw 03Dh, p41, 0000h
        dw 03Dh, p42, 0000h
        dw 03Dh, p43, 0000h
        dw 0
p0      db 'C0.TXT', 0
        times 16 db 0
p1      db 'C1.TXT', 0
        times 16 db 0
p2      db 'C2.TXT', 0
        times 16 db 0
p3      db 'C4.TXT', 0
        times 16 db 0
p4      db 'C6.TXT', 0
        times 16 db 0
p5      db 'C7.TXT', 0
        times 16 db 0
p6      db 'C10.TXT', 0
        times 16 db 0
p7      db 'C20.TXT', 0
        times 16 db 0
p8      db 'C21.TXT', 0
        times 16 db 0
p9      db 'C27.TXT', 0
        times 16 db 0
p10     db 'C40.TXT', 0
        times 16 db 0
p11     db 'C80.TXT', 0
        times 16 db 0
p12     db 'C100.TXT', 0
        times 16 db 0
p13     db 'C8000.TXT', 0
        times 16 db 0
p14     db 'N0.TXT', 0
        times 16 db 0
p15     db 'N1.TXT', 0
        times 16 db 0
p16     db 'N10.TXT', 0
        times 16 db 0
p17     db 'N20.TXT', 0
        times 16 db 0
p18     db 'N40.TXT', 0
        times 16 db 0
p19     db 'N80.TXT', 0
        times 16 db 0
p20     db 'T0.TXT', 0
        times 16 db 0
p21     db 'T2.TXT', 0
        times 16 db 0
p22     db 'TH.TXT', 0
        times 16 db 0
p23     db 'W.TXT', 0
        times 16 db 0
p24     db 'O.TXT', 0
        times 16 db 0
p25     db 'NOSUCH\X.TXT', 0
        times 16 db 0
p26     db 'A.B', 0
        times 16 db 0
p27     db 'A.B\', 0
        times 16 db 0
p28     db 'A.B\', 0
        times 16 db 0
p29     db 'A.B\', 0
        times 16 db 0
p30     db 'NOSUCH\', 0
        times 16 db 0
p31     db 'E.F\', 0
        times 16 db 0
p32     db 'E.F\*.*', 0
        times 16 db 0
p33     db 'G.H\', 0
        times 16 db 0
p34     db 'G.H\*.*', 0
        times 16 db 0
p35     db 'A.B\', 0
        times 16 db 0
p36     db 'A.B\', 0
        times 16 db 0
p37     db 'A.B\', 0
        times 16 db 0
p38     db 'A.B\NUL', 0
        times 16 db 0
p39     db 'NUL', 0
        times 16 db 0
p40     db 'LPT1', 0
        times 16 db 0
p41     db 'COM1', 0
        times 16 db 0
p42     db 'PRN', 0
        times 16 db 0
p43     db 'AUX', 0
        times 16 db 0
