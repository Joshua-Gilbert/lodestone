; SWAPS.COM script[/answers] (test_kernel t_swaps): each op of the script
; (the command tail) printed, then + or -, AX in hex; INT 24h prints
; [DI AH] and answers the next digit after '/' (Fail when none is left;
; 'a': 83h, the Fail a Lodestone handler gives with nobody asked).
; Ops: o p open B:K.TXT, B:L.TXT; r R read 1; w W write 600; c C close;
; n create B:N.TXT; e b seek to the end, the start; m commit (68h); d INT
; 21h 0Dh; f find B:*.*; g a free space on B:, A:; v 59h; k B:'s root's
; first sector read through INT 13h (as read and to be written); X: that,
; L.TXT renamed M.TXT in it, written back; Y B:'s boot sector, its label
; NEWLAB, written back; G B:'s boot sector, a sector more a track in what
; would be written (not written); x INT 21h F008h for B: with the last
; of those (the sector as read, then as written; none: the boot sector,
; zeros); q open B:\K.TXT (absolute); F find next; N create A:\NEW.TXT,
; write 600, close; O open A:\AW.TXT, S to its end and write 600, V close
; it.  Anything else is a sync: INT 21h AH=30h with BX=5A5Ah, CL the
; character (the test swaps disks there).  -DSCR="...": that script when
; the tail is empty (run from the Executive); -DNOH24: no INT 24h handler
; of its own (the one it was started with answers)
org 100h
%ifdef SCR
        cmp     byte [80h], 0
        jne     .tl
        mov     si, scrb
        mov     di, 81h
.cs:    lodsb
        stosb
        cmp     al, 13
        jne     .cs
.tl:
%endif
%ifndef NOH24
        mov     ax, 2524h
        mov     dx, h24
        int     21h
%endif
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
        db 'x'
        dw op_x
        db 'k'
        dw op_k
        db 'X'
        dw op_X
        db 'Y'
        dw op_Y
        db 'G'
        dw op_G
        db 'q'
        dw op_q
        db 'F'
        dw op_F
        db 'N'
        dw op_N
        db 'O'
        dw op_O
        db 'S'
        dw op_S
        db 'V'
        dw op_V
        db 0
op_q:   mov     dx, kabs
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     [h1], ax
.x:     ret
op_F:   mov     ah, 4Fh
        int     21h
        ret
op_N:   mov     dx, aname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
        mov     [h3], ax
        mov     bx, ax
        call    wr
        jc      .x
        mov     bx, [h3]
        jmp     clz
.x:     ret
op_O:   mov     dx, awname
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     [h3], ax
.x:     ret
op_S:   mov     bx, [h3]
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        jc      .x
        mov     bx, [h3]
        jmp     wr
.x:     ret
op_V:   mov     bx, [h3]
        jmp     clz
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
op_x:   mov     ax, 0F008h
        mov     dl, 1
        mov     cx, [lsec]
        mov     bx, pre
        int     21h
        ret
; B:'s boot sector -> pre and post, its layout (spt, hds, rtlba)
rdboot: mov     word [spt], 9
        mov     word [hds], 2
        xor     ax, ax
        mov     [lsec], ax
        mov     bx, pre
        call    rd13
        jc      .x
        mov     ax, [pre+18h]
        mov     [spt], ax
        mov     ax, [pre+1Ah]
        mov     [hds], ax
        mov     al, [pre+10h]
        cbw
        mul     word [pre+16h]
        add     ax, [pre+0Eh]
        mov     [rtlba], ax
        jmp     short cpost
.x:     ret
cpost:  mov     si, pre
        mov     di, post
        mov     cx, 256
        rep     movsw
        clc
        ret
; B:'s sector AX <-> ES:BX: rd13 reads, wr13 writes.  CF: AH the BIOS's
rd13:   mov     di, 0201h
        jmp     short io13
wr13:   mov     di, 0301h
io13:   xor     dx, dx
        div     word [spt]
        mov     cl, dl
        inc     cl
        xor     dx, dx
        div     word [hds]
        mov     ch, al
        mov     dh, dl
        mov     dl, 1
        mov     ax, di
        int     13h
        ret
op_k:   call    rdboot
        jc      .x
        mov     ax, [rtlba]
        mov     [lsec], ax
        mov     bx, pre
        call    rd13
        jc      .x
        call    cpost
.x:     ret
op_X:   call    op_k
        jc      .x
        mov     si, post
        mov     cx, 16
.l:     push    si
        push    cx
        mov     di, l11
        mov     cx, 11
        repe    cmpsb
        pop     cx
        pop     si
        jne     .n
        mov     byte [si], 'M'
.n:     add     si, 32
        loop    .l
        mov     ax, [lsec]
        mov     bx, post
        call    wr13
.x:     ret
op_Y:   call    rdboot
        jc      .x
        mov     si, newlab
        mov     di, post + 2Bh
        mov     cx, 11
        rep     movsb
        xor     ax, ax
        mov     bx, post
        call    wr13
.x:     ret
op_G:   call    rdboot
        jc      .x
        inc     byte [post+18h]
.x:     ret
op_d:   mov     ah, 0Dh
        int     21h
        clc
        ret
op_f:   mov     dx, fdta                ; (its own DTA: PSP:80h holds the
        mov     ah, 1Ah                 ;  script)
        int     21h
        mov     dx, wild
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
        cmp     al, 'a' - '0'           ; ('a': 83h, a Fail nobody was asked
        jne     .d                      ;  for, as the Executive's)
        mov     al, 83h
.d:     pop     si
        iret
h1      dw 0
h2      dw 0
op      db 0
ansp    dw 0
kname   db 'B:K.TXT', 0
kabs    db 'B:\K.TXT', 0
aname   db 'A:\NEW.TXT', 0
awname  db 'A:\AW.TXT', 0
h3      dw 0
%ifdef SCR
scrb    db SCR, 13
%endif
lname   db 'B:L.TXT', 0
nname   db 'B:N.TXT', 0
wild    db 'B:*.*', 0
rbuf    db 0
spt     dw 9
hds     dw 2
rtlba   dw 0
lsec    dw 0
l11     db 'L       TXT'
newlab  db 'NEWLAB     '
buf:
pre     equ buf + 704
post    equ pre + 512
fdta    equ post + 512
