; ---------------------------------------------------------------------
;  The Executive is the root process.  It runs on its own stack and uses
;  the kernel through INT 21h like any program: find first/next for the
;  list, CHDIR for subjects, EXEC to run programs.
; ---------------------------------------------------------------------
VSEG    equ 0B800h
LIST_Y  equ 24          ; first list row (pixels)
LIST_N  equ 13          ; visible list rows
RULE1   equ 19
RULE2   equ 237
FORM_Y  equ 244
INFO_Y  equ 336
BAND_Y  equ 360
TCOL    equ 3           ; title column
KEND    equ 77          ; kind column end (exclusive)
MAXENT  equ 240

section .bss
exec_dta    resb 44
entries     resb 32 * MAXENT    ; directory entries in FAT layout
mfound      resw 1              ; mouse port found at start-up
mstarted    resb 1
runpath     resb 80
exec_epb    resw 7
ex_code     resw 1
run_sel     resw 1
run_top     resw 1
subject     resb 70
lastact     resw 1
sv_due      resw 1
sv_col      resw 1
sv_y        resw 1
sv_seed     resw 1
sv_tail     resb 24
section .text

exec_main:
        cld
        push    cs
        pop     ds
        push    cs
        pop     es
        mov     dx, exec_dta
        mov     ah, 1Ah
        int     21h
        call    sysinfo
        cmp     byte [mstarted], 0
        jne     .mon
        mov     byte [mstarted], 1
        call    mouse_init
        jmp     .info
.mon:   call    mouse_on
.info:  call    build_info
        call    hires
        jnc     .hi
        mov     si, s_nohires
        call    bios_print
        xor     ah, ah
        int     16h
        jmp     reboot
.hi:    call    mkrows
        call    load_dir
        call    read_clock
        call    draw_all
        call    show_cursor
        call    act_now
        jmp     main

; mode 40h; CF if the panel doesn't have it
hires:  mov     ax, 0040h
        int     10h
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     al, [449h]
        pop     ds
        cmp     al, 40h
        je      .ok
        mov     ax, 0003h
        int     10h
        stc
        ret
.ok:    clc
        ret

; the current directory into entries/entlist, sorted
load_dir:
        mov     word [nent], 0
        mov     word [sel], 0
        mov     word [top], 0
        mov     dx, s_all
        mov     cx, 10h                 ; subdirectories too
        mov     ah, 4Eh
        int     21h
        jc      .done
        mov     di, entries
.e:     cmp     word [nent], MAXENT
        jae     .done
        cmp     word [exec_dta+30], '.'  ; "." (but keep "..")
        je      .next
        push    di
        call    dta2ent
        pop     di
        mov     bx, [nent]
        shl     bx, 1
        mov     [entlist+bx], di
        inc     word [nent]
        add     di, 32
.next:  mov     ah, 4Fh
        int     21h
        jnc     .e
.done:  call    sort_dir
        ; the subject: the current directory
        mov     byte [subject], '\'
        mov     si, subject + 1
        xor     dl, dl
        mov     ah, 47h
        int     21h
        ret

; exec_dta -> FAT-style entry at DI (name, attribute, time, date, size)
dta2ent:
        push    di
        mov     cx, 11
        mov     al, ' '
        rep     stosb
        pop     di
        mov     si, exec_dta + 30
        mov     bx, di
        cmp     byte [si], '.'
        jne     .n
        movsb                           ; ".."
        movsb
        jmp     .rest
.n:     mov     cx, 8
.nl:    lodsb
        or      al, al
        jz      .rest
        cmp     al, '.'
        je      .ext
        stosb
        loop    .nl
.sk:    lodsb                           ; (longer than 8: skip to '.')
        or      al, al
        jz      .rest
        cmp     al, '.'
        jne     .sk
.ext:   lea     di, [bx+8]
        mov     cx, 3
.el:    lodsb
        or      al, al
        jz      .rest
        stosb
        loop    .el
.rest:  mov     al, [exec_dta+21]
        mov     [bx+11], al
        mov     ax, [exec_dta+22]
        mov     [bx+22], ax
        mov     ax, [exec_dta+24]
        mov     [bx+24], ax
        mov     ax, [exec_dta+26]
        mov     [bx+28], ax
        mov     ax, [exec_dta+28]
        mov     [bx+30], ax
        ret

; Return on the selected entry
confirm:
        cmp     word [nent], 0
        je      .x
        mov     bx, [sel]
        call    ent_ptr
        test    byte [si+11], 10h
        jnz     .subject
        mov     ax, [si+8]
        mov     dl, [si+10]
        cmp     ax, 'CO'
        jne     .exe
        cmp     dl, 'M'
        je      .run
.exe:   cmp     ax, 'EX'
        jne     .other
        cmp     dl, 'E'
        je      .run
.other: mov     di, msgbuf              ; not a program: say so
        call    sb_title
        mov     si, s_sp2
        call    sb_str
        mov     bx, [sel]
        call    ent_ptr
        call    kind_of
        call    sb_str
        mov     si, s_noopen
        call    sb_str
        mov     byte [di], 0
        jmp     show_msg
.subject:
        mov     di, runpath             ; CHDIR into it
        call    sb_title
        mov     byte [di], 0
        mov     dx, runpath
        mov     ah, 3Bh
        int     21h
        call    hide_cursor
        call    load_dir
        call    draw_list
        call    draw_form
        jmp     show_cursor
.run:   mov     di, runpath             ; NAME.EXT in the current directory
        call    sb_title
        mov     al, '.'
        stosb
        mov     bx, [sel]
        call    ent_ptr
        add     si, 8
        mov     cx, 3
        rep     movsb
        mov     byte [di], 0
        jmp     run_prog
.x:     ret

; CODE-C: the command shell from COMSPEC
run_shell:
        push    es
        mov     es, [root_psp]
        mov     es, [es:2Ch]
        xor     di, di
.v:     cmp     byte [es:di], 0
        je      .def
        mov     si, s_comspec
        push    di
        mov     cx, 8
        repe    cmpsb
        je      .hit
        pop     di
        xor     al, al
        mov     cx, 0FFFFh
        repne   scasb
        jmp     .v
.hit:   add     sp, 2
        mov     si, di                  ; value -> runpath
        mov     di, runpath
.c:     mov     al, [es:si]
        mov     [di], al
        inc     si
        inc     di
        or      al, al
        jz      .go
        cmp     di, runpath + 78
        jb      .c
        mov     byte [di], 0
.go:    pop     es
        jmp     run_prog
.def:   pop     es
        mov     si, s_defshell
        mov     di, runpath
.d:     lodsb
        stosb
        or      al, al
        jnz     .d
        jmp     run_prog

; CODE-A: Claude (CLAUDE.COM here, else in the root)
run_claude:
        mov     si, s_claude + 3        ; "CLAUDE.COM" in this directory
        call    .try
        jnc     .go
        mov     ah, 19h                 ; "X:\CLAUDE.COM"
        int     21h
        add     al, 'A'
        mov     [s_claude], al
        mov     si, s_claude
        call    .try
        jnc     .go
        mov     di, msgbuf
        mov     si, s_noclaude
        call    sb_str
        mov     byte [di], 0
        jmp     show_msg
.go:    jmp     run_prog
.try:   mov     di, runpath
.c:     lodsb
        stosb
        or      al, al
        jnz     .c
        mov     dx, runpath
        mov     ax, 4300h
        int     21h
        ret

; F5: the disk again (after changing floppies)
refresh:
        mov     ah, 0Dh
        int     21h
        call    hide_cursor
        call    load_dir
        call    draw_list
        call    draw_form
        jmp     show_cursor

; run runpath; afterwards back to mode 40h and a fresh list
run_prog:
        mov     ax, [sel]               ; come back to the same place
        mov     [run_sel], ax
        mov     ax, [top]
        mov     [run_top], ax
        call    hide_cursor
        call    mouse_off
        mov     ax, 0003h
        int     10h
        mov     word [exec_epb], 0      ; our environment
        mov     word [exec_epb+2], s_notail
        mov     [exec_epb+4], cs
        mov     word [exec_epb+6], exec_fcb
        mov     [exec_epb+8], cs
        mov     word [exec_epb+10], exec_fcb
        mov     [exec_epb+12], cs
        mov     dx, runpath
        mov     bx, exec_epb
        mov     ax, 4B00h
        int     21h
        cld
        push    cs
        pop     ds
        push    cs
        pop     es
        mov     [ex_code], ax
        jc      .failed
        mov     ah, 4Dh
        int     21h
        mov     [ex_code], ax
        mov     dx, exec_dta            ; our DTA again
        mov     ah, 1Ah
        int     21h
        call    back_to_exec
        mov     di, msgbuf              ; "TM5000G.EXE ended"
        mov     si, runpath
        call    sb_base
        mov     si, s_ended
        call    sb_str
        cmp     byte [ex_code], 0
        je      .m
        mov     si, s_code
        call    sb_str
        mov     al, [ex_code]
        xor     ah, ah
        call    sb_u16
