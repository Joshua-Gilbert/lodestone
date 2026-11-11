; MTLIB.INC - what test_mt's DOS programs (MT*.ASM, VHOOK) had each written
; out for itself (as PROBE.INC is for the MS-DOS probes).  Macros, each used where its copy
; was, so every program's bytes, and the offsets test_mt reads in some of
; them, are as they were.  Not here: the copies that differ on purpose
; (MTSPIN's hex4 leaves ES = 40h; MTFAST's blanks leaves SI past the
; first non-blank, MTLAUNCH's skips ';' too, MTSRQ's and MTTERM's keep
; AL; MTPROBE's and MTTERM's hex4 go by hex2), and MTSRQ, whose `seen` the
; test reads at 10Dh.
%ifndef MTLIB_INC
%define MTLIB_INC

; ---- routines: each defines its label ------------------------------------

; blanks: past the blanks at SI (AL the first non-blank, SI at it)
%macro BLANKS 0
blanks: lodsb
        cmp     al, ' '
        je      blanks
        dec     si
        ret
%endmacro

; hex4: AX as 4 hex digits at DI (CX 0; hex4.h with CX digits, AX rotated)
%macro HEX4 0
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
%endmacro

; dec_out: AX in decimal at DI (BX 10, CX, DX changed)
%macro DEC_OUT 0
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
%endmacro

; cpz: the 0-ended string at SI to DI (its 0 not copied)
%macro CPZ 0
cpz:    lodsb
        or      al, al
        jz      .x
        stosb
        jmp     cpz
.x:     ret
%endmacro

; wout: a line end after out_ .. DI, then all of it added to FILE's end
; (fname; made if it isn't there)
%macro WOUT 0
wout:   mov     ax, 0A0Dh
        stosw
        mov     ax, 3D02h
        mov     dx, fname
        int     21h
        jnc     .o
        mov     ah, 3Ch
        xor     cx, cx
        int     21h
        jc      .x
.o:     xchg    bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        mov     ah, 40h
        mov     cx, di
        mov     dx, out_
        sub     cx, dx
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret
%endmacro

; TICKS label, n: label: n ticks of the BIOS's clock, with HLT (AX, DX
; changed); n is a value or a word in memory
%macro TICKS 2
%1:     push    es
        push    40h
        pop     es
        mov     dx, [es:6Ch]
        add     dx, %2
.w:     sti
        hlt
        mov     ax, [es:6Ch]
        sub     ax, dx
        js      .w
        pop     es
        ret
%endmacro

; ---- sequences, inline -----------------------------------------------------

; SAVEVEC n, old: INT n's vector (AH=35h) kept in the dword old (ES = its
; segment after)
%macro SAVEVEC 2
        mov     ax, 3500h + %1
        int     21h
        mov     [%2], bx
        mov     [%2 + 2], es
%endmacro

; HOOK n, old, handler: SAVEVEC, then INT n to CS:handler (AH=25h)
%macro HOOK 3
        SAVEVEC %1, %2
        mov     ax, 2500h + %1
        mov     dx, %3
        int     21h
%endmacro

; UNHOOK n, old: INT n back to the dword old (AH=25h; DS kept)
%macro UNHOOK 2
        push    ds
        lds     dx, [%2]
        mov     ax, 2500h + %1
        int     21h
        pop     ds
%endmacro

; IVTSET n, old, handler: INT n's vector written in the table itself (not
; AH=25h), the old one kept, under CLI (ES = 0 after)
%macro IVTSET 3
        xor     ax, ax
        mov     es, ax
        cli
        mov     ax, [es:%1 * 4]
        mov     [%2], ax
        mov     ax, [es:%1 * 4 + 2]
        mov     [%2 + 2], ax
        mov     word [es:%1 * 4], %3
        mov     [es:%1 * 4 + 2], cs
        sti
%endmacro

; EXECBLK label: EXEC's parameter block (AX=4B00h): the caller's
; environment, the command tail at `tail`, the PSP's two FCBs
%macro EXECBLK 1
%1      dw      0, tail, 0, 5Ch, 0, 6Ch, 0
%endmacro

%endif
