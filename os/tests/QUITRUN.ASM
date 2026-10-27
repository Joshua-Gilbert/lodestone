; QUITRUN.RUN - a window .RUN that ends the root process (tests/test_mt.py
; t_wroot): two UI_ALLOC blocks (64 and 32 paragraphs), a window; Q: INT
; 21h AH=4Ch from inside it, so the Executive starts over (run_cleanup,
; KMW's mw_clean for the other sessions).  ESC: the end.
;   python3 mkrun.py tests/QUITRUN.ASM tests/QUITRUN.RUN
%include "UIAPI.INC"
RUN_API equ 8
RUN_FLAGS equ RF_WIN
        org     RUN_ORG

start:  mov     bx, 64
        call    UI_ALLOC
        jc      .x
        mov     [bseg], ax
        mov     bx, 32
        call    UI_ALLOC
        jc      .x
        mov     [bseg2], ax
        mov     si, win
        call    UI_WOPEN
.l:     call    UI_EVENT
        cmp     ax, K_ESC
        je      .end
        cmp     al, 'Q'
        jne     .l
        mov     ax, 4C07h
        int     21h
        jmp     .l
.end:   call    UI_WCLOSE
.x:     xor     ax, ax
        ret

win     dw      30, 100, 20, 60, s_win, 0, 0
s_win   db      'Quit test', 0

section .bss
bseg    resw    1
bseg2   resw    1
run_bss_end:
