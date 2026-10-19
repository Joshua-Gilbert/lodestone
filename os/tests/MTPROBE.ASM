; MTPROBE.COM - INT 21h AH=F0h with AL = 00h, 10h, 11h, 12h (no room:
; CX = 0), 13h and FFh, for test_mt.py: one line each,
;   "F0xx CF=c AX=xxxx BX=xxxx CX=xxxx"
; (CF set and BX = CX = 1234h before each call, so what changed shows)
; nasm -f bin -o MTPROBE.COM MTPROBE.ASM
cpu 286
org 100h
        mov     si, als
.l:     lodsb
        cmp     al, 0EEh                ; (the list's end)
        je      .x
        push    si
        mov     [cur], al
        mov     ah, 0F0h
        mov     bx, 1234h
        mov     cx, bx
        push    ds
        pop     es
        mov     di, buf
        cmp     al, 12h
        jne     .c
        xor     cx, cx                  ; MT_LIST with no room: counted only
.c:     stc
        int     21h
        pushf
        push    cx
        push    bx
        push    ax
        mov     dx, s_f0
        call    out
        mov     al, [cur]
        call    hex2
        mov     dx, s_cf
        call    out
        pop     ax
        pop     bx
        pop     cx
        popf
        push    cx
        push    bx
        push    ax
        mov     al, '0'
        adc     al, 0
        call    chr
        mov     dx, s_ax
        call    out
        pop     ax
        call    hex4
        mov     dx, s_bx
        call    out
        pop     ax
        call    hex4
        mov     dx, s_cx
        call    out
        pop     ax
        call    hex4
        mov     dx, s_nl
        call    out
        pop     si
        jmp     .l
.x:     mov     ax, 4C00h
        int     21h

out:    mov     ah, 9
        int     21h
        ret
hex4:   push    ax
        mov     al, ah
        call    hex2
        pop     ax
hex2:   push    ax
        shr     al, 4
        call    hex1
        pop     ax
hex1:   and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     chr
        add     al, 7
chr:    push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        ret

als     db      00h, 10h, 11h, 12h, 13h, 0FFh, 0EEh
s_f0    db      'F0$'
s_cf    db      ' CF=$'
s_ax    db      ' AX=$'
s_bx    db      ' BX=$'
s_cx    db      ' CX=$'
s_nl    db      13, 10, '$'
cur     db      0
buf     times 16 db 0
