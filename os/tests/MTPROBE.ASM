; MTPROBE.COM - INT 21h AH=F0h with AL = 00h, 11h (not from a task's
; stub), 12h (no room: CX = 0), 13h (BL = 0, the Executive; 8, none such;
; 7, a free one), 14h, 1Bh, 1Ch, FFh, then 1Fh and 20h (T1) and 1Eh (T2:
; BL = 0, 7, 8, then 1 with CL = 1, task 1's first count: from a task,
; refused; CX = 1234h, ES:DI = buf) and 21h (T4: BL = 0, 7, 8, 1), for
; test_mt.py: one line each,
;   "F0xx CF=c AX=xxxx BX=xxxx CX=xxxx"
; (CF set and BX = CX = 1234h before each call, so what changed shows)
; nasm -f bin -o MTPROBE.COM MTPROBE.ASM
cpu 286
org 100h
        mov     si, als
.l:     lodsb
        cmp     al, 0EEh                ; (the list's end)
        je      .x
        mov     ah, [si]                ; (its BL, for 13h)
        inc     si
        mov     [cbl], ah
        cmp     al, 1Eh                 ; (MT_TOPEN: its CL, a count, next)
        jne     .k
        mov     ah, [si]
        inc     si
        mov     [ccl], ah
.k:     push    si
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
.c:     cmp     al, 13h
        je      .cb
        cmp     al, 1Eh
        je      .cb
        cmp     al, 1Fh
        je      .cb
        cmp     al, 20h
        je      .cb
        cmp     al, 21h
        jne     .c1
.cb:    mov     bl, [cbl]               ; MT_FRONT, MT_TOPEN, MT_TROWS, MT_TKEY,
                                        ;  MT_TMOUSE: BL (BH 0: no buttons)
        xor     bh, bh
        cmp     byte [cur], 1Eh
        jne     .c1
        mov     cl, [ccl]
.c1:    stc
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

als     db      00h, 0, 11h, 0, 12h, 0, 13h, 0, 13h, 8, 13h, 7, 14h, 0, 1Bh, 0
        db      1Ch, 0, 0FFh, 0, 1Fh, 0, 1Fh, 7, 1Fh, 8, 20h, 0, 20h, 7, 20h, 8
        db      1Eh, 0, 34h, 1Eh, 7, 34h, 1Eh, 8, 34h, 1Eh, 1, 1
        db      21h, 0, 21h, 7, 21h, 8, 21h, 1, 0EEh
cbl     db      0
ccl     db      0
s_f0    db      'F0$'
s_cf    db      ' CF=$'
s_ax    db      ' AX=$'
s_bx    db      ' BX=$'
s_cx    db      ' CX=$'
s_nl    db      13, 10, '$'
cur     db      0
buf     times 16 db 0
