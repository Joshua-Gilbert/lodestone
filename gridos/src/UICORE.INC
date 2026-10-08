; =====================================================================
;  UICORE.INC - the UI core (our COMMON.SHR): everything the Executive
;  and the .RUN programs share.  Starts at offset 0 of the UI segment
;  with the jump table that UIAPI.INC describes.
;
;  Inside the core: DS = ES = CS = the UI segment, DF clear.  Entry
;  points reached through the jump table keep every register that isn't
;  an output (UIAPI.INC); internal routines say what they change.
; =====================================================================
%include "UIAPI.INC"

VSEG        equ 0B800h
BAND_Y      equ SCR_BAND_Y
MIN_T       equ 1092                    ; a minute of ticks
NALLOC      equ 16                      ; blocks a .RUN can have from UI_ALLOC
NWIN        equ 4                       ; windows open at once
GOS_VER     equ 003Ah                   ; Grid-OS 0.3.10 (BH.BL: major, minor<<4 | patch)

; ---- the jump table: UIAPI.INC's numbering, checked here ---------------
%macro API 2
        times (%1) - ($ - $$) db 0CCh   ; (negative = out of order: an error)
        times ($ - $$) - (%1) db 0CCh
        jmp     near %2
%endmacro
ui_base:
        API     UI_VERSION,   api_version
        API     UI_CLS,       api_cls
        API     UI_FILL,      fill_band
        API     UI_HLINE,     hline
        API     UI_VLINE,     vline
        API     UI_DOTS,      hline_dots
        API     UI_INVERT,    invert_band
        API     UI_PUTC,      putc
        API     UI_PUTS,      api_puts
        API     UI_PUTSN,     putsn
        API     UI_CENTER,    api_center
        API     UI_BOX,       box
        API     UI_STRLEN,    strlen
        API     UI_SBSTR,     api_sbstr
        API     UI_SBU16,     api_sbu16
        API     UI_SBU32,     api_sbu32
        API     UI_SBDATE,    api_sbdate
        API     UI_SBTIME,    api_sbtime
        API     UI_SBHEX4,    api_sbhex4
        API     UI_SBERR,     api_sberr
        API     UI_EVENT,     ui_event
        API     UI_POLL,      ui_poll
        API     UI_TICK,      tick
        API     UI_SETREDRAW, api_setredraw
        API     UI_SCREEN,    ui_screen
        API     UI_BAND,      ui_band
        API     UI_MSG,       ui_msg
        API     UI_ASK,       ui_ask
        API     UI_WOPEN,     ui_wopen
        API     UI_WCLOSE,    ui_wclose
        API     UI_HELP,      ui_help
        API     UI_DISPATCH,  ui_dispatch
        API     UI_LVDRAW,    lv_draw
        API     UI_LVKEY,     lv_key
        API     UI_LVCLICK,   lv_click
        API     UI_LVSET,     lv_set
        API     UI_EDIT,      ui_edit
        API     UI_FORM,      ui_form
        API     UI_ALLOC,     ui_alloc
        API     UI_FREE,      ui_free
        API     UI_RUN,       ui_run
        API     UI_FINDAPP,   ui_findapp
        API     UI_CRITERR,   api_criterr
        API     UI_BEEP,      ui_beep
        API     UI_KEYSHIFT,  api_keyshift
        API     UI_FONT,      api_font
        API     UI_SAVER,     api_saver

section uibss
; mouse and pointer
mfound      resw 1              ; mouse port found at start-up
mstarted    resb 1
cur_x       resw 1
cur_y       resw 1
cur_xb      resw 1
cur_save    resb 26
new_save    resb 26
ubuf        resb 4 * 26
cnew_x      resw 1
cnew_y      resw 1
cnew_xb     resw 1
ux0         resw 1
uy0         resw 1
uw          resw 1
uh          resw 1
cflags      resb 1
ptr_on      resb 1              ; the pointer may show (UI_EVENT is waiting)
; clock, title bar, band
rtc_h       resb 1
rtc_m       resb 1
rtc_y       resb 1
rtc_mo      resb 1
rtc_d       resb 1
title_on    resb 1
title_ptr   resw 1
band1       resw 1
band2       resw 1
held1       resw 1              ; the band of a question, form or message
held2       resw 1              ;  still waiting (0: none): put back by
                                ;  redraw_all (the screen saver's redraw
                                ;  draws the program's usual band)
lastact     resw 1
saver_t     resw 1              ; idle ticks before the saver (FFFFh: never)
saver_min   resb 1              ;  the same in minutes (0: never)
lastpoll    resw 1
redraw_fn   resw 1
; windows: the save-under is in the disk cache's memory while any is open
wdepth      resw 1
wover       resw 1              ; windows opened past NWIN (not drawn)
wseg        resw 1              ; 0: no save-under
wcap        resw 1
wtop        resw 1
wstack      resw 2 * NWIN       ; (window, save offset or 0FFFFh)
help_w      resb W_SIZE
help_tab    resw 1
form_w      resb W_SIZE
; lists, forms, the line editor
lv_cur      resw 1
disp_fn     resw 1
fm_opt      resb 1
fm_lined    resb 1
fm_sel      resb 1
ed_buf      resw 1
ed_max      resw 1
ed_col      resw 1
ed_y        resw 1
ed_w        resw 1
ed_pos      resw 1
ed_off      resw 1
ed_fresh    resb 1
ed_keep     resb 1
font_name   resb 13             ; UI_FONT: "" = GRiD's, built in
font_path   resb 14             ; "\NAME.FNT"
fm_ptr      resw 1
fm_cur      resw 1
fm_b1       resw 1
fm_b2       resw 1
; programs
crit_err    resw 1
old24       resw 2
run_active  resb 1
lent        resb 1              ; the directory's memory is out (ui_lend)
need_room   resb 1              ; ui_room has a look at the next chance
run_base    resw 1              ; where a .RUN loads (offset)
ui_paras    resw 1              ; the UI block's own size
ent_max     resw 1              ; directory entries that fit (EXEC.INC)
alloc_tab   resw NALLOC
run_hdr     resb 16
run_hnd     resw 1
run_dta     resw 2
run_ret     resw 1
run_tail    resb 130
run_epb     resw 7
app_path    resb 80
rowtab      resw 400
tmp         resb 96
section ui

; =====================================================================
;  start-up: the kernel jumps here (UI segment, our own stack) at boot
;  and whenever the root process starts over
; =====================================================================
exec_main:
        cld
        push    cs
        pop     ds
        push    cs
        pop     es
        call    run_cleanup             ; (a .RUN ended by ^C or an error)
        cmp     byte [mstarted], 0
        jne     .again
        mov     byte [mstarted], 1
        mov     ax, ui_bss_end + 15     ; where .RUN programs load
        and     ax, 0FFF0h
        mov     [run_base], ax
        mov     ax, 3524h               ; the kernel's critical-error handler
        int     21h
        mov     [old24], bx
        mov     [old24+2], es
        push    cs
        pop     es
        mov     ax, cs                  ; the UI block's size, to shrink back to
        dec     ax
        push    es
        mov     es, ax
        mov     ax, [es:3]
        pop     es
        mov     [ui_paras], ax
        mov     word [ent_max], MAXENT
        call    mkrows
        call    mouse_init
        mov     bl, 5                   ; the saver after 5 minutes, unless
        call    saver_set               ;  GRIDOS.INI says otherwise
        call    font_boot               ; GRIDOS.INI's font and saver delay
        jmp     .go
.again: call    m33_end
        call    mouse_on
.go:    call    set24
        call    act_now
        jmp     ex_start                ; the Executive

; UI_FONT: AL = 0 -> SI = the font's name; AL = 1: SI = glyphs, DI = name
api_font:
        or      al, al
        jnz     .set
        mov     si, font_name
        ret
.set:   pusha
        push    si
        mov     si, di                  ; the name (12 characters at most)
        mov     di, font_name
        mov     cx, 12
.n:     lodsb
        stosb
        or      al, al
        jz      .g
        loop    .n
        mov     byte [di], 0
.g:     pop     si
        mov     di, font                ; the glyphs, over the font in use
        mov     cx, FONT_BYTES / 2
        rep     movsw
        popa
        ret

; at start-up: "FONT=NAME.FNT" in \GRIDOS.INI (a line of its own, any case)
; makes that file the font.  No file, no line, or a file that isn't exactly
; FONT_BYTES long: GRiD's font stays.  "SAVER=n": the saver after n minutes
; (0: never).  (The directory buffer is free yet.)
font_boot:
        mov     byte [font_path], '\'
        mov     dx, s_ini
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     bx, ax
        mov     dx, entries
        mov     cx, 511
        mov     ah, 3Fh
        int     21h
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     cx                      ; (bytes read)
        popf
        jc      .x
        mov     si, entries
        mov     di, si
        add     di, cx
        mov     byte [di], 0
.line:  mov     ax, [si]                ; "SAVER=n"?
        and     ax, 0DFDFh
        cmp     ax, 'SA'
        jne     .font
        mov     ax, [si+2]
        and     ax, 0DFDFh
        cmp     ax, 'VE'
        jne     .next
        mov     ax, [si+4]
        and     al, 0DFh
        cmp     ax, 'R='
        jne     .next
        add     si, 6
        xor     bx, bx
.d:     lodsb                           ; the number
        sub     al, '0'
        cmp     al, 9
        ja      .dn
        imul    bx, bx, 10
        add     bl, al
        cmp     bx, 100
        jb      .d
.dn:    dec     si
        call    saver_set
        jmp     .next
.font:  mov     ax, [si]                ; "FONT=" at the start of a line?
        and     ax, 0DFDFh
        cmp     ax, 'FO'                ; (memory "FO": AL = 'F', as NASM's)
        jne     .next
        mov     ax, [si+2]
        and     ax, 0DFDFh
        cmp     ax, 'NT'
        jne     .next
        cmp     byte [si+4], '='
        jne     .next
        add     si, 5
        mov     di, font_path + 1
        mov     cx, 12
.c:     lodsb
        cmp     al, ' '                 ; (CR, LF, the end, a space or tab)
        jbe     .e
        stosb
        loop    .c
.e:     mov     byte [di], 0
        cmp     di, font_path + 1
        je      .next                   ; ("FONT=": GRiD's)
        push    si
        call    font_file
        pop     si
.next:  lodsb
        or      al, al
        jz      .x
        cmp     al, 10
        jne     .next
        jmp     .line
.x:     ret

; font_path = "\NAME.FNT": that file is the font (if it is exactly one)
font_file:
        mov     dx, font_path
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     bx, ax
        mov     dx, entries + 512
        mov     cx, FONT_BYTES + 1      ; (one byte more: a longer file isn't one)
        mov     ah, 3Fh
        int     21h
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
        jc      .x
        cmp     ax, FONT_BYTES
        jne     .x
        mov     si, entries + 512
        mov     di, font_path + 1
        mov     al, 1
        jmp     api_font
.x:     ret

; UI_SAVER: AL = 0 -> AL = the saver's delay in minutes (0 never); AL = 1:
; BL = minutes
api_saver:
        or      al, al
        jnz     saver_set
        mov     al, [saver_min]
        ret
; BL = minutes (more than 30: 30; 0: never)
saver_set:
        push    ax
        push    dx
        cmp     bl, 30                  ; (the idle count stays under 8000h)
        jbe     .m
        mov     bl, 30
.m:     mov     [saver_min], bl
        mov     ax, 0FFFFh
        or      bl, bl
        jz      .t
        mov     al, bl
        xor     ah, ah
        mov     dx, MIN_T
        mul     dx
.t:     mov     [saver_t], ax
        pop     dx
        pop     ax
        ret

; INT 24h while the UI runs: fail the call, remember why (UI_CRITERR)
ui_int24:
        push    ax
        mov     ax, di
        xor     ah, ah
        inc     ax
        mov     [cs:crit_err], ax
        pop     ax
        mov     al, 3                   ; Fail
        iret

set24:  push    ax
        push    dx
        mov     dx, ui_int24
        mov     ax, 2524h
        int     21h
        pop     dx
        pop     ax
        ret

unset24:
        push    ax
        push    dx
        push    ds
        lds     dx, [old24]
        mov     ax, 2524h
        int     21h
        pop     ds
        pop     dx
        pop     ax
        ret

api_version:
        mov     ax, UI_API
        mov     bx, GOS_VER
        mov     cx, [ui_paras]
        mov     dx, [mbase]
        mov     si, ui_keep_end + 15    ; the size it keeps while a DOS
        shr     si, 4                   ;  program runs
        ret

api_criterr:
        mov     ax, [crit_err]
        mov     word [crit_err], 0
        ret

api_keyshift:
        push    bx
        mov     bl, ah
        mov     ah, 2
        int     16h
        mov     ah, bl
        pop     bx
        ret

api_setredraw:
        mov     [redraw_fn], si
        ret

; =====================================================================
;  events
; =====================================================================
; UI_EVENT: wait for a key or a click (the pointer shows meanwhile)
ui_event:
        mov     byte [ptr_on], 1
        call    show_cursor
.l:     call    poll_once
        jnc     .got
        sti
        hlt                             ; sleep until the next interrupt
        jmp     .l
.got:   mov     byte [ptr_on], 0
        jmp     hide_cursor

; UI_POLL: the same without waiting (CF set: nothing)
ui_poll:
        jmp     poll_once

; the next key, through INT 16h AH=10h.  The 1520's BIOS marks CODE with
; most punctuation and with Return, ESC and Backspace (CODE-?, CODE-Return,
; CODE-ESC ...) as enhanced-keyboard keys: AH=00h/01h skip them, and
; AH=01h even drops them from the buffer.  AH=10h returns them with AL = 0;
; the rest is made to look as AH=00h returns it (keypad Enter and / as the
; main keys, AL = 0 for the grey cursor keys).
read_key:
        mov     ah, 10h
        int     16h
        cmp     ah, 0E0h                ; keypad Enter, Ctrl-Enter or /
        jne     .grey
        mov     ah, 1Ch
        cmp     al, '/'
        jne     .x
        mov     ah, 35h
        ret
.grey:  cmp     al, 0E0h
        jne     .x
        or      ah, ah
        jz      .x                      ; (Alt-224 typed on the keypad)
        mov     al, 0
.x:     ret

; one look at the mouse, the keyboard and the clock.  CF clear with an
; event in AX (BX, CX for a click); CF set if none (BX, CX unchanged)
poll_once:
        push    ax
        push    bx
        push    cx
        cmp     byte [mflag], 0
        je      .nomouse
        call    act_now
        call    mouse_event
        jnc     .nomouse
        add     sp, 6
        clc
        ret
.nomouse:
        mov     ah, 11h
        int     16h
        jz      .nokey
        call    act_now
        call    read_key
        pop     cx                      ; (the mouse may have used them)
        pop     bx
        add     sp, 2
        clc
        ret
.nokey: mov     ah, 19h                 ; (the kernel takes a screen capture
        int     21h                     ;  asked for with Shift-PrtSc)
        call    tick
        mov     bx, ax                  ; more than ~2 s since the last look:
        sub     bx, [lastpoll]          ;  the clock was set (System), or a
        mov     [lastpoll], ax          ;  long job ran; neither is idle time
        cmp     bx, 36
        jbe     .idle
        mov     [lastact], ax
.idle:  mov     bx, ax                  ; idle [saver_t] ticks: the screen saver
        sub     bx, [lastact]
        cmp     bx, 8000h               ; (the clock went back at midnight)
        jb      .sv
        mov     [lastact], ax
        jmp     .ck
.sv:    cmp     bx, [saver_t]
        jb      .ck
        call    saver
        jmp     .none
.ck:    mov     bx, ax
        sub     bx, [lasttick]
        cmp     bx, 9                   ; ~0.5 s
        jb      .none
        mov     [lasttick], ax
        call    clock_tick
.none:  pop     cx
        pop     bx
        pop     ax
        stc
        ret

act_now:                                ; a key or the mouse: not idle
        push    ax
        call    tick
        mov     [lastact], ax
        pop     ax
        ret

; the pointer back on if UI_EVENT is waiting
ptr_restore:
        cmp     byte [ptr_on], 0
        je      .x
        call    show_cursor
.x:     ret

; the whole screen again: the program's redraw routine, the band, then
; each open window over it (their save-under still holds what the
; routine drew, so it stays valid)
redraw_all:
        pusha
        call    hide_cursor
        mov     si, [redraw_fn]
        or      si, si
        jz      .nofn
        call    si
.nofn:  mov     ax, [held1]             ; a question still waiting: its band,
        or      ax, ax                  ;  not the one the routine drew
        jz      .band
        mov     [band1], ax
        mov     ax, [held2]
        mov     [band2], ax
.band:  call    band_redraw
        xor     bx, bx
.w:     cmp     bx, [wdepth]
        jae     .x
        push    bx
        shl     bx, 2
        mov     si, [wstack+bx]
        call    win_paint
        pop     bx
        inc     bx
        jmp     .w
.x:     popa
        ret

; =====================================================================
;  mouse (Microsoft serial protocol, 1200 7N1) - COM2 first, then COM1
; =====================================================================
mouse_init:
        call    m33_hook                ; INT 33h for DOS programs
        call    m33_soft
        mov     word [mbase], 2F8h
        mov     byte [mirq], 3
        call    mouse_probe
        jnc     .found
        mov     word [mbase], 3F8h
        mov     byte [mirq], 4
        call    mouse_probe
        jnc     .found
        mov     word [mbase], 0
        ret
.found: mov     ax, [mbase]
        mov     [mfound], ax
mouse_hook:
        cli
        xor     ax, ax
        mov     es, ax
        mov     bl, [mirq]
        xor     bh, bh
        add     bx, 8
        shl     bx, 2                   ; IVT slot of IRQ3/4 (INT 0Bh/0Ch)
        mov     ax, [es:bx]
        mov     [oldvec], ax
        mov     ax, [es:bx+2]
        mov     [oldvec+2], ax
        mov     word [es:bx], mouse_isr
        mov     [es:bx+2], cs
        mov     [vecslot], bx
        call    uart_line               ; (a DOS program may have changed it)
        mov     dx, [mbase]
        inc     dx
        mov     al, 1                   ; IER: received-data interrupt
        out     dx, al
        add     dx, 3
        mov     al, 0Bh                 ; MCR: DTR + RTS + OUT2 (IRQ gate)
        out     dx, al
        mov     cl, [mirq]
        mov     ah, 1
        shl     ah, cl
        not     ah
        in      al, 21h
        and     al, ah
        out     21h, al
        mov     dx, [mbase]
        in      al, dx                  ; clear any pending byte
        sti
        push    cs
        pop     es
        ret

; the mouse again after a program (no new probe)
mouse_on:
        mov     ax, [mfound]
        or      ax, ax
        jz      .x
        cmp     word [mbase], 0
        jne     .x                      ; (already on)
        mov     [mbase], ax
        mov     byte [mirq], 3
        cmp     ax, 2F8h
        je      .h
        mov     byte [mirq], 4
.h:     call    mouse_hook
.x:     ret

; the mouse's line at [mbase]: 1200 baud, 7N1, and DLAB off at the end,
; so base+1 is the IER again
uart_line:
        mov     dx, [mbase]
        add     dx, 3
        mov     al, 80h
        out     dx, al                  ; DLAB
        mov     dx, [mbase]
        mov     al, 96                  ; 1200 baud
        out     dx, al
        inc     dx
        xor     al, al
        out     dx, al
        add     dx, 2
        mov     al, 02h                 ; 7N1, DLAB off
        out     dx, al
        ret

; CF clear if a Microsoft mouse answers 'M' at [mbase]
mouse_probe:
        mov     dx, [mbase]
        add     dx, 7
        mov     al, 5Ah
        out     dx, al
        jmp     short $+2
        in      al, dx
        cmp     al, 5Ah
        jne     .no
        call    uart_line               ; 1200 baud, 7N1 (DLAB off)
        mov     dx, [mbase]
        inc     dx
        xor     al, al
        out     dx, al                  ; IER off
        add     dx, 3
        out     dx, al                  ; DTR/RTS off: mouse powers down
        mov     cx, 3
        call    wait_ticks
        call    uart_drain
        mov     dx, [mbase]
        add     dx, 4
        mov     al, 03h
        out     dx, al                  ; DTR/RTS on: mouse sends 'M'
        call    tick
        mov     si, ax
.poll:  mov     dx, [mbase]
        add     dx, 5
        in      al, dx
        test    al, 1
        jz      .t
        mov     dx, [mbase]
        in      al, dx
        cmp     al, 'M'
        je      .yes
.t:     call    tick
        sub     ax, si
        cmp     ax, 6
        jb      .poll
.no:    stc
        ret
.yes:   clc
        ret

uart_drain:
        mov     cx, 16
.d:     mov     dx, [mbase]
        add     dx, 5
        in      al, dx
        test    al, 1
        jz      .x
        mov     dx, [mbase]
        in      al, dx
        loop    .d
.x:     ret

mouse_off:
        cmp     word [mbase], 0
        je      .x
        pusha
        push    es
        cli
        mov     dx, [mbase]
        inc     dx
        xor     al, al
        out     dx, al
        add     dx, 3
        out     dx, al
        mov     cl, [mirq]
        mov     ah, 1
        shl     ah, cl
        in      al, 21h
        or      al, ah
        out     21h, al
        xor     ax, ax
        mov     es, ax
        mov     bx, [vecslot]
        mov     ax, [oldvec]
        mov     [es:bx], ax
        mov     ax, [oldvec+2]
        mov     [es:bx+2], ax
        mov     word [mbase], 0
        sti
        pop     es
        popa
.x:     ret

mouse_isr:
        push    ax
        push    bx
        push    dx
.rd:    mov     dx, [cs:mbase]
        add     dx, 5
        in      al, dx
        test    al, 1
        jz      .done
        mov     dx, [cs:mbase]
        in      al, dx
        test    al, 40h                 ; first byte of a packet
        jz      .nf
        mov     byte [cs:midx], 0
.nf:    mov     bl, [cs:midx]
        cmp     bl, 3
        jae     .rd
        xor     bh, bh
        mov     [cs:mpkt+bx], al
        inc     bl
        mov     [cs:midx], bl
        cmp     bl, 3
        jne     .rd
        cmp     byte [cs:mpkt], 40h     ; packet must start with a sync byte
        jb      .rd
        mov     al, [cs:mpkt]           ; dx = (b0 & 3) << 6 | b1
        mov     ah, al
        and     al, 3
        shl     al, 6
        or      al, [cs:mpkt+1]
        cbw
        mov     [cs:m33_dx], ax
        add     ax, [cs:mx]
        jns     .x1
        xor     ax, ax
.x1:    cmp     ax, 639
        jbe     .x2
        mov     ax, 639
.x2:    mov     [cs:mx], ax
        mov     al, [cs:mpkt]           ; dy = (b0 & 0Ch) << 4 | b2
        and     al, 0Ch
        shl     al, 4
        or      al, [cs:mpkt+2]
        cbw
        mov     [cs:m33_dy], ax
        add     ax, [cs:my]
        jns     .y1
        xor     ax, ax
.y1:    cmp     ax, 399
        jbe     .y2
        mov     ax, 399
.y2:    mov     [cs:my], ax
        mov     al, [cs:mpkt]           ; buttons: 20h left, 10h right
        xor     bl, bl
        test    al, 20h
        jz      .b1
        or      bl, 1
.b1:    test    al, 10h
        jz      .b2
        or      bl, 2
.b2:    mov     [cs:mb], bl
        mov     byte [cs:mflag], 1
        call    m33_pkt                 ; (INT 33h's side)
        jmp     .rd
.done:  mov     al, 20h
        out     20h, al
        call    m33_call                ; a DOS program's event handler
        pop     dx
        pop     bx
        pop     ax
        iret

; the main-loop side of the mouse: move the pointer (if it shows);
; CF set with AX = EV_CLICK, BX = x, CX = y for a left-button press
mouse_event:
        push    dx
        cli
        mov     byte [mflag], 0
        mov     ax, [mx]
        mov     bx, [my]
        mov     cl, [mb]
        sti
        cmp     byte [ptr_on], 0
        je      .btn
        cmp     ax, [cur_x]
        jne     .mv
        cmp     bx, [cur_y]
        je      .btn
.mv:    push    cx
        cli
        mov     ax, [mx]                ; freshest position
        mov     bx, [my]
        sti
        call    move_cursor             ; flicker-free: never erased first
        pop     cx
.btn:   mov     ch, [oldmb]
        mov     [oldmb], cl
        test    cl, 1
        jz      .no
        test    ch, 1
        jnz     .no                     ; only on press
        mov     ax, EV_CLICK
        cli                             ; (x and y from the same packet)
        mov     bx, [mx]
        mov     cx, [my]
        sti
        pop     dx
        stc
        ret
.no:    pop     dx
        clc
        ret

%include "MOUSE33.INC"

; arrow pointer: 13 rows of (shape, spare); drawn by inverting the shape
cur_shape:
        db 10000000b, 00000000b
        db 11000000b, 00000000b
        db 11100000b, 01000000b
        db 11110000b, 01100000b
        db 11111000b, 01110000b
        db 11111100b, 01111000b
        db 11111110b, 01111100b
        db 11111111b, 01111110b
        db 11111111b, 01110000b
        db 11111000b, 01010000b
        db 11011100b, 00001000b
        db 10011100b, 00001000b
        db 00001100b, 00000000b

show_cursor:
        cmp     word [mbase], 0
        je      .x
        cmp     byte [curvis], 0
        jne     .x
        pusha
        push    es
        push    cs
        pop     es
        pushf
        cli                             ; (x and y from the same packet)
        mov     ax, [mx]
        mov     bx, [my]
        popf
        mov     [cnew_x], ax
        mov     [cnew_y], bx
        shr     ax, 3
        mov     [cnew_xb], ax
        call    move_cursor.rect
        mov     byte [cflags], 2
        call    compose
        mov     si, new_save
        mov     di, cur_save
        mov     cx, 26
        rep     movsb
        mov     ax, [cnew_x]
        mov     [cur_x], ax
        mov     ax, [cnew_y]
        mov     [cur_y], ax
        mov     ax, [cnew_xb]
        mov     [cur_xb], ax
        mov     byte [curvis], 1
        pop     es
        popa
.x:     ret

; move_cursor: AX = new x, BX = new y.  The old and new pointer areas are
; composed in RAM and every screen byte is written once, so there is no
; moment without a pointer (the old erase-then-draw flickered on the plasma).
move_cursor:
        cmp     byte [curvis], 0
        jne     .vis
        jmp     show_cursor
.vis:   pusha
        push    es
        push    cs
        pop     es
        mov     [cnew_x], ax
        mov     [cnew_y], bx
        shr     ax, 3
        mov     [cnew_xb], ax
        sub     ax, [cur_xb]            ; overlapping areas?
        jns     .a1
        neg     ax
.a1:    cmp     ax, 2
        jae     .disj
        mov     ax, bx
        sub     ax, [cur_y]
        jns     .a2
        neg     ax
.a2:    cmp     ax, 13
        jae     .disj
        mov     ax, [cnew_xb]           ; union of both areas
        mov     dx, [cur_xb]
        cmp     ax, dx
        jbe     .u1
        xchg    ax, dx
.u1:    mov     [ux0], ax
        sub     dx, ax
        add     dx, 2
        mov     cx, 80
        sub     cx, ax
        cmp     dx, cx
        jbe     .u2
        mov     dx, cx
.u2:    mov     [uw], dx
        mov     ax, [cnew_y]
        mov     dx, [cur_y]
        cmp     ax, dx
        jbe     .u3
        xchg    ax, dx
.u3:    mov     [uy0], ax
        sub     dx, ax
        add     dx, 13
        mov     cx, 400
        sub     cx, ax
        cmp     dx, cx
        jbe     .u4
        mov     dx, cx
.u4:    mov     [uh], dx
        mov     byte [cflags], 3
        call    compose
        jmp     .done
.disj:  mov     ax, [cnew_xb]           ; far apart: draw new, then erase old
        mov     bx, [cnew_y]
        call    .rect
        mov     byte [cflags], 2
        call    compose
        mov     ax, [cur_xb]
        mov     bx, [cur_y]
        call    .rect
        mov     byte [cflags], 1
        call    compose
.done:  mov     si, new_save
        mov     di, cur_save
        mov     cx, 26
        rep     movsb
        mov     ax, [cnew_x]
        mov     [cur_x], ax
        mov     ax, [cnew_y]
        mov     [cur_y], ax
        mov     ax, [cnew_xb]
        mov     [cur_xb], ax
        pop     es
        popa
        ret
.rect:  mov     [ux0], ax               ; AX = byte col, BX = y
        mov     cx, 80
        sub     cx, ax
        cmp     cx, 2
        jbe     .w
        mov     cx, 2
.w:     mov     [uw], cx
        mov     [uy0], bx
        mov     cx, 400
        sub     cx, bx
        cmp     cx, 13
        jbe     .h
        mov     cx, 13
.h:     mov     [uh], cx
        ret

; compose the area (ux0, uy0, uw, uh) in ubuf:  cflags bit 0 = restore the
; old pointer's background, bit 1 = save under and draw the new pointer
compose:
        pusha
        push    es
        push    VSEG
        pop     es
        xor     bp, bp                  ; 1. screen -> ubuf
.r1:    cmp     bp, [uh]
        jae     .r1d
        mov     bx, [uy0]
        add     bx, bp
        shl     bx, 1
        mov     si, [rowtab+bx]
        add     si, [ux0]
        mov     di, bp
        shl     di, 2
        add     di, ubuf
        mov     cx, [uw]
.c1:    mov     al, [es:si]
        mov     [di], al
        inc     si
        inc     di
        loop    .c1
        inc     bp
        jmp     .r1
.r1d:   test    byte [cflags], 1        ; 2. old background back into ubuf
        jz      .noold
        xor     bp, bp
.r2:    mov     ax, [cur_y]
        add     ax, bp
        cmp     ax, 400
        jae     .noold
        sub     ax, [uy0]
        shl     ax, 2
        add     ax, ubuf
        mov     di, ax
        mov     bx, bp
        shl     bx, 1
        mov     dx, [cur_xb]
        call    .old1
        inc     dx
        inc     bx
        call    .old1
        inc     bp
        cmp     bp, 13
        jb      .r2
.noold: test    byte [cflags], 2        ; 3. save under + draw new pointer
        jz      .nonew
        mov     cx, [cnew_x]
        and     cl, 7
        xor     bp, bp
.r3:    mov     ax, [cnew_y]
        add     ax, bp
        cmp     ax, 400
        jae     .nonew
        sub     ax, [uy0]
        shl     ax, 2
        add     ax, ubuf
        mov     si, [cnew_xb]
        sub     si, [ux0]
        add     si, ax
        mov     bx, bp
        shl     bx, 1
        mov     dh, [cur_shape+bx]
        xor     dl, dl
        shr     dx, cl                  ; arrow shape
        mov     al, [si]                ; invert what is underneath
        mov     [new_save+bx], al
        xor     al, dh
        mov     [si], al
        cmp     word [cnew_xb], 79
        jae     .n2
        mov     al, [si+1]
        mov     [new_save+bx+1], al
        xor     al, dl
        mov     [si+1], al
.n2:    inc     bp
        cmp     bp, 13
        jb      .r3
.nonew: xor     bp, bp                  ; 4. ubuf -> screen, once
.r4:    cmp     bp, [uh]
        jae     .r4d
        mov     bx, [uy0]
        add     bx, bp
        shl     bx, 1
        mov     di, [rowtab+bx]
        add     di, [ux0]
        mov     si, bp
        shl     si, 2
        add     si, ubuf
        mov     cx, [uw]
.c4:    mov     al, [si]
        mov     [es:di], al
        inc     si
        inc     di
        loop    .c4
        inc     bp
        jmp     .r4
.r4d:   pop     es
        popa
        ret
.old1:  cmp     dx, 80                  ; DX = byte col, DI = ubuf row, BX = save index
        jae     .ox
        mov     si, dx
        sub     si, [ux0]
        cmp     si, [uw]
        jae     .ox
        add     si, di
        mov     al, [cur_save+bx]
        mov     [si], al
.ox:    ret

hide_cursor:
        cmp     byte [curvis], 0
        je      .x
        pusha
        push    es
        push    VSEG
        pop     es
        xor     si, si
.row:   mov     bx, [cur_y]
        add     bx, si
        cmp     bx, 400
        jae     .done
        shl     bx, 1
        mov     di, [rowtab+bx]
        add     di, [cur_xb]
        mov     bx, si
        shl     bx, 1
        mov     al, [cur_save+bx]
        mov     [es:di], al
        cmp     word [cur_xb], 79
        jae     .nx
        mov     al, [cur_save+bx+1]
        mov     [es:di+1], al
.nx:    inc     si
        cmp     si, 13
        jb      .row
.done:  mov     byte [curvis], 0
        pop     es
        popa
.x:     ret

; =====================================================================
;  drawing primitives (mode 40h: 640x400, 4 interleaved banks of 100 rows)
; =====================================================================
mkrows: xor     bx, bx
        mov     di, rowtab
.l:     mov     ax, bx
        and     ax, 3
        shl     ax, 13
        mov     dx, bx
        shr     dx, 2
        imul    dx, dx, 80
        add     ax, dx
        mov     [di], ax
        add     di, 2
        inc     bx
        cmp     bx, 400
        jb      .l
        ret

; mode 40h; CF if the panel doesn't have it
hires:  push    ax
        mov     ax, 0040h
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
        pop     ax
        stc
        ret
.ok:    pop     ax
        clc
        ret

api_cls:
        mov     byte [title_on], 0
clear_screen:
        push    cx
        push    di
        push    ax
        push    es
        push    VSEG
        pop     es
        xor     di, di
        mov     cx, 16384
        xor     ax, ax
        rep     stosw
        pop     es
        pop     ax
        pop     di
        pop     cx
        ret

; DX = y, CX = rows, BX = byte column, BP = width in bytes, AL = value
fill_band:
        pusha
        call    clip_rows
        jz      .none
        push    es
        push    VSEG
        pop     es
.r:     mov     si, dx
        shl     si, 1
        mov     di, [rowtab+si]
        add     di, bx
        push    cx
        mov     cx, bp
        rep     stosb
        pop     cx
        inc     dx
        loop    .r
        pop     es
.none:  popa
        ret

; DX = y, CX = rows: CX cut to the screen's 400 rows (ZF: none left).
; (A count of 0 would make LOOP run 65,536 times.)
clip_rows:
        cmp     dx, 400
        jae     .none
        push    ax
        mov     ax, 400
        sub     ax, dx
        cmp     cx, ax
        jbe     .ok
        mov     cx, ax
.ok:    pop     ax
        test    cx, cx
        ret
.none:  xor     cx, cx                  ; (ZF set)
        ret

; DX = y, CX = rows, BX = byte column, BP = width: invert
invert_band:
        pusha
        test    bp, bp
        jz      .none
        call    clip_rows
        jz      .none
        push    es
        push    VSEG
        pop     es
.r:     mov     si, dx
        shl     si, 1
        mov     di, [rowtab+si]
        add     di, bx
        push    cx
        mov     cx, bp
.c:     not     byte [es:di]
        inc     di
        loop    .c
        pop     cx
        inc     dx
        loop    .r
        pop     es
.none:  popa
        ret

; DX = y, BX = byte column, CX = width in bytes
hline:  pusha
        mov     bp, cx
        mov     cx, 1
        mov     al, 0FFh
        call    fill_band
        popa
        ret

; dotted rule: DX = y, BX = column, CX = width
hline_dots:
        pusha
        mov     bp, cx
        mov     cx, 1
        mov     al, 0AAh
        call    fill_band
        popa
        ret

; AX = pixel x, DX = y0, CX = height
vline:  pusha
        call    clip_rows
        jz      .none
        push    es
        push    VSEG
        pop     es
        mov     bx, ax
        shr     bx, 3
        and     al, 7
        mov     ah, 80h
        push    cx
        mov     cl, al
        shr     ah, cl
        pop     cx
.r:     mov     si, dx
        shl     si, 1
        mov     di, [rowtab+si]
        or      [es:di+bx], ah
        inc     dx
        loop    .r
        pop     es
.none:  popa
        ret

; 1-px frame: BX = col, DX = y, CX = width in bytes, BP = height
box:    pusha
        call    hline
        push    dx
        add     dx, bp
        dec     dx
        call    hline
        pop     dx
        mov     ax, bx
        shl     ax, 3
        mov     di, cx
        mov     cx, bp
        call    vline
        shl     di, 3
        add     ax, di
        dec     ax
        call    vline
        popa
        ret

; AL = char, BX = column, DX = y (multiple of 4), AH = 00 normal / FF inverse
putc:   pusha
        push    es
        push    VSEG
        pop     es
        cmp     al, 32
        jb      .bad
        cmp     al, 127
        jbe     .ok
.bad:   mov     al, '?'
.ok:    mov     cl, ah
        xor     ah, ah
        sub     al, 32
        shl     ax, 4
        add     ax, font
        mov     si, ax
        mov     di, dx
        shl     di, 1
        mov     di, [rowtab+di]
        add     di, bx
        mov     ah, cl
%assign r 0
%rep 16
        lodsb
        xor     al, ah
        mov     [es:di + (r & 3) * 2000h + (r >> 2) * 80], al
%assign r r + 1
%endrep
        pop     es
        popa
        ret

; SI = ASCIIZ, BX = column, DX = y, AH = mask.  Returns SI past the NUL.
puts:
api_puts:
        push    bx
        push    ax
.l:     lodsb
        or      al, al
        jz      .x
        cmp     bx, 80
        jae     .l
        call    putc
        inc     bx
        jmp     .l
.x:     pop     ax
        pop     bx
        ret

; SI = text, CX = count, BX = column, DX = y, AH = mask.  The row's
; blitter: the screen segment and the cell address set up once.
putsn:  pusha
        push    es
        mov     bp, 80                  ; clipped at the right edge
        sub     bp, bx
        jbe     .x
        cmp     cx, bp
        jbe     .n
        mov     cx, bp
.n:     jcxz    .x
        mov     bp, ax                  ; (BP high byte: the mask)
        mov     di, dx
        shl     di, 1
        mov     di, [rowtab+di]
        add     di, bx
        push    VSEG
        pop     es
        jmp     .l
.x:     pop     es
        popa
        ret
.l:     lodsb
        cmp     al, 32
        jb      .bad
        cmp     al, 127
        jbe     .ok
.bad:   mov     al, '?'
.ok:    push    si
        xor     ah, ah
        sub     al, 32
        shl     ax, 4
        add     ax, font
        mov     si, ax
        mov     ax, bp
%assign r 0
%rep 16
        lodsb
        xor     al, ah
        mov     [es:di + (r & 3) * 2000h + (r >> 2) * 80], al
%assign r r + 1
%endrep
        pop     si
        inc     di
        dec     cx
        jz      .x
        jmp     .l

strlen: push    si                      ; SI -> CX = length
        push    ax
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .x
        inc     cx
        jmp     .l
.x:     pop     ax
        pop     si
        ret

; SI = text, DX = y, AH = mask: centred
api_center:
        push    bx
        push    cx
        push    si
        call    strlen
        mov     bx, 80
        sub     bx, cx
        sar     bx, 1
        jns     .p
        xor     bx, bx
.p:     call    puts
        pop     si
        pop     cx
        pop     bx
        ret

center: xor     ah, ah                  ; SI = text, DX = y (normal)
        jmp     api_center

; =====================================================================
;  text builders: append at DI
; =====================================================================
sb_str: lodsb                           ; (internal: SI past the NUL, AL = 0)
        or      al, al
        jz      .x
        stosb
        jmp     sb_str
.x:     ret

api_sbstr:
        push    si
        push    ax
        call    sb_str
        pop     ax
        pop     si
        ret

api_sbu16:
        push    ax
        push    cx
        xor     cx, cx
        call    sb_u32
        pop     cx
        pop     ax
        ret

api_sbu32:
        push    ax
        push    cx
        call    sb_u32
        pop     cx
        pop     ax
        ret

sb_u16: xor     cx, cx                  ; AX unsigned (internal: AX, CX change)
sb_u32: push    bx                      ; CX:AX unsigned
        push    dx
        push    si
        mov     si, sp
        mov     bx, 10
.d:     push    ax
        mov     ax, cx
        xor     dx, dx
        div     bx
        mov     cx, ax
        pop     ax
        div     bx
        push    dx
        mov     dx, cx
        or      dx, ax
        jnz     .d
.p:     cmp     sp, si
        je      .x
        pop     ax
        add     al, '0'
        stosb
        jmp     .p
.x:     pop     si
        pop     dx
        pop     bx
        ret

sb_2d:  aam                             ; AL (0..99) as two digits
        xchg    al, ah
        add     ax, '00'
        stosw
        ret

; AX = DOS date -> "4-Oct-26" (internal: AX, CX change)
sb_date:
        push    ax
        and     ax, 1Fh
        call    sb_u16
        mov     al, '-'
        stosb
        pop     ax
        push    ax
        shr     ax, 5
        and     ax, 0Fh
        dec     ax
        cmp     ax, 11
        jbe     .m
        xor     ax, ax
.m:     push    si
        imul    si, ax, 3
        add     si, months
        movsw
        movsb
        pop     si
        mov     al, '-'
        stosb
        pop     ax
        shr     ax, 9
        add     ax, 80
        cmp     ax, 100
        jb      .y
        sub     ax, 100
.y:     jmp     sb_2d

api_sbdate:
        push    ax
        push    cx
        call    sb_date
        pop     cx
        pop     ax
        ret

; AX = DOS time -> "9:41 pm"
api_sbtime:
        push    ax
        push    bx
        push    cx
        push    si
        mov     bx, ax
        shr     ax, 11                  ; hours
        mov     si, s_am
        cmp     ax, 12
        jb      .am
        mov     si, s_pm
        sub     ax, 12
.am:    or      ax, ax
        jnz     .h
        mov     ax, 12
.h:     call    sb_u16
        mov     al, ':'
        stosb
        mov     ax, bx
        shr     ax, 5
        and     ax, 3Fh
        call    sb_2d
        call    sb_str
        pop     si
        pop     cx
        pop     bx
        pop     ax
        ret

sb_hex4:                                ; AX as 4 hex digits at DI
        push    cx
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
        pop     cx
        ret

api_sbhex4:
        jmp     sb_hex4

; AX = DOS error -> its message at DI.  83 (failed on a critical error)
; says what the disk said instead.
api_sberr:
        push    ax
        push    bx
        push    si
        mov     bx, ax
        mov     si, dos_msgs
        cmp     bx, 83
        jne     .chk
        mov     ax, [crit_err]
        or      ax, ax
        jz      .chk
        mov     bx, ax
        mov     si, crit_msgs
.chk:   or      bh, bh                  ; (the tables hold codes under 256)
        jnz     .other
.find:  mov     al, [si]
        cmp     al, 0FFh
        je      .other
        inc     si
        cmp     al, bl
        je      .hit
.skip:  lodsb
        or      al, al
        jnz     .skip
        jmp     .find
.hit:   call    sb_str
        jmp     .x
.other: mov     si, s_err
        call    sb_str
        mov     ax, bx
        push    cx
        call    sb_u16
        pop     cx
.x:     pop     si
        pop     bx
        pop     ax
        ret

; =====================================================================
;  clock (RTC through INT 1Ah) and the title bar
; =====================================================================
read_clock:
        pusha
        mov     ah, 2
        int     1Ah
        mov     [rtc_h], ch
        mov     [rtc_m], cl
        mov     ah, 4
        int     1Ah
        mov     [rtc_y], cl
        mov     [rtc_mo], dh
        mov     [rtc_d], dl
        popa
        ret

clock_tick:
        cmp     byte [title_on], 0
        je      .x
        push    ax
        mov     al, [rtc_m]
        call    read_clock
        cmp     al, [rtc_m]
        pop     ax
        je      .x
        call    hide_cursor
        call    draw_clock
        call    ptr_restore
.x:     ret

draw_clock:
        pusha
        mov     dx, 0
        mov     cx, 16
        mov     bx, 1
        mov     bp, 11
        xor     al, al
        call    fill_band
        mov     bx, 67
        call    fill_band
        mov     di, tmp
        call    sb_dmy
        mov     si, tmp
        mov     bx, 1
        xor     dx, dx
        xor     ah, ah
        call    puts
        mov     di, tmp
        call    sb_hm
        mov     si, tmp
        call    strlen
        mov     bx, 79
        sub     bx, cx
        xor     dx, dx
        xor     ah, ah
        call    puts
        popa
        ret

; "4-Oct-26" at DI (NUL-terminated)
sb_dmy: mov     al, [rtc_d]
        call    bcd
        call    sb_u16
        mov     al, '-'
        stosb
        mov     al, [rtc_mo]
        call    bcd
        dec     ax
        cmp     ax, 11
        jbe     .mo
        xor     ax, ax
.mo:    imul    si, ax, 3
        add     si, months
        movsw
        movsb
        mov     al, '-'
        stosb
        mov     al, [rtc_y]
        call    bcd
        call    sb_2d
        mov     byte [di], 0
        ret

; "5:31 pm" at DI (NUL-terminated)
sb_hm:  mov     al, [rtc_h]
        call    bcd
        mov     si, s_am
        cmp     ax, 12
        jb      .am
        mov     si, s_pm
        sub     ax, 12
.am:    or      ax, ax
        jnz     .h
        mov     ax, 12
.h:     push    si
        call    sb_u16
        mov     al, ':'
        stosb
        mov     al, [rtc_m]
        call    bcd
        call    sb_2d
        pop     si
        call    sb_str
        mov     byte [di], 0
        ret

bcd:    mov     ah, al                  ; AL = BCD -> AX = binary
        shr     ah, 4
        and     al, 0Fh
        aad
        xor     ah, ah
        ret

; UI_SCREEN: SI = title
ui_screen:
        pusha
        call    hide_cursor
        mov     [title_ptr], si
        mov     byte [title_on], 1
        call    clear_screen
        call    read_clock
        call    draw_clock
        mov     si, [title_ptr]
        xor     dx, dx
        call    center
        mov     dx, 19
        xor     bx, bx
        mov     cx, 80
        call    hline
        popa
        ret

; =====================================================================
;  the prompt band (two inverse lines at the bottom)
; =====================================================================
; UI_BAND: SI = line 1, DI = line 2 (0 = blank)
ui_band:
        mov     [band1], si
        mov     [band2], di
band_redraw:
        pusha
        call    hide_cursor
        mov     dx, BAND_Y
        mov     cx, 400 - BAND_Y
        xor     bx, bx
        mov     bp, 80
        mov     al, 0FFh
        call    fill_band
        mov     ah, 0FFh
        mov     si, [band1]
        or      si, si
        jz      .l2
        mov     dx, BAND_Y + 4
        call    api_center
.l2:    mov     si, [band2]
        or      si, si
        jz      .x
        mov     dx, BAND_Y + 20
        call    api_center
.x:     popa
        ret

; UI_MSG: SI = message until a key or click -> AX = it
ui_msg: push    word [band1]
        push    word [band2]
        push    word [held1]
        push    word [held2]
        push    di
        mov     di, s_anykey
        call    ui_band
        call    hold_band
        call    ui_event
        pop     di
        pop     word [held2]
        pop     word [held1]
        pop     word [band2]
        pop     word [band1]
        jmp     band_redraw

; the band on screen now is a question's (or a form's, a message's): the
; screen saver's redraw puts it back.  The caller saves held1/2 before
; and restores them after
hold_band:
        push    ax
        mov     ax, [band1]
        mov     [held1], ax
        mov     ax, [band2]
        mov     [held2], ax
        pop     ax
        ret

; UI_ASK: SI = line 1.  CF clear: Return (or a click on the band); CF: ESC
ui_ask: push    ax
        push    bx
        push    cx
        push    di
        push    word [band1]
        push    word [band2]
        push    word [held1]
        push    word [held2]
        mov     di, s_confirm
        call    ui_band
        call    hold_band
.l:     call    ui_event
        cmp     ax, K_ENTER
        je      .yes
        cmp     ax, K_CODE_ENTER
        je      .yes
        cmp     ax, K_ESC
        je      .no
        cmp     ax, EV_CLICK
        jne     .l
        cmp     cx, BAND_Y
        jae     .yes
        jmp     .l
.yes:   clc
        jmp     .x
.no:    stc
.x:     pop     word [held2]
        pop     word [held1]
        pop     word [band2]
        pop     word [band1]
        pushf
        call    band_redraw
        popf
        pop     di
        pop     cx
        pop     bx
        pop     ax
        ret

ui_beep:
        pusha
        in      al, 61h
        push    ax
        mov     al, 0B6h                ; PIT channel 2: square wave
        out     43h, al
        mov     ax, 1193                ; 1 kHz
        out     42h, al
        mov     al, ah
        out     42h, al
        pop     ax
        push    ax
        or      al, 3
        out     61h, al
        mov     cx, 2
        call    wait_ticks
        pop     ax
        out     61h, al
        popa
        ret

; =====================================================================
;  windows (save-under in the disk cache's memory while any is open)
; =====================================================================
; UI_WOPEN: SI = window
ui_wopen:
        pusha
        call    hide_cursor
        mov     bx, [wdepth]
        cmp     bx, NWIN
        jb      .ok
        inc     word [wover]            ; (too deep: not drawn, but counted)
        jmp     .x
.ok:
        or      bx, bx
        jnz     .have
        mov     word [wseg], 0          ; the first window borrows the cache
        mov     word [wtop], 0
%ifndef NOTC
        push    es
        mov     ax, 0F002h
        int     21h
        jc      .nolend
        mov     [wseg], es
        mov     [wcap], cx
.nolend:
        pop     es
%endif
.have:  mov     ax, [si+W_W]            ; bytes needed
        mul     word [si+W_H]
        mov     cx, ax
        mov     di, 0FFFFh              ; (not saved)
        cmp     word [wseg], 0
        je      .push
        mov     ax, [wtop]
        add     ax, cx
        jc      .push
        cmp     ax, [wcap]
        ja      .push
        mov     di, [wtop]
        mov     [wtop], ax
        call    win_save                ; SI = window, DI = where
.push:  mov     bx, [wdepth]
        shl     bx, 2
        mov     [wstack+bx], si
        mov     [wstack+bx+2], di
        inc     word [wdepth]
        call    win_paint
.x:     popa
        ret

; copy the screen under window SI to wseg:DI
win_save:
        pusha
        push    ds
        push    es
        mov     es, [wseg]
        mov     dx, [si+W_Y]
        mov     cx, [si+W_H]
        mov     bp, [si+W_W]
        mov     ax, [si+W_COL]
.r:     mov     bx, dx
        shl     bx, 1
        mov     si, [rowtab+bx]
        add     si, ax
        push    cx
        push    ds
        push    VSEG
        pop     ds
        mov     cx, bp
        rep     movsb
        pop     ds
        pop     cx
        inc     dx
        loop    .r
        pop     es
        pop     ds
        popa
        ret

; draw window SI: blank body, title strip, frame, then its contents
win_paint:
        pusha
        mov     dx, [si+W_Y]
        mov     cx, [si+W_H]
        mov     bx, [si+W_COL]
        mov     bp, [si+W_W]
        xor     al, al
        call    fill_band
        cmp     word [si+W_TITLE], 0
        je      .notitle
        mov     cx, 20                  ; title strip
        mov     al, 0FFh
        call    fill_band
        push    si
        mov     si, [si+W_TITLE]
        add     bx, 2
        add     dx, 4
        mov     ah, 0FFh
        call    puts
        pop     si
        jmp     .frame
.notitle:
        mov     cx, bp
        call    hline
.frame: mov     dx, [si+W_Y]            ; bottom and sides
        add     dx, [si+W_H]
        dec     dx
        mov     bx, [si+W_COL]
        mov     cx, [si+W_W]
        call    hline
        mov     ax, [si+W_COL]
        shl     ax, 3
        mov     dx, [si+W_Y]
        mov     cx, [si+W_H]
        call    vline
        mov     bx, [si+W_W]
        shl     bx, 3
        add     ax, bx
        dec     ax
        call    vline
        mov     ax, [si+W_DRAW]
        or      ax, ax
        jz      .x
        mov     bx, si
        call    ax
.x:     popa
        ret

; UI_WCLOSE
ui_wclose:
        pusha
        call    hide_cursor
        cmp     word [wover], 0
        je      .real
        dec     word [wover]
        jmp     .x
.real:  mov     bx, [wdepth]
        or      bx, bx
        jz      .x
        dec     bx
        mov     [wdepth], bx
        shl     bx, 2
        mov     si, [wstack+bx]
        mov     di, [wstack+bx+2]
        cmp     di, 0FFFFh
        je      .redraw
        mov     [wtop], di
        push    ds
        push    es
        push    VSEG
        pop     es
        mov     dx, [si+W_Y]
        mov     cx, [si+W_H]
        mov     bp, [si+W_W]
        mov     ax, [si+W_COL]
        mov     si, di
        mov     ds, [wseg]
.r:     mov     bx, dx
        shl     bx, 1
        mov     di, [cs:rowtab+bx]
        add     di, ax
        push    cx
        mov     cx, bp
        rep     movsb
        pop     cx
        inc     dx
        loop    .r
        pop     es
        pop     ds
        jmp     .done
.redraw:
        call    redraw_all              ; (nothing saved: draw it all again)
.done:  cmp     word [wdepth], 0
        jne     .x
        call    win_giveback
.x:     popa
        ret

win_giveback:
        cmp     word [wseg], 0
        je      .x
        mov     word [wseg], 0
%ifndef NOTC
        push    ax
        mov     ax, 0F003h              ; the disk cache has it back
        int     21h
        pop     ax
%endif
.x:     ret

; UI_HELP: SI = key table, DI = title.  A window with the table's help
; lines; the next key or click closes it.
ui_help:
        pusha
        mov     [help_tab], si
        mov     [help_w+W_TITLE], di
        xor     dx, dx                  ; lines
        xor     bp, bp                  ; longest
.c:     cmp     word [si], 0
        je      .sized
        mov     ax, [si+4]
        or      ax, ax
        jz      .n
        inc     dx
        push    si
        mov     si, ax
        call    strlen
        pop     si
        cmp     cx, bp
        jbe     .n
        mov     bp, cx
.n:     add     si, 6
        jmp     .c
.sized: push    si
        mov     si, di                  ; the title is a line too, of sorts
        call    strlen
        pop     si
        cmp     cx, bp
        jbe     .t
        mov     bp, cx
.t:     add     bp, 6
        cmp     bp, 78
        jbe     .w
        mov     bp, 78
.w:     mov     [help_w+W_W], bp
        mov     ax, 80
        sub     ax, bp
        shr     ax, 1
        mov     [help_w+W_COL], ax
        cmp     dx, 18                  ; (18 lines fill SCR_TOP..BAND_Y)
        jbe     .h
        mov     dx, 18
.h:     shl     dx, 4
        add     dx, W_TOP + 12
        mov     [help_w+W_H], dx
        mov     ax, BAND_Y - SCR_TOP    ; centred between the title rule and
        sub     ax, dx                  ;  the band
        shr     ax, 1
        and     ax, 0FFFCh
        add     ax, SCR_TOP
        mov     [help_w+W_Y], ax
        mov     word [help_w+W_DRAW], help_draw
        mov     si, help_w
        call    ui_wopen
        call    ui_event
        call    ui_wclose
        popa
        ret

help_draw:
        mov     si, [help_tab]
        mov     dx, [bx+W_Y]
        add     dx, W_TOP + 4
        mov     cx, [bx+W_H]
        add     cx, [bx+W_Y]
        sub     cx, 16
        mov     bx, [bx+W_COL]
        add     bx, 3
.l:     cmp     word [si], 0
        je      .x
        cmp     dx, cx
        ja      .x
        mov     ax, [si+4]
        add     si, 6
        or      ax, ax
        jz      .l
        push    si
        mov     si, ax
        xor     ah, ah
        call    puts
        pop     si
        add     dx, 16
        jmp     .l
.x:     ret

; =====================================================================
;  key tables
; =====================================================================
; UI_DISPATCH: SI = table, AX = key -> the handler runs (CF clear), or CF
ui_dispatch:
        push    si
        push    dx
.l:     mov     dx, [si]
        or      dx, dx
        jz      .no
        cmp     dx, K_NONE
        je      .n
        or      dl, dl
        jnz     .ascii
        or      al, al                  ; by scan code: AL must be 0 or E0h
        jz      .scan
        cmp     al, 0E0h
        jne     .n
.scan:  cmp     dh, ah
        je      .hit
        jmp     .n
.ascii: cmp     dl, al
        je      .hit
.n:     add     si, 6
        jmp     .l
.no:    pop     dx
        pop     si
        stc
        ret
.hit:   mov     dx, [si+2]
        mov     [disp_fn], dx
        pop     dx
        pop     si
        call    [disp_fn]
        clc
        ret

; =====================================================================
;  list view (rows of 16 pixels; BX = the list)
; =====================================================================
lv_draw:
        pusha
        mov     [lv_cur], bx
        mov     cx, [bx+LV_ROWS]
        mov     ax, [bx+LV_TOP]
.l:     push    ax
        push    cx
        call    lv_row
        pop     cx
        pop     ax
        inc     ax
        loop    .l
        popa
        ret

; draw item AX of list [lv_cur] if it is showing
lv_row: mov     bx, [lv_cur]
        mov     dx, ax
        sub     dx, [bx+LV_TOP]
        jb      .x
        cmp     dx, [bx+LV_ROWS]
        jae     .x
        shl     dx, 4
        add     dx, [bx+LV_Y]
        xor     cl, cl
        cmp     ax, [bx+LV_SEL]
        jne     .f
        cmp     word [bx+LV_N], 0
        je      .f
        mov     cl, 0FFh
.f:     push    ax
        push    cx
        mov     al, cl
        mov     cx, 16
        mov     bp, [bx+LV_W]
        mov     bx, [bx+LV_COL]
        call    fill_band
        pop     cx
        pop     ax
        mov     bx, [lv_cur]
        cmp     ax, [bx+LV_N]
        jae     .x
        push    word [lv_cur]
        call    [bx+LV_DRAW]
        pop     word [lv_cur]
.x:     ret

; UI_LVKEY: BX = list, AX = key -> CF set if not a list key
lv_key: pusha
        mov     [lv_cur], bx
        mov     cx, ax                  ; (the cursor keys by scan code alone,
        mov     ax, -1                  ;  so the keypad's work with NumLock)
        cmp     ch, K_UP >> 8
        je      .mv
        mov     ax, 1
        cmp     ch, K_DOWN >> 8
        je      .mv
        mov     ax, [bx+LV_ROWS]
        cmp     ch, K_PGDN >> 8
        je      .mv
        neg     ax
        cmp     ch, K_PGUP >> 8
        je      .mv
        mov     ax, -30000
        cmp     ch, K_HOME >> 8
        je      .mv
        mov     ax, 30000
        cmp     ch, K_END >> 8
        je      .mv
        cmp     word [bx+LV_NAME], 0    ; a letter: the next name starting with it
        je      .no
        cmp     cl, '0'
        jb      .no
        cmp     cl, 'z'
        ja      .no
        call    lv_find
        jmp     .yes
.mv:    call    lv_move
.yes:   popa
        clc
        ret
.no:    popa
        stc
        ret

; AX = signed delta for list [lv_cur]
lv_move:
        mov     bx, [lv_cur]
        mov     cx, [bx+LV_N]
        jcxz    .x
        add     ax, [bx+LV_SEL]
        jns     .p
        xor     ax, ax
.p:     cmp     ax, cx
        jb      .in
        mov     ax, cx
        dec     ax
.in:    jmp     lv_setsel
.x:     ret

; CL = a letter: select the next item whose name starts with it
lv_find:
        mov     bx, [lv_cur]
        and     cl, 0DFh                ; (upper case)
        mov     dx, [bx+LV_N]
        or      dx, dx
        jz      .x
        mov     ax, [bx+LV_SEL]
.l:     inc     ax
        cmp     ax, [bx+LV_N]
        jb      .t
        xor     ax, ax
.t:     cmp     ax, [bx+LV_SEL]
        je      .x                      ; (round and back: none)
        push    ax
        push    bx
        push    cx
        push    dx
        call    [bx+LV_NAME]
        pop     dx
        pop     cx
        pop     bx
        mov     ch, [si]
        and     ch, 0DFh
        cmp     ch, cl
        pop     ax
        je      lv_setsel
        dec     dx
        jnz     .l
.x:     ret

; UI_LVSET: BX = list, AX = item
lv_set: pusha
        mov     [lv_cur], bx
        call    lv_setsel
        popa
        ret

; select item AX of list [lv_cur]: redraw what changed, then LV_CHG
lv_setsel:
        mov     bx, [lv_cur]
        cmp     ax, [bx+LV_N]
        jae     .x
        mov     dx, [bx+LV_SEL]
        cmp     ax, dx
        je      .x
        mov     [bx+LV_SEL], ax
        mov     cx, [bx+LV_TOP]
        cmp     ax, cx
        jb      .up
        add     cx, [bx+LV_ROWS]
        cmp     ax, cx
        jae     .dn
        push    ax
        mov     ax, dx
        call    lv_row
        pop     ax
        call    lv_row
        jmp     .chg
.up:    mov     [bx+LV_TOP], ax
        jmp     .full
.dn:    sub     ax, [bx+LV_ROWS]
        inc     ax
        mov     [bx+LV_TOP], ax
.full:  call    lv_draw
.chg:   mov     bx, [lv_cur]
        mov     ax, [bx+LV_CHG]
        or      ax, ax
        jz      .x
        push    bx
        call    ax
        pop     bx
        mov     [lv_cur], bx
.x:     ret

; UI_LVCLICK: BX = list, CX = y -> CF outside; AL = 1 the selected row again
lv_click:
        push    ax
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    bp
        mov     [lv_cur], bx
        mov     ax, cx
        sub     ax, [bx+LV_Y]
        jb      .out
        shr     ax, 4
        cmp     ax, [bx+LV_ROWS]
        jae     .out
        add     ax, [bx+LV_TOP]
        cmp     ax, [bx+LV_N]
        jae     .out
        cmp     ax, [bx+LV_SEL]
        je      .again
        call    lv_setsel
        xor     ax, ax                  ; (AX, not just AL: AH was the
        jmp     .in                     ;  row's high byte)
.again: mov     ax, 1
.in:    pop     bp
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        add     sp, 2                   ; (AL is the answer)
        clc
        ret
.out:   pop     bp
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        stc
        ret

; =====================================================================
;  the line editor
; =====================================================================
; UI_EDIT: SI = buffer, BP = most chars, BX = col, DX = y, CX = width
; -> AX = the key that ended it, or EV_CLICK (BX = x, CX = y)
ui_edit:
        mov     byte [ed_keep], 0
ed_enter:                               ; (ui_form, back in the same field:
        push    bx                      ;  [ed_keep] = 1 goes on where it was)
        push    cx
        push    si
        push    di
        push    dx
        push    bp
        mov     [ed_buf], si
        mov     [ed_max], bp
        mov     [ed_col], bx
        mov     [ed_y], dx
        mov     [ed_w], cx
        cmp     byte [ed_keep], 0
        jne     .kept
        call    strlen
        mov     [ed_pos], cx
        mov     word [ed_off], 0
        mov     byte [ed_fresh], 1      ; typing first replaces what is there
.kept:  mov     byte [ed_keep], 0
.l:     call    ed_draw
        call    ed_cursor
        call    ui_event
        call    ed_cursor               ; (off again)
        cmp     ax, EV_CLICK
        je      .out
        cmp     al, 0Dh
        je      .out
        cmp     al, 1Bh
        je      .out
        cmp     al, 09h
        je      .out
        cmp     al, ' '                 ; a character: in it goes
        jb      .key
        cmp     al, 7Eh
        ja      .key
        cmp     byte [ed_fresh], 0
        je      .ins
        mov     si, [ed_buf]            ; (typed first: instead of the old text)
        mov     byte [si], 0
        mov     word [ed_pos], 0
.ins:   mov     byte [ed_fresh], 0
        call    ed_ins
        jmp     .l
.key:   mov     byte [ed_fresh], 0      ; an editing key: edit what is there
        cmp     al, 08h
        je      .bksp
        cmp     ax, K_LEFT
        je      .left
        cmp     ax, K_RIGHT
        je      .right
        cmp     ax, K_HOME
        je      .home
        cmp     ax, K_END
        je      .end
        cmp     ax, K_DEL
        je      .del
        cmp     al, 19h                 ; Ctrl-Y: clear the field
        je      .clear
.ctl:   or      al, al
        jz      .out                    ; any other function key ends it
        cmp     al, 0E0h
        je      .out
        jmp     .l
.bksp:  cmp     word [ed_pos], 0
        je      .l
        dec     word [ed_pos]
.del:   call    ed_del
        jmp     .l
.left:  cmp     word [ed_pos], 0
        je      .l
        dec     word [ed_pos]
        jmp     .l
.right: mov     si, [ed_buf]
        add     si, [ed_pos]
        cmp     byte [si], 0
        je      .l
        inc     word [ed_pos]
        jmp     .l
.home:  mov     word [ed_pos], 0
        jmp     .l
.end:   mov     si, [ed_buf]
        call    strlen
        mov     [ed_pos], cx
        jmp     .l
.clear: mov     si, [ed_buf]
        mov     byte [si], 0
        mov     word [ed_pos], 0
        jmp     .l
.out:   push    ax
        push    word [ed_pos]
        xor     ax, ax                  ; shown from its start again (the
        mov     [ed_pos], ax            ;  cursor is kept for ed_enter)
        mov     [ed_off], ax
        call    ed_draw
        pop     word [ed_pos]
        pop     ax
        pop     bp
        pop     dx
        pop     di
        pop     si
        cmp     ax, EV_CLICK
        je      .click
        pop     cx
        pop     bx
        ret
.click: add     sp, 4                   ; (BX, CX: where the click was)
        ret

; insert AL at the cursor (if there is room)
ed_ins: mov     si, [ed_buf]
        call    strlen
        cmp     cx, [ed_max]
        jae     .x
        mov     di, si
        add     di, cx                  ; DI -> the NUL
        mov     si, [ed_buf]
        add     si, [ed_pos]
.mv:    mov     ah, [di]
        mov     [di+1], ah
        cmp     di, si
        je      .put
        dec     di
        jmp     .mv
.put:   mov     [si], al
        inc     word [ed_pos]
.x:     ret

; delete the character at the cursor
ed_del: mov     di, [ed_buf]
        add     di, [ed_pos]
        cmp     byte [di], 0
        je      .x
.l:     mov     al, [di+1]
        mov     [di], al
        inc     di
        or      al, al
        jnz     .l
.x:     ret

; the field: scrolled so the cursor shows
ed_draw:
        pusha
        mov     ax, [ed_pos]
        cmp     ax, [ed_off]
        jae     .a
        mov     [ed_off], ax
.a:     mov     cx, [ed_w]
        dec     cx
        mov     dx, ax
        sub     dx, [ed_off]
        cmp     dx, cx
        jbe     .b
        sub     ax, cx
        mov     [ed_off], ax
.b:     mov     dx, [ed_y]
        mov     cx, 16
        mov     bx, [ed_col]
        mov     bp, [ed_w]
        xor     al, al
        call    fill_band
        mov     si, [ed_buf]
        call    strlen
        sub     cx, [ed_off]
        jbe     .x
        cmp     cx, [ed_w]
        jbe     .c
        mov     cx, [ed_w]
.c:     add     si, [ed_off]
        xor     ah, ah
        call    putsn
.x:     popa
        ret

ed_cursor:                              ; invert the cell at the cursor
        pusha
        mov     bx, [ed_pos]
        sub     bx, [ed_off]
        add     bx, [ed_col]
        cmp     bx, 80
        jae     .x
        mov     dx, [ed_y]
        mov     cx, 16
        mov     bp, 1
        call    invert_band
.x:     popa
        ret

; =====================================================================
;  forms
; =====================================================================
; UI_FORM: SI = form -> CF set if cancelled
ui_form:
        cmp     word [wdepth], NWIN     ; (no room for its window: it would
        jb      .go                     ;  draw over the others unsaved, so
        call    ui_beep                 ;  it counts as cancelled)
        stc
        ret
.go:    pusha
        push    word [held1]
        push    word [held2]
        mov     [fm_ptr], si
        mov     ax, [band1]
        mov     [fm_b1], ax
        mov     ax, [band2]
        mov     [fm_b2], ax
        mov     ax, [si+F_TITLE]
        mov     [form_w+W_TITLE], ax
        mov     ax, [si+F_W]
        mov     [form_w+W_W], ax
        mov     bx, 80
        sub     bx, ax
        shr     bx, 1
        mov     [form_w+W_COL], bx
        mov     ax, [si+F_N]
        imul    ax, ax, 20
        add     ax, W_TOP + 16
        mov     [form_w+W_H], ax
        mov     word [form_w+W_Y], 96
        mov     word [form_w+W_DRAW], fm_paint
        mov     word [fm_cur], 0
        push    si
        mov     si, form_w
        call    ui_wopen
        pop     si
        mov     di, s_formhelp
        mov     si, [si+F_PROMPT]
        call    ui_band
        call    hold_band
.l:     call    fm_field                ; SI -> field, BX = col, DX = y
        call    fm_line_on
        mov     al, [si+FL_TYPE]
        cmp     al, FT_CHOICE
        je      .choice
        push    si
        mov     cl, [si+FL_TYPE+1]
        xor     ch, ch
        mov     bp, [si+FL_EXTRA]
        mov     si, [si+FL_DATA]
        call    ed_enter
        pop     si
        jmp     .key
.choice:
        call    ui_event
.key:   mov     byte [ed_keep], 0       ; (only .same goes on in the field)
        push    ax
        call    fm_field
        call    fm_line_off
        pop     ax
        cmp     ax, K_ENTER
        je      .next
        cmp     ax, K_CODE_ENTER
        je      .ok
        cmp     ax, K_ESC
        je      .cancel
        cmp     ax, K_TAB
        je      .down
        cmp     ax, K_DOWN
        je      .down
        cmp     ax, K_BTAB
        je      .up
        cmp     ax, K_UP
        je      .up
        cmp     ax, EV_CLICK
        je      .click
        cmp     byte [si+FL_TYPE], FT_CHOICE
        jne     .same                   ; (a key the editor gave back)
        cmp     ax, K_RIGHT
        je      .cnext
        cmp     al, ' '
        je      .cnext
        cmp     ax, K_LEFT
        je      .cprev
        jmp     .l
.next:  mov     ax, [fm_cur]
        inc     ax
        mov     bx, [fm_ptr]
        cmp     ax, [bx+F_N]
        jae     .ok
        mov     [fm_cur], ax
        jmp     .l
.down:  mov     ax, [fm_cur]
        inc     ax
        mov     bx, [fm_ptr]
        cmp     ax, [bx+F_N]
        jb      .set
        xor     ax, ax
.set:   mov     [fm_cur], ax
        jmp     .l
.up:    mov     ax, [fm_cur]
        or      ax, ax
        jnz     .u1
        mov     bx, [fm_ptr]
        mov     ax, [bx+F_N]
.u1:    dec     ax
        jmp     .set
.cnext: call    fm_choice_count         ; CX = options
        mov     bx, [si+FL_DATA]
        mov     al, [bx]
        inc     al
        cmp     al, cl
        jb      .cset
        xor     al, al
.cset:  mov     [bx], al
        call    fm_field
        call    fm_value
        jmp     .l
.cprev: call    fm_choice_count
        mov     bx, [si+FL_DATA]
        mov     al, [bx]
        or      al, al
        jnz     .cp1
        mov     al, cl
.cp1:   dec     al
        jmp     .cset
.click: cmp     cx, BAND_Y              ; the band: confirm
        jae     .ok
        mov     ax, cx                  ; a field's row: go there
        sub     ax, [form_w+W_Y]
        jb      .same                   ; (above the window: both borrows
        sub     ax, W_TOP + 2           ;  matter, or DIV below faults)
        jb      .same
        mov     dl, 20
        div     dl
        xor     ah, ah
        mov     bx, [fm_ptr]
        cmp     ax, [bx+F_N]
        jae     .same
        cmp     ax, [fm_cur]
        jne     .set
        cmp     byte [si+FL_TYPE], FT_CHOICE
        je      .cnext                  ; clicking a choice again: the next one
.same:  mov     byte [ed_keep], 1       ; back to the same field, as it was
        jmp     .l
.ok:    clc
        jmp     short .end
.cancel:
        stc
.end:   pop     word [held2]            ; (POP and POPA keep the flags)
        pop     word [held1]
        pushf
        call    ui_wclose
        mov     si, [fm_b1]
        mov     di, [fm_b2]
        call    ui_band
        popf
        popa
        ret

; field [fm_cur] -> SI = it, BX = value column, DX = its y
fm_field:
        mov     bx, [fm_ptr]
        mov     ax, [fm_cur]
fm_field_ax:
        mov     si, ax
        shl     si, 3
        add     si, bx
        add     si, F_FIELDS
        imul    dx, ax, 20
        add     dx, [form_w+W_Y]
        add     dx, W_TOP + 4
        mov     ax, [bx+F_LW]
        mov     bx, [form_w+W_COL]
        add     bx, ax
        add     bx, 3
        ret

; the outline round field SI's value: on, off (XOR, so it keeps count:
; a repaint of the window clears it)
fm_line_on:
        cmp     byte [fm_lined], 0
        jne     .x
        mov     byte [fm_lined], 1
        jmp     fm_outline
.x:     ret
fm_line_off:
        cmp     byte [fm_lined], 0
        je      .x
        mov     byte [fm_lined], 0
        jmp     fm_outline
.x:     ret

fm_outline:
        pusha
        mov     cl, [si+FL_TYPE+1]      ; text: its width
        xor     ch, ch
        cmp     byte [si+FL_TYPE], FT_CHOICE
        jne     .w
        mov     cx, [fm_ptr]
        mov     cx, [form_w+W_W]
        add     cx, [form_w+W_COL]
        sub     cx, bx
        sub     cx, 2
.w:     mov     ax, bx                  ; x0 = col * 8 - 3, x1 = (col + w) * 8 + 2
        shl     ax, 3
        sub     ax, 3
        mov     di, bx
        add     di, cx
        shl     di, 3
        add     di, 2
        sub     dx, 3                   ; y0 = y - 3, y1 = y + 18
        call    .h
        add     dx, 21
        call    .h
        sub     dx, 21
        mov     cx, 22
        call    .v
        mov     ax, di
        call    .v
        popa
        ret
.h:     push    ax                      ; XOR pixels AX..DI on row DX
.hl:    call    .px
        inc     ax
        cmp     ax, di
        jbe     .hl
        pop     ax
        ret
.v:     push    dx                      ; XOR pixels at column AX, rows DX..DX+CX-1
        push    cx
        inc     dx                      ; (the corners belong to .h)
        sub     cx, 2
.vl:    call    .px
        inc     dx
        loop    .vl
        pop     cx
        pop     dx
        ret
.px:    push    ax
        push    bx
        push    cx
        push    es
        push    VSEG
        pop     es
        mov     bx, dx
        shl     bx, 1
        mov     bx, [rowtab+bx]
        mov     cx, ax
        shr     ax, 3
        add     bx, ax
        and     cl, 7
        mov     al, 80h
        shr     al, cl
        xor     [es:bx], al
        pop     es
        pop     cx
        pop     bx
        pop     ax
        ret

; field SI's value at BX, DX
fm_value:
        pusha
        push    si
        push    bx
        push    dx
        mov     ax, [form_w+W_COL]      ; blank to the window's inner edge
        add     ax, [form_w+W_W]
        sub     ax, bx
        dec     ax
        mov     bp, ax
        mov     cx, 16
        xor     al, al
        call    fill_band
        pop     dx
        pop     bx
        pop     si
        cmp     byte [si+FL_TYPE], FT_CHOICE
        je      .ch
        mov     al, [si+FL_TYPE+1]      ; text: as much as the field shows
        xor     ah, ah
        mov     si, [si+FL_DATA]
        call    strlen
        cmp     cx, ax
        jbe     .t
        mov     cx, ax
.t:     xor     ah, ah
        call    putsn
        popa
        ret
.ch:    mov     di, [si+FL_DATA]
        mov     al, [di]
        mov     [fm_sel], al
        mov     byte [fm_opt], 0
        mov     si, [si+FL_EXTRA]
.o:     cmp     byte [si], 0
        je      .x
        xor     ah, ah
        mov     al, [fm_opt]
        cmp     al, [fm_sel]
        jne     .p
        mov     ah, 0FFh
.p:     mov     al, ' '
        call    putc
        inc     bx
        call    strlen
        call    puts                    ; (SI past its NUL)
        add     bx, cx
        mov     al, ' '
        call    putc
        add     bx, 2
        inc     byte [fm_opt]
        jmp     .o
.x:     popa
        ret

; CX = number of options of choice field SI
fm_choice_count:
        push    si
        xor     cx, cx
        mov     si, [si+FL_EXTRA]
.l:     cmp     byte [si], 0
        je      .x
        inc     cx
.s:     lodsb
        or      al, al
        jnz     .s
        jmp     .l
.x:     pop     si
        ret

; window contents: every label and value
fm_paint:
        mov     byte [fm_lined], 0
        xor     ax, ax
.l:     mov     bx, [fm_ptr]
        cmp     ax, [bx+F_N]
        jae     .x
        push    ax
        call    fm_field_ax
        push    bx
        mov     ax, [form_w+W_COL]
        add     ax, 2
        mov     bx, ax
        push    si
        mov     si, [si+FL_LABEL]
        xor     ah, ah
        call    puts
        pop     si
        pop     bx
        call    fm_value
        pop     ax
        inc     ax
        jmp     .l
.x:     ret

; =====================================================================
;  memory and programs
; =====================================================================
; UI_ALLOC: BX = paragraphs -> AX = segment, CF (BX = largest)
ui_alloc:
        push    si
        mov     ah, 48h
        int     21h
        jc      .x
        mov     si, alloc_tab
.l:     cmp     word [si], 0
        je      .put
        add     si, 2
        cmp     si, alloc_tab + 2 * NALLOC
        jb      .l
        push    es                      ; table full: it couldn't be freed
        mov     es, ax                  ;  for the program when it ends, so
        mov     ah, 49h                 ;  it doesn't get it
        int     21h
        pop     es
        mov     ax, 8
        stc
        jmp     .x
.put:   mov     [si], ax
.ok:    clc
.x:     pop     si
        ret

; UI_FREE: ES = block
ui_free:
        push    ax
        push    si
        mov     ax, es
        mov     si, alloc_tab
.l:     cmp     [si], ax
        jne     .n
        mov     word [si], 0
.n:     add     si, 2
        cmp     si, alloc_tab + 2 * NALLOC
        jb      .l
        mov     ah, 49h
        int     21h
        pop     si
        pop     ax
        ret

; after a .RUN (or when the root starts over): free what it left, close
; its windows, give the cache back, shrink the UI block to its own size
run_cleanup:
        pusha
        push    es
        mov     si, alloc_tab
.l:     mov     ax, [si]
        or      ax, ax
        jz      .n
        mov     es, ax
        mov     ah, 49h
        int     21h
        mov     word [si], 0
.n:     add     si, 2
        cmp     si, alloc_tab + 2 * NALLOC
        jb      .l
        pop     es
        mov     word [wdepth], 0
        mov     word [wover], 0
        call    win_giveback
        cmp     byte [run_active], 0
        je      .x
        mov     byte [run_active], 0
        mov     byte [need_room], 1
        push    es
        push    cs
        pop     es
        mov     bx, [ui_paras]
        mov     ah, 4Ah
        int     21h
        pop     es
.x:     popa
        ret

; UI_FINDAPP: SI = name -> SI = path (this subject, then the root of the
; disk Grid-OS started from: the programs stay there when B: is shown)
ui_findapp:
        push    ax
        push    cx
        push    dx
        push    di
        mov     di, app_path
        call    api_sbstr
        mov     byte [di], 0
        mov     dx, app_path
        mov     ax, 4300h
        int     21h
        jnc     .yes
        push    si
        mov     ax, 3305h               ; DL = the boot drive (1 = A:)
        int     21h
        mov     al, dl
        mov     di, app_path
        add     al, 'A' - 1
        stosb
        mov     ax, ':\'
        stosw
        pop     si
        call    api_sbstr
        mov     byte [di], 0
        mov     dx, app_path
        mov     ax, 4300h
        int     21h
        jc      .x
.yes:   mov     si, app_path
.x:     pop     di
        pop     dx
        pop     cx
        pop     ax
        ret

; UI_RUN: SI = path, DI = tail -> AX = exit code, CF (AX = error)
ui_run: push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    bp
        push    es
        call    is_run                  ; (a .RUN isn't a DOS program: the
        jnc     .dos                    ;  kernel would take it for a .COM)
        mov     ax, 11
        pop     es
        pop     bp
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        stc
        ret
.dos:   call    hide_cursor
        call    mouse_off
        mov     ax, 0003h
        int     10h
        call    exec_raw
        pushf
        push    ax
        call    m33_end                 ; (the program may have used INT 33h:
        call    mouse_off               ;  the mouse is ours again)
        call    hires
        call    mouse_on
        call    act_now
        call    redraw_all
        pop     ax
        popf
        pop     es
        pop     bp
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        ret

; CF if the path SI ends in .RUN
is_run: push    si
        push    ax
        push    cx
        call    strlen                  ; CX = length
        cmp     cx, 4
        jb      .no
        add     si, cx
        sub     si, 4
        mov     ax, [si]                ; ".R" in memory: AL = '.', AH = 'R'
        and     ax, 0DFFFh
        cmp     ax, '.R'                ; (NASM: first character low)
        jne     .no
        mov     ax, [si+2]
        and     ax, 0DFDFh
        cmp     ax, 'UN'
        jne     .no
        pop     cx
        pop     ax
        pop     si
        stc
        ret
.no:    pop     cx
        pop     ax
        pop     si
        clc
        ret

; EXEC SI with tail DI (as it is: no mode change, the mouse as it is);
; the kernel's own INT 24h meanwhile, our DTA kept.  -> AX = exit code / CF
exec_raw:
        push    word [crit_err]
        mov     ah, 2Fh                 ; our DTA, to put back
        int     21h
        push    es
        push    bx
        push    cs
        pop     es
        mov     bx, run_tail + 1        ; " tail", CR, length first
        mov     byte [bx], ' '
        inc     bx
        push    si
        mov     si, di
.t:     lodsb
        or      al, al
        jz      .te
        cmp     bx, run_tail + 127
        jae     .te
        mov     [bx], al
        inc     bx
        jmp     .t
.te:    pop     si
        mov     byte [bx], 13
        mov     ax, bx
        sub     ax, run_tail + 1
        cmp     ax, 1
        ja      .len
        xor     ax, ax                  ; (no tail: none at all)
        mov     byte [run_tail + 1], 13
.len:   mov     [run_tail], al
        mov     word [run_epb], 0       ; our environment
        mov     word [run_epb+2], run_tail
        mov     [run_epb+4], cs
        mov     word [run_epb+6], exec_fcb
        mov     [run_epb+8], cs
        mov     word [run_epb+10], exec_fcb
        mov     [run_epb+12], cs
        call    unset24
        call    ui_lend                 ; (the directory's memory too)
        mov     dx, si
        mov     bx, run_epb
        mov     ax, 4B00h
        int     21h
        cld
        push    cs
        pop     ds
        push    cs
        pop     es
        call    ui_reclaim
        jc      .fail
        mov     ah, 4Dh
        int     21h
        xor     ah, ah                  ; (how it ended is in AH: not wanted)
        clc
.fail:  pushf
        call    set24
        pop     cx                      ; flags
        pop     dx                      ; our DTA back
        pop     bx
        push    ds
        mov     ds, bx
        push    ax
        mov     ah, 1Ah
        int     21h
        pop     ax
        pop     ds
        pop     word [crit_err]
        push    cx
        popf
        ret

; While a DOS program runs (and no .RUN is loaded) the UI block shrinks
; to ui_keep_end: the Executive's directory buffer goes to the program.
ui_lend:
        cmp     byte [run_active], 0
        jne     .x
        pusha
        mov     bx, ui_keep_end + 15
        shr     bx, 4
        mov     ah, 4Ah                 ; (ES = CS)
        int     21h
        mov     byte [lent], 1
        popa
.x:     ret

; ... and has it back afterwards (flags kept).  If something resident now
; sits right after the block, the Executive lists fewer files.
ui_reclaim:
        pushf
        cmp     byte [lent], 0
        je      .x
        mov     byte [lent], 0
        mov     byte [need_room], 1     ; (something resident may be in the way)
        pusha
        mov     bx, ui_bss_end + 15
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        jnc     .all
        mov     ah, 4Ah                 ; BX = all it can have
        int     21h
        mov     ax, bx
        shl     ax, 4                   ; bytes (the block is < 64 KB)
        sub     ax, entries
        jnc     .some
        xor     ax, ax
.some:  shr     ax, 5
        mov     [ent_max], ax
        mov     [ui_paras], bx
        popa
        jmp     .x
.all:   mov     word [ent_max], MAXENT
        mov     [ui_paras], bx
        popa
.x:     popf
        ret

; Room for the UI block to be whole, with RUN_ROOM free right after it for
; a .RUN.  If something resident (a TSR) now sits there, the block moves:
; a new one is allocated past it, everything is copied (the stack too),
; and the code goes on in the copy.  The kernel, the mouse's and INT 24h's
; vectors and the DTA are told.  Only from a place where the stack holds
; no segment values: the Executive's main loop.
RUN_ROOM    equ 1024                    ; 16 KB
ui_room:
        cmp     byte [need_room], 0
        je      .x
        mov     byte [need_room], 0
        cmp     byte [run_active], 0
        jne     .x
        pusha
        mov     bx, ui_bss_end + 15 + RUN_ROOM * 16
        shr     bx, 4
        mov     ah, 4Ah                 ; (ES = CS) room here?
        int     21h
        jnc     .here
        mov     bx, ui_bss_end + 15 + RUN_ROOM * 16
        shr     bx, 4
        mov     ah, 48h                 ; no: a block past what is in the way
        int     21h
        jc      .stay                   ; (memory is short anyway: stay)
        call    hide_cursor
        call    mouse_off
        mov     dx, cs                  ; DX = the old block
        mov     es, ax
        xor     si, si
        xor     di, di
        mov     cx, ui_bss_end + 1
        shr     cx, 1
        rep     movsw                   ; (the stack is in it, ours included)
        cli
        mov     ss, ax
        sti
        push    ax
        push    word .moved
        retf
.moved: mov     ds, ax
        dec     ax
        mov     es, ax
        mov     word [es:1], 8          ; the system's, called UI
        mov     word [es:8], 'UI'
        push    cs
        pop     es
        mov     ah, 2Fh                 ; the DTA, if it was in the old block
        int     21h                     ;  (DX = the old block still)
        mov     ax, es
        cmp     ax, dx
        jne     .dta
        push    dx
        mov     dx, bx
        mov     ah, 1Ah                 ; (DS = the new block)
        int     21h
        pop     dx
.dta:   mov     es, dx                  ; the old block goes
        mov     ah, 49h
        int     21h
        push    cs
        pop     es
        mov     bx, cs                  ; where the root restarts
        mov     ax, 0F004h
        int     21h
        call    set24
        call    m33_hook
        call    mouse_on
.here:  mov     bx, ui_bss_end + 15     ; whole again (and the room left free)
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     [ui_paras], bx
        mov     word [ent_max], MAXENT
.stay:  popa
.x:     ret

; run the .RUN at SI with argument DI -> AX = its exit code; CF if it
; couldn't be started (AX = DOS error, or 11 for a file that isn't a .RUN)
run_app:
        cmp     byte [run_active], 0
        je      .free
        mov     ax, 8                   ; (one at a time)
        stc
        ret
.free:  pusha
        mov     [run_ret], di
        mov     dx, si
        mov     ax, 3D00h
        int     21h
        jc      .err
        mov     [run_hnd], ax
        mov     bx, ax
        mov     dx, run_hdr
        mov     cx, 16
        mov     ah, 3Fh
        int     21h
        jc      .errc
        cmp     ax, 16
        jne     .bad
        cmp     word [run_hdr], 'GR'
        jne     .bad
        cmp     word [run_hdr+2], 'UN'
        jne     .bad
        cmp     word [run_hdr+4], UI_API
        ja      .bad
        mov     ax, [run_hdr+10]        ; fixups after the image: room for them
        add     ax, [run_hdr+12]
        jc      .bad                    ; (a damaged header: counts that
        cmp     ax, 4000h               ;  overflow when doubled)
        jae     .bad
        shl     ax, 1
        cmp     ax, [run_hdr+8]
        jae     .room
        mov     ax, [run_hdr+8]
.room:  add     ax, [run_hdr+6]
        jc      .big
        add     ax, [run_base]
        jc      .big
        cmp     ax, 0FFF0h
        ja      .big
        add     ax, 15
        shr     ax, 4
        mov     bx, ax
        push    es
        push    cs
        pop     es
        mov     ah, 4Ah                 ; the UI block grows to hold it
        int     21h
        pop     es
        jc      .mem
        mov     byte [run_active], 1
        mov     bx, [run_hnd]
        mov     dx, [run_base]
        mov     cx, [run_hdr+6]
        add     cx, [run_hdr+10]
        add     cx, [run_hdr+10]
        add     cx, [run_hdr+12]
        add     cx, [run_hdr+12]
        mov     ah, 3Fh                 ; image + fixups in one read
        int     21h
        jc      .errr
        cmp     ax, cx
        jne     .badr
        mov     ah, 3Eh
        int     21h
        mov     bp, [run_base]          ; the fixups
        mov     si, bp
        add     si, [run_hdr+6]
        mov     dx, [run_hdr+6]         ; each must lie inside the image
        sub     dx, 2                   ;  (DX = the last word's offset)
        mov     cx, [run_hdr+10]
        jcxz    .rel
        cmp     dx, [run_hdr+6]
        ja      .badf                   ; (an image under 2 bytes)
.abs:   lodsw
        cmp     ax, dx
        ja      .badf
        mov     di, ax
        add     di, bp
        add     [di], bp
        loop    .abs
.rel:   mov     cx, [run_hdr+12]
        jcxz    .bss
        cmp     dx, [run_hdr+6]
        ja      .badf
.r:     lodsw
        cmp     ax, dx
        ja      .badf
        mov     di, ax
        add     di, bp
        sub     [di], bp
        loop    .r
.bss:   mov     di, bp                  ; BSS: zeroes (over the fixups too)
        add     di, [run_hdr+6]
        mov     cx, [run_hdr+8]
        mov     ax, [run_hdr+10]
        add     ax, [run_hdr+12]
        shl     ax, 1
        cmp     cx, ax
        jae     .z
        mov     cx, ax
.z:     xor     al, al
        rep     stosb
        mov     word [crit_err], 0
        push    es
        mov     ah, 2Fh                 ; the DTA, put back afterwards
        int     21h
        mov     [run_dta], bx
        mov     [run_dta+2], es
        pop     es
        mov     word [redraw_fn], 0     ; (until it sets its own)
        mov     si, [run_ret]           ; the argument
        call    bp
        cld
        push    cs
        pop     ds
        push    cs
        pop     es
        mov     [run_ret], ax
        push    ds
        lds     dx, [run_dta]
        mov     ah, 1Ah
        int     21h
        pop     ds
        call    run_cleanup
        popa
        mov     ax, [run_ret]
        clc
        ret
.badf:  mov     word [run_ret], 11      ; (the file is closed already)
        call    run_cleanup
        jmp     .fail
.badr:  mov     ax, 11
.errr:  push    ax
        mov     bx, [run_hnd]
        mov     ah, 3Eh
        int     21h
        pop     ax
        mov     [run_ret], ax
        call    run_cleanup
        jmp     .fail
.big:   mov     ax, 8
        jmp     .errc
.mem:   mov     ax, 8
        jmp     .errc
.bad:   mov     ax, 11
.errc:  push    ax
        mov     bx, [run_hnd]
        mov     ah, 3Eh
        int     21h
        pop     ax
.err:   mov     [run_ret], ax
.fail:  popa
        mov     ax, [run_ret]
        stc
        ret

; =====================================================================
;  the screen saver, after the delay set in System (SAVER= in GRIDOS.INI;
;  5 minutes without it) with no key or mouse; never if set so.  In the
;  Executive (no .RUN, no window, no question): first DEFRAG.COM, if it is on the
;  disk: it tidies the floppy while showing its map, and stops at a key or
;  the mouse (exit code 1) or when the disk is in order.  Then a dark
;  screen with the time and date moving to a new place every 20 seconds,
;  so the plasma never holds one picture.  Then the screen as it was.
; =====================================================================
saver:  pusha
        call    hide_cursor
        cli
        mov     byte [mflag], 0
        sti
        cmp     byte [run_active], 0
        jne     .own
        cmp     word [wdepth], 0
        jne     .own
        cmp     word [held1], 0         ; (nor while a question waits: a
        jne     .own                    ;  file it names stays as it is)
        call    sv_defrag
        jc      .own
        cmp     al, 1
        je      .wake
.own:   call    hires
        call    tick
        mov     [sv_due], ax
        mov     [sv_seed], ax
        mov     word [sv_col], 0FFFFh
.l:     mov     ah, 11h
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
.key:   call    read_key                ; the key that wakes it does
                                        ; nothing else
.wake:  cli
        mov     byte [mflag], 0
        mov     al, [mb]                ; (a button held while waking it
        mov     [oldmb], al             ;  is not a click)
        sti
        call    hires
        call    read_clock
        call    redraw_all
        call    ptr_restore
        call    act_now
        popa
        ret

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

; DEFRAG.COM /S from the root of the current drive (a floppy: not C:).
; CF if it isn't there or can't run; else AL = its exit code.  The mouse
; stays on: DEFRAG watches our mouse flag (passed as M=segment:offset).
sv_defrag:
        mov     ah, 19h
        int     21h
        cmp     al, 2
        jae     .no
        add     al, 'A'
        mov     [s_defrag], al
        mov     dx, s_defrag
        mov     ax, 4300h
        int     21h
        jc      .no
        mov     di, sv_tail
        mov     si, s_svarg
        call    sb_str
        mov     ax, cs
        call    sb_hex4
        mov     al, ':'
        stosb
        mov     ax, mflag
        call    sb_hex4
        mov     si, s_svfont            ; " F=": the font in use, for its map
        call    sb_str
        mov     ax, cs
        call    sb_hex4
        mov     al, ':'
        stosb
        mov     ax, font
        call    sb_hex4
        mov     byte [di], 0
        mov     si, s_defrag
        mov     di, sv_tail
        call    exec_raw
        jc      .no
        push    ax
        mov     ah, 36h                 ; the kernel takes the FAT in again
        xor     dl, dl                  ; now, while it is surely the same
        int     21h                     ; disk (so it can tell a swap later)
        pop     ax
        clc
        ret
.no:    stc
        ret

tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

wait_ticks:
        push    ax
        push    bx
        call    tick
        mov     bx, ax
.w:     call    tick
        sub     ax, bx
        cmp     ax, cx
        jb      .w
        pop     bx
        pop     ax
        ret

; =====================================================================
;  data
; =====================================================================
s_anykey    db 'Press any key',0
s_confirm   db 'Press RETURN to confirm or ESC to cancel',0
s_formhelp  db 'RETURN: next item    CODE-RETURN or click here: confirm    ESC: cancel',0
s_am        db ' am',0
s_pm        db ' pm',0
months      db 'JanFebMarAprMayJunJulAugSepOctNovDec'
s_defrag    db 'A:\DEFRAG.COM', 0
s_svarg     db '/S M=', 0
s_svfont    db ' F=', 0
s_ini       db '\GRIDOS.INI', 0
exec_fcb    db 0, '           ', 0, 0, 0, 0
s_err       db 'error ',0
; DOS errors (code, text); the INT 24h ones below
dos_msgs    db 2, 'File not found',0
            db 3, 'Path not found',0
            db 4, 'Too many files open',0
            db 5, 'Access denied',0
            db 8, 'Not enough memory',0
            db 11, 'Not a program',0
            db 15, 'No such drive',0
            db 18, 'No more files',0
            db 19, 'Disk is write-protected',0
            db 21, 'Drive not ready (no disk?)',0
            db 23, 'Disk error (data)',0
            db 25, 'Disk error (seek)',0
            db 26, 'Not a DOS disk',0
            db 27, 'Disk error (sector not found)',0
            db 29, 'Disk error (write)',0
            db 30, 'Disk error (read)',0
            db 31, 'Disk error',0
            db 39, 'Disk is full',0
            db 80, 'File already exists',0
            db 83, 'Disk error',0
            db 0FFh
crit_msgs   db 1, 'Disk is write-protected',0
            db 2, 'Unknown drive',0
            db 3, 'Drive not ready (no disk?)',0
            db 4, 'Disk error (unknown command)',0
            db 5, 'Disk error (data)',0
            db 6, 'Disk error (bad request)',0
            db 7, 'Disk error (seek)',0
            db 8, 'Not a DOS disk',0
            db 9, 'Disk error (sector not found)',0
            db 10, 'Printer out of paper',0
            db 11, 'Disk error (write)',0
            db 12, 'Disk error (read)',0
            db 13, 'Disk error',0
            db 0FFh

lasttick    dw 0
mx          dw 320
my          dw 200
mb          db 0
oldmb       db 0
mflag       db 0
midx        db 3
mpkt        db 0, 0, 0
mbase       dw 0
mirq        db 0
vecslot     dw 0
oldvec      dw 0, 0
curvis      db 0

section uibss
sv_due      resw 1
sv_col      resw 1
sv_y        resw 1
sv_seed     resw 1
sv_tail     resb 40                 ; "/S M=ssss:oooo F=ssss:oooo"
section ui
