; =====================================================================
;  KMW.INC - several window .RUNs at once (M8a), with MULTITASK=1 only.
;  Part of LODEMT.SYS (section mtt): off, none of it is in memory and the
;  UI is byte for byte as it was.
;
;  A window .RUN (its header says so, RF_WIN: CALC, TASKS, WRITE) is a
;  session: its own load area in the UI segment (a slot, from run_base
;  up, first fit), its own stack at the slot's end, and its own copy of
;  the core's globals
;  that belong to one program (mw_ctx's ranges: the band, the title, the
;  list and form and line editor's state, UI_ALLOC's blocks, its header).
;  Sessions run in turn inside the UI task: only the one in front (the
;  focus) runs; the others wait inside UI_EVENT, where they were.  The
;  Executive is one of them (record 0, M8c): a click on it, or CODE-F6,
;  brings it to the front under the windows, which stay on top; while it
;  draws, the core's drawing is clipped around them (mw_clipon).
;
;  The UI's own code is patched when MT_UI is first asked (ui_boot), each
;  patch over 5 bytes it checks first:
;    - run_app's first instruction (CMP BYTE [run_active],0) becomes a far
;      jump to mw_run: a window .RUN starts as a session; any other as
;      before (back to run_app past it);
;    - ui_event.got (CALL win_ev / JC .on) becomes a far call to mw_got:
;      with sessions, CODE-K and CODE-T open (or bring to the front) the
;      calculator and the tasks, CODE-F6 brings the next session to the
;      front, and a click on another session's window gives it the focus;
;    - run_cleanup's first 5 bytes become a far jump to mw_clean: the root
;      starting over (^C, a crash) forgets every session;
;    - ui_wopen's cache borrow (MOV AX,0F002h / INT 21h) becomes a far call
;      to mw_lend: while a window .RUN runs, no save-under, so closing,
;      moving or bringing a window to the front draws the screen again
;      (redraw_all), which stays right whichever window is in front;
;    - redraw_all's MOV SI,[redraw_fn] / OR SI,SI becomes a far call to
;      mw_rdfn: the base (the Executive) drawn again under a session keeps
;      the session's band, not its own (M8b).
;  A window .RUN is one whose header says so (RUN_FLAGS: RF_WIN; its
;  windows have W_FLAGS then, whatever its RUN_API).  M8b: CODE-W from
;  any window starts another Write (a new file); a WF_SIZE window is
;  resized by its bottom-right corner or CODE-F8 (mw_size, win_mv's way),
;  then its .RUN gets EV_SIZE.  While window .RUNs run, the UI block takes
;  the whole segment it can (mw_grow), so their own blocks (UI_ALLOC) go
;  past it and the next one still fits.
;  Window .RUNs started from anywhere don't make the starter wait: the new
;  one takes the focus.  A window belongs to the session whose slot holds
;  its structure (help_w: the running one's; a help or form window is
;  modal: no change of focus while one is open).
;  While window .RUNs run (M8c), the core's drawing primitives are patched
;  too (mw_cpt): with the Executive in front, what it draws is cut around
;  the sessions' windows (mw_clipq, mw_cdraw), except inside a window of
;  its own; win_paint and the saver draw unclipped (mw_nc).
; =====================================================================
MW_MAX      equ 4                       ; window .RUNs at once (NWIN windows)
MW_STK      equ 2560                    ; a session's stack (the core's is as big)
MW_TRAMP    equ 8                       ; (the slot's last bytes: JMP FAR mw_end)
; a session's record (mw_ses: 0 is the Executive's)
SE_USE      equ 0                       ; 1: a window .RUN runs here
SE_BASE     equ 2                       ; its slot: from (offset in the UI segment)
SE_END      equ 4                       ;  to (paragraph-aligned)
SE_SP       equ 6                       ; its SP while another runs (SS: the UI's)
SE_NAME     equ 8                       ; its file name (12 + 0)
SE_TASK     equ 21                      ; a terminal window's (MT_TOPEN, T2): its
SE_TGEN     equ 22                      ;  task (0: none), that task's count, and
SE_TCHG     equ 23                      ;  as mw_poll last saw them: its screen's
SE_TST      equ 25                      ;  changes (TX_CHG), its state, the BIOS
SE_TTK      equ 26                      ;  tick count at its last EV_TICK
SE_CTX      equ 28                      ; mw_ctx's ranges, while another runs
MW_CTXLEN   equ 100
SE_SIZE     equ SE_CTX + MW_CTXLEN

mw_ctx:     dw      title_on,  held2 + 2 - title_on
            dw      redraw_fn, 2
            dw      lv_cur,    ed_keep + 1 - lv_cur
            dw      fm_ptr,    fm_b2 + 2 - fm_ptr
            dw      crit_err,  2
            dw      alloc_tab, run_ret + 2 - alloc_tab
            dw      ex_mtw,    1        ; (2 only in the Executive's UI_EVENT:
            dw      0                   ;  a task's end is its event, M8c)
MW_CALLOC   equ (held2 + 2 - title_on) + 2 + (ed_keep + 1 - lv_cur) + (fm_b2 + 2 - fm_ptr) + 2
                                        ; (alloc_tab's place in a record's copy)
%if MW_CALLOC + (run_ret + 2 - alloc_tab) + 1 > MW_CTXLEN
%error "KMW: mw_ctx's ranges are longer than MW_CTXLEN"
%endif

mw_on       db      0                   ; 1: the UI is patched
mw_n        db      0                   ; window .RUNs running
mw_cur      db      0                   ; the session running (0: the Executive)
mw_rd       db      0                   ; once switched: 1 the screen again, 2
                                        ;  the band, 3 the session's windows
                                        ;  (on top now) and the band (mw_back)
mw_msg      db      0                   ; 1: mw_say's message waits (UI_MSG)
mw_ow       dw      0                   ; (mw_size: the size it had)
mw_oh       dw      0
MW_MINW     equ     24                  ; the smallest a window is resized to:
MW_MINH     equ     72                  ;  columns (a title fits, and Write scrolls
                                        ;  sideways by 20), pixels (a title, a
                                        ;  row, a status line)
MW_CORNER   equ     12                  ; its resize corner: its last column, the
                                        ;  bottom 12 pixel rows
mw_mru      times MW_MAX + 1 db 0FFh    ; the sessions, the Executive's (0) too,
                                        ;  the focus first (0FFh after them)
mw_new      db      0                   ; (mw_start: the one starting)
mw_hdr      times 16 db 0               ; a .RUN's header, read
MW_BSS      equ     (MW_MAX + 1) * SE_SIZE + NWIN * 4   ; (mw_ses, mw_tmp: in
                                        ;  mttbss, KMT.INC)

; ---------------------------------------------------------------------
;  the patches (from mt_uic: DS = KSEG, ES = the UI segment)
; ---------------------------------------------------------------------
mw_patch:
        cmp     byte [cs:mw_on], 0
        jne     .x
        cmp     byte [es:run_app], 80h          ; CMP BYTE [run_active],0
        jne     .x
        cmp     byte [es:run_app + 1], 3Eh
        jne     .x
        cmp     word [es:run_app + 2], run_active
        jne     .x
        cmp     byte [es:run_app + 4], 0
        jne     .x
        cmp     byte [es:ui_event.got], 0E8h    ; CALL win_ev / JC .on
        jne     .x
        cmp     byte [es:ui_event.got + 3], 72h
        jne     .x
        cmp     byte [es:ui_event.l], 0E8h      ; CALL poll_once / JNC .got
        jne     .x
        cmp     word [es:ui_event.l + 3], 73h + (ui_event.got - ui_event.l - 5) * 100h
        jne     .x
        cmp     word [es:run_cleanup], 0660h    ; PUSHA / PUSH ES / MOV SI,alloc_tab
        jne     .x
        cmp     byte [es:run_cleanup + 2], 0BEh
        jne     .x
        cmp     word [es:run_cleanup + 3], alloc_tab
        jne     .x
        cmp     word [es:..@ui_wlend], 02B8h    ; MOV AX,0F002h / INT 21h
        jne     .x
        cmp     word [es:..@ui_wlend + 2], 0CDF0h
        jne     .x
        cmp     byte [es:..@ui_wlend + 4], 21h
        jne     .x
        cmp     word [es:..@ui_rdfn], 368Bh     ; MOV SI,[redraw_fn] / OR SI,SI
        jne     .x
        cmp     word [es:..@ui_rdfn + 2], redraw_fn
        jne     .x
        cmp     word [es:..@ui_rdfn + 4], 0F609h
        jne     .x
        call    mw_cpchk                ; (the clipping's: made only while
        jne     .x                      ;  window .RUNs run)
        mov     byte [es:..@ui_rdfn], 9Ah       ; CALL FAR mw_rdfn, NOP
        mov     word [es:..@ui_rdfn + 1], mw_rdfn
        mov     [es:..@ui_rdfn + 3], cs
        mov     byte [es:..@ui_rdfn + 5], 90h
        mov     byte [es:run_app], 0EAh         ; JMP FAR mw_run
        mov     word [es:run_app + 1], mw_run
        mov     [es:run_app + 3], cs
        mov     byte [es:ui_event.got], 9Ah     ; CALL FAR mw_got
        mov     word [es:ui_event.got + 1], mw_got
        mov     [es:ui_event.got + 3], cs
        mov     byte [es:ui_event.l], 9Ah       ; CALL FAR mw_poll
        mov     word [es:ui_event.l + 1], mw_poll
        mov     [es:ui_event.l + 3], cs
        mov     byte [es:run_cleanup], 0EAh     ; JMP FAR mw_clean
        mov     word [es:run_cleanup + 1], mw_clean
        mov     [es:run_cleanup + 3], cs
        mov     byte [es:..@ui_wlend], 9Ah      ; CALL FAR mw_lend
        mov     word [es:..@ui_wlend + 1], mw_lend
        mov     [es:..@ui_wlend + 3], cs
        mov     byte [cs:mw_on], 1
.x:     ret

; ---------------------------------------------------------------------
;  run_app (DS = ES = the UI): SI = path, DI = argument; its caller's
;  near return on the stack
; ---------------------------------------------------------------------
mw_run: cmp     byte [cs:mw_n], 0
        jne     .ses
        cmp     byte [run_active], 0
        jne     .busy
        call    mw_peek                 ; a window .RUN?
        jc      .orig                   ; (can't tell: run_app says why)
        test    byte [cs:mw_hdr+14], RF_WIN     ; (its header says so: RUN_FLAGS)
        jz      .orig
        mov     byte [run_active], 1
.go:    call    mw_start                ; (the Executive waits in here while
        jc      .fail                   ;  others are in front)
        mov     ax, 0FFFFh              ; (no list again here: it was drawn as
        mov     [run_ret], ax           ;  each window closed, M8c; run_ret as
        clc                             ;  run_app leaves it)
        jmp     short .ret
.fail:  cmp     byte [cs:mw_n], 0       ; (others run: nothing to undo)
        jne     .f2
        mov     [run_ret], ax
        UCALL   run_cleanup             ; (run_active 0, the block as it was)
        mov     ax, [run_ret]
.f2:    stc
.ret:   push    ds                      ; RET (near) into the UI: to run_app's
        push    word ..@ui_ret          ;  caller
        retf
.busy:  mov     ax, 8                   ; (one at a time, as run_app says)
        stc
        jmp     .ret
.ses:   call    mw_peek                 ; windows open: another window .RUN
        jc      .f2                     ;  opens beside them (Return on a text:
        test    byte [cs:mw_hdr+14], RF_WIN     ;  a Write); any other needs the
        jnz     .go                     ;  whole screen
        mov     ax, 9
        call    mw_say
        mov     ax, 0FFFFh              ; (said: nothing more, no list again)
        clc
        jmp     .ret
.orig:  cmp     byte [run_active], 0    ; run_app as it was (ZF: its JE .free)
        push    ds
        push    word run_app + 5
        retf

; redraw_all's call of the redraw routine (CALL FAR, for MOV SI,[redraw_fn]
; / OR SI,SI): -> SI, ZF as they would be.  With a session in front, the
; routine (the Executive's relist, drawing the base) is called from here,
; and the session's band kept through it: the base would leave its own.
; Then SI = 0, so redraw_all calls nothing more
mw_rdfn:
        mov     si, [redraw_fn]
        cmp     byte [cs:mw_cur], 0
        je      .x
        or      si, si
        jz      .x
        push    word [band1]
        push    word [band2]
        push    cs                      ; (as UCALL, to SI)
        push    word .back
        push    word ..@ui_retf
        push    ds
        push    si
        retf
.back:  pop     word [band2]
        pop     word [band1]
        xor     si, si
.x:     or      si, si
        retf

; ui_wopen's borrow of the cache (CALL FAR): as before while no window
; .RUN runs (the Executive's help and forms have their save-under), none
; while one does (the screen is drawn again instead)
mw_lend:
        cmp     byte [cs:mw_n], 0
        jne     .no
        mov     ax, 0F002h
        int     21h
        retf
.no:    stc
        retf

; the header of .RUN SI into mw_hdr -> CF (AX = error, 11: not a .RUN)
mw_peek:
        push    bx
        push    cx
        push    dx
        mov     dx, si
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     bx, ax
        push    ds
        push    cs
        pop     ds
        mov     dx, mw_hdr
        mov     cx, 16
        mov     ah, 3Fh
        int     21h
        pop     ds
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
        jc      .x
        cmp     ax, 16
        jne     .bad
        cmp     word [cs:mw_hdr], 'GR'
        jne     .bad
        cmp     word [cs:mw_hdr+2], 'UN'
        jne     .bad
        cmp     word [cs:mw_hdr+4], UI_API
        ja      .bad
        clc
        jmp     short .x
.bad:   mov     ax, 11
        stc
.x:     pop     dx
        pop     cx
        pop     bx
        ret

; ---------------------------------------------------------------------
;  a window .RUN (path SI, argument DI) as a new session, in front: the
;  running one waits, and this returns when it runs again (the Executive:
;  when the last has ended, AX = its exit code).  CF before that if it
;  can't start: AX = error (8: no room, too many; 11: not a window .RUN).
;  mw_hdr: its header (mw_peek)
; ---------------------------------------------------------------------
mw_start:
        pusha
        mov     ax, 8
        cmp     byte [cs:mw_n], MW_MAX
        jae     .no
        cmp     word [wdepth], NWIN     ; (each has a window)
        jae     .no
        call    mw_peek
        jc      .no
        mov     ax, 11
        test    byte [cs:mw_hdr+14], RF_WIN
        jz      .no
        cmp     word [cs:mw_hdr+4], 6   ; (a window .RUN's windows have W_FLAGS,
        jae     .api                    ;  whatever API it asks for: run_hdr
        mov     word [cs:mw_hdr+4], 6   ;  says 6 then, for win_flags)
.api:
        mov     ax, [cs:mw_hdr+10]      ; its footprint, as run_app reckons it
        add     ax, [cs:mw_hdr+12]
        jc      .bad                    ; (a damaged header, as run_app says)
        cmp     ax, 4000h
        jae     .bad
        shl     ax, 1
        mov     [cs:mw_hdr+14], ax      ; (the fixups' bytes: mw_load reads
        cmp     ax, MW_STK              ;  them past the BSS, into the
        jae     .fx                     ;  stack's room, unused till it runs)
        mov     ax, MW_STK
.fx:    add     ax, [cs:mw_hdr+8]
        jc      .room
        add     ax, [cs:mw_hdr+6]
        jc      .room
        add     ax, MW_TRAMP + 15
        jc      .room
        and     al, 0F0h
        mov     cx, ax                  ; CX = the slot's size
        call    mw_slot                 ; -> BX = where; CF none
        jc      .room
        mov     dx, bx
        add     dx, cx                  ; DX = its end
        call    mw_grow                 ; the UI block to the highest end
        jc      .room
        call    mw_load                 ; read and fix it at BX (SI = path)
        jc      .lf
        cmp     byte [cs:mw_n], 0       ; the first: the Executive alone in the
        jne     .fr                     ;  focus order, its list as it is
        mov     word [cs:mw_mru], 0FF00h
        mov     word [cs:mw_mru + 2], 0FFFFh
        mov     byte [cs:mw_mru + 4], 0FFh
        mov     word [run_hdr+4], 6     ; (win_flags in its turns: each window's
                                        ;  own, the sessions' close boxes drawn)
.fr:    call    mw_free                 ; -> AL = a free session, BP = its record
        mov     [cs:mw_new], al
        mov     [cs:bp+SE_BASE], bx
        mov     [cs:bp+SE_END], dx
        call    mw_name                 ; its name, from SI
        mov     byte [cs:bp+SE_USE], 1
        mov     byte [cs:bp+SE_TASK], 0 ; (a terminal window's: MT_TOPEN)
        ; its stack: the trampoline at the slot's end, then a frame for
        ; mw_park's way out (mw_go): SI = its argument, BP = its entry
        mov     si, sp
        mov     ax, [si]                ; (pusha's DI: the argument)
        mov     di, dx
        sub     di, MW_TRAMP
        mov     byte [di], 0EAh         ; JMP FAR mw_end
        mov     word [di+1], mw_end
        mov     [di+3], cs
        mov     si, di
        sub     si, 2
        mov     [si], di                ; the .RUN's RET: to the trampoline
        sub     si, 2
        mov     word [si], mw_go        ; mw_park's RET: to mw_go
        sub     si, 16                  ; POPA's: DI SI BP SP BX DX CX AX
        mov     [si+2], ax
        mov     [si+4], bx
        sub     si, 4
        mov     [si], ds                ; ES
        mov     [si+2], ds              ; DS
        mov     [cs:bp+SE_SP], si
        ; the running session waits: its globals kept, then the new one's
        push    ax
        mov     al, [cs:mw_cur]
        call    mw_rec                  ; BP = the starter's record
        call    mw_save
        cmp     byte [cs:mw_cur], 0     ; started from a window: the band, the
        je      .ex                     ;  title, the redraw and the rest as
        mov     di, mw_ses              ;  the Executive left them, not
        call    mw_load_ctx.di          ;  pointers into the starter's slot
        pusha                           ; (and that band on the screen)
        UCALL   band_redraw
        popa
.ex:    mov     cx, NALLOC + 8 + 1      ; alloc_tab, run_hdr, run_hnd: none
        mov     di, alloc_tab
        xor     ax, ax
        rep     stosw
        cmp     [held1], ax             ; the Executive's question waiting (M8c:
        je      .nq                     ;  it may be in front at one): not the
        mov     [held1], ax             ;  new one's, nor its band
        mov     [held2], ax
        mov     [band1], ax
        mov     [band2], ax
        pusha
        UCALL   band_redraw
        popa
.nq:    pop     ax
        mov     [run_ret], ax           ; (its argument)
        push    ds
        mov     si, mw_hdr
        mov     di, run_hdr
        mov     cx, 8
        push    cs
        pop     ds
        rep     movsw
        pop     ds
        mov     word [crit_err], 0
        mov     byte [ex_mtw], 1        ; (a task's end isn't its event)
        ; in front, the starter waiting
        mov     al, [cs:mw_new]
        mov     [cs:mw_cur], al
        inc     byte [cs:mw_n]
        cmp     byte [cs:mw_n], 1       ; (the first: the clipping's patches)
        jne     .cl
        call    mw_clipon
.cl:    call    mw_front                ; first in mw_mru
        push    bp
        call    mw_rec
        mov     di, [cs:bp+SE_SP]       ; (the new stack)
        pop     bp
        call    mw_park                 ; the starter waits (SP into BP's record)
        popa                            ; (back here when the starter runs again)
        clc
        ret
.lf:                                    ; (no record kept: SE_USE is 0)
        jmp     short .no
.bad:   mov     ax, 11
        jmp     short .no
.room:  mov     ax, 8
.no:    mov     bp, sp
        mov     [bp+14], ax             ; (pusha's AX)
        popa
        stc
        ret

; the starter waits: its registers on its stack, its SP in record BP;
; then the stack DI is taken, and its frame (mw_park's) run on
mw_park:
        pusha
        push    ds
        push    es
        mov     [cs:bp+SE_SP], sp
        mov     sp, di
        pop     es
        pop     ds
        popa
        ret                             ; (a new session: to mw_go)

; a new session's first run: the .RUN's entry (BP), SI = its argument,
; DS = ES = SS = the UI's; its RET goes to the trampoline (mw_end)
mw_go:  cld
        push    ds
        push    bp
        retf

; ---------------------------------------------------------------------
;  a session's .RUN has returned (JMP FAR from its trampoline): AX = exit
;  code, SS = the UI's.  It goes; the next in front runs (or the Executive,
;  in run_app, when it was the last)
; ---------------------------------------------------------------------
mw_end: cld                             ; (its exit code isn't wanted: the
        push    ss                      ;  list was drawn again as its windows
        pop     ds                      ;  closed, the whole screen then)
        push    ss
        pop     es
        mov     si, alloc_tab           ; its UI_ALLOC blocks
.f:     mov     ax, [si]
        or      ax, ax
        jz      .fn
        push    es
        mov     es, ax
        mov     ah, 49h
        int     21h
        pop     es
        mov     word [si], 0
.fn:    add     si, 2
        cmp     si, alloc_tab + 2 * NALLOC
        jb      .f
        mov     al, [cs:mw_cur]
        call    mw_unwin                ; its windows off the stack (CF: some)
        jnc     .nw
        mov     byte [cs:mw_rd], 1      ; (the screen again where it goes)
.nw:    mov     al, [cs:mw_cur]
        call    mw_rec
        mov     byte [cs:bp+SE_USE], 0
        call    mw_drop                 ; out of mw_mru
        dec     byte [cs:mw_n]
        mov     al, [cs:mw_mru]         ; the one in front before it (the
        mov     [cs:mw_cur], al         ;  Executive, after the last)
        call    mw_rec
        mov     sp, [cs:bp+SE_SP]       ; (its stack now; the UI block stays
                                        ;  the whole segment till the last ends:
                                        ;  run_cleanup shrinks it then)
        or      al, al
        jnz     .top
        call    mw_load_ctx             ; the Executive
        cmp     byte [cs:mw_n], 0
        jne     .b
        push    dx                      ; the last: as run_app ends, from the
        mov     dx, exec_dta            ;  Executive's own stack (the slots'
        mov     ah, 1Ah                 ;  memory goes): its DTA, no clipping,
        int     21h                     ;  run_active 0 and the block as it was
        pop     dx
        call    mw_clipoff
        UCALL   run_cleanup
        jmp     short .b
.top:   mov     bx, [wdepth]            ; its windows on top, if they aren't
        or      bx, bx
        jz      .sw
        shl     bx, 2
        mov     si, [wstack+bx-4]
        mov     ah, al
        call    mw_own                  ; (AL = whose the top one is)
        cmp     al, ah
        mov     al, ah
        je      .sw
        call    mw_raise
        mov     byte [cs:mw_rd], 1
.sw:    call    mw_load_ctx
.b:     cmp     byte [cs:mw_rd], 0      ; its band at least (a question of its
        jne     .bk                     ;  own, still waiting), if the screen
        mov     byte [cs:mw_rd], 2      ;  isn't drawn again anyway
.bk:    jmp     mw_back

; ---------------------------------------------------------------------
;  ui_event.got (CALL FAR): AX = the event (BX, CX for a click), DS = the
;  UI.  As win_ev: back past the call with the event, or to ui_event.on
;  if it was taken (here: a change of focus, a window .RUN started)
; ---------------------------------------------------------------------
mw_got: cmp     byte [cs:mw_n], 0
        je      .win                    ; (no window .RUN: as before)
        pusha
        push    es
        push    ds                      ; (a .RUN may call UI_EVENT with any ES)
        pop     es
        call    mw_modal                ; (a help or form window open: its)
        jc      .own
        cmp     byte [cs:mw_msg], 0     ; (mw_say's message waiting: any key
        jne     .own                    ;  ends it, as without tasks)
        cmp     ax, K_CODE_K
        je      .calc
        cmp     ax, K_CODE_T
        je      .tasks
        cmp     ax, K_CODE_W
        je      .write
        cmp     ax, K_CODE_F6
        je      .next
        cmp     ax, K_CODE_F8
        je      .szk
        cmp     ax, EV_CLICK
        jne     .own
        call    mw_szwin                ; (on the top window's resize corner?)
        jc      .hit
        call    mw_corner
        jnc     .hit
        stc                             ; (by the mouse)
        jmp     short .size
.szk:   call    mw_szwin                ; CODE-F8: the top window, if it may be
        jc      .own                    ;  resized (else the key is the .RUN's)
        clc                             ; (by the keys)
.size:  call    mw_size
        jnc     .took                   ; (left as it was)
        mov     bp, sp                  ; EV_SIZE for the .RUN (pusha's AX,
        mov     word [bp+2+14], EV_SIZE ;  past the ES pushed)
        pop     es
        popa
        jmp     short .ret
.hit:   call    mw_hit                  ; AL = whose window is clicked
        jc      .base
.foc:   cmp     al, [cs:mw_cur]
        je      .own
        call    mw_focus
        jmp     short .took
.base:  xor     al, al                  ; none: the Executive's list, its form
        cmp     cx, SCR_BAND_Y          ;  or its top lines bring it to the
        jb      .foc                    ;  front (the band is the one in
        jmp     short .own              ;  front's)
.calc:  mov     si, s_calc
        jmp     short .open
.tasks: mov     si, s_tasks
.open:  push    si
        call    mw_open
        pop     si
        jnc     .took
        jmp     short .why
.write: mov     si, s_write             ; CODE-W: a new Write, whichever is
        push    si                      ;  in front (one more file)
        call    mw_open.new
        pop     si
        jnc     .took
.why:
        cmp     ax, 0FFFFh              ; (it is the one in front: the key is
        je      .own                    ;  its own, as without tasks)
        call    mw_say                  ; (why not, in the band)
        jmp     short .took
.next:  call    mw_cycle                ; the next in front (the one in front
.took:  pop     es                      ;  goes last; the Executive is one)
        popa
        jmp     short .wait
.own:   pop     es
        popa
        cmp     byte [cs:mw_cur], 0     ; the Executive in front: the top
        jne     .win                    ;  window, a session's, isn't its to
        call    mw_topses               ;  move or close (CODE-F7, its strip)
        jc      .ret
.win:   UCALL   win_ev
        jc      .wait
.ret:   retf                            ; (ui_event.got + 5: the event)
.wait:  push    bp
        mov     bp, sp
        mov     word [bp+2], ui_event.on
        pop     bp
        retf

; ui_event's look for an event (CALL FAR over its CALL poll_once / JNC
; .got; DS = the UI): poll_once's, else EV_TICK for a terminal window in
; front (T2: mw_tick); else back to ui_event's HLT, as before
mw_poll:
        UCALL   poll_once
        jnc     .ev
        cmp     byte [cs:mw_n], 0
        je      .y
        call    mw_tick
        jnc     .y
        mov     ax, EV_TICK
.ev:    push    bp                      ; (an event: to ui_event.got)
        mov     bp, sp
        mov     word [bp+2], ui_event.got
        pop     bp
.x:     retf
; T5d: nothing, and a task ready to run (one an SRQ woke while the UI was
; busy first, mt_want): its turn now, not at the next tick (the HLT after
; this would hold the CPU till then).  The mouse or a key brings the
; Executive back at the next tick (mt_mdset, mt_mwant: as from a drag's
; wait).  An interrupt's frame, as if the HLT had ended (..@ui_idle,
; interrupts on), and on as a tick's end (mt_tick.w: mt_safe vets it);
; back at ..@ui_idle, the loop's.  Not with INT 08h hooked ahead of MT
; (mt_tick.w would refuse each time: the HLT, not a spin).  mt_pick's
; look leaves mt_want and mt_mrot as they were (mt_preempt picks).  All
; kept (UI_EVENT's)
.y:     cli
        push    ax
        push    bx
        mov     ah, [cs:mt_want]
        mov     al, [cs:mt_mrot]
        call    mt_pick                 ; (AX kept; BL its pick)
        mov     [cs:mt_want], ah
        mov     [cs:mt_mrot], al
        jc      .z
        push    ds
        xor     bx, bx
        mov     ds, bx
        cmp     word [8 * 4], mt_tick
        jne     .q
        mov     bx, cs
        cmp     [8 * 4 + 2], bx
.q:     pop     ds
        jne     .z
        pop     bx
        pop     ax
        push    bp                      ; (its return, the HLT's: on at
        mov     bp, sp                  ;  ..@ui_idle instead, flags 0202h)
        push    word [bp+4]
        mov     word [bp+4], 0202h
        pop     word [bp+2]
        pop     bp
        push    word ..@ui_idle
        push    ax                      ; mt_tick's frame: AX, BX, DX, DS, BP
        push    bx
        push    dx
        push    ds
        push    bp
        mov     bp, sp
        push    KSEG
        pop     ds
        mov     byte [cs:mt_pend], 1
        jmp     mt_tick.w
.z:     pop     bx
        pop     ax
        retf                            ; (interrupts off: the HLT's STI next)

; CF: EV_TICK is due for the session in front, a terminal window (MT_TOPEN
; gave it its task): its task's screen (TX_CHG, and a published screen's
; PB_CHG: mt_tchg) or state changed, it ended
; (another count, or its end's count this one: mt_ui's test), or 9 ticks
; went by (about 0.5 s).  Not while a help or form window, or mw_say's
; message, waits (as mw_got: it would be read as a key).  All kept
mw_tick:
        push    ax
        push    bx
        push    bp
        push    es
        mov     al, [cs:mw_cur]
        or      al, al
        jz      .no
        call    mw_rec
        mov     al, [cs:bp+SE_TASK]
        or      al, al
        jz      .no
        cmp     byte [cs:mw_msg], 0
        jne     .no
        push    ds
        pop     es
        call    mw_modal
        jc      .no
        call    mt_ent
        mov     ah, [cs:bp+SE_TGEN]
        cmp     ah, [cs:bx+TE_GEN]      ; (its number given again: it ended)
        jne     .yes
        cmp     ah, [cs:bx+TE_EGEN]
        je      .yes
        mov     al, [cs:bx+TE_STATE]
        cmp     al, [cs:bp+SE_TST]
        mov     [cs:bp+SE_TST], al
        jne     .yes
        cmp     al, TS_PARKED           ; (parked: its TX in EMS)
        je      .t
        call    mt_tchg                 ; (T5b: a published screen's too)
        cmp     ax, [cs:bp+SE_TCHG]
        mov     [cs:bp+SE_TCHG], ax
        jne     .yes
.t:     call    .now
        sub     ax, [cs:bp+SE_TTK]
        cmp     ax, 9
        jb      .no
.yes:   call    .now
        mov     [cs:bp+SE_TTK], ax
        stc
        jmp     short .x
.no:    clc
.x:     pop     es
        pop     bp
        pop     bx
        pop     ax
        ret
.now:   push    es                      ; AX = the BIOS's tick count
        xor     ax, ax
        mov     es, ax
        mov     ax, [es:46Ch]
        pop     es
        ret

; SI = a window .RUN's name: in front if it runs, else started -> CF
; (AX = error) if it can't be; CF, AX = 0FFFFh: it runs in front already
mw_open:
        push    bp
        mov     al, 1
.s:     call    mw_rec
        cmp     byte [cs:bp+SE_USE], 0
        je      .n
        push    si
        push    di
        lea     di, [bp+SE_NAME]
.c:     mov     ah, [si]
        cmp     ah, [cs:di]
        jne     .ne
        inc     si
        inc     di
        or      ah, ah
        jnz     .c
.ne:    pop     di
        pop     si
        jne     .n
        pop     bp
        cmp     al, [cs:mw_cur]
        je      .y
        call    mw_focus
        clc
        ret
.y:     mov     ax, 0FFFFh
        stc
        ret
.n:     inc     al
        cmp     al, MW_MAX
        jbe     .s
        pop     bp
.new:   push    bp                      ; (.new: started, even if one runs:
        mov     bp, sp                  ;  CODE-W's Write)
        sub     sp, 2 * MW_PATH
        push    cx
        push    di
        push    ds                      ; ui_findapp's answer is in dstpath,
        pop     es                      ;  the Executive's Copy/Move destination,
        push    si                      ;  which may be waiting at its question
        mov     si, dstpath             ;  (M8c): kept on the stack meanwhile,
        lea     di, [bp - MW_PATH]      ;  and the path found copied there
        mov     cx, MW_PATH / 2
        rep     movsw
        pop     si                      ; (the name)
        UCALL   ui_findapp              ; SI = its path
        pushf
        lea     di, [bp - 2 * MW_PATH]
        mov     cx, MW_PATH / 2
        rep     movsw
        lea     si, [bp - MW_PATH]
        mov     di, dstpath
        mov     cx, MW_PATH / 2
        rep     movsw
        popf
        lea     si, [bp - 2 * MW_PATH]
        mov     ax, 2                   ; (not found)
        jc      .nf
        mov     di, s_empty
        call    mw_start
.nf:    pop     di
        pop     cx
        mov     sp, bp
        pop     bp
        ret
MW_PATH     equ     84                  ; (dstpath's size, EXEC.INC)

; window .RUN SI (its name) couldn't start, AX = why: said in the band
; (UI_MSG: till a key or a click), the name first
mw_say: pusha
        push    es
        mov     dx, ax                  ; (DX: why)
        mov     bx, si                  ; (a path: its last part)
.p:     lodsb
        cmp     al, '\'
        je      .pn
        cmp     al, ':'
        jne     .pe
.pn:    mov     bx, si
.pe:    or      al, al
        jnz     .p
        mov     si, bx
        mov     di, tmp
        mov     cx, 13
.n:     lodsb
        or      al, al
        jz      .w
        stosb
        loop    .n
.w:     mov     si, mw_s8
        cmp     dx, 8
        je      .c
        mov     si, mw_s2
        cmp     dx, 2
        je      .c
        mov     si, mw_s9
        cmp     dx, 9
        je      .c
        mov     si, mw_sx
.c:     push    ds
        push    cs
        pop     ds
.m:     lodsb
        stosb
        or      al, al
        jnz     .m
        pop     ds
        mov     si, tmp
        mov     byte [cs:mw_msg], 1
        mov     al, [ex_mtw]            ; (a task's end meanwhile isn't the
        push    ax                      ;  message's key: the Executive's, later)
        mov     byte [ex_mtw], 1
        UCALL   ui_msg
        pop     ax
        mov     [ex_mtw], al
        mov     byte [cs:mw_msg], 0
        pop     es
        popa
        ret
mw_s8   db      " doesn't fit: close a window first", 0
mw_s2   db      " is not on this disk", 0
mw_sx   db      " can't start", 0
mw_s9   db      " needs the whole screen: close the windows first", 0

; CODE-F6: the one in front goes last, the next comes to the front
mw_cycle:
        mov     al, [cs:mw_mru]
        push    ax
        call    mw_drop
        pop     ax
        xor     bx, bx
        mov     bl, [cs:mw_n]           ; (mw_n + 1 in it, the Executive too)
        mov     [cs:mw_mru + bx], al
        mov     al, [cs:mw_mru]
        ; (falls through)

; session AL (0: the Executive) to the front: first in mw_mru, its windows
; on top; once it runs, its windows drawn if they weren't on top, else its
; band
mw_focus:
        call    mw_front
        call    mw_raise                ; (CF: the order changed)
        mov     byte [cs:mw_rd], 2
        jnc     .o
        mov     byte [cs:mw_rd], 3
.o:     push    ax
        mov     al, [cs:mw_cur]
        call    mw_rec
        call    mw_save
        pop     ax
        mov     [cs:mw_cur], al
        push    bp
        call    mw_rec
        mov     di, bp
        pop     bp
        call    mw_load_ctx.di
        ; (falls through)

; to session [mw_cur]'s record DI (its globals in already): this one
; waits (its SP into record BP), that one goes on where it waited
mw_sw:  pusha
        push    ds
        push    es
        mov     [cs:bp+SE_SP], sp
        mov     sp, [cs:di+SE_SP]
mw_back:
        pop     es
        pop     ds
        popa
        cmp     byte [cs:mw_rd], 0
        je      .x
        pusha
        mov     al, 0
        xchg    al, [cs:mw_rd]
        cmp     al, 1
        jne     .w
        UCALL   redraw_all              ; 1: all of it
        jmp     short .p
.w:     cmp     al, 3                   ; 3: its windows, bottom to top (on
        jne     .b                      ;  top of the rest now), then the band
        UCALL   hide_cursor
        xor     bx, bx
.l:     cmp     bx, [wdepth]
        jae     .b
        push    bx
        shl     bx, 2
        mov     si, [wstack+bx]
        call    mw_own
        cmp     al, [cs:mw_cur]
        jne     .n
        UCALL   win_paint
.n:     pop     bx
        inc     bx
        jmp     .l
.b:     UCALL   band_redraw             ; 2: the band
.p:     popa
.x:     ret

; ---------------------------------------------------------------------
;  sessions, slots, windows
; ---------------------------------------------------------------------
; AL = a session -> BP = its record (in MT's segment)
mw_rec: push    ax
        push    dx
        xor     ah, ah
        mov     dx, SE_SIZE
        mul     dx
        add     ax, mw_ses
        mov     bp, ax
        pop     dx
        pop     ax
        ret

; task AL, its count AH: shown in a session's terminal window (MT_TOPEN
; gave it the task)?  CF if not.  All kept
mw_owns:
        pusha
        mov     dx, ax
        mov     al, 1
.l:     call    mw_rec
        cmp     byte [cs:bp+SE_USE], 0
        je      .n
        cmp     dx, [cs:bp+SE_TASK]     ; (SE_TASK, SE_TGEN)
        je      .y
.n:     inc     al
        cmp     al, MW_MAX
        jbe     .l
        stc
.y:     popa
        ret

; -> AL = an unused session, BP = its record (there is one: mw_n < MW_MAX)
mw_free:
        mov     al, 1
.l:     call    mw_rec
        cmp     byte [cs:bp+SE_USE], 0
        je      .x
        inc     al
        jmp     .l
.x:     ret

; the running globals (mw_ctx's ranges) into record BP / out of it
mw_save:
        pusha
        push    es
        push    cs
        pop     es
        lea     di, [bp+SE_CTX]
        mov     bx, mw_ctx
.r:     mov     si, [cs:bx]
        or      si, si
        jz      .x
        mov     cx, [cs:bx+2]
        rep     movsb
        add     bx, 4
        jmp     .r
.x:     pop     es
        popa
        ret
mw_load_ctx:
        push    di
        mov     di, bp
        call    .di
        pop     di
        ret
.di:    pusha                           ; (record DI)
        push    ds
        lea     si, [di+SE_CTX]
        push    ds
        pop     es
        push    cs
        pop     ds
        mov     bx, mw_ctx
.r:     mov     di, [bx]
        or      di, di
        jz      .x
        mov     cx, [bx+2]
        rep     movsb
        add     bx, 4
        jmp     .r
.x:     pop     ds
        push    ds
        pop     es
        popa
        ret

; its name: SI's last part (after any \ or :), 12 characters at most
mw_name:
        pusha
        mov     bx, si
.f:     lodsb
        or      al, al
        jz      .e
        cmp     al, '\'
        je      .p
        cmp     al, ':'
        jne     .f
.p:     mov     bx, si
        jmp     .f
.e:     mov     si, bx
        lea     di, [bp+SE_NAME]
        mov     cx, 12
.c:     lodsb
        cmp     al, 'a'
        jb      .u
        cmp     al, 'z'
        ja      .u
        sub     al, 20h
.u:     mov     [cs:di], al
        inc     di
        or      al, al
        jz      .x
        loop    .c
        mov     byte [cs:di], 0
.x:     popa
        ret

; a slot of CX bytes: the lowest place from run_base clear of every
; session's -> BX; CF if none below FFF0h
mw_slot:
        push    ax
        push    bp
        mov     bx, [run_base]
.again: mov     al, 1
.l:     call    mw_rec
        cmp     byte [cs:bp+SE_USE], 0
        je      .n
        mov     dx, bx                  ; [BX, BX+CX) against [base, end)
        add     dx, cx
        cmp     dx, [cs:bp+SE_BASE]
        jbe     .n
        cmp     bx, [cs:bp+SE_END]
        jae     .n
        mov     bx, [cs:bp+SE_END]      ; past it, and look again
        jmp     .again
.n:     inc     al
        cmp     al, MW_MAX
        jbe     .l
        mov     ax, bx
        add     ax, cx
        jc      .no
        cmp     ax, 0FFF0h
        ja      .no
        clc
        jmp     short .x
.no:    stc
.x:     pop     bp
        pop     ax
        ret

; the UI block to hold DX (a new slot's end) and every session's: CF if
; it can't.  It takes the whole segment (64 KB), or as much of it as is
; free after it: the new session's own blocks (UI_ALLOC: Write's text and
; its shadow) then go past it, not right after it, where they would keep
; the next window from fitting
mw_grow:
        push    ax
        push    bx
        push    dx
        call    mw_top
        cmp     dx, ax
        jae     .s
        mov     dx, ax
.s:     mov     ax, dx                  ; (at most 0FFF0h: no carry)
        add     ax, 15
        shr     ax, 4                   ; AX = the paragraphs it needs
        mov     bx, 1000h
        push    ax
        mov     ah, 4Ah
        int     21h                     ; (ES = the UI)
        pop     ax
        jnc     .x
        cmp     bx, ax                  ; (BX: the most it can have)
        jb      .x                      ; (CF: too little)
        mov     ah, 4Ah
        int     21h
.x:     pop     dx
        pop     bx
        pop     ax
        ret
; -> AX = the highest end of a session's slot (run_base if none)
mw_top: push    bp
        push    cx
        mov     ax, [run_base]
        mov     cl, 1
.l:     xchg    al, cl
        call    mw_rec
        xchg    al, cl
        cmp     byte [cs:bp+SE_USE], 0
        je      .n
        cmp     ax, [cs:bp+SE_END]
        jae     .n
        mov     ax, [cs:bp+SE_END]
.n:     inc     cl
        cmp     cl, MW_MAX
        jbe     .l
        pop     cx
        pop     bp
        ret

; read .RUN SI's image and fixups to BX, fix it there, its BSS zeroes
; (mw_hdr) -> CF, AX = error
mw_load:
        pusha
        mov     dx, si
        mov     ax, 3D00h
        int     21h
        jc      .no
        mov     di, ax                  ; DI = the handle
        mov     bx, ax
        mov     ax, 4200h               ; past the header
        xor     cx, cx
        mov     dx, 16
        int     21h
        jc      .cl
        mov     bp, sp
        mov     dx, [bp+8]              ; (pusha's BX: where)
        mov     cx, [cs:mw_hdr+6]       ; its image there, then its fixups
        mov     ah, 3Fh                 ;  past its BSS (in the stack's room:
        int     21h                     ;  mw_new's slot), so that they
        jc      .cl                     ;  aren't on top of a small BSS
        cmp     ax, cx
        jne     .bad
        add     dx, cx
        add     dx, [cs:mw_hdr+8]
        mov     cx, [cs:mw_hdr+14]
        mov     ah, 3Fh
        int     21h
        jc      .cl
        cmp     ax, cx
        jne     .bad
        mov     bx, di
        mov     ah, 3Eh
        int     21h
        mov     bp, sp
        mov     bp, [bp+8]              ; BP = where
        mov     si, bp
        add     si, [cs:mw_hdr+6]
        add     si, [cs:mw_hdr+8]
        mov     dx, [cs:mw_hdr+6]
        sub     dx, 2
        jb      .badf
        mov     cx, [cs:mw_hdr+10]
        jcxz    .rel
.abs:   lodsw
        cmp     ax, dx
        ja      .badf
        mov     di, ax
        add     di, bp
        add     [di], bp
        loop    .abs
.rel:   mov     cx, [cs:mw_hdr+12]
        jcxz    .bss
.r:     lodsw
        cmp     ax, dx
        ja      .badf
        mov     di, ax
        add     di, bp
        sub     [di], bp
        loop    .r
.bss:   mov     di, bp
        add     di, [cs:mw_hdr+6]
        mov     cx, [cs:mw_hdr+8]
        xor     al, al
        rep     stosb
        popa
        clc
        ret
.bad:   mov     ax, 11
.cl:    push    ax
        mov     bx, di
        mov     ah, 3Eh
        int     21h
        pop     ax
        jmp     short .no
.badf:  mov     ax, 11
.no:    mov     bp, sp
        mov     [bp+14], ax
        popa
        stc
        ret

; AL to the front of mw_mru (taken out first, if it is there)
mw_front:
        push    ax
        call    mw_drop
        pop     ax
        push    bx
        push    cx
        xor     bx, bx
        mov     bl, MW_MAX
.m:     mov     cl, [cs:mw_mru + bx - 1]
        mov     [cs:mw_mru + bx], cl
        dec     bx
        jnz     .m
        mov     [cs:mw_mru], al
        pop     cx
        pop     bx
        ret
; AL out of mw_mru (the rest close up; 0FFh after them)
mw_drop:
        push    bx
        push    cx
        xor     bx, bx
.f:     cmp     [cs:mw_mru + bx], al
        je      .m
        inc     bx
        cmp     bx, MW_MAX + 1
        jb      .f
        jmp     short .x
.m:     cmp     bx, MW_MAX
        jae     .z
        mov     cl, [cs:mw_mru + bx + 1]
        mov     [cs:mw_mru + bx], cl
        inc     bx
        jmp     .m
.z:     mov     byte [cs:mw_mru + MW_MAX], 0FFh
.x:     pop     cx
        pop     bx
        ret

; window SI -> AL = its session (help_w: the running one; else the one
; whose slot holds it; else 0, the Executive's)
mw_own: push    bp
        mov     al, [cs:mw_cur]
        cmp     si, help_w
        je      .x
        mov     al, 1
.l:     call    mw_rec
        cmp     byte [cs:bp+SE_USE], 0
        je      .n
        cmp     si, [cs:bp+SE_BASE]
        jb      .n
        cmp     si, [cs:bp+SE_END]
        jb      .x
.n:     inc     al
        cmp     al, MW_MAX
        jbe     .l
        xor     al, al
.x:     pop     bp
        ret

; session AL's windows to the top of the window stack, in their order ->
; CF if that changed it
mw_raise:
        pusha
        mov     dh, al                  ; (DH: whose)
        push    es
        push    cs
        pop     es
        mov     di, mw_tmp
        xor     dl, dl                  ; (pass 0: the others; 1: AL's)
.p:     xor     bx, bx
.l:     cmp     bx, [wdepth]
        jae     .e
        push    bx
        shl     bx, 2
        mov     si, [wstack+bx]
        call    mw_own
        cmp     al, dh
        mov     al, 0
        jne     .t
        inc     al
.t:     cmp     al, dl
        jne     .s
        mov     ax, [wstack+bx]
        stosw
        mov     ax, [wstack+bx+2]
        stosw
.s:     pop     bx
        inc     bx
        jmp     .l
.e:     inc     dl
        cmp     dl, 2
        jb      .p
        pop     es
        mov     cx, [wdepth]
        shl     cx, 1
        push    ds
        push    ds
        pop     es
        push    cs
        pop     ds
        mov     si, mw_tmp              ; (the same? CF clear)
        mov     di, wstack
        push    cx
        repe    cmpsw                   ; (CX = 0: ZF as the SHL left it, set)
        pop     cx
        je      .x
        mov     si, mw_tmp
        mov     di, wstack
        rep     movsw
        pop     ds
        popa
        stc
        ret
.x:     pop     ds
        popa
        clc
        ret

; session AL's windows off the window stack (the session goes) -> CF if
; it had any
mw_unwin:
        pusha
        mov     dh, al                  ; (DH: whose)
        xor     bx, bx                  ; (read)
        xor     di, di                  ; (kept)
        xor     dl, dl                  ; (DL: 1 if any went)
.l:     cmp     bx, [wdepth]
        jae     .e
        push    bx
        shl     bx, 2
        mov     si, [wstack+bx]
        call    mw_own
        cmp     al, dh
        jne     .k
        mov     dl, 1
        jmp     short .n
.k:     mov     ax, [wstack+bx]
        mov     cx, [wstack+bx+2]
        push    di
        shl     di, 2
        mov     [wstack+di], ax
        mov     [wstack+di+2], cx
        pop     di
        inc     di
.n:     pop     bx
        inc     bx
        jmp     .l
.e:     mov     [wdepth], di
        or      dl, dl
        jz      .x
        mov     word [wover], 0
        popa
        stc
        ret
.x:     popa
        clc
        ret

; a click at BX = x, CX = y -> AL = the session whose window is the
; topmost there; CF if none
mw_hit: push    si
        push    dx
        push    bp
        mov     dx, bx
        shr     dx, 3                   ; (the column)
        mov     bp, [wdepth]
.l:     dec     bp
        js      .no
        push    bp
        shl     bp, 2
        mov     si, [wstack+bp]
        pop     bp
        cmp     dx, [si+W_COL]
        jb      .l
        mov     ax, [si+W_COL]
        add     ax, [si+W_W]
        cmp     dx, ax
        jae     .l
        cmp     cx, [si+W_Y]
        jb      .l
        mov     ax, [si+W_Y]
        add     ax, [si+W_H]
        cmp     cx, ax
        jae     .l
        call    mw_own
        clc
        jmp     short .x
.no:    stc
.x:     pop     bp
        pop     dx
        pop     si
        ret

; a help or form window (help_w) open? CF if so
mw_modal:
        push    bx
        mov     bx, [wdepth]
        shl     bx, 2
.l:     sub     bx, 4
        jb      .no
        cmp     word [wstack+bx], help_w
        jne     .l
        stc
        jmp     short .x
.no:    clc
.x:     pop     bx
        ret

; ---------------------------------------------------------------------
;  resizing (WF_SIZE): win_mv's way, the outline's size following the
;  pointer or the arrow keys instead of its place
; ---------------------------------------------------------------------
; the top window, if the session running may resize it -> SI; CF if not
mw_szwin:
        push    ax
        mov     si, [wdepth]
        or      si, si
        jz      .no
        cmp     word [wover], 0         ; (windows past NWIN: the top isn't drawn)
        jne     .no
        shl     si, 2
        mov     si, [wstack+si-4]
        UCALL   win_flags               ; AL = its W_FLAGS (0 before API 6)
        test    al, WF_SIZE
        jz      .no
        call    mw_own
        cmp     al, [cs:mw_cur]
        jne     .no
        pop     ax
        clc
        ret
.no:    pop     ax
        stc
        ret

; a press at BX = x, CX = y on window SI's resize corner (its last
; column, the bottom 12 pixel rows)? CF if so
mw_corner:
        push    ax
        mov     ax, bx
        shr     ax, 3
        sub     ax, [si+W_COL]
        inc     ax
        cmp     ax, [si+W_W]
        jne     .no
        mov     ax, [si+W_Y]
        add     ax, [si+W_H]
        sub     ax, cx                  ; (rows from its bottom edge: 1 ...)
        jbe     .no
        cmp     ax, MW_CORNER
        ja      .no
        pop     ax
        stc
        ret
.no:    pop     ax
        clc
        ret

; resize window SI by the mouse (CF set: pressed on its corner; the
; outline's corner follows the pointer while the button is down) or by the
; keys (CF clear: CODE-F8; the arrows widen or narrow it a column, lengthen
; or shorten it a text row, Return keeps the size, ESC leaves it) -> CF
; set if its size changed (and the screen is drawn again)
mw_size:
        pusha
        sbb     bp, bp                  ; (BP = 0FFFFh: the mouse)
        UCALL   hide_cursor
        mov     ax, [si+W_COL]          ; the outline at its place, its size
        mov     [mv_c], ax
        mov     ax, [si+W_Y]
        mov     [mv_y], ax
        mov     ax, [si+W_W]
        mov     [cs:mw_ow], ax
        mov     ax, [si+W_H]
        mov     [cs:mw_oh], ax
        UCALL   mv_frame
        or      bp, bp
        jz      .k
        mov     byte [ptr_on], 0        ; (mouse_event leaves the pointer off)
.w:     sti
        hlt
        cmp     byte [mflag], 0
        je      .w
        UCALL   mouse_event             ; AX = x, BX = y (as win_mv takes them)
        jnc     .xy
        xchg    ax, bx
        mov     bx, cx
.xy:    mov     dx, bx
        shr     ax, 3
        sub     ax, [si+W_COL]
        inc     ax                      ; (the pointer's column: the last)
        sub     dx, [si+W_Y]
        add     dx, 4                   ; (its row: in the last 4)
        call    mw_szto
        test    byte [oldmb], 1
        jnz     .w
        jmp     short .end              ; (released: the next press is a click)
.k:     mov     ah, 11h
        int     16h
        jnz     .key
        sti
        hlt
        jmp     .k
.key:   UCALL   read_key
        mov     bx, [si+W_W]
        mov     dx, [si+W_H]
        cmp     ax, K_LEFT
        jne     .1
        dec     bx
.1:     cmp     ax, K_RIGHT
        jne     .2
        inc     bx
.2:     cmp     ax, K_UP
        jne     .3
        sub     dx, 16
.3:     cmp     ax, K_DOWN
        jne     .4
        add     dx, 16
.4:     cmp     al, 0Dh
        je      .end
        cmp     al, 1Bh
        je      .esc
        xchg    ax, bx
        call    mw_szto
        jmp     .k
.esc:   UCALL   mv_frame                ; (back as it was, exactly: not through
        mov     ax, [cs:mw_ow]          ;  mw_szto's rules, which a window's
        mov     [si+W_W], ax            ;  own size needn't keep)
        mov     ax, [cs:mw_oh]
        mov     [si+W_H], ax
        popa
        clc
        ret
.end:   UCALL   mv_frame                ; the outline off
        mov     ax, [si+W_W]
        cmp     ax, [cs:mw_ow]
        jne     .new
        mov     ax, [si+W_H]
        cmp     ax, [cs:mw_oh]
        je      .same
.new:   UCALL   redraw_all              ; (its W_DRAW, at the new size)
        popa
        stc
        ret
.same:  popa
        clc
        ret

; the outline of window SI to AX columns by DX pixels (signed; at least
; MW_MINW by MW_MINH, kept on the screen above the band, the height a
; multiple of 4): W_W and W_H take it
mw_szto:
        pusha
        cmp     ax, MW_MINW
        jge     .w1
        mov     ax, MW_MINW
.w1:    mov     bx, 80
        sub     bx, [si+W_COL]
        cmp     ax, bx
        jle     .w2
        mov     ax, bx
.w2:    cmp     dx, MW_MINH
        jge     .h1
        mov     dx, MW_MINH
.h1:    mov     bx, SCR_BAND_Y
        sub     bx, [si+W_Y]
        cmp     dx, bx
        jle     .h2
        mov     dx, bx
.h2:    and     dx, 0FFFCh
        cmp     ax, [si+W_W]
        jne     .ch
        cmp     dx, [si+W_H]
        je      .x
.ch:    UCALL   mv_frame                ; off at the old size, on at the new
        mov     [si+W_W], ax
        mov     [si+W_H], dx
        UCALL   mv_frame
.x:     popa
        ret

; ---------------------------------------------------------------------
;  clipping (M8c).  While window .RUNs run, the core's drawing primitives
;  start with a JMP FAR here (mw_clipon).  With the Executive in front,
;  what it draws (its list, its form, its information lines) is cut, row
;  by row, around the sessions' windows above it, unless it lies inside a
;  window of its own (a help, a form: nothing under that cuts it).
;  win_paint and the saver draw unclipped (mw_nc): a session's window
;  drawn by the Executive's redraw_all, the saver's dark screen.  Else, and
;  with nothing in the way, the primitive itself runs on (its first
;  instructions done here)
; ---------------------------------------------------------------------
mw_cpt: dw      clear_screen, mw_c_cls  ; where, to; its own first 5 bytes
        db      51h, 57h, 50h, 06h, 68h ; PUSH CX/DI/AX/ES, PUSH VSEG
        dw      fill_band, mw_c_fill
        db      60h, 0E8h               ; PUSHA, CALL clip_rows, JZ .none
        dw      clip_rows - (fill_band + 4)
        db      74h
        dw      invert_band, mw_c_inv
        db      60h, 85h, 0EDh, 74h     ; PUSHA, TEST BP,BP, JZ .none
        db      invert_band.none - (invert_band + 5)
        dw      vline, mw_c_vl
        db      60h, 0E8h               ; PUSHA, CALL clip_rows, JZ .none
        dw      clip_rows - (vline + 4)
        db      74h
        dw      putsn, mw_c_text
        db      60h, 06h, 0BDh, 80, 0   ; PUSHA, PUSH ES, MOV BP,80
        dw      xor_rect, mw_c_xor
        db      60h, 06h, 68h, VSEG & 0FFh, VSEG >> 8   ; PUSHA, PUSH ES, PUSH VSEG
        dw      win_paint, mw_c_wp
        db      60h, 8Bh, 54h, W_Y, 8Bh ; PUSHA, MOV DX,[SI+W_Y], MOV CX,[SI+W_H]
        dw      saver, mw_c_sv
        db      60h, 0E8h               ; PUSHA, CALL hide_cursor, CLI
        dw      hide_cursor - (saver + 4)
        db      0FAh
        dw      0
MW_CPE      equ     9
mw_cp       db      0                   ; 1: the patches are in
mw_nc       db      0                   ; (win_paint, the saver: unclipped)
mw_useg     dw      0                   ; the UI's segment (mw_clipon)
mw_kind     db      0                   ; the primitive (MK_*)
MK_FILL     equ     0
MK_INV      equ     1
MK_VL       equ     2
MK_TEXT     equ     3
MK_XOR      equ     4
mw_val      db      0                   ; MK_FILL's byte, MK_VL's bit
mw_tm       db      0                   ; MK_TEXT's mask
mw_xh       db      0                   ; (MK_XOR: 1 on its top or bottom row)
mw_tx       dw      0                   ; MK_TEXT's text (from column mw_r)
mw_p0       dw      0                   ; MK_XOR's pixels across
mw_p1       dw      0
mw_wo       db      0                   ; (mw_clipq: whose window)
mw_ot       dw      0                   ; the primitive's own code (mw_c_*.o)
mw_vx       dw      0                   ; MK_VL's pixel x
mw_yb       dw      0                   ; (mw_cdraw: the band's end)
mw_r        dw      0, 0, 0, 0          ; what is drawn: columns, rows (to: past)
mw_cln      dw      0                   ; the sessions' windows across it:
mw_cl       times NWIN * 4 dw 0         ;  columns, rows each (to: past)

; the patches' bytes as they should be (mw_patch: ES = the UI) -> ZF
mw_cpchk:
        push    si
        push    di
        push    cx
        push    ds
        push    cs
        pop     ds
        mov     si, mw_cpt
.l:     mov     di, [si]
        or      di, di
        jz      .ok
        push    si
        add     si, 4
        mov     cx, 5
        repe    cmpsb
        pop     si
        jne     .x
        add     si, MW_CPE
        jmp     .l
.ok:    cmp     byte [es:fill_band + 5], fill_band.none - (fill_band + 6)
        jne     .x                      ; (the JZs' targets past the 5 bytes)
        cmp     byte [es:vline + 5], vline.none - (vline + 6)
        jne     .x
        cmp     word [es:win_paint + 5], 4Ch + W_H * 256
.x:     pop     ds
        pop     cx
        pop     di
        pop     si
        ret

; the patches in, the first window .RUN starting / out, the last ended or
; all forgotten (DS = the UI)
mw_clipon:
        cmp     byte [cs:mw_cp], 0
        jne     .x
        mov     byte [cs:mw_nc], 0
        mov     [cs:mw_useg], ds        ; (the UI's: its stack is in it)
        pusha
        mov     si, mw_cpt
.l:     mov     di, [cs:si]
        or      di, di
        jz      .e
        mov     byte [di], 0EAh         ; JMP FAR
        mov     ax, [cs:si+2]
        mov     [di+1], ax
        mov     [di+3], cs
        add     si, MW_CPE
        jmp     .l
.e:     mov     byte [cs:mw_cp], 1
        popa
.x:     ret
mw_clipoff:
        mov     byte [cs:mw_nc], 0
        cmp     byte [cs:mw_cp], 0
        je      .x
        pusha
        mov     bx, mw_cpt
.l:     mov     di, [cs:bx]
        or      di, di
        jz      .e
        lea     si, [bx+4]
        mov     cx, 5
.c:     mov     al, [cs:si]
        mov     [di], al
        inc     si
        inc     di
        loop    .c
        add     bx, MW_CPE
        jmp     .l
.e:     mov     byte [cs:mw_cp], 0
        popa
.x:     ret

; the top window a session's (not the Executive's)? CF if so
mw_topses:
        push    si
        push    ax
        mov     si, [wdepth]
        or      si, si
        jz      .no
        shl     si, 2
        mov     si, [wstack+si-4]
        call    mw_own
        or      al, al
        jz      .no
        stc
        jmp     short .x
.no:    clc
.x:     pop     ax
        pop     si
        ret

; the primitives' entries (JMP FAR from them; DS = the UI, the caller's
; near return on the stack)
mw_c_cls:                               ; clear_screen
        cmp     byte [cs:mw_cur], 0
        jne     .o
        cmp     byte [cs:mw_nc], 0
        jne     .o
        pusha
        mov     byte [cs:mw_kind], MK_FILL
        mov     byte [cs:mw_val], 0
        mov     word [cs:mw_ot], mw_c_fill.o
        xor     bx, bx
        mov     bp, 80
        xor     dx, dx
        mov     cx, 400
        call    mw_cbox
        popa
        jnc     .o
        jmp     mw_uret
.o:     push    cx
        push    di
        push    ax
        push    es
        push    VSEG
        push    ds
        push    word clear_screen + 7
        retf

mw_c_fill:                              ; fill_band: DX = y, CX = rows,
        cmp     byte [cs:mw_cur], 0     ;  BX = column, BP = width, AL = value
        jne     .o
        cmp     byte [cs:mw_nc], 0
        jne     .o
        pusha
        mov     byte [cs:mw_kind], MK_FILL
        mov     [cs:mw_val], al
        mov     word [cs:mw_ot], .o
        call    mw_cbox
        popa
        jnc     .o
        jmp     mw_uret
.o:     pusha
        UCALL   clip_rows
        jz      .n
        push    ds
        push    word fill_band + 6
        retf
.n:     push    ds
        push    word fill_band.none
        retf

mw_c_inv:                               ; invert_band: as fill_band's
        cmp     byte [cs:mw_cur], 0
        jne     .o
        cmp     byte [cs:mw_nc], 0
        jne     .o
        test    bp, bp
        jz      .o
        pusha
        mov     byte [cs:mw_kind], MK_INV
        mov     word [cs:mw_ot], .o
        call    mw_cbox
        popa
        jnc     .o
        jmp     mw_uret
.o:     pusha
        test    bp, bp
        jz      .n
        push    ds
        push    word invert_band + 5
        retf
.n:     push    ds
        push    word invert_band.none
        retf

mw_c_vl:                                ; vline: AX = pixel x, DX = y0,
        cmp     byte [cs:mw_cur], 0     ;  CX = height
        jne     .o
        cmp     byte [cs:mw_nc], 0
        jne     .o
        pusha
        mov     byte [cs:mw_kind], MK_VL
        mov     word [cs:mw_ot], .o
        mov     [cs:mw_vx], ax
        mov     bx, ax
        shr     bx, 3
        push    cx
        mov     cl, al
        and     cl, 7
        mov     al, 80h
        shr     al, cl
        pop     cx
        mov     [cs:mw_val], al
        mov     bp, 1
        call    mw_cbox
        popa
        jnc     .o
        jmp     mw_uret
.o:     pusha
        UCALL   clip_rows
        jz      .n
        push    ds
        push    word vline + 6
        retf
.n:     push    ds
        push    word vline.none
        retf

mw_c_text:                              ; putsn: SI = text, CX = count,
        cmp     byte [cs:mw_cur], 0     ;  BX = column, DX = y, AH = mask
        jne     .o
        cmp     byte [cs:mw_nc], 0
        jne     .o
        pusha
        cmp     bx, 80                  ; (as putsn cuts it at the right edge)
        jae     .no
        mov     bp, 80
        sub     bp, bx
        cmp     cx, bp
        jbe     .n
        mov     cx, bp
.n:     jcxz    .no
        mov     byte [cs:mw_kind], MK_TEXT
        mov     word [cs:mw_ot], .o
        mov     [cs:mw_tm], ah
        mov     [cs:mw_tx], si
        mov     bp, cx
        mov     cx, 16
        call    mw_cbox
        popa
        jnc     .o
        jmp     mw_uret
.no:    popa
.o:     pusha
        push    es
        mov     bp, 80
        push    ds
        push    word putsn + 5
        retf

mw_c_xor:                               ; xor_rect: pixels AX..DI across,
        cmp     byte [cs:mw_cur], 0     ;  rows DX..DX+CX-1
        jne     .o
        cmp     byte [cs:mw_nc], 0
        jne     .o
        pusha
        mov     byte [cs:mw_kind], MK_XOR
        mov     [cs:mw_p0], ax
        mov     [cs:mw_p1], di
        mov     bx, ax
        shr     bx, 3
        mov     bp, di
        shr     bp, 3
        inc     bp
        sub     bp, bx
        call    mw_cbox
        popa
        jnc     .o
        jmp     mw_uret
.o:     pusha
        push    es
        push    VSEG
        push    ds
        push    word xor_rect + 5
        retf

mw_c_wp:                                ; win_paint: unclipped, whoever
        inc     byte [cs:mw_nc]         ;  draws (its RET comes back here)
        push    cs
        push    word .back
        push    word ..@ui_retf
        pusha
        mov     dx, [si+W_Y]
        mov     cx, [si+W_H]
        push    ds
        push    word win_paint + 7
        retf
.back:  dec     byte [cs:mw_nc]
mw_uret:                                ; RET (near) into the UI: to the
        push    ds                      ;  primitive's caller
        push    word ..@ui_ret
        retf

mw_c_sv:                                ; the saver: unclipped (in a DOS task,
        push    ax                      ;  ui_saver_far's, on its stack: not
        mov     ax, ss                  ;  counted, its drawing never clipped
        cmp     ax, [cs:mw_useg]        ;  there: mw_clipq)
        pop     ax
        je      .ui
        pusha
        UCALL   hide_cursor
        cli
        push    ds
        push    word saver + 5
        retf
.ui:    inc     byte [cs:mw_nc]
        push    cs
        push    word .back
        push    word ..@ui_retf
        pusha
        UCALL   hide_cursor
        cli
        push    ds
        push    word saver + 5
        retf
.back:  dec     byte [cs:mw_nc]
        jmp     mw_uret

; columns BX (BP of them), rows DX (CX of them), for mw_kind: drawn around
; the sessions' windows (CF set) if any is across it; else CF clear and
; nothing drawn
mw_cbox:
        mov     [cs:mw_r], bx
        add     bx, bp
        cmp     bx, 80
        jbe     .c
        mov     bx, 80
.c:     mov     [cs:mw_r+2], bx
        mov     [cs:mw_r+4], dx
        add     dx, cx
        cmp     dx, 400
        jbe     .r
        mov     dx, 400
.r:     mov     [cs:mw_r+6], dx
        call    mw_clipq
        jnc     .x
        call    mw_cdraw
        stc
.x:     ret

; the sessions' windows across mw_r, from the top window down to one of
; the Executive's that holds mw_r (if any), into mw_cl -> CF if any
mw_clipq:
        pusha
        xor     di, di                  ; (mw_cl's bytes)
        mov     ax, ss                  ; (a DOS task's call, ui_saver_far's:
        cmp     ax, [cs:mw_useg]        ;  its screen, not the windows')
        jne     .e
        mov     bx, [wdepth]
.l:     dec     bx
        js      .e
        mov     si, bx
        shl     si, 2
        mov     si, [wstack+si]
        call    mw_own
        mov     [cs:mw_wo], al
        mov     ax, [si+W_COL]          ; AX..CX, DX..BP: its columns, rows
        mov     cx, ax
        add     cx, [si+W_W]
        mov     dx, [si+W_Y]
        mov     bp, dx
        add     bp, [si+W_H]
        cmp     byte [cs:mw_wo], 0
        jne     .s
        cmp     ax, [cs:mw_r]           ; the Executive's: holding mw_r?
        ja      .l
        cmp     cx, [cs:mw_r+2]
        jb      .l
        cmp     dx, [cs:mw_r+4]
        ja      .l
        cmp     bp, [cs:mw_r+6]
        jb      .l
        jmp     short .e                ; (yes: nothing under it cuts)
.s:     cmp     ax, [cs:mw_r+2]         ; a session's: across mw_r?
        jae     .l
        cmp     cx, [cs:mw_r]
        jbe     .l
        cmp     dx, [cs:mw_r+6]
        jae     .l
        cmp     bp, [cs:mw_r+4]
        jbe     .l
        mov     [cs:mw_cl+di], ax
        mov     [cs:mw_cl+di+2], cx
        mov     [cs:mw_cl+di+4], dx
        mov     [cs:mw_cl+di+6], bp
        add     di, 8
        jmp     .l
.e:     shr     di, 3
        mov     [cs:mw_cln], di
        cmp     di, 1                   ; (CF: none)
        cmc
        popa
        ret

; mw_r drawn for mw_kind but where mw_cl's windows (mw_cln is 1 or more)
; hold it: in bands of rows between their edges, each band's spans (the
; same on all its rows) drawn by the primitive's own code where it can be
mw_cdraw:
        push    es
        push    VSEG
        pop     es
        mov     dx, [cs:mw_r+4]
.y:     cmp     dx, [cs:mw_r+6]
        jae     .x
        mov     di, [cs:mw_r+6]         ; the band: to the next edge below DX
        mov     si, mw_cl
        mov     cx, [cs:mw_cln]
.b:     mov     ax, [cs:si+4]
        cmp     ax, dx
        jbe     .b1
        cmp     ax, di
        jae     .b1
        mov     di, ax
.b1:    mov     ax, [cs:si+6]
        cmp     ax, dx
        jbe     .b2
        cmp     ax, di
        jae     .b2
        mov     di, ax
.b2:    add     si, 8
        loop    .b
        mov     [cs:mw_yb], di
        mov     ax, [cs:mw_r]
.s:     cmp     ax, [cs:mw_r+2]
        jae     .ny
        mov     si, mw_cl               ; a window holding column AX on row
        mov     cx, [cs:mw_cln]         ;  DX: on past it
.k:     cmp     dx, [cs:si+4]
        jb      .kn
        cmp     dx, [cs:si+6]
        jae     .kn
        cmp     ax, [cs:si]
        jb      .kn
        cmp     ax, [cs:si+2]
        jae     .kn
        mov     ax, [cs:si+2]
        jmp     .s
.kn:    add     si, 8
        loop    .k
        mov     bx, [cs:mw_r+2]         ; else a span: up to the next window
        mov     si, mw_cl               ;  on row DX
        mov     cx, [cs:mw_cln]
.e:     cmp     dx, [cs:si+4]
        jb      .en
        cmp     dx, [cs:si+6]
        jae     .en
        mov     di, [cs:si]
        cmp     di, ax
        jbe     .en
        cmp     di, bx
        jae     .en
        mov     bx, di
.en:    add     si, 8
        loop    .e
        call    mw_rect
        mov     ax, bx
        jmp     .s
.ny:    mov     dx, [cs:mw_yb]
        jmp     .y
.x:     pop     es
        ret

; columns AX..BX (past), rows DX..mw_yb (past), for mw_kind: the
; primitive's own code (mw_ot) for a fill, an inversion, a line, or text
; whose rows are all there; else row by row (mw_span).  All kept
mw_rect:
        pusha
        mov     cx, [cs:mw_yb]
        sub     cx, dx                  ; CX = rows
        mov     bp, bx
        sub     bp, ax                  ; BP = columns
        mov     bl, [cs:mw_kind]
        cmp     bl, MK_TEXT
        je      .t
        cmp     bl, MK_XOR
        je      .r
        cmp     bl, MK_VL
        je      .v
        mov     bx, ax                  ; MK_FILL, MK_INV: BX = the column,
        mov     al, [cs:mw_val]         ;  AL = the byte
        jmp     short .o
.v:     mov     ax, [cs:mw_vx]          ; MK_VL: AX = its pixel's x
        jmp     short .o
.t:     cmp     dx, [cs:mw_r+4]         ; MK_TEXT: whole glyphs?
        jne     .r
        cmp     cx, 16
        jne     .r
        mov     si, ax                  ; SI = from the character at column AX
        sub     si, [cs:mw_r]
        add     si, [cs:mw_tx]
        mov     bx, ax
        mov     cx, bp
        mov     ah, [cs:mw_tm]
.o:     push    cs                      ; the primitive past its patch, its
        push    word .x                 ;  RET to a RETF here
        push    word ..@ui_retf
        jmp     word [cs:mw_ot]
.r:     mov     bx, ax                  ; row by row
        add     bx, bp
.rl:    call    mw_span
        inc     dx
        loop    .rl
.x:     popa
        ret

; columns AX..BX (past) of row DX, for MK_TEXT (part of a glyph's rows) or
; MK_XOR (ES = the screen, DS = the UI); all registers kept
mw_span:
        pusha
        mov     di, dx                  ; DI = the row's offset (row_di's)
        and     di, 3
        ror     di, 3
        push    dx
        shr     dx, 2
        imul    dx, dx, 80
        add     di, dx
        pop     dx
        add     di, ax
        mov     cx, bx
        sub     cx, ax                  ; CX = bytes
        cmp     byte [cs:mw_kind], MK_TEXT
        jne     .4
        mov     si, ax                  ; the characters from column AX
        sub     si, [cs:mw_r]
        add     si, [cs:mw_tx]
        mov     bx, dx                  ; BX: the glyphs' row, the font's
        sub     bx, [cs:mw_r+4]         ;  first (32) less
        add     bx, font - 32 * 16
.t:     lodsb
        cmp     al, 32
        jb      .bad
        cmp     al, 127
        jbe     .ok
.bad:   mov     al, '?'
.ok:    xor     ah, ah
        shl     ax, 4
        push    si
        mov     si, ax
        mov     al, [si+bx]
        pop     si
        xor     al, [cs:mw_tm]
        stosb
        loop    .t
.x:     popa
        ret
.4:     mov     si, ax                  ; MK_XOR: SI = the column
        mov     bp, cx
        mov     byte [cs:mw_xh], 1      ; its top or bottom row: pixels p0..p1;
        cmp     dx, [cs:mw_r+4]         ;  any other: p0 and p1
        je      .xl
        mov     ax, dx
        inc     ax
        cmp     ax, [cs:mw_r+6]
        je      .xl
        mov     byte [cs:mw_xh], 0
        cmp     byte [cs:mw_xh], 0
        je      .xs
.xl:    mov     ax, [cs:mw_p0]          ; top or bottom: each column's p0..p1
        mov     bx, [cs:mw_p1]
        call    mw_pmask
        xor     [es:di], al
        inc     di
        inc     si
        dec     bp
        jnz     .xl
        jmp     .x
.xs:    mov     ax, [cs:mw_p0]          ; a side row: the columns of p0 and p1
        call    .xc                     ;  only, if in AX..BX (SI .. SI+BP)
        mov     ax, [cs:mw_p1]
        mov     bx, ax
        shr     bx, 3
        mov     cx, [cs:mw_p0]
        shr     cx, 3
        cmp     bx, cx                  ; (the same column: done)
        je      .x
        call    .xc
        jmp     .x
.xc:    push    di                      ; pixel AX, if its column is in the span
        push    si
        mov     bx, ax
        shr     bx, 3
        sub     bx, si                  ; (columns past the span's first)
        cmp     bx, bp
        jae     .xn
        add     di, bx
        add     si, bx
        mov     ax, [cs:mw_p0]          ; p0's and p1's bits in that column
        mov     bx, ax
        call    mw_pmask
        mov     cl, al
        mov     ax, [cs:mw_p1]
        mov     bx, ax
        call    mw_pmask
        or      al, cl
        xor     [es:di], al
.xn:    pop     si
        pop     di
        ret

; column SI's pixels AX..BX (signed; those in it) -> AL, a bit each
mw_pmask:
        push    bx
        push    cx
        push    dx
        mov     dx, si
        shl     dx, 3                   ; DX = its first pixel
        cmp     ax, dx
        jge     .a
        mov     ax, dx
.a:     add     dx, 7
        cmp     bx, dx
        jle     .b
        mov     bx, dx
.b:     cmp     ax, bx
        jg      .z
        mov     cl, al
        and     cl, 7
        mov     al, 0FFh
        shr     al, cl                  ; from pixel AX
        mov     cl, bl
        and     cl, 7
        mov     ch, 7
        sub     ch, cl
        mov     cl, ch
        mov     dl, 0FFh
        shl     dl, cl                  ; to pixel BX
        and     al, dl
        jmp     short .x
.z:     xor     al, al
.x:     pop     dx
        pop     cx
        pop     bx
        ret

; ---------------------------------------------------------------------
;  run_cleanup's first 5 bytes (JMP FAR, DS = the UI).  With sessions it
;  can only be the root starting over (a .RUN's ^C, a crash): every one
;  is forgotten, the blocks each had from UI_ALLOC freed
; ---------------------------------------------------------------------
mw_clean:
        cmp     byte [cs:mw_n], 0
        je      .x
        push    ax
        push    si
        push    bp
        push    es
        mov     al, 1
.s:     call    mw_rec
        cmp     al, [cs:mw_cur]         ; (the running one's: run_cleanup's)
        je      .n
        cmp     byte [cs:bp+SE_USE], 0
        je      .n
        mov     si, SE_CTX + MW_CALLOC
.f:     push    ax
        mov     ax, [cs:bp+si]          ; (its alloc_tab)
        or      ax, ax
        jz      .fn
        mov     es, ax
        mov     ah, 49h
        int     21h
.fn:    pop     ax
        add     si, 2
        cmp     si, SE_CTX + MW_CALLOC + 2 * NALLOC
        jb      .f
.n:     mov     byte [cs:bp+SE_USE], 0
        inc     al
        cmp     al, MW_MAX
        jbe     .s
        mov     byte [cs:mw_n], 0
        mov     byte [cs:mw_cur], 0
        mov     byte [cs:mw_rd], 0
        mov     byte [cs:mw_msg], 0
        call    mw_clipoff
        mov     byte [run_active], 1    ; (so run_cleanup shrinks the block)
        pop     es
        pop     bp
        pop     si
        pop     ax
.x:     pusha                           ; run_cleanup's own first 5 bytes,
        push    es                      ;  then on there
        mov     si, alloc_tab
        push    ds
        push    word run_cleanup + 5
        retf
