; REUSE.COM (test_kernel t_swaps): B:N.TXT created with its root write
; dropped by the disk and answered Ignore (the test drops it at sync 'V');
; the buffers pushed out by a search of A:\SUB; B:X.TXT created (the same
; slot: free on the disk), written, closed; then N written and closed.
; Each call's result printed: + or -, AX in hex
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     cl, 'V'
        call    sync
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, nn
        int     21h
        call    res
        mov     [h1], ax
        mov     cl, 'W'
        call    sync
        mov     ah, 4Eh                 ; evict: A:\SUB\*.* all
        mov     cx, 0
        mov     dx, sbn
        int     21h
.l:     jc      .d
        mov     ah, 4Fh
        int     21h
        jmp     .l
.d:     mov     ah, 4Eh
        mov     cx, 0
        mov     dx, any
        int     21h
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, xn
        int     21h
        call    res
        mov     bx, ax
        mov     [h2], ax
        mov     ah, 40h
        mov     cx, 100
        mov     dx, xbuf
        int     21h
        call    res
        mov     bx, [h2]
        mov     ah, 3Eh
        int     21h
        call    res
        mov     bx, [h1]
        mov     ah, 40h
        mov     cx, 600
        mov     dx, nbuf
        int     21h
        call    res
        mov     bx, [h1]
        mov     ah, 3Eh
        int     21h
        call    res
        mov     ax, 4C00h
        int     21h
sync:   mov     bx, 5A5Ah
        mov     ah, 30h
        int     21h
        ret
res:    pushf
        push    ax
        mov     dl, '+'
        jnc     .o
        mov     dl, '-'
.o:     mov     ah, 2
        int     21h
        pop     ax
        push    ax
        call    hx4
        mov     dl, ' '
        mov     ah, 2
        int     21h
        pop     ax
        popf
        ret
hx4:    mov     cx, 4
.l:     rol     ax, 4
        push    ax
        and     al, 15
        add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        push    cx
        int     21h
        pop     cx
        pop     ax
        loop    .l
        ret
h24:    mov     al, 0                   ; Ignore
        iret
h1      dw 0
h2      dw 0
nn      db 'B:N.TXT', 0
xn      db 'B:X.TXT', 0
sbn     db 'A:\SUB\*.*', 0
any     db 'A:\*.*', 0
xbuf    times 100 db 'X'
nbuf    times 600 db 'N'
