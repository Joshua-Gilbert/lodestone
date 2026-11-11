; =====================================================================
;  KFILE.INC - handles: the system file table (SFT) shared by everyone,
;  each process's 20-entry handle table (JFT, in its PSP), files on FAT
;  and the devices CON, NUL, AUX/COM1, COM2, PRN/LPT1 and GPIBnn.  All
;  of them read and write through the same calls.
; =====================================================================
S_REF   equ 0                   ; users (0 = free)
S_MODE  equ 1                   ; open mode as given (bit 7 = not inherited)
S_FLAGS equ 2
S_DEV   equ 3                   ; device number
S_DRV   equ 4
S_ATTR  equ 5
S_TIME  equ 6                   ; time, date, first cluster, size: as in
S_DATE  equ 8                   ;  the directory entry (its bytes 22-31),
S_CLU   equ 10                  ;  for sft_fill and sft_commit
S_SIZE  equ 12                  ; dword
S_DLBA  equ 16                  ; directory entry: sector,
S_DOFF  equ 18                  ;   offset (as d_lba, d_off)
S_NAME  equ 20                  ; 11
S_GEN   equ 31                  ; its floppy's mount (mgen: KDISK.INC rule 9)
S_POS   equ 32                  ; dword
S_CCL   equ 36                  ; cached cluster (0 = none)
S_CIX   equ 38                  ;   and its index in the chain
S_GADR  equ 40                  ; GPIB address
S_RAE   equ 42                  ; where the last read ended (low word)
SFT_SZ  equ 44
NSFT    equ 24
SF_DEV  equ 80h
SF_DIRTY equ 40h                ; written: update the directory at close
SF_RAW  equ 20h                 ; device in raw (binary) mode
SF_STAMP equ 10h                ; time/date set by the program
SF_LOST equ 08h                 ; its drive's changed FAT dropped (fat_drop,
                                ;  KDISK.INC rule 4), or another mount's
                                ;  (rule 9): no more reads or writes, its
                                ;  entry left as the disk has it
DEV_CON equ 0
DEV_NUL equ 1
DEV_AUX equ 2
DEV_PRN equ 3
DEV_COM2 equ 4
DEV_GPIB equ 5
DEV_EMM equ 6                   ; EMMXXXX0 (with EMS): reads and writes as NUL

section .bss
sft         resb SFT_SZ * NSFT
dta         resw 2              ; disk transfer address (offset, segment)
rw_left     resw 1
rw_done     resw 1
rw_seg      resw 1
rw_off      resw 1
rw_sft      resw 1
con_line    resb 130            ; CON reads, a line at a time
con_lpos    resw 1
con_llen    resw 1
section .text

section ovl
sft_init:
        mov     si, sft
        mov     byte [si+S_REF], 3      ; 0: CON (handles 0, 1, 2)
        mov     byte [si+S_MODE], 2
        mov     byte [si+S_FLAGS], SF_DEV
        mov     byte [si+S_DEV], DEV_CON
        add     si, SFT_SZ
        mov     byte [si+S_REF], 1      ; 1: AUX (handle 3)
        mov     byte [si+S_MODE], 2
        mov     byte [si+S_FLAGS], SF_DEV
        mov     byte [si+S_DEV], DEV_AUX
        add     si, SFT_SZ
        mov     byte [si+S_REF], 1      ; 2: PRN (handle 4)
        mov     byte [si+S_MODE], 1
        mov     byte [si+S_FLAGS], SF_DEV
        mov     byte [si+S_DEV], DEV_PRN
        ret
section .text
        times (($ - $$) & 1) ^ 1 db 90h ; (hot: h2sft even, h2sft_bp odd;
                                        ;  after KFAT.INC's last JMP)
; handle BX (current process) -> SI = SFT entry, AL = its number.
; CF: AX = 6.  Keeps BX.  h2sft_bp: the call's BX's
h2sft_bp:
        mov     bx, [bp+F_BX]
h2sft:  cmp     bx, 20
        jae     .bad
        push    es
        mov     es, [cur_psp]
        mov     al, [es:18h+bx]
        pop     es
        cmp     al, NSFT
        jae     .bad
        call    sft_of
        cmp     byte [si+S_REF], 0
        je      .bad
        clc
        ret
.bad:   mov     ax, 6
        stc
        ret

; SFT entry AL (below NSFT) -> SI.  Keeps AX
sft_of: push    ax
        cbw                             ; (AL < 128)
        imul    si, ax, SFT_SZ
        add     si, sft
        pop     ax
        ret

; a free SFT entry -> SI (cleared), AL = number.  CF: AX = 4
sft_alloc:
        push    cx
        push    di
        mov     si, sft
        xor     al, al
.l:     cmp     byte [si+S_REF], 0
        je      .got
        add     si, SFT_SZ
        inc     al
        cmp     al, NSFT
        jb      .l
        mov     ax, 4
        stc
        jmp     .x
.got:   push    ax
        mov     di, si
        mov     cx, SFT_SZ
        xor     al, al
        rep     stosb
        pop     ax
        clc
.x:     pop     di
        pop     cx
        ret

; a free handle of the current process -> BX.  CF: AX = 4
jft_alloc:
        push    es
        mov     es, [cur_psp]
        xor     bx, bx
.l:     cmp     byte [es:18h+bx], 0FFh
        je      .got
        inc     bx
        cmp     bx, 20
        jb      .l
        pop     es
        mov     ax, 4
        stc
        ret
.got:   pop     es
        clc
        ret

; SFT entry AL into handle BX, and return BX in AX (as INT 21h does)
give_handle:
        call    jft_set
        mov     ax, bx
        jmp     ok_ax

; handle BX of the current process <- SFT entry AL (FFh: free)
jft_set:
        push    es
        mov     es, [cur_psp]
        mov     [es:18h+bx], al
        pop     es
        ret

; is the directory entry d_lba/d_off of drive [act] open?  CF if so
sft_busy:
        push    ax
        push    bx
        push    cx
        mov     bx, sft
        mov     cx, NSFT
.l:     cmp     byte [bx+S_REF], 0
        je      .n
        test    byte [bx+S_FLAGS], SF_DEV | SF_LOST     ; (another mount's
        jnz     .n                      ;  are SF_LOST: the mount's, rule 9)
        mov     al, [act]
        cmp     [bx+S_DRV], al
        jne     .n
        mov     ax, [d_lba]
        cmp     [bx+S_DLBA], ax
        jne     .n
        mov     ax, [d_off]
        cmp     [bx+S_DOFF], ax
        jne     .n
        stc
        jmp     .x
.n:     add     bx, SFT_SZ
        loop    .l
        clc
.x:     pop     cx
        pop     bx
        pop     ax
        ret

; the entry just found (de, d_lba, d_off, act) into SFT SI, mode AL
sft_fill:
        push    ax
        push    cx
        push    di
        mov     [si+S_MODE], al
        mov     byte [si+S_REF], 1
        mov     al, [act]
        mov     [si+S_DRV], al
        push    ax
        call    gen_of
        mov     [si+S_GEN], ah
        pop     ax
        mov     al, [de+11]
        mov     [si+S_ATTR], al
        push    si
        lea     di, [si+S_TIME]         ; time, date, cluster, size
        mov     si, de + 22
        mov     cx, 5
        rep     movsw
        mov     si, d_lba               ; then d_lba, d_off
        movsw
        movsw
        mov     si, de                  ; then the name
        mov     cl, 11
        rep     movsb
        pop     si
        pop     di
        pop     cx
        pop     ax
        ret
        times   -(S_DATE != S_TIME + 2 || S_CLU != S_TIME + 4 || S_SIZE != S_TIME + 6) db 0
        times   -(S_DLBA != S_TIME + 10 || S_DOFF != S_DLBA + 2 || S_NAME != S_DLBA + 4) db 0
        times   -(d_off != d_lba + 2) db 0
        times ($ + 1 - $$) & 1 db 90h   ; (hot: dev_look_ax's loops even)

; ---------------------------------------------------------------------
;  devices by name
; ---------------------------------------------------------------------
; is the last component of path_buf (or of the path at AX) a device?
; -> AL = device, AH = GPIB address.  CF if not.  BX = the component (after
; the last \ or :; dev_where reads it)
dev_lookup:
        mov     ax, path_buf
dev_look_ax:
        push    cx
        push    si
        push    di
        xchg    si, ax
        mov     bx, si
.f:     lodsb
        or      al, al
        jz      .fe
        cmp     al, '\'
        je      .cut
        cmp     al, ':'
        jne     .f
.cut:   mov     bx, si
        jmp     .f
.fe:    mov     si, dev_names           ; BX = the base name
        xor     cx, cx
.t:     mov     cl, [si]                ; (ES = DS, DF clear: int21's)
        inc     si
        jcxz    .gpib
        mov     di, bx
        repe    cmpsb
        jne     .skip
.end:   mov     al, [di]                ; the name must end here
        or      al, al
        jz      .hit
        cmp     al, '.'
        jne     .skip
.e2:    inc     di                      ; (NUL.X.Y: no device, as MS-DOS)
        mov     al, [di]
        or      al, al
        jz      .hit
        cmp     al, '.'
        jne     .e2
.skip:  add     si, cx                  ; on past this name and its device
        inc     si
        jmp     .t
.hit:   mov     al, [si]                ; (SI: past the name, CX = 0)
        xor     ah, ah
        clc
        jmp     .x
.gpib:  mov     di, bx                  ; GPIBnn
        cmp     word [di], 'GP'
        jne     .no
        cmp     word [di+2], 'IB'
        jne     .no
        add     di, 4
        xor     ax, ax                  ; AH = the address
        mov     cx, 2
.g:     mov     al, [di]
        sub     al, '0'
        cmp     al, 9                   ; (below '0' too)
        ja      .gx
        aad                             ; AL = AH * 10 + AL
        mov     ah, al
        inc     di
        loop    .g
.gx:    cmp     cx, 2
        je      .no
        mov     al, [di]
        or      al, al
        jz      .gok
        cmp     al, '.'
        jne     .no
.gok:   cmp     ah, 30
        ja      .no
        mov     al, DEV_GPIB
        clc
        jmp     .x
.no:    stc
.x:     pop     di
        pop     si
        pop     cx
        ret
; each: its length, the name, the device; a length of 0 ends them
dev_names   db 3, 'CON', DEV_CON, 3, 'NUL', DEV_NUL, 3, 'AUX', DEV_AUX
            db 4, 'COM1', DEV_AUX, 4, 'COM2', DEV_COM2, 3, 'PRN', DEV_PRN
            db 4, 'LPT1', DEV_PRN, 6, 'CLOCK$', DEV_NUL
.emm        db 0, 'EMMXXXX0', DEV_EMM, 0        ; (KEMS.INC: 8 here, with EMS)

; device AL (AH = GPIB address) into a new SFT entry -> SI, AL = number
dev_open:
        push    ax
        call    sft_alloc
        pop     dx
        jc      .x
        mov     byte [si+S_REF], 1
        mov     byte [si+S_MODE], 2
        mov     byte [si+S_FLAGS], SF_DEV
        mov     [si+S_DEV], dl
        mov     [si+S_GADR], dh
        clc
.x:     ret

; ---------------------------------------------------------------------
;  open, create, close
; ---------------------------------------------------------------------
f_3D:   call    get_path                ; OPEN
        jc      .e
        call    jft_alloc
        jc      .e
        push    bx
        call    dev_lookup
        jnc     create.dev              ; (the same: a device's handle)
        call    find_file
        jc      .nf
        test    byte [de+11], A_DIR | A_VOL
        jnz     .acc
        mov     al, [bp+F_AX]
        test    al, 3
        jz      .rd
        test    byte [de+11], A_RO
        jnz     .acc
.rd:    call    sft_alloc
        jc      .e1
        push    ax
        mov     al, [bp+F_AX]
        call    sft_fill
        pop     ax
        pop     bx
        jmp     give_handle
.acc:   mov     ax, 5                   ; (nf_last leaves 5 alone)
.nf:    call    nf_last
.e1:    pop     bx
.e:     jmp     fail

f_5B:   mov     byte [cr_new], 1        ; CREATE NEW
        jmp     create
f_3C:   mov     byte [cr_new], 0        ; CREATE (or truncate)
create: call    get_path
        jc      .e
        call    jft_alloc
        jc      .e
        push    bx
        test    byte [bp+F_CX], 0D8h    ; (a directory's, 40h or 80h: 5, as
        jnz     f_3D.acc                ;  MS-DOS, before the path is looked at;
                                        ;  a label's, 8: 5, not a file over one)
        call    dev_lookup
        jnc     .dev
        call    do_create
        jc      .e1
        pop     bx
        jmp     give_handle
.dev:   call    dev_where               ; (OPEN's too)
        jc      .e1
        call    dev_open
        jc      .e1
        pop     bx
        jmp     give_handle
.e1:    pop     bx
.e:     jmp     fail

; a device's name with a directory in front: that directory must be there,
; as MS-DOS says (NOSUCH\NUL is 3: "IF EXIST DIR\NUL"), and the name no
; wildcard or bad name (2).  [X:]\DEV\ in front is the devices' own, as in
; MS-DOS.  AX kept; CF: AX = the error.  NUL, A:NUL, \DEV\NUL: no disk.
; BX: dev_lookup's (the name), so a : past the drive's is a bad directory
; part too (A:B:NUL, \DEV\C:NUL: 2, as MS-DOS)
dev_where:
        push    ax
        mov     si, path_buf
        cmp     byte [si+1], ':'
        jne     .d
        inc     si
        inc     si
.d:     cmp     word [si], '\D'
        jne     .f
        cmp     word [si+2], 'EV'
        jne     .f
        cmp     byte [si+4], '\'
        jne     .f
        add     si, 5
.f:     cmp     bx, si                  ; the name right there?
        jne     .r
        pop     ax                      ; (CF clear)
        ret
.r:     call    resolve
        pop     si
        jc      .x
        cmp     byte [r_wild], 0        ; (CF clear)
        jne     .w
        xchg    ax, si
        ret
.w:     mov     ax, 3                   ; (a wildcard: 2, through nf_last)
.x:     jmp     nf_last                 ; (a bad last name: 2)

section .bss
cr_new      resb 1
section .text

; create path_buf with attributes [bp+F_CX] -> SI = SFT, AL = number
do_create:
        call    resolve_new
        jc      nf_last
        call    find_named
        jc      .new
        cmp     byte [cr_new], 0
        jne     .exists
        mov     al, [bp+F_CX]           ; a directory, label or read-only
        and     al, A_HID | A_SYS       ;  file, or hidden or system without
        xor     al, A_DIR | A_VOL | A_HID | A_SYS | A_RO   ; asking for it
        test    [de+11], al             ;  again: 5, as MS-DOS
        jnz     .acc
        call    sft_busy
        jc      .acc
        mov     ax, [si+26]             ; truncate the old file: its entry a
        jmp     short .ne               ;  fresh one (the name the same: no
.new:   cmp     ax, 2                   ;  wildcards), and only then, that on
        jne     .err                    ;  the disk, its chain freed: a
        mov     ax, [r_dir]             ;  refused write frees nothing that
        call    dir_slot                ;  the disk's entry still names
        jc      .x
        xor     ax, ax                  ; (no chain to free)
.ne:    push    ax
        mov     cl, [bp+F_CX]
        and     cl, 7                   ; (CREATE TEMPORARY: 8 and the rest too)
        or      cl, A_ARC               ; new, or made anew: archive, as MS-DOS
        xor     ax, ax
        call    new_entry
        pop     dx                      ; (AX: the error, if any)
        jc      .x
        mov     ax, dx                  ; (two bytes: what follows even)
        call    free_chain              ; (the old chain; 0: none)
        push    si
        mov     di, de
        mov     cx, 16
        rep     movsw
        pop     si
.open:  call    fat_flush_act
        jc      .x
        call    sft_alloc
        jc      .x
        push    ax
        mov     al, 2
        call    sft_fill
        pop     ax
        clc
.x:     ret
.exists:
        mov     ax, 80
        stc
        ret
.acc:   mov     ax, 5
.err:   stc
        ret

; open, create: a last part that is no name (resolve: r_wild FFh) or has
; wildcards (1) is "file not found", as MS-DOS says, not 3.  CF kept set
nf_last:
        cmp     ax, 3
        jne     .x
        cmp     [r_wild], ah            ; (AH = 0)
        je      .x
        dec     ax
.x:     stc
        ret

f_5A:   call    get_path                ; CREATE TEMPORARY: path + name
        jc      .e
        mov     di, path_buf            ; end of the given directory path
        xor     al, al
        mov     cx, 128
        repne   scasb
        dec     di
        mov     word [tmp_ins], 0
        cmp     di, path_buf
        je      .cat
        cmp     byte [di-1], '\'
        je      .cat
        cmp     byte [di-1], ':'
        je      .cat
        mov     byte [di], '\'
        inc     di
        inc     word [tmp_ins]          ; (the caller gets that '\' too)
.cat:   mov     [tmp_at], di
        call    clock_ticks
        mov     [tmp_n], dx
.try:   mov     di, [tmp_at]
        mov     ax, [tmp_n]
        mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, 'A'
        stosb
        pop     ax
        loop    .h
        mov     ax, 'TM'
        stosw
        mov     ax, 'P'
        stosw
        call    jft_alloc
        jc      .e
        push    bx
        mov     byte [cr_new], 1
        call    do_create
        pop     bx
        jnc     .ok
        cmp     ax, 80
        jne     .e
        inc     word [tmp_n]
        jmp     .try
.ok:    push    ax                      ; the name back to the caller
        push    si
        mov     si, [tmp_at]
        sub     si, [tmp_ins]
        mov     es, [bp+F_DS]
        mov     di, [bp+F_DX]
        mov     ax, si
        sub     ax, path_buf
        add     di, ax
        mov     cx, 8
        add     cx, [tmp_ins]
        rep     movsb
        push    cs
        pop     es
        pop     si
        pop     ax
        jmp     give_handle
.e:     jmp     fail

section .bss
tmp_at      resw 1
tmp_ins     resw 1
tmp_n       resw 1
section .text

f_3E:   call    h2sft_bp                ; CLOSE
        jc      .e
        call    sft_release             ; the handle let go after: an Abort
        push    ax                      ;  in its INT 24h leaves it to
        mov     al, 0FFh                ;  terminate's close_all (else the
        mov     bx, [bp+F_BX]           ;  SFT stayed in use till a reboot)
        call    jft_set                 ; (flags kept)
        pop     ax
        jmp     ret_cf
.e:     jmp     fail

; one user less for SFT SI; the last one writes the directory entry back,
; while it still counts as open: another disk in by then is "Invalid disk
; change" (drv_pend), as MS-DOS's, so Retry with this one back writes it.
; CF: AX = error (the file let go all the same)
sft_release:
        cmp     byte [si+S_REF], 1
        jb      sft_commit.ok           ; (none: nothing to do)
        clc                             ; (JA: ZF alone now)
        ja      .d
        test    byte [si+S_FLAGS], SF_DEV       ; (CF clear)
        jnz     .d
        call    sft_commit
.d:     dec     byte [si+S_REF]         ; (CF kept)
        ret

; written file SI: directory entry and FAT to disk.  CF: AX = error
sft_commit:
        test    byte [si+S_FLAGS], SF_DIRTY
        jz      .ok
        call    sft_chk                 ; (the disk it was opened on still)
        jnc     .go
        test    byte [si+S_FLAGS], SF_LOST
        jnz     .lost                   ; (else kept changed: the same disk
        stc                             ;  back, Retry or a later close
        ret                             ;  writes it)
.go:    push    bx
        push    dx
        push    di
        mov     al, [si+S_DRV]
        call    use_drive_si
        call    fat_flush_drv           ; the chain first, then the entry
        jc      .e                      ; (another drive's FAT in the cache:
                                        ;  this one's went out when it left)
        mov     dx, [si+S_DLBA]
        mov     ax, [si+S_DOFF]
        push    si
        call    dent_buf
        mov     di, si
        pop     si
        jc      .e
        mov     bx, 10                  ; (not this file's name there: the
.nm:    mov     al, [si+S_NAME+bx]      ;  entry's write Ignored, its sector
        cmp     al, [di+bx]             ;  read again, the slot unused or
        jne     .dn                     ;  another file's since: left alone,
        dec     bx                      ;  not made a nameless one or the
        jns     .nm                     ;  other's, rule 6.  Open, its name
                                        ;  is kept: RENAME refuses it)
        mov     ax, [si+S_CLU]          ; (field by field: a rep movsw would
        mov     [di+26], ax             ;  need ES set up, close_all's PSP
        mov     ax, [si+S_SIZE]         ;  here, and be no faster)
        mov     [di+28], ax
        mov     ax, [si+S_SIZE+2]
        mov     [di+30], ax
        test    byte [si+S_FLAGS], SF_STAMP
        jnz     .st
        push    dx
        call    dos_stamp
        mov     [si+S_TIME], ax
        mov     [si+S_DATE], dx
        pop     dx
.st:    mov     ax, [si+S_TIME]
        mov     [di+22], ax
        mov     ax, [si+S_DATE]
        mov     [di+24], ax
        or      byte [di+11], A_ARC
        push    si
        mov     si, di
        call    buf_put
        pop     si
        jc      .e
.dn:    and     byte [si+S_FLAGS], ~(SF_DIRTY | SF_STAMP)
        pop     di
        pop     dx
        pop     bx
.ok:    clc
        ret
.e:     pop     di
        pop     dx
        pop     bx
        stc
        ret
.lost:  and     byte [si+S_FLAGS], ~(SF_DIRTY | SF_STAMP)
        mov     ax, 5                   ; (its entry as on the disk: the
        stc                             ;  chain its changes named is gone)
        ret
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)

; SFT SI (a file) still on the disk it was opened on?  A floppy's drive
; is looked at first (drv_ready: its change line; another disk with this
; one's files open is INT 24h's "Invalid disk change", KDISK.INC rule 4);
; one without a change line only if not used for ~2 s (MS-DOS's rule: the
; BIOS says "changed" every time, and each look reads the disk; path calls
; look every time).  Another mount's file, or one SF_LOST: SF_LOST, CF,
; AX = 5 (rule 9).  The look failing (INT 24h's Fail, "Invalid disk
; change" or not ready): CF, AX = 5 too, the file as it was (KDISK.INC
; rule 9: a handle call's code for it).  SI kept
sft_chk:
        test    byte [si+S_FLAGS], SF_LOST
        jnz     .lost
        mov     al, [si+S_DRV]
        cmp     al, NFLOP
        jae     .ok
        push    si
        push    es
        call    drv_look
        pop     es
        pop     si
        jc      .lost                   ; (another mount's: SF_LOST then)
        mov     al, [si+S_DRV]
        call    gen_of
        cmp     ah, [si+S_GEN]
        je      .ok
        or      byte [si+S_FLAGS], SF_LOST
.lost:  mov     ax, 5
        stc
        ret
.ok:    clc
        ret

        times ($ + 1 - $$) & 1 db 90h   ; (what follows odd: its hot
                                        ;  labels even)
; floppy AL without a change line (D_PRES 3), no look due (D_CHK), its
; last transfer (dio.bok: a read or write that reached the disk, a look's
; too) less than 2 s ago (36 ticks)?  NC if so.  Only compares: calls
; answered from the caches don't hold the 2 s open, as MS-DOS's driver
; times from its own last access.  All kept
cl_fresh:
        pusha
        push    es
        call    cl_at
        sub     ax, [di]                ; ticks since (all 32 bits: an hour
        sbb     cx, [di+2]              ;  later isn't 0 ticks later, nor
        jcxz    .t                      ;  is a day's end: the high part not
        mov     ah, 1                   ;  0, 256 or more)
.t:     shl     bx, 5                   ; (DRVSZ)
        cmp     byte [drvtab+bx+D_PRES], 3
        jb      .x                      ; (a change line: CF, looked at)
        cmp     byte [drvtab+bx+D_CHK], 0
        stc                             ; (a look due: D_CHK)
        jne     .x
        cmp     ax, 36
        cmc
.x:     pop     es
        popa
        ret
%if DRVSZ != 32
%error "cl_fresh: DRVSZ"
%endif
; AL a floppy: BX = AL, DI = its cl_tick, CX:AX = the BIOS tick, ES = 0
cl_at:  push    0
        pop     es
        cbw
        mov     bx, ax
        xchg    di, ax
        shl     di, 2
        add     di, cl_tick
        mov     ax, [es:46Ch]
        mov     cx, [es:46Eh]
        ret

; use_drive for AL keeping SI
use_drive_si:
        push    si
        call    use_drive
        pop     si
        ret

; ---------------------------------------------------------------------
;  read and write: SI = SFT, CX = bytes, ES:DI = memory -> AX = bytes.
;  CF: AX = error
; ---------------------------------------------------------------------
sft_read:
        test    byte [si+S_FLAGS], SF_DEV
        jnz     dev_read
        jmp     file_read
sft_write:
        test    byte [si+S_FLAGS], SF_DEV
        jnz     dev_write
        jmp     file_write

f_3F:   call    h2sft_bp                ; READ
        jc      f_40.e
        mov     al, [si+S_MODE]
        and     al, 3
        cmp     al, 1
        je      f_40.acc
        mov     cx, [bp+F_CX]
        mov     es, [bp+F_DS]
        mov     di, [bp+F_DX]
        call    sft_read
        jc      f_40.e
        jmp     ok_ax
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)

f_40:   call    h2sft_bp                ; WRITE
        jc      .e
        mov     al, [si+S_MODE]
        and     al, 3
        jz      .acc
        mov     cx, [bp+F_CX]
        mov     es, [bp+F_DS]
        mov     di, [bp+F_DX]
        call    sft_write
        jc      .e
        jmp     ok_ax
.acc:   mov     ax, 5
.e:     jmp     fail
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)

; a read or write of CX bytes for SFT SI begins: the memory pointer ES:DI
; as segment + offset < 16 in rw_seg / rw_off; the file's drive, with
; its FAT.  CF: AX = error
rw_start:
        push    cx
        call    sft_chk
        pop     cx
        jc      .x
        mov     [rw_sft], si
        mov     [rw_left], cx
        mov     word [rw_done], 0
        mov     ax, di
        shr     ax, 4
        mov     dx, es
        add     ax, dx
        mov     [rw_seg], ax
        mov     ax, di
        and     ax, 15
        mov     [rw_off], ax
        mov     al, [si+S_DRV]          ; its drive, and that drive's FAT
        call    use_drive_si
        jmp     fat_load
.x:     ret
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
; advance by AX bytes
rw_step:
        add     [rw_done], ax
        sub     [rw_left], ax
        add     [si+S_POS], ax
        adc     word [si+S_POS+2], 0
        add     ax, [rw_off]
        mov     dx, ax
        and     dx, 15
        mov     [rw_off], dx
        shr     ax, 4
        add     [rw_seg], ax
        ret

; SFT SI's cluster number BX of its chain -> AX (cache updated).
; CF if the chain is shorter
sft_cluster:
        push    cx
        mov     ax, [si+S_CLU]
        cmp     ax, 2
        jb      .no
        xor     cx, cx
        cmp     word [si+S_CCL], 0
        je      .w
        cmp     bx, [si+S_CIX]
        jb      .w
        mov     ax, [si+S_CCL]
        mov     cx, [si+S_CIX]
.w:     cmp     cx, bx
        je      .got
        call    fat_get
        cmp     ax, 2
        jb      .no
        cmp     ax, 0FFF0h
        jae     .no
        inc     cx
        jmp     .w
.got:   mov     [si+S_CCL], ax
        mov     [si+S_CIX], cx
        clc
        pop     cx
        ret
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
.no:    stc
        pop     cx
        ret

; the same, allocating clusters when the chain is too short
sft_cluster_alloc:
        call    sft_cluster
        jnc     .x
        push    cx
        push    dx
        cmp     word [si+S_CLU], 2
        jae     .ext
        xor     dx, dx                  ; empty file: its first cluster
        call    clu_alloc
        jc      .e
        call    .took
        mov     [si+S_CLU], ax
        or      byte [si+S_FLAGS], SF_DIRTY
        mov     word [si+S_CCL], 0
.ext:   call    sft_cluster
        jnc     .ok
        ; walk to the last cluster, then add one after it
        mov     ax, [si+S_CLU]
        xor     cx, cx
        cmp     word [si+S_CCL], 0
        je      .l
        mov     ax, [si+S_CCL]
        mov     cx, [si+S_CIX]
.l:     mov     dx, ax
        call    fat_get
        cmp     ax, 2                   ; (free or reserved: a broken chain,
        jb      .bad                    ;  not its end: KDISK.INC rule 7)
        cmp     ax, 0FFF0h
        jae     .add
        inc     cx
        jmp     .l
.add:   mov     [si+S_CCL], dx
        mov     [si+S_CIX], cx
        call    clu_alloc               ; after DX
        jc      .e
        call    .took
        jmp     .ext
.ok:    pop     dx
        pop     cx
        clc
.x:     ret
.bad:   mov     ax, 5
.e:     pop     dx
        pop     cx
        stc
        ret
; cluster AX taken after DX (0: the first): the write's first such kept
; (rw_a1, after rw_ap) for its undoing.  All kept
.took:  cmp     word [rw_a1], 0
        jne     .tx
        mov     [rw_a1], ax
        mov     [rw_ap], dx
.tx:    ret
        times ($ + 1 - $$) & 1 db 90h   ; (hot: rw_where.one even)

; position -> BX = cluster index, CX = sector in cluster, DX = offset
rw_where:
        push    si
        mov     di, si
        mov     al, [si+S_DRV]
        call    use_drive
        mov     cl, [si+D_SHIFT]
        mov     si, di
        mov     ax, [si+S_POS]
        mov     dx, [si+S_POS+2]
        mov     bx, ax
        and     bx, 511
        push    bx                      ; offset in the sector
        shr     ax, 9                   ; DX:AX = sector of the file
        mov     bx, dx
        shl     bx, 7
        or      ax, bx
        shr     dx, 9
        push    ax
        xor     ch, ch                  ; CX = log2(sectors per cluster)
        jcxz    .one
.sh:    shr     dx, 1
        rcr     ax, 1
        loop    .sh
.one:   mov     bx, ax                  ; cluster index
        pop     ax
        mov     di, [actp]
        mov     cl, [di+D_SPC]
        dec     cl
        and     al, cl
        xor     ah, ah
        mov     cx, ax                  ; sector in the cluster
        pop     dx
        pop     si
        ret

file_read:
        call    rw_start
        jc      .err
        ; no further than the end of the file
        mov     ax, [si+S_SIZE]
        mov     dx, [si+S_SIZE+2]
        sub     ax, [si+S_POS]
        sbb     dx, [si+S_POS+2]
        jb      .none
        or      dx, dx
        jnz     .seq
        cmp     ax, [rw_left]
        jae     .seq
        mov     [rw_left], ax
        ; Read in order (from the start, or from where the last read
        ; ended or a little past it)?  Then the disk may read ahead to the
        ; end of the track, as far as the file goes (rw_flast = its last
        ; sector; FFFFh = no read-ahead).
.seq:   mov     word [rw_flast], 0FFFFh
        mov     ax, [si+S_POS]
        or      ax, [si+S_POS+2]
        jz      .sq
        mov     ax, [si+S_POS]
        sub     ax, [si+S_RAE]
        cmp     ax, 512                 ; (an EXE header skip still counts)
        jae     .loop
.sq:    mov     ax, [si+S_SIZE]
        mov     dx, [si+S_SIZE+2]
        sub     ax, 1
        sbb     dx, 0
        jb      .loop
        call    sec_of
        mov     [rw_flast], ax
.loop:  cmp     word [rw_left], 0
        je      .done
        call    rw_where                ; BX index, CX sector, DX offset
        call    sft_cluster
        jc      .done
        mov     [rw_cix], bx
        call    rw_lba_of
        jc      .part
        ; whole sectors straight into memory, across touching clusters
        call    rw_run0
        mov     ax, [rw_left]
        shr     ax, 9
        mov     [rw_want], ax
.ext:   mov     ax, [rw_run]
        cmp     ax, [rw_want]
        jae     .go
        cmp     ax, 64
        jae     .go
        mov     ax, [rw_cl]
        call    fat_get
        mov     dx, [rw_cl]
        inc     dx
        cmp     ax, dx
        jne     .go
        call    rw_adv
        jmp     .ext
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
.go:    mov     ax, [rw_cl]             ; the next lookup starts from here
        mov     [si+S_CCL], ax
        mov     ax, [rw_cix]
        mov     [si+S_CIX], ax
        mov     cx, [rw_run]
        cmp     cx, [rw_want]
        jbe     .n1
        mov     cx, [rw_want]
.n1:    cmp     cx, 64
        jbe     .n2
        mov     cx, 64
.n2:    call    pos_sec
        add     ax, cx
        dec     ax
        call    rw_setra
        push    cx
        mov     al, [act]
        mov     ah, 2
        mov     dx, [rw_lba]
        mov     es, [rw_seg]
        mov     bx, [rw_off]
        call    disk_io
        pop     cx
        jc      .err
        mov     ax, cx
        shl     ax, 9
        call    rw_step
        jmp     .loop
.part:  call    pos_sec
        call    rw_setra
        call    rw_part
        jc      .err
        push    si
        push    cx
        mov     si, bx
        add     si, dx
        mov     es, [rw_seg]
        mov     di, [rw_off]
        rep     movsb
        pop     ax
        pop     si
        call    rw_step
        jmp     .loop
.none:  mov     word [rw_left], 0
.done:  mov     ax, [si+S_POS]
        mov     [si+S_RAE], ax
        mov     ax, [rw_done]
        clc
        ret
.err:   stc
        ret

; DX:AX (a file position) -> AX = its sector in the file (DX:AX >> 9)
sec_of: shr     ax, 9
        shl     dx, 7
        or      ax, dx
        ret
; file_read's and file_write's: DI = the drive's entry, [rw_run] = the
; sectors left in the cluster from sector CX
rw_run0:
        mov     di, [actp]
        mov     al, [di+D_SPC]
        xor     ah, ah
        sub     ax, cx
        mov     [rw_run], ax
        ret
; the run goes on into cluster AX
rw_adv: mov     [rw_cl], ax
        inc     word [rw_cix]
        mov     al, [di+D_SPC]
        xor     ah, ah
        add     [rw_run], ax
        ret
; cluster AX, sector CX of it, offset DX there: [rw_cl], and [rw_lba]
; its sector (its high bits in lba_hi: taken by disk_io or buf_getd).  CF:
; not a whole sector's (offset DX, or less than 512 to go: rw_part's)
rw_lba_of:
        mov     [rw_cl], ax
        push    cx
        call    clu2lba
        pop     cx
        add     ax, cx
        adc     byte [lba_hi], 0
        mov     [rw_lba], ax
        or      dx, dx
        stc
        jnz     .x
        cmp     word [rw_left], 512
.x:     ret
; [rw_lba] in a buffer, BX (SI kept); CX = the bytes of it from offset DX,
; [rw_left] at most.  CF: AX = the error
rw_part:
        push    dx
        mov     al, [act]
        mov     dx, [rw_lba]
        push    si
        call    buf_getd
        mov     bx, si
        pop     si
        pop     dx
        jc      .r
        mov     cx, 512
        sub     cx, dx
        cmp     cx, [rw_left]
        jbe     .x
        mov     cx, [rw_left]
.x:     clc
.r:     ret
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
; AX = the sector of the file the position of SFT SI is in
pos_sec:
        push    dx
        mov     ax, [si+S_POS]
        mov     dx, [si+S_POS+2]
        call    sec_of
        pop     dx
        ret
; AX = the file's last sector this transfer reads: allow the disk to
; read ahead the file's sectors after it (none if not read in order)
rw_setra:
        push    cx
        mov     cx, [rw_flast]
        cmp     cx, 0FFFFh
        je      .z
        sub     cx, ax
        jbe     .z
        cmp     cx, TC_SECS
        jbe     .s
        mov     cx, TC_SECS
.s:     mov     [io_ra], cx
        pop     cx
        ret
.z:     mov     word [io_ra], 0
        pop     cx
        ret

section .bss
rw_cl       resw 1
rw_cix      resw 1
rw_lba      resw 1
rw_run      resw 1
rw_want     resw 1
rw_flast    resw 1
rw_new      resw 1              ; free clusters joined to a write run
rw_link     resw 1              ;   after this one (the chain's end)
rw_t0       resb 1              ; sector in the track a write run starts at
            alignb 2
rw_a1       resw 1              ; the first cluster this write took (0: none),
rw_ap       resw 1              ;   linked after this one (0: the first)
rw_sz0      resw 2              ; the file's size as the write began,
rw_p0       resw 2              ;  its position,
rw_f0       resb 1              ;  and its flags
section .text

file_write:
        call    rw_start                ; (refused if SF_LOST: the chain it
        jc      .ex                     ;  had is gone; rw_start's sft_chk)
        call    fat_keep                ; (what a failed write gives back:
        xor     ax, ax                  ;  the clusters it took, and the
        mov     [rw_a1], ax             ;  FAT's changed state, KDISK.INC
        mov     ax, [si+S_SIZE]         ;  rule 5)
        mov     [rw_sz0], ax
        mov     ax, [si+S_SIZE+2]
        mov     [rw_sz0+2], ax
        mov     ax, [si+S_POS]
        mov     [rw_p0], ax
        mov     ax, [si+S_POS+2]
        mov     [rw_p0+2], ax
        mov     al, [si+S_FLAGS]
        mov     [rw_f0], al
        or      byte [si+S_FLAGS], SF_DIRTY
        or      cx, cx
        jnz     .loop
        jmp     .setsz
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
.loop:  cmp     word [rw_left], 0
        je      .done
        call    rw_where
        call    sft_cluster_alloc
        jc      .full
        call    rw_lba_of
        jc      .part
        ; Whole sectors, across touching clusters, to the end of the track
        ; at most.  Where the chain ends, the free clusters right after it
        ; join the run.  They are linked into the chain before the write
        ; if the run starts a track (the disk is busy reaching it anyway),
        ; otherwise after it: the CPU time between one write and the next
        ; decides whether the next sector is caught or a turn is lost.
        mov     [rw_cix], bx
        mov     word [rw_new], 0
        call    rw_run0
        mov     ax, [rw_lba]
        mov     dx, [lba_hi]
        div     word [di+D_SPT]
        mov     [rw_t0], dl             ; 0: the run starts a track
        mov     cx, [di+D_SPT]
        sub     cx, dx                  ; sectors to the end of the track
        mov     ax, [rw_left]
        shr     ax, 9
        cmp     ax, cx
        jbe     .wa
        mov     ax, cx
.wa:    mov     [rw_want], ax
.wext:  mov     ax, [rw_run]
        cmp     ax, [rw_want]
        jae     .wgo
        mov     ax, [rw_cl]
        call    fat_get
        cmp     ax, 0FFF0h
        jae     .wend
        mov     dx, [rw_cl]
        inc     dx
        cmp     ax, dx
        jne     .wgo                    ; not next to it: another run
        call    rw_adv
        jmp     .wext
.wend:  mov     ax, [rw_want]           ; the chain ends: free ones after it
        sub     ax, [rw_run]            ; (sectors still wanted
        mov     cl, [di+D_SPC]          ;  -> clusters, rounded up)
        xor     ch, ch
        add     ax, cx
        dec     ax
        mov     cl, [di+D_SHIFT]
        shr     ax, cl
        mov     cx, ax
        mov     ax, [rw_cl]
        mov     [rw_link], ax
        inc     ax
        call    free_run                ; -> CX in a row
        jcxz    .wgo
        mov     [rw_new], cx
        add     [rw_cl], cx
        add     [rw_cix], cx
        mov     al, [di+D_SPC]
        xor     ah, ah
        mul     cx
        add     [rw_run], ax
.wgo:   cmp     byte [rw_t0], 0
        jne     .wn
        call    .link                   ; (time to spare: before the write)
.wn:    mov     cx, [rw_run]
        cmp     cx, [rw_want]
        jbe     .n1
        mov     cx, [rw_want]
.n1:    mov     al, [act]
        mov     dx, [rw_lba]
        call    buf_inval_range
        push    cx
        mov     ah, 3
        mov     es, [rw_seg]
        mov     bx, [rw_off]
        call    disk_io
        pop     cx
        jc      .err
        call    .link                   ; (if not done before)
        mov     ax, [rw_cl]             ; the next lookup starts from here
        mov     [si+S_CCL], ax
        mov     ax, [rw_cix]
        mov     [si+S_CIX], ax
        mov     ax, cx
        shl     ax, 9
        call    rw_step
        call    .grow
        jmp     .loop
; link the run's [rw_new] free clusters after [rw_link] into the chain
.link:  push    cx
        mov     cx, [rw_new]
        jcxz    .lx
        mov     word [rw_new], 0
        mov     ax, [rw_link]
        cmp     word [rw_a1], 0         ; (the write's first taken: KDISK.INC
        jne     .lk                     ;  rule 5)
        mov     [rw_ap], ax
        inc     ax
        mov     [rw_a1], ax
        dec     ax
.lk:    mov     dx, ax
        inc     dx
        call    fat_set
        inc     ax
        loop    .lk
        mov     dx, 0FFFFh
        call    fat_set
        inc     ax
        mov     [di+D_HINT], ax
.lx:    pop     cx
        ret
.part:  call    rw_part
        jc      .err
        push    si
        push    ds
        push    cx
        push    cs
        pop     es
        mov     di, bx
        add     di, dx
        mov     si, [rw_off]
        mov     ds, [rw_seg]
        rep     movsb
        pop     cx
        pop     ds
        mov     si, bx
        call    buf_put
        pop     si
        jc      .err
        mov     ax, cx
        call    rw_step
        call    .grow
        jmp     .loop
.done:  mov     ax, [rw_done]
        clc
        ret
.full:  cmp     ax, 39                  ; disk full: what fitted
        je      .done
.err:   push    ax                      ; a failed write gives back the
        mov     ax, [rw_a1]             ;  clusters it took (KDISK.INC rule
        or      ax, ax                  ;  5), and the size it grew to
        jz      .ee
        mov     dx, [rw_ap]
        or      dx, dx
        jnz     .ec
        mov     [si+S_CLU], dx          ; (they were all the file had)
        jmp     short .ef
.ec:    xchg    ax, dx                  ; the chain ends where it did
        push    dx
        mov     dx, 0FFFFh
        call    fat_set
        pop     ax
.ef:    call    free_chain
        call    fat_back
        mov     word [si+S_CCL], 0
.ee:    mov     ax, [rw_sz0]            ; the size it had (grown inside a
        mov     [si+S_SIZE], ax         ;  cluster the file had already, too:
        mov     ax, [rw_sz0+2]          ;  no cluster taken, rw_a1 0),
        mov     [si+S_SIZE+2], ax
        mov     ax, [rw_p0]             ; the position it had (the write
        mov     [si+S_POS], ax          ;  failed), and with nothing written
        mov     ax, [rw_p0+2]           ;  its flags: no entry change to go
        mov     [si+S_POS+2], ax
        cmp     word [rw_done], 0
        jne     .ed
        mov     al, [rw_f0]
        xor     al, [si+S_FLAGS]
        and     al, SF_DIRTY
        xor     [si+S_FLAGS], al
.ed:    pop     ax
.ex:    stc
        ret
; the file grew?
.grow:  mov     ax, [si+S_POS]
        mov     dx, [si+S_POS+2]
        cmp     dx, [si+S_SIZE+2]
        jb      .gx
        ja      .gs
        cmp     ax, [si+S_SIZE]
        jbe     .gx
.gs:    mov     [si+S_SIZE], ax
        mov     [si+S_SIZE+2], dx
.gx:    ret
; the size is the position (the chain looked up afresh).  DX:AX = it
.psz:   mov     word [si+S_CCL], 0
        mov     ax, [si+S_POS]
        mov     dx, [si+S_POS+2]
        jmp     .gs
; a zero-byte write: the file ends (or grows to) here
.setsz: mov     ax, [si+S_POS]
        or      ax, [si+S_POS+2]
        jz      .zero
        ; keep (or allocate) clusters up to the one holding pos-1
        sub     word [si+S_POS], 1
        sbb     word [si+S_POS+2], 0
        call    rw_where
        add     word [si+S_POS], 1
        adc     word [si+S_POS+2], 0
        call    sft_cluster_alloc
        jc      .done
        push    ax
        call    fat_get
        mov     dx, ax
        pop     ax
        cmp     dx, 0FFF0h
        jae     .sz
        push    ax                      ; a shorter file: its entry, the new
        push    dx                      ;  size, on the disk first (.tcommit)
        call    .tcommit
        jc      .ts
        pop     dx
        pop     ax
        push    dx
        mov     dx, 0FFFFh
        call    fat_set                 ; end the chain here
        pop     ax
.tfree: call    free_chain              ; and drop the rest, then the FAT
        mov     al, [si+S_DRV]          ;  out (refused: the frees go at the
        call    fat_flush_drv           ;  next flush, their entry on the
        jmp     .done                   ;  disk already)
.zero:  mov     ax, [si+S_CLU]
        cmp     ax, 2
        jb      .sz
        push    ax
        call    .tcommit
        jc      .tz
        pop     ax
        jmp     .tfree
.ts:    pop     cx                      ; (refused: AX the error)
.tz:    pop     cx
        jmp     .err
; the entry of SI with its size S_POS (0: no cluster) on the disk, before
; the clusters past it are freed: a refused write frees nothing the disk's
; entry still names.  CF: AX, the SFT as it was
.tcommit:
        push    word [si+S_CLU]
        push    word [si+S_SIZE+2]
        push    word [si+S_SIZE]
        call    .psz
        or      dx, ax
        jnz     .tc
        mov     [si+S_CLU], dx
.tc:    call    sft_commit.go           ; (rw_start looked at the disk: no
                                        ;  second look to drop the FAT cache)
        jc      .tb
        add     sp, 6
        ret
.tb:    pop     word [si+S_SIZE]
        pop     word [si+S_SIZE+2]
        pop     word [si+S_CLU]
        ret
.sz:    call    .psz
        jmp     .done

; ---------------------------------------------------------------------
;  devices
; ---------------------------------------------------------------------
dev_read:
        mov     al, [si+S_DEV]
        cmp     al, DEV_CON
        je      con_read
        cmp     al, DEV_GPIB
        je      .gpib
        cmp     al, DEV_AUX
        je      .aux
        cmp     al, DEV_COM2
        je      .aux
        xor     ax, ax                  ; NUL, PRN: nothing
        clc
        ret
.aux:   push    cx
        push    dx
        xor     dx, dx                  ; AUX = COM1 (DX 0), COM2 (DX 1)
        cmp     al, DEV_COM2
        jne     .a0
        inc     dx
.a0:    push    ds                      ; a port the BIOS didn't find (its
        push    40h                     ;  base in the BDA 0): its INT 14h
        pop     ds                      ;  then answers without a time-out,
        mov     bx, dx                  ;  so this would read for ever
        add     bx, bx
        mov     bx, [bx]
        pop     ds
        test    bx, bx
        jz      .ax                     ; (BX = 0: nothing read)
        xor     bx, bx
.al:    jcxz    .ax
        mov     ah, 2
        int     14h
        test    ah, 80h
        jnz     .ax
        stosb
        inc     bx
        dec     cx
        jmp     .al
.ax:    mov     ax, bx
        pop     dx
        pop     cx
        clc
        ret
.gpib:  cmp     byte [gp_ok], 0
        je      .nog
        mov     bl, [si+S_GADR]
        xor     al, al
        mov     ah, 3
        int     60h
        jc      .ge
        mov     ax, cx
        clc
        ret
.ge:    mov     ax, 31
        stc
        ret
.nog:   mov     ax, 21
        stc
        ret

dev_write:
        mov     al, [si+S_DEV]
        cmp     al, DEV_CON
        je      .con
        cmp     al, DEV_GPIB
        je      .gpib
        cmp     al, DEV_AUX
        je      .aux
        cmp     al, DEV_COM2
        je      .aux
        cmp     al, DEV_PRN
        je      .prn
        mov     ax, cx                  ; NUL
        clc
        ret
.con:   push    cx
.cl:    jcxz    .cx
        mov     al, [es:di]
        inc     di
        call    tty_out
        dec     cx
        jmp     .cl
.cx:    pop     ax
        clc
        ret
.aux:   push    cx
        push    dx
        xor     dx, dx
        cmp     byte [si+S_DEV], DEV_COM2
        jne     .a1
        inc     dx
.a1:    jcxz    .a2
        mov     al, [es:di]
        inc     di
        mov     ah, 1
        int     14h
        dec     cx
        jmp     .a1
.a2:    pop     dx
        pop     ax
        clc
        ret
.prn:   push    cx
        push    dx
.p1:    jcxz    .p2
        mov     al, [es:di]
        inc     di
        xor     ah, ah
        xor     dx, dx
        int     17h
        dec     cx
        jmp     .p1
.p2:    pop     dx
        pop     ax
        clc
        ret
.gpib:  cmp     byte [gp_ok], 0
        je      dev_read.nog
        push    si
        push    ds
        mov     bl, [si+S_GADR]
        mov     si, di
        push    es
        pop     ds
        mov     ax, 0201h               ; write, EOI with the last byte
        int     60h
        pop     ds
        pop     si
        jc      dev_read.ge
        mov     ax, cx
        clc
        ret

; CON input: a line at a time with editing and echo (raw: as typed)
con_read:
        test    byte [si+S_FLAGS], SF_RAW
        jnz     .raw
        mov     ax, [con_lpos]
        cmp     ax, [con_llen]
        jb      .give
        call    con_readline
.give:  mov     ax, [con_llen]
        sub     ax, [con_lpos]
        cmp     cx, ax
        jbe     .n
        mov     cx, ax
.n:     push    cx
        push    si
        mov     si, con_line
        add     si, [con_lpos]
        add     [con_lpos], cx
        rep     movsb
        pop     si
        pop     ax
        clc
        ret
.raw:   push    cx
.r:     jcxz    .rx
        call    kbd_get
        stosb
        dec     cx
        jmp     .r
.rx:    pop     ax
        clc
        ret

con_readline:
        push    cx
        push    di
        push    es
        xor     cx, cx
.l:     call    kbd_get
        cmp     al, 3
        je      ctrlc
        or      al, al
        jnz     .n0
        call    kbd_get                 ; extended key: ignored
        jmp     .l
.n0:    cmp     al, 0Dh
        je      .end
        cmp     al, 8
        je      .bs
        cmp     al, 1Bh
        je      .esc
        cmp     cx, 126
        jae     .l
        mov     bx, cx
        mov     [con_line+bx], al
        inc     cx
        call    tty_out
        jmp     .l
.bs:    jcxz    .l
        dec     cx
        call    .rub
        jmp     .l
.esc:   jcxz    .l
        dec     cx
        call    .rub
        jmp     .esc
.rub:   mov     al, 8
        call    tty_out
        mov     al, ' '
        call    tty_out
        mov     al, 8
        jmp     tty_out
.end:   mov     bx, cx
        mov     word [con_line+bx], 0A0Dh
        add     cx, 2
        mov     [con_llen], cx
        mov     word [con_lpos], 0
        mov     al, 13
        call    tty_out
        mov     al, 10
        call    tty_out
        pop     es
        pop     di
        pop     cx
        ret

; ---------------------------------------------------------------------
;  seek, IOCTL, dup, time stamps, commit
; ---------------------------------------------------------------------
f_42:   call    h2sft_bp                ; LSEEK
        jc      .e
        mov     ax, [bp+F_DX]
        mov     dx, [bp+F_CX]
        mov     cl, [bp+F_AX]
        cmp     cl, 0
        je      .set
        cmp     cl, 1
        je      .cur
        cmp     cl, 2
        jne     .bad
        add     ax, [si+S_SIZE]
        adc     dx, [si+S_SIZE+2]
        jmp     .set
.cur:   add     ax, [si+S_POS]
        adc     dx, [si+S_POS+2]
.set:   mov     [si+S_POS], ax
        mov     [si+S_POS+2], dx
        mov     [bp+F_DX], dx
        jmp     ok_ax
.bad:   mov     ax, 1
.e:     jmp     fail

f_44:   mov     al, [bp+F_AX]           ; IOCTL
        cmp     al, 8
        je      .rem
        cmp     al, 9
        je      .remote
        cmp     al, 0Eh
        je      .map
        cmp     al, 0Fh
        je      .okk
        cmp     al, 0Bh
        je      .okk
        call    h2sft_bp
        jc      .e
        mov     al, [bp+F_AX]
        cmp     al, 0
        je      .get
        cmp     al, 1
        je      .set
        cmp     al, 6
        je      .ist
        cmp     al, 7
        je      .ost
        cmp     al, 0Ah
        je      .remote
        mov     ax, 1
.e:     jmp     fail
.get:   test    byte [si+S_FLAGS], SF_DEV
        jz      .gf
        mov     al, [si+S_DEV]
        mov     dx, 80C0h
        cmp     al, DEV_CON
        jne     .gn
        mov     dx, 80D3h
.gn:    cmp     al, DEV_NUL
        jne     .gr
        mov     dx, 8084h
.gr:    test    byte [si+S_FLAGS], SF_RAW
        jz      .gd
        or      dl, 20h
.gd:    mov     [bp+F_DX], dx
        mov     ax, dx
        jmp     ok_ax
.gf:    mov     dl, [si+S_DRV]
        xor     dh, dh
        test    byte [si+S_FLAGS], SF_DIRTY
        jnz     .gd
        or      dl, 40h
        jmp     .gd
.set:   test    byte [si+S_FLAGS], SF_DEV
        jz      .okk
        and     byte [si+S_FLAGS], ~SF_RAW
        test    byte [bp+F_DX], 20h
        jz      .okk
        or      byte [si+S_FLAGS], SF_RAW
.okk:   jmp     ok
.ist:   mov     al, 0FFh
        test    byte [si+S_FLAGS], SF_DEV
        jnz     .idev
        mov     dx, [si+S_POS+2]
        cmp     dx, [si+S_SIZE+2]
        jb      .iy
        ja      .in
        mov     dx, [si+S_POS]
        cmp     dx, [si+S_SIZE]
        jb      .iy
.in:    xor     al, al
.iy:    xor     ah, ah
        jmp     ok_ax
.idev:  cmp     byte [si+S_DEV], DEV_CON
        jne     .iy
        call    con_ready
        mov     al, 0FFh
        jnz     .iy
        xor     al, al
        jmp     .iy
.ost:   mov     ax, 00FFh
        jmp     ok_ax
.rem:   mov     al, [bp+F_BX]           ; removable?  (A: and B: are; C: and M:
        call    drv_dflt                ;  not)
        call    drv_present
        jc      .bdrv
        cmp     al, 2
        sbb     ax, ax                  ; (A:, B: -1, then 0; others 0, then 1)
        inc     ax
        jmp     ok_ax
.bdrv:  mov     ax, 15
        jmp     fail
.remote:
        mov     word [bp+F_DX], 0
        jmp     ok
.map:   xor     ax, ax
        jmp     ok_ax

f_45:   call    h2sft_bp                ; DUP
        jc      .e
        push    ax
        call    jft_alloc
        pop     dx
        jc      .e
        inc     byte [si+S_REF]
        mov     al, dl
        jmp     give_handle
.e:     jmp     fail

f_46:   call    h2sft_bp                ; DUP2: CX becomes a copy of BX
        jc      .e
        push    ax
        push    si
        mov     bx, [bp+F_CX]
        cmp     bx, 20
        jae     .e2
        call    h2sft
        jc      .free
        call    sft_release
.free:  pop     si
        pop     ax
        inc     byte [si+S_REF]
        mov     bx, [bp+F_CX]
        call    jft_set
        jmp     ok
.e2:    add     sp, 4
        mov     ax, 6
.e:     jmp     fail

f_57:   call    h2sft_bp                ; file date and time
        jc      .e
        cmp     byte [bp+F_AX], 0
        jne     .set
        mov     ax, [si+S_TIME]
        mov     [bp+F_CX], ax
        mov     ax, [si+S_DATE]
        mov     [bp+F_DX], ax
        jmp     ok
.set:   mov     ax, [bp+F_CX]
        mov     [si+S_TIME], ax
        mov     ax, [bp+F_DX]
        mov     [si+S_DATE], ax
        test    byte [si+S_FLAGS], SF_DEV
        jnz     .x
        or      byte [si+S_FLAGS], SF_DIRTY | SF_STAMP
.x:     jmp     ok
.e:     jmp     fail

f_68:   call    h2sft_bp                ; COMMIT
        jc      .e
        test    byte [si+S_FLAGS], SF_DEV
        jnz     .x
        call    sft_commit
        jc      .e
.x:     jmp     ok
.e:     jmp     fail

; close every handle of the PSP at ES
close_all:
        push    bx
        push    si
        xor     bx, bx
.l:     mov     al, [es:18h+bx]
        cmp     al, NSFT
        jae     .n
        mov     byte [es:18h+bx], 0FFh
        call    sft_of
        call    sft_release
.n:     inc     bx
        cmp     bx, 20
        jb      .l
        pop     si
        pop     bx
        ret
; close_all as terminate runs it: an INT 24h Abort in its closes is Fail
; (KMT.INC's task ends: else each Abort ended the stub again, inside them)
close_allt:
        mov     byte [term_now], 1
        call    close_all
        mov     byte [term_now], 0
        ret

; ---------------------------------------------------------------------
;  find first / next.  The DTA's first 21 bytes hold our search state:
;  [0] drive+1, [1] pattern (11), [12] attributes, [13] dir cluster,
;  [15] next entry
; ---------------------------------------------------------------------
f_4E:   call    get_path
        jc      .e
        call    resolve
        jc      .e
        les     di, [dta]
        mov     al, [act]
        inc     al
        stosb
        mov     si, r_name
        mov     cx, 11
        cmp     byte [si], 0
        jne     .p
        mov     al, '?'                 ; no name: everything
        rep     stosb
        jmp     short .q
.p:     rep     movsb
.q:     mov     al, [bp+F_CX]           ; (the label alone: where the path
        stosb                           ;  points, as GRiD MS-DOS 3.30's,
        mov     ax, [r_dir]             ;  NOMATCH_MS.TXT; only the FCB
        stosw                           ;  search goes to the root)
        xor     ax, ax
        stosw
        push    cs
        pop     es
        call    find_next               ; (nothing at all: 18, as MS-DOS)
        jmp     ret_cf
.e:     jmp     fail
f_4F:   call    find_next
        jmp     ret_cf

; FCB find first / next (11h, 12h), as MS-DOS's: DS:DX an FCB, or an
; extended one (FFh, 5 bytes, the attribute, the FCB).  In the drive's
; current directory, '?' in the 11-byte name any character, the attribute
; as 4Eh's (08h alone: the label, in the root).  The DTA gets the drive (1 = A) and the
; entry's 32 bytes as on the disk, after the extended header (FFh, 0 x 5,
; the attribute) if the call had one: so a label's 11 characters come
; back as they are, spaces and all (COMMAND's VOL reads it so).  Between
; calls the search is in the FCB from 0Ch (drive + 1, the directory's
; cluster, the next entry), the bytes MS-DOS keeps it in.  AL = 0, or FFh:
; nothing more (or no such drive, or a separator or control character in
; the name: as MS-DOS 3's TransFCB, but for '.', which it would take into
; the path it makes and Lodestone counts out with the rest)
FCB_D   equ path2_buf                   ; (K2: a DTA for find_next, 43)
f_11:   call    fcb_ptr
        mov     al, [es:di]             ; its drive (0: the current one):
        push    cs                      ;  there, read, its current
        pop     es                      ;  directory (resolve "X:")
        call    drv_dflt
        add     al, 'A'
        mov     ah, ':'
        mov     [path_buf], ax
        mov     byte [path_buf + 2], 0
        call    resolve
        jc      f_fcb
        call    fcb_ptr
        mov     dx, [r_dir]
        and     al, A_HID | A_SYS | A_DIR | A_VOL
        cmp     al, A_VOL               ; (the label alone: the root's,
        jne     .d                      ;  wherever the current directory
        xor     dx, dx                  ;  is, as MS-DOS's)
.d:     mov     al, [act]
        inc     ax
        mov     [es:di + 0Ch], al
        mov     [es:di + 0Dh], dx
        mov     word [es:di + 0Fh], 0
f_12:   call    fcb_ptr                 ; its search -> FCB_D, as 4Eh's DTA
        mov     [FCB_D + 12], al
        push    ds
        push    es
        pop     ds
        lea     si, [di + 1]
        push    cs
        pop     es
        mov     di, FCB_D + 1
        mov     cx, 11
        rep     movsb
        lodsb
        mov     [es:FCB_D], al
        lodsw
        mov     [es:FCB_D + 13], ax
        lodsw
        mov     [es:FCB_D + 15], ax
        pop     ds
        mov     si, FCB_D + 1           ; the name as MS-DOS 3's takes it
        xor     dx, dx                  ;  (made a path): capitals, a *
.u:     mov     al, [si]                ;  fills the rest of its part with
        cmp     si, FCB_D + 9           ;  ?, a first E5h is 05h
        jne     .s
        xor     dx, dx
.s:     or      dx, dx
        jnz     .q
        cmp     al, '*'
        jne     .lc
        inc     dx
.q:     mov     al, '?'
        jmp     short .p
.lc:    cmp     al, ' '                 ; (a control character or a
        jb      .bad                    ;  separator: no name, FFh, as
        push    cx                      ;  MS-DOS's TransFCB)
        push    di
        mov     di, sepchars
        mov     cx, NSEP
        repne   scasb
        pop     di
        pop     cx
        je      .bad
        call    up_al
.p:     mov     [si], al
        inc     si
        cmp     si, FCB_D + 12
        jb      .u
        cmp     byte [FCB_D + 1], 0E5h
        jne     .e5
        mov     byte [FCB_D + 1], 05h
.e5:    push    word [dta + 2]          ; find_next on FCB_D
        push    word [dta]
        mov     word [dta], FCB_D
        mov     [dta + 2], cs
        call    find_next               ; -> SI the entry (DS = ES = CS)
        pop     word [dta]
        pop     word [dta + 2]
        jc      f_fcb
        push    si
        call    fcb_ptr                 ; its next entry kept
        mov     ax, [FCB_D + 15]
        mov     [es:di + 0Fh], ax
        pop     si
        les     di, [dta]               ; the answer
        or      bl, bl
        jz      .n
        mov     al, 0FFh
        stosb
        xor     ax, ax
        stosw
        stosw
        stosb
        mov     al, [FCB_D + 12]
        stosb
.n:     mov     al, [FCB_D]
        stosb
        mov     cx, 16
        rep     movsw
        cmp     byte [es:di - 32], 05h  ; (E5h's place on the disk)
        jne     .x
        mov     byte [es:di - 32], 0E5h
.x:     push    cs
        pop     es
        xor     al, al
        jmp     ret_al
.bad:   jmp     f_fcb
; the caller's FCB -> ES:DI (past an extended header), AL its attribute
; (0 without one), BL = 1 if it had one
fcb_ptr:
        mov     es, [bp + F_DS]
        mov     di, [bp + F_DX]
        xor     ax, ax
        xor     bl, bl
        cmp     byte [es:di], 0FFh
        jne     .x
        mov     al, [es:di + 6]
        add     di, 7
        inc     bx
.x:     ret

find_next:
        les     di, [dta]               ; (kept by drv_present and fat_load,
        mov     al, [es:di]             ;  their M:, R: and C: hooks too)
        dec     al
        call    drv_present
        jc      .nomore
        cmp     byte [si+D_MNT], 0
        je      .nomore
        cmp     byte [si+D_CHK], 0      ; a look due (another disk seen and
        je      .ld                     ;  kept, an automatic Fail; INT 21h
        call    drv_ready               ;  0Dh): looked at first, as MS-
        jc      .nomore                 ;  DOS's buffers do, so the search
        les     di, [dta]               ;  never reads another disk's
.ld:    call    fat_load                ;  sectors as its own
        jc      .x
        mov     word [it_dir], 0
        push    ds                      ; the pattern
        push    es
        pop     ds
        lea     si, [di+1]
        push    cs
        pop     es
        push    di
        mov     di, nm11
        mov     cx, 11
        rep     movsb
        pop     di
        pop     ds
        les     di, [dta]               ; ES again (a clock faster than PUSH/POP)
        mov     ax, [es:di+13]
        call    dir_lim
        mov     bx, [es:di+15]
.l:     mov     ax, [es:di+13]
        push    es
        push    di
        push    cs
        pop     es
        call    dir_entry
        pop     di
        pop     es
        jc      .derr
.e:     mov     al, [si]
        or      al, al
        jz      .nomore
        cmp     al, 0E5h
        je      .n
        mov     al, [si+11]
        cmp     al, 0Fh
        je      .n
        mov     ah, [es:di+12]          ; (as MS-DOS's: read-only and
        and     ah, A_HID | A_SYS | A_DIR | A_VOL  ;  archive asked for count
        cmp     ah, A_VOL               ;  nothing)
        jne     .nv
        test    al, A_VOL               ; label search: labels only
        jz      .n
        jmp     .m
.nv:    test    al, A_VOL               ; (a label: out of the way, below)
        jnz     .lab
        and     al, A_HID | A_SYS | A_DIR
        not     ah
        test    al, ah
        jnz     .n
.m:     call    name_match
        jne     .n
        ; found: fill the DTA
        inc     bx
        mov     [es:di+15], bx
        mov     al, [si+11]             ; attribute, time, date, size
        add     di, 21
        stosb
        add     si, 22
        movsw
        movsw
        inc     si                      ; (past the cluster)
        inc     si
        movsw
        movsw
        sub     si, 32                  ; SI the entry again, DI at +30
        call    name_out
        push    cs
        pop     es
        clc
        ret
.n:     inc     bx                      ; the next entry: in this sector,
        test    bl, 15                  ; straight on in the buffer
        jz      .l
        cmp     bx, [dl_lim]
        jae     .l
        add     si, 32
        jmp     .e
.lab:   test    ah, A_VOL               ; a label with others asked for:
        jz      .n                      ;  when 08h is one of them, as
        jmp     .m                      ;  MS-DOS's
.derr:  cmp     ax, 18
        je      .nomore
        push    cs                      ; a disk error
        pop     es
        stc
        ret
.nomore:
        push    cs
        pop     es
        mov     ax, 18
        stc
.x:     ret
