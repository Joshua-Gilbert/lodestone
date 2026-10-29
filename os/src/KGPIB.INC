; =====================================================================
;  KGPIB.INC - the GRIDGPIB driver 1.23: the one source of both the
;  Lodestone kernel's built-in driver (INT 60h) and tools/GRIDGPIB.COM, the
;  driver for GRiD MS-DOS.  GRIDGPIB.ASM includes this file with
;  GPIB_STANDALONE defined; its differences are the islands under it
;  (f_present's DH, function 0Dh, f_stats' DX, INT 0Dh hooked by irq_on,
;  the data they use), and the kernel's bytes are the same without them.
;  First made from TM5000 driver/gridgpib/GRIDGPIB.ASM 1.1's resident part,
;  every global name prefixed gp_, then edited where marked LODESTONE.
;  Same API and 'GRIDGPIB' signature at entry+2 as ever, so TM5000G,
;  CLAUDE.COM and GGTEST use it unchanged.
; =====================================================================
gp_BASE    equ 02E1h
gp_R_DIR   equ gp_BASE+0000h
gp_R_ISR1  equ gp_BASE+0400h
gp_R_ISR2  equ gp_BASE+0800h
gp_R_SPSR  equ gp_BASE+0C00h
gp_R_ADSR  equ gp_BASE+1000h
gp_R_AUXMR equ gp_BASE+1400h
gp_R_ADR0  equ gp_BASE+1800h
gp_R_ADR1  equ gp_BASE+1C00h
gp_R_CDOR  equ gp_R_DIR
gp_R_IMR1  equ gp_R_ISR1
gp_R_IMR2  equ gp_R_ISR2
gp_R_SPMR  equ gp_R_SPSR
gp_R_ADMR  equ gp_R_ADSR
gp_R_ADR   equ gp_R_ADR0
gp_ISR1_DI  equ 01h
gp_ISR1_DO  equ 02h
gp_ISR1_ERR equ 04h
gp_ISR1_END equ 10h
gp_ISR2_CO  equ 08h
gp_ISR2_SRQ equ 40h
gp_IRQVEC  equ 0Dh                 ; IRQ 5: the cartridge's E1 jumper puts the 7210's INT pin there
gp_IRQBIT  equ 20h                 ;  (its bit in the PIC's mask and in-service register)
gp_ADSR_CIC equ 80h
gp_AUX_PON  equ 00h
gp_AUX_CR   equ 02h
gp_AUX_FH   equ 03h                ; finish handshake (release RFD holdoff)
gp_AUX_SEOI equ 06h
gp_AUX_GTS  equ 10h
gp_AUX_TCA  equ 11h
gp_AUX_CIFC equ 16h
gp_AUX_CREN equ 17h
gp_AUX_SIFC equ 1Eh
gp_AUX_SREN equ 1Fh
gp_MYADDR  equ 21
gp_UNL     equ 3Fh
gp_UNT     equ 5Fh
gp_SPE     equ 18h
gp_SPD     equ 19h
gp_GTL     equ 01h
gp_SDC     equ 04h
gp_GET     equ 08h
gp_DCL     equ 14h
gp_T_CMD   equ 9                   ; ticks: command byte
gp_T_SPOLL equ 3                   ; ticks: serial poll answer
gp_T_DEF   equ 36                  ; ticks: data byte (2 s)
gp_E_TMO   equ 1
gp_E_NOL   equ 2
gp_E_CIC   equ 3
gp_E_FUNC  equ 4
gp_E_NODATA equ 5
gp_E_BUSY  equ 6


gp_entry:  jmp     short gp_handler
gp_sig     db 'GRIDGPIB'                   ; entry+2: signature for clients
gp_handler:
        cmp     byte [cs:gp_busy], 0
        je      .go
        mov     ax, gp_E_BUSY
        stc
        retf    2
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
.go:    mov     byte [cs:gp_busy], 1
        sti
        cld
        push    bx
        push    si
        push    di
        push    bp
        push    ds
        push    es
        mov     [cs:gp_c_ds], ds
        push    cs
        pop     ds
        mov     [gp_c_es], es
        mov     [gp_c_si], si
        mov     [gp_c_di], di
        mov     [gp_c_cx], cx
        mov     [gp_c_dx], dx
        mov     [gp_c_bx], bx
        mov     [gp_c_al], al
        mov     byte [gp_err], 0
        mov     bl, ah
        cmp     bl, gp_NFUNC
        jb      .ok
.bad:   mov     byte [gp_err], gp_E_FUNC     ; (also function 0Dh: the same pushes)
        mov     ax, gp_E_FUNC
        jmp     .out
.ok:    xor     bh, bh
        shl     bx, 1
        mov     bx, [gp_functab+bx]
        push    bx
        mov     bx, [gp_c_bx]              ; BL = address for everyone
        mov     cx, [gp_c_cx]
        mov     dx, [gp_c_dx]
        ret                             ; -> function, which jumps to .out
.out:   pop     es
        pop     ds
        pop     bp
        pop     di
        pop     si
        pop     bx
        cmp     byte [cs:gp_err], 1        ; CF = (err == 0) ...
        cmc                             ; ... inverted: CF = error
        mov     byte [cs:gp_busy], 0       ; (MOV keeps the flags)
        retf    2
gp_done    equ     gp_handler.out

gp_functab dw gp_f_present, gp_f_init, gp_f_write, gp_f_read, gp_f_query, gp_f_spoll
        dw gp_f_clear, gp_f_trigger, gp_f_remote, gp_f_local, gp_f_timeout, gp_f_srq
%ifdef GPIB_STANDALONE
        dw gp_f_stats, gp_f_unload, gp_f_irq    ; (0Dh: GRIDGPIB /U's)
%else
        dw gp_f_stats, gp_handler.bad, gp_f_irq ; (0Dh, the standalone's unload: the
%endif                                  ;  bad-function answer, as it is built in)
gp_NFUNC   equ ($-gp_functab)/2

; ---- function bodies: return AX (and CX/DX where documented) -------
gp_f_present:
        mov     ax, 4747h
        mov     cx, 0123h               ; LODESTONE: 1.21: IRQ, 0Eh; 1.22: GPIBLOOP's
                                        ;  fast loops; 1.23: the frame check, 02h
                                        ;  AL=3, 03h AL=2 (GRIDGPIB.COM 1.23 too:
                                        ;  it is this code; 1.20 before)
%ifdef GPIB_STANDALONE
        mov     dh, [gp_intno]          ; (the vector it was put on)
%else
        mov     dh, 60h                 ; (the only vector it is put on)
%endif
        mov     dl, gp_MYADDR
        jmp     gp_done

gp_f_init: call    gp_bus_init
        jmp     gp_fin_ax

gp_f_write:
        mov     es, [gp_c_ds]
        mov     si, [gp_c_si]
        mov     al, [gp_c_al]
        mov     [gp_eoiflag], al
        call    gp_do_write
        jmp     gp_fin_ax_cx

gp_f_read: mov     es, [gp_c_es]
        mov     di, [gp_c_di]
        mov     al, [gp_c_al]
        mov     [gp_lfstop], al
        call    gp_do_read
        cmp     byte [gp_c_al], 2       ; AL = 2: BX = the Fletcher-16 (mod
        jne     gp_fin_read             ;  256, A = 1, B = 0 to start, BH = B)
        mov     bp, sp                  ;  of every byte read
        mov     bx, [gp_fa]
        mov     [bp+10], bx             ; (the caller's BX, as pushed)
        jmp     gp_fin_read

gp_f_query:
        mov     es, [gp_c_ds]
        mov     si, [gp_c_si]
        mov     byte [gp_eoiflag], 1
        call    gp_do_write
        or      ax, ax
        jnz     gp_fin_ax_cx
        mov     cx, [gp_c_dx]           ; then a read of at most DX bytes
        jmp     gp_f_read

gp_f_spoll:
        call    gp_spoll
        jnc     .ok
        mov     ax, gp_E_TMO << 8         ; AL = 0, AH = error
        mov     [gp_err], ah
        jmp     gp_done
.ok:    xor     ah, ah
        jmp     gp_done

gp_f_clear:
        mov     al, gp_DCL
        cmp     bl, 0FFh
        je      gp_uni
        mov     al, gp_SDC
        jmp     short gp_addressed
gp_f_trigger:
        mov     al, gp_GET
        jmp     short gp_addressed
gp_f_remote:
        call    gp_ren_on
        cmp     bl, 0FFh
        je      gp_ok0
        mov     al, 0                   ; just listen-address it
        jmp     short gp_addressed
gp_f_local:
        cmp     bl, 0FFh
        jne     gp_local_one
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_CREN
        out     dx, al
        mov     byte [gp_renon], 0
gp_ok0:    xor     ax, ax
        jmp     gp_fin_ax
gp_local_one:
        mov     al, gp_GTL
        ; fall through
; UNL, LAD addr, then command AL (0 = none), UNL
gp_addressed:
        push    ax
        call    gp_ensure_ctrl
        pop     ax
        jc      gp_cmdfail
        push    ax
        mov     al, gp_UNL
        call    gp_send_cmd
        jc      .f
        mov     al, bl
        or      al, 20h
        call    gp_send_cmd
        jc      .f
        pop     ax
        or      al, al
        jz      .n
        push    ax
        call    gp_send_cmd
        jc      .f
        pop     ax
.n:     mov     al, gp_UNL
        call    gp_send_cmd
        jc      gp_cmdfail
        xor     ax, ax
        jmp     gp_fin_ax
.f:     pop     ax
        jmp     gp_cmdfail
; universal command AL (DCL)
gp_uni:    push    ax
        call    gp_ensure_ctrl
        pop     ax
        jc      gp_cmdfail
        call    gp_send_cmd
        jc      gp_cmdfail
        xor     ax, ax
        jmp     gp_fin_ax

gp_f_timeout:
        mov     ax, [gp_tdata]             ; old value in ms
        mov     dx, 55
        mul     dx
        push    ax
        mov     ax, [gp_c_bx]
        or      ax, ax
        jnz     .c
        mov     ax, gp_T_DEF*55
.c:     add     ax, 54
        jnc     .d
        mov     ax, 0FFFFh
.d:     xor     dx, dx
        mov     cx, 55
        div     cx
        cmp     ax, 2
        jae     .s
        mov     ax, 2                   ; at least 2 ticks (55..110 ms)
.s:     mov     [gp_tdata], ax
        pop     ax
        jmp     gp_done

gp_f_srq:  mov     dx, gp_R_ISR2
        in      al, dx
        or      [gp_shadow2], al
        xor     ax, ax
        test    byte [gp_shadow2], gp_ISR2_SRQ
        jz      .n
        inc     ax
        and     byte [gp_shadow2], ~gp_ISR2_SRQ
.n:     jmp     gp_done

; 0Eh (LODESTONE): SRQ on IRQ 5.  AL = 0 off, 1 on, anything else: just ask.
; -> AX = the IRQ in use (5, or 0: none), DX:CX = a word the interrupt adds 1
; to at every SRQ: a client compares it with interrupts off before a HLT, so
; it can't sleep through an SRQ (AH=0Bh's latch is ORed in as before)
gp_f_irq:
        mov     al, [gp_c_al]
        cmp     al, 1
        ja      .q
        je      .on
        cli
        call    gp_irq_mask
        sti
        jmp     short .q
.on:    call    gp_irq_on
.q:     mov     al, [gp_irq]
        xor     ah, ah
        mov     cx, gp_nsrq
        mov     dx, cs
        jmp     gp_done

gp_f_stats:
        mov     ax, [gp_recov]
        mov     cx, [gp_ntmo]
%ifdef GPIB_STANDALONE
        mov     dx, gp_res_end          ; resident bytes, the PSP's too (org 100h)
        jmp     gp_done

; 0Dh (GRIDGPIB /U): -> CX = its PSP, DX:AX = the vector it found.  IRQ 5
; off and INT 0Dh given back first; error 6 if INT 0Dh was taken after it
gp_f_unload:
        cli
        cmp     byte [gp_hooked], 0     ; (never hooked: IRQ 5 never on)
        je      .v
        push    es
        push    0
        pop     es
        cmp     word [es:gp_IRQVEC*4], gp_isr   ; INT 0Dh back as we found it
        jne     .taken                  ;  if it is still ours (else the driver
        mov     ax, cs                  ;  stays as it is, SRQ on IRQ 5)
        cmp     [es:gp_IRQVEC*4+2], ax
        jne     .taken
        call    gp_irq_mask
        mov     ax, [gp_oldirq]
        mov     [es:gp_IRQVEC*4], ax
        mov     ax, [gp_oldirq+2]
        mov     [es:gp_IRQVEC*4+2], ax
        mov     byte [gp_hooked], 0
        pop     es
.v:     sti
        mov     cx, cs                  ; (.COM: CS = its PSP)
        mov     ax, [gp_oldvec]
        mov     dx, [gp_oldvec+2]
        jmp     gp_done
.taken: pop     es
        sti
        mov     ax, gp_E_BUSY
        jmp     gp_fin_ax
%else
        mov     dx, gp_res_end - gp_entry ; LODESTONE: size of the built-in driver
        jmp     gp_done
%endif

gp_cmdfail:
        call    gp_recover
        mov     ax, gp_E_TMO
gp_fin_ax:
gp_fin_ax_cx:
gp_fin_read:
        mov     [gp_err], al
        jmp     gp_done

; =====================================================================
;  Bus operations
; =====================================================================
gp_bus_init:
        mov     byte [gp_shadow1], 0
        mov     byte [gp_shadow2], 0
        call    gp_chip_init
        call    gp_ifc_ren
        mov     dx, gp_R_ADSR
        in      al, dx
        xor     ah, ah
        test    al, gp_ADSR_CIC
        jnz     .ok
        mov     al, gp_E_CIC
        ret
.ok:    xor     al, al
        ret

gp_ifc_ren:
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_SIFC
        out     dx, al
        call    gp_wait_tick
        mov     al, gp_AUX_CIFC
        out     dx, al
gp_ren_on: push    ax
        push    dx
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_SREN
        out     dx, al
        mov     byte [gp_renon], 1
        pop     dx
        pop     ax
        ret

; write CX bytes from ES:SI to device BL.  AX = error, CX = bytes sent
gp_do_write:
        mov     [gp_count], cx
        xor     ax, ax
        mov     [gp_done_n], ax
        inc     ax                      ; A, B so the first byte's add makes
        jcxz    .f0                     ;  1, 0 (no bytes: 1, 0)
        sub     al, [es:si]
        dec     ah
.f0:    mov     [gp_fa], ax
        cmp     byte [gp_renon], 0         ; auto-remote after LOCAL ALL
        jne     .r
        call    gp_ren_on
.r:     call    gp_ensure_ctrl
        jc      .cf
        mov     al, gp_UNL
        call    gp_send_cmd
        jc      .cf
        mov     al, 40h+gp_MYADDR          ; MTA
        call    gp_send_cmd
        jc      .cf
        mov     al, bl
        or      al, 20h                 ; LAD
        call    gp_send_cmd
        jc      .cf
        call    gp_wait_co
        jc      .cf
        call    gp_do_gts
%ifndef NOFAST
        call    gp_fast_write           ; the bulk, all but the last byte
%endif
.wb:    mov     cx, [gp_count]
        cmp     cx, [gp_done_n]
        je      .sent
        mov     cx, [gp_tdata]
        call    gp_tmo_start
.wdo:   mov     ah, gp_ISR1_DO | gp_ISR1_ERR
        call    gp_isr1_test
        jz      .nodo
        test    al, gp_ISR1_ERR
        jnz     .nol
        jmp     short .put
.nodo:  call    gp_tmo_check
        jnc     .wdo
        jmp     .tmo
.put:   mov     ax, [gp_done_n]
        inc     ax
        cmp     ax, [gp_count]
        jne     .noeoi
        mov     al, [gp_eoiflag]
        cmp     al, 3                   ; (3: EOI on the check, appended)
        je      .noeoi
        test    al, 1
        jz      .noeoi
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_SEOI
        out     dx, al
.noeoi: mov     al, [es:si]
        inc     si
        mov     dx, gp_R_CDOR
        out     dx, al
        call    gp_fsum                 ; (the first from the start above)
        inc     word [gp_done_n]
        jmp     .wb
.sent:  cmp     byte [gp_eoiflag], 3    ; AL = 3: then the frame check, A and
        jne     .last                   ;  B, as two more bytes, EOI with B
        mov     ax, [gp_fa]
        mov     [gp_chk], ax
        add     word [gp_count], 2
        mov     byte [gp_eoiflag], 1
        push    ds
        pop     es
        mov     si, gp_chk
        jmp     .wb
.last:  mov     cx, [gp_tdata]             ; last byte accepted?
        call    gp_tmo_start
.wl:    mov     ah, gp_ISR1_DO | gp_ISR1_ERR
        call    gp_isr1_test
        jnz     .fin
        call    gp_tmo_check
        jnc     .wl
        jmp     .tmo
.fin:   call    gp_unaddr
        xor     ax, ax
        jmp     .x
.nol:   call    gp_unaddr
        mov     ax, gp_E_NOL
        jmp     .x
.tmo:   inc     word [gp_ntmo]
        call    gp_unaddr
        mov     ax, gp_E_TMO
        jmp     .x
.cf:    call    gp_recover
        mov     ax, gp_E_TMO
.x:     mov     cx, [gp_done_n]
        ret

; (LODESTONE: the two fast loops, as GPIBLOOP measured them fastest on the
; 1520.  Both are CPU-bound: the bus keeps up, so every clock counts, and
; on the 286 a taken jump (the prefetch queue refilled) costs ~0.6 us.  So
; a byte that is ready costs one taken jump, LOOP's, and so does a write's
; poll that misses (a read's first poll does not miss).  The counts are
; kept in registers and [gp_done_n] is settled from SI/DI at the end.  The
; pad bytes put the jump targets at the parity they were measured at
; (they are executed once a call, if at all).
; GPIBLOOP 1.4-1.6: read 70 -> 152 KB/s, write 77 -> 119.)
;
; Fast path for the bulk of a write: the next byte is fetched while the bus
; handshakes, so DO -> OUT is three instructions, and a poll that misses
; costs one taken jump (back to the count just above the poll).  Polls DO
; alone; every 64 misses it looks for ERR (no listener: out at once), and
; 256 such waits send it to the careful loop.  Leaves the last byte (it
; may need EOI) and anything unusual to the careful loop above, which picks
; up at [gp_done_n] with ES:SI.
gp_fast_write:
        mov     cx, [gp_count]
        sub     cx, [gp_done_n]
        cmp     cx, 2
        jb      .x
        dec     cx                      ; not the last byte
        push    bx
        push    di
        push    si
        push    bp
        mov     bp, cx
        mov     dx, gp_R_ISR1
        mov     bh, [gp_shadow1]
        es lodsb
        mov     ah, al
        mov     cx, [gp_fa]             ; CL = A, CH = B (the frame check)
        mov     di, 64
        xor     bl, bl                  ; 256 waits of 64 polls
        test    bh, gp_ISR1_DO
        jz      .w
        and     bh, ~gp_ISR1_DO
        jmp     short .put
        times ($ + 5 - $$) & 1 db 90h   ; .w even, .put odd
.r:     or      bh, al                  ; a miss (ERR is cleared as it is read)
        dec     di
        jz      .c
.w:     in      al, dx
        test    al, gp_ISR1_DO
        jz      .r
.put:   mov     al, ah
        mov     dh, gp_R_CDOR >> 8
        out     dx, al
        mov     dh, gp_R_ISR1 >> 8
        add     cl, al                  ; the frame check (Fletcher-16, mod 256)
        add     ch, cl
        es lodsb                        ; (the last byte, after the last)
        mov     ah, al
        mov     di, 64
        dec     bp
        jnz     .w
        jmp     short .o
.c:     mov     di, 64                  ; 64 misses: ERR?  256 times?
        test    bh, gp_ISR1_ERR
        jnz     .o                      ; (ERR: the careful loop says NOL)
        dec     bl
        jnz     .w
.o:     dec     si                      ; (the byte fetched, not sent)
        mov     [gp_shadow1], bh
        mov     [gp_fa], cx
        pop     bp
        mov     ax, si
        pop     di                      ; (SI as it came)
        sub     ax, di
        add     [gp_done_n], ax
        pop     di
        pop     bx
.x:     ret

gp_fsum:                                ; the frame check, one byte (AL)
        push    ax
        add     [gp_fa], al
        mov     al, [gp_fa]
        add     [gp_fb], al
        pop     ax
        ret

; Fast path for the bulk of a read: all but the last two bytes of room (the
; careful loop holds off the one that fills the buffer), normal handshake.
; A byte that is there costs no taken jump but LOOP's; the wait is out of
; line.  END (the chip's, or LF with REOS when stopping at LF) stops it
; with CF set and [gp_endr] 1 or 2; at the count or anything slow, CF clear
; and the careful loop goes on from [gp_done_n] with ES:DI.
gp_fast_read:
        mov     cx, [gp_count]
        sub     cx, [gp_done_n]
        sub     cx, 2
        ja      .go
        clc
        ret
.go:    push    bx
        push    si
        push    di
        mov     dx, gp_R_ISR1
        mov     bh, [gp_shadow1]
        mov     bl, [gp_fa]             ; BL = A, AH = B (the frame check)
        mov     ah, [gp_fb]
        times ($ - $$) & 1 db 90h       ; .w and .g even
.w:     in      al, dx
        or      bh, al
        test    bh, gp_ISR1_DI
        jz      .s
.g:     mov     dh, gp_R_DIR >> 8
        in      al, dx                  ; (and the talker sends the next)
        mov     dh, gp_R_ISR1 >> 8
        add     bl, al
        add     ah, bl
        stosb
        test    bh, gp_ISR1_END
        jnz     .end
        and     bh, ~gp_ISR1_DI
        loop    .w
        jmp     short .slow
.s:     mov     si, 20000               ; ~ 40 ms, then the careful loop
.s2:    in      al, dx
        or      bh, al
        test    bh, gp_ISR1_DI | gp_ISR1_END
        jnz     .e
        dec     si
        jnz     .s2
.slow:  xor     cl, cl
        jmp     short .t
.e:     test    bh, gp_ISR1_DI
        jnz     .g
        mov     al, 1                   ; END after the last byte's DI
        jmp     short .st
.end:   cmp     al, 0Ah
        mov     al, 1
        jne     .st
        test    byte [gp_lfstop], 1
        jz      .st
        inc     al                      ; 2: stopped at LF
.st:    mov     [gp_endr], al
        and     bh, ~(gp_ISR1_DI | gp_ISR1_END)
        mov     cl, 1
.t:     mov     [gp_shadow1], bh
        mov     [gp_fa], bl
        mov     [gp_fb], ah
        mov     ax, di
        pop     si                      ; (DI as it came)
        sub     ax, si
        add     [gp_done_n], ax
        shr     cl, 1                   ; CF: stopped
        pop     si
        pop     bx
        ret

; read from device BL into ES:DI, max CX.  AX = error, CX = count, DL = end
; 1.1: normal handshake for the bulk of a message (the talker sends the
; next byte while we store this one); RFD holdoff on END (+REOS when
; stopping at LF), and holdoff-on-all is switched on just before the byte
; that fills the buffer.  So when we stop - END, LF, full buffer - nothing
; is in flight and TCA is safe; the talker keeps any rest for the next call.
gp_do_read:
        mov     [gp_count], cx
        mov     word [gp_done_n], 0
        mov     word [gp_fa], 1         ; (04h: the read's own frame check)
        mov     byte [gp_endr], 0
        call    gp_ensure_ctrl
        jc      .cf
        mov     al, gp_UNL
        call    gp_send_cmd
        jc      .cf
        mov     al, 20h+gp_MYADDR          ; MLA
        call    gp_send_cmd
        jc      .cf
        mov     al, bl
        or      al, 40h                 ; TAD
        call    gp_send_cmd
        jc      .cf
        call    gp_wait_co
        jc      .cf
        call    gp_clear_in
        mov     cx, [gp_count]
        or      cx, cx
        jnz     .nz
        jmp     .full
.nz:    mov     al, 92h                 ; AUXRA: RFD holdoff on END
        test    byte [gp_lfstop], 1
        jz      .a
        or      al, 04h                 ; ... and LF (EOS) counts as END
.a:     cmp     cx, 1
        ja      .a2
        or      al, 01h                 ; 1-byte buffer: hold every byte
.a2:    mov     [gp_auxra], al
        mov     dx, gp_R_AUXMR
        out     dx, al
        call    gp_do_gts
%ifndef NOFAST
        call    gp_fast_read
        jnc     .rb
        jmp     .stop
%endif
.rb:    mov     cx, [gp_tdata]
        call    gp_tmo_start
.wdi:   mov     ah, gp_ISR1_DI
        call    gp_isr1_test
        jnz     .byte
        call    gp_tmo_check
        jnc     .wdi
        inc     word [gp_ntmo]
        mov     byte [gp_endr], 8
        cmp     word [gp_done_n], 0
        jne     .stop
        call    gp_rd_stop
        mov     ax, gp_E_NODATA
        jmp     .x
.byte:  mov     ah, al
        and     byte [gp_shadow1], ~gp_ISR1_END
        ; The byte that will fill the last buffer slot must be held, so
        ; holdoff-on-all is switched on before reading the one before it
        ; (the chip decides on holdoff when it accepts the next byte).
        mov     cx, [gp_done_n]
        add     cx, 2
        cmp     cx, [gp_count]
        jne     .rd
        test    byte [gp_auxra], 01h
        jnz     .rd
        or      byte [gp_auxra], 01h
        mov     al, [gp_auxra]
        mov     dx, gp_R_AUXMR
        out     dx, al
.rd:    mov     dx, gp_R_DIR
        in      al, dx                  ; (completes the handshake unless held)
        stosb
        call    gp_fsum
        inc     word [gp_done_n]
        cmp     al, 0Ah
        jne     .ne
        test    byte [gp_lfstop], 1
        jz      .ne
        mov     byte [gp_endr], 2
        jmp     .stop
.ne:    test    ah, gp_ISR1_END
        jz      .ne2
        mov     byte [gp_endr], 1
        jmp     .stop
.ne2:   mov     cx, [gp_done_n]
        cmp     cx, [gp_count]
        jb      .rb                     ; not held: next byte already coming
.full:  mov     byte [gp_endr], 4
.stop:  call    gp_rd_stop
        xor     ax, ax
        jmp     .x
.cf:    call    gp_recover
        mov     ax, gp_E_TMO
.x:     mov     cx, [gp_done_n]
        mov     dl, [gp_endr]
        ret

; end of a read: take control (safe - RFD held), release, normal mode
gp_rd_stop:
        call    gp_cmd_begin
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_FH
        out     dx, al
        mov     al, 90h
        out     dx, al
gp_unaddr: call    gp_cmd_begin
        mov     al, gp_UNT
        call    gp_send_cmd
        jc      .r
        mov     al, gp_UNL
        call    gp_send_cmd
        jnc     .x
.r:     call    gp_recover
.x:     ret

; serial poll address BL -> AL = status, CF=1 if nobody answered
gp_spoll:  call    gp_ensure_ctrl
        jc      .fail
        mov     dx, gp_R_AUXMR
        mov     al, 91h                 ; RFD holdoff on all data
        out     dx, al
        mov     al, gp_UNL
        call    gp_send_cmd
        jc      .fail
        mov     al, 20h+gp_MYADDR
        call    gp_send_cmd
        jc      .fail
        mov     al, bl
        or      al, 40h
        call    gp_send_cmd
        jc      .fail
        mov     al, gp_SPE
        call    gp_send_cmd
        jc      .fail
        call    gp_wait_co
        jc      .fail
        call    gp_clear_in
        call    gp_do_gts
        mov     cx, gp_T_SPOLL
        call    gp_tmo_start
.w:     mov     ah, gp_ISR1_DI
        call    gp_isr1_test
        jnz     .got
        call    gp_tmo_check
        jnc     .w
        inc     word [gp_ntmo]
        call    gp_spoll_end
        stc
        ret
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
.got:   mov     dx, gp_R_DIR
        in      al, dx                  ; status byte (handshake held)
        push    ax
        call    gp_spoll_end
        pop     ax
        clc
        ret
.fail:  call    gp_recover
        stc
        ret

gp_spoll_end:
        call    gp_cmd_begin
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_FH
        out     dx, al
        mov     al, 90h
        out     dx, al
        call    gp_wait_co
        jnc     .ok
        call    gp_recover
.ok:    mov     al, gp_SPD
        call    gp_send_cmd
        mov     al, gp_UNT
        call    gp_send_cmd
        ret

; =====================================================================
;  uPD7210 primitives (from GPIBSCAN 1.5 / GPIBTEST 1.0)
; =====================================================================
gp_chip_init:
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_CR
        out     dx, al
        mov     al, 28h                 ; ICR: 8 MHz
        out     dx, al
        xor     al, al
        mov     dx, gp_R_IMR1
        out     dx, al
        mov     dx, gp_R_IMR2
        mov     al, [gp_imr2]           ; LODESTONE: SRQI on while IRQ 5 is (a
        out     dx, al                  ;  reset clears IMR2)
        xor     al, al
        mov     dx, gp_R_SPMR
        out     dx, al
        mov     dx, gp_R_ADMR
        mov     al, 31h
        out     dx, al
        mov     dx, gp_R_ADR
        mov     al, gp_MYADDR
        out     dx, al
        mov     al, 0E0h
        out     dx, al
        mov     dx, gp_R_ADR1
        mov     al, 0Ah                 ; EOS = LF
        out     dx, al
        mov     dx, gp_R_AUXMR
        mov     al, 80h
        out     dx, al
        mov     al, 0A0h
        out     dx, al
        mov     al, gp_AUX_PON
        out     dx, al
        ret

gp_wait_tick:
        push    ax
        push    bx
        call    gp_tick
        mov     bx, ax
.w:     call    gp_tick
        cmp     ax, bx
        je      .w
        pop     bx
        pop     ax
        ret

gp_tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

gp_tmo_start:
        push    ax
        call    gp_tick
        mov     [gp_t_start], ax
        mov     [gp_t_len], cx
        pop     ax
        ret

gp_tmo_check:
        push    ax
        call    gp_tick
        sub     ax, [gp_t_start]
        cmp     ax, [gp_t_len]
        pop     ax
        cmc
        ret

gp_cmd_begin:
        push    ax
        push    dx
        mov     dx, gp_R_ADSR
        in      al, dx
        test    al, 40h
        jz      .x
        and     byte [gp_shadow2], ~gp_ISR2_CO
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_TCA
        out     dx, al
.x:     pop     dx
        pop     ax
        ret

gp_do_gts: push    ax
        push    dx
        and     byte [gp_shadow2], ~gp_ISR2_CO
        mov     dx, gp_R_AUXMR
        mov     al, gp_AUX_GTS
        out     dx, al
        pop     dx
        pop     ax
        ret

gp_send_cmd:
        call    gp_wait_co
        jc      .x
        push    dx
        and     byte [gp_shadow2], ~gp_ISR2_CO
        mov     dx, gp_R_CDOR
        out     dx, al
        pop     dx
        clc
.x:     ret

gp_ensure_ctrl:
        push    ax
        push    dx
        call    gp_cmd_begin
        call    gp_wait_co
        jnc     .ok
        call    gp_recover
        call    gp_wait_co
.ok:    pop     dx
        pop     ax
        ret

        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
gp_clear_in:
        push    ax
        push    dx
        mov     dx, gp_R_ISR1
        in      al, dx
        in      al, dx
        mov     byte [gp_shadow1], 0
        mov     dx, gp_R_DIR
        in      al, dx
        pop     dx
        pop     ax
        ret

gp_recover:
        push    ax
        push    dx
        inc     word [gp_recov]
        mov     byte [gp_shadow2], 0
        mov     byte [gp_shadow1], 0
        call    gp_chip_init
        call    gp_ifc_ren
        mov     byte [gp_shadow1], 0
        call    gp_wait_co
        pop     dx
        pop     ax
        ret

gp_isr1_test:
        push    dx
        mov     dx, gp_R_ISR1
        cli
        in      al, dx
        test    al, 03h
        jz      .one
        push    ax
        in      al, dx
        pop     dx
        or      al, dl
        mov     dx, gp_R_ISR1
.one:   or      al, [gp_shadow1]
        sti
        test    al, ah
        jz      .none
        push    ax
        not     ah
        and     al, ah
        mov     [gp_shadow1], al
        pop     ax
        or      ah, 0FFh                ; ZF=0
        pop     dx
        ret
.none:  mov     [gp_shadow1], al
        cmp     al, al                  ; ZF=1
        pop     dx
        ret

gp_wait_co:
        push    ax
        push    cx
        push    dx
        mov     cx, gp_T_CMD
        call    gp_tmo_start
        mov     dx, gp_R_ISR2
.w:     in      al, dx
        or      [gp_shadow2], al
        test    byte [gp_shadow2], gp_ISR2_CO
        jnz     .ok
        call    gp_tmo_check
        jnc     .w
        stc
        jmp     .x
.ok:    clc
.x:     pop     dx
        pop     cx
        pop     ax
        ret

        times ($ - $$) & 1 db 90h       ; (hot: even)
; =====================================================================
;  LODESTONE: SRQ on IRQ 5 (INT 0Dh).  The 7210 interrupts on SRQ only
;  (IMR2 SRQI).  GPIBIRQ 1.0 on the 1520: one IRQ 5 an SRQ, at once, and it
;  wakes a HLT; SRQI latches on SRQ's edge and clears on read, so a held SRQ
;  doesn't interrupt again.  The handler ORs ISR2 into the shadow, as every
;  polled read of ISR2 does (AH=0Bh sees it), and counts the interrupt.
; =====================================================================
gp_isr:    push    ax
        mov     al, 0Bh                 ; OCW3: is IRQ 5 in service?  (In real
        out     20h, al                 ;  mode the 286 also raises INT 0Dh for
        in      al, 20h                 ;  a word at offset FFFFh: that goes on
        mov     ah, al                  ;  to the vector we found)
        mov     al, 0Ah                 ; (and port 20h reads the IRR again)
        out     20h, al
        test    ah, gp_IRQBIT
        jz      .not
        push    dx
        push    ds
        push    cs
        pop     ds
        mov     dx, gp_R_ISR2
        in      al, dx
        or      [gp_shadow2], al
        inc     word [gp_nsrq]
        push    es                      ; a line that keeps firing (no jumper,
        xor     ax, ax                  ;  a floating line): IRQ 5 off after 32
        mov     es, ax                  ;  in one tick
        mov     ax, [es:46Ch]
        pop     es
        cmp     ax, [gp_irqt]
        je      .same
        mov     [gp_irqt], ax
        mov     byte [gp_irqn], 0
.same:  inc     byte [gp_irqn]
        cmp     byte [gp_irqn], 32
        jb      .e
        call    gp_irq_mask
.e:     mov     al, 20h                 ; EOI  (KMT.INC: MULTITASK=1 makes
        out     20h, al                 ;  these 5 bytes, to POP DS, a far
                                        ;  jump to mt_srqi: a task woken)
        pop     ds
        pop     dx
        pop     ax
        iret
.not:   pop     ax
        jmp     far [cs:gp_oldirq]

; IRQ 5 on (the vector is ours from gpib_init): SRQI in IMR2, IRQ 5
; unmasked.  An SRQI already latched goes into the shadow first, so it
; doesn't fire at once.
gp_irq_on:
        cmp     byte [gp_irq], 0
        jne     .x
        push    ax
        push    dx
%ifdef GPIB_STANDALONE
        push    es                      ; INT 0Dh made ours the first time
        push    0
        pop     es
        cli
        cmp     byte [gp_hooked], 0
        jne     .h
        mov     byte [gp_hooked], 1
        mov     ax, [es:gp_IRQVEC*4]
        mov     [gp_oldirq], ax
        mov     ax, [es:gp_IRQVEC*4+2]
        mov     [gp_oldirq+2], ax
        mov     word [es:gp_IRQVEC*4], gp_isr
        mov     [es:gp_IRQVEC*4+2], cs
.h:
%else
        cli
%endif
        mov     byte [gp_irq], 5
        mov     byte [gp_imr2], gp_ISR2_SRQ
        mov     byte [gp_irqn], 0
        mov     dx, gp_R_ISR2
        in      al, dx
        or      [gp_shadow2], al
        mov     al, gp_ISR2_SRQ
        out     dx, al                  ; (IMR2)
        in      al, 21h
        and     al, ~gp_IRQBIT
        out     21h, al
        sti
%ifdef GPIB_STANDALONE
        pop     es
%endif
        pop     dx
        pop     ax
.x:     ret

; IRQ 5 off (interrupts off): masked at the PIC, SRQI out of IMR2.  The
; vector stays ours: IRQ 5 doesn't come masked, and the exception goes on.
gp_irq_mask:
        push    ax
        push    dx
        mov     byte [gp_irq], 0
        mov     byte [gp_imr2], 0
        mov     dx, gp_R_IMR2
        xor     al, al
        out     dx, al
        in      al, 21h
        or      al, gp_IRQBIT
        out     21h, al
        pop     dx
        pop     ax
        ret

; ---- resident data ----------------------------------------------------
gp_busy    db 0
gp_err     db 0
gp_shadow1 db 0
gp_shadow2 db 0
gp_eoiflag db 1
gp_lfstop  db 1
gp_endr    db 0
gp_auxra   db 0
gp_renon   db 0
gp_c_al    db 0
gp_irq     db 0                     ; LODESTONE: 5 while SRQ comes on IRQ 5
gp_imr2    db 0                     ;  IMR2 for gp_chip_init (SRQI, or 0)
gp_irqn    db 0                     ;  interrupts in tick gp_irqt
gp_irqt    dw 0
gp_nsrq    dw 0                     ;  +1 every interrupt (AH=0Eh's DX:CX)
gp_oldirq  dw 0, 0                  ;  INT 0Dh as we found it
%ifdef GPIB_STANDALONE
gp_intno   db 0                     ; GRIDGPIB.COM: the vector it is on,
gp_hooked  db 0                     ;  INT 0Dh ours (irq_on's first time)
gp_oldvec  dw 0, 0                  ;  the vector as it found it
%endif
gp_recov   dw 0
gp_ntmo    dw 0
gp_tdata   dw gp_T_DEF
gp_t_start dw 0
gp_t_len   dw 0
gp_count   dw 0
gp_done_n  dw 0
gp_c_ds    dw 0
gp_c_es    dw 0
gp_c_si    dw 0
gp_c_di    dw 0
gp_c_cx    dw 0
gp_c_dx    dw 0
gp_c_bx    dw 0
gp_fa      db 1                         ; the frame check's A and B (a word:
gp_fb      db 0                         ;  gp_fa first)
gp_chk     dw 0                         ; (02h AL=3: the check, as sent)
gp_res_end:
