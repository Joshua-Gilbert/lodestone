; UITEST.RUN - exercises the UI core API from a .RUN (tests/test_apps.py)
;   python3 mkrun.py tests/UITEST.ASM tests/UITEST.RUN
%include "UIAPI.INC"
RUN_API equ 4
        org     RUN_ORG

start:  mov     [arg], si               ; (an absolute fixup)
        mov     si, redraw
        call    UI_SETREDRAW            ; (a relative fixup)
        cmp     word [zero], 0          ; the loader zeroes BSS
        jne     .bad
        cmp     word [zero+98], 0
        jne     .bad
        mov     bx, 100                 ; left allocated: the loader frees it
        call    UI_ALLOC
        jc      .bad
        mov     [blk], ax
        call    redraw
.loop:  call    UI_EVENT
        cmp     ax, K_ESC
        je      .quit
        cmp     ax, EV_CLICK
        jne     .key
        mov     bx, lst
        call    UI_LVCLICK
        jmp     .loop
.key:
        mov     si, keys
        call    UI_DISPATCH
        jnc     .loop
        mov     bx, lst
        call    UI_LVKEY
        jmp     .loop
.quit:  mov     ax, 42
        ret
.bad:   mov     ax, 99
        ret

redraw: mov     si, title
        call    UI_SCREEN
        mov     si, b1
        mov     di, b2
        call    UI_BAND
        mov     si, s_arg
        mov     bx, 2
        mov     dx, 300
        xor     ah, ah
        call    UI_PUTS
        mov     si, [arg]
        mov     bx, 12
        call    UI_PUTS
        mov     di, line                ; "Find: <text> 1 2"
        mov     si, s_find
        call    UI_SBSTR
        mov     si, f_text
        call    UI_SBSTR
        mov     al, ' '
        stosb
        mov     al, [f_match]
        xor     ah, ah
        call    UI_SBU16
        mov     al, ' '
        stosb
        mov     al, [f_dir]
        xor     ah, ah
        call    UI_SBU16
        mov     byte [di], 0
        mov     si, line
        mov     bx, 2
        mov     dx, 320
        xor     ah, ah
        call    UI_PUTS
        mov     bx, lst
        jmp     UI_LVDRAW

row:    mov     di, line                ; AX = item, DX = y, CL = mask
        push    cx
        push    ax
        mov     si, s_item
        call    UI_SBSTR
        pop     ax
        inc     ax
        call    UI_SBU16
        mov     byte [di], 0
        pop     cx
        mov     ah, cl
        mov     si, line
        mov     bx, 4
        jmp     UI_PUTS

name:   mov     si, s_item              ; every item starts "Item"
        ret

do_help:
        mov     si, keys
        mov     di, title
        jmp     UI_HELP

do_form:
        mov     si, form
        call    UI_FORM
        jc      .x
        jmp     redraw
.x:     ret

do_ask: mov     si, s_ask
        call    UI_ASK
        mov     si, s_yes
        jnc     .y
        mov     si, s_no
.y:     mov     dx, 280
        mov     bx, 2
        xor     ah, ah
        jmp     UI_PUTS

do_err: mov     di, line                ; error 19's message
        mov     ax, 19
        call    UI_SBERR
        mov     byte [di], 0
        mov     si, line
        mov     dx, 260
        mov     bx, 2
        xor     ah, ah
        jmp     UI_PUTS

do_run: mov     si, s_self              ; UI_RUN on a .RUN: must be error 11
        mov     di, s_empty
        call    UI_RUN
        mov     di, line
        mov     si, s_runok
        jnc     .r
        mov     si, s_runerr
.r:     call    UI_SBSTR
        call    UI_SBU16
        mov     byte [di], 0
        mov     si, line
        mov     dx, 240
        mov     bx, 2
        xor     ah, ah
        jmp     UI_PUTS

keys:   KEY(K_F1,     do_help, h1)
        KEY(K_CODE_F, do_form, h2)
        KEY(K_CODE_Q, do_ask,  h3)
        KEY(K_CODE_E, do_err,  0)
        KEY(K_CODE_R, do_run,  0)
        KEY(K_NONE,   0,       h4)
        dw 0

lst:    dw 40, 10, 30, 0, 0, row, 0, 1, 78, name
form:   dw s_ftitle, s_fprompt, 50, 10, 3
        dw l_find,  FT_TEXT + (30 << 8), f_text, 30
        dw l_match, FT_CHOICE, f_match, o_match
        dw l_dir,   FT_CHOICE, f_dir, o_dir

title   db 'UI test',0
b1      db 'UI test: Select an item and confirm',0
b2      db 'Or press CODE-? for help',0
s_arg   db 'Argument:',0
s_find  db 'Find: ',0
s_self  db 'UITEST.RUN',0
s_empty db 0
s_runok db 'UI_RUN ran it: ',0
s_runerr db 'UI_RUN error ',0
s_item  db 'Item ',0
s_ask   db 'Quit: Confirm to quit',0
s_yes   db 'confirmed',0
s_no    db 'cancelled',0
h1      db 'F1         this help',0
h2      db 'CODE-F     the form',0
h3      db 'CODE-Q     ask',0
h4      db 'ESC        leave',0
s_ftitle db 'Find',0
s_fprompt db 'Find: Fill in form and confirm',0
l_find  db 'Find',0
l_match db 'Match',0
l_dir   db 'Direction',0
o_match db 'Independent of case',0,'Exactly',0,0
o_dir   db 'Forward',0,'Backward',0,0
f_text  db 'hello'
        times 32 db 0
f_match db 0
f_dir   db 0

section .bss
arg     resw 1
blk     resw 1
line    resb 80
zero    resb 100
run_bss_end:
