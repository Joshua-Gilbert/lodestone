; CAPTEST.COM - screens for the screen capture (tests/test_kernel.py).
; Each waits for a key through DOS (INT 21h 08h), where Shift-PrtSc is
; taken: mode 6 with line y filled with the byte y; 80-column text with a
; NUL in it; 40-column text.  Then a wait through the BIOS (INT 16h) with
; an INT 1Ch hook that calls DOS (2Ah) when InDOS is 0, as clock TSRs do:
; a Shift-PrtSc there waits for a DOS call outside the interrupt (here,
; the one that takes the hook out).
        org     100h
        cpu     286
        mov     ax, 0006h
        int     10h
        push    0B800h
        pop     es
        xor     bx, bx
.g:     mov     ax, bx                  ; line y: bank y & 1, row y / 2
        shr     ax, 1
        imul    di, ax, 80
        test    bl, 1
        jz      .e
        add     di, 2000h
.e:     mov     al, bl
        mov     cx, 80
        rep     stosb
        inc     bx
        cmp     bx, 200
        jb      .g
        call    getkey
        mov     ax, 0003h
        int     10h
        mov     dx, s80
        call    print
        mov     byte [es:3 * 160 + 5 * 2], 0
        call    getkey
        mov     ax, 0001h
        int     10h
        mov     dx, s40
        call    print
        call    getkey
        mov     ax, 0003h
        int     10h
        mov     dx, sbios
        call    print
        mov     ah, 34h
        int     21h
        mov     [indos], bx
        mov     [indos+2], es
        mov     ax, 351Ch
        int     21h
        mov     [old1c], bx
        mov     [old1c+2], es
        mov     dx, hook
        mov     ax, 251Ch
        int     21h
        xor     ah, ah
        int     16h
        push    ds
        lds     dx, [old1c]
        mov     ax, 251Ch
        int     21h
        pop     ds
        mov     ax, 4C00h
        int     21h

hook:   pusha
        push    es
        les     bx, [cs:indos]
        cmp     byte [es:bx], 0
        jne     .x
        mov     ah, 2Ah
        int     21h
.x:     pop     es
        popa
        jmp     far [cs:old1c]

print:  mov     ah, 9
        int     21h
        ret

getkey: mov     ah, 8
        int     21h
        ret

s80     db 'Line one   ', 13, 10, 'Second line', 13, 10, 13, 10, 'ABCDEFGHIJ$'
s40     db 'Forty$'
sbios   db 'BIOS wait$'
indos   dd 0
old1c   dd 0
