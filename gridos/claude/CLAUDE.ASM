; =====================================================================
;  CLAUDE.COM - Claude for GRiD: the GRiD side of the Claude link
;  Build:  nasm -f bin -i ../src/ -o CLAUDE.COM CLAUDE.ASM
;
;  CLAUDE [/A:nn] [/T | /C]
;    /A:nn  GPIB address of the AR488 bridge (default 7)
;    /T     Term: the GRiD is the screen and keyboard of the real Claude
;           Code on the Pi (your Claude subscription; no API key)
;    /C     chat: gridlink's own agent (an API key on the Pi)
;    neither: the Pi decides (gridlink's [grid] app setting)
;
;  Runs under MS-DOS 3.x with GRIDGPIB loaded (and later on Grid-OS).
;  Screen: 640x400 mode 40h, Terminus Bold 8x16, 80 x 25 cells:
;    chat: row 0 title band, rows 1-20 conversation, row 21 status line,
;    row 22 rule, rows 23-24 the prompt;
;    Term: rows 0-23 Claude Code's terminal, row 24 the status band.
;  Link: GLP 1 over GPIB (gridlink/PROTOCOL.md).  Strict alternation:
;  the GRiD writes one frame, then reads exactly one answer.
;  The GRiD also runs the requests Claude makes: files, DOS programs
;  (with keystroke scripts and screenshots), GPIB instruments, clock.
; =====================================================================
cpu 286
org 100h

VSEG     equ 0B800h
CROWS    equ 20                 ; conversation rows (screen rows 1-20)
SROW     equ 21                 ; status line
RROW     equ 22                 ; rule
PROW     equ 23                 ; prompt (rows 23-24)
NLINES   equ 160                ; conversation lines kept
LINEB    equ 160                ; bytes per line: 80 x (char, attribute)
MAXIN    equ 1000               ; longest prompt
HISTN    equ 4                  ; prompts remembered for Up/Down
HISTL    equ 400
TXMAX    equ 1024               ; GRiD -> Pi payload per frame
RXMAX    equ 255                ; Pi -> GRiD frame (patched AR488 line)
REQMAX   equ 4700               ; request reassembly
IOSIZE   equ 16384              ; reply buffer segment
SNAPMAX  equ 32768 + 11         ; snapshot segment: id, status, header, data
TXQN     equ 6                  ; outgoing messages queued
ASKMAX   equ 900
BOXL     equ 5                  ; dialog boxes: left column, width
BOXW     equ 70

LS_RESET equ 0
LS_IDLE  equ 1
LS_WAIT  equ 2

G_HELLO   equ 01h
G_POLL    equ 02h
G_PROMPT  equ 03h
G_EVENT   equ 04h
G_REPLY   equ 05h
G_NAK     equ 06h
G_KEYS    equ 07h
P_HELLO   equ 41h
P_NOP     equ 42h
P_TEXT    equ 43h
P_STATUS  equ 44h
P_REQUEST equ 45h
P_ASK     equ 46h
P_READY   equ 47h
P_NAK     equ 48h
P_TITLE   equ 49h
P_CLEAR   equ 4Ah
P_CELLS   equ 4Bh
HF_TERM   equ 01h                ; the Pi's HELLO: Term

; =====================================================================
;  start-up
; =====================================================================
start:  mov     sp, stack_top
        cld
        push    cs
        pop     es
        mov     di, bss                 ; clear BSS (nothing on the stack yet)
        mov     cx, bss_end
        sub     cx, di
        xor     al, al
        rep     stosb
        mov     bx, bss_end             ; keep code, data and BSS; free the rest
        add     bx, 15
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     byte [nano], 7
        call    parse_args
        call    find_gpib
        jnc     .gg
        mov     dx, msg_nogg
        jmp     fatal
.gg:    call    alloc_bufs
        jnc     .mem
        mov     dx, msg_nomem
        jmp     fatal
.mem:   call    crc_init
        call    sys_probe
        mov     si, s_title0
        mov     di, title_text
        call    copyz
        mov     word [c_dirty_col], 0FFFFh
        mov     ax, [convseg]           ; Term's shadow: the conversation's memory
        mov     [shadseg], ax
        cmp     byte [app_want], 'T'
        jne     .nt
        mov     byte [term], 1
.nt:    call    vec_save
        call    vec_ours
        call    get_ticks
        mov     [now], ax
        sub     ax, 100
        mov     [t_reset], ax           ; first connection attempt right away
        mov     si, st_connecting
        call    set_status_quiet
        call    video_on
main:   call    get_ticks
        mov     [now], ax
        call    link_service
        call    kbd_service
        call    req_service
        call    tick_service
        cmp     byte [quit], 0
        jne     leave
        call    maybe_idle
        jmp     main

leave:  mov     al, [oldmode]
        cmp     al, 40h
        jne     .m
        mov     al, 3
.m:     xor     ah, ah
        int     10h
        call    vec_dos
        mov     dx, msg_bye
        mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h

fatal:  mov     ah, 9
        int     21h
        mov     ax, 4C01h
        int     21h

; CLAUDE /A:nn
parse_args:
        mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 0
.scan:  lodsb
        or      al, al
        jz      .done
        cmp     al, '/'
        jne     .scan
        lodsb
        and     al, 0DFh
        cmp     al, 'T'
        je      .app
        cmp     al, 'C'
        je      .app
        cmp     al, 'A'
        jne     .scan
        lodsb
        cmp     al, ':'
        je      .num
        cmp     al, '='
        je      .num
        dec     si
.num:   xor     dx, dx
.dig:   lodsb
        sub     al, '0'
        jb      .setn
        cmp     al, 9
        ja      .setn
        imul    dx, dx, 10
        xor     ah, ah
        add     dx, ax
        jmp     .dig
.setn:  dec     si
        cmp     dx, 1
        jb      .scan
        cmp     dx, 30
        ja      .scan
        mov     [nano], dl
        jmp     .scan
.app:   mov     [app_want], al
        jmp     .scan
.done:  ret

; GRIDGPIB: first vector 60h-66h with 'GRIDGPIB' at entry+2.  CF if none.
find_gpib:
        mov     al, 60h
.v:     push    ax
        mov     ah, 35h
        int     21h
        pop     ax
        mov     cx, es
        or      cx, bx
        jz      .next
        lea     di, [bx+2]
        mov     si, sig_gg
        mov     cx, 8
        repe    cmpsb
        je      .found
.next:  inc     al
        cmp     al, 67h
        jb      .v
        push    cs
        pop     es
        stc
        ret
.found: push    cs
        pop     es
        mov     [ggint], al
        mov     [gg_call+1], al         ; patch "INT nn"
        mov     ah, 0
        call    gg_call
        cmp     ax, 4747h
        jne     .bad
        mov     [ggver], cx
        clc
        ret
.bad:   stc
        ret

gg_call:
        int     60h                     ; (patched)
        ret

alloc_bufs:
        mov     bx, (NLINES * LINEB + 15) / 16
        mov     ah, 48h
        int     21h
        jc      .x
        mov     [convseg], ax
        mov     bx, (IOSIZE + 15) / 16
        mov     ah, 48h
        int     21h
        jc      .x
        mov     [ioseg], ax
        push    es
        mov     es, [convseg]
        xor     di, di
        mov     ax, 0020h
        mov     cx, NLINES * LINEB / 2
        rep     stosw
        pop     es
        clc
.x:     ret

snap_alloc:                             ; CF if no memory
        cmp     word [snapseg], 0
        jne     .ok
        mov     bx, (SNAPMAX + 15) / 16
        mov     ah, 48h
        int     21h
        jc      .x
        mov     [snapseg], ax
.ok:    clc
.x:     ret

snap_free:
        cmp     word [snapseg], 0
        je      .x
        push    es
        mov     es, [snapseg]
        mov     ah, 49h
        int     21h
        pop     es
        mov     word [snapseg], 0
.x:     mov     byte [snap_taken], 0
        ret

; drives, EMS: things that don't change while we run
sys_probe:
        mov     di, drvstr
        mov     bl, 1
.d:     mov     ax, 4408h               ; IOCTL: removable?  error 0Fh = no drive
        push    bx
        int     21h
        pop     bx
        jnc     .have
        cmp     ax, 0Fh
        je      .nod
.have:  mov     al, bl
        add     al, 'A' - 1
        stosb
        mov     ax, ': '                ; ':' then ' '
        stosw
.nod:   inc     bl
        cmp     bl, 27
        jb      .d
        mov     byte [di], 0
        mov     ax, 3567h               ; EMS driver present?
        int     21h
        mov     di, 0Ah
        mov     si, s_emm
        mov     cx, 8
        repe    cmpsb
        push    cs
        pop     es
        jne     .x
        mov     ah, 42h
        int     67h
        or      ah, ah
        jnz     .x
        mov     [ems_free], bx
        mov     [ems_total], dx
        mov     byte [ems_ok], 1
.x:     ret

vec_save:
        mov     ax, 3523h
        int     21h
        mov     [old23], bx
        mov     [old23+2], es
        mov     ax, 3524h
        int     21h
        mov     [old24], bx
        mov     [old24+2], es
        push    cs
        pop     es
        ret

vec_ours:
        mov     dx, int23
        mov     ax, 2523h
        int     21h
        mov     dx, int24
        mov     ax, 2524h
        int     21h
        ret

vec_dos:
        push    ds
        lds     dx, [old23]
        mov     ax, 2523h
        int     21h
        pop     ds
        push    ds
        lds     dx, [old24]
        mov     ax, 2524h
        int     21h
        pop     ds
        ret

int23:  iret                            ; Ctrl-C: ignore

int24:  test    ah, 08h                 ; critical error: fail if allowed,
        jnz     .fail                   ; else ignore, never abort us
        test    ah, 20h
        jz      .fail
        xor     al, al
        iret
.fail:  mov     al, 3
        iret

; =====================================================================
;  screen
; =====================================================================
video_on:
        cmp     byte [vid_saved], 0
        jne     .s
        mov     ah, 0Fh
        int     10h
        mov     [oldmode], al
        mov     byte [vid_saved], 1
.s:     mov     ax, 0040h
        int     10h
        call    redraw_all
        ret

clear_screen:
        pusha
        push    es
        mov     ax, VSEG
        mov     es, ax
        xor     di, di
        xor     ax, ax
        mov     cx, 4000h
        rep     stosw
        pop     es
        popa
        ret

redraw_all:
        cmp     byte [term], 0
        je      .chat
        jmp     term_redraw
.chat:  call    clear_screen
        call    draw_title
        call    draw_rule
        call    draw_prompt
        call    redraw_body
        ret

redraw_body:
        cmp     byte [term], 0
        je      .chat
        ret
.chat:  call    draw_conv
        call    draw_status
        cmp     byte [ask_open], 0
        je      .h
        call    draw_ask
.h:     cmp     byte [help_open], 0
        je      .x
        call    draw_help
.x:     ret

%include "TERMCELL.INC"

; DS:SI -> 80 (char, attribute) pairs, DX = screen row, ES = VSEG
draw_line:
        pusha
        imul    di, dx, 320
        mov     cx, 80
.l:     lodsw
        call    cell
        inc     di
        loop    .l
        popa
        ret

; DS:SI -> ASCIIZ, ES:DI = cell, AH = attribute, CX = most cells.
; Returns DI after the text.
draw_strn:
        push    ax
        push    cx
        jcxz    .x
.l:     lodsb
        or      al, al
        jz      .x
        push    ax
        call    cell
        pop     ax
        inc     di
        loop    .l
.x:     pop     cx
        pop     ax
        ret

; DX = row, AH = attribute: 80 blank cells
blank_row:
        push    ax
        push    cx
        push    di
        imul    di, dx, 320
        mov     cx, 80
        mov     al, ' '
.l:     push    ax
        call    cell
        pop     ax
        inc     di
        loop    .l
        pop     di
        pop     cx
        pop     ax
        ret

strlen: push    si                      ; DS:SI -> CX
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .x
        inc     cx
        jmp     .l
.x:     pop     si
        ret

; title band: " <title>              GPIB link  5:31 pm"
draw_title:
        cmp     byte [term], 0
        je      .chat
        jmp     term_status
.chat:  pusha
        mov     di, rbuf
        mov     si, s_nolink
        cmp     byte [connected], 0
        je      .l
        mov     si, s_link
.l:     call    put_str
        mov     ax, '  '
        stosw
        call    fmt_clock
        mov     byte [di], 0
        push    es
        mov     ax, VSEG
        mov     es, ax
        xor     dx, dx
        mov     ah, 1
        call    blank_row
        mov     di, 1
        mov     si, title_text
        mov     ah, 1
        mov     cx, 56
        call    draw_strn
        mov     si, rbuf
        call    strlen
        mov     di, 79
        sub     di, cx
        mov     ah, 1
        call    draw_strn
        pop     es
        popa
        ret

draw_rule:
        pusha
        push    es
        mov     ax, VSEG
        mov     es, ax
        mov     di, RROW * 320
        mov     cx, 80
.l:     mov     ax, 008Dh
        call    cell
        inc     di
        loop    .l
        pop     es
        popa
        ret

; status line: "<spin> Thinking... (12s . esc to interrupt)        F1 help"
draw_status:
        cmp     byte [term], 0
        je      .chat
        jmp     term_status
.chat:  pusha
        mov     di, sline
        cmp     byte [busy], 0
        je      .idle
        mov     bl, [spin]
        xor     bh, bh
        mov     al, [spinseq + bx]
        stosb
        mov     al, ' '
        stosb
        mov     si, status_text
        cmp     byte [si], 0
        jne     .t
        mov     si, s_working
.t:     call    put_str
        mov     ax, ' ('
        stosw
        mov     ax, [now]
        sub     ax, [turn_t0]
        mov     cx, 10
        mul     cx
        mov     cx, 182
        div     cx
        call    put_dec
        mov     si, s_esc
        call    put_str
        jmp     .right
.idle:  mov     si, status_text
        call    put_str
.right: mov     byte [di], 0
        mov     di, rbuf
        mov     si, s_none
        cmp     word [view_off], 0
        je      .r1
        mov     si, s_scrolled
        jmp     .r2
.r1:    cmp     byte [busy], 0
        jne     .r2
        cmp     byte [connected], 0
        je      .r2
        mov     si, s_f1help
.r2:    call    put_str
        mov     byte [di], 0
        push    es
        mov     ax, VSEG
        mov     es, ax
        mov     dx, SROW
        xor     ah, ah
        call    blank_row
        mov     si, rbuf
        call    strlen
        mov     bx, cx                  ; right part's width
        mov     di, SROW * 320
        mov     si, sline
        mov     cx, 79
        sub     cx, bx
        xor     ah, ah
        call    draw_strn
        mov     di, SROW * 320 + 80
        sub     di, bx
        mov     si, rbuf
        mov     cx, bx
        call    draw_strn
        pop     es
        popa
        ret

; SI -> ASCIIZ (our segment): new status text
set_status:
        call    set_status_quiet
        call    draw_status
        ret
set_status_quiet:
        push    si
        push    di
        push    cx
        mov     di, status_text
        mov     cx, 70
.l:     lodsb
        stosb
        or      al, al
        jz      .x
        loop    .l
        mov     byte [di], 0
.x:     pop     cx
        pop     di
        pop     si
        ret

; prompt: rows 23-24, "> " then 2 x 78 cells of the input
draw_prompt:
        cmp     byte [term], 0
        je      .chat
        ret
.chat:  pusha
        mov     ax, [incur]
        xor     bx, bx
        cmp     ax, 156
        jb      .v
        sub     ax, 156
        xor     dx, dx
        mov     cx, 78
        div     cx
        inc     ax
        mul     cx
        mov     bx, ax
.v:     mov     [vstart], bx
        push    es
        mov     ax, VSEG
        mov     es, ax
        mov     di, PROW * 320
        mov     ax, 003Eh               ; '>'
        cmp     byte [connected], 0
        jne     .p
        mov     al, 86h                 ; a dot while not connected
.p:     call    cell
        inc     di
        mov     al, ' '
        cmp     word [vstart], 0
        je      .q
        mov     al, 82h                 ; ellipsis: more text to the left
.q:     xor     ah, ah
        call    cell
        mov     si, [vstart]
        mov     di, PROW * 320 + 2
        call    prow78
        mov     di, (PROW + 1) * 320
        mov     ax, 0020h
        call    cell
        inc     di
        mov     ax, 0020h
        call    cell
        inc     di
        call    prow78
        pop     es
        popa
        ret

prow78: mov     cx, 78
.l:     mov     al, ' '
        cmp     si, [inlen]
        jae     .c
        mov     al, [inbuf + si]
        cmp     al, 0Ah
        jne     .c
        mov     al, 8Fh                 ; a typed line break
.c:     xor     ah, ah
        cmp     si, [incur]
        jne     .d
        mov     ah, 1                   ; the cursor
.d:     call    cell
        inc     si
        inc     di
        loop    .l
        ret

; =====================================================================
;  conversation store (convseg: NLINES lines in a ring)
; =====================================================================
line_off:                               ; AX = line (0 = oldest) -> AX = offset
        add     ax, [c_head]
        cmp     ax, NLINES
        jb      .a
        sub     ax, NLINES
.a:     push    dx
        mov     dx, LINEB
        mul     dx
        pop     dx
        ret

conv_newline:
        pusha
        push    es
        cmp     word [c_count], NLINES
        jae     .full
        inc     word [c_count]
        jmp     .clr
.full:  mov     ax, [c_head]
        inc     ax
        cmp     ax, NLINES
        jb      .h
        xor     ax, ax
.h:     mov     [c_head], ax
.clr:   mov     ax, [c_count]
        dec     ax
        call    line_off
        mov     di, ax
        mov     es, [convseg]
        mov     ax, 0020h
        mov     cx, 80
        rep     stosw
        mov     word [c_col], 0
        mov     byte [c_dirty_full], 1
        cmp     word [view_off], 0
        je      .x
        inc     word [view_off]         ; reading back: keep the view still
.x:     pop     es
        popa
        ret

conv_putc:                              ; AL = character
        pusha
        push    es
        cmp     word [c_count], 0
        jne     .a
        call    conv_newline
.a:     cmp     word [c_col], 80
        jb      .b
        call    conv_newline
.b:     push    ax
        mov     ax, [c_count]
        dec     ax
        call    line_off
        mov     di, ax
        mov     bx, [c_col]
        shl     bx, 1
        add     di, bx
        pop     ax
        mov     ah, [c_attr]
        mov     es, [convseg]
        mov     [es:di], ax
        mov     ax, [c_col]
        cmp     ax, [c_dirty_col]
        jae     .c
        mov     [c_dirty_col], ax
.c:     inc     word [c_col]
        pop     es
        popa
        ret

; DS:SI -> TEXT payload, CX = length
conv_text:
        jcxz    .x
.l:     lodsb
        cmp     al, 0Ah
        je      .nl
        cmp     al, 0Eh
        je      .i1
        cmp     al, 0Fh
        je      .i0
        cmp     al, 10h
        je      .u1
        cmp     al, 11h
        je      .u0
        cmp     al, 20h
        jb      .n
        call    conv_putc
        jmp     .n
.nl:    cmp     word [c_count], 0
        jne     .nl2
        call    conv_newline
.nl2:   call    conv_newline
        jmp     .n
.i1:    or      byte [c_attr], 1
        jmp     .n
.i0:    and     byte [c_attr], 0FEh
        jmp     .n
.u1:    or      byte [c_attr], 2
        jmp     .n
.u0:    and     byte [c_attr], 0FDh
.n:     loop    .l
.x:     ret

; show what changed: the whole window after a scroll, else the last line
conv_refresh:
        cmp     byte [ask_open], 0
        jne     .x
        cmp     byte [help_open], 0
        jne     .x
        cmp     byte [c_dirty_full], 0
        jne     .full
        cmp     word [c_dirty_col], 0FFFFh
        je      .x
        cmp     word [view_off], 0
        jne     .clean
        mov     ax, [c_count]
        or      ax, ax
        jz      .clean
        mov     bx, ax
        sub     bx, CROWS
        jns     .t
        xor     bx, bx
.t:     dec     ax
        sub     ax, bx
        inc     ax
        mov     dx, ax                  ; screen row of the newest line
        mov     ax, [c_count]
        dec     ax
        call    line_off
        mov     si, ax
        push    ds
        push    es
        mov     ax, VSEG
        mov     es, ax
        mov     ds, [convseg]
        call    draw_line
        pop     es
        pop     ds
        jmp     .clean
.full:  call    draw_conv
.clean: mov     byte [c_dirty_full], 0
        mov     word [c_dirty_col], 0FFFFh
.x:     ret

draw_conv:
        pusha
        push    es
        mov     ax, [c_count]           ; clamp the scroll-back
        sub     ax, CROWS
        jns     .a
        xor     ax, ax
.a:     cmp     [view_off], ax
        jbe     .b
        mov     [view_off], ax
.b:     sub     ax, [view_off]
        mov     bp, ax                  ; first line shown
        mov     dx, 1
        mov     ax, VSEG
        mov     es, ax
.row:   cmp     bp, [c_count]
        jae     .blank
        mov     ax, bp
        call    line_off
        mov     si, ax
        push    ds
        mov     ds, [convseg]
        call    draw_line
        pop     ds
        jmp     .nx
.blank: mov     si, blankline
        call    draw_line
.nx:    inc     bp
        inc     dx
        cmp     dx, CROWS + 1
        jb      .row
        pop     es
        popa
        ret

conv_clear:
        mov     word [c_count], 0
        mov     word [c_head], 0
        mov     word [c_col], 0
        mov     word [view_off], 0
        mov     byte [c_attr], 0
        mov     byte [c_dirty_full], 1
        call    conv_refresh
        ret

; "> prompt" into the conversation
echo_prompt:
        cmp     word [c_col], 0
        je      .a
        call    conv_newline
.a:     cmp     word [c_count], 0
        je      .b
        call    conv_newline            ; blank line before
.b:     mov     byte [c_attr], 1
        mov     al, '>'
        call    conv_putc
        mov     byte [c_attr], 0
        mov     al, ' '
        call    conv_putc
        mov     si, pbuf
        mov     cx, [plen]
.l:     jcxz    .e
        lodsb
        cmp     al, 0Ah
        jne     .p
        call    conv_newline
        mov     al, ' '
        call    conv_putc
        call    conv_putc
        jmp     .n
.p:     call    conv_putc
.n:     dec     cx
        jmp     .l
.e:     call    conv_newline
        call    conv_newline            ; blank line before the answer
        mov     word [view_off], 0
        mov     byte [c_dirty_full], 1
        call    conv_refresh
        ret

; =====================================================================
;  dialogs: permission questions and help
; =====================================================================
; DX = top row, CX = rows including title and bottom rule, SI = title
draw_box:
        pusha
        push    es
        mov     ax, VSEG
        mov     es, ax
        push    cx
        push    si
        imul    di, dx, 320
        add     di, BOXL
        mov     cx, BOXW
.t:     mov     ax, 0120h
        call    cell
        inc     di
        loop    .t
        pop     si
        imul    di, dx, 320
        add     di, BOXL + 1
        mov     ah, 1
        mov     cx, BOXW - 2
        call    draw_strn
        pop     cx
        sub     cx, 2
        inc     dx
.b:     imul    di, dx, 320
        add     di, BOXL
        mov     ax, 008Eh
        call    cell
        inc     di
        push    cx
        mov     cx, BOXW - 2
.s:     mov     ax, 0020h
        call    cell
        inc     di
        loop    .s
        pop     cx
        mov     ax, 008Eh
        call    cell
        inc     dx
        loop    .b
        imul    di, dx, 320
        add     di, BOXL
        mov     ax, 0098h               ; bottom-left corner
        call    cell
        inc     di
        mov     cx, BOXW - 2
.r:     mov     ax, 008Dh
        call    cell
        inc     di
        loop    .r
        mov     ax, 0099h               ; bottom-right corner
        call    cell
        pop     es
        popa
        ret

; ASK body: id, kind, question\0 detail\0 always\0  (copied from reqbuf)
open_ask:
        mov     cx, [rq_len]
        cmp     cx, ASKMAX - 4
        jbe     .c
        mov     cx, ASKMAX - 4
.c:     mov     si, reqbuf
        mov     di, askbuf
        rep     movsb
        xor     ax, ax
        stosw
        stosw
        mov     al, [askbuf]
        mov     [ask_id], al
        mov     al, [askbuf+1]
        mov     [ask_kind], al
        mov     si, askbuf+2
        mov     [ask_q], si
        call    skipz
        mov     [ask_d], si
        call    skipz
        mov     [ask_a], si
        mov     byte [ask_sel], 0
        mov     byte [help_open], 0
        mov     byte [ask_open], 1
        call    draw_ask
        ret

skipz:  lodsb
        or      al, al
        jnz     skipz
        ret

draw_ask:
        pusha
        mov     di, optbuf              ; "[A] <always label>" (ES = ours here)
        mov     si, s_opt_a
        call    put_str
        mov     si, [ask_a]
        mov     cx, 40
.oa:    lodsb
        or      al, al
        jz      .oz
        stosb
        loop    .oa
.oz:    mov     byte [di], 0
        mov     dx, 6
        mov     cx, 11
        mov     si, [ask_q]
        call    draw_box
        push    es
        mov     ax, VSEG
        mov     es, ax
        mov     si, [ask_d]             ; detail: rows 8-12, 64 columns
        mov     dx, 8
.dl:    cmp     dx, 13
        jae     .opts
        cmp     byte [si], 0
        je      .opts
        imul    di, dx, 320
        add     di, BOXL + 3
        mov     cx, 64
.dc:    lodsb
        or      al, al
        jz      .dz
        cmp     al, 0Ah
        je      .dn
        xor     ah, ah
        call    cell
        inc     di
        loop    .dc
        jmp     .dn
.dz:    dec     si
.dn:    inc     dx
        jmp     .dl
.opts:  mov     di, 14 * 320 + BOXL + 3
        xor     bx, bx
        mov     si, s_opt_yes
        call    draw_opt
        cmp     byte [ask_kind], 1
        jne     .no
        mov     bx, 1
        mov     si, optbuf
        call    draw_opt
.no:    mov     bx, 2
        mov     si, s_opt_no
        call    draw_opt
        pop     es
        popa
        ret

; BX = option number, SI = text, DI = cell (ES = VSEG)
draw_opt:
        xor     ah, ah
        cmp     bl, [ask_sel]
        jne     .d
        mov     ah, 1
.d:     mov     al, ' '
        push    ax
        call    cell
        pop     ax
        inc     di
        mov     cx, 48
        call    draw_strn
        mov     al, ' '
        call    cell
        add     di, 4
        ret

; key in AX while a question is open
ask_key:
        cmp     ax, 011Bh
        je      .no
        cmp     ax, 1C0Dh
        je      .enter
        cmp     ax, 4B00h
        je      .left
        cmp     ax, 4D00h
        je      .right
        cmp     ax, 0F09h
        je      .right
        and     al, 0DFh
        cmp     al, 'Y'
        je      .yes
        cmp     al, 'N'
        je      .no
        cmp     al, 'A'
        jne     .x
        cmp     byte [ask_kind], 1
        jne     .x
.alw:   mov     al, 'a'
        jmp     ask_answer
.yes:   mov     al, 'y'
        jmp     ask_answer
.no:    mov     al, 'n'
        jmp     ask_answer
.enter: mov     al, [ask_sel]
        or      al, al
        jz      .yes
        cmp     al, 1
        je      .alw
        jmp     .no
.left:  mov     al, [ask_sel]
        or      al, al
        jz      .x
        dec     al
        cmp     byte [ask_kind], 1
        je      .set
        xor     al, al
        jmp     .set
.right: mov     al, [ask_sel]
        cmp     al, 2
        jae     .x
        inc     al
        cmp     byte [ask_kind], 1
        je      .set
        mov     al, 2
.set:   mov     [ask_sel], al
        call    draw_ask
.x:     ret

ask_answer:                             ; AL = 'y', 'a' or 'n'
        mov     [evans+2], al
        mov     al, [ask_id]
        mov     [evans+1], al
        mov     byte [evans], 02h
        mov     al, G_EVENT
        mov     dx, cs
        mov     si, evans
        mov     cx, 3
        call    txq_put
        mov     byte [ask_open], 0
        call    redraw_body
        ret

draw_help:
        pusha
        mov     dx, 3
        mov     cx, 16
        mov     si, s_helptitle
        call    draw_box
        push    es
        mov     ax, VSEG
        mov     es, ax
        mov     si, helptext
        mov     dx, 5
.l:     cmp     byte [si], 0FFh
        je      .x
        imul    di, dx, 320
        add     di, BOXL + 3
        xor     ah, ah
        mov     cx, 64
        push    si
        call    draw_strn
        pop     si
        call    skipz                   ; to the next line
        inc     dx
        jmp     .l
.x:     pop     es
        popa
        ret

; =====================================================================
;  keyboard
; =====================================================================
kbd_service:
        cmp     byte [term], 0
        je      .chat
        jmp     term_kbd
.chat:  mov     ah, 1
        int     16h
        jz      .x
        xor     ah, ah
        int     16h
        cmp     byte [help_open], 0
        jne     .help
        cmp     byte [ask_open], 0
        jne     .ask
        mov     si, keytab
.k:     mov     dx, [si]
        or      dx, dx
        jz      .other
        cmp     dx, ax
        je      .hit
        add     si, 4
        jmp     .k
.hit:   call    [si+2]
        ret
.other: cmp     al, 20h
        jb      .x
        cmp     al, 7Eh
        ja      .x
        call    ins_char
        ret
.help:  mov     byte [help_open], 0
        call    redraw_body
        ret
.ask:   call    ask_key
.x:     ret

keytab: dw 1C0Dh, k_enter
        dw 1C0Ah, k_newline             ; Ctrl-Enter
        dw 0E08h, k_bksp
        dw 5300h, k_del
        dw 4B00h, k_left
        dw 4D00h, k_right
        dw 4700h, k_home
        dw 4F00h, k_end
        dw 4800h, k_up
        dw 5000h, k_down
        dw 4900h, k_pgup
        dw 5100h, k_pgdn
        dw 7700h, k_top                 ; Ctrl-Home
        dw 7500h, k_bottom              ; Ctrl-End
        dw 011Bh, k_esc
        dw 3B00h, k_help                ; F1
        dw 1000h, k_quit                ; CODE-Q
        dw 2D00h, k_quit                ; CODE-X
        dw 260Ch, k_redraw              ; Ctrl-L
        dw 0

k_newline:
        mov     al, 0Ah
ins_char:                               ; AL = character
        mov     cx, [inlen]
        cmp     cx, MAXIN - 1
        jae     .x
        push    ax
        mov     si, inbuf - 1
        add     si, cx
        mov     di, si
        inc     di
        sub     cx, [incur]
        std
        rep     movsb
        cld
        pop     ax
        mov     bx, [incur]
        mov     [inbuf + bx], al
        inc     word [incur]
        inc     word [inlen]
        call    draw_prompt
.x:     ret

k_bksp: cmp     word [incur], 0
        je      .x
        dec     word [incur]
        call    del_at
.x:     ret

k_del:  mov     bx, [incur]
        cmp     bx, [inlen]
        jae     .x
        call    del_at
.x:     ret

del_at: mov     di, inbuf
        add     di, [incur]
        mov     si, di
        inc     si
        mov     cx, [inlen]
        sub     cx, [incur]
        dec     cx
        rep     movsb
        dec     word [inlen]
        call    draw_prompt
        ret

k_left: cmp     word [incur], 0
        je      .x
        dec     word [incur]
        call    draw_prompt
.x:     ret

k_right:
        mov     ax, [incur]
        cmp     ax, [inlen]
        jae     .x
        inc     word [incur]
        call    draw_prompt
.x:     ret

k_home: mov     word [incur], 0
        call    draw_prompt
        ret

k_end:  mov     ax, [inlen]
        mov     [incur], ax
        call    draw_prompt
        ret

k_up:   mov     al, [hist_sel]
        cmp     al, [hist_n]
        jae     .x
        inc     byte [hist_sel]
        call    hist_load
.x:     ret

k_down: cmp     byte [hist_sel], 0
        je      .x
        dec     byte [hist_sel]
        cmp     byte [hist_sel], 0
        jne     .l
        mov     word [inlen], 0
        mov     word [incur], 0
        call    draw_prompt
        ret
.l:     call    hist_load
.x:     ret

hist_load:                              ; entry hist_sel back from the newest
        mov     al, [hist_next]
        sub     al, [hist_sel]
        jns     .a
        add     al, HISTN
.a:     xor     ah, ah
        mov     bx, ax
        shl     bx, 1
        mov     cx, [hist_len + bx]
        imul    si, ax, HISTL
        add     si, hist
        mov     di, inbuf
        mov     [inlen], cx
        mov     [incur], cx
        rep     movsb
        call    draw_prompt
        ret

hist_push:
        mov     al, [hist_next]
        xor     ah, ah
        mov     bx, ax
        imul    di, ax, HISTL
        add     di, hist
        mov     cx, [inlen]
        cmp     cx, HISTL
        jbe     .c
        mov     cx, HISTL
.c:     shl     bx, 1
        mov     [hist_len + bx], cx
        mov     si, inbuf
        rep     movsb
        mov     al, [hist_next]
        inc     al
        cmp     al, HISTN
        jb      .n
        xor     al, al
.n:     mov     [hist_next], al
        cmp     byte [hist_n], HISTN
        jae     .x
        inc     byte [hist_n]
.x:     mov     byte [hist_sel], 0
        ret

k_pgup: add     word [view_off], CROWS - 2
        jmp     view_changed
k_pgdn: mov     ax, [view_off]
        sub     ax, CROWS - 2
        jns     .s
        xor     ax, ax
.s:     mov     [view_off], ax
        jmp     view_changed
k_top:  mov     word [view_off], 7FFFh
        jmp     view_changed
k_bottom:
        mov     word [view_off], 0
view_changed:
        cmp     byte [ask_open], 0
        jne     .x
        call    draw_conv
        call    draw_status
.x:     ret

k_esc:  cmp     byte [busy], 0
        je      .clear
        cmp     byte [int_sent], 0
        jne     .x
        mov     byte [int_sent], 1
        mov     al, G_EVENT
        mov     dx, cs
        mov     si, evint
        mov     cx, 1
        call    txq_put
        mov     si, st_interrupting
        call    set_status
        ret
.clear: mov     word [inlen], 0
        mov     word [incur], 0
        call    draw_prompt
.x:     ret

k_help: mov     byte [help_open], 1
        call    draw_help
        ret

k_quit: cmp     byte [busy], 0
        je      .q
        cmp     byte [quit_armed], 0
        jne     .q
        mov     byte [quit_armed], 1
        call    k_esc                   ; stop Claude first
        mov     si, st_quitarm
        call    set_status
        ret
.q:     mov     byte [quit], 1
        ret

k_redraw:
        call    redraw_all
        ret

k_enter:
        cmp     word [inlen], 0
        je      .x
        call    is_quit_cmd
        jnc     .notq
        mov     byte [quit], 1
        ret
.notq:  cmp     byte [connected], 0
        jne     .c
        mov     si, st_notconn
        call    set_status
        ret
.c:     call    hist_push
        cmp     byte [busy], 0
        je      .send
        cmp     byte [queued], 0
        jne     .full
        mov     si, inbuf
        mov     di, qbuf
        mov     cx, [inlen]
        mov     [qlen], cx
        rep     movsb
        mov     byte [queued], 1
        mov     si, st_queued
        call    set_status
        jmp     .clr
.full:  mov     si, st_qfull
        call    set_status
        ret
.send:  mov     si, inbuf
        mov     cx, [inlen]
        call    send_text
.clr:   mov     word [inlen], 0
        mov     word [incur], 0
        call    draw_prompt
.x:     ret

; CF if the input is /exit or /quit
is_quit_cmd:
        mov     si, s_exit
        call    .cmp
        jc      .yes
        mov     si, s_quit
        call    .cmp
        jc      .yes
        clc
        ret
.yes:   stc
        ret
.cmp:   mov     cx, [inlen]             ; CF clear = no match
        mov     di, inbuf
.l:     lodsb
        or      al, al
        jz      .end
        jcxz    .nm
        mov     ah, [di]
        cmp     ah, 'a'
        jb      .u
        sub     ah, 20h
.u:     cmp     al, ah
        jne     .nm
        inc     di
        dec     cx
        jmp     .l
.end:   jcxz    .m
.nm:    clc
        ret
.m:     stc
        ret

; DS:SI = prompt text, CX = length: echo it and send it
send_text:
        mov     di, pbuf
        mov     [plen], cx
        rep     movsb
        call    echo_prompt
        mov     al, G_PROMPT
        mov     dx, cs
        mov     si, pbuf
        mov     cx, [plen]
        call    txq_put
        mov     byte [busy], 1
        mov     byte [int_sent], 0
        mov     byte [quit_armed], 0
        mov     ax, [now]
        mov     [turn_t0], ax
        mov     byte [status_text], 0
        call    draw_status
        ret

%include "TERMKEYS.INC"

tick_service:
        mov     ax, [now]
        cmp     ax, [last_tick]
        je      .x
        mov     [last_tick], ax
        cmp     byte [busy], 0
        je      .c
        test    al, 1
        jnz     .c
        mov     bl, [spin]
        inc     bl
        cmp     bl, 10
        jb      .s
        xor     bl, bl
.s:     mov     [spin], bl
        call    draw_status
.c:     mov     ax, [now]
        sub     ax, [t_title]
        cmp     ax, 18
        jb      .x
        mov     ax, [now]
        mov     [t_title], ax
        mov     ah, 2Ch
        int     21h
        cmp     cl, [last_min]
        je      .x
        mov     [last_min], cl
        call    draw_title
.x:     ret

maybe_idle:                             ; HLT when nothing is due
        cmp     byte [lstate], LS_WAIT
        je      .x
        cmp     byte [req_ready], 0
        jne     .x
        cmp     byte [txq_n], 0
        jne     .x
        cmp     byte [nak_pending], 0
        jne     .x
        cmp     byte [resend], 0
        jne     .x
        cmp     byte [busy], 0
        jne     .x
        cmp     byte [pi_active], 0
        jne     .x
        mov     ah, 1                   ; typed ahead: keep going
        cmp     byte [term], 0
        je      .pk
        cmp     byte [keyn], 0          ; Term: keys waiting, or a key or a
        jne     .x                      ; screen change in the last 2 s
        mov     ax, [now]
        sub     ax, [t_active]
        cmp     ax, 36
        jb      .x
        mov     ah, 11h                 ; (01h would drop CODE-punctuation)
.pk:    int     16h
        jnz     .x
        sti                             ; (STI's shadow covers the HLT)
        hlt
.x:     ret

; =====================================================================
;  the link (GLP 1): TERMLINK.INC, and what CLAUDE does with it
; =====================================================================
%include "TERMLINK.INC"

msg_sent:
        cmp     byte [done_type], G_KEYS
        jne     .e
        mov     byte [keys_q], 0        ; the next keys can go
        ret
.e:     cmp     byte [done_type], G_EVENT
        jne     .r
        mov     byte [rep_q], 0         ; (Term's only EVENT: repaint)
        ret
.r:     cmp     byte [done_type], G_REPLY
        jne     .x
        mov     byte [reply_busy], 0
        cmp     byte [snap_reply], 0
        je      .x
        mov     byte [snap_reply], 0
        call    snap_free
.x:     ret

; the link went down (TERMLINK.INC link_fail): tell the user
link_lost:
        cmp     byte [connected], 0
        je      .nc
        mov     byte [connected], 0
        mov     byte [busy], 0
        mov     byte [ask_open], 0
        mov     si, st_lost
        call    set_status_quiet
        call    draw_title
        call    draw_prompt
        call    redraw_body
        ret
.nc:    cmp     byte [n_failrun], 3
        jb      .x
        mov     di, sline               ; "No answer at GPIB address 7 ..."
        mov     si, st_noans
        call    put_str
        mov     al, [nano]
        xor     ah, ah
        call    put_dec
        mov     si, st_noans2
        call    put_str
        mov     byte [di], 0
        mov     si, sline
        call    set_status
.x:     ret

; ---- frames from the Pi ------------------------------------------
pi_frame:                               ; BX = frame offset in rxbuf
        mov     al, [rxbuf+bx+1]
        mov     [pf_kind], al
        mov     cx, [rxbuf+bx+4]
        lea     si, [rxbuf+bx+6]
        and     al, 7Fh
        cmp     byte [connected], 0     ; the answer to our HELLO must be a HELLO:
        jne     .c                      ; anything else, start the link again
        cmp     al, P_HELLO
        je      .c
        jmp     link_fail
.c:     mov     byte [pi_active], 1
        cmp     al, P_NOP
        jne     .a
        mov     byte [pi_active], 0
        ret
.a:     sub     al, P_HELLO
        cmp     al, 0Bh
        jae     .x
        xor     ah, ah
        mov     di, ax
        shl     di, 1
        cmp     byte [term], 0
        jne     .t
        jmp     [pf_tab + di]
.t:     jmp     [pf_ttab + di]
.x:     ret
pf_tab: dw pf_hello, pf_nop, pf_text, pf_status, pf_reasm, pf_reasm
        dw pf_ready, pf_nop, pf_title, pf_clear, pf_cells
pf_ttab: dw pf_hello, pf_nop, pf_nop, pf_nop, pf_reasm, pf_nop  ; Term: the chat's
        dw pf_nop, pf_nop, pf_title, pf_nop, pf_cells           ; TEXT, ASK... ignored

pf_nop: ret

pf_hello:
        xor     bl, bl                          ; BL = Term (the Pi's flags)
        cmp     cx, 2
        jb      .f
        mov     bl, [si+1]
        and     bl, HF_TERM
.f:     mov     byte [connected], 1
        mov     byte [busy], 1                  ; the Pi sets up; READY ends it
        mov     ax, [now]
        mov     [turn_t0], ax
        mov     [t_active], ax
        mov     byte [n_failrun], 0
        mov     si, st_connected
        call    set_status_quiet
        cmp     bl, [term]
        je      .same
        mov     [term], bl                      ; the Pi chose the other way
        mov     byte [cur_on], 0
        or      bl, bl
        jz      .toch
        call    shadow_clear                    ; (the conversation's memory)
        jmp     .same
.toch:  call    conv_clear                      ; (it held Term's screen)
        call    redraw_all
.same:  cmp     byte [term], 0
        je      .chat
        mov     byte [busy], 0                  ; Term: no turns, no READY
        call    redraw_all
        ret
.chat:  call    draw_status
        call    draw_title
        call    draw_prompt
        ret

pf_cells:
        cmp     byte [term], 0
        je      .x
        mov     ax, [now]
        mov     [t_active], ax
        call    term_cells
.x:     ret

pf_text:
        call    conv_text
        call    conv_refresh
        ret

pf_status:
        mov     di, status_text
        cmp     cx, 70
        jbe     .c
        mov     cx, 70
.c:     rep     movsb
        mov     byte [di], 0
        call    draw_status
        ret

pf_title:
        mov     di, title_text
        cmp     cx, 70
        jbe     .c
        mov     cx, 70
.c:     rep     movsb
        mov     byte [di], 0
        call    draw_title
        ret

pf_clear:
        call    conv_clear
        ret

pf_ready:
        mov     byte [busy], 0
        mov     byte [int_sent], 0
        mov     byte [status_text], 0
        call    draw_status
        cmp     byte [queued], 0
        je      .x
        mov     byte [queued], 0
        mov     si, qbuf
        mov     cx, [qlen]
        call    send_text
.x:     ret

; REQUEST / ASK: collect the frames of one message in reqbuf
pf_reasm:
        cmp     byte [req_ready], 0     ; still holding an unrun request
        jne     .x
        mov     al, [pf_kind]
        and     al, 7Fh
        cmp     al, [rq_type]
        je      .add
        mov     [rq_type], al
        mov     word [rq_len], 0
        mov     byte [rq_over], 0
.add:   mov     ax, [rq_len]
        add     ax, cx
        cmp     ax, REQMAX
        ja      .over
        mov     di, reqbuf
        add     di, [rq_len]
        mov     [rq_len], ax
        rep     movsb
        jmp     .more
.over:  mov     byte [rq_over], 1
.more:  test    byte [pf_kind], 80h
        jnz     .x
        mov     al, [rq_type]
        mov     byte [rq_type], 0
        cmp     al, P_ASK
        je      .ask
        mov     byte [req_ready], 1     ; the main loop runs it
        ret
.ask:   call    open_ask
.x:     ret

; =====================================================================
;  requests from Claude
; =====================================================================
req_service:
        cmp     byte [req_ready], 0
        je      .x
        cmp     byte [reply_busy], 0
        jne     .x
        cmp     byte [txq_n], TXQN      ; room for the REPLY (txq_put would drop it)
        jae     .x
        mov     byte [req_ready], 0
        call    exec_request
.x:     ret

exec_request:
        mov     al, [reqbuf]
        mov     [rq_id], al
        cmp     byte [rq_over], 0
        je      .ok
        mov     byte [rq_over], 0
        mov     al, 0F0h                ; too large
        xor     cx, cx
        jmp     reply
.ok:    mov     al, [reqbuf+1]
        mov     si, optab
.l:     cmp     byte [si], 0
        je      .bad
        cmp     al, [si]
        je      .go
        add     si, 3
        jmp     .l
.go:    jmp     [si+1]
.bad:   mov     al, 0FFh
        xor     cx, cx
        jmp     reply

optab:  db 01h
        dw op_info
        db 02h
        dw op_dir
        db 03h
        dw op_read
        db 04h
        dw op_write
        db 05h
        dw op_delete
        db 06h
        dw op_rename
        db 07h
        dw op_mkdir
        db 08h
        dw op_rmdir
        db 09h
        dw op_stat
        db 0Ah
        dw op_free
        db 10h
        dw op_run
        db 11h
        dw op_screen
        db 20h
        dw op_gpib
        db 30h
        dw op_settime
        db 0

; AL = status, CX = data bytes already at ioseg:2 -> queue the REPLY
reply:  push    es
        mov     es, [ioseg]
        mov     ah, al
        mov     al, [rq_id]
        mov     [es:0], ax
        pop     es
        add     cx, 2
        mov     al, G_REPLY
        mov     dx, [ioseg]
        xor     si, si
        call    txq_put
        mov     byte [reply_busy], 1
        ret

; CF/AX from DOS, no data
dos_result:
        jc      .e
        xor     al, al
.e:     xor     cx, cx
        jmp     reply

op_info:
        push    es
        mov     es, [ioseg]
        mov     di, 2
        call    build_kv
        mov     cx, di
        sub     cx, 2
        pop     es
        xor     al, al
        jmp     reply

op_dir: mov     dx, dta
        mov     ah, 1Ah
        int     21h
        mov     dx, reqbuf+2
        mov     cx, 16h                 ; directories, hidden, system too
        mov     ah, 4Eh
        int     21h
        push    es
        mov     es, [ioseg]
        mov     di, 2
        jnc     .ent
        cmp     ax, 18
        je      .done
        cmp     ax, 2
        je      .done
        pop     es
        xor     cx, cx
        jmp     reply
.ent:   cmp     di, IOSIZE - 24
        ja      .done
        mov     al, [dta+15h]
        stosb
        mov     ax, [dta+16h]
        stosw
        mov     ax, [dta+18h]
        stosw
        mov     ax, [dta+1Ah]
        stosw
        mov     ax, [dta+1Ch]
        stosw
        mov     si, dta+1Eh
        mov     cx, 13
        rep     movsb
        mov     ah, 4Fh
        int     21h
        jnc     .ent
.done:  mov     cx, di
        sub     cx, 2
        pop     es
        xor     al, al
        jmp     reply

; offset (4), length (2), path
op_read:
        mov     dx, reqbuf+8
        mov     ax, 3D00h
        int     21h
        jc      .err
        mov     bx, ax
        mov     dx, [reqbuf+2]
        mov     cx, [reqbuf+4]
        mov     ax, 4200h
        int     21h
        jc      .errc
        mov     cx, [reqbuf+6]
        cmp     cx, IOSIZE - 2
        jbe     .n
        mov     cx, IOSIZE - 2
.n:     push    ds
        mov     ds, [ioseg]
        mov     dx, 2
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .errc
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     cx
        xor     al, al
        jmp     reply
.errc:  push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
.err:   xor     cx, cx
        jmp     reply

; mode (1: 0 create, 1 at offset, 2 append), offset (4), path, data
op_write:
        mov     si, reqbuf+7
.z:     lodsb
        or      al, al
        jnz     .z
        mov     [wr_data], si
        mov     cx, reqbuf
        add     cx, [rq_len]
        sub     cx, si
        mov     [wr_len], cx
        mov     dx, reqbuf+7
        cmp     byte [reqbuf+2], 0
        jne     .open
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .err
        mov     bx, ax
        jmp     .wr
.open:  mov     ax, 3D01h
        int     21h
        jnc     .seek
        cmp     ax, 2
        jne     .err
        cmp     byte [reqbuf+2], 2      ; append to a new file: create it
        jne     .err
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .err
.seek:  mov     bx, ax
        mov     dx, [reqbuf+3]
        mov     cx, [reqbuf+5]
        mov     ax, 4200h
        cmp     byte [reqbuf+2], 1
        je      .sk
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
.sk:    int     21h
        jc      .errc
.wr:    mov     cx, [wr_len]
        mov     dx, [wr_data]
        mov     ah, 40h
        int     21h
        jc      .errc
        mov     [wr_done], ax
        mov     ah, 3Eh
        int     21h
        push    es
        mov     es, [ioseg]
        mov     ax, [wr_done]
        mov     [es:2], ax
        pop     es
        xor     al, al
        mov     cx, 2
        jmp     reply
.errc:  push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
.err:   xor     cx, cx
        jmp     reply

op_delete:
        mov     dx, reqbuf+2
        mov     ah, 41h
        int     21h
        jmp     dos_result

op_rename:
        mov     si, reqbuf+2
        call    skipz
        mov     di, si
        mov     dx, reqbuf+2
        mov     ah, 56h
        int     21h
        jmp     dos_result

op_mkdir:
        mov     dx, reqbuf+2
        mov     ah, 39h
        int     21h
        jmp     dos_result

op_rmdir:
        mov     dx, reqbuf+2
        mov     ah, 3Ah
        int     21h
        jmp     dos_result

op_stat:
        mov     dx, dta
        mov     ah, 1Ah
        int     21h
        mov     dx, reqbuf+2
        mov     cx, 16h
        mov     ah, 4Eh
        int     21h
        jc      .err
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     al, [dta+15h]
        stosb
        mov     ax, [dta+16h]
        stosw
        mov     ax, [dta+18h]
        stosw
        mov     ax, [dta+1Ah]
        stosw
        mov     ax, [dta+1Ch]
        stosw
        pop     es
        mov     cx, 9
        xor     al, al
        jmp     reply
.err:   xor     cx, cx
        jmp     reply

op_free:
        mov     dl, [reqbuf+2]
        mov     ah, 36h
        int     21h
        cmp     ax, 0FFFFh
        jne     .ok
        mov     al, 15
        xor     cx, cx
        jmp     reply
.ok:    mov     si, dx                  ; total clusters
        mul     cx                      ; bytes per cluster
        mov     cx, ax
        mov     ax, bx
        mul     cx                      ; free bytes
        push    es
        mov     es, [ioseg]
        mov     [es:2], ax
        mov     [es:4], dx
        mov     ax, si
        mul     cx                      ; total bytes
        mov     [es:6], ax
        mov     [es:8], dx
        pop     es
        mov     cx, 8
        xor     al, al
        jmp     reply

; year (2), month, day, hour, minute, second
op_settime:
        mov     cx, [reqbuf+2]
        mov     dh, [reqbuf+4]
        mov     dl, [reqbuf+5]
        mov     ah, 2Bh
        int     21h
        mov     ch, [reqbuf+6]
        mov     cl, [reqbuf+7]
        mov     dh, [reqbuf+8]
        xor     dl, dl
        mov     ah, 2Dh
        int     21h
        mov     al, [reqbuf+6]          ; the real-time clock too (BCD)
        call    bin2bcd
        mov     ch, al
        mov     al, [reqbuf+7]
        call    bin2bcd
        mov     cl, al
        mov     al, [reqbuf+8]
        call    bin2bcd
        mov     dh, al
        xor     dl, dl
        mov     ah, 03h
        int     1Ah
        mov     ax, [reqbuf+2]
        mov     bl, 100
        div     bl                      ; AL = century, AH = year in century
        push    ax
        call    bin2bcd
        mov     ch, al
        pop     ax
        mov     al, ah
        call    bin2bcd
        mov     cl, al
        mov     al, [reqbuf+4]
        call    bin2bcd
        mov     dh, al
        mov     al, [reqbuf+5]
        call    bin2bcd
        mov     dl, al
        mov     ah, 05h
        int     1Ah
        call    draw_title
        xor     al, al
        xor     cx, cx
        jmp     reply

bin2bcd:
        aam
        shl     ah, 4
        or      al, ah
        ret

; ---- GPIB -------------------------------------------------------------
; op (1), address (1), flags (1), timeout ms (2), largest reply (2), data
op_gpib:
        mov     bx, [reqbuf+5]
        mov     ah, 0Ah
        call    gg_call
        mov     [old_tmo], ax
        mov     ax, [rq_len]
        sub     ax, 9
        mov     [gp_dlen], ax
        mov     cx, [reqbuf+7]
        cmp     cx, IOSIZE - 2
        jbe     .m
        mov     cx, IOSIZE - 2
.m:     mov     [gp_max], cx
        mov     al, [reqbuf+2]
        dec     al
        cmp     al, 9
        jae     .bad
        xor     ah, ah
        mov     di, ax
        shl     di, 1
        mov     bl, [reqbuf+3]
        call    [gp_tab + di]           ; -> AL = status, CX = bytes at ioseg:2
        jmp     .done
.bad:   mov     al, 4
        xor     cx, cx
.done:  push    ax
        push    cx
        mov     bx, [old_tmo]
        mov     ah, 0Ah
        call    gg_call
        pop     cx
        pop     ax
        jmp     reply

gp_tab: dw gp_write, gp_read, gp_query, gp_spoll, gp_clear, gp_trigger
        dw gp_local, gp_remote, gp_scan

gp_write:
        mov     si, reqbuf+9
        mov     cx, [gp_dlen]
        mov     al, [reqbuf+4]
        and     al, 1
        mov     ah, 02h
        call    gg_call
        jmp     gp_res0

gp_read:
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     cx, [gp_max]
        mov     al, [reqbuf+4]
        and     al, 1
        mov     ah, 03h
        call    gg_call
        pop     es
        jmp     gp_resc

gp_query:
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     si, reqbuf+9
        mov     cx, [gp_dlen]
        mov     dx, [gp_max]
        mov     al, [reqbuf+4]
        and     al, 1
        mov     ah, 04h
        call    gg_call
        pop     es
        jmp     gp_resc

gp_spoll:
        mov     ah, 05h
        call    gg_call
        jc      .e
        push    es
        mov     es, [ioseg]
        mov     [es:2], al
        pop     es
        mov     cx, 1
        xor     al, al
        ret
.e:     mov     al, ah
        xor     cx, cx
        ret

gp_clear:
        mov     ah, 06h
        call    gg_call
        jmp     gp_res0
gp_trigger:
        mov     ah, 07h
        call    gg_call
        jmp     gp_res0
gp_local:
        mov     ah, 09h
        call    gg_call
        jmp     gp_res0
gp_remote:
        mov     ah, 08h
        call    gg_call
        jmp     gp_res0

gp_scan:
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     bl, 1
.l:     cmp     bl, 21
        je      .n
        cmp     bl, [nano]
        je      .n
        mov     ah, 05h
        call    gg_call
        jc      .n
        mov     al, bl
        stosb
.n:     inc     bl
        cmp     bl, 31
        jb      .l
        mov     cx, di
        sub     cx, 2
        pop     es
        xor     al, al
        ret

gp_res0:                                ; driver CF/AX, no data
        jc      .e
        xor     al, al
.e:     xor     cx, cx
        ret

gp_resc:                                ; driver CF/AX, CX = bytes read
        jc      .e
        xor     al, al
        ret
.e:     xor     cx, cx
        ret

; ---- screen snapshots ---------------------------------------------
op_screen:
        cmp     byte [reqbuf+2], 1
        jne     .last
        call    snap_alloc
        jc      .nomem
        call    take_snapshot
.last:  cmp     byte [snap_taken], 0
        jne     .send
        mov     al, 0F5h
        xor     cx, cx
        jmp     reply
.nomem: mov     al, 0F1h
        xor     cx, cx
        jmp     reply
.send:  push    es
        mov     es, [snapseg]
        mov     al, [rq_id]
        mov     [es:0], al
        mov     byte [es:1], 0
        pop     es
        mov     cx, [snap_len]
        add     cx, 2
        mov     al, G_REPLY
        mov     dx, [snapseg]
        xor     si, si
        call    txq_put
        mov     byte [reply_busy], 1
        mov     byte [snap_reply], 1
        ret

; Copy the screen to snapseg: [2] mode, [3] banks, [4] bpp (0 = text),
; [5] width, [7] height, [9] bytes per line, [11] data.  Works from inside
; the INT 16h hook too, so every access goes through CS or explicit
; segments and all registers are kept.
take_snapshot:
        pusha
        push    ds
        push    es
        cld
        mov     ax, [cs:snapseg]
        or      ax, ax
        jnz     .go
        jmp     .x
.go:    mov     es, ax
        mov     ax, 40h
        mov     ds, ax
        mov     al, [49h]
        mov     [es:2], al
        mov     bx, [4Ah]
        mov     dx, [4Eh]
        cmp     al, 7
        je      .mono
        cmp     al, 3
        jbe     .text
        mov     byte [es:4], 1
        mov     word [es:5], 640
        mov     word [es:9], 80
        mov     cx, 2000h
        cmp     al, 6
        je      .cga1
        cmp     al, 4
        je      .cga2
        cmp     al, 5
        je      .cga2
        mov     byte [es:3], 4          ; 640x400 (mode 40h) and the rest
        mov     word [es:7], 400
        mov     cx, 4000h
        jmp     .copyg
.cga2:  mov     byte [es:4], 2
        mov     word [es:5], 320
.cga1:  mov     byte [es:3], 2
        mov     word [es:7], 200
.copyg: mov     ax, cx
        shl     ax, 1
        add     ax, 9
        mov     [cs:snap_len], ax
        mov     ax, VSEG
        mov     ds, ax
        xor     si, si
        mov     di, 11
        rep     movsw
        jmp     .done
.mono:  mov     ax, 0B000h
        jmp     .t2
.text:  mov     ax, VSEG
.t2:    mov     byte [es:3], 1
        mov     byte [es:4], 0
        mov     [es:5], bx
        mov     word [es:7], 25
        mov     cx, bx
        shl     cx, 1
        mov     [es:9], cx
        mov     cx, bx
        imul    cx, cx, 25
        push    cx
        shl     cx, 1
        add     cx, 9
        mov     [cs:snap_len], cx
        pop     cx
        mov     ds, ax
        mov     si, dx
        mov     di, 11
        rep     movsw
.done:  mov     byte [cs:snap_taken], 1
.x:     pop     es
        pop     ds
        popa
        ret

; ---- running DOS programs -----------------------------------------
; flags (1: bit0 capture, bit1 snapshot at exit), timeout (2),
; key script length (2), key script, command line
op_run: mov     si, reqbuf+2
        lodsb
        mov     [run_flags], al
        lodsw
        lodsw
        mov     [ks_len], ax
        mov     [ks_ptr], si
        add     si, ax
        mov     [run_cmd], si
        mov     word [ks_pos], 0
        mov     byte [ks_wait], 0
        mov     byte [snap_taken], 0
        test    byte [run_flags], 2
        jnz     .sb
        call    script_has_snap
        jnc     .ns
.sb:    call    snap_alloc
        jnc     .ns
        mov     al, 0F1h
        xor     cx, cx
        jmp     reply
.ns:    call    build_exec
        jnc     .go
        xor     cx, cx
        jmp     reply
.go:    mov     ax, 0003h               ; a plain text screen for the program
        int     10h
        call    vec_dos
        cmp     word [ks_len], 0
        je      .nh
        call    hook16
.nh:    call    do_exec
        mov     [run_err], ax
        pushf
        cmp     word [ks_len], 0
        je      .nu
        call    unhook16
.nu:    call    vec_ours
        popf
        jc      .fail
        mov     ah, 4Dh
        int     21h
        xor     ah, ah
        mov     [run_exit], ax
        test    byte [run_flags], 2
        jz      .back
        call    take_snapshot
.back:  call    video_on
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     ax, [run_exit]
        stosw
        mov     al, [run_flags]
        and     al, 1
        cmp     byte [snap_taken], 0
        je      .f
        or      al, 2
.f:     stosb
        mov     si, outname
        call    put_str
        xor     al, al
        stosb
        mov     cx, di
        sub     cx, 2
        pop     es
        xor     al, al
        jmp     reply
.fail:  call    video_on
        mov     al, [run_err]
        xor     cx, cx
        jmp     reply

; CF if the key script holds a snapshot mark
script_has_snap:
        mov     si, [ks_ptr]
        mov     cx, [ks_len]
.l:     cmp     cx, 2
        jb      .no
        cmp     byte [si], 0FFh
        jne     .key
        cmp     byte [si+1], 0FEh
        je      .yes
        cmp     byte [si+1], 0FFh
        jne     .key
        add     si, 3
        sub     cx, 3
        jae     .l
        jmp     .no
.key:   add     si, 2
        sub     cx, 2
        jmp     .l
.no:    clc
        ret
.yes:   stc
        ret

; exec_path + tail for run_cmd.  CF + AL = status on error.
build_exec:
        call    make_outname
        test    byte [run_flags], 1
        jnz     .shell
        call    resolve_direct          ; program found: run it directly
        jc      .shell
.sk:    cmp     byte [si], ' '
        jne     .dt
        inc     si
        jmp     .sk
.dt:    mov     di, tail+1
        mov     al, ' '
        stosb
        call    copy_tail_str
        jc      .long
        jmp     .fin
.shell: call    get_comspec
        mov     di, tail+1
        mov     si, s_slashc
        call    put_str
        mov     si, [run_cmd]
        call    copy_tail_str
        jc      .long
        test    byte [run_flags], 1
        jz      .fin
        mov     si, s_redir
        call    put_str
        mov     si, outname
        call    copy_tail_str
        jc      .long
.fin:   mov     ax, di
        sub     ax, tail+1
        mov     [tail], al
        mov     al, 0Dh
        stosb
        clc
        ret
.long:  mov     al, 0F3h
        stc
        ret

copy_tail_str:                          ; DS:SI -> ES:DI up to NUL; CF if too long
.l:     lodsb
        or      al, al
        jz      .ok
        cmp     di, tail + 126
        jae     .bad
        stosb
        jmp     .l
.ok:    clc
        ret
.bad:   stc
        ret

; first word of run_cmd as NAME, NAME.COM or NAME.EXE in exec_path.
; CF if not found; else SI -> the rest of the command line.
resolve_direct:
        mov     si, [run_cmd]
.sp:    cmp     byte [si], ' '
        jne     .tok
        inc     si
        jmp     .sp
.tok:   mov     di, exec_path
        xor     bx, bx
.c:     lodsb
        cmp     al, ' '
        je      .end
        or      al, al
        je      .end
        cmp     al, '.'
        jne     .s
        mov     bx, 1
.s:     stosb
        cmp     di, exec_path + 70
        jb      .c
        stc
        ret
.end:   dec     si
        mov     [run_rest], si
        mov     [ext_at], di
        or      bx, bx
        jz      .try
        xor     al, al
        stosb
        call    exists
        jc      .no
        jmp     .yes
.try:   mov     di, [ext_at]
        mov     si, s_dotcom
        call    copyz
        call    exists
        jnc     .yes
        mov     di, [ext_at]
        mov     si, s_dotexe
        call    copyz
        call    exists
        jnc     .yes
.no:    stc
        ret
.yes:   mov     si, [run_rest]
        clc
        ret

exists: mov     dx, dta                 ; exec_path -> CF if no such file
        mov     ah, 1Ah
        int     21h
        mov     dx, exec_path
        mov     cx, 07h
        mov     ah, 4Eh
        int     21h
        ret

; SI -> "NAME=" (ours): value to ES:DI (ASCIIZ).  CF if not in the environment.
env_get:
        push    ds
        push    bx
        mov     bx, si
        mov     ds, [2Ch]
        xor     si, si
.var:   cmp     byte [si], 0
        je      .none
        push    si
        push    bx
.cmp:   mov     al, [cs:bx]
        or      al, al
        jz      .hit
        cmp     al, [si]
        jne     .next
        inc     si
        inc     bx
        jmp     .cmp
.hit:   pop     bx
        pop     ax                      ; (start of the variable)
.cp:    lodsb
        stosb
        or      al, al
        jnz     .cp
        pop     bx
        pop     ds
        clc
        ret
.next:  pop     bx
        pop     si
.skip:  lodsb
        or      al, al
        jnz     .skip
        jmp     .var
.none:  pop     bx
        pop     ds
        stc
        ret

get_comspec:
        mov     si, s_comspec
        mov     di, exec_path
        call    env_get
        jnc     .x
        mov     si, s_defcomspec
        mov     di, exec_path
        call    copyz
.x:     ret

; outname = %TEMP%\CLAUDE.OUT, %TMP%\CLAUDE.OUT or X:\CLAUDE.OUT
make_outname:
        mov     si, s_temp
        mov     di, outname
        call    env_get
        jnc     .have
        mov     si, s_tmp
        mov     di, outname
        call    env_get
        jnc     .have
        mov     ah, 19h
        int     21h
        add     al, 'A'
        mov     di, outname
        stosb
        mov     al, ':'
        stosb
        jmp     .slash
.have:  dec     di                      ; back onto the NUL
        cmp     byte [di-1], '\'
        je      .name
.slash: mov     al, '\'
        stosb
.name:  mov     si, s_outfile
        call    copyz
        ret

do_exec:
        mov     [exec_ss], ss
        mov     [exec_sp], sp
        mov     word [epb], 0           ; our environment
        mov     word [epb+2], tail
        mov     [epb+4], cs
        mov     word [epb+6], fcb1
        mov     [epb+8], cs
        mov     word [epb+10], fcb2
        mov     [epb+12], cs
        mov     dx, exec_path
        mov     bx, epb
        mov     ax, 4B00h
        int     21h
        cli                             ; DOS 3 keeps only CS:IP
        mov     ss, [cs:exec_ss]
        mov     sp, [cs:exec_sp]
        sti
        push    cs
        pop     ds
        push    cs
        pop     es
        cld
        ret

hook16: mov     ax, 3516h
        int     21h
        mov     [old16], bx
        mov     [old16+2], es
        push    cs
        pop     es
        mov     dx, int16
        mov     ax, 2516h
        int     21h
        mov     byte [ks_active], 1
        ret

unhook16:
        mov     byte [ks_active], 0
        push    ds
        lds     dx, [old16]
        mov     ax, 2516h
        int     21h
        pop     ds
        ret

; INT 16h while a program runs: scripted keys first, then the keyboard.
int16:  cmp     byte [cs:ks_active], 0
        je      .chain
        cmp     ah, 0
        je      .read
        cmp     ah, 10h
        je      .read
        cmp     ah, 1
        je      .peek
        cmp     ah, 11h
        je      .peek
.chain: jmp     far [cs:old16]
.peek:  call    ks_ready
        jz      .chain                  ; nothing scripted now: real keyboard
        retf    2                       ; AX = key, ZF = 0
.read:  sti
.rl:    call    ks_ready
        jnz     .take
        cmp     byte [cs:ks_active], 0
        je      .chain
        push    ax                      ; a real key waiting?
        mov     ah, 1
        pushf
        call    far [cs:old16]
        pop     ax
        jnz     .chain
        hlt
        jmp     .rl
.take:  add     word [cs:ks_pos], 2
        iret

; ZF = 0 and AX = key if a scripted key is ready now; else ZF = 1, AX kept.
; Runs waits and snapshot marks as it meets them.
ks_ready:
        push    ax
        push    bx
        push    si
.again: mov     si, [cs:ks_pos]
        cmp     si, [cs:ks_len]
        jae     .end
        add     si, [cs:ks_ptr]
        mov     ax, [cs:si]
        cmp     ax, 0FFFFh
        je      .wait
        cmp     ax, 0FEFFh
        je      .snap
        pop     si
        pop     bx
        add     sp, 2                   ; drop the caller's AX; ZF = 0
        ret
.wait:  cmp     byte [cs:ks_wait], 0
        jne     .waiting
        push    ds
        push    40h
        pop     ds
        mov     bx, [6Ch]
        pop     ds
        mov     al, [cs:si+2]
        xor     ah, ah
        add     bx, ax
        mov     [cs:ks_until], bx
        mov     byte [cs:ks_wait], 1
.waiting:
        push    ds
        push    40h
        pop     ds
        mov     bx, [6Ch]
        pop     ds
        sub     bx, [cs:ks_until]
        js      .none
        mov     byte [cs:ks_wait], 0
        add     word [cs:ks_pos], 3
        jmp     .again
.snap:  call    take_snapshot
        add     word [cs:ks_pos], 3
        jmp     .again
.end:   mov     byte [cs:ks_active], 0
.none:  pop     si
        pop     bx
        pop     ax
        cmp     ax, ax                  ; ZF = 1
        ret

; =====================================================================
;  HELLO and INFO text
; =====================================================================
build_hello:                            ; -> CX = length of hellobuf
        mov     di, hellobuf
        mov     al, 1                   ; GLP version
        stosb
        mov     al, 1                   ; flags: bit 0, Term understood
        stosb
        mov     ax, TXMAX
        stosw
        mov     al, 80
        stosb
        mov     al, CROWS
        stosb
        call    build_kv
        mov     si, kv_appterm          ; CLAUDE /T or /C
        cmp     byte [app_want], 'T'
        je      .a
        mov     si, kv_appchat
        cmp     byte [app_want], 'C'
        jne     .n
.a:     call    put_str
.n:     mov     cx, di
        sub     cx, hellobuf
        ret

; key=value lines at ES:DI
build_kv:
        mov     si, kv_os
        call    put_str
        mov     ah, 30h
        int     21h
        push    ax
        xor     ah, ah
        call    put_dec
        mov     al, '.'
        stosb
        pop     ax
        mov     al, ah
        call    put_dec2
        mov     si, kv_cwd
        call    put_str
        mov     ah, 19h
        int     21h
        add     al, 'A'
        stosb
        mov     ax, ':\'                ; ':' then '\'
        stosw
        mov     si, cwdbuf
        mov     dl, 0
        mov     ah, 47h
        int     21h
        mov     si, cwdbuf
        call    put_str
        mov     si, kv_drives
        call    put_str
        mov     si, drvstr
        call    put_str
        mov     si, kv_mem
        call    put_str
        mov     bx, 0FFFFh
        mov     ah, 48h
        int     21h
        mov     ax, bx
        shr     ax, 6
        call    put_dec
        mov     si, kv_ems
        call    put_str
        cmp     byte [ems_ok], 0
        jne     .e
        mov     si, s_none2
        call    put_str
        jmp     .g
.e:     mov     ax, [ems_free]
        call    put_dec
        mov     al, '/'
        stosb
        mov     ax, [ems_total]
        call    put_dec
        mov     si, s_pages
        call    put_str
.g:     mov     si, kv_gpib
        call    put_str
        mov     al, [ggver+1]
        xor     ah, ah
        call    put_dec
        mov     al, '.'
        stosb
        mov     al, [ggver]
        call    put_hex8
        mov     si, s_onint
        call    put_str
        mov     al, [ggint]
        call    put_hex8
        mov     al, 'h'
        stosb
        mov     si, kv_addr
        call    put_str
        mov     al, [nano]
        xor     ah, ah
        call    put_dec
        mov     si, kv_date
        call    put_str
        mov     ah, 2Ah
        int     21h
        push    dx
        mov     ax, cx
        call    put_dec
        mov     al, '-'
        stosb
        pop     dx
        push    dx
        mov     al, dh
        call    put_dec2
        mov     al, '-'
        stosb
        pop     dx
        mov     al, dl
        call    put_dec2
        mov     al, ' '
        stosb
        mov     ah, 2Ch
        int     21h
        mov     al, ch
        call    put_dec2
        mov     al, ':'
        stosb
        mov     al, cl
        call    put_dec2
        mov     si, kv_grid
        call    put_str
        ret

; ---- small helpers -----------------------------------------------
put_str:                                ; DS:SI ASCIIZ -> ES:DI (no NUL)
.l:     lodsb
        or      al, al
        jz      .x
        stosb
        jmp     .l
.x:     ret

copyz:                                  ; DS:SI ASCIIZ -> ES:DI (with NUL)
.l:     lodsb
        stosb
        or      al, al
        jnz     .l
        ret

put_dec:                                ; AX -> ES:DI.  Destroys AX DX.
        push    bx
        push    cx
        mov     bx, 10
        xor     cx, cx
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.o:     pop     ax
        add     al, '0'
        stosb
        loop    .o
        pop     cx
        pop     bx
        ret

put_dec2:                               ; AL (0-99) -> two digits
        aam
        add     ax, 3030h
        xchg    al, ah
        stosw
        ret

put_hex8:                               ; AL -> two hex digits
        push    ax
        shr     al, 4
        call    .h
        pop     ax
        and     al, 0Fh
.h:     add     al, '0'
        cmp     al, '9'
        jbe     .s
        add     al, 7
.s:     stosb
        ret

fmt_clock:                              ; ES:DI <- "h:mm pm"
        mov     ah, 2Ch
        int     21h
        mov     al, ch
        mov     bl, 'a'
        cmp     al, 12
        jb      .am
        mov     bl, 'p'
        sub     al, 12
.am:    or      al, al
        jnz     .h
        mov     al, 12
.h:     xor     ah, ah
        push    cx
        call    put_dec
        pop     cx
        mov     al, ':'
        stosb
        mov     al, cl
        call    put_dec2
        mov     al, ' '
        stosb
        mov     al, bl
        stosb
        mov     al, 'm'
        stosb
        ret

; =====================================================================
;  data
; =====================================================================
sig_gg      db 'GRIDGPIB'
s_emm       db 'EMMXXXX0'
msg_nogg    db 'CLAUDE needs GRIDGPIB loaded first (run GRIDGPIB, then CLAUDE).', 13, 10, '$'
msg_nomem   db 'Not enough memory for CLAUDE.', 13, 10, '$'
msg_bye     db 'Claude for GRiD ended.', 13, 10, '$'
s_title0    db 8Bh, ' Claude for GRiD', 0
st_connecting db 'Connecting to the Pi through the GPIB bridge', 82h, 0
st_connected db 'Connected to the Pi', 0
st_lost     db 'Link to the Pi lost, reconnecting', 82h, 0
st_noans    db 'No answer from the bridge at GPIB address ', 0
st_noans2   db ' (is the Pi running?)', 0
st_notconn  db 'Not connected to the Pi yet', 0
st_queued   db 'Prompt queued; it goes when Claude finishes', 0
st_qfull    db 'A prompt is already queued', 0
st_interrupting db 'Interrupting', 82h, 0
st_quitarm  db 'Press CODE-Q again to quit', 0
s_working   db 'Working', 82h, 0
s_esc       db 's ', 86h, ' esc to interrupt)', 0
s_scrolled  db 'scrolled back ', 86h, ' PgDn', 0
s_f1help    db 'F1 help', 0
s_none      db 0
s_link      db 'GPIB link', 0
s_nolink    db 'no link', 0
s_opt_yes   db '[Y] Yes', 0
s_opt_a     db '[A] ', 0
s_opt_no    db '[N] No', 0
s_exit      db '/EXIT', 0
s_quit      db '/QUIT', 0
s_comspec   db 'COMSPEC=', 0
s_defcomspec db 'A:\COMMAND.COM', 0
s_temp      db 'TEMP=', 0
s_tmp       db 'TMP=', 0
s_outfile   db 'CLAUDE.OUT', 0
s_slashc    db ' /C ', 0
s_redir     db ' >', 0
s_dotcom    db '.COM', 0
s_dotexe    db '.EXE', 0
kv_os       db 'os=MS-DOS ', 0
kv_cwd      db 10, 'cwd=', 0
kv_drives   db 10, 'drives=', 0
kv_mem      db 10, 'mem=', 0
kv_ems      db 10, 'ems=', 0
kv_gpib     db 10, 'gpib=GRIDGPIB ', 0
kv_addr     db 10, 'addr=', 0
kv_date     db 10, 'date=', 0
kv_grid     db 10, 'grid=CLAUDE 1.1', 10, 0
kv_appterm  db 'app=term', 10, 0
kv_appchat  db 'app=chat', 10, 0
s_tkeys     db 'CODE-Q quits  CODE-R repaints', 0
evrepaint   db 03h
s_onint     db ' on INT ', 0
s_none2     db 'none', 0
s_pages     db ' pages free', 0
s_helptitle db 'Claude for GRiD ', 86h, ' keys', 0
helptext    db 'Enter         send the prompt', 0
            db 'Ctrl-Enter    new line in the prompt', 0
            db 'Esc           interrupt Claude, or clear the prompt', 0
            db 'Up / Down     earlier prompts', 0
            db 'PgUp / PgDn   scroll the conversation; Ctrl-End = newest', 0
            db 'Y / A / N     answer a question (Yes, Always, No)', 0
            db 'CODE-Q        quit', 0
            db ' ', 0
            db '/help lists Claude', 27h, 's commands: /clear /compact /model', 0
            db '/mode /cost /status /memory /init', 0
            db 0FFh
spinseq     db 87h, 88h, 89h, 8Ah, 8Bh, 8Ch, 8Bh, 8Ah, 89h, 88h
evint       db 01h
fcb1        db 0, '           ', 0, 0, 0, 0
fcb2        db 0, '           ', 0, 0, 0, 0
blankline:
%rep 80
            db ' ', 0
%endrep

%include "TERMINUS.INC"
%include "GLYPHS.INC"

            align 16
bss:
absolute bss
nano        resb 1
ggint       resb 1
ggver       resw 1
convseg     resw 1
ioseg       resw 1
snapseg     resw 1
oldmode     resb 1
vid_saved   resb 1
old23       resd 1
old24       resd 1
old16       resd 1
quit        resb 1
quit_armed  resb 1
now         resw 1
last_tick   resw 1
t_title     resw 1
last_min    resb 1
drvstr      resb 80
ems_ok      resb 1
ems_free    resw 1
ems_total   resw 1
; conversation
c_head      resw 1
c_count     resw 1
c_col       resw 1
c_attr      resb 1
c_dirty_full resb 1
c_dirty_col resw 1
view_off    resw 1
; prompt
inlen       resw 1
incur       resw 1
vstart      resw 1
inbuf       resb MAXIN
pbuf        resb MAXIN
plen        resw 1
qbuf        resb MAXIN
qlen        resw 1
queued      resb 1
hist        resb HISTN * HISTL
hist_len    resw HISTN
hist_n      resb 1
hist_next   resb 1
hist_sel    resb 1
; state
connected   resb 1
busy        resb 1
int_sent    resb 1
turn_t0     resw 1
spin        resb 1
status_text resb 72
title_text  resb 72
sline       resb 160
rbuf        resb 64
; link
lstate      resb 1
g_seq       resb 1
p_ack       resb 1
have_pi     resb 1
nak_pending resb 1
resend      resb 1
pi_active   resb 1
pend_msg    resb 1
pend_chunk  resw 1
done_type   resb 1
t_sent      resw 1
t_last      resw 1
t_reset     resw 1
n_fail      resw 1
n_failrun   resb 1
n_bad       resw 1
spoll_errs  resb 1
pit_last    resw 1
pit_tick    resw 1
txq_head    resb 1
txq_n       resb 1
txq         resb TXQN * 10
txlen       resw 1
txframe     resb TXMAX + 8
nakframe    resb 8
rxn         resw 1
rxbuf       resb RXMAX + 1
pf_kind     resb 1
rq_type     resb 1
rq_len      resw 1
rq_over     resb 1
rq_id       resb 1
req_ready   resb 1
reply_busy  resb 1
snap_reply  resb 1
reqbuf      resb REQMAX + 4
hellobuf    resb 512
evans       resb 4
crctab      resw 256
; Term
term        resb 1                      ; 1: the GRiD is Claude Code's terminal
app_want    resb 1                      ; 'T' or 'C' from the command line
t_active    resw 1                      ; tick of the last key or screen change
keyn        resb 1
keys_q      resb 1                      ; a KEYS message is in the queue
rep_q       resb 1                      ; a repaint EVENT is in the queue
keybuf      resw KEYMAX
keysend     resw KEYMAX
shadseg     resw 1                      ; TROWS x 80 (glyph, attribute)
cur_on      resb 1
cur_di      resw 1
t_flags     resb 1
t_cur       resw 1
; dialogs
ask_open    resb 1
help_open   resb 1
ask_id      resb 1
ask_kind    resb 1
ask_sel     resb 1
ask_q       resw 1
ask_d       resw 1
ask_a       resw 1
askbuf      resb ASKMAX
optbuf      resb 56
; requests
dta         resb 44
cwdbuf      resb 68
old_tmo     resw 1
gp_dlen     resw 1
gp_max      resw 1
wr_data     resw 1
wr_len      resw 1
wr_done     resw 1
run_flags   resb 1
run_cmd     resw 1
run_rest    resw 1
run_exit    resw 1
run_err     resw 1
ext_at      resw 1
exec_path   resb 80
outname     resb 80
tail        resb 130
epb         resw 7
exec_ss     resw 1
exec_sp     resw 1
ks_active   resb 1
ks_len      resw 1
ks_ptr      resw 1
ks_pos      resw 1
ks_wait     resb 1
ks_until    resw 1
snap_taken  resb 1
snap_len    resw 1
            resb 2048
stack_top:
bss_end:
