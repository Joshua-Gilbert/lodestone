; =====================================================================
;  KMT.INC - multitasking, behind a switch: MULTITASK=1 in \LODE.INI
;  (with EMS; without it, it stays off).  The design:
;  docs/lodestone-multitasking.md.  In it: the switch; tasks, each
;  a DOS program in a region of its own, switched when one waits for a
;  key; the front one chosen with CODE-Tab, each task's screen kept
;  in 2 EMS pages of its own; tasks preempted at the timer's tick,
;  where it is safe; each task's coprocessor state kept; a
;  background task's INT 10h output in its own screen, and a task that
;  writes the screen itself frozen in the background; keys for the
;  front task only, its waits in the BIOS switched from, CODE-Tab wherever
;  it is typed; each task's own INT 33h mouse state; each
;  task's own vectors (mt_vrun's swapped at every switch, the
;  keyboard's 09h and 1Bh at a change of the front, the rest the
;  machine's, those left pointing into a task's region put back at its
;  end); tasks ended whatever runs in them (MT_KILL, at their stub's
;  MT_END when they next run).  CODE-Tab not lost to the BIOS's look for
;  a key (mt_drop).
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
;      vectors; while the running task has one there the tick
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
;    - f_48, mem_largest and f_4B.xe (5 bytes each) become far jumps to
;      mt_48, mt_largest and mt_xenv: a task's region grows.
;    - f_3A.mt (RMDIR's CMP BYTE [r_name],0) becomes a far jump to mt_rd:
;      another task's current directory is refused too (16, as MS-DOS).
;  (mt_hooks, in mt_boot's section, lists the places.)
;    - gp_isr.e, the GPIB driver's EOI (MOV AL,20h / OUT 20h,AL / POP DS)
;      becomes a far jump to mt_srqi: a task woken by SRQ (MT_WAKE)
;      switched to at once, as at a tick's end.
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
;  the tick, on INT 21h's way out or at the GPIB driver's SRQ interrupt
;  where it is safe (mt_safe).
;  The calls: MTAPI.INC.
; =====================================================================
%ifndef NOTC
%include "MTAPI.INC"

; ---- a task's entry in mt_tab (the API's record is MT_REC: mt_f0.list)
TE_STATE    equ 0                       ; TS_*
TE_PSP      equ 2                       ; its stub's PSP (task 0: the root's)
TE_REG      equ 4                       ; its region (task 0: 0)
TE_TX       equ 6                       ; its TX's segment
TE_EXIT     equ 8                       ; the exit code of the last task ended
                                        ;  here (its program's: last_exit), kept
                                        ;  while the entry is free (MT_EXIT)
TE_NAME     equ 10                      ; TR_NAMELEN bytes
TE_SH       equ 22                      ; its screen's EMS handle (2 pages; 0:
                                        ;  none)
TE_SF       equ 23                      ; 1: its screen is kept there
TE_VF       equ 24                      ; VF_DIRECT, and its SPF_BG and SPF_FREEZE
TE_KILL     equ 25                      ; 1: MT_KILL ended it (it ends when it
                                        ;  next runs: mt_kdie)
TE_PST      equ 26                      ; parked (TS_PARKED): its state before
TE_PH       equ 27                      ;  it, the EMS handle its region is in
TE_PSZ      equ 28                      ;  (MT's), and the region's paragraphs
TE_GEN      equ 30                      ; the tasks started here, counted (1..255,
                                        ;  then 1 again; 0: none yet)
TE_EGEN     equ 31                      ; TE_GEN of the last one ended here
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
TX_MG       equ (V_PSP + (term_keep + 2 - cur_psp) + 1) & ~1    ; each
                                        ;  floppy's mount its directories are
                                        ;  of (mt_vsave, mt_vload)
TX_ML       equ TX_MG + 2 * NFLOP       ; mlook as it was (mt_vsave, mt_vload)
TX_KSTK     equ TX_ML + 2               ; (even, as kstack_top is: its words
                                        ;  aligned)
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
TX_CHG      equ TX_FVEC + MT_NFV * 4    ; its screen's changes in the background,
                                        ;  counted (MT_TROWS gives it)
TX_WGFX     equ TX_CHG + 2              ; 1: a terminal window's task, brought
                                        ;  to the front for graphics (
                                        ;  mt_wfront); 2: back to its window
                                        ;  at the next switch (a text mode,
                                        ;  mt_wback; mt_scrsv's 0)
TX_WPSP     equ TX_WGFX + 1             ; the program that asked (mt_gtext)
TX_MREL     equ TX_WPSP + 2             ; its window's clicks (MT_TMOUSE):
                                        ;  80h a press it hasn't read yet (AX=3
                                        ;  behind), 40h then a release held
                                        ;  till it has (the buttons then in bits
                                        ;  0-1, where: TX_MRX, TX_MRY)
TX_MPSP     equ TX_MREL + 1             ; the program that took the mouse (its
                                        ;  reset, AX=0 or 21h), 0 none: MT_TROWS
                                        ;  says so (a window's clicks its own)
TX_MRX      equ TX_MPSP + 2
TX_MRY      equ TX_MRX + 2
TX_IN13     equ TX_MRY + 2              ; its mt_in13 (one switched from
                                        ;  inside an INT 13h call, at its wait)
TX0_PARAS   equ (TX_IN13 + 2 + 15) / 16 ; (task 0's TX ends here)
TX_GSN      equ TX0_PARAS * 16          ; the vector table at its spawn (a
                                        ;  task's: the ones left pointing into
                                        ;  its region at its end put back)
TX_KN       equ TX_GSN + 1024           ; keys typed to it with MT_TKEY, for
TX_KH       equ TX_KN + 1               ;  its INT 16h: how many, the first's
TX_KR       equ TX_KN + 2               ;  place, then KRING of them
KRING       equ 32
TX_PUB      equ TX_KR + KRING * 2       ; its screen's descriptor (MT_PUB;
TX_PPSP     equ TX_PUB + 4              ;  0:0 none), the program that gave it
TX_PARAS    equ (TX_KR + KRING * 2 + 15) / 16
%if TX_PPSP + 2 > TX_PARAS * 16
%error "TX: TX_PUB past its last paragraph"
%endif
%if TX_PARAS * 16 > 4000h
%error "TX: in a parked region's first EMS page (mt_pmap)"
%endif
%ifdef CRASHLOG
MT_NVEC     equ 28                      ; (CRASHLOG: INT 06h the machine's, KCRASH.INC)
%else
MT_NVEC     equ 29                      ; (mt_vrun's and mt_vfr's counts)
%endif
MT_NFV      equ 2
; CRASHLOG's flight recorder (KCRASH.INC): a record with this tag (a
; letter), the caller's CS:IP, SS:SP, AX, BX.  Nothing in the normal build
; (and CMOS 3Dh's low nibble: a disk wait's phase, KCRASH.INC's cr_wtags)
%macro CRW 1
%ifdef CRASHLOG
        push    ax
        mov     al, %1
        call    cr_wt
        pop     ax
%endif
%endmacro
%macro CREC 1
%ifdef CRASHLOG
        pushf
        push    word %1
        call    mt_crec
        popf
%endif
%endmacro

; ---- the stub (a PSP, then this at 100h) --------------------------------
ST_PATH     equ 120h                    ; the program (ASCIIZ)
ST_PB       equ 1A0h                    ; EXEC's block
ST_FAIL     equ 1AEh                    ; EXEC's error, then 0FFh, if it failed
                                        ;  (0 if not): the exit code FFxxh
ST_TAIL     equ 1B0h                    ; its command tail
ST_STK      equ 340h                    ; its stack's top
SW_RET      equ 20                      ; (mt_switch's frame from the SP it
                                        ;  keeps: ES, DS, POPA's 8, then where
                                        ;  it goes back to: mt_load's RET)
ST_AFR      equ ST_STK - 26             ; its EXEC call's frame (INT 21h's, on
                                        ;  its stack): terminate's, if it is
                                        ;  ended itself (^C at its EXEC, or an
                                        ;  INT 24h handler's 4Ch meanwhile; no
                                        ;  longer an Abort: f_4B fails then)
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
%macro UCALL 1                          ; CALL a near routine of the UI (DS = it)
        push    cs
        push    word %%r
        push    word ..@ui_retf         ;  (its RET goes to a RETF there)
        push    ds
        push    word %1
        retf
%%r:
%endmacro

; ---- the resident part (in its own segment, from 0) -----------------
section mtt
mt_tstart:
mt_old08    dd      0                   ; INT 08h as it was
mt_ticks    dw      0                   ; ticks seen (mt_tick runs)
mt_facc     dw      0                   ; counter 0 run fast, its clocks since
                                        ;  the BIOS's last tick (mod 65536)
mt_flast    dw      0                   ;  and the count read to match (mt_fast)
mt_slice    db      2                   ; ticks left in the running task's turn
mt_pend     db      0                   ; 1: another task's turn (its turn over,
                                        ;  or a key for the front one waiting)
mt_lcs      dw      0                   ; (the last switch's interrupted CS,
mt_lip      dw      0                   ;  IP, flags and SP, for test_mt: set
mt_lfl      dw      0                   ;  by mt_safe when it says yes)
mt_lsp      dw      0
mt_mdrag    db      0                   ; 1: task 0 switched from at a drag's
mt_mx       dw      0                   ;  wait (..@ui_midle), the mouse there
mt_my       dw      0                   ;  then (the UI's mx, my, mb): moved
mt_mb       db      0                   ;  since, it runs next (mt_mwant)
mt_mrot     db      0                   ; the task such a boost took the turn
                                        ;  from: mt_pick goes on after it
mt_fpu      db      0                   ; 1: a coprocessor (INT 11h), kept per
                                        ;  task
mt_front    db      0                   ; the task in front
mt_cur      db      0                   ; the task running (the three in this
mt_tsrk     db      0                   ;  order: MT_TSR gives their address);
                                        ;  1: Resident Claude's pop-up waits
                                        ;  for the front task (as a key would:
                                        ;  mt_kin)
mt_tsro     dw      0                   ; Resident Claude's key wait (MT_TSR):
mt_tsrs     dw      0                   ;  a switch may come there; 0:0 none
mt_hotk     dw      0A500h, 0A5F0h      ; the hot key, CODE-Tab, as AH=10h
                                        ;  gives it on the 1520 (KEYCODE.COM),
                                        ;  and as a BIOS keeping CODE keys with
                                        ;  F0h would
mt_swreq    db      0FFh                ; a task to bring to the front (FFh: none)
%ifndef NOSYSREQ
mt_sysrq    db      0, 0                ; 1, SysReq pressed (mt_i15): as
%endif                                  ;  CODE-Tab at mt_hot's next look (2 B:
                                        ;  what follows keeps its parity)
mt_wkt      db      0FFh                ; the task MT_WAKE's program is in
mt_wkp      dw      0                   ;  (FFh: none), and its PSP
mt_want     db      0FFh                ; the task an SRQ woke: mt_pick's next
mt_wsv      db      0, 0               ; (mt_smap: windows 0 and 1 as they were)
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
mt_old15    dd      0                   ; INT 15h, 25h, 26h and 0Eh (IRQ 6, the
mt_old25    dd      0                   ;  floppy's) as they were
mt_old26    dd      0
mt_old0e    dd      0
mt_old76    dd      0                   ; INT 76h (IRQ 14, the hard disk's)
mt_down     db      0FFh                ; the task switched from at a
                                        ;  floppy's wait (INT 15h AX=9001h),
                                        ;  or the hard disk's (9000h),
                                        ;  till it runs again (FFh: none)
mt_ddev     db      1                   ; its device: 1 the floppy, 0 the hard
                                        ;  disk (as 9001h/9000h's AL)
mt_hirq     db      0                   ; 1: an IRQ 14 has come (mt_i76)
mt_htk      db      0                   ; hard-disk waits the tick ended, the
                                        ;  drive done, and no IRQ 14 yet (2: a
                                        ;  dead line, no more switches there)
mt_dto      db      0                   ; its time-out, in ticks left
mt_dtmo     db      0                   ; 1: it came back by the time-out
mt_dfw      db      0                   ; the EMS windows its transfer holds
                                        ;  (bit w: window w; only the cache's,
                                        ;  2 and 3)
mt_13ax     dw      0                   ; the latest INT 13h call's AX, BX and
mt_13bx     dw      0                   ;  ES (mt_i13: its transfer)
mt_13es     dw      0
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
mt_33pm     db      0                   ;  14h: 0 else) and the mask before,
mt_33fn     dw      0                   ;  the function (AX=3's read)
mt_33sb     db      0                   ; (mt_scrto: m33_busy as it was)
mt_33ot     db      0                   ; (mt_m33on: another driver answered)
; each task's own vectors, swapped at every switch: DOS's (22h-24h
; first: a new task's are MT's, not its spawner's; 21h, 28h, 2Fh), the
; CPU's traps, INT 02h (where the BIOS's INT 75h sends a coprocessor's
; error) and 75h, INT 08h (its timer hook ahead of mt_tick), 10h, 16h,
; 1Ch, and 34h-3Fh (compilers' floating-point emulators, overlay
; managers).  And the front task's: 09h and 1Bh (the keyboard's), swapped
; at a change of the front.  The rest are the machine's (13h, 33h, the
; other IRQs, 67h, the BIOS's tables)
mt_vrun     db      22h, 23h, 24h, 21h, 28h, 2Fh
%ifdef CRASHLOG
            db      00h, 01h, 02h, 03h, 04h, 75h
%else
            db      00h, 01h, 02h, 03h, 04h, 06h, 75h
%endif
            db      08h, 10h, 16h, 1Ch
            db      34h, 35h, 36h, 37h, 38h, 39h, 3Ah, 3Bh, 3Ch, 3Dh, 3Eh, 3Fh
%if $ - mt_vrun != MT_NVEC
%error "mt_vrun: MT_NVEC"
%endif
mt_vfr      db      09h, 1Bh
%if mt_vfr - mt_vrun != MT_NVEC
%error "mt_vfr: just after mt_vrun (mt_own, mt_pinned)"
%endif
mt_fv       times   MT_NFV * 2 dw 0     ; the front task's 09h and 1Bh while
                                        ;  another runs (mt_vfr's order)
mt_vr       dw      0                   ; (mt_vrep: the memory, its end, the
mt_ve       dw      0                   ;  table put back from, at DS:mt_vsb,
mt_vsb      dw      0                   ;  and 1 if the vector table is done
mt_vtab     db      0                   ;  too; mt_vfr's from mt_vfs)
mt_vfs      times   MT_NFV * 2 dw 0
mt_mv       dd      0                   ; (mt_move: INT 67h AH=57h's block: the
mt_mvs      db      0                   ;  length, then the source and the
            dw      0, 0, 0             ;  destination, each its type, handle,
mt_mvd      db      0                   ;  offset, and segment or page)
            dw      0, 0, 0
mt_psv      db      0                   ; (mt_pmap: window 0 as it was)
mt_hold     times   EMS_NH db 0         ; a parked task's programs' EMS handles:
mt_hown     times   EMS_NH dw 0         ;  that task (0: none), their owners
mt_xr       dw      0                   ; (mt_inr: a parked task's own region,
mt_xe       dw      0                   ;  while its TX is looked at: its own
                                        ;  vectors into it aren't another's,
                                        ;  who may be there now; else empty)
mt_vs       times   VIDLEN db 0         ; (mt_v10: the BIOS data worked on)
mt_vp0      dw      0                   ; (mt_vtty: where it was)
mt_vw       db      0                   ; (mt_vscr: the window's width, its
mt_vn       db      0                   ;  lines, attribute, rows blanked)
mt_va       db      0
mt_vb       db      0
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
mt_nend     db      0                   ; tasks ended (mt_end), and the count
mt_send     db      0                   ;  MT_UI's look last saw
mt_xgen     times MT_TASKS db 0         ; MT_UI: the count of the task the
                                        ;  Executive started there (0: none)
mt_eord     times MT_TASKS db 0         ; (each task's end: mt_nend then)
mt_xnm      dw      0                   ; (MT_UI: the program's name)
mt_xpb      times SP_SIZE db 0          ; (MT_UI's MT_SPAWN block)
mt_lbg      dw      mt_lnone            ; LODE.INI's lists (mt_lists): BG=,
mt_lfz      dw      mt_lnone            ;  FREEZE=, MTMEM=, FULL= (started
mt_lmem     dw      mt_lnone            ;  full screen, not in a terminal
mt_lfull    dw      mt_lnone            ;  window); in mt_ini
mt_lnone    db      0
mt_scant    db      "Can't run ", 0     ; (MT_UI's messages)
mt_smany    db      ': too many tasks', 0
mt_snomem   db      ': not enough memory or EMS; park or end a task', 0
mt_sended   db      ' ended', 0
mt_scode    db      ', exit code ', 0
mt_snost    db      ' could not be started: error ', 0
mt_fast     db      0                   ; how sure counter 0 runs fast, 0-3
                                        ;  (mt_tick).  Here, the align's pad
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

; the stub, copied to its PSP:0100h (DS = ES = SS = the PSP)
st_code:
        mov     ax, 4B00h
        mov     dx, ST_PATH
        mov     bx, ST_PB
        int     21h
        jnc     .e
        mov     [ST_FAIL], al           ; (its program not started: MT_END
        mov     byte [ST_FAIL + 1], 0FFh ;  keeps FFxxh as its exit code)
.e:     mov     ax, 0F000h + MT_END     ; (PSP:0Ah: where it ends, its own
        int     21h                     ;  parent, if it is aborted itself)
.h:     hlt                             ; (never: MT_END doesn't come back)
        jmp     .h
st_len      equ     $ - st_code
ST_END      equ     100h + st_code.e - st_code
            times   -(100h + st_len > ST_PATH) db 0     ; (it fits below ST_PATH)

; INT 08h: the BIOS's handler first (the tick count, INT 1Ch, the end of
; the interrupt), then ours.  A program that runs counter 0 fast (a
; game's music, its own INT 08h hook calling the BIOS's every Nth time)
; has that hook in its own turns only; in the others, entered straight
; (INT 08h mt_tick itself), MT does as it does: the BIOS's handler once
; 65536 of the counter's clocks have gone by, else only the interrupt's
; end.  The count read just after the interrupt is about its period
; (mode 2 or 3), the same each time; a tick held late under a long CLI
; reads low too, but not the same twice running.  So mt_fast counts how
; sure MT is (0-3): a low read the same as the last (within MT_FTOL) one
; surer, another one less (and the one to match, below 2); it divides
; from 2.  Not in the turns of a program whose own INT 1Ch hook is there
; (it gets it fast, as in DOS)
MT_FALW     equ     20                  ; (counted down since the IRQ)
MT_FTOL     equ     80h                 ; (two reads the same: within this)
; (mt_tick's own, on a low read, AX: here, ahead of it, so that its jumps
; are short and a tick at the BIOS's rate takes none)
mt_tfast:
        push    bx
        push    dx
        mov     bx, ax
        sub     bx, [cs:mt_flast]       ; the same as the last?
        jns     .a
        neg     bx
.a:     cmp     bx, MT_FTOL
        mov     bl, [cs:mt_fast]
        jae     .o
        or      bl, bl
        jz      .o                      ; (none to match)
        cmp     bl, 3                   ; the same: surer, up to 3
        adc     bl, 0
        jmp     short .c
.o:     dec     bl                      ; another: less sure
        cmp     bl, 2
        jge     .c
        mov     [cs:mt_flast], ax       ;  (below 2: this one to match)
        mov     bl, 1
.c:     mov     [cs:mt_fast], bl
        cmp     bl, 2
        jb      .b                      ; not sure yet: the BIOS's, as ever
        push    ax
        mov     ax, [1Ch * 4 + 2]       ; the running program's own INT 1Ch?
        cmp     ax, 0A000h              ; (the BIOS's, in ROM, as most often:
        cmc                             ;  not a program's, CF, without the
        jc      .r                      ;  walk of the arena)
        push    KSEG
        pop     ds
        call    mt_mine
.r:     pop     ax
        jnc     .b                      ; (then fast in its turns, as in DOS)
        pop     dx
        pop     bx
        add     ax, MT_FALW + 1
        add     [cs:mt_facc], ax
        jc      mt_tick.n               ; a whole tick of the BIOS's gone by
        mov     al, 20h                 ; else the interrupt's end only
        out     20h, al
        pop     ds
        pop     ax
        iret
.b:     pop     dx
        pop     bx
        jmp     short mt_tick.n
mt_tick:
        push    ax
        push    ds
        xor     ax, ax
        mov     ds, ax
        cmp     word [8 * 4], mt_tick   ; entered straight?  (A hook ahead:
        jne     .n                      ;  it divides, if it ran it fast)
        mov     ax, cs
        cmp     [8 * 4 + 2], ax
        jne     .n
        xor     al, al                  ; counter 0, latched
        out     43h, al
        in      al, 40h
        mov     ah, al
        in      al, 40h
        xchg    al, ah
        dec     ax                      ; (0: 65536)
        cmp     ax, 7FFFh
        jb      mt_tfast                ; low: maybe fast
        mov     byte [cs:mt_fast], 0    ; at the BIOS's rate: as ever
.n:     pop     ds
        pop     ax
        pushf
        call    far [cs:mt_old08]       ; (back with the EOI sent; interrupts
        cli                             ;  off, whatever a hook there did)
        inc     word [cs:mt_ticks]
%ifdef CRASHLOG
        call    mt_crt
%endif
        cmp     byte [cs:mt_down], 0FFh ; (a floppy owner's time-out)
        je      .d
        call    mt_dtick
.d:     nop                             ; (mt_par: what follows at its parity)
        push    ax
        push    bx
        push    dx
        push    ds
        push    bp
        mov     bp, sp                  ; ([bp+10]: the interrupted IP, CS, FL)
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
        jnz     .m
.p:     mov     byte [cs:mt_pend], 1
.m:     mov     ax, cs                  ; (MT's own code: the turn counted,
        cmp     [bp+12], ax             ;  no switch here)
        je      .r
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
.v:     lea     ax, [bp+16]
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

; The GPIB driver's SRQ interrupt (gp_isr.e, its EOI: JMP FAR here, by
; mt_boot), on gp_isr's AX, DX, DS (DS = KSEG).  The EOI and out, as
; there; but with a program asking (MT_WAKE) in another task, ready to run,
; that task is the next (mt_want) and its turn comes now, as at a tick's
; end (mt_tick.v: what was interrupted vetted by mt_safe; else at the
; running task's next INT 21h or tick)
mt_srqi:
        mov     al, 20h                 ; (gp_isr's EOI: before mt_safe, which
        out     20h, al                 ;  wants none in service)
        pop     ds
        pop     dx
        push    bx                      ; mt_tick's frame: AX, BX, DX, DS, BP
        push    dx
        push    ds
        push    bp
        mov     bp, sp
        push    KSEG
        pop     ds
        mov     al, [cs:mt_wkt]
        cmp     al, 0FFh                ; (none)
        je      .r
        cmp     al, [cs:mt_cur]         ; (its own: running, or woken from its
        je      .r                      ;  HLT by this interrupt)
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_RUN
        jne     .r
        call    mt_frz
        jnz     .r
        mov     [cs:mt_want], al
        mov     byte [cs:mt_pend], 1
        push    es                      ; IRQ 5 still gp_isr's?  (Else a hook
        xor     ax, ax                  ;  ahead of it was interrupted)
        mov     es, ax
        cmp     word [es:gp_IRQVEC * 4], gp_isr
        jne     .h
        cmp     word [es:gp_IRQVEC * 4 + 2], KSEG
.h:     pop     es
        jne     .r
        jmp     mt_tick.v
.r:     jmp     mt_tick.r

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
        call    mt_mwant                ; (or the mouse for the UI's drag)
        jnz     .p
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITK
        jne     .x
        call    mt_kin
        je      .x
.p:     mov     byte [cs:mt_pend], 1
.x:     ret

; front task AL: task 0 switched from at a drag's wait, and the mouse
; moved (or a button) since?  ZF clear if so: it runs next, so a drag
; follows the mouse while tasks behind take the pauses.  From its
; idle too (it gives the rest of its turn away there, mw_poll), and a key
; waiting as well.  Registers kept
mt_mwant:
        or      al, al
        jnz     .no
        cmp     byte [cs:mt_mdrag], 0
        je      .x
        call    mt_kin
        jnz     .x
        push    ds
        push    es
        push    bx
        push    KSEG
        pop     ds
        mov     es, [ui_seg]
        mov     bx, [es:mx]
        cmp     bx, [cs:mt_mx]
        jne     .y
        mov     bx, [es:my]
        cmp     bx, [cs:mt_my]
        jne     .y
        mov     bl, [es:mb]
        cmp     bl, [cs:mt_mb]
.y:     pop     bx
        pop     es
        pop     ds
.x:     ret
.no:    cmp     al, al
        ret

; the running task switched from: task 0 at a drag's wait (mt_safe's
; mt_lcs, mt_lip at ..@ui_midle)?  mt_mdrag, and the mouse then.
; Registers kept
mt_mdset:
        cmp     byte [cs:mt_cur], 0
        jne     .x
        push    ax
        push    bx
        push    ds
        push    es
        push    KSEG
        pop     ds
        mov     es, [ui_seg]
        xor     al, al
        mov     bx, [cs:mt_lcs]
        cmp     bx, [ui_seg]
        jne     .s
        cmp     word [cs:mt_lip], ..@ui_midle
        je      .m
        cmp     word [cs:mt_lip], ..@ui_idle    ; (its idle's too)
        jne     .s
.m:     inc     ax
        mov     bx, [es:mx]
        mov     [cs:mt_mx], bx
        mov     bx, [es:my]
        mov     [cs:mt_my], bx
        mov     bl, [es:mb]
        mov     [cs:mt_mb], bl
.s:     mov     [cs:mt_mdrag], al
        pop     es
        pop     ds
        pop     bx
        pop     ax
.x:     ret

; a key for the front task: one in the BIOS's buffer, or Resident Claude's
; pop-up waiting for its call (mt_tsrk: CODE-\ taken in another task's).
; ZF if none.  Registers kept
mt_kin: cmp     byte [cs:mt_tsrk], 0
        jne     .x
        push    ds
        push    ax
        push    40h
        pop     ds
        mov     ax, [1Ah]
        cmp     ax, [1Ch]
        pop     ax
        pop     ds
.x:     ret

; the interrupted (or calling) code at CS AX, IP BX, flags DX, on SS: may
; the running task be switched from there?  CF if not.  Only if: no INT 21h
; under way; interrupts were on, and no other hardware interrupt is in
; service; CS below A000h (not the BIOS, the ROM, the EMS frame), not the
; kernel's or MT's; in the UI's segment, only at its idle HLTs, and in
; Resident Claude's stub only at its key wait's (MT_TSR); no INT 33h
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
        cmp     byte [cs:mt_crit], 0    ; (the kernel's INT 24h, raised outside
        jne     .no                     ;  INT 21h: C:'s INT 25h/26h, its code
                                        ;  half way; its handler's own code)
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
        cmp     ax, [cs:mt_tsrs]        ; (Resident Claude's stub: only at its
        jne     .ui                     ;  key wait's HLT, MT_TSR, still there
        cmp     bx, [cs:mt_tsro]        ;  (an older CLAUDE /U doesn't say it
        jne     .no                     ;  went), in a read of the program's
        push    es                      ;  own: its frame's CS the task's, not
        mov     es, ax                  ;  the UI's (the Executive switched
        cmp     byte [es:bx-1], 0F4h    ;  from only at its idle HLTs) or a
        pop     es                      ;  TSR's)
        jne     .no
        mov     bx, [cs:mt_lsp]
        mov     ax, [ss:bx+2]
        cmp     ax, [ui_seg]
        je      .no
        call    mt_mine
        jc      .no
        jmp     short .pic
.ui:    cmp     ax, [ui_seg]
        jne     .pic
        cmp     bx, ..@ui_idle
        je      .pic
        cmp     bx, ..@ui_midle         ; (a drag's: UI_MOUSE, win_mv)
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
        mov     ax, [cs:mt_lcs]         ;  above; LCMD's saver runs there;
        cmp     ax, [ui_seg]            ;  Resident Claude's, at its HLT)
        je      .y
        cmp     ax, [cs:mt_tsrs]
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
        call    mt_cent
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
        call    mt_mwant                ; (the mouse moved in the UI's drag)
        jnz     .mw
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITK
        jne     .p
        call    mt_kin
        je      .p
        call    mt_dok                  ; (not with a floppy owner out)
        jnz     .p
        mov     byte [cs:mt_tsrk], 0    ; (given: Resident Claude's pop-up is
        jmp     short .f                ;  the front task's call's to bring)
.mw:    mov     ah, [cs:mt_cur]         ; (the turn taken from it: the round
        mov     [cs:mt_mrot], ah        ;  goes on after it, mt_pick)
.f:     mov     bl, al
        jmp     short .sw
.p:     call    mt_pick
        jnc     .sw
        call    mt_cent                 ; none: this one goes on, a new turn;
        cmp     byte [cs:bx+TE_KILL], 0 ;  unless it ended itself (now), or it
        jne     mt_kdie                 ;  is frozen here: then the front one
        call    mt_frz                  ;  (waiting for a key, or it would
                                        ;  have been picked)
        jnz     .fz
.nw:    mov     byte [cs:mt_slice], 2
        ret
.fz:    mov     al, [cs:mt_front]       ; (the front one only if it may
        call    mt_ent                  ;  run now; else this one goes on)
        call    mt_dok
        jnz     .nw
        mov     bl, al
.sw:    call    mt_mdset
        call    mt_tsrw
        jmp     mt_switch

; the running task, switched from Resident Claude's key wait (its HLT, where
; mt_safe said yes: mt_lcs, mt_lip): it waits for a key, as in MT
; (TS_WAITK), so it gets no turns behind, and in front one when a key comes
; (mt_kin) instead of every round.  Registers kept
mt_tsrw:
        push    ax
        mov     ax, [cs:mt_lcs]
        cmp     ax, [cs:mt_tsrs]
        jne     .x
        mov     ax, [cs:mt_lip]
        cmp     ax, [cs:mt_tsro]
        jne     .x
        push    bx
        call    mt_cent
        mov     byte [cs:bx+TE_STATE], TS_WAITK
        pop     bx
.x:     pop     ax
        ret

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
.f:     push    dx                      ; keys typed to it (MT_TKEY): read as
        mov     dx, 1                   ;  any (kbd_get's INT 16h: mt_i16)
        call    mt_ring
        pop     dx
        jnc     .have
        mov     al, [cs:mt_cur]
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
.idle:  call    mt_cent                 ; (it ended itself: now, if it can be
        cmp     byte [cs:bx+TE_KILL], 0 ;  here: this wait may be in its INT
        je      .wt                     ;  24h handler, or its mouse's)
        call    mt_kok
        je      mt_kdie
.wt:    pop     bx                      ; the kernel's own wait: PrtSc,
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
; prompt, or from an interrupt's handler (its IRQ in service), reads
; them as it is (mt_i16 lets them through: everything waits for the
; answer, the prompt on the real screen, as in DOS)
.bg:    call    mt_can
        jnc     .bgp
        jnz     .k                      ; (inside a call MT passed on to the
                                        ;  BIOS, an INT 13h call, a change of
                                        ;  the front, an INT 24h, an IRQ's
                                        ;  handler: as it is, mt_i16 letting
                                        ;  it read them)
        mov     [cs:mt_swreq], al       ; (this task, as mt_swnow does it: the
        call    mt_swnow                ;  one in front may be in its run)
        jmp     .k
        times   ($ - $$) & 1 db 90h     ; (what follows at the parity
                                        ;  it had, mt_i21 and mt_i16 with it)
; An INT 16h hook of the running program's, or of a program it
; runs under (a RUN's key script, CLAUDE's, in a window; not a TSR's,
; Resident Claude's, ended though resident): asked, as in front (mt_i16
; has none for it behind); none: it stays ready, another runs, and it
; asks again at its next turn (a script's wait is timed: no key would
; wake it).  Its code in the block of cur_psp or of a parent's, each
; a PSP in the task's region, up to its stub (task 0: as before)
.bgp:   push    cx
        push    si
        push    di
        push    es
        push    dx
        mov     al, [cs:mt_cur]
        or      al, al
        jz      .hn
        call    mt_ent
        mov     dx, [cs:bx+TE_PSP]      ; (the walk's end: its stub)
        mov     si, [cs:bx+TE_REG]
        lea     di, [si-1]
        mov     es, di
        mov     di, si
        add     di, [es:3]              ; its region: SI up to DI
        xor     bx, bx
        mov     es, bx
        mov     ax, [es:16h * 4]        ; its INT 16h's code's paragraph
        shr     ax, 4                   ;  (Resident Claude's segment is
        add     ax, [es:16h * 4 + 2]    ;  below its block: 130h in)
        mov     bx, [cur_psp]
        mov     cx, 8
.hp:    cmp     bx, dx
        je      .hn
        cmp     bx, si
        jbe     .hn
        cmp     bx, di
        jae     .hn
        dec     bx
        mov     es, bx                  ; (the PSP's block)
        inc     bx
        cmp     ax, bx
        jb      .hu
        add     bx, [es:3]
        cmp     ax, bx
        jb      .hz                     ; (CF: in it)
        sub     bx, [es:3]
.hu:    mov     es, bx
        mov     bx, [es:16h]            ; its parent
        loop    .hp
.hn:    clc
.hz:    pop     dx
        pop     es
        pop     di
        pop     si
        pop     cx
        jnc     .bgw
        mov     ah, 1
        int     16h
        jnz     .have
        call    mt_pick                 ; one ready to run; or the front one
        jnc     .hs                     ;  waiting for a key typed now (it
        mov     al, [cs:mt_front]       ;  wouldn't get it while this one
        call    mt_ent                  ;  stays in INT 21h); else the
        cmp     byte [cs:bx+TE_STATE], TS_WAITK ; kernel's HLT
        jne     .idle
        call    mt_kin
        je      .idle
        mov     bl, al
.hs:    call    mt_fdrain
        call    mt_switch
        jmp     .top
.bgw:   call    mt_pick                 ; one ready to run, or the front one
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
        call    mt_cent
        mov     byte [cs:bx+TE_STATE], TS_WAITK
        pop     bx
        jmp     mt_switch

; CF if the running task can't be switched away from here: a nested INT
; 21h (an INT 24h answer), or more kernel stack than its TX holds; inside
; a call MT passed on to the BIOS or an INT 13h call; while mt_swnow
; changes the front (an interrupt handler's DOS call meanwhile); inside
; the kernel's INT 24h (raised by C:'s INT 25h/26h, outside INT 21h: its
; handler's own DOS call); from an interrupt's handler, its IRQ still in
; service (another task would run with it so).  With CF, NZ for
; these last four (mt_busy, asked first: a task's own INT 24h handler's
; read is inside the kernel's INT 24h at InDOS 2), ZF for the first two.
; AX kept
mt_can: push    ax
        pushf
        cli                             ; (the PIC asked with interrupts off)
        call    mt_busy
        jnz     .nb
        popf
        cmp     byte [indos], 1
        jne     .no
        mov     ax, kstack_top          ; (and room for mt_switch's own
        sub     ax, sp                  ;  pushes)
        cmp     ax, KSLICE - 48
        jae     .no
        pop     ax
        clc
        ret
.nb:    popf
        pop     ax
        or      sp, sp                  ; (NZ)
        stc
        ret
        times   ($ - $$) & 1 db 90h     ; (mt_pick at its parity)
.no:    pop     ax
        cmp     sp, sp                  ; (ZF)
        stc
        ret

; a task other than the running one that is ready to run (TS_RUN) and
; not frozen in the background (mt_frz), the next after it in turn -> BL;
; CF if none.  (One an SRQ woke, mt_want, first)
mt_pick:
        push    ax
        push    cx
        mov     al, 0FFh
        xchg    al, [cs:mt_want]
        cmp     al, 0FFh
        jne     .wk
        mov     al, [cs:mt_cur]
        or      al, al                  ; (task 0 after a mouse boost: on
        jnz     .go                     ;  from the task it took the turn
        xchg    al, [cs:mt_mrot]        ;  from, not task 1 again; once)
        jmp     short .go
.wk:    dec     al                      ; (the turn from just before it)
.go:    mov     cx, MT_TASKS
.l:     inc     al
        and     al, MT_TASKS - 1
        cmp     al, [cs:mt_cur]
        je      .nx
        push    bx
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_RUN
        jne     .n
        call    mt_dok                  ; (with a floppy owner out)
        jnz     .n
        cmp     al, [cs:mt_down]        ; (the owner itself, back from its
        je      .n                      ;  wait: frozen or not, as nothing
                                        ;  else may enter the kernel till it
                                        ;  has run; it gives way after,
                                        ;  mt_dwait.bk)
        call    mt_frz
        jz      .n
        cmp     byte [cs:bx+TE_KILL], 1 ; (frozen, but ended: it runs, to end)
.n:     pop     bx
        je      .y
.nx:    loop    .l
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

; AL = the running task -> BX = its entry (mt_ent's)
mt_cent:
        mov     al, [cs:mt_cur]
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
        CREC    'S'                     ; (CRASHLOG: BL the task to run)
        pusha
        push    ds
        push    es
        cli
        cld                             ; (DF as the task had it, at a tick)
        pushf                           ; (and TF: a debugger single-stepping
        pop     ax                      ;  into INT 21h; its frame keeps it)
        and     ah, 0FEh
        push    ax
        popf
        push    bx
        call    mt_cent
        mov     es, [cs:bx+TE_TX]
        cmp     byte [cs:bx+TE_KILL], 0 ; (it ended itself where that couldn't
        je      .nk                     ;  be at once: it goes on at mt_kdie,
        mov     byte [cs:bx+TE_STATE], TS_RUN ; as one ended by another does,
        mov     bp, sp                  ;  ready whatever it was about to wait
        mov     word [bp+SW_RET+2], mt_kdie ; for; BX still pushed)
.nk:    pop     bx
.sv:    mov     [es:TX_SP], sp
        mov     [es:TX_SS], ss
        mov     al, [cs:mt_in13]        ; (the owner's, inside its call)
        mov     [es:TX_IN13], al
        call    mt_emsget
        mov     al, [cs:mt_cur]         ; windows held for an owner's
        cmp     al, [cs:mt_down]        ;  transfer, showing the cache's
        je      .eh                     ;  pages: another's saved as off
        test    byte [cs:mt_dfw], 4     ;  (they were, mt_dok: it never sees
        jz      .e3                     ;  the cache's)
        mov     byte [es:TX_EMS + 2], 0
.e3:    test    byte [cs:mt_dfw], 8
        jz      .eh
        mov     byte [es:TX_EMS + 3], 0
.eh:
        push    bx
        call    mt_vsv                  ; its own vectors, and the front's (09h,
        call    mt_fvsync               ;  1Bh) as its turn left them
        pop     bx
        cmp     byte [cs:mt_fpu], 0     ; its coprocessor's registers, control
        je      .nf                     ;  and status (mt_fdrain ran first:
        CRW     'n'                     ; (CRASHLOG: before the FNSAVE)
        fnsave  [es:TX_FPU]             ;  the 287 is idle, so this can't wait
        fwait                           ;  for ever).  Its error, if any, has
        CRW     'N'                     ; (CRASHLOG: after it)
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
        shr     cx, 1                   ; (in words, then an odd byte if any)
        rep     movsw
        adc     cx, cx
        rep     movsb
        push    bx
        call    mt_vsave                ; the kernel's variables
        pop     bx
mt_load:
        cli
        cld
        CRW     'L'                     ; (CRASHLOG: loading the next task)
        pushf                           ; (TF off, as in mt_switch)
        pop     ax
        and     ah, 0FEh
        push    ax
        popf
        mov     byte [cs:mt_inb], 0     ; (none under way at a switch, nor an
        mov     byte [cs:mt_crit], 0    ;  INT 24h prompt, INT 13h call, change
        mov     word [cs:mt_in13], 0    ;  of the front or kernel's idle: one
        mov     byte [cs:mt_idle], 0    ;  left by a program ended inside it,
        mov     [cs:mt_cur], bl         ;  cleared)
        or      bl, bl                  ; (task 0 running again: a boost of
        jnz     .md                     ;  its drag used up, mt_mdset sets it
        mov     [cs:mt_mdrag], bl       ;  again at the next switch from it)
.md:    mov     byte [cs:mt_pend], 0    ; its turn: 2 ticks in front, 1 else
        mov     byte [cs:mt_slice], 1
        cmp     bl, [cs:mt_front]
        jne     .t
        inc     byte [cs:mt_slice]
.t:
        mov     al, bl
        call    mt_ent
        mov     byte [cs:bx+TE_STATE], TS_RUN
        mov     es, [cs:bx+TE_TX]
        mov     ah, [es:TX_IN13]        ; (the owner's, back inside its
        mov     [cs:mt_in13], ah        ;  INT 13h call; else 0)
        cmp     byte [cs:mt_fpu], 0     ; its coprocessor state (none kept
        je      .nf                     ;  yet: as FNINIT leaves it)
        CRW     'p'                     ; (CRASHLOG: before FRSTOR / FNINIT)
        cmp     byte [es:TX_FPV], 0
        je      .fi
        frstor  [es:TX_FPU]
        jmp     .nf0
.fi:    fninit
.nf0:   CRW     'P'                     ; (CRASHLOG: after it)
.nf:    push    KSEG
        pop     ds
        call    mt_vload
        CRW     'v'                     ; (CRASHLOG: the kernel's variables back)
        call    mt_vld                  ; its own vectors; the front task's 09h
        call    mt_fvset                ;  and 1Bh (one ended may have set them)
        CRW     'w'                     ; (CRASHLOG: its vectors back)
        mov     cl, 0                   ; (windows held for an owner's
        mov     al, [cs:mt_cur]         ;  transfer, which another task's
        cmp     al, [cs:mt_down]        ;  registers don't change: CL the
        je      .hw                     ;  held ones, as bits 2-3, shifted
        mov     cl, [cs:mt_dfw]         ;  along, bit 0 the window's)
.hw:    mov     dx, EMS_PORT            ; its EMS windows
        mov     bx, TX_EMS
.em:    test    cl, 1
        jnz     .eh                     ; (held: as it is)
        mov     al, [es:bx]
        call    mt_eout
.eh:    shr     cl, 1
        inc     bx
        add     dh, 40h
        jnc     .em
        CRW     'e'                     ; (CRASHLOG: its EMS windows written)
        mov     ss, [es:TX_SS]
        mov     sp, [es:TX_SP]
        CRW     's'                     ; (CRASHLOG: on its stack)
        mov     cx, [es:TX_KLEN]
        jcxz    .go
        push    es                      ; its slice back where it was
        pop     ds
        mov     si, TX_KSTK
        push    ss
        pop     es
        mov     di, sp
        shr     cx, 1
        rep     movsw
        adc     cx, cx
        rep     movsb
.go:    CRW     'l'                     ; (CRASHLOG: loaded, on its way back)
        pop     es
        pop     ds
        popa
        sti
        ret
        db      90h                     ; (mt_par: what follows at its parity)

; the EMS windows' page registers to the TX at ES (AL, DX, DI changed)
mt_emsget:
        mov     dx, EMS_PORT
        mov     di, TX_EMS
.l:     in      al, dx
        stosb
        add     dh, 40h
        jnc     .l
        ret

; the kernel's variables (DS = KSEG) to the TX at ES, or back (AX too
; changed).  .r: the
; ranges at CS:BX, DS:x to ES:DI (mw_save's too), or ES:x from DS:SI with
; DS and ES swapped back after (mw_load_ctx's)
; Each floppy's mount (mgen) goes with the task's current directories
; (TX_MG): not that mount's if a look is due that finds them again (D_CHK
; 2); and the count of looks that took a disk for the same one, which may
; have changed elsewhere (mlook: TX_ML).  Back, another mount's, or any
; such look since (16 bits: 65536 of them while the task waits would be
; taken for none), and its floppies' are unknown, found again by name at
; the next path call (resolve's cwd_find, KDISK.INC rule 1), else the
; root: no look forced
mt_vsave:
        mov     ax, [mlook]
        mov     [es:TX_ML], ax
        mov     bx, 2 * (NFLOP - 1)
.g:     mov     ax, [mgen+bx]
        mov     si, bx
        shl     si, 4                   ; (DRVSZ / 2)
        cmp     byte [drvtab+si+D_CHK], 2
        jb      .g1                     ; (3: unmount's, rule 9)
        not     ax
.g1:    mov     [es:TX_MG+bx], ax
        dec     bx
        dec     bx
        jns     .g
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
        call    .r
        mov     cx, [es:TX_ML]          ; (after: D_CWD is the task's now)
        sub     cx, [mlook]
        mov     bx, 2 * (NFLOP - 1)
.g:     mov     ax, [es:TX_MG+bx]
        cmp     ax, [mgen+bx]
        jne     .gu
        jcxz    .g1
.gu:    mov     si, bx
        shl     si, 4
        or      word [drvtab+si+D_CWD], -1
.g1:    dec     bx
        dec     bx
        jns     .g
        ret
.r:     mov     di, [cs:bx]             ; (KMW.INC's mw_load_ctx's too)
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
;  each task's own vectors.  mt_vrun's are the running task's in
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
; as it left them.  The front task's go to mt_fv; another's, each one it
; set (it differs from mt_fv), are its own, to its TX (mt_fvset puts
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
        je      .n
.d:     push    bx                      ; (that one only: to its TX)
        call    mt_cent
        mov     es, [cs:bx+TE_TX]
        pop     bx
        sub     di, mt_fv - TX_FVEC
        movsw
        movsw
        add     di, mt_fv - TX_FVEC - 4
.n:     add     di, 4
        loop    .c
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
        cmp     byte [cs:bx+TE_STATE], TS_FREE  ; (a guard: mt_end hands over first)
        je      .ld
        mov     es, [cs:bx+TE_TX]
        push    cs
        pop     ds
        mov     si, mt_fv
        mov     di, TX_FVEC
        mov     cx, MT_NFV * 2
        rep     movsw
.ld:    pop     ax
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

; a new task's vectors (the TX at ES, its entry at BX; mt_spawn): its
; spawner's, but INT 22h-24h MT's (its stub's end, the kernel's ^C: end
; the program, mt_i24's prompt), not a shell's whose code goes on running
; in its own task (its ^C would go back to its prompt on this task's
; stack), and may end first; and the whole table as it is now (TX_GSN),
; with those and its 09h and 1Bh.  AX, BX, CX, SI, DI changed
mt_vnew:
        pushf
        cli
        push    bx
        call    mt_vsv
        call    mt_fvsync
        pop     bx
        call    mt_v24                  ; (TX_VEC's first three: 22h-24h)
        push    ds
        mov     al, [mt_cur]            ; its 09h and 1Bh: the spawner's (in
        cmp     al, [mt_front]          ;  mt_fv if it is in front, else in its
        jne     .o                      ;  TX)
        push    cs
        pop     ds
        mov     si, mt_fv
        jmp     short .c
.o:     call    mt_ent
        mov     ds, [bx+TE_TX]
        mov     si, TX_FVEC
.c:     mov     di, TX_FVEC
        mov     cx, MT_NFV * 2
        rep     movsw
        pop     ds
        popf                            ; (the rest with interrupts on: none of
        push    ds                      ;  the copies interrupts use)
        xor     si, si
        mov     ds, si
        mov     di, TX_GSN
        mov     cx, 1024 / 2
        rep     movsw
        push    es
        pop     ds
        mov     si, TX_VEC              ; 22h-24h, 09h and 1Bh as given above
        mov     di, TX_GSN + 22h * 4
        mov     cx, 3 * 2
        rep     movsw
        mov     si, TX_FVEC
        mov     di, TX_GSN + 09h * 4
        movsw
        movsw
        mov     di, TX_GSN + 1Bh * 4
        movsw
        movsw
        pop     ds
        ret

; INT 22h-24h for a new task (BX = its entry): in its TX (ES), TX_VEC's
; first three, and in its stub's PSP (0Ah-15h; 0Ah, its end, as set).
; AX changed
mt_v24: push    ds
        push    di
        mov     ds, [bx+TE_PSP]
        mov     ax, ST_END
        mov     [es:TX_VEC], ax
        mov     [es:TX_VEC + 2], ds
        mov     ax, int23
        mov     [es:TX_VEC + 4], ax
        mov     [0Eh], ax
        mov     ax, KSEG
        mov     [es:TX_VEC + 6], ax
        mov     [10h], ax
        mov     ax, mt_i24
        mov     [es:TX_VEC + 8], ax
        mov     [12h], ax
        mov     [es:TX_VEC + 10], cs
        mov     [14h], cs
        pop     di
        pop     ds
        ret

; the task at BX ends (mt_end, its region not yet freed): every vector
; left pointing into its region (a hook of its programs', one they never
; took away; a TSR's) put back as it was at its spawn (TX_GSN).  All kept
mt_vfix:
        pusha
        push    ds
        push    es
        mov     ax, [cs:bx+TE_REG]
        mov     [cs:mt_vr], ax
        dec     ax
        mov     es, ax
        mov     ax, [es:3]
        add     ax, [cs:mt_vr]
        mov     [cs:mt_ve], ax
        mov     ds, [cs:bx+TE_TX]       ; (its TX: not the region's start once
        mov     word [cs:mt_vsb], TX_GSN ;  it has grown)
        mov     byte [cs:mt_vtab], 1
        cld
        mov     si, TX_GSN + 09h * 4
        mov     di, mt_vfs
        call    .cp
        mov     si, TX_GSN + 1Bh * 4
        call    .cp
        call    mt_vrep
        pop     es
        pop     ds
        popa
        ret
.cp:    lodsw
        mov     [cs:di], ax
        lodsw
        mov     [cs:di+2], ax
        add     di, 4
        ret

; the task at BX ends: every program still owning memory in its arena
; (one that stayed resident, AH=31h; not the stub) has its files closed
; (if the owner is a PSP) and its EMS and memory freed, as terminate does
; for one that ends.  A damaged chain: no further.  DS = KSEG.  All kept
mt_owners:
        pusha
        push    es
        mov     dx, [cs:bx+TE_PSP]
        mov     bx, [first_mcb]         ; (the task's, running)
.l:     mov     es, bx
        mov     al, [es:0]
        cmp     al, 'M'
        je      .m
        cmp     al, 'Z'
        jne     .x
.m:     mov     ax, [es:1]
        or      ax, ax
        jz      .n
        cmp     ax, dx
        je      .n
        cmp     ax, 8
        je      .n
        push    es
        mov     es, ax                  ; a program's: its files, then its EMS
        cmp     word [es:0], 20CDh      ;  and its blocks (this one and on: the
        jne     .f                      ;  walk goes on); its end told to the UI
        KCALL   close_allt              ;  as terminate does (ui_progend: its
        push    ax                      ;  mouse handler forgotten, m33_busy
        push    bx                      ;  cleared if it ended inside it)
        push    es
        mov     bx, es
        KCALL   ui_progend
        pop     es
        pop     bx
        pop     ax
.f:     mov     ax, es
        KCALL   ems_free_owner
        pop     es
.n:     cmp     byte [es:0], 'Z'
        je      .x
        add     bx, [es:3]
        inc     bx
        jmp     .l
.x:     pop     es
        popa
        ret

; a program ends (mt_pgend, before terminate frees its blocks; its PSP at
; BX, INT 22h-24h put back from it): the other tasks' vectors pointing into
; one of its blocks (they started with them, from it or its task) as the
; running task's are now: the table's, but 09h and 1Bh behind its TX's.
; DS = KSEG.  All kept
mt_vpg: pusha
        push    ds
        push    es
        cld
        mov     dx, bx
        pushf                           ; (behind: its writes to the table's
        cli                             ;  09h, 1Bh to its TX, the table the
        call    mt_fvsync               ;  front's again)
        call    mt_fvset
        popf
        mov     bx, [first_mcb]         ; its blocks (the task's arena)
.l:     mov     es, bx
        mov     al, [es:0]
        cmp     al, 'M'
        je      .m
        cmp     al, 'Z'
        jne     .x
.m:     cmp     [es:1], dx
        jne     .n
        lea     ax, [bx+1]
        mov     [cs:mt_vr], ax
        add     ax, [es:3]
        mov     [cs:mt_ve], ax
        push    bx
        push    dx
        call    .fix
        pop     dx
        pop     bx
        mov     es, bx
.n:     cmp     byte [es:0], 'Z'
        je      .x
        add     bx, [es:3]
        inc     bx
        jmp     .l
.x:     pop     es
        pop     ds
        popa
        ret
; the block mt_vr..mt_ve.  The running task's 09h and 1Bh: behind, its
; TX's (one into the block, a write of the table's value it put back the
; table never showed: the front's, the likeliest), in front mt_fv
.fix:   mov     al, [cs:mt_cur]
        push    cs
        pop     es
        mov     di, mt_fv
        cmp     al, [cs:mt_front]
        je      .s
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        mov     di, TX_FVEC
        xor     si, si
        mov     cx, MT_NFV
.o:     call    mt_inr
        jc      .on
        mov     ax, [cs:mt_fv+si]
        mov     [es:di], ax
        mov     ax, [cs:mt_fv+si+2]
        mov     [es:di+2], ax
.on:    add     di, 4
        add     si, 4
        loop    .o
        mov     di, TX_FVEC
.s:     push    es
        pop     ds
        mov     si, di
        mov     di, mt_vfs
        call    mt_vfix.cp
        call    mt_vfix.cp
        xor     ax, ax
        mov     ds, ax                  ; (the table)
        mov     [cs:mt_vsb], ax
        mov     [cs:mt_vtab], al
        call    mt_vrep
        pushf                           ; (mt_fv, fixed, to the table)
        cli
        call    mt_fvset
        popf
        ret

; vectors pointing into mt_vr..mt_ve put back from the table at DS:mt_vsb
; (its vector N at mt_vsb + N * 4; mt_vfr's from mt_vfs): in the vector table (if mt_vtab; each
; with interrupts off), mt_fv, and the other tasks' (not the running one,
; not free ones) TX_VEC, TX_FVEC and (not task 0's) TX_GSN.  All kept but
; AX, BX, CX, DX, SI, DI, ES
mt_vrep:
        pushf
        cld
        cmp     byte [cs:mt_vtab], 0
        je      .ft
        xor     di, di
        mov     es, di
        call    .fa
.ft:    push    cs
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
        cmp     byte [cs:bx+TE_STATE], TS_PARKED
        je      .tp
        mov     es, [cs:bx+TE_TX]
        call    .one
.tn:    inc     al
        cmp     al, MT_TASKS
        jb      .t
        popf
        ret
.tp:    pushf                           ; (parked: its TX in its pages' first,
        cli                             ;  in window 0 meanwhile; its pages
        call    mt_pmap                 ;  gone, nothing)
        jc      .tq
        call    .one
        call    mt_punmap
.tq:    popf
        jmp     .tn
; task AL's TX at ES.  AL kept
.one:   push    ax
        mov     di, TX_VEC
        mov     bx, mt_vrun
        mov     cx, MT_NVEC
        call    .fx
        mov     di, TX_FVEC
        mov     bx, mt_vfr
        mov     cx, MT_NFV
        call    .fx
        pop     ax
        or      al, al                  ; (task 0's TX has no TX_GSN)
        jz      .or
        push    ax
        mov     di, TX_GSN
        call    .fa
        pop     ax
.or:    ret
; CX vectors at ES:DI, their numbers at CS:BX.  AX, BX, CX, SI, DI changed
.fx:    call    mt_inr
        jc      .fn
        mov     al, [cs:bx]
        xor     ah, ah
        shl     ax, 2
        call    .mv
.fn:    add     di, 4
        inc     bx
        loop    .fx
        ret
; a whole table at ES:DI, each one with interrupts off (and then as
; they came: one interrupt's turn between two).  AX, DX, SI, DI changed
.fa:    xor     dx, dx
.fl:    pushf
        cli
        call    mt_inr
        jc      .fm
        mov     ax, dx
        call    .mv
.fm:    popf
        add     di, 4
        add     dx, 4
        cmp     dx, 1024
        jb      .fl
        ret
; vector AX / 4 to ES:DI (DI kept): from DS:mt_vsb's table, mt_vfr's from
; mt_vfs.  AX, SI changed
.mv:    mov     si, mt_vfs
        cmp     ax, 09h * 4
        je      .mc
        mov     si, mt_vfs + 4
        cmp     ax, 1Bh * 4
        je      .mc
        mov     si, ax
        add     si, [cs:mt_vsb]
        movsw
        movsw
        sub     di, 4
        ret
.mc:    mov     ax, [cs:si]
        mov     [es:di], ax
        mov     ax, [cs:si+2]
        mov     [es:di+2], ax
        ret

;  INT 24h for a task (mt_v24): "<what> reading|writing drive X: Abort,
;  Retry, Fail?" through INT 10h's teletype and INT 16h, as a shell's
;  prompt does (it goes to the screen in front: mt_crit); the answer in AL
mt_i24: sti
        cld
        pusha
        push    ds
        push    cs
        pop     ds
        mov     dx, ax
        mov     si, s_24c
        call    .pr
        mov     si, s_24e               ; what: by the error's code (DI)
        mov     ax, di
        cmp     al, 2
        jne     .i
        mov     si, s_24n
.i:     cmp     al, 0Fh                 ; (as MS-DOS's COMMAND says it)
        jne     .w
        mov     si, s_24i
.w:     or      al, al
        jnz     .m
        mov     si, s_24w
.m:     call    .pr
        test    dh, 80h                 ; (a character device: no drive)
        jnz     .q
        mov     si, s_24r
        test    dh, 1
        jz      .rw
        mov     si, s_24wr
.rw:    call    .pr
        mov     al, dl
        add     al, 'A'
        call    .pc
.q:     mov     si, s_24q
        call    .pr
.k:     xor     ah, ah
        int     16h
        and     al, 0DFh
        mov     ah, 2
        cmp     al, 'A'
        je      .a
        mov     ah, 1
        cmp     al, 'R'
        je      .a
        mov     ah, 3
        cmp     al, 'F'
        jne     .k
.a:     push    ax
        call    .pc
        mov     si, s_24c
        call    .pr
        pop     ax
        mov     bp, sp                  ; the answer into POPA's AL (past DS)
        mov     [bp+2+14], ah
        pop     ds
        popa
        iret
        nop                             ; (never run: what follows as it was)
.pr:    lodsb
        or      al, al
        jz      .x
        call    .pc
        jmp     .pr
.x:     ret
.pc:    push    ax
        push    bx
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        pop     bx
        pop     ax
        ret
s_24c   db      13, 10, 0
s_24e   db      'Disk error', 0
s_24n   db      'Not ready', 0
s_24w   db      'Write protect error', 0
s_24i   db      'Invalid disk change', 0
s_24r   db      ' reading drive ', 0
s_24wr  db      ' writing drive ', 0
s_24q   db      ': Abort, Retry, Fail? ', 0

; the vector at ES:DI points into the region mt_vr..mt_ve, and not into
; mt_xr..mt_xe?  CF if not.  AX changed
mt_inr: mov     ax, [es:di]
        shr     ax, 4
        add     ax, [es:di+2]
        jc      .no
        cmp     ax, [cs:mt_vr]
        jb      .no
        cmp     ax, [cs:mt_ve]
        jae     .no
        cmp     ax, [cs:mt_xr]
        jb      .y
        cmp     ax, [cs:mt_xe]
        jb      .no
.y:     clc
        ret
.no:    stc
        ret

; ---------------------------------------------------------------------
;  INT 21h AH=F0h, from f_F0's first bytes: DS = SS = KSEG, BP = the frame
; ---------------------------------------------------------------------
mt_f0:  mov     al, [bp+F_AX]           ; (each handler with AL, its BX its own)
        mov     bl, al
        sub     bl, MT_SPAWN
        cmp     bl, MT_WAKE - MT_SPAWN
        ja      .own
        xor     bh, bh
        shl     bx, 1
        jmp     [cs:bx+.tab]
.own:   cmp     al, 1
        je      mt_open
.k:     or      al, al                  ; (f_F0's own two, then on there)
        jmp     KSEG:f_F0 + 5
.tab:   dw      mt_spawn, mt_end, mt_list, mt_frontc, mt_kill, mt_park
        dw      mt_unpark, mt_xcode, mt_flagsc, mt_uic, mt_tsrc, mt_bad
        dw      mt_screen, mt_winc, mt_topen, mt_trows, mt_tkey, mt_tmouse
        dw      mt_pub, mt_wake         ; (10h-23h: a new MT_* goes here too)
%if $ - .tab != 2 * (MT_WAKE - MT_SPAWN + 1)
%error "mt_f0.tab: one word a function, MT_SPAWN to MT_WAKE"
%endif
mt_bad: mov     ax, 1
mt_fail:
        jmp     KSEG:fail

; the caller's task BL, not a free one: AL = it, BX = its entry.  None
; such, or a free one: not back, the call fails (mt_bad).  Called first
; thing in a handler, nothing pushed: its return is what it drops
mt_targ:
        mov     al, [bp+F_BX]
        cmp     al, MT_TASKS
        jae     .no
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        jne     .x
.no:    pop     ax
        jmp     short mt_bad
.x:     ret
; and not task 0 nor a parked one: else not back, AX = 5 (as mt_targ)
mt_t5:  or      al, al
        jz      .no
        cmp     byte [cs:bx+TE_STATE], TS_PARKED
        jne     mt_targ.x
.no:    pop     ax
        jmp     mt_park.r5

; F0h AL=1 (files open on drive DL: DEFRAG and System ask before writing
; a disk's FAT and directories themselves): with another task there, at
; least 1, since it could open one meanwhile
mt_open:
        cmp     byte [cs:mt_cur], 0     ; (a task's: the Executive is another)
        jne     .y
        call    mt_others
        jnc     .y
        mov     al, 1                   ; (none: f_F0's own answer)
        jmp     short mt_f0.k
.y:     mov     word [bp+F_CX], 1
        jmp     KSEG:ok

; MT_EXIT: entry BL's state and count of tasks started there; the exit
; code of the last one ended there, and its count
mt_xcode:
        mov     al, [bp+F_BX]
        cmp     al, MT_TASKS
        jae     mt_bad
        call    mt_ent
        mov     al, [cs:bx+TE_STATE]
        mov     ah, [cs:bx+TE_GEN]
        mov     [bp+F_AX], ax
        mov     ax, [cs:bx+TE_EXIT]
        mov     [bp+F_DX], ax
        mov     al, [cs:bx+TE_EGEN]
        mov     [bp+F_CX], al
        jmp     KSEG:ok

; MT_FLAGS: task BL's SPF_BG and SPF_FREEZE, CL's cleared, then CH's set
; -> AL = them, and MTF_DIRECT (VF_DIRECT) as the detector last found it
mt_flagsc:
        call    mt_targ
        or      al, al                  ; (the Executive: frozen behind always,
        jz      mt_park.r5              ;  it draws in a graphics mode)
        mov     cx, [bp+F_CX]
        and     cx, (SPF_BG | SPF_FREEZE) * 101h
        not     cl
        and     [cs:bx+TE_VF], cl
        or      [cs:bx+TE_VF], ch
        mov     al, [cs:bx+TE_VF]
        mov     [bp+F_AX], al
        jmp     KSEG:ok

; MT_UI: the UI patched (KMW.INC: Return starts a task, mt_ui, and several
; window .RUNs at once)
mt_uic: push    es
        mov     es, [ui_seg]
        call    mw_patch
        pop     es
        jmp     KSEG:ok

; MT_WIN: is the UI code running a window .RUN's session (KMW.INC)?
mt_winc:
        cmp     byte [cs:mw_cur], 0
        je      mt_bad
        jmp     KSEG:ok

; MT_TOPEN: task BL, its count CL, is shown by the window .RUN that
; calls (its session, mw_cur: TERM.RUN), whose UI_EVENT gives EV_TICK from
; now on when there is something to show (mw_poll).  CF: AX = 1 (no such
; task, another count, not a window .RUN's call), 5 (task 0, parked)
mt_topen:
        cmp     byte [cs:mt_cur], 0     ; (the UI's call, not a task's)
        jne     mt_bad
        call    mt_targ
        call    mt_t5
        mov     ah, [bp+F_CX]
        cmp     ah, [cs:bx+TE_GEN]
        jne     mt_bad
        mov     dl, al
        mov     al, [cs:mw_cur]
        or      al, al
        jz      mt_bad
        push    bp
        call    mw_rec
        mov     [cs:bp+SE_TASK], dl
        mov     [cs:bp+SE_TGEN], ah
        mov     byte [cs:bp+SE_TST], 0FFh       ; (a tick at the first look)
        pop     bp
        jmp     KSEG:ok

; MT_TROWS: task BL's screen as its pages hold it, CX rows from row DX
; of the page shown, to ES:DI (inside INT 21h: none of its writes can come
; in the middle) -> AX = TX_CHG, BX = the cursor there, CL = columns, CH =
; the mode, DL = VF_DIRECT, 2 if nothing copied (not a text mode of 80
; columns or fewer, or past its 32 KB), 4 its pages gone (2 too), 8 in front
; (its pages not what is shown), 16 its program took the mouse (TX_MPSP),
; DH = its state (TS_FROZEN for one ready
; but frozen behind, as MT_LIST says).  With DH bit 7, a screen
; published and shown: its cells instead (mt_tpub)
mt_trows:
        call    mt_targ
        call    mt_t5
        mov     cx, [bp+F_CX]
        mov     dx, [bp+F_DX]
        and     dh, 7Fh                 ; (the published bit: the row in DL)
        jcxz    .bad
        add     dx, cx                  ; (rows 0-24)
        jc      .bad
        cmp     dx, 25
        ja      .bad
        mov     ax, [bp+F_DI]           ; (not where the pages go: windows 0
        cmp     ax, 10000h - 25 * 160   ;  and 1; no round to the segment's
        ja      .bad                    ;  start either)
        shr     ax, 4
        add     ax, [bp+F_ES]
        jc      .bad
        cmp     ax, EMS_FRAME + 800h
        jae     .in
        add     ax, 25 * 160 / 16 + 1
        cmp     ax, EMS_FRAME
        jbe     .in
.bad:   jmp     mt_bad
.in:    cld
        test    byte [bp+F_DX+1], 80h   ; its published cells, if shown
        jz      .pg
        mov     al, [bp+F_BX]
        call    mt_pshow
        jnc     mt_tpub
.pg:    mov     byte [cs:mt_vbusy], 1
        call    mt_vin
        push    cs
        pop     ds
        mov     dl, 6
        jc      .gone
        push    bx
        mov     dl, 2
        cmp     byte [VS_MODE], 3
        ja      .nt
        cmp     byte [VS_COLS], 80      ; (4000 bytes at most: the room)
        ja      .nt
        mov     bl, [VS_PAGE]
        mov     dh, [bp+F_DX]
        xor     dl, dl
        call    mt_vaddr
        mov     si, di
        mov     al, [VS_COLS]
        mul     byte [bp+F_CX]
        mov     cx, ax
        shl     ax, 1
        add     ax, si
        mov     dl, 2
        jc      .nt
        cmp     ax, 8000h               ; (all in the 32 KB)
        ja      .nt
        mov     es, [bp+F_ES]
        mov     di, [bp+F_DI]
        push    EMS_FRAME
        pop     ds
        rep     movsw
        push    cs
        pop     ds
        xor     dl, dl
.nt:    pop     bx
        push    dx
        call    mt_wrest
        pop     dx
.gone:  mov     byte [cs:mt_vbusy], 0   ; (CS: kept, for mt_par's parity)
        call    .dl
        call    mt_tchg
        mov     [bp+F_AX], ax
        mov     cl, [VS_COLS]
        mov     ch, [VS_MODE]
        mov     [bp+F_CX], cx
        mov     bl, [VS_PAGE]
        and     bx, 7
        shl     bx, 1
        mov     ax, [VS_CUR + bx]
        mov     [bp+F_BX], ax
        jmp     KSEG:ok                 ; (done: DS = KSEG)
; DL with VF_DIRECT, 8 in front, 16 its program took the mouse; DH its
; state: to the frame.  BX = its entry; ES = its TX after; AL changed.
; DS = CS
.dl:    mov     al, [bx+TE_VF]
        and     al, VF_DIRECT
        or      dl, al
        mov     al, [bp+F_BX]
        cmp     al, [mt_front]
        jne     .nf
        or      dl, 8
.nf:    mov     dh, [bx+TE_STATE]
        cmp     dh, TS_RUN
        jne     .st
        call    mt_frz
        jz      .st
        mov     dh, TS_FROZEN
.st:    mov     es, [bx+TE_TX]
        cmp     word [es:TX_MPSP], 0    ; (its program took the mouse)
        je      .mp
        or      dl, 16
.mp:    mov     [bp+F_DX], dx
        ret

; MT_TROWS of a screen published and shown (mt_pshow: DS:SI = its
; descriptor, ES = its TX, BX = its entry): rows of its cells to the
; caller's room (80 x 25 at most), rows past its PB_ROWS blank (0020h:
; PBA_* attributes, not a colour's) -> DL 32, CH = its rows, CL = its
; columns, BX = PB_CUR (PBF_NOCUR: its row's bit 7 set: TERM's
; view follows it, with no mark)
mt_tpub:
        mov     ax, [bp+F_SI]           ; (SI = A5h, the rows the window
        cmp     ah, 0A5h                ;  shows: to a PB_VER 2 descriptor's
        jne     .nv                     ;  PB_VIEW; else not said: an older
        or      al, al                  ;  TERM left SI as it was)
        jz      .nv
        cmp     byte [si+PB_VER], 2
        jb      .nv
        mov     [si+PB_VIEW], al
        nop                             ; (mt_par: what follows at its parity)
.nv:    mov     ax, [si+PB_CUR]
        test    byte [si+PB_FLAGS], PBF_NOCUR
        jz      .k
        or      ah, 80h
.k:     push    ax                      ; (BX's, to come)
        push    bx
        mov     bl, [si+PB_COLS]        ; BL its columns, BH its rows
        cmp     bl, 80
        jbe     .c
        mov     bl, 80
.c:     mov     bh, [si+PB_ROWS]
        cmp     bh, 25
        jbe     .r
        mov     bh, 25
.r:     mov     dl, [bp+F_DX]           ; DL the first row, DH how many
        mov     dh, [bp+F_CX]
        mov     al, bl
        mul     dl
        shl     ax, 1
        lds     si, [si+PB_CELLS]
        add     si, ax
        mov     es, [bp+F_ES]
        mov     di, [bp+F_DI]
        xor     ch, ch
.row:   mov     cl, bl
        cmp     dl, bh
        jae     .bl
        rep     movsw
        jmp     short .nx
.bl:    mov     ax, 0020h
        rep     stosw
.nx:    inc     dl
        dec     dh
        jnz     .row
        mov     cx, bx
        pop     bx
        push    cx
        push    cs
        pop     ds
        mov     dl, 32
        call    mt_trows.dl
        call    mt_tchg
        mov     [bp+F_AX], ax
        pop     word [bp+F_CX]
        pop     word [bp+F_BX]
        jmp     KSEG:ok

; Task AL (its entry BX) has a screen published and shown, and is
; behind (mt_pss) -> DS:SI = its descriptor, ES = its TX.  CF if not (ES,
; and DS and SI, changed)
mt_pshow:
        cmp     al, [cs:mt_front]
        jne     mt_pss
        stc
        ret
; task BX has a screen published (MT_PUB) and shown (PBF_SHOWN), in a text
; mode (its BIOS data's in its TX: not the front task's own) -> DS:SI = its
; descriptor, ES = its TX.  CF if not (ES, and DS and SI, changed)
mt_pss: mov     es, [cs:bx+TE_TX]
        cmp     byte [es:TX_VID], 3     ; (its mode: 40:49h's)
        ja      .no
        cmp     word [es:TX_PUB + 2], 0
        je      .no
        lds     si, [es:TX_PUB]
        test    byte [si+PB_FLAGS], PBF_SHOWN
        jz      .no
        ret                             ; (CF clear: TEST's)
.no:    stc
        ret

; AX = task BX's changes as a terminal window counts them: TX_CHG,
; and with a screen published (MT_PUB) its PB_CHG added.  Not task 0's, nor
; a parked task's.  ES = its TX
mt_tchg:
        mov     es, [cs:bx+TE_TX]
        mov     ax, [es:TX_CHG]
        cmp     word [es:TX_PUB + 2], 0
        je      .x
        push    ds
        push    si
        lds     si, [es:TX_PUB]
        add     ax, [si+PB_CHG]
        pop     si
        pop     ds
.x:     ret

; Task AL (its entry BX; not task 0, nor parked) has a screen
; published and shown, in a text mode (mt_pss), and a terminal window shows
; it (mw_owns): its window is its screen, so CODE-Tab passes over it and
; MT_FRONT refuses it.  CF if so.  All kept
mt_ispub:
        push    es
        push    ds
        push    si
        push    ax
        call    mt_pss
        cmc                             ; (not so: CF clear)
        jnc     .x
        mov     ah, [cs:bx+TE_GEN]
        call    mw_owns                 ; (CF: no window shows it)
        cmc
.x:     pop     ax
        pop     si
        pop     ds
        pop     es
        ret

; MT_WAKE: BL bit 0, the calling program woken by SRQ (MTAPI.INC)
mt_wake:
        mov     al, [cs:mt_cur]
        mov     dx, [cur_psp]
        test    byte [bp+F_BX], 1
        jz      .off
        mov     [cs:mt_wkp], dx         ; (the PSP first: mt_srqi reads only
        mov     [cs:mt_wkt], al         ;  the task)
        jmp     short .r
.off:   call    mt_wkme                 ; (its own only)
.r:     mov     al, [gp_irq]
        xor     ah, ah
        jmp     KSEG:ok_ax

; the wake (MT_WAKE) ended if it is the program at DX's in the running
; task (the task too: a PSP in a parked task's old place may be another's
; now).  AL changed.  .t: task AL's, whatever program (mt_kill: a parked
; task whose pages are gone); all kept
mt_wkme:
        mov     al, [cs:mt_cur]
        cmp     dx, [cs:mt_wkp]
        jne     .x
.t:     cmp     al, [cs:mt_wkt]
        jne     .x
        mov     byte [cs:mt_wkt], 0FFh
.x:     ret

; MT_PUB.  CL = 0, the running task's program: ES:DI its screen's
; descriptor (0:0 withdraws one), it and its cells, font and table all in
; the task's memory (mt_pin) and its fields in range; another than it
; gave before counted as a change (TX_CHG: one more than a window saw) ->
; AL = 1 if a terminal window shows the task (mw_owns), AH = the task; one
; in front then with its screen shown, in a text mode, goes back to its
; window (CODE-Tab took it there while its pages were shown).  CL = 1
; (task 0's call): task BL's descriptor -> ES:DI
mt_pub: mov     cl, [bp+F_CX]
        cmp     cl, 1
        je      .get
        ja      .bad
        mov     al, [cs:mt_cur]
        or      al, al
        jz      mt_park.r5
        mov     es, [bp+F_ES]
        mov     di, [bp+F_DI]
        mov     ax, es
        or      ax, di
        jz      .set                    ; (0:0: withdrawn)
        mov     dx, es
        mov     ax, di
        mov     cx, PB_SIZE
        cmp     byte [es:di+PB_VER], 2  ; (2's PB_VIEW, MT writes it)
        jb      .v1
        inc     cx
.v1:    call    mt_pin
        jc      .bd
        cmp     byte [es:di+PB_VER], 1
        jb      .bd
        mov     al, [es:di+PB_COLS]     ; (1-80: 0-79 less 1)
        dec     al
        cmp     al, 80
        jae     .bd
        mov     ah, [es:di+PB_ROWS]
        dec     ah
        cmp     ah, 25
        jae     .bd
        cmp     byte [es:di+PB_FIRST], 20h
        ja      .bd
        mov     cl, [es:di+PB_GEND]
        cmp     cl, 40h
        jb      .bd
        sub     cl, [es:di+PB_FIRST]    ; the font: 16 bytes a code
        xor     ch, ch
        shl     cx, 4
        push    ax
        mov     ax, [es:di+PB_FONT]
        mov     dx, [es:di+PB_FONT + 2]
        call    mt_pin
        pop     ax
        jc      .bd
        add     ax, 101h                ; the cells: a word each
        mul     ah
        shl     ax, 1
        xchg    ax, cx
        mov     ax, [es:di+PB_CELLS]
        mov     dx, [es:di+PB_CELLS + 2]
        call    mt_pin
        jc      .bd
        mov     ax, [es:di+PB_XLAT]
        mov     dx, [es:di+PB_XLAT + 2]
        mov     cx, ax
        or      cx, dx
        jz      .set                    ; (none)
        mov     cx, 128
        call    mt_pin
        jc      .bd
.set:   call    mt_cent
        mov     dx, es                  ; (DX:DI the new one)
        call    mt_tchg                 ; (AX: its count as a window saw it)
        cmp     di, [es:TX_PUB]
        jne     .ch
        cmp     dx, [es:TX_PUB + 2]
        je      .s
.ch:    inc     ax                      ; another: its count one up from what
        mov     cx, dx                  ;  a window saw, whatever the new
        or      cx, di                  ;  one's PB_CHG (TX_CHG less it)
        jz      .c0
        push    ds
        mov     ds, dx
        sub     ax, [di+PB_CHG]
        pop     ds
.c0:    mov     [es:TX_CHG], ax
.s:     mov     [es:TX_PUB], di
        mov     [es:TX_PUB + 2], dx
        or      dx, di
        jz      .p                      ; (withdrawn: no program's)
        mov     dx, [cur_psp]
.p:     mov     [es:TX_PPSP], dx
        mov     al, [cs:mt_cur]
        mov     ah, [cs:bx+TE_GEN]
        call    mw_owns
        mov     ah, al
        mov     al, 0
        jc      .r
        inc     ax                      ; (a window shows it)
        cmp     ah, [cs:mt_front]       ; in front (CODE-Tab took it there while
        jne     .r                      ;  its pages were shown), its screen
        xchg    al, ah                  ;  shown, in a text mode (the BIOS's:
        call    mt_ispub                ;  40:49h): back to its window, task 0
        xchg    al, ah                  ;  in front again
        jnc     .r
        push    40h
        pop     es
        cmp     byte [es:49h], 3
        ja      .r
        mov     byte [cs:mt_swreq], 0
.r:     mov     [bp+F_AX], ax
        jmp     KSEG:ok
.bd:    mov     ax, 0Dh
        jmp     mt_fail
.bad:   jmp     mt_bad
.get:   cmp     byte [cs:mt_cur], 0     ; (the UI's call, not a task's)
        jne     .bad
        call    mt_targ
        call    mt_t5
        mov     es, [cs:bx+TE_TX]
        les     di, [es:TX_PUB]
        mov     [bp+F_DI], di
        mov     [bp+F_ES], es
        jmp     KSEG:ok

; CX bytes (1 or more) at DX:AX all in the running task's memory
; (mt_mine: its region; its first and last byte's paragraphs)?  CF if not.
; DS = KSEG; AX, BX, DX changed
mt_pin:
        mov     bx, ax
        dec     cx                      ; (its last byte: no wrap past the
        add     ax, cx                  ;  segment's end)
        inc     cx                      ; (CF kept)
        jc      .no
        shr     ax, 4
        add     ax, dx
        jc      .no
        shr     bx, 4                   ; (its first byte's: no carry, as the
        add     bx, dx                  ;  last's had none)
        push    bx
        call    mt_mine
        pop     ax
        jc      .no
        jmp     mt_mine
.no:    stc
        ret

; MT_TKEY: key CX typed to task BL: into its TX's ring (KRING), for
; its INT 16h (mt_ring), and it is ready to run if it waited for one.  CF:
; AX = 1 (no such task), 5 (task 0, parked), 8 (KRING waiting already)
mt_tkey:
        call    mt_targ
        call    mt_t5
        mov     es, [cs:bx+TE_TX]
        pushf
        cli
        mov     al, [es:TX_KN]
        cmp     al, KRING
        jae     .full
        add     al, [es:TX_KH]
        and     ax, KRING - 1
        mov     di, ax
        shl     di, 1
        mov     ax, [bp+F_CX]
        mov     [es:TX_KR + di], ax
        inc     byte [es:TX_KN]
        cmp     byte [cs:bx+TE_STATE], TS_WAITK
        jne     .ok
        mov     byte [cs:bx+TE_STATE], TS_RUN
        mov     byte [cs:mt_pend], 1    ; (its turn soon: from this call's way
.ok:    popf                            ;  out, as MT_KILL's)
        jmp     KSEG:ok
.full:  popf
        jmp     mt_spawn.room           ; (AX = 8)

; MT_TMOUSE: a click in task BL's window, as TERM sees it: buttons BH
; at CX, DX (INT 33h's units), to its own state (TX_M33) as a packet would
; leave it (mt_mset), for its calls behind.  A release before it has read
; the press is held till it has (mt_33out; mt_m33ld, to the front), so a
; short click isn't lost between its turns.  CF: AX = 1 (no such task;
; not the Executive's call), 5 (task 0, parked)
mt_tmouse:
        cmp     byte [cs:mt_cur], 0     ; (the UI's call, not a task's)
        jne     mt_bad
        call    mt_targ
        call    mt_t5
        mov     es, [cs:bx+TE_TX]
        pushf
        cli
        call    mt_mheld                ; (one held: first)
        mov     al, [bp+F_BX+1]
        and     al, 3
        mov     cx, [bp+F_CX]
        mov     dx, [bp+F_DX]
        mov     ah, al
        not     ah
        test    [es:TX_M33 + m33_btn - m33_st], ah      ; (one let go?)
        jz      .s
        test    byte [es:TX_MREL], 80h  ; and its press not read yet: held
        jz      .s
        or      al, 40h
        or      [es:TX_MREL], al
        mov     [es:TX_MRX], cx
        mov     [es:TX_MRY], dx
        jmp     short .ok
.s:     call    mt_mset
.ok:    popf
        jmp     KSEG:ok

; a release held (TX_MREL 40h) to the task's state now, its press taken as
; read (ES = its TX, interrupts off).  All kept
mt_mheld:
        test    byte [es:TX_MREL], 40h
        jz      .x
        push    ax
        push    cx
        push    dx
        mov     al, [es:TX_MREL]
        and     al, 3
        mov     cx, [es:TX_MRX]
        mov     dx, [es:TX_MRY]
        mov     byte [es:TX_MREL], 0
        call    mt_mset
        pop     dx
        pop     cx
        pop     ax
.x:     ret

; the task's INT 33h state (ES = its TX) as the driver's packet leaves it
; (m33_pkt): buttons AL at CX, DX, in its ranges; each button's press or
; release counted, and where (05h, 06h); a press marked not read yet
; (TX_MREL 80h).  All kept
%define M3(f) TX_M33 + f - m33_st
mt_mset:
        pusha
        cmp     cx, [es:M3(m33_xmin)]
        jge     .x1
        mov     cx, [es:M3(m33_xmin)]
.x1:    cmp     cx, [es:M3(m33_xmax)]
        jle     .x2
        mov     cx, [es:M3(m33_xmax)]
.x2:    cmp     dx, [es:M3(m33_ymin)]
        jge     .y1
        mov     dx, [es:M3(m33_ymin)]
.y1:    cmp     dx, [es:M3(m33_ymax)]
        jle     .y2
        mov     dx, [es:M3(m33_ymax)]
.y2:    mov     [es:M3(m33_x)], cx
        mov     [es:M3(m33_y)], dx
        mov     ah, [es:M3(m33_btn)]
        mov     [es:M3(m33_btn)], al
        xor     ah, al                  ; AH = the buttons that changed
        xor     bx, bx
.b:     test    ah, 1
        jz      .nb
        mov     si, M3(m33_nr)
        test    al, 1
        jz      .r
        mov     si, M3(m33_np)
        or      byte [es:TX_MREL], 80h
.r:     inc     word [es:si + bx]
        mov     [es:si + bx + 4], cx
        mov     [es:si + bx + 8], dx
.nb:    shr     ax, 1                   ; next button (AL and AH both)
        add     bx, 2
        cmp     bx, 4
        jb      .b
        popa
        ret

; the running task's keys from MT_TKEY (its TX's ring; task 0 has none),
; but none while the kernel's INT 24h prompt, a call MT passed on to the
; BIOS, an INT 13h call or an interrupt is under way, as mt_i16 tells
; them: the keyboard's then.  CF if none;
; else AX = the first, taken out if DH is not 0; DL not 0: first those
; INT 16h AH=00h and 01h don't give are dropped (mt_kgive).  AX changed
mt_ring:
        push    es
        push    bx
        mov     al, [cs:mt_cur]
        or      al, al
        jz      .no
        pushf
        cli
        push    ax
        call    mt_busy                 ; (the PIC asked with interrupts off)
        pop     ax
        jnz     .none
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
.l:     cmp     byte [es:TX_KN], 0
        je      .none
        mov     bl, [es:TX_KH]
        xor     bh, bh
        shl     bx, 1
        mov     ax, [es:TX_KR + bx]
        or      dl, dl
        jz      .got
        call    mt_kgive
        jnc     .got
        call    .out
        jmp     short .l
.got:   or      dh, dh
        jz      .k
        call    .out
.k:     popf
        clc
        jmp     short .x
.none:  popf
.no:    stc
.x:     pop     bx
        pop     es
        ret
.out:   inc     byte [es:TX_KH]
        and     byte [es:TX_KH], KRING - 1
        dec     byte [es:TX_KN]
        ret

; MT_TSR: Resident Claude's key wait, where it may be switched from
; (mt_safe), and where it finds whose call it is (mt_front, mt_cur)
mt_tsrc:
        mov     ax, [bp+F_BX]
        mov     [cs:mt_tsro], ax
        mov     ax, [bp+F_ES]
        mov     [cs:mt_tsrs], ax
        mov     byte [cs:mt_tsrk], 0
        mov     word [bp+F_AX], mt_front
        mov     [bp+F_DX], cs
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
        cmp     ah, TS_WAITD            ; (a floppy owner's wait: as running)
        jne     .r
        mov     ah, TS_RUN
.r:     cmp     ah, TS_RUN              ; (ready but frozen behind: listed as
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
; or a key wait: mt_swnow).  Not one whose window is its screen
; (mt_ispub)
mt_frontc:
        call    mt_targ
        cmp     byte [cs:bx+TE_STATE], TS_PARKED
        je      mt_park.r5
        or      al, al
        jz      .f
        call    mt_ispub
        jc      mt_park.r5
.f:     mov     [cs:mt_swreq], al
        jmp     KSEG:ok

; MT_KILL: task BL ended, whatever runs in it.  Another task: where it would
; go on, mt_switch's return, becomes mt_kdie, which ends it when it next
; runs (no code of its programs' runs again); waiting, it is ready now, and
; frozen behind it runs all the same (mt_pick).  The caller's own: now, or
; from its next safe point
mt_kill:
        call    mt_targ
        or      al, al
        jz      mt_park.r5
        cmp     byte [cs:bx+TE_STATE], TS_PARKED
        jne     .k
        push    ax
        call    mt_pchk                 ; (its pages gone: .gone)
        pop     ax
        jc      .gone
        push    ds
        push    cs                      ; (mt_up: DS = CS)
        pop     ds
        call    mt_up                   ; (parked: back first, then as any)
        pop     ds
        jc      mt_fail
.k:     mov     byte [cs:bx+TE_KILL], 1
        cmp     al, [cs:mt_cur]
        jne     .o
        call    mt_kok                  ; its own: now, unless the call came
        je      mt_kdie                 ;  from where it can't end (mt_kok):
.df:    jmp     short .p                ;  then where it next can be (mt_switch,
                                        ;  mt_preempt, a wait with none other)
.o:     mov     byte [cs:bx+TE_STATE], TS_RUN
        mov     es, [cs:bx+TE_TX]
        cmp     word [es:TX_KLEN], 0    ; (switched from inside INT 21h: the
        je      .st                     ;  return in its kernel stack's slice)
        mov     word [es:TX_KSTK + SW_RET], mt_kdie
        jmp     short .p
.st:    mov     di, [es:TX_SP]          ; (else on its own stack; a new task's:
        mov     es, [es:TX_SS]          ;  mt_first's place)
        mov     word [es:di + SW_RET], mt_kdie
.p:     mov     byte [cs:mt_pend], 1    ; (its turn soon: from this call's way
.ok:    jmp     KSEG:ok                 ;  out, if the caller is at a safe point)
.gone:  stc                             ; parked, its pages gone: its programs'
        call    mt_hshow.f              ;  EMS and its wake freed, then the
        call    mt_wkme.t               ;  handle DX if still MT's
        or      dl, dl
        jz      .g
        mov     ax, cs
        cmp     [ems_h + si + 2], ax
        jne     .g
        call    mt_hfree
.g:     mov     ax, 0100h               ; (MT_KILL's: ^C's)
        call    mt_ended
        call    mt_tfree
        jmp     short .ok

; ZF if the running task can end here, at mt_kdie: not from an interrupt's
; handler (one in service, the mouse's event handler), an INT 24h handler
; or a call MT passed on (mt_can).  DS = KSEG; AX changed
mt_kok: call    mt_can
        jnc     mt_b33                  ; (m33_busy; then mt_busy's tests, which
                                        ;  mt_can ran: a rare path)
        or      sp, sp                  ; (NZ)
        ret

; MT_PARK: task BL's region to EMS, given back (mt_pk: DS = CS)
mt_park:
        push    cs
        pop     ds
        call    mt_targ
        call    mt_pk
        jc      mt_fail
        jmp     KSEG:ok
.r5:    mov     ax, 5
        jmp     mt_fail

; MT_UNPARK: parked task BL's region back where it was (mt_up: DS = CS)
mt_unpark:
        push    cs
        pop     ds
        call    mt_targ                 ; (a free one: not parked either)
        cmp     byte [bx+TE_STATE], TS_PARKED
        jne     mt_bad
        call    mt_up
        jc      mt_fail
        jmp     KSEG:ok

; task AL (its entry at BX, not free) parked: its region copied to pages
; of MT's own (their owner MT's segment, which no PSP has: no program's end
; takes them, and mt_pchk knows them from any other's) and freed.  Not task
; 0, the running one, the one in front, one being ended or parked
; already, nor one a vector points into (mt_pinned): AX = 5.  Not enough
; EMS: AX = 8.  CF then, nothing changed.  DS = CS (so do mt_pinned,
; mt_hnew and mt_phfree; the kernel's ems_h through SS:); AL, BX kept
mt_pk:  push    cx
        push    dx
        push    es
        push    ax
        mov     cx, 5
        or      al, al
        jz      .no
        cmp     al, [mt_cur]
        je      .no
        cmp     al, [mt_front]
        je      .no
        cmp     byte [bx+TE_KILL], 0
        jne     .no
        cmp     byte [bx+TE_STATE], TS_PARKED
        je      .no
        mov     dx, [bx+TE_REG]         ; the region and its paragraphs
        mov     [mt_vr], dx
        dec     dx
        mov     es, dx
        mov     dx, [es:3]
        mov     [bx+TE_PSZ], dx
        add     dx, [mt_vr]
        mov     [mt_ve], dx
        call    mt_pinned
        jc      .no
        mov     cx, 8
        push    bx                      ; its pages (16 KB: 1,024 paragraphs)
        mov     bx, [bx+TE_PSZ]
        add     bx, 1023
        shr     bx, 10
        mov     ah, 43h
        int     67h
        pop     bx
        or      ah, ah
        jnz     .no
        call    mt_hnew                 ; (no other entry keeps that handle)
        mov     [bx+TE_PH], dl
        push    bx                      ; (its owner: MT's segment)
        mov     bl, dl
        xor     bh, bh
        shl     bx, 2
        mov     [ss:ems_h + bx + 2], cs
        pop     bx
        xor     al, al                  ; the region to them
        call    mt_move
        jc      .fr
        pop     ax                      ; its programs' EMS kept from their
        push    ax                      ;  namesakes meanwhile (mt_hhide)
        call    mt_hhide
        mov     ax, [bx+TE_REG]         ; and the region freed
        dec     ax
        mov     es, ax
        mov     word [es:1], 0
        mov     al, [bx+TE_STATE]
        mov     [bx+TE_PST], al
        mov     byte [bx+TE_STATE], TS_PARKED
        pop     ax                      ; (asked to the front: mt_swnow passes
        pop     es                      ;  it by)
        pop     dx
        pop     cx
        clc
        ret
.fr:    call    mt_phfree               ; (the copy failed: its pages back)
.no:    pop     ax
        mov     ax, cx
        pop     es
        pop     dx
        pop     cx
        stc
        ret

; parked task AL (its entry at BX) back: its region where it was (tasks
; in the way parked first: mt_take, mt_pk), copied back from its pages,
; which go back, and its state as before it was parked.  CF: AX = 8 (the
; place has memory in it not a task's, or a task's that can't be parked;
; or its pages are gone); tasks parked on the way stay parked.  DS = CS
; (so does mt_take); AL, BX kept
mt_up:  push    cx
        push    dx
        push    si
        push    es
        push    ax
        mov     cx, 8
        call    mt_pchk
        jc      .no
.t:     call    mt_take
        jnc     .got
        cmp     al, 0FFh
        je      .no
        push    bx                      ; (task AL in the way: parked)
        call    mt_ent
        call    mt_pk
        pop     bx
        jnc     .t
        jmp     short .no
.got:   mov     al, 1                   ; the region back
        call    mt_move
        jc      .bad
        mov     dx, [bx+TE_REG]         ; its MCB: the system's, "T1".."T7"
        dec     dx
        mov     es, dx
        pop     ax
        push    ax
        add     al, '0'
        mov     ch, al
        mov     cl, 'T'
        call    mt_mcbnm
        pop     ax                      ; its programs' EMS theirs again
        push    ax
        call    mt_hshow
        call    mt_phfree               ; its pages given back
        mov     al, [bx+TE_PST]
        mov     [bx+TE_STATE], al
        pop     ax
        pop     es
        pop     si
        pop     dx
        pop     cx
        clc
        ret
.bad:   mov     dx, [bx+TE_REG]         ; (the copy failed: the place freed
        dec     dx                      ;  again, it stays parked)
        mov     es, dx
        mov     word [es:1], 0
.no:    pop     ax
        mov     ax, cx
        pop     es
        pop     si
        pop     dx
        pop     cx
        stc
        ret

; the pages of the parked region at entry BX (TE_PH) given back.  AX, DX
; changed
mt_phfree:
        mov     dl, [bx+TE_PH]
        xor     dh, dh
        mov     ah, 45h
        int     67h
        mov     byte [bx+TE_PH], 0
        ret

; the MCB at ES named CX, the rest of its name cleared.  CX = 0 after
mt_mcbnm:
        mov     [es:8], cx
        xor     cx, cx
        mov     [es:10], cx
        mov     [es:12], cx
        mov     [es:14], cx
        ret

; the region of the entry at BX (TE_REG, TE_PSZ) taken where it was: the
; free block holding it (the arena walked from mt_mcb0, free neighbours
; merged, as in mt_carve) split round it; its MCB owner 8 ("T" and the
; task: mt_up's).  CF if something is in the way: AL = the task whose
; region it is, or FFh (memory not a task's).  BX kept
mt_take:
        push    cx
        push    dx
        push    si
        push    di
        push    es
        mov     si, [bx+TE_REG]
        dec     si                      ; SI: its MCB's place
        mov     di, si
        add     di, [bx+TE_PSZ]
        inc     di                      ; DI: just past it
        mov     ax, [mt_mcb0]
.w:     mov     es, ax
        mov     cl, [es:0]              ; (a chain gone bad: no)
        cmp     cl, 'M'
        je      .w1
        cmp     cl, 'Z'
        jne     .oth
.w1:    cmp     word [es:1], 0
        jne     .e
        KCALL   mem_merge               ; free: the free ones after it merged
.e:     mov     cx, ax
        add     cx, [es:3]
        inc     cx                      ; CX: just past this block
        cmp     cx, si
        jbe     .nx                     ; (below the place)
        cmp     ax, di
        jae     .oth                    ; (past it: can't be)
        cmp     word [es:1], 0
        jne     .in                     ; in the way
        cmp     ax, si
        ja      .oth                    ; (can't be: the one before had it)
        cmp     cx, di
        jb      .nx                     ; (free, but what follows is in the way)
        mov     dl, [es:0]              ; the place in it: what is below it
        cmp     ax, si                  ;  stays free
        je      .h
        mov     byte [es:0], 'M'
        push    si
        sub     si, ax
        dec     si
        mov     [es:3], si
        pop     si
.h:     mov     es, si                  ; the region
        mov     byte [es:0], 'M'
        mov     word [es:1], 8
        mov     ax, di
        sub     ax, si
        dec     ax
        mov     [es:3], ax
        cmp     cx, di
        je      .z
        mov     es, di                  ; what is above it stays free
        mov     [es:0], dl
        mov     word [es:1], 0
        sub     cx, di
        dec     cx
        mov     [es:3], cx
        clc
        jmp     short .x
.z:     mov     [es:0], dl              ; (the end of it: the region's letter)
        clc
        jmp     short .x
.nx:    cmp     byte [es:0], 'Z'
        je      .oth
        mov     ax, cx
        jmp     .w
.in:    cmp     word [es:1], 8          ; a task's region ("T1".."T7", that
        jne     .oth                    ;  task's, resident)?
        cmp     byte [es:8], 'T'
        jne     .oth
        mov     al, [es:9]
        sub     al, '1'
        cmp     al, MT_TASKS - 1
        jae     .oth
        inc     al
        push    bx
        call    mt_ent
        mov     cx, es
        inc     cx
        cmp     [bx+TE_REG], cx
        jne     .ob
        cmp     byte [bx+TE_STATE], TS_FREE
        je      .ob
        cmp     byte [bx+TE_STATE], TS_PARKED
        je      .ob
        pop     bx
        stc
        jmp     short .x
.ob:    pop     bx
.oth:   mov     al, 0FFh
        stc
.x:     pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        ret

; the region of the entry at BX to its pages (AL = 0) or back (AL = 1),
; INT 67h AH=57h (interrupts on as it copies; meanwhile an interrupt's INT
; 10h goes to the BIOS: mt_vbusy).  Its TX at their start (mt_pmap reads
; it there): a region that has grown goes from its TX to its end,
; then what is below the TX after that.  CF if it failed.  All kept but
; the flags
mt_move:
        pusha
        push    ds
        push    cs
        pop     ds
        mov     dx, [bx+TE_REG]         ; from the TX to the end, to page 0
        add     dx, [bx+TE_PSZ]
        mov     cx, [bx+TE_TX]
        sub     dx, cx
        xor     di, di
        call    .one
        jc      .x
        mov     dx, [bx+TE_TX]          ; then below it (grown), after that
        mov     di, [bx+TE_REG]
        sub     dx, di
        jz      .x                      ; (CF clear)
        mov     cx, di
        mov     di, [bx+TE_PSZ]
        sub     di, dx
        call    .one
.x:     pop     ds
        popa
        ret
; DX paragraphs at segment CX, to (AL = 0) or from (1) paragraph DI of
; its pages.  CF if it failed.  AH, DX, SI changed
.one:   push    di
        mov     si, dx                  ; the length: paragraphs * 16
        shl     si, 4
        mov     [mt_mv], si
        shr     dx, 12
        mov     [mt_mv + 2], dx
        mov     si, mt_mvs              ; conventional memory: the source (to
        mov     di, mt_mvd              ;  its pages) or the destination
        or      al, al
        jz      .c
        xchg    si, di
.c:     mov     byte [si], 0
        mov     word [si + 1], 0
        mov     word [si + 3], 0
        mov     [si + 5], cx
        mov     si, di                  ; its pages: the other side, page
        pop     di                      ;  DI / 1,024, its offset the rest
        mov     byte [si], 1
        mov     dl, [bx+TE_PH]
        xor     dh, dh
        mov     [si + 1], dx
        mov     dx, di
        and     dx, 3FFh
        shl     dx, 4
        mov     [si + 3], dx
        mov     dx, di
        shr     dx, 10
        mov     [si + 5], dx
        mov     si, mt_mv
        mov     dl, 1
        xchg    dl, [mt_vbusy]
        push    ax
        mov     ax, 5700h
        int     67h
        mov     [mt_vbusy], dl
        neg     ah                      ; (CF if AH isn't 0)
        pop     ax
        ret

; task AL (its entry at BX) parked: the EMS handles whose owner is a PSP
; in its region (its programs') get owner FFFFh, which no PSP has, the
; owner kept in mt_hown and the task in mt_hold.  Else a program run in
; its place meanwhile, at the same segment (a task there is laid out as it
; was), would free them at its end (terminate's ems_free_owner, mt_owners).
; All kept
mt_hhide:
        pusha
        push    ds
        pushf
        cli
        push    KSEG
        pop     ds
        mov     cx, [cs:bx+TE_REG]
        mov     dx, cx
        add     dx, [cs:bx+TE_PSZ]
        xor     di, di                  ; (handle 0: the system's)
.l:     inc     di
        cmp     di, EMS_NH
        jae     .x
        mov     si, di
        shl     si, 2
        cmp     byte [ems_h + si], 0FFh ; (closed)
        je      .l
        mov     bp, [ems_h + si + 2]
        cmp     bp, cx
        jb      .l
        cmp     bp, dx
        jae     .l
        mov     [cs:mt_hold + di], al
        mov     word [ems_h + si + 2], 0FFFFh
        shl     di, 1
        mov     [cs:mt_hown + di], bp
        shr     di, 1
        jmp     .l
.x:     popf
        pop     ds
        popa
        ret

; task AL back: the handles mt_hhide kept for it their owners' again (one
; that isn't FFFFh any more was freed meanwhile, maybe given out again:
; not touched).  .f with CF: freed instead (its pages gone: mt_kill).
; All kept
mt_hshow:
        clc
.f:     pusha
        push    ds
        pushf
        sbb     cx, cx                  ; (CX: FFFFh, freed)
        cli
        push    KSEG
        pop     ds
        xor     di, di
.l:     inc     di
        cmp     di, EMS_NH
        jae     .x
        cmp     [cs:mt_hold + di], al
        jne     .l
        mov     byte [cs:mt_hold + di], 0
        mov     si, di
        shl     si, 2
        cmp     byte [ems_h + si], 0FFh
        je      .l
        cmp     word [ems_h + si + 2], 0FFFFh
        jne     .l
        jcxz    .o
        call    mt_hfree
        jmp     .l
.o:     shl     di, 1
        mov     bp, [cs:mt_hown + di]
        shr     di, 1
        mov     [ems_h + si + 2], bp
        jmp     .l
.x:     popf
        pop     ds
        popa
        ret

; CF if the parked region of the entry at BX has gone from its pages: its
; handle closed, not MT's (its owner MT's segment: mt_pk), or not of its
; size (a program freed it, and it was given out again).  DX = the handle,
; SI = its record (at KSEG:ems_h + SI), either way.  AX changed
mt_pchk:
        xor     dx, dx
        mov     dl, [cs:bx+TE_PH]
        mov     si, dx
        shl     si, 2
        or      dl, dl
        jz      .no
        push    ds
        push    KSEG
        pop     ds
        mov     ax, [cs:bx+TE_PSZ]
        add     ax, 1023
        shr     ax, 10
        cmp     byte [ems_h + si], 0FFh
        je      .nd
        push    ax
        mov     ax, cs
        cmp     [ems_h + si + 2], ax
        pop     ax
        jne     .nd
        cmp     [ems_h + si + 1], al
        jne     .nd
        pop     ds
        clc
        ret
.nd:    pop     ds
.no:    stc
        ret

; window 0: the first page of the parked region of the entry at BX (its
; TX: at EMS_FRAME:0) -> ES = EMS_FRAME, window 0's page register kept in
; mt_psv (mt_punmap puts it back), and its own region mt_inr's to pass by
; (its own vectors may point into it; another task may be there now).
; CF if its pages are gone (mt_pchk), nothing changed.  Interrupts off.  All kept but ES and the flags;
; mt_punmap keeps all
mt_pmap:
        push    ds
        push    si
        push    ax
        push    dx
        call    mt_pchk
        jc      .x
        push    KSEG
        pop     ds
        mov     al, [ems_h + si]        ; (its run's start)
        xor     ah, ah
        mov     si, ax
        mov     dx, EMS_PORT
        in      al, dx
        mov     [cs:mt_psv], al
        mov     al, [ems_ltab + si]
        call    mt_eout
        push    EMS_FRAME
        pop     es
        mov     ax, [cs:bx+TE_REG]      ; (its own region: mt_inr passes it by)
        mov     [cs:mt_xr], ax
        add     ax, [cs:bx+TE_PSZ]
        mov     [cs:mt_xe], ax
        clc
.x:     pop     dx
        pop     ax
        pop     si
        pop     ds
        ret
mt_punmap:
        push    ax
        push    dx
        mov     dx, EMS_PORT
        mov     al, [cs:mt_psv]
        call    mt_eout
        mov     word [cs:mt_xr], 0
        mov     word [cs:mt_xe], 0
        pop     dx
        pop     ax
        ret

; DL = a handle MT was just given: no entry keeps it as its screen's or
; its parked region's (its own freed by a program, given out again: it
; has none now).  All kept
mt_hnew:
        push    ax
        push    bx
        xor     al, al
.l:     call    mt_ent
        cmp     [bx+TE_SH], dl
        jne     .p
        mov     word [bx+TE_SH], 0
.p:     cmp     [bx+TE_PH], dl
        jne     .n
        mov     byte [bx+TE_PH], 0
.n:     inc     al
        cmp     al, MT_TASKS
        jb      .l
        pop     bx
        pop     ax
        ret

; CF if a vector points into mt_vr..mt_ve (the region of the entry at
; BX): in the table (each with interrupts off), mt_fv, or another task's
; own: its TX_VEC and TX_FVEC (the running one's TX_VEC are the table's;
; its TX_FVEC, if it is behind), and in its TX_GSN the machine's (not a
; task's own: those are put back from its TX at its end).  A parked
; task's TX through window 0 (mt_pmap), interrupts off.  All kept
mt_pinned:
        pusha
        push    es
        cld
        mov     bp, bx                  ; (the one asked about)
        xor     di, di
        mov     es, di
        mov     cx, 256
        call    .sc
        jc      .x
        push    cs
        pop     es
        mov     di, mt_fv
        mov     cx, MT_NFV
        call    .sc
        jc      .x
        xor     al, al
.t:     cmp     al, [mt_cur]
        je      .tc
        call    mt_ent
        cmp     bx, bp
        je      .tn
        cmp     byte [bx+TE_STATE], TS_FREE
        je      .tn
        cmp     byte [bx+TE_STATE], TS_PARKED
        je      .tp
        mov     es, [bx+TE_TX]
        call    .tx
        jc      .x
.tn:    inc     al
        cmp     al, MT_TASKS
        jb      .t
        clc
.x:     pop     es
        popa
        ret
.tp:    pushf
        cli
        call    mt_pmap
        cmc
        jnc     .tq                     ; (its pages gone: nothing to see)
        call    .tx
        call    mt_punmap
.tq:    sbb     si, si                  ; (CF: SI = FFFFh)
        popf
        neg     si
        jc      .x
        jmp     .tn
.tc:    call    mt_ent                  ; the running one (never parked)
        mov     es, [bx+TE_TX]
        cmp     al, [mt_front]
        je      .tg
        push    ax                      ; behind: its own 09h and 1Bh
        mov     di, TX_FVEC
        mov     cx, MT_NFV
        call    .sc
        pop     ax
        jc      .x
.tg:    call    .gs
        jc      .x
        jmp     .tn
; task AL's TX at ES -> CF if one there.  AL kept
.tx:    push    ax
        mov     di, TX_VEC              ; (TX_FVEC just after it)
        mov     cx, MT_NVEC + MT_NFV
        call    .sc
        pop     ax
        jc      .tr0
; its TX_GSN's (task AL's TX at ES): CF if one there.  AL kept
.gs:    push    ax
        or      al, al                  ; (task 0's has no TX_GSN)
        jz      .tr
        mov     di, TX_GSN
        xor     dx, dx
.g:     call    mt_own
        jc      .gn
        call    mt_inr
        jnc     .gy
.gn:    add     di, 4
        inc     dl
        jnz     .g
        clc
.tr:    pop     ax
.tr0:   ret
.gy:    stc
        jmp     .tr
; CX vectors at ES:DI, each with interrupts off (a hook's change can't be
; half read) -> CF if one points there.  AX, CX, DI changed
.sc:    pushf
        cli
        call    mt_inr
        jnc     .y
        popf
        add     di, 4
        loop    .sc
        clc
        ret
.y:     popf
        stc
        ret

; CF if vector DL is a task's own (mt_vrun's, mt_vfr's).  All kept but
; the flags
mt_own: push    ax
        push    cx
        push    di
        push    es
        push    cs
        pop     es
        mov     al, dl
        mov     di, mt_vrun
        mov     cx, MT_NVEC + MT_NFV    ; (mt_vfr just after it)
        repne   scasb
        stc
        je      .x
        clc
.x:     pop     es
        pop     di
        pop     cx
        pop     ax
        ret

; a task MT_KILL ended, going on (mt_load's return, or mt_kill in its own
; task): MT_END, as its stub makes it, with the stub the current PSP:
; whatever ran in it ends with the task (mt_owners: their files closed,
; their EMS and memory freed), the exit code ^C's.  Inside INT 21h (a key
; wait), from here; else through INT 21h, the kernel's own (the task's
; vector may be a program's hook)
mt_kdie:
        cli
        push    KSEG
        pop     ds
        call    mt_cent
        mov     ax, [cs:bx+TE_PSP]
        mov     [cur_psp], ax
        mov     word [last_exit], 0100h
        push    ds                      ; INT 22h-24h the stub's (MT's), as a
        mov     ds, ax                  ;  program's end puts them back: a disk
        mov     si, 0Ah                 ;  error as its files close gets
        xor     di, di                  ;  mt_i24, not a dying program's
        mov     es, di                  ;  handler
        mov     di, 22h * 4
        mov     cx, 6
        cld
        rep     movsw
        pop     ds
        cmp     byte [indos], 0
        je      .out
        jmp     mt_end
.out:   pushf                           ; (the call's frame: never gone back
        push    cs                      ;  to)
        push    word .h
        mov     ax, 0F000h + MT_END
        jmp     KSEG:int21
.h:     hlt
        jmp     .h

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

; f_25 and f_35's first 7 bytes (XOR BX,BX / MOV ES,BX / MOV BL,[BP+F_AX])
; become far jumps here.  INT 09h and 1Bh in a background task are its
; own, in its TX (TX_FVEC): set and given there, the table (the front
; task's) as it is.  Else on as they were.  DS = SS = KSEG, BP = the frame
mt_25:  call    mt_fvx
        jc      .k
        mov     ax, [bp+F_DX]
        mov     [es:di], ax
        mov     ax, [bp+F_DS]
        mov     [es:di+2], ax
        jmp     KSEG:done
.k:     xor     bx, bx
        mov     es, bx
        mov     bl, [bp+F_AX]
        jmp     KSEG:f_25 + 7
mt_35:  call    mt_fvx
        jc      .k
        mov     ax, [es:di]
        mov     [bp+F_BX], ax
        mov     ax, [es:di+2]
        mov     [bp+F_ES], ax
        jmp     KSEG:done
.k:     xor     bx, bx
        mov     es, bx
        mov     bl, [bp+F_AX]
        jmp     KSEG:f_35 + 7
; the call's vector (AL) one of mt_vfr's, from a background task?  ES:DI =
; its own in the running task's TX (its writes to the table this turn
; there first, the table the front's again); CF if not.  AX, BX, CX, SI
; changed
mt_fvx: mov     al, [bp+F_AX]
        cmp     al, 09h
        je      .b
        cmp     al, 1Bh
        jne     .no
.b:     mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        je      .no
        pushf
        cli
        call    mt_fvsync
        call    mt_fvset
        popf
        call    mt_cent
        mov     es, [cs:bx+TE_TX]
        mov     di, TX_FVEC
        cmp     byte [bp+F_AX], 09h
        je      .y
        mov     di, TX_FVEC + 4
.y:     clc
        ret
.no:    stc
        ret

; the task at entry BX ended (mt_end, mt_kill), exit code AX: MT_EXIT's
; record, MT_UI's count, its screen's pages freed if still MT's.  DS =
; KSEG; AX, DX changed
mt_ended:
        mov     [cs:bx+TE_EXIT], ax
        mov     al, [cs:bx+TE_GEN]      ; (MT_EXIT: this one's, ended)
        mov     [cs:bx+TE_EGEN], al
        inc     byte [cs:mt_nend]       ; (MT_UI's look: one more ended, and
        mov     al, [cs:mt_nend]        ;  this one's place in that count)
        push    bx
        sub     bx, mt_tab              ; (its number, from the entry)
        shr     bx, 5
        mov     [cs:mt_eord+bx], al
        pop     bx
        push    si
        call    mt_shm                  ; its screen's pages
        jc      .z
        call    mt_hfree
.z:     pop     si
        mov     byte [cs:bx+TE_SH], 0
        ret

; the EMS handle at KSEG:ems_h + SI freed as a program's end frees it
; (a 47h context too, which 45h refuses); a closed one left alone.  DS =
; KSEG; all kept
mt_hfree:
        pusha
        pushf
        cli
        add     si, ems_h
        cmp     byte [si], 0FFh         ; (closed)
        je      .x
        KCALL   ems_free
.x:     popf
        popa
        ret

; the entry at BX free, as a task's end leaves it; the last one but the
; Executive's: no shadow (alone).  All kept
mt_tfree:
        mov     byte [cs:bx+TE_STATE], TS_FREE
        mov     byte [cs:bx+TE_KILL], 0
        call    mt_others
        jnc     .x
        mov     byte [cs:mt_shd], 0
.x:     ret

; MT_END: from a task's stub, its program done.  Its handles (the
; inherited ones) closed, its region freed, and another task runs.
mt_end: call    mt_cent                 ; (first: a call refused changes
        or      al, al                  ;  nothing)
        jz      mt_bad                  ; (not the Executive)
        mov     ax, [cs:bx+TE_PSP]
        cmp     ax, [cur_psp]
        jne     mt_bad                  ; (only its stub)
        mov     es, ax
        cmp     byte [cs:mt_swing], 0   ; (a change of the front its handler
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
        call    mt_fdrain               ; (before mt_load's FRSTOR; then
        sti                             ;  interrupts on, as INT 21h had them)
        KCALL   close_allt              ; (an Abort in its closes: Fail)
        mov     ax, [last_exit]
        mov     es, [cs:bx+TE_PSP]      ; (its program not started: FFxxh)
        cmp     byte [es:ST_FAIL + 1], 0FFh
        jne     .ex
        mov     ax, [es:ST_FAIL]
.ex:    call    mt_ended
        call    mt_owners               ; (a TSR's files and EMS: closed, freed;
                                        ;  a killed task's programs' too)
        call    mt_vfix                 ; vectors left pointing into the region:
        push    bx                      ;  as they were; then, till another
        push    es                      ;  task runs, task 0's in the table (a
        cli                             ;  tick meanwhile runs its hooks, not
        xor     al, al                  ;  this one's own)
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        call    mt_vld
        call    mt_fvset
        sti
        pop     es
        pop     bx
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        jne     .f
        push    ax                      ; it was in front: the Executive's
        xor     al, al                  ;  task is, with its screen and its
        call    mt_scrto                ;  INT 33h state (this one's pages
        pop     ax                      ;  are gone: its screen not kept; its
                                        ;  TX, written, still its own)
.f:     mov     cx, [cs:bx+TE_REG]      ; the region freed (a program that
        dec     cx                      ;  stayed resident too: its hooks are
        mov     es, cx                  ;  gone, so is it)
        mov     word [es:1], 0
        call    mt_tfree
        cmp     al, [cs:mt_swreq]
        jne     .s
        mov     byte [cs:mt_swreq], 0FFh
.s:     call    mt_pick                 ; another ready one, or the front one
        jnc     .go                     ;  (it may wait for a key: it
        mov     bl, [cs:mt_front]       ;  was there when this one ran)
.go:    jmp     mt_load

; MT_SPAWN: DS:DX = the program, ES:BX = the block -> AL = the new task.
; It runs with DS = CS (MT's variables without CS: prefixes; the
; kernel's through SS:, as INT 21h's stack is the kernel's), so do the
; helpers it alone calls (mt_carve, mt_hnew, mt_vnew, mt_v24)
mt_spawn:
        push    cs
        pop     ds
        mov     byte [mt_inb], 0        ; (as in mt_end, but not mt_swing nor
                                        ;  mt_vbusy: a handler's spawn inside
                                        ;  a change of the front leaves them)
        mov     byte [mt_crit], 0
        mov     byte [mt_in13], 0
        mov     al, 1                   ; a free entry
.e:     call    mt_ent
        cmp     byte [bx+TE_STATE], TS_FREE
        je      .got
        inc     al
        cmp     al, MT_TASKS
        jb      .e
        mov     ax, 4
        jmp     mt_fail
.got:   mov     [mt_new], bx
        mov     [bp+F_AX], al           ; (the answer)
        mov     es, [bp+F_ES]
        mov     di, [bp+F_BX]
        mov     ax, [es:di+SP_PARAS]
        mov     [mt_arena], ax
        mov     al, [es:di+SP_FLAGS]
        mov     [mt_sflags], al
        mov     es, [bp+F_DS]           ; LODE.INI's lists, by its name: BG=,
        mov     si, [bp+F_DX]           ;  FREEZE=, and MTMEM= unless the block
        call    mt_lname                ;  gave its memory
        mov     di, [mt_lbg]
        call    mt_lmat
        jnc     .bg
        or      byte [mt_sflags], SPF_BG
.bg:    mov     di, [mt_lfz]
        call    mt_lmat
        jnc     .fz
        or      byte [mt_sflags], SPF_FREEZE
.fz:    cmp     word [mt_arena], 0
        jne     .a
        mov     di, [mt_lmem]
        call    mt_lmat                 ; (AX = its KB)
        jnc     .d
        shl     ax, 6
        jmp     short .m
.d:     mov     ax, MT_DEFARENA
.m:     mov     [mt_arena], ax
.a:     mov     es, [bp+F_ES]
        mov     di, [bp+F_BX]
        mov     ax, [es:di+SP_ENV]      ; the environment: the block's, or
        or      ax, ax                  ;  the caller's
        jnz     .ev
        mov     es, [ss:cur_psp]
        mov     ax, [es:2Ch]
.ev:    mov     [mt_envs], ax
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
        mov     [mt_envp], di
        mov     ax, TX_PARAS + ST_PARAS + 1     ; the region: TX, stub, env,
        add     ax, di                  ;  the arena's MCB, the arena
        add     ax, [mt_arena]
        jc      .room
        mov     [mt_size], ax
        call    mt_carve
        jnc     .r
.room:  mov     ax, 8
        jmp     mt_fail
.r:     mov     [mt_reg], ax
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
.sh:    call    mt_hnew                 ; (an entry with this number keeps
        mov     bx, [mt_new]            ;  none: a program freed it)
        mov     [bx+TE_SH], dl
        mov     byte [bx+TE_SF], 1      ; (kept: mode 3, clear, below)
        mov     al, [mt_sflags]
        and     al, SPF_BG | SPF_FREEZE
        mov     [bx+TE_VF], al
        mov     ax, [mt_reg]
        mov     [bx+TE_REG], ax
        mov     [bx+TE_TX], ax
        dec     ax                      ; its MCB: the system's, "T1".."T7"
        mov     es, ax
        mov     word [es:1], 8
        mov     al, [bp+F_AX]
        add     al, '0'
        mov     ah, al
        mov     al, 'T'
        mov     [es:8], ax
        ; the stub's PSP (make_psp: the caller's handles, inherited)
        mov     ax, [mt_reg]
        add     ax, TX_PARAS
        mov     es, ax
        mov     [bx+TE_PSP], ax
        add     ax, ST_PARAS            ; (the environment's copy)
        mov     dx, [mt_reg]
        add     dx, [mt_size]           ; (the region's end)
        mov     bx, [ss:cur_psp]
        KCALL   make_psp                ; (its environment: the copy)
        mov     ax, es                  ; its own parent: if it is ended
        mov     [es:16h], ax            ;  itself, it goes to MT_END
        mov     word [es:0Ah], ST_END
        mov     [es:0Ch], ax
        mov     word [es:2Eh], ST_AFR   ;  (as EXEC's .close would set it)
        mov     [es:30h], ax
        ; the stub's code, the program's path, its name for MT_LIST
        mov     si, st_code
        mov     di, 100h
        mov     cx, st_len
        rep     movsb
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
        xor     ax, ax                  ; ST_FAIL: not failed (yet)
        stosw
        ; the environment's copy
        push    ds
        mov     ax, es
        add     ax, ST_PARAS
        mov     es, ax
        mov     ds, [mt_envs]
        xor     si, si
        xor     di, di
        mov     cx, [cs:mt_envl]
        rep     movsb
        mov     word [es:di-2], 0       ; (two NULs, even if cut)
        pop     ds
        ; the arena: one free block to the region's end
        mov     ax, es
        add     ax, [mt_envp]
        mov     es, ax
        mov     byte [es:0], 'Z'
        mov     word [es:1], 0
        mov     cx, [mt_arena]
        mov     [es:3], cx
        push    ax                      ; (its MCB: the task's first_mcb)
        ; its TX: the caller's variables (its directories, ...), then its own
        mov     es, [mt_reg]
        push    ss                      ; (the kernel's: DS = KSEG)
        pop     ds
        call    mt_vsave
        push    cs
        pop     ds
        call    mt_emsget
        pop     ax
        mov     [es:V_MCB], ax
        mov     byte [es:V_INDOS], 0
        mov     byte [es:V_BRK + kbd_scan - brkflag], 0
        mov     byte [es:V_BRK + term_type - brkflag], 0
        mov     word [es:V_BRK + cc_sp - brkflag], 0
        mov     word [es:V_DTA + con_lpos - dta], 0     ; (no line half read)
        mov     word [es:V_DTA + con_llen - dta], 0
        xor     ax, ax                  ; (not in front for graphics; no
        mov     di, TX_WGFX             ;  click held, nor the mouse taken)
        mov     cx, (TX_IN13 + 2 - TX_WGFX) / 2
        rep     stosw
        mov     di, TX_PUB              ; (no screen published)
        mov     cl, (TX_PPSP + 2 - TX_PUB) / 2
        rep     stosw
        mov     [es:TX_KLEN], ax
        mov     [es:TX_KN], ax          ; (no keys typed to it)
        mov     [es:TX_FPV], al         ; (its coprocessor: FNINIT's, first)
%if (TX_IN13 + 2 - TX_WGFX) & 1 || (TX_PPSP + 2 - TX_PUB) & 1
%error "mt_spawn: TX_WGFX..TX_IN13, TX_PUB..TX_PPSP in words"
%endif
        mov     bx, [mt_new]
        mov     ax, [bx+TE_PSP]
        mov     [es:V_PSP + cur_psp - cur_psp], ax
        mov     word [es:V_PSP + last_exit - cur_psp], 0
        mov     word [es:V_DTA + 0], 80h
        mov     [es:V_DTA + 2], ax
        call    mt_m33new               ; (its INT 33h state)
        call    mt_33hk
        push    ax
        mov     bx, [mt_new]
        call    mt_vnew                 ; (its vectors: the caller's, mostly)
        pop     ax
        push    ax                      ; its screen: mode 3, clear (it may
        mov     si, mt_v3               ;  print before it is ever in front)
        mov     di, TX_VID
        mov     cx, VIDLEN
        rep     movsb
        push    es
        mov     bx, [mt_new]
        mov     byte [mt_vbusy], 1
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
.ns:    mov     byte [mt_vbusy], 0
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
        mov     bx, [mt_new]
        mov     byte [bx+TE_STATE], TS_RUN
        mov     byte [bx+TE_KILL], 0
        mov     byte [bx+TE_PH], 0
        inc     byte [bx+TE_GEN]        ; (TE_EXIT kept: the last one's, for
        jnz     .g                      ;  MT_EXIT till this one ends)
        inc     byte [bx+TE_GEN]
.g:     call    mt_sync                ; (the front one's screen shadowed now)
        test    byte [mt_sflags], SPF_FRONT
        jz      .x
        mov     al, [bp+F_AX]
        mov     [mt_swreq], al
.x:     jmp     KSEG:ok

; the program's name (its path's last part) into its entry (BX = mt_new),
; upper case, NUL-padded.  ES:ST_PATH = the path.
mt_name:
        mov     si, ST_PATH
        call    mt_lname
        push    ds
        push    es
        pop     ds
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

; the name part of the path at ES:SI (after its last \ or :) -> SI
mt_lname:
        push    ax
        push    di
        mov     di, si
.l:     mov     al, [es:si]
        inc     si
        or      al, al
        jz      .x
        cmp     al, '\'
        je      .m
        cmp     al, ':'
        jne     .l
.m:     mov     di, si
        jmp     .l
.x:     mov     si, di
        pop     di
        pop     ax
        ret

; is the name at ES:SI (to its NUL, any case) in LODE.INI's list at CS:DI
; (mt_lists: names, upper case, each with its 0 and a word)?  CF if so,
; AX = its word.  An entry with no '.' names the program whatever its
; extension (MTSPIN: MTSPIN.COM, MTSPIN.EXE); one with a '.', only that.
; (AX changes)
mt_lmat:
        push    si
        push    di
.e:     cmp     byte [cs:di], 0         ; (the list's end)
        je      .no
        push    si
.c:     mov     al, [es:si]
        inc     si
        cmp     al, 'a'
        jb      .u
        cmp     al, 'z'
        ja      .u
        sub     al, 20h
.u:     mov     ah, [cs:di]
        inc     di
        or      ah, ah
        jz      .end
        cmp     al, ah
        je      .c
.sk:    mov     ah, [cs:di]             ; (not this one: past its 0)
        inc     di
        or      ah, ah
        jnz     .sk
.nx:    inc     di                      ; (and its word)
        inc     di
        pop     si
        jmp     .e
.end:   or      al, al                  ; the entry done: the name too, or at
        jz      .y                      ;  its extension
        cmp     al, '.'
        jne     .nx
.y:     pop     si
        mov     ax, [cs:di]
        pop     di
        pop     si
        stc
        ret
.no:    pop     di
        pop     si
        clc
        ret

; ---------------------------------------------------------------------
;  The Executive's entry: called far by KMW's patches (mw_prog, mw_poll) in
;  its own task (task 0), not inside INT 21h, so it may call DOS; with CS
;  here no switch comes meanwhile (mt_safe).  DS = ES = the UI's segment.
;  AL = 0: Return on a program: start the program at DS:SI (its path, as
;   the Executive has it) as a task, in front.  Its memory: MTMEM='s (at
;   the spawn); else a .COM's 64 KB; an .EXE's as its header asks: at
;   least its minimum, up to its maximum but not more than leaves 64 KB
;   for another task.  CF if it can't: ES:DI = why ("Can't run X: ...",
;   ASCIIZ).
;  AL = 1: has a task ended since the last look?  CF if so (the files may
;   have changed); then AL = 1 for one the Executive started, its message
;   at ES:DI ("X ended[, exit code n]"), else AL = 0, ES:DI untouched.
;   One at a time, the first ended first: a second one's the next look.
; ---------------------------------------------------------------------
mt_ui:  push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    bp
        push    ds
        push    es
        cld
        or      al, al
        jz      mt_urun
        mov     al, [cs:mt_nend]        ; (the usual answer: no)
        cmp     al, [cs:mt_send]
        je      mt_uok
        mov     dx, 00FFh               ; DL: the first end of the Executive's
        xor     bp, bp                  ;  found (BP: its task), DH: how many
        mov     cx, 1
.l:     mov     si, cx                  ; (SI = the task)
        mov     ah, [cs:mt_xgen+si]
        or      ah, ah
        jz      .n                      ; (not the Executive's)
        mov     al, cl
        call    mt_ent
        cmp     ah, [cs:bx+TE_GEN]      ; (its number given again since: its
        jne     .drop                   ;  end missed, nothing to say)
        cmp     ah, [cs:bx+TE_EGEN]
        jne     .n                      ; (still there)
        inc     dh
        mov     al, [cs:mt_eord+si]     ; (ended: the first to end first, so
        sub     al, [cs:mt_send]        ;  the last one's message stays)
        cmp     al, dl
        jae     .n
        mov     dl, al
        mov     bp, si
        jmp     short .n
.drop:  mov     byte [cs:mt_xgen+si], 0
.n:     inc     cx
        cmp     cx, MT_TASKS
        jb      .l
        or      bp, bp
        jz      .seen                   ; (none of the Executive's: ES:DI as
        mov     byte [cs:mt_xgen+bp], 0 ;  it was, AL = 0)
        mov     ax, bp
        call    mt_ent
        call    mt_uend
        mov     al, 1                   ; (a message)
        cmp     dh, 1                   ; (another to tell: the next look)
        ja      mt_uyes
        jmp     short .all
.seen:  xor     al, al
.all:   mov     ah, [cs:mt_nend]        ; all seen
        mov     [cs:mt_send], ah
mt_uyes:
        stc
        jmp     short mt_ux
mt_uok: clc
mt_ux:  pop     es
        pop     ds
        pop     bp
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        retf

; AL = 0: Return
MT_XENV equ (ENVMAX + 132 + 2 + 15) / 16 + 1 ; EXEC's copy of the stub's
                                        ;  environment (ENVMAX at most) and
                                        ;  the name, with its MCB (f_4B)
mt_urun:
        mov     bp, si                  ; BP = the path
        mov     word [cs:mt_xpb + SP_PARAS], 0
        push    ds
        pop     es
        call    mt_lname
        mov     [cs:mt_xnm], si         ; (the name, for a message)
        mov     di, [cs:mt_lmem]
        call    mt_lmat
        jc      .sp                     ; (MTMEM=: mt_spawn takes it from there)
.d:     lodsb                           ; an .EXE?
        or      al, al
        jz      .sp
        cmp     al, '.'
        jne     .d
        lodsw
        and     ax, 0DFDFh
        cmp     ax, 'EX'
        jne     .sp
        lodsb
        and     al, 0DFh
        cmp     al, 'E'
        jne     .sp
        mov     dx, bp                  ; its header
        mov     ax, 3D00h
        int     21h
        jc      .sp                     ; (EXEC will say why)
        mov     bx, ax
        push    ds
        push    cs
        pop     ds
        mov     dx, mt_hdr
        mov     cx, 1Ch
        mov     ah, 3Fh
        int     21h
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
        jc      .spd
        cmp     ax, 1Ch
        jb      .spd
        mov     ax, [mt_hdr]
        cmp     ax, 'MZ'
        je      .mz
        cmp     ax, 'ZM'
        jne     .spd                    ; (EXEC takes it for a .COM)
.mz:    mov     ax, [mt_hdr + 4]        ; its load image, paragraphs: its
        cmp     ax, 800h                ;  pages, less its header, less what
        jae     .spd                    ;  the last page leaves unused (a
        shl     ax, 5                   ;  header past 1 MB: EXEC's to refuse)
        mov     cx, [mt_hdr + 2]
        jcxz    .fl
        neg     cx
        add     cx, 512
        shr     cx, 4
        sub     ax, cx
        jb      .spd
.fl:    sub     ax, [mt_hdr + 8]
        jb      .spd
        add     ax, MT_XENV + 10h       ; and its PSP, and EXEC's copy of the
        jc      .spd                    ;  environment, which goes in it too
        mov     dx, ax
        add     dx, [mt_hdr + 0Ah]      ; DX = the least it takes
        jc      .spd                    ; (more than there can be)
        add     ax, [mt_hdr + 0Ch]      ; AX = the most it asks for
        jnc     .hi
        mov     ax, 0FFFFh
.hi:    cmp     ax, dx                  ; (a maximum below its minimum: the
        jae     .hi2                    ;  minimum, as EXEC takes it)
        mov     ax, dx
.hi2:   push    ax
        mov     ah, 48h                 ; the most it gets: the largest block
        mov     bx, 0FFFFh              ;  less this task's region's own and
        int     21h                     ;  another's, with its 64 KB, and the
        pop     ax                      ;  Executive's room for a .RUN
        sub     bx, TX_PARAS + ST_PARAS + ENVMAX / 16 + 2 + MT_GRES
        jnc     .cap
        xor     bx, bx
.cap:   cmp     ax, bx                  ; its maximum, if that fits; else what
        jbe     .w                      ;  fits, but its minimum anyway (it
        mov     ax, bx                  ;  fails if even that doesn't fit:
        cmp     ax, dx                  ;  "not enough memory")
        jae     .w
        mov     ax, dx
.w:     mov     [mt_xpb + SP_PARAS], ax
.spd:   pop     ds
.sp:    push    ds                      ; in front, as before, if LODE.INI's
        pop     es                      ;  FULL=, FREEZE= (it never runs behind)
        mov     si, [cs:mt_xnm]         ;  or BG= (its INT 10h the real screen's)
        mov     di, [cs:mt_lfull]       ;  names it; else behind, in a terminal
        call    mt_lmat                 ;  window (mt_uwin)
        jc      .fs
        mov     di, [cs:mt_lfz]
        call    mt_lmat
        jc      .fs
        mov     di, [cs:mt_lbg]
        call    mt_lmat
        mov     al, 0
        jnc     .ff
.fs:    mov     al, SPF_FRONT
.ff:    mov     [cs:mt_xpb + SP_FLAGS], al
        mov     dx, bp
        push    cs
        pop     es
        mov     bx, mt_xpb
        mov     ax, 0F000h + MT_SPAWN
        stc
        int     21h
        pop     es                      ; (the message's room: ES:DI)
        push    es
        jc      .er
        mov     si, ax                  ; the Executive's: its count, to tell
        and     si, 0FFh                ;  its end by (mt_ui AL = 1)
        call    mt_ent
        mov     ah, [cs:bx+TE_GEN]
        mov     [cs:mt_xgen+si], ah
        test    byte [cs:mt_xpb + SP_FLAGS], SPF_FRONT
        jnz     .ok
        call    mt_uwin                 ; (behind: its window)
.ok:    jmp     mt_uok
.er:    mov     si, mt_snomem           ; "Can't run X: why"
        cmp     ax, 4
        jne     .em
        mov     si, mt_smany
.em:    mov     bx, sp
        mov     di, [ss:bx+6]           ; (the caller's DI, pushed)
        push    si
        mov     si, mt_scant
        call    mt_ucpy
        mov     si, [cs:mt_xnm]         ; (DS: the caller's)
.nm:    lodsb
        or      al, al
        jz      .why
        stosb
        jmp     .nm
.why:   pop     si
        call    mt_ucpy
        mov     byte [es:di], 0
        jmp     mt_uyes

; task AL (its count AH, its entry BX), started behind: its terminal
; window, TERM.RUN (UI_FINDAPP's) with the argument "task count name", as
; run_app runs it (mw_run: a session, the first or beside others); the
; Executive waits in here while others are in front.  If it can't open (no
; TERM.RUN, no room, too many windows): the task in front, as without
; windows.  (DS = the UI's; AX, BX, CX, SI, DI change)
mt_uwin:
        push    es
        push    ax
        cmp     byte [cs:mw_on], 0      ; (the UI not patched: no windows)
        je      .no
        push    ds
        pop     es
        mov     di, msgbuf              ; (the Executive's: free while it waits;
        mov     si, mt_sterm            ;  TERM copies its argument at once)
        call    mt_ucpy
        mov     byte [es:di], 0
        mov     di, msgbuf + 16
        pop     ax
        push    ax
        call    mt_udec                 ; (AL: the task)
        mov     al, ' '
        stosb
        pop     ax
        push    ax
        mov     al, ah
        call    mt_udec
        mov     al, ' '                 ; (its name: TERM's title)
        stosb
        call    mt_uname
        mov     byte [es:di], 0
        mov     si, msgbuf
        UCALL   ui_findapp              ; SI = its path
        jc      .no
        mov     di, msgbuf + 16
        UCALL   run_app                 ; (mw_run: CF clear whether or not
        pop     ax                      ;  the window opened: a TERM.RUN not
        push    ax                      ;  ours, or one that ended at once)
        call    mw_owns
        jnc     .x
.no:    pop     ax
        push    ax
        mov     [cs:mt_swreq], al       ; (in front: at the next switch)
.x:     pop     ax
        pop     es
        ret

; the ended task at BX: "X ended[, exit code n]", or "X could not be
; started: error n" (EXEC's), at ES:DI, ASCIIZ.  (AX, CX, SI change)
mt_uend:
        call    mt_uname
        mov     ax, [cs:bx+TE_EXIT]
        push    ax
        mov     si, mt_snost
        cmp     ah, 0FFh
        je      .c
        mov     si, mt_sended
        call    mt_ucpy
        pop     ax
        push    ax
        or      al, al                  ; (as the Executive says it for a
        jz      .x                      ;  program it ran itself: AL)
        mov     si, mt_scode
.c:     call    mt_ucpy
        pop     ax
        push    ax
        call    mt_udec
.x:     pop     ax
        mov     byte [es:di], 0
        ret

; the name of the task at BX (TE_NAME: TR_NAMELEN at most) at ES:DI, DI
; past it, no NUL (AL, CX, SI change)
mt_uname:
        lea     si, [bx+TE_NAME]
        mov     cx, TR_NAMELEN
.n:     mov     al, [cs:si]
        or      al, al
        jz      .x
        stosb
        inc     si
        loop    .n
.x:     ret

; the text at CS:SI (ASCIIZ) at ES:DI, DI and SI past it (AL changes)
mt_ucpy:
        mov     al, [cs:si]
        inc     si
        or      al, al
        jz      .x
        stosb
        jmp     mt_ucpy
.x:     ret

mt_sterm db     'TERM.RUN', 0

; AL in decimal at ES:DI (AX, CL change)
mt_udec:
        xor     ah, ah
        mov     cl, 10
        div     cl
        push    ax
        or      al, al
        jz      .d
        call    mt_udec
.d:     pop     ax
        mov     al, ah
        add     al, '0'
        stosb
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
%ifndef NOSYSREQ
.s0:    xor     al, al                  ; SysReq pressed?  As CODE-Tab
        xchg    al, [cs:mt_sysrq]       ;  (the buffer looked at the next time)
        or      al, al
        jnz     .c
        times   ($ - .s0) & 1 db 90h    ; (what follows keeps its parity)
%endif
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
        dec     cx                      ; (16 at most)
        jz      .e
        mov     ax, [bx]
        mov     [si], ax
        jmp     .m
.e:     mov     [1Ch], si
.c:     mov     al, [cs:mt_swreq]       ; the next task after that one
        cmp     al, 0FFh
        jne     .t
        mov     al, [cs:mt_front]
.t:     mov     cx, MT_TASKS - 1
.l:     inc     al
        and     al, MT_TASKS - 1
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        je      .ln
        cmp     byte [cs:bx+TE_STATE], TS_PARKED
        je      .ln
        or      al, al
        jz      .y
        call    mt_ispub                ; (its window is its screen)
        jnc     .y
.ln:    loop    .l
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
        je      .rp
        cmp     byte [cs:bx+TE_STATE], TS_PARKED
.rp:    pop     bx
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
;  INT 16h: keys for the front task only.  First, at any call made
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
;      the EMS frame; a read where the task can't be switched from): in
;      front AH=00h/01h through mt_drop, no switch (.fd); behind, and
;      AH=10h/11h, as they are.
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
        call    mt_busy                 ; (inside a call MT passed on to the
        jnz     .pas                    ;  BIOS, an INT 13h call, or a change
                                        ;  of the front: an interrupt's, as MT
                                        ;  takes INT 10h's there; the kernel's
                                        ;  INT 24h's prompt, raised inside INT
                                        ;  21h or not: as it is)
.top:   cmp     word [bp+4], 0A000h     ; (Resident Claude's console, at E000h,
        jb      .h                      ;  up: its keys its own, CODE-Tab too;
        cmp     word [cs:mt_tsrs], 0    ;  r_inpop, at 10Dh in its stub's
        je      .h                      ;  header)
        push    ds
        mov     ds, [cs:mt_tsrs]
        cmp     word [100h], 'CL'       ; (its header still there: not after
        jne     .hd                     ;  an older CLAUDE /U)
        cmp     byte [10Dh], 0
        jmp     short .he
.hd:    cmp     al, al
.he:    pop     ds
        jne     .nh
.h:     call    mt_hot
.nh:    cli
        cmp     byte [cs:mt_swreq], 0FFh ; (a task asked for: on the way out
        je      .f                      ;  of this INT 21h call, say, not only
        mov     byte [cs:mt_pend], 1    ;  at the turn's end)
.f:     test    byte [bp+I16_AH], 0EEh
        jnz     .pas
        mov     dh, [bp+I16_AH]         ; keys typed to it (MT_TKEY), for any
        mov     dl, dh                  ;  caller in it: a peek's, or a read's
        not     dl                      ;  (AH=00h and 01h: those they don't
        and     dx, 0110h               ;  give dropped first)
        xor     dh, 1
        call    mt_ring
        jc      .nr
        mov     [bp+I16_AH-1], ax       ; (the caller's AX, back at .ret)
        and     word [bp+6], ~40h       ; (ZF clear: a key; interrupts on)
        or      word [bp+6], 200h
        jmp     .ret
.nr:    mov     ax, ss                  ; whose?  The kernel's or MT's key wait
        cmp     ax, KSEG                ;  (on the kernel's stack, through a
        jne     .own                    ;  TSR's hook too, but not a pop-up's
        cmp     byte [cs:mt_idle], 0    ;  from the kernel's INT 28h), or the
        je      .k                      ;  program's own code (not a TSR's
.own:   mov     ax, [bp+4]              ;  hook's, the ROM's, the frame's)?
        call    mt_mine
        jc      .fd
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
        cmp     al, [cs:mt_front]       ;  only with nothing typed: for AH=00h,
        jne     .w                      ;  the keys it would skip dropped by
        test    byte [bp+I16_AH], 10h   ;  MT (mt_drop); for AH=10h, a peek of
        jnz     .rx                     ;  its kind (11h drops none)
        call    mt_drop
        jnz     .pas                    ; (one: the BIOS's read has it at once)
        jmp     short .w
.rx:    mov     ah, [bp+I16_AH]
        inc     ah
        pushf
        call    far [cs:mt_old16]
        cli
        jnz     .pas
.w:     call    mt_wkey
.wk:    jnc     .top
        call    mt_cent                 ; (no other task ready: until the
        cmp     byte [cs:bx+TE_KILL], 0 ;  next interrupt; unless it ended
        jne     mt_kdie                 ;  itself: now)
        sti
        hlt
        jmp     .top
.fd:    mov     al, [cs:mt_cur]         ; (a hook's call, a TSR chaining on
        cmp     al, [cs:mt_front]       ;  with PUSHF / CALL FAR: no switch
        jne     .pas                    ;  there, but in front the keys AH=00h
        jmp     short .kf               ;  and 01h skip dropped by MT all the
        nop                             ;  same, Resident Claude's CODE-\ kept.
                                        ;  The NOP: what follows keeps its
                                        ;  parity)
.k:     mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        jne     .kb
.kf:    test    byte [bp+I16_AH], 0FEh  ; in front, AH=00h or 01h: the keys
        jnz     .pas                    ;  they skip dropped by MT first, so
        call    mt_drop                 ;  the BIOS's own drops none (a key
        jnz     .pas                    ;  typed after MT looked: seen at the
        test    byte [bp+I16_AH], 1     ;  next look, not lost); none left: a
        jz      .pas                    ;  peek's answer is MT's, a read the
        jmp     short .none             ;  BIOS's (it waits)
.kb:    test    byte [bp+I16_AH], 1
        jz      .pas
.none:  or      word [bp+6], 0240h      ; (ZF: no key; interrupts on, as the
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

; the 1520's BIOS drops the keys AH=00h and 01h can't give (scan codes 85h
; and up but E0h's, and CODE keys: xxF0h with a scan code) as it looks.
; Its INT 16h turns interrupts on first (STI, F000:A02E; the look itself
; with them off): CODE-Tab typed after mt_hot looked and before the
; BIOS does would go.  So MT drops them first, with interrupts off, taking
; CODE-Tab (mt_hot) as it comes to it, and keeping Resident Claude's
; CODE-\ for its stub (made 2B00h: none now).  ZF if no key is left; else
; the one at the head is one AH=00h and 01h give.  (At most 16 looked at: a
; buffer gone bad is left to the BIOS.)  AX, BX changed
mt_drop:
        push    ds
        push    cx
        push    40h
        pop     ds
        mov     cx, 16
.l:     mov     bx, [1Ah]
        cmp     bx, [1Ch]
        je      .x                      ; (ZF: none)
        mov     ax, [bx]
        cmp     ax, [cs:mt_hotk]
        je      .h
        cmp     ax, [cs:mt_hotk + 2]
        je      .h
        db      81h, 0F8h               ; cmp ax, 2BF0h: Resident Claude's
        dw      2BF0h                   ;  CODE-\ (the 4-byte form: what
        je      .c                      ;  follows keeps its parity)
        call    mt_kgive
        jnc     .k
.d:     call    mt_hot.nx               ; dropped, as the BIOS would
        mov     [1Ah], bx
        loop    .l
        jmp     short .k
.h:     call    mt_hot                  ; (out, its task asked for: on the
        cli                             ;  way out of this call, as mt_i16's)
        cmp     byte [cs:mt_swreq], 0FFh
        je      .hl
        mov     byte [cs:mt_pend], 1
.hl:    loop    .l
.k:     or      sp, sp                  ; (ZF clear: a key)
.x:     pop     cx
        pop     ds
        ret
.c:     call    mt_rhot                 ; its stub there, the hot key on: made
        jne     .d                      ;  2B00h, which AH=00h and 01h give, so
        mov     byte [bx], 0            ;  nothing drops it and the stub's next
        jmp     short .x                ;  look takes it; none now (ZF)

; Resident Claude's stub there (MT_TSR; its header still there, as an
; older CLAUDE /U leaves the address) with its hot key on (r_off, at 10Eh,
; 0: no CLAUDE.COM runs): ZF.  Registers kept
mt_rhot:
        cmp     word [cs:mt_tsrs], 0
        je      .n
        push    ds
        mov     ds, [cs:mt_tsrs]
        cmp     word [100h], 'CL'
        jne     .p
        cmp     byte [10Eh], 0
.p:     pop     ds
        ret
.n:     or      sp, sp                  ; (none: not ZF)
        ret

; CF if key AX is one INT 16h AH=00h and 01h don't give (the 1520's BIOS
; drops it: scan codes 85h and up but E0h's, as mt_hot tells them, and
; CODE keys, xxF0h with a scan code).  All kept
mt_kgive:
        cmp     ah, 0E0h
        je      .y
        cmp     ah, 85h
        jae     .n
        cmp     al, 0F0h
        jne     .y
        or      ah, ah
        jz      .y
.n:     stc
        ret
.y:     clc
        ret

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
        call    mt_cent
        mov     byte [cs:bx+TE_STATE], TS_WAITK
        pop     bx
        call    mt_switch
.sw:    clc
.x:     ret

; task AL to the front: the front one's screen kept, AL's shown; a DOS
; program's INT 33h pointer off meanwhile (as RCON does), and each one's
; INT 33h state its own
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
;  INT 33h: each task its own mouse.  The UI's driver keeps one
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
        or      ax, ax                  ; (a reset, a program taking the
        jz      .tk                     ;  mouse: its window's clicks its own)
        cmp     ax, 21h
        jne     .go
.tk:    call    mt_mtake
.go:    mov     ax, [ui_seg]            ; (the UI's driver where the UI is
        mov     [cs:mt_old33 + 2], ax   ;  now: its block can move)
        cmp     byte [cs:mt_in33], 0
        jne     .pas
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]
        je      .pas
        call    mt_b33                  ; (the kernel's INT 24h's prompt, raised
        jnz     .pas                    ;  inside INT 21h or not: as it is)
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
        mov     [cs:mt_33fn], ax
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
        call    mt_cent
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
        mov     ax, [cs:mt_33fn]        ; (its window's press read, by 03h,
        cmp     ax, 3                   ;  05h or 06h: a release held, now; BX:
        je      .rd                     ;  its entry)
        cmp     ax, 5
        je      .rd
        cmp     ax, 6
        jne     .fr
.rd:
        push    es
        mov     es, [cs:bx+TE_TX]
        and     byte [es:TX_MREL], 7Fh
        call    mt_mheld
        pop     es
.fr:    mov     al, [cs:mt_front]
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
; tick doesn't switch); mt_m33nb gives it back as it was.  All kept but
; the flags
mt_m33bz:
        push    ax
        mov     ax, 0101h               ; (AH 1: the old one to mt_33sb)
        jmp     short mt_m33nb.x
mt_m33nb:
        push    ax
        mov     al, [cs:mt_33sb]
        mov     ah, 0
.x:     push    es
        push    KSEG
        pop     es
        mov     es, [es:ui_seg]
        xchg    al, [es:m33_busy]
        or      ah, ah
        jz      .r
        mov     [cs:mt_33sb], al
.r:     pop     es
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
        push    es
        push    KSEG
        pop     es
        mov     es, [es:ui_seg]
        pushf                           ; (no interrupt's own call between)
        cli
        mov     dx, [es:m33_cnt]
        mov     ax, 1
        call    mt_m33
        cmp     dx, [es:m33_cnt]        ; (after the change's AX=2, the UI's
        jne     .p                      ;  count is below 0, so AX=1 moves it;
        mov     byte [cs:mt_33ot], 1    ;  not so in mt_end inside a change)
.p:     popf
        pop     es
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

; the driver's state to task AL's TX.  All kept
mt_m33to:
        pusha
        push    es
        push    KSEG
        pop     es
        mov     es, [es:ui_seg]
        pushf
        cli
        call    mt_m33sv
        popf
        pop     es
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
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        mov     dx, TX_M33
        pushf
        cli
        call    mt_mheld                ; (a click's release held: no
        mov     byte [es:TX_MREL], 0    ;  button left down in front)
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
        pop     es
        pop     ds
        popa
        ret

; a new task's INT 33h state (ES = its TX; mt_spawn's, DS = CS): the driver's now,
; the pointer off and no event handler, until its program resets it.
; All kept
mt_m33new:
        pusha
        push    ds
        mov     ds, [ss:ui_seg]
        pushf
        cli
        mov     si, m33_st
        mov     di, TX_M33
        mov     cx, M33_ST / 2
        rep     movsw                   ; (DF clear: mt_spawn's copies ran)
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
        pop     ds
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
        pop     es
        pop     ds
        pop     ax
        ret

; KPROC's ui_progend (its first 5 bytes: MOV AX,[ui_seg] / OR AX,AX):
; the program at BX ends.  In a background task its event handler, if it
; is that program's, is forgotten in the task's own state, as the driver's
; m33_gone does for the front task's (a shell's next program can be
; loaded at the same segment).  Then on, past those bytes (DS = KSEG)
mt_pgend:
        mov     byte [cs:mt_crit], 0    ; (left by an INT 24h handler that ended
                                        ;  its program instead of answering)
        call    mt_vpg                  ; (the other tasks' vectors into it)
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
        jmp     short .a
.k:     call    mt_gtext
.a:     call    mt_mgone
        pop     ax
        mov     ax, [ui_seg]
        or      ax, ax
        jmp     KSEG:ui_progend + 5

; The program at BX ends: if it took the mouse (TX_MPSP), its task's
; window clicks are a selection's again, and none is held.  If it
; published its screen (TX_PPSP), that is withdrawn (a change: its window
; looks again).  Its SRQ wake ends.  All kept
mt_mgone:
        push    ax
        push    bx
        push    es
        push    bx
        call    mt_cent
        pop     ax
        mov     es, [cs:bx+TE_TX]
        cmp     [es:TX_MPSP], ax
        jne     .p
        mov     word [es:TX_MPSP], 0
        mov     byte [es:TX_MREL], 0
.p:     push    ax                      ; its SRQ wake (MT_WAKE) ended (a
        push    dx                      ;  kill, or its task's end for a TSR,
        mov     dx, ax                  ;  comes here too: mt_owners)
        call    mt_wkme
        pop     dx
        pop     ax
        cmp     byte [cs:mt_cur], 0     ; (task 0's TX ends before TX_PUB, TX_PPSP)
        je      .x
        cmp     [es:TX_PPSP], ax
        jne     .x
        call    mt_tchg                 ; (its count one up from what a window
        inc     ax                      ;  saw: its PB_CHG kept in TX_CHG)
        mov     [es:TX_CHG], ax
        xor     ax, ax
        mov     [es:TX_PUB], ax
        mov     [es:TX_PUB + 2], ax
        mov     [es:TX_PPSP], ax
.x:     pop     es
        pop     bx
        pop     ax
        ret

; The running task's program takes the mouse (its own reset: not
; MT's), so its window's clicks go to it (TX_MPSP).  All kept (DS = KSEG)
mt_mtake:
        cmp     byte [cs:mt_in33], 0
        jne     .x
        push    ax
        push    bx
        push    es
        call    mt_cent
        mov     es, [cs:bx+TE_TX]
        mov     ax, [cur_psp]
        mov     [es:TX_MPSP], ax
        mov     byte [es:TX_MREL], 0    ; (a click held from before: gone)
        pop     es
        pop     bx
        pop     ax
.x:     ret

; The program at BX, ending in front, is the one that asked for
; graphics (TX_WPSP) and leaves its task in them (TX_WGFX 1): a text mode
; for it, as if it set one itself, so that the task goes back to its
; window (mt_wback).  All kept
mt_gtext:
        pusha
        push    es
        mov     dx, bx
        mov     al, [cs:mt_front]
        call    mt_ent
        mov     es, [cs:bx+TE_TX]
        cmp     byte [es:TX_WGFX], 1
        jne     .x
        cmp     dx, [es:TX_WPSP]
        jne     .x
        mov     ax, [es:TX_PUB]         ; (a screen published, its
        or      ax, [es:TX_PUB + 2]     ;  program's: it sets the mode itself,
        jnz     .x                      ;  after its snapshot of this one)
        push    0
        pop     es
        cmp     byte [es:449h], 4       ; (still in graphics)
        jb      .x
        mov     ax, 3
        int     10h
.x:     pop     es
        popa
        ret

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
        mov     es, [cs:bx+TE_TX]
        cmp     byte [es:TX_WGFX], 2    ; (back to its window now; its
        jne     .sm                     ;  pages gone or not)
        mov     byte [es:TX_WGFX], 0
.sm:    call    mt_smap
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
        mov     es, [cs:bx+TE_TX]       ; its BIOS data (and its screen changed,
        inc     word [es:TX_CHG]        ;  for a window showing it)
        push    40h
        pop     ds
        mov     si, 49h
        mov     di, TX_VID
        mov     cx, VIDLEN
        rep     movsb
        mov     al, [62h]               ; its page's start as 62h x 4Ch, as the
        xor     ah, ah                  ;  BIOS writes: a program may have set
        mul     word [4Ch]              ;  them itself, not with 05h, and MT
        mov     [es:TX_VID + 4Eh - 49h], ax ;  trusts 4Eh behind (whatever the
        push    0B800h                  ;  mode, as the BIOS's 05h works it out)
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
        nop                             ; (what follows at its parity)

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
        call    mt_shm
        jc      .no
        mov     al, [ems_h + si]        ; (its run's start)
        mov     si, ax
        mov     dx, EMS_PORT
        in      al, dx
        mov     [cs:mt_wsv], al
        mov     al, [ems_ltab + si]
        call    mt_eout
        add     dh, 40h
        in      al, dx
        mov     [cs:mt_wsv + 1], al
        mov     al, [ems_ltab + si + 1]
        call    mt_eout
        clc
.x:     pop     dx
        pop     ax
        pop     si
        pop     ds
        ret
.no:    stc
        jmp     .x
; the entry at BX's screen handle (TE_SH) still MT's (owner 0, 2 pages)
; -> SI = its record (at KSEG:ems_h + SI), AH 0; else CF.  DS = KSEG;
; AX, DX changed
mt_shm: xor     ax, ax
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
        ret                             ; (CF clear: OR's)
.no:    stc
        ret
mt_wrest:
        mov     dx, EMS_PORT
        mov     al, [cs:mt_wsv]
        call    mt_eout
        add     dh, 40h
        mov     al, [cs:mt_wsv + 1]
        jmp     mt_eout
; the entry at BX's BIOS data (TX_VID) into mt_vs, then its pages mapped
; (mt_smap: CF if gone).  CX, SI, DI, DS, ES changed
mt_vin: push    cs
        pop     es
        mov     ds, [cs:bx+TE_TX]
        mov     si, TX_VID
        mov     di, mt_vs
        mov     cx, VIDLEN
        rep     movsb
        jmp     mt_smap

; ---------------------------------------------------------------------
;  INT 10h.  A background task's calls are done in its own screen
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
%ifdef CRASHLOG
        or      ah, ah                  ; (a mode set: AX)
        jnz     .ncr
        CREC    'V'
.ncr:
%endif
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
        call    mt_cent
        test    byte [cs:bx+TE_VF], SPF_BG
        jnz     .real
        push    KSEG                    ; a critical error's prompt (inside the
        pop     ds                      ;  kernel's INT 24h: everything waits
        cmp     byte [cs:mt_crit], 0    ;  for its answer; raised inside INT 21h
        jne     .real                   ;  or not): on the real screen.  Else
                                        ;  inside INT 21h too the task's,
.k:     call    mt_isr                  ;  whatever hook it comes through.  A
                                        ;  hardware interrupt in service, or an
        jnz     .real                   ;  INT 33h event handler running: on the
        mov     es, [ui_seg]            ;  real screen
        cmp     byte [es:m33_busy], 0
        jne     .real
        mov     es, [cs:bx+TE_TX]       ; (its screen may change: counted, for
        inc     word [es:TX_CHG]        ;  a window showing it)
        cmp     byte [bp+VF_AX+1], 0Eh  ; the teletype, not at a line's end:
        jne     .bl                     ;  the short way
        mov     ds, [cs:bx+TE_TX]
        mov     si, TX_VID
        mov     cl, 1
        call    mt_vfast
        jnc     .ret
.bl:    call    mt_vin                  ; its BIOS data, worked on in mt_vs, and
        jc      .ret                    ;  its screen (its pages gone: the call
                                        ;  goes nowhere)
        push    cs
        pop     ds
        push    EMS_FRAME
        pop     es
        push    bx
        call    mt_emu
.ble:   pop     bx                      ; (mt_emu.s13 knows this return)
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
.dr:    call    mt_cent                 ; (dropped: it may go on to write the
        or      byte [cs:bx+TE_VF], VF_DIRECT   ;  screen itself, so it is frozen
        jmp     .ret                    ;  behind from its next safe point,
                                        ;  as one that does)

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
        ja      .nb                     ; (in a byte: asserted at the end)
.pg:    mov     di, bx
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
        mov     bx, [si + 4Eh - 49h]    ; (the page's start, as the BIOS keeps
        mov     al, dh                  ;  it: mt_vaddrs)
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
        nop                             ; (.set even, as it was)
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
        times   ($ - $$) & 1 db 90h     ; (what follows at its parity)

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
        or      al, al                  ; a terminal window's task: in
        jz      .p                      ;  front at the next switch, for its
        mov     ah, [cs:bx+TE_GEN]      ;  graphics, full screen; back with a
        call    mw_owns                 ;  text mode (mt_vshad)
        jc      .p
        mov     [cs:mt_swreq], al
        push    es
        mov     es, [cs:bx+TE_TX]
        mov     byte [es:TX_WGFX], 1
        push    word [cur_psp]          ; (DS = KSEG: the program asking)
        pop     word [es:TX_WPSP]
        pop     es
.p:     call    mt_pick
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

; NZ if an INT 33h event handler runs (m33_busy; DS = KSEG); else mt_busy's
mt_b33: push    es
        mov     es, [ui_seg]
        cmp     byte [es:m33_busy], 0
        pop     es
        jne     mt_isr.x
; NZ if MT is inside a call it passed on to the BIOS, an INT 13h call or
; a change of the front, or the kernel's INT 24h runs; else mt_isr's
mt_busy:
        cmp     byte [cs:mt_inb], 0
        jne     mt_isr.x
        cmp     word [cs:mt_in13], 0    ; (and mt_swing)
        jne     mt_isr.x
        cmp     byte [cs:mt_crit], 0
        jne     mt_isr.x
; the PIC's in-service register -> AH; ZF if no interrupt is in service.
; AL changed
mt_isr: mov     al, 0Bh
        out     20h, al
        in      al, 20h
        mov     ah, al
        mov     al, 0Ah
        out     20h, al
        or      ah, ah
.x:     ret

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
; screen, since everything waits for its answer.  A background task's
; behind a graphics screen is Fail, an invalid disk change's too: held
; there, the others couldn't use a disk (the transfer's state is the
; kernel's) and nobody could see the question
mt_c24: push    ds                      ; (a task not in front, a graphics
        push    ax                      ;  screen in front: Fail, not a
        mov     al, [cs:mt_cur]         ;  prompt, its handler's or
        cmp     al, [cs:mt_front]       ;  mt_i24's, where nobody could
        je      .p                      ;  read it, everything stopped for
        xor     ax, ax                  ;  its answer.  A text one: its
        mov     ds, ax                  ;  handler runs, as MS-DOS)
        mov     al, [449h]              ; (the BIOS's mode: text 0-3, 7)
        cmp     al, 7
        je      .p
        cmp     al, 3
        jbe     .p
        pop     ax
        pop     ds
        mov     al, 83h                 ; (Fail, nobody asked: the disk's
        retf                            ;  changes kept, KDISK.INC rule 4)
.p:     pop     ax
        pop     ds
.f:     mov     si, crit_dev
        inc     byte [cs:mt_crit]
        int     24h
        cmp     byte [cs:mt_crit], 0    ; (cleared meanwhile: its handler ran a
        je      .x                      ;  program that ended)
        dec     byte [cs:mt_crit]
.x:     retf

; INT 13h: counted while it runs (mt_in13), so mt_v10 knows an INT 10h call
; meanwhile is an interrupt's, while a floppy's DMA may be going into the
; EMS frame: no window is mapped for it.  Its AX, BX and ES kept (the
; transfer, for mt_dcan).  Another task's call while a floppy owner is
; out waits for it (mt_gate), or is refused: AH = 80h, CF.  CF and
; the rest as the BIOS gives them back
mt_i13: cmp     byte [cs:mt_down], 0FFh
        jne     .g
.go:    mov     [cs:mt_13ax], ax
        mov     [cs:mt_13bx], bx
        mov     [cs:mt_13es], es
        inc     byte [cs:mt_in13]
        pushf
        call    far [cs:mt_old13]
        pushf
        dec     byte [cs:mt_in13]
        popf
        retf    2
.g:     call    mt_gfl
        jnc     .go
        mov     ah, 80h                 ; (a time-out, as no drive answering)
        sti
        stc
        retf    2

; =====================================================================
;  Tasks run while one waits on the floppy.  The 1520's BIOS calls
;  INT 15h AX=9001h before it waits for the controller's interrupt (IRQ 6,
;  whose handler calls AX=9101h), and takes CF back as a time-out.  At
;  9001h the waiting task (the owner) is switched from, where it can be
;  (mt_dcan), and another runs; 9101h, or about 2 s (mt_dto), makes it
;  ready, the next to run (mt_want), CF clear or set.  While it is out,
;  the kernel's disk code is half way through its call: only tasks
;  outside the kernel run (mt_dok), and their way in (INT 21h, 13h,
;  25h/26h; 67h while the cache's EMS windows are held) waits for the
;  owner to run again (mt_gate), or, where nothing can wait (an
;  interrupt's handler, a nested call), is refused.
;  The same at the hard disk's waits.  KHD.INC calls AX=9000h at a
;  wait IRQ 14 ends (after about 2 ms of it), and polls on when back; MT
;  takes IRQ 14 itself (mt_i76), where the BIOS hasn't the disk, and the
;  tick looks at the drive's status too (a dead line: mt_htk)
; =====================================================================
MT_DTO      equ 37                      ; (ticks: about 2 s, the BIOS's own wait)

; INT 15h: AX=9001h and 9101h (the floppy), 9000h and 9100h (the hard disk),
; 8500h (SysReq), the rest on
mt_i15: cmp     ax, 9001h
        je      mt_dwait
        cmp     ax, 9000h
        je      mt_hwait
        cmp     ax, 9101h
        je      .e
        cmp     ax, 9100h               ; (the BIOS's IRQ 14, with a disk of its
        je      .e                      ;  own: mt_i76 calls it first)
%ifndef NOSYSREQ
.s1:    cmp     ax, 8500h
        je      .s
.s2:
%endif
.o:     jmp     far [cs:mt_old15]
%ifndef NOSYSREQ
; SysReq down (the 1520's INT 9, once while it is held; never in the
; key buffer, so it takes no key from the program in front): the next
; task to the front, as CODE-Tab, at mt_hot's next look.  Not Confm
; (CODE-SysReq: CODE, the BIOS's Alt, held in 40:17h): the program's.
; Passed on either way.  Built without it: -dNOSYSREQ
.s:     push    ds
        push    40h
        pop     ds
        test    byte [17h], 8
        pop     ds
        jnz     .o
        mov     byte [cs:mt_sysrq], 1
        jmp     .o
        times   (.s2 - .s1 + $ - .s) & 1 db 90h ; (SysReq's bytes even: what follows
                                        ;  keeps its parity)
%endif
.e:     cmp     byte [cs:mt_down], 0FFh ; the device's interrupt: its owner,
        je      .o                      ;  out, ready, and the next to run
        cmp     al, [cs:mt_ddev]        ; (out on this device)
        jne     .o
        push    ax
        push    bx
        mov     al, [cs:mt_down]
        call    mt_dready
        pop     bx
        pop     ax
        jmp     .o

; IRQ 6, the floppy's: the BIOS's handler first (its EOI, its 9101h:
; the owner ready, mt_dready); then, with the owner ready, its turn now,
; as at a tick's end (mt_tick.v: what was interrupted vetted by mt_safe;
; else at the next tick, or the waiting task's next look)
mt_i0e: pushf
        call    far [cs:mt_old0e]
        cli
        CRW     'i'                     ; (CRASHLOG: IRQ 6 come)
        push    ax                      ; mt_tick's frame: AX, BX, DX, DS, BP
        push    bx
        push    dx
        push    ds
        push    bp
        mov     bx, 0Eh * 4
        mov     dx, mt_i0e
; (mt_i0e, mt_i76: the owner ready?  Then its turn now, if the vector at
; BX is still DX here, MT's: else a hook ahead of it was interrupted)
mt_iend:
        mov     bp, sp
        push    KSEG
        pop     ds
        cmp     byte [cs:mt_down], 0FFh
        je      .r
        mov     al, [cs:mt_down]
        push    bx
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_RUN
        pop     bx
        jne     .r
        push    es
        xor     ax, ax
        mov     es, ax
        cmp     [es:bx], dx
        jne     .h
        mov     ax, cs
        cmp     [es:bx+2], ax
.h:     pop     es
        jne     .r
        jmp     mt_tick.v
.r:     jmp     mt_tick.r

; IRQ 14, the hard disk's: the BIOS's handler first where it has the
; disk too (40:75h; its EOI, 40:8Eh, its 9100h: the owner ready, mt_i15);
; else the EOIs here, and the owner ready.  Then as mt_i0e.  (An IRQ 14
; with nobody out: one of the polled waits', counted only, mt_hirq)
mt_i76: push    ax
        push    ds
        xor     ax, ax
        mov     ds, ax
        cmp     [475h], al
        pop     ds
        je      .m
        pushf
        call    far [cs:mt_old76]
        cli
        jmp     short .c
.m:     mov     al, 20h
        out     0A0h, al
        out     20h, al
.c:     mov     byte [cs:mt_hirq], 1
        push    bx
        push    dx
        push    ds
        push    bp
        cmp     byte [cs:mt_ddev], 0
        jne     .v
        mov     al, [cs:mt_down]
        cmp     al, 0FFh
        je      .v
        call    mt_dready
.v:     mov     bx, 76h * 4
        mov     dx, mt_i76
        jmp     mt_iend

; INT 77h: IRQ 15, or the PIC's default answer when the drive's
; INTRQ went (a status read) before the CPU took IRQ 14.  The master's EOI,
; and the slave's only if IRQ 15 is in service.  (The 1520's 10/25/89
; BIOS sends both; its 1988 one neither, which would leave IRQ 3-15 off)
mt_i77: push    ax
        mov     al, 0Bh                 ; (OCW3: the slave's in-service bits,
        out     0A0h, al                ;  then its requests again)
        in      al, 0A0h
        test    al, 80h
        mov     al, 0Ah
        out     0A0h, al
        mov     al, 20h
        jz      .m
        out     0A0h, al
.m:     out     20h, al
        pop     ax
        iret
        db      90h                     ; (mt_par: what follows at its parity)

; task AL (mt_down) ready again, from its floppy's wait: the next to run,
; soon (mt_pend: the tick's, or a waiting task's look).  BX changed
mt_dready:
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITD
        jne     .x                      ; (called by 9101h and IRQ 6 both:
.w:     mov     byte [cs:bx+TE_STATE], TS_RUN   ;  .w once a wait)
        mov     [cs:mt_want], al
        mov     byte [cs:mt_pend], 1
.x:     ret

; the tick, with an owner out and waiting: its time-out counted; the hard
; disk's status looked at (not busy: ready, as by its IRQ 14; with none
; come yet, one more to mt_htk's count) (interrupts off).  All kept
mt_dtick:
        push    ax
        push    bx
        mov     al, [cs:mt_down]
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITD
        jne     .n
        cmp     byte [cs:mt_ddev], 0
        jne     .t
        call    mt_ddone
        jz      .t
        cmp     byte [cs:mt_hirq], 0
        jne     .r
        inc     byte [cs:mt_htk]
        jmp     short .r
.t:     dec     byte [cs:mt_dto]
        jnz     .n
        mov     byte [cs:mt_dtmo], 1
.r:     call    mt_dready
.n:     pop     bx
        pop     ax
        ret

; INT 15h AX=9001h: the floppy's controller is about to be waited for.
; The task switched from here if it can be (mt_dcan) and another can run
; meanwhile; back when it has run again (CF: by the time-out).  Else the
; BIOS waits, as before.  Back with RETF 2: interrupts on, CF as said.
; mt_hwait: AX=9000h, KHD.INC's at the hard disk's wait, the same
mt_hwait:
%ifdef NODWAIT
        jmp     far [cs:mt_old15]       ; (bisect build: no wait given away)
%endif
        push    ds
        push    es
        pusha
        mov     al, 0                   ; (mt_ddev: the hard disk)
        jmp     short mt_dwait.c
mt_dwait:
%ifdef NODWAIT
        jmp     far [cs:mt_old15]
%endif
        push    ds
        push    es
        pusha
        mov     al, 1                   ; (the floppy)
.c:     cli
        cmp     byte [cs:mt_down], 0FFh ; (one out already: not the kernel's
        jne     .s                      ;  call, nothing here touched)
        mov     [cs:mt_ddev], al
        push    KSEG
        pop     ds
        mov     byte [cs:mt_dtmo], 0
        call    mt_dcan                 ; (sets mt_dfw)
        jc      .x
        call    mt_fdrain               ; (interrupts on a moment: IRQ 6 may
        call    mt_ddone                ;  come then)
        jnz     .x
.out:   call    mt_cent                 ; (.out: a block's start, test_mt's)
        mov     [cs:mt_down], al        ; out: only those it allows run
        mov     byte [cs:mt_dto], MT_DTO
        mov     byte [cs:bx+TE_STATE], TS_WAITD
        call    mt_pick
        jc      .u
%ifdef CRASHLOG
        CRW     'g'                     ; (KCRASH.INC: going out, its stack kept)
        call    mt_crs0
%endif
        call    mt_switch               ; (back once 9101h or the time-out
.bk:                                    ;  made it ready, and it was picked)
%ifdef CRASHLOG
        call    mt_crs1                 ; (as it was?  Else the report)
        CRW     'b'                     ; (back)
%endif
        mov     byte [cs:mt_down], 0FFh
        mov     byte [cs:mt_dfw], 0
        call    mt_dwake
        call    mt_cent                 ; (frozen behind meanwhile, CODE-Tab:
        call    mt_frz                  ;  picked all the same, mt_pick; it
        jz      .x                      ;  gives way at the next safe point)
        mov     byte [cs:mt_pend], 1
        jmp     short .x
.u:     mov     byte [cs:mt_down], 0FFh ; (none to run: as before)
        mov     byte [cs:mt_dfw], 0
        call    mt_cent
        mov     byte [cs:bx+TE_STATE], TS_RUN
.x:     popa
        pop     es
        pop     ds
        cmp     byte [cs:mt_dtmo], 1    ; (CF if it came back by the time-out)
        cmc
        sti
        retf    2
.s:     popa
        pop     es
        pop     ds
        jmp     far [cs:mt_old15]

; ZF clear if the device's interrupt has come: the floppy's (40:3Eh bit
; 7); the hard disk not busy (its status read: that ends its INTRQ, and an
; IRQ 14 still on its way becomes an INT 77h, mt_i77).  All kept
mt_ddone:
        push    ax
        cmp     byte [cs:mt_ddev], 0
        je      .h
        push    ds
        push    0
        pop     ds
        mov     al, [43Eh]
        pop     ds
        jmp     short .t
.h:     push    dx
        mov     dx, 1F7h
        in      al, dx
        pop     dx
        not     al
.t:     test    al, 80h
        pop     ax
        ret

; may the task at the floppy's wait (9001h) be switched from?  CF if not:
; the interrupt already in; another INT 13h call running round this one
; (the hard disk's, 9000h: any; and none after IRQ 14 is found dead,
; mt_htk), a call MT passed on to the BIOS, the kernel's INT 24h, a change of the
; front, any interrupt in service, the UI's mouse event; MT_KILL ended it
; (it ends after its call); inside INT 21h, unless the kernel's stack is
; the one (an INT 28h hook's call on its own stack: no) and its slice fits
; the TX; outside it, unless its stack is its own; a transfer in EMS
; windows 0 or 1 (MT maps a task's screen there), or partly outside the
; frame.  A transfer in windows 2-3 (the cache's): those held (mt_dfw).
; (The hard disk's data moves by the owner's own REP INSW/OUTSW, its EMS
; map back first: no window held)
; DS = KSEG; interrupts off; AX, BX, DX changed
mt_dcan:
        mov     byte [cs:mt_dfw], 0
        call    mt_ddone
        jnz     .no
        mov     al, [cs:mt_in13]        ; (the floppy's own: 1; the hard
        cmp     al, [cs:mt_ddev]        ;  disk's, KHD's: 0)
        jne     .no
        or      al, al
        jnz     .f
        cmp     byte [cs:mt_htk], 2
        jae     .no
.f:
        cmp     byte [cs:mt_inb], 0
        jne     .no
        cmp     byte [cs:mt_crit], 0
        jne     .no
        cmp     byte [cs:mt_swing], 0
        jne     .no
        call    mt_isr
        jnz     .no
        push    es
        mov     es, [ui_seg]
        cmp     byte [es:m33_busy], 0
        pop     es
        jne     .no
        call    mt_cent
        cmp     byte [cs:bx+TE_KILL], 0
        jne     .no
%ifdef NODWAIT0
        or      al, al                  ; (bisect build: task 0, the Executive
        jz      .no                     ;  and its windows, never goes out)
%endif
        mov     al, [indos]
        or      al, al
        jz      .own
        dec     al
        jnz     .no
        mov     ax, ss
        cmp     ax, KSEG
        jne     .no
        mov     ax, kstack_top          ; (and room for mt_switch's own
        sub     ax, sp                  ;  pushes)
        cmp     ax, KSLICE - 48
        jae     .no
        jmp     short .em
.own:   mov     ax, ss
        call    mt_mine
        jc      .no
.em:    cmp     byte [cs:mt_ddev], 0
        je      .y
        mov     ax, [cs:mt_13ax]        ; a read or write: its buffer, linear
        cmp     ah, 2                   ;  (20 bits), and its length
        jb      .y
        cmp     ah, 3
        ja      .y
        xor     ah, ah
        mov     cx, ax                  ; (CX: sectors, kept by pusha)
        mov     ax, [cs:mt_13es]
        mov     dx, ax
        shl     ax, 4
        shr     dx, 12
        add     ax, [cs:mt_13bx]
        adc     dx, 0                   ; DX:AX its start
        cmp     dx, 0Eh                 ; (below the frame: no window)
        jb      .y
        ja      .no                     ; (past it: no window either; not one
                                        ;  for a DMA, anyway)
        cmp     ax, 8000h               ; in windows 0 or 1
        jb      .no
        mov     bx, ax                  ; its end (as far as it reaches):
        shl     cx, 9                   ;  still in the frame?
        add     bx, cx
        jc      .no
        dec     bx
        mov     dl, 4                   ; window 2, and 3 if it reaches it
        cmp     ax, 0C000h
        jb      .w2
        mov     dl, 0
.w2:    cmp     bx, 0C000h
        jb      .w3
        or      dl, 8
.w3:    mov     [cs:mt_dfw], dl
.y:     clc
        ret
.no:    stc
        ret

; task AL (its entry at BX): may it run now?  NZ if not: a floppy owner
; out, and AL not it, and inside INT 21h (switched from at a key
; wait: its kernel code may write a file, a redirected handle), or with
; an EMS window the owner's transfer holds mapped (as it last ran).
; Registers kept
mt_dok: cmp     byte [cs:mt_down], 0FFh
        je      .y
        cmp     al, [cs:mt_down]
        je      .y
        push    es
        mov     es, [cs:bx+TE_TX]
        cmp     word [es:TX_KLEN], 0
        jne     .n
        test    byte [cs:mt_dfw], 4
        jz      .w3
        cmp     byte [es:TX_EMS + 2], 0
        jne     .n
.w3:    test    byte [cs:mt_dfw], 8
        jz      .ok
        cmp     byte [es:TX_EMS + 3], 0
        jne     .n
.ok:    cmp     byte [cs:mt_ddev], 1    ; a floppy's owner out: its DMA may run,
        jne     .k                      ;  and on the 1520 an EMS page register
        push    ax                      ;  written meanwhile resets the machine
        push    cx                      ;  (2026-11-04): only a task whose
        push    dx                      ;  windows hold what they hold now, so
        push    di                      ;  loading it writes none (mt_eout:
        mov     cl, [cs:mt_dfw]         ;  the held ones aren't written)
        mov     dx, EMS_PORT
        mov     di, TX_EMS
.e:     test    cl, 1
        jnz     .en
        in      al, dx
        cmp     al, [es:di]
        jne     .ne
.en:    shr     cl, 1
        inc     di
        add     dh, 40h
        jnc     .e
        cmp     al, al                  ; (all as they are: ZF)
.ne:    pop     di
        pop     dx
        pop     cx
        pop     ax
        jne     .n
.k:     pop     es
.y:     cmp     al, al                  ; (ZF)
        ret
.n:     pop     es
        or      sp, sp                  ; (NZ)
        ret

; AL to the EMS page register at DX: not written if it holds AL already;
; else, while a floppy transfer is in flight (the controller busy with a
; command and not yet at its result: its DMA under way), first waited for,
; as on the 1520 a page register written meanwhile resets the machine
; (2026-11-04: the switch at a floppy's wait, mt_load).  At most about a
; turn of the disk: the controller then gives up or ends.  All kept, the
; flags too (mt_punmap's callers carry CF across it)
mt_eout:
        pushf
        push    ax
        mov     ah, al
        in      al, dx
        cmp     al, ah
        je      .x
        push    cx
        push    dx
        mov     dx, 3F4h                ; (the floppy controller's status)
        mov     cx, 8
.o:     push    cx
        xor     cx, cx
.w:     in      al, dx
        test    al, 10h                 ; (a command under way)
        jz      .go
        and     al, 0C0h                ; (its result phase: the DMA done)
        cmp     al, 0C0h
        je      .go
        loop    .w
        pop     cx
        loop    .o
        push    cx
.go:    pop     cx
        pop     dx
        pop     cx
        mov     al, ah
        out     dx, al
.x:     pop     ax
        popf
        ret

; the owner runs again: tasks that waited for it (TS_WAITD, at mt_gate)
; ready (each looks again).  Registers kept
mt_dwake:
        push    ax
        push    bx
        xor     al, al
.l:     call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_WAITD
        jne     .n
        mov     byte [cs:bx+TE_STATE], TS_RUN
.n:     inc     al
        cmp     al, MT_TASKS
        jb      .l
        pop     bx
        pop     ax
        ret

; an INT's hook, a floppy owner out, its caller not it: mt_gate with the
; caller's flags (the INT's frame above this call and the hook's return,
; [SP+6]).  CF: refused.  All kept but the flags
mt_gfl: push    dx
        push    bp
        mov     bp, sp
        mov     dx, [bp+10]             ; (BP, DX, our return, the hook's
        pop     bp                      ;  frame: IP, CS, flags)
        call    mt_gate
        pop     dx
        ret

; wait while a floppy owner is out: this task waits (TS_WAITD) while
; another runs, or HLTs if none can; on when the owner has run again.  CF
; if it can't wait here (refused): the caller's interrupts were off; an
; interrupt in service (a handler's call); inside INT 21h (a nested call:
; an INT 24h handler's); a call MT passed on to the BIOS, the kernel's
; INT 24h, a change of the front, the UI's mouse event.  DX = the caller's
; flags.  All kept but the flags
mt_gate:
        push    ax
        push    bx
        push    ds
        push    es
        push    KSEG
        pop     ds
.l:     cli
        cmp     byte [cs:mt_down], 0FFh
        je      .y
        test    dh, 2
        jz      .no
        cmp     byte [indos], 0
        jne     .no
        cmp     byte [cs:mt_inb], 0
        jne     .no
        cmp     byte [cs:mt_crit], 0
        jne     .no
        cmp     byte [cs:mt_swing], 0
        jne     .no
        call    mt_isr
        jnz     .no
        mov     es, [ui_seg]
        cmp     byte [es:m33_busy], 0
        jne     .no
        call    mt_cent
        mov     byte [cs:bx+TE_STATE], TS_WAITD
        call    mt_pick
        jc      .h
        call    mt_fdrain
        CRW     'G'                     ; (CRASHLOG: a call held at the gate)
        call    mt_switch
        jmp     .l
.h:     CRW     'H'                     ; (CRASHLOG: held, HLT)
        call    mt_cent                 ; (none: this one HLTs, ready, till
        mov     byte [cs:bx+TE_STATE], TS_RUN   ;  an interrupt, the owner's
        sti                             ;  9101h one, then looks again)
        hlt
        jmp     .l
.y:     clc
        jmp     short .x
.no:    CRW     'r'                     ; (CRASHLOG: refused)
        stc
.x:     pop     es
        pop     ds
        pop     bx
        pop     ax
        ret

; INT 21h's entry (int21's first 5 bytes: STI, CLD, PUSH ES, PUSH DS,
; PUSHA, a JMP FAR here; INT 20h's and 27h's too, which go there): with a
; floppy owner out, another task's call waits for it (mt_gate), or is
; refused: AX = 5, CF
mt_i21: cmp     byte [cs:mt_down], 0FFh
        jne     .g0
.go:    sti
        cld
        push    es
        push    ds
        pusha
        jmp     KSEG:int21 + 5
.g0:    CRW     'q'                     ; (CRASHLOG: a call while one is out)
.g:     call    mt_gfl
        jnc     .go
        push    bp                      ; (refused: CF in its flags)
        mov     bp, sp
        or      byte [bp+6], 1
        pop     bp
        mov     ax, 5
        iret

; INT 25h and 26h (C:'s absolute disk calls, KHD's): the same.  Refused:
; AX = 8002h (not ready), CF, the flags left pushed, as they leave them
mt_i25: cmp     byte [cs:mt_down], 0FFh
        jne     .g
.go:    jmp     far [cs:mt_old25]
.g:     call    mt_gfl
        jnc     .go
.no:    mov     ax, 8002h
        sti
        stc
        retf
mt_i26: cmp     byte [cs:mt_down], 0FFh
        jne     .g
.go:    jmp     far [cs:mt_old26]
.g:     call    mt_gfl
        jnc     .go
        jmp     mt_i25.no

; INT 67h's entry (ems_int67's first 5 bytes: CMP AH,44h / JNE ems_gen, a
; JMP FAR here): with the cache's EMS windows held for an owner's transfer
; (mt_dfw), another task's call (it may map one of them) waits, or is
; refused: AH = 80h
mt_i67: cmp     byte [cs:mt_dfw], 0
        jne     .g
        cmp     byte [cs:mt_down], 0FFh ; (a floppy's owner out: its DMA may
        je      .go                     ;  run, and the call may write a page
        cmp     byte [cs:mt_ddev], 1    ;  register: it waits too)
        je      .g
.go:    cmp     ah, 44h
        je      .m
        jmp     KSEG:ems_gen
.m:     jmp     KSEG:ems_int67.p
.g:     call    mt_gfl
        jnc     .go
        mov     ah, 80h
        iret

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
        pushf
        call    mt_wback
        popf
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

; The front task's own mode set (BX = its entry; CF: a graphics one).
; A terminal window's task in front for its graphics (TX_WGFX 1) goes
; back to its window with a text mode: task 0 in front at the next switch
; (TX_WGFX 2, mt_scrsv's 0); a graphics mode again before that switch
; keeps it in front (1).  All kept
mt_wback:
        push    ax
        push    es
        mov     ah, 0
        adc     ah, 0                   ; (AH: 1 for graphics)
        mov     al, [cs:mt_cur]
        cmp     al, [cs:mt_front]       ; (the front task's own call: not
        jne     .x                      ;  another's, BG='s, made for real)
        mov     es, [cs:bx+TE_TX]
        mov     al, [es:TX_WGFX]
        or      ah, ah
        jnz     .g
        cmp     al, 1                   ; a text mode: back
        jne     .x
        mov     byte [es:TX_WGFX], 2
        mov     byte [cs:mt_swreq], 0
        jmp     short .x
.g:     cmp     al, 2                   ; graphics again, still in front:
        jne     .x                      ;  stays so
        cmp     byte [cs:mt_swreq], 0
        jne     .x
        mov     byte [es:TX_WGFX], 1
        mov     byte [cs:mt_swreq], 0FFh
.x:     pop     es
        pop     ax
        ret

; mode AL as the 1520's BIOS takes it: 0-3 text, 4-6, 40h, 48h, 74h
; graphics (CF), anything else mode 2 (AL = the text mode)
mt_tmode:
        cmp     al, 6
        jbe     .t
        cmp     al, 40h
        je      .t
        cmp     al, 48h
        je      .t
        cmp     al, 74h
        je      .t
        mov     al, 2
.t:     cmp     al, 4
        cmc
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
.ok:    clc                             ; (every handler ends with CF known, 1
        ret                             ;  the wait: 0 as each starts, after
                                        ;  SHL BX, and at a bare RET from the
                                        ;  last AND, OR, TEST, XOR or .pg)
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
        ret
; 01h: the cursor's shape
.m1:    mov     ax, [bp+VF_CX]
        mov     [VS_SHAPE], ax
        ret
; 02h, 03h: page BH's cursor
.m2:    call    .pg
        jc      .ok
        mov     ax, [bp+VF_DX]
        mov     [VS_CUR + bx], ax
.m2x:   clc
        ret
.m3:    mov     ax, [VS_SHAPE]          ; (the shape, whatever the page)
        mov     [bp+VF_CX], ax
        call    .pg
        jc      .m2x
        mov     ax, [VS_CUR + bx]
        mov     [bp+VF_DX], ax
        ret
; 04h: the light pen, not triggered
.m4:    mov     byte [bp+VF_AX+1], 0
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
        jc      .m8x                    ; (AX back as it came)
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
        call    .pg
        jc      .wz
        push    dx
        mov     dx, [VS_CUR + bx]
        shr     bx, 1
        call    mt_vaddr
        pop     dx
        mov     ah, [bp+VF_BX]          ; (AL the caller's still)
        or      dl, dl                  ; 09h's run inside the 32 KB, not
        jz      .wl                     ;  round 16 bits: at once
        mov     bx, cx
        shl     bx, 1
        jc      .wl                     ; (CX 8000h or more: round them)
        add     bx, di
        jc      .wl
        cmp     bx, 8000h
        ja      .wl
        rep     stosw
        jmp     short .wz
            db      0                   ; (pad: .wl even, never run)
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
            db      0                   ; (pad: what follows at main's parity)
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
        ret
; 0Ch, 0Dh in a text mode: nothing (VidGrapPelMask's CF), AH back as the
; mode
.mC:    mov     al, [VS_MODE]
        mov     [bp+VF_AX+1], al
.mCx:   ret
; 0Eh: the teletype, on the page shown whatever BH says
.mE:    mov     bl, [VS_PAGE]
        cmp     bl, 10
        ja      .mCx
        xor     bh, bh
        mov     si, bx
        shl     si, 1
        mov     bh, bl
        mov     dx, [VS_CUR + si]
        xor     cl, cl                  ; (the character only, as 0Ah; AL the
                                        ;  caller's still)
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
.sz:    ret
.s13:   mov     bx, sp                  ; (in front: the shadow lost.  Behind,
        cmp     word [ss:bx], mt_v10.ble ;  mt_v10.bl's: dropped, the shadow
        je      .sz                     ;  kept)
        call    mt_vlose
        clc
        ret
; BX = 2 * the page in the caller's BH; CF if past page 10
.pg:    mov     bl, [bp+VF_BX+1]
        xor     bh, bh
        shl     bx, 1
        cmp     bx, 2 * 11
        cmc
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
; VidCalcOffsets works it out (16 bits); mt_vaddrs: on the page shown,
; from its start as the BIOS keeps it (40:4Eh: 40:62h x 40:4Ch while the
; BIOS keeps them in step; MTSCR E checks it does).  All else kept
        times   ($ - $$) & 1 db 90h     ; (mt_vaddrs even)
mt_vaddrs:
        push    ax
        mov     di, [VS_START]
        jmp     short mt_vaddr.r        ; (the jump here: mt_vaddr, per
        times   ($ - $$) & 1 db 90h     ;  character, falls through; even)
mt_vaddr:
        push    ax
        push    dx
        mov     al, bl
        xor     ah, ah
        mul     word [VS_LEN]
        mov     di, ax
        pop     dx
.r:     mov     al, dh
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
; (every teletype scroll) is moved at once, from the page shown's start
; as the BIOS keeps it (40:4Eh).  All kept
        times   ($ - $$) & 1 db 90h     ; (mt_vscr even)
mt_vscr:
        pusha
        cmp     dh, 25                  ; (the clamps)
        jb      .c1
        mov     dh, 24
.c1:    cmp     dl, [VS_COLS]
        jb      .c2
        mov     dl, [VS_COLS]
        dec     dl
; up to its bound test the fast way keeps AL, BX, CX and DX as clamped
; (AX in BP across the multiplying): .lit takes them so, from any jump
.c2:    cmp     ch, dh
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
        mov     bp, ax
        mov     al, ah
        mul     byte [VS_COLS]
        mov     si, ax                  ; (SI: the words in all the rows)
        mov     al, ch
        mul     byte [VS_COLS]
        shl     ax, 1
        add     ax, [VS_START]
        mov     di, ax                  ; (DI: the top row's start)
        mov     ax, si
        shl     ax, 1
        add     ax, di
        xchg    ax, bp                  ; (AX back, the flags kept)
        jc      .lit
        cmp     bp, 8000h
        ja      .lit
        cmp     al, ah                  ; (AL 0 unless below the rows: no
        sbb     cl, cl                  ;  branch; CL, 0 here, free from
        and     al, cl                  ;  this test on)
        mul     byte [VS_COLS]          ; (AX: the words AL lines hold)
        mov     cx, si
        or      ax, ax
        jz      .fa
        sub     cx, ax                  ; (CX: the words moved, DX: blanked)
        mov     dx, ax
        shl     ax, 1
        push    ds
        push    es
        pop     ds
        or      bl, bl
        jnz     .fd
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
        mov     cx, dx
.fa:    mov     al, ' '
        mov     ah, bh
        rep     stosw
        popa
        ret
        times   ($ - $$) & 1 db 90h     ; (.lit even)
; the BIOS's own way, register for register (AH the rows moved to .lc)
.lit:   mov     [mt_va], bh
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
        mov     [mt_vn], al             ; the lines; AH the rows moved (0: 256)
        mov     al, dh
        inc     al
        sub     al, ch
        sub     al, ah
        mov     [mt_vb], al             ; the rows blanked (0: 256)
        or      bl, bl
        jnz     .ld
        mov     dh, ch                  ; (up: from the top row, down: the
.ld:    mov     dl, cl                  ;  bottom one)
        call    mt_vaddrs
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
        popa
        ret
        times   ($ - $$) & 1 db 90h     ; (mt_vmov even)

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
        ja      .p
        rep     stosw
        jmp     short .y
.p:     cmp     di, 8000h - 1           ; (all of it past the 32 KB, not round
        jb      .w                      ;  16 bits: none written)
        mov     di, dx
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
        xor     bx, bx                  ; (the best so far: its MCB)
        mov     dx, [mt_size]
        mov     ax, [mt_mcb0]
.w:     mov     es, ax
        mov     cl, [es:0]              ; (a chain gone bad: none)
        cmp     cl, 'M'
        je      .w1
        cmp     cl, 'Z'
        jne     .no
.w1:    cmp     word [es:1], 0
        jne     .nx
        KCALL   mem_merge               ; free: merge the free ones after it
        cmp     [es:3], dx
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
.x:     pop     es
        ret

; ---------------------------------------------------------------------
;  A task's region grows on demand.  A 48h or an EXEC its arena
;  can't meet (mt_48, mt_largest) takes room from the free block just
;  below the region, MT_GRES left in it.  Nothing moves: the region's
;  MCB is rewritten lower, and the room is the first block of the task's
;  own chain (first_mcb), in front of its TX, stub and environment (an
;  owner-8 block, "TX", from the first growth on; TE_TX stays, TE_REG
;  moves down).  Only 48h and EXEC: 4Ah grows a block into what follows
;  it, never into what is in front.
; ---------------------------------------------------------------------
MT_GROW     equ 100h                    ; (in steps of 4 KB, or what fits)
MT_GRES     equ TX_PARAS + ST_PARAS + ENVMAX / 16 + 2 + MT_DEFARENA + RUN_ROOM
                                        ; (left: a task of 64 KB, and the
                                        ;  Executive's room for a .RUN; as
                                        ;  mt_urun leaves for an .EXE)

; the running task (not task 0) given room for a block of BX paragraphs at
; its chain's start.  CF if it can't (BX F000h or more: 48h FFFFh asks, it
; doesn't need; no free block just below its region, or not MT_GRES left
; in it): nothing changed.  DS = KSEG; all kept but the flags
mt_grow:
        pusha
        push    es
        cmp     bx, 0F000h
        jae     .no
        mov     di, bx                  ; DI: paragraphs wanted
        call    mt_cent                 ; BX: its entry
        mov     si, [cs:bx+TE_REG]
        dec     si                      ; SI: the region's MCB
        mov     ax, [cs:mt_mcb0]        ; the free block just below it (the
.w:     mov     es, ax                  ;  arena walked, free neighbours merged
        cmp     byte [es:0], 'M'        ;  as in mt_carve; the end, or a chain
        jne     .no                     ;  gone bad: none)
        cmp     word [es:1], 0
        jne     .nx
        KCALL   mem_merge
.nx:    mov     cx, ax                  ; the next one the region's MCB?
        add     cx, [es:3]
        inc     cx
        cmp     cx, si
        je      .f
        ja      .no                     ; (past it: can't be)
        mov     ax, cx
        jmp     .w
.f:     cmp     word [es:1], 0          ; (ES: that block) free?
        jne     .no
        mov     ax, di                  ; AX: d, the paragraphs it gives; BP:
        xor     bp, bp                  ;  0 the first growth, 1 the chain's
        mov     dx, [cs:bx+TE_TX]       ;  first block free, 2 a program's
        cmp     dx, [cs:bx+TE_REG]
        jne     .ag
        add     ax, 2                   ; (a free block's MCB, and the TX's)
        jmp     short .rd
.ag:    inc     bp
        push    es
        mov     es, [first_mcb]
        cmp     word [es:1], 0
        jne     .ow
        sub     ax, [es:3]              ; (free: by what it lacks)
        pop     es
        jbe     .no
        jmp     short .rd
.ow:    pop     es
        inc     bp
        inc     ax                      ; (a program's: a free block's MCB)
.rd:    mov     cx, [es:3]              ; CX: what the block below can give
        sub     cx, MT_GRES
        jb      .no
        cmp     ax, cx
        ja      .no
        mov     dx, ax                  ; (in steps of 4 KB, if that fits too)
        add     dx, MT_GROW - 1
        jc      .g
        and     dx, -MT_GROW
        cmp     dx, cx
        ja      .g
        mov     ax, dx
.g:     pushf
        cli
        sub     [es:3], ax              ; given: AX paragraphs
        mov     es, si                  ; the region's MCB, AX lower: its size
        mov     cx, [es:3]              ;  and name ("Tn")
        add     cx, ax
        mov     dx, [es:8]
        push    dx
        mov     dx, si
        sub     dx, ax
        mov     es, dx
        mov     byte [es:0], 'M'
        mov     word [es:1], 8
        mov     [es:3], cx
        pop     cx
        call    mt_mcbnm
        inc     dx                      ; DX: the region's start, the chain's
        mov     cx, [first_mcb]         ;  new first block (CX: the old one)
        mov     [cs:bx+TE_REG], dx
        mov     [first_mcb], dx
        mov     es, dx
        mov     byte [es:0], 'M'
        mov     word [es:1], 0
        dec     bp
        jz      .g1
        jns     .g2
        sub     ax, 2                   ; the first growth: a free block, then
        mov     [es:3], ax              ;  the old MCB's paragraph the TX's,
        mov     es, si                  ;  the stub's and the environment's
        mov     word [es:1], 8          ;  block (owner 8, "TX") to the old
        sub     cx, si                  ;  first block
        dec     cx
        mov     [es:3], cx
        mov     cx, 'TX'
        call    mt_mcbnm
        jmp     short .gx
.g1:    mov     es, cx                  ; the first block free: it starts AX
        add     ax, [es:3]              ;  lower
        mov     es, dx
        mov     [es:3], ax
        jmp     short .gx
.g2:    dec     ax                      ; a program's: a free block in front
        mov     [es:3], ax
.gx:    popf
        pop     es
        popa
        clc
        ret
.no:    pop     es
        popa
        stc
        ret

; INT 21h 48h with MT on (f_48: JMP FAR): as f_48; in a task, a block its
; arena hasn't room for grows the region (mt_grow) and is asked again.  On
; failure BX is the arena's own largest, as before.  DS = KSEG
mt_48:  mov     bx, [bp+F_BX]
        mov     dx, [cur_psp]
        KCALL   mem_alloc
        jnc     .x
        cmp     byte [cs:mt_cur], 0     ; (task 0, or not for room: failed, as
        je      .f                      ;  it was)
        cmp     ax, 8
        jne     .f
        push    bx
        mov     bx, [bp+F_BX]
        call    mt_grow
        pop     bx
        jc      .n
        call    mt_alloc
        jmp     short .x
.n:     mov     ax, 8
.f:     stc
.x:     mov     [bp+F_BX], bx
        jmp     KSEG:ret_cfax

; RMDIR with MT on (f_3A.mt: JMP FAR over its CMP BYTE [r_name],0): the
; directory (AX, its first cluster, on drive [act]) another task's current
; one is refused with 16, as MS-DOS's (each CDS; the running task's the
; kernel's own test).  A floppy's counts only if that task's are of this
; mount, no look since having taken a disk for the same one (TX_MG,
; TX_ML: else mt_vload has them found again by name, and a directory gone
; is the root then); an unknown one (FFFFh) is no cluster.  A parked
; task's TX: in window 0 meanwhile (mt_pmap; its pages gone: none).  Back
; to f_3A past the CMP, done here; DS = KSEG, AX kept
mt_rd:  push    ax
        push    bx
        push    cx
        push    dx
        push    di
        push    es
        xchg    dx, ax                  ; DX = the cluster
        xor     cx, cx                  ; CH: 1 if a task has it
        mov     al, [act]
        cmp     al, NDRV                ; (M:'s, R:'s: one for all tasks, no
        jae     .e                      ;  TX's, the kernel's own test)
        cbw
        shl     ax, 1
        xchg    di, ax                  ; DI = 2 * the drive
        xor     ax, ax
.t:     cmp     al, [cs:mt_cur]         ; (AL: the task)
        je      .n
        call    mt_ent
        cmp     byte [cs:bx+TE_STATE], TS_FREE
        je      .n
        cmp     byte [cs:bx+TE_STATE], TS_PARKED
        je      .p
        mov     es, [cs:bx+TE_TX]
        call    .one
        jmp     short .n
.p:     pushf
        cli
        call    mt_pmap
        jc      .pq
        call    .one
        call    mt_punmap
.pq:    popf
.n:     inc     al
        cmp     al, MT_TASKS
        jb      .t
.e:     or      ch, ch
        pop     es
        pop     di
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        jnz     .cur
        cmp     byte [r_name], 0
        jmp     KSEG:f_3A.mt + 5
.cur:   jmp     KSEG:f_3A.cur
.one:   cmp     dx, [es:V_DCWD+di]      ; (the task's TX at ES)
        jne     .o
        cmp     di, 2 * NFLOP
        jae     .y
        mov     bx, [es:TX_ML]
        cmp     bx, [mlook]
        jne     .o
        mov     bx, [es:TX_MG+di]
        cmp     bx, [mgen+di]
        jne     .o
.y:     mov     ch, 1
.o:     ret

; EXEC's block for the environment with MT on (f_4B.xe: JMP FAR over its
; MOV DX,[cur_psp] / CALL mem_alloc): as there; in a task, one its arena
; hasn't room for grows the region (mt_grow) and is asked again.  Back to
; f_4B.xr (its JC), CF and AX as mem_alloc gives them.  DS = KSEG
mt_xenv:
        push    bx
        call    mt_kalloc
        pop     bx
        jnc     .x
        cmp     ax, 8
        jne     .n
        cmp     byte [cs:mt_cur], 0
        je      .n
        call    mt_grow
        jc      .n
        call    mt_kalloc
        jmp     short .x
.n:     stc
.x:     jmp     KSEG:f_4B.xr

; EXEC's largest block with MT on (mem_largest: JMP FAR; EXEC its only
; caller): in a task, one below the program's minimum (ex_min) grows the
; region to it (mt_grow) and is asked again.  A .COM may use its
; whole segment without asking (DOS gives it the largest block; LCMD
; clears its BSS first), and in a grown region its block can end at the
; TX: one short of its minimum, or in a grown region (TE_TX not TE_REG)
; with less than 64 KB, has the region grown to 64 KB for it (else to
; its minimum, as an .EXE).  -> BX; DS = KSEG
mt_largest:
        push    ax
        push    dx
        call    mt_lrg
        cmp     byte [cs:mt_cur], 0
        je      .x
        cmp     byte [ex_isexe], 0
        jne     .n
        cmp     word [ex_min], 1000h
        jae     .n
        cmp     bx, 1000h               ; a .COM: 64 KB there?
        jae     .x
        cmp     bx, [ex_min]
        jb      .c
        push    bx                      ; (enough for its minimum: in a grown
        call    mt_cent                 ;  region, 64 KB if it can grow)
        mov     ax, [cs:bx+TE_TX]
        cmp     ax, [cs:bx+TE_REG]
        pop     bx
        je      .x
.c:     push    bx
        mov     bx, 1000h
        call    mt_grow
        pop     bx
        jnc     .a
.n:     cmp     bx, [ex_min]            ; (64 KB not there, or an .EXE: its
        jae     .x                      ;  minimum)
        push    bx
        mov     bx, [ex_min]
        call    mt_grow
        pop     bx
        jc      .x
.a:     call    mt_lrg
.x:     jmp     KSEG:mem_largest.x

; mem_alloc (DS = KSEG): for 48h's BX (mt_alloc), for BX (mt_kalloc), both
; the running program's; or none, BX = the largest block (mt_lrg).  As
; mem_alloc, DX changed
mt_lrg: mov     bx, 0FFFFh
        xor     dx, dx
        jmp     short mt_kalloc.k
mt_alloc:
        mov     bx, [bp+F_BX]
mt_kalloc:
        mov     dx, [cur_psp]
.k:     KCALL   mem_alloc
        ret

%include "KMW.INC"                      ; (several window .RUNs at once)
%ifdef CRASHLOG
%include "KCRASH.INC"
%endif
; the hot labels at the parity they had: a shift that flips one
; stops the build here (0 even, 1 odd)
%macro  mt_par 2
%ifndef CRASHLOG                        ; (a diagnostic build: not timed)
%ifndef NODWAIT                         ; (nor the bisect builds)
%ifndef NODWAIT0
            times   -(((%1 - mt_tstart) & 1) != %2) db 0
%endif
%endif
%endif
%endmacro
            mt_par  mt_tick, 0
            mt_par  mt_tick.p, 0
            mt_par  mt_exit, 1
            mt_par  mt_safe, 0
            mt_par  mt_kwait, 1
            mt_par  mt_kwait.bgp, 0
            mt_par  mt_can, 0
            mt_par  mt_pick, 1
            mt_par  mt_ent, 0
            mt_par  mt_switch, 0
            mt_par  mt_i16, 1
            mt_par  mt_v10, 0
            mt_par  mt_busy, 0
            mt_par  mt_isr, 0
            mt_par  mw_got, 1
            mt_par  mw_poll, 1
            mt_par  mt_emu.wl, 0
            mt_par  mt_vmov.w, 0
            mt_par  mt_vfast, 0         ; (INT 10h's per character
            mt_par  mt_vfast.ch, 0      ;  and per scroll)
            mt_par  mt_vfast.set, 0     ; (after a fixed NOP)
            mt_par  mt_vaddr, 0
            mt_par  mt_vscr, 0
; jumps that must stay in a byte, else NASM (cpu 286) makes each a JNA
; or the like over a near JMP, 4 clocks more where it isn't taken:
; mt_vscr's first JA .lit (4 bytes on from .c2), with JNZ .lit after it
; (two bytes more in the fast way: the pad before .lit takes the first),
; and mt_vfast's JA .nb for the page (3 bytes of room)
            times   -((mt_vscr.lit - mt_vscr.c2) > 4 + 127) db 0
            times   -((mt_vfast.nb - mt_vfast.pg) > 127) db 0
mt_tend:
MT_LEN      equ     mt_tend - mt_tstart

MT_TX0P     equ     (MT_LEN + 15) / 16  ; task 0's TX: in the BSS, which starts
MT_SSTK     equ     1024                ;  on the paragraph after the image;
MT_INIL     equ     160                 ; LODE.INI's lists' room
%ifdef CRASHLOG
CR_BSS      equ     CR_N * 16 + CR_LEN + CR_STK + 256 ; (KCRASH.INC: the ring, the report, a stack)
%else
CR_BSS      equ     0
%endif
MT_PARAS    equ     MT_TX0P + TX0_PARAS + (MT_TASKS * MT_ENT + MT_INIL + 20h + MW_BSS + MT_SSTK + CR_BSS + 15) / 16
                                        ; (then the lists, a header, KMW's
                                        ;  sessions, the stack)
section mttbss
mt_tx0      resb    TX0_PARAS * 16      ; (at MT_TX0P * 16; no TX_GSN: task 0
                                        ;  never ends)
mt_tab      resb    MT_TASKS * MT_ENT   ; the tasks (task 0, the Executive:
                                        ;  mt_boot)
mt_ini      resb    MT_INIL             ; (mt_lists)
mt_hdr      resb    20h                 ; (MT_UI: an .EXE's header)
mw_ses      resb    (MW_MAX + 1) * SE_SIZE  ; (KMW.INC: the sessions)
mw_tmp      resb    NWIN * 4            ; (mw_raise: the window stack, reordered)
            resb    MT_SSTK             ; (mt_swnow's stack)
%ifdef CRASHLOG
mt_crb      resb    CR_N * 16           ; (KCRASH.INC)
mt_crbuf    resb    CR_LEN
mt_crstk    resb    CR_STK
mt_crsv     resb    256                 ; (mt_crs0: the owner's stack's top)
%endif
mt_bend:

; ---- start-up (section boot, in the load image: CS = 1000h) ----------
section boot
mt_on   db      0                       ; md_boot: MULTITASK=1 is in LODE.INI
mt_sum  dw      0                       ; LODEMT.SYS's checksum (mkmt.py)
s_mteq  db      'MULTITASK', 1Dh, 0     ; (as "MULTITASK=" AND 0DFh)
s_mtsys db      '@:\LODEMT.SYS', 0
mt_s0   db      'Executive', 0          ; (task 0's TE_NAME)
; the kernel's places MT hooks (mt_boot): where, the opcode (EAh: JMP
; FAR, 9Ah: CALL FAR) and MT's routine there
%macro HOOK 3
        dw      %1
        db      %2
        dw      %3
%endmacro
mt_hooks:
%ifndef NOM10HOOKS
        HOOK    int21, 0EAh, mt_i21     ; INT 21h's entry
%endif
        HOOK    f_F0, 0EAh, mt_f0       ; INT 21h F0h
        HOOK    f_25, 0EAh, mt_25       ; AH=25h and 35h
        HOOK    f_35, 0EAh, mt_35
        HOOK    f_3A.mt, 0EAh, mt_rd    ; RMDIR: another task's directory
        HOOK    kbd_get.k, 0EAh, mt_kwait   ; the key wait
        HOOK    done.sw, 0EAh, mt_exit  ; INT 21h's way out
        HOOK    crit_disk.c24, 9Ah, mt_c24  ; INT 24h
        HOOK    ui_progend, 0EAh, mt_pgend  ; a program's end
        HOOK    f_48, 0EAh, mt_48       ; AH=48h, EXEC's largest block and
        HOOK    mem_largest, 0EAh, mt_largest   ;  its environment's: a
        HOOK    f_4B.xe, 0EAh, mt_xenv  ;  task's region grows
%ifndef SERIAL                          ; (-dSERIAL: pre-interrupt style, none)
        HOOK    gp_isr.e, 0EAh, mt_srqi ; the GPIB driver's SRQ interrupt, at
%endif                                  ;  its EOI: a task woken
        dw      0

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
        mov     di, MT_LEN              ; its BSS: zeros
        mov     cx, MT_PARAS * 16 - MT_LEN
        xor     al, al
        rep     stosb
        mov     di, mt_tab              ; task 0: the Executive (its PSP and
        mov     al, TS_RUN              ;  TX below)
        stosb
        mov     si, MDB(mt_s0)
        mov     di, mt_tab + TE_NAME
        mov     cl, 5
        rep     movsw
        mov     ah, 43h                 ; task 0's screen: 2 EMS pages (none:
        mov     bx, 2                   ;  it stays off)
        int     67h
        or      ah, ah
        jnz     .fr
        mov     [es:mt_tab + TE_SH], dl
        mov     ah, 3Eh
        mov     bx, bp
        int     21h
        call    mt_lists                ; LODE.INI's BG=, FREEZE=, MTMEM=
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
%ifdef NOMTFPU
        xor     al, al                  ; (a diagnostic build: the 287 never
%endif                                  ;  saved or restored at a switch)
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
%ifndef NOM10HOOKS                      ; (bisect build: none of the floppy wait's hooks)
        mov     ax, [15h * 4]           ; INT 15h, 25h and 26h
        mov     [es:mt_old15], ax
        mov     ax, [15h * 4 + 2]
        mov     [es:mt_old15 + 2], ax
        mov     word [15h * 4], mt_i15
        mov     [15h * 4 + 2], es
        mov     ax, [25h * 4]
        mov     [es:mt_old25], ax
        mov     ax, [25h * 4 + 2]
        mov     [es:mt_old25 + 2], ax
        mov     word [25h * 4], mt_i25
        mov     [25h * 4 + 2], es
        mov     ax, [26h * 4]
        mov     [es:mt_old26], ax
        mov     ax, [26h * 4 + 2]
        mov     [es:mt_old26 + 2], ax
        mov     word [26h * 4], mt_i26
        mov     [26h * 4 + 2], es
        mov     ax, [0Eh * 4]
        mov     [es:mt_old0e], ax
        mov     ax, [0Eh * 4 + 2]
        mov     [es:mt_old0e + 2], ax
        mov     word [0Eh * 4], mt_i0e
        mov     [0Eh * 4 + 2], es
        cmp     word [67h * 4], ems_int67       ; INT 67h the kernel's (EMS
        jne     .n67                    ;  resident): its entry through
        cmp     word [67h * 4 + 2], KSEG ;  mt_i67
        jne     .n67
        push    ds
        mov     ax, KSEG
        mov     ds, ax
        mov     byte [ems_int67], 0EAh
        mov     word [ems_int67 + 1], mt_i67
        mov     [ems_int67 + 3], es
        pop     ds
.n67:
%endif
%ifndef NOM10HOOKS
        push    ds                      ; C: (KHD.INC) there: its IRQ 14
        push    KSEG                    ;  through MT (mt_i76), on in both
        pop     ds                      ;  PICs (KHD's start-up turns it off
        cmp     byte [C_DT + D_PRES], 0 ;  without the BIOS's disk), and INT
        pop     ds                      ;  77h MT's
        je      .n76
        mov     ax, [76h * 4]
        mov     [es:mt_old76], ax
        mov     ax, [76h * 4 + 2]
        mov     [es:mt_old76 + 2], ax
        mov     word [76h * 4], mt_i76
        mov     [76h * 4 + 2], es
        mov     word [77h * 4], mt_i77
        mov     [77h * 4 + 2], es
        in      al, 0A1h
        and     al, 0BFh
        out     0A1h, al
        in      al, 21h
        and     al, 0FBh
        out     21h, al
.n76:
%endif
%ifdef CRASHLOG
        mov     word [6 * 4], mt_cr6    ; (KCRASH.INC: INT 06h, a restart through
        mov     [6 * 4 + 2], es         ;  40:67h with CMOS 0Fh = 0Ah, the ring
        mov     word [467h], mt_crst    ;  cleared; the last session's
        mov     [469h], es              ;  breadcrumbs to CR_PREV first)
        push    ds
        push    si
        push    di
        push    cx
        push    CR_PREV
        pop     ds
        xor     di, di
        mov     si, cr_psig
        mov     cx, 8
.cp:    mov     al, [es:si]
        mov     [di], al
        inc     si
        inc     di
        loop    .cp
        mov     al, 3Dh                 ; CMOS 3Dh's nibbles as the stage's and
        out     70h, al                 ;  the window tag's characters (never
        in      al, 71h                 ;  3Ch: KCRASH.INC's note)
        mov     ch, al
        mov     cl, 4
        shr     al, cl
        xor     ah, ah
        mov     si, ax
        mov     al, [es:si+cr_stch]
        mov     [di], al
        mov     al, ch
        and     ax, 0Fh
        mov     si, ax
        mov     al, [es:si+cr_wtags]
        mov     [di+1], al
        pop     cx
        pop     di
        pop     si
        pop     ds
        mov     al, 3Dh
        out     70h, al
        mov     al, CRB_ARMED << 4      ; (the window tag: '-', none)
        out     71h, al
        mov     al, 0Fh
        out     70h, al
        mov     al, 0Ah
        out     71h, al
        push    di
        push    cx
        mov     di, mt_crb
        mov     cx, CR_N * 16 / 2
        xor     ax, ax
        cld
        rep     stosw
        pop     cx
        pop     di
%endif
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
        mov     dx, es                  ; the kernel's hooks (mt_hooks):
        mov     ax, KSEG                ;  each a JMP FAR (CALL FAR) to MT
        mov     es, ax
        push    cs
        pop     ds
        mov     si, MDB(mt_hooks)
.hk:    lodsw
        xchg    di, ax
        or      di, di
        jz      .hx
        movsb                           ; (the opcode)
        movsw                           ; (MT's routine)
        xchg    ax, dx
        stosw
        xchg    ax, dx
        jmp     .hk
.hx:    mov     es, dx
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

; LODE.INI's BG=, FREEZE= and MTMEM= lists into mt_ini (ES = MT's block,
; its BSS zeroed; DS = CS), for mt_spawn: each program's name, upper case,
; its 0 and a word (MTMEM='s KB, 1-1023; 0 for the others), a 0 after a
; list's last.  Names are separated by commas, semicolons or blanks, and
; cut at 12 characters; MTMEM= gives NAME:kb (an entry without a number
; is left out).  What doesn't fit in mt_ini is left out.
mt_lists:
        cld
        mov     di, mt_ini
        mov     bx, MDB(s_bgeq)
        mov     bp, mt_lbg
        call    .one
        mov     bx, MDB(s_fzeq)
        mov     bp, mt_lfz
        call    .one
        mov     bx, MDB(s_memeq)
        mov     bp, mt_lmem
        call    .one
        mov     bx, MDB(s_fulleq)
        mov     bp, mt_lfull
.one:   call    ini_read                ; (SI = the text: read already)
        push    di
        mov     di, bx
        call    ini_key
        pop     di
        jc      .x
        mov     [es:bp], di             ; (the list: here)
.e:     lodsb                           ; to the next name
        call    .sep
        jc      .end
        je      .e
        cmp     di, mt_ini + MT_INIL - 19       ; (room: a name, 0, word, and
        ja      .end                    ;  the lists' four ends)
        mov     dx, di                  ; (the entry, should it go)
        mov     cx, 12
.n:     cmp     al, 'a'
        jb      .u
        cmp     al, 'z'
        ja      .u
        sub     al, 20h
.u:     jcxz    .nn                     ; (past 12: left out)
        stosb
        dec     cx
.nn:    lodsb
        cmp     al, ':'
        je      .k
        call    .sep
        jne     .n
        dec     si                      ; (the separator or the line's end
        cmp     bp, mt_lmem             ;  again, next)
        je      .drop                   ; (MTMEM= without a number)
        xor     ax, ax
        stosb
        stosw
        jmp     .e
.k:     xor     al, al                  ; NAME:kb
        stosb
        xor     bx, bx                  ; (BX = the KB)
.kd:    lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .kn
        cbw
        cmp     bx, 1024                ; (too big already: stays so)
        jae     .kd
        shl     bx, 1                   ; BX * 10 + the digit
        add     ax, bx
        shl     bx, 2
        add     bx, ax
        jmp     .kd
.kn:    dec     si
        xor     ax, ax
        cmp     bp, mt_lmem             ; (BG=, FREEZE=, FULL=: a number is
                                        ;  nothing)
        jne     .kw
        mov     ax, bx
        or      ax, ax
        jz      .drop
        cmp     ax, 1024
        jae     .drop
.kw:    stosw
.sk:    lodsb                           ; (and on to the separator)
        call    .sep
        jne     .sk
        dec     si
        jmp     .e
.drop:  mov     di, dx                  ; (MTMEM='s, not usable)
        jmp     .sk
.end:   xor     al, al
        stosb
.x:     ret
; AL a separator (ZF), the line's end (ZF and CF), or neither (both clear)?
.sep:   cmp     al, ','
        je      .sx
        cmp     al, ';'
        je      .sx
        cmp     al, ' '
        je      .sx
        cmp     al, 9
        je      .sx
        cmp     al, 13
        je      .se
        cmp     al, 10
        je      .se
        or      al, al
        jz      .se
.sx:    ret                             ; (CF clear from CMP or OR)
.se:    cmp     al, al
        stc
        ret

s_bgeq  db      'BG', 1Dh, 0            ; (as "BG=" AND 0DFh)
s_fzeq  db      'FREEZE', 1Dh, 0
s_memeq db      'MTMEM', 1Dh, 0
s_fulleq db     'FULL', 1Dh, 0
%endif
