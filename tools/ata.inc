; The AT-bus hard disk at 1F0h-1F7h, for HDPROBE and HDSCAN: commands,
; waits, data, and printing the status and error registers.  Needs io.inc
; (putc, puts, phex8, crlf) and timing.inc (tick).  Its data is at the end
; (inline: these are .COM programs).
HD      equ 1F0h                        ; data; +1 error, +2 count, +3 sector,
                                        ;  +4/+5 cylinder, +6 drive/head,
                                        ;  +7 status/command.  (Not 3F6h: on
                                        ;  the 1520 it reads nothing of the
                                        ;  drive's, 2026-10-07, and the BIOS
                                        ;  resets the floppy controller there)

; the registers from r_cnt.. and command AL; first waits up to 5 s for
; the drive not to be busy.  CF: it stayed busy
ata_cmd:
        push    ax
        mov     dx, HD + 6
        mov     al, [r_sdh]
        out     dx, al
        call    short_wait
        mov     cx, 5 * 18
        call    wait_nb
        pop     ax
        jc      .x
        push    ax
        mov     dx, HD + 2
        mov     al, [r_cnt]
        out     dx, al
        inc     dx
        mov     al, [r_sec]
        out     dx, al
        inc     dx
        mov     al, [r_cyl]
        out     dx, al
        inc     dx
        mov     al, [r_cyl+1]
        out     dx, al
        inc     dx
        mov     al, [r_sdh]
        out     dx, al
        inc     dx
        pop     ax
        out     dx, al
        clc
.x:     ret

; wait until BSY clears (wait_rdy: and DRDY is set), at most CX ticks.
; CF: timed out.  AL = status
wait_rdy:
        mov     word [w_cond], 0C040h   ; (the bits to look at: C0h; flip 40h)
        jmp     short wait_nb.go
wait_nb:
        mov     word [w_cond], 8000h
.go:    push    bx
        push    dx
        call    tick
        mov     bx, ax
        mov     dx, HD + 7
.l:     in      al, dx
        mov     ah, al
        xor     ah, [w_cond]
        and     ah, [w_cond+1]
        jz      .ok
        push    ax
        call    tick
        sub     ax, bx
        cmp     ax, cx
        pop     ax
        jb      .l
        stc
        jmp     .x
.ok:    clc
.x:     pop     dx
        pop     bx
        ret

; after a data command: wait (up to 10 s) for DRQ or an error.  CF: still
; busy.  AL = status
wait_drq:
        call    short_wait
        mov     cx, 10 * 18
        call    wait_nb
        jc      .x
        test    al, 09h                 ; DRQ or ERR
        jnz     .x
        push    bx
        push    dx                      ; neither yet: give DRQ a moment
        call    tick
        mov     bx, ax
        mov     dx, HD + 7
.l:     in      al, dx
        test    al, 89h
        jz      .w
        test    al, 80h
        jz      .y
.w:     push    ax
        call    tick
        sub     ax, bx
        cmp     ax, 18
        pop     ax
        jb      .l
.y:     pop     dx
        pop     bx
        clc
.x:     ret

; 256 words from the data register to DI
read_sector:
        push    cx
        push    dx
        mov     dx, HD
        mov     cx, 256
.l:     in      ax, dx
        stosw
        loop    .l
        pop     dx
        pop     cx
        ret

; about 0.4 ms: the drive may take 400 ns to show a new status
short_wait:
        push    cx
        push    ax
        mov     cx, 100
.l:     in      al, 80h
        loop    .l
        pop     ax
        pop     cx
        ret

; AL = status -> "58 (DRDY DSC DRQ)"
pstat:  pusha
        call    phex8
        mov     bl, al
        mov     al, ' '
        call    putc
        mov     al, '('
        call    putc
        mov     si, stat_names
        mov     bh, 80h
        call    pbits
        mov     al, ')'
        call    putc
        popa
        ret

; AL = error register -> " error 10 (IDNF: ...)" and a new line
perr:   pusha
        mov     bl, al
        mov     dx, s_err
        call    puts
        mov     al, bl
        call    phex8
        mov     al, ' '
        call    putc
        mov     al, '('
        call    putc
        mov     si, err_names
        mov     bh, 80h
        call    pbits
        mov     al, ')'
        call    putc
        call    crlf
        popa
        ret

; the names in SI (5 bytes each, '$'-padded) of the bits of BL set,
; from BH = 80h down, with spaces between
pbits:  xor     cl, cl                  ; (any printed yet?)
.l:     test    bl, bh
        jz      .n
        or      cl, cl
        jz      .f
        mov     al, ' '
        call    putc
.f:     mov     dx, si
        call    puts
        inc     cl
.n:     add     si, 5
        shr     bh, 1
        jnz     .l
        ret

; CX words at SI as an ATA string (each word's bytes swapped), trailing
; blanks off, in quotes
pstr:   pusha
        mov     di, strbuf
.l:     lodsw
        xchg    al, ah
        stosw
        loop    .l
.t:     cmp     di, strbuf
        je      .e
        cmp     byte [di-1], ' '
        je      .b
        cmp     byte [di-1], 0
        jne     .e
.b:     dec     di
        jmp     .t
.e:     mov     byte [di], 0
        mov     al, '"'
        call    putc
        mov     si, strbuf
.p:     lodsb
        or      al, al
        jz      .q
        cmp     al, ' '
        jb      .dot
        cmp     al, 7Eh
        jbe     .c
.dot:   mov     al, '.'
.c:     call    putc
        jmp     .p
.q:     mov     al, '"'
        call    putc
        popa
        ret

phex16: push    ax
        mov     al, ah
        call    phex8
        pop     ax
        jmp     phex8

; DX:AX = AX * CX ... with DX:AX coming in as a 32-bit number: DX:AX *= CX
mul32:  push    bx
        push    si
        mov     si, dx
        mul     cx                      ; DX:AX = low * CX
        push    ax
        mov     bx, dx
        mov     ax, si
        mul     cx                      ; high * CX (fits for our sizes)
        add     ax, bx
        mov     dx, ax
        pop     ax
        pop     si
        pop     bx
        ret


stat_names db 'BSY$ DRDY$DWF$ DSC$ DRQ$ CORR$IDX$ ERR$ '
err_names  db 'BBK$ UNC$ MC$  IDNF$MCR$ ABRT$TK0$ AMNF$'
s_err   db ', error $'
w_cond  dw 0
r_cnt   db 0
r_sec   db 0
r_cyl   dw 0
r_sdh   db 0A0h
strbuf  times 42 db 0
