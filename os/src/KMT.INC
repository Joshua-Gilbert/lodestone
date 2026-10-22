; =====================================================================
;  KMT.INC - multitasking, behind a switch: MULTITASK=1 in \LODE.INI
;  (with EMS; without it, it stays off).  Being built in steps (the plan:
;  docs/lodestone-multitasking.md).  So far: the switch (M1); tasks, each
;  a DOS program in a region of its own, switched when one waits for a
;  key (M2a); the front one chosen with CODE-Tab, each task's screen kept
;  in 2 EMS pages of its own (M2b); tasks preempted at the timer's tick,
;  where it is safe (M3); each task's coprocessor state kept (M3b); a
;  background task's INT 10h output in its own screen, and a task that
;  writes the screen itself frozen in the background (M4a); keys for the
;  front task only, its waits in the BIOS switched from, CODE-Tab wherever
;  it is typed (M4b); each task's own INT 33h mouse state (M4c); each
;  task's own vectors (M5a: mt_vrun's swapped at every switch, the
;  keyboard's 09h and 1Bh at a change of the front, the rest the
;  machine's, those left pointing into a task's region put back at its
;  end).
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
;    - INT 08h goes through mt_tick (the BIOS's handler first).  A
;      program's hook goes ahead of it, as in DOS, in its own task's
;      vectors (M5a); while the running task has one there the tick
;      doesn't switch it;
;    - done.sw, INT 21h's way out, becomes a far jump to mt_exit;
;    - INT 21h F0h through mt_f0: f_F0's first 5 bytes (MOV AL,[BP+F_AX]
;      and OR AL,AL) become a far jump to it, and it comes back past
;      them.  (KEMS.INC patches f_F0.lend and .back, further in.)
;    - kbd_get.k (MOV AH,1 / INT 16h / JNZ .have: 6 bytes) becomes a far
;      jump to mt_kwait, where a task waits for a key: only the front one
;      reads them; one that waits with nothing typed lets another run.
;    - INT 10h goes through mt_v10 (then the BIOS's): a background task's
;      calls are done in its own screen, the front one's shadowed there.
;    - INT 13h goes through mt_i13, which counts the calls running.
;    - INT 16h goes through mt_i16: keys for the front task only, and a
;      read with nothing typed waits there while the other tasks run.
;    - crit_disk.c24 (MOV SI,crit_dev / INT 24h: 5 bytes) becomes a far
;      call to mt_c24, which counts the critical error's prompt running.
;    - INT 33h goes through mt_i33 once the UI has set it to its driver
;      (put there at a spawn or a change of the front): a background
;      task's call is done on its own state.  And ui_progend (MOV AX,
;      [ui_seg] / OR AX,AX: 5 bytes) becomes a far jump to mt_pgend,
;      which forgets a background program's event handler as it ends.
;
;  A task (1 to 7; task 0 is the Executive and whatever it runs) is a
;  region, a block of its own (owner 8, "T1".."T7") carved from the top of
;  the free memory below MT's block, downward:
;    TX     its context while another runs: its SS:SP, the EMS windows'
;           page registers, the kernel's per-task variables (mt_ranges: the INT 21h nesting, the break
;           and console state, the current directories, the DTA and
;           console line, the current PSP, the memory arena's start),
;           the kernel stack's slice from SP up (it waits inside INT 21h),
;           its coprocessor's state and its INT 33h driver's (m33_st),
;           its own vectors (and, not task 0's, the table at its spawn)
;    stub   a PSP and a few instructions: EXEC the program, then MT_END
;           (its own parent: ended itself, it lands on MT_END too)
;    env    a copy of the spawner's environment (it may end first)
;    arena  the task's own MCB chain: its first_mcb, ended by a 'Z' here
;  Task 0's TX is in MT's block (section mttbss).  Switching happens inside
;  INT 21h (indos 1) at mt_kwait or when a task ends, and outside it at
;  the tick or on INT 21h's way out, where it is safe (mt_safe).
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
TE_VF       equ 24                      ; VF_DIRECT, and its SPF_BG and SPF_FREEZE
VF_DIRECT   equ 1                       ; (it wrote the screen itself, or was in
                                        ;  graphics, when last switched from in
                                        ;  front: frozen in the background)
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
TX_FPV      equ TX_KSTK + KSLICE        ; 1: its coprocessor state kept (0: FNINIT)
TX_FPU      equ (TX_FPV + 2) & ~1       ; the state (FNSAVE's 94 bytes, even)
TX_M33      equ TX_FPU + 94             ; its INT 33h state (the driver's m33_st:
                                        ;  where the pointer is, its ranges,
                                        ;  counts, shape, event handler)
TX_VEC      equ TX_M33 + M33_ST         ; its own vectors (mt_vrun's), while
                                        ;  another runs
TX_FVEC     equ TX_VEC + MT_NVEC * 4    ; its INT 09h and 1Bh (mt_vfr's), while
                                        ;  another is in front
TX0_PARAS   equ (TX_FVEC + MT_NFV * 4 + 15) / 16    ; (task 0's TX ends here)
TX_GSN      equ TX0_PARAS * 16          ; the vector table at its spawn (a
                                        ;  task's: the ones left pointing into
                                        ;  its region at its end put back)
TX_PARAS    equ TX0_PARAS + 1024 / 16
MT_NVEC     equ 16                      ; (mt_vrun's and mt_vfr's counts)
MT_NFV      equ 2

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

%macro VCALL 0                          ; INT 10h: the BIOS's, not mt_v10
        call    mt_vcall
%endmacro

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
mt_slice    db      2                   ; ticks left in the running task's turn
mt_pend     db      0                   ; 1: another task's turn (its turn over,
                                        ;  or a key for the front one waiting)
mt_lcs      dw      0                   ; (the last switch's interrupted CS,
mt_lip      dw      0                   ;  IP, flags and SP, for test_mt: set
mt_lfl      dw      0                   ;  by mt_safe when it says yes)
mt_lsp      dw      0
mt_fpu      db      0                   ; 1: a coprocessor (INT 11h), kept per
                                        ;  task
mt_front    db      0                   ; the task in front
mt_cur      db      0                   ; the task running
mt_swreq    db      0FFh                ; a task to bring to the front (FFh: none)
mt_hotk     dw      0A500h, 0A5F0h      ; the hot key, CODE-Tab, as AH=10h
                                        ;  gives it on the 1520 (KEYCODE.COM),
                                        ;  and as a BIOS keeping CODE keys with
                                        ;  F0h would
mt_wsv      db      0, 0                ; (mt_smap: windows 0 and 1 as they were)
mt_old10    dd      0                   ; INT 10h as it was
mt_shd      db      0                   ; 1: the front task's pages shadow
                                        ;  B800h's first 16 KB (a text mode,
                                        ;  another task there)
mt_vbusy    db      0                   ; 1: MT has a task's screen pages
                                        ;  mapped itself (interrupts on): INT
                                        ;  10h meanwhile straight to the BIOS
mt_inb      db      0                   ; MT's calls the BIOS is doing (VCALL;
                                        ;  after mt_vbusy, for mt_v10's test)
mt_vlost    db      0                   ; 1: a call went to the screen not
                                        ;  shadowed (mt_vlose): whether the
                                        ;  front task writes it is not known
mt_isr0     db      0                   ; (mt_vcall: the interrupts in service
                                        ;  when MT passed its call on)
mt_old13    dd      0                   ; INT 13h as it was
mt_in13     db      0                   ; INT 13h calls running (mt_i13)
mt_swing    db      0                   ; 1: mt_swnow is changing the front
                                        ;  (after mt_in13, for mt_i16's test)
mt_crit     db      0                   ; the kernel's INT 24h running (mt_c24)
mt_idle     db      0                   ; 1: a key wait in the kernel's idle
                                        ;  (its INT 28h; mt_kwait .idle)
mt_old16    dd      0                   ; INT 16h as it was
mt_mid      db      0                   ; 1: the front changed while the one in
                                        ;  front may be in the middle of its run
                                        ;  (not at a key wait: mt_scrsv)
mt_ssv      dw      0, 0                ; (mt_swnow: the stack it came on)
mt_old33    dd      0                   ; INT 33h as it was: the UI's driver
mt_in33     db      0                   ; MT's own INT 33h calls (mt_m33)
mt_33md     db      0                   ; (mt_i33: 40:49h as it was,
mt_33dn     dw      0                   ;  m33_dn and m33_dmode,
mt_33eb     dw      0                   ;  m33_ev and m33_busy,
mt_33pk     db      0                   ;  the mouse's IRQ bit masked (0Ch,
mt_33pm     db      0                   ;  14h: 0 else) and the mask before)
mt_33sb     db      0                   ; (mt_scrto: m33_busy as it was)
mt_33ot     db      0                   ; (mt_m33on: another driver answered)
; each task's own vectors (M5a), swapped at every switch: the CPU's traps,
; INT 08h (its timer hook ahead of mt_tick), 10h, 16h, 1Ch, DOS's (21h-24h,
; 28h, 2Fh) and the coprocessor's IRQ 13.  And the front task's: 09h and
; 1Bh (the keyboard's), swapped at a change of the front.  The rest are
; the machine's (13h, 33h, the other IRQs, 02h, 67h, the BIOS's tables)
mt_vrun     db      00h, 01h, 03h, 04h, 06h, 08h, 10h, 16h
            db      1Ch, 21h, 22h, 23h, 24h, 28h, 2Fh, 75h
%if $ - mt_vrun != MT_NVEC
%error "mt_vrun: MT_NVEC"
%endif
mt_vfr      db      09h, 1Bh
mt_fv       times   MT_NFV * 2 dw 0     ; the front task's 09h and 1Bh while
                                        ;  another runs (mt_vfr's order)
mt_vr       dw      0                   ; (mt_vfix: the region, its end)
mt_ve       dw      0
mt_vs       times   VIDLEN db 0         ; (mt_v10: the BIOS data worked on)
mt_vp0      dw      0                   ; (mt_vtty: where it was)
mt_vw       db      0                   ; (mt_vscr: the window's width, its
mt_vn       db      0                   ;  lines, attribute, rows moved and
mt_va       db      0                   ;  blanked, down or up)
mt_vt       db      0
mt_vb       db      0
mt_vd       db      0
; a text mode as the 1520's BIOS sets it (int10.asm VidSetMode; the
; tables in at_compat.asm): columns and Mode Control by mode, then the
; BIOS data of mode 3, a new task's
mt_vcols    db      40, 40, 80, 80
mt_vsel     db      2Ch, 28h, 2Dh, 29h
mt_v3       db      3                   ; 49h: the mode
            dw      80, 1000h, 0        ; 4Ah: columns, 4Ch: a page's length,
                                        ; 4Eh: the page shown's start
            times   16 db 0             ; 50h: the 8 pages' cursors
            dw      0607h               ; 60h: the cursor's shape
            db      0                   ; 62h: the page shown
            dw      3D4h                ; 63h: the CRTC's port
            db      29h, 30h            ; 65h: Mode Control, 66h: Colour Select
VS_MODE     equ     mt_vs               ; (mt_vs as 40:49h on)
VS_COLS     equ     mt_vs + 4Ah - 49h
VS_LEN      equ     mt_vs + 4Ch - 49h
VS_START    equ     mt_vs + 4Eh - 49h
VS_CUR      equ     mt_vs + 50h - 49h
VS_SHAPE    equ     mt_vs + 60h - 49h
VS_PAGE     equ     mt_vs + 62h - 49h
VS_PORT     equ     mt_vs + 63h - 49h
VS_MSEL     equ     mt_vs + 65h - 49h
VS_PAL      equ     mt_vs + 66h - 49h
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
        call    far [cs:mt_old08]       ; (back with the EOI sent; interrupts
        cli                             ;  off, whatever a hook there did)
        inc     word [cs:mt_ticks]
        push    ax
        push    bx
        push    dx
        push    ds
        push    bp
        mov     bp, sp                  ; ([bp+10]: the interrupted IP, CS, FL)
        mov     ax, cs                  ; (MT's own code interrupted: a task
        cmp     [bp+12], ax             ;  just resumed in mt_load, its turn
        je      .r                      ;  not touched; mt_fdrain; elsewhere
                                        ;  indos is 1)
        push    KSEG
        pop     ds
        push    es
        les     bx, [bp+10]             ; just after a HLT: idle, so its turn
        cmp     byte [es:bx-1], 0F4h    ;  is over
        pop     es
        je      .p
        cmp     byte [cs:mt_slice], 0   ; its turn over?
        je      .p
        dec     byte [cs:mt_slice]
        jnz     .w
.p:     mov     byte [cs:mt_pend], 1
.w:     call    mt_kwant                ; (or a key for the front task)
        cmp     byte [cs:mt_pend], 0
        je      .r
        push    es                      ; INT 08h still ours?  (Else a hook
        xor     ax, ax                  ;  ahead of it, in the running task's
        mov     es, ax                  ;  vectors, is what this interrupted,
        mov     ax, cs                  ;  maybe above a TSR's or the BIOS's
        cmp     word [es:8 * 4], mt_tick ;  code: the switch waits for INT
                                        ;  21h's way out.)
        jne     .h
        cmp     [es:8 * 4 + 2], ax
.h:     pop     es
        jne     .r
        lea     ax, [bp+16]
        mov     [cs:mt_lsp], ax
        mov     ax, [bp+12]
        mov     bx, [bp+10]
        mov     dx, [bp+14]
        call    mt_safe
        jc      .r
        call    mt_hot                  ; CODE-Tab, typed with nothing asking
        cli                             ;  for keys?  (Safe here: the task's own
        call    mt_preempt              ;  code interrupted, not the BIOS's)
.r:     pop     bp
        pop     ds
        pop     dx
        pop     bx
        pop     ax
        iret

; INT 21h's way out (done's MOV SS,AX / MOV SP,BX / POPA: interrupts off,
; DS = KSEG, AX:BX = the caller's stack with its frame): another task's
; turn, if one is due and the caller is at a safe point, then on out
mt_exit:
        mov     ss, ax
        mov     sp, bx
        cmp     byte [cs:mt_pend], 0
        jne     .c
.go:    popa
        pop     ds
        pop     es
        iret
.c:     push    bp
        mov     bp, sp                  ; ([bp+2]: the frame, F_*)
        lea     ax, [bp+2+F_USP]
        mov     [cs:mt_lsp], ax
        mov     ax, [bp+2+F_CS]
        mov     bx, [bp+2+F_IP]
        mov     dx, [bp+2+F_FL]
        call    mt_safe
        jc      .n
        call    mt_preempt
.n:     cli
        pop     bp
        jmp     .go

; a key in the BIOS's buffer, the front task waiting for one in the
; background: its turn (mt_pend).  DS = KSEG; AX, BX changed
mt_kwant:
        mov     al, [cs:mt_front]
        cmp     al, [cs:mt_cur]
        je      .x
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITK
        jne     .x
        push    ds
        push    40h
        pop     ds
        mov     ax, [1Ah]
        cmp     ax, [1Ch]
        pop     ds
        je      .x
        mov     byte [cs:mt_pend], 1
.x:     ret

; the interrupted (or calling) code at CS AX, IP BX, flags DX, on SS: may
; the running task be switched from there?  CF if not.  Only if: no INT 21h
; under way; interrupts were on, and no other hardware interrupt is in
; service; CS below A000h (not the BIOS, the ROM, the EMS frame), not the
; kernel's or MT's; in the UI's segment, only at its idle HLTs; no INT 33h
; event handler running; SS and CS in the task's own memory (mt_mine).
; DS = KSEG; AX, BX, DX changed
mt_safe:
        mov     [cs:mt_lcs], ax
        mov     [cs:mt_lip], bx
        mov     [cs:mt_lfl], dx
        test    dh, 2                   ; (IF)
        jz      .no
        cmp     byte [indos], 0
        jne     .no
        cmp     byte [cs:mt_inb], 0     ; (a hook's code inside a call MT
        jne     .no                     ;  passed on to the BIOS, or inside an
        cmp     word [cs:mt_in13], 0    ;  INT 13h call: an INT 15h or 40h hook
        jne     .no                     ;  the BIOS calls out to meanwhile; or
                                        ;  a handler's, on its own stack, while
                                        ;  mt_swnow changes the front)
        push    es                      ; (m33_busy is the UI's)
        mov     es, [ui_seg]
        cmp     byte [es:m33_busy], 0
        pop     es
        jne     .no
        cmp     ax, 0A000h
        jae     .no
        cmp     ax, KSEG
        je      .no
        mov     dx, cs
        cmp     ax, dx
        je      .no
        cmp     ax, [ui_seg]
        jne     .pic
        cmp     bx, ..@ui_idle
        je      .pic
        cmp     bx, ..@ui_sidle
        jne     .no
.pic:   mov     al, 0Bh                 ; the PIC's in-service register (as
        out     20h, al                 ;  capture reads it)
        in      al, 20h
        mov     ah, al
        mov     al, 0Ah
        out     20h, al
        or      ah, ah
        jnz     .no
        mov     ax, ss                  ; SS and CS the task's own: not a TSR's
        call    mt_mine                 ;  or a driver's stack or code (CS in
        jc      .no                     ;  the UI's: at an idle HLT, vetted
        mov     ax, [cs:mt_lcs]         ;  above; LCMD's saver runs there)
        cmp     ax, [ui_seg]
        je      .y
        call    mt_mine
        ret
.y:     clc
        ret
.no:    stc
        ret

; segment AX: in the running task's own memory?  CF if not.  A task's: its
; region.  Task 0's: the UI's block while the Executive runs, else a block
; of the running program's (cur_psp's), found in the arena.  DS = KSEG; BX,
; DX changed
mt_mine:
        push    es
        mov     bx, [cur_psp]           ; (task 0 running a program)
        cmp     byte [cs:mt_cur], 0
        jne     .t
        cmp     bx, [root_psp]
        jne     .w
        mov     bx, [ui_seg]            ; (the Executive)
        jmp     .b
.t:     push    ax                      ; (a task)
        mov     al, [cs:mt_cur]
        call    mt_ent
        pop     ax
        mov     bx, [cs:bx+TE_REG]
.b:     dec     bx                      ; in the block at BX
        mov     es, bx
        inc     bx
        cmp     ax, bx
        jb      .no
        add     bx, [es:3]
        cmp     ax, bx
        jae     .no
        jmp     .y
.w:     mov     dx, bx                  ; the block AX is in: cur_psp's?
        mov     bx, [cs:mt_mcb0]
.l:     mov     es, bx
        inc     bx
        cmp     ax, bx
        jb      .no                     ; (an MCB itself)
        add     bx, [es:3]
        cmp     ax, bx
        jb      .o
        cmp     byte [es:0], 'Z'
        jne     .l
        jmp     .no                     ; (past the arena)
.o:     cmp     [es:1], dx
        jne     .no
.y:     clc
        pop     es
        ret
.no:    stc
        pop     es
        ret

; another task's turn: the front one if it waits for a key that is there,
; else the next ready one, after a task asked for in front is brought
; there.  (Called from mt_tick or mt_exit; returns when this task runs
; again.)  None: this one goes on, a new turn (frozen in the background,
; it gives way to the front one all the same)
mt_preempt:
        call    mt_swnow                ; (first: interrupts on meanwhile)
        call    mt_fdrain               ; (then: nothing saved or chosen yet)
        mov     byte [cs:mt_pend], 0
        mov     al, [cs:mt_front]
        cmp     al, [cs:mt_cur]
        je      .p
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITK
        jne     .p
        push    ds
        push    40h
        pop     ds
        mov     bx, [1Ah]
        cmp     bx, [1Ch]
        pop     ds
        je      .p
        mov     bl, al
        jmp     mt_switch
.p:     call    mt_pick
        jnc     mt_switch
        mov     al, [cs:mt_cur]         ; none: this one goes on, a new turn;
        call    mt_ent                  ;  unless it is frozen here: then the
        call    mt_frz                  ;  front one (waiting for a key, or it
        jnz     .fz                     ;  would have been picked)
        mov     byte [cs:mt_slice], 2
        ret
.fz:    mov     bl, [cs:mt_front]
        jmp     mt_switch

; a new task's first return (mt_load): to its stub, flags with IF
mt_first:
        iret

; before a switch saves or chooses anything: a coprocessor error not yet
; handled, handled now.  The 1520 (as an AT) holds the 287's BUSY after an
; unmasked error until IRQ 13's handler (the BIOS's INT 75h) clears it
; with an OUT to F0h, and the 286 waits on BUSY before any coprocessor
; instruction but FNINIT: so with interrupts off, mt_switch's FNSAVE could
; wait for ever.  FNOP waits on it here with them on, so the error reaches
; this task as in DOS.  Its handler may even come back into the scheduler
; (a key read, a tick): with nothing half done, that is a switch like any
; other.  After it the 287 is idle, nothing of the task's in flight, so
; FNSAVE and FRSTOR can't be held up.  (Interrupts off again after it)
mt_fdrain:
        cmp     byte [cs:mt_fpu], 0
        je      .x
        sti
        jmp     short .w                ; (STI's shadow passed: IRQ 13 can
.w:     fnop                            ;  come in before FNOP, or in its wait;
        cli                             ;  pcemu, which looks for interrupts
.x:     ret                             ;  where a block starts, here too)

; ---------------------------------------------------------------------
;  kbd_get.k: a task waits for a key (inside INT 21h; DS anything)
; ---------------------------------------------------------------------
mt_kwait:
        mov     byte [cs:mt_idle], 0    ; (back from the kernel's idle)
        push    ds
        push    ax
        push    bx
        push    KSEG
        pop     ds
.top:   call    mt_hot                  ; CODE-Tab typed?  (Before the look for
        call    mt_can                  ;  a key: INT 16h AH=01h drops it.)  A
        jc      .f                      ;  task to bring to the front?  (Only
        call    mt_swkw                 ;  where it could run: else later.)
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
        pop     ds                      ;  (a TSR popping up from that INT 28h
        mov     byte [cs:mt_idle], 1    ;  on the kernel's stack: its INT 16h
        jmp     KSEG:kbd_get.k + 6      ;  calls its own, not the kernel's)
.have:  pop     bx
        pop     ax
        pop     ds
        jmp     KSEG:kbd_get.have
; in the background: it waits without reading keys, while another runs.
; Unless it can't be switched from: then it comes to the front for them
; (INT 16h gives keys to the front task only), or for a critical error's
; prompt reads them as it is (mt_i16 lets them through: everything waits
; for the answer, the prompt on the real screen)
.bg:    call    mt_can
        jnc     .bgp
        cmp     byte [cs:mt_crit], 0
        jne     .k
        cmp     byte [cs:mt_inb], 0     ; (inside a call MT passed on to the
        jne     .k                      ;  BIOS, an INT 13h call, or a change
        cmp     word [cs:mt_in13], 0    ;  of the front: as it is, mt_i16
        jne     .k                      ;  letting it read them)
        mov     [cs:mt_swreq], al       ; (this task, as mt_swnow does it: the
        call    mt_swnow                ;  one in front may be in its run)
        jmp     .k
.bgp:
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
.park:  call    mt_fdrain               ; (inside INT 21h: nothing switches
        push    bx                      ;  meanwhile, BL stays the one)
        mov     al, [cs:mt_cur]
        call    mt_ent
        mov     byte [cs:bx+TE_STATE], TS_WAITK
        pop     bx
        jmp     mt_switch

; CF if the running task can't be switched away from here: a nested INT
; 21h (an INT 24h answer), or more kernel stack than its TX holds; inside
; a call MT passed on to the BIOS or an INT 13h call; while mt_swnow
; changes the front (an interrupt handler's DOS call meanwhile)
mt_can: cmp     byte [indos], 1
        jne     .no
        cmp     byte [cs:mt_inb], 0
        jne     .no
        cmp     word [cs:mt_in13], 0    ; (and mt_swing)
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

; a task other than the running one that is ready to run (TS_RUN) and
; not frozen in the background (mt_frz), the next after it in turn -> BL;
; CF if none
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
        jne     .n
        call    mt_frz
.n:     pop     bx
        je      .y
        loop    .l
        stc
        jmp     short .x
.y:     mov     bl, al
        clc
.x:     pop     cx
        pop     ax
        ret

; task AL (its entry at BX) may run?  ZF if so: in front, or in the
; background unless frozen there (SPF_FREEZE; or VF_DIRECT, unless SPF_BG)
mt_frz: push    ax
        cmp     al, [cs:mt_front]
        je      .x
        mov     ah, [cs:bx+TE_VF]
        test    ah, SPF_FREEZE
        jnz     .x                      ; (ZF clear: frozen)
        and     ah, VF_DIRECT | SPF_BG
        cmp     ah, VF_DIRECT
        je      .fr
        xor     ah, ah                  ; (ZF: it runs)
        jmp     short .x
.fr:    or      ah, ah
.x:     pop     ax
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
        cld                             ; (DF as the task had it, at a tick)
        mov     al, [cs:mt_cur]
        push    bx
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        pop     bx
.sv:    mov     [es:TX_SP], sp
        mov     [es:TX_SS], ss
        call    mt_emsget
        push    bx
        call    mt_vsv                  ; its own vectors, and the front's (09h,
        call    mt_fvsync               ;  1Bh) as its turn left them
        pop     bx
        cmp     byte [cs:mt_fpu], 0     ; its coprocessor's registers, control
        je      .nf                     ;  and status (mt_fdrain ran first:
        fnsave  [es:TX_FPU]             ;  the 287 is idle, so this can't wait
        fwait                           ;  for ever).  Its error, if any, has
        mov     al, [es:TX_FPU]         ;  been handled: its unmasked
        and     al, 3Fh                 ;  exceptions and ES cleared in the
        or      al, 40h                 ;  saved status, so FRSTOR doesn't
        and     [es:TX_FPU + 2], al     ;  raise them again (a 387-class chip
        mov     byte [es:TX_FPV], 1     ;  works ES out from them)
.nf:
        push    KSEG
        pop     ds
        xor     cx, cx                  ; its slice of the kernel stack (none:
        cmp     byte [indos], 0         ;  switched from outside INT 21h, on
        je      .k                      ;  its own stack)
        mov     cx, kstack_top
        sub     cx, sp
.k:     mov     [es:TX_KLEN], cx
        mov     si, sp
        mov     di, TX_KSTK
        rep     movsb
        push    bx
        call    mt_vsave                ; the kernel's variables
        pop     bx
mt_load:
        cli
        cld
        mov     byte [cs:mt_inb], 0     ; (none under way at a switch, nor an
        mov     byte [cs:mt_crit], 0    ;  INT 24h prompt, INT 13h call, change
        mov     word [cs:mt_in13], 0    ;  of the front or kernel's idle: one
        mov     byte [cs:mt_idle], 0    ;  left by a program ended inside it,
        mov     [cs:mt_cur], bl         ;  cleared)
        mov     byte [cs:mt_pend], 0    ; its turn: 2 ticks in front, 1 else
        mov     byte [cs:mt_slice], 1
        cmp     bl, [cs:mt_front]
        jne     .t
        inc     byte [cs:mt_slice]
.t:
        mov     al, bl
        call    mt_ent
        mov     byte [cs:bx+TE_STATE], TS_RUN
        mov     es, [cs:bx+TE_TX]
        cmp     byte [cs:mt_fpu], 0     ; its coprocessor state (none kept
        je      .nf                     ;  yet: as FNINIT leaves it)
        cmp     byte [es:TX_FPV], 0
        je      .fi
        frstor  [es:TX_FPU]
        jmp     .nf
.fi:    fninit
.nf:    push    KSEG
        pop     ds
        call    mt_vload
        call    mt_vld                  ; its own vectors; the front task's 09h
        call    mt_fvset                ;  and 1Bh (one ended may have set them)
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
;  each task's own vectors (M5a).  mt_vrun's are the running task's in
;  the vector table and in its TX while another runs: whatever it set
;  there, through AH=25h or itself, is saved at the switch away (mt_vsv)
;  and put back as it runs again (mt_vld).  A new task starts with its
;  spawner's.  mt_vfr's (INT 09h and 1Bh, which the keyboard's interrupt
;  calls, whoever runs) are the front task's: kept in mt_fv while another
;  runs, in a task's TX while another is in front (mt_fvto at a change of
;  the front); one a background task set in its turn is its own, saved and
;  taken off at the switch away (mt_fvsync, then mt_fvset).  Interrupts
;  off for all of them
; ---------------------------------------------------------------------
; mt_vrun's vectors to the TX at ES.  AX, BX, CX, SI, DI changed
mt_vsv: push    ds
        xor     si, si
        mov     ds, si
        mov     bx, mt_vrun
        mov     di, TX_VEC
        mov     cx, MT_NVEC
.l:     mov     al, [cs:bx]
        inc     bx
        xor     ah, ah
        shl     ax, 2
        mov     si, ax
        movsw
        movsw
        loop    .l
        pop     ds
        ret

; and back, from the TX at ES.  AX, BX, CX, SI, DI changed
mt_vld: push    ds
        push    es
        push    es
        pop     ds
        xor     si, si
        mov     es, si
        mov     bx, mt_vrun
        mov     si, TX_VEC
        mov     cx, MT_NVEC
.l:     mov     al, [cs:bx]
        inc     bx
        xor     ah, ah
        shl     ax, 2
        mov     di, ax
        movsw
        movsw
        loop    .l
        pop     es
        pop     ds
        ret

; the running task's turn over (or the front changing): mt_vfr's vectors
; as it left them.  The front task's go to mt_fv; another's, if it set
; them (they differ from mt_fv), are its own, to its TX (mt_fvset puts
; mt_fv's back).  AX, BX, CX, SI, DI changed (a switch's, on the task's
; stack: kept short)
mt_fvsync:
        push    ds
        push    es
        cld
        xor     ax, ax
        mov     ds, ax
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        jne     .bg
        push    cs
        pop     es
        mov     di, mt_fv
        call    .cp
        jmp     short .x
.bg:    mov     bx, mt_vfr
        mov     di, mt_fv
        mov     cx, MT_NFV
.c:     mov     al, [cs:bx]
        inc     bx
        xor     ah, ah
        shl     ax, 2
        mov     si, ax
        mov     ax, [si]
        cmp     ax, [cs:di]
        jne     .d
        mov     ax, [si+2]
        cmp     ax, [cs:di+2]
        jne     .d
        add     di, 4
        loop    .c
        jmp     short .x
.d:     mov     al, [cs:mt_cur]
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        mov     di, TX_FVEC
        call    .cp
.x:     pop     es
        pop     ds
        ret
.cp:    mov     bx, mt_vfr              ; (mt_vfr's, from the table at DS = 0,
        mov     cx, MT_NFV              ;  to ES:DI)
.cl:    mov     al, [cs:bx]
        inc     bx
        xor     ah, ah
        shl     ax, 2
        mov     si, ax
        movsw
        movsw
        loop    .cl
        ret

; mt_fv to the vector table.  AX, BX, CX, SI, DI changed
mt_fvset:
        push    ds
        push    es
        cld
        xor     ax, ax
        mov     es, ax
        push    cs
        pop     ds
        mov     si, mt_fv
        mov     bx, mt_vfr
        mov     cx, MT_NFV
.l:     mov     al, [bx]
        inc     bx
        xor     ah, ah
        shl     ax, 2
        mov     di, ax
        movsw
        movsw
        loop    .l
        pop     es
        pop     ds
        ret

; task AL to the front (mt_scrld, before mt_front is set): the one in
; front keeps its 09h and 1Bh in its TX, AL's are put in.  All kept
mt_fvto:
        pushf
        cli
        pusha
        push    ds
        push    es
        cld
        push    ax
        call    mt_fvsync
        mov     al, [cs:mt_front]
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        push    cs
        pop     ds
        mov     si, mt_fv
        mov     di, TX_FVEC
        mov     cx, MT_NFV * 2
        rep     movsw
        pop     ax
        call    mt_ent
        mov     ds, [cs:bx+TE_TX]
        push    cs
        pop     es
        mov     si, TX_FVEC
        mov     di, mt_fv
        mov     cx, MT_NFV * 2
        rep     movsw
        call    mt_fvset
        pop     es
        pop     ds
        popa
        popf
        ret

; a new task's vectors (the TX at ES; mt_spawn): its spawner's, and the
; whole table as it is now (TX_GSN).  AX, BX, CX, SI, DI changed
mt_vnew:
        pushf
        cli
        call    mt_vsv
        call    mt_fvsync
        push    ds
        mov     al, [cs:mt_cur]         ; its 09h and 1Bh: the spawner's (in
        cmp     al, [cs:mt_front]       ;  mt_fv if it is in front, else in its
        jne     .o                      ;  TX)
        push    cs
        pop     ds
        mov     si, mt_fv
        jmp     short .c
.o:     call    mt_ent
        mov     ds, [cs:bx+TE_TX]
        mov     si, TX_FVEC
.c:     mov     di, TX_FVEC
        mov     cx, MT_NFV * 2
        rep     movsw
        xor     si, si
        mov     ds, si
        mov     di, TX_GSN
        mov     cx, 1024 / 2
        rep     movsw
        pop     ds
        popf
        ret

; the task at BX ends (mt_end, its region not yet freed): every vector
; left pointing into its region (a hook of its programs', one they never
; took away; a TSR's) put back as it was at its spawn (TX_GSN): in the
; table, mt_fv, and the other tasks' TXs (a task it spawned started with
; its vectors).  All kept
mt_vfix:
        pusha
        push    ds
        push    es
        pushf
        cli
        cld
        mov     ax, [cs:bx+TE_REG]
        mov     [cs:mt_vr], ax
        dec     ax
        mov     es, ax
        mov     ax, [es:3]
        add     ax, [cs:mt_vr]
        mov     [cs:mt_ve], ax
        mov     ds, [cs:mt_vr]          ; (DS = its TX)
        xor     di, di
        mov     es, di
        xor     dx, dx                  ; (the vector's number * 4)
.iv:    call    mt_inr
        jc      .in
        mov     si, dx
        add     si, TX_GSN
        movsw
        movsw
        sub     di, 4
.in:    add     di, 4
        add     dx, 4
        cmp     dx, 1024
        jb      .iv
        push    cs
        pop     es
        mov     di, mt_fv
        mov     bx, mt_vfr
        mov     cx, MT_NFV
        call    .fx
        xor     al, al
.t:     cmp     al, [cs:mt_cur]
        je      .tn
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        je      .tn
        mov     es, [cs:bx+TE_TX]
        push    ax
        mov     di, TX_VEC
        mov     bx, mt_vrun
        mov     cx, MT_NVEC
        call    .fx
        mov     di, TX_FVEC
        mov     bx, mt_vfr
        mov     cx, MT_NFV
        call    .fx
        pop     ax
.tn:    inc     al
        cmp     al, MT_TASKS
        jb      .t
        popf
        pop     es
        pop     ds
        popa
        ret
; CX vectors at ES:DI, their numbers at CS:BX: those in the region put
; back from the TX at DS.  AX, BX, CX, SI, DI changed
.fx:    call    mt_inr
        jc      .fn
        mov     al, [cs:bx]
        xor     ah, ah
        shl     ax, 2
        add     ax, TX_GSN
        mov     si, ax
        movsw
        movsw
        sub     di, 4
.fn:    add     di, 4
        inc     bx
        loop    .fx
        ret

; the vector at ES:DI points into the region mt_vr..mt_ve?  CF if not.
; AX changed
mt_inr: mov     ax, [es:di]
        shr     ax, 4
        add     ax, [es:di+2]
        jc      .no
        cmp     ax, [cs:mt_vr]
        jb      .no
        cmp     ax, [cs:mt_ve]
        jae     .no
        clc
        ret
.no:    stc
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
        cmp     al, MT_SCREEN
        je      mt_screen
        cmp     al, 1
        je      mt_open
        or      al, al                  ; (f_F0's own two, then on there)
        jmp     KSEG:f_F0 + 5
mt_bad: mov     ax, 1
mt_fail:
        jmp     KSEG:fail

; F0h AL=1 (files open on drive DL: DEFRAG and System ask before writing
; a disk's FAT and directories themselves): with another task there, at
; least 1, since it could open one meanwhile
mt_open:
        cmp     byte [cs:mt_cur], 0     ; (a task's: the Executive is another)
        jne     .y
        mov     al, 1
.l:     call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        jne     .y
        inc     al
        cmp     al, MT_TASKS
        jb      .l
        mov     al, 1                   ; (none: f_F0's own answer)
        or      al, al
        jmp     KSEG:f_F0 + 5
.y:     mov     word [bp+F_CX], 1
        jmp     KSEG:ok

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
        cmp     ah, TS_RUN              ; (ready but frozen behind: listed as
        jne     .s                      ;  TS_FROZEN)
        call    mt_frz
        jz      .s
        mov     ah, TS_FROZEN
.s:     inc     cx
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
        mov     ah, [cs:mt_cur]
        mov     [bp+F_CX], cx
        mov     [bp+F_AX], ax
        jmp     KSEG:ok

; MT_FRONT: task BL to the front, where tasks can next switch (the tick
; or a key wait: mt_swnow)
mt_frontc:
        mov     al, [bp+F_BX]
        cmp     al, MT_TASKS
        jae     mt_bad
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        je      mt_bad
        mov     [cs:mt_swreq], al
        jmp     KSEG:ok

; MT_SCREEN: the caller's screen, which it wrote itself, is as it should
; be (put back after a screen saver, say): if it is the front task's, in a
; text mode, with another task there, its pages are given the screen again,
; so the switch away doesn't find it writing the screen itself
mt_screen:
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        jne     .x
        call    mt_others
        jc      .x
        mov     byte [cs:mt_shd], 0
        call    mt_sync
.x:     jmp     KSEG:ok

; MT_END: from a task's stub, its program done.  Its handles (the
; inherited ones) closed, its region freed, and another task runs.
mt_end: cmp     byte [cs:mt_swing], 0   ; (a change of the front its handler
        je      .sw                     ;  ended it inside: the front one's
        call    mt_m33on                ;  INT 33h state put back, as that
        mov     al, [cs:mt_front]       ;  change would have, and m33_busy
        call    mt_m33ld                ;  clear: a handler busy as it began
        mov     byte [cs:mt_33sb], 0    ;  may be this task's, never back)
        call    mt_m33nb
.sw:    mov     word [cs:mt_vbusy], 0   ; (as in mt_load; and INT 13h's count,
        mov     byte [cs:mt_crit], 0    ;  should one have been left; and a
        mov     word [cs:mt_in13], 0    ;  change of the front its handler ended
                                        ;  it inside: mt_swing, mt_vbusy)
        mov     al, [cs:mt_cur]
        or      al, al
        jz      mt_bad                  ; (not the Executive)
        call    mt_fdrain               ; (before mt_load's FRSTOR; then
        sti                             ;  interrupts on, as INT 21h had them)
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
.np:    call    mt_vfix                 ; vectors left pointing into the region:
        mov     cx, [cs:bx+TE_REG]      ;  as they were; then the region freed
        dec     cx                      ;  (a program that stayed resident
        mov     es, cx                  ;  too: its hooks are gone, so is it)
        mov     word [es:1], 0
        mov     byte [cs:bx+TE_STATE], TS_FREE
        call    mt_others               ; (the last one: no shadow, alone)
        jnc     .o
        mov     byte [cs:mt_shd], 0
.o:     mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        jne     .f
        push    ax                      ; it was in front: the Executive's
        mov     ax, 2                   ;  task is, with its screen (the
        call    mt_m33                  ;  INT 33h pointer off meanwhile)
        xor     al, al                  ;  and its INT 33h state
        call    mt_scrld
        call    mt_m33on
        xor     al, al
        call    mt_m33ld
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
        mov     byte [cs:mt_inb], 0     ; (as in mt_end, but not mt_swing nor
                                        ;  mt_vbusy: a handler's spawn inside
                                        ;  a change of the front leaves them)
        mov     byte [cs:mt_crit], 0
        mov     byte [cs:mt_in13], 0
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
        mov     byte [cs:bx+TE_SF], 1   ; (kept: mode 3, clear, below)
        mov     al, [cs:mt_sflags]
        and     al, SPF_BG | SPF_FREEZE
        mov     [cs:bx+TE_VF], al
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
        call    mt_vnew                 ; (its vectors: the caller's)
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
        mov     byte [es:TX_FPV], 0     ; (its coprocessor: FNINIT's, first)
        call    mt_m33new               ; (its INT 33h state)
        call    mt_33hk
        push    ax                      ; its screen: mode 3, clear (it may
        push    ds                      ;  print before it is ever in front)
        push    cs
        pop     ds
        mov     si, mt_v3
        mov     di, TX_VID
        mov     cx, VIDLEN
        rep     movsb
        pop     ds
        push    es
        mov     bx, [cs:mt_new]
        mov     byte [cs:mt_vbusy], 1
        call    mt_smap                 ; (MT's own, just given: there)
        jc      .ns
        push    EMS_FRAME
        pop     es
        xor     di, di
        mov     ax, 0720h
        mov     cx, 2000h
        rep     stosw
        xor     ax, ax
        mov     cx, 2000h
        rep     stosw
        call    mt_wrest
.ns:    mov     byte [cs:mt_vbusy], 0
        pop     es
        pop     ax
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
        call    mt_sync                 ; (the front one's screen shadowed now)
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
; isn't followed round.)  Called at a key wait, an INT 16h call, and a tick
; at a safe point: never while the BIOS's own INT 16h code may be changing
; the buffer.  DS anything; AX, BX changed; interrupts off meanwhile (as
; the caller had them after)
mt_hot: pushf
        push    ds
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
.no:    pop     cx
        pop     si
        pop     ds
        popf
        ret
.nx:    inc     bx
        inc     bx
        cmp     bx, [82h]
        jb      .nr
        mov     bx, [80h]
.nr:    ret

; the task asked for in front (mt_swreq: CODE-Tab, MT_FRONT), if there is
; one and it is still there, brought there now: the caller is where tasks
; may switch.  The coprocessor drained first, on the caller's stack.  Then
; on MT's own (1 KB: the screens' copies, the BIOS's mode set, the INT 33h
; driver and a program's mouse handler need more than a program's may
; have), with interrupts on (as in a key wait; after, as they were) and
; mt_swing set: nothing switches meanwhile (mt_safe, mt_can), and a
; handler's call meanwhile leaves it for later.  From mt_preempt the one
; in front may be in the middle of its run (mt_mid, for mt_scrsv); from a
; key wait (mt_swkw) it is not, if it is the one waiting.  AX changed
mt_swkw:
        mov     ah, 0
        jmp     short mt_swnow.go
mt_swnow:
        mov     ah, 1
.go:    cmp     byte [cs:mt_swing], 0   ; (one under way: this one later)
        jne     .x
        cmp     byte [cs:mt_swreq], 0FFh
        je      .x
        pushf
        call    mt_fdrain               ; (first, on the caller's own stack: a
        cli                             ;  coprocessor error pending taken
        mov     al, 0FFh                ;  there, not on MT's)
        xchg    al, [cs:mt_swreq]
        cmp     al, 0FFh
        je      .r
        push    bx
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        pop     bx
        je      .r
        or      ah, ah                  ; (only now: a call meanwhile, refused,
        jnz     .m                      ;  leaves this one's; and from a key
        push    ax                      ;  wait, the one in front as it is
        mov     al, [cs:mt_cur]         ;  after the drain: its own if it is
        cmp     al, [cs:mt_front]       ;  the one waiting.  AL: the task for
        pop     ax                      ;  mt_scrto)
        je      .m
        inc     ah
.m:     mov     [cs:mt_mid], ah
        mov     [cs:mt_ssv], sp
        mov     [cs:mt_ssv + 2], ss
        push    cs
        pop     ss
        mov     sp, mt_bend
        mov     byte [cs:mt_swing], 1
        sti
        call    mt_scrto
        cli
        mov     byte [cs:mt_swing], 0
        mov     ss, [cs:mt_ssv + 2]
        mov     sp, [cs:mt_ssv]
.r:     popf
.x:     ret

; ---------------------------------------------------------------------
;  INT 16h (M4b): keys for the front task only.  First, at any call made
;  with no hardware interrupt in service, CODE-Tab is taken out of the
;  buffer (mt_hot), before a peek could drop it; the task asked for then
;  comes to the front at the next safe point (mt_pend: the tick, INT 21h's
;  way out), or here, in a read that may be switched from.  Then the
;  reads and peeks (AH = 00h, 01h, 10h, 11h):
;    - a critical error's prompt (the kernel's INT 24h running: everything
;      waits for its answer), or a call with an interrupt in service (a
;      TSR's pop-up: the machine's, as its output is): as they are;
;    - the kernel's own (DOS's key status and flush, AH=0Bh, 06h, 0Ch,
;      IOCTL 4406h) and MT's: in the background, no key;
;    - a program's own (its code in the task's own memory, mt_mine): in
;      the background a peek finds nothing.  A read, made where the task
;      may be switched from (mt_safe), waits here: in the background until
;      it is in front and a key comes, in front while nothing is typed,
;      other tasks running meanwhile (mt_wkey: the key brings it back);
;    - any other (through a TSR's hook loaded after MT, from the ROM or
;      the EMS frame; a read where the task can't be switched from): as
;      they are.
;  Other functions as they are (AH=05h's key goes to the front task).
; ---------------------------------------------------------------------
I16_AH      equ -3                      ; (the caller's AH, from mt_i16's BP;
                                        ;  its IP, CS, flags at BP+2)
mt_i16:
        cli
        push    bp
        mov     bp, sp
        push    ds
        push    ax
        push    bx
        push    dx
        push    KSEG
        pop     ds
        call    mt_isr
        jnz     .pas
        cmp     byte [cs:mt_inb], 0     ; (inside a call MT passed on to the
        jne     .pas                    ;  BIOS, an INT 13h call, or a change
        cmp     word [cs:mt_in13], 0    ;  of the front: an interrupt's, as M4a
        jne     .pas                    ;  takes INT 10h's there)
        cmp     byte [cs:mt_crit], 0    ; (a count left by a handler that never
        je      .top                    ;  came back: not inside INT 21h now)
        cmp     byte [indos], 0
        jne     .pas
.top:   call    mt_hot
        cli
        cmp     byte [cs:mt_swreq], 0FFh ; (a task asked for: on the way out
        je      .f                      ;  of this INT 21h call, say, not only
        mov     byte [cs:mt_pend], 1    ;  at the turn's end)
.f:     test    byte [bp+I16_AH], 0EEh
        jnz     .pas
        mov     ax, ss                  ; whose?  The kernel's or MT's key wait
        cmp     ax, KSEG                ;  (on the kernel's stack, through a
        jne     .own                    ;  TSR's hook too, but not a pop-up's
        cmp     byte [cs:mt_idle], 0    ;  from the kernel's INT 28h), or the
        je      .k                      ;  program's own code (not a TSR's
.own:   mov     ax, [bp+4]              ;  hook's, the ROM's, the frame's)?
        call    mt_mine
        jc      .pas
        lea     bx, [bp+8]              ; where it may be switched from?
        mov     [cs:mt_lsp], bx
        mov     bx, [bp+2]
        mov     dx, [bp+6]
        test    byte [bp+I16_AH], 1
        jz      .rd
        cmp     byte [cs:mt_pend], 0    ; a peek: another task's turn due (its
        je      .k                      ;  turn over, a task asked for in front),
        call    mt_safe                 ;  as on INT 21h's way out (a program
        jc      .k                      ;  that only polls, a tick seldom finds
        call    mt_preempt              ;  at a safe point); then none in the
.pk:    jmp     short .k                ;  background
.rd:    call    mt_safe                 ; a read
        jc      .pas
        call    mt_swkw
        mov     al, [cs:mt_cur]         ; in the background it waits; in front
        cmp     al, [cs:mt_front]       ;  only with nothing typed (a peek of
        jne     .w                      ;  its kind: the BIOS drops what that
        mov     ah, [bp+I16_AH]         ;  read would skip)
        inc     ah
        pushf
        call    far [cs:mt_old16]
        cli
        jnz     .pas                    ; (one: the BIOS's read has it at once)
.w:     call    mt_wkey
.wk:    jnc     .top
        sti                             ; (no other task ready: until the
        hlt                             ;  next interrupt)
        jmp     .top
.k:     mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        je      .pas
        test    byte [bp+I16_AH], 1
        jz      .pas
        or      word [bp+6], 0240h      ; (ZF: no key; interrupts on, as the
        jmp     short .ret              ;  BIOS returns)
.pas:   pop     dx
        pop     bx
        pop     ax
        pop     ds
        pop     bp
        jmp     far [cs:mt_old16]
.ret:   pop     dx
        pop     bx
        pop     ax
        pop     ds
        pop     bp
        iret

; the running task waits for a key (from mt_i16, where the caller is at a
; safe point): TS_WAITK, while the next ready task runs (mt_kwant and
; mt_preempt bring the front one back when one is typed), or in the
; background the front one if none is.  CF, nothing done, if it is in front
; and no other is ready; else back, CF clear, when it runs again
mt_wkey:
        call    mt_fdrain               ; (first: nothing saved or chosen yet)
        call    mt_pick
        jnc     .go
        mov     bl, [cs:mt_front]
        cmp     bl, [cs:mt_cur]
        stc
        je      .x
.go:    push    bx
        mov     al, [cs:mt_cur]
        call    mt_ent
        mov     byte [cs:bx+TE_STATE], TS_WAITK
        pop     bx
        call    mt_switch
.sw:    clc
.x:     ret

; task AL to the front: the front one's screen kept, AL's shown; a DOS
; program's INT 33h pointer off meanwhile (as RCON does), and each one's
; INT 33h state its own (M4c)
mt_scrto:
        cmp     al, [cs:mt_front]
        je      .x
        call    mt_m33bz                ; (no event handler meanwhile)
        call    mt_33hk
        push    ax
        mov     al, [cs:mt_front]       ; its INT 33h state kept, then its
        call    mt_m33to                ;  pointer off
        mov     ax, 2
        call    mt_m33
        mov     al, [cs:mt_front]
        call    mt_scrsv
        pop     ax
        push    ax
        call    mt_scrld
        call    mt_m33on                ; (another driver's: back on)
        pop     ax
        call    mt_m33ld                ; AL's state, its pointer as it says
        jmp     mt_m33nb
.x:     ret

; INT 33h function AX, if there is an INT 33h (MT's own: mt_i33 lets it
; through).  All kept
mt_m33: pusha
        push    ds
        push    es
        xor     bx, bx
        mov     ds, bx
        mov     bx, [33h * 4]
        or      bx, [33h * 4 + 2]
        jz      .x
        inc     byte [cs:mt_in33]
        int     33h
        dec     byte [cs:mt_in33]
.x:     pop     es
        pop     ds
        popa
        ret

; ---------------------------------------------------------------------
;  INT 33h (M4c): each task its own mouse.  The UI's driver keeps one
;  state (m33_st: where the pointer is, its ranges, counts, shape, the
;  event handler); it is the front task's, which the mouse moves and
;  whose pointer is drawn.  The others' are in their TXs (TX_M33), and a
;  change of the front swaps them (mt_scrto).  A background task's own
;  call is done on its own state, swapped in for it, with the pointer on
;  the real screen left as it is: the driver draws in no mode meanwhile
;  (40:49h 0FFh; for a reset, the task's own mode, for its ranges), its
;  drawn pointer is taken as none (m33_dn), and no event handler runs
;  (m33_busy, which also keeps the tick from switching).  As they are:
;  MT's own calls (mt_in33), the front task's, a call made with an
;  interrupt in service or by an event handler (m33_busy: the front
;  task's, whichever task it lands in), inside MT's call to the BIOS, an
;  INT 13h call, a change of the front or a critical error's prompt, and
;  a call that isn't from the task's own code (a TSR's: mt_mine)
; ---------------------------------------------------------------------
mt_i33: cli
        push    bp
        mov     bp, sp
        push    ds
        push    ax
        push    bx
        push    dx
        push    KSEG
        pop     ds
        mov     ax, [ui_seg]            ; (the UI's driver where the UI is
        mov     [cs:mt_old33 + 2], ax   ;  now: its block can move)
        cmp     byte [cs:mt_in33], 0
        jne     .pas
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        je      .pas
        call    mt_isr
        jnz     .pas
        cmp     byte [cs:mt_inb], 0
        jne     .pas
        cmp     word [cs:mt_in13], 0
        jne     .pas
        cmp     byte [cs:mt_crit], 0    ; (a count left by a handler that never
        je      .b                      ;  came back: not inside INT 21h now)
        cmp     byte [indos], 0
        jne     .pas
.b:     push    es
        mov     es, [ui_seg]
        cmp     byte [es:m33_busy], 0
        pop     es
        jne     .pas
        mov     ax, [bp+4]              ; (the caller's CS)
        call    mt_mine
        jnc     .bg
.pas:   pop     dx
        pop     bx
        pop     ax
        pop     ds
        pop     bp
        jmp     far [cs:mt_old33]
.bg:    pop     dx
        pop     bx
        pop     ax
        pop     ds
        pop     bp
        push    ds
        push    es
        pusha
        call    mt_33in                 ; (AX: the function)
        popa
        pop     es
        pop     ds
        pushf                           ; the call, with its registers
        call    far [cs:mt_old33]
        push    ds
        push    es
        pusha
        call    mt_33out
        popa
        pop     es
        pop     ds
        iret

; mt_i33's swap in (AX = the function; interrupts off): the front task's
; state to its TX, the background task's in its place; the pointer drawn
; on the real screen, the events pending and m33_busy kept aside.  All but
; the segment registers changed
mt_33in:
        mov     dx, ax
        push    KSEG
        pop     ds
        mov     es, [ui_seg]
        mov     al, [cs:mt_front]
        call    mt_m33sv
        mov     ax, [es:m33_dn]         ; (and m33_dmode)
        mov     [cs:mt_33dn], ax
        mov     byte [es:m33_dn], 0
        mov     al, [es:m33_ev]
        mov     ah, [es:m33_busy]
        mov     [cs:mt_33eb], ax
        mov     byte [es:m33_busy], 1
        mov     al, [cs:mt_cur]
        call    mt_ent
        push    ds
        mov     ds, [cs:bx+TE_TX]
        mov     si, TX_M33
        mov     di, m33_st
        mov     cx, M33_ST / 2
        cld
        rep     movsw
        mov     byte [cs:mt_33pk], 0
        or      dx, dx                  ; a reset: its pointer taken as off
        jz      .rst                    ;  (mouse_on turns interrupts on: a
        cmp     dx, 21h                 ;  packet then draws none), its
        je      .rst                    ;  ranges from its own mode
        cmp     dx, 0Ch                 ; 0Ch, 14h: interrupts on in the
        je      .msk                    ;  driver (INT 21h AH=62h): no packet
        cmp     dx, 14h                 ;  meanwhile, and 40:49h left as it
        je      .msk                    ;  is
        mov     al, 0FFh                ; the rest, with interrupts off: the
        jmp     short .m                ;  driver draws in no mode
.rst:   mov     word [es:m33_cnt], -1
        mov     al, [TX_VID]            ; (40:49h)
.m:     push    40h
        pop     ds
        xchg    al, [49h]
        mov     [cs:mt_33md], al
        pop     ds
        ret
.msk:   cmp     word [es:mfound], 0     ; (no mouse: no packets either, and
        jne     .k                      ;  40:49h kept as it is, through .m,
        push    40h                     ;  for mt_33out)
        pop     ds
        mov     al, [49h]
        jmp     short .m
.k:     pop     ds
        mov     cl, [es:mirq]
        mov     ah, 1
        shl     ah, cl
        in      al, 21h
        mov     [cs:mt_33pm], al
        or      al, ah
        out     21h, al
        mov     [cs:mt_33pk], ah
.x:     ret

; mt_i33's swap out: the background task's state back to its TX, the
; front one's in its place, as it was
mt_33out:
        cli
        push    KSEG
        pop     ds
        mov     es, [ui_seg]
        mov     ah, [cs:mt_33pk]        ; 0Ch, 14h: the mouse's IRQ unmasked,
        or      ah, ah                  ;  if it was (else as the call left
        jz      .md                     ;  it); a packet that came meanwhile
        test    [cs:mt_33pm], ah        ;  is the front task's, after this
        jnz     .cp
        in      al, 21h
        not     ah
        and     al, ah
        out     21h, al
        jmp     short .cp
.md:    push    ds
        push    40h
        pop     ds
        mov     al, [cs:mt_33md]
        mov     [49h], al
        pop     ds
.cp:    mov     al, [cs:mt_cur]
        call    mt_m33sv
        mov     al, [cs:mt_front]
        call    mt_ent
        push    ds
        mov     ds, [cs:bx+TE_TX]
        mov     si, TX_M33
        mov     di, m33_st
        mov     cx, M33_ST / 2
        cld
        rep     movsw
        pop     ds
        mov     ax, [cs:mt_33dn]
        mov     [es:m33_dn], ax
        mov     ax, [cs:mt_33eb]
        mov     [es:m33_ev], al
        mov     [es:m33_busy], ah
        ret

; the driver's state (ES = the UI's segment) to task AL's TX.  AX, BX, CX,
; SI, DI changed
mt_m33sv:
        call    mt_ent
        push    ds
        push    es
        push    es
        pop     ds
        mov     es, [cs:bx+TE_TX]
        mov     si, m33_st
        mov     di, TX_M33
        mov     cx, M33_ST / 2
        cld
        rep     movsw
        pop     es
        pop     ds
        ret

; m33_busy set while the front changes (mt_scrto): no event handler runs
; meanwhile, whose calls would act on the state being swapped (and the
; tick doesn't switch); mt_m33nb gives it back as it was.  All kept
mt_m33bz:
        push    ax
        push    ds
        push    es
        push    KSEG
        pop     ds
        mov     ax, [ui_seg]
        or      ax, ax
        jz      .x
        mov     es, ax
        mov     al, 1
        xchg    al, [es:m33_busy]
        mov     [cs:mt_33sb], al
.x:     pop     es
        pop     ds
        pop     ax
        ret
mt_m33nb:
        push    ax
        push    ds
        push    es
        push    KSEG
        pop     ds
        mov     ax, [ui_seg]
        or      ax, ax
        jz      .x
        mov     es, ax
        mov     al, [cs:mt_33sb]
        mov     [es:m33_busy], al
.x:     pop     es
        pop     ds
        pop     ax
        ret

; after a change of the front: the pointer back on through INT 33h (AX=1,
; after mt_scrto's AX=2) when INT 33h is another driver, or a program's
; hook in front: its show count as it was.  With the UI's driver, or MT's
; hook over it, mt_m33ld's 17h does that (the count exactly).  Whether
; the UI's driver answered (its show count moved: a hook) or another one
; did, in mt_33ot for mt_m33ld.  All kept
mt_m33on:
        mov     byte [cs:mt_33ot], 0
        call    mt_m33us
        je      .x
        pusha
        push    ds
        push    es
        push    KSEG
        pop     ds
        mov     cx, [ui_seg]
        pushf                           ; (no interrupt's own call between)
        cli
        jcxz    .on                     ; (no UI: none to tell apart)
        mov     es, cx
        mov     dx, [es:m33_cnt]
.on:    mov     ax, 1
        call    mt_m33
        jcxz    .p
        cmp     dx, [es:m33_cnt]        ; (after the change's AX=2, the UI's
        jne     .p                      ;  count is below 0, so AX=1 moves it;
        mov     byte [cs:mt_33ot], 1    ;  not so in mt_end inside a change)
.p:     popf
        pop     es
        pop     ds
        popa
.x:     ret

; ZF set if INT 33h is the UI's driver, or MT's hook over it.  All kept
; but the flags
mt_m33us:
        push    ax
        push    ds
        push    es
        push    KSEG
        pop     ds
        xor     ax, ax
        mov     es, ax
        cmp     word [es:33h * 4], mt_i33
        jne     .u
        mov     ax, cs
        cmp     [es:33h * 4 + 2], ax
        je      .x
.u:     cmp     word [es:33h * 4], int33_ui
        jne     .x
        mov     ax, [ui_seg]
        cmp     [es:33h * 4 + 2], ax
.x:     pop     es
        pop     ds
        pop     ax
        ret

; the driver's state to task AL's TX (none without the UI).  All kept
mt_m33to:
        pusha
        push    ds
        push    es
        push    KSEG
        pop     ds
        mov     cx, [ui_seg]
        jcxz    .x
        mov     es, cx
        pushf
        cli
        call    mt_m33sv
        popf
.x:     pop     es
        pop     ds
        popa
        ret

; task AL's state to the driver, by its own function 17h (the pointer
; taken away, the state copied in, the pointer drawn as it says), called
; directly: the UI's driver, whose state it is.  With another driver on
; INT 33h (mt_m33on, just before, found the UI's not answering), drawn in
; no mode (40:49h 0FFh meanwhile): that one's pointer is the one shown.
; All kept
mt_m33ld:
        pusha
        push    ds
        push    es
        push    KSEG
        pop     ds
        mov     cx, [ui_seg]
        jcxz    .x
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        mov     dx, TX_M33
        pushf
        cli
        mov     bl, 0FFh
        cmp     byte [cs:mt_33ot], 0
        jne     .md
        push    40h                     ; (ours: 40:49h as it is)
        pop     ds
        mov     bl, [49h]
.md:    push    40h
        pop     ds
        xchg    bl, [49h]
        push    bx
        mov     ax, 17h
        pushf                           ; (as INT 33h: its IRET to .r)
        push    cs
        push    .r
        push    cx
        push    int33_ui
        retf
.r:     cli
        pop     bx
        push    40h
        pop     ds
        mov     [49h], bl
        popf
.x:     pop     es
        pop     ds
        popa
        ret

; a new task's INT 33h state (ES = its TX; DS = KSEG): the driver's now,
; the pointer off and no event handler, until its program resets it.
; All kept
mt_m33new:
        pusha
        push    ds
        mov     cx, [ui_seg]
        jcxz    .x
        mov     ds, cx
        pushf
        cli
        mov     si, m33_st
        mov     di, TX_M33
        mov     cx, M33_ST / 2
        cld
        rep     movsw
        popf
        mov     word [es:TX_M33 + m33_cnt - m33_st], -1
        xor     ax, ax
        mov     [es:TX_M33 + m33_mx - m33_st], ax       ; (no counts: the
        mov     [es:TX_M33 + m33_my - m33_st], ax       ;  front task's)
        mov     di, TX_M33 + m33_np - m33_st
        mov     cx, (m33_rly + 4 - m33_np) / 2
        rep     stosw
        mov     [es:TX_M33 + m33_hmask - m33_st], ax
        mov     [es:TX_M33 + m33_hoff - m33_st], ax
        mov     [es:TX_M33 + m33_hseg - m33_st], ax
        mov     [es:TX_M33 + m33_hpsp - m33_st], ax
.x:     pop     ds
        popa
        ret

; INT 33h through mt_i33, if the UI has set it to its driver (at its
; start; again at the root's restart).  One put there since, a program's,
; is left alone.  All kept
mt_33hk:
        push    ax
        push    ds
        push    es
        push    KSEG
        pop     ds
        mov     ax, [ui_seg]
        or      ax, ax
        jz      .x
        push    0
        pop     es
        pushf
        cli
        cmp     word [es:33h * 4], int33_ui
        jne     .p
        cmp     [es:33h * 4 + 2], ax
        jne     .p
        mov     word [cs:mt_old33], int33_ui
        mov     [cs:mt_old33 + 2], ax
        mov     word [es:33h * 4], mt_i33
        mov     [es:33h * 4 + 2], cs
        pusha                           ; the front task's state, the driver's
        mov     es, ax                  ;  now, kept in its TX: the first time
        mov     al, [cs:mt_front]       ;  (task 0's), it may be loaded before
        call    mt_m33sv                ;  a change of the front saved it
        popa
.p:     popf
.x:     pop     es
        pop     ds
        pop     ax
        ret

; KPROC's ui_progend (its first 5 bytes: MOV AX,[ui_seg] / OR AX,AX):
; the program at BX ends.  In a background task its event handler, if it
; is that program's, is forgotten in the task's own state, as the driver's
; m33_gone does for the front task's (a shell's next program can be
; loaded at the same segment).  Then on, past those bytes (DS = KSEG)
mt_pgend:
        push    ax
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        je      .k
        push    bx
        push    es
        push    bx
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        pop     bx
        cmp     [es:TX_M33 + m33_hpsp - m33_st], bx
        jne     .n
        xor     ax, ax
        mov     [es:TX_M33 + m33_hmask - m33_st], ax
        mov     [es:TX_M33 + m33_hseg - m33_st], ax
        mov     [es:TX_M33 + m33_hpsp - m33_st], ax
.n:     cmp     byte [cs:mt_cur], 0     ; the program the UI ran (the root's
        jne     .e                      ;  child), in task 0: its pointer off
        mov     ax, [root_psp]          ;  there, as the UI's m33_end will do,
        push    es                      ;  but to the front task's state
        mov     es, bx
        cmp     [es:16h], ax
        pop     es
        jne     .e
        mov     word [es:TX_M33 + m33_cnt - m33_st], -1
.e:     pop     es
        pop     bx
.k:     pop     ax
        mov     ax, [ui_seg]
        or      ax, ax
        jmp     KSEG:ui_progend + 5

; the screen (B800:0000, 32 KB: any mode) and its BIOS data to task AL's
; pages and TX (with none, nothing; with its pages gone, say a program
; freed the handle, none from now on).  First, whether it wrote the
; screen itself while in front (VF_DIRECT: frozen in the background): in
; a graphics mode, yes; shadowed (mt_shd), if B800h's first 16 KB differ
; from its pages'; else not known, so no.  All kept but the flags
mt_scrsv:
        pusha
        push    ds
        push    es
        cld
        mov     byte [cs:mt_vbusy], 1
        mov     byte [cs:mt_vlost], 0
        call    mt_ent
        and     byte [cs:bx+TE_VF], ~VF_DIRECT
        call    mt_smap
        jc      .gone
        mov     byte [cs:bx+TE_SF], 1
        push    40h
        pop     ds
        cmp     byte [49h], 4
        jae     .dir
        cmp     byte [cs:mt_shd], 0
        je      .nk
        push    0B800h
        pop     ds
        push    EMS_FRAME
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 2000h
        repe    cmpsw
        je      .cl
        cmp     byte [cs:mt_vlost], 0   ; (an interrupt's call meanwhile, not
        je      .dir                    ;  shadowed: not known)
.nk:    cmp     byte [cs:mt_mid], 0     ; not known: at a key wait, as it is;
        je      .cl                     ;  switched from in the middle of its
        cmp     byte [cs:bx+TE_STATE], TS_WAITK ;  run (not waiting for a key),
        je      .cl                     ;  it may be writing the screen: frozen
.dir:   or      byte [cs:bx+TE_VF], VF_DIRECT   ;  behind, to be safe
.cl:    mov     byte [cs:mt_shd], 0
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
.x:     mov     byte [cs:mt_vbusy], 0
        pop     es
        pop     ds
        popa
        ret
.gone:  mov     word [cs:bx+TE_SH], 0   ; (TE_SH, TE_SF: none kept, nor freed at
        mov     byte [cs:mt_shd], 0     ;  its end: the number may be someone
        jmp     .x                      ;  else's now)

; task AL's screen shown, and AL in front (a task waiting to be: ready
; now): its mode, 3D9h (CGA's modes, before the screen, as RCON does), the
; screen, its BIOS data; in text modes, the page shown and the cursor, and
; its INT 10h calls shadowed from here if another task is there.  Never
; kept (or none kept): mode 3, clear.  The BIOS's INT 10h, not mt_v10's.
; All kept but the flags
mt_scrld:
        pusha
        push    ds
        push    es
        cld
        call    mt_fvto                 ; (its INT 09h and 1Bh)
        mov     byte [cs:mt_vbusy], 1
        mov     byte [cs:mt_vlost], 0
        mov     [cs:mt_front], al
        mov     byte [cs:mt_shd], 0
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITF
        jne     .nw
        mov     byte [cs:bx+TE_STATE], TS_RUN
.nw:    cmp     byte [cs:bx+TE_SF], 0
        je      .clr
        call    mt_smap
        jnc     .k
        mov     word [cs:bx+TE_SH], 0   ; (gone: none from now on)
.clr:   mov     ax, 0003h
        VCALL
        jmp     .x
.k:     mov     ds, [cs:bx+TE_TX]
        mov     al, [TX_VID]            ; (40:49h)
        xor     ah, ah
        push    ax
        push    bx
        VCALL
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
        VCALL
        mov     cx, [60h]               ; the cursor: its shape, and where it
        mov     ah, 1                   ;  is on that page
        VCALL
        mov     bh, [62h]
        mov     bl, bh
        xor     bh, bh
        shl     bx, 1
        mov     dx, [50h + bx]
        mov     bh, [62h]
        mov     ah, 2
        VCALL
        call    mt_others               ; (alone: nothing to shadow for)
        jc      .x
        mov     byte [cs:mt_shd], 1     ; (but an interrupt's call meanwhile,
        cmp     byte [cs:mt_vlost], 0   ;  not shadowed: not in step; one from
        je      .x                      ;  here on finds mt_vbusy, and clears
        mov     byte [cs:mt_shd], 0     ;  it itself)
.x:     mov     byte [cs:mt_vbusy], 0
        pop     es
        pop     ds
        popa
        ret

; another task there now: the front one's INT 10h calls shadowed from
; here, if it is in a text mode (its pages given B800h's first 16 KB).
; All kept but the flags
mt_sync:
        cmp     byte [cs:mt_shd], 0
        jne     .x
        pusha
        push    ds
        push    es
        cld
        mov     ax, 2                   ; (a DOS program's INT 33h pointer off
        call    mt_m33                  ;  meanwhile, not copied)
        mov     byte [cs:mt_vbusy], 1
        mov     byte [cs:mt_vlost], 0
        push    40h
        pop     ds
        cmp     byte [49h], 4
        jae     .r
        mov     al, [cs:mt_front]
        call    mt_ent
        call    mt_smap
        jc      .r
        push    0B800h
        pop     ds
        push    EMS_FRAME
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 2000h
        rep     movsw
        call    mt_wrest
        mov     byte [cs:mt_shd], 1     ; (as in mt_scrld)
        cmp     byte [cs:mt_vlost], 0
        je      .r
        mov     byte [cs:mt_shd], 0
.r:     mov     byte [cs:mt_vbusy], 0
        mov     ax, 1
        call    mt_m33
        pop     es
        pop     ds
        popa
.x:     ret

; CF if there is no task but the Executive's.  All kept
mt_others:
        push    ax
        push    bx
        mov     al, 1
.l:     call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        jne     .y
        inc     al
        cmp     al, MT_TASKS
        jb      .l
        stc
        jmp     short .x
.y:     clc
.x:     pop     bx
        pop     ax
        ret

; windows 0 and 1: mt_smap shows the 2 pages of the entry at BX in them,
; as INT 67h AH=44h would (KEMS's tables: the handle's run in ems_ltab),
; keeping their page registers first in mt_wsv; mt_wrest puts those back.
; CF if its pages are gone (none; a handle closed, which has no pages; or
; not MT's: 2 pages, owner 0, a program's has its PSP), nothing changed.
; mt_smap changes the flags; mt_wrest AL, DX and the flags
mt_smap:
        push    ds
        push    si
        push    ax
        push    dx
        xor     ax, ax
        mov     al, [cs:bx+TE_SH]
        or      al, al
        jz      .no
        mov     si, ax
        shl     si, 2
        push    KSEG
        pop     ds
        mov     dx, [ems_h + si + 2]    ; (owner 0, 2 pages)
        or      dl, dh
        mov     dh, [ems_h + si + 1]
        xor     dh, 2
        or      dl, dh
        jnz     .no
        mov     al, [ems_h + si]        ; (its run's start)
        mov     si, ax
        mov     dx, EMS_PORT
        in      al, dx
        mov     [cs:mt_wsv], al
        mov     al, [ems_ltab + si]
        out     dx, al
        add     dh, 40h
        in      al, dx
        mov     [cs:mt_wsv + 1], al
        mov     al, [ems_ltab + si + 1]
        out     dx, al
        clc
.x:     pop     dx
        pop     ax
        pop     si
        pop     ds
        ret
.no:    stc
        jmp     .x
mt_wrest:
        mov     dx, EMS_PORT
        mov     al, [cs:mt_wsv]
        out     dx, al
        add     dh, 40h
        mov     al, [cs:mt_wsv + 1]
        out     dx, al
        ret

; ---------------------------------------------------------------------
;  INT 10h (M4a).  A background task's calls are done in its own screen
;  (its 2 EMS pages, and its BIOS data, in its TX) as the 1520's BIOS
;  does them (int10.asm), so its output never reaches the screen in front.
;  A graphics mode or a pixel asked for there: it waits to be in front
;  (TS_WAITF), if it is at a safe point (else the call is dropped).  The
;  front task's calls go to the BIOS, the ones that write the screen done
;  in its pages too while another task is there (mt_shd), so that at the
;  switch away (mt_scrsv) the screen can be compared with them.  As they
;  are, to the BIOS: calls from the BIOS itself (the 1520's teletype calls
;  INT 10h again), the ROM or the EMS frame (Resident Claude), and any
;  inside an INT 13h call (mt_in13: taken as an interrupt's; no window
;  mapped while a floppy's DMA may be going into the frame); and a
;  background task's with SPF_BG, made with a hardware interrupt in
;  service (a TSR's clock: on the real screen, as in DOS), or made while
;  the kernel's INT 24h runs (mt_crit: its prompt, whoever prints it);
;  these last, on the real screen, are shadowed as the front task's own
; ---------------------------------------------------------------------
VF_AX       equ -2                      ; (the caller's registers, PUSHA's,
VF_CX       equ -4                      ;  from mt_v10's BP; the caller's own
VF_DX       equ -6                      ;  BP at [BP], then its IP, CS, flags)
VF_BX       equ -8
VF_ES       equ -20
mt_v10:
        cli                             ; (a hook's PUSHF / CALL FAR: interrupts
        push    bp                      ;  on; the IRET puts the caller's back)
        mov     bp, sp
        cmp     word [bp+4], 0A000h
        jae     .rom
        cmp     word [cs:mt_vbusy], 0   ; (mt_vbusy, mt_inb: one test)
        jne     .busy
.top:   push    ax
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        pop     ax
        jne     .bg
.fr:    cmp     byte [cs:mt_shd], 0     ; in front: shadowed (a mode set may
        jne     .sh                     ;  start it)
        or      ah, ah
        jz      .sh
.bios:  pop     bp
        jmp     far [cs:mt_old10]
.rom:   cmp     byte [cs:mt_inb], 0     ; from A000h up: inside a call MT
        jne     .inb                    ;  passed on to the BIOS, the BIOS's
        cmp     byte [cs:mt_vbusy], 0   ;  own; else a ROM's or the EMS frame's
        jne     .lose                   ;  (Resident Claude's console), as it
        cmp     byte [cs:mt_shd], 0     ;  is, not shadowed (nothing lost if
        je      .bios                   ;  nothing was)
        jmp     short .lose
.busy:  cmp     byte [cs:mt_inb], 0     ; inside a call MT passed on to the
        je      .lose                   ;  BIOS: the BIOS's own (through a hook
.inb:   push    ax                      ;  loaded after MT, say), unless an
        call    mt_isr                  ;  interrupt came in meanwhile (one in
        mov     al, [cs:mt_isr0]        ;  service now that wasn't then): not
        not     al                      ;  shadowed.  Else an interrupt's
        and     ah, al                  ;  inside MT's own use of the pages:
        pop     ax                      ;  not shadowed
        jz      .bios
.lose:  call    mt_vlose
        jmp     .bios
.sh:    pusha
        push    ds
        push    es
        cld
        mov     ax, ss                  ; (a stack in the EMS frame's windows 0
        sub     ax, EMS_FRAME           ;  and 1, where the pages are mapped:
        cmp     ax, 800h                ;  as it is, to the BIOS, not shadowed)
        jb      .lost
        cmp     byte [cs:mt_in13], 0    ; inside an INT 13h call (so an
        jne     .lost                   ;  interrupt's): its DMA may be going
        mov     ax, [bp+VF_AX]          ;  into the frame's windows: none mapped
        cmp     ah, 0Eh                 ; the teletype, not at a line's end
        jne     .sg                     ;  (most output): the short way
        mov     bl, [cs:mt_front]       ; (BX: its entry, as mt_ent gives it)
        xor     bh, bh
        shl     bx, 5
        add     bx, mt_tab
        push    40h
        pop     ds
        mov     si, 49h
        xor     cl, cl                  ; (the BIOS moves the cursor itself)
        call    mt_vfast
        jnc     .pass
.sg:    mov     ax, [bp+VF_AX]
        call    mt_vshad
.pass:  pop     es                      ; (to the BIOS as MT's own: its nested
        pop     ds                      ;  calls not shadowed again, whatever
        popa                            ;  hook they come through; mt_vcall's
        pop     bp                      ;  way, inline, interrupts off already)
        push    ax
        mov     al, 0Bh
        out     20h, al
        in      al, 20h
        mov     [cs:mt_isr0], al
        mov     al, 0Ah
        out     20h, al
        pop     ax
        inc     byte [cs:mt_inb]
        pushf
        call    far [cs:mt_old10]
        dec     byte [cs:mt_inb]
        iret
.lost:  call    mt_vlose
        pop     es
        pop     ds
        popa
        jmp     .bios
.real:  pop     es                      ; (a background task's call for the
        pop     ds                      ;  real screen: the BIOS's, shadowed
        popa                            ;  as the front task's would be)
        jmp     .fr
.bg:    pusha
        push    ds
        push    es
        cld
        mov     ax, ss                  ; (the same, and the same for a call
        sub     ax, EMS_FRAME           ;  inside INT 13h: to the real screen)
        cmp     ax, 800h
        jb      .lost
        cmp     byte [cs:mt_in13], 0
        jne     .lost
        mov     al, [cs:mt_cur]
        call    mt_ent
        test    byte [cs:bx+TE_VF], SPF_BG
        jnz     .real
        push    KSEG                    ; a critical error's prompt (inside the
        pop     ds                      ;  kernel's INT 24h: everything waits
        cmp     byte [cs:mt_crit], 0    ;  for its answer): on the real screen
        je      .k                      ;  (a count left by a handler that never
        cmp     byte [indos], 0         ;  came back: not inside INT 21h now).
        jne     .real                   ;  Else inside INT 21h too the task's,
.k:     call    mt_isr                  ;  whatever hook it comes through.  A
                                        ;  hardware interrupt in service, or an
        jnz     .real                   ;  INT 33h event handler running: on the
        mov     es, [ui_seg]            ;  real screen
        cmp     byte [es:m33_busy], 0
        jne     .real
        cmp     byte [bp+VF_AX+1], 0Eh  ; the teletype, not at a line's end:
        jne     .bl                     ;  the short way
        mov     ds, [cs:bx+TE_TX]
        mov     si, TX_VID
        mov     cl, 1
        call    mt_vfast
        jnc     .ret
.bl:    push    cs                      ; its BIOS data, worked on in mt_vs
        pop     es
        mov     ds, [cs:bx+TE_TX]
        mov     si, TX_VID
        mov     di, mt_vs
        mov     cx, VIDLEN
        rep     movsb
        call    mt_smap                 ; its screen (its pages gone: the call
        jc      .ret                    ;  goes nowhere)
        push    cs
        pop     ds
        push    EMS_FRAME
        pop     es
        push    bx
        call    mt_emu
        pop     bx
        pushf
        call    mt_wrest
        popf
        jc      .blk
        mov     es, [cs:bx+TE_TX]
        mov     si, mt_vs
        mov     di, TX_VID
        mov     cx, VIDLEN
        rep     movsb
.ret:   pop     es
        pop     ds
        popa
        pop     bp
        iret
.blk:   push    KSEG                    ; it waits to be in front, if it is at
        pop     ds                      ;  a safe point (the caller), then all
        lea     ax, [bp+8]              ;  again
        mov     [cs:mt_lsp], ax
        mov     ax, [bp+4]
        mov     bx, [bp+2]
        mov     dx, [bp+6]
        call    mt_safe
        jc      .dr
        call    mt_wfront
.wf:    cli
        pop     es
        pop     ds
        popa
        jmp     .top
.dr:    mov     al, [cs:mt_cur]         ; (dropped: it may go on to write the
        call    mt_ent                  ;  screen itself, so it is frozen behind
        or      byte [cs:bx+TE_VF], VF_DIRECT   ;  from its next safe point, as
        jmp     .ret                    ;  one that does)

; the teletype's character in mt_v10's frame (AL there) on the page shown,
; the cursor on a line of the screen, when it can't scroll: a character
; written (not at the line's last column) in the pages of the entry at BX
; as the BIOS writes it (not its attribute); BEL nothing; CR, BS, LF (not
; on the last line) only the cursor.  The cursor moved if CL is 1 (a
; background task's; the front one's BIOS moves its own).  The BIOS data
; at DS:SI (laid out from 40:49h on).  CF: not this way (a graphics mode,
; the line's end, the last line's LF, the pages gone), nothing done.  AX,
; DX, DI changed
mt_vfast:
        cmp     byte [si], 3            ; (a text mode)
        ja      .no
        push    bx
        mov     bl, [si + 62h - 49h]    ; the page shown (MT keeps the cursors of
        xor     bh, bh                  ;  pages 0-10: 40:50h to 40:65h)
        cmp     bl, 10
        ja      .nb
        mov     di, bx
        shl     di, 1
        add     di, si                  ; (its cursor at [DI + 50h - 49h])
        mov     dx, [di + 50h - 49h]
        cmp     dh, 24                  ; (below the screen: the long way)
        ja      .nb
        mov     al, [bp+VF_AX]
        cmp     al, 0Dh                 ; (most: above them all)
        ja      .ch
        je      .cr
        cmp     al, 0Ah
        je      .lf
        cmp     al, 8
        je      .bs
        cmp     al, 7
        je      .mv
.ch:    mov     al, [si + 4Ah - 49h]
        dec     al
        cmp     dl, al                  ; (its last column, or past it: the
        jae     .nb                     ;  long way: it may scroll)
        mov     ax, bx
        push    dx
        mul     word [si + 4Ch - 49h]
        pop     dx
        mov     bx, ax                  ; (the page's start)
        mov     al, dh
        mul     byte [si + 4Ah - 49h]
        add     al, dl
        adc     ah, 0
        shl     ax, 1
        add     ax, bx
        pop     bx
        cmp     ax, 8000h - 1
        jae     .no
        call    mt_smap
        jc      .no
        push    es
        push    di
        xchg    ax, di
        push    EMS_FRAME
        pop     es
        mov     al, [bp+VF_AX]
        stosb
        pop     di
        pop     es
        push    dx
        call    mt_wrest
        pop     dx
        inc     dx
        jmp     short .set
.cr:    xor     dl, dl
        jmp     short .mv
.lf:    cmp     dh, 24
        jae     .nb
        inc     dh
        jmp     short .mv
.bs:    sub     dl, 1
        jnb     .mv
        xor     dl, dl
.mv:    pop     bx
.set:   or      cl, cl
        jz      .y
        mov     [di + 50h - 49h], dx
.y:     clc
        ret
.nb:    pop     bx
.no:    stc
        ret

; the running task, in the background, waits to be in front (TS_WAITF;
; mt_scrld makes it TS_RUN): the next ready one runs, or the front one if
; it waits for a key.  (From mt_v10, where the caller is at a safe point:
; returns when this task runs again)
mt_wfront:
        call    mt_fdrain               ; (first: nothing saved or chosen yet)
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]       ; (brought to the front meanwhile, in
        je      .x                      ;  its handler: the call again, now
        call    mt_ent                  ;  the front one's)
        mov     byte [cs:bx+TE_STATE], TS_WAITF
        call    mt_pick
        jnc     .go
        mov     bl, [cs:mt_front]
.go:    jmp     mt_switch
.x:     ret

; a call not shadowed went to the screen: whether the front task writes it
; itself can't be known at its switch away (not frozen for it), and its
; shadow stops until it is in front again.  All kept
mt_vlose:
        mov     byte [cs:mt_shd], 0
        mov     byte [cs:mt_vlost], 1
        ret

; the PIC's in-service register -> AH; ZF if no interrupt is in service.
; AL changed
mt_isr: mov     al, 0Bh
        out     20h, al
        in      al, 20h
        mov     ah, al
        mov     al, 0Ah
        out     20h, al
        or      ah, ah
        ret

; INT 10h with the caller's registers, the BIOS's (not mt_v10's): MT's own
; call, marked (mt_inb) so the BIOS's nested calls are known whatever hook
; they come through, with the interrupts in service then (mt_isr0), so that
; one that comes in meanwhile is told from them.  What the BIOS gives back;
; the flags not kept
mt_vcall:
        push    ax
        pushf
        cli
        call    mt_isr
        mov     [cs:mt_isr0], ah
        popf
        pop     ax
        inc     byte [cs:mt_inb]
        pushf
        call    far [cs:mt_old10]
        dec     byte [cs:mt_inb]
        ret

; crit_disk.c24: the kernel's INT 24h (the critical error's prompt),
; counted while it runs (mt_crit): mt_v10 puts what it prints on the real
; screen, since everything waits for its answer
mt_c24: mov     si, crit_dev
        inc     byte [cs:mt_crit]
        int     24h
        dec     byte [cs:mt_crit]
        retf

; INT 13h: counted while it runs (mt_in13), so mt_v10 knows an INT 10h call
; meanwhile is an interrupt's, while a floppy's DMA may be going into the
; EMS frame: no window is mapped for it.  CF and the rest as the BIOS gives
; them back
mt_i13: inc     byte [cs:mt_in13]
        pushf
        call    far [cs:mt_old13]
        pushf
        dec     byte [cs:mt_in13]
        popf
        retf    2

; the front task's call, before the BIOS does it: one that writes the
; screen done in its pages too.  A mode set starts the shadow with a text
; mode (another task there), and ends it with a graphics one
mt_vshad:
        mov     al, [cs:mt_front]
        call    mt_ent
        mov     ax, [bp+VF_AX]
        or      ah, ah
        jnz     .w
        mov     byte [cs:mt_shd], 0
        call    mt_tmode
        jc      .x
        call    mt_others
        jc      .x
        jmp     short .go
.w:     cmp     ah, 6
        je      .go
        cmp     ah, 7
        je      .go
        cmp     ah, 9
        je      .go
        cmp     ah, 0Ah
        je      .go
        cmp     ah, 0Eh
        je      .go
        cmp     ah, 13h
        jne     .x
.go:    push    40h                     ; its BIOS data as it is now
        pop     ds
        push    cs
        pop     es
        mov     si, 49h
        mov     di, mt_vs
        mov     cx, VIDLEN
        rep     movsb
        call    mt_smap
        jc      .gone
        push    cs
        pop     ds
        push    EMS_FRAME
        pop     es
        push    word [bp+VF_AX]         ; (its registers to the BIOS as they
        call    mt_emu                  ;  were: 00h's AX)
        pop     word [bp+VF_AX]
        call    mt_wrest
        cmp     byte [bp+VF_AX+1], 0
        jne     .x
        mov     byte [cs:mt_shd], 1     ; (a text mode: in step from here)
.x:     ret
.gone:  mov     byte [cs:mt_shd], 0
        ret

; mode AL as the 1520's BIOS takes it: 0-3 text, 4-6, 40h, 48h, 74h
; graphics (CF), anything else mode 2 (AL = the text mode)
mt_tmode:
        cmp     al, 6
        jbe     .t
        cmp     al, 40h
        je      .g
        cmp     al, 48h
        je      .g
        cmp     al, 74h
        je      .g
        mov     al, 2
.t:     cmp     al, 4
        cmc
        ret
.g:     stc
        ret

; mt_v10's call (its frame at BP) done as the 1520's BIOS does it in a
; text mode, in the screen at ES:0 (32 KB) and the BIOS data in mt_vs,
; its results into the frame, the registers it changes as it changes them.
; Pages as the BIOS takes them, whole bytes; MT keeps the cursors of pages
; 0-10 (to 40:65h), and a call on a page past that does nothing.  Nothing
; written past the 32 KB.  CF: not here (a graphics mode, a pixel, or in a
; graphics mode now): it waits to be in front.  DS = CS; all changed but
; BP, DS, ES
mt_emu:
        mov     ax, [bp+VF_AX]
        or      ah, ah
        jz      .m0
        cmp     ah, 13h
        ja      .ok                     ; (none there: as the BIOS)
        cmp     byte [VS_MODE], 4
        jae     .wt
        mov     bl, ah
        xor     bh, bh
        shl     bx, 1
        jmp     [.tab + bx - 2]
.tab:   dw      .m1, .m2, .m3, .m4, .m5, .m6, .m7, .m8, .m9, .mA, .mB, .mC
        dw      .mC, .mE, .mF, .ok, .ok, .ok, .m13
.wt:    stc
        ret
.ok:    clc
        ret
; 00h: a text mode (VidSetMode): the BIOS data, the screen 16 KB of blanks;
; AX back as 00h and Mode Control
.m0:    call    mt_tmode
        jc      .wt
        mov     [VS_MODE], al
        xor     bh, bh
        mov     bl, al
        mov     al, [mt_vcols + bx]
        xor     ah, ah
        mov     [VS_COLS], ax
        mov     ax, 800h
        cmp     bl, 2
        jb      .ml
        shl     ax, 1
.ml:    mov     [VS_LEN], ax
        mov     al, [mt_vsel + bx]
        mov     [VS_MSEL], al
        xor     ah, ah
        mov     [bp+VF_AX], ax
        push    es
        push    ds
        pop     es
        mov     di, VS_START            ; (the page's start, the 8 cursors)
        xor     ax, ax
        mov     cx, 9
        rep     stosw
        pop     es
        mov     word [VS_SHAPE], 0607h
        mov     byte [VS_PAGE], 0
        mov     word [VS_PORT], 3D4h
        mov     byte [VS_PAL], 30h
        xor     di, di
        mov     ax, 0720h
        mov     cx, 2000h
        rep     stosw
        clc
        ret
; 01h: the cursor's shape
.m1:    mov     ax, [bp+VF_CX]
        mov     [VS_SHAPE], ax
        clc
        ret
; 02h, 03h: page BH's cursor
.m2:    call    .pg
        jc      .ok
        mov     ax, [bp+VF_DX]
        mov     [VS_CUR + bx], ax
        clc
        ret
.m3:    mov     ax, [VS_SHAPE]          ; (the shape, whatever the page)
        mov     [bp+VF_CX], ax
        call    .pg
        jc      .ok
        mov     ax, [VS_CUR + bx]
        mov     [bp+VF_DX], ax
        clc
        ret
; 04h: the light pen, not triggered
.m4:    mov     byte [bp+VF_AX+1], 0
        clc
        ret
; 05h: the page shown (only noted: the CRTC is the front task's); AX back
; as 0, as the BIOS's multiplying leaves it
.m5:    mov     [VS_PAGE], al
        xor     ah, ah
        mul     word [VS_LEN]
        mov     [VS_START], ax
        mov     word [bp+VF_AX], 0
        clc
        ret
; 06h, 07h: a window scrolled up or down, on the page shown
.m6:    xor     bl, bl
        jmp     short .sc
.m7:    mov     bl, 1
.sc:    mov     bh, [bp+VF_BX+1]
        mov     cx, [bp+VF_CX]
        mov     dx, [bp+VF_DX]
        call    mt_vscr
        clc
        ret
; 08h: the character and attribute at page BH's cursor
.m8:    call    .pg
        jc      .ok
        mov     dx, [VS_CUR + bx]
        shr     bx, 1
        call    mt_vaddr
        mov     ax, 0FFFFh              ; (past the 32 KB: nothing there)
        cmp     di, 8000h - 1
        jae     .m8x
        mov     ax, [es:di]
.m8x:   mov     [bp+VF_AX], ax
        clc
        ret
; 09h (with BL's attribute), 0Ah: CX of AL from page BH's cursor on
.m9:    mov     dl, 1
        jmp     short .wc
.mA:    xor     dl, dl
.wc:    mov     cx, [bp+VF_CX]
        jcxz    .wz
        push    dx
        call    .pg
        jc      .wp
        mov     dx, [VS_CUR + bx]
        shr     bx, 1
        call    mt_vaddr
        pop     dx
        mov     al, [bp+VF_AX]
        mov     ah, [bp+VF_BX]
.wl:    cmp     di, 8000h - 1           ; (past the 32 KB: not written, but
        jae     .ws                     ;  on round 16 bits, as the BIOS's DI,
        stosb                           ;  to page 0)
        or      dl, dl
        jz      .wn
        mov     [es:di], ah
.wn:    inc     di
        loop    .wl
.wz:    clc
        ret
.ws:    inc     di
        jmp     short .wn
.wp:    pop     dx
        clc
        ret
; 0Bh: the colour select (put in 3D9h when the task is shown); AL back as
; the new one
.mB:    mov     al, [VS_PAL]
        mov     bx, [bp+VF_BX]
        or      bh, bh
        jnz     .pp
        and     al, 0E0h
        and     bl, 1Fh
        or      al, bl
        jmp     short .pw
.pp:    and     al, 0DFh
        test    bl, 1
        jz      .pw
        or      al, 20h
.pw:    mov     [VS_PAL], al
        mov     [bp+VF_AX], al
        clc
        ret
; 0Ch, 0Dh in a text mode: nothing (VidGrapPelMask's CF), AH back as the
; mode
.mC:    mov     al, [VS_MODE]
        mov     [bp+VF_AX+1], al
        clc
        ret
; 0Eh: the teletype, on the page shown whatever BH says
.mE:    mov     bl, [VS_PAGE]
        cmp     bl, 10
        ja      .ok
        xor     bh, bh
        mov     si, bx
        shl     si, 1
        mov     bh, bl
        mov     dx, [VS_CUR + si]
        mov     al, [bp+VF_AX]
        xor     cl, cl                  ; (the character only, as 0Ah)
        call    mt_vtty
        mov     [VS_CUR + si], dx
        clc
        ret
; 0Fh: the mode, its columns, the page shown
.mF:    mov     al, [VS_MODE]
        mov     ah, [VS_COLS]
        mov     [bp+VF_AX], ax
        mov     al, [VS_PAGE]
        mov     [bp+VF_BX+1], al
        clc
        ret
; 13h: CX characters from ES:BP on page BH from DX (AL bit 1: each with its
; attribute, but BEL, BS, LF and CR; bit 0: the cursor left after them),
; written with 09h as the teletype does (VidWriteString).  (A string in
; the EMS frame's windows 0 and 1, under the pages: not done)
.m13:   test    al, 0FCh
        jnz     .sz
        mov     cx, [bp+VF_CX]
        jcxz    .sz
        mov     ax, [bp+VF_ES]
        sub     ax, EMS_FRAME
        cmp     ax, 800h
        jb      .s13
        mov     dx, [bp+VF_DX]
        mov     bx, [bp+VF_BX]
        cmp     bh, 10
        ja      .sz
        mov     si, [bp]
.sl:    push    cx
        push    ds
        mov     ds, [bp+VF_ES]
        lodsb
        test    byte [bp+VF_AX], 2
        jz      .sw
        cmp     al, 7
        je      .sw
        cmp     al, 8
        je      .sw
        cmp     al, 0Ah
        je      .sw
        cmp     al, 0Dh
        je      .sw
        mov     bl, [si]
        inc     si
.sw:    pop     ds
        mov     cl, 1
        call    mt_vtty
        pop     cx
        loop    .sl
        test    byte [bp+VF_AX], 1
        jz      .sz
        mov     bl, bh
        xor     bh, bh
        shl     bx, 1
        mov     [VS_CUR + bx], dx
.sz:    clc
        ret
.s13:   call    mt_vlose                ; (the BIOS's alone, if in front)
        clc
        ret
; BX = 2 * the page in the caller's BH; CF if past page 10
.pg:    mov     bl, [bp+VF_BX+1]
        xor     bh, bh
        cmp     bl, 10
        ja      .pn
        shl     bx, 1
        clc
        ret
.pn:    stc
        ret

; the teletype's character AL at DX (row, column; page BH's cursor) on
; page BH, as VidTeletypeChar: BEL nothing (no beep in the background),
; CR, BS, LF; else written (CL 1: with BL's attribute, as 09h; 0: the
; character only, as 0Ah), the cursor on, to the next line at the end of
; one.  Past the last line: the page shown scrolled up a line, the new
; one in the attribute at the cell DX was.  -> DX.  All else kept
mt_vtty:
        push    ax
        push    bx
        push    cx
        push    di
        mov     [mt_vp0], dx
        cmp     al, 7
        je      .x
        cmp     al, 0Dh
        je      .cr
        cmp     al, 8
        jne     .nb
        sub     dl, 1
        jnb     .w
        jmp     short .cr
.nb:    cmp     al, 0Ah
        jne     .ch
        inc     dh
        jmp     short .w
.ch:    push    bx
        mov     bl, bh
        call    mt_vaddr
        pop     bx
        cmp     di, 8000h - 1
        jae     .nx
        stosb
        or      cl, cl
        jz      .nx
        mov     [es:di], bl
.nx:    inc     dx
        cmp     dl, [VS_COLS]
        jne     .w
        inc     dh
.cr:    xor     dl, dl
.w:     cmp     dh, 25
        jne     .x
        dec     dh
        push    dx
        mov     dx, [mt_vp0]
        mov     bl, bh
        call    mt_vaddr
        mov     bh, 7
        cmp     di, 8000h - 1
        jae     .sa
        mov     bh, [es:di+1]
.sa:    mov     al, 1
        xor     cx, cx
        mov     dh, 24
        mov     dl, [VS_COLS]
        dec     dx
        xor     bl, bl
        call    mt_vscr
        pop     dx
.x:     pop     di
        pop     cx
        pop     bx
        pop     ax
        ret

; DI = the offset of row DH, column DL on page BL (a text mode), as
; VidCalcOffsets works it out (16 bits).  All else kept
mt_vaddr:
        push    ax
        push    dx
        mov     al, bl
        xor     ah, ah
        mul     word [VS_LEN]
        mov     di, ax
        pop     dx
        mov     al, dh
        mul     byte [VS_COLS]
        add     al, dl
        adc     ah, 0
        shl     ax, 1
        add     di, ax
        pop     ax
        ret

; rows CH to DH, columns CL to DL of the page shown scrolled up (BL 0) or
; down (BL 1) by AL lines, the new ones in attribute BH, as VidWinScroll
; and VidScrollImpl do it: DH and DL kept on the screen, AL 0 or more
; lines than the window has blanking all of it, and their counts bytes,
; unchecked, so a window upside down or right to left after that runs on
; as on the 1520 (within the 32 KB).  A whole-width window the right way up
; (every teletype scroll) is moved at once.  All kept
mt_vscr:
        pusha
        mov     bp, sp                  ; ([BP+14], 12, 10, 8: AX, CX, DX, BX)
        call    .clamp
        cmp     ch, dh
        ja      .lit
        or      cl, cl
        jnz     .lit
        mov     ah, [VS_COLS]
        dec     ah
        cmp     dl, ah
        jne     .lit
        mov     ah, dh
        sub     ah, ch
        inc     ah                      ; (the rows)
        cmp     al, ah
        jb      .rn
        xor     al, al
.rn:    mov     [mt_vn], al
        mov     [mt_va], bh
        mov     [mt_vd], bl
        mov     al, ah
        mul     byte [VS_COLS]
        mov     si, ax                  ; (SI: the words in all the rows)
        mov     dh, ch
        xor     dl, dl
        mov     bl, [VS_PAGE]
        call    mt_vaddr                ; (DI: the top row's start)
        mov     ax, si
        shl     ax, 1
        add     ax, di
        jc      .lit
        cmp     ax, 8000h
        ja      .lit
        mov     cx, si
        mov     al, [mt_vn]
        mul     byte [VS_COLS]          ; (AX: the words AL lines hold)
        or      ax, ax
        jz      .fa
        sub     cx, ax                  ; (CX: the words moved, BX: blanked)
        mov     bx, ax
        shl     ax, 1
        push    ds
        push    es
        pop     ds
        cmp     byte [cs:mt_vd], 0
        jne     .fd
        mov     si, di                  ; up: from AL lines below, forward
        add     si, ax
        rep     movsw
        jmp     short .fb
.fd:    push    di                      ; down: from the last word, backward
        mov     si, cx
        shl     si, 1
        add     si, di
        dec     si
        dec     si
        mov     di, si
        add     di, ax
        std
        rep     movsw
        cld
        pop     di
.fb:    pop     ds
        mov     cx, bx
.fa:    mov     al, ' '
        mov     ah, [mt_va]
        rep     stosw
        jmp     .x
; the BIOS's own way, register for register
.lit:   mov     ax, [bp+14]
        mov     cx, [bp+12]
        mov     dx, [bp+10]
        mov     bx, [bp+8]
        call    .clamp
        mov     [mt_va], bh
        sub     dl, cl
        mov     ah, dh
        sub     ah, ch
        inc     dl
        mov     [mt_vw], dl             ; the width
        sub     ah, al
        jnb     .l1
        xor     al, al
.l1:    or      al, al
        jnz     .l2
        mov     ah, -1
.l2:    inc     ah
        mov     [mt_vn], al             ; the lines
        mov     [mt_vt], ah             ; the rows moved (0: 256)
        mov     ah, dh
        inc     ah
        sub     ah, ch
        sub     ah, [mt_vt]
        mov     [mt_vb], ah             ; the rows blanked (0: 256)
        or      bl, bl
        jnz     .ld
        mov     dh, ch                  ; (up: from the top row, down: the
.ld:    mov     dl, cl                  ;  bottom one)
        push    bx
        mov     bl, [VS_PAGE]
        call    mt_vaddr
        pop     bx
        mov     dx, [VS_COLS]
        shl     dx, 1                   ; (DX: a row on)
        mov     bp, dx
        xor     ch, ch
        mov     cl, [mt_vw]
        shl     cx, 1
        sub     bp, cx                  ; (BP: a row's end to the next one)
        or      bl, bl
        jz      .lu
        sub     bp, dx
        sub     bp, dx
        neg     dx
.lu:    mov     al, [mt_vn]
        or      al, al
        jz      .lf
        mov     si, di
.ls:    add     si, dx
        dec     al
        jnz     .ls
        mov     ah, [mt_vt]
.lc:    mov     cl, [mt_vw]
        xor     ch, ch
        call    mt_vmov
        add     si, bp
        add     di, bp
        dec     ah
        jnz     .lc
.lf:    mov     ah, [mt_vb]
.lb:    mov     cl, [mt_vw]
        xor     ch, ch
        call    mt_vset
        add     di, bp
        dec     ah
        jnz     .lb
.x:     popa
        ret
.clamp: cmp     dh, 25
        jb      .c1
        mov     dh, 24
.c1:    cmp     dl, [VS_COLS]
        jb      .c2
        mov     dl, [VS_COLS]
        dec     dl
.c2:    ret

; CX words from ES:SI to ES:DI, each only where both are in the 32 KB;
; SI, DI on past them.  All else kept
mt_vmov:
        jcxz    .x
        push    ax
        push    dx
        mov     ax, cx
        shl     ax, 1
        mov     dx, di
        add     dx, ax
        jc      .w
        cmp     dx, 8000h
        ja      .w
        mov     dx, si
        add     dx, ax
        jc      .w
        cmp     dx, 8000h
        ja      .w
        push    ds                      ; (all of it inside: at once)
        push    es
        pop     ds
        rep     movsw
        pop     ds
        jmp     short .y
.w:     cmp     di, 8000h - 1
        jae     .s
        cmp     si, 8000h - 1
        jae     .s
        mov     ax, [es:si]
        mov     [es:di], ax
.s:     inc     si
        inc     si
        inc     di
        inc     di
        loop    .w
.y:     pop     dx
        pop     ax
.x:     ret

; CX blanks in attribute [mt_va] at ES:DI, each only in the 32 KB; DI on
; past them.  All else kept
mt_vset:
        jcxz    .x
        push    ax
        push    dx
        mov     al, ' '
        mov     ah, [mt_va]
        mov     dx, cx
        shl     dx, 1
        add     dx, di
        jc      .w
        cmp     dx, 8000h
        ja      .w
        rep     stosw
        jmp     short .y
.w:     cmp     di, 8000h - 1
        jae     .s
        mov     [es:di], ax
.s:     inc     di
        inc     di
        loop    .w
.y:     pop     dx
        pop     ax
.x:     ret

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
MT_SSTK     equ     1024                ;  on the paragraph after the image;
MT_PARAS    equ     MT_TX0P + TX0_PARAS + MT_SSTK / 16  ; then mt_swnow's stack

section mttbss
mt_tx0      resb    TX0_PARAS * 16      ; (at MT_TX0P * 16; no TX_GSN: task 0
                                        ;  never ends)
            resb    MT_SSTK             ; (mt_swnow's stack)
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
        int     11h                     ; a coprocessor?  (POST's own probe on
        and     al, 2                   ;  the 1520; with none, its
        shr     al, 1                   ;  instructions may trap: EM)
        mov     [es:mt_fpu], al
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
        mov     ax, [10h * 4]           ; INT 10h
        mov     [es:mt_old10], ax
        mov     ax, [10h * 4 + 2]
        mov     [es:mt_old10 + 2], ax
        mov     word [10h * 4], mt_v10
        mov     [10h * 4 + 2], es
        mov     ax, [13h * 4]           ; INT 13h
        mov     [es:mt_old13], ax
        mov     ax, [13h * 4 + 2]
        mov     [es:mt_old13 + 2], ax
        mov     word [13h * 4], mt_i13
        mov     [13h * 4 + 2], es
        mov     ax, [16h * 4]           ; INT 16h
        mov     [es:mt_old16], ax
        mov     ax, [16h * 4 + 2]
        mov     [es:mt_old16 + 2], ax
        mov     word [16h * 4], mt_i16
        mov     [16h * 4 + 2], es
        mov     si, mt_vfr              ; INT 09h and 1Bh: task 0's, in front
        mov     di, mt_fv
.fv:    mov     bl, [es:si]
        xor     bh, bh
        shl     bx, 2
        mov     ax, [bx]
        stosw
        mov     ax, [bx+2]
        stosw
        inc     si
        cmp     si, mt_vfr + MT_NFV
        jb      .fv
        mov     ax, KSEG                ; INT 21h F0h: JMP FAR mt_f0
        mov     ds, ax
        mov     byte [f_F0], 0EAh
        mov     word [f_F0 + 1], mt_f0
        mov     [f_F0 + 3], es
        mov     byte [kbd_get.k], 0EAh  ; the key wait: JMP FAR mt_kwait
        mov     word [kbd_get.k + 1], mt_kwait
        mov     [kbd_get.k + 3], es
        mov     byte [done.sw], 0EAh    ; INT 21h's way out: JMP FAR mt_exit
        mov     word [done.sw + 1], mt_exit
        mov     [done.sw + 3], es
        mov     byte [crit_disk.c24], 9Ah       ; INT 24h: CALL FAR mt_c24
        mov     word [crit_disk.c24 + 1], mt_c24
        mov     [crit_disk.c24 + 3], es
        mov     byte [ui_progend], 0EAh ; a program's end: JMP FAR mt_pgend
        mov     word [ui_progend + 1], mt_pgend
        mov     [ui_progend + 3], es
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
