; NAMES.COM (test_kernel t_fcbnames): names as MS-DOS 3.30 keeps them, and
; its FCB search.  NAMES C: names with a first E5h and a space inside made
; (3Ch), opened again (3Dh) and found (4Eh/4Fh: "F name"); then an extended
; FCB's search for the label (11h, attribute 08h: "L [11 bytes]") and a
; plain FCB's for *.TXT (11h/12h: "T [11 bytes]").  NAMES W: INT 21h 47h
; into a 64-byte buffer, a guard byte after it ("W n G" n its length, G
; the guard kept, or "W n X").  Each line ends CR LF
org 100h
        mov     ah, 1Ah
        mov     dx, dta
        int     21h
        mov     al, [82h]
        and     al, 0DFh
        cmp     al, 'W'
        je      cwd
        mov     si, nm_e5               ; made, opened again
        call    make
        mov     si, nm_sp
        call    make
        mov     dx, pat                 ; found
        mov     cx, 0
        mov     ah, 4Eh
        int     21h
.f:     jc      .lab
        mov     al, 'F'
        call    putc
        mov     al, ' '
        call    putc
        mov     si, dta + 30
        call    puts
        call    crlf
        mov     ah, 4Fh
        int     21h
        jmp     .f
.lab:   mov     dx, xfcb                ; the label
        mov     ah, 11h
        int     21h
        or      al, al
        jnz     .tx
        mov     al, 'L'
        mov     si, dta + 8
        call    raw
.tx:    mov     dx, fcb                 ; *.TXT, plain FCB
        mov     ah, 11h
.tl:    int     21h
        or      al, al
        jnz     .end
        mov     al, 'T'
        mov     si, dta + 1
        call    raw
        mov     dx, fcb
        mov     ah, 12h
        jmp     .tl
.end:   mov     ax, 4C00h
        int     21h

cwd:    mov     byte [buf + 64], 0A5h
        mov     si, buf
        xor     dl, dl
        mov     ah, 47h
        int     21h
        mov     al, 'W'
        call    putc
        mov     al, ' '
        call    putc
        mov     di, buf
        mov     cx, 200
        xor     al, al
        repne   scasb
        mov     ax, di
        sub     ax, buf + 1
        call    putn
        mov     al, ' '
        call    putc
        mov     al, 'G'
        cmp     byte [buf + 64], 0A5h
        je      .g
        mov     al, 'X'
.g:     call    putc
        call    crlf
        mov     ax, 4C00h
        int     21h

; make the name at SI (3Ch), write, close, open it again (3Dh): "M name ok"
; or "M name made-not" / "M name open-not"
make:   push    si
        mov     al, 'M'
        call    putc
        mov     al, ' '
        call    putc
        call    puts
        pop     dx
        push    dx
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        mov     si, s_mk
        jc      .s
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
        pop     dx
        push    dx
        mov     ax, 3D00h
        int     21h
        mov     si, s_op
        jc      .s
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
        mov     si, s_ok
.s:     call    puts
        call    crlf
        pop     si
        ret

; AL, then " [", 11 bytes at SI, "]"
raw:    call    putc
        mov     al, ' '
        call    putc
        mov     al, '['
        call    putc
        mov     cx, 11
.l:     lodsb
        call    putc
        loop    .l
        mov     al, ']'
        call    putc
        jmp     crlf

putn:   mov     bl, 10                  ; AX (< 256) in decimal
        div     bl
        push    ax
        or      al, al
        jz      .u
        xor     ah, ah
        div     bl
        push    ax
        or      al, al
        jz      .t
        add     al, '0'
        call    putc
.t:     pop     ax
        mov     al, ah
        add     al, '0'
        call    putc
.u:     pop     ax
        mov     al, ah
        add     al, '0'
        jmp     putc

puts:   lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     puts
.x:     ret
crlf:   mov     al, 13
        call    putc
        mov     al, 10
putc:   push    ax
        push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        pop     ax
        ret

nm_e5   db 0E5h, 'ABC.TXT', 0
nm_sp   db 'AB CD.TXT', 0
pat     db '*.TXT', 0
s_ok    db ' ok', 0
s_mk    db ' made-not', 0
s_op    db ' open-not', 0
xfcb    db 0FFh, 0, 0, 0, 0, 0, 08h, 0, '???????????'
        times 25 db 0
fcb     db 0, '????????TXT'
        times 25 db 0
dta     times 64 db 0
buf     times 200 db 0