.m:     mov     byte [di], 0
        jmp     show_msg
.failed:
        mov     dx, exec_dta
        mov     ah, 1Ah
        int     21h
        call    back_to_exec
        mov     di, msgbuf
        mov     si, s_cant
        call    sb_str
        mov     si, runpath
        call    sb_base
        mov     si, s_colon
        call    sb_str
        mov     ax, [ex_code]
        mov     si, s_e2
        cmp     ax, 2
        je      .em
        mov     si, s_e8
        cmp     ax, 8
        je      .em
        mov     si, s_e11
        cmp     ax, 11
        je      .em
        mov     si, s_eio
.em:    call    sb_str
        mov     byte [di], 0
        jmp     show_msg

back_to_exec:
        call    hires
        call    mouse_on
        call    act_now
relist: call    load_dir                ; (the same place in the list)
        mov     ax, [run_sel]
        cmp     ax, [nent]
        jae     .r
        mov     [sel], ax
        mov     ax, [run_top]
        cmp     ax, [sel]
        ja      .r
        mov     [top], ax
.r:
        call    read_clock
        call    draw_all
        ret

; ---------------------------------------------------------------------
; The screen saver, after 5 minutes without a key or the mouse.
; First DEFRAG.COM, if it is on the disk: it tidies the floppy while
; showing its map, and stops at a key or the mouse (exit code 1) or when
; the disk is in order.  It runs like any program, so its memory is free
; again afterwards.  Then a dark screen with the time and date moving to
; a new place every 20 seconds, so the plasma never holds one picture.
SAVER_T equ 5462                        ; 5 minutes of 55 ms ticks

act_now:                                ; a key or the mouse: not idle
        push    ax
        call    tick
        mov     [lastact], ax
        pop     ax
        ret

saver:  cmp     byte [helpopen], 0
        je      .h
        call    close_help
.h:     call    hide_cursor
        mov     byte [msgshown], 0
        mov     ax, [sel]
        mov     [run_sel], ax
        mov     ax, [top]
        mov     [run_top], ax
        cli
        mov     byte [mflag], 0
        sti
        call    sv_defrag
        jc      .own
        cmp     al, 1
        je      .wake
.own:   call    hires
        call    tick
        mov     [sv_due], ax
        mov     [sv_seed], ax
        mov     word [sv_col], 0FFFFh
.l:     mov     ah, 1
        int     16h
        jnz     .key
        cmp     byte [mflag], 0
        jne     .wake
        call    tick
        sub     ax, [sv_due]
        cmp     ax, 8000h
        jae     .z                      ; (not yet)
        call    sv_move
.z:     sti
        hlt
        jmp     .l
.key:   xor     ah, ah                  ; the key that wakes it does
        int     16h                     ; nothing else
.wake:  cli
        mov     byte [mflag], 0
        mov     al, [mb]                ; (a button held while waking it
        mov     [oldmb], al             ;  is not a click)
        sti
        call    hires
        call    relist
        call    show_cursor
        jmp     act_now

; the time and date somewhere else on the dark screen
sv_move:
        call    tick
        add     ax, 364                 ; next in 20 s
        mov     [sv_due], ax
        cmp     word [sv_col], 0FFFFh
        je      .new
        mov     dx, [sv_y]
        mov     cx, 36
        mov     bx, [sv_col]
        mov     bp, 10
        xor     al, al
        call    fill_band
.new:   mov     ax, [sv_seed]
        mov     dx, 25173
        mul     dx
        add     ax, 13849
        mov     [sv_seed], ax
        xor     dx, dx
        mov     bx, 70
        div     bx
        mov     [sv_col], dx
        mov     ax, [sv_seed]
        xchg    al, ah
        xor     dx, dx
        mov     bx, 90
        div     bx
        shl     dx, 2
        mov     [sv_y], dx
        call    read_clock
        mov     di, tmp
        call    sb_hm
        mov     si, tmp
        mov     bx, [sv_col]
        mov     dx, [sv_y]
        xor     ah, ah
        call    puts
        mov     di, tmp
        call    sb_dmy
        mov     si, tmp
        mov     bx, [sv_col]
        mov     dx, [sv_y]
        add     dx, 20
        xor     ah, ah
        jmp     puts

; DEFRAG.COM /S from the root of the current drive.  CF if it isn't
; there or can't run; else AL = its exit code.  The mouse stays on: DEFRAG
; watches our mouse flag (passed as M=segment:offset).
sv_defrag:
        mov     ah, 19h
        int     21h
        add     al, 'A'
        mov     [s_defrag], al
        mov     dx, s_defrag
        mov     ax, 4300h
        int     21h
        jc      .no
        mov     di, sv_tail + 1
        mov     si, s_svarg
        call    sb_str
        mov     ax, cs
        call    sb_hex4
        mov     al, ':'
        stosb
        mov     ax, mflag
        call    sb_hex4
        mov     byte [di], 13
        mov     ax, di
        sub     ax, sv_tail + 1
        mov     [sv_tail], al
        mov     word [exec_epb], 0
        mov     word [exec_epb+2], sv_tail
        mov     [exec_epb+4], cs
        mov     word [exec_epb+6], exec_fcb
        mov     [exec_epb+8], cs
        mov     word [exec_epb+10], exec_fcb
        mov     [exec_epb+12], cs
        mov     dx, s_defrag
        mov     bx, exec_epb
        mov     ax, 4B00h
        int     21h
        cld
        push    cs
        pop     ds
        push    cs
        pop     es
        jc      .no
        mov     ah, 4Dh
        int     21h
        push    ax
        mov     dx, exec_dta
        mov     ah, 1Ah
        int     21h
        mov     ah, 36h                 ; the kernel takes the FAT in again
        xor     dl, dl                  ; now, while it is surely the same
        int     21h                     ; disk (so it can tell a swap later)
        pop     ax
        clc
        ret
.no:    stc
        ret

sb_hex4:                                ; AX as 4 hex digits at DI
        mov     cx, 4
.l:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .d
        add     al, 7
.d:     stosb
        pop     ax
        loop    .l
        ret

; the file name part of the path at SI, appended at DI
sb_base:
        mov     bx, si
.f:     lodsb
        or      al, al
        jz      .c
        cmp     al, '\'
        je      .s
        cmp     al, ':'
        jne     .f
.s:     mov     bx, si
        jmp     .f
.c:     mov     si, bx
        jmp     sb_str

; msgbuf in the prompt band until the next key or click
show_msg:
        call    hide_cursor
        call    band_clear
        mov     si, msgbuf
        mov     dx, BAND_Y + 4
        call    band_center
        mov     si, s_anykey
        mov     dx, BAND_Y + 20
        call    band_center
        mov     byte [msgshown], 1
        jmp     show_cursor

; the mouse again after a program (no new probe)
mouse_on:
        mov     ax, [mfound]
        or      ax, ax
        jz      .x
        mov     [mbase], ax
        mov     byte [mirq], 3
        cmp     ax, 2F8h
        je      .h
        mov     byte [mirq], 4
.h:     call    mouse_hook
.x:     ret

s_all       db '*.*', 0
s_defrag    db 'A:\DEFRAG.COM', 0
s_svarg     db ' /S M=', 0
s_claude    db 'A:\CLAUDE.COM', 0
s_noclaude  db 'CLAUDE.COM is not on this disk', 0
s_comspec   db 'COMSPEC='
s_defshell  db 'A:\GRIDCMD.COM', 0
s_notail    db 0, 13
exec_fcb    db 0, '           ', 0, 0, 0, 0
s_noopen    db ' - nothing opens this kind yet', 0
s_ended     db ' ended', 0
s_code      db ', exit code ', 0
s_cant      db "Can't run ", 0
s_colon     db ': ', 0
s_e2        db 'file not found', 0
s_e8        db 'not enough memory', 0
s_e11       db 'not a program', 0
s_eio       db 'disk error', 0
