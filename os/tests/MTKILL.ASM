; MTKILL.COM - for test_mt.py: tasks ended with MT_KILL (KMT's mt_kill,
; M5b).
;   MTKILL MODE N FILE
;   F  creates FILE and writes N bytes ("k"s) to it, takes an EMS page,
;      then reads a line (INT 21h AH=0Ah: it waits in kbd_get), the file
;      still open; given one, writes "!" to it and ends
;   S  as F, but then computes for ever (no INT 21h call), interrupts on
;   C  runs MTKILL F N FILE as its child (AH=4Bh), then ends
;   X  as F, but then ends its own task (AL=12h for its number, AL=14h);
;      back from that, writes "!" and ends
;   K  waits 9 ticks, ends task N (AL=14h), and writes FILE: "cf ax" (CF
;      as 0 or 1, AX as 4 hex digits)
;   M  sets a mouse event handler (INT 33h 0Ch, every event) and computes;
;      the handler, called in its own task, waits for a key (AH=08h)
;   Z  as M, but the handler ends its own task (AL=14h)
;   R  as Z, but once the handler has run, reads a key (INT 16h AH=00h)
;   T  hooks INT 1Ch and computes; its 5th call ends its own task (AL=14h,
;      the timer's interrupt in service)
;   (M, Z, R and T take N and FILE but use neither)
; nasm -f bin -i ../src/ -o MTKILL.COM MTKILL.ASM
cpu 286
org 100h
%include "MTAPI.INC"
        mov     sp, stk_top
        mov     ah, 4Ah                 ; (only its own memory: C runs a child)
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
        mov     [fpos], si              ; (FILE, as typed: C's child gets it)
        mov     di, fname
.f:     lodsb
        cmp     al, ' '
        jbe     .fe
        stosb
        jmp     .f
.fe:    mov     byte [di], 0
        mov     al, [mode]
        cmp     al, 'C'
        je      m_c
        cmp     al, 'K'
        je      m_k
        cmp     al, 'M'
        je      m_m
        cmp     al, 'Z'
        je      m_m
        cmp     al, 'R'
        je      m_m
        cmp     al, 'T'
        je      m_t
        ; F, S, X: the file, N bytes, open
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      ends
        mov     [fh], ax
        mov     cx, [n]
.w:     jcxz    .we
        push    cx
        cmp     cx, 64
        jbe     .wn
        mov     cx, 64
.wn:    mov     bx, [fh]
        mov     dx, ks
        mov     ah, 40h
        int     21h
        pop     cx
        jc      ends
        or      ax, ax                  ; (none written: a full disk)
        jz      ends
        sub     cx, ax
        jmp     .w
.we:    mov     ah, 43h                 ; an EMS page of its own
        mov     bx, 1
        int     67h
        mov     al, [mode]
        cmp     al, 'S'
        je      .spin
        cmp     al, 'X'
        je      .self
        mov     dx, line                ; F: a line
        mov     ah, 0Ah
        int     21h
        jmp     short bang
.spin:  sti
.sp:    inc     word [cnt]
        jmp     .sp
.self:  mov     ax, 0F000h + MT_LIST    ; X: its own task's number (AH)
        push    cs
        pop     es
        mov     di, recs
        xor     cx, cx
        int     21h
        mov     bl, ah
        mov     ax, 0F000h + MT_KILL
        int     21h
bang:   mov     bx, [fh]                ; (back: "!", and the end)
        mov     dx, s_bang
        mov     cx, 1
        mov     ah, 40h
        int     21h
ends:   mov     ax, 4C00h
        int     21h

; C: MTKILL F N FILE as its child
m_c:    push    cs
        pop     es
        mov     di, tail + 1            ; " F ", then N and FILE as typed, CR
        mov     ax, ' ' + 'F' * 256
        stosw
        mov     al, ' '
        stosb
        mov     ax, [n]
        call    dec_out
        mov     al, ' '
        stosb
        mov     si, [fpos]
.c:     lodsb
        cmp     al, 0Dh
        je      .ce
        stosb
        jmp     .c
.ce:    mov     al, 0Dh
        stosb
        mov     ax, di
        sub     ax, tail + 2
        mov     [tail], al
        mov     [pb + 4], cs
        mov     [pb + 8], cs
        mov     [pb + 12], cs
        mov     ax, 4B00h
        mov     dx, s_prog
        mov     bx, pb
        int     21h
        jmp     ends

; K: task N ended, 9 ticks from now
m_k:    push    es
        push    40h
        pop     es
        mov     dx, [es:6Ch]
        add     dx, 9
.t:     sti
        hlt
        mov     ax, [es:6Ch]
        sub     ax, dx
        js      .t
        pop     es
        mov     bl, [n]
        mov     ax, 0F000h + MT_KILL
        int     21h
        push    cs
        pop     es
        mov     di, buf
        push    ax
        mov     al, '0'
        adc     al, 0
        stosb
        mov     al, ' '
        stosb
        pop     ax
        call    hex4
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      ends
        mov     bx, ax
        mov     cx, di
        sub     cx, buf
        mov     dx, buf
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
        jmp     ends

; M, Z: its task's number, a mouse event handler, then computing
m_m:    call    mine_
        xor     ax, ax
        int     33h
        mov     ax, 0Ch
        mov     cx, 7Fh
        push    cs
        pop     es
        mov     dx, hnd
        int     33h
        sti
        cmp     byte [mode], 'R'
        je      .r
.s:     inc     word [cnt]
        jmp     .s
.r:     cmp     word [hits], 0          ; R: computing until its handler has
        je      .r                      ;  ended its task, then a key read
.k:     xor     ah, ah
        int     16h
        jmp     .k
hnd:    pusha                           ; (called by the driver, far)
        push    ds
        push    es
        push    cs
        pop     ds
        call    mine_.ask               ; (in its own task only: the front
        cmp     ah, [mine]              ;  task's handler runs in whichever
        jne     .x                      ;  task the mouse finds)
        inc     word [hits]
        cmp     byte [mode], 'M'
        jne     .z
        mov     ah, 08h
        int     21h
        jmp     short .x
.z:     mov     bl, [mine]
        mov     ax, 0F000h + MT_KILL
        int     21h
.x:     pop     es
        pop     ds
        popa
        retf

; T: its task's number, INT 1Ch hooked, then computing
m_t:    call    mine_
        mov     ax, 251Ch
        mov     dx, h1c
        int     21h
        sti
.s:     inc     word [cnt]
        jmp     .s
h1c:    push    ax
        push    bx
        push    ds
        push    cs
        pop     ds
        inc     word [hits]
        cmp     word [hits], 5
        jne     .x
        mov     bl, [mine]
        mov     ax, 0F000h + MT_KILL
        int     21h
.x:     pop     ds
        pop     bx
        pop     ax
        iret

; its task's number (AH=12h's AH) -> [mine]
mine_:  call    .ask
        mov     [mine], ah
        ret
.ask:   mov     ax, 0F000h + MT_LIST
        push    cs
        pop     es
        mov     di, recs
        xor     cx, cx
        int     21h
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

n       dw      0
fh      dw      0
fpos    dw      0
cnt     dw      0
hits    dw      0
mine    db      0
mode    db      0
s_bang  db      '!'
s_prog  db      'MTKILL.COM', 0
ks      times   64 db 'k'
line    db      40, 0
        times   41 db 0
pb      dw      0, tail, 0, 5Ch, 0, 6Ch, 0      ; (EXEC's: env, tail, FCBs)
tail    times   128 db 0
recs    times   MT_REC db 0
fname   times   80 db 0
buf     times   16 db 0
        times   256 db 0
stk_top:
the_end:
