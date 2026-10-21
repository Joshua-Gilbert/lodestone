; MTKEY.COM - for test_mt.py: keys through INT 16h (KMT's mt_i16, M4b).
;   MTKEY MODE FILE
;   R  a key read with INT 16h AH=00h (in the BIOS, it waits there);
;      FILE gets the AX it gave (4 hex digits)
;   E  the same with AH=10h
;   C  the same as R, with interrupts off (CLI before the INT 16h)
;   H  stays resident, hooking INT 16h: a read waits in its own loop (a
;      peek of its kind through the INT 16h it found, then HLT), as
;      Resident Claude's does, then goes on there (JMP FAR); the rest are
;      called there (PUSHF / CALL FAR, as most TSRs chain)
;   P  for 18 ticks, INT 16h AH=01h and AH=11h in turn: FILE gets
;      "nnnn kkkk", the peeks made and how many found a key
;   D  for 18 ticks, INT 21h AH=0Bh and AH=06h (DL=FFh) in turn, then
;      AH=0Ch AL=0 (a flush): FILE gets "aaaa bbbb", AH=0Bh's "a key"
;      answers and the characters AH=06h got
;   X  as D, with INT 08h hooked meanwhile (its handler goes straight on
;      to the one it found: a timer hook ahead of MT's)
;   Y  as P, with INT 08h hooked meanwhile, as X
;   Q  as P, each call made with interrupts off; only those that came back
;      with them on (as the BIOS's do: its STI) counted
;   T  for 18 ticks, an INT 1Ch handler of its own peeks (INT 16h AH=01h,
;      with the timer's interrupt in service): FILE gets "nnnn kkkk", the
;      handler's calls and how many peeks found a key
; nasm -f bin -o MTKEY.COM MTKEY.ASM
cpu 286
org 100h
        mov     si, 81h
        call    blanks
        lodsb
        and     al, 0DFh
        mov     [mode], al
        call    blanks
        mov     di, fname
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        stosb
        jmp     .n
.ne:    mov     byte [di], 0
        mov     di, out_
        mov     al, [mode]
        cmp     al, 'R'
        je      .rd
        cmp     al, 'E'
        je      .rd
        cmp     al, 'C'
        je      .rd
        cmp     al, 'H'
        je      hk_
        call    t18
        cmp     al, 'X'
        je      .hx
        cmp     al, 'Y'
        jne     .nx
.hx:    push    es
        xor     ax, ax
        mov     es, ax
        cli
        mov     ax, [es:8 * 4]
        mov     [o08], ax
        mov     ax, [es:8 * 4 + 2]
        mov     [o08 + 2], ax
        mov     word [es:8 * 4], h08
        mov     [es:8 * 4 + 2], cs
        sti
        pop     es
        mov     al, [mode]
        cmp     al, 'Y'
        je      .pl
.nx:    cmp     al, 'P'
        je      .pl
        cmp     al, 'Q'
        je      .ql
        cmp     al, 'T'
        je      .tk
.dl:    mov     ah, 0Bh                 ; D
        int     21h
        or      al, al
        jz      .d1
        inc     word [ca]
.d1:    mov     ah, 6
        mov     dl, 0FFh
        int     21h
        jz      .d2
        inc     word [cb]
.d2:    call    tdone
        jc      .dl
        mov     ax, 0C00h
        int     21h
        jmp     .two
.pl:    mov     ah, 1                   ; P
        int     16h
        jz      .p1
        inc     word [cb]
.p1:    mov     ah, 11h
        int     16h
        jz      .p2
        inc     word [cb]
.p2:    add     word [ca], 2
        call    tdone
        jc      .pl
        jmp     .two
.ql:    cli                             ; Q
        mov     ah, 1
        int     16h
        pushf
        sti
        pop     bx
        call    qcount
        cli
        mov     ah, 11h
        int     16h
        pushf
        sti
        pop     bx
        call    qcount
        call    tdone
        jc      .ql
        jmp     short .two
.tk:    mov     ax, 351Ch               ; T
        int     21h
        mov     [o1c], bx
        mov     [o1c + 2], es
        mov     ax, 251Ch
        mov     dx, h1c
        int     21h
.tw:    sti
        hlt
        call    tdone
        jc      .tw
        push    ds
        lds     dx, [o1c]
        mov     ax, 251Ch
        int     21h
        pop     ds
        push    ds                      ; (ES: AH=35h's)
        pop     es
.two:   cmp     word [o08 + 2], 0       ; (X, Y: INT 08h back)
        je      .t2
        push    es
        xor     ax, ax
        mov     es, ax
        cli
        mov     ax, [o08]
        mov     [es:8 * 4], ax
        mov     ax, [o08 + 2]
        mov     [es:8 * 4 + 2], ax
        sti
        pop     es
.t2:    mov     ax, [ca]
        call    hex4
        mov     al, ' '
        stosb
        mov     ax, [cb]
        call    hex4
        jmp     short .wr
.rd:    cmp     al, 'E'                 ; R, E, C
        mov     ah, 10h
        je      .r
        mov     ah, 0
        cmp     al, 'C'
        jne     .r
        cli
.r:     int     16h
        sti
        call    hex4
.wr:    mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .x
        xchg    bx, ax
        mov     ah, 40h
        mov     cx, di
        mov     dx, out_
        sub     cx, dx
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

h08:    jmp     far [cs:o08]            ; (X's)

h1c:    push    ax                      ; (T's: a peek, from INT 1Ch)
        inc     word [cs:ca]
        mov     ah, 1
        int     16h
        jz      .n
        inc     word [cs:cb]
.n:     pop     ax
        jmp     far [cs:o1c]

hk_:    mov     ax, 3516h               ; H
        int     21h
        mov     [old16], bx
        mov     [old16 + 2], es
        mov     ax, 2516h
        mov     dx, h16
        int     21h
        mov     dx, (the_end - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h

h16:    cmp     ah, 0                   ; (H's: a read waits here)
        je      .w
        cmp     ah, 10h
        je      .w
        pushf
        call    far [cs:old16]
        retf    2
.go:    jmp     far [cs:old16]
.w:     sti
        push    ax
        inc     ah
        pushf
        call    far [cs:old16]
        pop     ax
        jnz     .go
        hlt
        jmp     .w

blanks: lodsb
        cmp     al, ' '
        je      blanks
        dec     si
        ret

; the end: 18 ticks from now (AL kept)
t18:    push    es
        push    40h
        pop     es
        mov     dx, [es:6Ch]
        add     dx, 18
        mov     [tend], dx
        pop     es
        ret

; Q's call, its flags BX: counted if back with interrupts on, found if ZF
; clear
qcount: test    bh, 2
        jz      .x
        inc     word [ca]
        test    bl, 40h
        jnz     .x
        inc     word [cb]
.x:     ret

; CF while the end isn't reached
tdone:  push    es
        push    40h
        pop     es
        mov     ax, [es:6Ch]
        pop     es
        sub     ax, [tend]
        shl     ah, 1
        ret

; AX as 4 hex digits at DI
hex4:   mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .s
        add     al, 7
.s:     stosb
        pop     ax
        loop    .h
        ret

mode    db      0
o1c     dd      0
o08     dd      0
old16     dd      0
tend    dw      0
ca      dw      0
cb      dw      0
out_    times   16 db 0
fname   times   80 db 0
the_end:
