; CRASHRPT.COM - with the CRASHLOG build (os/diag): after a crash it caught
; and the restart, the report it kept at 5000:0 to CRASH.BIN in the
; current directory (send it in; tools/crashdecode.py reads it), then
; the report forgotten (its signature cleared).  Exit code 0 written, 1
; no report there, 2 it couldn't be written.
;   nasm -f bin -o CRASHRPT.COM CRASHRPT.ASM
        cpu     286
        org     100h
CR_SEG  equ     5000h

        push    ds
        mov     ax, CR_SEG
        mov     es, ax
        xor     di, di
        mov     si, sig
        mov     cx, 8
        repe    cmpsb
        jne     none
        mov     cx, [es:8]              ; its length: 16 .. 60 KB, even
        cmp     cx, 16
        jbe     none
        cmp     cx, 0F000h
        ja      none
        test    cl, 1
        jnz     none
        mov     [len], cx
        mov     si, 16                  ; its sum
        sub     cx, 16
        shr     cx, 1
        xor     dx, dx
        push    es
        pop     ds
.s:     lodsw
        add     dx, ax
        loop    .s
        pop     ds
        cmp     dx, [es:10]
        jne     bad
        mov     ah, 3Ch                 ; CRASH.BIN
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      wfail
        mov     bx, ax
        mov     cx, [len]
        push    ds
        push    es
        pop     ds
        xor     dx, dx
        mov     ah, 40h
        int     21h
        pop     ds
        jc      wfail
        cmp     ax, [len]
        jne     wfail
        mov     ah, 3Eh
        int     21h
        jc      wfail
        mov     word [es:0], 0          ; forgotten
        mov     dx, s_ok
        mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h
none:   pop     ds
        mov     dx, s_none
        jmp     short out1
bad:    mov     dx, s_bad
out1:   mov     ah, 9
        int     21h
        mov     ax, 4C01h
        int     21h
wfail:  mov     dx, s_wf
        mov     ah, 9
        int     21h
        mov     ax, 4C02h
        int     21h

sig     db      'LODECRSH'
fname   db      'CRASH.BIN', 0
len     dw      0
s_ok    db      'CRASHRPT: the report written to CRASH.BIN.', 13, 10, '$'
s_none  db      'CRASHRPT: no report kept (nothing was caught, or it was written already).', 13, 10, '$'
s_bad   db      'CRASHRPT: a report is there, but damaged (its sum is wrong): not written.', 13, 10, '$'
s_wf    db      'CRASHRPT: CRASH.BIN could not be written.', 13, 10, '$'
