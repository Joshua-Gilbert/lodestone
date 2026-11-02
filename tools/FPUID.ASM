; =====================================================================
;  FPUID.COM - which 80287 is fitted, and can it store?      (Lodestone)
;  Build: nasm -f bin -o FPUID.COM FPUID.ASM
;
;  For any 286 machine under MS-DOS or Lodestone; written for the
;  GRiDCase 1520 after a 287XL there (2026-11) did single-word stores
;  (FNSTCW, FNSTSW) but hung the machine, BUSY held, on every multi-word
;  one: FSTP qword, FNSTENV, FNSAVE.  The original 80287 works in the
;  same socket.
;
;  It says:
;    - what INT 11h reports (bit 1: the BIOS found a coprocessor);
;    - whether a coprocessor answers FNINIT (its control word, 037Fh);
;    - which kind: after FNINIT an 80287 treats +inf and -inf as equal
;      (projective infinity), a 287XL or any 387-class chip orders them;
;    - one single-word store (FNSTCW) and three multi-word ones (FSTP
;      qword, 8 bytes; FNSTENV, 14; FNSAVE, 94), each checked.
;
;  Each store runs under a watchdog on the timer (INT 08h): if it hasn't
;  finished in 4 ticks (about 0.2 s; it takes microseconds) the watchdog
;  clears the coprocessor's BUSY latch (OUT F0h) and resets it (OUT F1h),
;  which lets the 286 go on, and the store is reported as hanging.  So a
;  chip with the fault is named, not left to lock the machine.  (Should
;  the machine lock up anyway, that is the answer too.)  Each test's name
;  is printed before it runs.
;
;  Exit code: 0 all stores work; 1 no coprocessor; 2 a store hangs;
;  3 a store wrote the wrong data; 4 not a 286 or later.
;  With -dFPTEST the multi-word stores are replaced by a wait for the
;  watchdog (the emulator's coprocessor never hangs): the hang path.
; =====================================================================
cpu 286
org 100h

TICKS   equ 4

start:  mov     dx, s_title
        call    puts
        ; ---- a 286 or later (on an 8086 SMSW would be POP CS) -------
        pushf
        pop     ax
        and     ax, 0FFFh
        push    ax
        popf
        pushf
        pop     ax
        and     ax, 0F000h
        cmp     ax, 0F000h
        jne     .is286
        mov     dx, s_8086
        call    puts
        mov     ax, 4C04h
        int     21h
.is286:
        ; ---- what the BIOS says --------------------------------------
        int     11h
        mov     dx, s_bios_yes
        test    al, 2
        jnz     .b
        mov     dx, s_bios_no
.b:     call    puts
        smsw    ax
        test    al, 4                   ; EM: coprocessor instructions trap
        jz      .probe
        mov     dx, s_em
        call    puts
        mov     ax, 4C01h
        int     21h

        ; ---- does one answer? -----------------------------------------
.probe: fninit
        mov     word [cw], 5A5Ah
        fnstcw  [cw]                    ; (no WAIT: an empty socket can't hang it)
        mov     cx, 400                 ; (as the BIOS's POST: time to store)
.d:     loop    .d
        mov     ax, [cw]
        and     ax, 1F3Fh
        cmp     ax, 033Fh
        je      .there
        mov     dx, s_none
        call    puts
        mov     ax, 4C01h
        int     21h
.there:
        ; ---- which kind ------------------------------------------------
        fld1
        fldz
        fdivp   st1, st0                ; +inf (zero-divide is masked)
        fld     st0
        fchs                            ; -inf
        fcompp
        fnstsw  [sw]                    ; (single-word stores are fine)
        mov     cx, 400
.d2:    loop    .d2
        fninit
        mov     dx, s_287
        test    byte [sw+1], 40h        ; C3: equal
        jnz     .k
        mov     dx, s_xl
.k:     call    puts

        ; ---- the watchdog on INT 08h ---------------------------------
        mov     ax, 3508h
        int     21h
        mov     [old8], bx
        mov     [old8+2], es
        mov     dx, t8
        mov     ax, 2508h
        int     21h
        sti

        ; ---- the stores --------------------------------------------
        mov     dx, s_t1
        call    puts
        call    arm
        fnstcw  [buf]
        fwait
        call    disarm
        mov     si, x_cw
        mov     cx, 2
        call    result

        mov     dx, s_t2
        call    puts
        call    arm
        fld1
%ifdef FPTEST
        call    hang
%else
        fstp    qword [buf]
        fwait
%endif
        call    disarm
        mov     si, x_one
        mov     cx, 8
        call    result

        mov     dx, s_t3
        call    puts
        call    arm
%ifdef FPTEST
        call    hang
%else
        fnstenv [buf]
        fwait
%endif
        call    disarm
        call    env

        mov     dx, s_t4
        call    puts
        call    arm
%ifdef FPTEST
        call    hang
%else
        fnsave  [buf]
        fwait
%endif
        call    disarm
        call    env

        ; ---- put INT 08h back; the verdict -----------------------------
        push    ds
        lds     dx, [old8]
        mov     ax, 2508h
        int     21h
        pop     ds
        fninit
        mov     al, [worst]
        mov     dx, s_ok
        or      al, al
        jz      .v
        mov     dx, s_vhang
        cmp     al, 2
        je      .v
        mov     dx, s_vbad
.v:     call    puts
        mov     ah, 4Ch
        int     21h

; ---------------------------------------------------------------------
; arm: a fresh coprocessor, the buffer filled with 5Ah, the watchdog on
arm:    fninit
        push    ax
        push    cx
        push    di
        push    ds
        pop     es
        mov     di, buf
        mov     cx, 96
        mov     al, 5Ah
        cld
        rep     stosb
        pop     di
        pop     cx
        pop     ax
        cli
        mov     byte [n], 0
        mov     byte [fired], 0
        mov     byte [armed], 1
        sti
        ret

disarm: mov     byte [armed], 0
        ret

%ifdef FPTEST
hang:   cmp     byte [fired], 0         ; the store that never ends
        je      hang
        ret
%endif

; result: the watchdog fired -> "HANGS"; else the first CX bytes of
; buf against SI -> "works" or "wrong data"
result: cmp     byte [fired], 0
        je      .ran
        mov     dx, s_hangs
        mov     al, 2
        jmp     .r
.ran:   mov     di, buf
        push    ds
        pop     es
        cld
        repe    cmpsb
        mov     dx, s_works
        mov     al, 0
        je      .r
        mov     dx, s_wrong
        mov     al, 3
.r:     call    puts
        cmp     al, 2                   ; worst: 2 (hang) over 3 over 0
        je      .w2
        cmp     byte [worst], 0
        jne     .x
        mov     [worst], al
.x:     ret
.w2:    mov     [worst], al
        ret

; env: an environment's control word (offset 0) and tag word (offset 4)
; checked; not its status word, whose C0-C3 an 80287's FNINIT leaves
env:    mov     ax, [buf+4]
        mov     [buf+2], ax
        mov     si, x_env
        mov     cx, 4
        jmp     result

; the watchdog: the BIOS's tick first, then, armed and TICKS gone,
; release the 286 and reset the coprocessor
t8:     pushf
        call    far [cs:old8]
        cmp     byte [cs:armed], 0
        je      .x
        inc     byte [cs:n]
        cmp     byte [cs:n], TICKS
        jb      .x
        mov     byte [cs:armed], 0
        mov     byte [cs:fired], 1
        push    ax
        xor     al, al
        out     0F0h, al                ; clear BUSY: the 286 goes on
        out     0F1h, al                ; reset the coprocessor
        pop     ax
.x:     iret

puts:   push    ax
        mov     ah, 09h
        int     21h
        pop     ax
        ret

; ---------------------------------------------------------------------
s_title db 'FPUID 1.0 - which 80287, and can it store?', 13, 10, '$'
s_8086  db 'Needs a 286 or later.', 13, 10, '$'
s_bios_yes db 'BIOS (INT 11h):  coprocessor present', 13, 10, '$'
s_bios_no  db 'BIOS (INT 11h):  no coprocessor', 13, 10, '$'
s_em    db 'The EM bit is set: coprocessor instructions are emulated here.', 13, 10, '$'
s_none  db 'Coprocessor:     none answered FNINIT', 13, 10, '$'
s_287   db 'Coprocessor:     80287 (infinities equal: projective)', 13, 10, '$'
s_xl    db 'Coprocessor:     287XL or other 387-class (infinities ordered)', 13, 10, '$'
s_t1    db '  FNSTCW         (2 bytes) ... $'
s_t2    db '  FSTP qword     (8 bytes) ... $'
s_t3    db '  FNSTENV       (14 bytes) ... $'
s_t4    db '  FNSAVE        (94 bytes) ... $'
s_works db 'works', 13, 10, '$'
s_wrong db 'WRONG DATA', 13, 10, '$'
s_hangs db 'HANGS (BUSY held; FPUID reset the coprocessor)', 13, 10, '$'
s_ok    db 'Result: every store completed. This coprocessor is fine.', 13, 10, '$'
s_vhang db 'Result: multi-word stores hang. Programs that store a', 13, 10
        db 'result (a calculator, a spreadsheet) or save its state', 13, 10
        db '(a multitasker) will lock up with this chip.', 13, 10, '$'
s_vbad  db 'Result: a store wrote the wrong data.', 13, 10, '$'

x_cw    dw 037Fh                        ; FNINIT's control word
x_one   dq 1.0
x_env   dw 037Fh, 0FFFFh                ; FNINIT's control word and tags
old8    dd 0
cw      dw 0
sw      dw 0
n       db 0
fired   db 0
armed   db 0
worst   db 0
buf     times 96 db 0
