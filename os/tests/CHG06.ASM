; CHG06.COM (test_kernel t_chg06): B:BIG.TXT's first 30000 bytes in one
; read (several clusters, read-ahead, the cylinder cache), then written to
; A:OUT.TXT (SMALL: all of it, 128 bytes a read).  Prints R+ or R- and the
; error + '0'; then '.' at the end.
; Its INT 24h handler prints [the code + 'A'] and answers with the key
; typed: r Retry, anything else Fail.  The test changes B:'s disk under
; one of the reads (the BIOS's 06h)
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, iname
        mov     ax, 3D00h
        int     21h
        jc      x
        mov     bx, ax
%ifdef SMALL
        mov     di, buf                 ; (SMALL: 128 bytes a call till the
.r:     mov     cx, 128                 ;  end, each a handle call; WAIT: 'a'
        mov     dx, di                  ;  after the first, then 3 s with no
        mov     ah, 3Fh                 ;  call)
        int     21h
        jc      .e
        add     di, ax
        or      ax, ax
        jz      .e
%ifdef WAIT
        cmp     di, buf + 128
        jne     .r
        push    bx
%ifdef ZD
        mov     ah, 0Dh                 ; (ZD: INT 21h 0Dh first, and 0.3 s)
        int     21h
%endif
        mov     dl, 'a'
        mov     ah, 2
        int     21h
        xor     ax, ax
        mov     es, ax
        mov     bx, [es:46Ch]
.w:     mov     ax, [es:46Ch]
        sub     ax, bx
%ifdef ZD
        cmp     ax, 6
%else
        cmp     ax, 55
%endif
        jb      .w
        push    cs
        pop     es
        pop     bx
%endif
        jmp     .r
.e:     pushf
        sub     di, buf
        mov     [n], di
        popf
%else
        mov     cx, 30000
        mov     dx, buf
        mov     ah, 3Fh
        int     21h
        mov     [n], ax
%endif
        mov     dl, 'R'
        call    st
        jc      x
        mov     dx, oname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      x
        mov     bx, ax
        mov     cx, [n]
        mov     dx, buf
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
x:      mov     dl, '.'
        mov     ah, 2
        int     21h
        mov     ax, 4C00h
        int     21h
; DL, then + (NC) or - and AL + '0' (CF).  Flags kept
st:     pushf
        push    ax
        mov     ah, 2
        int     21h
        pop     ax
        mov     dl, '+'
        popf
        pushf
        jnc     .o
        push    ax
        mov     dl, '-'
        mov     ah, 2
        int     21h
        pop     ax
        mov     dl, al
        add     dl, '0'
.o:     mov     ah, 2
        int     21h
        popf
        ret
h24:    push    dx
        push    ax
        mov     dl, '['
        mov     ah, 2
        int     21h
        mov     dx, di
        add     dl, 'A'
        mov     ah, 2
        int     21h
        mov     dl, ']'
        int     21h
        mov     ah, 8
        int     21h
        mov     dl, 1
        cmp     al, 'r'
        je      .r
        mov     dl, 3
.r:     pop     ax
        mov     al, dl
        pop     dx
        iret
n       dw 0
iname   db 'B:BIG.TXT', 0
oname   db 'A:OUT.TXT', 0
buf:
