; =====================================================================
;  GRIDPROBE.COM 1.0  -  Lodestone hardware probe for the GRiDCase 1520
;  Build:  nasm -f bin -o GRIDPROBE.COM GRIDPROBE.ASM   (needs io.inc,
;          timing.inc from the same folder)
;  Run  :  GRIDPROBE        full probe, report to A:\GPROBE.TXT and
;                           application ROM images to A:\ROMn.BIN
;          GRIDPROBE /N     same, but no ROM image dumps (headers only)
;
;  Answers the questions the BIOS source cannot:
;   1. machine id, memory mode, ports from the BDA
;   2. display: panel type (port 7F8h), V6366 id (3DFh), whether BIOS
;      mode 40h (640x400) works, and video RAM speed in that mode
;   3. application ROMs: count, header (GRiD EPROM trailer) and a full
;      128 KB image of each, via the BIOS's own INT 15h E400-E404 calls
;   4. serial ports: UART present, and a Microsoft serial mouse ID check
;   5. keyboard: logs the codes of keys you press (ESC ends)
;  Everything is read-only except the UART line settings during the
;  mouse check (saved and restored) and the ROM window (unmapped again).
;  Reboot after running it if the machine boots from the EPROM.
; =====================================================================
cpu 286
org 100h

start:  cld
        mov     sp, stack_top
        mov     bx, (prog_end - start + 100h + 15) / 16
        mov     ah, 4Ah                 ; shrink to our image
        int     21h
        call    log_open
        mov     dx, s_title
        call    puts
        cmp     word [fh], 0
        jne     .fok
        mov     dx, s_nofile
        call    puts
.fok:   ; ---- /N switch ----
        mov     si, 81h
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
        cmp     al, 'n'
        jne     .pa
        mov     byte [nodump], 1
.pd:    ; ---- two 64 KB work buffers ----
        mov     ah, 48h
        mov     bx, 1000h
        int     21h
        jc      .nob
        mov     [blk1], ax
        mov     ah, 48h
        mov     bx, 1000h
        int     21h
        jc      .nob
        mov     [blk2], ax
.nob:   call    pit_init
        call    sysinfo
        call    commit
        call    video
        call    commit
        call    approm
        call    commit
        call    serial
        call    commit
        call    keys
        call    pit_done
        mov     dx, s_done
        call    puts
        call    log_close
        mov     ax, 4C00h
        int     21h

; =====================================================================
; 1. system
; =====================================================================
sysinfo:
        mov     dx, s_sys
        call    puts
        push    es
        mov     ax, 0F000h
        mov     es, ax
        mov     di, 0FFF5h
        mov     cx, 8
.bd:    mov     al, [es:di]
        inc     di
        call    putc
        loop    .bd
        pop     es
        mov     ax, 0E448h              ; GRiD: model bytes + backplane
        int     15h
        jc      .n48
        push    dx
        push    cx
        mov     dx, s_ibm
        call    puts
        pop     cx
        push    cx
        mov     al, cl
        call    phex8
        mov     dx, s_gridm
        call    puts
        pop     cx
        mov     al, ch
        call    phex8
        mov     dx, s_bkpl
        call    puts
        pop     dx
        mov     al, dl
        call    phex8
.n48:   call    crlf
        mov     dx, s_mmode
        call    puts
        mov     ax, 0E442h
        mov     dl, 0FFh
        int     15h
        mov     al, dl
        mov     dx, s_ext
        test    al, 1
        jz      .mm
        mov     dx, s_ems
.mm:    call    puts
        mov     ax, 0E440h
        int     15h
        mov     ax, cx
        call    pdec
        mov     dx, s_kbems
        call    puts
        mov     ax, 0E441h
        int     15h
        mov     ax, cx
        call    pdec
        mov     dx, s_kbext
        call    puts
        ; BDA ports
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     si, 400h
        mov     di, bda
        push    cs
        pop     es
        mov     cx, 16
        rep     movsb
        mov     ax, [410h]
        mov     [cs:equip], ax
        mov     al, [4A6h]
        mov     [cs:colmap], al
        pop     ds
        mov     dx, s_com
        call    puts
        mov     si, bda
        mov     cx, 4
.cp:    lodsw
        call    phex16
        mov     al, ' '
        call    putc
        loop    .cp
        mov     dx, s_lpt
        call    puts
        mov     cx, 3
.lp:    lodsw
        call    phex16
        mov     al, ' '
        call    putc
        loop    .lp
        mov     dx, s_equip
        call    puts
        mov     ax, [equip]
        call    phex16
        call    crlf
        ret

; =====================================================================
; 2. display
; =====================================================================
video:
        mov     dx, s_vid
        call    puts
        mov     dx, 7F8h
        in      al, dx
        mov     [p7f8], al
        call    phex8
        mov     dx, s_panel
        call    puts
        mov     al, [p7f8]
        test    al, 08h
        mov     dx, s_pext
        jz      .pt
        and     al, 7
        mov     dx, s_p1
        cmp     al, 1
        je      .pt
        mov     dx, s_p5
        cmp     al, 5
        je      .pt
        mov     dx, s_p6
        cmp     al, 6
        je      .pt
        mov     dx, s_p7
        cmp     al, 7
        je      .pt
        mov     dx, s_punk
.pt:    call    puts
        mov     dx, s_6f8
        call    puts
        mov     dx, 6F8h
        in      al, dx
        call    phex8
        mov     dx, s_3df
        call    puts
        mov     dx, 3DFh
        in      al, dx
        call    phex8
        mov     dx, s_cmap
        call    puts
        mov     al, [colmap]
        call    phex8
        call    crlf
        call    commit

        ; ---- try BIOS mode 40h (640x400) ----
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     al, [449h]
        pop     ds
        mov     [oldmode], al
        mov     ax, 0040h
        int     10h
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     al, [449h]
        pop     ds
        mov     [newmode], al
        cmp     al, 40h
        jne     .restore                ; BIOS fell back (mode 6) - no hi-res
        cmp     word [blk2], 0
        je      .pattern
        ; -- timings: 8 passes of 32000 bytes each --
        mov     es, [blk1]              ; RAM source pattern
        xor     di, di
        mov     cx, 16000
        mov     ax, 0AA55h
        rep     stosw
        mov     bx, t_fill
        call    t_start
        mov     ax, 0B800h
        mov     es, ax
        mov     dx, 8
.f:     xor     di, di
        mov     cx, 16000
        xor     ax, ax
        rep     stosw
        dec     dx
        jnz     .f
        call    t_end
        mov     bx, t_copy
        call    t_start
        push    ds
        mov     ds, [blk1]
        mov     dx, 8
.c:     xor     si, si
        xor     di, di
        mov     cx, 16000
        rep     movsw
        dec     dx
        jnz     .c
        pop     ds
        call    t_end
        mov     bx, t_read
        call    t_start
        push    ds
        mov     ax, 0B800h
        mov     ds, ax
        mov     dx, 8
.r:     xor     si, si
        mov     cx, 16000
        rep     lodsw
        dec     dx
        jnz     .r
        pop     ds
        call    t_end
        mov     bx, t_ram
        call    t_start
        push    ds
        mov     ds, [blk1]
        mov     es, [blk2]
        mov     dx, 8
.m:     xor     si, si
        xor     di, di
        mov     cx, 16000
        rep     movsw
        dec     dx
        jnz     .m
        pop     ds
        call    t_end
.pattern:
        call    draw_pattern
        xor     ah, ah                  ; wait for a key
        int     16h
.restore:
        mov     al, [oldmode]
        xor     ah, ah
        int     10h
        mov     dx, s_m40
        call    puts
        mov     al, [newmode]
        call    phex8
        mov     dx, s_m40ok
        cmp     byte [newmode], 40h
        je      .m40p
        mov     dx, s_m40no
.m40p:  call    puts
        cmp     byte [newmode], 40h
        jne     .vx
        cmp     word [blk2], 0
        je      .vx
        mov     dx, s_tfill
        mov     bx, t_fill
        call    t_print
        mov     dx, s_tcopy
        mov     bx, t_copy
        call    t_print
        mov     dx, s_tread
        mov     bx, t_read
        call    t_print
        mov     dx, s_tram
        mov     bx, t_ram
        call    t_print
.vx:    ret

; frame + diagonal + text, drawn straight into the 4-bank buffer
draw_pattern:
        mov     ax, 0B800h
        mov     es, ax
        xor     di, di
        mov     cx, 16384
        xor     ax, ax
        rep     stosw
        xor     bx, bx                  ; y
.row:   call    rowaddr                 ; DI = start of row BX
        cmp     bx, 0
        je      .full
        cmp     bx, 399
        je      .full
        or      byte [es:di], 80h       ; left edge
        or      byte [es:di+79], 01h    ; right edge
        ; diagonal: x = y * 8 / 5  (0..638)
        mov     ax, bx
        shl     ax, 3
        push    dx
        xor     dx, dx
        mov     cx, 5
        div     cx
        pop     dx
        mov     cx, ax
        shr     ax, 3
        add     di, ax
        and     cl, 7
        mov     al, 80h
        shr     al, cl
        or      [es:di], al
        jmp     .next
.full:  push    di
        mov     cx, 40
        mov     ax, 0FFFFh
        rep     stosw
        pop     di
.next:  inc     bx
        cmp     bx, 400
        jb      .row
        ; text via BIOS (mode 40h uses the 8x16 font)
        mov     ah, 02h
        xor     bh, bh
        mov     dx, 0A14h               ; row 10, col 20
        int     10h
        mov     si, s_pat
.t:     lodsb
        or      al, al
        jz      .td
        mov     ah, 0Eh
        mov     bx, 0001h
        int     10h
        jmp     .t
.td:    ret

; DI = offset of pixel row BX in mode 40h: bank (y&3)*2000h + (y>>2)*80
rowaddr:
        push    ax
        push    cx
        mov     ax, bx
        and     ax, 3
        mov     cl, 13
        shl     ax, cl
        mov     di, ax
        mov     ax, bx
        shr     ax, 2
        mov     cx, 80
        push    dx
        mul     cx
        pop     dx
        add     di, ax
        pop     cx
        pop     ax
        ret

t_start: push   ax
        push    dx
        call    stamp
        mov     [bx], ax
        mov     [bx+2], dx
        pop     dx
        pop     ax
        ret
t_end:  push    ax
        push    dx
        call    stamp
        sub     ax, [bx]
        sbb     dx, [bx+2]
        mov     [bx], ax
        mov     [bx+2], dx
        pop     dx
        pop     ax
        ret
; print label DX, then time for 256000 bytes in ms and KB/s
t_print:
        call    puts
        mov     ax, [bx]
        mov     dx, [bx+2]
        call    pms
        mov     dx, s_ms
        call    puts
        mov     ax, [bx]
        mov     dx, [bx+2]
        mov     cx, 1193
        call    ldiv                    ; AX = ms
        or      ax, ax
        jz      .z
        mov     cx, ax
        mov     ax, 0D090h              ; 250000 = 0003D090h
        mov     dx, 0003h
        call    ldiv
        call    pdec
        mov     dx, s_kbs
        call    puts
.z:     call    crlf
        ret

; =====================================================================
; 3. application ROMs (BIOS INT 15h E400-E404)
; =====================================================================
approm:
        mov     dx, s_rom
        call    puts
        mov     ax, 0E400h
        int     15h
        push    cx
        push    bx
        call    phex8                   ; AL = max images
        mov     dx, s_rdseg
        call    puts
        pop     ax
        call    pdec                    ; BX = paragraphs
        mov     dx, s_rsock
        call    puts
        pop     cx
        mov     al, cl
        call    pdec8
        call    crlf
        ; DS for the ROM calls = our paragraph-aligned table
        mov     ax, cs
        add     ax, (romds - $$ + 100h) / 16
        mov     [romseg], ax
        push    ds
        mov     ds, ax
        mov     ax, 0E401h
        int     15h
        pop     ds
        jnc     .ok
        mov     dx, s_rnone
        call    puts
        mov     al, ah
        call    phex8
        call    crlf
        ret
.ok:    mov     [nimg], al
        mov     dx, s_rcount
        call    puts
        mov     al, [nimg]
        call    pdec8
        call    crlf
        mov     byte [img], 0
.each:  mov     al, [img]
        cmp     al, [nimg]
        jae     .done
        call    one_image
        call    commit
        inc     byte [img]
        jmp     .each
.done:  ret

one_image:
        mov     dx, s_rimg
        call    puts
        mov     al, [img]
        call    pdec8
        push    ds
        mov     ds, [cs:romseg]
        mov     ax, 0E402h
        mov     dl, [cs:img]
        int     15h
        pop     ds
        jnc     .i2
        mov     dx, s_rerr
        call    puts
        mov     al, ah
        call    phex8
        jmp     crlf
.i2:    push    es
        push    dx
        push    cx
        push    bx
        mov     dx, s_rid
        call    puts
        pop     ax
        call    phex16                  ; BX = ROM id
        mov     dx, s_rpar
        call    puts
        pop     ax
        call    phex16                  ; CX = "paragraphs" (image select)
        mov     dx, s_rsys
        call    puts
        pop     dx
        mov     al, dh
        call    phex8                   ; DH = system type (1 = MS-DOS)
        mov     dx, s_rbase
        call    puts
        pop     ax
        call    phex16                  ; ES = window base
        call    crlf
        call    commit
        ; ---- map, copy header (and image), unmap: interrupts off ----
        cli
        push    ds
        mov     ds, [cs:romseg]
        mov     ax, 0E403h
        mov     dl, [cs:img]
        int     15h
        pop     ds
        push    ds
        mov     ax, 0BFF0h
        mov     ds, ax
        xor     si, si
        mov     di, hdr
        push    cs
        pop     es
        mov     cx, 128
        rep     movsw
        pop     ds
        cmp     byte [nodump], 0
        jne     .unmap
        cmp     word [blk2], 0
        je      .unmap
        push    ds
        mov     ax, 0A000h
        mov     ds, ax
        mov     es, [cs:blk1]
        xor     si, si
        xor     di, di
        mov     cx, 8000h
        rep     movsw
        mov     ax, 0B000h
        mov     ds, ax
        mov     es, [cs:blk2]
        xor     si, si
        xor     di, di
        mov     cx, 8000h
        rep     movsw
        pop     ds
        mov     byte [dumped], 1
.unmap: push    ds
        mov     ds, [cs:romseg]
        mov     ax, 0E404h
        int     15h
        pop     ds
        sti
        call    print_header
        cmp     byte [dumped], 0
        je      .x
        mov     byte [dumped], 0
        call    write_image
.x:     ret

; decode the 256-byte GRiD EPROM trailer [GridEprom D-3]
print_header:
        mov     dx, s_h1
        call    puts
        mov     ax, [hdr+0]
        call    phex16
        mov     dx, s_h2
        call    puts
        mov     al, [hdr+2]
        call    phex8
        mov     dx, s_h3
        call    puts
        mov     al, [hdr+3]
        call    phex8
        mov     dx, s_h4
        call    puts
        mov     ax, [hdr+4]
        call    phex16
        mov     dx, s_h5
        call    puts
        mov     al, [hdr+6]
        call    phex8
        mov     dx, s_h6
        call    puts
        mov     al, [hdr+7]
        call    pdec8
        mov     dx, s_h7
        call    puts
        mov     al, [hdr+8]
        call    phex8
        call    crlf
        mov     dx, s_h8
        call    puts
        mov     ax, [hdr+9]
        call    phex16
        mov     dx, s_h9
        call    puts
        mov     ax, [hdr+11]
        call    phex16
        mov     dx, s_h10
        call    puts
        mov     ax, [hdr+13]
        call    pdec
        mov     dx, s_h11
        call    puts
        mov     ax, [hdr+15]
        call    phex16
        mov     dx, s_h12
        call    puts
        mov     ax, [hdr+17]
        call    pdec
        mov     dx, s_h13
        call    puts
        mov     ax, [hdr+19]
        call    phex16
        call    crlf
        mov     dx, s_hc
        mov     si, hdr+21
        mov     cx, 45
        call    ptext
        mov     dx, s_ht
        mov     si, hdr+66
        mov     cx, 11
        call    ptext
        mov     dx, s_hp
        mov     si, hdr+77
        mov     cx, 9+15
        call    ptext
        mov     dx, s_hb
        mov     si, hdr+102
        mov     cx, 30
        call    ptext
        mov     dx, s_hi
        mov     si, hdr+142
        mov     cx, 50
        call    ptext
        mov     dx, s_h14
        call    puts
        mov     al, [hdr+133]
        call    phex8
        mov     dx, s_h15
        call    puts
        mov     ax, [hdr+134]
        call    phex16
        mov     dx, s_h16
        call    puts
        mov     ax, [hdr+250]
        call    phex16
        mov     dx, s_h17
        call    puts
        mov     al, [hdr+255]
        call    phex8
        call    crlf
        ; raw hex of the whole trailer
        mov     si, hdr
        mov     bx, 16
.hl:    mov     dx, s_ind
        call    puts
        mov     cx, 16
.hb:    lodsb
        call    phex8
        mov     al, ' '
        call    putc
        loop    .hb
        call    crlf
        dec     bx
        jnz     .hl
        ret

; label DX, then CX bytes at SI as text (non-printables as '.')
ptext:  call    puts
        mov     al, '"'
        call    putc
.l:     lodsb
        cmp     al, 20h
        jb      .d
        cmp     al, 7Eh
        jbe     .p
.d:     mov     al, '.'
.p:     call    putc
        loop    .l
        mov     al, '"'
        call    putc
        jmp     crlf

write_image:
        mov     ah, 36h                 ; free space on A:
        mov     dl, 1
        int     21h
        mul     cx                      ; AX = bytes per cluster
        mul     bx                      ; DX:AX = free bytes
        cmp     dx, 3                   ; need >= 196608 (128 KB + slack)
        jae     .room
        mov     dx, s_noroom
        call    puts
        ret
.room:  mov     al, [img]
        add     al, '0'
        mov     [n_rom+6], al
        mov     dx, n_rom
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .err
        mov     [rfh], ax
        mov     dx, [blk1]
        call    .w64
        jc      .err
        mov     dx, [blk2]
        call    .w64
        jc      .err
        mov     bx, [rfh]
        mov     ah, 3Eh
        int     21h
        mov     dx, s_saved
        call    puts
        mov     dx, n_rom
        call    pasciz
        call    crlf
        ret
.err:   mov     dx, s_werr
        call    puts
        ret
.w64:   push    ds                      ; write 64 KB at DX:0000 in 2 halves
        mov     ds, dx
        xor     dx, dx
        mov     cx, 8000h
        mov     bx, [cs:rfh]
        mov     ah, 40h
        int     21h
        jc      .wx
        mov     dx, 8000h
        mov     cx, 8000h
        mov     ah, 40h
        int     21h
.wx:    pop     ds
        ret

; =====================================================================
; 4. serial ports + Microsoft mouse ID
; =====================================================================
serial:
        mov     dx, s_ser
        call    puts
        mov     si, bda
        mov     byte [comn], 1
.each:  lodsw
        or      ax, ax
        jz      .nx
        mov     [cbase], ax
        push    si
        call    one_com
        pop     si
.nx:    inc     byte [comn]
        cmp     byte [comn], 2
        jbe     .each
        ret

one_com:
        mov     dx, s_comx
        call    puts
        mov     al, [comn]
        call    pdec8
        mov     dx, s_at
        call    puts
        mov     ax, [cbase]
        call    phex16
        ; scratch register test
        mov     dx, [cbase]
        add     dx, 7
        mov     al, 5Ah
        out     dx, al
        jmp     short $+2
        in      al, dx
        cmp     al, 5Ah
        mov     dx, s_uart
        je      .u
        mov     dx, s_nouart
        call    puts
        jmp     crlf
.u:     call    puts
        ; save line settings
        mov     dx, [cbase]
        add     dx, 1
        in      al, dx
        mov     [s_ier], al
        add     dx, 2
        in      al, dx
        mov     [s_lcr], al
        inc     dx
        in      al, dx
        mov     [s_mcr], al
        mov     dx, s_msr
        call    puts
        mov     dx, [cbase]
        add     dx, 6
        in      al, dx
        call    phex8
        call    crlf
        ; IER off, 1200 baud 7N1, DTR/RTS low then high
        mov     dx, [cbase]
        inc     dx
        xor     al, al
        out     dx, al
        add     dx, 2
        mov     al, 80h
        or      al, [s_lcr]
        out     dx, al
        mov     dx, [cbase]
        in      al, dx
        mov     [s_dll], al
        inc     dx
        in      al, dx
        mov     [s_dlm], al
        mov     dx, [cbase]
        mov     al, 96
        out     dx, al
        inc     dx
        xor     al, al
        out     dx, al
        add     dx, 2
        mov     al, 02h                 ; 7 data bits, 1 stop, no parity
        out     dx, al
        inc     dx
        xor     al, al                  ; DTR/RTS off
        out     dx, al
        mov     cx, 4
        call    wticks
        call    drain
        mov     dx, [cbase]
        add     dx, 4
        mov     al, 03h                 ; DTR + RTS on: mouse powers up
        out     dx, al
        mov     byte [nrx], 0
        call    tick
        mov     [t0], ax
