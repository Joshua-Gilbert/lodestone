; =====================================================================
;  FPU.INC - is there a coprocessor, and which?  (the Executive's info
;  line, System's Devices, CALC)
;
;  fpu_detect -> AL = 0 none, 1 an 80287, 2 a 287XL (or any 387-class
;  chip); AH changes too.  Nothing runs on the coprocessor unless INT 11h
;  says there is one: with none, the 286's EM bit may be set, and a
;  coprocessor instruction would trap to INT 7.  The 1520's POST sets that
;  bit only after the chip answered FNINIT, FNSTCW and FNSTSW (its
;  reset.asm), so this never waits on an empty socket.  Then FNINIT must
;  answer with a clear status word (with no chip the 286 reads the idle
;  bus: not 0), but for C0-C3: a real 80287's FNINIT leaves them as they
;  were (POST masks them too; a 387-class chip clears them, so the
;  emulator never showed it).  The two kinds are told apart by infinity: after
;  FNINIT an 80287 compares +inf and -inf equal (projective), a 287XL
;  doesn't.  It ends with FNINIT: nothing is left on the coprocessor.
; =====================================================================
fpu_detect:
        int     11h
        and     al, 2                   ; (AX not 0 from here on)
        jz      .x
        fninit
        fnstsw  ax
%ifdef CALC_287
        or      ah, 47h                 ; (tests: C0-C3 left set, as an 80287 may)
%endif
        test    ax, 0B8BFh              ; all but C0-C3 (and bit 6, reserved
        mov     al, 0                   ;  on an 80287)
        jnz     .x
        fld1
        fldz
        fdivp   st1, st0                ; +inf
        fld     st0
        fchs                            ; -inf
        fcompp
        fstsw   ax                      ; (waits for the compare)
        fninit
        mov     al, 1
        test    ah, 40h                 ; C3: equal
        jnz     .x
        inc     ax
.x:     ret
