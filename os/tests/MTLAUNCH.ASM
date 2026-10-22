; MTLAUNCH.COM - for test_mt.py: start programs as tasks (INT 21h F0h
; AL=10h, MTAPI.INC), list the tasks (AL=12h), then wait for a line
; itself (AH=0Ah), so they run.
;   MTLAUNCH [/F] [/B] [/Z] [/M:n] [/R:n] PROG.COM args; [/F] ... PROG2.COM args; ...
; /F: it comes to the front (SPF_FRONT); /B: it runs in the background
; whatever it does (SPF_BG); /Z: never there (SPF_FREEZE); /M:n: n paragraphs for it; /R:n:
; n of it (a command line holds 126 characters).  /G:n on its own: task n
; to the front (AL=13h; "MTLAUNCH: error E" if it fails); /K:n: task n
; ended (AL=14h, the same); /P:n: parked (AL=15h), /U:n: back (AL=16h);
; /X:n: "exit: SS GG XXXX EE" (AL=17h, hex: state, count, exit code, its count).
; Prints "task N" for each, or "MTLAUNCH: error E" (CF, AX = E); then
; "list:" and " N S NAME;" for each task (S: its TS_* state).
; nasm -f bin -i ../src/ -o MTLAUNCH.COM MTLAUNCH.ASM
cpu 286
org 100h
%include "MTAPI.INC"
        mov     sp, stk_top             ; (a .COM has all the memory: keep
        mov     ah, 4Ah                 ;  only its own, as a program that
        mov     bx, (stk_top - $$ + 100h + 15) / 16     ;  runs others does)
        int     21h
        mov     si, 81h
.cmd:   mov     byte [pb + SP_FLAGS], 0
        mov     word [pb + SP_PARAS], 0
        mov     word [rep_], 1
.opt:   call    blanks
        cmp     al, 0Dh
        je      .list
        cmp     al, '/'
        jne     .prog
        inc     si
        lodsb
        and     al, 0DFh
        cmp     al, 'F'
        jne     .ob
        or      byte [pb + SP_FLAGS], SPF_FRONT
        jmp     .opt
.ob:    cmp     al, 'B'
        jne     .oz
        or      byte [pb + SP_FLAGS], SPF_BG
        jmp     .opt
.oz:    cmp     al, 'Z'
        jne     .om
        or      byte [pb + SP_FLAGS], SPF_FREEZE
        jmp     .opt
.om:    mov     [opt], al
        inc     si                      ; /M:n, /R:n
        xor     bx, bx
.d:     lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .de
        cbw
        imul    bx, bx, 10
        add     bx, ax
        jmp     .d
.de:    dec     si
        cmp     byte [opt], 'R'
        je      .or
        cmp     byte [opt], 'G'
        je      .og
        cmp     byte [opt], 'K'
        je      .okl
        cmp     byte [opt], 'P'
        je      .opk
        cmp     byte [opt], 'U'
        je      .oup
        cmp     byte [opt], 'X'
        je      .oxc
        mov     [pb + SP_PARAS], bx
        jmp     .opt
.or:    mov     [rep_], bx
        jmp     .opt
.opk:   mov     ax, 0F000h + MT_PARK
        jmp     short .oc
.oup:   mov     ax, 0F000h + MT_UNPARK
        jmp     short .oc
.og:    mov     ax, 0F000h + MT_FRONT
        jmp     short .oc
.oxc:   mov     ax, 0F000h + MT_EXIT    ; "exit: SS GG DXDX CC" (hex)
        int     21h
        jc      .oe
        push    dx
        push    cx
        push    ax
        mov     dx, s_exit
        call    out
        pop     ax
        push    ax
        call    hx2
        pop     ax
        mov     al, ah
        call    hx2
        pop     cx
        pop     dx
        push    cx
        mov     al, dh
        call    hx2
        mov     al, dl
        call    hx1
        pop     cx
        mov     al, cl
        call    hx2
        mov     dx, s_nl
        call    out
        jmp     .opt
.okl:   mov     ax, 0F000h + MT_KILL
.oc:    int     21h
        jnc     .opt
.oe:
        push    ax
        mov     dx, s_err
        call    out
        pop     ax
        call    dec_
        mov     dx, s_nl
        call    out
        jmp     .opt
.prog:  mov     di, path                ; the program, to a blank, ; or the end
.p:     lodsb
        cmp     al, ' '
        je      .pe
        cmp     al, ';'
        je      .pe
        cmp     al, 0Dh
        je      .pe
        stosb
        jmp     .p
.pe:    dec     si
        mov     byte [di], 0
        mov     di, tail + 1            ; its arguments, to ; or the end
.t:     lodsb
        cmp     al, ';'
        je      .te
        cmp     al, 0Dh
        je      .te
        stosb
        jmp     .t
.te:    cmp     al, 0Dh
        jne     .t1
        dec     si
.t1:    mov     ax, di
        sub     ax, tail + 1
        mov     [tail], al
        mov     byte [di], 0Dh
        mov     [pb + SP_TAIL + 2], cs
        push    si
.again: mov     ax, 0F000h + MT_SPAWN
        mov     dx, path
        push    ds
        pop     es
        mov     bx, pb
        int     21h
        mov     dx, s_task
        jnc     .ok
        mov     dx, s_err
.ok:    push    ax
        call    out
        pop     ax
        call    dec_
        mov     dx, s_nl
        call    out
        dec     word [rep_]
        jnz     .again
        pop     si
        jmp     .cmd
.list:  mov     dx, s_list              ; the tasks
        call    out
        push    ds
        pop     es
        mov     ax, 0F000h + MT_LIST
        mov     di, recs
        mov     cx, MT_TASKS
        int     21h
        jc      .wait
        jcxz    .wait
        mov     si, recs
.r:     mov     al, ' '
        call    chr
        mov     al, [si + TR_ID]
        call    dec_
        mov     al, ' '
        call    chr
        mov     al, [si + TR_STATE]
        call    dec_
        mov     al, ' '
        call    chr
        push    si
        push    cx
        add     si, TR_NAME
        mov     cx, TR_NAMELEN
.nm:    lodsb
        or      al, al
        jz      .ne
        call    chr
        loop    .nm
.ne:    pop     cx
        pop     si
        mov     al, ';'
        call    chr
        add     si, MT_REC
        loop    .r
.wait:  mov     dx, s_wait
        call    out
        mov     ah, 0Ah
        mov     dx, line
        int     21h
        mov     ax, 4C00h
        int     21h

blanks: lodsb                           ; past blanks and ; -> AL = the next
        cmp     al, ' '
        je      blanks
        cmp     al, ';'
        je      blanks
        dec     si
        ret
out:    mov     ah, 9
        int     21h
        ret
chr:    push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        ret
hx2:    push    ax                      ; " " and AL in hex (hx1: no blank)
        mov     al, ' '
        call    chr
        pop     ax
hx1:    push    ax
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .c
        add     al, 7
.c:     jmp     chr
dec_:   aam                             ; AL (0..99) in decimal
        or      ah, ah
        jz      .1
        push    ax
        mov     al, ah
        add     al, '0'
        call    chr
        pop     ax
.1:     add     al, '0'
        jmp     chr

s_task  db      'task $'
s_err   db      'MTLAUNCH: error $'
s_exit  db      'exit:$'
s_list  db      'list:$'
s_wait  db      13, 10, 'MTLAUNCH waits> $'
s_nl    db      13, 10, '$'
pb      dw      0, tail, 0, 0, 0, 0, 0, 0       ; (SP_*: env, tail, FCBs, paras)
        db      0                               ;  (flags)
rep_    dw      1
opt     db      0
line    db      40, 0
        times   42 db 0
path    times   80 db 0
tail    times   130 db 0
recs    times   MT_TASKS * MT_REC db 0
        align   2
        times   256 db 0
stk_top:
