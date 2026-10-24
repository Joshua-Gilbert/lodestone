; CRITKEY.COM - for test_resident_term.py: its own INT 24h handler waits for
; a key through the BIOS (INT 16h AH=00h, inside INT 21h: DOS one call deep,
; the call not the kernel's), then fails the call.  It reads ZZ.DAT (the
; test makes its sectors bad), says "CRITKEY: n" (the INT 24h calls) and
; waits for Esc.
; nasm -f bin -o CRITKEY.COM CRITKEY.ASM
cpu 286
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     ax, 3D00h
        mov     dx, s_zz
        int     21h
        jc      .s
        mov     bx, ax
        mov     ah, 3Fh
        mov     cx, 512
        mov     dx, buf
        int     21h
        mov     ah, 3Eh
        int     21h
.s:     mov     al, [n24]
        add     [s_n], al
        mov     dx, s_done
        mov     ah, 9
        int     21h
.k:     xor     ah, ah
        int     16h
        cmp     al, 1Bh
        jne     .k
        mov     ax, 4C00h
        int     21h

h24:    sti
        push    ds
        push    cs
        pop     ds
        inc     byte [n24]
        push    bx
        push    si
        mov     si, s_pr                ; (the BIOS's teletype: no DOS here)
.l:     lodsb
        or      al, al
        jz      .w
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     .l
.w:     xor     ah, ah
        int     16h
        pop     si
        pop     bx
        pop     ds
        mov     al, 3                   ; Fail
        iret

s_zz    db      'ZZ.DAT', 0
s_pr    db      'CRITKEY waits', 13, 10, 0
s_done  db      'CRITKEY: '
s_n     db      '0', 13, 10, '$'
n24     db      0
buf:
