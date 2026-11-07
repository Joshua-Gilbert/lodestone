; WPFAIL.COM (test_kernel t_wpfail): a file held open across a write that
; fails (its own INT 24h answers Fail), then, after a key, written again and
; closed.  Each step's answer: "W1 ok" / "W1 err n", "W2 ...", "C ...".
; Each line ends CR LF
org 100h
        mov     ax, 2524h               ; INT 24h: Fail, always
        mov     dx, h24
        int     21h
        mov     dx, name
        mov     ax, 3D02h
        int     21h
        jc      .x
        mov     [h], ax
        mov     bx, ax
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        mov     al, '1'
        call    wr
        mov     ah, 8                   ; a key: the tab may come off now
        int     21h
        mov     al, '2'
        call    wr
        mov     bx, [h]
        mov     ah, 3Eh
        int     21h
        pushf
        push    ax
        mov     dl, 'C'
        call    out1
        pop     ax
        popf
        call    status
.x:     mov     ax, 4C00h
        int     21h

wr:     mov     [wn], al
        mov     bx, [h]
        mov     cx, 100                 ; (part of a sector: through a buffer)
        mov     dx, data
        mov     ah, 40h
        int     21h
        jc      .e
        cmp     ax, cx
        je      .e                      ; (CF clear: ok)
        mov     ax, 0FFh                ; (short)
        stc
.e:     pushf
        push    ax
        mov     dl, 'W'
        call    out1
        mov     dl, [wn]
        call    out1
        pop     ax
        popf

; " ok" (CF clear) or " err n" (AX), CR LF
status: jc      .err
        mov     si, s_ok
        jmp     puts0
.err:   push    ax
        mov     si, s_err
        call    puts0
        pop     ax
        aam
        add     ax, 3030h
        push    ax
        mov     dl, ah
        call    out1
        pop     ax
        mov     dl, al
        call    out1
        mov     si, s_nl
        jmp     puts0
out1:   push    ax
        mov     ah, 2
        int     21h
        pop     ax
        ret
puts0:  lodsb
        or      al, al
        jz      .x
        mov     dl, al
        call    out1
        jmp     puts0
.x:     ret

h24:    mov     al, 3
        iret

name    db 'K.TXT', 0
s_ok    db ' ok', 13, 10, 0
s_err   db ' err ', 0
s_nl    db 13, 10, 0
h       dw 0
wn      db 0
data    times 100 db 'w'
