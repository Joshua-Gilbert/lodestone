; =====================================================================
;  CALC.INC - the calculator's engine: an expression, a number, its text.
;  CALC.COM (the command prompt) and CALC.RUN (the window over the
;  Executive) are the two hosts.
;
;  calc_init  which coprocessor (FPU.INC) -> c_fpu: 0 none, 1 an 80287,
;             2 a 287XL.  Built with -DCALC_287, a 287XL is used as an
;             80287 (the tests run the 80287's code paths that way).
;  calc_eval  SI = expression (ASCIIZ) -> CF clear: the answer in c_ans;
;             CF: AX = error (calc_err gives its text).  c_deg = 1:
;             sin, cos, tan and atan in degrees.
;  calc_fmt   DI = buffer -> the answer as text, DI at its NUL; the
;             coprocessor is left as FNINIT leaves it
;  calc_err   AX = error -> SI = its text
;  The host supplies calc_var: SI = a name (upper case) -> SI = its value
;  as text, or CF and AL = the error (E_NAME none, E_LVAL too long).
;  DS = ES = SS; each routine may change any register but the segment
;  registers.
;
;  The grammar, by recursive descent:
;    expr  = term  { (+ | -) term }
;    term  = unary { (* | / | \ | %) unary }       \ whole part, % remainder
;    unary = (+ | -) unary | power                 -2^2 = -4
;    power = prim [ ^ unary ]                       2^3^2 = 2^9, 2^-1
;    prim  = number | name | name(expr) | (expr)
;  An expression that starts with + * / \ % ^ goes on from the answer.
;
;  With a coprocessor, the number being worked on is in ST0 and the left
;  side of each operator waits in c_vs (10-byte slots), so the
;  coprocessor's own stack never holds more than four.  Every exception
;  stays masked (there is no IRQ 13 handler): the flags are read once at
;  the end.  On the 80287, FYL2X, F2XM1, FPTAN and FPATAN outside their
;  ranges give garbage without a flag, so they are kept in range on both
;  chips; the 287XL's FSIN, FCOS and full-range FPTAN and FPATAN are used
;  when it is there.  Without a coprocessor: whole numbers, 32 bits
;  signed, in c_iacc.
; =====================================================================

E_SYN   equ 1
E_DIV   equ 2
E_BIG   equ 3
E_NAN   equ 4
E_287   equ 5
E_DEEP  equ 6
E_NAME  equ 7
E_LNAME equ 8
E_LVAL  equ 9
VS_N    equ 20                         ; operators waiting at once
DEPTH   equ 24                          ; brackets inside each other

calc_init:
        call    fpu_detect
%ifdef CALC_287
        or      al, al
        jz      .s
        mov     al, 1
.s:
%endif
        mov     [c_fpu], al
        ret

calc_err:
        mov     si, c_msgs
c_nth:  mov     cx, ax                  ; (SI = ASCIIZ texts: the AXth)
.n:     dec     cx
        jz      .x
.s:     lodsb
        or      al, al
        jnz     .s
        jmp     .n
.x:     ret

; SI -> AL = the next character that isn't a space, SI at it
c_skip: lodsb
        cmp     al, ' '
        je      c_skip
        cmp     al, 9
        je      c_skip
        dec     si
        ret

calc_eval:
        mov     [c_sp], sp
        xor     ax, ax
        mov     [c_vsp], ax
        mov     [c_lvl], al
        mov     [c_lead], al
        cmp     [c_fpu], al
        je      .i
        fninit
.i:     call    c_skip
        mov     di, c_leadops
        mov     cx, 6
        repne   scasb
        jne     .e
        inc     byte [c_lead]
.e:     call    c_expr
        call    c_skip
        or      al, al
        jnz     c_esyn
        cmp     byte [c_fpu], 0
        je      .int
        call    c_check
        fstp    tword [c_ans]
        fwait
        clc
        ret
.int:   mov     ax, [c_iacc]
        mov     dx, [c_iacc+2]
        mov     [c_ans], ax
        mov     [c_ans+2], dx
        clc
        ret

; ST0 and the flags so far: an error, or a number to go on with.  The
; flags first (invalid: a negative root, 0/0 ...; divide by zero; too
; big), then FXAM for a NaN or an infinity that came without one
c_check:
        fstsw   ax
        test    al, 1
        jnz     c_enan
        test    al, 4
        jnz     c_ediv
        test    al, 8
        jnz     c_ebig
        fxam
        fstsw   ax
        test    ah, 1                   ; C0: not a number, or infinite
        jz      .x
        test    ah, 4                   ; C2: infinite
        jnz     c_ebig
        jmp     short c_enan
.x:     ret

; the errors: back to calc_eval's caller from any depth
c_esyn: mov     al, E_SYN
        jmp     short c_fail
c_ediv: mov     al, E_DIV
        jmp     short c_fail
c_ebig: mov     al, E_BIG
        jmp     short c_fail
c_enan: mov     al, E_NAN
        jmp     short c_fail
c_e287: mov     al, E_287
        jmp     short c_fail
c_edeep: mov    al, E_DEEP
        jmp     short c_fail
c_elnam: mov    al, E_LNAME
c_fail: mov     sp, [c_sp]
        cbw
        cmp     byte [c_fpu], 0
        je      .x
        fninit
.x:     stc
        ret

c_expr: inc     byte [c_lvl]
        cmp     byte [c_lvl], DEPTH
        ja      c_edeep
        call    c_term
.l:     call    c_skip
        cmp     al, '+'
        je      .op
        cmp     al, '-'
        jne     .x
.op:    inc     si
        push    ax
        call    c_push
        call    c_term
        pop     ax
        call    c_bin
        jmp     .l
.x:     dec     byte [c_lvl]
        ret

c_term: call    c_unary
.l:     call    c_skip
        mov     di, c_mulops
        mov     cx, 4
        repne   scasb
        jne     .x
        inc     si
        push    ax
        call    c_push
        call    c_unary
        pop     ax
        call    c_bin
        jmp     .l
.x:     ret

c_unary:
        cmp     byte [c_lead], 0        ; (+5 after an answer: the answer + 5)
        jne     c_power
        call    c_skip
        cmp     al, '+'
        je      .p
        cmp     al, '-'
        jne     c_power
        inc     si
        call    c_unary
        jmp     c_neg
.p:     inc     si
        jmp     c_unary

c_power:
        call    c_prim
        call    c_skip
        cmp     al, '^'
        jne     .x
        inc     si
        call    c_push
        call    c_unary
        mov     al, '^'
        jmp     c_bin
.x:     ret

c_prim: call    c_skip
        cmp     byte [c_lead], 0
        je      .n
        dec     byte [c_lead]
        jmp     c_ldans
.n:     cmp     al, '('
        jne     .num
        inc     si
        call    c_expr
        jmp     c_close
.num:   cmp     al, '.'
        je      .dig
        cmp     al, '0'
        jb      .nm
        cmp     al, '9'
        ja      .nm
.dig:   jmp     c_num
.nm:    call    c_alpha
        jnc     .name
        jmp     c_esyn
.name:  call    c_rdname
        jnc     .nm1
        jmp     c_elnam
.nm1:   push    si                      ; (the parse goes on from here)
        mov     bx, c_names
.f:     mov     si, bx
        mov     di, c_nm
.c:     lodsb
        scasb
        jne     .nx
        or      al, al
        jnz     .c
        lodsb                           ; 0 a constant, 1 a function
        mov     dx, [si]
        pop     si
        or      al, al
        jz      .go
        call    c_skip
        cmp     al, '('
        jne     .syn
        inc     si
        push    dx
        call    c_expr
        call    c_close
        pop     dx
        cmp     byte [c_fpu], 0
        jne     .go
        cmp     dx, f_abs               ; (without a coprocessor, only ABS)
        je      .go
        jmp     c_e287
.go:    jmp     dx
.syn:   jmp     c_esyn
.nx:    mov     si, bx                  ; the next name in the table
.s:     lodsb
        or      al, al
        jnz     .s
        add     si, 3
        mov     bx, si
        cmp     byte [bx], 0
        jne     .f
        mov     si, c_nm                ; not ours: the host's (a variable)
        call    calc_var
        jnc     .val
        jmp     c_fail                  ; (AL: no such name, or too long)
.val:   call    c_skip
        mov     bl, 0
        cmp     al, '-'
        jne     .v1
        inc     si
        inc     bx
.v1:    push    bx
        call    c_num
        call    c_skip
        or      al, al
        jnz     .syn
        pop     bx
        pop     si
        or      bl, bl
        jz      .vx
        jmp     c_neg
.vx:    ret

; a closing bracket, or a syntax error
c_close:
        call    c_skip
        cmp     al, ')'
        jne     .e
        inc     si
        ret
.e:     jmp     c_esyn

; AL: CF clear for a letter or _
c_alpha:
        cmp     al, '_'
        je      .y
        push    ax
        and     al, 0DFh
        sub     al, 'A'
        cmp     al, 26
        pop     ax
        cmc
.y:     ret

; SI at a letter -> c_nm (upper case), SI after the name; CF: longer than
; 15 (c_nm has its first 15).  Called before calc_eval too: no c_fail
c_rdname:
        mov     di, c_nm
        mov     cx, 16
.l:     lodsb
        cmp     al, '0'
        jb      .a
        cmp     al, '9'
        jbe     .k
.a:     call    c_alpha
        jc      .x
        cmp     al, 'a'
        jb      .k
        sub     al, 20h
.k:     dec     cx
        jz      .long
        stosb
        jmp     .l
.long:  clc                             ; (CF after the CMC below)
.x:     dec     si
        mov     byte [di], 0
        cmc                             ; (at the end of a name c_alpha set CF)
        ret

; the number being worked on onto c_vs (the left side of an operator)
c_push: mov     bx, [c_vsp]
        cmp     bx, VS_N * 10
        jb      .ok
        jmp     c_edeep
.ok:    add     word [c_vsp], 10
        add     bx, c_vs
        cmp     byte [c_fpu], 0
        je      .i
        fstp    tword [bx]
        ret
.i:     mov     ax, [c_iacc]
        mov     [bx], ax
        mov     ax, [c_iacc+2]
        mov     [bx+2], ax
        ret

; AL = operator: the left side from c_vs, the right is the number being
; worked on.  Coprocessor: ST0 = left, ST1 = right -> ST0.  Whole
; numbers: CX:BX = left, DX:AX = right -> DX:AX.
c_bin:  push    si
        mov     si, c_ops
.f:     cmp     [si], al
        je      .h
        add     si, 5
        jmp     .f
.h:     mov     ax, [si+1]
        cmp     byte [c_fpu], 0
        jne     .x
        mov     ax, [si+3]
.x:     mov     [c_h], ax
        sub     word [c_vsp], 10
        mov     bx, [c_vsp]
        add     bx, c_vs
        cmp     byte [c_fpu], 0
        je      .i
        fld     tword [bx]
        call    [c_h]
        pop     si
        ret
.i:     mov     cx, [bx+2]
        mov     bx, [bx]
        mov     ax, [c_iacc]
        mov     dx, [c_iacc+2]
        call    [c_h]
        mov     [c_iacc], ax
        mov     [c_iacc+2], dx
        pop     si
        ret

c_ldans:
        cmp     byte [c_fpu], 0
        je      .i
        fld     tword [c_ans]
        ret
.i:     mov     ax, [c_ans]
        mov     [c_iacc], ax
        mov     ax, [c_ans+2]
        mov     [c_iacc+2], ax
        ret

k_pi:   cmp     byte [c_fpu], 0
        jne     .f
        jmp     c_e287
.f:     fldpi
        ret

c_neg:  cmp     byte [c_fpu], 0
        je      .i
        fchs
        ret
.i:     mov     ax, [c_iacc]
        mov     dx, [c_iacc+2]
        cmp     dx, 8000h               ; -(-2^31) doesn't fit
        jne     .n
        or      ax, ax
        jnz     .n
        jmp     c_ebig
.n:     call    i_neg
        mov     [c_iacc], ax
        mov     [c_iacc+2], dx
        ret

; ---- numbers --------------------------------------------------------
; SI at a digit or '.': the number -> the number being worked on
c_num:  cmp     byte [c_fpu], 0
        je      .int
        fldz
        xor     bx, bx                  ; its power of ten
        xor     dx, dx                  ; DL: past the point, DH: digits
.l:     lodsb
        cmp     al, '.'
        jne     .d
        or      dl, dl
        jnz     .syn
        inc     dx
        jmp     .l
.d:     sub     al, '0'
        cmp     al, 9
        ja      .e
        inc     dh
        cbw
        mov     [c_w], ax
        fimul   word [c_k10]
        fiadd   word [c_w]
        mov     al, dl
        cbw
        sub     bx, ax
        jmp     .l
.e:     dec     si
        or      dh, dh
        jz      .syn
        mov     al, [si]
        or      al, 20h
        cmp     al, 'e'
        jne     .sc
        inc     si
        call    c_int
        jc      .syn
        add     bx, ax
.sc:    mov     ax, bx
        fild    word [c_k10]
        jmp     c_ipow
.syn:   jmp     c_esyn
.int:   xor     ax, ax                  ; whole numbers: DX:AX
        xor     dx, dx
        xor     di, di
.il:    mov     bl, [si]
        cmp     bl, '.'
        je      .287
        sub     bl, '0'
        cmp     bl, 9
        ja      .ie
        inc     si
        inc     di
        push    bx
        mov     bx, 10                  ; DX:AX * 10 + the digit
        mov     cx, ax
        mov     ax, dx
        mul     bx
        jc      .big
        xchg    ax, cx
        mul     bx
        add     dx, cx
        jc      .big
        pop     bx
        xor     bh, bh
        add     ax, bx
        adc     dx, 0
        js      .big
        jmp     .il
.ie:    or      di, di
        jz      .syn
        mov     bl, [si]
        or      bl, 20h
        cmp     bl, 'e'
        je      .287
        mov     [c_iacc], ax
        mov     [c_iacc+2], dx
        ret
.287:   jmp     c_e287
.big:   jmp     c_ebig

; SI -> AX = a whole number with an optional sign (at most 9999: that is
; out of range anyway), CF if there were no digits
c_int:  xor     dx, dx                  ; DL: negative, DH: digits
        mov     al, [si]
        cmp     al, '+'
        je      .s
        cmp     al, '-'
        jne     .n
        inc     dx
.s:     inc     si
.n:     xor     cx, cx
.l:     lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .x
        inc     dh
        cmp     cx, 999
        ja      .l
        cbw
        imul    cx, cx, 10
        add     cx, ax
        jmp     .l
.x:     dec     si
        mov     ax, cx
        test    dl, 1
        jz      .p
        neg     ax
.p:     cmp     dh, 1                   ; CF: none
        ret

; ---- the coprocessor's operators -------------------------------------
f_add:  fadd    st0, st1
        jmp     short f_drop
f_sub:  fsub    st0, st1
        jmp     short f_drop
f_mul:  fmul    st0, st1
        jmp     short f_drop
f_div:  fdiv    st0, st1
f_drop: fstp    st1
        ret
f_mod:  call    f_rem                   ; the remainder, with the left's sign
        jmp     f_drop
f_quo:  fld     st1                     ; R L R
        fld     st1                     ; L R L R
        call    f_rem                   ; rem R L R
        fstp    st1                     ; rem L R
        fsubp   st1, st0                ; L-rem R
        fdiv    st0, st1
        frndint
        jmp     f_drop

; ST0 mod ST1 (a zero ST1: divide by zero; FPREM only on a number: with
; a NaN or an infinity it may never finish)
f_rem:  call    c_check
        fxch
        ftst
        fstsw   ax
        fxch
        sahf
        jne     .l
        jmp     c_ediv
.l:     fprem
        fstsw   ax
        test    ah, 4                   ; C2: not finished
        jnz     .l
        ret

; ST0 = x, ST1 = y -> x^y: multiplied out for a whole y (exact, and a
; negative x is fine), else 2^(y log2 x)
f_pow:  fld     st1
        frndint
        fcomp   st2
        fstsw   ax
        sahf
        jne     .real
        fld     st1
        fabs
        ficomp  word [c_k32k]
        fstsw   ax
        sahf
        ja      .real
        fld     st1
        fistp   word [c_w]
        fwait
        fld1                            ; 1 x y
        fxch                            ; x 1 y
        mov     ax, [c_w]
        call    c_ipow
        jmp     f_drop
.real:  ftst
        fstsw   ax
        sahf
        jb      .nan                    ; (a fraction of a negative)
        jne     .pos
        fxch                            ; 0^y: 0, or for y < 0 1/0
        ftst
        fstsw   ax
        fxch
        sahf
        jb      .div
        jmp     f_drop
.pos:   fyl2x                           ; y log2 x
        jmp     c_exp2
.nan:   jmp     c_enan
.div:   jmp     c_ediv

; ST0 = base, ST1 = v, AX = n -> ST0 = v * base^n (n a 16-bit integer)
c_ipow: fld1                            ; product, base, v
        mov     cx, ax
        or      cx, cx
        jns     .l
        neg     cx
.l:     shr     cx, 1
        jnc     .n
        fmul    st0, st1
.n:     jz      .d
        fxch
        fmul    st0, st0
        fxch
        jmp     .l
.d:     fstp    st1                     ; product, v
        or      ax, ax
        js      .neg
        fmulp   st1, st0
        ret
.neg:   fdivp   st1, st0                ; v / product
        ret

; ST0 = z -> 2^z.  F2XM1 only ever sees 0..1/2 and FSCALE a whole number
; under 2^15, as the 80287 needs
c_exp2: fld     st0
        frndint                         ; i z
        fld     st0
        fabs
        ficomp  word [c_klim]
        fstsw   ax
        sahf
        ja      .far
        fsub    st1, st0                ; i f   (|f| <= 1/2)
        fxch                            ; f i
        ftst
        fstsw   ax
        sahf
        jae     .p
        fabs                            ; 2^-|f| = 1 / 2^|f|
        f2xm1
        fld1
        faddp   st1, st0
        fld1
        fdivrp  st1, st0
        jmp     short .s
.p:     f2xm1
        fld1
        faddp   st1, st0
.s:     fscale
        fstp    st1
        ret
.far:   fstp    st0                     ; z
        ftst
        fstsw   ax
        sahf
        jb      .zero
        jmp     c_ebig
.zero:  fstp    st0                     ; 2^(very negative) = 0
        fldz
        ret

; ---- the coprocessor's functions --------------------------------------
f_sqrt: fsqrt
        ret
f_abs:  cmp     byte [c_fpu], 0
        je      .i
        fabs
        ret
.i:     test    byte [c_iacc+3], 80h
        jz      .x
        jmp     c_neg
.x:     ret
f_exp:  fldl2e
        fmulp   st1, st0
        jmp     c_exp2
f_ln:   fldln2
        jmp     short f_lg
f_log:  fldlg2
f_lg:   fxch                            ; x, log base 2 of e or 10
        ftst
        fstsw   ax
        sahf
        jbe     .nan                    ; FYL2X wants x > 0
        fyl2x
        ret
.nan:   jmp     c_enan

f_sin:  mov     bl, 0
        jmp     short c_trig
f_cos:  mov     bl, 1
        jmp     short c_trig
f_tan:  mov     bl, 2
c_trig: cmp     byte [c_deg], 0         ; degrees: c_trig287, which reduces
        jne     c_trig287               ;  by 45 exactly (cos 90 is 0)
        cmp     byte [c_fpu], 2
        jne     c_trig287
        cpu     386                     ; the 287XL's own (C2: |x| >= 2^63,
        cmp     bl, 1                   ;  x unchanged: the long way)
        jb      .s
        je      .c
        fptan
        fstsw   ax
        test    ah, 4
        jnz     c_trig287
        fstp    st0                     ; (the 1 it pushes)
        ret
.s:     fsin
        jmp     short .k
.c:     fcos
.k:     fstsw   ax
        test    ah, 4
        jnz     c_trig287
        ret
        cpu     286

; the 80287's way: FPREM by pi/4 (in degrees by 45, exact: 90 and 180
; leave r = 0) gives the octant and r in [0, pi/4); FPTAN gives Y/X =
; tan r (never at 0 or pi/4, outside its range); an odd octant takes
; pi/4 - r as (X-Y)/(X+Y); then sin and cos are Y and X over their
; hypotenuse, swapped and signed for the octant
c_trig287:
        call    c_check                 ; (FPREM: as in f_rem)
        mov     bh, 0
        ftst
        fstsw   ax
        sahf
        jae     .p
        fabs
        inc     bh                      ; a negative x: sin and tan change sign
.p:     cmp     byte [c_deg], 0
        je      .rad
        fild    word [c_k45]
        jmp     short .q
.rad:   fldpi
        fidiv   word [c_k4]
.q:     fxch                            ; |x| pi/4 (or 45)
.m:     fprem
        fstsw   ax
        test    ah, 4
        jnz     .m
        fstp    st1                     ; r
        xor     cx, cx                  ; CL = the octant: C0 C3 C1
        test    ah, 1
        jz      .a
        or      cl, 4
.a:     test    ah, 40h
        jz      .b
        or      cl, 2
.b:     test    ah, 2
        jz      .c
        or      cl, 1
.c:     ftst
        fstsw   ax
        sahf
        jne     .t
        fld1                            ; r = 0: X = 1, Y = r = 0
        jmp     short .o
.t:     cmp     byte [c_deg], 0
        je      .tr
        fldpi                           ; r degrees -> radians
        fmulp   st1, st0
        fidiv   word [c_k180]
.tr:    fptan                           ; X Y
.o:     test    cl, 1
        jz      .e
        fld     st0                     ; X X Y
        fadd    st0, st2                ; X+Y X Y
        fxch    st2                     ; Y X X+Y
        fsubp   st1, st0                ; X-Y X+Y
        fxch                            ; X+Y X-Y
.e:     mov     al, cl                  ; octants 1, 2, 5, 6: swapped
        inc     ax
        test    al, 2
        jz      .ns
        fxch
.ns:    mov     dl, cl                  ; ST0 = the cosine's side, ST1 the
        shr     dl, 2                   ;  sine's.  DL bit 0: sin negative
        xor     dl, bh                  ;  (octants 4-7), DH: cos (2-5)
        mov     dh, cl
        add     dh, 2
        shr     dh, 2
        cmp     bl, 2
        jne     .sc
        fdivp   st1, st0                ; tan = S / C
        xor     dl, dh
        jmp     short .sg
.sc:    fld     st0
        fmul    st0, st0                ; C2 C S
        fld     st2
        fmul    st0, st0                ; S2 C2 C S
        faddp   st1, st0
        fsqrt                           ; h C S
        cmp     bl, 1
        je      .cos
        fdivp   st2, st0                ; C S/h
        fstp    st0
        jmp     short .sg
.cos:   fdivp   st1, st0                ; C/h S
        fstp    st1
        mov     dl, dh
.sg:    test    dl, 1
        jz      .x
        fchs
.x:     ret

f_atan: cmp     byte [c_fpu], 2
        jne     .p
        fld1
        fpatan                          ; (287XL: any argument)
        jmp     short .deg
.p:     mov     bh, 0                   ; 80287: 0 < Y < X only
        ftst
        fstsw   ax
        sahf
        je      .x                      ; atan 0 = 0
        jae     .a
        fabs
        inc     bh
.a:     fld1                            ; 1 v
        fcom    st1
        fstsw   ax
        sahf
        je      .one
        ja      .lt
        fxch                            ; v 1: atan(1/v),
        fpatan
        fldpi
        fidiv   word [c_k2]
        fsubrp  st1, st0                ;  and pi/2 - that
        jmp     short .sg
.one:   fcompp
        fldpi
        fidiv   word [c_k4]
        jmp     short .sg
.lt:    fpatan                          ; atan(v / 1)
.sg:    or      bh, bh
        jz      .deg
        fchs
.deg:   cmp     byte [c_deg], 0
        je      .x
        fimul   word [c_k180]
        fldpi
        fdivp   st1, st0
.x:     ret

; ---- whole numbers: CX:BX = left, DX:AX = right -> DX:AX ----------------
i_add:  add     ax, bx
        adc     dx, cx
        jo      i_big
        ret
i_sub:  sub     bx, ax
        sbb     cx, dx
        jo      i_big
        mov     ax, bx
        mov     dx, cx
        ret
i_big:  jmp     c_ebig

i_neg:  neg     dx
        neg     ax
        sbb     dx, 0
        ret
i_abs:  or      dx, dx
        js      i_neg
        ret

i_mul:  mov     bp, dx
        xor     bp, cx                  ; the product's sign
        call    i_abs
        xchg    ax, bx
        xchg    dx, cx
        call    i_abs                   ; |left| DX:AX, |right| CX:BX
        jcxz    .m
        or      dx, dx
        jnz     i_big
        xchg    ax, bx
        xchg    dx, cx
.m:     mov     cx, ax                  ; DX:AX * BX
        mov     ax, dx
        mul     bx
        jc      i_big
        xchg    ax, cx
        mul     bx
        add     dx, cx
        jc      i_big
        test    dx, dx
        jns     .ok
        or      bp, bp                  ; 2^31 and more: only -2^31 fits
        jns     i_big
        cmp     dx, 8000h
        jne     i_big
        or      ax, ax
        jnz     i_big
        ret
.ok:    or      bp, bp
        jns     .x
        call    i_neg
.x:     ret

; CX:BX / DX:AX -> DX:AX = the quotient (towards 0), CX:BX = the
; remainder (with the left's sign)
i_divm: mov     di, ax
        or      di, dx
        jnz     .nz
        jmp     c_ediv
.nz:    push    cx                      ; the left's sign: the remainder's
        mov     bp, cx
        xor     bp, dx                  ; the quotient's
        call    i_abs
        xchg    ax, bx
        xchg    dx, cx
        call    i_abs                   ; DX:AX = |left|, CX:BX = |right|
        push    bp
        xor     si, si                  ; SI:DI = the remainder
        xor     di, di
        mov     bp, 32
.l:     shl     ax, 1
        rcl     dx, 1
        rcl     di, 1
        rcl     si, 1
        cmp     si, cx
        jb      .n
        ja      .s
        cmp     di, bx
        jb      .n
.s:     sub     di, bx
        sbb     si, cx
        inc     ax
.n:     dec     bp
        jnz     .l
        pop     bp
        mov     cx, si
        mov     bx, di
        or      bp, bp
        js      .ng
        test    dx, dx                  ; 2^31: -2^31 / -1
        jns     .q
        jmp     c_ebig
.ng:    call    i_neg
.q:     pop     bp
        or      bp, bp
        jns     .x
        xchg    ax, bx
        xchg    dx, cx
        call    i_neg
        xchg    ax, bx
        xchg    dx, cx
.x:     ret

i_quo:  jmp     i_divm
i_mod:  call    i_divm
        mov     ax, bx
        mov     dx, cx
        ret
i_div:  call    i_divm                  ; / only when it comes out whole
        mov     di, bx
        or      di, cx
        jnz     .f
        ret
.f:     jmp     c_e287

; CX:BX ^ DX:AX, by squaring
i_pow:  or      dx, dx
        jns     .p
        jmp     c_e287                  ; a fraction
.p:     mov     [c_pn], ax
        mov     [c_pn+2], dx
        mov     [c_pb], bx
        mov     [c_pb+2], cx
        mov     word [c_pr], 1
        mov     word [c_pr+2], 0
.l:     shr     word [c_pn+2], 1
        rcr     word [c_pn], 1
        jnc     .n
        mov     ax, [c_pr]
        mov     dx, [c_pr+2]
        mov     bx, [c_pb]
        mov     cx, [c_pb+2]
        call    i_mul
        mov     [c_pr], ax
        mov     [c_pr+2], dx
.n:     mov     ax, [c_pn]
        or      ax, [c_pn+2]
        jz      .d
        mov     ax, [c_pb]
        mov     dx, [c_pb+2]
        mov     bx, ax
        mov     cx, dx
        call    i_mul
        mov     [c_pb], ax
        mov     [c_pb+2], dx
        jmp     .l
.d:     mov     ax, [c_pr]
        mov     dx, [c_pr+2]
        ret

; ---- the answer as text ----------------------------------------------
; 15 digits: the decimal exponent e from log10, the number scaled to
; 15 digits (corrected when log10 was off by one), FBSTP for the digits.
; e from -5 to 14 is written out (0.001, 1024), else 1.5E+20.
calc_fmt:
        cmp     byte [c_fpu], 0
        jne     .f
        mov     ax, [c_ans]
        mov     dx, [c_ans+2]
        or      dx, dx
        jns     .u
        mov     byte [di], '-'
        inc     di
        call    i_neg
.u:     call    c_u32
        jmp     .end
.f:     fld     tword [c_ans]
        ftst
        fstsw   ax
        sahf
        jne     .nz
.tiny:  fstp    st0
        mov     al, '0'
        stosb
        jmp     .end
.nz:    jae     .pos
        mov     al, '-'
        stosb
        fabs
.pos:   fld     st0                     ; e ~ the binary exponent * log10 2
        fxtract                         ;  (exact for any size; the
        fstp    st0                     ;  corrections below take the
        fldlg2                          ;  rest)
        fmulp   st1, st0
        fistp   word [c_e]
        fwait
        cmp     word [c_e], -4900       ; (a denormal)
        jl      .tiny
        mov     ax, 14
        sub     ax, [c_e]
        fild    word [c_k10]
        call    c_ipow                  ; v * 10^(14-e)
.hi:    fcom    qword [c_e15]
        fstsw   ax
        sahf
        jb      .lo
        fidiv   word [c_k10]
        inc     word [c_e]
        jmp     .hi
.lo:    fcom    qword [c_e14]
        fstsw   ax
        sahf
        jae     .rnd
        fimul   word [c_k10]
        dec     word [c_e]
        jmp     .lo
.rnd:   frndint
        fcom    qword [c_e15]           ; (9.99...95 rounds up)
        fstsw   ax
        sahf
        jb      .bcd
        fidiv   word [c_k10]
        inc     word [c_e]
.bcd:   fbstp   tword [c_bcd]
        fwait
        mov     si, c_bcd + 7           ; the 15 digits, packed two a byte
        mov     bx, c_dig
        mov     cx, 15
        mov     dl, 1
.d:     mov     al, [si]
        test    dl, 1
        jz      .dh
        and     al, 0Fh
        dec     si
        jmp     short .dw
.dh:    shr     al, 4
.dw:    add     al, '0'
        mov     [bx], al
        inc     bx
        xor     dl, 1
        loop    .d
.z:     cmp     byte [bx-1], '0'        ; BP = after the last digit that
        jne     .ze                     ;  isn't a trailing 0
        dec     bx
        jmp     .z
.ze:    mov     bp, bx
        mov     si, c_dig
        mov     ax, [c_e]
        cmp     ax, -5
        jl      .sci
        cmp     ax, 14
        jg      .sci
        or      ax, ax
        js      .small
        mov     cx, ax                  ; the whole part, then the rest
        inc     cx
        rep     movsb
        call    c_frac
        jmp     short .end
.small: mov     cx, ax                  ; 0.00 and the digits
        mov     ax, '0' + '.' * 256
        stosw
        not     cx                      ; -e - 1 zeros
        mov     al, '0'
        rep     stosb
        call    c_copy
        jmp     short .end
.sci:   movsb
        call    c_frac
        mov     al, 'E'
        stosb
        mov     ax, [c_e]
        mov     bl, '+'
        or      ax, ax
        jns     .ep
        neg     ax
        mov     bl, '-'
.ep:    mov     [di], bl
        inc     di
        cmp     ax, 10
        jae     .e2
        mov     byte [di], '0'
        inc     di
.e2:    xor     dx, dx
        call    c_u32
.end:   mov     byte [di], 0
        cmp     byte [c_fpu], 0         ; nothing left on the coprocessor (its
        je      .x                      ;  sticky flags: a program after us
        fninit                          ;  may unmask them)
.x:     ret

; the digits from SI to BP after a '.' (none: nothing)
c_frac: cmp     si, bp
        jae     c_copy.x
        mov     al, '.'
        stosb
c_copy: cmp     si, bp
        jae     .x
        movsb
        jmp     c_copy
.x:     ret

; DX:AX (unsigned) in decimal at DI
c_u32:  mov     bx, 10
        xor     cx, cx
.d:     push    ax
        mov     ax, dx
        xor     dx, dx
        div     bx
        mov     si, ax
        pop     ax
        div     bx
        push    dx
        inc     cx
        mov     dx, si
        or      si, ax
        jnz     .d
.o:     pop     ax
        add     al, '0'
        stosb
        loop    .o
        ret

%include "FPU.INC"

c_leadops db '+*/\%^'
c_mulops  db '*/\%'
c_ops   db '+'
        dw f_add, i_add
        db '-'
        dw f_sub, i_sub
        db '*'
        dw f_mul, i_mul
        db '/'
        dw f_div, i_div
        db '\'
        dw f_quo, i_quo
        db '%'
        dw f_mod, i_mod
        db '^'
        dw f_pow, i_pow
c_names db 'SQRT',0,1
        dw f_sqrt
        db 'SIN',0,1
        dw f_sin
        db 'COS',0,1
        dw f_cos
        db 'TAN',0,1
        dw f_tan
        db 'ATAN',0,1
        dw f_atan
        db 'LN',0,1
        dw f_ln
        db 'LOG',0,1
        dw f_log
        db 'EXP',0,1
        dw f_exp
        db 'ABS',0,1
        dw f_abs
        db 'PI',0,0
        dw k_pi
        db 'ANS',0,0
        dw c_ldans
        db 0
c_msgs  db 'Syntax error',0,'Divide by zero',0,'Too big',0,'Not a number',0
        db 'Needs an 80287',0,'Too deep',0,'Unknown name',0,'Name too long',0
        db 'Value too long',0
c_k2    dw 2
c_k4    dw 4
c_k10   dw 10
c_k45   dw 45
c_k180  dw 180
c_klim  dw 16000
c_k32k  dw 32767
c_e14   dq 1.0e14
c_e15   dq 1.0e15

section .bss
c_fpu   resb 1                          ; 0 none, 1 80287, 2 287XL
c_deg   resb 1                          ; 1: degrees
c_lead  resb 1                          ; 1: start from the answer
c_lvl   resb 1                          ; brackets deep
c_sp    resw 1                          ; calc_eval's SP, for the errors
c_vsp   resw 1                          ; bytes used in c_vs
c_h     resw 1                          ; the operator's routine
c_w     resw 1
c_e     resw 1                          ; the answer's decimal exponent
c_iacc  resd 1                          ; whole numbers: the one worked on
c_pn    resd 1                          ;  ^: the exponent, base, product
c_pb    resd 1
c_pr    resd 1
c_ans   resb 10                         ; the answer (TBYTE, or 32 bits)
c_bcd   resb 10
c_nm    resb 16                         ; a name, upper case
c_dig   resb 15
c_vs    resb VS_N * 10
section .text
