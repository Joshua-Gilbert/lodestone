; MNTSWB.COM (test_kernel t_mount): B:OUT.DAT created, 3000 bytes written
; (A), A:'s free space (the FAT cache goes to A:) (R), a key (another disk
; goes in B:), 3000 more written (B), closed (C); "+" or "-n".  OPENK: B:K.TXT
; opened instead and nothing written at A (a file open, nothing to go);
; NOA: no free space on A:; PATHB: B:'s free space after the key (P)
org 100h
        mov     dx, oname
%ifdef OPENK
        mov     ax, 3D02h
%else
        xor     cx, cx
        mov     ah, 3Ch
%endif
        int     21h
        jc      x
        mov     [h], ax
        mov     dl, 'A'
%ifdef OPENK
        clc
        call    st
%else
        call    wr
%endif
%ifndef NOA
        mov     ah, 36h
        mov     dl, [odrv]
        int     21h
%endif
        mov     dl, 'R'
        clc
        call    st
        mov     ah, 8
        int     21h
%ifdef PATHB
        mov     ah, 36h
        mov     dl, 2
        int     21h
        mov     dl, 'P'
        cmp     ax, 0FFFFh
        cmc
        call    st
%endif
        mov     dl, 'B'
        call    wr
        mov     bx, [h]
        mov     ah, 3Eh
        int     21h
        mov     dl, 'C'
        call    st
x:      mov     ax, 4C00h
        int     21h
wr:     push    dx
        mov     bx, [h]
        mov     cx, 3000
        mov     dx, data
        mov     ah, 40h
        int     21h
        pop     dx
st:     pushf
        push    ax
        mov     ah, 2
        int     21h
        pop     ax
        popf
        mov     dl, '+'
        jnc     .o
        add     al, '0'
        push    ax
        mov     ah, 2
        mov     dl, '-'
        int     21h
        pop     ax
        mov     dl, al
.o:     mov     ah, 2
        int     21h
        mov     dl, ' '
        int     21h
        ret
odrv    db      1
%ifdef OPENK
oname   db 'B:K.TXT', 0
%else
oname   db 'B:OUT.DAT', 0
%endif
h       dw 0
data    times 3000 db 'w'
