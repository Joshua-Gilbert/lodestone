; =====================================================================
;  GPIBLOOP.COM 1.6 - which GPIB byte loop is fastest on the 1520, and at
;  which alignment.
;  Build:  nasm -f bin -o GPIBLOOP.COM GPIBLOOP.ASM
;  Usage:  GPIBLOOP [a]      a = the echo device's address (default 7)
;
;  The other end must echo, as for GPIBXFER: the Pico bridge with the
;  gpib-bridge daemon's thrutest handler (on the Pi: sudo systemctl stop
;  gridlink; sudo systemctl start gpib-bridge; afterwards the other way).
;
;  The kernel's fast loops (os/src/KGPIB.INC) lost 4-10 % when the kernel
;  above them grew by an odd number of bytes: the 286 fetches words, and a
;  jump to an odd address costs another fetch.  So each loop here is in
;  twice, starting at an even and at an odd address (every label inside
;  flips), and timed on the PIT (channel 0 in mode 2 while it runs) from
;  the message's first byte to its last:
;    read  K  the kernel's gp_fast_read (count and LF stop in memory)
;    read  R  the count in CX (LOOP), no LF stop, END ends it
;    write K  the kernel's gp_fast_write (INC of a word in memory a byte)
;    write R  without it
;  1.1 (after 1.0 on the 1520: read K 70 KB/s, R 129; write K 77, R 88):
;    read  K and R at their faster alignment, and 2: R with the spin out
;          of line (a byte that is there costs no taken jump but LOOP's)
;    write K and R as before, 2 (the same for writes), and 2 with AUXRB's
;          TRI bit: T1, the 7210's settling time before DAV, 500 ns
;          instead of 2 us after the first byte (three-state drivers)
;  1.2 (after 1.1: read 2 152 KB/s even; write 2 77, TRI no change, R 88 --
;       the write's first poll mostly misses, so its spin belongs inline):
;    read  2 as the reference, and 3: END tested on the same ISR1 read
;          as DI (no OR into the shadow, no AND per byte)
;    write R as the reference; 3: the next byte fetched while the bus
;          handshakes, so DO -> OUT is three instructions; 4: 3 with the
;          poll at its tightest (no time-out count: a bench figure only)
;  1.3 (after 1.2: read 3 76 KB/s, its first poll too early; write 3 94,
;       4 119 -- the poll's own length is what counts):
;    read  2 as the reference; 4: the byte count in SI and the poll
;          IN / TEST / LOOPZ with CX as its time-out (65536 polls), so it
;          is as tight as write 4's and still ends
;    write 4 as the reference; 5: the same LOOPZ poll on DO alone (ERR,
;          no listener, ends it by the time-out), the count in DI
;  1.4 (after 1.3: read 4 129, write 5 101 -- slower than 2 and 4: the
;       loops are CPU-bound, every clock counts, and a poll that misses
;       costs its whole length):
;    read  2 as the reference; 5: 2 with its wait unrolled, IN / TEST /
;          JNZ four times a count, the shortest a poll that misses can be
;    write 4 as the reference; 7: the same unrolled wait on DO alone
;          (ERR ends it by the time-out), straight to the OUT
;  1.5 (after 1.4: read 5 = 2, so a read's first poll never misses; write
;       7 110 against 4's 119 -- a taken jump costs ~0.6 us here, and 4's
;       first poll mostly hits and falls through):
;    read  2 alone (the reference)
;    write 4 as the reference; 8: 4 exactly while the first poll hits
;          (on DO alone), the unrolled wait of 7 out of line for a miss
;  1.6 (after 1.5: write 8 107 -- 4's first poll often misses, and its
;       retry, one taken jump, is what makes it fast):
;    write 4 as the reference; 9: 4's loop with the count just above it,
;          so a miss is still one taken jump (JZ back to DEC / JZ / IN),
;          DO alone, the count reset per byte while the bus handshakes
;  4096-byte messages; the rounds go through every loop in turn, 6 times,
;  and each loop's median is shown, in ns a byte and KB/s, with the
;  parity of its spin loop's label (.w) and of the label it jumps to for a
;  byte (.g).  Every echo read is checked against what was sent.
;
;  Chip-level like GPIBXFER; at the end GRIDGPIB, if loaded, sets the chip up
;  again (INT 60h AH=01h: rearm.inc).
;  Appends what it prints to GPIBLOOP.TXT.
; =====================================================================
cpu 286
org 100h

%include "direct_equ.inc"

MSGLEN  equ 4096
ROUNDS  equ 6
AUXRA_HOLDEND equ 82h
T_XFER  equ 36

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
        mov     di, txbuf               ; the message: every byte value
        xor     cx, cx
.f:     mov     al, cl
        mov     ah, ch
        shr     ah, 3
        add     al, ah
        stosb
        inc     cx
        cmp     cx, MSGLEN
        jb      .f
        call    pit_init
        call    d_recover

        mov     cx, ROUNDS
        xor     bp, bp                  ; BP = round * 2
.r:     push    cx
        xor     bx, bx                  ; read loops (each after a write by W0)
.rv:    push    bx
        mov     bx, 0
        call    msg_out
        pop     bx
        jc      .fo
        push    bx
        call    msg_in
        pop     bx
        jc      .fi
        call    check_echo
        mov     si, bx                  ; rres[variant][round]
        imul    si, si, ROUNDS
        add     si, bp
        mov     [rres+si], ax
        add     bx, 2
        cmp     bx, 2 * NR
        jb      .rv
        xor     bx, bx                  ; write loops (each read by R0)
.wv:    push    bx
        call    msg_out
        pop     bx
        jc      .fo
        mov     si, bx
        imul    si, si, ROUNDS
        add     si, bp
        mov     [wres+si], ax
        push    bx
        mov     bx, 0
        call    msg_in
        pop     bx
        jc      .fi
        call    check_echo
        add     bx, 2
        cmp     bx, 2 * NW
        jb      .wv
        pop     cx
        add     bp, 2
        loop    .r

        mov     dx, s_rhead
        call    out_str
        xor     bx, bx
.pr:    mov     si, bx
        imul    si, si, ROUNDS
        add     si, rres
        mov     di, [rname+bx]
        mov     al, [rpar+bx]
        mov     ah, [rpar+bx+1]
        call    report
        add     bx, 2
        cmp     bx, 2 * NR
        jb      .pr
        mov     dx, s_whead
        call    out_str
        xor     bx, bx
.pw:    mov     si, bx
        imul    si, si, ROUNDS
        add     si, wres
        mov     di, [wname+bx]
        mov     al, [wpar+bx]
        mov     ah, [wpar+bx+1]
        call    report
        add     bx, 2
        cmp     bx, 2 * NW
        jb      .pw
        mov     dx, s_bad
        call    out_str
        mov     ax, [nbad]
        call    out_dec
        call    out_crlf
        jmp     short done
.fo:    pop     cx
        mov     dx, s_fo
        jmp     short .ff
.fi:    pop     cx
        mov     dx, s_fi
.ff:    call    out_str
        mov     al, [why]
        call    out_hex
        call    out_crlf
done:   call    pit_done
        call    d_recover
        mov     dx, s_done
        call    out_str
        call    d_rearm                 ; (X55: the driver's IMR2, IFC, REN)
        call    save_log
        mov     ax, 4C00h
        int     21h

; the echo in rxbuf against txbuf (count the bad ones)
check_echo:
        push    cx
        push    si
        push    di
        mov     si, txbuf
        mov     di, rxbuf
        mov     cx, MSGLEN
        repe    cmpsb
        je      .x
        inc     word [nbad]
.x:     pop     di
        pop     si
        pop     cx
        ret

; SI = ROUNDS words of ns/byte (0FFFFh: failed), DI = name, AL/AH = the
; parity of .w / .g: "name  w odd g even:  nnnnn ns a byte, nn KB/s"
report: push    bx
        push    ax
        mov     dx, di
        call    out_str
        pop     ax
        push    ax
        mov     dx, s_weven
        test    al, 1
        jz      .a
        mov     dx, s_wodd
.a:     call    out_str
        pop     ax
        mov     dx, s_geven
        test    ah, 1
        jz      .b
        mov     dx, s_godd
.b:     call    out_str
        push    si
        mov     di, srt                 ; the median of the rounds
        mov     cx, ROUNDS
        rep     movsw
        pop     si
        call    sort
        mov     ax, [srt + ROUNDS - 2 + 2] ; (the 4th of 6)
        cmp     ax, 0FFFFh
        jne     .n
        mov     dx, s_failed
        call    out_str
        jmp     short .x
.n:     push    ax
        call    out_dec
        mov     dx, s_ns
        call    out_str
        pop     cx
        mov     dx, 000Eh               ; 976562 (0EE6B2h) / ns = KB/s
        mov     ax, 0E6B2h
        div     cx
        call    out_dec
        mov     dx, s_kbs
        call    out_str
        mov     ax, [srt]               ; and the spread: best .. worst
        call    out_dec
        mov     al, '-'
        call    out_chr
        mov     ax, [srt + 2 * ROUNDS - 2]
        call    out_dec
        mov     dx, s_close
        call    out_str
.x:     pop     bx
        ret

; ---- one message out with write loop BX -> AX = ns a byte; CF on failure
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
        cmp     byte [wtri+bx], 0       ; TRI: T1 500 ns after the first byte
        je      .nt
        mov     dx, R_AUXMR
        mov     al, 0A4h                ; AUXRB: TRI
        out     dx, al
.nt:    call    d_do_gts
        mov     byte [why], 2
        mov     dx, R_ISR1              ; the chip ready for the first byte
        mov     bh, [shadow1]
        mov     cx, T_XFER
        push    bx
        call    d_tmo_start
        pop     bx
.w0:    in      al, dx
        or      bh, al
        test    bh, ISR1_DO | ISR1_ERR
        jnz     .g0
        call    d_tmo_check
        jnc     .w0
        jmp     short .f
.g0:    test    bh, ISR1_ERR
        jnz     .f
        push    bx
        call    stamp
        pop     bx
        mov     [t0], ax
        mov     [t0+2], dx
        mov     si, txbuf
        mov     cx, MSGLEN - 1          ; all but the last (it has EOI)
        mov     word [v_done], 0
        push    bx
        xor     bh, bh
        mov     ax, [wvar+bx]
        pop     bx
        mov     byte [why], 3
        call    ax                      ; ES:SI, CX, BH = the shadow
        jc      .f
        mov     [shadow1], bh
        mov     byte [why], 4
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
.f:     call    no_tri
        mov     byte [shadow1], 0
        stc
        ret
.ok:    call    stamp
        call    no_tri
        mov     cx, MSGLEN
        jmp     per_byte

no_tri: push    ax                      ; AUXRB back to its default
        push    dx
        mov     dx, R_AUXMR
        mov     al, 0A0h
        out     dx, al
        pop     dx
        pop     ax
        ret

; ---- one echo in with read loop BX -> AX = ns a byte; CF on failure
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
        push    bx
        mov     cx, T_XFER              ; the first byte: up to ~2 s (the Pi
        call    d_tmo_start             ;  answers)
        pop     bx
        call    d_do_gts
        mov     byte [why], 12h
        mov     dx, R_ISR1
        xor     ah, ah
.w0:    in      al, dx
        or      ah, al
        test    ah, ISR1_DI
        jnz     .g0
        push    ax
        call    d_tmo_check
        pop     ax
        jnc     .w0
        jmp     short .f
.g0:    mov     [v_bh], ah
        push    bx
        call    stamp
        pop     bx
        mov     [t0], ax
        mov     [t0+2], dx
        mov     di, rxbuf
        mov     cx, MSGLEN + 16         ; (END ends it)
        mov     word [v_done], 0
        mov     word [v_count], MSGLEN + 16
        mov     byte [v_lfstop], 0
        mov     ax, [rvar+bx]
        mov     bh, [v_bh]
        mov     byte [why], 13h
        call    ax                      ; ES:DI, CX, BH = the shadow
        jc      .f
        call    stamp
        push    ax
        push    dx
        mov     byte [shadow1], 0
        call    d_rd_end
        mov     al, UNT
        call    d_send_cmd
        mov     al, UNL
        call    d_send_cmd
        pop     dx
        pop     ax
        mov     cx, di
        sub     cx, rxbuf
        cmp     cx, MSGLEN
        jne     .short
        jmp     per_byte
.short: mov     byte [why], 14h
.f:     mov     byte [shadow1], 0
        call    d_rd_end
        mov     al, UNT
        call    d_send_cmd
        mov     al, UNL
        call    d_send_cmd
        stc
        ret

; DX:AX = the end stamp, [t0] the start, CX = bytes -> AX = ns a byte
per_byte:
        sub     ax, [t0]
        sbb     dx, [t0+2]
        cmp     dx, 4                   ; (over 220 ms: not a 4 KB transfer)
        jae     .long
        mov     bx, dx
        push    cx
        mov     cx, 838                 ; 0.838 us a PIT count
        mul     cx                      ; DX:AX = ns (the low word's)
        imul    bx, bx, 838             ;  and the high word's, * 65536
        add     dx, bx
        pop     cx
        cmp     dx, cx
        jae     .long
        div     cx
        clc
        ret
.long:  mov     ax, 0FFFEh
        clc
        ret

; =====================================================================
;  The loops.  In: DX = R_ISR1, BH = ISR1's shadow (with the first DI or
;  DO already in it), ES = DS.  Read: ES:DI, CX = room.  Write: SI, CX =
;  bytes.  CF on a timeout (20000 spins, as the kernel's).
; =====================================================================
%macro RK 1                             ; the kernel's gp_fast_read
%1:     mov     dx, R_ISR1
%1_n:   mov     ax, [v_done]
        add     ax, 3
        cmp     ax, [v_count]
        ja      %1_slow
        mov     si, 20000
%1_w:   in      al, dx
        or      bh, al
        test    bh, ISR1_DI
        jnz     %1_g
        dec     si
        jnz     %1_w
        jmp     short %1_slow
%1_g:   mov     ah, bh
        and     bh, ~(ISR1_DI | ISR1_END)
        mov     dh, R_DIR >> 8
        in      al, dx
        mov     dh, R_ISR1 >> 8
        stosb
        inc     word [v_done]
        cmp     al, 0Ah
        jne     %1_ne
        test    byte [v_lfstop], 1
        jz      %1_ne
        jmp     short %1_stop
%1_ne:  test    ah, ISR1_END
        jz      %1_n
%1_stop: clc
        ret
%1_slow: stc
        ret
%endmacro

%macro RR 1                             ; the count in CX
%1:     mov     dx, R_ISR1
%1_n:   mov     si, 20000
%1_w:   in      al, dx
        or      bh, al
        test    bh, ISR1_DI
        jnz     %1_g
        dec     si
        jnz     %1_w
        stc
        ret
%1_g:   mov     dh, R_DIR >> 8
        in      al, dx
        mov     dh, R_ISR1 >> 8
        stosb
        test    bh, ISR1_END
        jnz     %1_x
        and     bh, ~ISR1_DI
        loop    %1_n
%1_x:   clc
        ret
%endmacro

%macro R2 1                             ; the spin out of line
%1:     mov     dx, R_ISR1
%1_w:   in      al, dx
        or      bh, al
        test    bh, ISR1_DI
        jz      %1_s
%1_g:   mov     dh, R_DIR >> 8
        in      al, dx
        mov     dh, R_ISR1 >> 8
        stosb
        test    bh, ISR1_END
        jnz     %1_x
        and     bh, ~ISR1_DI
        loop    %1_w
%1_x:   clc
        ret
%1_s:   mov     si, 20000
%1_s2:  in      al, dx
        or      bh, al
        test    bh, ISR1_DI | ISR1_END
        jnz     %1_e
        dec     si
        jnz     %1_s2
        stc
        ret
%1_e:   test    bh, ISR1_DI
        jnz     %1_g
        clc                             ; END after the last DI: the end
        ret
%endmacro

%macro W2 1                             ; the spin out of line (ERR there)
%1:     push    di
        mov     dx, R_ISR1
        jmp     short %1_put
%1_w:   in      al, dx
        or      bh, al
        test    bh, ISR1_DO
        jz      %1_s
%1_put: and     bh, ~ISR1_DO
        es lodsb
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        loop    %1_w
        pop     di
        clc
        ret
%1_s:   test    bh, ISR1_ERR
        jnz     %1_f
        mov     di, 20000
%1_s2:  in      al, dx
        or      bh, al
        test    bh, ISR1_DO | ISR1_ERR
        jnz     %1_e
        dec     di
        jnz     %1_s2
%1_f:   pop     di
        stc
        ret
%1_e:   test    bh, ISR1_ERR
        jnz     %1_f
        jmp     short %1_put
%endmacro

%macro R3 1                             ; END from the same ISR1 read
%1:     mov     dx, R_ISR1
%1_w:   in      al, dx
        test    al, ISR1_DI
        jz      %1_s
        test    al, ISR1_END
        jnz     %1_l
%1_g:   mov     dh, R_DIR >> 8
        in      al, dx
        mov     dh, R_ISR1 >> 8
        stosb
        loop    %1_w
        clc
        ret
%1_l:   or      bh, al                  ; the last byte
        and     bh, ~ISR1_DI
        mov     dh, R_DIR >> 8
        in      al, dx
        stosb
        clc
        ret
%1_s:   or      bh, al
        test    bh, ISR1_DI | ISR1_END
        jnz     %1_e
        mov     si, 20000
%1_s2:  in      al, dx
        or      bh, al
        test    bh, ISR1_DI | ISR1_END
        jnz     %1_e
        dec     si
        jnz     %1_s2
        stc
        ret
%1_e:   test    bh, ISR1_DI
        jz      %1_x
        mov     al, bh
        and     bh, ~(ISR1_DI | ISR1_END)
        test    al, ISR1_END
        jz      %1_g
        mov     bh, al
        jmp     short %1_l
%1_x:   clc                             ; END after the last DI: the end
        ret
%endmacro

%macro W3 1                             ; the next byte fetched early
%1:     push    di
        mov     dx, R_ISR1
        and     bh, ~ISR1_DO
        es lodsb
        mov     ah, al
        jmp     short %1_put
%1_n:   mov     di, 20000
%1_w:   in      al, dx
        test    al, ISR1_DO | ISR1_ERR
        jnz     %1_g
        dec     di
        jnz     %1_w
        jmp     short %1_out
%1_g:   test    al, ISR1_ERR
        jnz     %1_e
%1_put: mov     al, ah
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        es lodsb                        ; (one past the end on the last)
        mov     ah, al
        loop    %1_n
        dec     si
        pop     di
        clc
        ret
%1_e:   or      bh, al
%1_out: pop     di
        stc
        ret
%endmacro

%macro W4 1                             ; 3 with no time-out count
%1:     mov     dx, R_ISR1
        and     bh, ~ISR1_DO
        es lodsb
        mov     ah, al
        jmp     short %1_put
%1_w:   in      al, dx
        test    al, ISR1_DO | ISR1_ERR
        jz      %1_w
        test    al, ISR1_ERR
        jnz     %1_e
%1_put: mov     al, ah
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        es lodsb
        mov     ah, al
        loop    %1_w
        dec     si
        clc
        ret
%1_e:   or      bh, al
        stc
        ret
%endmacro

%macro R4 1                             ; LOOPZ poll, the count in SI
%1:     push    si
        mov     si, cx
        mov     dx, R_ISR1
        mov     al, bh                  ; the first DI may be in the shadow
        and     bh, ~ISR1_DI
        test    al, ISR1_DI
        jnz     %1_g
%1_n:   xor     cx, cx                  ; 65536 polls, then give up
%1_w:   in      al, dx
        test    al, ISR1_DI
        loopz   %1_w
        jz      %1_t
%1_g:   mov     ah, al
        mov     dh, R_DIR >> 8
        in      al, dx
        mov     dh, R_ISR1 >> 8
        stosb
        test    ah, ISR1_END
        jnz     %1_x
        dec     si
        jnz     %1_n
%1_x:   or      bh, ah
        and     bh, ~ISR1_DI
        pop     si
        clc
        ret
%1_t:   or      bh, al                  ; a late END (no DI): the end
        test    bh, ISR1_END
        jnz     %1_x
        pop     si
        stc
        ret
%endmacro

%macro W5 1                             ; LOOPZ poll on DO, the count in DI
%1:     push    di
        mov     di, cx
        mov     dx, R_ISR1
        and     bh, ~ISR1_DO
        es lodsb
        mov     ah, al
        jmp     short %1_put
%1_n:   xor     cx, cx                  ; 65536 polls, then give up
%1_w:   in      al, dx
        test    al, ISR1_DO
        loopz   %1_w
        jz      %1_t
%1_put: mov     al, ah
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        es lodsb                        ; (one past the end on the last)
        mov     ah, al
        dec     di
        jnz     %1_n
        dec     si
        pop     di
        clc
        ret
%1_t:   or      bh, al                  ; (ERR: no listener)
        dec     si
        pop     di
        stc
        ret
%endmacro

%macro R5 1                             ; 2 with the wait unrolled
%1:     mov     dx, R_ISR1
%1_w:   in      al, dx
        or      bh, al
        test    bh, ISR1_DI
        jz      %1_s
%1_g:   mov     dh, R_DIR >> 8
        in      al, dx
        mov     dh, R_ISR1 >> 8
        stosb
        test    bh, ISR1_END
        jnz     %1_x
        and     bh, ~ISR1_DI
        loop    %1_w
%1_x:   clc
        ret
%1_s:   mov     si, 16384               ; 65536 polls, then give up
%1_s2:  in      al, dx
        test    al, ISR1_DI | ISR1_END
        jnz     %1_h
        in      al, dx
        test    al, ISR1_DI | ISR1_END
        jnz     %1_h
        in      al, dx
        test    al, ISR1_DI | ISR1_END
        jnz     %1_h
        in      al, dx
        test    al, ISR1_DI | ISR1_END
        jnz     %1_h
        dec     si
        jnz     %1_s2
        stc
        ret
%1_h:   or      bh, al
        test    bh, ISR1_DI
        jnz     %1_g
        clc                             ; END after the last DI: the end
        ret
%endmacro

%macro W7 1                             ; 4 with the wait unrolled
%1:     push    di
        mov     dx, R_ISR1
        and     bh, ~ISR1_DO
        es lodsb
        mov     ah, al
        jmp     short %1_put
%1_w:   in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        mov     di, 16384               ; then 65536 polls, then give up
%1_s:   in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        dec     di
        jnz     %1_s
        or      bh, al                  ; (ERR: no listener)
        dec     si
        pop     di
        stc
        ret
%1_put: mov     al, ah
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        es lodsb                        ; (one past the end on the last)
        mov     ah, al
        loop    %1_w
        dec     si
        pop     di
        clc
        ret
%endmacro

%macro W8 1                             ; 4 with the wait out of line
%1:     push    di
        mov     dx, R_ISR1
        and     bh, ~ISR1_DO
        es lodsb
        mov     ah, al
        jmp     short %1_put
%1_w:   in      al, dx
        test    al, ISR1_DO
        jz      %1_m
%1_put: mov     al, ah
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        es lodsb                        ; (one past the end on the last)
        mov     ah, al
        loop    %1_w
        dec     si
        pop     di
        clc
        ret
%1_m:   mov     di, 16384               ; 65536 polls, then give up
%1_s:   in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        in      al, dx
        test    al, ISR1_DO
        jnz     %1_put
        dec     di
        jnz     %1_s
        or      bh, al                  ; (ERR: no listener)
        dec     si
        pop     di
        stc
        ret
%endmacro

%macro W9 1                             ; 4 with the count above the poll
%1:     push    di
        mov     dx, R_ISR1
        and     bh, ~ISR1_DO
        es lodsb
        mov     ah, al
        jmp     short %1_put
%1_r:   dec     di                      ; a miss: one taken jump, as in 4
        jz      %1_t
%1_w:   in      al, dx
        test    al, ISR1_DO
        jz      %1_r
%1_put: mov     al, ah
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        es lodsb                        ; (one past the end on the last)
        mov     ah, al
        xor     di, di                  ; 65535 misses, then give up
        loop    %1_w
        dec     si
        pop     di
        clc
        ret
%1_t:   or      bh, al                  ; (ERR: no listener)
        dec     si
        pop     di
        stc
        ret
%endmacro

%macro WK 1                             ; the kernel's gp_fast_write
%1:     push    di
        mov     dx, R_ISR1
        jmp     short %1_put            ; (the first byte's DO is in BH)
%1_n:   mov     di, 20000
%1_w:   in      al, dx
        or      bh, al
        test    bh, ISR1_DO | ISR1_ERR
        jnz     %1_g
        dec     di
        jnz     %1_w
        jmp     short %1_out
%1_g:   test    bh, ISR1_ERR
        jnz     %1_out
%1_put: and     bh, ~ISR1_DO
        es lodsb
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        inc     word [v_done]
        loop    %1_n
        pop     di
        clc
        ret
%1_out: pop     di
        stc
        ret
%endmacro

%macro WR 1                             ; no INC in memory
%1:     push    di
        mov     dx, R_ISR1
        jmp     short %1_put
%1_n:   mov     di, 20000
%1_w:   in      al, dx
        or      bh, al
        test    bh, ISR1_DO | ISR1_ERR
        jnz     %1_g
        dec     di
        jnz     %1_w
        jmp     short %1_out
%1_g:   test    bh, ISR1_ERR
        jnz     %1_out
%1_put: and     bh, ~ISR1_DO
        es lodsb
        mov     dh, R_CDOR >> 8
        out     dx, al
        mov     dh, R_ISR1 >> 8
        loop    %1_n
        pop     di
        clc
        ret
%1_out: pop     di
        stc
        ret
%endmacro

        align   2
        nop
        R2      r21                     ; the fastest so far (.w and .g even)
        align   2
        align   2
        W4      w40                     ; the fastest so far (.w even)
        align   2
        W9      w90
        align   2
        nop
        W9      w91

NR      equ 1
NW      equ 3
rvar    dw r21
rname   dw s_r2
rpar    db (r21_w - $$) & 1, (r21_g - $$) & 1
wvar    dw w40, w90, w91
wtri    db 0, 0, 0, 0, 0, 0                 ; (by BX: words; 1 = AUXRB TRI)
wname   dw s_w4, s_w9, s_w9
wpar    db (w40_w - $$) & 1, (w40_put - $$) & 1
        db (w90_w - $$) & 1, (w90_put - $$) & 1, (w91_w - $$) & 1, (w91_put - $$) & 1

; ---- time (as GPIBIRQ) ---------------------------------------------------
pit_init:
        mov     byte [pitset], 1
        mov     al, 34h
        jmp     short pitw
pit_done:
        cmp     byte [pitset], 0
        je      pitx
        mov     byte [pitset], 0
        mov     al, 36h
pitw:   cli
        out     43h, al
        xor     al, al
        out     40h, al
        jmp     short $+2
        out     40h, al
        sti
pitx:   ret

stamp:  push    bx
        push    cx
.r:     call    d_tick
        mov     bx, ax
        cli
        xor     al, al
        out     43h, al
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

out_dec:
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

s_title db 13,10,'GPIBLOOP 1.6 - the GPIB byte loops at both alignments, echo at $'
s_rhead db 13,10,'Reading 4096 bytes (median of 6; best-worst in ns):',13,10,'$'
s_whead db 13,10,'Writing 4096 bytes:',13,10,'$'
s_rk    db '  K (the kernel',27h,'s)  $'
s_rr    db '  R (count in CX) $'
s_wk    db '  K (the kernel',27h,'s)  $'
s_wr    db '  R (no INC)      $'
s_r2    db '  2 (spin aside)  $'
s_w2    db '  2 (spin aside)  $'
s_w2t   db '  2 + TRI (T1 .5) $'
s_r3    db '  3 (END same in) $'
s_w3    db '  3 (byte early)  $'
s_w4    db '  4 (no time-out) $'
s_r4    db '  4 (LOOPZ poll)  $'
s_w5    db '  5 (LOOPZ poll)  $'
s_r5    db '  5 (wait x4)     $'
s_w7    db '  7 (wait x4)     $'
s_w8    db '  8 (miss aside)  $'
s_w9    db '  9 (count above) $'
s_weven db '.w even $'
s_wodd  db '.w odd  $'
s_geven db '.g even:  $'
s_godd  db '.g odd:   $'
s_ns    db ' ns a byte, $'
s_kbs   db ' KB/s  ($'
s_close db ')',13,10,'$'
s_failed db 'FAILED',13,10,'$'
s_bad   db 13,10,'echoes that differed from what was sent: $'
s_fo    db 13,10,'sending failed, step $'
s_fi    db 13,10,'receiving failed, step $'
s_done  db 13,10,'Done.  GRIDGPIB, if loaded, set up again.  Also in GPIBLOOP.TXT.',13,10,'$'
s_logname db 'GPIBLOOP.TXT',0

RBUFLEN equ 80
LOGMAX  equ 1536
dev     db 7
why     db 0
pitset  db 0
v_bh    db 0
v_lfstop db 0
        align 2
v_done  dw 0
v_count dw 0
nbad    dw 0
t0      dw 0, 0
rres    times NR * ROUNDS dw 0FFFFh
wres    times NW * ROUNDS dw 0FFFFh
srt     times ROUNDS dw 0
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
        align 2
txbuf   times MSGLEN db 0
rxbuf:                                  ; MSGLEN + 16 (past the end of the file)
