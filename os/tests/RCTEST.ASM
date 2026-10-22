; RCTEST.RUN - right clicks (UI API 7) as a .RUN sees them (tests/test_apps.py
; t_rclick).  Every event UI_EVENT gives goes into evs (AX, BX, CX; nevs of
; them).  E: UI_EDIT on ebuf (its key in edkey), A: UI_ASK (its CF in ask),
; ESC: the end.  RC6.ASM builds the same for API 6: no right clicks.
;   python3 mkrun.py tests/RCTEST.ASM tests/RCTEST.RUN
%include "UIAPI.INC"
%ifndef RC_API
RUN_API equ 7
%else
RUN_API equ RC_API
%endif
        org     RUN_ORG

start:  call    UI_CLS
.l:     call    UI_EVENT
        mov     di, [nevs]
        cmp     di, 32
        jae     .full
        imul    di, di, 6
        mov     [evs + di], ax
        mov     [evs + di + 2], bx
        mov     [evs + di + 4], cx
        inc     word [nevs]
.full:  cmp     ax, K_ESC
        jne     .k
        cmp     byte [wopen], 0         ; (ESC closes the window first)
        je      .x
        mov     byte [wopen], 0
        call    UI_WCLOSE
        jmp     .l
.k:
        cmp     al, 'E'
        je      .edit
        cmp     al, 'W'                 ; W: a window that moves (ESC closes it)
        jne     .a
        mov     si, win
        call    UI_WOPEN
        mov     byte [wopen], 1
        jmp     .l
.a:
        cmp     al, 'A'
        jne     .l
        mov     si, s_ask
        call    UI_ASK
        sbb     ax, ax
        inc     ax                      ; (1: confirmed, 0: cancelled)
        mov     [ask], ax
        jmp     .l
.edit:  mov     si, ebuf
        mov     bp, 20
        mov     bx, 10
        mov     dx, 100
        mov     cx, 20
        call    UI_EDIT
        mov     [edkey], ax
        jmp     .l
.x:     xor     ax, ax
        ret

s_ask   db 'Ask: Confirm',0
win     dw 20, 100, 30, 80, s_win, 0, WF_MOVE | WF_CLOSE
s_win   db 'Window',0

section .bss
wopen   resb 1
nevs    resw 1
evs     resw 3 * 32
edkey   resw 1
ask     resw 1
ebuf    resb 24
run_bss_end:
