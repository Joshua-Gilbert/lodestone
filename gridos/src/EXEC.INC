; =====================================================================
;  EXEC.INC - the Executive: the root process, on the UI core.  It uses
;  the kernel through INT 21h like any program: find first/next for the
;  list, CHDIR for subjects, EXEC for DOS programs; .RUN programs go
;  through the core's loader.
; =====================================================================
LIST_Y  equ 24          ; first list row (pixels)
LIST_N  equ 13          ; visible list rows
RULE2   equ 237
FORM_Y  equ 244         ; the File form: Device, Subject, Title, Kind,
ITEM_H  equ 20          ;  this far apart (room for the outline; text rows
                        ;  stay on multiples of 4, as the blitter wants)
INFO_Y  equ 336
TCOL    equ 3           ; title column
KEND    equ 77          ; kind column end (exclusive)
MAXENT  equ 240
FOC_TIT equ 0           ; the outlined item: Title (the list holds titles),
FOC_DEV equ 1           ;  Device (the drives),
FOC_SUB equ 2           ;  Subject (the subjects of this drive)
SUBJ    equ 14          ; a subject in the list: depth, NAME    EXT, date

section uibss
exec_dta    resb 44
entlist     resw MAXENT         ; -> entries (FAT layout), at the end of the
                                ;  UI segment's BSS (GRIDOS.ASM)
runpath     resb 80
argpath     resb 84                 ; X:\ + a 66-char subject + \ + NAME.EXT
dir_note    resw 1              ; load_dir: 0, a DOS error, or FFFFh (too many)
last_sel    resw 1              ; relist: the selection before an empty list
last_top    resw 1
focus       resb 1              ; FOC_*: the outlined item
dirty       resb 1              ; the drive or subject changed since Title
t_sel       resw 1              ; Title's place, while another item is out-
t_top       resw 1              ;  lined (subjects are read into entries)
nsubj       resw 1
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
            dw ex_row, ex_chg, 1, 78, ex_lvname
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
        call    focus_key               ; Tab, Shift-Tab; Return and ESC
        jnc     ex_loop                 ;  in Device and Subject
        mov     bx, ex_list
        call    lv_key
        jnc     ex_loop
        mov     si, ex_keys
        call    ui_dispatch
        jmp     ex_loop
.click: cmp     cx, BAND_Y              ; the prompt band: help
        jb      .form
        call    ex_help
        jmp     ex_loop
.form:  cmp     cx, FORM_Y - 2          ; an item of the form: outline it
        jb      .list
        mov     ax, cx
        sub     ax, FORM_Y - 2
        mov     cl, ITEM_H
        div     cl                      ; AL = item: Device, Subject, Title
        cmp     al, 2
        ja      ex_loop
        inc     al                      ; (item -> FOC_*)
        cmp     al, 3
        jb      .fi
        xor     al, al
.fi:    call    set_focus
        jmp     ex_loop
.list:  mov     bx, ex_list
        call    lv_click
        jc      ex_loop
        cmp     al, 1                   ; the selected row again: confirm
        jne     ex_loop
        cmp     byte [focus], FOC_TIT
        jne     .nx
        call    confirm
        jmp     ex_loop
.nx:    mov     ax, K_ENTER             ; (Device, Subject: the next item)
        call    focus_key
        jmp     ex_loop

; Tab / Shift-Tab: the next / previous item of the form (Title, Device,
; Subject, round).  In Device and Subject also Return (the next item) and
; ESC (back to Title); Left and Right there are Up and Down.  CF set (AX
; maybe changed) for a key that isn't one of these.
focus_key:
        mov     dl, 1
        cmp     ax, K_TAB
        je      .move
        mov     dl, 2
        cmp     ax, K_BTAB
        je      .move
        cmp     byte [focus], FOC_TIT
        je      .no
        mov     dl, 1
        cmp     ax, K_ENTER
        je      .move
        cmp     ax, K_ESC
        je      .tit
        cmp     ah, K_LEFT >> 8
        jne     .r
        mov     ax, K_UP
.r:     cmp     ah, K_RIGHT >> 8
        jne     .no
        mov     ax, K_DOWN
.no:    stc
        ret
.tit:   mov     al, FOC_TIT
        jmp     short .set
.move:  mov     al, [focus]
        add     al, dl
        cmp     al, 3
        jb      .set
        sub     al, 3
.set:   call    set_focus
        clc
        ret

; outline item AL (FOC_*): its choices in the list, then the screen again
set_focus:
        cmp     byte [focus], FOC_TIT   ; leaving Title: its place, to come
        jne     .f                      ;  back to if nothing changes
        mov     bx, [sel]
        mov     [t_sel], bx
        mov     bx, [top]
        mov     [t_top], bx
        mov     byte [dirty], 0
.f:     mov     [focus], al
        cmp     al, FOC_DEV
        je      .dev
        cmp     al, FOC_SUB
        je      .sub
        call    load_dir                ; Title: the titles again
        cmp     byte [dirty], 0
        jne     .draw
        mov     ax, [t_sel]
        cmp     ax, [nent]
        jae     .draw
        mov     [sel], ax
        mov     ax, [t_top]
        mov     [top], ax
        jmp     short .draw
.dev:   call    ndrives                 ; Device: the drives, this one chosen
        cbw
        mov     [nent], ax
        mov     ah, 19h
        int     21h
        cbw
        mov     [sel], ax
        mov     word [top], 0
        mov     word [dir_note], 0
        jmp     short .draw
.sub:   call    sub_build
.draw:  jmp     draw_all

; the list's selection moved: in Device and Subject it takes effect at once
ex_chg: cmp     byte [focus], FOC_DEV
        je      .dev
        cmp     byte [focus], FOC_SUB
        jne     .form
        mov     bx, [sel]               ; Subject: CHDIR there
        call    sub_path
        mov     dx, runpath
        mov     ah, 3Bh
        int     21h
        jc      .bad
        jmp     short .chg
.dev:   mov     dl, [sel]               ; Device: that drive
        mov     ah, 0Eh
        int     21h
.chg:   mov     byte [dirty], 1
        call    get_subject
.form:  jmp     draw_form
.bad:   mov     [ex_code], ax
        mov     si, runpath
        mov     bx, s_cantopen
        jmp     cant_msg

ex_help:
        mov     si, ex_keys
        mov     di, s_hlptitle
        jmp     ui_help

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
        xor     cx, cx                  ; files (the subjects are an item
        mov     ah, 4Eh                 ;  of the form of their own)
        int     21h
        jc      .first
        mov     di, entries
.e:     mov     ax, [nent]
        cmp     ax, [ent_max]           ; (fewer if the UI block couldn't
        jae     .full                   ;  have all its memory back)
        push    di
        call    dta2ent
        pop     di
        mov     bx, [nent]
        shl     bx, 1
        mov     [entlist+bx], di
        inc     word [nent]
        add     di, 32
        mov     ah, 4Fh
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
; the subject: the current directory, "\PATH"
get_subject:
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
relist: mov     al, [focus]
        cmp     al, FOC_TIT
        je      .tit
        mov     byte [focus], 0FFh      ; (Device, Subject: their list again)
        jmp     set_focus
.tit:   mov     ax, [sel]
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
        mov     cx, 8
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

; insertion sort of entlist by name
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

; compare the 11-byte names at SI and DI: flags as for SI - DI
ent_cmp:
        push    cx
        push    si
        push    di
        mov     cx, 11
        repe    cmpsb
        pop     di
        pop     si
        pop     cx
        ret

ent_ptr:                                ; BX = index -> SI = entry
        push    bx
        shl     bx, 1
        mov     si, [entlist+bx]
        pop     bx
        ret

ex_lvname:                                ; (type-to-find) AX = item -> SI
        mov     bx, ax
        cmp     byte [focus], FOC_DEV
        je      .dev
        cmp     byte [focus], FOC_SUB
        jne     ent_ptr
        mov     si, s_root
        or      bx, bx
        jz      .x
        call    sub_ptr
        inc     si
.x:     ret
.dev:   lea     si, [s_drvlet + bx]
        ret

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
        push    dx
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
        call    sb_fcb
        mov     byte [di], 0
        ret

; the 11-byte name at SI as NAME.EXT at DI (SI kept)
sb_fcb: push    si
        call    sb_title
        add     si, 8
        cmp     byte [si], ' '
        je      .x
        mov     al, '.'
        stosb
        mov     cx, 3
.e:     lodsb
        cmp     al, ' '
        je      .x
        stosb
        loop    .e
.x:     pop     si
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

; AL = floppy drives (1 or 2: the kernel's A: and B:)
ndrives:
        int     11h
        test    al, 1
        jz      .one
        shr     al, 6
        and     al, 1                   ; (2 or more: 2)
        inc     al
        ret
.one:   mov     al, 1
        ret

;  Subjects: Root, then every directory of the drive, depth first, by
;  name, read into the directory buffer (entries) while Subject is out-
;  lined.  Entry: depth (0 Root), NAME    EXT, date.
sub_build:
        mov     di, entries
        mov     byte [di], 0
        mov     word [di + 12], 0
        mov     word [nsubj], 1
        mov     word [dir_note], 0
        xor     bx, bx                  ; BX = the subject being read
.s:     cmp     bx, [nsubj]
        jae     .sel
        push    bx
        call    sub_scan
        pop     bx
        inc     bx
        jmp     .s
.sel:   mov     ax, [nsubj]             ; the list: this subject chosen
        mov     [nent], ax
        xor     bx, bx
.f:     push    bx
        call    sub_path
        mov     si, runpath
        mov     di, subject
        call    strlen
        inc     cx
        repe    cmpsb
        pop     bx
        je      .hit
        inc     bx
        cmp     bx, [nsubj]
        jb      .f
        xor     bx, bx
.hit:   mov     [sel], bx
        sub     bx, LIST_N - 1
        jae     .t
        xor     bx, bx
.t:     mov     [top], bx
        ret

; the subjects in subject BX, by name, into the list right after it
sub_scan:
        call    sub_ptr
        mov     al, [si]
        cmp     al, 5                   ; (deeper: a path DOS can't take)
        jae     .x
        inc     al
        mov     [tmp + 40], al          ; their depth
        mov     [tmp + 41], bx          ; the first goes after BX
        call    sub_path                ; "\PATH\*.*"
        cmp     di, runpath + 1
        je      .r
        mov     al, '\'
        stosb
.r:     mov     si, s_all
        call    sb_str
        mov     byte [di], 0
        mov     dx, runpath
        mov     cx, 10h
        mov     ah, 4Eh
        int     21h
        jc      .err
.e:     test    byte [exec_dta + 21], 10h
        jz      .n
        cmp     byte [exec_dta + 30], '.'
        je      .n
        mov     ax, [ent_max]           ; (room: 2 for each list entry)
        shl     ax, 1
        cmp     [nsubj], ax
        jae     .x
        mov     di, tmp
        call    dta2ent                 ; the name, FAT-style, at tmp
        mov     bx, [tmp + 41]          ; after the ones before it by name
.p:     inc     bx
        cmp     bx, [nsubj]
        jae     .ins
        call    sub_ptr
        mov     al, [si]
        cmp     al, [tmp + 40]
        jb      .ins                    ; (past this subject's ones)
        inc     si
        mov     di, tmp
        call    ent_cmp
        jb      .p
.ins:   call    sub_ptr                 ; make room at BX
        push    si
        mov     ax, [nsubj]
        push    bx
        mov     bx, ax
        call    sub_ptr
        pop     bx
        mov     cx, si
        pop     si
        push    si
        sub     cx, si                  ; (bytes after it)
        mov     di, si
        add     si, cx
        dec     si
        add     di, cx
        add     di, SUBJ - 1
        std
        rep     movsb
        cld
        pop     di
        mov     al, [tmp + 40]
        stosb
        mov     si, tmp
        mov     cx, 11
        rep     movsb
        mov     ax, [tmp + 24]
        stosw
        inc     word [nsubj]
.n:     mov     ah, 4Fh
        int     21h
        jnc     .e
        cmp     ax, 18
        je      .x
.err:   cmp     ax, 18                  ; (none there)
        je      .x
        cmp     ax, 2
        je      .x
        mov     [dir_note], ax
.x:     ret

; BX = subject -> SI = its entry
sub_ptr:
        push    ax
        push    dx
        mov     ax, SUBJ
        mul     bx
        add     ax, entries
        mov     si, ax
        pop     dx
        pop     ax
        ret

; BX = subject -> runpath = "\NAME\NAME" ("\" for Root); DI at its end
sub_path:
        mov     di, runpath
        mov     al, '\'
        stosb
        call    .emit
        cmp     di, runpath + 1
        je      .z
        dec     di                      ; (no '\' at the end)
.z:     mov     byte [di], 0
        ret
.emit:  push    bx                      ; BX's path's names, each with a '\'
        call    sub_ptr
        mov     al, [si]
        or      al, al
        jz      .r
        dec     al                      ; the parent: the nearest one before
.p:     dec     bx                      ;  it a level up
        push    si
        call    sub_ptr
        cmp     [si], al
        pop     si
        jne     .p
        push    si
        call    .emit
        pop     si
        inc     si
        call    sb_fcb
        mov     al, '\'
        stosb
.r:     pop     bx
        ret

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
        mov     si, s_lbl_dev           ; Device, Subject, Title, Kind
        mov     bx, TCOL
        mov     dx, FORM_Y
        xor     ah, ah
.lbl:   call    puts
        add     dx, ITEM_H
        cmp     dx, FORM_Y + 4 * ITEM_H
        jb      .lbl
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
        mov     bl, [focus]
        xor     bh, bh
        add     bx, bx
        mov     si, [prompts + bx]
        mov     di, s_prompt2
        jmp     ui_band

draw_empty:
        cmp     byte [focus], FOC_TIT
        jne     .x
        cmp     word [nent], 0
        jne     .x
        mov     si, s_nofiles
        mov     dx, LIST_Y + 16
        call    center
.x:     ret

; list row (the core's LV_DRAW): AX = entry, DX = y, CL = mask
ex_row: mov     [rowmask], cl
        mov     bx, ax
        cmp     byte [focus], FOC_DEV
        je      .dev
        cmp     byte [focus], FOC_SUB
        jne     .tit
        call    sub_ptr                 ; a subject: indented by its depth
        mov     di, tmp
        mov     cl, [si]
        mov     ch, 0
        jcxz    .root
        add     cx, cx
        mov     al, ' '
        rep     stosb
        inc     si
        call    sb_fcb
        dec     si
        jmp     short .sp
.root:  push    si
        mov     si, s_root
        call    sb_str
        pop     si
.sp:    mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, TCOL
        mov     ah, [rowmask]
        call    puts
        pop     si
        mov     ax, [si + 12]           ; its date (Root has none)
        or      ax, ax
        jz      .x
        mov     di, tmp
        call    sb_date
        mov     byte [di], 0
        mov     si, tmp
        mov     bx, 40
        mov     ah, [rowmask]
        jmp     puts
.dev:   mov     si, s_dev_a             ; a drive
        add     al, 'A'
        mov     [s_dev_a + 7], al
        mov     bx, TCOL
        mov     ah, [rowmask]
        jmp     puts
.x:     ret
.tit:   call    ent_ptr                 ; SI -> directory entry
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
        ; size
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
        call    kind_of
        call    strlen
        mov     bx, KEND
        sub     bx, cx
        mov     ah, [rowmask]
        jmp     puts

; the File form under the list: Device, Subject, Title, Kind (with the
; size and date), the outlined item in a box
draw_form:
        mov     dx, FORM_Y - 2          ; clear the values (cols 12..79)
        mov     cx, 4 * ITEM_H - 4
        mov     bx, 12
        mov     bp, 68
        xor     al, al
        call    fill_band
        mov     ah, 19h                 ; Device
        int     21h
        mov     si, s_dev_a
        add     al, 'A'
        mov     [s_dev_a + 7], al
        mov     bx, 14
        mov     dx, FORM_Y
        xor     ah, ah
        call    puts
        mov     si, subject + 1         ; Subject ("DOS.330\DEEP", or Root)
        cmp     byte [si], 0
        jne     .sub
        mov     si, s_root
.sub:   add     dx, ITEM_H
        call    puts
        mov     al, [focus]             ; the outline: FOC_* -> item 0..2
        add     al, 2
        cmp     al, 3
        jb      .o
        sub     al, 3
.o:     mov     ah, ITEM_H
        mul     ah
        add     ax, FORM_Y - 2
        mov     dx, ax
        mov     bx, 13
        mov     cx, 67
        call    hline
        push    dx
        add     dx, ITEM_H - 2
        call    hline
        pop     dx
        mov     ax, 13 * 8
        mov     cx, ITEM_H - 1
        call    vline
        mov     ax, 80 * 8 - 1
        call    vline
        cmp     byte [focus], FOC_TIT   ; Title and Kind: the chosen title's
        jne     .x                      ;  (none while another item is
        cmp     word [nent], 0          ;  outlined)
        je      .x
        mov     bx, [sel]
        call    ent_ptr
        mov     di, tmp
        call    sb_title
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, 14
        mov     dx, FORM_Y + 2 * ITEM_H
        xor     ah, ah
        call    puts
        pop     si
        push    si
        call    kind_of
        mov     dx, FORM_Y + 3 * ITEM_H
        xor     ah, ah
        call    puts
        pop     si
        mov     di, tmp                 ; 1234 bytes   dated 4-Oct-26
        mov     ax, [si+28]
        mov     cx, [si+30]
        call    sb_u32
        push    si
        mov     si, s_bytes
        call    sb_str
        mov     si, s_dated
        call    sb_str
        pop     si
        mov     ax, [si+24]
        call    sb_date
        mov     byte [di], 0
        mov     si, tmp
        mov     bx, 30
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
        KEY(K_NONE,      0,          h_tab)
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
        KEY(K_NONE,      0,          h_saver)
        KEY(K_NONE,      0,          h_code)
        dw 0

h_choose    db 'Up / Down, PgUp / PgDn   choose',0
h_home      db 'Home / End               first / last',0
h_tab       db 'Tab / Shift-Tab          Device, Subject, Title',0
h_letter    db 'A letter                 the next name with it',0
h_mouse     db 'Mouse                    point and click',0
h_confirm   db 'Return or click again    open it / next item',0
h_help      db 'CODE-?  or  F1           this help',0
h_usage     db 'CODE-U                   Usage: the System program',0
h_write     db 'CODE-W                   Write: a new text file',0
h_claude    db 'CODE-A                   Claude',0
h_shell     db 'CODE-C                   command prompt',0
h_f5        db 'F5                       after a disk swap',0
h_saver     db '5 minutes idle           screen saver',0
h_code      db 'CODE is the Alt key.  Any key closes.',0

; ---------------------------------------------------------------------
;  data
; ---------------------------------------------------------------------
s_brand     db 'Grid-OS 0.3',0
s_hlptitle  db 'Grid-OS 0.3 Help',0
prompts     dw s_prompt1, s_prdev, s_prsub
s_prompt1   db 'Select a file and confirm',0
s_prdev     db 'Device: Select item and confirm',0
s_prsub     db 'Subject: Select item and confirm',0
s_prompt2   db 'Or press CODE-? for help',0
s_sp2       db '  ',0
s_empty     db 0
s_nofiles   db '(no files)',0
s_lbl_dev   db 'Device',0
s_lbl_sub   db 'Subject',0
s_lbl_tit   db 'Title',0
s_lbl_kind  db 'Kind',0
s_dev_a     db 'Floppy A:',0
s_drvlet    db 'AB'                 ; (type-to-find in Device)
s_root      db 'Root',0
s_bytes     db ' bytes',0
s_dated     db '   dated ',0
s_nohires   db 'Grid-OS needs the GRiD 640x400 panel (BIOS mode 40h).',13,10
            db 'Press a key to restart.',13,10,0
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
