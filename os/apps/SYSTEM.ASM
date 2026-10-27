; =====================================================================
;  SYSTEM.RUN - Usage: memory, disks, the clock, devices, GPIB, about
;  python3 mkrun.py apps/SYSTEM.ASM apps/SYSTEM.RUN
;
;  CODE-U in the Executive, as GRiD's "Usage CODE-U  Show memory and
;  device usage".  Topics on the left, details on the right.  Return sets
;  the clock (Clock), scans the GPIB bus (GPIB), or takes the next font,
;  saver delay or size of the temporary disk M:, or (Settings, started
;  from the ROM) goes back to the ROM's own settings.  Space turns the
;  start-up picture (Display) or the saver's tidying on or off.
;
;  The settings (LODE.INI): started from a floppy, the one on it.  Started
;  from the ROM, R:\LODE.INI holds Lodestone's own, which are also the
;  built-in defaults, and the changes made here go in C:\LODE.INI (A:\
;  without the hard disk), read over them: INT 21h 3305h's DH says which
;  (KROM.INC).  Only what differs from the defaults is written.
; =====================================================================
%include "UIAPI.INC"
RUN_API equ 4                           ; (UI_SAVER's tidying)
        org     RUN_ORG

TOP_Y   equ 32                          ; first topic / detail line
NTOPIC  equ 11
INI_MAX equ 1024                        ; LODE.INI: the most we rewrite
PCOL    equ 18                          ; the details panel: from this column
LCOL    equ 20                          ; labels
VCOL    equ 46                          ; values
RCOL    equ 58                          ; memory sizes end here

start:  mov     si, redraw
        call    UI_SETREDRAW
        mov     dx, dta                 ; our own DTA (the loader puts the
                                        ;  Executive's back)
        mov     ah, 1Ah
        int     21h
        mov     ax, 3305h               ; fonts: on the disk Lodestone started
        int     21h                     ;  from (DL = 1: A:); the settings
        add     dl, 'A' - 1             ;  saved where DH says (from the ROM
        mov     [s_fntall], dl          ;  with none yet: C:, else A:)
        mov     [boot_l], dl
        mov     al, dh
        add     al, 'A' - 1
        or      dh, dh
        jnz     .si
        mov     al, dl
        cmp     al, 'R'
        jne     .si
        mov     ax, 4408h               ; (C: there?)
        mov     bl, 3
        int     21h
        mov     al, 'C'
        jnc     .si
        mov     al, 'A'
.si:    mov     [s_ini], al
        mov     [read_l], dh
        call    find_gpib
        call    redraw
.loop:  cmp     byte [quit], 0
        jne     .quit
        call    UI_EVENT
        cmp     ax, EV_CLICK
        je      .click
        mov     si, keys
        call    UI_DISPATCH
        jnc     .loop
        mov     bx, topics
        call    UI_LVKEY
        jmp     .loop
.click: cmp     cx, SCR_BAND_Y
        jb      .list
        call    k_help
        jmp     .loop
.list:  cmp     bx, (PCOL - 2) * 8      ; (the details aren't the list)
        jae     .loop
        mov     bx, topics
        call    UI_LVCLICK
        jc      .loop
        cmp     al, 1
        jne     .loop
        call    k_enter
        jmp     .loop
.quit:  xor     ax, ax
        ret

redraw: mov     si, s_title
        call    UI_SCREEN
        mov     ax, PCOL * 8 - 5        ; the rule between topics and details
        mov     dx, 24
        mov     cx, SCR_BAND_Y - 32
        call    UI_VLINE
        mov     bx, topics
        call    UI_LVDRAW
        jmp     show_topic              ; (the band too: UI_SCREEN cleared it,
                                        ;  and at the start it is still the
                                        ;  Executive's)

topic_row:                              ; AX = topic, DX = y, CL = mask
        call    topic_name
        mov     ah, cl
        mov     bx, 2
        jmp     UI_PUTS

topic_name:                             ; AX = topic -> SI
        mov     bx, ax
        shl     bx, 1
        mov     si, [topic_names+bx]
        ret

; the selected topic's details and band
show_topic:
        mov     bx, [topics+LV_SEL]
        shl     bx, 1
        mov     di, [topic_band+bx]
        mov     si, s_band1
        call    UI_BAND
topic_details:
        mov     dx, 24                  ; clear the panel
        mov     cx, SCR_BAND_Y - 32
        mov     bx, PCOL
        mov     bp, 80 - PCOL
        xor     al, al
        call    UI_FILL
        mov     word [py], TOP_Y
        mov     bx, [topics+LV_SEL]
        shl     bx, 1
        jmp     [topic_draw+bx]

; ---------------------------------------------------------------------
;  details: label SI, value in vbuf (built at DI) -> the next line
; ---------------------------------------------------------------------
vstart: mov     di, vbuf
        ret

pline:  mov     bx, VCOL                ; SI = label, vbuf = value (ended at DI)
pline_at:
        mov     byte [di], 0
        mov     dx, [py]
        push    bx
        mov     bx, LCOL
        xor     ah, ah
        call    UI_PUTS
        pop     bx
        mov     si, vbuf
        call    UI_PUTS
        add     word [py], 16
        ret

pline_r:                                ; the same, the value right-aligned
        mov     bx, RCOL
        sub     bx, di
        add     bx, vbuf
        jmp     pline_at

ptext:  mov     dx, [py]                ; SI = a line of its own
        mov     bx, LCOL
        xor     ah, ah
        call    UI_PUTS
        add     word [py], 16
        ret

pgap:   add     word [py], 8
        ret

; an EMS manager on INT 67h ('EMMXXXX0' at its segment:000Ah; Lodestone's
; own when there is EMS)?  CF if not
ems_mgr:
        push    es
        mov     ax, 3567h
        int     21h
        mov     di, 0Ah
        mov     si, s_emm
        mov     cx, 8
        repe    cmpsb
        pop     es
        je      .x
        stc
.x:     ret

; AX = paragraphs, SI = the label -> "570.6 KB" on the next line
kb_line:
        push    si
        call    vstart
        call    sb_kb
        pop     si
        jmp     pline_r

; AX = paragraphs -> "570.6 KB" at DI
sb_kb:  push    ax
        push    bx
        push    cx
        push    dx
        mov     bx, 10
        mul     bx                      ; DX:AX = paragraphs * 10
        add     ax, 32
        adc     dx, 0
        mov     cx, 6
.s:     shr     dx, 1
        rcr     ax, 1
        loop    .s                      ; / 64 = tenths of a KB
        xor     dx, dx
        div     bx
        call    UI_SBU16
        mov     al, '.'
        stosb
        mov     al, dl
        add     al, '0'
        stosb
        mov     si, s_kb
        call    UI_SBSTR
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

; ---------------------------------------------------------------------
;  Memory: the MCB chain, read the way the kernel keeps it
; ---------------------------------------------------------------------
t_memory:
        call    UI_VERSION              ; CX = the UI block's own size, SI =
        mov     [ui_base], cx           ;  what it keeps while DOS programs run
        mov     [ui_keep], si
        mov     ah, 52h                 ; the first MCB is at [ES:BX-2]
        int     21h
        mov     ax, [es:bx-2]
        push    cs
        pop     es
        mov     [first], ax
        sub     ax, 60h                 ; the kernel: from 0060:0000
        mov     [m_kernel], ax
        mov     ah, 62h
        int     21h
        mov     [psp], bx
        xor     ax, ax
        mov     [m_ui], ax
        mov     [m_cache], ax
        mov     [m_md], ax
        mov     [m_exec], ax
        mov     [m_other], ax
        mov     [m_best], ax
        mov     [m_run], ax
        mov     byte [m_inrun], 0
        mov     byte [m_prevui], 0
        mov     ax, [first]
.walk:  push    ds
        mov     ds, ax
        mov     dl, [0]                 ; 'M' or 'Z'
        mov     cx, [1]                 ; owner
        mov     bx, [3]                 ; size
        mov     si, [8]                 ; name
        pop     ds
        cmp     dl, 'M'
        je      .ok
        cmp     dl, 'Z'
        jne     .done                   ; (damaged: stop)
.ok:    or      cx, cx
        jnz     .used
        cmp     byte [m_inrun], 0       ; free: one run with the free ones
        je      .first                  ;  just before it
        add     [m_run], bx
        inc     word [m_run]
        jmp     .next
.first: mov     [m_run], bx
        mov     byte [m_inrun], 1
        mov     cl, [m_prevui]
        mov     [m_runadj], cl
        jmp     .next
.used:  call    .close
        mov     byte [m_prevui], 0
        cmp     cx, 8
        jne     .notsys
        cmp     si, 'UI'
        jne     .notui
        mov     [m_ui], bx
        mov     byte [m_prevui], 1
        jmp     .next
.notui: cmp     si, 'SC'
        jne     .notsc
        mov     [m_cache], bx
        jmp     .next
.notsc: cmp     si, 'MD'                ; M:'s resident part (and its MCB)
        jne     .other
        inc     bx
        mov     [m_md], bx
        dec     bx
        jmp     .next
.notsys:
        cmp     cx, [psp]
        jne     .other
        add     [m_exec], bx
        inc     word [m_exec]
        jmp     .next
.other: add     [m_other], bx
        inc     word [m_other]
.next:  cmp     dl, 'Z'
        je      .done
        add     ax, bx
        inc     ax
        jmp     .walk
.done:  call    .close
        ; the lines
        call    ems_mgr
        sbb     al, al
        mov     [m_noems], al
        int     12h
        mov     cx, 6
        shl     ax, cl
        mov     si, l_conv
        call    kb_line
        mov     ax, [m_kernel]
        mov     si, l_kernel
        cmp     byte [m_noems], 0
        jne     .kd
        mov     si, l_kernel_e          ; (Lodestone's EMS manager is in it)
.kd:    call    kb_line
        mov     ax, [m_md]              ; M:'s resident part: split off the
        or      ax, ax                  ;  environment's spare bytes
        jz      .nomd
        mov     si, l_mdres
        call    kb_line
.nomd:  mov     ax, [ui_base]
        add     ax, [m_exec]
        inc     ax                      ; (its MCB)
        mov     si, l_exec
        call    kb_line
        mov     ax, [m_ui]
        sub     ax, [ui_base]
        mov     si, l_this
        call    kb_line
        call    vstart
        mov     ax, [m_cache]
        or      ax, ax                  ; no "SC" block, Lodestone's EMS: the
        jnz     .ckb                    ;  cache is in two of its pages
        cmp     byte [m_noems], 0
        jne     .ckb
        mov     si, s_cems
        call    UI_SBSTR
        jmp     short .cl
.ckb:   call    sb_kb
.cl:    mov     si, l_cache
        call    pline_r
        cmp     word [m_other], 0
        je      .noother
        mov     ax, [m_other]
        mov     si, l_other
        call    kb_line
.noother:
        mov     ax, [m_best]
        mov     si, l_free
        call    kb_line
        call    pgap
        cmp     byte [m_noems], 0       ; expanded memory: the EMS manager's
        jne     .bios                   ;  pages, and how many are free
        mov     ah, 42h
        int     67h
        or      ah, ah
        jnz     .bios
        push    bx
        xchg    ax, dx
        mov     si, l_ems
        call    .pages
        pop     ax
        mov     si, l_dfree
        call    .pages
        jmp     short .noems
.pages: shl     ax, 4                   ; AX pages, on a line labelled SI
.kb:    push    si                      ; AX KB, on a line labelled SI
        call    vstart
        call    UI_SBU16
        mov     si, s_kb
        call    UI_SBSTR
        pop     si
        jmp     pline_r
.bios:  mov     ax, 0E440h              ; else expanded / extended as the GRiD
        int     15h                     ;  BIOS has them
        jc      .noems
        jcxz    .noems
        xchg    ax, cx
        mov     si, l_ems
        call    .kb
.noems: mov     ax, 0E441h
        int     15h
        jc      .noext
        jcxz    .noext
        xchg    ax, cx
        mov     si, l_ext
        jmp     .kb
.noext: ret
; the end of a run of free blocks: as one block once this program has
; gone and a DOS program starts (the UI block shrinks into the run if it
; follows it straight on)
.close: cmp     byte [m_inrun], 0
        je      .cx
        mov     byte [m_inrun], 0
        push    ax
        mov     ax, [m_run]
        cmp     byte [m_runadj], 0
        je      .cmp
        add     ax, [m_ui]              ; (this program goes, and the
        sub     ax, [ui_keep]           ;  Executive lends its directory)
.cmp:   cmp     ax, [m_best]
        jbe     .cp
        mov     [m_best], ax
.cp:    pop     ax
.cx:    ret

; ---------------------------------------------------------------------
;  Disks: A: (and B: when there is a second drive, C: when there is the
;  hard disk, M: when there is the temporary disk)
; ---------------------------------------------------------------------
t_disks:
        mov     byte [drv], 0
.d:     call    disk_lines
        inc     byte [drv]
        int     11h
        rol     al, 2
        and     al, 3                   ; drives - 1
        cmp     [drv], al
        ja      .c
        call    pgap
        jmp     .d
.c:     mov     bl, 3                   ; C:, then M:, if they are there
        call    .one
        mov     bl, MD_DRV + 1
.one:   call    has_drv
        jc      .x
        dec     bx
        mov     [drv], bl
        call    pgap
        jmp     disk_lines
.x:     ret

; is there a C: (Lodestone's hard disk)?  CF if not.  has_drv: drive BL (1 =
; A:) there?  (IOCTL "removable?" says no such drive: CF.)  BX kept
has_c:  mov     bl, 3
has_drv:
        mov     ax, 4408h
        int     21h
        ret

disk_lines:
        mov     al, [drv]
        add     al, 'A'
        mov     [s_drive+6], al
        mov     [s_vol], al
        call    UI_CRITERR              ; (forget any earlier one)
        mov     dl, [drv]
        inc     dl
        mov     ah, 36h
        int     21h
        cmp     ax, 0FFFFh
        jne     .ok
        call    vstart
        mov     ax, 83                  ; what INT 24h said
        call    UI_SBERR
        mov     si, s_drive
        jmp     pline
.ok:    mov     [d_spc], ax
        mov     [d_free], bx
        mov     [d_bps], cx
        mov     [d_total], dx
        call    vstart                  ; "Drive A:   label LODESTONE"
        push    di
        mov     dx, s_vol
        mov     cx, 08h
        mov     ah, 4Eh
        int     21h
        pop     di
        jc      .nolab
        test    byte [dta+21], 08h
        jz      .nolab
        mov     si, dta + 30
.lab:   lodsb
        or      al, al
        jz      .labx
        cmp     al, '.'
        je      .lab                    ; (a label's "extension" belongs to it)
        stosb
        jmp     .lab
.labx:  jmp     .lab2
.nolab: mov     si, s_nolabel
        call    UI_SBSTR
.lab2:  mov     si, s_drive
        call    pline
        mov     ax, [d_total]           ; size
        mov     si, l_dsize
        call    clus_line
        mov     ax, [d_free]            ; free
        mov     si, l_dfree
        call    clus_line
        mov     ax, [d_total]           ; in use
        sub     ax, [d_free]
        mov     si, l_dused
        ; (on into clus_line)

; AX clusters, SI = the label -> "1423 KB" on the next line
clus_line:
        push    si
        call    vstart
        mul     word [d_spc]            ; DX:AX = sectors
        mov     cx, [d_bps]
        shr     cx, 9                   ; 512-byte units per sector
        jcxz    .h
.m:     dec     cx
        jz      .h
        shl     ax, 1
        rcl     dx, 1
        jmp     .m
.h:     shr     dx, 1                   ; two of them make a KB
        rcr     ax, 1
        mov     cx, dx
        call    UI_SBU32
        mov     si, s_kb
        call    UI_SBSTR
        pop     si
        jmp     pline

; ---------------------------------------------------------------------
;  Clock
; ---------------------------------------------------------------------
t_clock:
        call    vstart
        mov     ah, 2Ah
        int     21h                     ; CX year, DH month, DL day, AL weekday
        push    cx
        push    dx
        xor     ah, ah
        mov     bx, ax
        shl     bx, 1
        mov     si, [day_names+bx]
        call    UI_SBSTR
        mov     ax, ', '
        stosw
        pop     dx
        push    dx
        mov     al, dl
        xor     ah, ah
        call    UI_SBU16
        mov     al, ' '
        stosb
        pop     dx
        mov     bl, dh
        xor     bh, bh
        dec     bx
        shl     bx, 1
        mov     si, [month_names+bx]
        call    UI_SBSTR
        mov     al, ' '
        stosb
        pop     ax
        call    UI_SBU16
        mov     si, l_date
        call    pline
        call    vstart
        call    now_time
        call    UI_SBTIME
        mov     si, l_time
        call    pline
        call    pgap
        mov     si, s_setclock
        jmp     ptext

now_time:                               ; -> AX = DOS-style time
        mov     ah, 2Ch
        int     21h                     ; CH hours, CL minutes
        mov     al, ch
        xor     ah, ah
        shl     ax, 11
        xor     ch, ch
        shl     cx, 5
        or      ax, cx
        ret

; Return on Clock: a form with the date and time as text
set_clock:
        mov     di, f_date              ; "5-Oct-2026"
        mov     ah, 2Ah
        int     21h
        push    cx
        push    dx
        mov     al, dl
        xor     ah, ah
        call    UI_SBU16
        mov     al, '-'
        stosb
        pop     dx
        mov     bl, dh
        xor     bh, bh
        dec     bx
        imul    si, bx, 3
        add     si, months3
        movsw
        movsb
        or      word [di-2], 2020h      ; ("Oct")
        mov     al, '-'
        stosb
        pop     ax
        call    UI_SBU16
        mov     byte [di], 0
        mov     di, f_time
        call    now_time
        call    UI_SBTIME
        mov     byte [di], 0
.form:  mov     si, clock_form
        call    UI_FORM
        jc      .x
        mov     si, f_time              ; both read before either is set, so
        call    parse_time              ;  a bad time leaves the date alone
        jc      .bad_t
        mov     [new_time], cx
        mov     si, f_date
        call    parse_date
        jc      .bad_d
        mov     ah, 2Bh                 ; (the kernel checks the day exists)
        int     21h
        or      al, al
        jnz     .bad_d
        mov     cx, [new_time]          ; (parse_time checked its ranges)
        xor     dx, dx
        mov     ah, 2Dh
        int     21h
.x:     jmp     redraw                  ; (the title bar's clock too)
.bad_d: mov     si, s_baddate
        jmp     .bad
.bad_t: mov     si, s_badtime
.bad:   call    UI_MSG
        jmp     .form

; SI = text: digits -> AX, CF if there were none
getnum: xor     ax, ax                  ; (at most 4 digits: CF for more,
        xor     cx, cx                  ;  which would wrap past 65535)
.l:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .e
        cmp     cx, 4
        jae     .bad
        inc     si
        inc     cx
        xor     bh, bh
        push    bx
        mov     bx, 10
        mul     bx
        pop     bx
        add     ax, bx
        jmp     .l
.e:     cmp     cx, 1                   ; CF if none
        ret
.bad:   stc
        ret

; past anything that isn't a letter or a digit (not past the NUL)
skipsep:
        mov     al, [si]
        or      al, al
        jz      .x
        cmp     al, '0'
        jb      .s
        cmp     al, '9'
        jbe     .x
        and     al, 0DFh
        cmp     al, 'A'
        jb      .s
        cmp     al, 'Z'
        jbe     .x
.s:     inc     si
        jmp     skipsep
.x:     ret

; "5-Oct-2026", "5/10/26", "5 october 2026" -> CX year, DH month, DL day
parse_date:
        call    skipsep
        call    getnum
        jc      .bad
        cmp     ax, 31
        ja      .bad
        mov     [pd_day], al
        call    skipsep
        mov     al, [si]
        cmp     al, '9'
        ja      .name
        call    getnum
        jc      .bad
        cmp     ax, 12
        ja      .bad
        mov     [pd_mon], al
        jmp     .year
.name:  mov     bx, months3             ; the first three letters
        mov     byte [pd_mon], 1
.n:     mov     ax, [si]
        and     ax, 0DFDFh
        cmp     ax, [bx]
        jne     .nn
        mov     al, [si+2]
        and     al, 0DFh
        cmp     al, [bx+2]
        je      .found
.nn:    add     bx, 3
        inc     byte [pd_mon]
        cmp     byte [pd_mon], 12
        jbe     .n
        jmp     .bad
.found: mov     bl, [pd_mon]            ; more letters must go on with
        xor     bh, bh                  ;  the month's name ("Sept", "october")
        dec     bx
        shl     bx, 1
        mov     bx, [month_names+bx]
        add     bx, 3
        add     si, 3
.r:     mov     al, [si]
        and     al, 0DFh
        cmp     al, 'A'
        jb      .year
        cmp     al, 'Z'
        ja      .year
        mov     ah, [bx]
        and     ah, 0DFh
        cmp     al, ah
        jne     .bad
        inc     si
        inc     bx
        jmp     .r
.year:  call    skipsep
        call    getnum
        jc      .bad
        cmp     ax, 100
        jae     .y4
        add     ax, 1900
        cmp     ax, 1980
        jae     .y4
        add     ax, 100
.y4:    mov     cx, ax
        call    skipsep                 ; nothing may follow
        cmp     byte [si], 0
        jne     .bad
        mov     dh, [pd_mon]
        mov     dl, [pd_day]
        clc
        ret
.bad:   stc
        ret

; "9:41 pm", "21:41", "9 pm" -> CH hours, CL minutes
parse_time:
        call    skipsep
        call    getnum
        jc      .bad
        cmp     ax, 23
        ja      .bad
        mov     [pd_day], al            ; (hours)
        mov     byte [pd_mon], 0        ; (minutes)
        call    skipsep
        mov     al, [si]
        or      al, al
        jz      .done                   ; ("21": on the hour)
        cmp     al, '9'
        ja      .ampm
        call    getnum
        jc      .bad
        cmp     ax, 59
        ja      .bad
        mov     [pd_mon], al
        call    skipsep
.ampm:  mov     al, [si]
        and     al, 0DFh
        mov     ah, [pd_day]
        cmp     al, 'A'
        je      .ap
        cmp     al, 'P'
        jne     .end                    ; (a 24-hour time)
.ap:    or      ah, ah                  ; am/pm: hours 1-12 only
        jz      .bad
        cmp     ah, 12
        ja      .bad
        cmp     al, 'P'
        je      .pm
        cmp     ah, 12                  ; 12 am = 0
        jne     .sfx
        xor     ah, ah
        jmp     .sfx
.pm:    cmp     ah, 12                  ; 1 pm .. 11 pm (12 pm = 12)
        je      .sfx
        add     ah, 12
.sfx:   mov     [pd_day], ah
        inc     si                      ; past the a/p, and an m after it
        mov     al, [si]
        and     al, 0DFh
        cmp     al, 'M'
        jne     .end
        inc     si
.end:   call    skipsep                 ; nothing may follow
        cmp     byte [si], 0
        jne     .bad
.done:  mov     ch, [pd_day]
        mov     cl, [pd_mon]
        clc
        ret
.bad:   stc
        ret

; ---------------------------------------------------------------------
;  Devices
; ---------------------------------------------------------------------
t_devices:
        call    vstart
        mov     si, s_286
        call    UI_SBSTR
        mov     si, l_cpu
        call    pline
        call    vstart
        call    fpu_detect              ; 0 none, 1 80287, 2 287XL
        mov     si, s_none
        dec     al
        js      .fpu
        mov     si, s_287
.fpu:   call    UI_SBSTR
        dec     al
        jnz     .nxl
        mov     si, s_xl
        call    UI_SBSTR
.nxl:
        mov     si, l_fpu
        call    pline
        call    vstart                  ; BIOS date at F000:FFF5
        mov     si, s_grid
        call    UI_SBSTR
        push    ds
        mov     ax, 0F000h
        mov     ds, ax
        mov     si, 0FFF5h
        mov     cx, 8
        rep     movsb
        pop     ds
        mov     si, l_bios
        call    pline
        call    vstart                  ; the panel (GRiD port 7F8h)
        mov     dx, 7F8h
        in      al, dx
        and     al, 0Fh
        mov     si, s_plasma
        cmp     al, 0Dh
        je      .p
        mov     si, s_lcd
        cmp     al, 0Fh
        je      .p
        mov     si, s_panel
.p:     call    UI_SBSTR
        mov     si, l_display
        call    pline
        call    vstart                  ; the mouse (from the core)
        call    UI_VERSION
        mov     si, s_none
        or      dx, dx
        jz      .m
        mov     si, s_mouse1
        cmp     dx, 3F8h
        je      .m
        mov     si, s_mouse2
.m:     call    UI_SBSTR
        mov     si, l_mouse
        call    pline
        mov     word [port_n], 0        ; serial ports, from the BIOS data area
        call    vstart
        mov     bx, 0
.com:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [400h+bx]
        pop     ds
        or      ax, ax
        jz      .nc
        push    ax
        mov     si, s_comma
        cmp     word [port_n], 0
        je      .c1
        call    UI_SBSTR
.c1:    mov     si, s_com
        call    UI_SBSTR
        mov     ax, bx
        shr     ax, 1
        inc     ax
        call    UI_SBU16
        mov     al, ' '
        stosb
        pop     ax
        call    UI_SBHEX4
        mov     al, 'h'
        stosb
        inc     word [port_n]
.nc:    add     bx, 2
        cmp     bx, 8
        jb      .com
        cmp     word [port_n], 0
        jne     .cs
        mov     si, s_none
        call    UI_SBSTR
.cs:    mov     si, l_serial
        call    pline
        call    vstart                  ; LPT1
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [408h]
        pop     ds
        or      ax, ax
        jnz     .lpt
        mov     si, s_none
        call    UI_SBSTR
        jmp     .lx
.lpt:   push    ax
        mov     si, s_lpt
        call    UI_SBSTR
        pop     ax
        call    UI_SBHEX4
        mov     al, 'h'
        stosb
.lx:    mov     si, l_printer
        call    pline
        call    vstart                  ; what PrtSc does (the kernel's)
        call    prn_get
        jz      .pf
        push    si
        mov     si, s_prtwith
        call    UI_SBSTR
        pop     si
        jmp     short .pr
.pf:    mov     si, s_prtfile
.pr:    call    UI_SBSTR
        mov     si, l_prtsc
        call    pline
        call    vstart                  ; floppy drives, from CMOS 10h
        mov     al, 10h
        pushf
        cli                             ; (index and data as one)
        out     70h, al
        in      al, 71h
        popf
        mov     [cmos10], al
        shr     al, 4
        call    drive_kind
        mov     si, s_and
        mov     al, [cmos10]
        and     al, 0Fh
        jz      .one
        call    UI_SBSTR
        mov     byte [s_b+0], 'B'
        call    drive_kind
.one:   mov     si, l_floppy
        call    pline
        call    vstart                  ; the hard disk: the name it gives
        call    has_c                   ;  itself
        jc      .nh
        call    hd_name
        jnc     .hn
.nh:    mov     si, s_none
        call    UI_SBSTR
.hn:    mov     si, l_hdisk
        mov     bx, 80                  ; (a long name: to the right edge)
        sub     bx, di
        add     bx, vbuf
        cmp     bx, VCOL
        jbe     .hr
        mov     bx, VCOL
.hr:    jmp     pline_at

; the hard disk's own name (IDENTIFY, words 27-46) at DI.  CF if it doesn't
; answer within a second
hd_name:
        mov     dx, 1F6h
        mov     al, 0A0h                ; drive 0
        out     dx, al
        inc     dx
        mov     al, 0ECh                ; IDENTIFY
        out     dx, al
        call    UI_TICK
        mov     bx, ax
.w:     in      al, dx
        test    al, 80h
        jnz     .b
        test    al, 09h                 ; DRQ, or ERR
        jnz     .r
.b:     call    UI_TICK
        sub     ax, bx
        cmp     ax, 18
        jb      .w
.no:    stc
        ret
.r:     test    al, 01h
        jnz     .no
        push    di
        mov     di, fbuf
        mov     cx, 256
        mov     dx, 1F0h
        rep     insw
        pop     di
        mov     si, fbuf + 27 * 2       ; 40 characters, each pair swapped
        mov     cx, 20
.n:     lodsw
        xchg    al, ah
        stosw
        loop    .n
.t:     cmp     di, vbuf                ; trailing blanks off
        jbe     .x
        cmp     byte [di-1], ' '
        ja      .x
        dec     di
        jmp     .t
.x:     clc
        ret

; AL = CMOS drive type -> "A: 1.44 MB" at DI (first A:, then B:)
drive_kind:
        push    ax
        mov     si, s_b
        call    UI_SBSTR
        mov     byte [s_b], 'A'
        pop     ax
        xor     ah, ah
        cmp     al, 5
        jb      .k
        xor     al, al
.k:     mov     bx, ax
        shl     bx, 1
        mov     si, [drive_types+bx]
        jmp     UI_SBSTR

; ---------------------------------------------------------------------
;  GPIB: the GRIDGPIB API (built into Lodestone on INT 60h)
; ---------------------------------------------------------------------
find_gpib:                              ; -> [gp_vec] = 0 or the vector
        mov     word [gp_vec+2], 0
        mov     bl, 60h
.v:     push    ds
        xor     ax, ax
        mov     ds, ax
        xor     bh, bh
        shl     bx, 2
        lds     si, [bx]
        shr     bx, 2
        mov     ax, ds
        or      ax, si
        jz      .n
        cmp     word [si+2], 'GR'
        jne     .n
        cmp     word [si+4], 'ID'
        jne     .n
        cmp     word [si+6], 'GP'
        jne     .n
        cmp     word [si+8], 'IB'
        jne     .n
        mov     ax, ds
        pop     ds
        mov     [gp_vec], si
        mov     [gp_vec+2], ax
        mov     [gp_int], bl
        ret
.n:     pop     ds
        inc     bl
        cmp     bl, 66h
        jbe     .v
        ret

gpib:   pushf                           ; AH = function (as INT 6xh)
        call    far [gp_vec]
        ret

t_gpib: call    vstart
        cmp     word [gp_vec+2], 0
        jne     .have
        mov     si, s_nogpib
        call    UI_SBSTR
        mov     si, l_driver
        jmp     pline
.have:  mov     ah, 0                   ; present: CX version, DH INT, DL address
        call    gpib
        push    dx
        push    cx
        mov     si, s_gpver
        call    UI_SBSTR
        pop     ax
        push    ax
        mov     al, ah
        xor     ah, ah
        call    UI_SBU16
        mov     al, '.'
        stosb
        pop     ax
        xor     ah, ah
        mov     cx, ax
        mov     al, cl
        shr     al, 4
        add     al, '0'
        stosb
        mov     al, cl
        and     al, 0Fh
        add     al, '0'
        stosb
        mov     si, s_onint
        call    UI_SBSTR
        mov     al, [gp_int]
        xor     ah, ah
        call    UI_SBHEX4
        sub     di, 2                   ; ("0060" -> "60")
        mov     ax, [di]
        mov     [di-2], ax
        mov     byte [di], 'h'
        inc     di
        mov     si, l_driver
        call    pline
        call    vstart
        pop     dx
        mov     al, dl
        xor     ah, ah
        mov     [gp_my], al
        call    UI_SBU16
        mov     si, l_myaddr
        call    pline
        mov     ax, 0EFFh               ; SRQ on IRQ 5 (driver 1.21: AH=0Eh,
        call    gpib                    ;  just asking), or polled
        jc      .nq
        push    ax
        call    vstart
        pop     ax
        mov     si, s_srqirq
        or      ax, ax
        jnz     .sq
        mov     si, s_srqpoll
.sq:    call    UI_SBSTR
        mov     si, l_srq
        call    pline
.nq:    call    pgap
        cmp     byte [gp_scanned], 0
        je      .hint
        call    vstart                  ; what the last scan found
        mov     si, s_none
        cmp     byte [gp_nfound], 0
        je      .none
        xor     bx, bx
.f:     cmp     bl, [gp_nfound]
        jae     .fx
        cmp     di, vbuf + 80 - VCOL - 4        ; (room for ", nn"?)
        ja      .fx
        or      bx, bx
        jz      .f1
        mov     ax, ', '
        stosw
.f1:    mov     al, [gp_found+bx]
        xor     ah, ah
        call    UI_SBU16
        inc     bx
        jmp     .f
.none:  call    UI_SBSTR
.fx:    mov     si, l_found
        call    pline
        call    pgap
.hint:  mov     si, s_scanhint
        jmp     ptext

; Return on GPIB: serial-poll every address; who answers is there
scan_gpib:
        cmp     word [gp_vec+2], 0
        je      .x
        mov     si, s_scanask
        call    UI_ASK
        jc      .x
        mov     si, s_scanning
        mov     di, 0
        call    UI_BAND
        mov     byte [gp_nfound], 0
        xor     bx, bx
.a:     cmp     bl, [gp_my]
        je      .n
        push    bx
        mov     ah, 5                   ; serial poll BL
        call    gpib
        pop     bx
        jc      .n
        mov     al, [gp_nfound]
        xor     ah, ah
        mov     si, ax
        mov     [gp_found+si], bl
        inc     byte [gp_nfound]
.n:     inc     bl
        cmp     bl, 30
        jbe     .a
        mov     ah, 9                   ; GTL to all (drop REN): local again
        mov     bl, 0FFh
        call    gpib
        mov     byte [gp_scanned], 1
        jmp     show_topic
.x:     ret

; ---------------------------------------------------------------------
;  About
; ---------------------------------------------------------------------
t_about:
        call    UI_VERSION              ; BX = Lodestone version
        mov     di, vbuf
        mov     si, s_lodestone
        call    UI_SBSTR
        mov     al, bh
        xor     ah, ah
        call    UI_SBU16
        mov     al, '.'
        stosb
        mov     al, bl
        shr     al, 4
        add     al, '0'
        stosb
        and     bl, 0Fh
        jz      .np
        mov     al, '.'
        stosb
        mov     al, bl
        xor     ah, ah
        call    UI_SBU16
.np:    mov     byte [di], 0
        mov     si, vbuf
        call    ptext
        mov     si, s_about1
        call    ptext
        call    pgap
        call    vstart
        mov     ah, 30h
        int     21h
        push    ax
        xor     ah, ah
        call    UI_SBU16
        mov     al, '.'
        stosb
        pop     ax
        mov     al, ah
        xor     ah, ah
        call    UI_SBU16
        mov     si, s_compat
        call    UI_SBSTR
        mov     si, l_dos
        call    pline
        call    vstart
        call    UI_VERSION
        call    UI_SBU16
        mov     si, l_api
        call    pline
        call    pgap
        mov     si, s_about2
        call    ptext
        mov     si, s_about3
        jmp     ptext

; ---------------------------------------------------------------------
;  Display: the screen font.  GRiD's is built into the core (and copied
;  here, to switch back to); others are .FNT files in the disk's root:
;  FONT_BYTES of 8x16 glyphs.  The choice goes in \LODE.INI as FONT=,
;  which the core reads at start-up.  And the start-up picture (the
;  kernel's, KSPLASH.INC): Space turns it off or on, SPLASH=0 in LODE.INI
;  when off.
; ---------------------------------------------------------------------
t_display:
        call    splash_get              ; (LODE.INI read the first time)
        call    vstart
        xor     al, al
        call    UI_FONT                 ; SI = its name ("" = built in)
        cmp     byte [si], 0
        jne     .n
        mov     si, s_gridfont
.n:     call    UI_SBSTR
        mov     si, l_font
        call    pline
        call    vstart                  ; the start-up picture
        mov     si, s_yes
        cmp     byte [splash_off], 0
        je      .p
        mov     si, s_no
.p:     call    UI_SBSTR
        mov     si, l_splash
        call    pline
        call    pgap
        mov     si, l_fonts
        call    ptext
        call    vstart                  ; GRiD's, and every .FNT here
        mov     si, s_gridfont
        call    UI_SBSTR
        mov     dx, s_fntall
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        jc      .d
.f:     cmp     di, vbuf + 80 - LCOL - 2 - 14   ; (room for ", NAME.EXT"?)
        ja      .d
        mov     ax, ', '
        stosw
        mov     si, dta + 30
        call    UI_SBSTR
        mov     ah, 4Fh
        int     21h
        jnc     .f
.d:     mov     byte [di], 0
        mov     si, vbuf
        mov     dx, [py]
        mov     bx, LCOL + 2
        xor     ah, ah
        call    UI_PUTS
        add     word [py], 16
        call    pgap
        mov     si, s_sample1
        call    ptext
        mov     si, s_sample2
        jmp     ptext

; Return on Display: the next font (the files in the order the disk has
; them, then GRiD's again), saved in LODE.INI, and the screen redrawn
next_font:
        xor     al, al
        call    UI_FONT
        mov     di, cur_font
        call    UI_SBSTR
        mov     byte [di], 0
        mov     byte [past], 0          ; (past the one in use yet?)
        cmp     byte [cur_font], 0
        jne     .find
        mov     byte [past], 1          ; GRiD's now: the first file is next
.find:  mov     dx, s_fntall
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
.l:     jc      .grid                   ; none after it: GRiD's again
        cmp     byte [past], 0
        je      .cmp
        call    load_fnt                ; this one, if it is a font
        jnc     .file
        jmp     .nx
.cmp:   mov     si, dta + 30
        mov     di, cur_font
        call    same_name
        jne     .nx
        mov     byte [past], 1
.nx:    mov     ah, 4Fh
        int     21h
        jmp     .l
.grid:  mov     si, grid_font
        mov     di, s_empty
        jmp     .set
.file:  mov     si, fbuf
        mov     di, dta + 30
.set:   mov     al, 1
        call    UI_FONT
        call    save_ini
        jmp     redraw

;  Screen saver: how long the Executive waits, idle, before the saver
;  (DEFRAG on each disk, then the dark clock).  Return: the next choice,
;  saved in LODE.INI as SAVER= (none for the usual 5 minutes).  Space:
;  whether it tidies the disks first (TIDY=0 when not).
; ---------------------------------------------------------------------
t_saver:
        call    vstart
        call    saver_text
        mov     si, l_saver
        call    pline
        call    vstart                  ; tidies the disks first?
        xor     al, al
        call    UI_SAVER
        mov     si, s_yes
        or      ah, ah
        jz      .t
        mov     si, s_no
.t:     call    UI_SBSTR
        mov     si, l_tidy
        call    pline
        call    pgap
        mov     si, s_svchoices
        call    ptext
        mov     si, s_svspace
        call    ptext
        call    pgap
        mov     si, s_svwhat1
        call    ptext
        mov     si, s_svwhat2
        jmp     ptext

; "5 minutes" / "1 minute" / "never" at DI
saver_text:
        xor     al, al
        call    UI_SAVER
        mov     si, s_never
        or      al, al
        jz      .s
        xor     ah, ah
        push    ax
        call    UI_SBU16
        pop     ax
        mov     si, s_minutes
        cmp     al, 1
        jne     .s
        mov     si, s_minute
.s:     jmp     UI_SBSTR

next_saver:
        xor     al, al
        call    UI_SAVER                ; AL = the delay now
        mov     si, sv_steps
        mov     cx, NSTEPS
.f:     cmp     al, [si]
        je      .hit
        inc     si
        loop    .f
        mov     si, sv_steps - 1        ; (not one of them: the first)
.hit:   inc     si                      ; the next one, round
        cmp     si, sv_steps + NSTEPS
        jb      .n
        mov     si, sv_steps
.n:     mov     bl, [si]
        mov     al, 1
        call    UI_SAVER
        call    save_ini
        jmp     redraw

sv_steps    db 1, 2, 5, 10, 15, 30, 0   ; minutes (0: never)

NSTEPS      equ $ - sv_steps

; the printer driver PrtSc uses (the kernel's): its path into
; prn_cur, SI = its name, ZF if there is none (PrtSc saves files).  DI kept
prn_get:
        push    di
        push    es
        mov     ax, 0F006h
        int     21h                     ; ES:BX = its path
        mov     si, prn_cur
        mov     di, si                  ; (the name: after the last \)
.c:     mov     al, [es:bx]
        inc     bx
        mov     [si], al
        inc     si
        cmp     al, '\'
        jne     .n
        mov     di, si
.n:     or      al, al
        jnz     .c
        pop     es
        mov     si, di
        pop     di
        cmp     byte [si], 0
        ret

; Return on Devices: the next printer driver (the .PRN files where PATH
; finds programs: from the ROM C:\LODE, then the root of the drive
; started from), then none again (PrtSc saves files).  The kernel
; has its path at once; LODE.INI gets PRINTER=NAME.
next_prtsc:
        call    prn_get                 ; (prn_cur)
        mov     byte [past], 0
        cmp     byte [prn_cur], 0
        jne     .d0
        mov     byte [past], 1          ; none now: the first one is next
.d0:    mov     al, [boot_l]
        mov     [s_prnroot], al
        mov     bx, s_prnlode           ; from the ROM: C:\LODE's first
        cmp     al, 'R'
        je      .dir
.d1:    mov     bx, s_prnroot
.dir:   mov     dx, bx
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
.l:     jc      .nd
        mov     si, bx                  ; vbuf = the directory, the name
        mov     di, vbuf
.p:     lodsb
        cmp     al, '*'
        je      .pn
        stosb
        jmp     .p
.pn:    mov     si, dta + 30
        call    UI_SBSTR
        mov     byte [di], 0
        cmp     byte [past], 0
        je      .cur
        call    prn_ok                  ; past the one in use: this one, if
        jc      .nx                     ;  it is a driver
        jmp     short .set
.cur:   mov     si, vbuf
        mov     di, prn_cur
        call    same_name
        jne     .nx
        mov     byte [past], 1
.nx:    mov     ah, 4Fh
        int     21h
        jmp     .l
.nd:    cmp     bx, s_prnlode
        je      .d1
        mov     byte [vbuf], 0          ; past the last: none again
.set:   push    es
        mov     ax, 0F006h
        int     21h                     ; ES:BX = the kernel's, CX its room
        mov     di, bx
        mov     si, vbuf
.cp:    lodsb
        stosb
        or      al, al
        loopnz  .cp
        mov     byte [es:di-1], 0
        pop     es
        call    save_ini
        jmp     redraw

; started from the ROM, and R:\LODE.INI's (first) PRINTER= line names a
; driver?  CF if not.  (Reads it into ini_old: save_ini is past it.)
rom_prn:
        cmp     byte [boot_l], 'R'
        jne     .no
        pusha
        mov     dx, s_romini
        mov     di, ini_old
        mov     cx, INI_MAX
        call    read_file
        jc      .n
        xchg    cx, ax
        mov     si, di
        mov     bx, si
        add     bx, cx                  ; BX = its end
.l:     cmp     si, bx
        jae     .n
        mov     di, s_printeq
        call    ini_is
        jne     .sk
        add     si, 8                   ; (past "PRINTER=")
        cmp     si, bx
        jae     .n
        cmp     byte [si], ' '
        jbe     .n
        popa
        clc
        ret
.sk:    cmp     si, bx                  ; the next line
        jae     .n
        lodsb
        cmp     al, 10
        jne     .sk
        jmp     .l
.n:     popa
.no:    stc
        ret

; vbuf = a .PRN's path, the DTA its entry: CF if it isn't a printer driver
; (16 bytes to 1 KB, and "PRN", 1 after its JMP SHORT, as the kernel checks;
; a print job saved as .PRN isn't one)
prn_ok: cmp     word [dta + 28], 0
        jne     .no
        mov     ax, [dta + 26]
        cmp     ax, 16
        jb      .no
        cmp     ax, 1024
        ja      .no
        push    bx
        mov     dx, vbuf
        mov     di, vbuf + 64
        mov     cx, 6
        call    read_file
        jc      .r
        cmp     ax, 6
        jne     .nb
        cmp     word [vbuf + 66], 'PR'
        jne     .nb
        cmp     word [vbuf + 68], 'N' + 100h
        je      .r                      ; (CF clear)
.nb:    stc
.r:     pop     bx
        ret
.no:    stc
        ret

; Space on Display: the start-up picture or not; on Screen saver: tidy
; the disks first, or not
k_space:
        cmp     word [topics+LV_SEL], 5
        jne     .sv
        call    splash_get
        xor     byte [splash_off], 1
        call    save_ini
        jnc     .rd
        xor     byte [splash_off], 1    ; not saved: as it was (it only
.rd:    jmp     redraw                  ;  counts at the next start-up)
.sv:    cmp     word [topics+LV_SEL], 6
        jne     .mt
        xor     al, al
        call    UI_SAVER
        mov     bl, ah
        xor     bl, 1
        mov     al, 2
        call    UI_SAVER
        call    save_ini
        jmp     redraw
.mt:    cmp     word [topics+LV_SEL], 9 ; Multitasking: on or off from the
        jne     .x                      ;  next start-up
        call    mt_get
        xor     byte [mt_want], 1
        call    save_ini
        jnc     .rd
        xor     byte [mt_want], 1
        jmp     redraw
.x:     ret

;  Temporary disk M:: a RAM disk in EMS (the kernel's, through INT 67h
;  5Bh 'M').  Return: the next size, Off, 64, 128, 256, 512 KB, 1 MB or
;  all the EMS free, at once (M: is made again, empty: if it holds files,
;  Confirm first; not while a file on it is open), and saved in LODE.INI
;  as MDISK= (none for the usual 256 KB).  Without EMS: "needs EMS".
; ---------------------------------------------------------------------
MD_DRV  equ 12
t_mdisk:
        call    md_query                ; (before vstart: ems_mgr moves DI)
        call    vstart
        jnc     .here
        mov     si, s_needems
        call    UI_SBSTR
        mov     si, l_mdsize
        call    pline
        call    pgap
        mov     si, s_mdwhat1
        call    ptext
        mov     si, s_mdneeds
        jmp     ptext
.here:  mov     ax, [md_size]
        or      ax, ax
        jz      .off
        call    md_kbs                  ; "256 KB" ("1 MB", ...)
        mov     ax, [md_set]
        cmp     ax, 0FFFFh
        mov     si, s_mdall             ; " (all the EMS that was free)"
        je      .s
        cmp     ax, [md_size]
        jbe     .l
        mov     si, s_mdshort           ; " (less EMS was free)"
.s:     call    UI_SBSTR
.l:     mov     si, l_mdsize
        call    pline
        mov     dl, MD_DRV + 1          ; and free on it
        mov     ah, 36h
        int     21h
        cmp     ax, 0FFFFh
        je      .tail
        mov     [d_spc], ax
        mov     [d_bps], cx
        xchg    ax, bx
        mov     si, l_mdfree
        call    clus_line
        jmp     short .tail
.off:   mov     si, s_mdoff
        call    UI_SBSTR
        cmp     word [md_set], 0
        je      .o
        mov     si, s_mdnone            ; (asked for, but no EMS was free)
        call    UI_SBSTR
.o:     mov     si, l_mdsize
        call    pline
.tail:  call    vstart                  ; what all the EMS free would give
        mov     ax, [md_max]
        call    md_kbs
        mov     si, l_mdmax
        call    pline
        call    pgap
        mov     si, s_mdchoices
        call    ptext
        mov     si, s_mderase
        call    ptext
        call    pgap
        mov     si, s_mdwhat1
        call    ptext
        mov     si, s_mdwhat2
        jmp     ptext

; AX KB as "256 KB" or "1 MB" at DI
md_kbs: test    ax, 3FFh
        jnz     .k
        or      ax, ax
        jz      .k
        shr     ax, 10
        call    UI_SBU16
        mov     si, s_mb
        jmp     UI_SBSTR
.k:     call    UI_SBU16
        mov     si, s_kb
        jmp     UI_SBSTR

; M:'s setting, size and the most it can have -> md_set, md_size, md_max.
; CF if there is no M: here (no EMS, or EMS without the disk cache in it)
md_query:
        call    ems_mgr
        jc      .x
        mov     ax, 5B4Dh
        xor     bl, bl
        int     67h
        or      ah, ah
        jnz     .no
        mov     [md_set], bx
        mov     [md_size], cx
        mov     [md_max], dx
        clc
        ret
.no:    stc
.x:     ret

; Return on Temporary disk M:: the next size
next_mdisk:
        call    md_query
        jnc     .q
        jmp     UI_BEEP
.q:     mov     bx, [md_set]            ; the first step past the setting
        mov     si, md_steps            ;  (past all of them: off)
.f:     lodsw
        cmp     ax, bx
        ja      .got
        cmp     si, md_steps_end
        jb      .f
        xor     ax, ax
.got:   mov     [md_new], ax
        cmp     word [md_size], 0
        je      .set
        mov     ax, 0F001h              ; M: there: not while a file on it is
        mov     dl, MD_DRV              ;  open; Confirm if it holds any
        int     21h
        jcxz    .shut
        mov     si, s_mdopen
        jmp     UI_MSG
.shut:  mov     dx, s_mdall_files
        mov     cx, 16h
        mov     ah, 4Eh
        int     21h
        jc      .set
        mov     si, s_mdask
        call    UI_ASK
        jnc     .set
        ret
.set:   mov     ax, 5B4Dh
        mov     bl, 1
        mov     cx, [md_new]
        int     67h
        mov     si, s_mdopen
        cmp     ah, 80h
        je      .msg
        push    ax
        call    save_ini
        call    redraw
        pop     ax
        mov     si, s_mdroom
        cmp     ah, 81h
        je      .msg
        mov     si, s_mdnoems
        cmp     ah, 82h
        jne     .x
.msg:   jmp     UI_MSG
.x:     ret

md_steps    dw 0, 64, 128, 256, 512, 1024, 0FFFFh
md_steps_end:

; the file named at dta+30 into fbuf -> CF if it isn't exactly a font
load_fnt:
        mov     di, fpath
        mov     ax, [s_fntall]          ; "X:"
        stosw
        mov     al, '\'
        stosb
        mov     si, dta + 30
        call    UI_SBSTR
        mov     byte [di], 0
        mov     dx, fpath
        mov     di, fbuf
        mov     cx, FONT_BYTES + 1      ; (one more: a longer file isn't one)
        call    read_file
        jc      .x
        cmp     ax, FONT_BYTES
        je      .x                      ; (CF clear)
        stc
.x:     ret

; DX = a file's path: up to CX bytes of it to DI -> AX = how many (CF:
; it can't be opened or read; BX, CX, DX change)
read_file:
        mov     ax, 3D00h
        int     21h
        jc      .x
        xchg    bx, ax
        mov     dx, di
        mov     ah, 3Fh
        int     21h
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
.x:     ret

; SI, DI: names (ASCIIZ, any case) -> ZF if they are the same
same_name:
        push    si
        push    di
.l:     lodsb
        mov     ah, [di]
        inc     di
        and     ax, 0DFDFh
        cmp     al, ah
        jne     .x
        or      al, al
        jnz     .l
.x:     pop     di
        pop     si
        ret

; \LODE.INI into ini_old -> CX = its length (0: no file; INI_MAX + 1:
; longer than we keep)
ini_read:
        mov     dx, s_ini
        mov     di, ini_old
        mov     cx, INI_MAX + 1
        call    read_file
        jnc     .x
        xor     ax, ax                  ; (none, or unreadable: nothing)
.x:     xchg    cx, ax
        ret

; is the start-up picture off?  SPLASH=0 (or No, or Off) in \LODE.INI, as
; the kernel reads it -> splash_off.  Read once, when Display is first
; shown or saved (not at System's start: it costs a disk read).
splash_get:
        cmp     byte [splash_known], 0
        jne     splash_scan.x
        call    ini_read
; ... from the file in ini_old (CX bytes); all registers kept
splash_scan:
        pusha
        mov     byte [splash_known], 1
        mov     byte [splash_off], 0
        mov     si, ini_old
        mov     bx, si
        add     bx, cx                  ; BX = its end
.line:  cmp     si, bx
        jae     .done
        mov     di, s_splasheq
        call    ini_is
        jne     .next
        add     si, 7                   ; (past "SPLASH=")
        cmp     si, bx
        jae     .done
        mov     ax, [si]
        cmp     al, '0'
        je      .off
        and     ax, 0DFDFh
        cmp     al, 'N'
        je      .off
        cmp     ax, 'OF'
        jne     .done
.off:   mov     byte [splash_off], 1
.done:  popa
.x:     ret
.next:  cmp     si, bx                  ; on to the next line
        jae     .done
        lodsb
        cmp     al, 10
        jne     .next
        jmp     .line

; multitasking at the next start-up?  MULTITASK=1 (or On, or Yes) in
; \LODE.INI, as the kernel reads it -> mt_want.  Read once, as splash_get.
mt_get: cmp     byte [mt_known], 0
        jne     mt_scan.x
        call    ini_read
; ... from the file in ini_old (CX bytes); all registers kept
mt_scan:
        pusha
        mov     byte [mt_known], 1
        mov     byte [mt_want], 0
        mov     si, ini_old
        mov     bx, si
        add     bx, cx                  ; BX = its end
.line:  cmp     si, bx
        jae     .done
        mov     di, s_mteq
        call    ini_is
        jne     .next
        add     si, 10                  ; (past "MULTITASK=")
        cmp     si, bx
        jae     .done
        mov     ax, [si]                ; 1, On or Yes, and nothing after it,
        and     ax, 0DFDFh              ;  as the kernel reads it (KMDISK)
        mov     dx, 1
        cmp     al, '1' & 0DFh
        je      .end
        inc     dx
        cmp     ax, 'ON'
        je      .end
        cmp     ax, 'YE'
        jne     .done
        mov     al, [si+2]
        and     al, 0DFh
        cmp     al, 'S'
        jne     .done
        inc     dx
.end:   add     si, dx
        cmp     si, bx                  ; (the text's end, a blank or the
        ja      .done                   ;  line's)
        je      .on
        cmp     byte [si], ' '
        ja      .done
.on:    mov     byte [mt_want], 1
.done:  popa
.x:     ret
.next:  cmp     si, bx
        jae     .done
        lodsb
        cmp     al, 10
        jne     .next
        jmp     .line

; FONT=, SAVER=, TIDY=, MDISK=, SPLASH= and PRINTER= in \LODE.INI for the
; font, saver, temporary disk, start-up picture and PrtSc in use: its other
; lines are kept, old FONT=, SAVER=, TIDY=, MDISK=, SPLASH= and PRINTER= lines go, and GRiD's
; font, the usual 5 minutes, tidying, 256 KB and the picture need none (no
; lines left: no file).  Without M: (no EMS) an MDISK= line stays as it
; is.  CF if it couldn't be saved (said in the band).
save_ini:
        cmp     byte [boot_l], 'R'      ; started with the ROM's own settings
        jne     .ok                     ;  (the menu's 2) while there are
        cmp     byte [read_l], 0        ;  changes: not saved, or the changes
        jne     .ok                     ;  saved before would be lost
        mov     dx, s_ini
        mov     ax, 4300h
        int     21h
        jc      .ok
        mov     si, s_setnosave
        call    UI_MSG
        stc
        ret
.ok:    call    md_query                ; (md_ok: M: is ours to write)
        sbb     al, al
        not     al
        mov     [md_ok], al
        call    ini_read                ; the old file
        cmp     byte [splash_known], 0  ; (its SPLASH= line, if not read
        jne     .kn                     ;  yet: it is kept as it says; and
        call    splash_scan             ;  its MULTITASK= line)
.kn:    cmp     byte [mt_known], 0
        jne     .km
        call    mt_scan
.km:    cmp     cx, INI_MAX             ; (longer than we keep: leave it be)
        ja      .long
.new:   mov     si, ini_old
        mov     bx, si
        add     bx, cx                  ; BX = its end
        mov     di, ini_new
.line:  cmp     si, bx
        jae     .end
        push    di                      ; (DI: where the new text goes)
        mov     di, s_fonteq            ; "FONT=", "SAVER=" or "TIDY="
        call    ini_is                  ;  (any case)?
        je      .ours
        mov     di, s_savereq
        call    ini_is
        je      .ours
        mov     di, s_tidyeq
        call    ini_is
        je      .ours
        mov     di, s_splasheq
        call    ini_is
        je      .ours
        mov     di, s_printeq
        call    ini_is
        je      .ours
        mov     di, s_mteq
        call    ini_is
        je      .ours
        mov     di, s_mdeq              ; MDISK=: ours only with M: here
        call    ini_is
        jne     .ours
        cmp     byte [md_ok], 0FFh
.ours:  pop     di
        je      .skip
        jmp     short .keep
.skip:  cmp     si, bx                  ; the old line goes
        jae     .end
        lodsb
        cmp     al, 10
        jne     .skip
        jmp     .line
.keep:  cmp     si, bx                  ; any other line stays
        jae     .nolf
        lodsb
        stosb
        cmp     al, 10
        jne     .keep
        jmp     .line
.nolf:  mov     ax, 0A0Dh               ; (the last one had no line end)
        stosw
.end:   xor     al, al                  ; the font in use, unless GRiD's
        call    UI_FONT
        cmp     byte [si], 0
        je      .wr
        push    si
        mov     si, s_fonteq
        call    UI_SBSTR
        pop     si
        call    UI_SBSTR
        mov     ax, 0A0Dh
        stosw
.wr:    xor     al, al                  ; the saver's delay, unless 5 minutes
        call    UI_SAVER
        cmp     al, 5
        je      .wr2
        push    ax
        mov     si, s_savereq
        call    UI_SBSTR
        pop     ax
        xor     ah, ah
        call    UI_SBU16
        mov     ax, 0A0Dh
        stosw
.wr2:   xor     al, al                  ; not tidying: TIDY=0
        call    UI_SAVER
        or      ah, ah
        jz      .wr3
        mov     si, s_tidy0
        call    UI_SBSTR
.wr3:   cmp     byte [splash_off], 0    ; no start-up picture: SPLASH=0
        je      .wr3t
        mov     si, s_splash0
        call    UI_SBSTR
.wr3t:  cmp     byte [mt_want], 0       ; multitasking: MULTITASK=1
        je      .wr3p
        mov     si, s_mt1
        call    UI_SBSTR
.wr3p:  call    prn_get                ; a printer driver: PRINTER=NAME;
        jnz     .wr3d                   ;  none while the ROM's settings name
        call    rom_prn                 ;  one: PRINTER=, so none stays none
        jc      .wr3m                   ;  (the changes' line is read first)
        mov     si, s_empty
.wr3d:  push    si
        mov     si, s_printeq
        call    UI_SBSTR
        pop     si
        call    UI_SBSTR
        mov     ax, 0A0Dh
        stosw
.wr3m:  cmp     byte [md_ok], 0         ; M:'s size, unless 256 KB
        je      .wr4
        mov     ax, [md_set]
        cmp     ax, 256
        je      .wr4
        mov     si, s_mdeq
        call    UI_SBSTR
        mov     si, s_mdalleq
        cmp     ax, 0FFFFh
        je      .all
        call    UI_SBU16
        jmp     short .crlf
.all:   call    UI_SBSTR
.crlf:  mov     ax, 0A0Dh
        stosw
.wr4:   mov     bp, di                  ; BP = the end of the new text
        cmp     di, ini_new
        je      .del
        mov     dx, s_ini
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .err
        mov     bx, ax
        mov     cx, bp
        sub     cx, ini_new
        mov     dx, ini_new
        mov     ah, 40h
        int     21h
        jc      .errc
        cmp     ax, cx
        mov     ax, 39                  ; (short: the disk is full)
        jne     .errc
        mov     ah, 3Eh
        int     21h
        clc
        ret
.del:   mov     dx, s_ini               ; nothing to keep: no file
        mov     ah, 41h
        int     21h
        clc
        ret
.long:  mov     si, s_inilong
        call    UI_MSG
        stc
        ret
.errc:  push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
.err:   mov     di, vbuf                ; (a font, delay or size stays set
        mov     si, s_cantsave          ;  for now anyway)
        call    UI_SBSTR
        call    UI_SBERR
        mov     byte [di], 0
        mov     si, vbuf
        call    UI_MSG
        stc
        ret

; does the line at SI (its text ends at BX) start with DI ("FONT=", any
; case)? -> ZF.  SI, DI kept
ini_is: push    si
        push    di
        push    ax
.l:     mov     al, [di]
        or      al, al
        jz      .x                      ; (all of it: ZF set)
        cmp     si, bx
        jae     .no
        mov     ah, [si]
        cmp     ah, 'a'
        jb      .c
        cmp     ah, 'z'
        ja      .c
        sub     ah, 20h
.c:     cmp     al, ah
        jne     .x
        inc     si
        inc     di
        jmp     .l
.no:    or      si, si                  ; (ZF clear: SI isn't 0)
.x:     pop     ax
        pop     di
        pop     si
        ret

; ---------------------------------------------------------------------
;  Settings: where they come from, and where changes go
; ---------------------------------------------------------------------
t_settings:
        call    vstart
        mov     si, s_setrom            ; "the ROM, R:"
        cmp     byte [boot_l], 'R'
        je      .b
        mov     si, s_setfl             ; "Floppy A:"
        mov     al, [boot_l]
        mov     [si + 7], al
.b:     call    UI_SBSTR
        mov     si, l_started
        call    pline
        cmp     byte [boot_l], 'R'
        je      .rom
        call    vstart                  ; from a floppy: its LODE.INI
        mov     si, s_ini
        call    UI_SBSTR
        mov     si, l_setfile
        call    pline
        call    pgap
        mov     si, s_setfl1
        jmp     ptext
.rom:   call    vstart
        mov     si, s_setdef            ; "R:\LODE.INI (the ROM's own)"
        call    UI_SBSTR
        mov     si, l_setfile
        call    pline
        call    vstart                  ; the changes: there, none yet, or
        mov     si, s_ini               ;  not read this time (the menu's 2)
        call    UI_SBSTR
        mov     dx, s_ini
        mov     ax, 4300h
        int     21h
        mov     si, s_setnone
        jc      .c
        mov     si, s_setoff
        cmp     byte [read_l], 0
        je      .c
        mov     si, s_empty
.c:     call    UI_SBSTR
        mov     si, l_setchg
        call    pline
        call    pgap
        mov     si, s_setr1
        call    ptext
        mov     si, s_setr2
        call    ptext
        call    pgap
        mov     si, s_setr3
        call    ptext
        mov     si, s_setr4
        jmp     ptext

; Return on Settings: back to the ROM's own (the changes' file deleted,
; after asking).  From a floppy, or with no changes: a beep
set_back:
        cmp     byte [boot_l], 'R'
        jne     .no
        mov     dx, s_ini
        mov     ax, 4300h
        int     21h
        jc      .no
        mov     si, s_setask
        call    UI_ASK
        jc      .x
        mov     dx, s_ini
        mov     ah, 41h
        int     21h
        jc      .err
        mov     word [splash_known], 0  ; (and mt_known: both read again)
        mov     si, s_setdone
        call    UI_MSG
        jmp     redraw
.err:   mov     si, s_setcant
        jmp     UI_MSG
.no:    jmp     UI_BEEP
.x:     ret

; ---------------------------------------------------------------------
;  Multitasking: on now?  At the next start-up?  (MULTITASK=1 in
;  \LODE.INI; it stays off without EMS, 32 KB of it free, or LODEMT.SYS)
; ---------------------------------------------------------------------
t_mtask:
        call    mt_get
        mov     ax, 0F012h              ; on now?  (MTAPI.INC's MT_LIST: CX = 0,
        xor     cx, cx                  ;  only counted)
        stc
        int     21h
        sbb     al, al
        inc     al                      ; (AL = 1: on)
        mov     [mt_now], al
        call    vstart
        mov     si, s_on
        cmp     byte [mt_now], 0
        jne     .n
        mov     si, s_off
.n:     call    UI_SBSTR
        mov     si, l_mtnow
        call    pline
        call    vstart                  ; at the next start-up
        mov     si, s_on
        cmp     byte [mt_want], 0
        jne     .w
        mov     si, s_off
.w:     call    UI_SBSTR
        mov     si, l_mtnext
        call    pline
        call    pgap
        cmp     byte [mt_now], 0        ; asked for, but off: why
        jne     .t
        cmp     byte [mt_want], 0
        je      .t
        mov     si, s_mtwhy1
        call    ptext
        mov     si, s_mtwhy2
        call    ptext
        call    pgap
.t:     mov     si, s_mt1t
        call    ptext
        mov     si, s_mt2t
        call    ptext
        mov     si, s_mt3t
        jmp     ptext

; ---------------------------------------------------------------------
;  keys
; ---------------------------------------------------------------------
k_enter:
        mov     bx, [topics+LV_SEL]
        cmp     bx, 2
        je      set_clock
        cmp     bx, 3
        je      next_prtsc
        cmp     bx, 4
        je      scan_gpib
        cmp     bx, 5
        je      next_font
        cmp     bx, 6
        je      next_saver
        cmp     bx, 7
        je      next_mdisk
        cmp     bx, 8
        je      set_back
        ret
k_help: mov     si, keys
        mov     di, s_helptitle
        jmp     UI_HELP
k_quit: mov     byte [quit], 1
        ret
k_f5:   jmp     show_topic

keys:   KEY(K_NONE,      0,       h_topic)
        KEY(K_ENTER,     k_enter, h_enter)
        KEY(K_SPACE,     k_space, h_space)
        KEY(K_F5,        k_f5,    h_f5)
        KEY(K_F1,        k_help,  h_help)
        KEY(K_CODE_HELP, k_help,  0)
        KEY(K_ESC,       k_quit,  h_quit)
        KEY(K_CODE_Q,    k_quit,  0)
        KEY(K_CODE_U,    k_quit,  0)
        dw 0

; ---------------------------------------------------------------------
;  data
; ---------------------------------------------------------------------
topics:     dw TOP_Y, NTOPIC, NTOPIC, 0, 0, topic_row, show_topic, 1, PCOL - 3, topic_name
topic_names dw n_memory, n_disks, n_clock, n_devices, n_gpib, n_display, n_saver, n_mdisk, n_settings, n_mtask, n_about
topic_draw  dw t_memory, t_disks, t_clock, t_devices, t_gpib, t_display, t_saver, t_mdisk, t_settings, t_mtask, t_about
topic_band  dw s_band2, s_band2, s_band_clk, s_band_dev, s_band_gp, s_band_font, s_band_sv, s_band_md, s_band_set, s_band_mt, s_band2
n_memory    db 'Memory',0
n_disks     db 'Disks',0
n_clock     db 'Clock',0
n_devices   db 'Devices',0
n_gpib      db 'GPIB',0
n_display   equ l_display
n_saver     db 'Screen saver',0
n_mdisk     db 'Temporary disk',0
n_settings  equ l_setfile
n_mtask     db 'Multitasking',0
n_about     db 'About',0

clock_form: dw s_clocktitle, s_clockprompt, 46, 10, 2
            dw l_fdate, FT_TEXT + (20 << 8), f_date, 20
            dw l_ftime, FT_TEXT + (20 << 8), f_time, 20

s_title     db 'System',0
s_helptitle db 'System Help',0
s_band1     db 'System: Select a topic',0
s_band2     db 'CODE-? for help    ESC: back to the Executive',0
s_band_clk  db 'RETURN: set the date and time    ESC: back',0
s_band_gp   db 'RETURN: scan the bus    ESC: back',0
s_band_dev  db 'RETURN: the next printer driver (Shift-PrtSc: a file)   ESC: back',0
s_band_font db 'RETURN: the next font    SPACE: picture or not    ESC: back',0
s_band_sv   db 'RETURN: the next delay    SPACE: tidy or not    ESC: back',0
s_band_md   db 'RETURN: the next size    ESC: back',0
s_band_set  db "RETURN: back to the ROM's settings    ESC: back",0
s_band_mt   db 'SPACE: on or off from the next start-up    ESC: back',0
h_topic     db 'Up / Down, a letter, mouse   choose a topic',0
h_enter     db 'Return                       what the band says',0
h_space     db 'Space                        on or off (see the band)',0
h_f5        db 'F5                           look again',0
h_help      db 'CODE-?  or  F1               this help',0
h_quit      db 'ESC  or  CODE-Q              back to the Executive',0
s_kb        db ' KB',0
l_conv      db 'Conventional memory',0
l_kernel    db 'Kernel (DOS + GPIB)',0
l_kernel_e  db 'Kernel (DOS + GPIB + EMS)',0
s_emm       db 'EMMXXXX0'
l_exec      db 'Executive and UI core',0
l_this      db 'System (this program)',0
l_cache     db 'Disk cache',0
l_mdres     db 'Temporary disk M:',0
s_cems      db '32 KB of EMS',0
l_other     db 'Resident programs',0
l_free      db 'Free for programs',0
l_ems       db 'Expanded memory (EMS)',0
l_ext       db 'Extended memory',0
s_drive     db 'Drive A:',0
s_vol       db 'A:\*.*',0
s_nolabel   db '(no label)',0
l_dsize     db '  Size',0
l_dfree     db '  Free',0
l_dused     db '  In use',0
l_date      db 'Date',0
l_time      db 'Time',0
s_setclock  db 'Return: set the date and time',0
s_clocktitle db 'Date and time',0
s_clockprompt db 'Clock: Fill in form and confirm',0
l_fdate     equ l_date
l_ftime     equ l_time
s_baddate   db 'Not a date: try 5-Oct-2026',0
s_badtime   db 'Not a time: try 9:41 pm or 21:41',0
l_cpu       db 'Processor',0
l_fpu       db 'Coprocessor',0
l_bios      db 'BIOS',0
l_display   db 'Display',0
l_mouse     db 'Mouse',0
l_serial    db 'Serial ports',0
l_printer   db 'Printer port',0
l_prtsc     db 'PrtSc',0
l_floppy    db 'Floppy drives',0
l_hdisk     db 'Hard disk',0
s_286       db '80286',0
s_287       db '80287',0
s_xl        db 'XL',0
s_none      db 'none',0
s_grid      db 'GRiD, ',0
s_plasma    db 'Plasma 640x400',0
s_lcd       db 'LCD 640x400',0
s_panel     db 'Panel',0
s_mouse1    db 'Microsoft serial on COM1',0
s_mouse2    db 'Microsoft serial on COM2',0
s_comma     db ', ',0
s_com       db 'COM',0
s_lpt       db 'LPT1 ',0
s_and       db ' and ',0
s_b         db 'A: ',0
drive_types dw s_dnone, s_d360, s_d12, s_d720, s_d144
s_dnone     equ s_none
s_d360      db '360 KB',0
s_d12       db '1.2 MB',0
s_d720      db '720 KB',0
s_d144      db '1.44 MB',0
l_driver    db 'Driver',0
l_myaddr    db 'Our address',0
l_srq       db 'SRQ',0
s_srqirq    db 'on IRQ 5 (GPIBIRQ=0: polled)',0
s_srqpoll   db 'polled',0
l_found     db 'Instruments at',0
s_nogpib    db 'no GPIB controller found',0
s_gpver     db 'built in, version ',0
s_onint     db ', INT ',0
s_scanhint  db 'Return: scan the bus (serial poll 0-30)',0
s_scanask   db 'GPIB: Confirm to scan the bus',0
s_scanning  db 'Scanning the GPIB bus...',0
s_lodestone    db 'Lodestone ',0
s_about1    db 'for the GRiDCase 1520',0
l_dos       db 'DOS version',0
s_compat    db ' compatible',0
l_api       db 'UI core API',0
s_about2    db 'Programs: the Executive, System, Write',0
s_about3    db "Font: GRiD's InteGRiD system font (TC8X16)",0
day_names   dw d0, d1, d2, d3, d4, d5, d6
d0          db 'Sunday',0
d1          db 'Monday',0
d2          db 'Tuesday',0
d3          db 'Wednesday',0
d4          db 'Thursday',0
d5          db 'Friday',0
d6          db 'Saturday',0
month_names dw m1, m2, m3, m4, m5, m6, m7, m8, m9, m10, m11, m12
m1          db 'January',0
m2          db 'February',0
m3          db 'March',0
m4          db 'April',0
m5          db 'May',0
m6          db 'June',0
m7          db 'July',0
m8          db 'August',0
m9          db 'September',0
m10         db 'October',0
m11         db 'November',0
m12         db 'December',0
months3     db 'JANFEBMARAPRMAYJUNJULAUGSEPOCTNOVDEC'
quit        db 0
splash_off  db 0                        ; SPLASH=0: no start-up picture
splash_known db 0                       ;  (1: LODE.INI read for it)
mt_known    db 0                        ; the same for MULTITASK= (set_back
                                        ;  clears both as a word)
gp_scanned  db 0
l_font      db 'Font',0
l_fonts     db 'Fonts on the start-up disk:',0
s_gridfont  db 'GRiD (built in)',0
s_fntall    db '@:\*.FNT',0              ; (@: the disk Lodestone started from,
s_ini       db '@:\LODE.INI',0          ;  which reads them: set at the start;
                                        ;  the settings: where changes go)
boot_l      db 'A'                      ; the drive started from
read_l      db 0                        ; 3305h's DH: the changes read (0 none)
l_started   db 'Started from',0
l_setfile   db 'Settings',0
l_setchg    db 'Your changes',0
s_setrom    db 'the ROM, R:',0
s_setfl     db 'Floppy A:',0
s_setdef    db "R:\LODE.INI, the ROM's own",0
s_setnone   db ' (none yet)',0
s_setoff    db ' (not read: started with the ROM',27h,'s)',0
s_setfl1    db 'Changes made here are saved in it.',0
s_setr1     db 'Changes made here are saved there, and read over',0
s_setr2     db "the ROM's at every start-up.",0
s_setr3     db "Return: back to the ROM's settings (it asks first).",0
s_setr4     db "Shift held at start-up: 2 starts once with the ROM's.",0
s_setask    db "Settings: Confirm to go back to the ROM's",0
s_setdone   db "The ROM's settings are used from the next start-up",0
s_setcant   db "Your changes can't be deleted",0
s_setnosave db "Started with the ROM's own: not saved this time",0
s_fonteq    db 'FONT=',0
s_savereq   db 'SAVER=',0
s_tidyeq    db 'TIDY=',0
s_tidy0     db 'TIDY=0', 13, 10, 0
s_splasheq  db 'SPLASH=',0
s_splash0   db 'SPLASH=0', 13, 10, 0
s_mdeq      db 'MDISK=',0
s_mteq      db 'MULTITASK=',0
s_mt1       db 'MULTITASK=1', 13, 10, 0
l_mtnow     db 'Multitasking now',0
l_mtnext    db 'From the next start-up',0
s_on        db 'on',0
s_off       db 'off',0
s_mtwhy1    db 'Asked for, but off this time: it needs EMS, with',0
s_mtwhy2    db '32 KB of it free, and LODEMT.SYS beside LODE.SYS.',0
s_mt1t      db 'Programs started from the Executive run as tasks.',0
s_mt2t      db 'CODE-Tab: the next task.  CODE-T in the',0
s_mt3t      db 'Executive: the tasks.  LCMD: START, TASKS, WAIT.',0
mt_want     db 0                        ; MULTITASK=1 in \LODE.INI (mt_known)
mt_now      db 0                        ; (on now)
s_printeq   db 'PRINTER=',0
s_romini    db 'R:\LODE.INI',0
s_prtfile   db 'saves SCREENnn.BMP / .TXT',0
s_prtwith   db 'prints with ',0
s_prnroot   db '@:\*.PRN',0
s_prnlode   db 'C:\LODE\*.PRN',0
s_mdalleq   db 'ALL',0
l_mdsize    equ l_dsize + 2             ; ('Size' and 'Free')
l_mdfree    equ l_dfree + 2
l_mdmax     db 'All free EMS would give',0
s_mb        db ' MB',0
s_mdoff     db 'off',0
s_mdnone    db ' (no EMS was free)',0
s_mdshort   db ' (less EMS was free)',0
s_mdall     db ' (all the EMS free)',0
s_needems   db 'needs EMS',0
s_mdneeds   db 'This 1520 has no expanded memory (EMS) set up.',0
s_mdchoices db 'RETURN: off, 64, 128, 256, 512 KB, 1 MB, all free',0
s_mderase   db 'A new size empties M: (it asks first)',0
s_mdwhat1   db 'M: is a disk in expanded memory: no waiting.',0
s_mdwhat2   db 'Kept in LODE.INI as MDISK= (256 KB: no line).',0
s_mdall_files db 'M:\*.*',0
s_mdask     db 'M: holds files: Confirm to erase them',0
s_mdopen    db "A file on M: is open: M: can't change now",0
s_mdroom    db "No room in memory for M:'s part there: M: is off",0
s_mdnoems   db 'No EMS is free for M:: it is off',0
l_saver     db 'Starts after',0
s_never     db 'never',0
s_minutes   db ' minutes',0
s_minute    db ' minute',0
l_tidy      db 'Tidies the disks first',0
l_splash    db 'Start-up picture',0
s_yes       db 'yes',0
s_no        db 'no',0
s_svchoices db 'RETURN: 1, 2, 5, 10, 15 or 30 minutes, or never',0
s_svspace   db 'SPACE: tidy the disks first, or not',0
s_svwhat1   db 'Idle that long in the Executive, it tidies each disk',0
s_svwhat2   db '(DEFRAG), then shows the time on a dark screen.',0
s_empty     db 0
s_cantsave  db "LODE.INI can't be saved: ",0
s_inilong   db 'LODE.INI is too long to change here',0
s_sample1   db 'The quick brown fox jumps over the lazy dog',0
s_sample2   db '0123456789  ([{<>}])  .,;:!?  @#$%&*+-=/',0
%include "FPU.INC"                      ; (Devices: which coprocessor)
grid_font:                              ; GRiD's font, to switch back to
%include "FONT.INC"

section .bss
py          resw 1
vbuf        resb 128                ; ("0, 1, ... 30" is 109)
dta         resb 44
ui_base     resw 1
ui_keep     resw 1
first       resw 1
psp         resw 1
m_kernel    resw 1
m_ui        resw 1
m_cache     resw 1
m_md        resw 1
m_exec      resw 1
m_other     resw 1
m_best      resw 1
m_run       resw 1
m_inrun     resb 1
m_prevui    resb 1
m_noems     resb 1                  ; FFh: no EMS manager on INT 67h
m_runadj    resb 1
drv         resb 1
cmos10      resb 1
d_spc       resw 1
d_free      resw 1
d_bps       resw 1
d_total     resw 1
port_n      resw 1
pd_day      resb 1
pd_mon      resb 1
new_time    resw 1
f_date      resb 24
f_time      resb 24
gp_vec      resw 2
gp_int      resb 1
gp_my       resb 1
gp_nfound   resb 1
gp_found    resb 32
cur_font    resb 13
prn_cur     resb 24                 ; the printer driver's path (the kernel's)
md_set      resw 1                  ; M:: its setting (KB, 0 off, FFFFh all),
md_size     resw 1                  ;  its size (KB), the most it can have,
md_max      resw 1
md_new      resw 1                  ;  the next setting
md_ok       resb 1                  ;  and FFh: there is M: here
past        resb 1
fpath       resb 18
ini_old     resb INI_MAX + 1
ini_new     resb INI_MAX + 40
        times   -(FONT_BYTES + 1 > $ - ini_old) resb 1  ; (fbuf fits in both)
fbuf        equ ini_old                ; (a font file, or a disk's IDENTIFY
                                        ;  sector: never while LODE.INI is in
                                        ;  ini_old/ini_new; UI_FONT copies it)
run_bss_end:
