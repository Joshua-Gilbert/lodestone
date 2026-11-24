; DIVT.COM - for the kernel's INT 00h (KCORE.INC's int00): divide errors
; outside a plain program's own code (test_kernel.py, test_mt.py).
;   DIVT MODE [N]
;   Z  "Z1", then a divide by zero ("Z2" never comes)
;   W  waits N ticks (40:6Ch, HLT), printing a dot each, then as Z
;   O  its own INT 00h handler (AH=35h/25h); waits N ticks, divides, the
;      handler says "own" and returns past the DIV; puts INT 00h back
;      (AH=25h), "back", exit code 3
;   K  as O, but leaves its handler in INT 00h: exit code 4
;   T  stays resident (AH=31h) with two hooks: INT 10h (AH=0Eh with AL =
;      '!' divides; anything else goes on) and INT 1Ch (with the byte at
;      CS:0103h not 0: it is cleared, then a divide; else goes on)
;   B  "A", "!", "B" through AH=02h, then exit code 7 (with T resident, the
;      '!' divides inside INT 21h)
; nasm -f bin -o DIVT.COM DIVT.ASM
cpu 286
org 100h
        jmp     near start
arm     db      0                       ; (103h: T's INT 1Ch divides when set)
zero    dw      0

; T's hooks (resident)
h10:    cmp     ax, 0E00h + '!'
        jne     .on
        div     word [cs:zero]
.on:    jmp     far [cs:old10]
h1c:    cmp     byte [cs:arm], 0
        je      .on
        mov     byte [cs:arm], 0
        div     word [cs:zero]
.on:    jmp     far [cs:old1c]
old10   dd      0
old1c   dd      0
res_end:

start:  mov     si, 81h
.b:     lodsb
        cmp     al, ' '
        je      .b
        and     al, 0DFh
        mov     [mode], al
.s:     lodsb
        cmp     al, ' '
        je      .s
        dec     si
        xor     bx, bx                  ; N
.n:     lodsb
        sub     al, '0'
        jb      .go
        cmp     al, 9
        ja      .go
        cbw
        imul    bx, bx, 10
        add     bx, ax
        jmp     .n
.go:    mov     [count], bx
        mov     al, [mode]
        cmp     al, 'Z'
        je      m_z
        cmp     al, 'W'
        je      m_w
        cmp     al, 'O'
        je      m_o
        cmp     al, 'K'
        je      m_o
        cmp     al, 'T'
        je      m_t
        cmp     al, 'B'
        je      m_b
        mov     ax, 4C01h
        int     21h

m_w:    call    wait_n
m_z:    mov     dx, s_z1
        mov     ah, 9
        int     21h
        xor     bx, bx
        div     bx
        mov     dx, s_z2
        mov     ah, 9
        int     21h
        mov     ax, 4C05h
        int     21h

m_o:    mov     ax, 3500h
        int     21h
        mov     [old0], bx
        mov     [old0+2], es
        mov     dx, h0
        mov     ax, 2500h
        int     21h
        call    wait_n
        xor     bx, bx
        mov     ax, 1234
        div     bx                      ; (2 bytes: h0 returns past them)
        mov     dx, s_after
        mov     ah, 9
        int     21h
        cmp     byte [mode], 'K'
        mov     ax, 4C04h
        je      .x
        push    ds
        lds     dx, [old0]
        mov     ax, 2500h
        int     21h
        pop     ds
        mov     dx, s_back
        mov     ah, 9
        int     21h
        mov     ax, 4C03h
.x:     int     21h
h0:     push    bp
        mov     bp, sp
        add     word [bp+2], 2
        pop     bp
        push    ax
        push    dx
        push    ds
        push    cs
        pop     ds
        mov     dx, s_own
        mov     ah, 9
        int     21h
        pop     ds
        pop     dx
        pop     ax
        iret

; N ticks of 40:6Ch (HLT between), a dot for each
wait_n: mov     cx, [count]
        jcxz    .x
        push    0
        pop     es
.t:     mov     ax, [es:46Ch]
.h:     sti
        hlt
        cmp     ax, [es:46Ch]
        je      .h
        mov     dl, '.'
        mov     ah, 2
        int     21h
        loop    .t
        push    ds
        pop     es
.x:     ret

m_t:   mov     ax, 3510h
        int     21h
        mov     [old10], bx
        mov     [old10+2], es
        mov     ax, 351Ch
        int     21h
        mov     [old1c], bx
        mov     [old1c+2], es
        mov     dx, h10
        mov     ax, 2510h
        int     21h
        mov     dx, h1c
        mov     ax, 251Ch
        int     21h
        mov     dx, s_t
        mov     ah, 9
        int     21h
        mov     dx, (res_end - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h

m_b:    mov     dl, 'A'
        mov     ah, 2
        int     21h
        mov     dl, '!'
        mov     ah, 2
        int     21h
        mov     dl, 'B'
        mov     ah, 2
        int     21h
        mov     ax, 4C07h
        int     21h

s_z1    db      'Z1$'
s_z2    db      'Z2$'
s_own   db      'own $'
s_after db      'after $'
s_back  db      'back$'
s_t     db      'DIVT resident', 13, 10, '$'
mode    db      0
count   dw      0
old0    dd      0