.poll:  mov     dx, [cbase]
        add     dx, 5
        in      al, dx
        test    al, 1
        jz      .nod
        mov     dx, [cbase]
        in      al, dx
        mov     bl, [nrx]
        cmp     bl, 16
        jae     .nod
        xor     bh, bh
        mov     [rx+bx], al
        inc     byte [nrx]
.nod:   call    tick
        sub     ax, [t0]
        cmp     ax, 10                  ; ~0.55 s
        jb      .poll
        ; restore
        mov     dx, [cbase]
        add     dx, 3
        mov     al, 80h
        out     dx, al
        mov     dx, [cbase]
        mov     al, [s_dll]
        out     dx, al
        inc     dx
        mov     al, [s_dlm]
        out     dx, al
        add     dx, 2
        mov     al, [s_lcr]
        out     dx, al
        inc     dx
        mov     al, [s_mcr]
        out     dx, al
        mov     dx, [cbase]
        inc     dx
        mov     al, [s_ier]
        out     dx, al
        ; report
        mov     dx, s_mouse
        call    puts
        mov     cl, [nrx]
        xor     ch, ch
        jcxz    .none
        mov     si, rx
        mov     byte [ism], 0
.pb:    lodsb
        cmp     al, 'M'
        jne     .pb2
        mov     byte [ism], 1
.pb2:   call    phex8
        mov     al, ' '
        call    putc
        loop    .pb
        mov     dx, s_mm
        cmp     byte [ism], 1
        je      .r
        mov     dx, s_mx
        jmp     .r
.none:  mov     dx, s_mnone
.r:     call    puts
        ret

drain:  mov     cx, 32
.d:     mov     dx, [cbase]
        add     dx, 5
        in      al, dx
        test    al, 1
        jz      .x
        mov     dx, [cbase]
        in      al, dx
        loop    .d
.x:     ret

wticks: call    tick                    ; wait CX BIOS ticks
        mov     bx, ax
.w:     call    tick
        sub     ax, bx
        cmp     ax, cx
        jb      .w
        ret

; =====================================================================
; 5. keyboard codes
; =====================================================================
keys:   mov     dx, s_keys
        call    puts
        call    commit
        mov     byte [nk], 0
.k:     xor     ah, ah
        int     16h
        push    ax
        mov     dx, s_key
        call    puts
        pop     ax
        push    ax
        call    phex16
        mov     dx, s_shift
        call    puts
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     al, [417h]
        pop     ds
        call    phex8
        call    crlf
        pop     ax
        cmp     al, 1Bh
        je      .x
        inc     byte [nk]
        cmp     byte [nk], 80
        jb      .k
.x:     ret

; ---------------------------------------------------------------------
phex16: push    ax
        mov     al, ah
        call    phex8
        pop     ax
        jmp     phex8
pdec8:  push    ax
        xor     ah, ah
        call    pdec
        pop     ax
        ret
pasciz: push    si
        mov     si, dx
.l:     lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     .l
.x:     pop     si
        ret

%include "io.inc"
%include "timing.inc"

; ---------------------------------------------------------------------
s_title db 'GRIDPROBE 1.0 - Lodestone hardware probe for the GRiDCase 1520',13,10,'$'
s_nofile db '** Cannot create A:\GPROBE.TXT - screen output only',13,10,'$'
s_sys   db 13,10,'[1] SYSTEM',13,10,'  BIOS date $'
s_ibm   db '   IBM model $'
s_gridm db '  GRiD model $'
s_bkpl  db '  drive backplane $'
s_mmode db '  Memory mode: $'
s_ext   db 'EXTENDED   EMS $'
s_ems   db 'EMS   EMS $'
s_kbems db ' KB   EXT $'
s_kbext db ' KB',13,10,'$'
s_com   db '  COM ports (BDA): $'
s_lpt   db 13,10,'  LPT ports (BDA): $'
s_equip db 13,10,'  Equipment word: $'
s_vid   db 13,10,'[2] DISPLAY',13,10,'  Port 7F8h = $'
s_panel db '  -> $'
s_pext  db 'external CRT active$'
s_p1    db 'internal plasma/EL 640x200$'
s_p5    db 'internal plasma/EL 640x400$'
s_p6    db 'internal LCD 640x200$'
s_p7    db 'internal LCD 640x400 (dual drive)$'
s_punk  db 'internal panel, unknown type$'
s_6f8   db 13,10,'  Port 6F8h = $'
s_3df   db '   V6366 control/ID (3DFh) = $'
s_cmap  db '   colour map = $'
s_m40   db '  INT 10h mode 40h -> BIOS mode byte $'
s_m40ok db ' : 640x400 hi-res mode WORKS',13,10,'$'
s_m40no db ' : no 640x400 on this panel (BIOS fell back)',13,10,'$'
s_tfill db '  VRAM fill  (rep stosw) 250 KB: $'
s_tcopy db '  RAM->VRAM  (rep movsw) 250 KB: $'
s_tread db '  VRAM read  (rep lodsw) 250 KB: $'
s_tram  db '  RAM->RAM   (rep movsw) 250 KB: $'
s_ms    db ' ms  = $'
s_kbs   db ' KB/s$'
s_pat   db 'LODESTONE 640x400 TEST - frame, diagonal, 8x16 text. Press a key.',0
s_rom   db 13,10,'[3] APPLICATION ROMS (INT 15h E400-E404)',13,10,'  max images $'
s_rdseg db '  data seg paras $'
s_rsock db '  sockets $'
s_rnone db '  E401 init failed / no ROM images, AH=$'
s_rcount db '  logical ROM images found: $'
s_rimg  db '  -- image $'
s_rerr  db '  E402 error AH=$'
s_rid   db ': id $'
s_rpar  db '  sel $'
s_rsys  db '  system type $'
s_rbase db '  window $'
s_h1    db '     flag $'
s_h2    db ' sysType $'
s_h3    db ' bootable $'
s_h4    db ' bootSeg $'
s_h5    db ' romAddr $'
s_h6    db ' sizeKB $'
s_h7    db ' wait $'
s_h8    db '     dirSel $'
s_h9    db ' dirLen $'
s_h10   db ' files $'
s_h11   db ' page0Sel $'
s_h12   db ' pages $'
s_h13   db ' romId $'
s_hc    db '     copyright $'
s_ht    db '     time      $'
s_hp    db '     part      $'
s_hb    db '     boot msg  $'
s_hi    db '     id text   $'
s_h14   db '     roms/pkg $'
s_h15   db ' sum0 $'
s_h16   db ' word250 $'
s_h17   db ' checksum $'
s_ind   db '     $'
s_noroom db '     (not enough room on A: for the 128 KB image)',13,10,'$'
s_saved db '     image saved to $'
s_werr  db '     ** error writing the image file',13,10,'$'
s_ser   db 13,10,'[4] SERIAL',13,10,'$'
s_comx  db '  COM$'
s_at    db ' at $'
s_uart  db 'h: UART present$'
s_nouart db 'h: no UART response$'
s_msr   db '  MSR $'
s_mouse db '  mouse ID bytes after DTR/RTS: $'
s_mm    db ' -> Microsoft-protocol serial mouse',13,10,'$'
s_mx    db ' -> something answered (not a Microsoft ID)',13,10,'$'
s_mnone db 'none (no serial mouse here)',13,10,'$'
s_keys  db 13,10,'[5] KEYBOARD - press keys to log their codes (Fn, Alt, Ctrl combos too).',13,10
        db '    ESC finishes.',13,10,'$'
s_key   db '  key AX=$'
s_shift db '  shift flags $'
s_done  db 13,10,'Done. Report in A:\GPROBE.TXT. Reboot before using the EPROM drive.',13,10,'$'
n_log   db 'A:\GPROBE.TXT',0
n_rom   db 'A:\ROM0.BIN',0
s_crlf  db 13,10,'$'

fh      dw 0
bufn    dw 0
pitset  db 0
nodump  db 0
dumped  db 0
blk1    dw 0
blk2    dw 0
romseg  dw 0
nimg    db 0
img     db 0
rfh     dw 0
p7f8    db 0
colmap  db 0
equip   dw 0
oldmode db 0
newmode db 0
t_fill  dd 0
t_copy  dd 0
t_read  dd 0
t_ram   dd 0
comn    db 0
cbase   dw 0
s_ier   db 0
s_lcr   db 0
s_mcr   db 0
s_dll   db 0
s_dlm   db 0
nrx     db 0
ism     db 0
nk      db 0
t0      dw 0
rx      times 16 db 0
bda     times 16 db 0
hdr     times 256 db 0
fbuf    times 512 db 0
        align 16
romds   times 256 db 0
        times 1024 db 0
stack_top:
prog_end:
