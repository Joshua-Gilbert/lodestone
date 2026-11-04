; =====================================================================
;  MODEMID.COM - which internal modem the GRiDCase 1520 has     nasm -f bin
;
;  The 1500 series' internal modem (TechRef chapter 12) sits on COM1,
;  3F8h, and came as Option 330 (1200 and 300 baud, Hayes Smartmodem
;  1200 commands, with one-bit registers at 420h and 421h) or Option 331
;  (2400, 1200 and 300, V.22bis, no I/O registers).  GRIDPROBE found a
;  UART at 3F8h that didn't answer a mouse.
;
;  This asks it: AT at 2400 baud, then 1200, then 300 (a Hayes modem
;  takes its speed from the AT), and at the first that answers, ATI0 to
;  ATI4 (product code, ROM checksum, ...).  It never dials, never goes
;  off hook, and doesn't write 420h or 421h (it only reads them).  The
;  UART's registers are put back as they were.  Polled: no interrupts.
;
;  Report on the screen and in MODEMID.TXT in the current directory.
; =====================================================================
        cpu     286
        org     100h

BASE    equ     3F8h                    ; COM1: the internal modem
TICKS   equ     46Ch                    ; (0:46Ch, the BIOS's tick count)
BUFMAX  equ     6000

start:  cld
        mov     si, s_head
        call    puts
        xor     ax, ax                  ; the BIOS's port table
        mov     es, ax
        mov     si, s_bda
        call    puts
        mov     ax, [es:400h]
        call    hex16
        mov     si, s_sp
        call    puts
        mov     ax, [es:402h]
        call    hex16
        call    crlf

        mov     si, s_420               ; Option 330's registers, read only
        call    puts
        mov     dx, 420h
        in      al, dx
        call    hex8
        mov     si, s_421
        call    puts
        mov     dx, 421h
        in      al, dx
        call    hex8
        mov     si, s_ff
        call    puts

        ; ---- a UART at 3F8h?  (its scratch register, then LCR)
        mov     dx, BASE + 7
        in      al, dx
        mov     bl, al
        mov     al, 5Ah
        out     dx, al
        jmp     $ + 2
        in      al, dx
        mov     bh, al
        mov     al, bl
        out     dx, al
        cmp     bh, 5Ah
        je      .uart
        mov     dx, BASE + 3            ; (an 8250 has no scratch register)
        in      al, dx
        mov     bl, al
        mov     al, 1Bh
        out     dx, al
        jmp     $ + 2
        in      al, dx
        mov     bh, al
        mov     al, bl
        out     dx, al
        cmp     bh, 1Bh
        je      .uart
        mov     si, s_nouart
        call    puts
        mov     byte [result], 'U'
        jmp     done

.uart:  mov     si, s_uart
        call    puts
        call    save                    ; its registers, to put back
        mov     dx, BASE + 1            ; no interrupts from it
        xor     al, al
        out     dx, al
        mov     si, s_msr0
        call    puts
        mov     dx, BASE + 6
        in      al, dx
        call    hex8
        mov     dx, BASE + 4            ; DTR and RTS on
        mov     al, 03h
        out     dx, al
        mov     cx, 4
        call    delay
        mov     si, s_msr1
        call    puts
        mov     dx, BASE + 6
        in      al, dx
        call    hex8
        mov     si, s_msrk
        call    puts

        ; ---- AT at each speed, fastest first
        mov     bx, speeds
.sp:    mov     ax, [bx]
        or      ax, ax
        jz      .none
        push    bx
        mov     si, s_try
        call    puts
        mov     ax, [bx + 2]
        call    dec16
        mov     si, s_baud
        call    puts
        mov     ax, [bx]
        call    setbaud
        mov     cx, 3                   ; (settle)
        call    delay
        call    flush
        mov     si, c_at
        call    ask
        pop     bx
        call    answered
        jc      .got
        add     bx, 4
        jmp     .sp
.none:  mov     si, s_none
        call    puts
        mov     byte [result], 'N'
        jmp     .back

.got:   mov     ax, [bx + 2]
        mov     [speed], ax
        mov     si, s_ok1
        call    puts
        mov     ax, [speed]
        call    dec16
        mov     si, s_ok2
        call    puts
        mov     si, c_set               ; words, echo, result codes
        call    ask
        mov     si, c_i0
        call    ask
        mov     si, c_i1
        call    ask
        mov     si, c_i2
        call    ask
        mov     si, c_i3
        call    ask
        mov     si, c_i4
        call    ask
        mov     byte [result], 'Y'

.back:  call    restore

done:   call    crlf
        mov     si, s_r_u
        cmp     byte [result], 'U'
        je      .r
        mov     si, s_r_n
        cmp     byte [result], 'N'
        je      .r
        mov     si, s_r_331
        cmp     word [speed], 2400
        je      .r
        mov     si, s_r_330
        cmp     word [speed], 1200
        je      .r
        mov     si, s_r_300
.r:     call    puts
        ; the report to MODEMID.TXT
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .nf
        mov     bx, ax
        mov     ah, 40h
        mov     cx, [bufp]
        mov     dx, buf
        int     21h
        mov     ah, 3Eh
        int     21h
        mov     si, s_saved
        call    puts2
        jmp     .x
.nf:    mov     si, s_nosave
        call    puts2
.x:     mov     ax, 4C00h
        int     21h

; ---- the UART ------------------------------------------------------
; keep LCR, the divisor, IER and MCR
save:   mov     dx, BASE + 3
        in      al, dx
        mov     [o_lcr], al
        or      al, 80h
        out     dx, al
        mov     dx, BASE
        in      al, dx
        mov     [o_dll], al
        inc     dx
        in      al, dx
        mov     [o_dlm], al
        mov     dx, BASE + 3
        mov     al, [o_lcr]
        and     al, 7Fh
        out     dx, al
        mov     dx, BASE + 1
        in      al, dx
        mov     [o_ier], al
        mov     dx, BASE + 4
        in      al, dx
        mov     [o_mcr], al
        ret
restore:
        mov     dx, BASE + 3
        mov     al, 80h
        out     dx, al
        mov     dx, BASE
        mov     al, [o_dll]
        out     dx, al
        inc     dx
        mov     al, [o_dlm]
        out     dx, al
        mov     dx, BASE + 3
        mov     al, [o_lcr]
        and     al, 7Fh
        out     dx, al
        mov     dx, BASE + 4
        mov     al, [o_mcr]
        out     dx, al
        mov     dx, BASE + 1
        mov     al, [o_ier]
        out     dx, al
        call    flush
        ret
; the divisor AX, 8 bits, no parity, 1 stop
setbaud:
        push    ax
        mov     dx, BASE + 3
        mov     al, 80h
        out     dx, al
        pop     ax
        mov     dx, BASE
        out     dx, al
        inc     dx
        mov     al, ah
        out     dx, al
        mov     dx, BASE + 3
        mov     al, 03h
        out     dx, al
        ret
; whatever is waiting, dropped
flush:  mov     cx, 64
.f:     mov     dx, BASE + 5
        in      al, dx
        test    al, 1
        jz      .x
        mov     dx, BASE
        in      al, dx
        loop    .f
.x:     ret
; wait CX ticks (55 ms each)
delay:  push    es
        xor     ax, ax
        mov     es, ax
        sti
.t:     mov     ax, [es:TICKS]
.u:     cmp     ax, [es:TICKS]
        je      .u
        loop    .t
        pop     es
        ret

; send the command at SI (ends in 0), show it, then what comes back:
; up to 2 s, or 0.5 s after the last character.  Kept at rbuf (rlen)
ask:    push    si
        mov     si, s_cmd
        call    puts
        pop     si
        push    si
.e:     lodsb                           ; (shown without its CR)
        cmp     al, 13
        je      .e1
        call    putc
        jmp     .e
.e1:    call    crlf
        pop     si
        mov     word [rlen], 0
        ; sent a character at a time; what comes back while it goes (the
        ; echo: the UART holds only one) is read as it arrives
.s:     lodsb
        or      al, al
        jz      .r
        mov     ah, al
        mov     cx, 0FFFFh
.w:     call    rx1                     ; (anything waiting: kept)
        mov     dx, BASE + 5            ; (the transmitter empty)
        in      al, dx
        test    al, 20h
        loopz   .w
        mov     al, ah
        mov     dx, BASE
        out     dx, al
        jmp     .s
        ; then until its result: OK or ERROR (and their line end) ends it;
        ; nothing at all in 1 s, or 4 s in all, gives up
.r:     push    es
        xor     ax, ax
        mov     es, ax
        sti
        mov     bx, [es:TICKS]          ; the start
.l:     call    rx1
        call    final
        jc      .d
        mov     ax, [es:TICKS]
        sub     ax, bx
        cmp     ax, 72                  ; 4 s in all
        jae     .d
        cmp     ax, 18                  ; 1 s with nothing: no modem here
        jb      .l
        cmp     word [rlen], 0
        jne     .l
.d:     pop     es
        ; show it
        mov     si, s_got
        call    puts
        mov     cx, [rlen]
        jcxz    .z
        mov     si, rbuf
.p:     lodsb
        call    showc
        loop    .p
        call    crlf
        ret
.z:     mov     si, s_nothing
        call    puts
        ret
; one received character, if there is one, to rbuf.  AX, DX, SI kept
rx1:    push    ax
        push    dx
        push    si
        mov     dx, BASE + 5
        in      al, dx
        test    al, 1
        jz      .x
        mov     dx, BASE
        in      al, dx
        mov     si, [rlen]
        cmp     si, 255                 ; (full: the rest dropped)
        jae     .x
        mov     [rbuf + si], al
        inc     word [rlen]
.x:     pop     si
        pop     dx
        pop     ax
        ret
; CF set if rbuf ends in a final result line: OK or ERROR then CR LF, or
; a numeric one (V0: a digit, then CR) after the echo's CR
final:  push    ax
        push    cx
        push    si
        mov     cx, [rlen]
        mov     si, rbuf
        add     si, cx
        cmp     cx, 4
        jb      .v0
        cmp     word [si - 2], 0A0Dh
        jne     .v0
        cmp     word [si - 4], 'OK'
        je      .y
        cmp     cx, 7
        jb      .v0
        cmp     word [si - 7], 'ER'
        jne     .v0
        cmp     word [si - 5], 'RO'
        jne     .v0
        cmp     byte [si - 3], 'R'
        je      .y
.v0:    cmp     cx, 3                   ; (the echo's CR, a digit, its CR)
        jb      .n
        cmp     byte [si - 1], 13
        jne     .n
        cmp     byte [si - 3], 13
        jne     .n
        mov     al, [si - 2]
        cmp     al, '0'
        jb      .n
        cmp     al, '9'
        ja      .n
.y:     stc
        jmp     .x
.n:     clc
.x:     pop     si
        pop     cx
        pop     ax
        ret
; a received character, shown: CR dropped, LF a new line (indented),
; others not printable as <hh>
showc:  cmp     al, 13
        je      .x
        cmp     al, 10
        jne     .c
        push    si
        mov     si, s_nl
        call    puts
        pop     si
        ret
.c:     cmp     al, ' '
        jb      .h
        cmp     al, 7Eh
        ja      .h
        jmp     putc
.h:     push    ax
        mov     al, '<'
        call    putc
        pop     ax
        call    hex8
        mov     al, '>'
        jmp     putc
.x:     ret
; CF set if rbuf holds OK, or a 0 result code, or our own AT echoed
answered:
        mov     cx, [rlen]
        cmp     cx, 2
        jb      .no
        mov     si, rbuf
        dec     cx
.l:     mov     ax, [si]
        and     ax, 0DFDFh              ; (upper case)
        cmp     ax, 'OK'
        je      .yes
        cmp     ax, 'AT'
        je      .yes
        inc     si
        loop    .l
        mov     si, rbuf                ; a lone '0' (numeric results)
        mov     cx, [rlen]
.m:     lodsb
        cmp     al, '0'
        jne     .m1
        cmp     byte [si], 13
        je      .yes
.m1:    loop    .m
.no:    clc
        ret
.yes:   stc
        ret

; ---- output: the screen, and kept for the file ---------------------
putc:   push    ax
        push    dx
        push    di
        mov     di, [bufp]
        cmp     di, BUFMAX
        jae     .s
        mov     [buf + di], al
        inc     word [bufp]
.s:     mov     dl, al
        mov     ah, 2
        int     21h
        pop     di
        pop     dx
        pop     ax
        ret
puts:   lodsb                           ; SI: a 0-ended string
        or      al, al
        jz      .x
        call    putc
        jmp     puts
.x:     ret
puts2:  lodsb                           ; the screen only
        or      al, al
        jz      .x
        mov     dl, al
        mov     ah, 2
        int     21h
        jmp     puts2
.x:     ret
crlf:   mov     al, 13
        call    putc
        mov     al, 10
        jmp     putc
hex16:  push    ax
        mov     al, ah
        call    hex8
        pop     ax
hex8:   push    ax
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
        jbe     .p
        add     al, 7
.p:     jmp     putc
dec16:  push    bx
        push    cx
        push    dx
        mov     bx, 10
        xor     cx, cx
.a:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .a
.b:     pop     ax
        add     al, '0'
        call    putc
        loop    .b
        pop     dx
        pop     cx
        pop     bx
        ret

; ---- data ----------------------------------------------------------
speeds  dw      48, 2400, 96, 1200, 384, 300, 0
c_at    db      'AT', 13, 0
c_set   db      'ATE1V1Q0', 13, 0
c_i0    db      'ATI0', 13, 0
c_i1    db      'ATI1', 13, 0
c_i2    db      'ATI2', 13, 0
c_i3    db      'ATI3', 13, 0
c_i4    db      'ATI4', 13, 0
fname   db      'MODEMID.TXT', 0

s_head  db      'MODEMID 1.1 - the GRiDCase 1520', 39, 's internal modem (COM1, 3F8h)', 13, 10
        db      'It never dials or goes off hook.', 13, 10, 13, 10, 0
s_bda   db      'BIOS serial ports: COM1 ', 0
s_sp    db      '  COM2 ', 0
s_420   db      'Port 420h = ', 0
s_421   db      '  421h = ', 0
s_ff    db      '  (Option 330', 39, 's registers, read only; FF = nothing there)', 13, 10, 0
s_nouart db     'No UART at 3F8h.', 13, 10, 0
s_uart  db      'UART at 3F8h: present', 13, 10, 0
s_msr0  db      'Modem status: ', 0
s_msr1  db      ' before DTR/RTS, ', 0
s_msrk  db      ' after  (80 DCD, 40 RI, 20 DSR, 10 CTS)', 13, 10, 0
s_try   db      13, 10, '--- ', 0
s_baud  db      ' baud ---', 13, 10, 0
s_cmd   db      '  sent:   ', 0
s_got   db      '  answer: ', 0
s_nl    db      13, 10, '          ', 0
s_nothing db    '(nothing)', 13, 10, 0
s_none  db      13, 10, 'No answer at any speed.', 13, 10, 0
s_ok1   db      13, 10, 'A modem answered at ', 0
s_ok2   db      ' baud.  Asking it what it is:', 13, 10, 0
s_r_u   db      'RESULT: no serial port at 3F8h, so no internal modem.', 13, 10, 0
s_r_n   db      'RESULT: COM1', 39, 's UART is there, but nothing answered AT at 2400, 1200', 13, 10
        db      'or 300 baud: probably no modem fitted (or it is switched off).', 13, 10, 0
s_r_331 db      'RESULT: it answered at 2400 baud: Option 331 (2400/1200/300, V.22bis).', 13, 10, 0
s_r_330 db      'RESULT: it answered at 1200 baud but not 2400: Option 330 (1200/300).', 13, 10, 0
s_r_300 db      'RESULT: it answered only at 300 baud, which neither option should do.', 13, 10, 0
s_saved db      13, 10, 'Report saved to MODEMID.TXT.', 13, 10, 0
s_nosave db     13, 10, 'Could not save MODEMID.TXT.', 13, 10, 0

result  db      0
speed   dw      0
o_lcr   db      0
o_dll   db      0
o_dlm   db      0
o_ier   db      0
o_mcr   db      0
rlen    dw      0
bufp    dw      0
rbuf    equ     $
buf     equ     rbuf + 256
