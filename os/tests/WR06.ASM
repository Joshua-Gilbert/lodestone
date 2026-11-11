; WR06.COM (test_kernel t_mntback): B:X.DAT made, 4096 bytes written (W1),
; then 8192 (W2: the test swaps B:'s disk before its first INT 13h write,
; the BIOS's 06h), closed (Z).  Prints each step's digit or letter and +
; or -.  Its INT 24h handler prints [the code + 'A'] and answers Fail
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, oname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      x
        mov     [h], ax
        mov     cx, 4096
        mov     dl, '1'
        call    wr
        mov     cx, 8192
        mov     dl, '2'
        call    wr
        mov     bx, [h]
        mov     ah, 3Eh
        int     21h
        mov     dl, 'Z'
        call    st
x:      mov     ax, 4C00h
        int     21h
wr:     push    dx
        mov     bx, [h]
        mov     dx, buf
        mov     ah, 40h
        int     21h
        pop     dx
st:     pushf
        push    ax
        pushf
        mov     ah, 2
        int     21h
        popf
        mov     dl, '+'
        jnc     .o
        mov     dl, '-'
        mov     ah, 2
        int     21h
        mov     bp, sp
        mov     dl, [bp+2]
        add     dl, '0'
.o:     mov     ah, 2
        int     21h
        mov     dl, ' '
        int     21h
        pop     ax
        popf
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
%ifdef RETRY
        mov     al, 1
%else
        mov     al, 3
%endif
        iret
h       dw 0
oname   db 'B:X.DAT', 0
buf:    times 8192 db 'w'
