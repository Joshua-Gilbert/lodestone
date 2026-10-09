; GRIDCMD.COM - the Grid-OS command shell (DOS 3.30 style)
;
;   GRIDCMD            interactive, EXIT goes back to the Executive
;   GRIDCMD /C line    run one command line and return its exit code
;   GRIDCMD /P         permanent (a system's first shell): EXIT does
;                      nothing, \AUTOEXEC.BAT runs at the start
;
; Not called COMMAND.COM on purpose: GRiD MS-DOS in the EPROM takes
; A:\COMMAND.COM as its own shell when the Grid-OS floppy is in the drive.
;
; Built in: DIR TYPE COPY DEL ERASE REN RENAME MD MKDIR RD RMDIR CD CHDIR
; CLS ECHO VER VOL SET PATH PROMPT DATE TIME PAUSE REM EXIT, drive changes
; (A:), programs through PATH (.COM .EXE), batch files (.BAT, %0-%9, @,
; ECHO OFF), redirection < > >> and pipes |.
cpu 286
org 100h

LBUF    equ 128
ENVPARA equ 40h                         ; our environment: 1 KB
COPYBUF equ 4096

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
        mov     dx, dta
        mov     ah, 1Ah
        int     21h
        call    env_init
        mov     dx, ctrlc
        mov     ax, 2523h
        int     21h
        mov     dx, crit
        mov     ax, 2524h
        int     21h
        mov     byte [echo], 1
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
        cmp     al, ' '
        je      .sw
        cmp     al, 9
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
.inter: mov     si, s_banner
        call    puts

; ---- the prompt loop ----------------------------------------------------
prompt_loop:
        cld
        mov     sp, [main_sp]
        push    cs
        pop     ds
        push    cs
        pop     es
        call    redir_undo
        cmp     byte [bat_on], 0
        je      .ask
        call    bat_next
        jmp     prompt_loop
.ask:   cmp     byte [echo], 0
        je      .np
        call    crlf_if_col
        call    show_prompt
.np:    mov     byte [inbuf], LBUF - 2
        mov     dx, inbuf
        mov     ah, 0Ah
        int     21h
        call    crlf
        mov     cl, [inbuf+1]
        xor     ch, ch
        mov     si, inbuf+2
        mov     di, line
        rep     movsb
        mov     byte [di], 0
        mov     si, line
        call    do_line
        jmp     prompt_loop

; Ctrl-C: a program of ours ends; our own command is abandoned
ctrlc:  cmp     byte [cs:child], 0
        je      .us
        stc
        retf                            ; ends the program
.us:    push    cs
        pop     ds
        cmp     byte [bat_on], 0
        je      .nb
        mov     byte [bat_on], 0
        mov     bx, [bat_h]
        mov     ah, 3Eh
        int     21h
.nb:
        cmp     byte [oneshot], 0
        je      .p
        mov     al, 255
        mov     ah, 4Ch
        int     21h
.p:     jmp     prompt_loop

; INT 24h: "Not ready reading drive A / Abort, Retry, Fail?"
crit:   sti
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    ds
        push    es
        push    cs
        pop     ds
        mov     [crit_ah], ah
        mov     [crit_al], al
        mov     bx, di
        xor     bh, bh
        cmp     bl, 0Ch
        jbe     .k
        mov     bl, 0Ch
.k:     shl     bx, 1
        mov     si, [crit_msgs + bx]
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
        cmp     al, 2                   ; Abort in our own work: Fail instead
        jne     .x
        cmp     byte [child], 0
        jne     .x
        mov     al, 3
.x:     pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
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

; ---------------------------------------------------------------------
; one command line at SI (NUL-terminated): pipes, redirection, then the
; command itself
do_line:
        mov     dx, dta
        mov     ah, 1Ah
        int     21h
        call    skipsp
        cmp     byte [si], '@'
        jne     .np
        inc     si
        call    skipsp
.np:    cmp     byte [si], 0
        jne     .some
        ret
.some:  cmp     byte [si], ':'          ; a batch label
        jne     .go
        ret
.go:    mov     [pipe_rest], si
        mov     byte [pipe_n], 0
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
.bar:   mov     byte [di], 0
        mov     [pipe_rest], si
.cut:   ; the pipe's files: in from the last, out to the next
        mov     byte [in_name], 0
        mov     byte [out_name], 0
        mov     byte [out_app], 0
        cmp     byte [pipe_n], 0
        je      .ni
        mov     si, pipe_a
        test    byte [pipe_n], 1
        jnz     .pi
        mov     si, pipe_b
.pi:    mov     di, in_name
        call    strcpy
.ni:    cmp     word [pipe_rest], 0
        je      .no
        mov     si, pipe_b
        test    byte [pipe_n], 1
        jnz     .po
        mov     si, pipe_a
.po:    mov     di, out_name
        call    strcpy
.no:    call    parse_redir
        jc      .x
        call    redir_do
        jc      .x
        mov     si, cmdl
        call    run_cmd
        cld
        push    cs
        pop     es
        call    redir_undo
        inc     byte [pipe_n]
        cmp     word [pipe_rest], 0
        jne     .seg
.x:     call    redir_undo
        cmp     byte [pipe_n], 0        ; a pipe leaves its files
        je      .r
        mov     dx, pipe_a
        mov     ah, 41h
        int     21h
        mov     dx, pipe_b
        mov     ah, 41h
        int     21h
.r:     ret

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
        cmp     al, ' '
        je      .ne
        cmp     al, 9
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
        mov     si, e_notfound
        call    puts
        stc
        ret
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
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        pop     bx
        jmp     .oo
.cr:    mov     dx, out_name
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jnc     .c2
        mov     si, e_create
        call    puts
        stc
        ret
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

redir_undo:
        mov     bx, [save_out]
        cmp     bx, 0FFFFh
        je      .i
        mov     cx, 1
        mov     ah, 46h
        int     21h
        mov     ah, 3Eh
        int     21h
        mov     word [save_out], 0FFFFh
.i:     mov     bx, [save_in]
        cmp     bx, 0FFFFh
        je      .x
        xor     cx, cx
        mov     ah, 46h
        int     21h
        mov     ah, 3Eh
        int     21h
        mov     word [save_in], 0FFFFh
.x:     ret

; ---------------------------------------------------------------------
; the command at SI (redirection already done)
run_cmd:
        call    skipsp
        cmp     byte [si], 0
        jne     .w
        ret
.w:     mov     di, cword               ; the first word, upper case
        mov     cx, 70
.c:     lodsb
        call    is_wordend
        je      .e
        call    upcase
        stosb
        loop    .c
.e:     dec     si
        mov     byte [di], 0
        mov     [argp], si
        ; drive change "B:"
        cmp     byte [cword+1], ':'
        jne     .bi
        cmp     byte [cword+2], 0
        jne     .bi
        mov     dl, [cword]
        sub     dl, 'A'
        mov     [tmpb], dl
        mov     ah, 0Eh
        int     21h
        mov     ah, 19h
        int     21h
        cmp     al, [tmpb]
        je      .x
        mov     si, e_drive
        jmp     puts
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
        mov     ax, cx
        mov     si, cword2
        call    strlen
        sub     ax, cx
        mov     si, [argp]
        sub     si, ax
        mov     [argp2], si
.look:  mov     bx, builtins
.bl:    mov     si, [bx]
        or      si, si
        jz      .ext
        mov     di, cword2
        call    streq
        je      .hit
        add     bx, 4
        jmp     .bl
.hit:   mov     ax, [bx+2]
        mov     si, [argp2]
        call    skipsp
        jmp     ax
.ext:   jmp     run_external
.x:     ret

is_wordend:                             ; ZF if AL ends a command word
        cmp     al, ' '
        je      .y
        cmp     al, 9
        je      .y
        cmp     al, '/'
        je      .y
        cmp     al, '='
        je      .y
        cmp     al, ';'
        je      .y
        cmp     al, ','
        je      .y
        cmp     al, '+'
        je      .y
        or      al, al
.y:     ret

builtins:
        dw c_dir, do_dir
        dw c_type, do_type
        dw c_copy, do_copy
        dw c_del, do_del
        dw c_erase, do_del
        dw c_ren, do_ren
        dw c_rename, do_ren
        dw c_md, do_md
        dw c_mkdir, do_md
        dw c_rd, do_rd
        dw c_rmdir, do_rd
        dw c_cd, do_cd
        dw c_chdir, do_cd
        dw c_cls, do_cls
        dw c_echo, do_echo
        dw c_ver, do_ver
        dw c_vol, do_vol
        dw c_set, do_set
        dw c_path, do_path
        dw c_prompt, do_prompt
        dw c_date, do_date
        dw c_time, do_time
        dw c_pause, do_pause
        dw c_rem, do_rem
        dw c_exit, do_exit
        dw 0

; ---------------------------------------------------------------------
; programs: NAME[.COM|.EXE|.BAT] here or on the PATH
run_external:
        mov     si, cword
        mov     di, prog
        call    strcpy
        mov     si, prog
        call    name_part
        call    find_ext
        ; a path given: only there
        mov     si, prog
        call    has_path
        jc      .dir
        call    try_exts
        jnc     .found
        jmp     .bad
.dir:   call    try_exts                ; current directory, then the PATH
        jnc     .found
        push    es
        call    env_seg
        mov     si, s_pathv
        call    env_find
        pop     es
        jc      .bad
        mov     [pathp], di
.pl:    mov     si, [pathp]
        call    env_seg                 ; one directory from the PATH
        mov     di, prog2
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
        cmp     di, prog2
        je      .pl
        cmp     byte [di-1], '\'
        je      .ps
        mov     al, '\'
        stosb
.ps:    mov     si, cword
        call    strcpy
        mov     si, prog2
        mov     di, prog
        call    strcpy
        mov     si, prog
        call    name_part
        call    find_ext
        call    try_exts
        jnc     .found
        jmp     .pl
.pe:    push    cs
        pop     es
.bad:   mov     si, e_badcmd
        jmp     puts
.found: cmp     byte [is_bat], 0
        je      .run
        jmp     bat_start
.run:   ; command tail: " args", FCBs from the first two
        mov     si, [argp]
        mov     di, tail + 1
        xor     cx, cx
.t:     lodsb
        or      al, al
        jz      .te
        cmp     cx, 126
        jae     .t
        stosb
        inc     cx
        jmp     .t
.te:    mov     [tail], cl
        mov     byte [di], 13
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
        mov     dx, dta                 ; the DTA is the parent's PSP:80h now
        mov     ah, 1Ah
        int     21h
        pop     ax
        popf
        jc      .fail
        mov     ah, 4Dh
        int     21h
        mov     [errlvl], al
        ret
.fail:  mov     si, e_nomem
        cmp     ax, 8
        je      .fm
        mov     si, e_badcmd
.fm:    jmp     puts

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
.test:  mov     dx, prog
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
        mov     bx, x_list
.a:     mov     si, [bx]
        or      si, si
        jz      .none
        mov     di, [extend]
        mov     al, '.'
        stosb
        call    strcpy
        mov     dx, prog
        mov     ax, 4300h
        int     21h
        jc      .an
        test    cl, 18h
        jnz     .an
        mov     byte [is_bat], 0
        cmp     bx, x_list + 4
        jne     .ok
        mov     byte [is_bat], 1
.ok:    clc
        ret
.an:    add     bx, 2
        jmp     .a
.none:  mov     di, [extend]
        mov     byte [di], 0
        stc
        ret

; CF if the name at SI has no drive or directory part
has_path:
.l:     lodsb
        or      al, al
        jz      .no
        cmp     al, '\'
        je      .y
        cmp     al, ':'
        je      .y
        jmp     .l
.no:    stc
        ret
.y:     clc
        ret

; ---------------------------------------------------------------------
; batch files: one line at a time from the file, %0-%9 from its command
bat_start:
        cmp     byte [bat_on], 0
        je      .new
        mov     bx, [bat_h]             ; one batch runs another: replaced
        mov     ah, 3Eh
        int     21h
.new:   mov     dx, prog
        mov     ax, 3D00h
        int     21h
        jnc     .op
        mov     si, e_batch
        jmp     puts
.op:    mov     [bat_h], ax
        mov     byte [bat_on], 1
        mov     al, [echo]              ; ECHO comes back on at the end
        mov     [bat_echo], al
        ; %0 = the name as typed, %1.. the words after it
        mov     si, cword
        mov     di, bat_args
        call    strcpy
        mov     si, [argp]
        call    strcpy
        ret

; run the batch file's next line (or end it)
bat_next:
        mov     bx, [bat_h]
        mov     dx, bat_raw
        mov     cx, LBUF
        mov     ah, 3Fh
        int     21h
        jc      .end
        or      ax, ax
        jz      .end
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
        jmp     .got
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
.back:  ; seek back over what wasn't used
        sub     cx, dx
        jz      .got
        push    dx
        mov     dx, cx
        neg     dx
        mov     cx, 0FFFFh
        mov     bx, [bat_h]
        mov     ax, 4201h
        int     21h
        pop     dx
.got:   ; %n substitution
        mov     si, bat_raw
        mov     di, line
.s:     lodsb
        cmp     al, '%'
        jne     .st
        mov     al, [si]
        cmp     al, '%'
        je      .pp
        sub     al, '0'
        cmp     al, 9
        ja      .pct
        inc     si
        call    bat_arg
        jmp     .s
.pp:    inc     si
.pct:   mov     al, '%'
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
        call    puts
        call    crlf
.run:   mov     si, line
        call    do_line
        cmp     byte [bat_last], 0
        jne     .end
        ret
.end:   cmp     byte [bat_on], 0
        je      .x
        mov     byte [bat_on], 0
        mov     al, [bat_echo]
        mov     [echo], al
        mov     byte [bat_last], 0
        mov     bx, [bat_h]
        mov     ah, 3Eh
        int     21h
.x:     ret

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
        cmp     al, ' '
        je      .nx
        cmp     al, 9
        je      .nx
        or      al, al
        jnz     .sk
        jmp     .x
.nx:    dec     ah
        jmp     .w
.cp:    lodsb
        cmp     al, ' '
        je      .x
        cmp     al, 9
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
; DIR [path] [/W] [/P]
do_dir: mov     byte [dir_w], 0
        mov     byte [dir_p], 0
        mov     byte [path1], 0
        mov     byte [dir_lines], 0
.a:     call    skipsp
        lodsb
        or      al, al
        jz      .ad
        cmp     al, '/'
        jne     .nm
        lodsb
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
        mov     di, path1
        call    getarg
        jmp     .a
.ad:    mov     si, path1
        mov     di, pat
        call    make_pattern
        ; header
        call    crlf
        mov     dl, [pat_drv]
        call    show_volume
        mov     si, s_dirof
        call    puts
        mov     si, pat_dir
        call    puts
        call    crlf
        call    crlf
        mov     word [dir_n], 0
        mov     dx, pat
        mov     cx, 10h
        mov     ah, 4Eh
        int     21h
        jnc     .e
        mov     si, e_notfound
        jmp     puts
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
        xor     dx, dx
        mov     cx, 9
        call    pu32w
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
        call    puts
        ret

dir_more:
        cmp     byte [dir_p], 0
        je      .x
        inc     byte [dir_lines]
        cmp     byte [dir_lines], 23
        jb      .x
        mov     byte [dir_lines], 0
        call    do_pause
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
        cmp     byte [si], '.'          ; "." and ".."
        jne     .n
.dl:    lodsb
        or      al, al
        jz      .dz
        call    putc
        dec     cx
        jmp     .dl
.dz:    dec     si
        jmp     .pn
.n:     mov     al, [si]
        or      al, al
        jz      .pn
        cmp     al, '.'
        je      .pn
        call    putc
        inc     si
        loop    .n
        jmp     .e0
.pn:    mov     al, ' '
.pl:    call    putc
        loop    .pl
.e0:    mov     al, ' '
        call    putc
        cmp     byte [si], '.'
        jne     .ne
        inc     si
.ne:    mov     cx, 3
.e:     mov     al, [si]
        or      al, al
        jz      .ep
        call    putc
        inc     si
        loop    .e
        ret
.ep:    mov     al, ' '
.el:    call    putc
        loop    .el
        ret

; DOS date AX -> "  mm-dd-yy"
put_date:
        push    ax
        mov     al, ' '
        call    putc
        call    putc
        pop     ax
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
        push    ax
        mov     al, ' '
        call    putc
        call    putc
        pop     ax
        push    ax
        shr     ax, 11
        mov     byte [ampm], 'a'
        cmp     ax, 12
        jb      .am
        mov     byte [ampm], 'p'
        sub     ax, 12
.am:    or      ax, ax
        jnz     .h
        mov     ax, 12
.h:     call    pu2sp
        mov     al, ':'
        call    putc
        pop     ax
        shr     ax, 5
        and     ax, 63
        call    pu2z
        mov     al, [ampm]
        jmp     putc

; " Volume in drive A is NAME" / "has no label" for drive DL (0 = A)
show_volume:
        mov     [vol_drv], dl
        mov     si, s_volin
        call    puts
        mov     al, [vol_drv]
        add     al, 'A'
        call    putc
        mov     byte [vpat], al
        mov     word [vpat + 1], ':\'
        mov     word [vpat + 3], '*.'
        mov     word [vpat + 5], '*'
        mov     dx, vpat
        mov     cx, 8
        mov     ah, 4Eh
        int     21h
        jc      .none
        test    byte [dta + 21], 8
        jz      .none
        mov     si, s_is
        call    puts
        mov     si, dta + 30            ; the label, without the dot
.l:     lodsb
        or      al, al
        jz      .d
        cmp     al, '.'
        je      .l
        call    putc
        jmp     .l
.d:     jmp     crlf
.none:  mov     si, s_nolabel
        call    puts
        jmp     crlf

; the pattern for path SI -> DI (pat), plus pat_drv and pat_dir
; ("X:\DIR" for the header).  A directory gets \*.*, a bare name .*
make_pattern:
        push    di
        call    strcpy
        pop     di
        mov     si, di
        ; drive
        mov     ah, 19h
        int     21h
        cmp     byte [si+1], ':'
        jne     .dr
        mov     al, [si]
        call    upcase
        sub     al, 'A'
.dr:    mov     [pat_drv], al
        mov     si, di
        call    is_dir
        jc      .file
        ; a directory: add \*.*
        mov     si, di
        call    strend
        cmp     di, pat
        je      .all
        cmp     byte [di-1], '\'
        je      .all
        cmp     byte [di-1], ':'
        je      .all
        mov     al, '\'
        stosb
.all:   mov     si, s_all
        call    strcpy
        jmp     .hdr
.file:  ; no extension in the name part: NAME.*
        mov     si, pat
        call    name_part
        mov     bx, si
.e:     lodsb
        or      al, al
        jz      .noext
        cmp     al, '.'
        je      .hdr
        jmp     .e
.noext: dec     si
        mov     di, si
        mov     si, s_dotstar
        call    strcpy
.hdr:   ; the directory part, made absolute
        mov     si, pat
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
        ret

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
        mov     ah, 19h
        int     21h
        cmp     byte [si+1], ':'
        jne     .d
        mov     al, [si]
        call    upcase
        sub     al, 'A'
        add     si, 2
.d:     mov     dl, al
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
        inc     dl
        mov     ah, 47h
        int     21h
        pop     si
        call    .end
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
.n1:    lodsb
        or      al, al
        jz      .dn
        cmp     al, '\'
        je      .c
        call    upcase
        stosb
        jmp     .n1
.dn:    dec     si
.done:  cmp     di, [canon_root]        ; "X:\" keeps its backslash
        ja      .t
        mov     di, [canon_root]
.t:     mov     byte [di], 0
        pop     ax
        ret
.end:   cmp     byte [di], 0
        je      .ex
        inc     di
        jmp     .end
.ex:    ret

; ---------------------------------------------------------------------
; TYPE file
do_type:
        mov     di, path1
        call    getarg
        cmp     byte [path1], 0
        jne     .o
        mov     si, e_param
        jmp     puts
.o:     mov     dx, path1
        mov     ax, 3D00h
        int     21h
        jnc     .r
        mov     si, e_notfound
        jmp     puts
.r:     mov     [fh1], ax
.l:     mov     bx, [fh1]
        mov     dx, cbuf
        mov     cx, 512
        mov     ah, 3Fh
        int     21h
        jc      .c
        or      ax, ax
        jz      .c
        mov     cx, ax                  ; up to a ^Z
        mov     di, cbuf
        mov     al, 1Ah
        push    cx
        repne   scasb
        pop     cx
        jne     .w
        mov     cx, di
        sub     cx, cbuf + 1
        mov     byte [tmpb], 1
        jmp     .w2
.w:     mov     byte [tmpb], 0
.w2:    mov     bx, 1
        mov     dx, cbuf
        mov     ah, 40h
        int     21h
        cmp     byte [tmpb], 0
        je      .l
.c:     mov     bx, [fh1]
        mov     ah, 3Eh
        int     21h
        ret

; ---------------------------------------------------------------------
; COPY src [dst]: wildcards; to a directory; several files into one
do_copy:
        mov     di, path1
        call    getarg_sw
        mov     di, path2
        call    getarg_sw
        cmp     byte [path1], 0
        jne     .s
        mov     si, e_param
        jmp     puts
.s:     mov     word [copied], 0
        mov     byte [concat], 0
        ; the source: a directory means all of it
        mov     si, path1
        call    is_dir
        jc      .sf
        call    strend
        cmp     byte [di-1], '\'
        je      .sa
        cmp     byte [di-1], ':'
        je      .sa
        mov     al, '\'
        stosb
.sa:    mov     si, s_all
        call    strcpy
.sf:    ; the destination: a directory (or nothing: here)
        mov     byte [dst_dir], 1
        cmp     byte [path2], 0
        je      .dd
        mov     si, path2
        call    is_dir
        jnc     .dd
        mov     byte [dst_dir], 0
.dd:    mov     dx, path1
        mov     cx, 0
        mov     ah, 4Eh
        int     21h
        jnc     .one
        ; a device (COPY CON FILE)?
        mov     dx, path1
        mov     ax, 3D00h
        int     21h
        jc      .nf
        mov     bx, ax
        mov     ax, 4400h
        int     21h
        mov     ah, 3Eh
        int     21h
        test    dl, 80h
        jz      .nf
        mov     si, path1
        mov     di, src
        call    strcpy
        mov     si, path1
        call    name_part
        mov     [srcname], si
        call    copy_one
        jmp     .tot
.nf:    mov     si, e_notfound
        jmp     puts
.one:   ; source path = dir part of path1 + found name
        mov     si, path1
        mov     di, src
        call    strcpy
        mov     si, src
        call    name_part
        mov     di, si
        mov     si, dta + 30
        mov     [srcname], di
        call    strcpy
        call    copy_one
        jc      .tot
        mov     ah, 4Fh
        int     21h
        jnc     .one
.tot:   mov     ax, [copied]
        xor     dx, dx
        mov     cx, 9
        call    pu32w
        mov     si, s_copied
        jmp     puts

; copy src (name part at srcname) to its destination.  CF to stop.
copy_one:
        ; destination name
        mov     di, dst
        cmp     byte [dst_dir], 0
        je      .df
        mov     si, path2
        call    strcpy
        cmp     di, dst
        je      .dn
        cmp     byte [di-1], '\'
        je      .dn
        cmp     byte [di-1], ':'
        je      .dn
        mov     al, '\'
        stosb
.dn:    mov     si, [srcname]
        call    strcpy
        jmp     .dok
.df:    mov     si, path2
        call    has_wild
        jc      .dplain
        mov     si, path2               ; wildcards: map the name
        call    strcpy
        mov     si, dst
        call    name_part
        mov     di, si
        mov     bx, [srcname]
        call    wild_map
        jmp     .dok
.dplain:
        mov     si, path2
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
        cmp     byte [concat], 0
        jne     .skip
        mov     si, e_self
        call    puts
        stc
        ret
.skip:  clc
        ret
.go:    mov     si, path1                 ; show the name for wildcards
        call    has_wild
        jc      .q
        mov     si, src
        call    puts
        call    crlf
.q:     mov     dx, src
        mov     ax, 3D00h
        int     21h
        jnc     .so
        mov     si, e_notfound
        call    puts
        stc
        ret
.so:    mov     [fh1], ax
        ; several files into one file: append after the first
        cmp     byte [dst_dir], 0
        jne     .new
        cmp     byte [concat], 0
        je      .new
        mov     dx, dst
        mov     ax, 3D01h
        int     21h
        jc      .new
        mov     [fh2], ax
        mov     bx, ax
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        jmp     .loop
.new:   mov     dx, dst
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jnc     .dop
        mov     bx, [fh1]
        mov     ah, 3Eh
        int     21h
        mov     si, e_create
        call    puts
        stc
        ret
.dop:   mov     [fh2], ax
        mov     byte [concat], 1
.loop:  mov     bx, [fh1]
        mov     dx, cbuf
        mov     cx, COPYBUF
        mov     ah, 3Fh
        int     21h
        jc      .rerr
        or      ax, ax
        jz      .eof
        mov     cx, ax
        mov     di, cbuf                ; ^Z ends text from a device
        mov     al, 1Ah
        push    cx
        repne   scasb
        pop     cx
        jne     .wr
        mov     bx, [fh1]
        push    cx
        mov     ax, 4400h
        int     21h
        pop     cx
        test    dl, 80h
        jz      .wr
        mov     cx, di
        sub     cx, cbuf + 1
        mov     byte [tmpb], 1
        jmp     .wr2
.wr:    mov     byte [tmpb], 0
.wr2:   push    cx
        mov     bx, [fh2]
        mov     dx, cbuf
        mov     ah, 40h
        int     21h
        pop     cx
        jc      .full
        cmp     ax, cx
        jne     .full
        cmp     byte [tmpb], 0
        je      .loop
.eof:   ; keep the source's date and time
        mov     bx, [fh1]
        mov     ax, 4400h
        int     21h
        test    dl, 80h
        jnz     .cl
        mov     bx, [fh1]
        mov     ax, 5700h
        int     21h
        mov     bx, [fh2]
        mov     ax, 5701h
        int     21h
.cl:    mov     bx, [fh2]
        mov     ah, 3Eh
        int     21h
        mov     bx, [fh1]
        mov     ah, 3Eh
        int     21h
        inc     word [copied]
        clc
        ret
.full:  mov     si, e_full
        jmp     .err
.rerr:  mov     si, e_read
.err:   call    puts
        mov     bx, [fh2]
        mov     ah, 3Eh
        int     21h
        mov     bx, [fh1]
        mov     ah, 3Eh
        int     21h
        mov     dx, dst
        mov     ah, 41h
        int     21h
        stc
        ret

; name DI (in place, a pattern "*.BAK" etc.) from pattern at DI and the
; name at BX: '?' and '*' take the source's characters
wild_map:
        push    di
        mov     si, di
        mov     di, fcbp
        mov     ax, 2900h
        int     21h
        mov     si, bx
        mov     di, fcbs
        mov     ax, 2900h
        int     21h
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
        ; back to NAME.EXT
        xor     bx, bx
.n:     mov     al, [fcbr + bx]
        cmp     al, ' '
        je      .ne
        stosb
        inc     bx
        cmp     bx, 8
        jb      .n
.ne:    cmp     byte [fcbr + 8], ' '
        je      .z
        mov     al, '.'
        stosb
        mov     bx, 8
.x:     mov     al, [fcbr + bx]
        cmp     al, ' '
        je      .z
        stosb
        inc     bx
        cmp     bx, 11
        jb      .x
.z:     mov     byte [di], 0
        ret

; ---------------------------------------------------------------------
; DEL pattern
do_del: mov     di, path1
        call    getarg_sw
        cmp     byte [path1], 0
        jne     .p
        mov     si, e_param
        jmp     puts
.p:     mov     si, path1
        call    is_dir
        jc      .f
        call    strend
        cmp     byte [di-1], '\'
        je      .a
        cmp     byte [di-1], ':'
        je      .a
        mov     al, '\'
        stosb
.a:     mov     si, s_all
        call    strcpy
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
.go:    mov     word [copied], 0
        mov     dx, path1
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        jnc     .d
        mov     si, e_notfound
        jmp     puts
.d:     mov     si, path1
        mov     di, src
        call    strcpy
        mov     si, src
        call    name_part
        mov     di, si
        mov     si, dta + 30
        call    strcpy
        mov     dx, src
        mov     ah, 41h
        int     21h
        jnc     .n
        mov     si, e_access
        call    puts
.n:     mov     ah, 4Fh
        int     21h
        jnc     .d
.x:     ret

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
do_ren: mov     di, path1
        call    getarg
        mov     di, path2
        call    getarg
        cmp     byte [path2], 0
        jne     .g
        mov     si, e_syntax
        jmp     puts
.g:     mov     word [copied], 0
        mov     dx, path1
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        jc      .bad
.r:     mov     si, path1               ; old: dir part + found name
        mov     di, src
        call    strcpy
        mov     si, src
        call    name_part
        mov     di, si
        mov     si, dta + 30
        mov     bx, di
        call    strcpy
        mov     si, path1               ; new: same dir, name mapped
        mov     di, dst
        call    strcpy
        mov     si, dst
        call    name_part
        mov     di, si
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
        inc     word [copied]
        mov     ah, 4Fh
        int     21h
        jnc     .r
        ret
.bad:   mov     si, e_dup
        jmp     puts

; MD, RD, CD
do_md:  mov     di, path1
        call    getarg
        cmp     byte [path1], 0
        je      .pm
        mov     dx, path1
        mov     ah, 39h
        int     21h
        jnc     .x
        mov     si, e_mkdir
        jmp     puts
.pm:    mov     si, e_param
        jmp     puts
.x:     ret
do_rd:  mov     di, path1
        call    getarg
        cmp     byte [path1], 0
        je      do_md.pm
        mov     dx, path1
        mov     ah, 3Ah
        int     21h
        jnc     .x
        mov     si, e_rmdir
        jmp     puts
.x:     ret
do_cd:  mov     di, path1
        call    getarg
        cmp     byte [path1], 0
        je      .show
        cmp     byte [path1+1], ':'     ; "CD B:" shows B's
        jne     .set
        cmp     byte [path1+2], 0
        jne     .set
        mov     al, [path1]
        call    upcase
        sub     al, 'A' - 1
        jmp     .sh
.set:   mov     dx, path1
        mov     ah, 3Bh
        int     21h
        jnc     .x
        mov     si, e_dir
        jmp     puts
.show:  mov     ah, 19h
        int     21h
        inc     al
.sh:    mov     dl, al
        add     al, 'A' - 1
        mov     [cdbuf], al
        mov     word [cdbuf+1], ':\'
        mov     si, cdbuf + 3
        mov     ah, 47h
        int     21h
        jc      .bd
        mov     si, cdbuf
        call    puts
        jmp     crlf
.bd:    mov     si, e_drive
        jmp     puts
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
.p:     call    puts
        jmp     crlf
.a:     cmp     byte [si], '.'          ; "ECHO." = a blank line
        jne     .w
        cmp     byte [si+1], 0
        jne     .w
        jmp     crlf
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
.t:     call    puts
        jmp     crlf

do_ver: mov     si, s_ver
        jmp     puts

do_vol: mov     ah, 19h
        int     21h
        mov     dl, al
        cmp     byte [si+1], ':'
        jne     .v
        mov     al, [si]
        call    upcase
        sub     al, 'A'
        mov     dl, al
.v:     call    crlf
        jmp     show_volume

do_rem: ret

do_pause:
        mov     si, s_pause
        call    puts
        mov     ah, 8
        int     21h
        jmp     crlf

do_exit:
        cmp     byte [oneshot], 0
        jne     .x
        cmp     byte [perm], 0          ; the first shell can't go
        jne     .x
        mov     al, 0
        mov     ah, 4Ch
        int     21h
.x:     ret

; SET, SET NAME=, SET NAME=value
do_set: cmp     byte [si], 0
        jne     .s
        call    env_seg
        xor     si, si
.l:     cmp     byte [es:si], 0
        je      .d
.c:     mov     al, [es:si]
        inc     si
        or      al, al
        jz      .e
        call    putc
        jmp     .c
.e:     call    crlf
        jmp     .l
.d:     push    cs
        pop     es
        ret
.s:     jmp     env_set_line

; PATH, PATH dirs, PATH ;
do_path:
        cmp     byte [si], 0
        jne     .s
        push    es
        call    env_seg
        mov     si, s_pathv
        call    env_find
        pop     es
        jc      .none
        mov     si, s_pathv
        call    puts
        call    env_seg
.c:     mov     al, [es:di]
        inc     di
        or      al, al
        jz      .e
        call    putc
        jmp     .c
.e:     push    cs
        pop     es
        jmp     crlf
.none:  mov     si, s_nopath
        jmp     puts
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
        push    cx
        push    dx
        mov     si, s_curdate
        call    puts
        mov     bl, al
        xor     bh, bh
        shl     bx, 1
        mov     si, [days + bx]
        call    puts
        mov     al, ' '
        call    putc
        pop     dx
        pop     cx
        push    cx
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
        pop     ax
        xor     dx, dx
        xor     cx, cx
        call    pu32w
        call    crlf
        mov     si, [argp]
        cmp     byte [si], 0
        jne     .set
        mov     si, s_newdate
        call    puts
        call    read_reply
        cmp     byte [si], 0
        je      .x
.set:   call    getnum                  ; month
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
        jmp     puts
.x:     ret

do_time:
        mov     [argp], si
        mov     ah, 2Ch
        int     21h
        push    dx
        push    cx
        mov     si, s_curtime
        call    puts
        pop     cx
        push    cx
        mov     al, ch
        xor     ah, ah
        call    pu2sp
        mov     al, ':'
        call    putc
        pop     cx
        mov     al, cl
        xor     ah, ah
        call    pu2z
        mov     al, ':'
        call    putc
        pop     dx
        push    dx
        mov     al, dh
        xor     ah, ah
        call    pu2z
        mov     al, '.'
        call    putc
        pop     dx
        mov     al, dl
        xor     ah, ah
        call    pu2z
        call    crlf
        mov     si, [argp]
        cmp     byte [si], 0
        jne     .set
        mov     si, s_newtime
        call    puts
        call    read_reply
        cmp     byte [si], 0
        je      .x
.set:   call    getnum
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
        jmp     puts
.x:     ret

; a line from the keyboard -> SI
read_reply:
        mov     byte [inbuf], 40
        mov     dx, inbuf
        mov     ah, 0Ah
        int     21h
        call    crlf
        mov     bl, [inbuf+1]
        xor     bh, bh
        mov     byte [inbuf+2+bx], 0
        mov     si, inbuf+2
        call    skipsp
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
        call    env_seg
        mov     si, s_comspecv
        call    env_find
        push    cs
        pop     es
        jnc     .ae
        mov     di, setbuf
        mov     si, s_comspecv
        call    strcpy
        mov     ah, 19h
        int     21h
        add     al, 'A'
        stosb
        mov     si, s_selfname
        call    strcpy
        mov     si, setbuf
        call    env_set_line
.ae:    mov     ah, 19h                 ; X:\AUTOEXEC.BAT
        int     21h
        add     al, 'A'
        mov     [prog], al
        mov     si, s_autoexec
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

env_seg:                                ; AX (and ES) = environment
        push    ds
        mov     ds, [cs:mypsp]
        mov     ax, [2Ch]
        pop     ds
        mov     es, ax
        ret

; find NAME= (SI, upper case, with '=') in the environment ES -> DI at
; the value.  CF if not there
env_find:
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
        xor     al, al
        mov     cx, 0FFFFh
        repne   scasb
        jmp     .v
.no:    stc
        ret

; SI = "NAME=value" (or "NAME="): set or remove it
env_set_line:
        mov     di, setbuf2             ; NAME= in upper case
.n:     lodsb
        or      al, al
        jz      .syn
        call    upcase
        stosb
        cmp     al, '='
        jne     .n
        mov     byte [di], 0
        mov     [valp], si
        ; remove the old one
        call    env_seg
        push    si
        mov     si, setbuf2
        call    env_find
        pop     si
        jc      .add
        mov     si, setbuf2             ; DI -> value: back to the name
        call    strlen
        sub     di, cx
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
        call    env_seg
        xor     di, di                  ; the end
.e:     cmp     byte [es:di], 0
        je      .end
        xor     al, al
        mov     cx, 0FFFFh
        repne   scasb
        jmp     .e
.end:   mov     si, setbuf2
        call    strlen
        mov     bx, cx
        mov     si, [valp]
        call    strlen
        add     bx, cx
        add     bx, di
        add     bx, 2
        cmp     bx, ENVPARA * 16
        jae     .full
        mov     si, setbuf2
.a1:    lodsb
        or      al, al
        jz      .a2
        stosb
        jmp     .a1
.a2:    mov     si, [valp]
.a3:    lodsb
        stosb
        or      al, al
        jnz     .a3
        mov     byte [es:di], 0
.x:     push    cs
        pop     es
        ret
.full:  push    cs
        pop     es
        mov     si, e_envfull
        jmp     puts
.syn:   mov     si, e_syntax
        jmp     puts

; ---------------------------------------------------------------------
; the prompt from PROMPT ($P$G by default)
show_prompt:
        push    si
        push    es
        call    env_seg
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
        mov     dl, al
        add     al, 'A'
        mov     [cdbuf], al
        mov     word [cdbuf+1], ':\'
        mov     si, cdbuf + 3
        inc     dl
        mov     ah, 47h
        int     21h
        mov     si, cdbuf
        jmp     puts
.g:     mov     ah, '>'
        cmp     al, 'G'
        je      .c
        mov     ah, '<'
        cmp     al, 'L'
        je      .c
        mov     ah, '$'
        cmp     al, '$'
        je      .c
        mov     ah, '='
        cmp     al, 'Q'
        je      .c
        mov     ah, '|'
        cmp     al, 'B'
        je      .c
        mov     ah, 8
        cmp     al, 'H'
        je      .c
        mov     ah, 27
        cmp     al, 'E'
        je      .c
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
        mov     al, ch
        xor     ah, ah
        push    cx
        call    pu2sp
        mov     al, ':'
        call    putc
        pop     cx
        mov     al, cl
        xor     ah, ah
        jmp     pu2z
.dt:    cmp     al, 'D'
        jne     .x
        mov     ah, 2Ah
        int     21h
        push    dx
        push    cx
        mov     al, dh
        xor     ah, ah
        call    pu2z
        mov     al, '-'
        call    putc
        pop     cx
        pop     dx
        push    cx
        mov     al, dl
        xor     ah, ah
        call    pu2z
        mov     al, '-'
        call    putc
        pop     ax
        xor     dx, dx
        xor     cx, cx
        jmp     pu32w
.c:     mov     al, ah
        jmp     putc
.x:     ret

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
puts:   push    ax
        push    bx
        push    cx
        push    dx
        push    si
        mov     dx, si
        call    strlen
        jcxz    .x
        mov     bx, 1
        mov     ah, 40h
        int     21h
.x:     pop     si
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret
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
; the same, skipping /switches
getarg_sw:
        call    skipsp
        cmp     byte [si], '/'
        jne     .a
        add     si, 2
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
; DX:AX right-aligned in CX columns (0 = no padding)
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
c_dir       db 'DIR', 0
c_type      db 'TYPE', 0
c_copy      db 'COPY', 0
c_del       db 'DEL', 0
c_erase     db 'ERASE', 0
c_ren       db 'REN', 0
c_rename    db 'RENAME', 0
c_md        db 'MD', 0
c_mkdir     db 'MKDIR', 0
c_rd        db 'RD', 0
c_rmdir     db 'RMDIR', 0
c_cd        db 'CD', 0
c_chdir     db 'CHDIR', 0
c_cls       db 'CLS', 0
c_echo      db 'ECHO', 0
c_ver       db 'VER', 0
c_vol       db 'VOL', 0
c_set       db 'SET', 0
c_path      db 'PATH', 0
c_prompt    db 'PROMPT', 0
c_date      db 'DATE', 0
c_time      db 'TIME', 0
c_pause     db 'PAUSE', 0
c_rem       db 'REM', 0
c_exit      db 'EXIT', 0

x_list      dw x_com, x_exe, x_bat, 0
x_com       db 'COM', 0
x_exe       db 'EXE', 0
x_bat       db 'BAT', 0

s_banner    db 13, 10, 'Grid-OS 0.4 command shell (DOS 3.30 compatible)', 13, 10
            db 'Type EXIT to return to the Executive.', 13, 10, 0
s_ver       db 13, 10, 'Grid-OS version 0.4 (DOS 3.30 compatible)', 13, 10, 0
s_crlf      db 13, 10, 0
s_defprompt db '$P$G', 0
s_promptv   db 'PROMPT=', 0
s_comspecv  db 'COMSPEC=', 0
s_selfname  db ':\GRIDCMD.COM', 0
s_autoexec  db ':\AUTOEXEC.BAT', 0
s_autoname  db 'AUTOEXEC', 0
s_empty     db 0
s_pathv     db 'PATH=', 0
s_nopath    db 'No Path', 13, 10, 0
s_all       db '*.*', 0
s_dotstar   db '.*', 0
s_volin     db ' Volume in drive ', 0
s_is        db ' is ', 0
s_nolabel   db ' has no label', 0
s_dirof     db ' Directory of  ', 0
s_dirtag    db '    <DIR>', 0
s_files     db ' File(s)', 0
s_free      db ' bytes free', 13, 10, 0
s_sp4       db '    ', 0
s_copied    db ' File(s) copied', 13, 10, 0
s_sure      db 'Are you sure (Y/N)? ', 0
s_echois    db 'ECHO is ', 0
s_on        db 'ON', 0
s_off       db 'OFF', 0
s_pause     db 'Strike a key when ready . . . ', 0
s_curdate   db 'Current date is ', 0
s_newdate   db 'Enter new date (mm-dd-yy): ', 0
s_curtime   db 'Current time is ', 0
s_newtime   db 'Enter new time: ', 0
days        dw d0, d1, d2, d3, d4, d5, d6
d0          db 'Sun', 0
d1          db 'Mon', 0
d2          db 'Tue', 0
d3          db 'Wed', 0
d4          db 'Thu', 0
d5          db 'Fri', 0
d6          db 'Sat', 0
pipe_a      db '\PIPE1.$$$', 0
pipe_b      db '\PIPE2.$$$', 0

e_badcmd    db 'Bad command or file name', 13, 10, 0
e_notfound  db 'File not found', 13, 10, 0
e_create    db 'File creation error', 13, 10, 0
e_drive     db 'Invalid drive specification', 13, 10, 0
e_dir       db 'Invalid directory', 13, 10, 0
e_mkdir     db 'Unable to create directory', 13, 10, 0
e_rmdir     db 'Invalid path, not directory,', 13, 10, 'or directory not empty', 13, 10, 0
e_param     db 'Required parameter missing', 13, 10, 0
e_syntax    db 'Syntax error', 13, 10, 0
e_dup       db 'Duplicate file name or File not found', 13, 10, 0
e_access    db 'Access denied', 13, 10, 0
e_self      db 'File cannot be copied onto itself', 13, 10, 0
e_full      db 'Insufficient disk space', 13, 10, 0
e_read      db 'Read error', 13, 10, 0
e_nomem     db 'Insufficient memory', 13, 10, 0
e_batch     db 'Batch file missing', 13, 10, 0
e_envfull   db 'Out of environment space', 13, 10, 0
e_date      db 'Invalid date', 13, 10, 0
e_time      db 'Invalid time', 13, 10, 0

crit_msgs   dw ce0, ce1, ce2, ce3, ce4, ce5, ce6, ce7, ce8, ce9, ceA, ceB, ceC
ce0         db 13, 10, 'Write protect error', 0
ce1         db 13, 10, 'Unknown unit error', 0
ce2         db 13, 10, 'Not ready error', 0
ce3         db 13, 10, 'Unknown command error', 0
ce4         db 13, 10, 'Data error', 0
ce5         db 13, 10, 'Bad request error', 0
ce6         db 13, 10, 'Seek error', 0
ce7         db 13, 10, 'Unknown media type', 0
ce8         db 13, 10, 'Sector not found', 0
ce9         db 13, 10, 'Printer out of paper', 0
ceA         db 13, 10, 'Write fault', 0
ceB         db 13, 10, 'Read fault', 0
ceC         db 13, 10, 'General failure', 0
s_reading   db ' reading drive ', 0
s_writing   db ' writing drive ', 0
s_arf       db 13, 10, 'Abort, Retry, Fail?', 0

save_in     dw 0FFFFh
save_out    dw 0FFFFh
padw        dw 0

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
tmpw        resw 1
crit_ah     resb 1
crit_al     resb 1
ampm        resb 1
vol_drv     resb 1
argp        resw 1
argp2       resw 1
extp        resw 1
extend      resw 1
pathp       resw 1
valp        resw 1
canon_root  resw 1
is_bat      resb 1
bat_on      resb 1
bat_echo    resb 1
bat_last    resb 1
bat_h       resw 1
pipe_rest   resw 1
pipe_n      resb 1
out_app     resb 1
dir_w       resb 1
dir_p       resb 1
dir_lines   resb 1
dir_n       resw 1
pat_drv     resb 1
dst_dir     resb 1
concat      resb 1
copied      resw 1
srcname     resw 1
fh1         resw 1
fh2         resw 1
epb         resw 7
fcb1        resb 37
fcb2        resb 37
fcbp        resb 37
fcbs        resb 37
fcbr        resb 12
numbuf      resb 12
vpat        resb 8
dta         resb 44
inbuf       resb LBUF + 2
line        resb LBUF + 2
cmdl        resb LBUF + 2
bat_raw     resb LBUF + 2
bat_args    resb LBUF + 2
tail        resb 130
cword       resb 72
cword2      resb 72
in_name     resb 80
out_name    resb 80
prog        resb 80
prog2       resb 80
path1       resb 80
path2       resb 80
pat         resb 80
pat_dir     resb 80
src         resb 80
dst         resb 80
canon1      resb 80
canon2      resb 80
cdbuf       resb 72
setbuf      resb LBUF + 8
setbuf2     resb 80
cbuf        resb COPYBUF
            resb 1024
stack_top:
prog_end:
