; =====================================================================
;  KMW.INC - several window .RUNs at once (M8a), with MULTITASK=1 only.
;  Part of LODEMT.SYS (section mtt): off, none of it is in memory and the
;  UI is byte for byte as it was.
;
;  A window .RUN (RUN_API 6 and up: CALC, TASKS) is a session: its own
;  load area in the UI segment (a slot, from run_base up, first fit), its
;  own stack at the slot's end, and its own copy of the core's globals
;  that belong to one program (mw_ctx's ranges: the band, the title, the
;  list and form and line editor's state, UI_ALLOC's blocks, its header).
;  Sessions run in turn inside the UI task: only the one in front (the
;  focus) runs; the others wait inside UI_EVENT, where they were.  The
;  Executive waits meanwhile in run_app until the last has ended (M8b
;  makes it live), as it waits for a .RUN today.
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
SE_CTX      equ 22                      ; mw_ctx's ranges, while another runs
MW_CTXLEN   equ 100
SE_SIZE     equ SE_CTX + MW_CTXLEN

%macro UCALL 1                          ; CALL a near routine of the UI (DS = it)
        push    cs
        push    word %%r
        push    word ..@ui_retf         ;  (its RET goes to a RETF there)
        push    ds
        push    word %1
        retf
%%r:
%endmacro

mw_ctx:     dw      title_on,  held2 + 2 - title_on
            dw      redraw_fn, 2
            dw      lv_cur,    ed_keep + 1 - lv_cur
            dw      fm_ptr,    fm_b2 + 2 - fm_ptr
            dw      crit_err,  2
            dw      alloc_tab, run_ret + 2 - alloc_tab
            dw      0
MW_CALLOC   equ (held2 + 2 - title_on) + 2 + (ed_keep + 1 - lv_cur) + (fm_b2 + 2 - fm_ptr) + 2
                                        ; (alloc_tab's place in a record's copy)
%if MW_CALLOC + (run_ret + 2 - alloc_tab) > MW_CTXLEN
%error "KMW: mw_ctx's ranges are longer than MW_CTXLEN"
%endif

mw_on       db      0                   ; 1: the UI is patched
mw_n        db      0                   ; window .RUNs running
mw_cur      db      0                   ; the session running (0: the Executive)
mw_rd       db      0                   ; 1: the screen again once switched
mw_msg      db      0                   ; 1: mw_say's message waits (UI_MSG)
mw_ow       dw      0                   ; (mw_size: the size it had)
mw_oh       dw      0
MW_MINW     equ     16                  ; the smallest a window is resized to:
MW_MINH     equ     72                  ;  columns, pixels (title, a row, a status)
MW_CORNER   equ     12                  ; its resize corner: its last column, the
                                        ;  bottom 12 pixel rows
mw_mru      times MW_MAX db 0           ; the sessions, the focus first
mw_xc       dw      0                   ; the last one's exit code
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
mw_run: cmp     byte [run_active], 0
        jne     .busy
        call    mw_peek                 ; a window .RUN?
        jc      .orig                   ; (can't tell: run_app says why)
        test    byte [cs:mw_hdr+14], RF_WIN     ; (its header says so: RUN_FLAGS)
        jz      .orig
        mov     byte [run_active], 1
        mov     word [cs:mw_xc], 0FFFFh ; (none has said "the list again" yet)
        call    mw_start                ; (the Executive waits in here till
        jc      .fail                   ;  the last window .RUN has ended)
        mov     ax, [cs:mw_xc]
        mov     [run_ret], ax
        push    dx
        mov     dx, exec_dta            ; the Executive's DTA again
        mov     ah, 1Ah
        int     21h
        pop     dx
        UCALL   run_cleanup
        mov     ax, [run_ret]
        clc
        jmp     short .ret
.fail:  mov     [run_ret], ax
        UCALL   run_cleanup             ; (run_active 0, the block as it was)
        mov     ax, [run_ret]
        stc
.ret:   push    ds                      ; RET (near) into the UI: to run_app's
        push    word ..@ui_ret          ;  caller
        retf
.busy:  mov     ax, 8                   ; (one at a time, as run_app says)
        stc
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
        mov     [cs:mw_hdr+14], ax      ; (the fixups' bytes)
        cmp     ax, [cs:mw_hdr+8]
        jae     .fx
        mov     ax, [cs:mw_hdr+8]
.fx:    add     ax, [cs:mw_hdr+6]
        jc      .room
        add     ax, MW_STK + MW_TRAMP + 15
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
        call    mw_free                 ; -> AL = a free session, BP = its record
        mov     [cs:mw_new], al
        mov     [cs:bp+SE_BASE], bx
        mov     [cs:bp+SE_END], dx
        call    mw_name                 ; its name, from SI
        mov     byte [cs:bp+SE_USE], 1
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
        pop     ax
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
        ; in front, the starter waiting
        mov     al, [cs:mw_new]
        mov     [cs:mw_cur], al
        inc     byte [cs:mw_n]
        call    mw_front                ; first in mw_mru
        push    bp
        call    mw_rec
        mov     di, [cs:bp+SE_SP]       ; (the new stack)
        pop     bp
        call    mw_park                 ; the starter waits (SP into BP's record)
        popa                            ; (back here when the starter runs again)
        clc
        ret
.lf:    call    mw_shrink               ; (no record kept: SE_USE is 0)
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
mw_end: cld
        push    ss
        pop     ds
        push    ss
        pop     es
        cmp     ax, 0FFFFh              ; its exit code, unless 0FFFFh (no
        je      .xk                     ;  relist): any other one's is kept
        mov     [cs:mw_xc], ax
.xk:    mov     si, alloc_tab           ; its UI_ALLOC blocks
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
        mov     word [cs:mw_xc], 0      ; (and the Executive's list)
.nw:    mov     al, [cs:mw_cur]
        call    mw_rec
        mov     byte [cs:bp+SE_USE], 0
        call    mw_drop                 ; out of mw_mru
        dec     byte [cs:mw_n]
        xor     al, al                  ; the next in front, else the Executive
        cmp     byte [cs:mw_n], 0
        je      .go
        mov     al, [cs:mw_mru]
.go:    mov     [cs:mw_cur], al
        call    mw_rec
        mov     sp, [cs:bp+SE_SP]       ; (its stack now: this slot's may go)
        call    mw_shrink
        or      al, al
        jnz     .top
        mov     byte [cs:mw_rd], 0      ; (the Executive draws its list itself)
        jmp     short .sw
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
        cmp     byte [cs:mw_cur], 0     ; a session's band, if the screen
        je      .b                      ;  isn't drawn again anyway (its
        cmp     byte [cs:mw_rd], 0      ;  question, still waiting)
        jne     .b
        UCALL   band_redraw
.b:     jmp     mw_back

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
        jc      .own
        or      al, al                  ; (the Executive's: it waits, M8a)
        jz      .own
        cmp     al, [cs:mw_cur]
        je      .own
        call    mw_focus
        jmp     short .took
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
.next:  cmp     byte [cs:mw_n], 2       ; the next in front (the one in front
        jb      .took                   ;  goes last)
        call    mw_cycle
.took:  pop     es
        popa
        jmp     short .wait
.own:   pop     es
        popa
.win:   UCALL   win_ev
        jc      .wait
.ret:   retf                            ; (ui_event.got + 5: the event)
.wait:  push    bp
        mov     bp, sp
        mov     word [bp+2], ui_event.on
        pop     bp
        retf

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
.new:   UCALL   ui_findapp              ; SI = its path (.new: started, even
                                        ;  if one runs: CODE-W's Write)
        jc      .nf
        push    di
        mov     di, s_empty
        call    mw_start
        pop     di
        ret
.nf:    mov     ax, 2
        ret

; window .RUN SI (its name) couldn't start, AX = why: said in the band
; (UI_MSG: till a key or a click), the name first
mw_say: pusha
        push    es
        mov     dx, ax                  ; (DX: why)
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
        UCALL   ui_msg
        mov     byte [cs:mw_msg], 0
        pop     es
        popa
        ret
mw_s8   db      " doesn't fit: close a window first", 0
mw_s2   db      " is not on this disk", 0
mw_sx   db      " can't start", 0

; CODE-F6: the one in front goes last, the next comes to the front
mw_cycle:
        mov     al, [cs:mw_mru]
        push    ax
        call    mw_drop
        pop     ax
        xor     bx, bx
        mov     bl, [cs:mw_n]
        mov     [cs:mw_mru + bx - 1], al
        mov     al, [cs:mw_mru]
        ; (falls through)

; session AL to the front: first in mw_mru, its windows on top, the
; screen again once it runs
mw_focus:
        call    mw_front
        call    mw_raise
        mov     byte [cs:mw_rd], 1
        push    ax
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
        mov     byte [cs:mw_rd], 0
        UCALL   redraw_all
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
; the UI block back to the highest end still used (any: run_cleanup's)
mw_shrink:
        cmp     byte [cs:mw_n], 0
        je      .x
        pusha
        call    mw_top                  ; AX = that end
        add     ax, 15
        shr     ax, 4
        mov     bx, ax
        mov     ah, 4Ah
        int     21h                     ; (ES = the UI)
        popa
.x:     ret

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
        mov     cx, [cs:mw_hdr+6]
        add     cx, [cs:mw_hdr+14]
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
        mov     ax, [cs:mw_hdr+14]
        cmp     cx, ax
        jae     .z
        mov     cx, ax
.z:     xor     al, al
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
        mov     bl, MW_MAX - 1
.m:     mov     cl, [cs:mw_mru + bx - 1]
        mov     [cs:mw_mru + bx], cl
        dec     bx
        jnz     .m
        mov     [cs:mw_mru], al
        pop     cx
        pop     bx
        ret
; AL out of mw_mru (the rest close up; 0 after them)
mw_drop:
        push    bx
        push    cx
        xor     bx, bx
.f:     cmp     [cs:mw_mru + bx], al
        je      .m
        inc     bx
        cmp     bx, MW_MAX
        jb      .f
        jmp     short .x
.m:     cmp     bx, MW_MAX - 1
        jae     .z
        mov     cl, [cs:mw_mru + bx + 1]
        mov     [cs:mw_mru + bx], cl
        inc     bx
        jmp     .m
.z:     mov     byte [cs:mw_mru + MW_MAX - 1], 0
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

; session AL's windows to the top of the window stack, in their order
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
        mov     si, mw_tmp
        mov     di, wstack
        push    ds
        push    ds
        pop     es
        push    cs
        pop     ds
        rep     movsw
        pop     ds
        popa
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
.esc:   mov     ax, [cs:mw_ow]          ; (back as it was)
        mov     dx, [cs:mw_oh]
        call    mw_szto
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
        mov     word [cs:mw_mru], 0
        mov     word [cs:mw_mru + 2], 0
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
