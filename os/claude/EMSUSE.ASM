; EMSUSE.COM - a program that keeps four EMS pages of its own in all four
; windows while it waits for keys, and checks after every key that they
; are still there, whole (resident Claude's console must give them back).
;   EMSUSE      reads keys with INT 16h AH=00h      EMSUSE /X   with AH=10h
; Esc ends: "EMSUSE: n keys, k bad", exit code k (at most 255).
cpu 286
org 100h
        mov     byte [rd], 0
        mov     si, 81h
.a:     lodsb
        cmp     al, 13
        je      .ad
        and     al, 0DFh
        cmp     al, 'X'
        jne     .a
        mov     byte [rd], 10h
        jmp     .a
.ad:    mov     ah, 43h
        mov     bx, 4
        int     67h
        or      ah, ah
        jnz     .noems
        mov     [handle], dx
        xor     bx, bx                  ; page w in window w, filled with
.m:     mov     ax, 4400h               ;  its own pattern
        add     al, bl
        mov     dx, [handle]
        push    bx
        int     67h
        pop     bx
        inc     bx
        cmp     bx, 4
        jb      .m
        push    0E000h
        pop     es
        xor     di, di
        xor     ax, ax
        mov     cx, 8000h
.f:     stosw
        add     ax, 4F1Bh
        loop    .f
        push    cs
        pop     es
        mov     dx, 0258h               ; the registers as mapped
        mov     si, regs
        mov     cx, 4
.r:     in      al, dx
        mov     [si], al
        inc     si
        add     dx, 4000h
        loop    .r
.key:   mov     dx, s_key
        mov     ah, 9
        int     21h
        mov     ah, [rd]
        int     16h
        cmp     al, 27
        je      .end
        inc     word [keys]
        call    check
        mov     dx, s_ok
        jnc     .p
        inc     word [bad]
        mov     dx, s_bad
.p:     mov     ah, 9
        int     21h
        jmp     .key
.end:   call    check
        jnc     .e1
        inc     word [bad]
.e1:    mov     ah, 45h
        mov     dx, [handle]
        int     67h
        mov     dx, s_res
        mov     ah, 9
        int     21h
        mov     ax, [keys]
        call    pnum
        mov     dx, s_res2
        mov     ah, 9
        int     21h
        mov     ax, [bad]
        call    pnum
        mov     dx, s_res3
        mov     ah, 9
        int     21h
        mov     al, [bad]
        cmp     word [bad], 255
        jbe     .x
        mov     al, 255
.x:     mov     ah, 4Ch
        int     21h
.noems: mov     dx, s_noems
        mov     ah, 9
        int     21h
        mov     ax, 4C01h
        int     21h

; CF if a window's register or a word of the 64 KB isn't as it was
check: mov     dx, 0258h
        mov     si, regs
        mov     cx, 4
.r:     in      al, dx
        cmp     al, [si]
        jne     .bad
        inc     si
        add     dx, 4000h
        loop    .r
        push    ds
        push    0E000h
        pop     ds
        xor     si, si
        xor     bx, bx
        mov     cx, 8000h
.c:     lodsw
        cmp     ax, bx
        jne     .b2
        add     bx, 4F1Bh
        loop    .c
        pop     ds
        clc
        ret
.b2:    pop     ds
.bad:   stc
        ret

pnum:   xor     cx, cx
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     dx
        add     dl, '0'
        mov     ah, 2
        int     21h
        loop    .p
        ret

s_key   db 'key? $'
s_ok    db 'ok', 13, 10, '$'
s_bad   db 'EMS NOT AS IT WAS', 13, 10, '$'
s_res   db 'EMSUSE: $'
s_res2  db ' keys, $'
s_res3  db ' bad', 13, 10, '$'
s_noems db 'EMSUSE needs 4 free EMS pages', 13, 10, '$'
rd      db 0
handle  dw 0
keys    dw 0
bad     dw 0
regs    db 0, 0, 0, 0
