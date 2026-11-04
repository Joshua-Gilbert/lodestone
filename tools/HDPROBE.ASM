; =====================================================================
;  HDPROBE.COM 1.5  -  the GRiDCase 1520's internal hard disk, close up
;  Build:  nasm -f bin -o HDPROBE.COM HDPROBE.ASM   (needs io.inc,
;          timing.inc and ata.inc from the same folder)
;  Run  :  HDPROBE        report on screen and to A:\HDPROBE.TXT; the
;                         drive's IDENTIFY block to A:\HDIDENT.BIN and
;                         its first sector to A:\HDSECT0.BIN
;          HDPROBE /X     the same up to IDENTIFY, then exercise the arm:
;                         20 rounds of recalibrate, seeks and a read;
;                         report to A:\HDPROBEX.TXT
;
;  The 1520's BIOS turns the hard disk on only if IDENTIFY names one of
;  the Conner drives it knows (CP3022/3024/344/3044/3042/3104); anything
;  else, or no answer, leaves CMOS 12h at 0 and INT 13h without a hard
;  disk, so DOS tools can't reach it.  This talks to the drive's own
;  registers (AT-compatible, 1F0h-1F7h) instead:
;   1. what the BIOS made of it (backplane, CMOS, BDA, INT 13h)
;   2. the registers: do they answer at all?
;   3. the status for 2 s, and the index pulse (is the disk turning?)
;   4. is it ready; the drive's self-test (its diagnostic code), and
;      whether its interrupt (IRQ 14) arrives: the BIOS waits for it
;   5. IDENTIFY: model, firmware, geometry; would the BIOS take it?
;   6. heads and sectors: recalibrate, seeks, and reads at the start,
;      middle and end of the disk
;   7. what it means
;  HDPROBE /X: after 5, exercise the arm instead (see exercise).
;  Read-only: nothing is written to the disk.  The commands sent are
;  90h (self-test), ECh (identify), 91h (geometry), 10h
;  (recalibrate: the heads to track 0), 70h (seek) and 20h (read).  IRQ 14
;  is masked meanwhile (but for the interrupt test, with a handler of our
;  own) and put back after.
; =====================================================================
cpu 286
org 100h

start:  cld
        mov     sp, stack_top
        mov     bx, (prog_end - start + 100h + 15) / 16
        mov     ah, 4Ah                 ; shrink to our image
        int     21h
        mov     ax, 0F012h              ; multitasking (MT_LIST) with other
        xor     cx, cx                  ;  tasks there?  They may be using C:,
        int     21h                     ;  and this talks to the drive itself
        jc      .one                    ;  (CF: multitasking off)
        cmp     cx, 1
        jbe     .one
        mov     dx, s_tasks
        mov     ah, 9
        int     21h
        mov     ax, 4C01h
        int     21h
.one:
        mov     si, 81h                 ; /X: exercise the arm afterwards
        mov     cl, [80h]
        xor     ch, ch
.pa:    jcxz    .pd
        lodsb
        dec     cx
        cmp     al, '/'
        jne     .pa
        jcxz    .pd
        mov     al, [si]
        or      al, 20h
        cmp     al, 'x'
        jne     .pa
        mov     byte [f_exer], 1
        mov     byte [n_lext], 'X'      ; (its own report: HDPROBEX.TXT)
        mov     word [n_lext+1], '.T'
        mov     word [n_lext+3], 'XT'
.pd:    call    log_open
        mov     dx, s_title
        call    puts
        cmp     word [fh], 0
        jne     .fok
        mov     dx, s_nofile
        call    puts
.fok:   call    pit_init
        in      al, 0A1h                ; IRQ 14 off while we work
        mov     [pic2], al
        or      al, 40h
        out     0A1h, al
        call    bios
        call    commit
        call    regs
        call    commit
        cmp     byte [f_regs], 0
        je      .end                    ; nothing there: the rest can't help
        call    watch
        call    commit
        call    selftest
        call    irqtest
        call    commit
        call    ident
        call    commit
        cmp     byte [f_exer], 0
        je      .sec
        call    exercise
        jmp     .end2
.sec:   call    sectors
.end:   call    verdict
.end2:
        mov     dx, HD + 7              ; (any interrupt the drive raised)
        in      al, dx
        mov     al, [pic2]
        out     0A1h, al
        call    pit_done
        mov     dx, s_done
        call    puts
        call    log_close
        mov     ah, 8
        int     21h
        mov     ax, 4C00h
        int     21h

; =====================================================================
; 1. what the BIOS says
; =====================================================================
bios:   mov     dx, s_bios
        call    puts
        mov     dx, s_bkpl
        call    puts
        mov     dx, 6F8h
        in      al, dx
        shr     al, 4
        mov     [bkpl], al
        call    phex8
        mov     dx, s_bk9
        cmp     byte [bkpl], 9
        je      .bk
        mov     dx, s_bk7
        cmp     byte [bkpl], 7
        je      .bk
        mov     dx, s_bk5
        cmp     byte [bkpl], 5
        je      .bk
        mov     dx, s_bkx
.bk:    call    puts
        mov     dx, s_cmos12
        call    puts
        mov     al, 12h
        call    cmos
        mov     [cmos12], al
        call    phex8
        mov     dx, s_cmos19
        call    puts
        mov     al, 19h
        call    cmos
        call    phex8
        mov     dx, s_cmos0e
        call    puts
        mov     al, 0Eh
        call    cmos
        call    phex8
        mov     dx, s_bda
        call    puts
        push    es
        push    40h
        pop     es
        mov     al, [es:75h]
        mov     ah, [es:74h]
        pop     es
        push    ax
        xor     ah, ah
        call    pdec
        mov     dx, s_bda2
        call    puts
        pop     ax
        mov     al, ah
        call    phex8
        call    crlf
        mov     dx, s_i13
        call    puts
        mov     ah, 08h
        mov     dl, 80h
        push    es
        int     13h
        pop     es
        jc      .err
        push    dx
        push    cx
        mov     dx, s_i13ok
        call    puts
        pop     cx
        push    cx
        mov     al, cl                  ; cylinders: CH + CL bits 6-7
        shl     ax, 2
        mov     al, ch
        and     ah, 3
        inc     ax
        call    pdec
        mov     dx, s_cyl
        call    puts
        pop     cx
        pop     dx
        mov     al, dh
        xor     ah, ah
        inc     ax
        call    pdec
        mov     dx, s_heads
        call    puts
        mov     al, cl
        and     ax, 3Fh
        call    pdec
        mov     dx, s_spt
        jmp     puts
.err:   mov     al, ah
        push    ax
        mov     dx, s_i13err
        call    puts
        pop     ax
        call    phex8
        mov     dx, s_i13no
        jmp     puts

; AL = CMOS register -> AL = its value
cmos:   cli
        or      al, 80h                 ; (NMI stays off while we look)
        out     70h, al
        jmp     short $+2
        in      al, 71h
        push    ax
        mov     al, 0Dh                 ; NMI back on
        out     70h, al
        jmp     short $+2
        in      al, 71h
        pop     ax
        sti
        ret

; =====================================================================
; 2. the registers
; =====================================================================
regs:   mov     dx, s_regs
        call    puts
        mov     al, 0A0h                ; drive 0, head 0
        mov     dx, HD + 6
        out     dx, al
        call    short_wait
        mov     cx, 7
        mov     dx, HD + 1
.r:     push    dx
        push    cx
        mov     ax, dx
        call    phex16
        mov     al, ' '
        call    putc
        pop     cx
        pop     dx
        in      al, dx
        cmp     dx, HD + 7
        jne     .h
        mov     [stat0], al
        call    pstat
        jmp     .s
.h:     call    phex8
.s:     push    dx
        mov     dx, s_2sp
        call    puts
        pop     dx
        inc     dx
        loop    .r
        call    crlf
        ; the echo: sector count and number hold what is written
        mov     dx, s_echo
        call    puts
        mov     bx, 0AA55h
        call    echo1
        mov     bx, 055AAh
        call    echo1
        ; does anything drive the bus at all?  A drive that is busy reads
        ; its status (BSY) at every register, so the echo fails then; but a
        ; bus nobody drives reads whatever was last on it (opcode bytes,
        ; mostly): no steady BSY
        mov     cx, 8
        xor     bx, bx                  ; BL disagreements, BH both busy
        mov     dx, HD + 7
.fl:    in      al, dx
        times 4 db 45h, 4Dh             ; (INC BP, DEC BP: what a floating bus
        mov     ah, al                  ;  reads after an IN is mostly the code
        in      al, dx                  ;  just fetched, so make it bytes with
        times 4 db 45h, 4Dh             ;  no BSY bit)
        test    al, ah
        jns     .nb2
        inc     bh
.nb2:   and     ax, 0FDFDh              ; (not the index pulse)
        cmp     al, ah
        je      .same
        inc     bl
.same:  loop    .fl
        mov     [nmis], bl
        mov     byte [f_regs], 1
        mov     dx, s_echook
        cmp     byte [echo_ok], 2
        je      .e
        mov     dx, s_echoff
        cmp     byte [ff_seen], 2
        jne     .n2
        cmp     byte [stat0], 0FFh
        je      .stop
.n2:    mov     dx, s_echobsy
        cmp     bh, 8
        je      .e                      ; busy throughout: [4] waits for it
        mov     dx, s_echofl
        mov     byte [floating], 1
.stop:  mov     byte [f_regs], 0        ; nothing sane on the bus: stop here
.e:     jmp     puts

; write BL to the sector count and BH to the sector number, read them back
echo1:  mov     al, bl
        call    phex8
        mov     al, ' '
        call    putc
        mov     al, bh
        call    phex8
        mov     dx, s_arrow
        call    puts
        mov     dx, HD + 2
        mov     al, bl
        out     dx, al
        inc     dx
        mov     al, bh
        out     dx, al
        call    short_wait
        mov     dx, HD + 2
        in      al, dx
        mov     cl, al
        call    phex8
        mov     al, ' '
        call    putc
        inc     dx
        in      al, dx
        mov     ch, al
        call    phex8
        mov     dx, s_2sp
        call    puts
        cmp     cx, bx
        jne     .n
        inc     byte [echo_ok]
.n:     cmp     cx, 0FFFFh
        jne     .x
        inc     byte [ff_seen]
.x:     ret

; =====================================================================
; 3. the status for 2 s, and the index pulse
; =====================================================================
watch:  mov     dx, s_watch
        call    puts
        mov     di, n_samp              ; (the counts, 32 bits: 100,000+
        mov     cx, 11                  ;  reads in 2 s on a 1520)
        xor     ax, ax
        rep     stosw
        mov     byte [last_idx], 0
        call    tick
        mov     bx, ax
        mov     dx, HD + 7
.l:     in      al, dx
        mov     si, n_samp
        call    inc32
        test    al, 80h
        jz      .nb
        mov     si, n_bsy
        call    inc32
        jmp     .n                      ; (the other bits mean nothing then)
.nb:    mov     si, n_rdy
        test    al, 40h
        call    inc32nz
        mov     si, n_dsc
        test    al, 10h
        call    inc32nz
        mov     si, n_err
        test    al, 01h
        call    inc32nz
        and     al, 02h                 ; index: count rising edges
        cmp     al, [last_idx]
        je      .n
        mov     [last_idx], al
        or      al, al
        jz      .n
        inc     word [n_idx]
.n:     push    ax
        call    tick
        sub     ax, bx
        cmp     ax, 36                  ; ~2 s
        pop     ax
        jb      .l
        mov     dx, s_samp
        call    puts
        mov     ax, [n_samp]
        mov     dx, [n_samp+2]
        mov     cx, 1000
        call    ldiv
        call    pdec
        mov     ax, [n_samp]            ; a hundredth of them, for the shares
        mov     dx, [n_samp+2]
        mov     cx, 100
        call    ldiv
        or      ax, ax
        jnz     .q
        inc     ax
.q:     mov     [pct_q], ax
        mov     dx, s_ksamp
        mov     si, n_bsy
        call    ppct
        mov     dx, s_srdy
        mov     si, n_rdy
        call    ppct
        cmp     al, 50                  ; ready in under half the reads,
        jae     .r50                    ;  asked nothing: busy with itself
        mov     byte [f_unready], 1
.r50:   mov     dx, s_sdsc
        mov     si, n_dsc
        call    ppct
        mov     dx, s_serr
        mov     si, n_err
        call    ppct
        call    crlf
.rdy:   mov     dx, s_idx
        call    puts
        mov     ax, [n_idx]
        call    pdec
        cmp     word [n_idx], 0
        je      .noidx
        cmp     word [n_idx], 20        ; (under 600 rpm: not a disk at speed)
        jb      .few
        mov     dx, s_idx2
        call    puts
        mov     ax, [n_idx]             ; per 2 s -> per minute
        mov     cx, 30
        mul     cx
        mov     [rpm], ax
        call    pdec
        mov     dx, s_rpm
        jmp     puts
.noidx: mov     dx, s_noidx
        jmp     puts
.few:   mov     dx, s_idxfew
        jmp     puts

; the dword at SI plus one (inc32nz: only if ZF is clear)
inc32nz:
        jz      inc32.x
inc32:  add     word [si], 1
        adc     word [si+2], 0
.x:     ret

; DX = a label to print, then the dword at SI as a share of n_samp: "n%".
; AX = the share
ppct:   call    puts
        mov     ax, [si]
        mov     dx, [si+2]
        mov     cx, [pct_q]
        call    ldiv
        call    pdec
        push    ax
        mov     al, '%'
        call    putc
        pop     ax
        ret

; =====================================================================
; 4. ready, self-test, interrupt
; =====================================================================
selftest:
        mov     dx, s_self
        call    puts
        mov     dx, s_reset
        call    puts
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     cx, 31 * 18             ; a drive has 31 s to be ready
        call    wait_rdy
        pushf
        call    elapsed
        popf
        jnc     .rok
        mov     dx, s_still
        call    puts
        call    pstat
        call    crlf
        ret
.rok:   mov     byte [f_ready], 1
        mov     dx, s_ready
        call    puts
        call    pstat
        mov     al, 01h                 ; (no reset: the self-test's code counts)
        mov     [diag1], al
        call    crlf
        ; EXECUTE DEVICE DIAGNOSTIC
        mov     dx, s_d90
        call    puts
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     al, 90h
        call    ata_cmd
        jc      .busy
        call    short_wait
        mov     cx, 10 * 18
        call    wait_nb
        pushf
        call    elapsed
        popf
        jc      .busy
        mov     dx, HD + 1
        in      al, dx
        mov     [diag2], al
        mov     byte [f_d90], 1
        jmp     pdiag
.busy:  mov     dx, s_busy
        jmp     puts

; does the drive's interrupt arrive?  A 90h with IRQ 14 (and the cascade)
; unmasked and our own INT 76h handler, for up to 2 s.  Everything put
; back after.  The BIOS waits for this interrupt on every command.
irqtest:
        cmp     byte [f_ready], 0
        je      .x
        mov     dx, s_irq
        call    puts
        mov     dx, HD + 7              ; (nothing left over)
        in      al, dx
        push    es
        xor     ax, ax
        mov     es, ax
        cli
        mov     ax, [es:76h * 4]
        mov     [old76], ax
        mov     ax, [es:76h * 4 + 2]
        mov     [old76 + 2], ax
        mov     word [es:76h * 4], irq76
        mov     [es:76h * 4 + 2], cs
        in      al, 21h
        mov     [pic1], al
        and     al, 0FBh                ; the cascade (IRQ 2) on
        out     21h, al
        in      al, 0A1h
        and     al, 0BFh                ; IRQ 14 on
        out     0A1h, al
        mov     byte [got_irq], 0
        sti
        mov     byte [r_sdh], 0A0h
        mov     al, 90h
        call    ata_cmd
        jc      .back
        call    tick
        mov     bx, ax
.w:     cmp     byte [got_irq], 0
        jne     .back
        call    tick
        sub     ax, bx
        cmp     ax, 36
        jb      .w
.back:  cli
        mov     al, [pic2]              ; IRQ 14 off again
        or      al, 40h
        out     0A1h, al
        mov     al, [pic1]
        out     21h, al
        mov     ax, [old76]
        mov     [es:76h * 4], ax
        mov     ax, [old76 + 2]
        mov     [es:76h * 4 + 2], ax
        sti
        pop     es
        mov     dx, HD + 7
        in      al, dx
        cmp     byte [got_irq], 0
        je      .none
        mov     byte [f_irq], 1
        mov     dx, s_irqok
        jmp     puts
.none:  mov     byte [f_irq], 2
        mov     dx, s_irqno
        jmp     puts
.x:     ret

irq76:  push    ax
        push    dx
        push    ds
        push    cs
        pop     ds
        mov     byte [got_irq], 1
        mov     dx, HD + 7              ; (ends the drive's request)
        in      al, dx
        mov     al, 20h
        out     0A0h, al
        out     20h, al
        pop     ds
        pop     dx
        pop     ax
        iret

; AL = the drive's diagnostic code -> " code nn: meaning" and a new line
pdiag:  push    ax
        mov     dx, s_code
        call    puts
        pop     ax
        push    ax
        call    phex8
        pop     ax
        mov     dx, s_dg01
        cmp     al, 01h
        je      .p
        mov     dx, s_dg02
        cmp     al, 02h
        je      .p
        mov     dx, s_dg03
        cmp     al, 03h
        je      .p
        mov     dx, s_dg04
        cmp     al, 04h
        je      .p
        mov     dx, s_dg05
        cmp     al, 05h
        je      .p
        mov     dx, s_dg8x
        test    al, 80h
        jnz     .p
        mov     dx, s_dgxx
.p:     jmp     puts

; =====================================================================
; 5. IDENTIFY
; =====================================================================
ident:  mov     dx, s_ident
        call    puts
        cmp     byte [f_ready], 0
        jne     .go
        mov     dx, s_skip
        jmp     puts
.go:    mov     byte [r_sdh], 0A0h
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     al, 0ECh
        call    ata_cmd
        jc      .busy
        call    wait_drq
        pushf
        call    elapsed
        popf
        jc      .busy
        push    ax
        mov     dx, s_st
        call    puts
        pop     ax
        call    pstat
        test    al, 08h
        jnz     .data
        mov     dx, HD + 1              ; refused: the error register
        in      al, dx
        call    perr
        mov     dx, s_noid
        jmp     puts
.busy:  mov     dx, s_busy
        jmp     puts
.data:  call    crlf
        mov     di, idbuf
        call    read_sector
        mov     byte [f_id], 1
        mov     dx, n_ident
        mov     si, idbuf
        call    save512
        ; the strings (byte-swapped words)
        mov     dx, s_model
        call    puts
        mov     si, idbuf + 27 * 2
        mov     cx, 20
        call    pstr
        mov     dx, s_firm
        call    puts
        mov     si, idbuf + 23 * 2
        mov     cx, 4
        call    pstr
        mov     dx, s_serial
        call    puts
        mov     si, idbuf + 10 * 2
        mov     cx, 10
        call    pstr
        call    crlf
        ; the geometry
        mov     ax, [idbuf + 1 * 2]
        mov     [cyls], ax
        mov     ax, [idbuf + 3 * 2]
        mov     [heads], ax
        mov     ax, [idbuf + 6 * 2]
        mov     [spt], ax
        mov     dx, s_geom
        call    puts
        mov     ax, [cyls]
        call    pdec
        mov     dx, s_cyl
        call    puts
        mov     ax, [heads]
        call    pdec
        mov     dx, s_heads
        call    puts
        mov     ax, [spt]
        call    pdec
        mov     dx, s_spt2
        call    puts
        mov     ax, [cyls]              ; sectors = cyl * heads * spt, and
        mul     word [heads]            ;  MB (millions of bytes) = sectors
        mov     cx, [spt]               ;  / 1953
        call    mul32
        mov     cx, 1953
        call    ldiv
        call    pdec
        mov     dx, s_mb
        call    puts
        mov     dx, s_words
        call    puts
        mov     ax, [idbuf]
        call    phex16
        mov     dx, s_w20
        call    puts
        mov     ax, [idbuf + 20 * 2]
        call    phex16
        mov     al, ' '
        call    putc
        mov     ax, [idbuf + 21 * 2]
        call    phex16
        mov     al, ' '
        call    putc
        mov     ax, [idbuf + 22 * 2]
        call    phex16
        mov     dx, s_w47
        call    puts
        mov     ax, [idbuf + 47 * 2]
        call    phex16
        mov     dx, s_w49
        call    puts
        mov     ax, [idbuf + 49 * 2]
        call    phex16
        call    crlf
        ; would the BIOS take it?  The model after its "-", spaces
        ; skipped, against the Conner models it knows
        mov     si, idbuf + 27 * 2
        mov     di, model
        mov     cx, 20
.sw:    lodsw
        xchg    al, ah
        stosw
        loop    .sw
        mov     si, model
        mov     cx, 40
.hy:    cmp     byte [si], '-'
        je      .hf
        inc     si
        loop    .hy
        jmp     .unk
.hf:    inc     si
        dec     cx
        jz      .unk
.sp:    cmp     byte [si], ' '
        jne     .cmp
        inc     si
        loop    .sp
        jmp     .unk
.cmp:   mov     bx, known
.k:     cmp     byte [bx], 0
        je      .unk
        push    si
        mov     di, bx
        inc     di                      ; (past the type byte)
.c:     mov     al, [di]
        or      al, al
        jz      .match
        cmp     al, [si]
        jne     .nm
        inc     si
        inc     di
        jmp     .c
.nm:    pop     si
.nx:    inc     bx                      ; next entry
        cmp     byte [bx], 0
        jne     .nx
        inc     bx
        jmp     .k
.match: pop     si
        mov     byte [f_known], 1
        mov     al, [bx]
        mov     [btype], al
        mov     dx, s_known
        call    puts
        lea     dx, [bx+1]
        call    putz
        mov     dx, s_known2
        call    puts
        mov     al, [btype]
        call    phex8
        mov     dx, s_known3
        jmp     puts
.unk:   mov     dx, s_unknown
        jmp     puts

; =====================================================================
; 6. heads and sectors
; =====================================================================
sectors:
        mov     dx, s_sect
        call    puts
        cmp     byte [f_id], 0
        jne     .geo
        mov     dx, s_skip2
        jmp     puts
.geo:   mov     ax, [heads]             ; a geometry we can use?
        dec     ax
        cmp     ax, 15
        ja      .badg
        cmp     word [spt], 0
        je      .badg
        cmp     word [spt], 63
        ja      .badg
        cmp     word [cyls], 0
        jne     .g2
.badg:  mov     dx, s_badg
        jmp     puts
.g2:    ; INITIALIZE DEVICE PARAMETERS, as the BIOS does
        mov     dx, s_d91
        call    puts
        mov     al, [heads]
        dec     al
        or      al, 0A0h
        mov     [r_sdh], al
        mov     al, [spt]
        mov     [r_cnt], al
        mov     al, 91h
        call    timed_cmd
        ; RECALIBRATE
        mov     dx, s_d10
        call    puts
        mov     byte [r_sdh], 0A0h
        mov     al, 10h
        call    timed_cmd
        mov     [recal_st], al
        mov     [recal_er], ah
        ; seeks: the middle, the end, and back to 0 (does the arm move?)
        mov     ax, [cyls]
        shr     ax, 1
        call    seek_one
        mov     ax, [cyls]
        dec     ax
        call    seek_one
        xor     ax, ax
        call    seek_one
        ; reads: the first sector, the middle, the last
        xor     ax, ax
        mov     [c_cyl], ax
        mov     byte [c_head], 0
        mov     byte [c_sec], 1
        mov     byte [first], 1
        call    rd_one
        mov     byte [first], 0
        mov     ax, [cyls]
        shr     ax, 1
        mov     [c_cyl], ax
        mov     al, [heads]
        shr     al, 1
        mov     [c_head], al
        mov     al, [spt]
        shr     al, 1
        inc     al
        mov     [c_sec], al
        call    rd_one
        mov     ax, [cyls]
        dec     ax
        mov     [c_cyl], ax
        mov     al, [heads]
        dec     al
        mov     [c_head], al
        mov     al, [spt]
        mov     [c_sec], al
        jmp     rd_one

; SEEK (70h) to cylinder AX, head 0, timed; n_skfail counts the failures
seek_one:
        mov     [r_cyl], ax
        push    ax
        mov     dx, s_seek
        call    puts
        pop     ax
        call    pdec
        mov     dx, s_colon
        call    puts
        mov     byte [r_sdh], 0A0h
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     al, 70h
        call    seek_cmd
        pushf
        call    elapsed
        popf
        jc      .bad
        push    ax
        mov     dx, s_st
        call    puts
        pop     ax
        call    pstat
        call    crlf
        ret
.bad:   inc     byte [n_skfail]
        cmp     al, 0FFh
        je      .busy
        mov     dx, s_nodsc
        cmp     al, 0FEh
        je      .p
        push    ax
        mov     dx, s_st
        call    puts
        pop     ax
        call    pstat
        mov     dx, HD + 1
        in      al, dx
        jmp     perr
.busy:  mov     dx, s_busy
.p:     jmp     puts

; SEEK (70h) to r_cyl: sent, then BSY clear (31 s) and seek complete (DSC,
; 10 s more: a Conner may drop BSY at once and seek on).  CF: it failed,
; AL = status (ERR), FEh no seek complete, FFh busy throughout
seek_cmd:
        call    ata_cmd
        jc      .busy
        call    short_wait
        mov     cx, 31 * 18
        call    wait_nb
        jc      .busy
        push    bx
        push    dx
        call    tick
        mov     bx, ax
        mov     dx, HD + 7
.d:     in      al, dx
        test    al, 80h
        jnz     .w
        test    al, 01h
        jnz     .err
        test    al, 10h
        jnz     .ok
.w:     push    ax
        call    tick
        sub     ax, bx
        cmp     ax, 10 * 18
        pop     ax
        jb      .d
        test    al, 80h
        mov     al, 0FEh
        jz      .err
        mov     al, 0FFh
.err:   stc
.ok:    pop     dx
        pop     bx
        ret
.busy:  mov     al, 0FFh
        stc
        ret

; read the sector at c_cyl/c_head/c_sec and say how it went
rd_one: mov     dx, s_read
        call    puts
        mov     ax, [c_cyl]
        call    pdec
        mov     dx, s_rh
        call    puts
        mov     al, [c_head]
        xor     ah, ah
        call    pdec
        mov     dx, s_rs
        call    puts
        mov     al, [c_sec]
        xor     ah, ah
        call    pdec
        mov     dx, s_colon
        call    puts
        mov     byte [r_cnt], 1
        mov     al, [c_sec]
        mov     [r_sec], al
        mov     ax, [c_cyl]
        mov     [r_cyl], ax
        mov     al, [c_head]
        or      al, 0A0h
        mov     [r_sdh], al
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     al, 20h
        call    ata_cmd
        jc      .busy
        call    wait_drq
        pushf
        call    elapsed
        popf
        jc      .busy
        test    al, 08h
        jz      .fail
        push    ax
        mov     di, secbuf
        call    read_sector
        pop     ax
        test    al, 01h                 ; (data came, but an error too?)
        jnz     .fail
        inc     byte [n_rok]
        mov     dx, s_rok
        call    puts
        cmp     byte [first], 0
        je      .x
        mov     dx, n_sect0
        mov     si, secbuf
        call    save512
        jmp     mbr
.x:     jmp     crlf
.fail:  push    ax
        mov     dx, s_st
        call    puts
        pop     ax
        call    pstat
        mov     dx, HD + 1
        in      al, dx
        test    al, 10h
        jz      .ni
        inc     byte [n_idnf]
.ni:    jmp     perr
.busy:  inc     byte [n_rbusy]
        mov     dx, s_busy
        jmp     puts

; the first sector: its last two bytes, and a partition table if 55 AA
mbr:    mov     dx, s_ends
        call    puts
        mov     al, [secbuf + 510]
        call    phex8
        mov     al, ' '
        call    putc
        mov     al, [secbuf + 511]
        call    phex8
        cmp     word [secbuf + 510], 0AA55h
        je      .pt
        mov     dx, s_nopt
        jmp     puts
.pt:    mov     dx, s_pt
        call    puts
        mov     si, secbuf + 446
        mov     cx, 4
        mov     bl, '1'
.e:     cmp     byte [si + 4], 0
        je      .nx
        mov     dx, s_ptn
        call    puts
        mov     al, bl
        call    putc
        mov     dx, s_ptt
        call    puts
        mov     al, [si + 4]
        call    phex8
        mov     dx, s_ptb
        call    puts
        mov     al, [si]
        call    phex8
        mov     dx, s_pts
        call    puts
        mov     ax, [si + 12]           ; sectors -> KB, or MB from 64 MB
        mov     dx, [si + 14]           ;  (as the geometry: 1953 a MB)
        push    cx
        push    bx
        cmp     dx, 2
        jb      .kb
        mov     cx, 1953
        call    ldiv
        call    pdec
        mov     dx, s_mb
        jmp     .pp
.kb:    shr     dx, 1
        rcr     ax, 1
        call    pdec
        mov     dx, s_kb
.pp:    call    puts
        pop     bx
        pop     cx
.nx:    add     si, 16
        inc     bl
        loop    .e
        ret

; =====================================================================
; /X: exercise the arm, as one would a sticky floppy drive.  Up to 20
; rounds of recalibrate, a seek to the last cylinder and back to 0, and a
; read of the first sector, a line a round; any key stops.  Read-only.
; =====================================================================
exercise:
        mov     dx, s_exer
        call    puts
        cmp     byte [f_id], 0
        jne     .geo
        mov     dx, s_skip2
        jmp     puts
.geo:   mov     ax, [heads]
        dec     ax
        cmp     ax, 15
        ja      .badg
        cmp     word [spt], 0
        je      .badg
        cmp     word [spt], 63
        ja      .badg
        cmp     word [cyls], 0
        jne     .g2
.badg:  mov     dx, s_badg
        jmp     puts
.g2:    mov     al, [heads]             ; the geometry first, as the BIOS
        dec     al                      ;  does
        or      al, 0A0h
        mov     [r_sdh], al
        mov     al, [spt]
        mov     [r_cnt], al
        mov     al, 91h
        call    ata_cmd
        call    short_wait
        mov     cx, 5 * 18
        call    wait_nb
.round: mov     ah, 1                   ; a key stops it
        int     16h
        jz      .go
        xor     ah, ah
        int     16h
        jmp     .sum
.go:    inc     byte [x_round]
        mov     al, [x_round]
        xor     ah, ah
        call    pdec2
        mov     al, ':'
        call    putc
        ; recalibrate
        mov     dx, s_xrecal
        call    puts
        call    t0now
        mov     byte [r_sdh], 0A0h
        mov     al, 10h
        call    ata_cmd
        jc      .rbusy
        call    short_wait
        mov     cx, 31 * 18
        call    wait_nb
        jc      .rbusy
        call    xms
        call    xres
        jc      .seek
        inc     byte [x_recok]
        jmp     .seek
.rbusy: call    xms
        call    xbusy
        ; to the last cylinder and back to 0
.seek:  mov     dx, s_xend
        call    puts
        mov     ax, [cyls]
        dec     ax
        call    xseek
        mov     dx, s_x0
        call    puts
        xor     ax, ax
        call    xseek
        ; the first sector
        mov     dx, s_xread
        call    puts
        call    t0now
        mov     byte [r_cnt], 1
        mov     byte [r_sec], 1
        mov     word [r_cyl], 0
        mov     byte [r_sdh], 0A0h
        mov     al, 20h
        call    ata_cmd
        jc      .dbusy
        call    wait_drq
        jc      .dbusy
        call    xms
        test    al, 01h
        jnz     .derr
        test    al, 08h
        jz      .derr
        mov     di, secbuf
        call    read_sector
        inc     byte [x_readok]
        mov     dx, s_xok
        call    puts
        jmp     .eol
.derr:  mov     dx, s_xnod
        test    al, 01h
        jz      .dn
        call    xres
        jmp     .eol
.dn:    call    puts
        jmp     .eol
.dbusy: call    xms
        call    xbusy
.eol:   call    crlf
        call    commit
        cmp     byte [x_round], 20
        jb      .round
.sum:   mov     dx, s_xsum
        call    puts
        mov     al, [x_round]
        xor     ah, ah
        call    pdec
        mov     dx, s_xsum2
        call    puts
        mov     al, [x_recok]
        xor     ah, ah
        call    pdec
        mov     dx, s_xsum3
        call    puts
        mov     al, [x_seekok]
        xor     ah, ah
        call    pdec
        mov     dx, s_xsum4
        call    puts
        mov     al, [x_round]
        xor     ah, ah
        shl     ax, 1
        call    pdec
        mov     dx, s_xsum5
        call    puts
        mov     al, [x_readok]
        xor     ah, ah
        call    pdec
        mov     dx, s_xsum6
        call    puts
        mov     dx, s_xbetter
        cmp     byte [x_readok], 0
        jne     .p
        mov     dx, s_xworse
.p:     jmp     puts

; a seek in the exercise: to cylinder AX, " n ms ok" or the trouble
xseek:  mov     [r_cyl], ax
        call    t0now
        mov     byte [r_sdh], 0A0h
        mov     al, 70h
        call    seek_cmd
        pushf
        call    xms
        popf
        jc      .bad
        inc     byte [x_seekok]
        mov     dx, s_xok
        jmp     puts
.bad:   cmp     al, 0FFh
        je      xbusy
        mov     dx, s_xnodsc
        cmp     al, 0FEh
        je      xbusy.p
        jmp     xres.e

; status AL after a command: " ok" (CF clear), or the error's names (CF)
xres:   test    al, 01h
        jnz     .e
        mov     dx, s_xok
        call    puts
        clc
        ret
.e:     push    ax
        mov     al, ' '
        call    putc
        mov     dx, HD + 1
        in      al, dx
        or      al, al
        jnz     .n
        mov     dx, s_xerr              ; (an error with no bit in the
        call    puts                    ;  error register)
        jmp     .x
.n:     push    bx
        push    cx
        mov     bl, al
        mov     si, err_names
        mov     bh, 80h
        call    pbits
        pop     cx
        pop     bx
.x:     pop     ax
        stc
        ret

xbusy:  mov     dx, s_xbusy
.p:     call    puts
        stc
        ret

t0now:  push    ax
        push    dx
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        pop     dx
        pop     ax
        ret

; " n ms" since t0, whole milliseconds (AX, DX kept)
xms:    push    ax
        push    bx
        push    cx
        push    dx
        mov     al, ' '
        call    putc
        call    stamp
        sub     ax, [t0]
        sbb     dx, [t0+2]
        mov     cx, 1193
        call    ldiv
        or      dx, dx
        jz      .ok
        mov     ax, 0FFFFh
.ok:    call    pdec
        mov     dx, s_xms
        call    puts
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

; =====================================================================
; 7. what it means
; =====================================================================
verdict:
        mov     dx, s_verd
        call    puts
        cmp     byte [f_regs], 0
        jne     .r
        mov     dx, s_v_none
        cmp     byte [floating], 0
        je      .n0
        mov     dx, s_v_float
.n0:    call    puts
        mov     dx, s_v_next
        jmp     puts
.r:     cmp     byte [echo_ok], 2
        je      .ec
        test    byte [stat0], 80h
        jnz     .ec
        mov     dx, s_v_odd
        call    puts
.ec:    cmp     word [n_idx], 20
        jb      .ni
        mov     dx, s_v_spin
        call    puts
        mov     ax, [rpm]
        call    pdec
        mov     dx, s_v_spin2
        call    puts
.ni:    cmp     byte [f_unready], 0
        je      .ur
        mov     dx, s_v_unready
        call    puts
.ur:    cmp     byte [f_ready], 0
        jne     .rd
        mov     dx, s_v_busy
        jmp     puts
.rd:    mov     al, [diag1]
        cmp     byte [f_d90], 0
        je      .d1
        mov     al, [diag2]             ; (the self-test's code counts)
.d1:    cmp     al, 01h
        je      .dg
        mov     dx, s_v_diag
        call    puts
.dg:    cmp     byte [f_irq], 2
        jne     .dq
        mov     dx, s_v_noirq
        call    puts
.dq:    cmp     byte [f_id], 0
        jne     .id
        mov     dx, s_v_noid
        jmp     puts
.id:    cmp     byte [f_irq], 1
        jne     .id2
        mov     dx, s_v_iface
        call    puts
.id2:    cmp     byte [f_known], 0
        jne     .kn
        mov     dx, s_v_unk
        call    puts
        jmp     .rc
.kn:    mov     dx, s_v_kn
        call    puts
        cmp     byte [cmos12], 0
        jne     .rc
        cmp     byte [f_irq], 2
        je      .rc
        mov     dx, s_v_kn0
        call    puts
.rc:    test    byte [recal_st], 01h
        jz      .rok
        mov     dx, s_v_tk0
        test    byte [recal_er], 02h
        jnz     .rp
        mov     dx, s_v_recal
.rp:    call    puts
.rok:   cmp     byte [n_rok], 3
        jne     .r2
        mov     dx, s_v_reads
        jmp     puts
.r2:    cmp     byte [n_idnf], 0
        je      .r3
        test    byte [recal_st], 01h    ; the arm can't find its way: not
        jnz     .mech                   ;  the format, the mechanics
        cmp     byte [n_skfail], 0
        je      .fmt
.mech:  mov     dx, s_v_mech
        call    puts
        jmp     .r3
.fmt:
        mov     dx, s_v_idnf
        call    puts
.r3:    cmp     byte [n_rok], 0
        je      .x
        mov     dx, s_v_some
        call    puts
.x:     ret

; =====================================================================
; the drive
; =====================================================================
; a command without data: send AL, wait up to 31 s, then " n ms, status
; ..." and the error register if ERR.  AL = status, AH = error register
timed_cmd:
        push    ax
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        pop     ax
        call    ata_cmd
        jc      .busy
        call    short_wait
        mov     cx, 31 * 18
        call    wait_nb
        pushf
        call    elapsed
        popf
        jc      .busy
        push    ax
        mov     dx, s_st
        call    puts
        pop     ax
        call    pstat
        xor     ah, ah
        test    al, 01h
        jz      .ok
        push    ax                      ; (AL = status)
        mov     dx, HD + 1
        in      al, dx
        call    perr
        mov     ah, al
        pop     dx
        mov     al, dl
        ret
.ok:    jmp     crlf
.busy:  mov     dx, s_busy
        call    puts
        mov     ax, 0181h               ; (BSY + ERR, as a failure)
        ret

; " n ms" since t0 (keeps flags' meaning to the caller; AX kept)
elapsed:
        push    ax
        push    dx
        call    stamp
        sub     ax, [t0]
        sbb     dx, [t0+2]
        push    bx
        push    cx
        mov     cx, 1193                ; PIT counts -> ms, and a tenth
        call    ldiv
        or      dx, dx
        jz      .ok
        mov     ax, 0FFFFh
.ok:    call    pdec
        mov     al, '.'
        call    putc
        mov     ax, bx
        mov     bx, 10
        mul     bx
        div     cx
        add     al, '0'
        call    putc
        pop     cx
        pop     bx
        mov     dx, s_ms
        call    puts
        pop     dx
        pop     ax
        ret

; =====================================================================
; printing
; =====================================================================
; DS:DX ASCIIZ
putz:   pusha
        mov     si, dx
.l:     lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     .l
.x:     popa
        ret

; 512 bytes at SI to the file named at DX (A:\...); quietly skipped if
; it can't be written
save512:
        pusha
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
        mov     bx, ax
        mov     dx, si
        mov     cx, 512
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     popa
        ret

%include "io.inc"
%include "timing.inc"
%include "ata.inc"

; =====================================================================
; data
; =====================================================================
s_tasks db 'HDPROBE: other tasks are running, and may be using the hard disk.',13,10
        db 'End them first, then run HDPROBE with Shift-Return in the Executive.',13,10,'$'
s_title db 'HDPROBE 1.5 - the GRiDCase 1520',39,'s internal hard disk, close up (read-only)',13,10,'$'
s_nofile db '  (the report file could not be made: screen only)',13,10,'$'
s_bios  db 13,10,'[1] WHAT THE BIOS MADE OF IT',13,10,'$'
s_bkpl  db '  Drive backplane $'
s_bk9   db ': internal 1.44 MB floppy + AT-compatible hard disk',13,10,'$'
s_bk7   db ': AT-compatible hard disk, no floppy',13,10,'$'
s_bk5   db ': AT-compatible hard disk (fixed type 17), no floppy',13,10,'$'
s_bkx   db ': not an AT-compatible hard disk backplane (this probe expects 9, 7 or 5)',13,10,'$'
s_cmos12 db '  CMOS 12h (hard disk type) = $'
s_cmos19 db '   19h = $'
s_cmos0e db '   0Eh (POST status) = $'
s_bda   db 13,10,'  BDA: hard disks $'
s_bda2  db ', last status $'
s_i13   db '  INT 13h 08h, drive 80h: $'
s_i13ok db 'the BIOS has a hard disk: $'
s_i13err db 'error $'
s_i13no db ' (the BIOS has no hard disk)',13,10,'$'
s_cyl   db ' cylinders, $'
s_heads db ' heads, $'
s_spt   db ' sectors',13,10,'$'
s_spt2  db ' sectors a track = $'
s_mb    db ' MB',13,10,'$'
s_regs  db 13,10,'[2] THE DRIVE',39,'S REGISTERS (drive 0 selected)',13,10,'  $'
s_2sp   db '  $'
s_echo  db '  Echo, sector count and number: $'
s_arrow db ' -> $'
s_echook db 13,10,'  -> the drive',39,'s registers answer',13,10,'$'
s_echoff db 13,10,'  -> nothing answers: every register reads FF (no drive on the bus)',13,10,'$'
s_echobad db 13,10,'  -> the registers don',39,'t hold what is written (a bad connection, or a fault)',13,10,'$'
s_echofl db 13,10,'  -> no drive answers: the registers don',39,'t hold what is written, and what is',13,10
        db '     read isn',39,'t a busy drive',39,'s status either.  These are leftovers on a',13,10
        db '     bus nobody drives.',13,10,'$'
s_echobsy db 13,10,'  -> the drive is busy (BSY), and a busy drive ignores writes; [4] waits',13,10
        db '     for it',13,10,'$'
s_watch db 13,10,'[3] THE STATUS FOR 2 SECONDS (read as fast as we can)',13,10,'$'
s_samp  db '  $'
s_ksamp db ' thousand reads: busy $'
s_srdy  db ', ready $'
s_sdsc  db ', seek complete $'
s_serr  db ', error $'
s_idx   db '  Index pulses seen: $'
s_idx2  db ' -> about $'
s_rpm   db ' rpm: the disk is turning',13,10,'$'
s_noidx db 13,10,'  (none: the disk may not be turning, or this drive doesn',39,'t show them)',13,10,'$'
s_idxfew db 13,10,'  (too few for a disk at speed: this drive doesn',39,'t report the index, or the',13,10
        db '  disk isn',39,'t up to speed)',13,10,'$'
s_self  db 13,10,'[4] READY, SELF-TEST, INTERRUPT',13,10,'$'
s_reset db '  Ready? (up to 31 s): $'
s_still db ', not ready after 31 s, status $'
s_ready db ', status $'
s_code  db ', code $'
s_dg01  db ': passed',13,10,'$'
s_dg02  db ': formatter device error',13,10,'$'
s_dg03  db ': sector buffer error',13,10,'$'
s_dg04  db ': ECC circuitry error',13,10,'$'
s_dg05  db ': controlling microprocessor error',13,10,'$'
s_dg8x  db ': drive 1 failed (drive 0 bits below)',13,10,'$'
s_dgxx  db ': not a code the standard knows',13,10,'$'
s_d90   db '  Self-test (90h): $'
s_irq   db '  Interrupt (IRQ 14) after another 90h: $'
s_irqok db 'it arrives',13,10,'$'
s_irqno db 'none in 2 s',13,10,'$'
s_busy  db ' busy: no answer in time',13,10,'$'
s_nodsc db ', no seek complete (DSC) in 10 s',13,10,'$'
s_ident db 13,10,'[5] IDENTIFY (ECh)',13,10,'  $'
s_skip  db 'skipped: the drive never came ready',13,10,'$'
s_st    db ', status $'
s_noid  db '  -> IDENTIFY refused (ABRT: a drive older than the command, or confused)',13,10,'$'
s_model db '  Model    $'
s_firm  db 13,10,'  Firmware $'
s_serial db '   Serial $'
s_geom  db '  Geometry $'
s_words db '  Words: 0 = $'
s_w20   db '   20-22 (buffer type, size, ECC) = $'
s_w47   db '   47 = $'
s_w49   db '   49 = $'
s_known db '  The BIOS knows $'
s_known2 db ': it would make it type $'
s_known3 db ' (saved: A:\HDIDENT.BIN)',13,10,'$'
s_unknown db '  The BIOS doesn',39,'t know this model (only Conner CP3022, CP3024, CP344, CP3044,',13,10
        db '  CP3042, CP3104): it leaves the drive off.  (saved: A:\HDIDENT.BIN)',13,10,'$'
s_sect  db 13,10,'[6] HEADS AND SECTORS (geometry from IDENTIFY)',13,10,'$'
s_skip2 db '  skipped: no IDENTIFY, so no geometry',13,10,'$'
s_badg  db '  skipped: IDENTIFY',39,'s geometry doesn',39,'t make sense',13,10,'$'
s_d91   db '  Set the geometry (91h): $'
s_d10   db '  Recalibrate, heads to track 0 (10h): $'
s_seek  db '  Seek (70h) to cylinder $'
s_exer  db 13,10,'[6] EXERCISE (HDPROBE /X): recalibrate, seek to the end and back, read the',13,10
        db '    first sector; 20 rounds, any key stops.  Times in ms.',13,10,'$'
s_xrecal db ' recal$'
s_xend  db '  seek end$'
s_x0    db '  seek 0$'
s_xread db '  read$'
s_xok   db ' ok$'
s_xerr  db 'ERR$'
s_xbusy db ' busy$'
s_xnodsc db ' noDSC$'
s_xnod  db ' no data$'
s_xms   db 'ms$'
s_xsum  db 13,10,'  $'
s_xsum2 db ' rounds: recalibrate worked $'
s_xsum3 db ' times, seeks $'
s_xsum4 db ' of $'
s_xsum5 db ', the read $'
s_xsum6 db ' times.',13,10,'$'
s_xbetter db '  It reads now: run HDPROBE again (without /X) for the whole check.',13,10,'$'
s_xworse db '  Not even one read: exercising hasn',39,'t freed it.  If the seek times above',13,10
        db '  got shorter round by round, more may help; if not, it needs opening up',13,10
        db '  (the crash stop) or another drive.',13,10,'$'
s_read  db '  Read cylinder $'
s_rh    db ' head $'
s_rs    db ' sector $'
s_colon db ': $'
s_rok   db ', ok$'
s_ends  db ', ends $'
s_nopt  db ' (no partition table)',13,10,'$'
s_pt    db ': a partition table (saved: A:\HDSECT0.BIN)',13,10,'$'
s_ptn   db '    $'
s_ptt   db ': type $'
s_ptb   db '  boot $'
s_pts   db '  $'
s_kb    db ' KB',13,10,'$'
s_ms    db ' ms$'
s_verd  db 13,10,'[7] WHAT IT MEANS',13,10,'$'
s_v_none db '  No drive answers at 1F0h: every register reads FF, as with nothing on the',13,10
        db '  bus.',13,10,'$'
s_v_float db '  No drive answers at 1F0h: nothing drives the bus (the backplane says a',13,10
        db '  hard disk belongs there, but no drive electronics are talking).',13,10,'$'
s_v_next db '  Does the drive spin up at power-on (a whine, a few clicks)?  If it does,',13,10
        db '  power reaches it but its interface is silent: the cable or connector to',13,10
        db '  the backplane, or the drive',39,'s board.  If it doesn',39,'t: no power, or a',13,10
        db '  dead drive.  Another IDE drive or a CF card on an IDE adapter in its place',13,10
        db '  would tell the 1520',39,'s side from the drive',39,'s: HDPROBE should then see it.',13,10,'$'
s_v_odd db '  The drive',39,'s registers don',39,'t hold what is written: a bad connection or a',13,10
        db '  failing drive board.',13,10,'$'
s_v_spin db '  The disk turns (about $'
s_v_spin2 db ' rpm).',13,10,'$'
s_v_busy db '  The drive',39,'s board answers but it stays busy: it may not get up to speed',13,10
        db '  (stuck heads or spindle, or not enough power).',13,10,'$'
s_v_diag db '  Its self-test reports a fault (the code above).',13,10,'$'
s_v_noirq db '  Its interrupt (IRQ 14) never arrives.  The BIOS waits for it after every',13,10
        db '  command, IDENTIFY included, so it gives up: this alone leaves CMOS 12h',13,10
        db '  at 00.  Look at the drive',39,'s interrupt line (cable, connector).',13,10,'$'
s_v_noid db '  It is ready but won',39,'t identify itself, so the BIOS can',39,'t type it.',13,10,'$'
s_v_unk db '  It identifies itself, but not as a Conner the BIOS knows: this alone',13,10
        db '  keeps INT 13h, and so every DOS tool, from seeing it.  A BIOS that takes',13,10
        db '  any drive, or a driver that talks to it directly, would.',13,10,'$'
s_v_kn  db '  The BIOS knows this model.',13,10,'$'
s_v_kn0 db '  Yet CMOS 12h is 00: at the last power-on it didn',39,'t answer IDENTIFY in time.',13,10
        db '  The BIOS asks very early, before the screen is on, and waits about 20 s;',13,10
        db '  a slow or sticky spin-up misses that.  Try Ctrl-Alt-Del with the drive',13,10
        db '  already turning, then HDPROBE again: if 12h is still 00, it isn',39,'t that.',13,10,'$'
s_v_tk0 db '  Recalibrate: track 0 not found.  The heads can',39,'t get back to track 0:',13,10
        db '  stuck heads, or the Conner crash-stop rubber gone soft.',13,10,'$'
s_v_recal db '  Recalibrate failed (the error above).',13,10,'$'
s_v_reads db '  All three test reads worked: the drive reads its own format.',13,10,'$'
s_v_idnf db '  Sector not found (IDNF): there are no sector IDs where they should be, so',13,10
        db '  the low-level format is gone there (or the geometry is wrong).',13,10,'$'
s_v_some db '  Some reads worked: the drive is partly readable.',13,10,'$'
s_v_mech db '  It can',39,'t find its way on the disk: recalibrate or seeks fail, and reads',13,10
        db '  end in sector not found, each after seconds of retrying.  That points at',13,10
        db '  the heads or the mechanics (the servo it steers by can',39,'t be read), not at',13,10
        db '  a lost low-level format.  On Conners of this age: the rubber crash stop',13,10
        db '  gone soft and gluing the arm, or heads stuck to the platter (stiction).',13,10,'$'
s_v_iface db '  The 1520',39,'s hard-disk interface works: registers, data transfers and the',13,10
        db '  interrupt all answer.',13,10,'$'
s_v_unready db '  In [3], asked nothing, it was busy or not ready most of the time: still',13,10
        db '  spinning up, or retrying its own start-up (servo) calibration.',13,10,'$'
s_done  db 13,10,'Done.  Press any key.',13,10,'$'
s_crlf  db 13,10,'$'
n_log   db 'A:\HDPROBE'
n_lext  db '.TXT',0,0
n_ident db 'A:\HDIDENT.BIN',0
n_sect0 db 'A:\HDSECT0.BIN',0
; the Conner models the BIOS takes, and the type it gives each (as
; GRiD's numbering: CMOS gets 02h, 11h or E0h)
known   db 02h, 'CP3022', 0, 02h, 'CP3024', 0, 11h, 'CP3044', 0
        db 11h, 'CP3042', 0, 11h, 'CP344', 0, 0E0h, 'CP3104', 0, 0

fh      dw 0
bufn    dw 0
pitset  db 0
pic2    db 0
bkpl    db 0
cmos12  db 0
stat0     db 0
f_regs  db 0
f_ready db 0
f_id    db 0
f_known db 0
f_irq   db 0                            ; 1 it arrived, 2 it didn't
floating db 0
f_d90   db 0
f_unready db 0
n_skfail db 0
f_exer  db 0
x_round db 0
x_recok db 0
x_seekok db 0
x_readok db 0
nmis    db 0
got_irq db 0
pic1    db 0
echo_ok db 0
ff_seen db 0
diag1   db 0
diag2   db 0
btype   db 0
first   db 0
recal_st db 0
recal_er db 0
n_rok   db 0
n_idnf  db 0
n_rbusy db 0
last_idx db 0
        align 2
n_samp  dd 0                            ; (11 words, cleared together)
n_bsy   dd 0
n_rdy   dd 0
n_dsc   dd 0
n_err   dd 0
n_idx   dw 0
pct_q   dw 0
rpm     dw 0
t0      dd 0
old76   dd 0
cyls    dw 0
heads   dw 0
spt     dw 0
c_cyl   dw 0
c_head  db 0
c_sec   db 0
        align 2
model   times 42 db 0
idbuf   times 512 db 0
secbuf  times 512 db 0
fbuf    times 512 db 0
        align 2
        times 512 db 0
stack_top:
prog_end:
