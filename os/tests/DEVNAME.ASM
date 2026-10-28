; DEVNAME.COM (test_kernel t_devname): OPEN and CREATE of device names and
; names that are nearly one (dev_look_ax's table walk, the NUL.X.Y rule, the
; GPIBnn parse).  Each line: fn, the name, ok or the error.  test_kernel
; holds the answers, and which device and GPIB address each one opened
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
        mov     al, 0
        cmp     ah, 3Dh
        jne     .go
        mov     al, 2                   ; open: read/write
.go:    xor     cx, cx
        int     21h
        jc      .err
        mov     bx, ax                  ; a handle: close it
        mov     ah, 3Eh
        int     21h
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
s_f     db 'fn $'
s_ok    db ' -> ok$'
s_err   db ' -> err $'
s_nl    db 13, 10, '$'

; the names (A.B is a directory on the disk)
%assign i 0
%macro name 1
n%[i]   db %1, 0
%assign i i+1
%endmacro
        name 'CON'
        name 'NUL'
        name 'AUX'
        name 'COM1'
        name 'COM2'
        name 'PRN'
        name 'LPT1'
        name 'CLOCK$'
        name 'NUL.TXT'
        name 'COM'
        name 'CONX'
        name 'NU'
        name 'CON.X'
        name 'NUL.'
        name 'NUL..'
        name 'NUL.X.'
        name 'NUL.X.Y'
        name 'LPT1.PRN'
        name 'CLOCK'
        name 'CLOCK$$'
        name 'A.B\CLOCK$'
        name 'A.B\EMMXXXX0'
        name 'EMMXXXX0'
        name 'EMMXXXX'
        name 'EMMXXXX0.X'
        name '\DEV\\NUL'
        name 'GPIB5'
        name 'GPIB05'
        name 'GPIB30'
        name 'GPIB31'
        name 'GPIB'
        name 'GPIBX'
        name 'GPIB5.X'
        name 'GPIB5.X.Y'
        name 'GPIB1Z'
        name 'NOSUCH\GPIB5'
        name '\DEV\GPIB9'
        name 'A:GPIB12'
        name 'GPIB99'
        name 'GPIB5\'
        name 'GPIB0'
        name 'GPIB123'
        name 'GPIB/5'
        name 'GPIB:5'
%assign nnames i
; each name opened, then created
tests:
%assign i 0
%rep nnames
        dw 3D00h, n%[i]
        dw 3C00h, n%[i]
%assign i i+1
%endrep
        dw 0
