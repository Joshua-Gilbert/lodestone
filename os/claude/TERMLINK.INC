; =====================================================================
;  TERMLINK.INC - GLP 1, the GRiD side of the link (gridlink/PROTOCOL.md)
;
;  Shared by CLAUDE.COM's chat and Term modes, and by resident Claude's
;  console (RCON.ASM, RCON defined: never INT 60h AH=0Bh, which clears the
;  program's SRQ latch; the driver's SRQ interrupt count instead, when it
;  has one).  The program provides:
;    build_hello  -> CX = length of hellobuf
;    pi_frame     a new frame from the Pi at rxbuf+BX
;    msg_sent     a queued message has gone (done_type)
;    link_lost    the link failed (state already reset)
;    gg_call      INT nn of GRIDGPIB / the kernel's GPIB
;  and the variables it uses (lstate, txq, rxbuf, txframe, ...).
;  DS = CS throughout.  No DOS calls.
; =====================================================================

; The link's state that link_reset clears: each program declares it with
; TERMLINK_RESET_VARS in its BSS (whatever is put inside is cleared too)
%macro TERMLINK_RESET_VARS 0
lr_first:
g_seq       resb 1
p_ack       resb 1
have_pi     resb 1
nak_pending resb 1
resend      resb 1
pend_msg    resb 1
txq_head    resb 1
txq_n       resb 1
rq_type     resb 1
rq_len      resw 1
req_ready   resb 1
reply_busy  resb 1
snap_reply  resb 1
keyn        resb 1
keys_q      resb 1
rep_q       resb 1
use_fl      resb 1                      ; 1: frames carry a Fletcher sum, not CRC-16
wake_ok     resb 1                      ; 1: our HELLO offered GF_WAKE (the driver latches SRQ;
                                        ;  RCON: it counts SRQ interrupts)
tlook       resb 1                      ; 1: link_wait's serial poll is a tick's look, no SRQ seen
srq_held    resb 1                      ; 1: an answer was there at a tick's look, its SRQ no
                                        ;  edge (another device holds the line): the PIT's
                                        ;  polls, and no sleeping for the SRQ, till the next HELLO
lr_end:
%endmacro

link_service:
        mov     bl, [lstate]
        xor     bh, bh
        shl     bx, 1
        jmp     [ls_tab + bx]
ls_tab: dw link_reset, link_idle, link_wait

link_reset:
        mov     ax, [now]
        sub     ax, [t_reset]
        cmp     ax, 18                  ; once a second
        jb      .x
        mov     bl, [nano]              ; clear a half-read line in the bridge
        mov     ah, 06h
        call    gg_call
        push    es                      ; the link's state (TERMLINK_RESET_VARS)
        push    ds
        pop     es
        mov     di, lr_first
        mov     cx, lr_end - lr_first
        xor     al, al
        rep     stosb
        pop     es
        call    build_hello
        mov     al, G_HELLO
        mov     si, hellobuf
        call    txq_put_cs
        mov     byte [lstate], LS_IDLE
.x:     ret

link_idle:
        cmp     byte [nak_pending], 0
        jne     .nak
        cmp     byte [resend], 0
        jne     .again
        cmp     byte [txq_n], 0
        jne     .msg
        cmp     byte [connected], 0
        je      .x
        cmp     byte [busy], 0
        jne     .poll
        cmp     byte [pi_active], 0
        jne     .poll
        cmp     byte [term], 0          ; Term: back to back for 2 s after
        je      .t                      ; a key or a screen change
        mov     ax, [now]
        sub     ax, [t_active]
        cmp     ax, 36
        jb      .poll
.t:     cmp     byte [wake_ok], 0       ; the Pi rang (SRQ while we are idle):
        je      .t1                     ; POLL now, not at the next second
        cmp     word [irq_ptr+2], 0     ; (the driver's SRQ interrupt: its
%ifdef RCON                             ;  count moved?  RCON offers GF_WAKE
        je      .t1                     ;  only with it)
%else
        je      .t2
%endif
        call    srq_new
        jz      .t1
%ifndef RCON
        jmp     short .ts
.t2:    mov     ah, 0Bh
        call    gg_call
        jc      .t1
        or      ax, ax
        jz      .t1
%endif
.ts:    mov     bl, [nano]              ; an SRQ since the last look: the Pi's,
        mov     ah, 05h                 ; or one from our last answer (the driver
        call    gg_call                 ; latches every SRQ it sees): ask
        jc      .t1
        test    al, 40h
        jnz     .poll
.t1:    mov     ax, [now]
        sub     ax, [t_last]
        cmp     ax, 18
        jb      .x
.poll:  call    frame_poll
        jmp     link_write
.nak:   mov     byte [nak_pending], 0
        jmp     link_write_nak
.again: mov     byte [resend], 0
        jmp     link_write
.msg:   call    frame_next
        jmp     link_write
.x:     ret

; POLL frame (no payload) with a new sequence number
frame_poll:
%ifdef KSUM
        mov     byte [tx_app], 0
%endif
        mov     byte [pend_msg], 0
        inc     byte [g_seq]
        mov     di, txframe
        mov     ah, G_POLL
        call    frame_short
        mov     [txlen], cx
        ret

; a frame with no payload at DI: AH = type, the sequence number g_seq.
; Returns SI = DI, CX = 8 (its length).  Destroys AX BX.
frame_short:
        mov     al, [g_seq]
        xor     cx, cx
        call    frame_hdr
        lea     si, [di+1]
        mov     cx, 5
        mov     ax, 0FFFFh
        call    fcs
        mov     [di+6], ax
        mov     si, di
        mov     cx, 8
        ret

; a frame's header at DI: AH = type, AL = sequence number, CX = length.
; Destroys AL.
frame_hdr:
        mov     byte [di], 47h
        mov     [di+1], ah
        mov     [di+2], al
        mov     al, [p_ack]
        mov     [di+3], al
        mov     [di+4], cx
        ret

; next fragment of the message at the head of the queue
frame_next:
        mov     bl, [txq_head]
        xor     bh, bh
        imul    bx, bx, 10
        add     bx, txq
        mov     cx, [bx+6]
        sub     cx, [bx+8]              ; bytes left
        mov     ah, [bx]                ; type
        cmp     cx, TXMAX
        jbe     .last
        mov     cx, TXMAX
        or      ah, 80h                 ; MORE
.last:  mov     [pend_chunk], cx
        mov     byte [pend_msg], 1
        mov     al, [g_seq]
        inc     al
        cmp     byte [bx], G_HELLO
        jne     .s
        xor     al, al                  ; HELLO is always frame 0
.s:     mov     [g_seq], al
        mov     di, txframe
        call    frame_hdr
        add     di, 6
        push    ds
        mov     si, [bx+4]
        add     si, [bx+8]
        mov     ds, [bx+2]
        push    cx
        PROF    5
        shr     cx, 1
        rep     movsw
        adc     cx, cx
        rep     movsb
        PROF    0
        pop     cx
        pop     ds
%ifdef KSUM
        mov     al, [ksum]              ; the driver adds the check as it sends
        and     al, [use_fl]            ;  (1.23: 02h AL=3)
        mov     [tx_app], al
        jz      .fc
        add     cx, 6
        mov     [txlen], cx
        ret
.fc:
%endif
        push    cx
        mov     si, txframe+1
        add     cx, 5
        mov     ax, 0FFFFh
        call    fcs
        pop     cx
        mov     di, txframe+6
        add     di, cx
        mov     [di], ax
        add     cx, 8
        mov     [txlen], cx
        ret

link_write:
        mov     si, txframe
        mov     cx, [txlen]
%ifdef KSUM
        mov     al, [tx_app]            ; 3: EOI, after the driver's check
        shl     al, 1
        or      al, 1
        mov     [lw_eoi], al
%endif
lw_go:
        cmp     word [irq_ptr+2], 0     ; (SRQs before our frame aren't its
        je      .w                      ;  answer's)
        call    srq_new
.w:
        mov     bl, [nano]
%ifdef KSUM
        mov     al, [lw_eoi]
%else
        mov     al, 1                   ; EOI with the last byte
%endif
        mov     ah, 02h
        PROF    1
        call    gg_call
        PROF    0
        jnc     .ok
        jmp     link_fail
.ok:    mov     ax, [now]
        mov     [t_sent], ax
        mov     byte [lstate], LS_WAIT
        mov     byte [spoll_errs], 0
        jmp     pit_mark

; NAK the Pi's last answer (it was damaged, or none came); our pending
; fragment stays, and so does t_sent: link_wait's ~2 s run from the frame
; the answer is for, so only good answers keep the link up (a read that
; timed out, 2 s, and then another, NAK after NAK, would never fail it)
link_write_nak:
%ifdef KSUM
        mov     byte [lw_eoi], 1
%endif
        mov     di, nakframe
        mov     ah, G_NAK
        call    frame_short
        push    word [t_sent]
        call    lw_go
        pop     word [t_sent]
        ret

link_wait:
        mov     ax, [now]
        sub     ax, [t_sent]
        cmp     ax, 40                  ; ~2 s without an answer
        jbe     .t
        jmp     link_fail
.t:     mov     byte [tlook], 0
        cmp     word [irq_ptr+2], 0
        je      .t0
        call    srq_new                 ; the SRQ interrupt came: poll now
        jnz     .poll                   ;  (maybe_idle, RCON's idle, sleep till it)
        cmp     byte [srq_held], 0      ; (no edges for us: the PIT's polls)
        jne     .t0
        mov     ax, [now]               ; else once a tick, should one go astray
        cmp     ax, [pit_tick]
        je      .x
        inc     byte [tlook]
        jmp     short .poll
.t0:
%ifndef RCON                            ; (resident: never AH=0Bh, which clears
        mov     ah, 0Bh                 ;  the program's SRQ latch)
        PROF    3                       ; SRQ since the last call?
        call    gg_call
        PROF    0
        jc      .chk
        or      ax, ax
        jnz     .poll
.chk:
%endif
        call    pit_due                 ; else poll every few ms
        jnc     .x
.poll:  call    pit_mark
        mov     bl, [nano]
        mov     ah, 05h
        PROF    3
        call    gg_call                 ; AL = status byte
        PROF    0
        jc      .perr
        mov     byte [spoll_errs], 0
        test    al, 40h
        jz      .x
        cmp     byte [tlook], 0         ; the answer there at a tick's look, and
        je      .r                      ;  still no SRQ interrupt for it now (it
        push    ax                      ;  may have come since that look): the
        call    srq_new                 ;  line held by another device
        pop     ax
        jnz     .r
        mov     byte [srq_held], 1
.r:
        test    al, 20h                 ; patched bridge: the line is complete
        jnz     .read
        and     ax, 1Fh                 ; stock bridge: wait as the Pi asked
        mov     cx, ax
        call    delay_ms
.read:  call    link_read
%ifdef LINK_CHAIN
        cmp     byte [lstate], LS_IDLE  ; the answer is in: the next frame at
        jne     .x                      ;  once, not after a round of the main
        cmp     byte [req_ready], 0     ;  loop (keys, ticks: ~0.4 ms a frame on
        jne     .x                      ;  the 1520) -- unless a request is to
%ifdef RCON                             ;  run first: its REPLY is what goes.
        cmp     byte [quit], 0          ;  (RCON going back: what is queued
        jne     .x                      ;  goes, and no POLLs, from session)
%endif
        jmp     link_idle
%endif
.x:     ret
.perr:  inc     byte [spoll_errs]
        cmp     byte [spoll_errs], 8
        jb      .x
        jmp     link_fail

link_read:
        mov     di, rxbuf
        mov     cx, RXMAX
        mov     bl, [nano]
        xor     al, al                  ; binary: stop at EOI only
%ifdef KSUM
        mov     al, [ksum]              ; 2: and BX = the driver's check of
        and     al, [use_fl]            ;  every byte (1.23)
        shl     al, 1
%endif
        mov     ah, 03h
        PROF    2
        call    gg_call
        PROF    0
        jc      .bad
        mov     [rxn], cx
%ifdef KSUM
        mov     al, [ksum]
        and     al, [use_fl]
        jz      .scan
        call    ks_check
        jnc     .ok
.scan:
%endif
        call    find_frame
        jc      .bad
.ok:    jmp     took_answer
.bad:   mov     byte [nak_pending], 1
        mov     byte [lstate], LS_IDLE
        inc     word [n_bad]
        ret

%ifdef KSUM
; One frame and nothing else, CX = rxn bytes: is it good, by the driver's
; Fletcher-16 of all of them (BL = A, BH = B; A = 1, B = 0 to start)?  The
; frame's own check leaves out the first byte (47h) and the check (the last
; two, A then B), so:  A1 = A - 47h, B1 = B - 1 - n * 47h, then
; A2 = A1 - a - b and B2 = B1 - 2 A1 + b must be the a and b sent.
; -> BX = 0, CF clear if it is good.  (find_frame scans for anything else.)
ks_check:
        cmp     cx, 8
        jb      .no
        cmp     byte [rxbuf], 47h
        jne     .no
        mov     ax, [rxbuf+4]
        cmp     ax, RXMAX - 9
        ja      .no
        add     ax, 8
        cmp     ax, cx
        jne     .no
        PROF    4
        mov     si, cx
        mov     dx, [rxbuf+si-2]        ; DL = a, DH = b
        mov     al, cl
        mov     ah, 47h
        mul     ah                      ; AL = n * 47h (mod 256)
        sub     bh, al
        dec     bh                      ; B1
        sub     bl, 47h                 ; A1
        sub     bh, bl
        sub     bh, bl
        add     bh, dh                  ; B2
        sub     bl, dl
        sub     bl, dh                  ; A2
        PROF    0
        cmp     bx, dx
        jne     .no
        inc     word [n_kok]            ; (frames the driver's check passed)
        xor     bx, bx
        clc
        ret
.no:    stc
        ret
%endif

; rxbuf[0..rxn) -> BX = offset of the first good frame, CF if none
find_frame:
        xor     bx, bx
.s:     mov     ax, [rxn]
        sub     ax, bx
        cmp     ax, 8
        jb      .no
        cmp     byte [rxbuf+bx], 47h
        jne     .nx
        mov     cx, [rxbuf+bx+4]
        cmp     cx, RXMAX - 9
        ja      .nx
        mov     dx, cx
        add     dx, 8
        cmp     dx, ax
        ja      .nx
        push    bx
        push    cx
        lea     si, [rxbuf+bx+1]
        add     cx, 5
        mov     ax, 0FFFFh
        call    fcs
        pop     cx
        pop     bx
        mov     si, bx
        add     si, cx
        cmp     ax, [rxbuf+si+6]
        je      .ok
.nx:    inc     bx
        jmp     .s
.no:    stc
        ret
.ok:    clc
        ret

; a good answer at rxbuf+BX
took_answer:
        mov     byte [lstate], LS_IDLE
        mov     ax, [now]
        mov     [t_last], ax
        mov     byte [n_failrun], 0
        mov     al, [rxbuf+bx+1]
        and     al, 7Fh
        cmp     al, P_NAK
        jne     .ok
        mov     byte [resend], 1        ; the Pi lost our frame: send it again
        ret
.ok:    call    commit_fragment         ; our frame got through
        mov     al, [rxbuf+bx+2]
        cmp     byte [have_pi], 0
        je      .new
        cmp     al, [p_ack]
        jne     .new
        ret                             ; an answer we already handled
.new:   mov     [p_ack], al
        mov     byte [have_pi], 1
        jmp     pi_frame

commit_fragment:
        cmp     byte [pend_msg], 0
        je      .x
        mov     byte [pend_msg], 0
        push    bx
        mov     bl, [txq_head]
        xor     bh, bh
        imul    bx, bx, 10
        add     bx, txq
        mov     ax, [pend_chunk]
        add     [bx+8], ax
        mov     ax, [bx+8]
        cmp     ax, [bx+6]
        jb      .y
        mov     al, [bx]                ; message done
        mov     [done_type], al
        mov     al, [txq_head]
        inc     al
        cmp     al, TXQN
        jb      .h
        xor     al, al
.h:     mov     [txq_head], al
        dec     byte [txq_n]
        call    msg_sent
.y:     pop     bx
.x:     ret

link_fail:
        mov     byte [lstate], LS_RESET
        mov     ax, [now]
        mov     [t_reset], ax
        inc     word [n_fail]
        inc     byte [n_failrun]
        jmp     link_lost

; queue a message: AL = type, DX:SI = body (txq_put_cs: CS:SI), CX = length
txq_put_cs:
        mov     dx, cs
txq_put:
        push    bx
        push    di
        mov     bl, [txq_n]
        cmp     bl, TXQN
        jae     .x
        add     bl, [txq_head]
        cmp     bl, TXQN
        jb      .a
        sub     bl, TXQN
.a:     xor     bh, bh
        imul    di, bx, 10
        add     di, txq
        mov     [di], al
        mov     [di+2], dx
        mov     [di+4], si
        mov     [di+6], cx
        mov     word [di+8], 0
        inc     byte [txq_n]
.x:     pop     di
        pop     bx
        ret

; ---- timing ---------------------------------------------------------
get_ticks:
        push    ds
        push    40h
        pop     ds
        mov     ax, [6Ch]
        pop     ds
        ret

pit_read:                               ; AX = PIT channel 0 count
        pushf
        cli
        xor     al, al
        out     43h, al
        in      al, 40h
        mov     ah, al
        in      al, 40h
        popf
        xchg    al, ah
        ret

; ZF clear: an SRQ interrupt since the last look (the GPIB driver's count,
; INT 60h AH=0Eh: irq_ptr; Lodestone's built-in driver, IRQ 5)
srq_new:
        push    es
        push    bx
        les     bx, [irq_ptr]
        mov     ax, [es:bx]
        pop     bx
        pop     es
        cmp     ax, [srq_seen]
        mov     [srq_seen], ax          ; (MOV keeps the flags)
        ret

pit_mark:
        push    ax
        call    pit_read
        mov     [pit_last], ax
        mov     ax, [now]
        mov     [pit_tick], ax
        pop     ax
        ret

pit_due:                                ; CF = 1 once ~2-4 ms have passed
        push    ax
        push    dx
        mov     ax, [now]
        cmp     ax, [pit_tick]
        jne     .yes
        call    pit_read
        mov     dx, [pit_last]
        sub     dx, ax
        cmp     dx, 5000
        jae     .yes
        clc
        jmp     .x
.yes:   stc
.x:     pop     dx
        pop     ax
        ret

; CX = milliseconds, timed by the refresh toggle (port 61h bit 4, 15 us)
delay_ms:
        jcxz    .x
        push    ax
        push    bx
        push    dx
.ms:    mov     bx, 66
        in      al, 61h
        and     al, 10h
        mov     ah, al
.w:     mov     dx, 2000                ; give up on a toggle that never comes
.t:     in      al, 61h
        and     al, 10h
        cmp     al, ah
        jne     .tg
        dec     dx
        jnz     .t
.tg:    mov     ah, al
        dec     bx
        jnz     .w
        loop    .ms
        pop     dx
        pop     bx
        pop     ax
.x:     ret

; A frame's check over DS:SI, CX bytes -> AX: CRC-16 until the Pi's HELLO
; agrees to the Fletcher sum (use_fl; link_reset clears it, so HELLO and its
; answer always go with the CRC).  Destroys BX SI CX.
%ifdef PROFILE
fcs:    PROF    4
        call    fcs_
        PROF    0
        ret
fcs_:
%else
fcs:
%endif
        cmp     byte [use_fl], 0
        je      crc16
; Fletcher-16 with 8-bit sums: A = 1 + the bytes, B = the sum of the A's,
; both mod 256 (the registers' own wrap: no modulo step at all, where
; Fletcher's mod 255 would cost an ADC after every add); AX = B << 8 | A.
; Four bytes a pass: about 8.5 clocks a byte on the 286 by the tables,
; against about 34 for the table CRC.  Destroys BX SI CX (as crc16).
fl16:   push    dx
        mov     bx, 1                   ; BL = A, BH = B
        mov     dx, cx
        shr     cx, 2
        jcxz    .t
.l:     lodsw
        add     bl, al
        add     bh, bl
        add     bl, ah
        add     bh, bl
        lodsw
        add     bl, al
        add     bh, bl
        add     bl, ah
        add     bh, bl
        loop    .l
.t:     and     dx, 3                   ; the last 0-3 bytes
        jz      .x
.b:     lodsb
        add     bl, al
        add     bh, bl
        dec     dx
        jnz     .b
.x:     mov     ax, bx
        pop     dx
        ret

; CRC-16/CCITT-FALSE.  AX = crc, DS:SI -> data (RCON: ES:SI, ES = CS but for
; the shadow's), CX = count.  Destroys BX SI CX.
crc16:  jcxz    .x
.l:     mov     bl, ah
%ifdef RCON
        xor     bl, [es:si]
%else
        xor     bl, [si]
%endif
        inc     si
        xor     bh, bh
        shl     bx, 1
        mov     ah, al
        xor     al, al
        xor     ax, [crctab + bx]
        loop    .l
.x:     ret

crc_init:
        xor     bx, bx
.i:     mov     ah, bl
        xor     al, al
        mov     cx, 8
.b:     shl     ax, 1
        jnc     .n
        xor     ax, 1021h
.n:     loop    .b
        mov     di, bx
        shl     di, 1
        mov     [crctab + di], ax
        inc     bx
        cmp     bx, 256
        jb      .i
        ret
