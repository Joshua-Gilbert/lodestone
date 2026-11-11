; CLOSE2.COM: B:K.TXT and B:L.TXT opened read and write, a byte written in place to each (changed files, the
; FAT not), '?' and a key (the test puts another disk in B:), a write to the first (INT 24h "Invalid disk
; change"; this handler's Fail, or Abort with -DABORT), '?' and a key (the first disk back), Z, then the
; program ends with both files still open (close_all closes them: test_kernel t_mntback)
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, n1
        mov     ax, 3D02h
        int     21h
        jc      x
        mov     [h1], ax
        mov     dx, n2
        mov     ax, 3D02h
        int     21h
        jc      x
        mov     [h2], ax
        mov     bx, [h1]
        mov     dl, 'A'
        call    wr
        mov     bx, [h2]
        mov     dl, 'B'
        call    wr
        call    key
        mov     bx, [h1]
        mov     dl, 'R'
        call    wr
        call    key
        mov     dl, 'Z'
        mov     ah, 2
        int     21h
x:      mov     ax, 4C00h
        int     21h
key:    mov     dl, '?'
        mov     ah, 2
        int     21h
        xor     ah, ah
        int     16h
        ret
wr:     mov     [buf], dl
        push    dx
        mov     cx, 1
        mov     dx, buf
        mov     ah, 40h
        int     21h
        pop     dx
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
%ifdef ABORT
        mov     al, 2
%else
        mov     al, 3
%endif
        iret
h1      dw 0
h2      dw 0
n1      db 'B:K.TXT', 0
n2      db 'B:L.TXT', 0
buf     db 0
