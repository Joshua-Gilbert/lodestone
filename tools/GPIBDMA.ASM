; =====================================================================
;  GPIBDMA.COM 1.0 - is the 1520's uPD7210 wired to a DMA channel?
;  Build:  nasm -f bin -o GPIBDMA.COM GPIBDMA.ASM
;  Usage:  GPIBDMA [n]       n = an instrument's GPIB address (default 6,
;                            the FG5010); it is sent ID? and must answer.
;
;  The 7210 raises its DRQ pin when IMR2's DMA bits allow it: DMAO (20h)
;  while it is talker with its data-out register empty, DMAI (10h) while
;  it is listener with a byte waiting in DIR.  The 8237s show the request
;  lines they see in their status registers (port 08h bits 4-7 for
;  channels 0-3, port D0h bits 4-7 for channels 4-7) whether or not the
;  channel is set up, so the test needs no DMA transfer at all: every
;  channel stays masked and nothing is ever written to memory by DMA.
;
;  For each direction it samples the request bits with the DMA bit off,
;  then on, then off again.  A bit that is set only while it is on is the
;  7210's channel.  Nothing set: DRQ isn't wired to an 8237 (or GRiD gates
;  it with something this program doesn't set).
;
;  Chip-level, like GPIBTEST: it resets the 7210 and pulses IFC at the
;  start and the end.  Then GRIDGPIB, if loaded, sets the chip up again
;  (INT 60h AH=01h: rearm.inc), since it doesn't know what was done to it.
;  Prints to the screen and appends the same to GPIBDMA.TXT.
; =====================================================================
cpu 286
org 100h

%include "direct_equ.inc"

IMR2_DMAI equ 10h
IMR2_DMAO equ 20h
SAMPLES   equ 400

start:  cld
        mov     byte [dev], 6
        mov     si, 81h                 ; the command line: an address?
.sp:    lodsb
        cmp     al, ' '
        je      .sp
        cmp     al, '0'
        jb      .go
        cmp     al, '9'
        ja      .go
        sub     al, '0'
        mov     ah, al
        lodsb
        cmp     al, '0'
        jb      .one
        cmp     al, '9'
        ja      .one
        sub     al, '0'
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
        call    d_recover

        ; ---- idle: what the 8237s show with the 7210 quiet ----------
        call    sample
        mov     [idle], ax
        mov     dx, s_idle
        call    out_str
        call    show

        ; ---- DMA out: the GRiD talker, its data-out register empty ----
        mov     dx, s_out
        call    out_str
        call    d_cmd_begin
        mov     al, UNL
        call    d_send_cmd
        jc      .nobus
        mov     al, 40h + MYADDR        ; MTA: we talk
        call    d_send_cmd
        jc      .nobus
        mov     al, [dev]
        or      al, 20h                 ; LAD of the instrument
        call    d_send_cmd
        jc      .nobus
        call    d_wait_co
        jc      .nobus
        call    d_do_gts
        call    d_wait_tick
        mov     bl, IMR2_DMAO
        call    three                   ; off, on, off
        mov     dx, R_ISR1
        in      al, dx
        mov     [isr1o], al
        mov     dx, s_isr1
        call    out_str
        mov     al, [isr1o]
        call    out_hex
        mov     dx, s_isr1do
        call    out_str
        call    verdict
        call    d_recover

        ; ---- DMA in: the instrument talks, one byte held in DIR -------
        mov     dx, s_in
        call    out_str
        mov     bl, [dev]
        mov     si, s_idq
        call    d_query                 ; it answers ID? at all?
        jnc     .ans
        mov     dx, s_noans
        call    out_str
        jmp     .end
.ans:   mov     dx, s_answer
        call    out_str
        mov     dx, rbuf
        call    out_str
        call    out_crlf
        mov     bl, [dev]               ; ID? again, and this time keep the
        mov     si, s_idq               ;  first byte of the answer in DIR
        call    dev_write
        jc      .nobus
        call    d_cmd_begin
        mov     al, UNL
        call    d_send_cmd
        jc      .nobus
        mov     al, 20h + MYADDR        ; MLA
        call    d_send_cmd
        jc      .nobus
        mov     al, [dev]
        or      al, 40h                 ; TAD
        call    d_send_cmd
        jc      .nobus
        call    d_wait_co
        jc      .nobus
        call    d_clear_in
        mov     dx, R_AUXMR
        mov     al, 81h                 ; AUXRA: RFD holdoff on every byte
        out     dx, al
        call    d_do_gts
        call    d_wait_tick             ; the first byte arrives and waits
        call    d_wait_tick
        mov     bl, IMR2_DMAI
        call    three
        mov     dx, R_ISR1
        in      al, dx
        mov     [isr1o], al
        mov     dx, R_DIR
        in      al, dx
        mov     [dirb], al
        mov     dx, s_isr1
        call    out_str
        mov     al, [isr1o]
        call    out_hex
        mov     dx, s_isr1di
        call    out_str
        mov     al, [dirb]
        call    out_hex
        mov     dx, s_dirend
        call    out_str
        call    verdict
        jmp     .end

.nobus: mov     dx, s_nobus
        call    out_str
.end:   call    d_recover
        mov     dx, s_reboot
        call    out_str
        call    d_rearm                 ; (X55: the driver's IMR2, IFC, REN)
        call    save_log
        mov     ax, 4C00h
        int     21h

; ---------------------------------------------------------------------
; the request bits: AL = port 08h bits 4-7 (channels 0-3), AH = port D0h
; bits 4-7 (channels 4-7), ORed over SAMPLES reads
sample:
        push    bx
        push    cx
        push    dx
        xor     bx, bx
        mov     cx, SAMPLES
.s:     in      al, 08h
        or      bl, al
        in      al, 0D0h
        or      bh, al
        loop    .s
        mov     ax, bx
        and     ax, 0F0F0h
        pop     dx
        pop     cx
        pop     bx
        ret

; IMR2 = 0, sample -> off1; IMR2 = BL, sample -> on; IMR2 = 0, sample -> off2
three:
        mov     dx, R_IMR2
        xor     al, al
        out     dx, al
        call    sample
        mov     [off1], ax
        mov     dx, R_IMR2
        mov     al, bl
        out     dx, al
        call    sample
        mov     [on], ax
        mov     dx, R_IMR2
        xor     al, al
        out     dx, al
        call    sample
        mov     [off2], ax
        mov     dx, s_off
        call    out_str
        mov     ax, [off1]
        call    show
        mov     dx, s_on
        call    out_str
        mov     ax, [on]
        call    show
        mov     dx, s_off2
        call    out_str
        mov     ax, [off2]
        call    show
        ret

; the channels that were set only while the DMA bit was on
verdict:
        mov     ax, [off1]
        or      ax, [off2]
        or      ax, [idle]
        not     ax
        and     ax, [on]
        or      ax, ax
        jnz     .found
        mov     dx, s_none
        jmp     out_str
.found: mov     [hits], ax
        mov     dx, s_found
        call    out_str
        mov     ax, [hits]
        call    chans
        jmp     out_crlf

; AX (request bits) -> "  ch0 . ch1 . ..." for the 8 channels
show:
        call    chans
        jmp     out_crlf

chans:  push    bx
        push    cx
        mov     bx, ax
        xor     cx, cx                  ; CL = channel
.c:     mov     al, ' '
        call    out_chr
        mov     al, 'c'
        call    out_chr
        mov     al, 'h'
        call    out_chr
        mov     al, cl
        add     al, '0'
        call    out_chr
        mov     al, ':'
        call    out_chr
        mov     al, cl
        mov     ah, 10h
        cmp     al, 4
        jb      .lo
        sub     al, 4
        push    cx
        mov     cl, al
        shl     ah, cl
        pop     cx
        test    bh, ah
        jmp     short .t
.lo:    push    cx
        mov     cl, al
        shl     ah, cl
        pop     cx
        test    bl, ah
.t:     mov     al, '.'
        jz      .p
        mov     al, 'R'
.p:     call    out_chr
        inc     cl
        cmp     cl, 8
        jb      .c
        pop     cx
        pop     bx
        ret

; send ASCIIZ at SI to device BL, EOI on the last byte (d_query's first
; half).  CF=1 on a timeout or no listener.
dev_write:
        push    bx
        call    d_cmd_begin
        mov     al, UNL
        call    d_send_cmd
        jc      .f
        mov     al, 40h + MYADDR
        call    d_send_cmd
        jc      .f
        mov     al, bl
        or      al, 20h
        call    d_send_cmd
        jc      .f
        call    d_wait_co
        jc      .f
        call    d_do_gts
.wb:    lodsb
        or      al, al
        jz      .sent
        mov     ah, al
        mov     cx, T_DATA
        call    d_tmo_start
.wdo:   push    ax
        mov     ah, ISR1_DO | ISR1_ERR
        call    d_isr1_test
        mov     dl, al
        pop     ax
        jz      .nodo
        test    dl, ISR1_ERR
        jnz     .f
        cmp     byte [si], 0
        jne     .put
        mov     dx, R_AUXMR
        mov     al, AUX_SEOI
        out     dx, al
.put:   mov     dx, R_CDOR
        mov     al, ah
        out     dx, al
        jmp     .wb
.nodo:  call    d_tmo_check
        jnc     .wdo
        jmp     .f
.sent:  mov     cx, T_DATA
        call    d_tmo_start
.wl:    mov     ah, ISR1_DO
        call    d_isr1_test
        jnz     .ok
        call    d_tmo_check
        jnc     .wl
.f:     pop     bx
        stc
        ret
.ok:    pop     bx
        clc
        ret

; ---- output: the screen and the log buffer ----------------------------
out_str:                                ; '$'-terminated at DX
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

out_chr:                                ; AL
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

out_hex:                                ; AL as 2 hex digits
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

out_num:                                ; AL (0-99)
        push    ax
        xor     ah, ah
        mov     bl, 10
        div     bl
        or      al, al
        jz      .u
        add     al, '0'
        call    out_chr
.u:     mov     al, ah
        add     al, '0'
        call    out_chr
        pop     ax
        ret

save_log:                               ; append logbuf to GPIBDMA.TXT
        mov     dx, s_logname
        mov     ax, 3D01h               ; open for writing
        int     21h
        jnc     .op
        mov     ah, 3Ch                 ; or create
        xor     cx, cx
        int     21h
        jc      .x
.op:    mov     bx, ax
        mov     ax, 4202h               ; to the end
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

; ---- data -------------------------------------------------------------
s_title  db 13,10,'GPIBDMA 1.0 - the 7210 and the DMA channels.  Instrument at address $'
s_idle   db 'Idle (7210 quiet), 8237 request lines:',13,10,'  $'
s_out    db 13,10,'DMA OUT: the GRiD talker, data-out register empty, IMR2 DMAO (20h)',13,10,'$'
s_in     db 13,10,'DMA IN: the instrument talker, one byte held in DIR, IMR2 DMAI (10h)',13,10,'$'
s_off    db '  DMA bit off: $'
s_on     db '  DMA bit on:  $'
s_off2   db '  off again:   $'
s_isr1   db '  ISR1 $'
s_isr1do db 'h (DO is 02h)',13,10,'$'
s_isr1di db 'h (DI is 01h), DIR $'
s_dirend db 'h',13,10,'$'
s_none   db '  -> no request line followed the DMA bit',13,10,'$'
s_found  db '  -> REQUEST LINE FOLLOWS THE DMA BIT:$'
s_idq    db 'ID?',0
s_answer db '  it answers ID?: $'
s_noans  db '  no answer to ID? at that address: try GPIBDMA n with another instrument',13,10,'$'
s_nobus  db '  the bus did not take the commands (cable? controller?)',13,10,'$'
s_reboot db 13,10,'Done.  GRIDGPIB, if loaded, set up again.  Also in GPIBDMA.TXT.',13,10,'$'
s_logname db 'GPIBDMA.TXT',0

RBUFLEN equ 80
LOGMAX  equ 2048
dev     db 6
isr1o   db 0
dirb    db 0
idle    dw 0
off1    dw 0
on      dw 0
off2    dw 0
hits    dw 0
shadow1 db 0
shadow2 db 0
recov   dw 0
rxcnt   dw 0
lat     dw 0                    ; (direct.inc's d_spoll keeps these)
rawisr1 db 0
rawadsr db 0
rawdir  db 0
t_start dw 0
t_len   dw 0
logp    dw logbuf
rbuf    times RBUFLEN+2 db 0
logbuf  times LOGMAX db 0
