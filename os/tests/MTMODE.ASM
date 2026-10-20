; MTMODE.COM - for test_mt.py: a task's screen kept while another is in
; front.  MTMODE MM FILE: video mode MM (hex), its 32 KB at B800h filled
; with a pattern; then it waits for a key (AH=08h) and writes "ok" to
; FILE if the pattern is all still there, else "bad".
; nasm -f bin -o MTMODE.COM MTMODE.ASM
cpu 286
org 100h
        mov     si, 81h
        call    blanks
        call    hexd                    ; the mode
        mov     ah, al
        shl     ah, 4
        call    hexd
        or      al, ah
        xor     ah, ah
        int     10h
        call    blanks
        mov     [fn], si                ; FILE, to a blank or the end
.f:     lodsb
        cmp     al, ' '
        ja      .f
        mov     byte [si-1], 0
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
.w:     mov     ah, 3Ch
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
blanks: lodsb
        cmp     al, ' '
        je      blanks
        dec     si
        ret
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
s_ok    db      'ok'
s_bad   db      'bad'
