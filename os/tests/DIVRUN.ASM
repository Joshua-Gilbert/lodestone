; DIVRUN.RUN - a .RUN with a divide error (KCORE.INC's int00; test_apps.py
; t_divrun, test_mt.py t_divmt): a UI_ALLOC block (64 paragraphs), its own
; file open (DIVRUN.RUN, read), a window; then keys:
;   M  a divide by zero in its own loop
;   D  a divide by zero in a key handler UI_DISPATCH calls
;   F  DIVRUN.RUN opened again and again till the handle table is full
;      (error 4), all left open
;   K  the end with its file left open: the window closed, exit code 6
;   ESC  the end: the window closed, the file closed, exit code 5
; A window .RUN (RF_WIN): with MULTITASK=1 a session beside others; the
; core with the switch off ignores the flag.
;   python3 mkrun.py tests/DIVRUN.ASM tests/DIVRUN.RUN
%include "UIAPI.INC"
RUN_API equ 8
RUN_FLAGS equ RF_WIN
        org     RUN_ORG

start:  mov     bx, 64
        call    UI_ALLOC
        jc      .x
        mov     [bseg], ax
        mov     dx, s_file
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     [hnd], ax
        mov     si, win
        call    UI_WOPEN
        mov     si, s_in
        mov     bx, 32
        mov     dx, 120
        xor     ah, ah
        call    UI_PUTS
.l:     call    UI_EVENT
        cmp     ax, K_ESC
        je      .end
        cmp     al, 'K'
        je      .keep
        cmp     al, 'M'
        jne     .k
        xor     bx, bx
        div     bx
        jmp     .l
.keep:  call    UI_WCLOSE
        mov     ax, 6
        ret
.k:     mov     si, keys
        call    UI_DISPATCH
        jmp     .l
.end:   call    UI_WCLOSE
        mov     bx, [hnd]
        mov     ah, 3Eh
        int     21h
        mov     ax, 5
        ret
.x:     mov     ax, 1
        ret

k_div:  xor     dx, dx
        xor     cx, cx
        div     cx
        ret

k_fill: mov     dx, s_file
.f:     mov     ax, 3D00h
        int     21h
        jnc     .f
        mov     [fillerr], ax
        ret

keys:   KEY('D', k_div, 0)
        KEY('F', k_fill, 0)
        dw 0

win     dw      30, 100, 20, 60, s_win, 0, 0
s_win   db      'Divide test', 0
s_in    db      'DIVRUN', 0
s_file  db      'DIVRUN.RUN', 0

section .bss
bseg    resw    1
hnd     resw    1
fillerr resw    1                       ; (F: the error that stopped it)
run_bss_end:
