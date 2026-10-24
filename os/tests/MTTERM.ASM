; MTTERM.COM - for test_mt.py: a terminal window's calls (T1), from the
; Executive's task (CODE-P's prompt):
;   MTTERM R n FILE [row rows]   MT_TROWS of task n (rows 0-24 unless
;      given, decimal): FILE gets CF (a byte), AX, BX, CX, DX after it
;      (words), then the 4000 bytes of room it copied to (00h before)
;   MTTERM F n FILE [row rows]   the same with the room at E000h:buf (the
;      EMS frame's window 0, where MT maps the task's pages: refused)
;   MTTERM K n FILE kkkk ...     MT_TKEY of task n, each key (hex) in turn:
;      FILE gets "cccc eeee", the keys it took and the first refusal's AX
;      (0000: none)
; nasm -f bin -o MTTERM.COM MTTERM.ASM
cpu 286
org 100h
        mov     si, 81h
        call    blanks
        lodsb
        and     al, 0DFh
        mov     [mode], al
        call    blanks
        lodsb
        sub     al, '0'
        mov     [task], al
        call    blanks
        mov     di, fname
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        stosb
        jmp     .n
.ne:    mov     byte [di], 0
        dec     si
        cmp     byte [mode], 'K'
        je      keys
        call    blanks                  ; R
        cmp     byte [si], '0'
        jb      .r
        call    dec_
        mov     [row], ax
        call    blanks
        call    dec_
        mov     [rows], ax
.r:     mov     ax, 0F000h + 1Fh
        mov     bl, [task]
        mov     dx, [row]
        mov     cx, [rows]
        push    ds
        pop     es
        cmp     byte [mode], 'F'
        jne     .c
        push    0E000h                  ; F: the room in the EMS frame
        pop     es
.c:     mov     di, buf
        stc
        int     21h
        mov     [h_ax], ax
        mov     [h_bx], bx
        mov     [h_cx], cx
        mov     [h_dx], dx
        mov     al, 0
        adc     al, 0
        mov     [h_cf], al
        mov     dx, hdr
        mov     cx, 9 + 4000
        jmp     short wr

keys:   call    blanks
        cmp     byte [si], ' '
        jbe     .d
        call    hex_
        mov     cx, ax
        mov     ax, 0F000h + 20h
        mov     bl, [task]
        stc
        int     21h
        jc      .e
        inc     word [took]
        jmp     keys
.e:     cmp     word [err], 0
        jne     keys
        mov     [err], ax
        jmp     keys
.d:     mov     di, txt
        mov     ax, [took]
        call    hex4
        mov     al, ' '
        stosb
        mov     ax, [err]
        call    hex4
        mov     dx, txt
        mov     cx, 9

wr:     push    cx
        push    dx
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        pop     dx
        pop     cx
        jc      .x
        mov     bx, ax
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

blanks: cmp     byte [si], ' '
        jne     .x
        inc     si
        jmp     blanks
.x:     ret

dec_:   xor     ax, ax                  ; a decimal number at SI -> AX
.l:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .x
        inc     si
        mov     cx, 10
        mul     cx
        xor     bh, bh
        add     ax, bx
        jmp     .l
.x:     ret

hex_:   xor     dx, dx                  ; a hex number at SI -> AX
.l:     mov     al, [si]
        cmp     al, '0'
        jb      .x
        cmp     al, '9'
        jbe     .d
        and     al, 0DFh
        cmp     al, 'A'
        jb      .x
        cmp     al, 'F'
        ja      .x
        sub     al, 7
.d:     sub     al, '0'
        inc     si
        shl     dx, 4
        or      dl, al
        jmp     .l
.x:     mov     ax, dx
        ret

hex4:   push    ax                      ; AX as 4 hex digits at DI
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
        jbe     .s
        add     al, 7
.s:     stosb
        ret

mode    db      0
task    db      0
row     dw      0
rows    dw      25
took    dw      0
err     dw      0
txt     times 9 db 0
fname   times 64 db 0
hdr:
h_cf    db      0
h_ax    dw      0
h_bx    dw      0
h_cx    dw      0
h_dx    dw      0
buf     times 4000 db 0
