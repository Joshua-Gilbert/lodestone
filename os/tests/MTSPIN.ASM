; MTSPIN.COM - for test_mt.py: a task that computes, for preemption.
;   MTSPIN T CNTFILE [D | W DATAFILE | C | S | F | R | H | T | O]
; Counts, as fast as it can, for T ticks of the BIOS's clock (40:6Ch),
; then writes the count (8 hex digits) to CNTFILE.  It prints nothing.
;   D  an INT 21h call (AH=2Ch) on each count
;   W  a 64-byte record written to DATAFILE on each (so its size is the
;      count times 64)
;   C  AH=2Ch on each count with interrupts off (CLI before the INT 21h)
;   S  counts with its stack outside its own memory (B800:7F00, past the
;      text screen's pages in use)
;   F  counts with its stack in a block it took (AH=48h) and gave back:
;      free memory, nobody's
;   R  INT 62h on each count (MTHOOK S's service: 2 ticks, in its code)
;   H  hooks INT 1Ch (AH=25h) meanwhile: its handler does STI and, with
;      InDOS 0, AH=2Ch, then chains (so INT 21h's way out with IRQ 0 in
;      service)
;   T  hooks INT 08h meanwhile, writing the vector itself (not AH=25h):
;      its handler does STI and chains with PUSHF / CALL FAR
;   O  no counting: the count is what INT 21h F0h AL=1 says for A: (files
;      open there)
; nasm -f bin -o MTSPIN.COM MTSPIN.ASM
cpu 286
org 100h
        mov     sp, stk_top
        mov     ah, 4Ah                 ; (only its own memory)
        mov     bx, (stk_top - $$ + 100h + 15) / 16
        int     21h
        mov     si, 81h
        call    blanks
        xor     bx, bx                  ; T
.d:     lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .de
        cbw
        imul    bx, bx, 10
        add     bx, ax
        jmp     .d
.de:    mov     [tks], bx
        call    blanks
        mov     [cnf], si               ; CNTFILE
        call    word_
        call    blanks
        lodsb
        and     al, 0DFh
        mov     [mode], al
        cmp     al, 'O'
        jne     .w0
        mov     ax, 0F001h
        xor     dl, dl
        int     21h
        mov     [cnt], cx
        jmp     .c
.w0:    cmp     al, 'W'
        jne     .h0
        call    blanks
        mov     dx, si                  ; DATAFILE
        call    word_
        mov     ah, 3Ch
        xor     cx, cx
        int     21h
        jc      .x
        mov     [dh_], ax
.h0:    cmp     byte [mode], 'H'
        jne     .t0
        mov     ah, 34h                 ; (InDOS)
        int     21h
        mov     [indp], bx
        mov     [indp + 2], es
        mov     ax, 351Ch
        int     21h
        mov     [o1c], bx
        mov     [o1c + 2], es
        mov     ax, 251Ch
        mov     dx, h1c
        int     21h
.t0:    cmp     byte [mode], 'T'
        jne     .go
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
.go:    push    40h
        pop     es
        mov     ax, [es:6Ch]
        mov     [t0], ax
        mov     dx, 0B800h              ; (S: the stack at B800:7F00)
        mov     cx, 7F00h
        cmp     byte [mode], 'S'
        je      .ss
        cmp     byte [mode], 'F'
        jne     .l
        mov     ah, 48h                 ; (F: in a block of 256 bytes taken,
        mov     bx, 16                  ;  then given back)
        int     21h
        jc      .x
        mov     dx, ax
        push    es
        mov     es, ax
        mov     ah, 49h
        int     21h
        pop     es
        mov     cx, 100h
.ss:    cli
        mov     [ssv], ss
        mov     [spv], sp
        mov     ss, dx
        mov     sp, cx
        sti
.l:     add     word [cnt], 1
        adc     word [cnt + 2], 0
        cmp     byte [mode], 'D'
        jne     .i
        mov     ah, 2Ch
        int     21h
.i:     cmp     byte [mode], 'R'
        jne     .i2
        int     62h
.i2:    cmp     byte [mode], 'C'
        jne     .w
        mov     ah, 2Ch
        cli
        int     21h
        sti
.w:     cmp     byte [mode], 'W'
        jne     .t
        mov     ah, 40h
        mov     bx, [dh_]
        mov     cx, 64
        mov     dx, rec
        int     21h
.t:     mov     ax, [es:6Ch]
        sub     ax, [t0]
        cmp     ax, [tks]
        jb      .l
        cmp     word [ssv], 0
        je      .ue
        cli
        mov     ss, [ssv]
        mov     sp, [spv]
        sti
.ue:    cmp     byte [mode], 'T'
        jne     .uh
        xor     ax, ax
        mov     es, ax
        cli
        mov     ax, [o08]
        mov     [es:8 * 4], ax
        mov     ax, [o08 + 2]
        mov     [es:8 * 4 + 2], ax
        sti
.uh:    cmp     byte [mode], 'H'
        jne     .uw
        push    ds
        mov     ax, 251Ch
        lds     dx, [o1c]
        int     21h
        pop     ds
.uw:    cmp     byte [mode], 'W'
        jne     .c
        mov     ah, 3Eh
        mov     bx, [dh_]
        int     21h
.c:     mov     di, out_                ; the count, in hex
        mov     ax, [cnt + 2]
        call    hex4
        mov     ax, [cnt]
        call    hex4
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, [cnf]
        int     21h
        jc      .x
        mov     bx, ax
        mov     ah, 40h
        mov     cx, 8
        mov     dx, out_
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

h1c:    sti                             ; INT 1Ch (H)
        push    ds
        push    bx
        push    ax
        push    cx
        push    dx
        lds     bx, [cs:indp]
        cmp     byte [bx], 0
        jne     .s
        mov     ah, 2Ch
        int     21h
.s:     pop     dx
        pop     cx
        pop     ax
        pop     bx
        pop     ds
        jmp     far [cs:o1c]
h08:    sti                             ; INT 08h (T)
        pushf
        call    far [cs:o08]
        iret

blanks: lodsb
        cmp     al, ' '
        je      blanks
        dec     si
        ret
word_:  lodsb                           ; to a blank or the end: NUL there
        cmp     al, ' '
        ja      word_
        mov     byte [si - 1], 0
        cmp     al, 0Dh                 ; (at the end: stay on that NUL, so
        jne     .x                      ;  nothing more is read)
        dec     si
.x:     ret
hex4:   push    ds
        pop     es
        mov     cx, 4
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
        push    40h
        pop     es
        ret

tks     dw      0
t0      dw      0
cnt     dw      0, 0
cnf     dw      0
dh_     dw      0
ssv     dw      0
spv     dw      0
indp    dd      0
o1c     dd      0
o08     dd      0
mode    db      0
out_    times 8 db 0
rec     db      '0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDE', 0Ah
        times   256 db 0
stk_top:
