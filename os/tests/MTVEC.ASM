; MTVEC.COM - for test_mt.py: each task's own vectors (KMT's mt_vrun,
; mt_vfr, mt_vfix: M5a).
;   MTVEC MODE [N] [FILE]
;   H  hooks INT 1Ch (AH=35h/25h, a handler that counts its calls and goes
;      on), waits N ticks (HLT), puts INT 1Ch back (AH=25h) and writes
;      FILE: "cccc", its handler's calls
;   G  sets INT 62h (the machine's) and 2Fh (its own) to handlers of its
;      own, writes FILE ("g") and ends, putting neither back
;   R  as G, then, a file (RO.TXT) open and an EMS page taken, stays
;      resident (AH=31h)
;   V  waits N ticks, then writes FILE: "ssss oooo" for INT 1Ch, 2Fh, 23h
;      and 24h, as AH=35h gives them
;   T  stays resident with an INT 1Ch hook (AH=35h/25h) that counts its
;      calls (the word before its handler) and goes on
;   K  writes INT 09h in the vector table itself (a handler that goes on),
;      waits N ticks, puts it back itself and writes FILE ("k")
;   P  sets INT 2Fh to a handler of its own that goes on, starts MTVEC V N
;      FILE as a task (INT 21h F0h AL=10h), and ends, putting it not back
;   Q  writes INT 09h in the table itself (in front, its own), starts
;      MTVEC V N FILE as a task in front, and ends, putting it not back
;   C  hooks INT 1Ch (AH=35h/25h), starts MTVEC V N FILE as a task, puts
;      INT 1Ch back and ends
;   B  hooks INT 1Bh (AH=35h/25h), asks for it again (AH=35h), waits N
;      ticks, puts it back (AH=25h), waits 3 N ticks more, writes FILE ("b
;      ssss oooo": the vector AH=35h gave the second time) and ends
; nasm -f bin -i ../src/ -o MTVEC.COM MTVEC.ASM
cpu 286
org 100h
%include "MTAPI.INC"
        mov     sp, stk_top
        mov     ah, 4Ah                 ; (only its own memory: P starts a task)
        mov     bx, (the_end - $$ + 100h + 15) / 16
        int     21h
        mov     si, 81h
        call    blanks
        lodsb
        and     al, 0DFh
        mov     [mode], al
        call    blanks
        xor     bx, bx                  ; N
.d:     lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .de
        imul    bx, bx, 10
        xor     ah, ah
        add     bx, ax
        jmp     .d
.de:    dec     si
        mov     [n], bx
        call    blanks
        mov     di, fname
.f:     lodsb
        cmp     al, ' '
        jbe     .fe
        stosb
        jmp     .f
.fe:    mov     byte [di], 0
        mov     al, [mode]
        cmp     al, 'H'
        je      m_h
        cmp     al, 'G'
        je      m_g
        cmp     al, 'R'
        je      m_g
        cmp     al, 'V'
        je      m_v
        cmp     al, 'T'
        je      m_t
        cmp     al, 'K'
        je      m_k
        cmp     al, 'P'
        je      m_p
        cmp     al, 'Q'
        je      m_q
        cmp     al, 'C'
        je      m_c
        cmp     al, 'B'
        je      m_b
        mov     ax, 4C01h
        int     21h

m_h:    mov     ax, 351Ch
        int     21h
        mov     [old1c], bx
        mov     [old1c + 2], es
        mov     ax, 251Ch
        mov     dx, h1c
        int     21h
        call    wait_n
        push    ds
        lds     dx, [old1c]
        mov     ax, 251Ch
        int     21h
        pop     ds
        push    cs                      ; (ES: AH=35h's, still)
        pop     es
        mov     ax, [cnt]
        mov     di, buf
        call    hex4
        jmp     wr_end

m_g:    mov     ax, 2562h
        mov     dx, hret
        int     21h
        mov     ax, 352Fh
        int     21h
        mov     [old2f], bx
        mov     [old2f + 2], es
        mov     ax, 252Fh
        mov     dx, h2f
        int     21h
        mov     byte [buf], 'g'
        mov     di, buf + 1
        call    wr_file
        cmp     byte [mode], 'R'
        jne     .x
        mov     ah, 3Ch                 ; (R: a file left open, an EMS page)
        xor     cx, cx
        mov     dx, s_ro
        int     21h
        mov     ah, 43h
        mov     bx, 1
        int     67h
        mov     dx, (the_end - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
.x:     mov     ax, 4C00h
        int     21h

m_v:    call    wait_n
        mov     di, buf
        mov     ax, 351Ch
        call    vec4
        mov     ax, 352Fh
        call    vec4
        mov     ax, 3523h
        call    vec4
        mov     ax, 3524h
        call    vec4
        dec     di
        jmp     wr_end

m_t:    mov     ax, 351Ch
        int     21h
        mov     [old1c], bx
        mov     [old1c + 2], es
        mov     ax, 251Ch
        mov     dx, h1c
        int     21h
        mov     dx, (the_end - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h

m_k:    xor     ax, ax
        mov     es, ax
        cli
        mov     ax, [es:9 * 4]
        mov     [old09], ax
        mov     ax, [es:9 * 4 + 2]
        mov     [old09 + 2], ax
        mov     word [es:9 * 4], k09
        mov     [es:9 * 4 + 2], cs
        sti
        call    wait_n
        xor     ax, ax
        mov     es, ax
        cli
        mov     ax, [old09]
        mov     [es:9 * 4], ax
        mov     ax, [old09 + 2]
        mov     [es:9 * 4 + 2], ax
        sti
        push    cs
        pop     es
        mov     byte [buf], 'k'
        mov     di, buf + 1
        jmp     wr_end

m_c:    mov     ax, 351Ch
        int     21h
        mov     [old1c], bx
        mov     [old1c + 2], es
        mov     ax, 251Ch
        mov     dx, h1c
        int     21h
        jmp     m_pq
m_b:    mov     ax, 351Bh
        int     21h
        mov     [old1b], bx
        mov     [old1b + 2], es
        mov     ax, 251Bh
        mov     dx, h1b
        int     21h
        mov     ax, 351Bh
        int     21h
        mov     [got1b], bx
        mov     [got1b + 2], es
        call    wait_n
        push    ds
        lds     dx, [old1b]
        mov     ax, 251Bh
        int     21h
        pop     ds
        mov     ax, [n]
        imul    ax, ax, 3
        mov     [n], ax
        call    wait_n
        push    cs
        pop     es
        mov     di, buf
        mov     ax, 'b '
        stosw
        mov     ax, [got1b + 2]
        call    hex4
        mov     al, ' '
        stosb
        mov     ax, [got1b]
        call    hex4
        jmp     wr_end
m_q:    xor     ax, ax
        mov     es, ax
        cli
        mov     ax, [es:9 * 4]
        mov     [old09], ax
        mov     ax, [es:9 * 4 + 2]
        mov     [old09 + 2], ax
        mov     word [es:9 * 4], k09
        mov     [es:9 * 4 + 2], cs
        sti
        mov     byte [pb + SP_FLAGS], SPF_FRONT
        jmp     short m_pq
m_p:    mov     ax, 352Fh
        int     21h
        mov     [old2f], bx
        mov     [old2f + 2], es
        mov     ax, 252Fh
        mov     dx, h2f
        int     21h
m_pq:   push    cs
        pop     es
        mov     di, tail + 1            ; " v N FILE", CR
        mov     si, s_v
.c1:    lodsb
        or      al, al
        jz      .c2
        stosb
        jmp     .c1
.c2:    mov     ax, [n]
        call    dec_out
        mov     al, ' '
        stosb
        mov     si, fname
.c3:    lodsb
        or      al, al
        jz      .c4
        stosb
        jmp     .c3
.c4:    mov     ax, di
        sub     ax, tail + 1
        mov     [tail], al
        mov     al, 0Dh
        stosb
        mov     [pb + SP_TAIL + 2], cs
        mov     ax, 0F000h + MT_SPAWN
        mov     dx, s_prog
        mov     bx, pb
        int     21h
        cmp     byte [mode], 'C'        ; (C: INT 1Ch back, then the end)
        jne     .q
        push    ds
        lds     dx, [old1c]
        mov     ax, 251Ch
        int     21h
        pop     ds
.q:     cmp     byte [mode], 'Q'       ; (Q: until V is in front, then the end)
        jne     .e
        mov     word [n], 9
        call    wait_n
.e:     mov     ax, 4C00h
        int     21h

; N ticks, with HLT.  AX, DX changed
wait_n: push    es
        push    40h
        pop     es
        mov     dx, [es:6Ch]
        add     dx, [n]
.w:     sti
        hlt
        mov     ax, [es:6Ch]
        sub     ax, dx
        js      .w
        pop     es
        ret

; AH=35h for the vector in AL (AX as given) -> "ssss oooo " at DI
vec4:   push    es
        int     21h
        mov     ax, es
        pop     es
        push    bx
        call    hex4
        mov     al, ' '
        stosb
        pop     ax
        call    hex4
        mov     al, ' '
        stosb
        ret

; buf .. DI to FILE, then the end
wr_end: call    wr_file
        mov     ax, 4C00h
        int     21h
wr_file:
        push    di
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        pop     cx
        jc      .x
        mov     bx, ax
        sub     cx, buf
        mov     dx, buf
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret

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

; AX in decimal at DI
dec_out:
        mov     bx, 10
        xor     cx, cx
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.o:     pop     ax
        add     al, '0'
        stosb
        loop    .o
        ret

blanks: lodsb
        cmp     al, ' '
        je      blanks
        dec     si
        ret

; the handlers
        dw      0                       ; (T: read by the test, before h1c)
cnt     equ     $ - 2
h1c:    inc     word [cs:cnt]
        jmp     far [cs:old1c]
hret:   iret
h2f:    jmp     far [cs:old2f]
k09:    jmp     far [cs:old09]
h1b:    jmp     far [cs:old1b]

old1c   dd      0
old2f   dd      0
old09   dd      0
old1b   dd      0
got1b   dd      0
s_ro    db      'RO.TXT', 0
n       dw      0
mode    db      0
s_v     db      ' v ', 0
s_prog  db      'MTVEC.COM', 0
pb      dw      0, tail, 0, 0, 0, 0, 0, 0       ; (SP_*: env, tail, FCBs, paras)
        db      0                               ;  flags: in the background
tail    times   128 db 0
fname   times   80 db 0
buf     times   40 db 0
        times   256 db 0
stk_top:
the_end:
