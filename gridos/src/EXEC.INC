; =====================================================================
;  EXEC.INC - the Executive: the root process, on the UI core.  It uses
;  the kernel through INT 21h like any program: find first/next for the
;  list, CHDIR for subjects, EXEC for DOS programs; .RUN programs go
;  through the core's loader.
; =====================================================================
LIST_Y  equ 24          ; first list row (pixels)
LIST_N  equ 13          ; visible list rows
RULE2   equ 237
FORM_Y  equ 244
INFO_Y  equ 336
TCOL    equ 3           ; title column
KEND    equ 77          ; kind column end (exclusive)
MAXENT  equ 240

section uibss
exec_dta    resb 44
entlist     resw MAXENT         ; -> entries (FAT layout), at the end of the
                                ;  UI segment's BSS (GRIDOS.ASM)
runpath     resb 80
argpath     resb 84                 ; X:\ + a 66-char subject + \ + NAME.EXT
dir_note    resw 1              ; load_dir: 0, a DOS error, or FFFFh (too many)
last_sel    resw 1              ; relist: the selection before an empty list
last_top    resw 1
subject     resb 70
ex_code     resw 1
rowmask     resb 1
panel       resb 1
convkb      resw 1
emskb       resw 1
extkb       resw 1
equip       resw 1
biosdate    resb 8
kindbuf     resb 4
msgbuf      resb 128
infobuf     resb 128
section ui

; the file list (UI_LV* layout); nent, sel and top are read by the tests
ex_list:    dw LIST_Y, LIST_N
nent        dw 0
sel         dw 0
top         dw 0
            dw ex_row, draw_form, 1, 78, ex_lvname
msgshown    db 0

ex_start:
        mov     dx, exec_dta
        mov     ah, 1Ah
        int     21h
        call    sysinfo
        call    build_info
        call    hires
        jnc     .hi
        mov     si, s_nohires
        call    bios_print
        xor     ah, ah
        int     16h
        jmp     reboot
.hi:    mov     word [redraw_fn], relist
        mov     byte [msgshown], 0
        call    load_dir
        call    draw_all

; ---------------------------------------------------------------------
ex_loop:
        push    word [ent_max]
        call    ui_room                 ; (after programs: room for .RUNs)
        pop     ax
        cmp     ax, [ent_max]
        je      .ev
        mov     al, [msgshown]
        push    ax
        call    relist                  ; (it moved: the whole list again)
        pop     ax
        or      al, al                  ; ("TSR.COM ended" was in the band:
        jz      .ev                     ;  relist drew the usual prompt)
        call    show_msg
.ev:    call    ui_event
        cmp     byte [msgshown], 0      ; a message waits for the next key
        je      .k
        mov     byte [msgshown], 0
        push    ax
        call    draw_prompt_default
        pop     ax
        cmp     ax, K_ENTER             ; (Return or a click only clears it)
        je      ex_loop
        cmp     ax, EV_CLICK
        je      ex_loop
.k:     cmp     ax, EV_CLICK
        je      .click
        mov     bx, ex_list
        call    lv_key
        jnc     ex_loop
        mov     si, ex_keys
        call    ui_dispatch
        jmp     ex_loop
.click: cmp     cx, BAND_Y              ; the prompt band: help
        jb      .list
        call    ex_help
        jmp     ex_loop
.list:  mov     bx, ex_list
        call    lv_click
        jc      ex_loop
        cmp     al, 1                   ; the selected file again: confirm
        jne     ex_loop
        call    confirm
        jmp     ex_loop

ex_help:
        mov     si, ex_keys
        mov     di, s_hlptitle
        jmp     ui_help

boot_rom:
        call    mouse_off
        mov     ax, 0003h
        int     10h
        mov     si, s_bootrom
        call    bios_print
        int     19h                     ; BIOS boot loop: EPROM first

reboot: call    mouse_off
        push    0
        pop     ds
        mov     word [472h], 1234h      ; warm boot
        jmp     0F000h:0FFF0h

bios_print:
        lodsb
        or      al, al
        jz      .x
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     bios_print
.x:     ret

; ---------------------------------------------------------------------
;  the directory
; ---------------------------------------------------------------------
; the current directory into entries/entlist, sorted
load_dir:
        mov     word [nent], 0
        mov     word [sel], 0
        mov     word [top], 0
        mov     word [dir_note], 0
        mov     dx, s_all
        mov     cx, 10h                 ; subdirectories too
        mov     ah, 4Eh
        int     21h
        jc      .first
        mov     di, entries
.e:     mov     ax, [nent]
        cmp     ax, [ent_max]           ; (fewer if the UI block couldn't
        jae     .full                   ;  have all its memory back)
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
        cmp     ax, 18                  ; no more files: the end
        je      .done
        jmp     .err
.first: cmp     ax, 18                  ; nothing there
        je      .done
        cmp     ax, 2
        je      .done
.err:   mov     [dir_note], ax          ; a disk error: said in the band
        jmp     .done
.full:  mov     word [dir_note], 0FFFFh ; more than fit: said in the band
.done:  call    sort_dir
        ; the subject: the current directory
        mov     byte [subject], '\'
        mov     si, subject + 1
        xor     dl, dl
        mov     ah, 47h
        int     21h
        jnc     .x
        mov     byte [subject + 1], 0
.x:     ret

; the list again, keeping the place in it (the core's redraw routine:
; after the screen saver, DEFRAG or a program the disk may differ)
relist: mov     ax, [sel]
        mov     bx, [top]
        cmp     word [nent], 0          ; (an empty list, e.g. while the
        jne     .keep                   ;  directory's memory was lent: the
        mov     ax, [last_sel]          ;  selection from before it)
        mov     bx, [last_top]
.keep:  mov     [last_sel], ax
        mov     [last_top], bx
        push    ax
        push    bx
        call    load_dir
        pop     ax
        pop     bx
        cmp     bx, [nent]
        jae     .r
        mov     [sel], bx
        cmp     ax, bx
        ja      .r
        mov     [top], ax
.r:     jmp     draw_all

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

; insertion sort of entlist: "..", then subjects, then files, by name
sort_dir:
        mov     cx, [nent]
        cmp     cx, 2
        jb      .x
        mov     bx, 2                   ; byte index i
.i:     mov     dx, [entlist+bx]        ; key
        mov     bp, bx
.j:     or      bp, bp
        jz      .put
        mov     si, [entlist+bp-2]
        mov     di, dx
        call    ent_cmp
        jbe     .put                    ; prev <= key
        mov     ax, [entlist+bp-2]
        mov     [entlist+bp], ax
        sub     bp, 2
        jmp     .j
.put:   mov     [entlist+bp], dx
        add     bx, 2
        mov     ax, [nent]
        shl     ax, 1
        cmp     bx, ax
        jb      .i
.x:     ret

; compare entries SI and DI: flags as for SI - DI
ent_cmp:
        push    cx
        push    si
        push    di
        call    .rank
        mov     ah, al
        xchg    si, di
        call    .rank
        xchg    si, di
        cmp     ah, al
        jne     .x
        mov     cx, 11
        repe    cmpsb
.x:     pop     di
        pop     si
        pop     cx
        ret
.rank:  mov     al, 0
        cmp     word [si], '..'
        je      .r
        mov     al, 1
        test    byte [si+11], 10h
        jnz     .r
        mov     al, 2
.r:     ret

ent_ptr:                                ; BX = index -> SI = entry
        push    bx
        shl     bx, 1
        mov     si, [entlist+bx]
        pop     bx
        ret

ex_lvname:                                ; (type-to-find) AX = item -> SI
        mov     bx, ax
        jmp     ent_ptr

; append the entry's title (name without trailing spaces) at DI
sb_title:
        push    si
        mov     cx, 8
.c:     lodsb
        cmp     al, ' '
        je      .x
        stosb
        loop    .c
.x:     pop     si
        ret

; SI = entry -> SI = kind string, AL = what opens it (0 nothing, 1 it's a
; DOS program, 2 a .RUN, 3 Write).  (Entry pointer lost; callers re-fetch.)
kind_of:
        test    byte [si+11], 10h
        jz      .file
        mov     si, k_subject
        xor     al, al
        ret
.file:  push    dx
        push    bx
        mov     ax, [si+8]
        mov     dl, [si+10]
        mov     bx, kinds
.k:     cmp     byte [bx], 0
        je      .raw
        cmp     ax, [bx]
        jne     .n
        cmp     dl, [bx+2]
        jne     .n
        mov     si, [bx+3]
        mov     al, [bx+5]
        jmp     .x
.n:     add     bx, 6
        jmp     .k
.raw:   mov     si, kindbuf             ; unknown extension: show it
        mov     [si], ax
        mov     [si+2], dl
        mov     byte [si+3], 0
        cmp     byte [si+2], ' '        ; (a shorter one: no trailing spaces)
        jne     .r1
        mov     byte [si+2], 0
        cmp     byte [si+1], ' '
        jne     .r1
        mov     byte [si+1], 0
.r1:    xor     al, al
        cmp     byte [si], ' '
        jne     .x
        mov     si, k_file
.x:     pop     bx
        pop     dx
        ret

; ---------------------------------------------------------------------
;  confirming: Return or a second click on the selected entry
; ---------------------------------------------------------------------
confirm:
        cmp     word [nent], 0
        je      .x
        mov     bx, [sel]
        call    ent_ptr
        test    byte [si+11], 10h
        jnz     .subject
        call    kind_of
        cmp     al, 1
        je      .dos
        cmp     al, 2
        je      .run
        cmp     al, 3
        je      .write
        mov     di, msgbuf              ; nothing opens it: say so
        mov     bx, [sel]
        call    ent_ptr
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
        call    sel_name                ; CHDIR into it (by NAME.EXT: a
        mov     dx, runpath             ;  subject can have an extension)
        mov     ah, 3Bh
        int     21h
        jc      .nosub
        call    load_dir
        mov     bx, ex_list
        call    lv_draw
        call    draw_empty
        call    draw_form
        jmp     dir_band
.nosub: mov     [ex_code], ax
        mov     si, runpath
        mov     bx, s_cantopen
        jmp     cant_msg
.dos:   call    sel_name                ; NAME.EXT in the current directory
        jmp     run_prog
.run:   call    sel_name
        mov     si, runpath
        mov     di, s_empty
        jmp     run_run
.write: call    sel_path                ; X:\SUBJECT\NAME.EXT for Write
        mov     di, argpath
        mov     si, s_write
        jmp     run_named
.x:     ret

; the selected entry as NAME.EXT in runpath
sel_name:
        mov     bx, [sel]
        call    ent_ptr
        mov     di, runpath
        call    sb_title
        mov     al, '.'
        stosb
        add     si, 8
        mov     cx, 3
.e:     lodsb
        cmp     al, ' '
        je      .x
        stosb
        loop    .e
.x:     cmp     byte [di-1], '.'
        jne     .z
        dec     di
.z:     mov     byte [di], 0
        ret

; the selected entry with its whole path in argpath
sel_path:
        call    sel_name
        mov     di, argpath
        mov     ah, 19h
        int     21h
        add     al, 'A'
        stosb
        mov     ax, ':\'
        stosw
        mov     si, subject + 1
        cmp     byte [si], 0
        je      .n
        call    sb_str
        mov     al, '\'
        stosb
.n:     mov     si, runpath
        call    sb_str
        mov     byte [di], 0
        ret

