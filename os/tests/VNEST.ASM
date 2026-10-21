; VNEST.BIN - for test_mt.py: an INT 10h teletype as the 1520's BIOS
; does it (int10.asm VidTeletype), calling INT 10h again for each step: 03h
; for the cursor, 0Ah for the character, 08h and 06h to scroll, 02h for
; the new cursor.  test_mt puts it at D000:0000 (outside conventional
; memory, as the ROM BIOS is) and makes it KMT's mt_old10, its own `old'
; pcemu's INT 10h; every other function goes straight there.
; nasm -f bin -o VNEST.BIN VNEST.ASM
cpu 286
org 0
        cmp     ah, 0Eh
        je      tty
        jmp     far [cs:old]
tty:    push    ax
        push    bx
        push    cx
        push    dx
        push    ds
        push    40h
        pop     ds
        mov     bh, [62h]               ; the page shown
        push    ax
        mov     ah, 3
        int     10h                     ; -> DX
        pop     ax
        cmp     al, 7
        je      .x
        cmp     al, 0Dh
        je      .cr
        cmp     al, 8
        jne     .nb
        sub     dl, 1
        jnb     .w
        jmp     short .cr
.nb:    cmp     al, 0Ah
        jne     .ch
        inc     dh
        jmp     short .w
.ch:    mov     ah, 0Ah
        mov     cx, 1
        int     10h
        inc     dx
        cmp     dl, [4Ah]
        jne     .w
        inc     dh
.cr:    xor     dl, dl
.w:     cmp     dh, 25
        jne     .s
        dec     dh
        push    dx
        push    bx
        mov     ah, 8
        int     10h                     ; (the attribute at the cursor)
        mov     bh, ah
        mov     ax, 0601h
        xor     cx, cx
        mov     dl, [4Ah]
        dec     dx
        int     10h
        pop     bx
        pop     dx
.s:     mov     ah, 2
        int     10h
.x:     pop     ds
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        iret
old     dd      0                       ; (test_mt: pcemu's INT 10h)
