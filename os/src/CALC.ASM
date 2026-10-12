; =====================================================================
;  CALC.COM - the calculator at the command prompt
;
;    CALC [/D] [name=]expression                CALC /?  how to use it
;
;  Prints the answer (to standard output, so it can be redirected), or
;  "CALC: Divide by zero" and the like on standard error with ERRORLEVEL
;  1; so too with no expression, a wrong switch, or an answer it couldn't
;  write (a full disk).  Names in the expression are environment
;  variables; name= also sets one in the command prompt's environment, so
;  a batch file can count:  CALC N=N+1  then  %N%.  /D: angles in degrees.
;  The engine is CALC.INC, shared with CALC.RUN.
;
;  name= writes into LCMD's own environment block only: its MCB belongs
;  to our parent, is LCMD's size (ENVPARA), and has nothing after its end
;  (a copy made by EXEC has 0001h and a program name there).  Under any
;  other parent (the Executive: the master environment, which M: shares)
;  it is left alone, and after the answer CALC says so, ERRORLEVEL 1.
; =====================================================================
        cpu     286
        org     100h

%include "LCMDENV.INC"                  ; ENVPARA

section .bss
bss_start:                              ; (before CALC.INC's)
section .text

start:  cld
        mov     di, bss_start           ; DOS doesn't clear it
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     bl, [80h]               ; the command tail, ASCIIZ
        xor     bh, bh
        mov     [81h+bx], bh
        call    calc_init
        mov     si, 81h
        call    c_skip
        cmp     al, '/'
        jne     .nd
        mov     al, [si+1]
        cmp     al, '?'
        je      help
        or      al, 20h
        cmp     al, 'd'
        jne     usage
        inc     byte [c_deg]
        add     si, 2
        call    c_skip
.nd:    or      al, al
        jz      usage
        mov     [exprp], si
        call    c_alpha                 ; name= ?
        jc      .ev
        call    c_rdname
        mov     ax, E_LNAME
        jc      .err
        call    c_skip
        cmp     al, '='
        jne     .ev
        inc     si
        mov     [exprp], si
        mov     si, c_nm
        mov     di, setname
        mov     cx, 8
        rep     movsw
.ev:    mov     si, [exprp]
        call    calc_eval
        jc      .err
        mov     di, outbuf
        call    calc_fmt
        mov     ax, 0A0Dh
        stosw
        mov     cx, di
        mov     dx, outbuf
        sub     cx, dx
        mov     bx, 1
        call    write
        mov     byte [di-2], 0          ; (outbuf: the value again, ASCIIZ)
        mov     ax, E_WRITE
        jc      .err
        cmp     byte [setname], 0
        je      .ok
        call    setvar
        jc      .err
.ok:    mov     ax, 4C00h
        int     21h
.err:   push    ax                      ; "CALC: " and why, on standard error
        mov     dx, s_calc
        mov     cx, 6
        mov     bx, 2
        call    write
        pop     ax
        push    ax
        cmp     ax, E_ENV
        jb      .eng
        sub     ax, E_ENV - 1
        mov     si, s_hmsgs
        call    c_nth
        jmp     short .m
.eng:   call    calc_err
.m:     mov     dx, si
        call    strlen
        call    write
        pop     ax
        cmp     ax, E_NAME              ; a name's: which name
        jb      .nl
        cmp     ax, E_LVAL
        ja      .nl
        mov     dx, s_colon
        mov     cx, 2
        call    write
        mov     dx, c_nm
        mov     si, dx
        call    strlen
        call    write
.nl:    mov     dx, s_crlf
        mov     cx, 2
        call    write
        mov     ax, 4C01h
        int     21h

E_ENV   equ E_LVAL + 1                  ; CALC.COM's own, after the engine's
E_LCMD  equ E_LVAL + 2
E_WRITE equ E_LVAL + 3

; CALC alone, a wrong switch: how to use it on standard error, ERRORLEVEL
; 1; CALC /?: on standard output
usage:  mov     bx, 2
        mov     bp, 4C01h
        jmp     short show
help:   mov     bx, 1
        mov     bp, 4C00h
show:   mov     dx, s_usage
        mov     si, dx
        call    strlen
        call    write
        mov     al, [c_fpu]
        mov     si, s_none
        dec     al
        js      .u
        mov     si, s_287
        jz      .u
        mov     si, s_287xl
.u:     mov     dx, si
        call    strlen
        call    write
        mov     ax, bp
        int     21h

; DX = text, CX = length, BX = handle -> CF: not all of it written
write:  mov     ah, 40h
        int     21h
        jc      .x
        cmp     ax, cx                  ; (a full disk: fewer)
.x:     ret

; SI = ASCIIZ -> CX = length (AL changes)
strlen: push    si
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .x
        inc     cx
        jmp     .l
.x:     pop     si
        ret

; a name's value from our environment (a copy of the prompt's): SI = name
; -> SI = the value, or CF and AL = E_NAME (none) or E_LVAL (more than
; 31 characters: not cut short into another number)
calc_var:
        push    es
        mov     es, [2Ch]
        xor     di, di
.f:     cmp     byte [es:di], 0
        je      .no
        push    si
        push    di
.c:     lodsb
        or      al, al
        jz      .eq
        scasb
        je      .c
.nx:    pop     di
        pop     si
        xor     al, al
        mov     cx, 0FFFFh
        repne   scasb
        jmp     .f
.eq:    cmp     byte [es:di], '='
        jne     .nx
        inc     di
        add     sp, 4
        mov     si, vbuf
.cp:    mov     al, [es:di]
        mov     [si], al
        inc     di
        inc     si
        or      al, al
        jz      .ok
        cmp     si, vbuf + 32
        jb      .cp
        mov     al, E_LVAL
        jmp     short .er
.ok:    mov     si, vbuf
        pop     es
        clc
        ret
.no:    mov     al, E_NAME
.er:    pop     es
        stc
        ret

; setname = outbuf in LCMD's environment, as its SET does it: the old
; one out, the new one at the end.  CF: AX = E_ENV (no room) or E_LCMD
; (not LCMD's, see the top); nothing changed.  LCMD's block is its own
; (owned by it, 40h paragraphs) and has nothing after its end; a copy made
; by EXEC for any other program has 0001h and the program's name there.
setvar: push    es
        mov     dx, [16h]               ; the parent
        mov     ax, cs
        cmp     dx, ax
        je      .no
        mov     es, dx
        mov     ax, [es:2Ch]
        or      ax, ax
        jz      .no
        dec     ax
        mov     es, ax
        cmp     [es:1], dx              ; its block,
        jne     .no
        cmp     word [es:3], ENVPARA    ;  LCMD's size
        jne     .no
        inc     ax
        mov     es, ax
        mov     si, setname             ; NAME=
        call    strlen
        mov     di, setname
        add     di, cx
        mov     word [di], '='
        xor     bp, bp                  ; BP: the old one + 1 (0: none)
        xor     di, di
.f:     cmp     byte [es:di], 0
        je      .end
        mov     bx, di
        mov     si, setname
.c:     lodsb
        or      al, al
        jz      .hit
        scasb
        je      .c
        jmp     short .nx
.hit:   lea     bp, [bx+1]
.nx:    mov     di, bx
        call    skipz
        jmp     .f
.no:    mov     ax, E_LCMD
        jmp     short .fail
.end:   cmp     word [es:di+1], 1       ; (a copy made by EXEC: not LCMD's)
        je      .no
        mov     dx, di                  ; room: the end, less the old one,
        or      bp, bp
        jz      .r
        mov     di, bp
        dec     di
        call    skipz
        sub     di, bp
        inc     di
        sub     dx, di
.r:     mov     si, setname             ;  plus NAME=value and two NULs
        call    strlen                  ;  (strlen changes AL: DX adds up)
        add     dx, cx
        mov     si, outbuf
        call    strlen
        add     dx, cx
        add     dx, 2
        cmp     dx, ENVPARA * 16
        jb      .room
        mov     ax, E_ENV
.fail:  pop     es
        stc
        ret
.room:  or      bp, bp                  ; the old one out: the rest moves down
        jz      .add
        mov     di, bp
        dec     di
        push    ds
        push    es
        pop     ds
        mov     si, di
.sk:    lodsb
        or      al, al
        jnz     .sk
.mv:    cmp     byte [si], 0
        je      .mvd
.m2:    lodsb
        stosb
        or      al, al
        jnz     .m2
        jmp     .mv
.mvd:   mov     byte [di], 0
        pop     ds
.add:   xor     di, di                  ; the end
.e:     cmp     byte [es:di], 0
        je      .a0
        call    skipz
        jmp     .e
.a0:    mov     si, setname
.a1:    lodsb
        or      al, al
        jz      .a2
        stosb
        jmp     .a1
.a2:    mov     si, outbuf
.a3:    lodsb
        stosb
        or      al, al
        jnz     .a3
        stosb                           ; the end
        pop     es
        clc
        ret

; ES:DI -> past the next NUL
skipz:  xor     al, al
        mov     cx, 0FFFFh
        repne   scasb
        ret

%include "CALC.INC"

s_calc  db 'CALC: '
s_crlf  db 13, 10
s_colon db ': '
s_hmsgs db 'Out of environment space', 0, 'name= works only at the command prompt', 0
        db "Can't write the answer", 0
s_usage db 'CALC [/D] [name=]expression', 13, 10
        db '  + - * / ^ ( )   \ whole part of a division   % remainder', 13, 10
        db '  sqrt sin cos tan atan ln log exp abs pi ans   /D: degrees', 13, 10
        db '  name= sets %name% too (in a batch file write %% for %)', 13, 10
        db 'Coprocessor: ', 0
s_none  db 'none: whole numbers only', 13, 10, 0
s_287   db '80287', 13, 10, 0
s_287xl db '80287XL', 13, 10, 0

section .bss
exprp   resw 1
setname resb 18                         ; NAME=
vbuf    resb 32
outbuf  resb 48
bss_end:
