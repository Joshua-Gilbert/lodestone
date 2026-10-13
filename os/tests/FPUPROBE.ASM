; FPUPROBE.COM - what the coprocessor answers after FNINIT, raw.
;
;   FPUPROBE      prints one line, e.g.
;     INT 11h 4463  MSW FFF0  after FNINIT: control 037F  status 4100
;       C0-C3 0101  infinities equal (80287)
;
; Written for the 1520's 80287 (found 2026-10-13): POST's own probe masks
; the condition codes C0-C3, which a real 80287's FNINIT leaves as they
; were; fpu_detect wanted the whole status word 0.  Nothing runs on the
; coprocessor when the 286's EM bit is set (it would trap to INT 7); with
; EM clear and no chip the 286 reads the idle bus, as every probe does.
; Exit code 0 a coprocessor answered, 1 none (or EM set).
cpu 286
org 100h

        int     11h
        mov     si, s_eq
        call    phex
        smsw    ax
        push    ax
        mov     si, s_msw
        call    phex
        pop     ax
        test    al, 4                   ; EM: coprocessor instructions trap
        jz      .go
        mov     si, s_em
        call    puts
        jmp     .none
.go:    fninit
        fnstsw  ax                      ; (no WAIT: an empty socket can't hang it)
        mov     [sw], ax
        mov     word [cw], 5A5Ah
        fnstcw  [cw]
        mov     cx, 400                 ; (as POST: give it time to store)
.d:     loop    .d
        mov     ax, [cw]
        mov     si, s_cw
        call    phex
        mov     ax, [sw]
        mov     si, s_sw
        call    phex
        mov     si, s_cc                ; C0 C1 C2 C3 as bits
        call    puts
        mov     bx, [sw]
        mov     al, bh
        and     al, 1                   ; C0: bit 8
        call    pbit
        mov     al, bh
        shr     al, 1                   ; C1: bit 9
        call    pbit
        mov     al, bh
        shr     al, 2                   ; C2: bit 10
        call    pbit
        mov     al, bh
        shr     al, 6                   ; C3: bit 14
        call    pbit
        mov     ax, [cw]
        and     ax, 1F3Fh               ; POST's test: 033Fh after FNINIT
        cmp     ax, 033Fh
        jne     .nochip
        fld1                            ; 80287 or a 387-class chip
        fldz
        fdivp   st1, st0
        fld     st0
        fchs
        fcompp
        fstsw   ax
        fninit
        mov     si, s_proj
        test    ah, 40h
        jnz     .k
        mov     si, s_aff
.k:     call    puts
        mov     ax, 4C00h
        int     21h
.nochip:
        mov     si, s_none
        call    puts
.none:  mov     ax, 4C01h
        int     21h

; "label" then AX in hex
phex:   push    ax
        call    puts
        pop     bx
        mov     cx, 4
.h:     rol     bx, 4
        mov     al, bl
        and     al, 15
        add     al, '0'
        cmp     al, '9'
        jbe     .o
        add     al, 7
.o:     call    putc
        loop    .h
        ret
pbit:   and     al, 1
        add     al, '0'
putc:   mov     dl, al
        mov     ah, 2
        int     21h
        ret
puts:   lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     puts
.x:     ret

s_eq    db 'INT 11h ', 0
s_msw   db '  MSW ', 0
s_em    db '  EM set: no coprocessor use', 13, 10, 0
s_cw    db '  after FNINIT: control ', 0
s_sw    db '  status ', 0
s_cc    db 13, 10, '  C0-C3 ', 0
s_proj  db '  infinities equal (80287)', 13, 10, 0
s_aff   db '  infinities ordered (287XL or 387-class)', 13, 10, 0
s_none  db '  no coprocessor answered', 13, 10, 0
sw      dw 0
cw      dw 0
