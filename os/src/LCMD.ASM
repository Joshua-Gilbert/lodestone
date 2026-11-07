; LCMD.COM - the Lodestone command shell (DOS 3.30 style)
;
;   LCMD            interactive, EXIT goes back to the Executive
;   LCMD /C line    run one command line and return its exit code
;   LCMD /P         permanent (a system's first shell): EXIT does
;                      nothing, \AUTOEXEC.BAT runs at the start
;
; Not called COMMAND.COM on purpose: GRiD MS-DOS in the EPROM takes
; A:\COMMAND.COM as its own shell when the Lodestone floppy is in the drive.
;
; Built in: DIR TYPE COPY DEL ERASE REN RENAME MD MKDIR RD RMDIR CD CHDIR
; CLS ECHO VER VOL SET PATH PROMPT DATE TIME PAUSE REM EXIT, drive changes
; (A:), programs through PATH (.COM .EXE), batch files (.BAT, %0-%9,
; %NAME%, @, ECHO OFF, IF, GOTO, FOR, CALL, SHIFT, CHOICE), redirection
; < > >> and pipes |, and && / || between commands.  With multitasking on
; (MULTITASK=1, MTAPI.INC): TASKS, START, FG, KILL, PARK, UNPARK and WAIT.
;
; The prompt edits its line (Left, Right, Home, End, Backspace, Del, ESC),
; keeps a history (Up, Down, F3) and completes file names (Tab, again for
; the next).  Waiting there, at PAUSE or at CHOICE, the Executive's screen
; saver comes on after its delay (Lodestone only: INT 21h F0h AL=5), with
; DEFRAG's round only at the prompt; a key ends it.
;
; ERRORLEVEL: a program's exit code; a built-in command that can fail sets
; 0 or 1 (ECHO, REM, CLS, VER, PAUSE, GOTO, SHIFT, IF, FOR and CALL leave it
; to the commands they run, CHOICE sets the key's number, WAIT the task's
; exit code).  && runs the next
; command if the last one worked, || if it didn't.  In a batch file an error
; says where: "NAME line n: File not found".
cpu 286
org 100h

LBUF    equ 128
FB_DTA  equ 0                       ; FOR's block (L4): its DTA, its set
FB_BUF  equ 44                      ;  and command (each ending in 0),
FB_ZERO equ FB_BUF + LBUF + 2       ;  and a 0 (the name a plain item adds)
FB_PARAS equ (FB_ZERO + 1 + 15) / 16
%include "LCMDENV.INC"                  ; ENVPARA: our environment, 1 KB
%include "MTAPI.INC"                    ; TASKS: multitasking's calls
HIST    equ 512                         ; the prompt's history
RMAX    equ 12                          ; lines run inside lines (FOR, CALL)
CMAX    equ 8                           ; CALLs inside CALLs

; Hot code on even offsets (a taken jump to an odd one costs the 286 a
; fetch): os/bench/hot.py's counts over the prompt's work (DIR, TYPE, COPY,
; a batch file's loop, the PATH, pipes, the task commands), plan.py placed
; the pads ("hot": each `times ($ - $$) & 1`, after a JMP or RET, so never
; run).  The labels in the EVEN list at the code's end must stay even, or
; no build (the PSP is a paragraph, so the offset's parity is the address's)
%include "EVEN.INC"

start:  mov     sp, stack_top
        cld
        mov     di, bss_start           ; DOS doesn't clear memory for us
        mov     cx, stack_top - bss_start
        xor     al, al
        rep     stosb
        mov     bx, prog_end + 15
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     [main_sp], sp
        mov     ah, 51h
        int     21h
        mov     [mypsp], bx
        ; the command line before the DTA moves over it
        mov     si, 81h
        mov     cl, [80h]
        xor     ch, ch
        mov     di, line
.ct:    jcxz    .ctd
        lodsb
        cmp     al, 13
        je      .ctd
        stosb
        dec     cx
        jmp     .ct
.ctd:   mov     byte [di], 0
        call    set_dta
        call    env_init
        mov     byte [vfcb], 0FFh       ; VOL's extended FCB: the label's
        mov     byte [vfcb + 6], 08h    ;  attribute, ??????????? (ES = CS)
        mov     di, vfcb + 8
        mov     cx, 11
        mov     al, '?'
        rep     stosb
        mov     dx, ctrlc
        mov     ax, 2523h
        int     21h
        mov     dx, crit
        mov     ax, 2524h
        int     21h
        mov     byte [echo], 1
        mov     word [hist_end], hist
        mov     word [sv_t], 0FFFFh     ; the Executive's screen saver: its
        xor     ax, ax                  ;  delay and where it is (ES stays 0
        mov     es, ax                  ;  if this isn't Lodestone)
        mov     ax, 0F005h
        int     21h
        mov     cx, es
        jcxz    .nsv
        mov     [sv_t], ax
        mov     [sv_entry], bx
        mov     [sv_entry+2], es
.nsv:   push    cs
        pop     es
        ; its own parent: the first shell of the system
        push    es
        mov     es, [mypsp]
        mov     ax, [es:16h]
        pop     es
        cmp     ax, [mypsp]
        jne     .sw0
        mov     byte [perm], 1
.sw0:   ; switches: [path] [/P] [/E:n] [/C line]
        mov     si, line
.sw:    call    skipsp
        lodsb
        or      al, al
        jz      .swd
        cmp     al, '/'
        jne     .word                   ; a path ("A:\ /P"): skip it
        lodsb
        call    upcase
        cmp     al, 'C'
        je      .slc
        cmp     al, 'P'
        jne     .word
        mov     byte [perm], 1
.word:  lodsb
        or      al, al
        jz      .swd
        call    is_blank
        je      .sw
        cmp     al, '/'
        jne     .word
        dec     si
        jmp     .sw
.swd:   cmp     byte [perm], 0
        je      .inter
        call    perm_start
        jmp     .inter
.slc:   mov     byte [oneshot], 1       ; /C: the rest is the command
        mov     di, line
        call    strcpy
        mov     si, line
        call    do_line
.batch1:
        cmp     byte [bat_on], 0        ; a batch file it started runs out
        je      .quit
        call    bat_next
        jmp     .batch1
.quit:  mov     al, [errlvl]
        mov     ah, 4Ch
        int     21h
; ---------------------------------------------------------------------
; the environment: a 1 KB copy of our own, so SET has room
env_init:
        mov     bx, ENVPARA
        mov     ah, 48h
        int     21h
        jc      .x
        mov     es, ax
        xor     di, di
        mov     cx, ENVPARA * 8
        xor     ax, ax
        rep     stosw
        push    ds
        mov     ds, [mypsp]
        mov     ax, [2Ch]
        or      ax, ax                  ; (none at all: start empty)
        jz      .none
        mov     ds, ax
        xor     si, si
        xor     di, di
.c:     cmp     byte [si], 0
        je      .d
.s:     lodsb
        stosb
        or      al, al
        jnz     .s
        cmp     di, ENVPARA * 16 - 2
        jb      .c
.d:     pop     ds
        push    es
        mov     es, [mypsp]             ; give the old one back
        mov     ax, [es:2Ch]
        pop     bx
        mov     [es:2Ch], bx
        mov     es, ax
        mov     ah, 49h
        int     21h
.x:     push    cs
        pop     es
        ret
.none:  pop     ds
        mov     ax, es
        mov     es, [mypsp]
        mov     [es:2Ch], ax
        jmp     .x

; the first shell: COMSPEC if nobody set it, then \AUTOEXEC.BAT
perm_start:
        mov     ah, 19h                 ; (X: the current drive)
        int     21h
        add     al, 'A'
        mov     [prog], al
        mov     si, s_comspec
        call    env_find                ; (SI kept)
        push    cs
        pop     es
        jnc     .ae
        mov     di, setbuf
        call    strcpy
        mov     al, [prog]
        stosb
        mov     si, s_selfname
        call    strcpy
        mov     si, setbuf
        call    env_set_line
.ae:    mov     si, s_autoexec          ; X:\AUTOEXEC.BAT
        mov     di, prog + 1
        call    strcpy
        mov     dx, prog
        mov     ax, 4300h
        int     21h
        jc      .x
        mov     si, s_autoname
        mov     di, cword
        call    strcpy
        mov     word [argp], s_empty
        call    bat_start
.x:     ret

s_banner    db 13, 10, 'Lodestone 1.0 command shell (DOS 3.30 compatible)', 13, 10
            db 'Type EXIT to return to the Executive.', 13, 10, 0
s_selfname  db ':\LCMD.COM', 0
s_autoexec  db ':\AUTOEXEC.BAT', 0
s_autoname  db 'AUTOEXEC', 0

start.inter:
        mov     si, s_banner
        call    puts
        ; (from start to here: only run once, so the history lies over
        ;  it: hist equ start)

; ---- the prompt loop ----------------------------------------------------
prompt_loop:
        cld
        mov     sp, [main_sp]
        push    cs
        pop     ds
        push    cs
        pop     es
        call    unwind
        cmp     byte [bat_on], 0
        je      .ask
        call    bat_next
        jmp     prompt_loop
.ask:   cmp     byte [echo], 0
        je      .np
        call    crlf_if_col
        call    show_prompt
.np:    call    edit_line
        call    crlf
        mov     si, line
        call    do_line
        jmp     prompt_loop

; back at the prompt (after Ctrl-C too): every level of redirection undone,
; the batch files that CALLed others closed, no FOR
unwind: cmp     byte [rdepth], 0
        je      .r0
        call    rpop
        jmp     unwind
.r0:    mov     byte [tpre_on], 0       ; (a pipe's TEMP: read again; even:
                                        ;  the hot labels after)
        call    redir_undo
.c:     mov     bl, [cdepth]
        or      bl, bl
        jz      .f
        dec     bl
        mov     [cdepth], bl
        xor     bh, bh
        shl     bx, 1
        mov     es, [call_segs + bx]
        cmp     byte [es:for_on - bat_ctx], 0   ; (its FOR's block)
        je      .nf
        push    es
        mov     es, [es:for_seg - bat_ctx]
        mov     ah, 49h
        int     21h
        pop     es
.nf:    cmp     byte [es:bat_on - bat_ctx], 0
        je      .fr
        mov     bx, [es:bat_h - bat_ctx]
        mov     ah, 3Eh
        int     21h
        mov     al, [es:bat_echo - bat_ctx]     ; (the outermost's last)
        mov     [echo], al
.fr:    mov     ah, 49h
        int     21h
        push    cs
        pop     es
        jmp     .c
.f:     cmp     byte [for_on], 0        ; a FOR's block (Ctrl-C in one)
        je      .f0
        call    for_free
.f0:    mov     byte [for_on], 0
        mov     byte [for_n], 0
        cmp     byte [aborted], 0
        je      .x
        mov     byte [aborted], 0
        cmp     word [cb_seg], 0        ; COPY's or TYPE's buffer
        je      .h
        call    cbuf_free
.h:     mov     bx, 5                   ; and their files (nothing of ours
.hc:    mov     ah, 3Eh                 ;  is open at the prompt)
        int     21h
        inc     bx
        cmp     bx, 20
        jb      .hc
.x:     ret

; Ctrl-C: a program of ours ends; our own command is abandoned
ctrlc:  cmp     byte [cs:sv_busy], 0    ; (the Executive's saver: on)
        je      .ns
        iret
.ns:    cmp     byte [cs:child], 0
        je      .us
        stc
        retf                            ; ends the program
.us:    push    cs
        pop     ds
        mov     byte [aborted], 1
        call    bat_end

        cmp     byte [oneshot], 0
        je      .p
        mov     al, 255
        mov     ah, 4Ch
        int     21h
.p:     jmp     prompt_loop

; INT 24h: "Not ready reading drive A / Abort, Retry, Fail?"
crit:   sti
        pusha
        push    ds
        push    es
        push    cs
        pop     ds
        cmp     byte [crit_q], 0        ; (Tab looking: Fail, no prompt in
        je      .ask                    ;  the line being edited)
        mov     al, 3
        jmp     .x
.ask:   mov     [crit_ah], ah
        mov     [crit_al], al
        mov     si, s_crlf
        call    bputs
        mov     cx, di                  ; the message
        xor     ch, ch
        cmp     cl, 0Ch
        jbe     .k
        mov     cl, 0Ch
.k:     call    ce_msg
        call    bputs
        mov     si, s_reading
        test    byte [crit_ah], 1
        jz      .rw
        mov     si, s_writing
.rw:    call    bputs
        mov     al, [crit_al]
        add     al, 'A'
        call    bputc
        mov     si, s_arf
        call    bputs
.key:   xor     ah, ah
        int     16h
        call    upcase
        mov     ah, 2
        cmp     al, 'A'
        je      .ans
        mov     ah, 1
        cmp     al, 'R'
        je      .ans
        mov     ah, 3
        cmp     al, 'F'
        je      .ans
        jmp     .key
.ans:   push    ax
        call    bputc
        mov     si, s_crlf
        call    bputs
        pop     ax
        mov     al, ah
        cmp     al, 1
        je      .an
        mov     byte [crit_seen], 1     ; (Abort or Fail: why EXEC fails, said)
.an:    cmp     byte [child], 0         ; Abort or Fail in our own work:
        jne     .x                      ;  Fail, and the rest of this
        cmp     al, 1                   ;  command fails without asking
        je      .x                      ;  again (one question, not one
        mov     al, 3                   ;  for each call it makes)
        mov     [crit_q], al
.x:     mov     bp, sp                  ; the answer into pusha's AX
        mov     [bp+4+14], al           ;  (past ES and DS)
        pop     es
        pop     ds
        popa
        iret

; console output for the critical error handler (BIOS only)
bputs:  lodsb
        or      al, al
        jz      .x
        call    bputc
        jmp     bputs
.x:     ret
bputc:  push    ax
        push    bx
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        pop     bx
        pop     ax
        ret

; INT 24h's message for code CX (0-12) -> SI: CX + 1 NULs on from the one
; before ce0
ce_msg: inc     cx
        mov     si, ce0 - 1
.s:     lodsb
        or      al, al
        jnz     .s
        loop    .s
        ret

; ---------------------------------------------------------------------
; one command line at SI (NUL-terminated): pipes, redirection, then the
; command itself
do_line:
        call    set_dta
        call    skipsp
        cmp     byte [si], '@'
        jne     .np
        inc     si
        call    skipsp
.np:    cmp     byte [si], 0
        je      .x
        cmp     byte [si], ':'          ; a batch label
        je      .x
        mov     bl, 1                   ; BL: run this part
.part:  mov     di, si                  ; it ends at the end, && or ||
.f:     mov     al, [di]
        or      al, al
        jz      .e
        cmp     al, '&'
        je      .2
        cmp     al, '|'
        jne     .n
.2:     cmp     al, [di+1]
        je      .e
.n:     inc     di
        jmp     .f
.e:     mov     byte [di], 0
        push    ax                      ; AL: what follows (0, '&' or '|')
        push    di
        or      bl, bl
        jz      .sk
        call    do_pipe
.sk:    pop     si
        pop     ax
        or      al, al
        jz      .x
        inc     si                      ; (past the two)
        inc     si
        mov     bl, [failed]            ; || runs the next part after a
        cmp     al, '|'                 ;  failure, && after success
        je      .part
        xor     bl, 1
        jmp     .part
.x:     ret

; one command, or a pipe of them, with its redirection.  The redirection
; of a line this one runs inside (FOR, CALL) is kept meanwhile, a level of
; its own (unwind takes them all back after Ctrl-C)
do_pipe:
        mov     bl, [rdepth]
        cmp     bl, RMAX
        jb      .ok
        mov     si, e_deep
        jmp     err
.ok:    inc     byte [rdepth]
        xor     bh, bh
        shl     bx, 2
        mov     ax, [save_in]
        mov     [rsave + bx], ax
        mov     ax, [save_out]
        mov     [rsave + bx + 2], ax
        mov     ax, 0FFFFh
        mov     [save_in], ax
        mov     [save_out], ax
        push    word [pipe_rest]
        push    word [pipe_n]
        mov     [pipe_rest], si
        mov     byte [pipe_n], 0
        call    .seg
        pop     word [pipe_n]
        pop     word [pipe_rest]
        jmp     rpop
.seg:   mov     si, [pipe_rest]
        mov     di, cmdl                ; cut at the next '|'
.cp:    lodsb
        cmp     al, '|'
        je      .bar
        stosb
        or      al, al
        jnz     .cp
        mov     word [pipe_rest], 0
        jmp     .cut
        times   ($ + 1 - $$) & 1 db 90h ; (hot: odd here, so .cut on even)
.bar:   mov     byte [di], 0
        mov     [pipe_rest], si
.cut:   ; the pipe's files: in from the last, out to the next
        mov     byte [in_name], 0
        mov     byte [out_name], 0
        mov     byte [out_app], 0
        cmp     byte [pipe_n], 0
        je      .ni
        mov     al, '1'
        test    byte [pipe_n], 1
        jnz     .pi
        mov     al, '2'
.pi:    mov     di, in_name
        call    pipe_name
.ni:    cmp     word [pipe_rest], 0
        je      .no
        mov     al, '2'
        test    byte [pipe_n], 1
        jnz     .po
        mov     al, '1'
.po:    mov     di, out_name
        call    pipe_name
.no:    inc     byte [pipe_n]           ; (counted first: a later one's
        call    parse_redir             ;  redirection failing, the files
        jc      .x                      ;  the one before made go too)
        call    redir_do
        jc      .x
        mov     si, cmdl
        call    run_cmd
        cld
        push    cs
        pop     es
        call    redir_undo
        cmp     word [pipe_rest], 0
        jne     .seg
.x:     call    redir_undo
        cmp     byte [pipe_n], 1        ; a pipe leaves its files (one
        jbe     .r                      ;  command: none, and no INT 24h)
        mov     al, '1'                 ; (the names no longer needed: made
        call    .del                    ;  again there)
        mov     al, '2'
        call    .del
.r:     mov     al, [rdepth]            ; (the pipe that read TEMP over:
        cmp     [tpre_on], al           ;  the next reads it again)
        jne     .rr
        mov     byte [tpre_on], 0
.rr:    ret
.del:   mov     di, in_name
        call    pipe_name
        mov     dx, in_name
        mov     ah, 41h
        int     21h
        ret

; AL = '1' or '2', DI = 80 bytes -> this level's pipe file's name there:
; %TEMP%\PIPEx1.$$n (no TEMP: %TMP%; neither: \PIPEx1.$$n, the
; current drive's root, as MS-DOS 3.3), x for the level (a pipe inside a
; CALL or FOR inside a pipe has its own), n our task's number ($ with multitasking off: LCMDs in two
; tasks have their own).  TEMP is ours (SET TEMP= counts; from the ROM
; without C: the kernel's M:\, so a pipe works from R:), 64 characters of
; it at most, read once by the outermost pipe running (tpre_on: its level)
; for it and the pipes inside it: a SET TEMP= meanwhile moves no file
pipe_name:
        mov     dl, al
        cmp     byte [tpre_on], 0
        jne     .h
        mov     al, [rdepth]
        mov     [tpre_on], al
        push    es
        push    di
        mov     si, s_tempv
        call    env_find                ; -> ES:DI its value
        jnc     .v
        mov     si, s_tmpv              ; (none: TMP, as CLAUDE.COM)
        call    env_find
.v:     mov     si, di
        mov     di, tpre
        jc      .rt
        mov     cx, 64
.t:     mov     al, [es:si]
        inc     si
        or      al, al
        jz      .e
        mov     [di], al
        inc     di
        loop    .t
.e:     cmp     di, tpre                ; ("TEMP=": the root)
        je      .rt
        cmp     byte [di-1], '\'
        je      .f
.rt:    mov     byte [di], '\'
        inc     di
.f:     mov     byte [di], 0
        pop     di
        pop     es
.h:     mov     si, tpre
        call    strcpy                  ; (DI on its NUL)
        mov     si, pipe_t
        mov     bx, di
        call    strcpy
        mov     [bx + 5], dl            ; 1 or 2
        mov     al, [rdepth]
        add     al, 'A' - 1
        mov     [bx + 4], al
        call    mt_mine
        mov     al, '$'
        jc      .n
        mov     al, ah
        add     al, '0'
.n:     mov     [bx + 9], al
        ret
        times   ($ + 1 - $$) & 1 db 90h ; (rpop odd: the hot labels after even)

; one level of redirection done: the one around it again
rpop:   call    redir_undo
        dec     byte [rdepth]
        mov     bl, [rdepth]
        xor     bh, bh
        shl     bx, 2
        mov     ax, [rsave + bx]
        mov     [save_in], ax
        mov     ax, [rsave + bx + 2]
        mov     [save_out], ax
        ret

; take < > >> out of cmdl (into in_name / out_name)
parse_redir:
        mov     si, cmdl
        mov     di, cmdl
.l:     lodsb
        cmp     al, '<'
        je      .in
        cmp     al, '>'
        je      .out
        stosb
        or      al, al
        jnz     .l
        clc
        ret
.in:    push    di
        mov     di, in_name
        jmp     .name
.out:   mov     byte [out_app], 0
        cmp     byte [si], '>'
        jne     .o1
        inc     si
        mov     byte [out_app], 1
.o1:    push    di
        mov     di, out_name
.name:  call    skipsp
        mov     cx, 78
.n:     lodsb
        call    is_blank
        je      .ne
        cmp     al, '<'
        je      .nb
        cmp     al, '>'
        je      .nb
        or      al, al
        je      .nb
        stosb
        loop    .n
.ne:    mov     byte [di], 0
        pop     di
        jmp     .l
.nb:    dec     si
        mov     byte [di], 0
        pop     di
        jmp     .l

; apply in_name/out_name to handles 0/1.  CF (message shown) on error
redir_do:
        cmp     byte [in_name], 0
        je      .o
        mov     dx, in_name
        mov     ax, 3D00h
        int     21h
        jnc     .io
        jmp     err_notfound
.io:    mov     bx, ax
        mov     cx, 0
        call    swap_handle
        mov     [save_in], ax
.o:     cmp     byte [out_name], 0
        je      .x
        mov     dx, out_name
        cmp     byte [out_app], 0
        je      .cr
        mov     ax, 3D01h
        int     21h
        jc      .cr
        mov     bx, ax
        push    bx
        call    seek_end
        pop     bx
        jmp     .oo
.cr:    mov     dx, out_name
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jnc     .c2
        jmp     err_create
.c2:    mov     bx, ax
.oo:    mov     cx, 1
        call    swap_handle
        mov     [save_out], ax
.x:     clc
        ret

; make handle CX refer to file handle BX (which is closed); AX = a copy
; of what CX was
swap_handle:
        push    bx
        mov     bx, cx
        mov     ah, 45h
        int     21h
        pop     bx
        jc      .x
        push    ax
        mov     ah, 46h
        int     21h
        mov     ah, 3Eh
        int     21h
        pop     ax
.x:     ret

        times   ($ + 1 - $$) & 1 db 90h ; (hot: odd here, so the hot labels after even)
redir_undo:
        mov     di, save_out
        mov     cx, 1
        call    .one
        mov     di, save_in
        xor     cx, cx
.one:   mov     bx, 0FFFFh              ; handle CX back from the copy at
        xchg    bx, [di]                ;  [DI] (FFFFh: none), which is
        inc     bx                      ;  closed; FFFFh left there
        jz      .x
        dec     bx
        mov     ah, 46h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret

; ---------------------------------------------------------------------
; the command at SI (redirection already done)
run_cmd:
        call    skipsp
        cmp     byte [si], 0
        jne     .w
        ret
.w:     mov     byte [failed], 0
        call    get_word
        ; drive change "B:"
        cmp     byte [cword+1], ':'
        jne     .bi
        cmp     byte [cword+2], 0
        jne     .bi
        mov     ax, do_drive
        jmp     .set
        times   ($ - $$) & 1 db 90h     ; (hot: even)
.bi:    ; a built-in?  The name may run into '\' or '.' ("CD\", "CD..")
        mov     si, cword
        mov     di, cword2
.b2:    lodsb
        cmp     al, '\'
        je      .b3
        cmp     al, '.'
        je      .b3
        stosb
        or      al, al
        jnz     .b2
        mov     ax, [argp]
        mov     [argp2], ax
        jmp     .look
.b3:    mov     byte [di], 0
        mov     si, cword               ; args start where cword2 ends
        call    strlen
        mov     dx, cx                  ; (strlen leaves AL 0)
        mov     si, cword2
        call    strlen
        sub     dx, cx
        mov     si, [argp]
        sub     si, dx
        mov     [argp2], si
.look:  mov     si, builtins            ; (each: its name, NUL, where it is)
.bl:    cmp     byte [si], 0
        je      .ext
        mov     di, cword2
        call    streq                   ; (keeps SI)
        pushf
.bs:    lodsb
        or      al, al
        jnz     .bs
        lodsw
        popf
        jne     .bl
        mov     bx, si                  ; (past its entry)
        mov     si, [argp2]
        call    skipsp
        cmp     bx, builtins_pass       ; (these leave ERRORLEVEL alone)
        ja      .pass
.set:   call    ax
        mov     al, [failed]            ; 0: it worked, 1: it didn't
        mov     [errlvl], al
        ret
.pass:  jmp     ax
.ext:   jmp     run_external

do_drive:                               ; "B:"
        mov     dl, [cword]
        sub     dl, 'A'
        cmp     dl, 26                  ; ("@:" FFh, and past Z:: none)
        jae     .bad
        mov     [tmpb], dl
        mov     ah, 0Eh
        int     21h
        mov     ah, 19h
        int     21h
        cmp     al, [tmpb]
        je      .x
.bad:   jmp     vol_bad
.x:     ret
        times   ($ - $$) & 1 db 90h     ; (hot: get_word.c even)

; the word at SI, upper case, into cword (70 characters at most): DI on its
; NUL, SI and [argp] just past it (past the 70th of a longer one).  ES = CS
; (is_wordend)
get_word:
        mov     di, cword
        mov     cx, 70
.c:     lodsb
        call    is_wordend
        je      .e
        call    upcase
        stosb
        loop    .c
        inc     si                      ; (70 kept: SI stays on what follows)
.e:     dec     si
        mov     byte [di], 0
        mov     [argp], si
        ret

is_wordend:                             ; ZF if AL ends a command word
        push    cx                      ;  (ES = CS)
        push    di
        mov     di, wordends
        mov     cx, 8
        repne   scasb
        pop     di
        pop     cx
        ret

builtins:
        db 'DIR', 0
        dw do_dir
        db 'TYPE', 0
        dw do_type
        db 'COPY', 0
        dw do_copy
        db 'DEL', 0
        dw do_del
        db 'ERASE', 0
        dw do_del
        db 'REN', 0
        dw do_ren
        db 'RENAME', 0
        dw do_ren
        db 'MD', 0
        dw do_md
        db 'MKDIR', 0
        dw do_md
        db 'RD', 0
        dw do_rd
        db 'RMDIR', 0
        dw do_rd
        db 'CD', 0
        dw do_cd
        db 'CHDIR', 0
        dw do_cd
        db 'SET', 0
        dw do_set
        db 'PATH', 0
        dw do_path
        db 'PROMPT', 0
        dw do_prompt
        db 'DATE', 0
        dw do_date
        db 'TIME', 0
        dw do_time
        db 'VOL', 0
        dw do_vol
        db 'TASKS', 0
        dw do_tasks
        db 'START', 0
        dw do_start
        db 'FG', 0
        dw do_fg
        db 'KILL', 0
        dw do_kill
        db 'PARK', 0
        dw do_park
        db 'UNPARK', 0
        dw do_unpark
builtins_pass:
        db 'WAIT', 0
        dw do_wait
        db 'ECHO', 0
        dw do_echo
        db 'REM', 0
        dw do_rem
        db 'CLS', 0
        dw do_cls
        db 'VER', 0
        dw do_ver
        db 'PAUSE', 0
        dw do_pause
        db 'IF', 0
        dw do_if
        db 'GOTO', 0
        dw do_goto
        db 'FOR', 0
        dw do_for
        db 'CALL', 0
        dw do_call
        db 'SHIFT', 0
        dw do_shift
        db 'CHOICE', 0
        dw do_choice
        db 'EXIT', 0
        dw do_exit
        db 0

; ---------------------------------------------------------------------
; programs: NAME[.COM|.EXE|.BAT] here or on the PATH
run_external:
        call    find_prog
        jnc     .found
        mov     byte [errlvl], 1
        mov     si, e_badcmd
        jmp     err
.found: cmp     byte [is_bat], 0
        je      .run
        jmp     bat_start
.run:   ; command tail: " args", FCBs from the first two
        call    mk_tail
        mov     si, tail + 1
        mov     di, fcb1
        mov     ax, 2901h
        int     21h
        mov     di, fcb2
        mov     ax, 2901h
        int     21h
        mov     word [epb], 0
        mov     word [epb+2], tail
        mov     [epb+4], cs
        mov     word [epb+6], fcb1
        mov     [epb+8], cs
        mov     word [epb+10], fcb2
        mov     [epb+12], cs
        mov     dx, prog
        mov     bx, epb
        mov     byte [child], 1
        mov     byte [crit_q], 0        ; (a program is asked each time)
        mov     byte [crit_seen], 0
        mov     [stack_seg], ss
        mov     [main_sp_run], sp
        mov     ax, 4B00h
        int     21h
        cli
        mov     ss, [cs:stack_seg]
        mov     sp, [cs:main_sp_run]
        sti
        cld
        push    cs
        pop     ds
        push    cs
        pop     es
        mov     byte [child], 0
        pushf
        push    ax
        call    set_dta                 ; (the parent's PSP:80h now)
        pop     ax
        popf
        jc      .fail
        mov     ah, 4Dh
        int     21h
        mov     [errlvl], al
        or      al, al
        jz      .x
        mov     byte [failed], 1
.x:     ret
.fail:  mov     byte [errlvl], 1
        cmp     byte [crit_seen], 0     ; a disk error while it loaded,
        je      .fe0                    ;  answered Fail or Abort here: said
        mov     byte [failed], 1        ;  already (its code 19-31, or 11
        ret                             ;  for a short read)
.fe0:   cmp     ax, 19                  ; else (MT's Fail behind, say) INT
        jb      .fm0                    ;  24h's message for its code
        cmp     ax, 31
        ja      .fm0
        xchg    ax, cx
        sub     cx, 19
        call    ce_msg
        jmp     .fm
.fm0:   mov     si, e_nomem
        cmp     ax, 8
        je      .fm
        mov     si, e_badcmd
.fm:    jmp     err

; a program's command tail: [argp]'s line (.t: after the CX characters
; already at DI), its count, CR
mk_tail:
        mov     di, tail + 1
        xor     cx, cx
.t:     mov     si, [argp]
        call    tcopy
        mov     [tail], cl
        mov     byte [di], 13
        ret

; the ASCIIZ at SI added to the tail at DI (CX characters so far, 126 kept)
tcopy:  lodsb
        or      al, al
        jz      .x
        cmp     cx, 126
        jae     tcopy
        stosb
        inc     cx
        jmp     tcopy
.x:     ret
        times   ($ + 1 - $$) & 1 db 90h ; (hot: odd here, so the hot labels after even)

; the program cword names, here or on the PATH -> prog (its path), is_bat;
; CF if there's none
find_prog:
        mov     si, cword
        mov     di, prog
        call    strcpy
        call    .ext                    ; a path given: only there
        cmp     bx, prog
        je      .dir
        jmp     try_exts
.dir:   call    try_exts                ; current directory, then the PATH
        jnc     .x
        push    es
        mov     si, s_pathv
        call    env_find
        pop     es
        jc      .x
        mov     [pathp], di
.pl:    mov     si, [pathp]
        call    env_seg                 ; one directory from the PATH
        mov     di, prog
        cmp     byte [es:si], 0
        je      .pe
.pc:    mov     al, [es:si]
        inc     si
        cmp     al, ';'
        je      .pd
        or      al, al
        jz      .pz
        mov     [di], al
        inc     di
        jmp     .pc
.pz:    dec     si
.pd:    push    cs
        pop     es
        mov     [pathp], si
        cmp     di, prog
        je      .pl
        cmp     byte [di-1], '\'
        je      .ps
        mov     al, '\'
        stosb
.ps:    mov     si, cword
        call    strcpy
        call    .ext
        call    try_exts
        jnc     .x
        jmp     .pl
.pe:    push    cs
        pop     es
        stc
.x:     ret
        times   ($ - $$) & 1 db 90h     ; (hot: even)
.ext:   mov     si, prog                ; extp, and BX its name part
        call    name_part               ; (on into find_ext)

; extp = after the '.' in the name at SI (0 if none)
find_ext:
        xor     dx, dx
.d:     lodsb
        or      al, al
        jz      .x
        cmp     al, '.'
        jne     .d
        mov     dx, si
        jmp     .d
.x:     mov     [extp], dx
        ret

; try prog as it is (if it has an extension) or with .COM .EXE .BAT
try_exts:
        cmp     word [extp], 0
        je      .add
        mov     si, [extp]
        mov     di, x_bat
        call    streqi
        mov     byte [is_bat], 1
        je      .test
        mov     byte [is_bat], 0
        mov     di, x_com
        call    streqi
        je      .test
        mov     di, x_exe
        call    streqi
        je      .test
        stc
        ret
.test:  mov     dx, prog                ; (keeps BX, SI)
        mov     ax, 4300h
        int     21h
        jc      .r
        test    cl, 18h
        jnz     .no
        clc
.r:     ret
.no:    stc
        ret
.add:   mov     si, prog
        call    strend
        mov     [extend], di
        mov     si, x_com               ; .COM, .EXE, .BAT in turn
.a:     mov     di, [extend]
        mov     al, '.'
        stosb
        mov     bx, si                  ; (BX: this one, SI: the next)
        call    strcpy
        call    .test
        jc      .an
        mov     byte [is_bat], 0
        cmp     bx, x_bat
        jne     .ok
        mov     byte [is_bat], 1
.ok:    clc
        ret
.an:    cmp     ax, 3                   ; (no directory, or a drive not
        je      .none                   ;  ready: one INT 24h, not three)
        cmp     bx, x_bat
        jb      .a
.none:  mov     di, [extend]
        mov     byte [di], 0
        stc
        ret

; ---------------------------------------------------------------------
; batch files: one line at a time from the file, %0-%9 from its command,
; %NAME% from the environment
bat_start:
        mov     dl, [echo]              ; ECHO as it was, for the end
        cmp     byte [bat_on], 1        ; (2: CALL, a level of its own)
        jne     .new
        mov     bx, [bat_h]             ; one batch runs another: replaced
        mov     ah, 3Eh                 ;  (ECHO at the end as the first
        int     21h                     ;  one found it)
        mov     byte [bat_on], 0
        mov     dl, [bat_echo]
.new:   push    dx
        mov     dx, prog
        mov     ax, 3D80h               ; (not inherited: a task START's keeps none)
        int     21h
        pop     dx
        jnc     .op
        mov     [echo], dl
        mov     byte [errlvl], 1
        mov     si, e_batch
        jmp     err
.op:    mov     [bat_h], ax
        mov     [bat_echo], dl
        mov     byte [bat_on], 1
        xor     ax, ax
        mov     [bat_line], ax
        mov     [bat_last], al
        mov     si, cword               ; its name, for errors
        call    name_part
        mov     di, bat_name
        mov     cx, 13
.nm:    lodsb
        stosb
        or      al, al
        loopnz  .nm
        mov     byte [di], 0
        ; %0 = the name as typed, %1.. the words after it
        mov     si, cword
        mov     di, bat_args
        call    strcpy
        mov     si, [argp]
        jmp     strcpy

; the batch file's next line into bat_raw (NUL-terminated), counted in
; bat_line.  CF at its end
bat_read:
        cmp     byte [bat_last], 0      ; (a ^Z ended the one before)
        jne     .end
        mov     bx, [bat_h]
        mov     dx, bat_raw
        mov     cx, LBUF
        mov     ah, 3Fh
        int     21h
        jc      .end
        or      ax, ax
        jz      .end
        inc     word [bat_line]
        ; up to the end of the line; seek back to the next one
        mov     cx, ax
        mov     si, bat_raw
        xor     dx, dx                  ; bytes used
.f:     cmp     dx, cx
        jae     .eol
        mov     al, [si]
        cmp     al, 1Ah
        je      .eof
        cmp     al, 13
        je      .cr
        cmp     al, 10
        je      .lf
        inc     si
        inc     dx
        jmp     .f
.eof:   mov     byte [si], 0
        mov     byte [bat_last], 1
        clc
        ret
.cr:    mov     byte [si], 0
        inc     dx
        cmp     dx, cx
        jae     .back
        cmp     byte [si+1], 10
        jne     .back
        inc     dx
        jmp     .back
.lf:    mov     byte [si], 0
        inc     dx
        jmp     .back
.eol:   mov     byte [si], 0
.back:  sub     cx, dx                  ; seek back over what wasn't used
        jz      .got
        mov     dx, cx
        neg     dx
        mov     cx, 0FFFFh
        mov     bx, [bat_h]
        mov     ax, 4201h
        int     21h
.got:   clc
        ret
.end:   stc
        ret

; run the batch file's next line (or end it)
bat_next:
        mov     byte [crit_q], 0        ; (each line asks again, as each
        call    bat_read                ;  typed one does: edit_line's .key)
        jc      bat_end
        mov     si, bat_raw             ; %n, %NAME% and %%
        mov     di, line
.s:     lodsb
        cmp     al, '%'
        jne     .st
        mov     al, [si]
        cmp     al, '%'
        je      .pp
        sub     al, '0'
        cmp     al, 9
        ja      .var
        inc     si
        call    bat_arg
        jmp     .s
.var:   call    bat_var
        jnc     .s
        mov     al, '%'                 ; (no second %: as it is)
        jmp     .st
.pp:    inc     si
        mov     al, '%'
.st:    stosb
        cmp     di, line + LBUF - 2
        jb      .s0
        dec     di
        mov     byte [di], 0
        jmp     .sd
.s0:    or      al, al
        jnz     .s
.sd:    ; echo it (unless ECHO OFF or @)
        mov     si, line
        call    skipsp
        cmp     byte [echo], 0
        je      .run
        cmp     byte [si], '@'
        je      .run
        cmp     byte [si], 0
        je      .run
        call    show_prompt
        call    puts_nl
.run:   mov     si, line
        jmp     do_line

; the batch file is done: closed, ECHO as it was before it
bat_end:
        cmp     byte [bat_on], 0
        je      .x
        mov     byte [bat_on], 0
        mov     al, [bat_echo]
        mov     [echo], al
        mov     bx, [bat_h]
        mov     ah, 3Eh
        int     21h
.x:     ret

; %NAME% at SI (past the first %): the variable's value at DI (nothing
; if there is none), SI past the second %.  CF if there is no second %
bat_var:
        mov     bx, si
.f:     mov     al, [bx]
        or      al, al
        jz      .no
        inc     bx
        cmp     al, '%'
        jne     .f
        push    di                      ; "NAME=" in upper case
        mov     di, setbuf2
.c:     lodsb
        cmp     al, '%'
        je      .e
        call    upcase
        stosb
        cmp     di, setbuf2 + 70
        jb      .c
.e:     mov     ax, '='
        stosw
        pop     di
        push    bx                      ; (past the second %)
        push    es
        push    di
        mov     si, setbuf2
        call    env_find
        mov     si, di
        pop     di
        jc      .x
.v:     mov     al, [es:si]
        inc     si
        or      al, al
        jz      .x
        cmp     di, line + LBUF - 4
        jae     .x
        mov     [di], al
        inc     di
        jmp     .v
.x:     pop     es
        pop     si
        clc
        ret
.no:    stc
        ret

; GOTO label: on from the line after ":label" (out of a FOR too)
do_goto:
        cmp     byte [bat_on], 1
        jne     .x
        cmp     byte [si], ':'
        jne     .l
        inc     si
.l:     call    getarg1
        mov     byte [for_stop], 1      ; (out of a FOR)
        push    word [bat_line]         ; (for the message)
        mov     bx, [bat_h]             ; from the top
        mov     al, 0
        call    seek
        xor     ax, ax
        mov     [bat_line], ax
        mov     [bat_last], al
.r:     call    bat_read
        jc      .nf
        mov     si, bat_raw
        call    skipsp
        lodsb
        cmp     al, ':'
        jne     .r
        mov     di, path2
        call    getarg
        mov     si, path1
        mov     di, path2
        call    streqi
        jne     .r
        pop     ax
.x:     ret
.nf:    pop     word [bat_line]
        mov     si, e_label
        call    err
        jmp     bat_end

; IF [NOT] ERRORLEVEL n | EXIST name | a==b  command
do_if:  mov     byte [if_not], 0
.w:     mov     [argp], si
        call    getarg1
        mov     bx, si                  ; (after the word)
        mov     si, path1
        mov     di, s_not
        call    streqi
        jne     .el
        xor     byte [if_not], 1
        mov     si, bx
        jmp     .w
.el:    mov     di, s_errlvl
        call    streqi
        jne     .ex
        mov     si, bx
        call    skipsp
        call    getnum
        or      ah, ah                  ; (over 255: never)
        jnz     .no
        cmp     [errlvl], al
        jae     .yes
        jmp     .no
.ex:    mov     di, s_exist
        call    streqi
        jne     .str
        mov     si, bx
        call    getarg1
        push    si                      ; (the command)
        mov     si, path1
        call    name_part
        mov     di, s_nul
        call    streqi
        jne     .xf
        mov     byte [si], 0            ; "dir\NUL": is dir a directory?
        cmp     si, path1               ; (NUL alone, X:NUL, X:\NUL, \NUL:
        je      .xy                     ;  yes; its \ off first)
        cmp     byte [si-1], '\'
        jne     .xd
        dec     si
        mov     byte [si], 0
        cmp     si, path1
        je      .xy
.xd:    cmp     byte [si-1], ':'
        je      .xy
        mov     dx, path1
        mov     ax, 4300h
        int     21h
        jc      .xn
        test    cl, 10h
        jz      .xn
.xy:    pop     si
        jmp     .yes
.xf:    mov     cx, 10h                 ; a file or a directory
        call    find1a
        jc      .xn
        pop     si
        jmp     .yes
.xn:    pop     si
        jmp     .no
.str:   mov     si, [argp]              ; "a==b"
        call    skipsp
        mov     di, si
.q:     mov     al, [di]
        or      al, al
        jz      .syn
        cmp     al, '='
        jne     .qn
        cmp     byte [di+1], '='
        je      .qe
.qn:    inc     di
        jmp     .q
.qe:    mov     dx, di                  ; DX: the end of the first
.tr:    cmp     dx, si
        jbe     .t2
        mov     bx, dx
        mov     al, [bx-1]
        call    is_blank
        jne     .t2
.td:    dec     dx
        jmp     .tr
.t2:    sub     dx, si                  ; DX: its length
        lea     bx, [di+2]
        xchg    si, bx                  ; SI: the second, BX: the first
        call    skipsp
        mov     di, si
.e2:    mov     al, [di]
        call    is_blank
        je      .e2d
        or      al, al
        jz      .e2d
        inc     di
        jmp     .e2
.e2d:   mov     cx, di
        sub     cx, si                  ; CX: the second's length
        push    di                      ; (the command after it)
        cmp     cx, dx
        jne     .ne
        mov     di, bx
        repe    cmpsb
.ne:    pop     si
        jne     .no
.yes:   mov     al, 1
        jmp     .c
.no:    xor     al, al
.c:     xor     al, [if_not]
        jz      .x
        call    skipsp
        jmp     run_cmd
.x:     ret
.syn:   jmp     err_syntax

; FOR %V IN (set) DO command: the command once for each item of the set
; (the names that match, for one with * or ?), the item in place of %V
do_for: cmp     byte [for_on], 0
        jne     .syn                    ; (not one inside another)
        lodsb
        cmp     al, '%'
        jne     .syn
        lodsb
        cmp     al, ' '
        jbe     .syn
        mov     [for_var], al
        call    getarg1
        push    si
        mov     si, path1
        mov     di, s_in
        call    streqi
        pop     si
        jne     .syn
        call    skipsp
        lodsb
        cmp     al, '('
        jne     .syn
        mov     [for_item], si          ; (for now: the set's start)
.p:     lodsb
        or      al, al
        jz      .syn
        cmp     al, ')'
        jne     .p
        mov     byte [si-1], 0
        call    getarg1
        push    si
        mov     si, path1
        mov     di, s_do
        call    streqi
        pop     si
        jne     .syn
        call    skipsp
        cmp     byte [si], 0
        je      .syn
        mov     [for_cmdp], si          ; (for now: the command's start)
        mov     bx, FB_PARAS            ; the set, the command and the DTA
        mov     ah, 48h                 ;  in a block of their own, out of
        int     21h                     ;  the way of the lines it runs and
        jnc     .m                      ;  only while it runs (L4)
        jmp     err_nomem
.m:     mov     [for_seg], ax
        mov     es, ax
        mov     di, FB_BUF
        mov     si, [for_item]
        call    strcpy
        inc     di
        mov     si, [for_cmdp]
        mov     [for_cmdp], di
        call    strcpy
        mov     byte [es:FB_ZERO], 0
        push    cs
        pop     es
        mov     byte [for_on], 1
        inc     byte [for_n]
        mov     byte [for_stop], 0
        mov     ds, [for_seg]           ; DS = the block (ours by cs:) till .done
        mov     si, FB_BUF
.item:  lodsb                           ; the next item
        or      al, al
        jz      .done
        call    is_delim
        je      .item
        dec     si
        mov     [cs:for_item], si
.ie:    lodsb
        or      al, al
        jz      .il
        call    is_delim
        jne     .ie
        mov     byte [si-1], 0
        jmp     .in
.il:    dec     si                      ; (the last one)
.in:    mov     [cs:for_next], si
        mov     si, [cs:for_item]
        call    has_wild
        jnc     .wild
        call    strlen
        mov     bx, FB_ZERO
        call    for_run
        jmp     .nx
.wild:  mov     dx, FB_DTA              ; (a DTA of its own: the commands
        mov     ah, 1Ah                 ;  use theirs)
        int     21h
        mov     dx, [cs:for_item]
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        jc      .nx
.wl:    mov     si, [cs:for_item]       ; its directory, the name found
        call    name_part
        mov     cx, si
        sub     cx, [cs:for_item]
        mov     bx, FB_DTA + 30
        call    for_run
        cmp     byte [cs:for_stop], 0
        jne     .done
        mov     dx, FB_DTA
        mov     ah, 1Ah
        int     21h
        mov     ah, 4Fh
        int     21h
        jnc     .wl
.nx:    cmp     byte [cs:for_stop], 0
        jne     .done
        mov     si, [cs:for_next]
        jmp     .item
.done:  push    cs
        pop     ds
        mov     byte [for_on], 0
        dec     byte [for_n]
        jmp     for_free
.syn:   jmp     err_syntax

; FOR's block given back, and the DTA ours again (DS = CS)
for_free:
        mov     es, [for_seg]
        mov     ah, 49h
        int     21h
        push    cs
        pop     es
set_dta:                                ; the DTA ours again (DS = CS)
        mov     dx, dta
        mov     ah, 1Ah
        int     21h
        ret

; ZF if AL separates FOR's items
is_delim:
        cmp     al, ','
        je      is_blank.y
        cmp     al, ';'
        je      is_blank.y
        cmp     al, '='
        je      is_blank.y
; ZF if AL is a space or a tab
is_blank:
        cmp     al, ' '
        je      .y
        cmp     al, 9
.y:     ret

; one turn of FOR: its command with %V as the item (CX bytes at
; [for_item], then the name at BX), built in line and run.  DS = FOR's
; block, as it is again after
        times   ($ + 1 - $$) & 1 db 90h ; (hot: odd here, so the hot labels after even)
for_run:
        mov     si, [cs:for_cmdp]
        mov     di, line                ; (the FOR's own line is in the block)
.c:     lodsb
        cmp     al, '%'
        jne     .s
        mov     ah, [cs:for_var]
        cmp     ah, [si]
        jne     .s
        inc     si
        push    si
        push    cx
        mov     si, [cs:for_item]
.i:     jcxz    .n
        lodsb
        call    .put
        dec     cx
        jmp     .i
.n:     mov     si, bx
.nl:    lodsb
        or      al, al
        jz      .nd
        call    .put
        jmp     .nl
.nd:    pop     cx
        pop     si
        jmp     .c
.s:     call    .put
        or      al, al
        jnz     .c
        push    cs
        pop     ds
        mov     byte [line + LBUF], 0   ; (cut short, it still ends)
        mov     si, line
        call    do_line
        mov     ds, [for_seg]
        ret
        times   ($ - $$) & 1 db 90h     ; (hot: even)
.put:   cmp     di, line + LBUF
        jae     .px
        stosb
.px:    ret

; CALL name args: a batch file runs to its end, then this one goes on (a
; program just runs).  This one's file, line, arguments and FOR wait in a
; block of their own
do_call:
        cmp     byte [cdepth], CMAX
        jb      .ok
        mov     si, e_deep
        jmp     err
.ok:    push    si
        mov     bx, (BATCTX + 15) / 16
        mov     ah, 48h
        int     21h
        pop     si
        jnc     .m
        jmp     err_nomem
.m:     mov     bl, [cdepth]
        xor     bh, bh
        shl     bx, 1
        mov     [call_segs + bx], ax
        inc     byte [cdepth]
        mov     es, ax                  ; this batch file's place, kept
        push    si
        mov     si, bat_ctx
        xor     di, di
        mov     cx, BATCTX
        rep     movsb
        push    cs
        pop     es
        pop     si
        mov     byte [bat_on], 2        ; (its errors still say where)
        mov     byte [for_on], 0        ; (it may have a FOR of its own)
        call    run_cmd
.l:     cmp     byte [bat_on], 1
        jne     .back
        call    bat_next
        jmp     .l
.back:  dec     byte [cdepth]
        mov     bl, [cdepth]
        xor     bh, bh
        shl     bx, 1
        mov     ax, [call_segs + bx]
        push    ds
        mov     ds, ax
        xor     si, si
        mov     di, bat_ctx
        mov     cx, BATCTX
        rep     movsb
        pop     ds
        mov     es, ax
        mov     ah, 49h
        int     21h
        push    cs
        pop     es
        ret

; SHIFT: %1 becomes %0, %2 %1 ...
do_shift:
        mov     si, bat_args
        call    skipsp
.w:     lodsb
        cmp     al, ' '
        ja      .w
        dec     si
        mov     di, bat_args
        jmp     strcpy

; CHOICE [/C[:]keys] [/N] [/S] [/T[:]c,nn] [text]: waits for one of the
; keys (Y and N without /C), shows it; ERRORLEVEL = its place (1, 2 ..).
; /N: no "[Y,N]?"; /S: upper and lower case differ; /T: c after nn seconds
do_choice:
        mov     word [ch_keys], s_yn
        xor     ax, ax
        mov     [ch_t], ax
        mov     [ch_n], ax              ; (and ch_s)
.a:     call    skipsp
        cmp     byte [si], '/'
        jne     .txt
        inc     si
        lodsb
        call    upcase
        cmp     byte [si], ':'
        jne     .o
        inc     si
.o:     cmp     al, 'C'
        jne     .on
        cmp     byte [si], ' '          ; (/C with no keys: none could
        jbe     .syn                    ;  answer it)
        mov     [ch_keys], si
.ck:    lodsb                           ; to the end of the keys
        cmp     al, ' '
        ja      .ck
        mov     byte [si-1], 0
        or      al, al
        jnz     .a
        dec     si
        jmp     .a
.on:    cmp     al, 'N'
        jne     .os
        mov     byte [ch_n], 1
        jmp     .a
.os:    cmp     al, 'S'
        jne     .ot
        mov     byte [ch_s], 1
        jmp     .a
.ot:    cmp     al, 'T'
        jne     .syn
        lodsb
        or      al, al                  ; ("/T" last)
        jz      .syn
        mov     [ch_def], al
        cmp     byte [si], ','
        jne     .syn
        inc     si
        call    getnum                  ; seconds -> ticks (18.2 a second)
        cmp     ax, 99                  ; (99 at most, as DOS's CHOICE)
        jbe     .t9
        mov     ax, 99
.t9:    mov     cx, 91
        mul     cx
        mov     cx, 5
        div     cx
        or      ax, ax
        jnz     .t
        inc     ax
.t:     mov     [ch_t], ax
        jmp     .a
.syn:   jmp     err_syntax
.txt:   call    puts
        cmp     byte [ch_n], 0
        jne     .w
        mov     al, '['                 ; "[Y,N]?"
        mov     si, [ch_keys]
.l:     call    putc
        lodsb
        call    ch_putc
        mov     al, ','
        cmp     byte [si], 0
        jne     .l
        mov     al, ']'
        call    putc
        mov     al, '?'
        call    putc
.w:     mov     al, [for_n]             ; (no saver in a FOR: DEFRAG could
        mov     [sv_req], al            ;  upset its search)
        mov     cx, [ch_t]
        call    wait_key
        jnc     .k
        mov     al, [ch_def]            ; (the time is up)
.k:     cmp     al, 3
        je      .brk
        cmp     al, 1Ah                 ; (the end of a file: no answer)
        je      .eof
        or      al, al
        jz      .w
        mov     dl, al                  ; which one?
        mov     si, [ch_keys]
        xor     bx, bx
.f:     lodsb
        or      al, al
        jz      .bad
        inc     bx
        cmp     al, dl
        je      .hit
        cmp     byte [ch_s], 0
        jne     .f
        call    upcase
        mov     ah, al
        mov     al, dl
        call    upcase
        cmp     al, ah
        jne     .f
.hit:   mov     al, [si-1]
        call    ch_putc
        call    crlf
        mov     [errlvl], bl
        ret
.bad:   mov     al, 7
        call    putc
        jmp     .w
.brk:   call    crlf
        mov     byte [errlvl], 0
        int     23h
        ret
.eof:   mov     byte [errlvl], 0
        jmp     crlf
; a key as CHOICE shows it: upper case, unless /S
ch_putc:
        cmp     byte [ch_s], 0
        jne     .p
        call    upcase
.p:     jmp     putc

; append batch argument AL (0-9) at DI
bat_arg:
        push    si
        mov     si, bat_args
        mov     ah, al
.w:     call    skipsp
        cmp     byte [si], 0
        je      .x
        or      ah, ah
        jz      .cp
.sk:    lodsb
        call    is_blank
        je      .nx
        or      al, al
        jnz     .sk
        jmp     .x
.nx:    dec     ah
        jmp     .w
.cp:    lodsb
        call    is_blank
        je      .x
        or      al, al
        jz      .x
        cmp     di, line + LBUF - 4
        jae     .x
        stosb
        jmp     .cp
.x:     pop     si
        ret

; ---------------------------------------------------------------------
; the command line into `line' (NUL-terminated).  From the keyboard with
; editing (Left, Right, Home, End, Backspace, Del, ESC clears), history
; (Up, Down, F3: the rest of the last line) and Tab completion of names
; (again: the next one); from a file or another device DOS's own.
; Only prompt_loop calls it: the history it writes lies over the start-up
; code, which /C still runs after its command
        times   ($ + 1 - $$) & 1 db 90h ; (hot: odd here, so the hot labels after even)
edit_line:
        mov     byte [crit_q], 0        ; (each line asks again: one read
        call    con_in                  ;  from a file too) the console?
        jc      .dos
        je      .ed
        jns     .dos                    ; a file at its end: this shell is
        mov     ax, 4406h               ;  done (unless it is the first)
        int     21h
        or      al, al
        jnz     .dos
        cmp     byte [perm], 0
        jne     .dos
        mov     al, [errlvl]
        mov     ah, 4Ch
        int     21h
.dos:   mov     al, LBUF - 2
        call    get_line
        mov     di, line
        jmp     strcpy
.ed:    mov     ah, 3                   ; where the line starts
        xor     bh, bh
        int     10h
        mov     [ed_row], dh
        mov     [ed_col], dl
        xor     ax, ax
        mov     [ed_len], ax            ; (and ed_pos)
        mov     [ed_old], al
        mov     [ed_tab], al
        mov     ax, [hist_end]
        mov     [hist_cur], ax
.key:   mov     byte [crit_q], 0        ; (Tab's looking done)
        mov     al, [ed_tab]            ; (no saver between Tabs: DEFRAG
        mov     [sv_req], al            ;  could upset the search)
        xor     cx, cx
        call    wait_key
        xor     bl, bl
        xchg    bl, [ed_tab]            ; BL: the key before was Tab
        mov     dl, [ed_pos]            ; DL: the cursor, DH: the length
        mov     dh, [ed_len]
        or      al, al
        jz      .ext
        cmp     al, 13
        je      .enter
        cmp     al, 8
        je      .bs
        cmp     al, 27
        je      .esc
        cmp     al, 9
        je      .tab
        cmp     al, 3
        je      .brk
        cmp     al, ' '
        jb      .key
        mov     cx, 1                   ; a character, in at the cursor
        call    ed_room
        jc      .beep
        mov     bl, dl
        xor     bh, bh
        mov     [line + bx], al
        inc     bl
        mov     [ed_pos], bl
.show:  call    ed_show                 ; (from DL on)
        jmp     .key
.beep:  mov     al, 7
        call    putc
        jmp     .key
.ext:   cmp     ah, 4Bh                 ; Left
        jne     .r
        or      dl, dl
        jz      .key
        dec     dl
.mv:    mov     [ed_pos], dl
        mov     al, dl
        call    ed_at
        jmp     .key
.r:     cmp     ah, 4Dh                 ; Right
        jne     .h
        cmp     dl, dh
        jae     .key
        inc     dl
        jmp     .mv
.h:     cmp     ah, 47h                 ; Home
        jne     .e
        xor     dl, dl
        jmp     .mv
.e:     cmp     ah, 4Fh                 ; End
        jne     .d
        mov     dl, dh
        jmp     .mv
.d:     cmp     ah, 53h                 ; Del
        jne     .u
        cmp     dl, dh
        jae     .key
.del:   mov     cx, 1
        call    ed_cut
        jmp     .show
.bs:    or      dl, dl
        jz      .key
        dec     dl
        mov     [ed_pos], dl
        jmp     .del
.esc:   xor     dl, dl
        mov     [ed_pos], dl
        mov     [ed_len], dl
        jmp     .show
.u:     cmp     ah, 48h                 ; Up: the line before
        jne     .dn
        mov     si, [hist_cur]
        cmp     si, hist
        jbe     .key
        call    hist_back
        mov     [hist_cur], si
        jmp     .get
.dn:    cmp     ah, 50h                 ; Down: the one after
        jne     .f3
        mov     si, [hist_cur]
        cmp     si, [hist_end]
        jae     .key
.db:    lodsb
        or      al, al
        jnz     .db
        mov     [hist_cur], si
.get:   mov     di, line                ; it in place of this one (past the
        cmp     si, [hist_end]          ;  newest: an empty line)
        jae     .gd
        call    strcpy
.gd:    xor     dl, dl                  ; (drawn from DL)
.gset:  mov     ax, di                  ; the line's end at DI
        sub     ax, line
        mov     [ed_len], al
        mov     [ed_pos], al
        jmp     .show
.f3:    cmp     ah, 3Dh                 ; F3: the rest of the last line
        jne     .key
        mov     si, [hist_end]
        cmp     si, hist
        jbe     .key
        call    hist_back
        mov     cl, dh                  ; past as much as is typed
        xor     ch, ch
.fk:    jcxz    .fc
        cmp     byte [si], 0
        je      .key
        inc     si
        dec     cx
        jmp     .fk
.fc:    mov     bl, dh
        xor     bh, bh
        lea     di, [line + bx]
.fl:    lodsb
        or      al, al
        jz      .fd
        cmp     di, line + LBUF - 2
        jae     .fd
        stosb
        jmp     .fl
.fd:    mov     dl, dh
        jmp     .gset
.brk:   mov     al, dh                  ; Ctrl-C: the line is dropped
        call    ed_at
        mov     si, s_ctrlc
        call    puts
        mov     byte [line], 0
        ret
.enter: mov     al, dh
        call    ed_at                   ; (the cursor after the line)
        mov     bl, dh
        xor     bh, bh
        mov     byte [line + bx], 0
        or      bl, bl
        jz      .x
        mov     si, [hist_end]          ; into the history, unless it is
        cmp     si, hist                ;  the last line again
        jbe     .add
        call    hist_back
        mov     di, line
        call    streq
        je      .x
.add:   mov     cx, bx
        inc     cx                      ; (with its NUL)
.fit:   mov     ax, [hist_end]
        add     ax, cx
        cmp     ax, hist + HIST
        jbe     .cp
        mov     si, hist                ; no room: the oldest goes
.o:     lodsb
        or      al, al
        jnz     .o
        mov     di, hist
        push    cx
        mov     cx, [hist_end]
        sub     cx, si
        rep     movsb
        pop     cx
        mov     [hist_end], di
        jmp     .fit
.cp:    mov     di, [hist_end]
        mov     si, line
        rep     movsb
        mov     [hist_end], di
.x:     ret
.tab:   mov     byte [crit_q], 1        ; (no INT 24h prompt in the line)
        or      bl, bl                  ; Tab again: the next name
        jnz     .tnext
        mov     bl, dl                  ; the word before the cursor
        xor     bh, bh
.tw:    or      bx, bx
        jz      .tf
        mov     al, [line + bx - 1]
        cmp     al, ' '
        je      .tf
        cmp     al, '>'
        je      .tf
        cmp     al, '<'
        je      .tf
        cmp     al, '|'
        je      .tf
        dec     bx
        jmp     .tw
.tf:    lea     si, [line + bx]         ; it and * (or *.*) as a pattern;
        mov     di, pat                 ;  its name part is what changes
        mov     [ed_ns], bl
        xor     ah, ah                  ; AH: a dot in the name part
.tc:    cmp     bl, dl
        jae     .te
        cmp     di, pat + 75            ; (a word too long: cut)
        jae     .te
        lodsb
        stosb
        inc     bl
        cmp     al, '.'
        jne     .t1
        mov     ah, 1
.t1:    cmp     al, '\'
        je      .t2
        cmp     al, ':'
        jne     .tc
.t2:    mov     [ed_ns], bl
        xor     ah, ah
        jmp     .tc
.te:    mov     al, '*'
        stosb
        or      ah, ah
        jnz     .t3
        mov     ax, '.*'
        stosw
.t3:    mov     byte [di], 0
        mov     byte [ed_wrap], 0
        call    set_dta
.tfirst:
        mov     dx, pat
        mov     cx, 10h
        mov     ah, 4Eh
.tfind: int     21h
        jc      .beep
.tdot:  cmp     byte [dta + 30], '.'    ; (not . and ..)
        je      .tskip
        mov     si, dta + 30            ; (nor a name with a space inside:
.tsp:   lodsb                           ;  the line would take it for two,
        or      al, al                  ;  and DEL or COPY hit the first)
        jz      .tput
        cmp     al, ' '
        jne     .tsp
.tskip: mov     ah, 4Fh
        int     21h
        jnc     .tdot
.twrap: cmp     byte [ed_wrap], 0       ; past the last: the first again
        jne     .beep                   ;  (once: every name left has a
        inc     byte [ed_wrap]          ;  space, or there is none)
        jmp     .tfirst
.tnext: call    set_dta
        mov     byte [ed_wrap], 0
        mov     ah, 4Fh
        int     21h
        jnc     .tdot
        jmp     .twrap
.tput:  mov     si, dta + 30            ; the name found, in place of the
        call    strlen                  ;  one typed (if it fits)
        test    byte [dta + 21], 10h    ; (a directory: with its \)
        jz      .t4
        inc     cx
.t4:    mov     dl, [ed_ns]
        mov     al, [ed_pos]
        sub     al, dl                  ; AL: what goes
        mov     ah, [ed_len]
        sub     ah, al
        add     ah, cl
        cmp     ah, LBUF - 2
        ja      .beep
        push    cx
        mov     cl, al
        xor     ch, ch
        call    ed_cut
        pop     cx
        call    ed_room
        mov     bl, dl
        xor     bh, bh
        lea     di, [line + bx]
.t5:    lodsb
        or      al, al
        jz      .t6
        stosb
        jmp     .t5
.t6:    test    byte [dta + 21], 10h
        jz      .t7
        mov     al, '\'
        stosb
.t7:    mov     ax, di
        sub     ax, line
        mov     [ed_pos], al
        mov     byte [ed_tab], 1
        jmp     .show
        times   ($ + 1 - $$) & 1 db 90h ; (hot: odd here, so .b on even)

; SI -> the start of the history line that ends just before it
hist_back:
        dec     si
.b:     cmp     si, hist
        jbe     .x
        cmp     byte [si-1], 0
        je      .x
        dec     si
        jmp     .b
.x:     ret

; room for CX characters at position DL of the line (CF: there isn't)
ed_room:
        pusha
        mov     bl, [ed_len]
        xor     bh, bh
        mov     ax, bx
        add     ax, cx
        cmp     ax, LBUF - 2
        ja      .no
        mov     [ed_len], al
        lea     si, [line + bx - 1]     ; the rest moves up, from its end
        mov     di, si
        add     di, cx
        sub     bl, dl
        mov     cx, bx
        std
        rep     movsb
        cld
        popa
        clc
        ret
.no:    popa
        stc
        ret

; CX characters out at position DL
ed_cut: pusha
        mov     bl, dl
        xor     bh, bh
        lea     di, [line + bx]
        mov     si, di
        add     si, cx
        mov     al, [ed_len]
        sub     al, cl
        mov     [ed_len], al
        sub     al, dl
        xor     ah, ah
        xchg    ax, cx
        rep     movsb
        popa
        ret

; the line drawn again from position DL on (spaces over what was longer
; before), the cursor to ed_pos.  When the screen scrolls the line's start
; goes up with it.
ed_show:
        mov     al, dl
        call    ed_at
        mov     cl, [ed_len]
        sub     cl, dl
        xor     ch, ch
        jcxz    .p
        xor     dh, dh
        add     dx, line
        mov     bx, 1
        mov     ah, 40h
        int     21h
.p:     mov     cl, [ed_old]
        sub     cl, [ed_len]
        jbe     .s
        xor     ch, ch
        mov     al, ' '
.sp:    call    putc
        loop    .sp
.s:     mov     al, [ed_old]            ; the cursor is past the longer of
        cmp     al, [ed_len]            ;  the two now: which row should
        jae     .m                      ;  that be?
        mov     al, [ed_len]
.m:     call    ed_rc
        push    dx
        mov     ah, 3
        xor     bh, bh
        int     10h
        pop     ax
        sub     ah, dh                  ; rows it scrolled
        jbe     .k
        sub     [ed_row], ah
.k:     mov     al, [ed_len]
        mov     [ed_old], al
        mov     al, [ed_pos]
; the cursor to position AL of the line
ed_at:  pusha
        call    ed_rc
        xor     bh, bh
        mov     ah, 2
        int     10h
        popa
        ret
; position AL of the line -> DH row, DL column
ed_rc:  xor     ah, ah
        add     al, [ed_col]
        adc     ah, 0
        mov     dl, 80
        div     dl
        add     al, [ed_row]
        mov     dh, al
        mov     dl, ah
        ret

; a key from standard input -> AL (0 for an extended key, its scan code
; in AH).  CX: ticks to wait at most (0: for ever, with the Executive's
; screen saver after its delay); CF if they pass first
wait_key:
        push    bx
        push    dx
        call    con_in                  ; standard input the console?
        jc      .con
        je      .con
        mov     ah, 7                   ; no: a file or another device,
        int     21h                     ;  read (^Z at a file's end)
        xor     ah, ah
        jmp     .r
.con:   call    tick
        mov     bx, ax                  ; BX: since when (the wait)
        mov     dx, ax                  ; DX: since when (the saver)
.w:     mov     ah, 0Bh
        int     21h
        or      al, al
        jnz     .k
        call    tick
        jcxz    .sv
        sub     ax, bx
        cmp     ax, cx
        jb      .z
        stc
        jmp     .x
.sv:    cmp     word [sv_t], 0FFFFh
        je      .z
        cmp     byte [sv_req], 0
        jne     .z
        sub     ax, dx
        cmp     ax, 8000h               ; (midnight)
        jae     .re
        cmp     ax, [sv_t]
        jb      .z
        call    run_saver
.re:    call    tick
        mov     dx, ax
.z:     sti
        hlt
        jmp     .w
        times   ($ - $$) & 1 db 90h     ; (hot: even)
.k:     mov     ah, 7
        int     21h
        xor     ah, ah
        or      al, al
        jnz     .r
        mov     ah, 7
        int     21h
        mov     ah, al
        xor     al, al
.r:     clc
.x:     pop     dx
        pop     bx
        ret

; standard input's device word (IOCTL): CF if DOS says no, else ZF if it
; is the console and SF clear if it is another device.  BX = 0
con_in: mov     ax, 4400h
        xor     bx, bx
        int     21h
        jc      .x
        and     dl, 81h
        xor     dl, 81h
.x:     ret

tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

; the Executive's screen saver (INT 21h F0h AL=5 told where), the text
; screen kept meanwhile in memory taken for it and put back, the key that
; ends it taken.  Text modes only
run_saver:
        pusha
        push    es
        call    mt_mine                 ; (with multitasking, only in front:
        jc      .on                     ;  behind, the screen isn't ours)
        cmp     al, ah
        jne     .x
.on:    mov     ah, 0Fh
        int     10h
        cmp     al, 3
        ja      .x
        mov     [sv_mode], al
        mov     ah, 3
        xor     bh, bh
        int     10h
        mov     [sv_pos], dx
        mov     [sv_shape], cx
        mov     bx, 4000 / 16
        mov     ah, 48h
        int     21h
        jc      .x
        mov     es, ax
        push    ds
        push    0B800h
        pop     ds
        xor     si, si
        xor     di, di
        mov     cx, 2000
        rep     movsw
        pop     ds
        mov     byte [sv_busy], 1       ; (Ctrl-C meanwhile: nothing)
        inc     byte [crit_q]           ; (no disk to look for DEFRAG on:
        push    ds                      ;  Fail, no prompt; put back after)
        push    es
        mov     ds, [sv_entry+2]        ; (DS, ES: the Executive's)
        push    ds
        pop     es
        call    far [cs:sv_entry]
        pop     es
        pop     ds
        dec     byte [crit_q]
        mov     byte [sv_busy], 0
        mov     al, [sv_mode]
        xor     ah, ah
        int     10h
        mov     bx, es
        push    ds
        mov     ds, bx
        push    0B800h
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 2000
        rep     movsw
        pop     ds
        mov     ax, 0F000h + MT_SCREEN  ; (put back by us: multitasking isn't
        int     21h                     ;  to take it as writing the screen)
        mov     es, bx
        mov     ah, 49h
        int     21h
        mov     cx, [sv_shape]
        mov     ah, 1
        int     10h
        mov     dx, [sv_pos]
        xor     bh, bh
        mov     ah, 2
        int     10h
        mov     dx, crit                ; our INT 24h (the Executive's now,
                                        ;  after a DEFRAG run)
        mov     ax, 2524h
        int     21h
.x:     pop     es
        popa
        ret

; the commonest messages (each on into err)
err_syntax:
        mov     si, e_syntax
        jmp     short err
err_notfound:
        mov     si, e_notfound
        jmp     short err
err_nomem:
        mov     si, e_nomem
        jmp     short err
err_create:
        mov     si, e_create
        jmp     short err
err_param:
        mov     si, e_param
; an error message SI: the command failed.  In a batch file "NAME line n: "
; comes first (NAME as it was called)
err:    pusha
        mov     byte [failed], 1
        cmp     byte [bat_on], 0
        je      .m
        mov     si, bat_name
        call    puts
        mov     si, s_line
        call    puts
        mov     ax, [bat_line]
        call    pu16
        mov     si, s_colon
        call    puts
.m:     popa
        call    puts_nl
        stc                             ; (CF: callers return it)
        ret

; COPY's and TYPE's buffer: free memory, BX paragraphs at most (or what
; there is) -> cb_seg, cb_len.  CF ("Insufficient memory") under 512 bytes
cbuf_get:
        mov     ah, 48h
        int     21h
        jnc     .ok
        cmp     bx, 32
        jb      .no
        mov     ah, 48h
        int     21h
        jc      .no
.ok:    mov     [cb_seg], ax
        shl     bx, 4
        and     bx, 0FE00h              ; whole sectors: every read and write
        mov     [cb_len], bx            ;  after the first starts on one
        ret
.no:    jmp     err_nomem
cbuf_free:
        push    es
        mov     es, [cb_seg]
        mov     ah, 49h
        int     21h
        pop     es
        mov     word [cb_seg], 0
        ret

; ---------------------------------------------------------------------
; DIR [path] [/W] [/P]
        times   ($ - $$) & 1 db 90h     ; (hot: even)
do_dir: xor     ax, ax
        mov     [dir_w], ax             ; (and dir_p)
        mov     [dir_lines], al
        mov     [path1], al
.a:     call    skipsp
        lodsb
        or      al, al
        jz      .ad
        cmp     al, '/'
        jne     .nm
        lodsb
        or      al, al                  ; ("DIR /": the end, X14)
        jz      .ad
        call    upcase
        cmp     al, 'W'
        jne     .ap
        mov     byte [dir_w], 1
        jmp     .a
.ap:    cmp     al, 'P'
        jne     .a
        mov     byte [dir_p], 1
        jmp     .a
.nm:    dec     si
        call    getarg1
        jmp     .a
.ad:    mov     si, path1
        mov     di, pat
        call    make_pattern
        jc      .nf                     ; (too long for pat: X26)
        mov     dl, [pat_drv]           ; no such drive: DOS's word, no
        call    drv_chk                 ;  header
        jc      vol_bad
        ; header
        call    crlf
        mov     dl, [pat_drv]
        call    show_volume
        mov     si, s_dirof
        call    puts
        mov     si, pat_dir
        call    puts_nl
        call    crlf
        mov     word [dir_n], 0
        mov     dx, pat
        mov     cx, 10h
        mov     ah, 4Eh
        int     21h
        jnc     .e
.nf:    jmp     err_notfound
.e:     inc     word [dir_n]
        cmp     byte [dir_w], 0
        jne     .wide
        call    dir_line
        call    dir_more
        jmp     .n
.wide:  mov     si, dta + 30
        call    put_83
        mov     ax, [dir_n]             ; five to a line
        mov     cl, 5
        div     cl
        or      ah, ah
        jnz     .ws
        call    crlf
        call    dir_more
        jmp     .n
.ws:    mov     si, s_sp4
        call    puts
.n:     mov     ah, 4Fh
        int     21h
        jnc     .e
        cmp     byte [dir_w], 0
        je      .t
        call    crlf
.t:     ; "  n File(s)  nnnnn bytes free"
        mov     ax, [dir_n]
        mov     cx, 9
        call    pu16w
        mov     si, s_files
        call    puts
        mov     dl, [pat_drv]
        inc     dl
        mov     ah, 36h
        int     21h
        mul     cx                      ; bytes per cluster
        mul     bx
        mov     cx, 10
        call    pu32w
        mov     si, s_free
        jmp     puts_nl

dir_more:
        cmp     byte [dir_p], 0
        je      .x
        inc     byte [dir_lines]
        cmp     byte [dir_lines], 23
        jb      .x
        mov     byte [dir_lines], 0
        mov     byte [sv_req], 1        ; (no saver in DIR's search)
        call    do_pause.p
.x:     ret

; "NAME     EXT     size  mm-dd-yy  hh:mmp"
dir_line:
        mov     si, dta + 30
        call    put_83
        test    byte [dta + 21], 10h
        jz      .f
        mov     si, s_dirtag
        call    puts
        jmp     .d
.f:     mov     ax, [dta + 26]
        mov     dx, [dta + 28]
        mov     cx, 9
        call    pu32w
.d:     mov     ax, [dta + 24]
        call    put_date
        mov     ax, [dta + 22]
        call    put_time
        jmp     crlf

; name at SI ("NAME.EXT") as "NAME     EXT" (12 columns)
put_83: mov     cx, 8
        mov     dl, '.'                 ; (DL: what ends a part; "." and
        cmp     [si], dl                ;  "..": only their NUL)
        jne     .nd
        mov     dl, 0
.nd:    call    .part
        mov     al, ' '
        call    putc
        cmp     byte [si], '.'          ; (after 8: the dot still there)
        jne     .ne
        inc     si
.ne:    mov     cx, 3
; up to CX characters of SI's part, to DL or its NUL (SI past DL), then
; spaces to CX
.part:  mov     al, [si]
        or      al, al
        jz      .pn
        inc     si
        cmp     al, dl
        je      .pn
        call    putc
        loop    .part
        ret
        times   ($ - $$) & 1 db 90h     ; (hot: even)
.pn:    mov     al, ' '
.pl:    call    putc
        loop    .pl
        ret

; DOS date AX -> "  mm-dd-yy"
put_date:
        call    sp2
        push    ax
        shr     ax, 5
        and     ax, 15
        call    pu2sp
        mov     al, '-'
        call    putc
        pop     ax
        push    ax
        and     ax, 31
        call    pu2z
        mov     al, '-'
        call    putc
        pop     ax
        shr     ax, 9
        add     ax, 80
        cmp     ax, 100
        jb      .y
        sub     ax, 100
.y:     jmp     pu2z
; DOS time AX -> "  hh:mmp"
put_time:
        call    sp2
        mov     cx, ax
        shr     ch, 3                   ; CH: the hour
        shr     ax, 5
        and     al, 63
        mov     cl, al                  ; CL: the minute
        mov     dl, 'a'
        cmp     ch, 12
        jb      .am
        mov     dl, 'p'
        sub     ch, 12
.am:    or      ch, ch
        jnz     .h
        mov     ch, 12
.h:     call    put_hm                  ; (keeps DX)
        mov     al, dl
        jmp     putc
; two spaces (keeps AX)
sp2:    push    ax
        mov     al, ' '
        call    putc
        call    putc
        pop     ax
        ret

; " Volume in drive A is NAME" / "has no label" for drive DL (0 = A)
show_volume:
        mov     [vol_drv], dl
        mov     si, s_volin
        call    puts
        mov     al, [vol_drv]
        add     al, 'A'
        call    putc
        inc     ax                      ; (A = 1)
        sub     al, 'A'
        mov     [vfcb + 7], al
        mov     dx, vfcb                ; the label's 11 characters as on
        mov     ah, 11h                 ;  the disk: an extended FCB's
        int     21h                     ;  search, as DOS's COMMAND
        or      al, al
        jnz     .none
        mov     si, s_is
        call    puts
        mov     si, dta + 8 + 11        ; (its trailing spaces off)
        mov     cx, 11
.t:     cmp     byte [si-1], ' '
        jne     .p
        dec     si
        loop    .t
.p:     mov     si, dta + 8
        jcxz    .d
.l:     lodsb
        call    putc
        loop    .l
.d:     jmp     crlf
.none:  mov     si, s_nolabel
        jmp     puts_nl

; the pattern for path SI -> DI (pat), plus pat_drv and pat_dir
; ("X:\DIR" for the header).  A directory gets \*.*, a bare name .*.
; CF if that is longer than pat takes
make_pattern:
        push    di
        call    strcpy
        pop     di
        mov     si, di
        call    drv_of
        mov     [pat_drv], al
        mov     si, di
        call    dir_all                 ; a directory: \*.* added
        jnc     .hdr
.file:  ; no extension in the name part: NAME.*
        mov     si, pat
        call    name_part
        call    find_ext                ; (DX: its extension; SI past the NUL)
        or      dx, dx
        jnz     .hdr
        lea     di, [si - 1]
        mov     si, s_dotstar
        call    strcpy
.hdr:   ; the directory part, made absolute
        mov     si, pat
        call    strlen                  ; (CF: the pattern doesn't fit pat
        cmp     cx, 79                  ;  with its NUL.  What ran on is in
        ja      .long                   ;  pat_dir, which canon then writes)
        call    name_part
        mov     [tmpw], si
        mov     al, [si]
        push    ax
        mov     byte [si], 0
        mov     si, pat
        mov     di, pat_dir
        call    canon
        mov     si, [tmpw]
        pop     ax
        mov     [si], al
        clc
        ret
.long:  stc
        ret

; the drive of path SI -> AL (0 = A; the current one if it names none), SI
; past its "X:"
drv_of: mov     ah, 19h
        int     21h
        cmp     byte [si], 0            ; ("": what follows its NUL is old)
        je      .x
        cmp     byte [si+1], ':'
        jne     .x
        lodsb
        call    upcase
        sub     al, 'A'
        inc     si
.x:     ret

; path SI: a directory (or a drive, or nothing) gets \*.* at its end, DI
; after it.  CF if it isn't one (nothing added)
dir_all:
        call    is_dir
        jc      .x
        call    strend
        call    add_bslash
        mov     si, s_all
        jmp     strcpy                  ; (CF clear)
.x:     ret

; a '\' at DI, the end of path SI, unless it ends in '\' or ':' (or is "")
add_bslash:
        cmp     di, si
        je      .x
        cmp     byte [di-1], '\'
        je      .x
        cmp     byte [di-1], ':'
        je      .x
        mov     al, '\'
        stosb
.x:     ret

; CF clear if path SI is a directory (or a drive).  Keeps SI, DI
is_dir: push    di
        cmp     byte [si], 0
        je      .y
        push    si
        call    strend
        pop     si
        mov     al, [di-1]
        cmp     al, '\'
        je      .y
        cmp     al, ':'
        je      .y
        cmp     al, '.'                 ; ".", "..", "X\.", "X\.."
        jne     .a
        lea     bx, [di-1]
        cmp     bx, si
        je      .y
        mov     al, [di-2]
        cmp     al, '.'
        je      .y
        cmp     al, '\'
        je      .y
        cmp     al, ':'
        je      .y
.a:     call    has_wild
        jnc     .n
        mov     dx, si
        mov     ax, 4300h
        int     21h
        jc      .n
        test    cl, 10h
        jz      .n
.y:     pop     di
        clc
        ret
.n:     pop     di
        stc
        ret

; CF clear if SI has * or ?
has_wild:
        push    si
.l:     lodsb
        or      al, al
        jz      .no
        cmp     al, '*'
        je      .y
        cmp     al, '?'
        jne     .l
.y:     pop     si
        clc
        ret
.no:    pop     si
        stc
        ret

; SI -> the name part of the path at SI (after the last \ or :)
name_part:
        mov     bx, si
.l:     lodsb
        or      al, al
        jz      .x
        cmp     al, '\'
        je      .s
        cmp     al, ':'
        jne     .l
.s:     mov     bx, si
        jmp     .l
.x:     mov     si, bx
        ret

; path SI -> DI as "X:\DIR\NAME", with . and .. worked out
canon:  push    di
        push    bx
        call    drv_of
        mov     dl, al
        add     al, 'A'
        stosb
        mov     al, ':'
        stosb
        mov     al, '\'
        stosb
        mov     [canon_root], di
        cmp     byte [si], '\'
        je      .abs
        push    si                      ; relative: from the current directory
        mov     si, di
        mov     byte [si], 0            ; (none if 47h fails, on a drive that
        inc     dl                      ;  isn't there: not what was left)
        mov     ah, 47h
        int     21h
        call    strend                  ; (DI -> its NUL)
        pop     si
        jmp     .comp
.abs:   inc     si
.comp:  ; DI = end of what we have (no trailing \ except the root)
.c:     cmp     byte [si], 0
        je      .done
        cmp     byte [si], '\'
        jne     .w
        inc     si
        jmp     .c
.w:     cmp     byte [si], '.'
        jne     .name
        cmp     byte [si+1], '.'
        je      .up
        mov     al, [si+1]
        or      al, al
        jz      .dot
        cmp     al, '\'
        jne     .name
.dot:   inc     si
        jmp     .c
.up:    add     si, 2
.ub:    cmp     di, [canon_root]
        jbe     .c
        dec     di
        cmp     byte [di], '\'
        jne     .ub
        cmp     di, [canon_root]
        jae     .c
        inc     di
        jmp     .c
.name:  cmp     di, [canon_root]
        je      .n1
        mov     al, '\'
        stosb
.n1:    mov     bx, 8                   ; (each part cut to 8.3, a dot
.n2:    lodsb                           ;  last dropped: as the kernel
        or      al, al                  ;  reads it, so COPY's "onto
        jz      .ne                     ;  itself" sees the same file
        cmp     al, '\'                 ;  however spelled)
        je      .ne
        cmp     al, '.'
        jne     .nc
        or      bh, bh
        jnz     .nc
        mov     bx, 103h                ; (the extension: 3)
        stosb
        jmp     .n2
.nc:    or      bl, bl
        jz      .n2
        dec     bl
        call    upcase
        stosb
        jmp     .n2
.ne:    cmp     byte [di-1], '.'
        jne     .nd
        dec     di
.nd:    or      al, al
        jnz     .c
.dn:    dec     si
.done:  cmp     di, [canon_root]        ; "X:\" keeps its backslash
        ja      .t
        mov     di, [canon_root]
.t:     mov     byte [di], 0
        pop     bx
        pop     ax
        ret

; ---------------------------------------------------------------------
; TYPE file
do_type:
        call    getarg1
        jne     .o
        jmp     err_param
.o:     mov     dx, path1
        mov     ax, 3D00h
        int     21h
        jnc     .r
        jmp     err_notfound
.r:     mov     [fh1], ax
        mov     bx, 512 / 16            ; (512 bytes a read: a bad sector
        call    cbuf_get                ;  loses no more of the text)
        jc      .c
        mov     word [fh2], 1           ; to standard output (not closed),
        mov     byte [zstop], 1         ;  up to a ^Z whatever the file
        call    pump                    ; (an error ends it, unsaid)
        call    cbuf_free
.c:     jmp     close1

; ---------------------------------------------------------------------
; COPY src[+src...] [dst] [/A] [/B]: wildcards; to a directory; several
; files into one.  As MS-DOS's: one plain destination file and a source
; with wildcards or a "+" list is concatenation: one destination, kept
; open through the list, each source's name shown, ASCII by default (each
; source up to its first ^Z, one ^Z at the end, none to a device) and
; "1 File(s) copied"; one that came out empty is deleted, 0.  The
; destination as the first source is kept, cut at its first ^Z in ASCII,
; and the rest appended; met later, after the copy made it, "Content of
; destination lost before copy" and the rest go on.  "+" to no destination,
; or a directory: the first source's name (there; one with wildcards then
; is "Syntax error": MS-DOS pairs such names, not done here); to a name
; with wildcards: that name made once, from the first source.  A "+" part
; not there is passed over without a word.  "COPY A+" is onto itself;
; "COPY /B A+,," gives A the date and time of now.  A single copy is
; binary unless /A.  /A and /B are by position: each for the source it is
; next to and those after it, and for the destination when given with it
; or after it.  On an error while appending, the destination is cut back
; to where that source began, its ^Z put back, and kept if it was there
; before the command (MS-DOS deletes it on a write error); one this copy
; made is deleted.  The count is of destinations closed whole.
do_copy:
        xor     ax, ax
        mov     [copied], ax
        mov     di, dstate              ; (dstate to touch: 0)
        mov     cx, touch + 1 - dstate
        rep     stosb
        call    cparse                  ; -> plist, plus, path2, dsw, touch
        jnc     .p1
        jmp     err
.p1:    mov     si, plist
        call    next_src
        cmp     byte [path1], 0         ; (no first source)
        jne     .p2
.par:   jmp     err_param
.p2:    cmp     byte [plus], 0
        jne     .sf
        ; the source: a directory means all of it
        mov     si, path1
        call    dir_all
.sf:    ; the destination: a directory (or nothing: here)
        mov     byte [dst_dir], 1
        cmp     byte [path2], 0
        je      .dd
        mov     si, path2
        call    is_dir
        jnc     .dd
        mov     byte [dst_dir], 0
.dd:    cmp     byte [plus], 0
        je      .cm
        cmp     byte [dst_dir], 0       ; "+" to here or a directory: the
        je      .cc                     ;  first source's name there
        mov     si, path1
        call    has_wild
        jnc     .syn
        mov     si, path2
        call    strend
        cmp     di, path2
        je      .p3
        mov     si, path2
        call    add_bslash
.p3:    mov     si, path1
        call    name_part
        call    strcpy
        mov     byte [dst_dir], 0
        jmp     short .cc
.syn:   jmp     err_syntax
.cm:    cmp     byte [dst_dir], 0       ; one plain file from wildcards:
        jne     .ab                     ;  concatenation too
        mov     si, path2
        call    has_wild
        jnc     .ab
        mov     si, path1
        call    has_wild
        jc      .ab
.cc:    mov     byte [cmode], 1
.ab:    mov     bx, 0FFFh
        call    cbuf_get
        jc      .x
.src:   call    find1                   ; each source in the list
        jnc     .one
        ; a device (COPY CON FILE)?
        mov     dx, path1
        mov     ax, 3D00h
        int     21h
        jc      .nf
        xchg    bx, ax
        call    isdev
        mov     ah, 3Eh
        int     21h
        or      dl, dl
        jz      .nf
        mov     di, src
        call    dir_of                  ; (the whole name: BX its name part)
        call    copy_one
        jc      .err
        jmp     short .next
.nf:    cmp     byte [plus], 0          ; (a part of a list: passed over, as
        jne     .next                   ;  MS-DOS's)
        mov     si, e_notfound
        call    err
        jmp     cbuf_free
.one:   call    src_found               ; dir part of path1 + found name
        cmp     di, src + 79            ; (longer: skipped)
        ja      .nx
        call    copy_one
        jc      .err
.nx:    mov     ah, 4Fh
        int     21h
        jnc     .one
.next:  mov     si, [pnext]             ; the list's next source
        cmp     byte [si], 0
        je      .end
        call    next_src
        cmp     byte [path1], 0
        je      .next
        jmp     .src
.err:   mov     byte [dstate], 0        ; (its files closed, its count made)
.end:   cmp     byte [cmode], 0
        je      .tot
        call    cat_end
.tot:   mov     ax, [copied]
        mov     cx, 9
        call    pu16w
        mov     si, s_copied
        call    puts_nl
        jmp     cbuf_free
.x:     ret

; COPY's command tail at SI (dsw, touch and plus 0) -> plist (the sources, "+" between them, the
; /A or /B of each kept by it, as is one before the first or before the
; destination: with the source it follows), path2 (the destination) and
; dsw (its switch: with it or after it); touch: "+,,".  CF: SI = message
; (a name longer than 79, a word past the destination)
cparse: call    plus_join               ; ("a + b": "a+b")
        mov     di, plist
        xor     bx, bx                  ; BX: the name's length so far
        xor     dl, dl                  ; DL: the last but switches
.l:     lodsb                           ; the list
        or      al, al
        jz      .z
        call    is_blank
        je      .b
        cmp     al, ','
        je      .b
        cmp     al, '/'
        je      .sw
        cmp     al, '+'
        jne     .ch
        mov     [plus], al              ; (not 0: a "+" list)
        xor     bx, bx
        jmp     short .st
.ch:    inc     bx
        cmp     bx, 79
        ja      .long
.st:    cmp     di, plist + LBUF
        jae     .long
        mov     dl, al
        stosb
        jmp     .l
.sw:    lodsb                           ; a switch: kept, by its source
        or      al, al
        jz      .z
        mov     byte [di], '/'
        inc     di
        stosb
        jmp     .l
.b:     dec     si                      ; blanks and commas: past them
.bl:    lodsb
        cmp     al, ','                 ; (after "+": the date of now)
        jne     .b1
        cmp     dl, '+'
        jne     .bl
        mov     byte [touch], 1
        jmp     .bl
.b1:    call    is_blank
        je      .bl
        dec     si
        or      al, al                  ; the list goes on: none in it yet,
        jz      .z                      ;  a "+" last, or a switch next
        cmp     al, '/'
        je      .l
        or      dl, dl
        jz      .l
        cmp     dl, '+'
        je      .l
        mov     byte [di], 0            ; the destination
        mov     di, path2
.d:     lodsb
        cmp     al, ' '
        jbe     .de
        cmp     al, ','
        je      .de
        cmp     al, '/'
        jne     .ds
        call    .dsw
        jmp     .d
.ds:    stosb
        jmp     .d
.de:    mov     byte [di], 0
        dec     si
.r:     lodsb                           ; past it: switches only
        or      al, al
        jz      .ok
        call    is_blank
        je      .r
        cmp     al, ','
        je      .r
        cmp     al, '/'
        jne     .many
        call    .dsw
        jmp     .r
.z:     mov     byte [di], 0
        mov     byte [path2], 0
.ok:    clc
        ret
.long:  mov     si, e_plong
        stc
        ret
.many:  mov     si, e_pmany
        stc
        ret
.dsw:   lodsb                           ; the destination's /A or /B
        or      al, al
        jz      .dz
        call    upcase
        cmp     al, 'A'
        je      .dn
        cmp     al, 'B'
        jne     .dx
.dn:    mov     [dsw], al
.dx:    ret
.dz:    dec     si
        ret

; the list's source at SI (up to a "+" or its end) -> path1, its /A or
; /B (or the last before it) in smode; [pnext] past it
next_src:
        mov     di, path1
.l:     lodsb
        or      al, al
        jz      .z
        cmp     al, '+'
        je      .e
        cmp     al, '/'
        je      .sw
        stosb
        jmp     .l
.sw:    lodsb                           ; (cparse kept the letter with it)
        call    upcase
        cmp     al, 'A'
        je      .n
        cmp     al, 'B'
        jne     .l
.n:     mov     [smode], al
        jmp     .l
.z:     dec     si
.e:     mov     byte [di], 0
        mov     [pnext], si
        ret

; the command tail at SI: blanks before or after a "+" dropped, in place
; (SI kept)
plus_join:
        push    si
        mov     di, si
        mov     dx, si
.l:     lodsb
        call    is_blank
        je      .sp
.st:    stosb
        or      al, al
        jnz     .l
        pop     si
        ret
.sp:    mov     bx, si                  ; past the blanks: a "+" next?
.sk:    cmp     byte [bx], ' '
        je      .sn
        cmp     byte [bx], 9
        jne     .se
.sn:    inc     bx
        jmp     .sk
.se:    cmp     byte [bx], '+'
        je      .dr
        cmp     di, dx                  ; or one just before them?
        je      .st
        cmp     byte [di-1], '+'
        jne     .st
.dr:    mov     si, bx
        jmp     .l

; AL = 1 if this source is read as ASCII (to its first ^Z): its /A, or
; with no /A or /B so far concatenation's default
s_ascii:
        mov     al, [smode]
        or      al, al
        jz      d_ascii.c
        jmp     short d_ascii.m
; AL = 1 if the destination is written as ASCII (a ^Z at its end): its own
; /A or /B, or the sources' last, or concatenation's default
d_ascii:
        mov     al, [dsw]
        or      al, al
        jnz     .m
        mov     al, [smode]
        or      al, al
        jnz     .m
.c:     mov     al, [cmode]
        ret
.m:     sub     al, 'B'                 ; 'A' -> 1, 'B' -> 0
        neg     al
        ret

; the destination's ^Z (ASCII; none to a device).  CF: SI = e_full
zend:   call    d_ascii
        or      al, al
        jz      .x
        mov     bx, [fh2]
        call    isdev
        jnz     .x
        mov     byte [zbyte], 1Ah
        mov     dx, zbyte
        mov     cx, 1
        mov     ah, 40h
        int     21h
        mov     si, e_full
        jc      .r
        dec     ax
        jz      .x
        stc
.r:     ret
.x:     clc
        ret

; the end of a concatenation: its ^Z and close; empty (one it made): it
; deleted, 0; the destination only the first source: "onto itself", or
; with "+,," its date and time now
cat_end:
        mov     al, [dstate]
        or      al, al
        jz      .x
        mov     dx, dst
        cmp     al, 2
        je      .kept
        mov     bx, [fh2]               ; made, or kept and appended to
        cmp     al, 1
        jne     .z
        call    isdev                   ; (made: empty?  A device never)
        jnz     .z
        mov     al, 1
        call    seek
        or      ax, dx
        jnz     .z
        mov     ah, 3Eh
        int     21h
        mov     dx, dst
        mov     ah, 41h
        int     21h
        jmp     short .x
.z:     call    zend
        jnc     .c
        call    err
        dec     word [copied]           ; (not whole: 0)
.c:     inc     word [copied]
        mov     bx, [fh2]
        mov     ah, 3Eh
        int     21h
.x:     ret
.kept:  cmp     byte [touch], 0
        jne     .t
        mov     si, e_self
        jmp     err
.t:     mov     ax, 3D02h               ; "+,,": written, nothing changed,
        int     21h                     ;  so closed with the date of now
        jc      .te
        xchg    bx, ax
        call    seek_end
        xor     cx, cx
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
        inc     word [copied]
        ret
.te:    jmp     err_create

; copy src (BX: its name part) to its destination.  CF to stop (the
; files closed; in concatenation, the destination as said above)
copy_one:
        mov     [srcname], bx
        ; destination name
        mov     di, dst
        mov     si, path2
        call    strcpy
        cmp     byte [dst_dir], 0
        je      .df
        mov     si, dst
        call    add_bslash
        mov     si, [srcname]
        call    strcpy
        jmp     .dok
.df:    mov     si, path2
        call    has_wild
        jc      .dok
        mov     si, dst                 ; wildcards: map the name
        call    name_part
        mov     di, si
        mov     bx, [srcname]
        call    wild_map
        cmp     byte [cmode], 0         ; (concatenation: that name for the
        je      .dok                    ;  whole list, as MS-DOS's)
        mov     si, dst
        mov     di, path2
        call    strcpy
.dok:   ; not onto itself
        mov     si, src
        mov     di, canon1
        call    canon
        mov     si, dst
        mov     di, canon2
        call    canon
        mov     si, canon1
        mov     di, canon2
        call    streq
        jne     .go
        cmp     byte [cmode], 0
        jne     .cat
        mov     si, e_self
        jmp     err
.cat:   mov     si, src                 ; concatenation, the destination:
        call    puts_nl                 ;  first, kept, the rest after it;
        mov     al, [dstate]            ;  made already, what it held is
        cmp     al, 1                   ;  gone, as MS-DOS says
        je      .lost
        or      al, al
        jnz     .ret
        mov     byte [dstate], 2
        call    s_ascii
        mov     [kascii], al
.ret:   clc
        ret
.lost:  mov     si, e_dlost
        call    puts_nl
        clc
        ret
.go:    cmp     byte [cmode], 0         ; show the name for wildcards and
        jne     .sh                     ;  concatenation
        mov     si, path1
        call    has_wild
        jc      .q
.sh:    mov     si, src
        call    puts_nl
.q:     mov     dx, src
        mov     ax, 3D00h
        int     21h
        jnc     .so
        jmp     err_notfound
.so:    mov     [fh1], ax
        cmp     byte [cmode], 0
        je      .new
        mov     al, [dstate]            ; concatenation: the destination
        cmp     al, 2                   ;  made, kept (opened now: cut at
        je      .kopen                  ;  its first ^Z in ASCII), or open
        or      al, al
        jnz     .apos
.new:   mov     dx, dst
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .cfail
.dop:   mov     [fh2], ax
        cmp     byte [cmode], 0
        je      .loop
        mov     byte [dstate], 1
        jmp     short .apos
.kopen: mov     dx, dst
        mov     ax, 3D02h
        int     21h
        jnc     .ko
.cfail: call    close1                  ; (a kept one never made afresh)
        jmp     err_create
.ko:    mov     [fh2], ax
        mov     byte [dstate], 3
        cmp     byte [kascii], 0
        jne     .kz
        mov     bx, ax
        call    seek_end
        jmp     short .apos
.kz:    call    zcut
        jnc     .apos
        call    err                     ; (nothing changed in it: closed)
        call    close2
        stc
        ret
.apos:  mov     bx, [fh2]               ; where this source begins
        mov     al, 1
        call    seek
        mov     [apos], ax
        mov     [apos + 2], dx
.loop:  mov     bx, [fh1]               ; a device's text ends at a ^Z, and
        call    isdev                   ;  in ASCII a file's
        call    s_ascii
        or      dl, al
        mov     [zstop], dl
        call    pump
        jc      .err
        cmp     byte [cmode], 0
        je      .one
        call    close1                  ; (concatenation: the destination
        clc                             ;  stays open)
        ret
.one:   call    zend
        jc      .err
        cmp     byte [zstop], 0         ; keep the source's date and time
        jne     .cl                     ;  (a binary copy)
        call    d_ascii
        or      al, al
        jnz     .cl
        mov     bx, [fh1]
        mov     ax, 5700h
        int     21h
        mov     bx, [fh2]
        mov     ax, 5701h
        int     21h
.cl:    call    close2
        inc     word [copied]
        clc
        ret
.err:   call    err
        mov     byte [crit_q], 0        ; (the partial copy's close and
        cmp     byte [cmode], 0         ;  delete ask again: a Retry there
        je      .del                    ;  leaves no lost clusters)
        mov     bx, [fh2]               ; concatenation: back to where this
        call    zcut.cut                ;  source began
        cmp     byte [dstate], 1
        je      .del
        call    zend                    ; there before: its ^Z back, kept
        call    close2
        mov     word [copied], 0
        stc
        ret
.del:   call    close2
        mov     dx, dst
        mov     ah, 41h
        int     21h
        cmp     byte [cmode], 0
        je      .dx
        mov     word [copied], 0
.dx:    stc
        ret

; a kept destination at fh2 (at its start): to its first ^Z, cut there (as
; MS-DOS reads it in ASCII), or to its end.  CF: SI = what went wrong
zcut:   xor     ax, ax
        mov     [apos], ax
        mov     [apos + 2], ax
        mov     bx, [fh2]
.r:     call    cb_read
        jc      .x
        or      ax, ax                  ; (its end: CF clear)
        jz      .x
        mov     cx, ax
        call    cb_z
        pushf
        add     [apos], cx
        adc     word [apos + 2], 0
        popf
        jne     .r
.cut:   mov     dx, [apos]              ; BX cut at apos (copy_one's .err too)
        mov     cx, [apos + 2]
        mov     ax, 4200h
        int     21h
        xor     cx, cx                  ; (cut there)
        mov     ah, 40h
        int     21h
        mov     si, e_full
.x:     ret

        times   ($ - $$) & 1 db 90h     ; (hot: pump.l even)
; pump: [fh1] into [fh2], [cb_len] bytes a read through cb_seg, up to its
; end or, when [zstop], a ^Z (COPY from a device, TYPE).  CF: SI = what
; went wrong (a read failed; a write came short: the disk is full)
pump:
.l:     mov     bx, [fh1]
        call    cb_read
        jc      .x
        or      ax, ax                  ; (CF clear)
        jz      .x
        mov     cx, ax
        mov     byte [tmpb], 0
        cmp     byte [zstop], 0
        je      .w
        call    cb_z
        jne     .w
        inc     byte [tmpb]             ; (up to the ^Z: the last write)
.w:     push    cx
        mov     bx, [fh2]
        mov     ah, 40h
        call    cb_io
        pop     cx
        mov     si, e_full
        jc      .x
        cmp     ax, cx
        jne     .short
        cmp     byte [tmpb], 0          ; (CF clear: 0 or 1 less 0)
        je      .l
.x:     ret
.short: stc
        ret

; BX's next [cb_len] bytes into the buffer -> AX (CF: SI = e_read)
cb_read:
        mov     si, e_read
        mov     cx, [cb_len]
        mov     ah, 3Fh
; INT 21h AH (3Fh, 40h) with the buffer, BX and CX
cb_io:  push    ds
        mov     ds, [cb_seg]
        xor     dx, dx
        int     21h
        pop     ds
        ret
; the first ^Z in the buffer's first CX bytes: ZF, CX the bytes before it
; (else CX kept)
cb_z:   push    es
        mov     es, [cb_seg]
        xor     di, di
        mov     al, 1Ah
        push    cx
        repne   scasb
        pop     cx
        pop     es
        jne     .x
        lea     cx, [di - 1]
.x:     ret

; DL = 80h, ZF clear, if BX is a device (else 0, ZF)
isdev:  mov     ax, 4400h
        int     21h
        and     dl, 80h
        ret

; BX's file pointer to its end, or (seek) AL = 0 its start, 1 where it is
; -> DX:AX
seek_end:
        mov     al, 2
seek:   mov     ah, 42h
        xor     cx, cx
        xor     dx, dx
        int     21h
        ret

close2: mov     bx, [fh2]               ; COPY's and TYPE's files closed
        mov     ah, 3Eh
        int     21h
close1: mov     bx, [fh1]
        mov     ah, 3Eh
        int     21h
        ret

; name DI (in place, a pattern "*.BAK" etc.) from pattern at DI and the
; name at BX: '?' and '*' take the source's characters
wild_map:
        push    di
        mov     si, di
        mov     di, fcbp
        mov     ax, 2900h
        int     21h
        mov     si, bx                  ; the name as its 11 bytes, spaces
        mov     di, fcbs + 1            ;  inside kept (29h stops at one)
        call    to11
        pop     di
        mov     cx, 11
        xor     bx, bx
.m:     mov     al, [fcbp + 1 + bx]
        cmp     al, '?'
        jne     .k
        mov     al, [fcbs + 1 + bx]
.k:     mov     [fcbr + bx], al
        inc     bx
        loop    .m
        ; back to NAME.EXT, as the kernel's name_out (MS-DOS's): only
        ; each part's trailing spaces dropped
        mov     si, fcbr
        mov     cx, 8
        rep     movsb
.nt:    cmp     byte [di-1], ' '
        jne     .ne
        dec     di
        inc     cx
        cmp     cx, 8
        jb      .nt
.ne:    cmp     word [fcbr + 8], '  '
        jne     .x
        cmp     byte [fcbr + 10], ' '
        je      .z
.x:     mov     al, '.'
        stosb
        mov     cx, 3
        rep     movsb
.xt:    cmp     byte [di-1], ' '
        jne     .z
        dec     di
        jmp     .xt
.z:     mov     byte [di], 0
        ret

; "NAME.EXT" at SI (a name FIND FIRST gave) -> its 11 bytes at DI, the
; spaces inside kept
to11:   push    di
        mov     cx, 11
        mov     al, ' '
        rep     stosb
        pop     di
        mov     cx, 8
.n:     lodsb
        or      al, al
        jz      .x
        cmp     al, '.'
        je      .e
        jcxz    .n
        stosb
        dec     cx
        jmp     .n
.e:     add     di, cx
        mov     cx, 3
.t:     lodsb
        or      al, al
        jz      .x
        jcxz    .t
        stosb
        dec     cx
        jmp     .t
.x:     ret

; ---------------------------------------------------------------------
; DEL pattern
do_del: mov     di, path1
        call    getarg_sw
        cmp     byte [path1], 0
        jne     .p
        jmp     err_param
.p:     mov     si, path1
        call    dir_all
.f:     ; *.* asks first
        mov     si, path1
        call    name_part
        mov     di, fcbp
        mov     ax, 2900h
        int     21h
        mov     di, fcbp + 1
        mov     cx, 11
        mov     al, '?'
        repe    scasb
        jne     .go
        mov     si, s_sure
        call    yes_no
        jne     .x
.go:    call    find1
        jnc     .d
        jmp     err_notfound
.d:     call    src_found
        mov     dx, src
        mov     ah, 41h
        int     21h
        jnc     .n
        mov     si, e_access
        call    err
.n:     mov     ah, 4Fh
        int     21h
        jnc     .d
.x:     ret

; FIND FIRST for path1: files (find1), or attributes CX (find1a)
find1:  xor     cx, cx
find1a: mov     dx, path1
        mov     ah, 4Eh
        int     21h
        ret

; path1's directory part copied to DI (src or dst): DI and BX -> where its
; name part starts
dir_of: push    di
        mov     si, path1
        call    strcpy
        pop     si
        call    name_part               ; (SI = BX)
        mov     di, si
        ret
; src = path1's directory part + the name found (the DTA's); BX -> its name,
; DI -> its NUL (past src + 79: run into dst)
src_found:
        mov     di, src
        call    dir_of
        mov     si, dta + 30
        jmp     strcpy

; question SI, Y or N from standard input: ZF if Y
yes_no: call    puts
        mov     ah, 1
        int     21h
        push    ax
        call    crlf
        pop     ax
        call    upcase
        cmp     al, 'Y'
        je      .y
        cmp     al, 'N'
        jne     yes_no
        or      al, al                  ; ZF clear
.y:     ret

; REN old new
do_ren: call    getarg1
        mov     di, path2
        call    getarg
        cmp     byte [path2], 0
        jne     .g
        jmp     err_syntax
.g:     call    find1
        jc      .bad
.r:     call    src_found               ; old: dir part + found name
        cmp     di, src + 79            ; (79 characters at most)
        ja      .bad
        mov     di, dst                 ; new: same dir, name mapped
        call    dir_of
        push    di
        mov     si, path2
        call    name_part
        call    strcpy
        pop     di
        mov     bx, dta + 30
        call    wild_map
        mov     dx, src
        mov     di, dst
        mov     ah, 56h
        int     21h
        jc      .bad
        mov     ah, 4Fh
        int     21h
        jnc     .r
        ret
.bad:   mov     si, e_dup
        jmp     err

; MD, RD, CD
do_md:  mov     ah, 39h                 ; (getarg1 keeps AH and BX)
        mov     bx, e_mkdir
        jmp     short md_rd
do_rd:  mov     ah, 3Ah
        mov     bx, e_rmdir
md_rd:  call    getarg1
        je      .pm
        mov     dx, path1
        int     21h
        jnc     .x
        mov     si, bx
        jmp     err
.pm:    jmp     err_param
.x:     ret
do_cd:  call    getarg1
        je      .show
        cmp     byte [path1+1], ':'     ; "CD B:" shows B's
        jne     .set
        cmp     byte [path1+2], 0
        jne     .set
        mov     al, [path1]
        call    upcase
        sub     al, 'A' - 1             ; (A = 1; "@:" and past Z: none)
        jz      .bd
        cmp     al, 26
        ja      .bd
        jmp     .sh
.set:   mov     si, path1               ; a \ last (Tab puts one after a
        call    strend                  ;  directory's name) cut, not the
        dec     di                      ;  root's (\, X:\): DOS says 3 for
        cmp     di, si                  ;  SUB\, as MS-DOS (X20)
        jbe     .go
        cmp     byte [di], '\'
        jne     .go
        cmp     byte [di-1], ':'
        je      .go
        mov     byte [di], 0
.go:    mov     dx, si
        mov     ah, 3Bh
        int     21h
        jnc     .x
        mov     si, e_dir
        jmp     err
.show:  mov     ah, 19h
        int     21h
        inc     al
.sh:    mov     dl, al
        call    cwd_puts
        jc      .bd
        jmp     crlf
.bd:    jmp     vol_bad
.x:     ret

; "X:\DIR", the current directory of drive DL (1 = A), printed.  CF (and
; nothing printed) if DOS says no
cwd_puts:
        mov     al, dl
        add     al, 'A' - 1
        mov     si, cdbuf
        mov     [si], al
        mov     word [si+1], ':\'
        add     si, 3
        mov     ah, 47h
        int     21h
        jc      .x
        mov     si, cdbuf
        call    puts
        clc
.x:     ret

do_cls: mov     ah, 0Fh
        int     10h
        xor     ah, ah
        int     10h
        ret

do_echo:
        cmp     byte [si], 0
        jne     .a
        mov     si, s_echois
        call    puts
        mov     si, s_on
        cmp     byte [echo], 0
        jne     .p
        mov     si, s_off
.p:     jmp     puts_nl
.a:     cmp     byte [si], '.'          ; "ECHO." a blank line, "ECHO.text"
        jne     .w                      ;  the text
        inc     si
        jmp     .t
.w:     mov     di, s_on
        call    streqi
        jne     .o
        mov     byte [echo], 1
        ret
.o:     mov     di, s_off
        call    streqi
        jne     .t
        mov     byte [echo], 0
        ret
.t:     jmp     puts_nl

do_ver: mov     si, s_ver
        jmp     puts

; the tasks' records (multitasking, MTAPI.INC) in tail -> CX of them, AL =
; the front one, AH = ours (mt_me too); CF, SI = the message, if it's off
mt_lst: push    ds
        pop     es
        mov     ax, 0F000h + MT_LIST
        mov     di, tail                ; (MT_TASKS records fit)
        mov     cx, MT_TASKS
        stc                             ; (another DOS may leave CF as it was)
        int     21h
        jc      .off
        mov     [mt_me], ah
        cmp     cx, MT_TASKS
        jbe     .n
        mov     cx, MT_TASKS
.n:     clc
        ret
.off:   mov     si, e_mtoff
        ret

; multitasking's front task (AL) and ours (AH), no records; CF if it's off
mt_mine:
        mov     ax, 0F000h + MT_LIST
        xor     cx, cx
        stc                             ; (another DOS may leave CF as it was)
        int     21h
        ret

; TASKS: the tasks there are, the front one marked, and the parked and
; frozen ones
do_tasks:
        call    mt_lst
        jc      .off
        jcxz    .x
        mov     dl, al                  ; (the front task)
        mov     si, tail
.t:     call    sp2
        mov     al, [si+TR_ID]
        add     al, '0'
        call    putc
        call    sp2
        push    si
        push    cx
        add     si, TR_NAME
        mov     cx, TR_NAMELEN
.c:     lodsb                           ; (up to the NUL, or all 12)
        or      al, al
        jz      .e
        call    putc
        loop    .c
.e:     pop     cx
        pop     si
        push    si
        mov     al, [si+TR_STATE]
        mov     ah, [si+TR_ID]
        mov     si, s_front
        cmp     ah, dl
        je      .s
        mov     si, s_parked
        cmp     al, TS_PARKED
        je      .s
        mov     si, s_frozen
        cmp     al, TS_FROZEN
        jne     .nf
.s:     call    puts
.nf:    pop     si
        call    crlf
        add     si, MT_REC
        loop    .t
.x:     ret
.off:   jmp     err

; the task named at SI, by its number or its program's name (MTLINE or
; MTLINE.COM, any case) -> BL; CF, SI = the message, if there's none
task_arg:
        call    mt_lst                  ; (SI kept, unless off)
        jc      .x
        mov     al, [si]
        cmp     al, 0
        jne     .a
        mov     si, e_param
        stc
        ret
.a:     sub     al, '0'
        cmp     al, 9
        ja      .nm
        call    getnum
        cmp     ax, MT_TASKS
        jae     .no
        mov     bl, al
        clc
        ret
.nm:    mov     bx, tail                ; each record's name
.r:     jcxz    .no
        push    si
        lea     di, [bx+TR_NAME]
        xor     dx, dx                  ; (characters alike)
.c:     lodsb
        call    upcase
        mov     ah, [di]
        cmp     al, ' '                 ; (the word's end)
        jbe     .e
        cmp     dx, TR_NAMELEN
        je      .nx
        cmp     al, ah
        jne     .nx
        inc     di
        inc     dx
        jmp     .c
.e:     cmp     dx, TR_NAMELEN          ; all of it, or up to its '.'
        je      .y
        or      ah, ah
        jz      .y
        cmp     ah, '.'
        je      .y
.nx:    pop     si
        add     bx, MT_REC
        dec     cx
        jmp     .r
.y:     pop     si                      ; (CF clear)
        mov     bl, [bx+TR_ID]
        ret
.no:    mov     si, e_notask
        stc
.x:     ret

; FG, KILL, PARK, UNPARK: the task named, to the front, ended, parked,
; brought back
do_fg:  mov     dl, MT_FRONT
        jmp     short task_do
do_kill:
        mov     dl, MT_KILL
        jmp     short task_do
do_park:
        mov     dl, MT_PARK
        jmp     short task_do
do_unpark:
        mov     dl, MT_UNPARK
task_do:
        push    dx
        call    task_arg
        pop     ax
        jc      .e
        mov     ah, 0F0h
        stc
        int     21h
        jnc     .x
        call    mt_emsg
.e:     jmp     err
.x:     ret

; a call's error (AX) -> SI = its message
mt_emsg:
        mov     si, e_notask
        cmp     ax, 1
        je      .x
        mov     si, e_tmany
        cmp     ax, 4
        je      .x
        mov     si, e_tnot
        cmp     ax, 5
        je      .x
        mov     si, e_tmem
.x:     ret

; START [/B] [/D] [/W] [/M:kb] program [args]: the program as a new task (in
; front, unless /W; /B: it always runs behind, /D: never), TASK= its number
do_start:
        call    mt_lst
        jc      .er
        mov     word [spb + SP_PARAS], 0
        mov     byte [spb + SP_FLAGS], SPF_FRONT
.sw:    call    skipsp
        cmp     byte [si], '/'
        jne     .pg
        mov     al, [si+1]
        call    upcase
        add     si, 2
        mov     bl, SPF_BG
        cmp     al, 'B'
        je      .or
        mov     bl, SPF_FREEZE
        cmp     al, 'D'
        je      .or
        cmp     al, 'W'
        je      .w
        cmp     al, 'M'
        jne     .sy
        cmp     byte [si], ':'
        jne     .sy
        inc     si
        mov     al, [si]                ; (digits, under 1024)
        sub     al, '0'
        cmp     al, 9
        ja      .sy
        call    getnum
        cmp     ax, 1024
        jae     .sy
        shl     ax, 6                   ; (KB: paragraphs)
        mov     [spb + SP_PARAS], ax
        cmp     byte [si-1], '/'        ; (getnum went past one: a switch's
        jne     .sw                     ;  back)
        dec     si
        jmp     .sw
.w:     and     byte [spb + SP_FLAGS], ~SPF_FRONT
        jmp     .sw
.or:    or      [spb + SP_FLAGS], bl
        jmp     .sw
.sy:    mov     si, e_syntax
.er:    push    si                      ; (TASK= out: not an earlier one's)
        push    es
        mov     si, s_taskv
        call    env_set_line
        pop     es
        pop     si
        jmp     err
.pg:    call    get_word                ; the program's name
        mov     si, e_param
        cmp     di, cword
        je      .er
        call    find_prog
        mov     si, e_badcmd
        jc      .er
        cmp     byte [is_bat], 0        ; its tail; a batch file's through
        je      .t0                     ;  COMSPEC: " /C file args"
        push    es
        mov     si, s_comspec
        call    env_find
        jc      .nc
        mov     si, di
        mov     di, prog2
.cc:    mov     al, [es:si]
        inc     si
        mov     [di], al
        inc     di
        or      al, al                  ; (CF clear)
        jz      .nc
        cmp     di, prog2 + 79          ; (79 characters at most)
        jbe     .cc
        stc
.nc:    pop     es
        mov     si, e_badcmd
        jc      .er
        mov     di, tail + 1
        xor     cx, cx
        mov     si, s_slashc
        call    tcopy
        mov     si, prog
        call    tcopy
        call    mk_tail.t
        mov     dx, prog2
        jmp     short .t
.t0:    call    mk_tail
        mov     dx, prog
.t:     mov     word [spb + SP_ENV], 0
        mov     word [spb + SP_TAIL], tail
        mov     [spb + SP_TAIL + 2], cs
        mov     bx, spb
        mov     ax, 0F000h + MT_SPAWN
        stc
        int     21h
        jnc     .ok
        call    mt_emsg
        jmp     .er
.ok:    push    ax
        mov     di, setbuf              ; TASK=n
        mov     si, s_taskv
        call    strcpy
        pop     ax
        add     al, '0'
        cbw                             ; (a task: 1-7)
        stosw
        mov     si, setbuf
        jmp     env_set_line

; WAIT task: till it ends; ERRORLEVEL its exit code (AL of 4Dh's), and
; && / || as for a program (ended by ^C or KILL: AL 0, but failed)
do_wait:
        call    task_arg
        jc      .er
        cmp     bl, [mt_me]
        mov     si, e_tnot
        je      .er
        mov     [wtask], bl
        call    .get
        jc      .er
        or      ah, ah
        mov     si, e_notask
        jz      .er
        or      al, al                  ; (free: the last one there ended)
        jz      .end
        mov     [wgen], ah
.l:     mov     ah, 1                   ; keys waiting?  A ^C or a Ctrl-Break
        int     16h                     ;  (0000h) among them: the keys up to
        jz      .h                      ;  it taken, and INT 23h, ours: back
        push    ax                      ;  to the prompt (Lodestone's 0Bh
        call    mt_mine                 ;  doesn't look for ^C).  Other keys
        cmp     al, ah                  ;  stay for the prompt.  In front the
        pop     ax                      ;  BIOS's ring is ours; behind (X34,
        je      .fw                     ;  asked at every pass: the front can
        cmp     al, 3                   ;  change) it is the front task's, and
        je      .tk                     ;  ours is MT's: the key at its head
        or      ax, ax                  ;  only, taken when it is ^C (a ^C
        jnz     .h                      ;  typed into our window).  (WAIT
.tk:    cbw                             ;  gets here with MT on only)
        int     16h                     ; (AH = 0: AL is 3 or 0)
        jmp     short .cc
.fw:    push    ds
        push    40h
        pop     ds
        cli
        mov     bx, [1Ah]
        mov     cx, 16                  ; (a ring's worth at most, as mt_hot)
.s:     cmp     bx, [1Ch]
        je      .n
        mov     ax, [bx]
        inc     bx
        inc     bx
        cmp     bx, [82h]               ; (wrapping at 40:82h)
        jb      .w
        mov     bx, [80h]
.w:     cmp     al, 3
        je      .c
        or      ax, ax
        jz      .c
        loop    .s
        jmp     short .n
.c:     mov     [1Ah], bx
        sti
        pop     ds
.cc:    mov     si, s_ctrlc             ; (as every ^C shows)
        call    puts_nl
        int     23h
        jmp     short .h
.n:     sti
        pop     ds
.h:     sti
        hlt                             ; (the other tasks run)
        call    .get
        jc      .er
        cmp     cl, [wgen]
        je      .end
        cmp     ah, [wgen]              ; (the number given to another, and
        je      .l                      ;  that one ended too: its code lost)
        mov     si, e_lost
        jmp     short .er
.end:   mov     [errlvl], dl
        mov     byte [failed], 0
        or      dx, dx
        jz      .x
        cmp     dx, 0300h               ; (stayed resident, code 0: worked)
        je      .x
        mov     byte [failed], 1
        cmp     dh, 0FFh                ; (its program not started)
        jne     .x
        mov     si, e_nostart
        jmp     err
.x:     ret
.er:    mov     byte [errlvl], 1
        jmp     err
.get:   mov     bl, [wtask]             ; MT_EXIT
        mov     ax, 0F000h + MT_EXIT
        stc
        int     21h
        jnc     .gx
        call    mt_emsg
        stc
.gx:    ret

do_vol: call    drv_of
        mov     dl, al
        call    drv_chk
        jc      vol_bad
        call    crlf
        jmp     show_volume
vol_bad:
        mov     si, e_drive
        jmp     err

; drive DL (0 = A) there?  CF if not (INT 21h 47h: 15, no disk read;
; past Z:, or "@:" (FFh), without asking).  DL kept
drv_chk:
        cmp     dl, 26
        cmc
        jc      .x
        push    dx
        push    si
        sub     sp, 68
        mov     si, sp
        inc     dl
        mov     ah, 47h
        int     21h
        lea     sp, [si+68]
        pop     si
        pop     dx
.x:     ret

do_rem: ret

do_pause:
        mov     al, [for_n]             ; (no saver in a FOR: DEFRAG could
        mov     [sv_req], al            ;  upset its search)
.p:     mov     si, s_pause
        call    puts
        xor     cx, cx
        call    wait_key
        cmp     al, 3                   ; (Ctrl-C: the batch file stops)
        jne     .x
        call    crlf
        int     23h
.x:     jmp     crlf

do_exit:
        cmp     byte [oneshot], 0
        jne     .x
        cmp     byte [perm], 0          ; the first shell can't go
        jne     .x
        mov     ax, 4C00h
        int     21h
.x:     ret

; SET, SET NAME=, SET NAME=value
do_set: cmp     byte [si], 0
        jne     .s
        call    env_seg
        xor     si, si
.l:     cmp     byte [es:si], 0
        je      .d
        call    es_puts
        call    crlf
        jmp     .l
.d:     push    cs
        pop     es
        ret
.s:     jmp     env_set_line

; PATH, PATH dirs, PATH ;
do_path:
        cmp     byte [si], 0
        jne     .s
        mov     si, s_pathv
        call    env_find                ; (ES the environment; SI kept)
        jc      .none
        call    puts
        mov     si, di
        call    es_puts
        push    cs
        pop     es
        jmp     crlf
.none:  push    cs
        pop     es
        mov     si, s_nopath
        jmp     puts_nl
.s:     cmp     byte [si], '='
        jne     .v
        inc     si
.v:     mov     di, setbuf
        push    si
        mov     si, s_pathv
        call    strcpy
        pop     si
        cmp     byte [si], ';'
        jne     .a
        inc     si
.a:     call    strcpy
        mov     si, setbuf
        jmp     env_set_line

; ES:SI printed up to its NUL, SI past it
es_puts:
        es lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     es_puts
.x:     ret

do_prompt:
        mov     di, setbuf
        push    si
        mov     si, s_promptv
        call    strcpy
        pop     si
        call    strcpy
        mov     si, setbuf
        jmp     env_set_line

; DATE [mm-dd-yy], TIME [hh:mm[:ss]]
do_date:
        mov     [argp], si
        mov     ah, 2Ah
        int     21h
        mov     si, s_curdate
        call    puts
        cbw                             ; (AL: the day, 0-6)
        shl     ax, 2
        add     ax, days
        xchg    si, ax
        call    puts
        mov     al, ' '
        call    putc
        call    put_dmy
        mov     si, s_newdate
        call    dt_new
        je      .x
        call    getnum                  ; month
        mov     dh, al
        call    getnum
        mov     dl, al
        call    getnum
        cmp     ax, 100
        jae     .y4
        add     ax, 1900
        cmp     ax, 1980
        jae     .y4
        add     ax, 100
.y4:    mov     cx, ax
        mov     ah, 2Bh
        int     21h
        or      al, al
        jz      .x
        mov     si, e_date
        jmp     err
.x:     ret

do_time:
        mov     [argp], si
        mov     ah, 2Ch
        int     21h
        mov     si, s_curtime
        call    puts
        call    put_hm
        mov     al, ':'
        call    putc
        mov     al, dh
        xor     ah, ah
        call    pu2z
        mov     al, '.'
        call    putc
        mov     al, dl
        xor     ah, ah
        call    pu2z
        mov     si, s_newtime
        call    dt_new
        je      .x
        call    getnum
        mov     ch, al
        call    getnum
        mov     cl, al
        call    getnum
        mov     dh, al
        xor     dl, dl
        mov     ah, 2Dh
        int     21h
        or      al, al
        jz      .x
        mov     si, e_time
        jmp     err
.x:     ret

; the new date or time: the one given ([argp]), else asked for with SI ->
; SI; ZF if there is none
dt_new: call    crlf
        xchg    si, [argp]
        cmp     byte [si], 0
        jne     .x
        mov     si, [argp]
        call    puts
        call    read_reply
        cmp     byte [si], 0
.x:     ret

; CH:CL as "hh:mm" (keeps CX and DX)
put_hm: mov     al, ch
        xor     ah, ah
        call    pu2sp
        mov     al, ':'
        call    putc
        mov     al, cl
        xor     ah, ah
        jmp     pu2z
; DH-DL-CX as "mm-dd-yyyy"
put_dmy:
        mov     al, dh
        xor     ah, ah
        call    pu2z
        mov     al, '-'
        call    putc
        mov     al, dl
        xor     ah, ah
        call    pu2z
        mov     al, '-'
        call    putc
        xchg    ax, cx
        jmp     pu16

; a line from the keyboard -> SI
read_reply:
        mov     al, 40
        call    get_line
        call    crlf
        jmp     skipsp
; a line from standard input (DOS's), AL characters at most -> SI, its NUL
; at the end
get_line:
        mov     [inbuf], al
        mov     dx, inbuf
        mov     ah, 0Ah
        int     21h
        mov     bl, [inbuf+1]
        xor     bh, bh
        mov     si, inbuf+2
        mov     [si+bx], bh
        ret

; decimal at SI -> AX, past one separator
getnum: push    cx
        push    dx
        xor     ax, ax
        xor     bx, bx
.l:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .e
        mov     cx, 10
        mul     cx
        add     ax, bx
        inc     si
        jmp     .l
.e:     cmp     byte [si], 0
        je      .x
        inc     si
.x:     pop     dx
        pop     cx
        ret

env_seg:                                ; AX (and ES) = environment
        push    ds
        mov     ds, [cs:mypsp]
        mov     ax, [2Ch]
        pop     ds
        mov     es, ax
        ret

; find NAME= (SI, upper case, with '=') in the environment (ES, from here
; on) -> DI at the value.  CF if not there
env_find:
        call    env_seg
        xor     di, di
.v:     cmp     byte [es:di], 0
        je      .no
        push    si
        push    di
.c:     lodsb
        or      al, al
        jz      .hit
        cmp     al, [es:di]
        jne     .n
        inc     di
        jmp     .c
.hit:   add     sp, 2
        pop     si
        clc
        ret
.n:     pop     di
        pop     si
        call    skipz
        jmp     .v
.no:    stc
        ret

; ES:DI -> the environment's end (the NUL after its last string)
env_end:
        xor     di, di
.e:     cmp     byte [es:di], 0
        je      skipz.x
        call    skipz
        jmp     .e
; ES:DI past the next NUL
skipz:  xor     al, al
        mov     cx, 0FFFFh
        repne   scasb
.x:     ret

; SI = "NAME=value" (or "NAME="): set or remove it
env_set_line:
        mov     di, setbuf2             ; NAME= in upper case
.n:     lodsb
        or      al, al
        jz      .syn
        cmp     di, setbuf2 + 78        ; (a name longer than setbuf2
        ja      .syn                    ;  takes, with = and its NUL)
        call    upcase
        stosb
        cmp     al, '='
        jne     .n
        mov     byte [di], 0
        mov     [valp], si
        ; the old one: where it is, and its length with its NUL (0: none)
        mov     word [env_old], 0
        push    si
        mov     si, setbuf2
        call    env_find
        pop     si
        jc      .room
        mov     si, setbuf2             ; DI -> value: back to the name
        call    strlen
        sub     di, cx
        mov     [env_oldp], di
        call    skipz
        sub     di, [env_oldp]
        mov     [env_old], di
        ; room for NAME=value and two NULs once the old one is out?  Asked
        ; before anything changes: when there isn't, the old one stays
.room:  mov     si, [valp]
        cmp     byte [si], 0
        je      .del                    ; (NAME= alone: only takes it out)
        call    env_end
        mov     si, setbuf2
        call    strlen
        mov     bx, cx
        mov     si, [valp]
        call    strlen
        add     bx, cx
        add     bx, di
        add     bx, 2
        sub     bx, [env_old]
        cmp     bx, ENVPARA * 16
        jae     .full
        ; remove the old one
.del:   cmp     word [env_old], 0
        je      .add
        mov     di, [env_oldp]
        push    ds
        push    es
        pop     ds
        mov     si, di
.sk:    lodsb                           ; SI -> the next variable
        or      al, al
        jnz     .sk
.mv:    cmp     byte [si], 0            ; move the rest down
        je      .mvd
.m2:    lodsb
        stosb
        or      al, al
        jnz     .m2
        jmp     .mv
.mvd:   mov     byte [di], 0
        pop     ds
.add:   mov     si, [valp]
        cmp     byte [si], 0
        je      .x
        call    env_end                 ; (moved by the removal)
        mov     si, setbuf2
        call    strcpy
        mov     si, [valp]
        call    strcpy
        mov     byte [es:di+1], 0
.x:     push    cs
        pop     es
        ret
.full:  push    cs
        pop     es
        mov     si, e_envfull
        jmp     err
.syn:   jmp     err_syntax

; ---------------------------------------------------------------------
; the prompt from PROMPT ($P$G by default)
        times   ($ + 1 - $$) & 1 db 90h ; (hot: odd here, so the hot labels after even)
show_prompt:
        push    si
        push    es
        mov     si, s_promptv
        call    env_find                ; ES:DI = the PROMPT string
        jnc     .l
        push    cs
        pop     es
        mov     di, s_defprompt
.l:     mov     al, [es:di]
        inc     di
        or      al, al
        jz      .x
        cmp     al, '$'
        je      .d
        call    putc
        jmp     .l
.d:     mov     al, [es:di]
        inc     di
        or      al, al
        jz      .x
        call    upcase
        push    es
        push    di
        push    cs
        pop     es
        call    prompt_code
        pop     di
        pop     es
        jmp     .l
.x:     pop     es
        pop     si
        ret

prompt_code:
        cmp     al, 'P'
        jne     .g
        mov     ah, 19h
        int     21h
        inc     ax
        xchg    dx, ax                  ; (DL: the drive, 1 = A)
        jmp     cwd_puts
.g:     mov     si, p_chars             ; $G $L $$ $Q $B $H $E
.gl:    mov     dx, [si]
        inc     si
        inc     si
        cmp     al, dl
        je      .c
        or      dl, dl
        jnz     .gl
        cmp     al, '_'
        je      crlf
        cmp     al, 'N'
        jne     .v
        mov     ah, 19h
        int     21h
        add     al, 'A'
        jmp     putc
.v:     cmp     al, 'V'
        jne     .t
        mov     si, s_ver + 2
        jmp     puts_line
.t:     cmp     al, 'T'
        jne     .dt
        mov     ah, 2Ch
        int     21h
        jmp     put_hm
.dt:    cmp     al, 'D'
        jne     .x
        mov     ah, 2Ah
        int     21h
        jmp     put_dmy
.c:     mov     al, dh
        jmp     putc
.x:     ret
p_chars db 'G>L<$$Q=B|H', 8, 'E', 27, 0

puts_line:                              ; up to CR
        lodsb
        cmp     al, 13
        je      .x
        or      al, al
        jz      .x
        call    putc
        jmp     puts_line
.x:     ret

; a new line first if the cursor isn't at the left (after a program)
crlf_if_col:
        mov     ah, 3
        xor     bh, bh
        int     10h
        or      dl, dl
        jz      .x
        call    crlf
.x:     ret

; ---------------------------------------------------------------------
; small things
putc:   push    ax
        push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        pop     ax
        ret
        times   ($ - $$) & 1 db 90h     ; (hot: even)
puts:   pusha
        mov     dx, si
        call    strlen
        jcxz    .x
        mov     bx, 1
        mov     ah, 40h
        int     21h
.x:     popa
        ret
puts_nl:                                ; SI, then a new line
        call    puts
crlf:   push    si
        mov     si, s_crlf
        call    puts
        pop     si
        ret
strlen: push    si                      ; SI -> CX
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .x
        inc     cx
        jmp     .l
.x:     pop     si
        ret
strcpy: lodsb                           ; SI -> DI, DI left on the NUL
        stosb
        or      al, al
        jnz     strcpy
        dec     di
        ret
strend: mov     di, si                  ; DI -> the NUL of SI
.l:     cmp     byte [di], 0
        je      .x
        inc     di
        jmp     .l
.x:     ret
        times   ($ - $$) & 1 db 90h     ; (hot: even)
streq:  push    si                      ; ZF if SI = DI
        push    di
.l:     lodsb
        cmp     al, [di]
        jne     .x
        inc     di
        or      al, al
        jnz     .l
.x:     pop     di
        pop     si
        ret
streqi: push    si                      ; ZF if SI = DI ignoring case
        push    di
.l:     lodsb
        call    upcase
        mov     ah, al
        mov     al, [di]
        call    upcase
        cmp     ah, al
        jne     .x
        inc     di
        or      al, al
        jnz     .l
.x:     pop     di
        pop     si
        ret
upcase: cmp     al, 'a'
        jb      .x
        cmp     al, 'z'
        ja      .x
        sub     al, 20h
.x:     ret
skipsp: cmp     byte [si], ' '
        je      .s
        cmp     byte [si], 9
        jne     .x
.s:     inc     si
        jmp     skipsp
.x:     ret
; next argument at SI -> DI (up to a space or a switch)
getarg: call    skipsp
.l:     lodsb
        cmp     al, ' '
        je      .e
        cmp     al, 9
        je      .e
        cmp     al, ','
        je      .e
        or      al, al
        jz      .z
        stosb
        jmp     .l
.z:     dec     si
.e:     mov     byte [di], 0
        ret
; the first argument into path1: ZF if there is none
getarg1:
        mov     di, path1
        call    getarg
        cmp     byte [path1], 0
        ret
; the same, skipping /switches
getarg_sw:
        call    skipsp
        cmp     byte [si], '/'
        jne     .a
        inc     si
        cmp     byte [si], 0            ; ("COPY X /": the end, X14)
        je      .a
        inc     si
        jmp     getarg_sw
.a:     push    di
        call    getarg
        pop     di
        mov     bx, di                  ; cut a switch stuck to it
.c:     cmp     byte [bx], 0
        je      .x
        cmp     byte [bx], '/'
        je      .cut
        inc     bx
        jmp     .c
.cut:   mov     byte [bx], 0
.x:     ret

; AX right-aligned in 2 (space before) / 2 (zero before)
pu2sp:  cmp     ax, 10
        jae     pu2z
        push    ax
        mov     al, ' '
        call    putc
        pop     ax
        add     al, '0'
        jmp     putc
pu2z:   push    ax
        mov     bl, 10
        div     bl
        add     ax, '00'
        call    putc
        mov     al, ah
        call    putc
        pop     ax
        ret
; DX:AX right-aligned in CX columns (0 = no padding); AX alone (pu16w),
; and with no padding (pu16)
pu16:   xor     cx, cx
pu16w:  xor     dx, dx
pu32w:  mov     [padw], cx
        push    si
        mov     si, numbuf + 11
        mov     byte [si], 0
        mov     bx, 10
.d:     push    ax                      ; DX:AX / 10
        mov     ax, dx
        xor     dx, dx
        div     bx
        mov     [tmpw], ax
        pop     ax
        div     bx
        add     dl, '0'
        dec     si
        mov     [si], dl
        mov     dx, [tmpw]
        mov     cx, ax
        or      cx, dx
        jnz     .d
        call    strlen
.p:     cmp     cx, [padw]
        jae     .o
        mov     al, ' '
        call    putc
        inc     cx
        jmp     .p
.o:     call    puts
        pop     si
        ret

; ---------------------------------------------------------------------
s_front     db ' (in front)', 0
s_parked    db ' (parked)', 0
s_frozen    db ' (frozen)', 0
s_taskv     db 'TASK=', 0
s_comspec   db 'COMSPEC=', 0
s_slashc    db ' /C ', 0
s_not       db 'NOT', 0
s_errlvl    db 'ERRORLEVEL', 0
s_exist     db 'EXIST', 0
s_in        db 'IN', 0
s_do        db 'DO', 0
s_yn        db 'YN', 0
s_line      db ' line ', 0
s_colon     db ': ', 0
s_ctrlc     db '^C', 0

x_com       db 'COM', 0                 ; (try_exts: these three in a row)
x_exe       db 'EXE', 0
x_bat       db 'BAT', 0
            times -(x_bat != x_com + 8) db 0
wordends    db ' ', 9, '/', '=', ';', ',', '+', 0

s_ver       db 13, 10, 'Lodestone version 1.0 (DOS 3.30 compatible)'
s_crlf      db 13, 10, 0
s_defprompt db '$P$G', 0
s_promptv   db 'PROMPT=', 0
s_empty     db 0
s_pathv     db 'PATH=', 0
s_nopath    db 'No Path', 0
s_all       db '*'
s_dotstar   db '.*', 0
s_volin     db ' Volume in drive ', 0
s_nolabel   db ' has no label', 0
s_dirof     db ' Directory of  ', 0
s_dirtag    db '    <DIR>', 0
s_files     db ' File(s)', 0
s_free      db ' bytes free', 0
s_sp4       db '    ', 0
s_copied    db ' File(s) copied', 0
s_sure      db 'Are you sure (Y/N)? ', 0
s_echois    db 'ECHO'
s_is        db ' is ', 0
s_on        db 'ON', 0
s_off       db 'OFF', 0
s_pause     db 'Strike a key when ready . . . ', 0
s_curdate   db 'Current date is ', 0
s_newdate   db 'Enter new date (mm-dd-yy): ', 0
s_curtime   db 'Current time is ', 0
s_newtime   db 'Enter new time: ', 0
days        db 'Sun', 0, 'Mon', 0, 'Tue', 0, 'Wed', 0   ; (4 bytes each)
            db 'Thu', 0, 'Fri', 0, 'Sat', 0
pipe_t      db 'PIPEA1.$$$', 0          ; (pipe_name's: A the level, 1 or 2)
s_tempv     db 'TEMP=', 0
s_tmpv      db 'TMP=', 0
s_nul       db 'NUL', 0

e_badcmd    db 'Bad command or file name', 0
e_create    db 'File creation error', 0
e_drive     db 'Invalid drive specification', 0
e_mtoff     db 'Multitasking is off (MULTITASK=1 in LODE.INI)', 0
e_notask    db 'No such task', 0
e_tmany     db 'Too many tasks', 0
e_tnot      db 'Not possible for that task', 0
e_tmem      db 'Not enough memory or EMS', 0
e_nostart   db 'Its program could not be started', 0
e_lost      db 'Its exit code is lost', 0
e_dir       db 'Invalid directory', 0
e_mkdir     db 'Unable to create directory', 0
e_rmdir     db 'Invalid path, not directory,', 13, 10, 'or directory not empty', 0
e_param     db 'Required parameter missing', 0
e_syntax    db 'Syntax error', 0
e_dup       db 'Duplicate file name or '
e_notfound  db 'File not found', 0
e_access    db 'Access denied', 0
e_self      db 'File cannot be copied onto itself', 0
e_dlost     db 'Content of destination lost before copy', 0
e_plong     db 'Invalid path or file name', 0
e_pmany     db 'Too many parameters', 0
e_full      db 'Insufficient disk space', 0
e_read      db 'Read error', 0
e_nomem     db 'Insufficient memory', 0
e_batch     db 'Batch file missing', 0
e_envfull   db 'Out of environment space', 0
e_date      db 'Invalid date', 0
e_time      db 'Invalid time', 0
e_label     db 'Label not found', 0
e_deep      db 'Nested too deep', 0

; INT 24h's messages, in the order of its error codes (ce_msg counts NULs
; from the one that ends e_deep)
ce0         db 'Write protect error', 0
ce1         db 'Unknown unit error', 0
ce2         db 'Not ready error', 0
ce3         db 'Unknown command error', 0
ce4         db 'Data error', 0
ce5         db 'Bad request error', 0
ce6         db 'Seek error', 0
ce7         db 'Unknown media type', 0
ce8         db 'Sector not found', 0
ce9         db 'Printer out of paper', 0
ceA         db 'Write fault', 0
ceB         db 'Read fault', 0
ceC         db 'General failure', 0
            times -(ce0 - e_deep != 16) db 0
s_reading   db ' reading drive ', 0
s_writing   db ' writing drive ', 0
s_arf       db 13, 10, 'Abort, Retry, Fail?', 0

save_in     dw 0FFFFh
save_out    dw 0FFFFh
padw        dw 0

        EVEN    do_line.n, do_pipe.cp, do_pipe.cut, parse_redir.l, redir_undo.x, run_cmd.b2, run_cmd.bl, run_cmd.bs
        EVEN    get_word.c, is_wordend, find_prog.pc, find_ext.d, bat_read.f, bat_next.s, bat_next.s0, for_run.s, for_run.put
        EVEN    edit_line.key, hist_back.b, ed_room, ed_show.s, ed_at, ed_rc, wait_key, wait_key.k, wait_key.r, con_in
        EVEN    do_dir.e, do_dir.n, put_83, put_83.part, put_83.pn, put_83.pl, pump.l, show_prompt.l
        EVEN    putc, puts, crlf, strlen.l, strlen.x, strcpy, strend.l, streq, streq.l, streq.x, upcase, upcase.x
        EVEN    skipsp.x, getarg.l, pu2sp

section .bss
bss_start:
mypsp       resw 1
main_sp     resw 1
main_sp_run resw 1
stack_seg   resw 1
oneshot     resb 1
perm        resb 1
echo        resb 1
child       resb 1
errlvl      resb 1
tmpb        resb 1
zstop       resb 1                      ; pump: a ^Z ends the text
tmpw        resw 1
crit_ah     resb 1
crit_q      resb 1                      ; INT 24h fails (Tab looking; the
                                        ;  saver; a line answered F or A once)
crit_al     resb 1
crit_seen   resb 1                      ; crit answered Abort or Fail (since
                                        ;  this EXEC began)
vol_drv     resb 1
mt_me       resb 1                      ; our task (set only by mt_lst)
wtask       resb 1                      ; WAIT's task, and the count it has
wgen        resb 1                      ;  (MT_EXIT's AH) while it runs
spb         resb SP_SIZE                ; START's block (MT_SPAWN)
            alignb  2                   ; (the words after the bytes: even)
argp        resw 1
argp2       resw 1
extp        resw 1
extend      resw 1
pathp       resw 1
valp        resw 1
env_oldp    resw 1                      ; SET: the old NAME= in the environment
env_old     resw 1                      ;  and its length with its NUL (0: none)
canon_root  resw 1
is_bat      resb 1
pipe_rest   resw 1
pipe_n      resb 1
out_app     resb 1
dir_w       resb 1                  ; (dir_w, dir_p: a word)
dir_p       resb 1
dir_lines   resb 1
dir_n       resw 1
pat_drv     resb 1
dst_dir     resb 1
dstate      resb 1                  ; COPY: concatenation's destination: 0 none
                                    ;  yet, 1 made (open), 2 the first source
                                    ;  (kept), 3 that, open
cmode       resb 1                  ;  concatenation
plus        resb 1                  ;  a "+" list
smode       resb 1                  ;  the sources' /A or /B so far
dsw         resb 1                  ;  the destination's
kascii      resb 1                  ;  the kept one read as ASCII
touch       resb 1                  ;  "+,,"
zbyte       resb 1
pnext       resw 1                  ;  the list's next source
apos        resw 2                  ;  where this source began in it
plist       resb LBUF + 2           ;  the list
copied      resw 1
srcname     resw 1
fh1         resw 1
fh2         resw 1
epb         resw 7
fcb1        resb 37
fcb2        resb 37
fcbp        equ epb                 ; (REN's and COPY's name mapping: no
fcbs        equ epb + 37            ;  program is started meanwhile)
fcbr        equ epb + 74
numbuf      resb 12
vfcb        resb 44                 ; (start's: FFh, 0 x 5, 08h, drive, ????????
                                    ;  ???, the rest 0)
dta         resb 44
cmdl        resb LBUF + 2
bat_raw     resb LBUF + 2
inbuf       equ bat_raw             ; (DOS's line input: not while a line
                                    ;  of a batch file is read)
cword       resb 72
in_name     resb 80
out_name    resb 80
path1       equ in_name             ; (a command's own names: redirection is
path2       equ out_name            ;  done before it runs, and taken back by
                                    ;  its handles)
prog        resb 80
prog2       resb 80
cword2      equ prog2               ; (the built-in's name: before PATH)
cdbuf       equ prog2               ; (CD and $P: not inside the PATH's walk)
pat         resb 80
pat_dir     resb 80
tail        equ pat                 ; (130 bytes: a program's command tail
                                    ;  and TASKS's list; DIR and Tab: never
                                    ;  together)
            resb 16                 ; (for canon2)
src         resb 80                 ; (a name found: 79 characters, checked)
; COPY's two names checked, in prog..src, which COPY doesn't use otherwise.
; Neither getarg nor canon has a bound: path2 (a line's last word, up to
; LBUF-6 characters) runs on into prog, so canon1 starts past that, with
; room for any real file's name (X:\, 63 characters of directory, \, 8.3)
; before canon2, and canon2 (that directory, then path2 and a name) ends
; before src
canon1      equ prog + 46
canon2      equ canon1 + 82
        times   -(prog != out_name + 80 || canon1 - prog < LBUF - 6 + 1 - 80) resb 1
        times   -(canon2 - canon1 < 3 + 65 + 1 + 12 + 1) resb 1
        times   -(src - canon2 < 3 + 65 + 1 + (LBUF - 6) + 13 + 1) resb 1
dst         resb 80
; DIR's canon (pat's directory part, 79 characters at most, after the
; current directory) may run on past pat_dir, into canon2's 16 and src,
; which DIR doesn't use; never into dst
        times   -(dst - pat_dir < 3 + 65 + 1 + 79 + 1) resb 1
setbuf      equ src                 ; (PATH, PROMPT, COMSPEC: no COPY then)
setbuf2     resb 80
failed      resb 1                  ; the command didn't work
aborted     resb 1                  ; (Ctrl-C: unwind closes what was open)
sv_busy     resb 1                  ; (the saver: Ctrl-C does nothing)
sv_req      resb 1                  ; not 0: no saver this time
for_n       resb 1                  ; FORs running, all levels
if_not      resb 1
rdepth      resb 1                  ; levels of redirection kept (rsave)
tpre_on     resb 1                  ; pipe_name: tpre read at this level (0: none)
tpre        resb 66                 ; pipe_name: %TEMP%, a '\' after (\: none)
cdepth      resb 1                  ; CALLs (call_segs)
ed_tab      resb 1
ed_wrap     resb 1                      ; Tab: wrapped to the first once
ed_len      resb 1                  ; (ed_len, ed_pos: a word)
ed_pos      resb 1
ed_old      resb 1                  ; the length on the screen
ed_row      resb 1                  ; where the line starts
ed_col      resb 1
ed_ns       resb 1                  ; (Tab: where the name starts)
ch_n        resb 1                  ; (ch_n, ch_s: a word)
ch_s        resb 1
ch_def      resb 1
sv_mode     resb 1
sv_t        resw 1                  ; the saver's delay (FFFFh: none)
sv_entry    resd 1
sv_pos      resw 1
sv_shape    resw 1
ch_keys     resw 1
ch_t        resw 1
cb_seg      resw 1
cb_len      resw 1
hist_end    resw 1
hist_cur    resw 1
rsave       resw 2 * RMAX
call_segs   resw CMAX
; a batch file's place, the line being run and FOR's state: CALL keeps
; them in a block of its own while the other batch file runs
bat_ctx:
bat_h       resw 1
bat_line    resw 1
bat_on      resb 1                  ; 1: a batch file runs (2: CALL starts one)
bat_echo    resb 1
bat_last    resb 1
for_on      resb 1
for_stop    resb 1                  ; (GOTO)
for_var     resb 1
for_cmdp    resw 1
for_item    resw 1
for_next    resw 1
for_seg     resw 1                  ; FOR's block (L4): FB_DTA, FB_BUF, FB_ZERO
bat_name    resb 14                 ; for errors (SHIFT moves %0)
bat_args    resb LBUF + 2
line        resb LBUF + 2
BATCTX      equ $ - bat_ctx
            alignb  2                   ; (the stack even, whatever the bytes
            resb 1024                   ;  before it)
stack_top:
prog_end:
hist        equ start               ; (the code that starts LCMD: the
                                    ;  prompt is the first to write it)
        times   -(prompt_loop - start < HIST) resb 1
