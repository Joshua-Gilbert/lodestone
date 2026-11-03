; =====================================================================
;  CALC.RUN - the calculator: a window over the Executive (CODE-K)
;  python3 mkrun.py apps/CALC.ASM apps/CALC.RUN
;
;  The line at the top is the core's line editor: type a sum, Return
;  gives the answer under it.  Typing after an answer starts a new sum;
;  + * / \ % ^ first go on from the answer.  The keys below are the same
;  typing with the mouse.  The engine is CALC.INC, shared with CALC.COM.
;
;  It never sets a redraw routine, so the Executive stays under it (after
;  the saver too), and it ends with exit code 0FFFFh: the window closed,
;  the screen is as it was, the Executive doesn't redraw (API 5).  If the
;  Executive was redrawn under it meanwhile (the saver), its save-under
;  may be older than that: exit code 0, and the Executive redraws.
;
;  The window moves (API 6): by its title strip with the mouse, or
;  CODE-F7 and the arrow keys; its close box is ESC.  Everything in it is
;  drawn from where the window is now (icol, ey, ry, ky).
; =====================================================================
%include "UIAPI.INC"
RUN_API equ 6                           ; (W_FLAGS: it moves and closes.  Its help's HT,
                                        ;  n is API 10's, but a higher RUN_API would
                                        ;  take EV_RCLICK and EV_CLOSE too: an older
                                        ;  LODE.SYS shows the HT, n as 2 characters)
RUN_FLAGS equ RF_WIN                    ; (a window .RUN: with MULTITASK=1 one
                                        ;  of several at once, M8)
        org     RUN_ORG

WCOL    equ 41                          ; the window, where it first opens
WY      equ 28
WW      equ 38
WH      equ 228
KW      equ 6                           ; a key: 6 bytes by 24 pixels
KH      equ 24
EMAX    equ 120                         ; characters in the line
KQ      equ 16                          ; keys typed ahead (the BIOS holds 15)

start:  call    calc_init
        mov     si, win
        call    UI_WOPEN
.ed:    call    keep_line
        mov     si, ebuf
        mov     bp, EMAX
        mov     bx, [icol]
        inc     bx
        mov     dx, [ey]
        add     dx, 4
        mov     cx, KW * 6 - 2
        call    UI_EDIT
        cmp     ax, EV_CLICK
        je      .click
        cmp     al, 0Dh
        je      .eval
        mov     si, keys
        call    UI_DISPATCH
        cmp     byte [quit], 0
        je      .ed
        call    UI_WCLOSE
        mov     ax, 0FFFFh              ; the screen is as it was,
        cmp     byte [paints], 1
        je      .r
        xor     ax, ax                  ;  or redraw the Executive
.r:     ret
.eval:  call    evaluate
        jmp     .ed
.click: call    click
        jmp     .ed

; the line -> the answer, or what is wrong
evaluate:
        mov     si, ebuf
        call    c_skip
        or      al, al
        jz      .x
        call    calc_eval
        mov     di, rbuf
        jc      .err
        mov     ax, '= '
        stosw
        call    calc_fmt
        jmp     short .ok
.err:   call    calc_err
        call    UI_SBSTR
        mov     byte [di], 0
.ok:    mov     si, ebuf                ; (unchanged since: a key starts afresh)
        mov     di, lastx
        mov     cx, EMAX / 2 + 1
        rep     movsw
        call    draw_ans
.x:     ret

; a click on a key: BX = x, CX = y
        times ($ - $$) & 1 db 90h       ; (hot: even, EVEN.INC)
click:  sub     cx, [ky]
        jb      .x
        mov     ax, cx
        xor     dx, dx
        mov     cx, KH
        div     cx
        cmp     ax, 6
        jae     .x
        mov     di, ax                  ; DI = row
        shr     bx, 3
        sub     bx, [icol]
        jb      .x
        mov     ax, bx
        mov     cl, KW
        div     cl
        cmp     al, 6
        jae     .x
        xor     ah, ah
        imul    di, di, 6
        add     di, ax                  ; the key's number
        mov     dl, [kact+di]           ; DL = what it does
        cmp     dl, A_EQ
        je      evaluate
        cmp     dl, A_DEG
        je      k_deg
        cmp     dl, A_FN
        ja      .keep
        push    di                      ; typing after an answer: afresh
        mov     si, ebuf
        mov     di, lastx
        call    streq
        pop     di
        jne     .keep
        mov     byte [ebuf], 0
.keep:  mov     si, ebuf
        call    UI_STRLEN
        mov     bx, cx                  ; BX = its length
        cmp     dl, A_CLR
        je      .clear
        cmp     dl, A_BS
        je      .bs
        shl     di, 2                   ; the label, without its spaces
        lea     si, [klab+di]
        mov     cx, 4
.c:     lodsb
        cmp     al, ' '
        je      .n
        call    .put
.n:     loop    .c
        cmp     dl, A_FN
        jne     .z
        mov     al, '('
        call    .put
        jmp     short .z
.bs:    or      bx, bx
        jz      .z
        dec     bx
        jmp     short .z
        times ($ - $$) & 1 db 90h       ; (hot: even)
.clear: xor     bx, bx
.z:     mov     byte [ebuf+bx], 0
        mov     byte [lastx], 0FFh      ; (edited: no longer the answer's)
.x:     ret
.put:   cmp     bx, EMAX
        jae     .pf
        mov     [ebuf+bx], al
        inc     bx
.pf:    ret

; back to the line editor: unless the line is the answer's (then a key
; typed starts afresh), End first, so typing goes on where it was
; (UI_EDIT would replace the line).  INT 16h AH=05h puts the key in the
; BIOS's buffer (the 1520's BIOS has it: KbPlaceChar); keys typed
; meanwhile come out first and go back after it, in order (and so End
; always has room)
keep_line:
        cmp     byte [ebuf], 0
        je      .x
        mov     si, ebuf
        mov     di, lastx
        call    streq
        je      .x
        xor     bx, bx
.t:     mov     ah, 11h                 ; (as the core reads them)
        int     16h
        jz      .e
        mov     ah, 10h
        int     16h
        mov     [kq+bx], ax
        inc     bx
        inc     bx
        cmp     bx, KQ * 2
        jb      .t
.e:     mov     cx, K_END
        xor     si, si
.p:     mov     ah, 5
        int     16h
        cmp     si, bx
        jae     .x
        mov     cx, [kq+si]
        inc     si
        inc     si
        jmp     .p
.x:     ret

; F2, the Deg key: degrees or radians (the key lit for degrees)
k_deg:  xor     byte [c_deg], 1
deg_lamp:
        mov     bx, [icol]
        add     bx, 5 * KW + 1
        mov     dx, [ky]
        add     dx, 5 * KH + 1
        mov     cx, KH - 1
        mov     bp, KW - 1
        jmp     UI_INVERT

k_help: mov     si, keys
        mov     di, s_help
        jmp     UI_HELP

k_quit: inc     byte [quit]
        ret

; SI, DI: the same ASCIIZ text?  ZF
        times ($ - $$) & 1 db 90h       ; (hot: even)
streq:  lodsb
        scasb
        jne     .x
        or      al, al
        jnz     streq
.x:     ret

; the window's contents (BX = the window)
w_draw: mov     ax, [win+W_COL]         ; where the parts are now: inside it,
        inc     ax                      ;  the line, the answer, the keys
        mov     dx, [win+W_Y]
        add     dx, 24
        cmp     byte [paints], 0        ; drawn again at the same place: a
        je      .n                      ;  repaint over an older screen (at a
        cmp     ax, [icol]              ;  new place, a move saved what is
        jne     .geo                    ;  under it just now)
        cmp     dx, [ey]
        jne     .geo
.n:     stc
        rcl     byte [paints], 1        ; paints: 1 once, then 3, 7 ... FF (never 1 again)
.geo:   mov     [icol], ax
        mov     [ey], dx
        mov     ax, dx
        add     ax, 32
        mov     [ry], ax
        add     ax, 24
        mov     [ky], ax
        mov     bx, [icol]              ; the line's frame and the line
        mov     dx, [ey]
        mov     cx, KW * 6
        mov     bp, 24
        call    UI_BOX
        mov     si, ebuf
        call    UI_STRLEN
        cmp     cx, KW * 6 - 2
        jbe     .l
        mov     cx, KW * 6 - 2
.l:     inc     bx
        add     dx, 4
        xor     ah, ah
        call    UI_PUTSN
        call    draw_ans
        mov     dx, [ky]                ; the keys: lines,
        mov     di, dx
        add     di, 6 * KH
        mov     bx, [icol]
        mov     cx, KW * 6
.h:     call    UI_HLINE
        add     dx, KH
        cmp     dx, di
        jbe     .h
        mov     ax, [icol]
        shl     ax, 3
        mov     di, ax
        add     di, 6 * KW * 8
        mov     dx, [ky]
        mov     cx, 6 * KH + 1
.v:     call    UI_VLINE
        add     ax, KW * 8
        cmp     ax, di
        jbe     .v
        mov     si, klab                ;  and labels
        mov     dx, [ky]
        mov     bp, dx
        add     bp, 6 * KH
        add     dx, 4
        mov     di, [icol]
        add     di, 6 * KW
.r:     mov     bx, [icol]
        inc     bx
.k:     mov     cx, 4
        xor     ah, ah
        call    UI_PUTSN
        add     si, 4
        add     bx, KW
        cmp     bx, di
        jb      .k
        add     dx, KH
        cmp     dx, bp
        jb      .r
        cmp     byte [c_deg], 0
        je      .x
        jmp     deg_lamp
.x:     ret

; the answer's line, to the right
draw_ans:
        mov     bx, [icol]
        mov     dx, [ry]
        mov     cx, 16
        mov     bp, KW * 6
        xor     al, al
        call    UI_FILL
        mov     si, rbuf
        call    UI_STRLEN
        add     bx, KW * 6
        sub     bx, cx
        jae     .p
        mov     bx, [icol]
.p:     xor     ah, ah
        jmp     UI_PUTS

calc_var:                               ; (no variables here: only ANS)
        mov     al, E_NAME
        stc
        ret

%define CALC_RUN                        ; (c_u32: the core's UI_SBU32)
%include "CALC.INC"

A_INS   equ 0                           ; what a key does: its label
A_FN    equ 1                           ;  its label and (
A_EQ    equ 2
A_CLR   equ 3
A_BS    equ 4
A_DEG   equ 5

win     dw WCOL, WY, WW, WH, s_title, w_draw, WF_MOVE | WF_CLOSE
klab    db '  7   8   9   /   (   ) '
        db '  4   5   6   *   ^ sqrt'
        db '  1   2   3   -  sin cos'
        db '  0   .   E   +  tanatan'
        db '  C  <-  Ans  =  ln  log'
        db ' pi  exp  %   \  abs Deg'
kact    db 0, 0, 0, 0, 0, 0
        db 0, 0, 0, 0, 0, 1
        db 0, 0, 0, 0, 1, 1
        db 0, 0, 0, 0, 1, 1
        db 3, 4, 0, 2, 1, 1
        db 0, 1, 0, 0, 1, 5
keys    KEY(K_NONE,   0,      h_type)
        KEY(K_NONE,   0,      h_more)
        KEY(K_NONE,   0,      h_clear)
        KEY(K_F2,     k_deg,  h_deg)
        KEY(K_F1,     k_help, 0)
        KEY(K_ESC,    k_quit, h_quit)
        KEY(K_CODE_K, k_quit, 0)
        KEY(K_NONE,   0,      h_move)
        KEY(K_NONE,   0,      h_fns)
        dw 0
h_type  db 'Type a sum, Return', HT, 25, 'the answer',0
h_more  db '+ * / \ % ^ first', HT, 25, 'go on from it',0
h_clear db 'Ctrl-Y', HT, 25, 'clear the line',0
h_deg   db 'F2', HT, 25, 'degrees / radians',0
h_quit  db 'ESC or CODE-K', HT, 25, 'close',0
h_move  db 'CODE-F7, arrows, Return  move (or drag its title)',0
h_fns   db '\ whole part  % remainder  sqrt sin cos tan',0
s_title db 'Calculator',0
s_help  db 'Calculator Help',0

; the hot labels even (EVEN.INC: bench/hot.py's calc, drag and term; no pads
; inside CALC.INC, CALC.COM's too)
%include "EVEN.INC"
        EVEN    evaluate, evaluate.ok, evaluate.x, click, click.c, click.n, keep_line, keep_line.x
        EVEN    streq, streq.x, w_draw.geo, w_draw.l, w_draw.v, w_draw.k, draw_ans, draw_ans.p
        EVEN    c_skip, c_check, c_check.x, c_expr.x, c_term.l, c_unary, c_power, c_power.x, c_prim.n
        EVEN    c_push.ok, c_bin.h, c_num, c_num.e, calc_fmt.f, calc_fmt.nz, calc_fmt.hi, calc_fmt.lo
        EVEN    calc_fmt.rnd, calc_fmt.bcd, calc_fmt.d, calc_fmt.dh, calc_fmt.ze, calc_fmt.end, c_copy

section .bss
icol    resw 1                          ; inside the window, where it is now:
ey      resw 1                          ;  the first column, the line's row,
ry      resw 1                          ;  the answer's, the keys'
ky      resw 1
quit    resb 1
paints  resb 1                          ; the window drawn: 1 once, more: not
ebuf    resb EMAX + 2
lastx   resb EMAX + 2
rbuf    resb 48
kq      resw KQ
run_bss_end:
