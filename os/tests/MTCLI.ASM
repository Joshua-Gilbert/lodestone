; MTCLI.COM - for test_mt.py: a program that holds the timer's interrupt
; late, by a different time each tick (M9b: mt_tick's fast counter).
;   MTCLI T FILE
; Counter 0 left at the BIOS's rate (mode 3, 65536): over and over, with
; interrupts off, it waits for the count to reload, then to fall below a
; target drawn afresh each time (3000h-6FFFh), then lets interrupts in.
; IRQ 0 comes as the count reloads (one reload in two), so it waits each
; time from 15 to 22 ms, read low (below 8000h) but never the same twice.
; After T ticks of the BIOS's clock (40:6Ch), FILE gets "ok".
; nasm -f bin -o MTCLI.COM MTCLI.ASM
cpu 286
org 100h
        mov     si, 81h
.b:     lodsb
        cmp     al, ' '
        je      .b
        xor     bx, bx
.d:     sub     al, '0'
        jb      .de
        cmp     al, 9
        ja      .de
        cbw
        imul    bx, bx, 10
        add     bx, ax
        lodsb
        jmp     .d
.de:    mov     [ticks], bx
.s:     lodsb
        cmp     al, ' '
        je      .s
        dec     si
        mov     di, fname
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        stosb
        jmp     .n
.ne:    mov     byte [di], 0
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     bx, [46Ch]
        mov     [cs:t0], bx
        pop     ds
.w:     mov     ax, [seed]              ; (a target: 3000h-6FFFh)
        mov     dx, 25173
        mul     dx
        add     ax, 13849
        mov     [seed], ax
        mov     dx, ax
        and     dx, 3FFFh
        add     dx, 3000h
        cli
.r:     call    count                   ; the count's reload first (the IRQ's
        cmp     ax, 8000h               ;  moment, half of them), so that it
        jb      .r                      ;  comes in this wait
.c:     call    count
        cmp     ax, dx
        jae     .c
        sti
        nop
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        sub     ax, [t0]
        cmp     ax, [ticks]
        jb      .w
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .x
        xchg    bx, ax
        mov     ah, 40h
        mov     cx, 2
        mov     dx, okm
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

count:  xor     al, al                  ; counter 0, latched -> AX
        out     43h, al
        in      al, 40h
        mov     ah, al
        in      al, 40h
        xchg    al, ah
        ret

okm     db      'ok'
seed    dw      1234h
t0      dw      0
ticks   dw      0
fname   times   70 db 0
