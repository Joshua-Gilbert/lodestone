; =====================================================================
;  KMT.INC - multitasking, behind a switch: MULTITASK=1 in \LODE.INI
;  (with EMS; without it, it stays off).  Being built in steps (the plan:
;  docs/lodestone-multitasking.md).  So far: the switch (M1); tasks, each
;  a DOS program in a region of its own, switched when one waits for a
;  key (M2a); the front one chosen with CODE-Tab, each task's screen kept
;  in 2 EMS pages of its own (M2b).  Nothing preempts a task yet (M3).
;
;  Off, none of it is in memory: its start-up (mt_boot, section boot) is
;  only in the load image, its resident part (section mtt) isn't even in
;  LODE.SYS, and INT 21h F0h with AL = 10h and up fails as before (f_F0's
;  f_bad).  The resident part is the file's last section, which the build
;  (mkmt.py) cuts off into LODEMT.SYS, writing its checksum into mt_sum.
;  On, mt_boot (from md_boot, after M:) reads \LODEMT.SYS from the drive
;  started from (R: from the ROM) into a block of its own (owner 8, "MT")
;  at the top of memory: a filler block takes the rest first, then goes,
;  so DOS programs still get one block below it, and the UI block keeps its
;  room for a .RUN right after it.  A LODEMT.SYS that isn't this LODE.SYS's
;  (shorter, or its first MT_LEN bytes' checksum differs), none, or no
;  room: it stays off.  The part runs in its own segment, assembled from
;  0; it reaches the kernel with far jumps (and its near routines with
;  KCALL), so it doesn't have to be within KSEG's 64 KB.  Its hooks:
;    - INT 08h goes through mt_tick (the BIOS's handler first);
;    - INT 21h F0h through mt_f0: f_F0's first 5 bytes (MOV AL,[BP+F_AX]
;      and OR AL,AL) become a far jump to it, and it comes back past
;      them.  (KEMS.INC patches f_F0.lend and .back, further in.)
;    - kbd_get.k (MOV AH,1 / INT 16h / JNZ .have: 6 bytes) becomes a far
;      jump to mt_kwait, where a task waits for a key: only the front one
;      reads them; one that waits with nothing typed lets another run.
;
;  A task (1 to 7; task 0 is the Executive and whatever it runs) is a
;  region, a block of its own (owner 8, "T1".."T7") carved from the top of
;  the free memory below MT's block, downward:
;    TX     its context while another runs: its SS:SP, the EMS windows'
;           page registers, the kernel's per-task variables (mt_ranges: the INT 21h nesting, the break
;           and console state, the current directories, the DTA and
;           console line, the current PSP, the memory arena's start), and
;           the kernel stack's slice from SP up (it waits inside INT 21h)
;    stub   a PSP and a few instructions: EXEC the program, then MT_END
;           (its own parent: ended itself, it lands on MT_END too)
;    env    a copy of the spawner's environment (it may end first)
;    arena  the task's own MCB chain: its first_mcb, ended by a 'Z' here
;  Task 0's TX is in MT's block (section mttbss).  Switching happens only
;  inside INT 21h (indos 1), at mt_kwait, or when a task ends.
;  The calls: MTAPI.INC.
; =====================================================================
%ifndef NOTC
%include "MTAPI.INC"

; ---- a task's entry in mt_tab (the API's record is MT_REC: mt_f0.list)
TE_STATE    equ 0                       ; TS_*
TE_PSP      equ 2                       ; its stub's PSP (task 0: the root's)
TE_REG      equ 4                       ; its region (task 0: 0)
TE_TX       equ 6                       ; its TX's segment
TE_EXIT     equ 8                       ; its program's exit code (last_exit)
TE_NAME     equ 10                      ; TR_NAMELEN bytes
TE_SH       equ 22                      ; its screen's EMS handle (2 pages; 0:
                                        ;  none)
TE_SF       equ 23                      ; 1: its screen is kept there
MT_ENT      equ 32

; ---- a TX (context) ----------------------------------------------------
TX_SP       equ 0
TX_SS       equ 2
TX_KLEN     equ 4                       ; bytes of kernel stack saved (0: none)
TX_EMS      equ 6                       ; the EMS windows' 4 page registers
TX_VID      equ 10                      ; its screen's BIOS data (40:49h-66h)
VIDLEN      equ 30
V_INDOS     equ TX_VID + VIDLEN         ; the kernel's variables, mt_ranges'
V_BRK       equ V_INDOS + 1             ;  order (V_x + (var - first) for one
V_MCB       equ V_BRK + (onebyte + 1 - brkflag)   ;  inside a range)
V_DCWD      equ V_MCB + 2
V_CWD       equ V_DCWD + 2 * NDRV
V_DTA       equ V_CWD + (cur_drv + 1 - cwdstr)
V_PSP       equ V_DTA + (rw_t0 + 1 - dta)
TX_KSTK     equ V_PSP + (term_keep + 2 - cur_psp)
KSLICE      equ 256                     ; room for the kernel stack's slice
TX_PARAS    equ (TX_KSTK + KSLICE + 15) / 16

; ---- the stub (a PSP, then this at 100h) --------------------------------
ST_PATH     equ 120h                    ; the program (ASCIIZ)
ST_PB       equ 1A0h                    ; EXEC's block
ST_TAIL     equ 1B0h                    ; its command tail
ST_STK      equ 340h                    ; its stack's top
ST_AFR      equ ST_STK - 26             ; its EXEC call's frame (INT 21h's, on
                                        ;  its stack): terminate's, if it is
                                        ;  ended itself (an Abort while it EXECs)
ST_PARAS    equ ST_STK / 16
ENVMAX      equ 1024                    ; most of an environment kept

%macro KCALL 1                          ; CALL a near routine of the kernel
        push    cs
        push    word %%r
        push    word k_retf             ;  (its RET goes to a RETF there)
        jmp     KSEG:%1
%%r:
%endmacro

; ---- the resident part (in its own segment, from 0) -----------------
section mtt
mt_tstart:
mt_old08    dd      0                   ; INT 08h as it was
mt_ticks    dw      0                   ; ticks seen (mt_tick runs)
mt_front    db      0                   ; the task in front
mt_cur      db      0                   ; the task running
mt_swreq    db      0FFh                ; a task to bring to the front (FFh: none)
mt_hotk     dw      0A500h, 0A5F0h      ; the hot key, CODE-Tab, as AH=10h
                                        ;  gives it on the 1520 (KEYCODE.COM),
                                        ;  and as a BIOS keeping CODE keys with
                                        ;  F0h would
mt_wsv      db      0, 0                ; (mt_wsave: windows 0 and 1)
mt_mcb0     dw      0                   ; the whole arena's first MCB
mt_new      dw      0                   ; (MT_SPAWN: its entry, and the sizes)
mt_envs     dw      0
mt_envl     dw      0
mt_envp     dw      0
mt_reg      dw      0
mt_size     dw      0
mt_arena    dw      0
mt_sflags   db      0
            align   2
; the kernel's per-task variables: (offset, bytes), as V_* lays them out
mt_ranges:  dw      indos, 1
            dw      brkflag, onebyte + 1 - brkflag
            dw      first_mcb, 2
%assign d 0
%rep NDRV
            dw      drvtab + d * DRVSZ + D_CWD, 2
%assign d d+1
%endrep
            dw      cwdstr, cur_drv + 1 - cwdstr
            dw      dta, rw_t0 + 1 - dta
            dw      cur_psp, term_keep + 2 - cur_psp
            dw      0

mt_tab:     dw      TS_RUN, 0, 0, 0, 0  ; task 0: the Executive (PSP, TX: mt_boot)
            db      'Executive', 0, 0, 0
            times   MT_ENT - (TE_NAME + TR_NAMELEN) db 0
            times   (MT_TASKS - 1) * MT_ENT db 0

; the stub, copied to its PSP:0100h (DS = ES = SS = the PSP)
st_code:
        mov     ax, 4B00h
        mov     dx, ST_PATH
        mov     bx, ST_PB
        int     21h
.e:     mov     ax, 0F000h + MT_END     ; (PSP:0Ah: where it ends, its own
        int     21h                     ;  parent, if it is aborted itself)
.h:     hlt                             ; (never: MT_END doesn't come back)
        jmp     .h
st_len      equ     $ - st_code
ST_END      equ     100h + st_code.e - st_code

; INT 08h: the BIOS's handler first (the tick count, INT 1Ch, the end of
; the interrupt), then ours
mt_tick:
        pushf
        call    far [cs:mt_old08]
        inc     word [cs:mt_ticks]
        iret

; a new task's first return (mt_load): to its stub, flags with IF
mt_first:
        iret

; ---------------------------------------------------------------------
;  kbd_get.k: a task waits for a key (inside INT 21h; DS anything)
; ---------------------------------------------------------------------
mt_kwait:
        push    ds
        push    ax
        push    bx
        push    KSEG
        pop     ds
.top:   call    mt_hot                  ; CODE-Tab typed?  (Before the look for
        mov     al, [cs:mt_swreq]       ;  a key: INT 16h AH=01h drops it.)
        cmp     al, 0FFh                ; a task to bring to the front?  (Only
        je      .f                      ;  where it could run: else later.)
        call    mt_can
        jc      .f
        mov     byte [cs:mt_swreq], 0FFh
        call    mt_ent                  ; (BX = its entry)
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        je      .f
        call    mt_scrto                ; its screen, and it is in front
.f:     mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        jne     .bg
.k:     mov     ah, 1                   ; in front: a key?
        int     16h
        jnz     .have
        call    mt_can                  ; none: another task to run meanwhile?
        jc      .idle
        call    mt_pick
        jc      .idle
        call    .park                   ; (it runs; then back here)
        jmp     .top
.idle:  pop     bx                      ; the kernel's own wait: PrtSc,
        pop     ax                      ;  INT 28h, HLT, and here again
        pop     ds
        jmp     KSEG:kbd_get.k + 6
.have:  pop     bx
        pop     ax
        pop     ds
        jmp     KSEG:kbd_get.have
; in the background: it waits without reading keys, while another runs
; (unless it can't be switched from: then it reads them, as in front; an
; INT 24h answer, say)
.bg:    call    mt_can
        jc      .k
        call    mt_pick                 ; one ready to run, or the front one
        jnc     .bgs
        mov     bl, [cs:mt_front]
        mov     al, bl
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITK
        jne     .idle
        mov     bl, al
.bgs:   call    .park
        jmp     .top
; this task waits (TS_WAITK) while task BL runs
.park:  push    bx
        mov     al, [cs:mt_cur]
        call    mt_ent
        mov     byte [cs:bx+TE_STATE], TS_WAITK
        pop     bx
        jmp     mt_switch

; CF if the running task can't be switched away from here: a nested INT
; 21h (an INT 24h answer), or more kernel stack than its TX holds
mt_can: cmp     byte [indos], 1
        jne     .no
        push    ax
        mov     ax, kstack_top          ; (and room for mt_switch's own
        sub     ax, sp                  ;  pushes)
        cmp     ax, KSLICE - 48
        pop     ax
        jae     .no
        clc
        ret
.no:    stc
        ret

; a task other than the running one that is ready to run (TS_RUN), the
; next after it in turn -> BL; CF if none
mt_pick:
        push    ax
        push    cx
        mov     al, [cs:mt_cur]
        mov     cx, MT_TASKS - 1
.l:     inc     al
        and     al, MT_TASKS - 1
        push    bx
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_RUN
        pop     bx
        je      .y
        loop    .l
        stc
        jmp     short .x
.y:     mov     bl, al
        clc
.x:     pop     cx
        pop     ax
        ret

; AL = a task -> BX = its entry in mt_tab
mt_ent: push    ax
        xor     ah, ah
        mov     bx, ax                  ; (AL * MT_ENT, 32: DX kept)
        shl     bx, 5
        add     bx, mt_tab
        pop     ax
        ret

; ---------------------------------------------------------------------
;  switching: mt_switch saves the running task and runs task BL;
;  mt_load runs task BL without saving (the running one has ended).
;  The saved task comes back from mt_switch, all its registers kept.
; ---------------------------------------------------------------------
mt_switch:
        pusha
        push    ds
        push    es
        cli
        mov     al, [cs:mt_cur]
        push    bx
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        pop     bx
        mov     [es:TX_SP], sp
        mov     [es:TX_SS], ss
        call    mt_emsget
        mov     cx, kstack_top          ; its slice of the kernel stack
        sub     cx, sp
        mov     [es:TX_KLEN], cx
        push    KSEG
        pop     ds
        mov     si, sp
        mov     di, TX_KSTK
        rep     movsb
        push    bx
        call    mt_vsave                ; the kernel's variables
        pop     bx
mt_load:
        cli
        mov     [cs:mt_cur], bl
        mov     al, bl
        call    mt_ent
        mov     byte [cs:bx+TE_STATE], TS_RUN
        mov     es, [cs:bx+TE_TX]
        push    KSEG
        pop     ds
        call    mt_vload
        mov     dx, EMS_PORT            ; its EMS windows
        mov     bx, TX_EMS
.em:    mov     al, [es:bx]
        out     dx, al
        inc     bx
        add     dh, 40h
        jnc     .em
        mov     ss, [es:TX_SS]
        mov     sp, [es:TX_SP]
        mov     cx, [es:TX_KLEN]
        jcxz    .go
        push    es                      ; its slice back where it was
        pop     ds
        mov     si, TX_KSTK
        push    ss
        pop     es
        mov     di, sp
        rep     movsb
.go:    pop     es
        pop     ds
        popa
        sti
        ret

; the EMS windows' page registers to the TX at ES (AL, DX, DI changed)
mt_emsget:
        mov     dx, EMS_PORT
        mov     di, TX_EMS
.l:     in      al, dx
        stosb
        add     dh, 40h
        jnc     .l
        ret

; the kernel's variables (DS = KSEG) to the TX at ES, or back
mt_vsave:
        mov     bx, mt_ranges
        mov     di, V_INDOS
.r:     mov     si, [cs:bx]
        or      si, si
        jz      .x
        mov     cx, [cs:bx+2]
        rep     movsb
        add     bx, 4
        jmp     .r
.x:     ret
mt_vload:
        push    ds
        push    es
        pop     ds                      ; (from the TX: DS)
        pop     es                      ; (to KSEG: ES)
        mov     bx, mt_ranges
        mov     si, V_INDOS
.r:     mov     di, [cs:bx]
        or      di, di
        jz      .x
        mov     cx, [cs:bx+2]
        rep     movsb
        add     bx, 4
        jmp     .r
.x:     push    es                      ; (ES = the TX, DS = KSEG again)
        push    ds
        pop     es
        pop     ds
        ret

; ---------------------------------------------------------------------
;  INT 21h AH=F0h, from f_F0's first bytes: DS = SS = KSEG, BP = the frame
; ---------------------------------------------------------------------
mt_f0:  mov     al, [bp+F_AX]
        cmp     al, MT_LIST
        je      mt_list
        cmp     al, MT_SPAWN
        je      mt_spawn
        cmp     al, MT_END
        je      mt_end
        cmp     al, MT_FRONT
        je      mt_frontc
        or      al, al                  ; (f_F0's own two, then on there)
        jmp     KSEG:f_F0 + 5
mt_bad: mov     ax, 1
mt_fail:
        jmp     KSEG:fail

; MT_LIST: the records of the tasks there are, as many as fit in CX
mt_list:
        push    cs
        pop     ds
        mov     es, [bp+F_ES]
        mov     di, [bp+F_DI]
        mov     dx, [bp+F_CX]           ; (room)
        xor     cx, cx
        xor     al, al
.l:     call    mt_ent
        mov     ah, [cs:bx+TE_STATE]
        or      ah, ah                  ; (TS_FREE)
        jz      .n
        inc     cx
        cmp     cx, dx
        ja      .n                      ; (no room: only counted)
        stosw                           ; TR_ID, TR_STATE
        mov     si, [cs:bx+TE_PSP]
        xchg    ax, si
        stosw                           ; TR_PSP
        xchg    ax, si
        push    cx
        lea     si, [bx+TE_NAME]
        mov     cx, TR_NAMELEN / 2
        rep     movsw                   ; TR_NAME (DS = CS here)
        pop     cx
.n:     inc     al
        cmp     al, MT_TASKS
        jb      .l
        mov     al, [cs:mt_front]
        mov     [bp+F_CX], cx
        mov     [bp+F_AX], al
        jmp     KSEG:ok

; MT_FRONT: task BL to the front, at the next key wait
mt_frontc:
        mov     al, [bp+F_BX]
        cmp     al, MT_TASKS
        jae     mt_bad
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        je      mt_bad
        mov     [cs:mt_swreq], al
        jmp     KSEG:ok

; MT_END: from a task's stub, its program done.  Its handles (the
; inherited ones) closed, its region freed, and another task runs.
mt_end: mov     al, [cs:mt_cur]
        or      al, al
        jz      mt_bad                  ; (not the Executive)
        call    mt_ent
        mov     ax, [cs:bx+TE_PSP]
        cmp     ax, [cur_psp]
        jne     mt_bad                  ; (only its stub)
        mov     es, ax
        KCALL   close_all
        mov     ax, [last_exit]
        mov     [cs:bx+TE_EXIT], ax
        mov     dl, [cs:bx+TE_SH]       ; its screen's pages
        xor     dh, dh
        or      dl, dl
        jz      .np
        mov     ah, 45h
        int     67h
        mov     byte [cs:bx+TE_SH], 0
.np:    mov     ax, [last_exit]
        mov     cx, [cs:bx+TE_REG]
        dec     cx
        mov     es, cx
        cmp     ah, 3                   ; the region: free (a program that
        jne     .fr                     ;  stays resident keeps it, "TR")
        mov     word [es:8], 'TR'
        jmp     short .t
.fr:    mov     word [es:1], 0
.t:     mov     byte [cs:bx+TE_STATE], TS_FREE
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        jne     .f
        push    ax                      ; it was in front: the Executive's
        mov     ax, 2                   ;  task is, with its screen (the
        call    mt_m33                  ;  INT 33h pointer off meanwhile)
        xor     al, al
        call    mt_scrld
        mov     ax, 1
        call    mt_m33
        pop     ax
.f:     cmp     al, [cs:mt_swreq]
        jne     .s
        mov     byte [cs:mt_swreq], 0FFh
.s:     call    mt_pick                 ; another ready one, or the front one
        jnc     .go                     ;  (in M2a it waits for a key: it
        mov     bl, [cs:mt_front]       ;  was there when this one ran)
.go:    jmp     mt_load

; MT_SPAWN: DS:DX = the program, ES:BX = the block -> AL = the new task
mt_spawn:
        mov     al, 1                   ; a free entry
.e:     call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        je      .got
        inc     al
        cmp     al, MT_TASKS
        jb      .e
        mov     ax, 4
        jmp     mt_fail
.got:   mov     [cs:mt_new], bx
        mov     [bp+F_AX], al           ; (the answer)
        mov     es, [bp+F_ES]
        mov     di, [bp+F_BX]
        mov     ax, [es:di+SP_PARAS]
        or      ax, ax
        jnz     .a
        mov     ax, MT_DEFARENA
.a:     mov     [cs:mt_arena], ax
        mov     al, [es:di+SP_FLAGS]
        mov     [cs:mt_sflags], al
        mov     ax, [es:di+SP_ENV]      ; the environment: the block's, or
        or      ax, ax                  ;  the caller's
        jnz     .ev
        mov     es, [cur_psp]
        mov     ax, [es:2Ch]
.ev:    mov     [cs:mt_envs], ax
        mov     es, ax                  ; its length: to its two NULs (or
        xor     di, di                  ;  ENVMAX, cut there; none: empty)
        or      ax, ax
        jz      .ee
.el:    cmp     word [es:di], 0
        je      .ee
        inc     di
        cmp     di, ENVMAX - 2
        jb      .el
.ee:    inc     di
        inc     di
        mov     [cs:mt_envl], di
        add     di, 15
        shr     di, 4
        mov     [cs:mt_envp], di
        mov     ax, TX_PARAS + ST_PARAS + 1     ; the region: TX, stub, env,
        add     ax, di                  ;  the arena's MCB, the arena
        add     ax, [cs:mt_arena]
        jc      .room
        mov     [cs:mt_size], ax
        call    mt_carve
        jnc     .r
.room:  mov     ax, 8
        jmp     mt_fail
.r:     mov     [cs:mt_reg], ax
        push    ax                      ; its screen's 2 EMS pages (none: the
        mov     ah, 43h                 ;  region goes again)
        mov     bx, 2
        int     67h
        pop     cx
        or      ah, ah
        jz      .sh
        dec     cx
        mov     es, cx
        mov     word [es:1], 0
        jmp     .room
.sh:    xor     al, al                  ; an entry with this number (its own
.dh:    call    mt_ent                  ;  freed by a program, given out
        cmp     [cs:bx+TE_SH], dl       ;  again): it keeps none
        jne     .dn
        mov     word [cs:bx+TE_SH], 0
.dn:    inc     al
        cmp     al, MT_TASKS
        jb      .dh
        mov     bx, [cs:mt_new]
        mov     [cs:bx+TE_SH], dl
        mov     byte [cs:bx+TE_SF], 0
        mov     ax, [cs:mt_reg]
        mov     [cs:bx+TE_REG], ax
        mov     [cs:bx+TE_TX], ax
        dec     ax                      ; its MCB: the system's, "T1".."T7"
        mov     es, ax
        mov     word [es:1], 8
        mov     al, [bp+F_AX]
        add     al, '0'
        mov     ah, al
        mov     al, 'T'
        mov     [es:8], ax
        ; the stub's PSP (make_psp: the caller's handles, inherited)
        mov     ax, [cs:mt_reg]
        add     ax, TX_PARAS
        mov     es, ax
        mov     [cs:bx+TE_PSP], ax
        add     ax, ST_PARAS            ; (the environment's copy)
        mov     dx, [cs:mt_reg]
        add     dx, [cs:mt_size]        ; (the region's end)
        mov     bx, [cur_psp]
        KCALL   make_psp                ; (its environment: the copy)
        mov     ax, es                  ; its own parent: if it is ended
        mov     [es:16h], ax            ;  itself, it goes to MT_END
        mov     word [es:0Ah], ST_END
        mov     [es:0Ch], ax
        mov     word [es:2Eh], ST_AFR   ;  (as EXEC's .close would set it)
        mov     [es:30h], ax
        ; the stub's code, the program's path, its name for MT_LIST
        push    ds
        push    cs
        pop     ds
        mov     si, st_code
        mov     di, 100h
        mov     cx, st_len
        rep     movsb
        pop     ds
        push    ds
        mov     ds, [bp+F_DS]
        mov     si, [bp+F_DX]
        mov     di, ST_PATH
        mov     cx, 127
.p:     lodsb
        stosb
        or      al, al
        loopnz  .p
        mov     byte [es:di-1], 0       ; (cut at 127)
        pop     ds
        call    mt_name
        ; the command tail (count, text, CR), or none
        push    ds
        mov     ds, [bp+F_ES]
        mov     si, [bp+F_BX]
        lds     si, [si+SP_TAIL]
        mov     di, ST_TAIL
        mov     ax, ds
        or      ax, si
        jz      .nt
        mov     cl, [si]
        cmp     cl, 126
        jbe     .tl
        mov     cl, 126
.tl:    xor     ch, ch
        mov     [es:di], cl
        inc     di
        inc     si
        rep     movsb
        mov     al, 0Dh
        stosb
        jmp     short .te
.nt:    mov     ax, 0D00h
        stosw
.te:    pop     ds
        mov     di, ST_PB               ; EXEC's block: the stub's own env,
        xor     ax, ax                  ;  the tail, its two (blank) FCBs
        stosw
        mov     ax, ST_TAIL
        stosw
        mov     ax, es
        stosw
        mov     ax, 5Ch
        stosw
        mov     ax, es
        stosw
        mov     ax, 6Ch
        stosw
        mov     ax, es
        stosw
        ; the environment's copy
        push    ds
        mov     ax, es
        add     ax, ST_PARAS
        mov     es, ax
        mov     ds, [cs:mt_envs]
        xor     si, si
        xor     di, di
        mov     cx, [cs:mt_envl]
        rep     movsb
        mov     word [es:di-2], 0       ; (two NULs, even if cut)
        pop     ds
        ; the arena: one free block to the region's end
        mov     ax, es
        add     ax, [cs:mt_envp]
        mov     es, ax
        mov     byte [es:0], 'Z'
        mov     word [es:1], 0
        mov     cx, [cs:mt_arena]
        mov     [es:3], cx
        push    ax                      ; (its MCB: the task's first_mcb)
        ; its TX: the caller's variables (its directories, ...), then its own
        mov     es, [cs:mt_reg]
        call    mt_vsave
        call    mt_emsget
        pop     ax
        mov     [es:V_MCB], ax
        mov     byte [es:V_INDOS], 0
        mov     byte [es:V_BRK + kbd_scan - brkflag], 0
        mov     byte [es:V_BRK + term_type - brkflag], 0
        mov     word [es:V_BRK + cc_sp - brkflag], 0
        mov     word [es:V_DTA + con_lpos - dta], 0     ; (no line half read)
        mov     word [es:V_DTA + con_llen - dta], 0
        mov     bx, [cs:mt_new]
        mov     ax, [cs:bx+TE_PSP]
        mov     [es:V_PSP + cur_psp - cur_psp], ax
        mov     word [es:V_PSP + last_exit - cur_psp], 0
        mov     word [es:V_DTA + 0], 80h
        mov     [es:V_DTA + 2], ax
        mov     word [es:TX_KLEN], 0
        ; its first run: on the stub's stack, as mt_load pops it: ES, DS,
        ; POPA's eight, mt_first, then IRET's IP, CS, flags
        mov     [es:TX_SS], ax
        mov     word [es:TX_SP], ST_STK - 28
        push    es
        mov     es, ax
        mov     di, ST_STK - 28
        stosw                           ; ES
        stosw                           ; DS
        push    ax
        xor     ax, ax
        mov     cx, 8
        rep     stosw                   ; DI .. AX
        mov     ax, mt_first
        stosw
        mov     ax, 100h
        stosw                           ; IP
        pop     ax
        stosw                           ; CS
        mov     ax, 0202h
        stosw                           ; flags: IF
        pop     es
        mov     bx, [cs:mt_new]
        mov     byte [cs:bx+TE_STATE], TS_RUN
        mov     word [cs:bx+TE_EXIT], 0
        test    byte [cs:mt_sflags], SPF_FRONT
        jz      .x
        mov     al, [bp+F_AX]
        mov     [cs:mt_swreq], al
.x:     jmp     KSEG:ok

; the program's name (its path's last part) into its entry (BX = mt_new),
; upper case, NUL-padded.  ES:ST_PATH = the path.
mt_name:
        push    ds
        push    es
        pop     ds
        mov     si, ST_PATH
        mov     dx, si
.s:     lodsb                           ; (after the last \ or :)
        or      al, al
        jz      .c
        cmp     al, '\'
        je      .m
        cmp     al, ':'
        jne     .s
.m:     mov     dx, si
        jmp     .s
.c:     mov     si, dx
        mov     bx, [cs:mt_new]
        lea     di, [bx+TE_NAME]
        mov     cx, TR_NAMELEN
.n:     lodsb
        or      al, al
        jz      .z
        cmp     al, 'a'
        jb      .u
        cmp     al, 'z'
        ja      .u
        sub     al, 20h
.u:     mov     [cs:di], al
        inc     di
        loop    .n
        jmp     short .x
.z:     mov     byte [cs:di], 0
        inc     di
        loop    .z
.x:     pop     ds
        ret

; CODE-Tab in the BIOS's key buffer: taken out, and the next task (after the
; one asked for, or the front one) asked for.  Only when no key but those
; AH=01h drops (the 1520's BIOS: scan codes 85h and up but E0h's, and
; CODE keys, xxF0h with a scan code) is ahead of it: the others are the
; front task's, typed before it.  (At most 16 words looked at: a buffer gone bad
; isn't followed round.)  DS anything; AX, BX changed
mt_hot: push    ds
        push    si
        push    cx
        push    40h
        pop     ds
        cli
        mov     bx, [1Ah]               ; (head to tail, wrapping at 40:82h)
        mov     cx, 16
.s:     cmp     bx, [1Ch]
        je      .no
        mov     ax, [bx]
        cmp     ax, [cs:mt_hotk]
        je      .m
        cmp     ax, [cs:mt_hotk + 2]
        je      .m
        cmp     ah, 0E0h                ; (a key ahead of it: later)
        je      .no
        cmp     ah, 85h
        jae     .sk
        cmp     al, 0F0h
        jne     .no
        or      ah, ah
        jz      .no
.sk:    call    .nx
        loop    .s
        jmp     short .no
.m:     mov     si, bx                  ; the words after it, one back
        call    .nx
        cmp     bx, [1Ch]
        je      .e
        mov     ax, [bx]
        mov     [si], ax
        jmp     .m
.e:     mov     [1Ch], si
        sti
        mov     al, [cs:mt_swreq]       ; the next task after that one
        cmp     al, 0FFh
        jne     .t
        mov     al, [cs:mt_front]
.t:     mov     cx, MT_TASKS - 1
.l:     inc     al
        and     al, MT_TASKS - 1
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        jne     .y
        loop    .l
        jmp     short .no               ; (the only one)
.y:     cmp     al, [cs:mt_front]
        jne     .q
        mov     al, 0FFh                ; (round to the front one: as it is)
.q:     mov     [cs:mt_swreq], al
.no:    sti
        pop     cx
        pop     si
        pop     ds
        ret
.nx:    inc     bx
        inc     bx
        cmp     bx, [82h]
        jb      .nr
        mov     bx, [80h]
.nr:    ret

; task AL to the front: the front one's screen kept, AL's shown; a DOS
; program's INT 33h pointer off meanwhile (as RCON does)
mt_scrto:
        cmp     al, [cs:mt_front]
        je      .x
        push    ax
        mov     ax, 2
        call    mt_m33
        mov     al, [cs:mt_front]
        call    mt_scrsv
        pop     ax
        call    mt_scrld
        mov     ax, 1
        jmp     mt_m33
.x:     ret

; INT 33h function AX, if there is an INT 33h.  All kept
mt_m33: pusha
        push    ds
        push    es
        xor     bx, bx
        mov     ds, bx
        mov     bx, [33h * 4]
        or      bx, [33h * 4 + 2]
        jz      .x
        int     33h
.x:     pop     es
        pop     ds
        popa
        ret

; the screen (B800:0000, 32 KB: any mode) and its BIOS data to task AL's
; pages and TX (with none, nothing; with its pages gone, say a program
; freed the handle, none from now on).  All kept but the flags
mt_scrsv:
        pusha
        push    ds
        push    es
        call    mt_ent
        cmp     byte [cs:bx+TE_SH], 0
        je      .x
        call    mt_wsave
        call    mt_wmap
        jc      .gone
        mov     byte [cs:bx+TE_SF], 1
        mov     es, [cs:bx+TE_TX]       ; its BIOS data
        push    40h
        pop     ds
        mov     si, 49h
        mov     di, TX_VID
        mov     cx, VIDLEN
        rep     movsb
        push    0B800h
        pop     ds
        push    EMS_FRAME
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 4000h
        rep     movsw
        call    mt_wrest
.x:     pop     es
        pop     ds
        popa
        ret
.gone:  call    mt_wgone
        jmp     .x

; its pages gone: windows 0 and 1 back, and none kept for the entry at BX
; (nor freed at its end: the number may be someone else's now)
mt_wgone:
        call    mt_wrest
        mov     word [cs:bx+TE_SH], 0   ; (TE_SH, TE_SF)
        ret

; task AL's screen shown, and AL in front: its mode, 3D9h (CGA's modes,
; before the screen, as RCON does), the screen, its BIOS data; in text
; modes, the page shown and the cursor.  Never shown yet (or none kept):
; mode 3, clear.  All kept but the flags
mt_scrld:
        pusha
        push    ds
        push    es
        mov     [cs:mt_front], al
        call    mt_ent
        cmp     byte [cs:bx+TE_SF], 0
        je      .clr
        call    mt_wsave
        call    mt_wmap
        jnc     .k
        call    mt_wgone
.clr:   mov     ax, 0003h
        int     10h
        jmp     .x
.k:     mov     ds, [cs:bx+TE_TX]
        mov     al, [TX_VID]            ; (40:49h)
        xor     ah, ah
        push    ax
        push    bx
        int     10h
        pop     bx
        pop     ax
        cmp     al, 6
        ja      .s
        mov     al, [TX_VID + 66h - 49h]
        mov     dx, 3D9h
        out     dx, al
.s:     push    EMS_FRAME
        pop     ds
        push    0B800h
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 4000h
        rep     movsw
        mov     ds, [cs:bx+TE_TX]
        push    40h
        pop     es
        mov     si, TX_VID
        mov     di, 49h
        mov     cx, VIDLEN
        rep     movsb
        call    mt_wrest
        push    es
        pop     ds
        cmp     byte [49h], 3
        ja      .x
        mov     al, [62h]               ; the page shown
        mov     ah, 5
        int     10h
        mov     cx, [60h]               ; the cursor: its shape, and where it
        mov     ah, 1                   ;  is on that page
        int     10h
        mov     bh, [62h]
        mov     bl, bh
        xor     bh, bh
        shl     bx, 1
        mov     dx, [50h + bx]
        mov     bh, [62h]
        mov     ah, 2
        int     10h
.x:     pop     es
        pop     ds
        popa
        ret

; windows 0 and 1: their page registers kept (mt_wrest puts them back);
; mt_wmap maps the 2 pages of the entry at BX into them (INT 67h AH=44h),
; CF if it can't (its handle gone).  AL, DX changed
mt_wsave:
        mov     dx, EMS_PORT
        in      al, dx
        mov     [cs:mt_wsv], al
        add     dh, 40h
        in      al, dx
        mov     [cs:mt_wsv + 1], al
        ret
mt_wrest:
        mov     dx, EMS_PORT
        mov     al, [cs:mt_wsv]
        out     dx, al
        add     dh, 40h
        mov     al, [cs:mt_wsv + 1]
        out     dx, al
        ret
mt_wmap:
        push    bx
        push    cx
        push    ds
        mov     dl, [cs:bx+TE_SH]       ; still MT's?  (Open, 2 pages, owner 0:
        xor     dh, dh                  ;  a program's has its PSP)
        push    KSEG
        pop     ds
        mov     bx, dx
        shl     bx, 2
        cmp     byte [ems_h + bx], 0FFh
        je      .e
        cmp     byte [ems_h + bx + 1], 2
        jne     .e
        cmp     word [ems_h + bx + 2], 0
        jne     .e
        push    dx
        mov     ax, 4400h
        xor     bx, bx
        int     67h
        pop     dx
        or      ah, ah
        jnz     .e
        mov     ax, 4401h
        mov     bx, 1
        int     67h
        or      ah, ah
        jz      .x
.e:     stc
.x:     pop     ds
        pop     cx
        pop     bx
        ret

; a region of [mt_size] paragraphs at the top of the highest free block
; that has room (the arena walked from mt_mcb0, free neighbours merged)
; -> AX = its segment; CF if none
mt_carve:
        push    es
        push    ds
        xor     bx, bx                  ; (the best so far: its MCB)
        mov     dx, [cs:mt_size]
        mov     ax, [cs:mt_mcb0]
.w:     mov     es, ax
        mov     cl, [es:0]              ; (a chain gone bad: none)
        cmp     cl, 'M'
        je      .w1
        cmp     cl, 'Z'
        jne     .no
.w1:    cmp     word [es:1], 0
        jne     .nx
.mg:    cmp     byte [es:0], 'M'        ; free: merge the free ones after it
        jne     .fit
        mov     cx, ax
        add     cx, [es:3]
        inc     cx
        mov     ds, cx
        cmp     word [ds:1], 0
        jne     .fit
        mov     cl, [ds:0]
        mov     [es:0], cl
        mov     cx, [ds:3]
        inc     cx
        add     [es:3], cx
        jmp     .mg
.fit:   cmp     [es:3], dx
        jb      .nx
        mov     bx, ax                  ; (the highest one that fits)
.nx:    cmp     byte [es:0], 'Z'
        je      .end
        add     ax, [es:3]
        inc     ax
        jmp     .w
.end:   or      bx, bx
        jz      .no
        mov     es, bx
        mov     cx, [es:3]
        sub     cx, dx
        cmp     cx, 1
        jbe     .all                    ; (exactly, or no room for an MCB: all)
        dec     cx                      ; the rest stays free, below
        mov     [es:3], cx
        mov     al, [es:0]
        mov     byte [es:0], 'M'
        mov     cx, bx
        add     cx, [es:3]
        inc     cx
        mov     es, cx
        mov     [es:0], al
        mov     [es:3], dx
.all:   mov     word [es:1], 8          ; (mt_spawn names it)
        mov     ax, es
        inc     ax
        clc
        jmp     short .x
.no:    stc
.x:     pop     ds
        pop     es
        ret
mt_tend:
MT_LEN      equ     mt_tend - mt_tstart

MT_TX0P     equ     (MT_LEN + 15) / 16  ; task 0's TX: in the BSS, which starts
MT_PARAS    equ     MT_TX0P + TX_PARAS  ;  on the paragraph after the image

section mttbss
mt_tx0      resb    TX_PARAS * 16       ; (at MT_TX0P * 16)
mt_bend:

; ---- start-up (section boot, in the load image: CS = 1000h) ----------
section boot
mt_on   db      0                       ; md_boot: MULTITASK=1 is in LODE.INI
mt_sum  dw      0                       ; LODEMT.SYS's checksum (mkmt.py)
s_mteq  db      'MULTITASK', 1Dh, 0     ; (as "MULTITASK=" AND 0DFh)
s_mtsys db      '@:\LODEMT.SYS', 0

; \LODEMT.SYS into a block at the top of memory, INT 08h, INT 21h F0h
; and the key wait through it.  No such file, not this LODE.SYS's, or no
; room: it stays off.
mt_boot:
        push    cs
        pop     ds
        mov     ax, 3305h               ; on the drive started from
        int     21h
        add     dl, 'A' - 1
        mov     [MDB(s_mtsys)], dl
        mov     dx, MDB(s_mtsys)
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     bp, ax                  ; BP = the file
        mov     ah, 48h
        mov     bx, 0FFFFh
        int     21h                     ; -> BX = the largest block
        sub     bx, MT_PARAS + 1
        jbe     .cl
        mov     ah, 48h                 ; a filler: all of it but MT's block
        int     21h                     ;  (and its MCB)
        jc      .cl
        mov     es, ax
        mov     ah, 48h
        mov     bx, MT_PARAS
        int     21h                     ; (the rest: the very end)
        pushf
        push    ax
        mov     ah, 49h                 ; the filler goes
        int     21h
        pop     dx                      ; DX = MT's block
        popf
        jc      .cl
        mov     es, dx
        dec     dx                      ; the last block?  (Not if a hole
        mov     ds, dx                  ;  below the largest one took it.)
        cmp     byte [0], 'Z'
        jne     .fr
        push    es
        pop     ds
        xor     dx, dx
        mov     cx, MT_LEN
        mov     bx, bp
        mov     ah, 3Fh                 ; the file into it
        int     21h
        push    cs
        pop     ds
        jc      .fr
        cmp     ax, MT_LEN
        jne     .fr
        xor     si, si                  ; this LODE.SYS's?  (mkmt.py's sum:
        xor     dx, dx                  ;  rotate left, add the byte)
        xor     ax, ax
        mov     cx, MT_LEN
.s:     mov     al, [es:si]
        rol     dx, 1
        add     dx, ax
        inc     si
        loop    .s
        cmp     dx, [MDB(mt_sum)]
        jne     .fr
        mov     ah, 43h                 ; task 0's screen: 2 EMS pages (none:
        mov     bx, 2                   ;  it stays off)
        int     67h
        or      ah, ah
        jnz     .fr
        mov     [es:mt_tab + TE_SH], dl
        mov     ah, 3Eh
        mov     bx, bp
        int     21h
        mov     di, MT_LEN              ; its BSS: zeros
        mov     cx, MT_PARAS * 16 - MT_LEN
        xor     al, al
        rep     stosb
        mov     dx, es
        mov     ah, 62h                 ; task 0: the Executive, the root
        int     21h                     ;  process; its TX in MT's BSS
        mov     [es:mt_tab+TE_PSP], bx
        mov     ax, dx
        add     ax, MT_TX0P
        mov     [es:mt_tab+TE_TX], ax
        push    KSEG
        pop     ds
        mov     ax, [first_mcb]
        mov     [es:mt_mcb0], ax
        dec     dx
        mov     ds, dx
        mov     word [1], 8             ; the system's, called MT
        mov     word [8], 'MT'
        xor     ax, ax
        mov     ds, ax
        cli
        mov     ax, [8 * 4]             ; INT 08h
        mov     [es:mt_old08], ax
        mov     ax, [8 * 4 + 2]
        mov     [es:mt_old08 + 2], ax
        mov     word [8 * 4], mt_tick
        mov     [8 * 4 + 2], es
        mov     ax, KSEG                ; INT 21h F0h: JMP FAR mt_f0
        mov     ds, ax
        mov     byte [f_F0], 0EAh
        mov     word [f_F0 + 1], mt_f0
        mov     [f_F0 + 3], es
        mov     byte [kbd_get.k], 0EAh  ; the key wait: JMP FAR mt_kwait
        mov     word [kbd_get.k + 1], mt_kwait
        mov     [kbd_get.k + 3], es
        sti
        push    cs
        pop     ds
        ret
.fr:    push    cs                      ; (no: MT's block goes, and the file
        pop     ds                      ;  is closed)
        mov     ah, 49h
        int     21h
.cl:    mov     bx, bp
        mov     ah, 3Eh
        int     21h
.x:     ret
%endif
