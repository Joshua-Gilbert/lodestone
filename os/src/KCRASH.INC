; =====================================================================
;  KCRASH.INC - CRASHLOG, a diagnostic build of LODEMT.SYS (KFLAGS=
;  -dCRASHLOG; os/diag/build.sh).  Not in the normal build.
;
;  A flight recorder: the last CR_N events in a ring in MT's BSS, 16
;  bytes each (CR_* below): every tick (what it interrupted), every
;  switch, KMW's window operations, the front task's mode sets, an INT
;  06h (an invalid opcode).  And a catch for a restart: mt_boot puts
;  mt_crst at 40:67h and shutdown code 0Ah in CMOS 0Fh, so the 1520's
;  BIOS, at any reset after the first (a CPU shutdown: a stack wrapped at
;  SP = 1, a fault in a fault; the keyboard controller's reset; a jump to
;  FFFF:0 or F000:E05B), jumps there at once with memory as it was, no
;  POST (its Reset_Actual, SD_JMP_WITHOUT_INT).  Ctrl-Alt-Del and
;  Lodestone's own restarts (40:72h = 1234h) go on as ever.
;
;  Caught, it copies what it can into a report (CRO_* below, CR_LEN
;  bytes) at CR_SEG:0, puts the BIOS's own vectors back for the screen and
;  the keys, shows the last records in text mode, and on a key restarts
;  (a soft reset, 1234h: the BIOS clears only the first 64 KB, so the
;  report at CR_SEG is still there).  Then CRASHRPT.COM writes it to
;  CRASH.BIN, which tools/crashdecode.py reads with LODE.MAP.
;
;  Breadcrumbs in CMOS 3Dh alone, which survives any restart, a full POST
;  too: its high nibble the stage (CRB_*: armed, in the catch, the report
;  kept, on the screen, a restart passed on), its low nibble the last
;  window operation (its tag's place in cr_wtags; KMW's CREC).  NOT 3Ch:
;  the labelled BIOS source calls 3Ch and 3Dh unused, but the author's
;  10/25/89 ROM keeps the boot password's checksum in 3Ch (F000:F104:
;  the sum of 34h-3Bh and 3Fh & FEh; POST, F000:8D20 -> F1B6, asks for
;  the password when it matches and 3Fh bit 1 is set, and his 3Fh is
;  02h), so a tag written there could lock the machine at the next POST.
;  Nothing in that ROM touches 3Dh.  Each window operation also arms the
;  catch again (CMOS 0Fh, 40:67h), in case something cleared it.  At the
;  next start-up mt_boot puts the old stage and window tag, as the two
;  characters CRASHRPT reads, at CR_PREV, then arms
; =====================================================================
CR_N        equ 256                     ; records in the ring
CR_SEG      equ 5000h                   ; the report (free after a start-up)
CR_STK      equ 512                     ; the catch's own stack
CR_PREV     equ 4FF0h                   ; the last session's breadcrumbs, at
                                        ;  start-up: 'LODEPREV', the stage's
                                        ;  and the window tag's characters
CRB_ARMED   equ 1                       ; (CMOS 3Dh's high nibble: cr_stch
CRB_IN      equ 2                       ;  has their characters)
CRB_KEPT    equ 3
CRB_SHOWN   equ 4
CRB_PASS    equ 5
CRB_VEC     equ 6                       ; (40:67h found changed at a tick, put
CRB_STACK   equ 8                       ; (the owner's stack changed while it
                                        ;  was out on a disk wait: mt_crs1)
CRB_CMOS    equ 7                       ;  back; CMOS 0Fh found changed at a
                                        ;  window operation, set again)

; a record: the tick count, the tag (a letter), the running task, the
; top two words of the caller's stack (at a routine's start its return
; address; a tick: the IP and CS it interrupted), its SP and SS, AX, BX
; (a tick: its flags)
CR_TICK     equ 0
CR_TAG      equ 2
CR_TASK     equ 3
CR_IP       equ 4
CR_CS       equ 6
CR_SP       equ 8
CR_SS       equ 10
CR_AX       equ 12
CR_BX       equ 14

; the report
CRO_SIG     equ 0                       ; 'LODECRSH'
CRO_LEN     equ 8                       ; CR_LEN
CRO_SUM     equ 10                      ; the words from CRO_VARS on, added
CRO_CAUSE   equ 12                      ; 'R' a restart, 'X' INT 06h
CRO_MTSEG   equ 14
CRO_VARS    equ 16                      ; MT's bytes (cr_vb's), then words:
CRO_WORDS   equ 32                      ;  mt_ticks, mt_crp, ui_seg, then for
                                        ;  'X' the fault's IP CS FL SP SS AX
                                        ;  BX CX DX SI DI BP DS ES
CRO_TAB     equ 96                      ; mt_tab (MT_TASKS * MT_ENT)
CRO_RING    equ CRO_TAB + MT_TASKS * MT_ENT
CRO_IVT     equ CRO_RING + CR_N * 16    ; 0:0, 1 KB
CRO_BDA     equ CRO_IVT + 1024          ; 40:0, 256 bytes
CRO_KSTK    equ CRO_BDA + 256           ; the kernel's stack, 1536 bytes to
                                        ;  kstack_top
CRO_LSTK    equ CRO_KSTK + 1536         ; the newest record's stack: 512
                                        ;  bytes from its SP less 384
CRO_TSTK    equ CRO_LSTK + 512          ; each task: its TX's SP, SS, then
                                        ;  256 bytes from that SP less 128
CR_LEN      equ CRO_TSTK + MT_TASKS * 260

cr_vb       dw      mt_cur, mt_front, mt_down, mt_ddev, mt_swing, mt_inb
            dw      mt_crit, mt_in13, mt_vbusy, mt_shd, mw_n, mt_pend
            dw      mt_slice, mt_want, mt_hirq, mt_htk
CR_NVB      equ     ($ - cr_vb) / 2     ; (16)
mt_crp      dw      0                   ; the next record's offset in the ring
mt_crcause  db      0
mt_crss     dw      0                   ; (mt_crs0: the owner's SS, SP, the
mt_crsp     dw      0                   ;  bytes kept, from SP up)
mt_crsn     dw      0
            db      0
mt_crrg     times 14 dw 0               ; 'X': IP CS FL SP SS AX BX CX DX SI
                                        ;  DI BP DS ES

; CREC's record: tag [SP+2], the caller's flags [SP+4] (popped after).
; All kept (the flags by CREC's POPF)
mt_crec:
        cli
        push    bp
        mov     bp, sp
        push    ax
        push    di
        mov     di, [cs:mt_crp]
        add     word [cs:mt_crp], 16
        and     word [cs:mt_crp], CR_N * 16 - 1
        add     di, mt_crb
        mov     [cs:di+CR_AX], ax
        mov     [cs:di+CR_BX], bx
        mov     ax, [cs:mt_ticks]
        mov     [cs:di+CR_TICK], ax
        mov     al, [bp+4]
        mov     ah, [cs:mt_cur]
        mov     [cs:di+CR_TAG], ax
        mov     ax, [bp+8]              ; (the caller's stack's top two words:
        mov     [cs:di+CR_IP], ax       ;  at a routine's start, its return,
        mov     ax, [bp+10]             ;  near or far; crashdecode names
        mov     [cs:di+CR_CS], ax       ;  both)
        lea     ax, [bp+8]
        mov     [cs:di+CR_SP], ax
        mov     [cs:di+CR_SS], ss
        mov     al, [bp+4]                      ; a window operation's: its tag
        cmp     al, 'S'                         ;  to CMOS 3Dh's low nibble, the
        je      .x                              ;  catch armed again
        cmp     al, 'X'
        je      .x
        cmp     al, 'V'
        je      .x
        call    cr_wt
        mov     al, 0Fh                         ; (still 0Ah?  Else something
        out     70h, al                         ;  changed it: stage 7)
        in      al, 71h
        cmp     al, 0Ah
        je      .ok
        mov     al, CRB_CMOS
        call    cr_st
.ok:    mov     ax, 0A0Fh                       ; (CMOS 0Fh = 0Ah: cr_cm takes the
        call    cr_cm                           ;  register in AL.  Swapped, it
                                                ;  wrote 0Fh to status A, 0Ah, and
                                                ;  stopped the clock: POST's
                                                ;  "Time-of-day clock stopped")
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     word [467h], mt_crst
        mov     [469h], cs
        pop     ds
.x:     pop     di
        pop     ax
        pop     bp
        ret     2

; CMOS register AL = AH (NMI left on).  All kept
cr_cm:  out     70h, al
        xchg    al, ah
        out     71h, al
        xchg    al, ah
        ret
; the stage AL (CRB_*) to CMOS 3Dh's high nibble.  All kept
cr_st:  push    ax
        push    cx
        pushf
        cli
        mov     cl, 4
        shl     al, cl
        mov     ah, al
        mov     al, 3Dh
        out     70h, al
        in      al, 71h
        and     al, 0Fh
        or      ah, al
        mov     al, 3Dh
        call    cr_cm
        popf
        pop     cx
        pop     ax
        ret
; the window tag AL to CMOS 3Dh's low nibble (its place in cr_wtags, 0Fh
; if it isn't there).  All kept
cr_wt:  push    ax
        push    cx
        push    si
        pushf
        cli
        mov     si, cr_wtags
        mov     cx, 15
        xor     ah, ah
.l:     cmp     al, [cs:si]
        je      .f
        inc     si
        inc     ah
        loop    .l
        cmp     al, [cs:si]                     ; (the 16th, or none)
        jne     .x
.f:     mov     al, 3Dh
        out     70h, al
        in      al, 71h
        and     al, 0F0h
        or      ah, al
        mov     al, 3Dh
        call    cr_cm
.x:     popf
        pop     si
        pop     cx
        pop     ax
        ret

; the tick's record (from mt_tick, the interrupted IP, CS, FL at [SP+2]):
; 'T'.  AX the interrupted AX, BX its flags.  Interrupts off; all kept
mt_crt: push    bp
        mov     bp, sp
        push    ax
        push    di
        mov     di, [cs:mt_crp]
        add     word [cs:mt_crp], 16
        and     word [cs:mt_crp], CR_N * 16 - 1
        add     di, mt_crb
        mov     [cs:di+CR_AX], ax
        mov     ax, [bp+8]
        mov     [cs:di+CR_BX], ax
        mov     ax, [cs:mt_ticks]
        mov     [cs:di+CR_TICK], ax
        mov     al, 'T'
        mov     ah, [cs:mt_cur]
        mov     [cs:di+CR_TAG], ax
        mov     ax, [bp+4]
        mov     [cs:di+CR_IP], ax
        mov     ax, [bp+6]
        mov     [cs:di+CR_CS], ax
        lea     ax, [bp+10]
        mov     [cs:di+CR_SP], ax
        mov     [cs:di+CR_SS], ss
        push    ds                              ; 40:67h still the catch's?  Else
        xor     ax, ax                          ;  something wrote there: put
        mov     ds, ax                          ;  back, stage 6
        cmp     word [467h], mt_crst
        jne     .v
        mov     ax, cs
        cmp     [469h], ax
        je      .vo
.v:     mov     word [467h], mt_crst
        mov     [469h], cs
        mov     al, CRB_VEC
        call    cr_st
.vo:    pop     ds
        pop     di
        pop     ax
        pop     bp
        ret

; INT 06h, an invalid opcode (any task's: not one of mt_vrun's in this
; build): its frame and registers kept, a record 'X', then the report
mt_cr6: cli
        mov     [cs:mt_crrg+10], ax
        mov     [cs:mt_crrg+12], bx
        mov     [cs:mt_crrg+14], cx
        mov     [cs:mt_crrg+16], dx
        mov     [cs:mt_crrg+18], si
        mov     [cs:mt_crrg+20], di
        mov     [cs:mt_crrg+22], bp
        mov     [cs:mt_crrg+24], ds
        mov     [cs:mt_crrg+26], es
        mov     bp, sp
        mov     ax, [ss:bp]
        mov     [cs:mt_crrg+0], ax
        mov     ax, [ss:bp+2]
        mov     [cs:mt_crrg+2], ax
        mov     ax, [ss:bp+4]
        mov     [cs:mt_crrg+4], ax
        lea     ax, [bp+6]
        mov     [cs:mt_crrg+6], ax
        mov     [cs:mt_crrg+8], ss
        mov     ax, [cs:mt_crrg+10]
        CREC    'X'
        mov     byte [cs:mt_crcause], 'X'
        jmp     mt_crx

; a disk wait's owner going out (mt_dwait, before mt_switch: interrupts
; off): the top of its stack kept, from its SP (the caller's, past this
; call's return) up: the kernel's slice to kstack_top (256 bytes at
; most), or 128 bytes of its own stack.  All kept
mt_crs0:
        pusha
        push    ds
        push    es
        mov     [cs:mt_crss], ss
        mov     si, sp                          ; (past PUSHA, DS, ES, the return)
        add     si, 22
        mov     [cs:mt_crsp], si
        mov     cx, 128
        mov     ax, ss
        cmp     ax, KSEG
        jne     .n
        mov     cx, kstack_top
        sub     cx, si
        cmp     cx, 256
        jbe     .n
        mov     cx, 256
.n:     mov     [cs:mt_crsn], cx
        push    ss
        pop     ds
        push    cs
        pop     es
        mov     di, mt_crsv
        cld
        rep     movsb
        pop     es
        pop     ds
        popa
        ret
; the owner back (mt_dwait.bk): its SS, SP and those bytes as they were?
; Else the report (cause 'K', stage 8), never back.  All kept
mt_crs1:
        pushf
        pusha
        push    ds
        push    es
        cli
        mov     ax, ss
        cmp     ax, [cs:mt_crss]
        jne     .bad
        mov     si, sp                          ; (PUSHF too)
        add     si, 24
        cmp     si, [cs:mt_crsp]
        jne     .bad
        mov     cx, [cs:mt_crsn]
        push    ss
        pop     ds
        push    cs
        pop     es
        mov     di, mt_crsv
        cld
        repe    cmpsb
        jne     .bad
        pop     es
        pop     ds
        popa
        popf
        ret
.bad:   mov     byte [cs:mt_crcause], 'K'
        mov     al, CRB_STACK
        call    cr_st
        jmp     mt_crx

; the BIOS's jump through 40:67h (shutdown code 0Ah): interrupts off,
; its own stack.  1234h at 40:72h: a restart asked for, as ever
mt_crst:
        cli
        xor     ax, ax
        mov     ds, ax
        cmp     word [472h], 1234h
        jne     .c
        mov     al, CRB_PASS
        call    cr_st
        jmp     0F000h:0E05Bh
.c:     mov     byte [cs:mt_crcause], 'R'
; the report, then the screen; a key restarts.  Never returns
mt_crx: cli
        cld
        mov     al, CRB_IN
        call    cr_st
        mov     ax, cs
        mov     ss, ax
        mov     sp, mt_crstk + CR_STK
        mov     es, ax
        mov     ds, ax
        mov     di, mt_crbuf                    ; (MT's BSS first: a task's
        mov     cx, CR_LEN / 2                  ;  stack may be at CR_SEG)
        xor     ax, ax
        rep     stosw
        mov     di, mt_crbuf
        mov     si, cr_sig
        mov     cx, 8
        rep     movsb
        mov     word [mt_crbuf+CRO_LEN], CR_LEN
        mov     al, [mt_crcause]
        mov     [mt_crbuf+CRO_CAUSE], al
        mov     [mt_crbuf+CRO_MTSEG], cs
        mov     si, cr_vb                       ; MT's bytes
        mov     di, mt_crbuf + CRO_VARS
        mov     cx, CR_NVB
.vb:    lodsw
        mov     bx, ax
        mov     al, [bx]
        stosb
        loop    .vb
        mov     di, mt_crbuf + CRO_WORDS
        mov     ax, [mt_ticks]
        stosw
        mov     ax, [mt_crp]
        stosw
        push    ds
        push    KSEG
        pop     ds
        mov     ax, [ui_seg]
        pop     ds
        stosw
        mov     si, mt_crrg
        mov     cx, 14
        rep     movsw
        mov     si, mt_tab
        mov     di, mt_crbuf + CRO_TAB
        mov     cx, MT_TASKS * MT_ENT / 2
        rep     movsw
        mov     si, mt_crb
        mov     di, mt_crbuf + CRO_RING
        mov     cx, CR_N * 16 / 2
        rep     movsw
        xor     si, si                          ; the IVT and the BDA
        mov     di, mt_crbuf + CRO_IVT
        mov     cx, (1024 + 256) / 2
        push    ds
        mov     ds, si
        rep     movsw
        mov     si, kstack_top - 1536           ; the kernel's stack
        mov     di, mt_crbuf + CRO_KSTK
        mov     cx, 1536 / 2
        push    KSEG
        pop     ds
        rep     movsw
        pop     ds
        cmp     byte [mt_crcause], 'K'          ; a disk wait's owner's stack
        jne     .ls                             ;  changed: as kept, then now
        mov     si, mt_crsv
        mov     di, mt_crbuf + CRO_LSTK
        mov     cx, 256
        rep     movsb
        mov     si, [mt_crsp]
        mov     ax, [mt_crss]
        mov     cx, 256
        call    cr_cpy
        jmp     short .lx
.ls:    mov     bx, [mt_crp]                    ; the newest record's stack
        sub     bx, 16
        and     bx, CR_N * 16 - 1
        mov     si, [mt_crb+bx+CR_SP]
        mov     ax, [mt_crb+bx+CR_SS]
        sub     si, 384
        mov     di, mt_crbuf + CRO_LSTK
        mov     cx, 512
        call    cr_cpy
.lx:        mov     di, mt_crbuf + CRO_TSTK         ; each task's, as it was last
        xor     bx, bx                          ;  switched from
.tk:    push    bx
        shl     bx, 5
        add     bx, mt_tab
        cmp     byte [bx+TE_STATE], 0
        je      .tn
        push    es
        mov     es, [bx+TE_TX]
        mov     si, [es:TX_SP]
        mov     ax, [es:TX_SS]
        pop     es
        mov     [di], si
        mov     [di+2], ax
        add     di, 4
        sub     si, 128
        mov     cx, 256
        call    cr_cpy
        jmp     short .tx
.tn:    add     di, 260
.tx:    pop     bx
        inc     bx
        cmp     bx, MT_TASKS
        jb      .tk
        mov     si, mt_crbuf + CRO_VARS         ; its sum
        mov     cx, (CR_LEN - CRO_VARS) / 2
        xor     dx, dx
.s:     lodsw
        add     dx, ax
        loop    .s
        mov     [mt_crbuf+CRO_SUM], dx
        mov     si, mt_crbuf                    ; to CR_SEG
        mov     ax, CR_SEG
        mov     es, ax
        xor     di, di
        mov     cx, CR_LEN / 2
        rep     movsw
        mov     al, CRB_KEPT
        call    cr_st
        ; the BIOS's vectors back for the timer, the keys and the screen
        ; (its entry points, the PC's), the PICs: only those two IRQs on
        xor     ax, ax
        mov     es, ax
        mov     si, cr_bv
.bv:    lodsw
        or      ax, ax
        jz      .pic
        xchg    ax, bx
        lodsw
        mov     [es:bx], ax
        mov     word [es:bx+2], 0F000h
        jmp     .bv
.pic:   mov     al, 0FFh
        out     0A1h, al
        mov     al, 0FCh
        out     21h, al
        mov     cx, 4
.eoi:   mov     al, 20h
        out     0A0h, al
        out     20h, al
        loop    .eoi
        mov     al, 0Dh                         ; (NMI on again: the BIOS's
        out     70h, al                         ;  reset turned it off)
        sti
        mov     ax, 0003h
        int     10h
        mov     si, cr_t1
        call    cr_ps
        mov     al, [mt_crcause]
        call    cr_ch
        mov     si, cr_t2
        call    cr_ps
        mov     ax, [mt_ticks]
        call    cr_h4
        mov     si, cr_t3
        call    cr_ps
        mov     si, mt_crbuf + CRO_VARS         ; MT's bytes, in cr_vn's order
        mov     bx, cr_vn
        mov     cx, CR_NVB
.vn:    push    si
        mov     si, bx
        call    cr_ps
        mov     bx, si
        pop     si
        lodsb
        call    cr_h2
        loop    .vn
        mov     si, cr_t4
        call    cr_ps
        mov     ax, [mt_crbuf+CRO_WORDS+4]
        call    cr_h4
        mov     si, cr_t5
        call    cr_ps
        mov     ax, cs
        call    cr_h4
        cmp     byte [mt_crcause], 'X'
        jne     .nx
        mov     si, cr_t6                       ; 'X': where
        call    cr_ps
        mov     ax, [mt_crrg+2]
        call    cr_h4
        mov     al, ':'
        call    cr_ch
        mov     ax, [mt_crrg+0]
        call    cr_h4
        mov     si, cr_t7
        call    cr_ps
        mov     ax, [mt_crrg+8]
        call    cr_h4
        mov     al, ':'
        call    cr_ch
        mov     ax, [mt_crrg+6]
        call    cr_h4
.nx:    mov     si, cr_t8
        call    cr_ps
        mov     bx, [mt_crp]                    ; the newest 16, oldest first
        sub     bx, 16 * 16
        mov     cx, 16
.r:     and     bx, CR_N * 16 - 1
        mov     ax, [mt_crb+bx+CR_TICK]
        call    cr_h4
        call    cr_sp
        mov     al, [mt_crb+bx+CR_TAG]
        call    cr_ch
        call    cr_sp
        mov     al, [mt_crb+bx+CR_TASK]
        call    cr_h2
        call    cr_sp
        mov     ax, [mt_crb+bx+CR_CS]
        call    cr_h4
        mov     al, ':'
        call    cr_ch
        mov     ax, [mt_crb+bx+CR_IP]
        call    cr_h4
        call    cr_sp
        mov     ax, [mt_crb+bx+CR_SS]
        call    cr_h4
        mov     al, ':'
        call    cr_ch
        mov     ax, [mt_crb+bx+CR_SP]
        call    cr_h4
        call    cr_sp
        mov     ax, [mt_crb+bx+CR_AX]
        call    cr_h4
        call    cr_sp
        mov     ax, [mt_crb+bx+CR_BX]
        call    cr_h4
        call    cr_nl
        add     bx, 16
        loop    .r
        mov     si, cr_t9
        call    cr_ps
        mov     al, CRB_SHOWN
        call    cr_st
        xor     ah, ah
        int     16h
        xor     ax, ax                          ; a soft reset: the report
        mov     ds, ax                          ;  stays at CR_SEG
        mov     word [472h], 1234h
        jmp     0F000h:0E05Bh

; CX bytes from AX:SI to ES:DI (DS kept; the source may be anywhere)
cr_cpy: push    ds
        mov     ds, ax
        rep     movsb
        pop     ds
        ret
; the screen: AL, a blank, a new line, the text at CS:SI (SI past its 0),
; AL / AX in hex.  All kept but SI
cr_ch:  push    ax
        push    bx
        mov     ah, 0Eh
        xor     bx, bx
        int     10h
        pop     bx
        pop     ax
        ret
cr_sp:  push    ax
        mov     al, ' '
        call    cr_ch
        pop     ax
        ret
cr_nl:  push    ax
        mov     al, 13
        call    cr_ch
        mov     al, 10
        call    cr_ch
        pop     ax
        ret
cr_ps:  push    ax
.l:     mov     al, [cs:si]
        inc     si
        or      al, al
        jz      .x
        call    cr_ch
        jmp     .l
.x:     pop     ax
        ret
cr_h4:  xchg    al, ah
        call    cr_h2
        xchg    al, ah
cr_h2:  push    ax
        shr     al, 4
        call    .d
        pop     ax
        push    ax
        and     al, 0Fh
        call    .d
        pop     ax
        ret
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .o
        add     al, 7
.o:     jmp     cr_ch

cr_sig      db      'LODECRSH'
cr_psig     db      'LODEPREV'
; CMOS 3Dh's nibbles as CRASHRPT's characters: the stage (CRB_*), the
; window tag (KMW's CREC tags; '-' none, '?' another)
cr_stch     db      '?1234P678???????'
cr_wtags    db      '-vwePgbiGHLlsNqr'  ; (a tag not here: not written)
cr_bv       dw      08h * 4, 0FEA5h, 09h * 4, 0E987h, 10h * 4, 0F065h
            dw      16h * 4, 0E82Eh, 15h * 4, 0F859h, 1Ch * 4, 0FF53h
            dw      1Bh * 4, 0FF53h, 0
cr_t1       db      13, 10, 'Lodestone CRASHLOG caught: ', 0
cr_t2       db      ' (R a restart, X INT 06h), tick ', 0
cr_t3       db      13, 10, 0
cr_vn       db      'cur ', 0, ' front ', 0, ' down ', 0, ' ddev ', 0, ' swing ', 0
            db      ' inb ', 0, ' crit ', 0, ' in13 ', 0, 13, 10, 'vbusy ', 0, ' shd ', 0
            db      ' mw_n ', 0, ' pend ', 0, ' slice ', 0, ' want ', 0, ' hirq ', 0, ' htk ', 0
cr_t4       db      13, 10, 'UI ', 0
cr_t5       db      '  MT ', 0
cr_t6       db      '  INT 06h at ', 0
cr_t7       db      ' stack ', 0
cr_t8       db      13, 10, 'tick tg tk CS:IP      SS:SP      AX   BX/FL', 13, 10, 0
cr_t9       db      'Kept at 5000:0 through the restart: run CRASHRPT then (it writes', 13, 10
            db      'CRASH.BIN).  A photo of this screen helps too.  A key restarts.', 0
