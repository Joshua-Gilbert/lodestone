; PROBE.INC - the driver of the MS-DOS probes (ERRS, NAMES, NULDIR, NOMATCH;
; test_kernel's ms_probe runs them here, and they were run on GRiD MS-DOS
; 3.30 for the *_MS.TXT answers): for each entry of `tests` (fn, name 1,
; name 2 or 0, CX; 0 ends it) the call is made and a line printed: fn, the
; name(s), ' -> ok' or ' -> err ' and AL in hex.  3Dh opens read/write; a
; handle from 3Dh, 3Ch or 5Bh is closed (H7)
org 100h
        mov     si, tests
.t:     lodsw                   ; function
        or      ax, ax
        jz      .done
        mov     bx, ax
        lodsw                   ; name 1
        mov     dx, ax
        lodsw                   ; name 2 (ES:DI for 56h)
        mov     di, ax
        lodsw                   ; CX
        mov     [tcx], ax
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
        or      di, di
        jz      .one
        mov     ah, 2
        mov     dl, '>'
        int     21h
        mov     si, di
        call    pz
.one:   pop     dx
        mov     ah, bh
        mov     al, 0
        cmp     ah, 3Dh
        jne     .go
        mov     al, 2                   ; open: read/write
.go:    mov     cx, [tcx]
        push    ds
        pop     es
        int     21h
        jc      .err
        cmp     bh, 3Dh                 ; a handle: close it
        je      .cl
        cmp     bh, 3Ch
        je      .cl
        cmp     bh, 5Bh
        jne     .ok
.cl:    mov     bx, ax
        mov     ah, 3Eh
        int     21h
.ok:    mov     ah, 9
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
tcx     dw 0
s_f     db 'fn $'
s_ok    db ' -> ok$'
s_err   db ' -> err $'
s_nl    db 13, 10, '$'
