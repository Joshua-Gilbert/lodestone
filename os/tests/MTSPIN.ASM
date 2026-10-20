; MTSPIN.COM - for test_mt.py: a task that computes, for preemption.
;   MTSPIN T CNTFILE [D | W DATAFILE]
; Counts, as fast as it can, for T ticks of the BIOS's clock (40:6Ch),
; then writes the count (8 hex digits) to CNTFILE.  D: an INT 21h call
; (AH=2Ch) on each count; W: a 64-byte record written to DATAFILE on each
; (so its size is the count times 64).  It prints nothing.
; nasm -f bin -o MTSPIN.COM MTSPIN.ASM
cpu 286
org 100h
        mov     sp, stk_top
        mov     ah, 4Ah                 ; (only its own memory)
        mov     bx, (stk_top - $$ + 100h + 15) / 16
        int     21h
        mov     si, 81h
        call    blanks
        xor     bx, bx                  ; T
.d:     lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .de
        cbw
        imul    bx, bx, 10
        add     bx, ax
        jmp     .d
.de:    mov     [tks], bx
        call    blanks
        mov     [cnf], si               ; CNTFILE
        call    word_
        call    blanks
        lodsb
        and     al, 0DFh
        mov     [mode], al
        cmp     al, 'W'
        jne     .go
        call    blanks
        mov     dx, si                  ; DATAFILE
        call    word_
        mov     ah, 3Ch
        xor     cx, cx
        int     21h
        jc      .x
        mov     [dh_], ax
.go:    push    40h
        pop     es
        mov     ax, [es:6Ch]
        mov     [t0], ax
.l:     add     word [cnt], 1
        adc     word [cnt + 2], 0
        cmp     byte [mode], 'D'
        jne     .w
        mov     ah, 2Ch
        int     21h
.w:     cmp     byte [mode], 'W'
        jne     .t
        mov     ah, 40h
        mov     bx, [dh_]
        mov     cx, 64
        mov     dx, rec
        int     21h
.t:     mov     ax, [es:6Ch]
        sub     ax, [t0]
        cmp     ax, [tks]
        jb      .l
        cmp     byte [mode], 'W'
        jne     .c
        mov     ah, 3Eh
        mov     bx, [dh_]
        int     21h
.c:     mov     di, out_                ; the count, in hex
        mov     ax, [cnt + 2]
        call    hex4
        mov     ax, [cnt]
        call    hex4
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, [cnf]
        int     21h
        jc      .x
        mov     bx, ax
        mov     ah, 40h
        mov     cx, 8
        mov     dx, out_
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

blanks: lodsb
        cmp     al, ' '
        je      blanks
        dec     si
        ret
word_:  lodsb                           ; to a blank or the end: NUL there
        cmp     al, ' '
        ja      word_
        mov     byte [si - 1], 0
        cmp     al, 0Dh                 ; (at the end: stay on that NUL, so
        jne     .x                      ;  nothing more is read)
        dec     si
.x:     ret
hex4:   push    ds
        pop     es
        mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .s
        add     al, 7
.s:     stosb
        pop     ax
        loop    .h
        push    40h
        pop     es
        ret

tks     dw      0
t0      dw      0
cnt     dw      0, 0
cnf     dw      0
dh_     dw      0
mode    db      0
out_    times 8 db 0
rec     db      '0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDE', 0Ah
        times   256 db 0
stk_top:
