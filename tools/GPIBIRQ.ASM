; =====================================================================
;  GPIBIRQ.COM 1.0 - does the GPIB cartridge's interrupt reach the 286?
;  Build:  nasm -f bin -o GPIBIRQ.COM GPIBIRQ.ASM
;  Usage:  GPIBIRQ [a]      a = the bridge's address (default 7)
;
;  The cartridge's E1 jumper puts the 7210's INT pin on IRQ 5 (INT 0Dh).
;  The test lets the 7210 interrupt on SRQ only (IMR2 bit 6, SRQI) and
;  makes the Pi raise SRQ: it sends the bridge a GLP NAK frame, gridlink
;  answers at once (its last answer again), and the bridge raises SRQ
;  when that answer is in (auto service request mode).  So gridlink must
;  be running as usual, and CLAUDE must NOT be (quit it first).
;
;    0. IRQ 5 before we start: its vector, the PIC's mask, and whether
;       anything interrupts on it while the 7210's interrupts are off.
;    1. Polled: ISR2 read in a loop until SRQI.  The baseline: how long
;       the Pi takes to answer, from the end of our frame to SRQ.
;    2. Interrupt, busy loop: the same, the 7210's INT on IRQ 5 sets a
;       flag.  About the same times as 1 = the interrupt comes at once.
;    3. Interrupt, HLT: the CPU halted until an interrupt, as CLAUDE's
;       idle loop.  "woke 1" = IRQ 5 itself woke it (not the timer).
;  Each round ends with a serial poll (60h expected: RQS + READY) and the
;  read of the answer.  If 2 gets no interrupt at all, 2 is tried again
;  with the 7210's INT pin inverted (AUXRB INV).
;
;  Times in PIT counts (channel 0 in mode 2 while it runs, 0.1 ms shown).
;  Chip-level like GPIBXFER; at the end GRIDGPIB, if loaded, sets the chip up
;  again (INT 60h AH=01h: rearm.inc).
;  Appends what it prints to GPIBIRQ.TXT.
; =====================================================================
cpu 286
org 100h

%include "direct_equ.inc"

ROUNDS  equ 10
RXMAX   equ 4200                ; the biggest GLP answer is 4104 bytes
AUXRA_HOLDEND equ 82h           ; RFD holdoff on END
IMR2_SRQI equ 40h
ISR2_SRQI equ 40h
IRQVEC  equ 0Dh                 ; IRQ 5
IRQBIT  equ 20h                 ; its bit in the PIC's mask (port 21h)
T_WAIT  equ 20                  ; ~1.1 s for the SRQ

start:  cld
        mov     byte [dev], 7
        mov     si, 81h
.sp:    lodsb
        cmp     al, ' '
        je      .sp
        sub     al, '0'
        cmp     al, 9
        ja      .go
        mov     ah, al
        lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .one
        xchg    al, ah
        mov     bl, 10
        mul     bl
        add     al, ah
        jmp     short .set
.one:   mov     al, ah
.set:   cmp     al, 30
        ja      .go
        mov     [dev], al
.go:    mov     dx, s_title
        call    out_str
        mov     al, [dev]
        call    out_num
        call    out_crlf

        ; ---- 0. IRQ 5 as we find it -------------------------------------
        mov     ax, 3500h + IRQVEC
        int     21h
        mov     [oldvec], bx
        mov     [oldvec+2], es
        push    ds
        pop     es
        in      al, 21h
        mov     [oldmask], al
        mov     dx, s_vec
        call    out_str
        mov     ax, [oldvec+2]
        call    out_hex16
        mov     al, ':'
        call    out_chr
        mov     ax, [oldvec]
        call    out_hex16
        mov     dx, s_mask
        call    out_str
        mov     al, [oldmask]
        call    out_hex
        mov     dx, s_masked
        test    byte [oldmask], IRQBIT
        jnz     .m
        mov     dx, s_unmasked
.m:     call    out_str

        call    pit_init
        call    d_recover

        ; ---- 1. polled --------------------------------------------------
        mov     dx, s_p1
        call    out_str
        mov     byte [mode], 0
        call    rounds

        ; ---- 2. interrupt, busy loop ------------------------------------
        mov     dx, R_IMR2
        xor     al, al
        out     dx, al
        mov     dx, irq5
        mov     ax, 2500h + IRQVEC
        int     21h
        mov     byte [hooked], 1
        cli
        in      al, 21h
        and     al, ~IRQBIT
        out     21h, al
        sti
        mov     word [nirq], 0
        mov     cx, 3
        call    wait_ticks
        mov     dx, s_quiet
        call    out_str
        mov     ax, [nirq]
        call    out_dec
        call    out_crlf
        mov     dx, R_ISR2              ; SRQI on, but no SRQ yet
        in      al, dx
        and     al, ~ISR2_SRQI
        or      [shadow2], al
        mov     word [nirq], 0
        mov     dx, R_IMR2
        mov     al, IMR2_SRQI
        out     dx, al
        mov     cx, 3
        call    wait_ticks
        mov     dx, R_IMR2
        xor     al, al
        out     dx, al
        mov     dx, s_quiet2
        call    out_str
        mov     ax, [nirq]
        call    out_dec
        call    out_crlf

        mov     dx, s_p2
        call    out_str
        mov     word [nirq], 0
        mov     word [nsrq], 0
        mov     byte [mode], 1
        call    rounds
        call    irq_counts
        cmp     word [nirq], 0
        jne     .p3
        mov     dx, s_p2i               ; nothing: the pin the other way up
        call    out_str
        mov     dx, R_AUXMR
        mov     al, 0A8h                ; AUXRB: INV
        out     dx, al
        mov     cx, 2
        call    wait_ticks
        mov     word [nirq], 0
        mov     word [nsrq], 0
        call    rounds
        call    irq_counts
        mov     dx, R_AUXMR
        mov     al, 0A0h
        out     dx, al

        ; ---- 3. interrupt, HLT ------------------------------------------
.p3:    mov     dx, s_p3
        call    out_str
        mov     word [nirq], 0
        mov     word [nsrq], 0
        mov     byte [mode], 2
        call    rounds
        call    irq_counts
        mov     dx, s_wakes
        call    out_str
        mov     si, wk
        mov     cx, ROUNDS
.wl:    lodsw
        call    out_dec
        mov     al, ' '
        call    out_chr
        loop    .wl
        call    out_crlf

        call    cleanup
        mov     dx, s_done
        call    out_str
        call    d_rearm                 ; (X55: the driver's IMR2, IFC, REN)
        call    save_log
        mov     ax, 4C00h
        int     21h

; IRQ 5 off again, its old vector, the PIT and the bus as they were
cleanup:
        mov     dx, R_IMR2
        xor     al, al
        out     dx, al
        cmp     byte [hooked], 0
        je      .p
        cli
        in      al, 21h
        and     al, ~IRQBIT
        mov     ah, [oldmask]
        and     ah, IRQBIT
        or      al, ah
        out     21h, al
        sti
        push    ds
        lds     dx, [oldvec]
        mov     ax, 2500h + IRQVEC
        int     21h
        pop     ds
        mov     byte [hooked], 0
.p:     call    pit_done
        call    d_recover
        ret

; ---- the rounds of one part: mode 0 polled, 1 IRQ + busy loop, 2 IRQ + HLT
rounds: mov     word [ntmo], 0
        mov     word [nwf], 0
        mov     word [nok], 0
        mov     word [lastgot], 0
        xor     bx, bx
.r:     push    bx
        call    round
        pop     bx
        mov     [lats+bx], ax
        mov     ax, [wakes]
        mov     [wk+bx], ax
        mov     al, [st]
        shr     bx, 1
        mov     [sts+bx], al
        shl     bx, 1
        add     bx, 2
        cmp     bx, 2 * ROUNDS
        jb      .r
        ; report: min / median / max of the ones that came
        mov     si, lats
        mov     di, srt
        mov     cx, ROUNDS
        rep     movsw
        call    sort
        mov     dx, s_srq
        call    out_str
        mov     ax, [srt]
        call    out_tenths
        mov     dx, s_med
        call    out_str
        mov     ax, [srt + ROUNDS]      ; (the 6th of 10)
        call    out_tenths
        mov     dx, s_max
        call    out_str
        mov     ax, [srt + 2 * ROUNDS - 2]
        call    out_tenths
        mov     dx, s_msx
        call    out_str
        mov     dx, s_stat
        call    out_str
        mov     si, sts
        mov     cx, ROUNDS
.s:     lodsb
        call    out_hex
        mov     al, ' '
        call    out_chr
        loop    .s
        mov     dx, s_ans
        call    out_str
        mov     ax, [nok]
        call    out_dec
        mov     dx, s_ans2
        call    out_str
        mov     ax, [lastgot]
        call    out_dec
        mov     dx, s_bytes
        call    out_str
        cmp     word [nwf], 0
        je      .x
        mov     dx, s_wfail
        call    out_str
        mov     ax, [nwf]
        call    out_dec
        call    out_crlf
.x:     ret

irq_counts:
        mov     dx, s_irqs
        call    out_str
        mov     ax, [nirq]
        call    out_dec
        mov     dx, s_srqs
        call    out_str
        mov     ax, [nsrq]
        call    out_dec
        mov     dx, s_isr2
        call    out_str
        mov     al, [isr2a]
        call    out_hex
        mov     dx, s_then
        call    out_str
        mov     al, [isr2b]
        call    out_hex
        mov     dx, s_isr2e
        call    out_str
        cmp     byte [storm], 0
        je      .x
        mov     dx, s_storm
        call    out_str
.x:     ret

; one round -> AX = 0.1 ms from the end of our frame to SRQ (0FFFFh: none)
round:  mov     byte [st], 0
        mov     word [wakes], 0
        mov     dx, R_ISR2              ; forget an old SRQI
        in      al, dx
        and     al, ~ISR2_SRQI
        or      [shadow2], al
        and     byte [shadow2], ~ISR2_SRQI
        mov     byte [irqflag], 0
        cmp     byte [mode], 0
        je      .s
        mov     dx, R_IMR2              ; arm (the handler disarms)
        mov     al, IMR2_SRQI
        out     dx, al
.s:     mov     si, nakframe
        mov     cx, 8
        call    gpib_write
        jnc     .sent
        inc     word [nwf]
        call    d_recover
        mov     ax, 0FFFFh
        jmp     .fin
.sent:  call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     cx, T_WAIT
        call    d_tmo_start
        cmp     byte [mode], 1
        je      .spin
        ja      .hlt
.poll:  mov     dx, R_ISR2
        in      al, dx
        or      [shadow2], al
        test    byte [shadow2], ISR2_SRQI
        jnz     .got
        call    d_tmo_check
        jnc     .poll
        jmp     short .tmo
.spin:  cmp     byte [irqflag], 0
        jne     .got
        call    d_tmo_check
        jnc     .spin
        jmp     short .tmo
.hlt:   cli                             ; (an interrupt between the look and
        cmp     byte [irqflag], 0       ;  the HLT would leave it to the timer)
        jne     .goti
        sti                             ; (STI's shadow covers the HLT)
        hlt
        inc     word [wakes]
        call    d_tmo_check
        jnc     .hlt
        jmp     short .tmo
.goti:  sti
        jmp     short .got
.tmo:   inc     word [ntmo]
        mov     ax, 0FFFFh
        jmp     short .fin
.got:   call    stamp
        sub     ax, [t0]
        sbb     dx, [t0+2]
        mov     cx, 119                 ; PIT counts -> 0.1 ms (1193.18 a ms)
        call    ldiv
        or      dx, dx
        jz      .fin
        mov     ax, 0FFFEh
.fin:   push    ax
        mov     dx, R_IMR2              ; disarm
        xor     al, al
        out     dx, al
        call    finish
        and     byte [shadow2], ~ISR2_SRQI
        pop     ax
        ret

; the serial poll, and the answer if the bridge has one (20h)
finish: mov     bl, [dev]
        call    d_spoll
        jc      .x
        mov     [st], al
        test    al, 20h
        jz      .x
        call    rd_reply
        jc      .x
        mov     [lastgot], ax
        cmp     byte [rxbuf], 47h       ; a GLP frame
        jne     .x
        inc     word [nok]
.x:     ret

; ---- SI = bytes, CX = count: to [dev], EOI with the last; CF on failure
gpib_write:
        call    d_cmd_begin
        mov     al, UNL
        call    d_send_cmd
        jc      .f
        mov     al, 40h + MYADDR
        call    d_send_cmd
        jc      .f
        mov     al, [dev]
        or      al, 20h
        call    d_send_cmd
        jc      .f
        call    d_wait_co
        jc      .f
        call    d_do_gts
.b:     push    cx
        mov     cx, T_DATA
        call    d_tmo_start
        pop     cx
.w:     mov     ah, ISR1_DO | ISR1_ERR
        call    d_isr1_test
        jnz     .g
        call    d_tmo_check
        jnc     .w
        jmp     short .f
.g:     test    al, ISR1_ERR
        jnz     .f
        cmp     cx, 1
        jne     .n
        mov     dx, R_AUXMR
        mov     al, AUX_SEOI
        out     dx, al
.n:     lodsb
        mov     dx, R_CDOR
        out     dx, al
        loop    .b
        mov     cx, T_DATA              ; the last byte gone
        call    d_tmo_start
.l:     mov     ah, ISR1_DO
        call    d_isr1_test
        jnz     .ok
        call    d_tmo_check
        jnc     .l
.f:     stc
        ret
.ok:    clc
        ret

; ---- read one message from [dev] into rxbuf -> AX = bytes; CF on failure
rd_reply:
        call    d_cmd_begin
        mov     al, UNL
        call    d_send_cmd
        jc      .f0
        mov     al, 20h + MYADDR
        call    d_send_cmd
        jc      .f0
        mov     al, [dev]
        or      al, 40h
        call    d_send_cmd
        jc      .f0
        call    d_wait_co
        jc      .f0
        call    d_clear_in
        mov     dx, R_AUXMR
        mov     al, AUXRA_HOLDEND
        out     dx, al
        call    d_do_gts
        mov     di, rxbuf
        mov     cx, T_DATA
        call    d_tmo_start
        mov     cx, RXMAX
        mov     dx, R_ISR1
        xor     ah, ah
.pb:    xor     bx, bx
.pw:    in      al, dx
        or      ah, al
        test    ah, ISR1_DI
        jnz     .pg
        test    ah, ISR1_END            ; END latched after the last DI
        jnz     .done
        dec     bx
        jnz     .pw
        call    d_tmo_check
        jnc     .pb
        jmp     short .f
.pg:    mov     dx, R_DIR
        in      al, dx
        stosb
        mov     dx, R_ISR1
        and     ah, ~ISR1_DI
        in      al, dx                  ; a second look, for END (a DI here
        or      ah, al                  ;  is the next byte's: END is its)
        test    ah, ISR1_END
        jz      .more
        test    ah, ISR1_DI
        jz      .done
.more:  loop    .pb
.f:     call    rd_end
        stc
        ret
.f0:    mov     di, rxbuf
        jmp     short .f
.done:  mov     byte [shadow1], 0
        call    rd_end
        clc
        ret

rd_end: pushf
        call    d_rd_end
        mov     al, UNT
        call    d_send_cmd
        mov     al, UNL
        call    d_send_cmd
        mov     ax, di
        sub     ax, rxbuf
        popf
        ret

; ---- IRQ 5 ---------------------------------------------------------------
irq5:   push    ax
        push    dx
        push    ds
        push    cs
        pop     ds
        inc     word [nirq]
        mov     dx, R_ISR2
        in      al, dx
        mov     [isr2a], al
        in      al, dx                  ; a second look: SRQI again = it
        mov     [isr2b], al             ;  follows the line, not its edge
        or      al, [isr2a]
        or      [shadow2], al           ; (CO for the polled routines)
        test    byte [shadow2], ISR2_SRQI
        jz      .n
        and     byte [shadow2], ~ISR2_SRQI
        inc     word [nsrq]
        mov     byte [irqflag], 1
.n:     mov     dx, R_IMR2              ; once per arming
        xor     al, al
        out     dx, al
        cmp     word [nirq], 1000       ; a stuck line: IRQ 5 off
        jb      .e
        in      al, 21h
        or      al, IRQBIT
        out     21h, al
        mov     byte [storm], 1
.e:     mov     al, 20h                 ; EOI
        out     20h, al
        pop     ds
        pop     dx
        pop     ax
        iret

; ---- time ----------------------------------------------------------------
pit_init:
        mov     byte [pitset], 1
        mov     al, 34h                 ; channel 0, mode 2, full count
        jmp     short pitw
pit_done:
        cmp     byte [pitset], 0
        je      pitx
        mov     byte [pitset], 0
        mov     al, 36h                 ; mode 3 again (the BIOS's)
pitw:   cli
        out     43h, al
        xor     al, al
        out     40h, al
        jmp     short $+2
        out     40h, al
        sti
pitx:   ret

; DX:AX = BIOS tick * 65536 + PIT counts into it (retried across a tick)
stamp:  push    bx
        push    cx
.r:     call    d_tick
        mov     bx, ax
        cli
        xor     al, al
        out     43h, al                 ; latch counter 0
        jmp     short $+2
        in      al, 40h
        mov     cl, al
        jmp     short $+2
        in      al, 40h
        mov     ch, al
        sti
        nop
        call    d_tick
        cmp     ax, bx
        jne     .r
        mov     ax, cx
        neg     ax
        mov     dx, bx
        pop     cx
        pop     bx
        ret

; DX:AX = DX:AX / CX
ldiv:   push    bx
        push    si
        mov     si, ax
        mov     ax, dx
        xor     dx, dx
        div     cx
        mov     bx, ax
        mov     ax, si
        div     cx
        mov     dx, bx
        pop     si
        pop     bx
        ret

wait_ticks:                             ; CX ticks, interrupts on
        sti
.w:     call    d_wait_tick
        loop    .w
        ret

; srt[0..ROUNDS) ascending (insertion sort)
sort:   mov     bx, 2
.o:     cmp     bx, 2 * ROUNDS
        jae     .x
        mov     ax, [srt+bx]
        mov     si, bx
.i:     or      si, si
        jz      .p
        cmp     [srt+si-2], ax
        jbe     .p
        mov     dx, [srt+si-2]
        mov     [srt+si], dx
        sub     si, 2
        jmp     .i
.p:     mov     [srt+si], ax
        add     bx, 2
        jmp     .o
.x:     ret

; ---- output (as GPIBXFER) ---------------------------------------------
out_tenths:                             ; AX = 0.1 ms; 0FFFFh none, 0FFFEh long
        cmp     ax, 0FFFFh
        jne     .l
        mov     dx, s_none
        jmp     out_str
.l:     cmp     ax, 0FFFEh
        jne     .n
        mov     dx, s_long
        jmp     out_str
.n:     push    ax
        push    bx
        push    dx
        xor     dx, dx
        mov     bx, 10
        div     bx
        call    out_dec
        mov     al, '.'
        call    out_chr
        mov     al, dl
        add     al, '0'
        call    out_chr
        pop     dx
        pop     bx
        pop     ax
        ret

out_str:
        push    ax
        push    si
        mov     si, dx
.l:     lodsb
        cmp     al, '$'
        je      .x
        call    out_chr
        jmp     .l
.x:     pop     si
        pop     ax
        ret

out_crlf:
        push    ax
        mov     al, 13
        call    out_chr
        mov     al, 10
        call    out_chr
        pop     ax
        ret

out_chr:
        push    ax
        push    dx
        push    di
        mov     dl, al
        mov     ah, 02h
        int     21h
        mov     di, [logp]
        cmp     di, logbuf + LOGMAX
        jae     .x
        mov     [di], dl
        inc     word [logp]
.x:     pop     di
        pop     dx
        pop     ax
        ret

out_hex16:
        push    ax
        mov     al, ah
        call    out_hex
        pop     ax
out_hex:
        push    ax
        push    ax
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
        call    .d
        pop     ax
        ret
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     jmp     out_chr

out_num:
        push    ax
        xor     ah, ah
        call    out_dec
        pop     ax
        ret

out_dec:                                ; AX unsigned
        push    ax
        push    bx
        push    cx
        push    dx
        mov     bx, 10
        xor     cx, cx
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     ax
        add     al, '0'
        call    out_chr
        loop    .p
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

save_log:
        mov     dx, s_logname
        mov     ax, 3D01h
        int     21h
        jnc     .op
        mov     ah, 3Ch
        xor     cx, cx
        int     21h
        jc      .x
.op:    mov     bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        mov     cx, [logp]
        sub     cx, logbuf
        mov     dx, logbuf
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret

%include "direct.inc"
%include "rearm.inc"

; GLP NAK (seq 0, ack 0, CRC-16): gridlink sends its last answer again
nakframe db 47h, 06h, 0, 0, 0, 0, 89h, 0DCh

s_title db 13,10,'GPIBIRQ 1.0 - the 7210 interrupt on IRQ 5 (SRQ), bridge at $'
s_vec   db '0. IRQ 5 (INT 0Dh) vector $'
s_mask  db ', PIC mask $'
s_masked db 'h: IRQ 5 masked (nobody uses it)',13,10,'$'
s_unmasked db 'h: IRQ 5 UNMASKED - something else may use it',13,10,'$'
s_quiet db '   interrupts on IRQ 5 in 3 ticks, the 7210 quiet (want 0): $'
s_quiet2 db '   the same with SRQI on but no SRQ (want 0): $'
s_p1    db 13,10,'1. Polled (ISR2 in a loop):',13,10,'$'
s_p2    db 13,10,'2. Interrupt, busy loop:',13,10,'$'
s_p2i   db '   no interrupt at all: again with the INT pin inverted (AUXRB INV)',13,10,'$'
s_p3    db 13,10,'3. Interrupt, CPU halted (HLT) until it comes:',13,10,'$'
s_srq   db '   end of our frame to SRQ: best $'
s_med   db ', median $'
s_max   db ', worst $'
s_msx   db ' ms',13,10,'$'
s_stat  db '   serial poll: $'
s_ans   db 13,10,'   answers read: $'
s_ans2  db ' of 10, the last $'
s_bytes db ' bytes',13,10,'$'
s_wfail db '   OUR FRAME DID NOT GO, times: $'
s_irqs  db '   IRQ 5 interrupts: $'
s_srqs  db ', with SRQI: $'
s_isr2  db '; ISR2 in the handler $'
s_then  db 'h, read again $'
s_isr2e db 'h',13,10,'$'
s_storm db '   IRQ 5 KEPT FIRING: masked after 1000',13,10,'$'
s_wakes db '   woke from HLT, each round (1 = by IRQ 5 itself): $'
s_none  db 'none$'
s_long  db '>6 s$'
s_done  db 13,10,'Done.  GRIDGPIB, if loaded, set up again.  Also in GPIBIRQ.TXT.',13,10,'$'
s_logname db 'GPIBIRQ.TXT',0

RBUFLEN equ 80
LOGMAX  equ 2048
dev     db 7
mode    db 0
st      db 0
irqflag db 0
hooked  db 0
storm   db 0
pitset  db 0
isr2a   db 0
isr2b   db 0
oldmask db 0
oldvec  dw 0, 0
nirq    dw 0
nsrq    dw 0
ntmo    dw 0
nwf     dw 0
nok     dw 0
lastgot dw 0
wakes   dw 0
t0      dw 0, 0
lats    times ROUNDS dw 0
srt     times ROUNDS dw 0
wk      times ROUNDS dw 0
sts     times ROUNDS db 0
shadow1 db 0
shadow2 db 0
recov   dw 0
rxcnt   dw 0
lat     dw 0                    ; (direct.inc's d_spoll)
rawisr1 db 0
rawadsr db 0
rawdir  db 0
t_start dw 0
t_len   dw 0
logp    dw logbuf
rbuf    times RBUFLEN+2 db 0
logbuf  times LOGMAX db 0
rxbuf:                                  ; RXMAX bytes (past the end of the file)