; CODE-C: the command shell from COMSPEC
run_shell:
        push    es
        mov     ah, 62h                 ; our PSP (the root's)
        int     21h
        mov     es, bx
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
        mov     si, s_claude
        call    ui_findapp
        jc      .no
        mov     di, runpath
        call    sb_str
        mov     byte [di], 0
        jmp     run_prog
.no:    mov     di, msgbuf
        mov     si, s_claude
        call    sb_str
        mov     si, s_notondisk
        call    sb_str
        mov     byte [di], 0
        jmp     show_msg

; CODE-U: Usage, the System program; CODE-W: Write with a new file
run_usage:
        mov     si, s_system
        mov     di, s_empty
        jmp     run_named
run_write:
        mov     si, s_write
        mov     di, s_empty
        ; (falls through)

; the .RUN named SI (here, else in the root) with argument DI
run_named:
        push    si
        call    ui_findapp
        jc      .no
        add     sp, 2
        jmp     run_run
.no:    pop     si
        mov     di, msgbuf
        call    sb_str
        mov     si, s_notondisk
        call    sb_str
        mov     byte [di], 0
        jmp     show_msg

; run the .RUN at SI with argument DI, then the list again
run_run:
        push    si
        call    run_app
        mov     word [redraw_fn], relist
        jc      .fail
        add     sp, 2
        jmp     relist
.fail:  pop     si
        mov     [ex_code], ax
        push    si
        call    relist
        pop     si
        jmp     cant_run

; F5: the disk again (after changing floppies)
refresh:
        mov     ah, 0Dh
        int     21h
        jmp     relist

; run the DOS program at runpath; afterwards a fresh list and a message
run_prog:
        mov     si, runpath
        mov     di, s_empty
        call    ui_run                  ; (redraws the list itself)
        jc      .failed
        mov     [ex_code], ax
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
        mov     [ex_code], ax
        mov     si, runpath
cant_run:                               ; "Can't run X: why"
        mov     bx, s_cant
cant_msg:                               ; (BX = "Can't run " / "Can't open ")
        mov     di, msgbuf
        push    si
        mov     si, bx
        call    sb_str
        pop     si
        call    sb_base
        mov     si, s_colon
        call    sb_str
        mov     ax, [ex_code]
        call    api_sberr
        mov     byte [di], 0
        jmp     show_msg

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
        mov     si, msgbuf
        mov     di, s_anykey
        call    ui_band
        mov     byte [msgshown], 1
        ret

; ---------------------------------------------------------------------
;  the screen
; ---------------------------------------------------------------------
draw_all:
        mov     si, s_brand
        call    ui_screen
        mov     bx, ex_list
        call    lv_draw
        call    draw_empty
        mov     dx, RULE2
        xor     bx, bx
        mov     cx, 80
        call    hline
        mov     si, s_lbl_dev
        mov     bx, TCOL
        mov     dx, FORM_Y
        xor     ah, ah
        call    puts
        mov     si, s_lbl_sub
        mov     dx, FORM_Y + 16
        call    puts
        mov     si, s_lbl_tit
        mov     dx, FORM_Y + 36
        call    puts
        mov     si, s_lbl_kind
        mov     dx, FORM_Y + 56
        call    puts
        mov     si, s_lbl_size
        mov     dx, FORM_Y + 72
        call    puts
        call    draw_form
        mov     si, infobuf
        mov     dx, INFO_Y
        call    center
        mov     dx, INFO_Y - 4
        mov     bx, 1
        mov     cx, 78
        call    hline_dots
        jmp     dir_band

; the band after reading a directory: what went wrong, or the usual prompt
dir_band:
        mov     ax, [dir_note]
        or      ax, ax
        jz      draw_prompt_default
        mov     di, msgbuf
        cmp     ax, 0FFFFh
        je      .more
        mov     si, s_cantdir           ; "Can't read the disk: why"
        call    sb_str
        call    api_sberr
        jmp     .m
.more:  mov     si, s_first             ; "Only the first 240 are listed"
        call    sb_str
        mov     ax, [nent]
        call    sb_u16
        mov     si, s_listed
        call    sb_str
.m:     mov     byte [di], 0
        jmp     show_msg

draw_prompt_default:
        mov     byte [msgshown], 0
        mov     si, s_prompt1
        mov     di, s_prompt2
        jmp     ui_band

draw_empty:
        cmp     word [nent], 0
        jne     .x
        mov     si, s_nofiles
        mov     dx, LIST_Y + 16
        call    center
.x:     ret

; list row (the core's LV_DRAW): AX = entry, DX = y, CL = mask
ex_row: mov     [rowmask], cl
        mov     bx, ax
        call    ent_ptr                 ; SI -> directory entry
        mov     di, tmp
        call    sb_title
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, TCOL
        mov     ah, [rowmask]
        call    puts
        pop     si
        ; date
        mov     di, tmp
        mov     ax, [si+24]
        call    sb_date
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, 40
        mov     ah, [rowmask]
        call    puts
        pop     si
        ; size (files only)
        test    byte [si+11], 10h
        jnz     .nosz
        mov     di, tmp
        mov     ax, [si+28]
        mov     cx, [si+30]
        call    sb_u32
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, 60
        call    strlen
        sub     bx, cx
        mov     ah, [rowmask]
        call    puts
        pop     si
.nosz:  call    kind_of
        call    strlen
        mov     bx, KEND
        sub     bx, cx
        mov     ah, [rowmask]
        jmp     puts

; form under the list for the selected entry
draw_form:
        ; clear value area (cols 12..79 of the five form rows)
        mov     dx, FORM_Y
        mov     cx, 88
        mov     bx, 12
        mov     bp, 67
        xor     al, al
        call    fill_band
        mov     ah, 19h
        int     21h
        mov     si, s_dev_a
        add     al, 'A'
        mov     [s_dev_a + 7], al
        mov     bx, 14
        mov     dx, FORM_Y
        xor     ah, ah
        call    puts
        mov     si, subject
        cmp     word [si], '\'
        jne     .sub
        mov     si, s_root
.sub:   mov     dx, FORM_Y + 16
        call    puts
        ; title box
        mov     dx, FORM_Y + 33
        mov     bx, 13
        mov     cx, 28
        call    hline
        mov     dx, FORM_Y + 54
        call    hline
        mov     ax, 13 * 8
        mov     dx, FORM_Y + 33
        mov     cx, 22
        call    vline
        mov     ax, 41 * 8 - 1
        call    vline
        cmp     word [nent], 0
        je      .x
        mov     bx, [sel]
        call    ent_ptr
        mov     di, tmp
        call    sb_title
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, 14
        mov     dx, FORM_Y + 36
        xor     ah, ah
        call    puts
        pop     si
        call    kind_of
        mov     bx, 14
        mov     dx, FORM_Y + 56
        xor     ah, ah
        call    puts
        mov     bx, [sel]
        call    ent_ptr
        mov     di, tmp
        test    byte [si+11], 10h
        jnz     .dir
        mov     ax, [si+28]
        mov     cx, [si+30]
        call    sb_u32
        push    si
        mov     si, s_bytes
        call    sb_str
        pop     si
        push    si
        mov     si, s_dated
        jmp     .dt
.dir:   push    si
        mov     si, s_dated + 3
.dt:    call    sb_str
        pop     si
        mov     ax, [si+24]
        call    sb_date
        mov     byte [di], 0
        mov     si, tmp
        mov     bx, 14
        mov     dx, FORM_Y + 72
        xor     ah, ah
        call    puts
.x:     ret

; ---------------------------------------------------------------------
;  the system information line
; ---------------------------------------------------------------------
sysinfo:
        int     12h
        mov     [convkb], ax
        mov     ax, 0E440h
        int     15h
        jnc     .e1
        xor     cx, cx
.e1:    mov     [emskb], cx
        mov     ax, 0E441h
        int     15h
        jnc     .e2
        xor     cx, cx
.e2:    mov     [extkb], cx
        int     11h
        mov     [equip], ax
        mov     dx, 7F8h
        in      al, dx
        mov     [panel], al
        push    ds
        mov     ax, 0F000h
        mov     ds, ax
        mov     si, 0FFF5h
        push    cs
        pop     es
        mov     di, biosdate
        mov     cx, 8
        rep     movsb
        pop     ds
        ret

build_info:
        mov     di, infobuf
        mov     si, s_cpu
        call    sb_str
        test    byte [equip], 2
        jz      .nf
        mov     si, s_fpu
        call    sb_str
.nf:    mov     si, s_gap
        call    sb_str
        mov     ax, [convkb]
        call    sb_u16
        mov     si, s_k
        call    sb_str
        mov     ax, [emskb]
        mov     si, s_ems
        or      ax, ax
        jnz     .m
        mov     ax, [extkb]
        mov     si, s_ext
.m:     push    si
        push    ax
        mov     si, s_plus
        call    sb_str
        pop     ax
        call    sb_u16
        pop     si
        call    sb_str
        mov     si, s_gap
        call    sb_str
        mov     al, [panel]
        and     al, 0Fh
        mov     si, s_plasma
        cmp     al, 0Dh
        je      .p
        mov     si, s_lcd
        cmp     al, 0Fh
        je      .p
        mov     si, s_panel
.p:     call    sb_str
        mov     si, s_gap
        call    sb_str
        mov     si, s_nomouse
        mov     ax, [mbase]
        or      ax, ax
        jz      .mo
        mov     si, s_mouse2
        cmp     ax, 2F8h
        je      .mo
        mov     si, s_mouse1
.mo:    call    sb_str
        mov     si, s_gap
        call    sb_str
        mov     si, s_bios
        call    sb_str
        mov     si, biosdate
        mov     cx, 8
        rep     movsb
        mov     byte [di], 0
        ret

; ---------------------------------------------------------------------
;  keys (and the help window, which is made from this table)
; ---------------------------------------------------------------------
ex_keys:
        KEY(K_NONE,      0,          h_choose)
        KEY(K_NONE,      0,          h_home)
        KEY(K_NONE,      0,          h_letter)
        KEY(K_NONE,      0,          h_mouse)
        KEY(K_ENTER,     confirm,    h_confirm)
        KEY(K_F1,        ex_help,    h_help)
        KEY(K_CODE_HELP, ex_help,    0)
        KEY(K_CODE_U,    run_usage,  h_usage)
        KEY(K_CODE_W,    run_write,  h_write)
        KEY(K_CODE_A,    run_claude, h_claude)
        KEY(K_CODE_C,    run_shell,  h_shell)
        KEY(K_F5,        refresh,    h_f5)
        KEY(K_CODE_D,    boot_rom,   h_dos)
        KEY(K_CODE_R,    reboot,     h_restart)
        KEY(K_NONE,      0,          h_saver)
        KEY(K_NONE,      0,          h_code)
        dw 0

h_choose    db 'Up / Down, PgUp / PgDn   choose a file',0
h_home      db 'Home / End               first / last',0
h_letter    db 'A letter                 the next name with it',0
h_mouse     db 'Mouse                    point and click',0
h_confirm   db 'Return or click again    run it / open it',0
h_help      db 'CODE-?  or  F1           this help',0
h_usage     db 'CODE-U                   Usage: the System program',0
h_write     db 'CODE-W                   Write: a new text file',0
h_claude    db 'CODE-A                   Claude',0
h_shell     db 'CODE-C                   command prompt',0
h_f5        db 'F5                       after a disk swap',0
h_dos       db 'CODE-D                   boot GRiD MS-DOS',0
h_restart   db 'CODE-R                   restart',0
h_saver     db '5 minutes idle           screen saver',0
h_code      db 'CODE is the Alt key.  Any key closes.',0

; ---------------------------------------------------------------------
;  data
; ---------------------------------------------------------------------
s_brand     db 'Grid-OS 0.3',0
s_hlptitle  db 'Grid-OS 0.3 Help',0
s_prompt1   db 'Select a file and confirm',0
s_prompt2   db 'Or press CODE-? for help',0
s_sp2       db '  ',0
s_empty     db 0
s_nofiles   db '(no files)',0
s_lbl_dev   db 'Device',0
s_lbl_sub   db 'Subject',0
s_lbl_tit   db 'Title',0
s_lbl_kind  db 'Kind',0
s_lbl_size  db 'Size',0
s_dev_a     db 'Floppy A:',0
s_root      db 'Root',0
s_bytes     db ' bytes',0
s_dated     db '   dated ',0
s_nohires   db 'Grid-OS needs the GRiD 640x400 panel (BIOS mode 40h).',13,10
            db 'Press a key to restart.',13,10,0
s_bootrom   db 'Grid-OS: booting from the EPROM...',13,10,0
s_cpu       db '80286',0
s_fpu       db '+80287',0
s_gap       db '   ',0
s_k         db 'K',0
s_plus      db ' + ',0
s_ems       db 'K EMS',0
s_ext       db 'K ext',0
s_plasma    db 'Plasma 640x400',0
s_lcd       db 'LCD 640x400',0
s_panel     db 'Panel',0
s_mouse1    db 'Mouse COM1',0
s_mouse2    db 'Mouse COM2',0
s_nomouse   db 'No mouse',0
s_bios      db 'BIOS ',0
s_all       db '*.*', 0
s_claude    db 'CLAUDE.COM', 0
s_system    db 'SYSTEM.RUN', 0
s_write     db 'WRITE.RUN', 0
s_notondisk db ' is not on this disk', 0
s_comspec   db 'COMSPEC='
s_defshell  db 'A:\GRIDCMD.COM', 0
s_noopen    db ' - nothing opens this kind yet', 0
s_ended     db ' ended', 0
s_code      db ', exit code ', 0
s_cant      db "Can't run ", 0
s_cantopen  db "Can't open ", 0
s_cantdir   db "Can't read the disk: ", 0
s_first     db 'Only the first ', 0
s_listed    db ' are listed', 0
s_colon     db ': ', 0
k_subject   db 'Subject',0
k_file      db 'File',0
k_run       db 'Run',0
k_program   db 'Program',0
k_system    db 'System',0
k_text      db 'Text',0
k_data      db 'Data',0
k_batch     db 'Batch',0
k_settings  db 'Settings',0
k_font      db 'Font',0
k_profile   db 'Profile',0
k_source    db 'Source',0
; extension, kind, what opens it (1 DOS, 2 .RUN, 3 Write)
kinds       db 'COM'
            dw k_run
            db 1
            db 'EXE'
            dw k_run
            db 1
            db 'RUN'
            dw k_program
            db 2
            db 'SYS'
            dw k_system
            db 0
            db 'TXT'
            dw k_text
            db 3
            db 'DOC'
            dw k_text
            db 3
            db 'BIN'
            dw k_data
            db 0
            db 'DAT'
            dw k_data
            db 0
            db 'BAT'
            dw k_batch
            db 3
            db 'CFG'
            dw k_settings
            db 3
            db 'INI'
            dw k_settings
            db 3
            db 'EMS'
            dw k_settings
            db 0
            db 'TYP'
            dw k_font
            db 0
            db 'PRO'
            dw k_profile
            db 3
            db 'ASM'
            dw k_source
            db 3
            db 'INC'
            dw k_source
            db 3
            db 'C  '
            dw k_source
            db 3
            db 'H  '
            dw k_source
            db 3
            db 0
