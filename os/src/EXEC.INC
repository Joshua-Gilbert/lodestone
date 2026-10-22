; =====================================================================
;  EXEC.INC - the Executive: the root process, on the UI core.  It uses
;  the kernel through INT 21h like any program: find first/next for the
;  list, CHDIR for subjects, EXEC for DOS programs; .RUN programs go
;  through the core's loader.  Copy, Erase, Move and Rename work on the
;  chosen title; Copy and Erase on the chosen subject too.
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
SUBMAX  equ 66          ; a subject's path, "\" and all (the kernel's CWDLEN - 2)

section uibss
exec_dta    resb 44
entlist     resw MAXENT         ; -> entries (FAT layout), at the end of the
                                ;  UI segment's BSS (LODE.ASM)
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
lampw       resb 1                  ; the coprocessor lamp: 0 none, 7 80287, 9 287XL
biosdate    resb 8
kindbuf     resb 4
msgbuf      resb 128
infobuf     equ tmp                 ; the information line: built by draw_all
                                    ;  just before it is drawn (draw_form and
                                    ;  the clock use tmp too)
dstpath     resb 84                 ; Copy, Move: X: + \ + a 66-char subject + \ +
tmppath     resb 84                 ;  NAME.EXT (83); the subject it goes to, then
                                    ;  the new file in it (X:\SUBJECT\ABCDTMP, 78)
curdir      resb 72                 ; X:\SUBJECT, where the list is
c_sub       resb SUBMAX + 1         ; the forms' fields: Subject, Title, Device
c_tit       resb 13
c_dev       resb 1
fcbbuf      equ tmp                 ; relist_name's title (11; load_dir
                                    ;  doesn't use tmp)
xmode       resb 1                  ; 0 Copy, 1 Move
x_here      resb 1                  ; 1: it goes to the subject listed
d_exists    resb 1                  ; the destination is there already
tmp_made    resb 1                  ; copy_file made the new file (delete it on failure)
tmp_kept    resb 1                  ; ... and kept it: the old destination was gone
x_part      resb 1                  ; Move: copied, but the original stays
id_src      equ tmp                 ; same_file: drive, directory, entry
id_dst      equ tmp + 5
ftitle      resb 24                 ; the form's window title: "Copy NAME.EXT"
o_sel       resw 1                  ; the list's place before a command
o_top       resw 1
h_src       resw 1
h_tmp       resw 1
buf_seg     resw 1
buf_len     resw 1
f_time      resw 1
f_date      resw 1
tpath       equ dstpath             ; Delete on a subject: the path walked
t_lvl       resw 1                  ;  (X:\ + at most 66 + \NAME.EXT)
c_pat       resb 13                 ; the forms' Titles: a title or a pattern
c_repl      resb 1                  ; Replace: 0 Ask, 1 All, 2 None
c_newer     resb 1                  ; Only newer: 0 No, 1 Yes
wild        resb 1                  ; 1: Titles has * or ?
x_skip      resb 1                  ; xfer_do left it: 1 (Replace None, not
                                    ;  newer), 2 (ESC at the question)
nm_seg      resw 1                  ; the titles matched (pat_find): 17 bytes
nm_max      resw 1                  ;  each, NAME.EXT + 0 in 13, time, date
nm_n        resw 1
nm_i        resw 1
n_done      resw 1
n_skip      resw 1
s_time      resw 1                  ; the one in hand: its time and date
s_date      resw 1
sc_seg      resw 1                  ; Copy on a subject: the subjects to copy (sc_list)
sc_rd       resw 1                  ;  the one in hand
sc_wr       resw 1                  ;  the end of the list
sc_max      resw 1                  ;  the block's size
sc_lim      resw 1                  ;  the longest path below it DOS takes, both ends
section ui

; the file list (UI_LV* layout); nent, sel and top are read by the tests
ex_list:    dw LIST_Y, LIST_N
nent        dw 0
sel         dw 0
top         dw 0
            dw ex_row, ex_chg, 1, 78, ex_lvname
msgshown    db 0

; The Executive's DTA is exec_dta from here on, always: exec_raw puts it
; back after a DOS program, run_app after a .RUN, ui_room after the block
; moves (with MULTITASK=1 the kernel keeps each task's own), so nothing
; that finds files sets it again
ex_start:
        mov     dx, exec_dta
        mov     ah, 1Ah
        int     21h
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
        mov     [nent], ax
        mov     [sel], dx
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
.dev:   mov     al, [sel]               ; Device: that drive
        call    drv_let
        sub     al, 'A'
        xchg    dx, ax
        mov     ah, 0Eh
        int     21h
.chg:   mov     byte [dirty], 1
        call    get_subject
.form:  jmp     draw_form
.bad:   mov     bx, s_cantopen
        jmp     cant_ax

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
        call    ff                      ;  of the form of their own)
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
; (AX, BX, CX, SI, DI change)
dta2ent:
        mov     si, exec_dta + 30
        call    to_fcb                  ; (BX = DI as it was)
        mov     al, [exec_dta+21]
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
.dev:   imul    si, bx, 3               ; ("A:", ...)
        add     si, o_drives
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
        mov     al, [bx+3]              ; (from k_file)
        cbw
        add     ax, k_file
        xchg    si, ax
        mov     al, [bx+4]
        jmp     .x
.n:     add     bx, 5
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
        jmp     sb_show
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

; the selected entry with its whole path in argpath (and curdir set)
sel_path:
        call    sel_name
        call    cur_dir
.arg:   mov     di, argpath             ; (nm_next: runpath's whole path)
        mov     si, runpath
        jmp     sb_dirname

; CODE-P: the command prompt (COMSPEC)
run_shell:
        push    es
        mov     si, s_comspec
        mov     cx, 8
        call    env_find
        jc      .def
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
        call    sb_strz
        jmp     run_prog
.no:    jmp     run_named.nf            ; (SI = the name: ui_findapp's answer)

; CODE-K: the calculator, a window over the list
run_calc:
        mov     si, s_calc
        jmp     run_write.e

; CODE-U: Usage, the System program; CODE-W: Write with a new file
run_usage:
        mov     si, s_system
        jmp     short run_write.e
run_write:
        mov     si, s_write
.e:     mov     di, s_empty
        ; (falls through)

; the .RUN named SI (here, else in the root) with argument DI
run_named:
        push    si
        call    ui_findapp
        jc      .no
        add     sp, 2
        jmp     run_run
.no:    pop     si
.nf:    call    msg_begin               ; "WRITE.RUN is not on this disk"
        mov     si, s_notondisk
        jmp     sb_show

; run the .RUN at SI with argument DI, then the list again (not after
; exit code 0FFFFh: it left the screen as it found it, as the calculator)
run_run:
        push    si
        call    run_app
        mov     word [redraw_fn], relist
        jc      .fail
        add     sp, 2
        inc     ax
        jz      .kept
        jmp     relist
.kept:  ret
.fail:  pop     si
        mov     [ex_code], ax
        push    si
        call    relist
        pop     si
        mov     bx, s_cant
        jmp     cant_msg

; F5: the disk again (after changing floppies)
refresh:
        mov     ah, 0Dh
        int     21h
        jmp     relist

; AL = drive -> SI = its name: "Floppy A:", "Hard disk C:"
dev_str:                                ; AL = the drive's letter -> SI
        mov     si, s_dev_r
        cmp     al, 'R'
        je      .x
        mov     si, s_dev_m
        cmp     al, 'M'
        je      .x
        mov     si, s_dev_c
        cmp     al, 'C'
        je      .x
        mov     si, s_dev_a
        mov     [s_dev_a + 7], al
.x:     ret

; AX = drives to list, their letters in o_drives (the forms' choices: "A:",
; and "B:", "C:", "M:" when the kernel has them - a second floppy, the
; hard disk, the temporary disk -, a 0 after the last); DX = the current
; drive's place among them (0 if it isn't there).  BX changed
ndrives:
        mov     ah, 19h
        int     21h
        inc     ax
        mov     dh, al                  ; DH = the current drive (1 = A:)
        xor     cx, cx                  ; CX = drives so far
        mov     dl, ch                  ; DL = its place
        mov     di, o_drives
        mov     bl, 1                   ; BL: A: to R: (D: to L:, N: to Q:
                                        ;  never there)
.l:     call    has_drv
        jc      .n
        cmp     bl, dh
        jne     .s
        mov     dl, cl
.s:     lea     ax, [bx + 'A' - 1]
        stosb
        inc     di
        inc     di
        inc     cx
.n:     inc     bx
        cmp     bl, 18
        jbe     .l
        mov     [di], ch
        mov     dh, ch
        xchg    ax, cx
        ret
; drive BL there (1 = A:)?  CF if not (IOCTL 4408h answers 15: no such drive)
has_drv:
        mov     ax, 4408h
        int     21h
        ret

;  Subjects: Root, then every directory of the drive, depth first, by
;  name, read into the directory buffer (entries) while Subject is out-
;  lined.  Entry: depth (0 Root), NAME    EXT, date.  No room for the
;  buffer (a program just left something resident right after the UI
;  block, which the main loop's ui_room moves past it next): an empty list
;  for now, nothing written there.
sub_build:
        xor     ax, ax
        mov     [nsubj], ax
        mov     [nent], ax
        cmp     [ent_max], ax
        je      .none
        mov     di, entries
        mov     [di], al
        mov     [di + 12], ax
        inc     word [nsubj]
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
.none:  ret

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
        call    sb_strz
        mov     dx, runpath
        mov     cx, 10h
        call    ff
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
        je      show_msgz
        mov     si, s_code
        call    sb_str
        mov     al, [ex_code]
        xor     ah, ah
        call    sb_u16
        jmp     short show_msgz
.failed:
        mov     bx, s_cant
; "Can't run X: why" in the band (BX = the verb: s_cant, s_cantopen ...):
; X runpath and the error AX (cant_ax) or ex_code's (cant_rp), or (cant_msg)
; X the file name part of the path SI.  (BX changes)
cant_ax:
        mov     [ex_code], ax
cant_rp:
        mov     si, runpath
cant_msg:
        call    .h
        mov     si, s_colon
        call    sb_str
        mov     ax, [ex_code]
        call    api_sberr
        jmp     short show_msgz
.h:     push    si                      ; msgbuf = "Can't ", the verb BX, the
        mov     si, s_cant_             ;  file name part of the path SI
        call    msg_begin
        mov     si, bx
        call    sb_str
        pop     si
        ; (falls through)

; the file name part of the path at SI, appended at DI (BX changes)
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

; msgbuf begun with the text at SI (DI past it)
msg_begin:
        mov     di, msgbuf
        jmp     sb_str
; the text at SI added at DI and ended with a 0 (DI on it; CF clear)
sb_strz:
        call    sb_str
        mov     byte [di], 0
        ret
; the text at SI added, msgbuf ended and asked (ui_ask: CF for no)
sb_ask: call    sb_strz
        mov     si, msgbuf
        jmp     ui_ask
; the text at SI added, msgbuf ended (show_msgz: at DI) and shown
sb_show:
        call    sb_str
show_msgz:
        mov     byte [di], 0
; msgbuf in the prompt band until the next key or click
show_msg:
        mov     si, msgbuf
        mov     di, s_anykey
        call    ui_band
        mov     byte [msgshown], 1
        ret

; ---------------------------------------------------------------------
;  file commands on the chosen title, verb first as in GRiD's Executive:
;  the command, then a form or a question, then confirm.  CODE-C Copy,
;  CODE-D Delete (erase), CODE-M Move, CODE-R Rename
; ---------------------------------------------------------------------
COPYBUF equ 800h                        ; Copy's buffer: 32 KB (paragraphs)

; CF (and a beep) unless a title is chosen: Title outlined, a file listed
file_ok:
        cmp     byte [focus], FOC_TIT
        jne     .no
        cmp     word [nent], 0
        je      .no
        clc
        ret
.no:    call    ui_beep
        stc
        ret

; CODE-D: Delete (erase).  A form: Titles, the chosen one to start with;
; with * or ? in it a question first, then each title that matches
ex_erase:
        cmp     byte [focus], FOC_SUB   ; a subject: sub_erase
        je      sub_erase
        call    file_ok
        jc      .x
        call    sel_name
        mov     si, s_delete
        call    form_title
        call    pat_init
        mov     si, del_form
        call    ui_form
        jc      .x
        mov     bx, s_canterase
        call    pat_check
        jc      .x
        cmp     byte [wild], 0
        je      .go
        mov     si, s_eraseq            ; "Erase: Confirm to erase 5 titles *.BAK"
        call    msg_begin
        mov     ax, [nm_n]
        call    sb_n_tit
        mov     al, ' '
        stosb
        mov     si, c_pat
        call    sb_ask
        jc      nm_free
.go:    call    nm_next
        jc      .end
        call    api_criterr             ; (an old disk error forgotten)
        mov     dx, argpath
        mov     ah, 41h
        int     21h
        jc      .err
        inc     word [n_done]
        jmp     .go
.x:     ret
.err:   cmp     ax, 5                   ; Access denied: read-only?
        jne     .e
        push    ax
        mov     dx, argpath
        mov     ax, 4300h
        int     21h
        pop     ax
        jc      .e
        test    cl, 1
        jz      .e
        inc     word [n_skip]           ; (several: counted, the rest go on)
        cmp     byte [wild], 0
        jne     .go
        call    nm_free
        mov     bx, s_canterase
        mov     si, s_readonly
        jmp     cant_why
.e:     mov     [ex_code], ax
        call    nm_relist
        mov     bx, s_canterase
        jmp     cant_rp
.end:   call    nm_relist
        cmp     byte [wild], 0
        je      .x
        mov     si, s_erased            ; "Erased 5 titles, 1 read-only kept"
        call    msg_begin
        mov     ax, [n_done]
        call    sb_n_tit
        mov     si, s_rokept
        jmp     sum_skip

; CODE-D with Subject outlined: the chosen subject (the current one) and
; all in it, after a question ("Erase: Confirm to erase \OLD and all in
; it").  Not Root.  The list then shows the subject above it
sub_erase:
        cmp     byte [subject + 1], 0
        jne     .go
        jmp     ui_beep
.go:    mov     di, tpath               ; "X:\OLD"
        call    cur_dir.at
        mov     si, s_eraseq
        call    msg_begin
        mov     si, subject
        call    sb_str
        mov     si, s_allin
        call    sb_ask
        jc      .x
        mov     dx, s_dotdot            ; out of it, to the one above
        mov     ah, 3Bh
        int     21h
        jc      .bad
        mov     byte [dirty], 1
        call    tree_del
        jc      .bad
        call    .re
        mov     si, s_erased            ; "Erased \OLD"
        call    msg_begin
        mov     si, tpath + 2
        jmp     sb_show
.bad:   mov     [ex_code], ax
        call    .re
        mov     si, tpath + 2           ; "Can't erase X.TXT: why"
        mov     bx, s_canterase
        jmp     cant_msg
.re:    call    get_subject             ; the subjects again
        mov     al, FOC_SUB
        jmp     set_focus
.x:     ret

; every title and subject under tpath ("X:\OLD") erased (read-only ones
; too), each subject once empty, then tpath itself.  A level is searched
; again from its start after a subject in it goes.  CF: AX = DOS error,
; tpath = what it was about
tree_del:
        mov     word [t_lvl], 0
.open:  call    tw_end                  ; X:\OLD\*.*
        mov     si, s_star
        call    sb_strz
        mov     dx, tpath
        call    ff_16                   ; (hidden, system, subjects too)
        jc      .err
        cmp     byte [exec_dta + 30], '.'       ; a subject starts with ".":
        mov     ax, 3                   ;  else a damaged disk (the root, or
        jne     .err                    ;  another subject): leave it
.nx:    mov     ah, 4Fh
        int     21h
        jc      .end
        cmp     byte [exec_dta + 30], '.'       ; ("..")
        je      .nx
        call    tw_name                 ; X:\OLD\NAME
        test    byte [exec_dta + 21], 10h
        jnz     .dir
        mov     dx, tpath
        xor     cx, cx
        mov     ax, 4301h               ; (read-only too)
        int     21h
        mov     ah, 41h
        int     21h
        jnc     .nx
        ret
.dir:   call    tw_end                  ; (a path longer than DOS takes:
        cmp     di, tpath + 2 + 66      ;  only from a damaged disk)
        mov     ax, 3
        ja      .bad
        inc     word [t_lvl]
        jmp     .open
.end:   cmp     ax, 18
        jne     .err
        call    tw_cut                  ; this subject, now empty
        mov     dx, tpath
        mov     ah, 3Ah
        int     21h
        jc      .x
        dec     word [t_lvl]
        js      .x                      ; (CF clear: done)
        call    tw_cut                  ; the one above, from its start
        jmp     .open
.err:   push    ax                      ; (tpath: the subject)
        call    tw_cut
        pop     ax
.bad:   stc
.x:     ret

; tpath: the last name replaced by the name found; the last name cut off
tw_name:
        call    tw_cut
        mov     byte [di], '\'
        inc     di
        mov     si, exec_dta + 30
        jmp     sb_strz
tw_cut: call    tw_end
.b:     dec     di
        cmp     byte [di], '\'
        jne     .b
        mov     byte [di], 0
        ret
tw_end: mov     di, tpath
str_end:                                ; DI -> the 0 at the end of its text
        xor     al, al
        mov     cx, 0FFFFh
        repne   scasb
        dec     di
        ret

; CODE-C with Subject outlined: the chosen subject (the current one) and
; all in it, titles and subjects, to the subject filled in: the same one
; to start with, so for another disk only Device changes.  Replace and
; Only newer as for titles.  The subjects are listed before anything is
; made, so the copy can't take itself in; the Subject list then shows
; them again
sub_copy:
        mov     di, runpath             ; its name: "Copy WORK" ("Copy Root")
        mov     si, subject
        call    sb_base
        cmp     di, runpath
        jne     .n
        mov     si, s_root
        call    sb_str
.n:     mov     byte [di], 0
        mov     si, s_copy
        call    form_title
        call    form_fill               ; Device, Subject: this one
        mov     si, sub_form
        call    ui_form
        jc      .x
        call    .name                   ; (a redraw meanwhile used runpath)
        mov     bx, s_cantcopy
        call    chk_sub
        jc      .why
        call    xfer_dest               ; tmppath: where it goes ("B:\WORK")
        mov     si, curdir              ; not into itself (nor Root into a
        mov     di, tmppath             ;  subject of its own drive)
.c:     lodsb
        or      al, al
        jz      .in
        scasb
        je      .c
        jmp     short .go
.in:    mov     al, [di]
        or      al, al
        jz      .self
        cmp     al, '\'
        je      .self
        cmp     byte [si-2], '\'
        jne     .go
.self:  mov     si, s_inself            ; "Can't copy WORK into itself: ..."
.why:   jmp     cant_why
.x:     ret
.go:    xor     ax, ax
        mov     [n_done], ax
        mov     [n_skip], ax
        inc     ax
        mov     [wild], al              ; (each title keeps its name)
        mov     si, s_all
        mov     di, c_pat
        call    sb_str
        stosb
        call    sc_list
        jnc     .mk
        mov     bx, s_cantcopy          ; (nothing made: the list as it is)
        jmp     cant_ax
.mk:    call    xfer_mkdir              ; where it goes: there, or made
        jnc     .cp
        mov     si, tmppath
        mov     [ex_code], ax
        or      ax, ax
        mov     al, 2
        jnz     .end
        mov     bx, sc_seg              ; (ESC: nothing made)
        jmp     seg_free
.cp:    call    sc_copy                 ; -> AL as xfer_all, SI
.end:   push    si
        push    ax
        or      al, al
        jnz     .f
        call    sc_dest                 ; (tmppath: where it went)
        stosb
        call    xfer_dest
.f:     call    nm_free
        mov     bx, sc_seg
        call    seg_free
        call    sub_erase.re            ; the subjects again
        pop     ax
        pop     si
        mov     bx, s_cantcopy
        cmp     al, 1
        jb      .sum
        je      .same
        cmp     al, 3
        je      .kept
        jmp     cant_msg                ; "Can't copy NAME.TXT: why"
.kept:  jmp     xfer.kmsg
.sum:   mov     si, s_copied            ; "Copied 5 titles to B:\WORK"
        jmp     sum_to
.same:  call    .name                   ; (it went where it is)
        jmp     .self
.name:  mov     si, ftitle + 5          ; runpath: its name again, from the
        mov     di, runpath             ;  form's title ("Copy WORK")
        jmp     sb_strz

SC_REL  equ 68                          ; sc_seg: where it goes (tmppath's
                                        ;  subject), then from here the list

; the subjects to copy, into a block of their own (sc_seg): "" for the
; subject itself, then each subject in it as a path from it ("\SUB",
; "\SUB\DEEP"), a level at a time, so each comes after the one it is in.
; CF: AX = DOS error (3: a path too long for DOS at either end), no block
sc_list:
        mov     si, subject             ; the longest path below it: what DOS
        call    .len                    ;  takes less the longer of the
        mov     bx, cx                  ;  subject and where it goes (where
        mov     si, tmppath + 2         ;  it goes too long already: 3)
        call    .len
        cmp     cx, bx
        jae     .l
        mov     cx, bx
.l:     mov     bx, SUBMAX
        sub     bx, cx
        mov     [sc_lim], bx
        mov     ax, 3
        stc
        js      .r
        mov     bx, 0FFFh
        mov     cx, 16
        call    alloc_big
        jc      .r
        mov     [sc_seg], ax
        shl     bx, 4
        mov     [sc_max], bx
        push    es
        mov     es, ax
        xor     di, di                  ; where it goes (SI: tmppath + 2
        call    sb_str                  ;  still), then ""
        stosb
        mov     di, SC_REL
        stosb
        pop     es
        mov     [sc_wr], di
        mov     word [sc_rd], SC_REL
.s:     mov     si, [sc_rd]             ; each one listed: the subjects in it
        cmp     si, [sc_wr]
        jae     .end
        mov     di, argpath
        call    sc_src
        push    si
        mov     si, s_star
        call    sb_join
        mov     byte [di], 0
        mov     dx, argpath
        call    ff_16                   ; (hidden and system ones too)
.f:     jc      .nf
        test    byte [exec_dta + 21], 10h
        jz      .n
        cmp     byte [exec_dta + 30], '.'
        je      .n
        call    sc_add
        jc      .err
.n:     mov     ah, 4Fh
        int     21h
        jmp     .f
.nf:    cmp     ax, 18                  ; (no more, or none)
        je      .nx
        cmp     ax, 2
        jne     .err
.nx:    pop     word [sc_rd]
        jmp     .s
.end:   mov     bx, [sc_wr]             ; the block cut to the list
        add     bx, 15
        shr     bx, 4
        push    es
        mov     es, [sc_seg]
        mov     ah, 4Ah
        int     21h
        pop     es
        clc
.r:     ret
.err:   pop     si
        mov     bx, sc_seg
        call    seg_free                ; (AX kept)
        stc
        ret
.len:   call    strlen                  ; SI -> CX: its length, 0 for "\"
        cmp     cx, 1                   ;  (the root adds nothing when a
        jne     .lx                     ;  path is put after it)
        dec     cx
.lx:    ret

; the subject found (exec_dta) in the one at [sc_rd], added to the list.
; CF: AX = 3 (its path too long), 8 (no room)
sc_add:
        mov     ax, [sc_max]
        sub     ax, [sc_wr]
        cmp     ax, 80                  ; (the longest: 66 + \ + NAME.EXT + 0)
        mov     ax, 8
        jb      .no
        mov     si, [sc_rd]
        mov     di, [sc_wr]
        push    es
        push    ds
        mov     es, [sc_seg]
        mov     ds, [sc_seg]
        call    sb_str
        pop     ds
        mov     al, '\'
        stosb
        mov     si, exec_dta + 30
        call    sb_str
        stosb
        pop     es
        mov     ax, di
        sub     ax, [sc_wr]
        dec     ax
        cmp     ax, [sc_lim]            ; (below 0 when one end is
        mov     ax, 3                   ;  already as long as DOS takes)
        jg      .no
        mov     [sc_wr], di
        clc
        ret
.no:    stc
        ret

; each subject listed: made where it goes (the first, the subject itself,
; by xfer_mkdir already), then its titles copied -> AL as xfer_all (0: all
; done; 2 also for a subject that can't be made or read, ex_code), SI =
; the path it was about
sc_copy:
        mov     word [sc_rd], SC_REL
.l:     mov     si, [sc_rd]
        cmp     si, [sc_wr]
        mov     al, 0
        jae     .r
        mov     di, curdir              ; where its titles are
        call    sc_src
        push    si
        call    sc_dest                 ; where they go
        mov     si, [sc_rd]
        call    sc_cat
        pop     word [sc_rd]
        call    xfer_dest
        cmp     byte [tmppath + 3], 0   ; (a root is there)
        je      .t
        call    xfer_mkdir.last         ; made (hidden or system as it is),
        jc      .m                      ;  unless it is there already as a
        mov     si, curdir              ;  subject (the first one: made by
        call    hs_copy                 ;  xfer_mkdir, or a file, or no disk)
        jmp     short .t
.m:     push    ax                      ; (DX = tmppath)
        call    ff_16
        pop     ax
        mov     si, tmppath
        jc      .e
        test    byte [exec_dta + 21], 10h
        jz      .e
.t:     mov     bp, 6                   ; its titles, hidden and system too
        call    pat_here
        jnc     .c
        cmp     ax, 2                   ; (none)
        je      .l
        mov     si, curdir
.e:     mov     [ex_code], ax
        mov     al, 2
        ret
.c:     call    xfer_all
        call    nm_free                 ; (AX kept)
        mov     si, argpath
        or      al, al
        jz      .l
.r:     ret

; DI = a buffer: "X:\SUBJECT" and the path at SI in sc_seg ("X:\SUBJECT\SUB",
; one '\' where they meet), a 0 at its end (DI); SI past the path
sc_src:
        push    si
        call    cur_dir.at
        pop     si
sc_cat: push    ds                      ; (the path at SI in sc_seg added at DI)
        mov     ds, [sc_seg]
        call    sb_join
        pop     ds
        mov     byte [di], 0
        ret

; the ASCIIZ text at SI added at DI (no 0), without its '\' when DI follows one
sb_join:
        cmp     byte [es:di-1], '\'
        jne     .s
        cmp     byte [si], '\'
        jne     .s
        inc     si
.s:     jmp     sb_str

; ---------------------------------------------------------------------
;  Titles: one title or a pattern (* and ?) in the listed subject
; ---------------------------------------------------------------------
; the form's Titles: the chosen title (in runpath); Replace Ask, not newer
pat_init:
        mov     word [c_repl], 0        ; (c_repl, c_newer)
pat_name:
        mov     di, c_pat
        jmp     name_to

; Titles checked (no \ or :; empty: the chosen one), wild set, and the
; titles that match found (pat_find).  CF: said why in the band ("Can't
; erase " etc. at BX)
pat_check:
        mov     si, c_pat
        call    upcase_trim
        cmp     byte [si], 0
        jne     .c
        call    pat_name
        mov     si, c_pat
.c:     mov     di, s_pathch
        call    has_any
        jnc     .w
        mov     si, s_badpat
        call    cant_why
        stc
        ret
.w:     mov     byte [wild], 0
        mov     di, s_wildch
        call    has_any
        adc     byte [wild], 0
        push    bx
        call    pat_find
        pop     bx
        jnc     .x
        mov     [ex_code], ax
        mov     si, c_pat
        call    cant_msg
        stc
.x:     ret

; the titles in the listed subject that match c_pat, with their time and
; date, into a block of their own (nm_seg) -> nm_n; nm_i, n_done, n_skip
; 0.  CF: AX = DOS error (2: none match), no block
pat_find:
        call    cur_dir
        xor     ax, ax
        mov     [n_done], ax
        mov     [n_skip], ax
        xor     bp, bp                  ; (files and read-only ones)
pat_here:                               ; (sub_copy: in curdir, the counts go on;
                                        ;  BP = the search's attributes)
        xor     ax, ax
        mov     [nm_n], ax
        mov     [nm_i], ax
        mov     bx, 0FFFh               ; 64 KB: more titles than a disk holds
        mov     cx, 2
        call    alloc_big
        jc      .x
        mov     [nm_seg], ax
        mov     ax, bx
        shl     ax, 4
        xor     dx, dx
        mov     cx, 17
        div     cx
        mov     [nm_max], ax
        mov     di, argpath             ; X:\SUBJECT\PATTERN
        mov     si, c_pat
        call    sb_dirname
        mov     dx, argpath
        mov     cx, bp
        mov     ah, 4Eh
.f:     int     21h
        jc      .end
        mov     ax, [nm_n]
        cmp     ax, [nm_max]
        jae     .end
        inc     word [nm_n]
        imul    di, ax, 17
        push    es
        mov     es, [nm_seg]
        mov     si, exec_dta + 30
        mov     cx, 13
        rep     movsb
        mov     ax, [exec_dta + 22]
        stosw
        mov     ax, [exec_dta + 24]
        stosw
        pop     es
        mov     ah, 4Fh
        jmp     .f
.end:   mov     dx, ax                  ; (the find's error)
        mov     ax, [nm_n]              ; the block cut to what it holds,
        imul    bx, ax, 17              ;  for Copy's buffer
        add     bx, 15
        shr     bx, 4
        jz      .none
        push    es
        mov     es, [nm_seg]
        mov     ah, 4Ah
        int     21h
        pop     es
        clc
        ret
.none:  xchg    ax, dx
        cmp     ax, 18
        jne     .e
        mov     al, 2
.e:     call    nm_free                 ; (none: AX = the find's error)
        stc
.x:     ret

; DI = curdir, '\' (unless the root) and the name at SI
sb_dirname:
        push    si
        mov     si, curdir
        call    sb_str
        pop     si
        cmp     byte [di-1], '\'
        je      .n
        mov     al, '\'
        stosb
.n:     jmp     sb_strz                 ; (CF clear: nm_next's answer)

; the next title found: runpath = NAME.EXT, argpath = its whole path,
; s_time and s_date.  CF: no more
nm_next:
        mov     ax, [nm_i]
        cmp     ax, [nm_n]
        cmc
        jc      .x
        inc     word [nm_i]
        imul    si, ax, 17
        push    ds
        mov     di, runpath
        mov     ds, [nm_seg]
        mov     cx, 13
        rep     movsb
        lodsw
        mov     [es:s_time], ax
        lodsw
        mov     [es:s_date], ax
        pop     ds
        jmp     sel_path.arg            ; (CF clear)
.x:     ret

; the block freed, and after a change the list read again
nm_relist:
        call    nm_free
; the list again if anything was done (the place kept)
xfer_rel:
        cmp     word [n_done], 0
        je      relist_sel.x
relist_sel:
        mov     ax, [sel]
        jmp     relist_at
.x:     ret
nm_free:
        mov     bx, nm_seg
; the block whose segment is in the word at BX freed, if there is one
; (AX kept)
seg_free:
        push    ax
        mov     ax, [bx]
        or      ax, ax
        jz      .x
        push    es
        mov     es, ax
        mov     ah, 49h
        int     21h
        pop     es
        mov     word [bx], 0
.x:     pop     ax
        ret

; BX paragraphs, or as many as there are if at least CX -> AX = the
; segment, BX = its size.  CF: AX = DOS error
alloc_big:
        mov     ah, 48h
        int     21h
        jnc     .x
        cmp     bx, cx
        jb      .x                      ; (CF, AX = 8)
        mov     ah, 48h
        int     21h
.x:     ret

; AX as "5 titles" ("1 title") at DI
sb_n_tit:
        push    ax
        call    sb_u16
        mov     si, s_title
        call    sb_str
        pop     ax
        cmp     ax, 1
        je      .x
        mov     al, 's'
        stosb
.x:     ret

; CODE-R: Rename, in its subject (a form: the new title)
ex_rename:
        call    file_ok
        jc      .x
        call    sel_name
        mov     si, s_rename
        call    form_title
        call    tit_name
        mov     si, ren_form
        call    ui_form
        jc      .x
        mov     si, c_tit
        call    upcase_trim
        cmp     byte [c_tit], 0
        je      .x
        mov     si, runpath             ; the same title: nothing to do
        mov     di, c_tit
        call    str_eq
        je      .x
        call    chk_tit                 ; a title only (RENAME would take a
        jnc     .ok                     ;  path and move the file)
        mov     bx, s_cantren
        jmp     cant_why
.ok:    call    api_criterr
        mov     dx, c_tit               ; that title taken: say so (RENAME
        mov     ax, 4300h               ;  itself would say Access denied)
        int     21h
        mov     ax, 80
        jnc     .err
        mov     dx, runpath
        mov     di, c_tit
        mov     ah, 56h
        int     21h
        jc      .err
        mov     si, c_tit
        jmp     relist_name
.x:     ret
.err:   mov     bx, s_cantren
        jmp     cant_ax

; CODE-C: Copy, CODE-M: Move.  A form: Titles (the chosen one, or a
; pattern), Device, Subject (and for Copy a Title, as the copy is called),
; Replace, and for Copy Only newer.  (In pieces: the 286 has only short
; conditional jumps.)
ex_copy:
        mov     byte [xmode], 0
        cmp     byte [focus], FOC_SUB   ; a subject: sub_copy
        jne     xfer
        jmp     sub_copy
ex_move:
        mov     byte [xmode], 1
xfer:   call    file_ok
        jc      .x
        call    xfer_form
        jc      .x
        call    xfer_check              ; no path in Titles or a title, no
        jc      .bad                    ;  wildcard in a subject
        call    xfer_cant
        call    pat_check
        jc      .x
        call    xfer_mkdir              ; a subject not there: made, if asked
        jc      .nomk
        call    xfer_all
        call    nm_free                 ; (AX kept)
        cmp     al, 1
        je      .same
        cmp     al, 2
        je      .fail
        cmp     al, 3
        je      .kept
        cmp     al, 4                   ; (a Move copied, not erased: said so,
        je      xfer_done               ;  and the rest not tried)
        cmp     byte [wild], 0
        jne     xfer_sum
        cmp     word [n_skip], 0        ; one title, left as it was
        je      xfer_done
        cmp     byte [x_skip], 2        ; (ESC at the question: nothing said)
        je      .x
        mov     si, c_tit               ; "NOTES.TXT is there already: left
        call    msg_begin               ;  as it was"
        mov     si, s_left
        jmp     sb_show
.fail:  call    xfer_rel
        call    xfer_cant
        jmp     cant_rp
.bad:   call    xfer_cant
        jmp     cant_why
.nomk:  call    nm_free                 ; (ESC: AX = 0, nothing said)
        or      ax, ax
        jz      .x
        mov     [ex_code], ax
        jmp     short .fail
.x:     ret
.same:  mov     si, runpath
        call    msg_begin
        mov     si, s_same
        jmp     sb_show
.kept:  call    relist_sel              ; the old destination went, the copy
                                        ;  couldn't take its name: where it is
.kmsg:  mov     si, s_kept              ; "Copy kept as B:\WORK\ABCDTMP: why"
        call    msg_begin
        mov     si, tmppath
        call    sb_str
        mov     si, s_colon
        call    sb_str
        mov     ax, [ex_code]
        call    api_sberr
        jmp     show_msgz

; the subject it goes to: there, or made after a question ("B:\NEW isn't
; there: Confirm to make it"; each level made in turn).  CF: AX = DOS error,
; or 0 if the answer was no
xfer_mkdir:
        mov     al, [c_tit]             ; (xfer_dest fills an empty Title)
        push    ax
        call    xfer_dest
        pop     ax
        or      al, al
        jnz     .t
        mov     [c_tit], al
.t:     cmp     byte [tmppath + 3], 0   ; (the root is always there)
        je      .ok
        mov     dx, tmppath
        mov     cx, 10h
        call    ff
        jnc     .ok                     ; (there, or a file: said later)
        cmp     ax, 3
        je      .ask
        cmp     ax, 2
        jne     .ok                     ; (a disk error: said later)
.ask:   mov     si, tmppath
        call    msg_begin
        mov     si, s_mkq
        call    sb_ask
        mov     ax, 0                   ; (CF kept)
        jc      .x
        mov     si, tmppath + 3         ; each level: "X:\A", "X:\A\B" ...
.l:     lodsb
        or      al, al
        jz      .last
        cmp     al, '\'
        jne     .l
        mov     byte [si-1], 0
        call    .last                   ; (there already: Access denied)
        mov     byte [si-1], '\'
        jmp     .l
.last:  mov     dx, tmppath             ; (sc_copy too: CF, AX = DOS error)
        mov     ah, 39h
        int     21h
        jc      .x
.ok:    clc
.x:     ret

; each title found, copied or moved -> AL = 0 all done (or left), 4 a Move
; copied but not erased (x_part); 1 the file itself (runpath), 2 a DOS
; error (ex_code, runpath), 3 the copy kept under its made-up name
xfer_all:
        call    nm_next
        mov     al, 0
        jc      .r
        cmp     byte [wild], 0          ; several: each keeps its title
        je      .t
        mov     byte [c_tit], 0
.t:     call    xfer_dest
        mov     si, argpath             ; the file itself (however spelled):
        mov     di, dstpath             ;  nothing to do
        call    str_eq
        je      .same
        call    same_file
        je      .same
        call    xfer_do
        jc      .err
        cmp     byte [x_skip], 0
        je      .d
        inc     word [n_skip]
        jmp     xfer_all
.d:     inc     word [n_done]
        cmp     byte [x_part], 0
        je      xfer_all
        mov     al, 4
.r:     ret
.same:  mov     al, 1
        ret
.err:   mov     [ex_code], ax
        mov     al, 2
        cmp     byte [tmp_kept], 0
        je      .r
        inc     ax
        ret

; after several: the list again, and "Copied 5 titles to B:\WORK, 2 left
; as they were"
xfer_sum:
        call    xfer_rel
        mov     byte [c_tit], 0         ; (tmppath: the subject it went to)
        call    xfer_dest
        mov     si, s_copied
        call    xpick
; SI = "Copied to " or "Moved to ", tmppath = where (sub_copy too)
sum_to: call    msg_begin
        sub     di, 3                   ; ("Copied to " less "to ")
        mov     ax, [n_done]
        call    sb_n_tit
        mov     si, s_to
        call    sb_str
        mov     si, tmppath
        call    sb_str
        mov     si, s_leftn
; ", 2 left as they were" (SI = the end) if any were left; then the band
sum_skip:
        cmp     word [n_skip], 0
        je      .x
        push    si
        mov     si, s_comma
        call    sb_str
        mov     ax, [n_skip]
        call    sb_u16
        pop     si
        jmp     sb_show
.x:     jmp     show_msgz

; SI = a Copy string -> the Move one after it in the data when it's a Move
; (each Move string follows its Copy string: s_copy, s_copying, s_copied,
; s_cantcopy)
xpick:  cmp     byte [xmode], 0
        je      .x
.s:     lodsb
        or      al, al
        jnz     .s
.x:     ret

; BX = "copy " or "move " (cant_msg's verb)
xfer_cant:
        push    si
        mov     si, s_cantcopy
        call    xpick
        mov     bx, si
        pop     si
        ret

; CF (SI = why) if Title is not a plain title (as filled in, or empty: the
; same title; with * or ? in Titles it must be), or Subject has a wildcard
xfer_check:
        mov     si, c_tit
        call    upcase_trim
        mov     di, runpath             ; (as filled in: as empty)
        call    str_eq
        jne     .t
        mov     byte [si], 0
.t:     mov     si, c_pat
        mov     di, s_wildch
        call    has_any
        jnc     .one
        cmp     byte [c_tit], 0
        mov     si, s_badwtit
        stc
        jne     chk_sub.x
.one:   call    chk_tit
        jc      chk_sub.x
; CF (SI = why) if Subject has : * or ?
chk_sub:
        mov     si, c_sub
        mov     di, s_subch
        call    has_any
        mov     si, s_badsub
.x:     ret
; CF (SI = why) if Title has \ : * or ?
chk_tit:
        mov     si, c_tit
        mov     di, s_titch
        call    has_any
        mov     si, s_badtit
        ret

; after Copy or Move: the list again (a copy here chosen in it), and in the
; band what happened
xfer_done:
        cmp     byte [xmode], 0
        jne     .keep
        cmp     byte [x_here], 0
        je      .keep
        mov     si, c_tit
        call    relist_name
        jmp     short .msg
.keep:  call    relist_sel
.msg:   cmp     byte [x_part], 0
        jne     .part
        mov     si, s_copied            ; "Copied to B:\WORK\NOTES.TXT"
        call    xpick
        call    msg_begin
        mov     si, dstpath
        jmp     sb_show
.part:  mov     si, s_partial           ; "Copied, but can't erase NOTES.TXT
        call    msg_begin               ;  here: Disk is write-protected"
        call    sb_run
        mov     si, s_here
        call    sb_str
        mov     ax, [ex_code]
        call    api_sberr
        jmp     show_msgz

; the Copy or Move form, filled in with where the file is -> CF: cancelled
xfer_form:
        call    sel_path                ; argpath = the file, runpath = NAME.EXT
        mov     si, s_copy
        call    xpick
        call    form_title
        call    form_fill
        mov     si, copy_form
        cmp     byte [xmode], 0
        je      .f
        mov     si, move_form
.f:     jmp     ui_form

; the forms' Device, Subject and Title: where the list is, the title in
; runpath; Replace Ask, not Only newer; the drives there are (sub_copy too)
form_fill:
        call    cur_dir
        mov     di, c_sub               ; "\" or "\DOS.330"
        mov     si, curdir + 2
        call    sb_strz
        call    tit_name
        call    pat_init
        call    ndrives                 ; the drives there are, as choices,
        mov     [c_dev], dl             ;  this one chosen
        ret

; the Device chosen in a form -> AL = its letter (BX kept)
c_letter:
        mov     al, [c_dev]
; AL = a place in the drive list (ndrives) -> AL = its letter (BX kept)
drv_let:
        push    bx
        mov     ah, 3
        mul     ah
        xchg    ax, bx
        mov     al, [o_drives + bx]
        pop     bx
        ret

; from the form: tmppath = "X:\SUBJECT" ("X:\" for Root), dstpath =
; "X:\SUBJECT\TITLE", x_here = 1 if that is the subject listed
xfer_dest:
        mov     si, c_tit               ; (no title: the same one)
        call    upcase_trim
        cmp     byte [c_tit], 0
        jne     .sub
        call    tit_name
.sub:   mov     si, c_sub
        call    upcase_trim
        mov     di, tmppath
        call    c_letter
        mov     ah, ':'
        stosw
        cmp     byte [c_sub], '\'
        je      .s1
        mov     al, '\'
        stosb
.s1:    mov     si, c_sub
        call    sb_str
        cmp     di, tmppath + 3         ; no '\' at the end (but "X:\")
        je      .s2
        cmp     byte [di-1], '\'
        jne     .s2
        dec     di
.s2:    mov     byte [di], 0
        mov     si, tmppath
        mov     di, dstpath
        call    sb_str
        cmp     byte [di-1], '\'
        je      .s3
        mov     al, '\'
        stosb
.s3:    mov     si, c_tit
        call    sb_strz
        mov     byte [x_here], 0        ; (asked now: copy_file adds to
        mov     si, tmppath             ;  tmppath)
        mov     di, curdir
        call    str_eq
        jne     .x
        inc     byte [x_here]
.x:     ret

; do it: replace what is there (if the answer is yes), then Copy, or Move
; (RENAME on the same drive, else copy and erase) -> CF: AX = DOS error.
; x_skip if left as it was (Replace None, not older, or the answer no).  (x_part: moved to the other drive but
; the original stays, error in ex_code; tmp_kept: copy_file's new file
; kept under its made-up name)
xfer_do:
        call    api_criterr             ; (an old disk error forgotten)
        xor     ax, ax
        mov     [d_exists], al
        mov     [x_part], al
        mov     [tmp_kept], al
        mov     [x_skip], al
        call    ff_dst                  ; there already?  (search state, time
        jc      .new                    ;  and date in exec_dta: same_file
                                        ;  made it the DTA)
        test    byte [exec_dta + 21], 10h       ; (a subject: no)
        mov     ax, 5
        stc
        jnz     .r
        cmp     byte [c_newer], 0       ; Only newer: left unless older
        je      .ask
        mov     ax, [exec_dta + 24]
        cmp     ax, [s_date]
        jne     .cmp
        mov     ax, [exec_dta + 22]
        cmp     ax, [s_time]
.cmp:   jae     .left
.ask:   mov     al, [c_repl]            ; Replace: Ask, All, None
        cmp     al, 1
        je      .yes
        ja      .left
        mov     si, c_tit               ; "NAME.EXT is there already: ..."
        call    msg_begin
        mov     si, s_replace
        call    sb_ask
        jnc     .yes
        inc     byte [x_skip]           ; (2: ESC)
.left:  inc     byte [x_skip]
        clc
        ret
.yes:   mov     byte [d_exists], 1
        jmp     short .go
.new:   cmp     ax, 2                   ; (only "not found" is good news)
        stc
        jne     .r
.go:    cmp     byte [xmode], 0
        je      .copy
        call    c_letter                ; Move on the same drive: RENAME
        cmp     al, [argpath]
        jne     .other
        jmp     move_here
.r:     ret
.other: mov     dx, argpath             ; Move to the other drive: copy, then
        mov     ax, 4300h               ;  erase.  A read-only file couldn't
        int     21h                     ;  be erased, so it isn't copied
        jc      .r2
        test    cl, 1
        mov     ax, 5
        stc
        jnz     .r2
.copy:  mov     si, s_copying           ; "Copying NAME.EXT" in the band
        call    xpick
        call    msg_begin
        mov     si, runpath
        call    sb_strz
        mov     si, msgbuf
        xor     di, di
        call    ui_band
        call    copy_file
        jc      .r2
        mov     si, argpath             ; (hidden or system: only Copy on a
        mov     dx, dstpath             ;  subject takes such titles)
        call    hs_copy
        cmp     byte [xmode], 0         ; (Copy: done, CF clear)
        je      .r2
        mov     dx, argpath             ; Move: the original goes
        mov     ah, 41h
        int     21h
        jnc     .r2
        mov     [ex_code], ax           ; (it can't: copied, not moved; the
        mov     byte [x_part], 1        ;  band says so)
        clc
.r2:    ret

; Move on the same drive: RENAME.  An old destination is erased first, with
; the source held open: were they one file after all, DOS refuses (Access
; denied) and nothing is lost
move_here:
        cmp     byte [d_exists], 0
        je      .ren
        mov     dx, argpath
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     bx, ax
        mov     dx, dstpath
        mov     ah, 41h
        int     21h
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
        jc      .x
.ren:   mov     dx, argpath
        mov     di, dstpath
        mov     ah, 56h
        int     21h
.x:     ret

; ZF set if argpath and dstpath are one file, however dstpath is spelled:
; the kernel takes "\WORK\..", "\WORK." and names cut at 8.3 too.  Find
; first leaves the drive, the directory and the entry it found in the
; DTA's search state (KFILE.INC f_4E).  ZF clear if either isn't there
same_file:
        mov     dx, argpath
        mov     di, id_src
        call    file_id
        jc      .no
        mov     dx, dstpath
        mov     di, id_dst
        call    file_id
        jc      .no
        mov     si, id_src
        mov     di, id_dst
        mov     cx, 5
        repe    cmpsb
        ret
.no:    or      sp, sp                  ; (ZF clear)
        ret

; DX = path -> 5 bytes at DI: its drive, directory and entry (the search
; state); CF if it isn't there
file_id:
        mov     cx, 06h                 ; (hidden and system files too)
        call    ff
        jc      .x
        mov     al, [exec_dta]
        stosb
        mov     ax, [exec_dta + 13]
        stosw
        mov     ax, [exec_dta + 15]
        stosw
.x:     ret

; the hidden and system bits of the title or subject at SI given to the
; one at DX, if it has any (errors ignored: CF as it comes)
hs_copy:
        push    dx
        mov     dx, si
        mov     ax, 4300h
        int     21h
        pop     dx
        jc      .x
        and     cx, 6
        jz      .x
        mov     ax, 4301h
        int     21h
.x:     ret

; copy argpath to dstpath, the date and time with it.  The copy is made as
; a new file in the destination subject (tmppath, the name made up by
; DOS); only when all of it is there does the old destination go
; (d_exists) and the copy take its name.  So a full disk or a bad sector
; leaves the destination as it was.  CF: AX = DOS error
copy_file:
        mov     word [h_src], 0FFFFh
        mov     word [h_tmp], 0FFFFh
        mov     word [buf_seg], 0
        mov     byte [tmp_made], 0
        call    cf_open
        jc      .fail
        call    cf_data
        jc      .fail
        call    cf_end
        jc      .fail
        ret
.fail:  push    ax                      ; undo: handles, buffer, the new file
        call    cf_free
        mov     bx, [h_tmp]
        cmp     bx, 0FFFFh
        je      .f1
        mov     ah, 3Eh
        int     21h
.f1:    cmp     byte [tmp_made], 0
        je      .f2
        mov     dx, tmppath
        mov     ah, 41h
        int     21h
.f2:    pop     ax
        stc
        ret

; the source open, its date and time, the new file, the buffer
cf_open:
        mov     dx, argpath
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     [h_src], ax
        mov     bx, ax
        mov     ax, 5700h
        int     21h
        jc      .x
        mov     [f_time], cx
        mov     [f_date], dx
        mov     di, tmppath             ; "X:\SUBJECT\" for CREATE TEMPORARY
        call    str_end
        cmp     byte [di-1], '\'
        je      .t
        mov     word [di], '\'          ; ('\', 0)
.t:     mov     dx, tmppath
        xor     cx, cx
        mov     ah, 5Ah
        int     21h
        jc      .x
        mov     [h_tmp], ax
        mov     byte [tmp_made], 1
        mov     bx, COPYBUF             ; the buffer: 32 KB, or what there is
        mov     cx, 32                  ;  (under 512 bytes: no)
        call    alloc_big
        jc      .x
        mov     [buf_seg], ax
        shl     bx, 4
        mov     [buf_len], bx
        clc
.x:     ret

; the source into the new file, a buffer at a time
cf_data:
        mov     bx, [h_src]
        mov     cx, [buf_len]
        push    ds
        mov     ds, [buf_seg]
        xor     dx, dx
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .x
        or      ax, ax                  ; (the end: CF clear)
        jz      .x
        mov     cx, ax
        mov     bx, [h_tmp]
        push    ds
        mov     ds, [buf_seg]
        xor     dx, dx
        mov     ah, 40h
        int     21h
        pop     ds
        jc      .x
        cmp     ax, cx                  ; less written: the disk is full
        mov     ax, 39
        jb      .x
        jmp     cf_data
.x:     ret

; the new file dated and closed, the old destination erased (the source
; still open: were they one file, DOS refuses), the name given.  Once the
; old destination is gone the new file is all there is: kept if it can't
; take the name (tmp_kept)
cf_end: mov     bx, [h_tmp]
        mov     cx, [f_time]
        mov     dx, [f_date]
        mov     ax, 5701h
        int     21h
        jc      .x
        mov     ah, 3Eh                 ; (closing writes the rest out)
        int     21h
        jc      .x
        mov     word [h_tmp], 0FFFFh
        cmp     byte [d_exists], 0
        je      .name
        mov     dx, dstpath
        mov     ah, 41h
        int     21h
        jc      .x
        mov     byte [tmp_made], 0
        mov     byte [tmp_kept], 1
.name:  call    cf_free
        mov     dx, tmppath
        mov     di, dstpath
        mov     ah, 56h
        int     21h
        jc      .x
        mov     byte [tmp_kept], 0      ; (CF stays clear)
.x:     ret

; the source closed and the buffer freed, if they are
cf_free:
        mov     bx, [h_src]
        cmp     bx, 0FFFFh
        je      .fr
        mov     ah, 3Eh
        int     21h
        mov     word [h_src], 0FFFFh
.fr:    mov     bx, buf_seg
        jmp     seg_free

; "Verb NAME.EXT" (verb SI, the name in runpath) as the form's title
form_title:
        mov     di, ftitle
        call    sb_str
        jmp     short name_to

; c_tit = runpath (the chosen title); name_to: at DI
tit_name:
        mov     di, c_tit
name_to:
        mov     si, runpath
        jmp     sb_strz
; runpath added at DI
sb_run: mov     si, runpath
        jmp     sb_str

; curdir = "X:\SUBJECT" ("X:\" for Root): where the list is; .at: at DI
cur_dir:
        mov     di, curdir
.at:    mov     ah, 19h
        int     21h
        add     al, 'A'
        mov     ah, ':'
        stosw
        mov     si, subject
        jmp     sb_strz

; sc_seg's first path, where it goes, as c_sub (DI at its end, no 0)
sc_dest:
        push    ds
        mov     ds, [sc_seg]
        xor     si, si
        mov     di, c_sub
        call    sb_str
        pop     ds
        ret

; find first: DX = the path (ff_dst: dstpath), CX = attributes (ff_16:
; hidden, system and subjects)
ff_dst: mov     dx, dstpath
ff_16:  mov     cx, 16h
ff:     mov     ah, 4Eh
        int     21h
        ret

; the ASCIIZ text at SI as typed into a form: in capitals, '/' as '\',
; no spaces before or after
upcase_trim:
        pusha
        mov     bx, si
        mov     di, si
.sp:    lodsb
        cmp     al, ' '
        je      .sp
        dec     si
.c:     lodsb
        cmp     al, 'a'
        jb      .s
        cmp     al, 'z'
        ja      .s
        sub     al, 'a' - 'A'
.s:     cmp     al, '/'
        jne     .st
        mov     al, '\'
.st:    stosb
        or      al, al
        jnz     .c
        dec     di
.t:     cmp     di, bx
        je      .z
        cmp     byte [di-1], ' '
        jne     .z
        dec     di
        jmp     .t
.z:     mov     byte [di], 0
        popa
        ret

; CF if the ASCIIZ text at SI has any of the characters in the ASCIIZ set DI
has_any:
        push    si
.l:     lodsb
        or      al, al                  ; (the end: CF clear)
        jz      .x
        push    di
.c:     cmp     byte [di], 0
        je      .n
        cmp     al, [di]
        je      .y
        inc     di
        jmp     .c
.n:     pop     di
        jmp     .l
.y:     pop     di
        stc
.x:     pop     si
        ret

; "Can't copy NAME.EXT" (BX = the verb; the name in runpath) and the
; reason SI, in the band (BX changes)
cant_why:
        push    si
        mov     si, runpath
        call    cant_msg.h
        pop     si
        jmp     sb_show

; ZF set if the ASCIIZ texts at SI and DI are the same
str_eq: push    si
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

; "NAME.EXT" at SI as an 11-byte FAT name at DI (BX = that DI; dta2ent
; counts on it)
to_fcb: push    di
        mov     cx, 11
        mov     al, ' '
        rep     stosb
        pop     di
        mov     bx, di
        mov     cx, 8
.n:     lodsb
        or      al, al
        jz      .x
        cmp     al, '.'
        je      .e
        jcxz    .n                      ; (past 8: left out)
        stosb
        dec     cx
        jmp     .n
.e:     lea     di, [bx+8]
        mov     cx, 3
.el:    lodsb
        or      al, al
        jz      .x
        stosb
        loop    .el
.x:     ret

; after a command: the directory again, with item AX chosen (the last one
; if the list is shorter now) ...
relist_at:
        push    ax
        call    save_place
        call    load_dir
        pop     ax
        jmp     short place_at

; ... or with title SI ("NAME.EXT") chosen, if it is listed
relist_name:
        mov     di, fcbbuf
        call    to_fcb
        call    save_place
        call    load_dir
        xor     bx, bx
.f:     cmp     bx, [nent]
        jae     .no
        call    ent_ptr
        mov     di, fcbbuf
        call    ent_cmp
        je      .hit
        inc     bx
        jmp     .f
.no:    mov     bx, [o_sel]
.hit:   mov     ax, bx
        ; (falls through)

; choose item AX and scroll the list as little as will show it, from
; where it was (o_top); then the screen
place_at:
        mov     cx, [nent]
        jcxz    .d
        cmp     ax, cx
        jb      .s
        mov     ax, cx
        dec     ax
.s:     mov     [sel], ax
        mov     bx, [o_top]
        cmp     ax, bx                  ; above the rows shown: at the top
        jae     .lo
        mov     bx, ax
.lo:    mov     dx, bx                  ; below them: at the bottom
        add     dx, LIST_N
        cmp     ax, dx
        jb      .hi
        mov     bx, ax
        sub     bx, LIST_N - 1
.hi:    mov     dx, cx                  ; and no empty rows under the last
        sub     dx, LIST_N
        jae     .h2
        xor     dx, dx
.h2:    cmp     bx, dx
        jbe     .t
        mov     bx, dx
.t:     mov     [top], bx
.d:     jmp     draw_all

save_place:
        mov     ax, [sel]
        mov     [o_sel], ax
        mov     ax, [top]
        mov     [o_top], ax
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
        call    build_info              ; (in tmp: after draw_form)
        mov     si, infobuf
        mov     dx, INFO_Y
        call    center
        mov     al, [lampw]             ; light the coprocessor: from the
        or      al, al                  ;  space after 80286, 7 or 9 wide
        jz      .nolamp
        cbw
        xchg    bp, ax
        call    strlen
        mov     bx, 80 + 10
        sub     bx, cx
        shr     bx, 1
        mov     cx, 16
        call    invert_band
.nolamp:
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
        cmp     ax, 0FFFFh
        je      .more
        mov     si, s_cantdir           ; "Can't read the disk: why"
        call    msg_begin
        mov     ax, [dir_note]          ; (AL: sb_str's 0)
        call    api_sberr
        jmp     show_msgz
.more:  mov     si, s_first             ; "Only the first 240 are listed"
        call    msg_begin
        mov     ax, [nent]
        call    sb_u16
        mov     si, s_listed
        jmp     sb_show

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
.sp:    mov     bx, TCOL
        call    puts_tmp
        mov     ax, [si + 12]           ; its date (Root has none)
        or      ax, ax
        jz      .x
        mov     di, tmp
        call    sb_date
        mov     bx, 40
        jmp     puts_tmp
.dev:   xchg    ax, bx                  ; a drive
        call    drv_let
        call    dev_str
        mov     bx, TCOL
        mov     ah, [rowmask]
        jmp     puts
.x:     ret
.tit:   call    ent_ptr                 ; SI -> directory entry
        mov     di, tmp
        call    sb_title
        mov     bx, TCOL
        call    puts_tmp
        mov     di, tmp                 ; date
        mov     ax, [si+24]
        call    sb_date
        mov     bx, 40
        call    puts_tmp
        mov     di, tmp                 ; size, ending at column 60
        mov     ax, [si+28]
        mov     cx, [si+30]
        call    sb_u32
        mov     bx, 60 + tmp
        sub     bx, di
        call    puts_tmp
        call    kind_of
        call    strlen
        mov     bx, KEND
        sub     bx, cx
        mov     ah, [rowmask]
        jmp     puts

; tmp, ended at DI, at column BX, row DX, with rowmask (SI kept)
puts_tmp:
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     ah, [rowmask]
        call    puts
        pop     si
        ret

; the File form under the list: Device, Subject, Title, Kind (with the
; size and date), the outlined item in a box
draw_form:
        mov     byte [rowmask], 0       ; (puts_tmp: normal)
        mov     dx, FORM_Y - 2          ; clear the values (cols 12..79)
        mov     cx, 4 * ITEM_H - 4
        mov     bx, 12
        mov     bp, 68
        xor     al, al
        call    fill_band
        mov     ah, 19h                 ; Device
        int     21h
        add     al, 'A'
        call    dev_str
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
        mov     bp, ITEM_H - 1
        call    box
        cmp     byte [focus], FOC_TIT   ; Title and Kind: the chosen title's
        jne     .x                      ;  (none while another item is
        cmp     word [nent], 0          ;  outlined)
        je      .x
        mov     bx, [sel]
        call    ent_ptr
        mov     di, tmp
        call    sb_title
        mov     bx, 14
        mov     dx, FORM_Y + 2 * ITEM_H
        call    puts_tmp
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
        mov     bx, 30
        jmp     puts_tmp
.x:     ret

; ---------------------------------------------------------------------
;  the system information line
; ---------------------------------------------------------------------
section uiboot                          ; (once, at start-up: UICORE.INC ui_boot)
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
        call    fpu_detect              ; 0 none, 1 80287, 2 287XL:
        or      al, al                  ;  the lamp " 80287 " or " 80287XL "
        jz      .f
        shl     al, 1
        add     al, 5
.f:     mov     [lampw], al
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

%include "FPU.INC"
section ui

; "80286 80287XL   640K + ...": the coprocessor, when there is one, is lit
; (draw_all inverts " 80287 " or " 80287XL " after drawing the line)
build_info:
        mov     di, infobuf
        mov     si, s_cpu
        call    sb_str
        mov     al, [lampw]
        cbw
        dec     ax                      ; " 80287" or " 80287XL"
        js      .nf
        xchg    cx, ax
        mov     si, s_fpu
        rep     movsb
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
        KEY(K_NONE,      0,          h_tab)
        KEY(K_NONE,      0,          h_letter)
        KEY(K_ENTER,     confirm,    h_confirm)
        KEY(K_F1,        ex_help,    0)
        KEY(K_CODE_HELP, ex_help,    0)
        KEY(K_CODE_U,    run_usage,  h_usage)
        KEY(K_CODE_W,    run_write,  h_write)
        KEY(K_CODE_A,    run_claude, h_claude)
        KEY(K_CODE_K,    run_calc,   h_calc)
        KEY(K_CODE_P,    run_shell,  h_shell)
        KEY(K_CODE_C,    ex_copy,    h_copy)
        KEY(K_CODE_D,    ex_erase,   h_erase)
        KEY(K_CODE_M,    ex_move,    h_move)
        KEY(K_CODE_R,    ex_rename,  h_rename)
        KEY(K_F5,        refresh,    h_f5)
        KEY(K_NONE,      0,          h_code)
        dw 0                            ; (14 help lines; there is room for 18)

h_choose    db 'Up / Down, PgUp / PgDn   choose',0
h_tab       db 'Tab / Shift-Tab          Device, Subject, Title',0
h_letter    db 'Type its first letter    find a name',0
h_confirm   db 'Return or click again    open it / next item',0
h_usage     db 'CODE-U                   System',0
h_write     db 'CODE-W                   Write: a new text file',0
h_claude    db 'CODE-A                   Claude',0
h_calc      db 'CODE-K                   Calculator',0
h_shell     db 'CODE-P                   command prompt',0
h_copy      db 'CODE-C                   Copy the file / subject',0
h_erase     db 'CODE-D                   Delete the file / subject',0
h_move      db 'CODE-M                   Move the file',0
h_rename    db 'CODE-R                   Rename the file',0
h_f5        db 'F5                       after a disk swap',0
h_code      db 'CODE is the Alt key.  Any key closes.',0

; ---------------------------------------------------------------------
;  data
; ---------------------------------------------------------------------
s_brand     db 'Lodestone 0.6',0
s_hlptitle  db 'Lodestone 0.6 Help',0
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
s_dev_c     db 'Hard disk C:',0
s_dev_m     db 'Temporary disk M:',0
s_dev_r     db 'ROM R:',0
s_root      db 'Root',0
s_bytes     db ' bytes',0
s_dated     db '   dated ',0
s_nohires   db 'Lodestone needs the GRiD 640x400 panel (BIOS mode 40h).',13,10
            db 'Press a key to restart.',13,10,0
s_cpu       db '80286',0
s_fpu       db ' 80287XL'
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
s_calc      db 'CALC.RUN', 0
s_notondisk db ' is not on this disk', 0
s_comspec   db 'COMSPEC='
s_defshell  db 'A:\LCMD.COM', 0
s_noopen    db ' - nothing opens this kind yet', 0
s_ended     db ' ended', 0
s_code      db ', exit code ', 0
s_cant_     db "Can't ", 0                ; (cant_msg: then one of these verbs)
s_cant      db 'run ', 0
s_cantopen  db 'open ', 0
s_cantdir   db "Can't read the disk: ", 0
s_first     db 'Only the first ', 0
s_listed    db ' are listed', 0
s_colon     db ': ', 0
; the file commands
copy_form:  dw ftitle, s_copyp, 60, 11, 6
            dw s_lbl_tits, FT_TEXT + (12 << 8), c_pat, 12
            dw s_lbl_dev, FT_CHOICE, c_dev, o_drives
            dw s_lbl_sub, FT_TEXT + (40 << 8), c_sub, SUBMAX
            dw s_lbl_tit, FT_TEXT + (12 << 8), c_tit, 12
            dw s_lbl_repl, FT_CHOICE, c_repl, o_repl
            dw s_lbl_newer, FT_CHOICE, c_newer, o_yesno
move_form:  dw ftitle, s_movep, 60, 11, 4
            dw s_lbl_tits, FT_TEXT + (12 << 8), c_pat, 12
            dw s_lbl_dev, FT_CHOICE, c_dev, o_drives
            dw s_lbl_sub, FT_TEXT + (40 << 8), c_sub, SUBMAX
            dw s_lbl_repl, FT_CHOICE, c_repl, o_repl
sub_form:   dw ftitle, s_copyp, 60, 11, 4
            dw s_lbl_dev, FT_CHOICE, c_dev, o_drives
            dw s_lbl_sub, FT_TEXT + (40 << 8), c_sub, SUBMAX
            dw s_lbl_repl, FT_CHOICE, c_repl, o_repl
            dw s_lbl_newer, FT_CHOICE, c_newer, o_yesno
del_form:   dw ftitle, s_delp, 44, 10, 1
            dw s_lbl_tits, FT_TEXT + (12 << 8), c_pat, 12
ren_form:   dw ftitle, s_renp, 44, 10, 1
            dw s_lbl_new, FT_TEXT + (12 << 8), c_tit, 12
o_drives    db 'A:', 0, 'B:', 0, 'C:', 0, 'M:', 0, 'R:', 0, 0    ; (ndrives: the drives there are)
o_repl      db 'Ask', 0, 'All', 0, 'None', 0, 0
o_yesno     db 'No', 0, 'Yes', 0, 0
s_lbl_tits  db 'Titles', 0
s_lbl_repl  db 'Replace', 0
s_lbl_newer db 'Only newer', 0
s_delete    db 'Delete ', 0
s_delp      db 'Delete: Confirm to erase (* or ? for several)', 0
s_erased    db 'Erased ', 0
s_rokept    db ' read-only kept', 0
s_title     db ' title', 0
s_to        db ' to ', 0
s_comma     db ', ', 0
s_left      db ' is there already: left as it was', 0
s_leftn     db ' left as they were', 0
s_allin     db ' and all in it', 0
s_dotdot    db '..', 0
s_star      db '\*.*', 0
s_mkq       db " isn't there: Confirm to make it", 0
s_copy      db 'Copy ', 0
s_move      db 'Move ', 0
s_rename    db 'Rename ', 0
s_copyp     db 'Copy: Fill in form and confirm', 0
s_movep     db 'Move: Fill in form and confirm', 0
s_renp      db 'Rename: Fill in form and confirm', 0
s_lbl_new   db 'New title', 0
s_eraseq    db 'Erase: Confirm to erase ', 0
s_replace   db ' is there already: Confirm to replace it', 0
s_same      db ' is there now: choose another place', 0
s_inself    db ' into itself: choose another place', 0
s_copying   db 'Copying ', 0
s_moving    db 'Moving ', 0
s_copied    db 'Copied to ', 0
s_moved     db 'Moved to ', 0
s_cantcopy  db 'copy ', 0                ; (xpick: the Move one next)
s_cantmove  db 'move ', 0
s_canterase db 'erase ', 0
s_cantren   db 'rename ', 0
            times -(s_move != s_copy + 6 || s_moving != s_copying + 9) db 0     ; (xpick: each
            times -(s_moved != s_copied + 11 || s_cantmove != s_cantcopy + 6) db 0 ;  Move string next)
s_readonly  db ': it is read-only', 0
s_titch     db '\:'                     ; not in a title (a path,
s_wildch    db '*?', 0                  ;  wildcards)
s_pathch    db '\:', 0                  ; not in Titles
s_badpat    db ": titles can't have \ or :", 0
s_badwtit   db ": with * or ? in Titles, leave Title as it was", 0
s_subch     db ':*?', 0                 ; not in a subject
s_badtit    db ": a title can't have \ : * or ?", 0
s_badsub    db ": a subject can't have : * or ?", 0
s_partial   db "Copied, but can't erase ", 0
s_here      db ' here: ', 0
s_kept      db 'Copy kept as ', 0
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
            times -(k_source - k_file > 127) db 0      ; (kind_of: cbw)
; extension, kind (its offset from k_file), what opens it (1 DOS, 2 .RUN,
; 3 Write)
kinds       db 'COM'
            db k_run - k_file
            db 1
            db 'EXE'
            db k_run - k_file
            db 1
            db 'RUN'
            db k_program - k_file
            db 2
            db 'SYS'
            db k_system - k_file
            db 0
            db 'TXT'
            db k_text - k_file
            db 3
            db 'DOC'
            db k_text - k_file
            db 3
            db 'BIN'
            db k_data - k_file
            db 0
            db 'DAT'
            db k_data - k_file
            db 0
            db 'BAT'
            db k_batch - k_file
            db 3
            db 'CFG'
            db k_settings - k_file
            db 3
            db 'INI'
            db k_settings - k_file
            db 3
            db 'EMS'
            db k_settings - k_file
            db 0
            db 'TYP'
            db k_font - k_file
            db 0
            db 'PRO'
            db k_profile - k_file
            db 3
            db 'ASM'
            db k_source - k_file
            db 3
            db 'INC'
            db k_source - k_file
            db 3
            db 'C  '
            db k_source - k_file
            db 3
            db 'H  '
            db k_source - k_file
            db 3
            db 0
