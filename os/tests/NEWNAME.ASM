; NEWNAME.COM (test_kernel t_newname): CREATE, CREATE NEW, MKDIR and RENAME
; (of X.TXT) onto names with no last part: A:\, \, A:, A.B\, ., A.B\. and
; the empty name (new_name's answers).  Each line: fn, the name, ok or the
; error.  test_kernel holds the answers
org 100h
        mov     si, tests
.t:     lodsw                   ; function
        or      ax, ax
        jz      .done
        mov     bx, ax
        lodsw                   ; name
        mov     dx, ax
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
        pop     dx
        mov     ah, bh
        xor     al, al
        xor     cx, cx
        cmp     ah, 56h
        jne     .go
        mov     di, dx                  ; RENAME X.TXT to the name
        mov     dx, s_x
.go:    int     21h
        jc      .err
        mov     ah, 9
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
s_x     db 'X.TXT', 0
s_f     db 'fn $'
s_ok    db ' -> ok$'
s_err   db ' -> err $'
s_nl    db 13, 10, '$'
n0      db 'A:\', 0
n1      db '\', 0
n2      db 'A:', 0
n3      db 'A.B\', 0
n4      db '.', 0
n5      db 'A.B\.', 0
n6      db 0
tests:  dw 3C00h, n0, 3C00h, n1, 3C00h, n2, 3C00h, n3, 3C00h, n4, 3C00h, n5, 3C00h, n6
        dw 5B00h, n0, 5B00h, n2, 5B00h, n4
        dw 3900h, n0, 3900h, n1, 3900h, n2, 3900h, n3, 3900h, n4, 3900h, n5
        dw 5600h, n0, 5600h, n1, 5600h, n2, 5600h, n4, 5600h, n5
        dw 0
