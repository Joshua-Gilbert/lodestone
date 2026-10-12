; RUNCALC.COM - runs  CALC N=5  as its child, then prints its exit code,
; (EL1), and its own environment (tests/test_kernel.py): CALC's name=
; writes only into the command prompt's environment, never into another
; parent's, and says so
        cpu     286
        org     100h
        mov     sp, stack_top
        mov     bx, (stack_top - $$ + 256 + 15) / 16
        mov     ah, 4Ah
        int     21h
        mov     [epb+4], cs
        mov     [epb+8], cs
        mov     [epb+12], cs
        mov     dx, path
        mov     bx, epb
        mov     ax, 4B00h
        int     21h
        mov     ah, 4Dh                 ; its exit code
        int     21h
        add     [el+3], al
        mov     si, el
.p:     lodsb
        or      al, al
        jz      .pd
        mov     dl, al
        call    putc
        jmp     .p
.pd:    mov     es, [2Ch]
        xor     di, di
.v:     cmp     byte [es:di], 0
        je      .x
        mov     dl, '['
        call    putc
.c:     mov     dl, [es:di]
        inc     di
        or      dl, dl
        jz      .e
        call    putc
        jmp     .c
.e:     mov     dl, ']'
        call    putc
        jmp     .v
.x:     mov     ax, 4C00h
        int     21h
putc:   mov     ah, 2
        int     21h
        ret

el      db      '(EL0)', 0
path    db      'CALC.COM', 0
tail    db      4, ' N=5', 13
epb     dw      0, tail, 0, fcb, 0, fcb, 0
fcb     times 16 db 0
        times 256 db 0
stack_top:
