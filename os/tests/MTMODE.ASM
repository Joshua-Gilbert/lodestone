; MTMODE.COM - for test_mt.py: a task's screen kept while another is in
; front.  MTMODE MM FILE [T]: video mode MM (hex), its 32 KB at B800h filled
; with a pattern; then it waits for a key (AH=08h) and writes "ok" to
; FILE if the pattern is all still there, else "bad".  T: after that
; key, mode 3, "MTMODE: text" printed and another key, before the file.
; B: after that key, mode 3 and at once mode MM again, then another
; key.  No arguments: mode 40h, no file
; nasm -f bin -o MTMODE.COM MTMODE.ASM
cpu 286
org 100h
%include "MTLIB.INC"
        mov     ax, 40h
        cmp     byte [80h], 0
        je      .m
        mov     si, 81h
        call    blanks
        call    hexd                    ; the mode
        mov     ah, al
        shl     ah, 4
        call    hexd
        or      al, ah
        xor     ah, ah
        push    ax
        call    blanks
        mov     [fn], si                ; FILE, to a blank or the end
.f:     lodsb
        cmp     al, ' '
        ja      .f
        mov     byte [si-1], 0
        jne     .n                      ; (the end: no T)
        call    blanks
        lodsb
        and     al, 0DFh
        sub     al, 'T'
        je      .t
        cmp     al, 'B' - 'T'
        jne     .n
        mov     byte [bnc], 1
        jmp     short .n
.t:     mov     byte [txt], 1
.n:     pop     ax
.m:     mov     [mode], ax
        int     10h
        push    0B800h
        pop     es
        xor     di, di
        mov     cx, 8000h
.p:     call    pat
        stosb
        loop    .p
        mov     ah, 8
        int     21h
        xor     di, di
        mov     cx, 8000h
        mov     word [res], s_ok
.c:     call    pat
        scasb
        jne     .bad
        loop    .c
        jmp     .w
.bad:   mov     word [res], s_bad
.w:     cmp     byte [bnc], 0
        je      .w1
        mov     ax, 3                   ; B: text, and at once MM again
        int     10h
        mov     ax, [mode]
        int     10h
        mov     ah, 8
        int     21h
.w1:    cmp     byte [txt], 0
        je      .w2
        mov     ax, 3                   ; T: text again, a line, a key
        int     10h
        mov     ah, 9
        mov     dx, s_text
        int     21h
        mov     ah, 8
        int     21h
.w2:    cmp     word [fn], 0
        je      .x
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, [fn]
        int     21h
        jc      .x
        mov     bx, ax
        mov     dx, [res]
        mov     cx, 2
        cmp     dx, s_ok
        je      .wr
        inc     cx
.wr:    mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

pat:    mov     ax, di                  ; DI's byte: (DI * 5) XOR (DI >> 8)
        mov     dx, ax
        shl     ax, 2
        add     ax, dx
        xor     al, dh
        ret
        BLANKS
hexd:   lodsb                           ; a hex digit -> AL
        cmp     al, '9'
        ja      .a
        sub     al, '0'
        ret
.a:     and     al, 0DFh
        sub     al, 'A' - 10
        ret

fn      dw      0
res     dw      0
txt     db      0
bnc     db      0
mode    dw      0
s_text  db      'MTMODE: text', 13, 10, '$'
s_ok    db      'ok'
s_bad   db      'bad'
