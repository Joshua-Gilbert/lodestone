; =====================================================================
;  GPIBXFER.COM 1.4 - real DMA through the 1520's 7210 (channel 3), and
;  how fast it is next to the CPU's own loop.
;  Build:  nasm -f bin -o GPIBXFER.COM GPIBXFER.ASM
;  Usage:  GPIBXFER [a]      a = the echo device's address (default 7)
;
;  The other end must echo: the Pico bridge with the gpib-bridge daemon's
;  thrutest handler (on the Pi: sudo systemctl stop gridlink;
;  sudo systemctl start gpib-bridge).  Each message is 4096 bytes, every
;  byte value; the bridge sends back the last message it got.
;
;    1. CPU (PIO): 16 messages out, 16 echoes in, the last one checked.
;    2. DMA:       the same through 8237 channel 3 (GPIBDMA 1.0 found the
;                  7210's DRQ there).  Out: mode 4Bh (single, memory to
;                  the 7210), all but the last byte, which goes by the CPU
;                  with EOI.  In: mode 47h (single, the 7210 to memory),
;                  every byte; the 7210 holds RFD after the END byte.
;  Each echo is compared with what was sent.  A DMA that ends at once with
;  wrong bytes means DACK isn't wired to the 7210 (the 8237 runs its
;  cycles, nothing answers them).  Channel 3 is masked again after every
;  message and on any error.
;
;  Chip-level like GPIBDMA; at the end GRIDGPIB, if loaded, sets the chip up
;  again (INT 60h AH=01h: rearm.inc).
;  Appends what it prints to GPIBXFER.TXT.
; =====================================================================
cpu 286
org 100h

%include "direct_equ.inc"

MSGLEN  equ 4096
NMSG    equ 16
IMR2_DMAI equ 10h
IMR2_DMAO equ 20h
AUXRA_HOLDEND equ 82h           ; RFD holdoff on END
T_XFER  equ 36                  ; ~2 s for one message

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
.go:    call    place                   ; buffers clear of a 64 KB boundary
        mov     dx, s_title
        call    out_str
        mov     al, [dev]
        call    out_num
        call    out_crlf
        mov     di, [txp]               ; the message: every byte value
        xor     cx, cx
.f:     mov     al, cl
        mov     ah, ch
        shr     ah, 3
        add     al, ah
        stosb
        inc     cx
        cmp     cx, MSGLEN
        jb      .f
        call    d_recover

        ; ---- 1. the CPU's loop ----------------------------------------
        mov     dx, s_pio
        call    out_str
        mov     byte [usedma], 0
        call    run_both
        ; ---- 2. DMA, channel 3 -----------------------------------------
        mov     dx, s_dma
        call    out_str
        mov     byte [usedma], 1
        call    run_both
        call    dma_off
        call    d_recover
        mov     dx, s_done
        call    out_str
        call    d_rearm                 ; (X55: the driver's IMR2, IFC, REN)
        call    save_log
        mov     ax, 4C00h
        int     21h

; out: NMSG messages (CPU or DMA as usedma) -> the GRiD -> device rate.
; CPU run: then NMSG write + read pairs (the bridge answers a read once per
; message, as THRUTEST uses it), less the writes -> the device -> GRiD rate.
; DMA run: one write by DMA, its echo read by the CPU and checked (DMA reads
; are not wired: 1.1/1.2 got FF in memory while the 7210 gave its bytes up).
run_both:
        call    d_tick
        mov     [t0], ax
        mov     cx, NMSG
.w:     push    cx
        call    msg_out
        pop     cx
        jc      .fail_o
        loop    .w
        call    d_tick
        sub     ax, [t0]
        mov     [tout], ax
        mov     dx, s_outr
        call    out_str
        mov     ax, [tout]
        call    rate
        cmp     byte [usedma], 0
        jne     .dmachk
        call    d_tick
        mov     [t0], ax
        mov     cx, NMSG
.r:     push    cx
        call    spoil
        call    msg_out
        jc      .fo2
        call    msg_in
        pop     cx
        jc      .fail_i
        loop    .r
        call    d_tick
        sub     ax, [t0]
        sub     ax, [tout]              ; the pairs less the writes alone
        jns     .pos
        xor     ax, ax
.pos:   mov     [tin], ax
        mov     dx, s_inr
        call    out_str
        mov     ax, [tin]
        call    rate
        jmp     short .cmp
.fo2:   pop     cx                      ; (a pair's write that failed)
        jmp     .fail_o
.dmachk: call   spoil                   ; the last DMA message's echo, by the CPU
        mov     byte [usedma], 0
        call    msg_in
        mov     byte [usedma], 1
        jc      .fail_i
        mov     dx, s_dmachk
        call    out_str
.cmp:   mov     si, [txp]               ; the last echo against the message
        mov     di, [rxp]
        mov     cx, MSGLEN
        repe    cmpsb
        jne     .bad
        mov     dx, s_same
        jmp     out_str
.bad:   mov     dx, s_diff
        call    out_str
        mov     ax, MSGLEN
        sub     ax, cx
        call    out_dec
        call    out_crlf
        ; what came back: the first bytes, how many are FF, and whether it
        ; is the message shifted (rx[i] = tx[i+d], d = -3..+3)
        mov     dx, s_sent
        call    out_str
        mov     si, [txp]
        call    .hex16
        mov     dx, s_gotb
        call    out_str
        mov     si, [rxp]
        call    .hex16
        mov     si, [rxp]
        mov     cx, MSGLEN
        xor     bx, bx
.ff:    lodsb
        cmp     al, 0FFh
        jne     .nff
        inc     bx
.nff:   loop    .ff
        mov     dx, s_ffs
        call    out_str
        mov     ax, bx
        call    out_dec
        call    out_crlf
        mov     word [shift], -3
.sh:    mov     si, [rxp]               ; matches of rx[i] against tx[i+d]
        mov     di, [txp]
        add     di, [shift]
        xor     bx, bx                  ; BX = matches
        mov     cx, MSGLEN - 6
        add     si, 3
        add     di, 3
.sm:    mov     al, [si]
        cmp     al, [di]
        jne     .sn
        inc     bx
.sn:    inc     si
        inc     di
        loop    .sm
        mov     dx, s_shift
        call    out_str
        mov     ax, [shift]
        or      ax, ax
        jns     .sp
        push    ax
        mov     al, '-'
        call    out_chr
        pop     ax
        neg     ax
.sp:    call    out_dec
        mov     dx, s_match
        call    out_str
        mov     ax, bx
        call    out_dec
        mov     dx, s_of
        call    out_str
        inc     word [shift]
        cmp     word [shift], 4
        jl      .sh
        ret

; 16 bytes at SI in hex, then a new line
.hex16: push    cx
        mov     cx, 16
.h:     lodsb
        call    out_hex
        mov     al, ' '
        call    out_chr
        loop    .h
        pop     cx
        jmp     out_crlf
.fail_o: mov    dx, s_fo
        jmp     short .f2
.fail_i: mov    dx, s_fi
.f2:    call    out_str
        mov     al, [why]
        call    out_hex
        mov     dx, s_got
        call    out_str
        mov     ax, [got]
        call    out_dec
        mov     dx, s_isr
        call    out_str
        mov     al, [lastisr]
        call    out_hex
        call    out_crlf
        call    dma_off
        jmp     d_recover

spoil:  push    cx
        push    di
        mov     di, [rxp]
        mov     cx, MSGLEN
        mov     al, 0A5h
        rep     stosb
        pop     di
        pop     cx
        ret

; AX ticks for NMSG * MSGLEN bytes -> "n.n s, n KB/s"
rate:   push    ax
        mov     bx, 55
        mul     bx                      ; ms
        mov     [ms], ax
        call    out_dec
        mov     dx, s_ms
        call    out_str
        pop     ax
        or      ax, ax
        jnz     .k
        mov     dx, s_fast
        jmp     out_str
.k:     mov     ax, NMSG * MSGLEN / 1024 * 1000
        xor     dx, dx
        div     word [ms]
        call    out_dec
        mov     dx, s_kbs
        jmp     out_str

; ---- one message out (the GRiD talks, the device listens) -------------
msg_out:
        mov     byte [why], 1
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
        mov     si, [txp]
        mov     cx, MSGLEN - 1          ; all but the last byte
        cmp     byte [usedma], 0
        je      .pio
        mov     byte [why], 2
        mov     al, 4Bh                 ; single, read (memory -> I/O), ch 3
        mov     bx, si
        call    dma_set
        call    d_do_gts
        mov     dx, R_IMR2
        mov     al, IMR2_DMAO
        out     dx, al
        call    dma_wait
        pushf
        mov     dx, R_IMR2
        xor     al, al
        out     dx, al
        call    dma_off
        popf
        jc      .f
        add     si, MSGLEN - 1
        jmp     short .last
.pio:   call    d_do_gts
        mov     byte [why], 3
        mov     dx, R_ISR1
.pb:    mov     bx, 0                   ; ~ the kernel's fast loop
.pw:    in      al, dx
        test    al, ISR1_DO | ISR1_ERR
        jnz     .pg
        dec     bx
        jnz     .pw
        jmp     short .f
.pg:    test    al, ISR1_ERR
        jnz     .f
        lodsb
        mov     dx, R_CDOR
        out     dx, al
        mov     dx, R_ISR1
        loop    .pb
        mov     byte [shadow1], 0
.last:  mov     byte [why], 4           ; the last byte, with EOI
        mov     cx, T_XFER
        call    d_tmo_start
.lw:    mov     ah, ISR1_DO | ISR1_ERR
        call    d_isr1_test
        jnz     .lg
        call    d_tmo_check
        jnc     .lw
        jmp     short .f
.lg:    test    al, ISR1_ERR
        jnz     .f
        mov     dx, R_AUXMR
        mov     al, AUX_SEOI
        out     dx, al
        mov     dx, R_CDOR
        lodsb
        out     dx, al
        mov     byte [why], 5
        mov     cx, T_XFER
        call    d_tmo_start
.lx:    mov     ah, ISR1_DO
        call    d_isr1_test
        jnz     .ok
        call    d_tmo_check
        jnc     .lx
.f:     stc
        ret
.ok:    clc
        ret

; ---- one echo in (the device talks, the GRiD listens) -----------------
msg_in:
        mov     byte [why], 11h
        call    d_cmd_begin
        mov     al, UNL
        call    d_send_cmd
        jc      .f
        mov     al, 20h + MYADDR
        call    d_send_cmd
        jc      .f
        mov     al, [dev]
        or      al, 40h
        call    d_send_cmd
        jc      .f
        call    d_wait_co
        jc      .f
        call    d_clear_in
        mov     dx, R_AUXMR
        mov     al, AUXRA_HOLDEND
        out     dx, al
        mov     di, [rxp]
        mov     cx, MSGLEN
        cmp     byte [usedma], 0
        je      .pio
        mov     byte [why], 12h
        mov     al, 47h                 ; single, write (I/O -> memory), ch 3
        mov     bx, di
        call    dma_set
        mov     dx, R_IMR2
        mov     al, IMR2_DMAI
        out     dx, al
        call    d_do_gts
        call    dma_wait
        pushf
        mov     dx, R_IMR2
        xor     al, al
        out     dx, al
        call    dma_off
        mov     dx, R_ISR1
        in      al, dx
        mov     [lastisr], al
        mov     ax, MSGLEN
        sub     ax, [left]
        mov     [got], ax
        popf
        jc      .f
        mov     byte [why], 13h         ; the END byte was the last
        mov     dx, R_ISR1
        in      al, dx
        mov     ah, al
        in      al, dx
        or      al, ah
        or      al, [shadow1]
        mov     byte [shadow1], 0
        mov     [lastisr], al
        test    al, ISR1_END
        jz      .f
        jmp     short .end
.pio:   push    cx
        mov     cx, T_XFER              ; the first byte: up to ~2 s (the Pi
        call    d_tmo_start             ;  answers once the stale replies go)
        pop     cx
        call    d_do_gts
        mov     byte [why], 14h         ; (14h: a byte didn't come)
        mov     dx, R_ISR1
        xor     ah, ah
.pb:    mov     bx, 0
.pw:    in      al, dx
        or      ah, al
        test    ah, ISR1_DI
        jnz     .pg
        test    ah, ISR1_END            ; END latched after the last byte's DI
        jnz     .lateend
        dec     bx
        jnz     .pw
        cmp     di, [rxp]               ; nothing yet: wait on to the timeout
        jne     .pf
        call    d_tmo_check
        jnc     .pb
        jmp     short .pf
.pg:    mov     dx, R_DIR
        in      al, dx
        stosb
        mov     dx, R_ISR1
        and     ah, ~ISR1_DI            ; this byte's DI is used up
        in      al, dx                  ; a second look, for END (as d_isr1_test);
        or      ah, al                  ;  a DI here is the next byte's
        test    ah, ISR1_END
        jz      .more
        cmp     cx, 1
        je      .pend                   ; END with the last byte: done
        test    ah, ISR1_DI
        jz      .pend                   ; END and nothing more: early
.more:  loop    .pb
        mov     byte [why], 16h         ; (16h: no END by MSGLEN bytes)
        mov     bx, 0                   ;  - or END just late: one more look
.pl:    in      al, dx
        or      ah, al
        test    ah, ISR1_END
        jnz     .pok
        dec     bx
        jnz     .pl
        jmp     short .pf
.lateend: mov   byte [why], 15h         ; (15h: END with bytes still to come)
        jmp     short .pf
.pend:  dec     cx
        mov     byte [why], 15h
        jnz     .pf
.pok:   mov     byte [shadow1], 0
.end:   call    d_rd_end
        clc
        ret
.pf:    mov     [lastisr], ah
        mov     ax, di
        sub     ax, [rxp]
        mov     [got], ax
.f:     call    d_rd_end
        stc
        ret

; ---- 8237 channel 3: AL = mode, BX = offset in DS, CX = bytes ----------
dma_set:
        push    ax
        mov     al, 07h                 ; mask channel 3
        out     0Ah, al
        pop     ax
        out     0Bh, al                 ; mode
        out     0Ch, al                 ; clear the byte flip-flop
        mov     ax, ds                  ; physical address of DS:BX
        mov     dx, ax
        shl     ax, 4
        shr     dx, 12
        add     ax, bx
        adc     dl, 0
        out     06h, al                 ; channel 3 address
        mov     al, ah
        out     06h, al
        mov     al, dl
        out     82h, al                 ; channel 3 page
        mov     ax, cx
        dec     ax
        out     07h, al                 ; channel 3 count - 1
        mov     al, ah
        out     07h, al
        in      al, 08h                 ; (clear any old TC)
        mov     al, 03h                 ; unmask channel 3
        out     0Ah, al
        ret

dma_off:
        mov     al, 07h
        out     0Ah, al
        ret

; wait for channel 3's terminal count (status bit 3); CF=1 on a timeout,
; [left] = the bytes the 8237 had left then
dma_wait:
        push    cx
        mov     cx, T_XFER
        call    d_tmo_start
.w:     in      al, 08h
        test    al, 08h
        jnz     .ok
        call    d_tmo_check
        jnc     .w
        in      al, 08h
        mov     [dst], al
        out     0Ch, al                 ; how far it got
        in      al, 07h
        mov     ah, al
        in      al, 07h
        xchg    al, ah
        inc     ax
        mov     [left], ax
        out     0Ch, al
        in      al, 06h
        mov     ah, al
        in      al, 06h
        xchg    al, ah
        mov     [dadr], ax
        pop     cx
        stc
        ret
.ok:    mov     word [left], 0
        pop     cx
        clc
        ret

; buffers that don't cross a 64 KB physical boundary (8237 pages)
place:  mov     ax, ds
        mov     dx, ax
        shl     ax, 4
        add     ax, bufs                ; low 16 bits of the physical address
        mov     bx, bufs
        mov     cx, ax
        add     cx, 2 * MSGLEN
        jnc     .ok                     ; both fit before the boundary
        neg     ax                      ; bytes to the boundary
        add     bx, ax                  ; start right after it
.ok:    mov     [txp], bx
        add     bx, MSGLEN
        mov     [rxp], bx
        ret

; ---- output (as GPIBDMA) -----------------------------------------------
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

s_title db 13,10,'GPIBXFER 1.4 - 16 x 4096-byte messages each way, echoed by the device at $'
s_pio   db 13,10,'CPU loop:',13,10,'$'
s_dma   db 13,10,'DMA, channel 3:',13,10,'$'
s_outr  db '  GRiD -> device: $'
s_inr   db '  device -> GRiD: $'
s_ms    db ' ms, $'
s_kbs   db ' KB/s',13,10,'$'
s_fast  db ' (under a tick)',13,10,'$'
s_same  db '  the echo is every byte right',13,10,'$'
s_sent  db '  sent: $'
s_gotb  db '  back: $'
s_ffs   db '  FF bytes in what came back: $'
s_shift db '  shifted by $'
s_match db ': $'
s_of    db ' of 4090 bytes match',13,10,'$'
s_dmachk db '  (the DMA message read back by the CPU)',13,10,'$'
s_diff  db '  THE ECHO DIFFERS from byte $'
s_fo    db '  sending failed, step $'
s_fi    db '  receiving failed, step $'
s_got   db 'h; bytes in: $'
s_isr   db ', 7210 ISR1 $'
s_cnt   db '  8237 channel 3: bytes left $'
s_adr   db ', address $'
s_st    db 'h, status $'
s_first db 'h; buffer starts $'
s_done  db 13,10,'Done.  GRIDGPIB, if loaded, set up again.  Also in GPIBXFER.TXT.',13,10,'$'
s_logname db 'GPIBXFER.TXT',0

RBUFLEN equ 80
LOGMAX  equ 1024
dev     db 7
usedma  db 0
why     db 0
t0      dw 0
tout    dw 0
tin     dw 0
ms      dw 0
left    dw 0
shift   dw 0
got     dw 0
dadr    dw 0
dst     db 0
lastisr db 0
txp     dw 0
rxp     dw 0
shadow1 db 0
shadow2 db 0
recov   dw 0
rxcnt   dw 0
lat     dw 0
rawisr1 db 0
rawadsr db 0
rawdir  db 0
t_start dw 0
t_len   dw 0
logp    dw logbuf
rbuf    times RBUFLEN+2 db 0
logbuf  times LOGMAX db 0
bufs:                                   ; 2 * MSGLEN, and room to move past
                                        ;  a 64 KB boundary (place)
