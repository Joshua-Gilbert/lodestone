; MENUTEST.RUN - UI_MENU and UI_MOUSE (UI API 8) as a .RUN sees them
; (tests/test_apps.py t_menu, tests/test_mt.py).  A window .RUN: it opens
; its window (a pattern inside) at the start; ESC closes it, and ESC with
; none open ends it.  A right click: UI_MENU there (its answer in mres,
; 0FFFFh for none; nmenu counts them).  M and N: the menu at (639, 399)
; and at (0, 0) (M with the fourth item lit first, N with AH past the
; last); T: 20 items at (100, 399); L: one item longer than a line; O:
; one more window (ESC closes those first); U: UI_MOUSE once (dcf); Z and
; V: UI_MENU with 0 and 21 items (refused); H: UI_HELP, its title longer
; than its line; W: UI_HELP, a line longer than the screen.  A left click: UI_MOUSE until the left button is up
; (dn samples, the first and the last in d0 and d1, dcf its CF).  Every
; event UI_EVENT gives goes into evs (AX; nevs of them).
;   python3 mkrun.py tests/MENUTEST.ASM tests/MENUTEST.RUN
%include "UIAPI.INC"
RUN_API equ 8
RUN_FLAGS equ RF_WIN
        org     RUN_ORG

start:  call    UI_VERSION
        mov     [ver], ax
        mov     si, win
        call    UI_WOPEN
        mov     byte [wopen], 1
.l:     call    UI_EVENT
        mov     di, [nevs]
        cmp     di, 64
        jae     .full
        add     di, di
        mov     [evs + di], ax
        inc     word [nevs]
.full:  cmp     ax, K_ESC
        jne     .r
        cmp     byte [nmore], 0         ; (the windows O opened first)
        je      .w
        dec     byte [nmore]
        call    UI_WCLOSE
        jmp     .l
.w:     cmp     byte [wopen], 0
        je      .x
        mov     byte [wopen], 0
        call    UI_WCLOSE
        jmp     .l
.r:     cmp     ax, EV_RCLICK
        je      .menu
        cmp     ax, EV_CLICK
        je      .drag
        xchg    dx, ax                  ; (DL: the key)
        cmp     dl, 'U'                 ; U: UI_MOUSE once (its CF in dcf)
        je      .mouse
        mov     si, hkeys
        mov     di, s_htitle
        cmp     dl, 'H'                 ; H: help, the title its longest line
        je      .help
        mov     si, wkeys
        mov     di, s_win2
        cmp     dl, 'W'                 ; W: help, a line wider than the screen
        je      .help
        mov     bx, 100
        mov     cx, 100
        mov     si, many
        xor     ax, ax                  ; Z: no items
        cmp     dl, 'Z'
        je      .call
        mov     al, 21                  ; V: one item too many
        cmp     dl, 'V'
        je      .call
        mov     bx, 639
        mov     cx, 399
        mov     si, items
        mov     ax, (3 << 8) | NITEMS   ; M: the fourth lit first
        cmp     dl, 'M'
        je      .call
        mov     bx, 100
        mov     si, many
        mov     ax, 20                  ; T: 20 items, near the band
        cmp     dl, 'T'
        je      .call
        cmp     dl, 'O'                 ; O: one more window (ESC closes it)
        je      .more
        mov     bx, 300
        mov     cx, 100
        mov     si, longi
        mov     ax, 1
        cmp     dl, 'L'                 ; L: an item too long for the screen
        je      .call
        xor     bx, bx
        xor     cx, cx
        mov     si, items
        mov     ax, (9 << 8) | NITEMS   ; N: AH past the last item
        cmp     dl, 'N'
        je      .call
        jmp     .l
.help:  call    UI_HELP
        jmp     .l
.mouse: call    UI_MOUSE
        sbb     dx, dx
        mov     [dcf], dx
        jmp     .l
.more:  mov     si, win2
        call    UI_WOPEN
        inc     byte [nmore]
        jmp     .l
.menu:  mov     si, items
        mov     ax, NITEMS
.call:  call    UI_MENU
        jnc     .got
        mov     ax, 0FFFFh
.got:   mov     [mres], ax
        inc     word [nmenu]
        jmp     .l
.drag:  mov     word [dn], 0
.d:     call    UI_MOUSE
        sbb     dx, dx
        mov     [dcf], dx
        jc      .l
        cmp     word [dn], 0
        jne     .d1
        mov     [d0], ax
        mov     [d0 + 2], bx
        mov     [d0 + 4], cx
.d1:    mov     [d1], ax
        mov     [d1 + 2], bx
        mov     [d1 + 4], cx
        inc     word [dn]
        test    al, 1
        jnz     .d
        jmp     .l
.x:     xor     ax, ax
        ret

; the window: a pattern of 55h bytes inside
paint:  mov     dx, [bx+W_Y]
        add     dx, W_TOP
        mov     cx, [bx+W_H]
        sub     cx, W_TOP + 4
        mov     bp, [bx+W_W]
        sub     bp, 2
        mov     bx, [bx+W_COL]
        inc     bx
        mov     al, 55h
        jmp     UI_FILL

NITEMS  equ 5
items   dw s_cut, s_copy, s_paste, s_erase, s_find
many    times 4 dw s_cut, s_copy, s_paste, s_erase, s_find
s_cut   db 'Cut       CODE-Z',0
s_copy  db 'Copy      CODE-C',0
s_paste db 'Paste     CODE-V',0
s_erase db 'Erase     CODE-E',0
s_find  db 'Find...   CODE-F',0
longi   dw s_long
s_long  db 'A very long item, longer than a line of the screen: ninety characters, and then some more.',0
hkeys   KEY(K_NONE, 0, s_cut)
        dw 0
wkeys   KEY(K_NONE, 0, s_long)
        dw 0
s_htitle db 'Help with a title longer than any line',0
win2    dw 50, 200, 20, 60, s_win2, 0, 0
s_win2  db 'More',0
win     dw 4, 48, 72, 280, s_win, paint, WF_MOVE | WF_CLOSE
s_win   db 'Menu test',0

section .bss
ver     resw 1
wopen   resb 1
nmore   resb 1
mres    resw 1
nmenu   resw 1
dn      resw 1
dcf     resw 1
d0      resw 3
d1      resw 3
nevs    resw 1
evs     resw 64
run_bss_end:
