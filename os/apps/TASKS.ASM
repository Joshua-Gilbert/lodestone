; =====================================================================
;  TASKS.RUN - the tasks (MULTITASK=1): a window over the Executive
;  (CODE-T).  python3 mkrun.py apps/TASKS.ASM apps/TASKS.RUN
;
;  One row a task (MTAPI.INC's MT_LIST): its number, its program, what it
;  is doing, and whether it may run behind ("auto": unless it writes the
;  screen itself; "yes": SPF_BG; "no": SPF_FREEZE).  Return brings the
;  task to the front (a parked one is brought back first) and closes the
;  window: the change comes at the Executive's next wait.  CODE-Z parks a
;  task or brings it back, CODE-B goes round auto, yes, no, CODE-D ends
;  it (after a question).  The list is as it was when the window opened or
;  at the last change: F5 looks again.  A task asked to end goes at its
;  next turn (this window's wait is a safe point); its row says so till
;  the list is read again.
;
;  As the calculator, it never sets a redraw routine and ends with exit
;  code 0FFFFh (the screen as it was), or 0 if the saver repainted the
;  Executive under it.  The window moves and closes (API 6).
; =====================================================================
%include "UIAPI.INC"
%include "MTAPI.INC"
RUN_API equ 6
RUN_FLAGS equ RF_WIN                    ; (a window .RUN, M8)
        org     RUN_ORG

WCOL    equ 16                          ; the window, where it first opens
WY      equ 64
WW      equ 48
WH      equ 228
LROW    equ W_TOP + 20                  ; the list's first row, in the window
HROW    equ LROW + MT_TASKS * 16 + 12   ; the keys' two lines

start:  call    refresh
        mov     si, win
        call    UI_WOPEN
.loop:  call    UI_EVENT
        cmp     ax, EV_CLICK
        je      .click
        cmp     ax, EV_MOVED
        je      .loop
        mov     si, keys
        call    UI_DISPATCH
        jnc     .next
        mov     bx, lst
        call    UI_LVKEY
.next:  cmp     byte [quit], 0
        je      .loop
        call    UI_WCLOSE
        mov     ax, 0FFFFh              ; the screen is as it was,
        cmp     byte [paints], 1
        je      .r
        xor     ax, ax                  ;  or redraw the Executive
.r:     ret
.click: mov     ax, [win+W_COL]         ; (UI_LVCLICK looks only at y)
        shl     ax, 3
        cmp     bx, ax
        jb      .loop
        add     ax, (WW - 1) * 8
        cmp     bx, ax
        jae     .loop
        mov     bx, lst
        call    UI_LVCLICK
        jc      .loop
        cmp     al, 1                   ; the selected row again: Return
        jne     .loop
        call    k_front
        jmp     .next

; the tasks again (MT_LIST), each one's SPF_BG and SPF_FREEZE (MT_FLAGS)
refresh:
        mov     di, recs
        mov     cx, MT_TASKS
        mov     ax, 0F000h + MT_LIST
        stc
        int     21h
        jnc     .on
        mov     byte [off], 1           ; (off: no list)
        xor     cx, cx
.on:    cmp     cx, MT_TASKS
        jbe     .n
        mov     cx, MT_TASKS
.n:     mov     [lst+LV_N], cx
        mov     [front], al
        jcxz    .s
        mov     si, recs
        mov     di, flags
.f:     push    cx
        mov     bl, [si+TR_ID]
        xor     cx, cx
        mov     ax, 0F000h + MT_FLAGS   ; (task 0: CF, none)
        stc
        int     21h
        jnc     .fl
        mov     al, 0FFh
.fl:    mov     [di], al
        mov     al, [si+TR_ID]          ; (asked to end, and still there: as
        cmp     al, [ending]            ;  it was asked)
        jne     .nf
        mov     bl, al
        mov     ax, 0F000h + MT_EXIT
        stc
        int     21h
        jc      .ne
        cmp     ah, [endgen]
        je      .nf
.ne:    mov     byte [ending], 0FFh
.nf:    inc     di
        add     si, MT_REC
        pop     cx
        loop    .f
.s:     mov     ax, [lst+LV_SEL]        ; the selection still in the list
        mov     cx, [lst+LV_N]
        cmp     ax, cx
        jb      .x
        mov     ax, cx
        dec     ax
        jns     .t
        xor     ax, ax
.t:     mov     [lst+LV_SEL], ax
        mov     word [lst+LV_TOP], 0
.x:     ret

; F5, and after each change: the list again, drawn
redo:   call    refresh
        mov     bx, lst
        jmp     UI_LVDRAW

; the selected task -> BL = its number, SI = its record; CF if none
sel_task:
        mov     ax, [lst+LV_SEL]
        cmp     ax, [lst+LV_N]
        jae     .no
        shl     ax, 4
        add     ax, recs
        mov     si, ax
        mov     bl, [si+TR_ID]
        clc
        ret
.no:    stc
        ret

; Return: the task to the front (a parked one back first), and close
k_front:
        call    sel_task
        jc      .x
        cmp     byte [si+TR_STATE], TS_PARKED
        jne     .f
        mov     ax, 0F000h + MT_UNPARK
        stc
        int     21h
        jc      fail
.f:     mov     ax, 0F000h + MT_FRONT
        stc
        int     21h
        jc      fail
        inc     byte [quit]
.x:     ret

; CODE-Z: park it, or bring it back
k_park: call    sel_task
        jc      k_front.x
        mov     ax, 0F000h + MT_PARK
        cmp     byte [si+TR_STATE], TS_PARKED
        jne     .p
        mov     al, MT_UNPARK
.p:     stc
        int     21h
        jc      fail
        jmp     redo

; CODE-B: may it run behind?  auto, yes (SPF_BG), no (SPF_FREEZE), round
k_behind:
        call    sel_task
        jc      k_front.x
        mov     di, [lst+LV_SEL]
        mov     al, [flags+di]
        mov     cl, SPF_BG | SPF_FREEZE ; (both cleared, then the next set)
        mov     ch, 0                   ; no -> auto
        test    al, SPF_FREEZE
        jnz     .g
        mov     ch, SPF_FREEZE          ; yes -> no
        test    al, SPF_BG
        jnz     .g
        mov     ch, SPF_BG              ; auto -> yes
.g:     mov     ax, 0F000h + MT_FLAGS
        stc
        int     21h
        jc      fail
        jmp     redo

; CODE-D: end it, after a question
k_end:  call    sel_task
        jc      k_front.x
        push    si
        mov     di, qline               ; "End MTLINE.COM: Confirm to end the task"
        mov     si, s_endq
        call    UI_SBSTR
        pop     si
        call    put_name
        mov     si, s_endq2
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, qline
        call    UI_ASK                  ; (BX kept: BL the task)
        jc      .x
        mov     ax, 0F000h + MT_KILL
        stc
        int     21h
        jc      fail
        mov     [ending], bl            ; (as it was asked: till it has gone)
        mov     ax, 0F000h + MT_EXIT
        stc
        int     21h
        mov     [endgen], ah
        jmp     redo
.x:     ret

; a call failed (AX = its error): why, in the band till a key
fail:   mov     si, e_tnot
        cmp     ax, 5
        je      .m
        mov     si, e_tmem
        cmp     ax, 8
        je      .m
        mov     si, e_notask
.m:     call    UI_MSG
        jmp     redo

; the name of the record at SI (12 at most) at DI
put_name:
        push    si
        add     si, TR_NAME
        mov     cx, TR_NAMELEN
.c:     lodsb
        or      al, al
        jz      .x
        stosb
        loop    .c
.x:     pop     si
        ret

k_help: mov     si, keys
        mov     di, s_help
        jmp     UI_HELP

k_quit: inc     byte [quit]
        ret

; a row: AX = the item, DX = y, CL = the mask
row:    push    cx
        push    dx
        mov     si, ax
        shl     si, 4
        add     si, recs
        mov     bx, ax                  ; (BX = the item)
        mov     di, line
        mov     al, [si+TR_ID]          ; its number, two blanks
        add     al, '0'
        stosb
        mov     ax, '  '
        stosw
        push    di                      ; the program, in 13 columns
        call    put_name
        pop     ax
        add     ax, 13
.p:     cmp     di, ax
        jae     .st
        mov     byte [di], ' '
        inc     di
        jmp     .p
.st:    mov     al, [si+TR_ID]          ; what it does
        mov     ah, [si+TR_STATE]
        mov     si, s_ending
        cmp     al, [ending]
        je      .w
        mov     si, s_front
        cmp     al, [front]
        je      .w
        mov     si, s_parked
        cmp     ah, TS_PARKED
        je      .w
        mov     si, s_frozen
        cmp     ah, TS_FROZEN
        je      .w
        mov     si, s_waitk
        cmp     ah, TS_WAITK
        je      .w
        mov     si, s_waitf
        cmp     ah, TS_WAITF
        je      .w
        mov     si, s_run
.w:     push    di
        call    UI_SBSTR
        pop     ax
        add     ax, 23
.q:     cmp     di, ax
        jae     .bg
        mov     byte [di], ' '
        inc     di
        jmp     .q
.bg:    mov     al, [flags+bx]          ; may it run behind?
        mov     si, s_empty
        cmp     al, 0FFh                ; (the Executive: never asked)
        je      .b
        mov     si, s_no
        test    al, SPF_FREEZE
        jnz     .b
        mov     si, s_yes
        test    al, SPF_BG
        jnz     .b
        mov     si, s_auto
.b:     call    UI_SBSTR
        mov     byte [di], 0
        pop     dx
        pop     cx
        mov     ah, cl
        mov     si, line
        mov     bx, [lst+LV_COL]
        jmp     UI_PUTS

; type-to-find: AX = the item -> SI = its program's name
row_name:
        shl     ax, 4
        add     ax, recs + TR_NAME
        mov     si, ax
        ret

; the window's contents (BX = the window), from where it is now
w_draw: mov     ax, [win+W_COL]
        inc     ax
        mov     dx, [win+W_Y]
        cmp     byte [paints], 0        ; (as the calculator: drawn again at
        je      .n                      ;  the same place is a repaint)
        cmp     ax, [lst+LV_COL]
        jne     .geo
        mov     cx, dx
        add     cx, LROW
        cmp     cx, [lst+LV_Y]
        jne     .geo
.n:     stc
        rcl     byte [paints], 1
.geo:   mov     [lst+LV_COL], ax
        mov     bx, ax
        add     dx, W_TOP
        cmp     byte [off], 0
        je      .on
        mov     si, s_off               ; multitasking off: why, and how
        xor     ah, ah
        call    UI_PUTS
        add     dx, 20
        mov     si, s_off2
        call    UI_PUTS
        mov     [lst+LV_Y], dx
        ret
.on:    mov     si, s_head
        xor     ah, ah
        call    UI_PUTS
        add     dx, 20
        mov     [lst+LV_Y], dx
        mov     bx, lst
        call    UI_LVDRAW
        mov     dx, [win+W_Y]
        add     dx, HROW
        mov     bx, [lst+LV_COL]
        mov     si, s_k1
        xor     ah, ah
        call    UI_PUTS
        add     dx, 16
        mov     si, s_k2
        jmp     UI_PUTS

win     dw WCOL, WY, WW, WH, s_title, w_draw, WF_MOVE | WF_CLOSE
lst     dw 0, MT_TASKS, 0, 0, 0, row, 0, WCOL + 1, WW - 2, row_name
keys    KEY(K_NONE,   0,        h_choose)
        KEY(K_ENTER,  k_front,  h_front)
        KEY(K_CODE_Z, k_park,   h_park)
        KEY(K_CODE_B, k_behind, h_behind)
        KEY(K_CODE_D, k_end,    h_end)
        KEY(K_F5,     redo,     h_f5)
        KEY(K_F1,     k_help,   0)
        KEY(K_ESC,    k_quit,   h_quit)
        KEY(K_CODE_T, k_quit,   0)
        KEY(K_NONE,   0,        h_move)
        dw 0
h_choose db 'Up / Down, or click      choose a task',0
h_front db 'Return or click again    to the front, close',0
h_park  db 'CODE-Z                   park it in EMS / back',0
h_behind db 'CODE-B                   runs behind: auto, yes, no',0
h_end   db 'CODE-D                   end it',0
h_f5    db 'F5                       look again',0
h_quit  db 'ESC or CODE-T            close',0
h_move  db 'CODE-F7, arrows, Return  move (or drag its title)',0
s_title db 'Tasks',0
s_help  db 'Tasks Help',0
s_head  db '#  Program      Doing                  Behind',0
s_k1    db 'Return: to the front   CODE-Z: park, back',0
s_k2    db 'CODE-B: behind   CODE-D: end   F1: help',0
s_off   db 'Multitasking is off.',0
s_off2  db 'MULTITASK=1 in LODE.INI (System) turns it on.',0
s_front db 'in front',0
s_run   db 'running',0
s_waitk db 'waiting for a key',0
s_waitf db 'waiting to be in front',0
s_frozen db 'frozen behind',0
s_parked db 'parked',0
s_ending db 'being ended',0
s_auto  db 'auto',0
s_yes   db 'yes',0
s_no    db 'no',0
s_empty db 0
s_endq  db 'End ',0
s_endq2 db ': Confirm to end the task',0
e_tnot  db 'Not possible for that task',0
e_tmem  db 'Not enough memory or EMS',0
e_notask db 'No such task',0
ending  db 0FFh                         ; the task asked to end (FFh: none),
endgen  db 0                            ;  and its count then (MT_EXIT)

section .bss
quit    resb 1
paints  resb 1                          ; the window drawn: 1 once, more: not
off     resb 1                          ; multitasking off
front   resb 1                          ; the task in front
recs    resb MT_TASKS * MT_REC          ; MT_LIST's records
flags   resb MT_TASKS                   ; each one's MT_FLAGS (FFh: task 0)
line    resb 80
qline   resb 48                         ; (the question: drawing the rows, line,
                                        ;  while it waits would change it)
run_bss_end:
