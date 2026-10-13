; GFXUSE.COM [mode] - a program in a video mode of its own (hex, 4 if not
; given; 3, 6, 40 ...) with a pattern in all 32 KB of video memory and, in
; CGA modes, a colour register set through the BIOS.  After every key it
; checks the video memory and the BIOS's video data (40:49h-66h) are as it
; left them (for RSPIKE's pop-up).  Esc: text mode, "GFXUSE: n keys, k bad".
cpu 286
org 100h
        mov     si, 81h
        xor     bx, bx
.a:     lodsb
        cmp     al, ' '
        je      .a
        cmp     al, 13
        je      .ad
.h:     sub     al, '0'
        cmp     al, 9
        jbe     .dg
        and     al, 0DFh
        sub     al, 'A' - '0' - 10
.dg:    shl     bl, 4
        or      bl, al
        lodsb
        cmp     al, ' '
        ja      .h
.ad:    or      bl, bl
        jnz     .md
        mov     bl, 4
.md:    mov     [mode], bl
        mov     al, bl
        xor     ah, ah
        int     10h
        cmp     byte [mode], 6          ; CGA graphics: background 1, palette 1
        ja      .pat
        cmp     byte [mode], 4
        jb      .pat
        mov     ax, 0B00h
        mov     bx, 0001h
        int     10h
        mov     ax, 0B00h
        mov     bx, 0101h
        int     10h
.pat:   push    0B800h
        pop     es
        xor     di, di
        mov     ax, 1357h
        mov     cx, 4000h
.f:     stosw
        add     ax, 2B19h
        loop    .f
        push    cs
        pop     es
        call    sums
        mov     [sum0], ax
        mov     [sum0 + 2], dx
.key:   xor     ah, ah
        int     16h
        cmp     al, 27
        je      .end
        inc     word [keys]
        call    sums
        cmp     ax, [sum0]
        jne     .bad
        cmp     dx, [sum0 + 2]
        je      .key
.bad:   inc     word [bad]
        jmp     .key
.end:   mov     ax, 3
        int     10h
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
        mov     ah, 4Ch
        int     21h

; DX:AX: the video memory's words summed (AX) and rotated-xored (DX), and
; the BIOS's video data folded in
sums:   push    ds
        push    0B800h
        pop     ds
        xor     si, si
        xor     bx, bx
        xor     dx, dx
        mov     cx, 4000h
.s:     lodsw
        add     bx, ax
        rol     dx, 1
        xor     dx, ax
        loop    .s
        push    40h
        pop     ds
        mov     si, 49h
        mov     cx, 15
.b:     lodsw
        add     bx, ax
        rol     dx, 3
        xor     dx, ax
        loop    .b
        pop     ds
        mov     ax, bx
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

s_res   db 'GFXUSE: $'
s_res2  db ' keys, $'
s_res3  db ' bad', 13, 10, '$'
mode    db 4
keys    dw 0
bad     dw 0
sum0    dw 0, 0
