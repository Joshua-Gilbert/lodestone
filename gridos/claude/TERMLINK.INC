; =====================================================================
;  TERMLINK.INC - GLP 1, the GRiD side of the link (gridlink/PROTOCOL.md)
;
;  Shared by CLAUDE.COM's chat and Term modes.  The program provides:
;    build_hello  -> CX = length of hellobuf
;    pi_frame     a new frame from the Pi at rxbuf+BX
;    msg_sent     a queued message has gone (done_type)
;    link_lost    the link failed (state already reset)
;    gg_call      INT nn of GRIDGPIB / the kernel's GPIB
;  and the variables it uses (lstate, txq, rxbuf, txframe, ...).
;  DS = CS throughout.  No DOS calls.
; =====================================================================

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
        mov     byte [have_pi], 0
        mov     byte [p_ack], 0
        mov     byte [g_seq], 0
        mov     byte [nak_pending], 0
        mov     byte [resend], 0
        mov     byte [pend_msg], 0
        mov     byte [rq_type], 0
        mov     word [rq_len], 0
        mov     byte [req_ready], 0
        mov     byte [reply_busy], 0
        mov     byte [snap_reply], 0
        mov     byte [txq_n], 0
        mov     byte [txq_head], 0
        mov     byte [keys_q], 0
        mov     byte [rep_q], 0
        mov     byte [keyn], 0
        call    build_hello
        mov     al, G_HELLO
        mov     dx, cs
        mov     si, hellobuf
        call    txq_put
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
.t:     mov     ax, [now]
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
        mov     byte [pend_msg], 0
        mov     al, [g_seq]
        inc     al
        mov     [g_seq], al
        mov     di, txframe
        mov     byte [di], 47h
        mov     byte [di+1], G_POLL
        mov     [di+2], al
        mov     al, [p_ack]
        mov     [di+3], al
        mov     word [di+4], 0
        mov     si, txframe+1
        mov     cx, 5
        mov     ax, 0FFFFh
        call    crc16
        mov     [txframe+6], ax
        mov     word [txlen], 8
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
        mov     byte [di], 47h
        mov     [di+1], ah
        mov     [di+2], al
        mov     al, [p_ack]
        mov     [di+3], al
        mov     [di+4], cx
        add     di, 6
        push    ds
        mov     si, [bx+4]
        add     si, [bx+8]
        mov     ds, [bx+2]
        push    cx
        rep     movsb
        pop     cx
        pop     ds
        push    cx
        mov     si, txframe+1
        add     cx, 5
        mov     ax, 0FFFFh
        call    crc16
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
lw_go:  mov     bl, [nano]
        mov     al, 1                   ; EOI with the last byte
        mov     ah, 02h
        call    gg_call
        jnc     .ok
        jmp     link_fail
.ok:    mov     ax, [now]
        mov     [t_sent], ax
        mov     byte [lstate], LS_WAIT
        mov     byte [spoll_errs], 0
        call    pit_mark
        ret

; NAK the Pi's last answer (it was damaged); our pending fragment stays
link_write_nak:
        mov     di, nakframe
        mov     byte [di], 47h
        mov     byte [di+1], G_NAK
        mov     al, [g_seq]
        mov     [di+2], al
        mov     al, [p_ack]
        mov     [di+3], al
        mov     word [di+4], 0
        mov     si, nakframe+1
        mov     cx, 5
        mov     ax, 0FFFFh
        call    crc16
        mov     [nakframe+6], ax
        mov     si, nakframe
        mov     cx, 8
        jmp     lw_go

link_wait:
        mov     ax, [now]
        sub     ax, [t_sent]
        cmp     ax, 40                  ; ~2 s without an answer
        jbe     .t
        jmp     link_fail
.t:     mov     ah, 0Bh                 ; SRQ since the last call?
        call    gg_call
        jc      .chk
        or      ax, ax
        jnz     .poll
.chk:   call    pit_due                 ; else poll every few ms
        jnc     .x
.poll:  call    pit_mark
        mov     bl, [nano]
        mov     ah, 05h
        call    gg_call                 ; AL = status byte
        jc      .perr
        mov     byte [spoll_errs], 0
        test    al, 40h
        jz      .x
        test    al, 20h                 ; patched bridge: the line is complete
        jnz     .read
        and     ax, 1Fh                 ; stock bridge: wait as the Pi asked
        mov     cx, ax
        call    delay_ms
.read:  call    link_read
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
        mov     ah, 03h
        call    gg_call
        jc      .bad
        mov     [rxn], cx
        call    find_frame
        jc      .bad
        call    took_answer
        ret
.bad:   mov     byte [nak_pending], 1
        mov     byte [lstate], LS_IDLE
        inc     word [n_bad]
        ret

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
        cmp     cx, 246
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
        call    crc16
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
        call    pi_frame
        ret

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

; queue a message: AL = type, DX:SI = body, CX = length
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

; CRC-16/CCITT-FALSE.  AX = crc, DS:SI -> data, CX = count.  Destroys BX SI CX.
crc16:  jcxz    .x
.l:     mov     bl, ah
        xor     bl, [si]
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
