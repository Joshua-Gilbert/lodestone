; direct uPD7210 access (GPIBTEST 1.0 primitives, labels prefixed d_)
d_chip_init:
        mov     dx, R_AUXMR
        mov     al, AUX_CR              ; chip reset
        out     dx, al
        mov     al, 28h                 ; ICR: 8 MHz clock (as DRVR488)
        out     dx, al
        xor     al, al
        mov     dx, R_IMR1
        out     dx, al
        mov     dx, R_IMR2
        out     dx, al
        mov     dx, R_SPMR
        out     dx, al
        mov     dx, R_ADMR
        mov     al, 31h                 ; mode 1, TRM1/TRM0 = normal
        out     dx, al
        mov     dx, R_ADR
        mov     al, MYADDR              ; primary address, talk+listen
        out     dx, al
        mov     al, 0E0h                ; ADR1: disabled
        out     dx, al
        mov     dx, R_ADR1
        mov     al, 0Ah                 ; EOS = LF (not enabled by default)
        out     dx, al
        mov     dx, R_AUXMR
        mov     al, 80h                 ; AUXRA: normal handshake
        out     dx, al
        mov     al, 0A0h                ; AUXRB: defaults
        out     dx, al
        mov     al, AUX_PON             ; leave reset state
        out     dx, al
        ret

; wait for the next BIOS d_tick (>= 0..55 ms)
d_wait_tick:
        push    ax
        push    bx
        call    d_tick
        mov     bx, ax
.w:     call    d_tick
        cmp     ax, bx
        je      .w
        pop     bx
        pop     ax
        ret

d_tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

; start a timeout of CX ticks
d_tmo_start:
        push    ax
        call    d_tick
        mov     [t_start], ax
        mov     [t_len], cx
        pop     ax
        ret

; CF=1 if the timeout has expired
d_tmo_check:
        push    ax
        call    d_tick
        sub     ax, [t_start]
        cmp     ax, [t_len]
        pop     ax
        cmc                             ; ax>=len -> NC -> make it CY
        ret

; take control (ATN on).  Only when in standby (ADSR bit 6 set), exactly
; like Driver488; the stale CO is dropped so we wait for a fresh one.
d_cmd_begin:
        push    ax
        push    dx
        mov     dx, R_ADSR
        in      al, dx
        test    al, 40h
        jz      .x                      ; already active: nothing to do
        and     byte [shadow2], ~ISR2_CO
        mov     dx, R_AUXMR
        mov     al, AUX_TCA
        out     dx, al
.x:     pop     dx
        pop     ax
        ret

; go to standby (ATN off); CO seen so far is stale afterwards
d_do_gts: push    ax
        push    dx
        and     byte [shadow2], ~ISR2_CO
        mov     dx, R_AUXMR
        mov     al, AUX_GTS
        out     dx, al
        pop     dx
        pop     ax
        ret

; send command byte AL with ATN asserted; CF=1 on timeout.
; Consumes CO from the shadow only when the byte is written.
d_send_cmd:
        call    d_wait_co
        jc      .x
        push    dx
        and     byte [shadow2], ~ISR2_CO
        mov     dx, R_CDOR
        out     dx, al
        pop     dx
        clc
.x:     ret

; d_send_cmd with one recovery attempt
d_send_cmd_r:
        call    d_send_cmd
        jnc     .x
        call    d_recover
        call    d_send_cmd
.x:     ret

; serial poll address BL -> AL = status, CF=1 if nobody answered.
d_spoll:  push    bx
        push    cx
        push    dx
        call    d_ensure_ctrl
        mov     dx, R_AUXMR
        mov     al, 91h                 ; AUXRA: RFD holdoff on all data
        out     dx, al
        mov     al, UNL
        call    d_send_cmd
        jc      .fail
        mov     al, 20h+MYADDR          ; MLA
        call    d_send_cmd
        jc      .fail
        mov     al, bl
        or      al, 40h                 ; TAD
        call    d_send_cmd
        jc      .fail
        mov     al, SPE
        call    d_send_cmd
        jc      .fail
        call    d_wait_co
        jc      .fail
        call    d_clear_in                ; forget any stale DI / DIR byte
        call    d_do_gts
        mov     word [lat], 0
        mov     cx, T_SPOLL
        call    d_tmo_start
.w:     inc     word [lat]
        mov     ah, ISR1_DI
        call    d_isr1_test
        jnz     .got
        call    d_tmo_check
        jnc     .w
        jmp     .fail
.got:   mov     [rawisr1], al
        mov     dx, R_ADSR
        in      al, dx
        mov     [rawadsr], al
        mov     dx, R_DIR
        in      al, dx                  ; status byte (handshake held)
        mov     [rawdir], al
        call    d_spoll_end
        mov     al, [rawdir]
        clc
        jmp     .x
.fail:  call    d_spoll_end
        stc
.x:     pop     dx
        pop     cx
        pop     bx
        ret

; common exit: take control asynchronously (safe: RFD is held, nothing
; can be in flight), release the holdoff, normal handshake, SPD, UNT
d_spoll_end:
        call    d_cmd_begin               ; TCA (standby -> active)
        mov     dx, R_AUXMR
        mov     al, 03h                 ; release RFD holdoff
        out     dx, al
        mov     al, 90h                 ; AUXRA: normal handshake
        out     dx, al
        call    d_wait_co
        jnc     .ok
        call    d_recover
.ok:    mov     al, SPD
        call    d_send_cmd
        mov     al, UNT
        call    d_send_cmd
        ret

; make sure we hold ATN and the chip takes commands; d_recover if not
d_ensure_ctrl:
        push    ax
        push    dx
        call    d_cmd_begin
        call    d_wait_co
        jnc     .ok
        call    d_recover
.ok:    pop     dx
        pop     ax
        ret

; clear ISR1 latches (two reads), the software shadow and DIR
d_clear_in:
        push    ax
        push    dx
        mov     dx, R_ISR1
        in      al, dx
        in      al, dx
        mov     byte [shadow1], 0
        mov     dx, R_DIR
        in      al, dx
        pop     dx
        pop     ax
        ret

; re-initialise the chip and the bus (IFC), count it
d_recover:
        push    ax
        push    dx
        inc     word [recov]
        mov     byte [shadow2], 0
        mov     byte [shadow1], 0
        call    d_chip_init
        mov     dx, R_AUXMR
        mov     al, AUX_SIFC
        out     dx, al
        call    d_wait_tick
        mov     al, AUX_CIFC
        out     dx, al
        mov     al, AUX_SREN
        out     dx, al
        mov     byte [shadow1], 0
        call    d_wait_co
        pop     dx
        pop     ax
        ret

; Read ISR1 into the software shadow (the register clears on read; when
; DI/DO are set Driver488 reads it a second time and ORs the result).
; AH = bits to test.  Returns AL = shadow before clearing, ZF=0 if any
; tested bit was set (those bits are then removed from the shadow).
d_isr1_test:
        push    dx
        mov     dx, R_ISR1
        cli
        in      al, dx
        test    al, 03h
        jz      .one
        mov     dx, R_ISR1
        push    ax
        in      al, dx
        pop     dx
        or      al, dl
        mov     dx, R_ISR1
.one:   or      al, [shadow1]
        sti
        test    al, ah
        jz      .none
        push    ax
        not     ah
        and     al, ah
        mov     [shadow1], al
        pop     ax
        or      ah, 0FFh                ; ZF=0
        pop     dx
        ret
.none:  mov     [shadow1], al
        cmp     al, al                  ; ZF=1
        pop     dx
        ret

; wait until CO is in the ISR2 shadow (peek - does NOT consume it)
d_wait_co:
        push    ax
        push    cx
        push    dx
        mov     cx, T_CMD
        call    d_tmo_start
        mov     dx, R_ISR2
.w:     in      al, dx
        or      [shadow2], al
        test    byte [shadow2], ISR2_CO
        jnz     .ok
        call    d_tmo_check
        jnc     .w
        stc
        jmp     .x
.ok:    clc
.x:     pop     dx
        pop     cx
        pop     ax
        ret

; d_query: send ASCIIZ at SI to device BL (EOI on last byte), then read the
; reply into rbuf ('$'-terminated for printing).  CF=1 if no reply.
d_query:  push    bx
        push    si
        mov     di, rbuf
        mov     word [rxcnt], 0
        call    d_cmd_begin
        mov     al, UNL
        call    d_send_cmd
        jc      .fail
        mov     al, 40h+MYADDR          ; MTA: we talk
        call    d_send_cmd
        jc      .fail
        mov     al, bl
        or      al, 20h                 ; LAD of the device
        call    d_send_cmd
        jc      .fail
        call    d_wait_co
        jc      .fail
        call    d_do_gts
.wb:    lodsb
        or      al, al
        jz      .sent
        mov     ah, al
        mov     cx, T_DATA
        call    d_tmo_start
        mov     dx, R_ISR1
.wdo:   push    ax
        mov     ah, ISR1_DO | ISR1_ERR
        call    d_isr1_test
        mov     dl, al
        pop     ax
        jz      .nodo
        test    dl, ISR1_ERR            ; no listeners
        jnz     .fail
        jmp     .put
.nodo:
        call    d_tmo_check
        jnc     .wdo
        jmp     .fail
.put:   cmp     byte [si], 0            ; last byte? -> send with EOI
        jne     .noeoi
        mov     dx, R_AUXMR
        mov     al, AUX_SEOI
        out     dx, al
.noeoi: mov     dx, R_CDOR
        mov     al, ah
        out     dx, al
        jmp     .wb
.sent:  mov     cx, T_DATA              ; wait for the last byte to go
        call    d_tmo_start
        mov     dx, R_ISR1
.wl:    push    ax
        mov     ah, ISR1_DO
        call    d_isr1_test
        pop     ax
        jnz     .rd
        call    d_tmo_check
        jnc     .wl
        jmp     .fail
        ; ---- now read the answer ----
.rd:    mov     word [rxcnt], 0
        call    d_cmd_begin
        mov     al, UNL
        call    d_send_cmd
        jc      .fail
        mov     al, 20h+MYADDR          ; MLA
        call    d_send_cmd
        jc      .fail
        mov     al, bl
        or      al, 40h                 ; TAD
        call    d_send_cmd
        jc      .fail
        call    d_wait_co
        jc      .fail
        call    d_clear_in
        mov     dx, R_AUXMR
        mov     al, 96h                 ; AUXRA: RFD holdoff on END (LF=END)
        out     dx, al
        call    d_do_gts
        mov     di, rbuf
.rb:    mov     cx, T_DATA
        call    d_tmo_start
.wdi:   mov     ah, ISR1_DI
        call    d_isr1_test
        jnz     .byte
        call    d_tmo_check
        jnc     .wdi
        cmp     di, rbuf                ; timeout: fail only if nothing came
        je      .fail
        jmp     .eom
.byte:  mov     ah, al                  ; keep END flag
        mov     dx, R_DIR
        in      al, dx
        inc     word [rxcnt]
        cmp     al, 20h                 ; keep printable text only
        jb      .ctl
        cmp     al, 7Eh
        ja      .ctl
        cmp     al, '$'
        je      .ctl
        cmp     di, rbuf+RBUFLEN
        jae     .ctl
        stosb
.ctl:   test    ah, ISR1_END
        jnz     .eom
        cmp     al, 0Ah                 ; LF also ends a message
        je      .eom
        jmp     .rb
.eom:   mov     byte [di], '$'
        call    d_rd_end
        mov     al, UNT
        call    d_send_cmd
        mov     al, UNL
        call    d_send_cmd
        clc
        jmp     .x
.fail:  mov     byte [di], '$'
        call    d_rd_end
        mov     al, UNT
        call    d_send_cmd
        mov     al, UNL
        call    d_send_cmd
        stc
.x:     pop     si
        pop     bx
        ret

; read-only: address device BL to talk and read one message (no d_query)
d_query_read:
        push    bx
        push    si
        mov     di, rbuf
        jmp     d_query.rd

; end of a read: TCA is safe (RFD held on END, or nothing arrived),
; then release the holdoff and go back to the normal handshake
d_rd_end: call    d_cmd_begin
        push    ax
        push    dx
        mov     dx, R_AUXMR
        mov     al, 03h                 ; release RFD holdoff
        out     dx, al
        mov     al, 90h                 ; AUXRA: normal handshake
        out     dx, al
        pop     dx
        pop     ax
        ret

; =====================================================================
;  Automated test set
; =====================================================================
P_POLL  equ 0
P_488   equ 1
P_TEK   equ 2
P_METER equ 3
REPS    equ 10
SPREPS  equ 20

; test one device, address BL
