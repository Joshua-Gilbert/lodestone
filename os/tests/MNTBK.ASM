; MNTBK.COM (test_kernel t_mntback): B:K.TXT opened read-only (RW: read
; and write), then three 1-byte reads (RW: writes of the step's letter) A,
; R and S, a '?' printed and a key awaited before R and before S (the test
; swaps B:'s disk there), then a close, Z.  MID: after R, another '?' and a
; key, then a search of B:*.* (M: the disk in mounted).  Each step prints
; its letter and + (a read: the byte read too) or - and the error + '0'.
; Its INT 24h handler prints [the code + 'A'] and answers Fail
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, oname
%ifdef RW
        mov     ax, 3D02h
%else
        mov     ax, 3D00h
%endif
        int     21h
        jc      x
        mov     [h], ax
        mov     dl, 'A'
        call    op
        call    key
        mov     dl, 'R'
        call    op
%ifdef MID
        call    key
        mov     dx, pat
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        mov     dl, 'M'
        call    st
%endif
        call    key
        mov     dl, 'S'
        call    op
        mov     bx, [h]
        mov     ah, 3Eh
        int     21h
        mov     dl, 'Z'
        call    st
x:      mov     ax, 4C00h
        int     21h
key:    mov     dl, '?'
        mov     ah, 2
        int     21h
        xor     ah, ah
        int     16h
        ret
op:     mov     [buf], dl
        push    dx
        mov     bx, [h]
        mov     cx, 1
        mov     dx, buf
%ifdef RW
        mov     ah, 40h
%else
        mov     ah, 3Fh
%endif
        int     21h
        pop     dx
        jc      st
        call    st
%ifndef RW
        mov     dl, [buf]
        mov     ah, 2
        int     21h
%endif
        ret
st:     push    ax
        pushf
        mov     ah, 2
        int     21h
        popf
        pop     ax
        mov     dl, '+'
        jnc     .o
        push    ax
        mov     dl, '-'
        mov     ah, 2
        int     21h
        pop     dx
        add     dl, '0'
.o:     mov     ah, 2
        int     21h
        ret
h24:    push    ax
        push    dx
        mov     dl, '['
        mov     ah, 2
        int     21h
        mov     dx, di
        add     dl, 'A'
        mov     ah, 2
        int     21h
        mov     dl, ']'
        int     21h
        pop     dx
        pop     ax
        mov     al, 3
        iret
h       dw 0
oname   db 'B:K.TXT', 0
pat     db 'B:*.*', 0
buf     db 0
