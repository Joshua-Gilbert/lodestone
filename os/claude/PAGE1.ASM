; PAGE1.COM - a text program on display page 1 (INT 10h AH=05h), for
; resident Claude's SCREEN: its cells start at B800:[40:4Eh], not at 0.
; Every byte of the 32 KB is set first (a pattern: each word its offset),
; so a byte the console doesn't put back shows.  Reads keys until Esc.
cpu 286
org 100h
start:  mov     ax, 0003h
        int     10h
        push    0B800h
        pop     es
        xor     di, di
        mov     cx, 4000h
.f:     mov     ax, di
        stosw
        loop    .f
        mov     ax, 0501h               ; page 1 shown
        int     10h
        push    40h
        pop     ds
        mov     di, [4Eh]               ; where the BIOS says it starts
        push    cs
        pop     ds
        mov     si, msg
        mov     ah, 07h
.m:     lodsb
        or      al, al
        jz      .k
        stosw
        jmp     .m
.k:     xor     ah, ah
        int     16h
        cmp     al, 1Bh
        jne     .k
        mov     ax, 0500h
        int     10h
        mov     ax, 4C00h
        int     21h
msg     db      'PAGE1 ready', 0
