; =====================================================================
;  OPS.INC - the GRiD's file and GPIB requests (gridlink/PROTOCOL.md), for
;  CLAUDE.COM and for resident Claude's console (RCON.ASM, which defines
;  RCON: no INFO, SETTIME or PROF there).  The includer gives reqbuf (id,
;  op, arguments) and rq_len, rq_id, ioseg (the reply's segment: id and
;  status at 0, the data from 2) and IOSIZE, dta (44 bytes), gp_dlen,
;  gp_max, wr_data, wr_len, wr_done, nano, gg_call, skipz, PROF, and
;  TERMLINK's txq_put and reply_busy; GP_OTMO, a word for the driver's
;  timeout meanwhile (default old_tmo).  DS = ES = CS.
; =====================================================================
%ifndef GP_OTMO
%define GP_OTMO old_tmo
%endif

; CF/AX from DOS, no data
dos_result:
        jc      reply0
        xor     al, al
reply0: xor     cx, cx                  ; AL = status, no data
; AL = status, CX = data bytes already at ioseg:2 -> queue the REPLY
reply:  push    es
        mov     es, [ioseg]
        mov     ah, al
        mov     al, [rq_id]
        mov     [es:0], ax
        pop     es
        add     cx, 2
        mov     al, G_REPLY
        mov     dx, [ioseg]
        xor     si, si
        call    txq_put
        mov     byte [reply_busy], 1
        ret

%ifndef RCON
op_info:
        push    es
        mov     es, [ioseg]
        mov     di, 2
        call    build_kv
        mov     cx, di
        sub     cx, 2
        pop     es
        xor     al, al
        jmp     reply

%endif
op_dir: mov     dx, dta
        mov     ah, 1Ah
        int     21h
        mov     dx, reqbuf+2
        mov     cx, 16h                 ; directories, hidden, system too
        mov     ah, 4Eh
        int     21h
        push    es
        mov     es, [ioseg]
        mov     di, 2
        jnc     .ent
        cmp     ax, 18
        je      .done
        cmp     ax, 2
        je      .done
        pop     es
        jmp     reply0
.ent:   cmp     di, IOSIZE - 24
        ja      .done
        mov     si, dta+15h             ; attribute, time, date, size, name
        mov     cx, 9 + 13
        rep     movsb
        mov     ah, 4Fh
        int     21h
        jnc     .ent
.done:  mov     cx, di
        sub     cx, 2
        pop     es
        xor     al, al
        jmp     reply

; offset (4), length (2), path
op_read:
        mov     dx, reqbuf+8
        mov     ax, 3D00h
        PROF    6
        int     21h
        PROF    0
        jc      .err
        mov     bx, ax
        mov     dx, [reqbuf+2]
        mov     cx, [reqbuf+4]
        mov     ax, 4200h
        PROF    7
        int     21h
        PROF    0
        jc      .errc
        mov     cx, [reqbuf+6]
        cmp     cx, IOSIZE - 2
        jbe     .n
        mov     cx, IOSIZE - 2
.n:     PROF    8
        push    ds
        mov     ds, [ioseg]
        mov     dx, 2
        mov     ah, 3Fh
        int     21h
        pop     ds
        PROF    0
        jc      .errc
        push    ax
        mov     ah, 3Eh
        PROF    9
        int     21h
        PROF    0
        pop     cx
        xor     al, al
        jmp     reply
.errc:  push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
.err:   jmp     reply0

; mode (1: 0 create, 1 at offset, 2 append), offset (4), path, data
op_write:
        mov     si, reqbuf+7
.z:     lodsb
        or      al, al
        jnz     .z
        mov     [wr_data], si
        mov     cx, reqbuf
        add     cx, [rq_len]
        sub     cx, si
        mov     [wr_len], cx
        mov     dx, reqbuf+7
        cmp     byte [reqbuf+2], 0
        jne     .open
        xor     cx, cx
        mov     ah, 3Ch
        PROF    6
        int     21h
        PROF    0
        jc      op_read.err
        mov     bx, ax
        jmp     .wr
.open:  mov     ax, 3D01h
        PROF    6
        int     21h
        PROF    0
        jnc     .seek
        cmp     ax, 2
        jne     op_read.err
        cmp     byte [reqbuf+2], 2      ; append to a new file: create it
        jne     op_read.err
        xor     cx, cx
        mov     ah, 3Ch
        PROF    6
        int     21h
        PROF    0
        jc      op_read.err
.seek:  mov     bx, ax
        mov     dx, [reqbuf+3]
        mov     cx, [reqbuf+5]
        mov     ax, 4200h
        cmp     byte [reqbuf+2], 1
        je      .sk
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
.sk:    PROF    7
        int     21h
        PROF    0
        jc      op_read.errc
.wr:    mov     cx, [wr_len]
        mov     dx, [wr_data]
        mov     ah, 40h
        PROF    8
        int     21h
        PROF    0
        jc      op_read.errc
        mov     [wr_done], ax
        mov     ah, 3Eh
        PROF    9
        int     21h
        PROF    0
        push    es
        mov     es, [ioseg]
        mov     ax, [wr_done]
        mov     [es:2], ax
        pop     es
        xor     al, al
        mov     cx, 2
        jmp     reply

op_delete:
        mov     dx, reqbuf+2
        mov     ah, 41h
        int     21h
        jmp     dos_result

op_rename:
        mov     si, reqbuf+2
        call    skipz
        mov     di, si
        mov     dx, reqbuf+2
        mov     ah, 56h
        int     21h
        jmp     dos_result

op_mkdir:
        mov     dx, reqbuf+2
        mov     ah, 39h
        int     21h
        jmp     dos_result

op_rmdir:
        mov     dx, reqbuf+2
        mov     ah, 3Ah
        int     21h
        jmp     dos_result

op_stat:
        mov     dx, dta
        mov     ah, 1Ah
        int     21h
        mov     dx, reqbuf+2
        mov     cx, 16h
        mov     ah, 4Eh
        int     21h
        jc      .err
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     si, dta+15h             ; attribute, time, date, size
        mov     cx, 9
        rep     movsb
        pop     es
        mov     cx, 9
        xor     al, al
        jmp     reply
.err:   jmp     reply0

op_free:
        mov     dl, [reqbuf+2]
        mov     ah, 36h
        int     21h
        cmp     ax, 0FFFFh
        jne     .ok
        mov     al, 15
        jmp     reply0
.ok:    mov     si, dx                  ; total clusters
        mul     cx                      ; bytes per cluster
        mov     cx, ax
        mov     ax, bx
        mul     cx                      ; free bytes
        push    es
        mov     es, [ioseg]
        mov     [es:2], ax
        mov     [es:4], dx
        mov     ax, si
        mul     cx                      ; total bytes
        mov     [es:6], ax
        mov     [es:8], dx
        pop     es
        mov     cx, 8
        xor     al, al
        jmp     reply

%ifndef RCON
; year (2), month, day, hour, minute, second
op_settime:
        mov     cx, [reqbuf+2]
        mov     dh, [reqbuf+4]
        mov     dl, [reqbuf+5]
        mov     ah, 2Bh
        int     21h
        mov     ch, [reqbuf+6]
        mov     cl, [reqbuf+7]
        mov     dh, [reqbuf+8]
        xor     dl, dl
        mov     ah, 2Dh
        int     21h
        mov     al, [reqbuf+6]          ; the real-time clock too (BCD)
        call    bin2bcd
        mov     ch, al
        mov     al, [reqbuf+7]
        call    bin2bcd
        mov     cl, al
        mov     al, [reqbuf+8]
        call    bin2bcd
        mov     dh, al
        xor     dl, dl
        mov     ah, 03h
        int     1Ah
        mov     ax, [reqbuf+2]
        mov     bl, 100
        div     bl                      ; AL = century, AH = year in century
        push    ax
        call    bin2bcd
        mov     ch, al
        pop     ax
        mov     al, ah
        call    bin2bcd
        mov     cl, al
        mov     al, [reqbuf+4]
        call    bin2bcd
        mov     dh, al
        mov     al, [reqbuf+5]
        call    bin2bcd
        mov     dl, al
        mov     ah, 05h
        int     1Ah
%ifdef PROFILE
        call    prof_rebase             ; (the clock moved: not a stretch of time)
%endif
        call    draw_title
        xor     al, al
        jmp     reply0

%ifdef PROFILE
op_prof:                                ; (CLAUDEP: gridlink.bench --prof)
        mov     al, [reqbuf+2]
        call    prof_window
        xor     al, al
        jmp     reply0
%endif

bin2bcd:
        aam
        shl     ah, 4
        or      al, ah
        ret

%endif
; ---- GPIB -------------------------------------------------------------
; op (1), address (1), flags (1), timeout ms (2), largest reply (2), data
op_gpib:
        mov     bx, [reqbuf+5]
        mov     ah, 0Ah
        call    gg_call
        mov     [GP_OTMO], ax
        mov     ax, [rq_len]
        sub     ax, 9
        mov     [gp_dlen], ax
        mov     cx, [reqbuf+7]
        cmp     cx, IOSIZE - 2
        jbe     .m
        mov     cx, IOSIZE - 2
.m:     mov     [gp_max], cx
        mov     al, [reqbuf+2]
        dec     al
        cmp     al, 9
        jae     .bad
        xor     ah, ah
        mov     di, ax
        shl     di, 1
        mov     bl, [reqbuf+3]
        call    [gp_tab + di]           ; -> AL = status, CX = bytes at ioseg:2
        jmp     .done
.bad:   mov     al, 4
        xor     cx, cx
.done:  push    ax
        push    cx
        mov     bx, [GP_OTMO]
        mov     ah, 0Ah
        call    gg_call
        pop     cx
        pop     ax
        jmp     reply

gp_tab: dw gp_write, gp_read, gp_query, gp_spoll, gp_clear, gp_trigger
        dw gp_local, gp_remote, gp_scan

gp_write:
        mov     si, reqbuf+9
        mov     cx, [gp_dlen]
        mov     al, [reqbuf+4]
        and     al, 1
        mov     ah, 02h
        call    gg_call
        jmp     gp_res0

gp_read:
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     cx, [gp_max]
        mov     al, [reqbuf+4]
        and     al, 1
        mov     ah, 03h
        call    gg_call
        pop     es
        jmp     gp_resc

gp_query:
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     si, reqbuf+9
        mov     cx, [gp_dlen]
        mov     dx, [gp_max]
        mov     al, [reqbuf+4]
        and     al, 1
        mov     ah, 04h
        call    gg_call
        pop     es
        jmp     gp_resc

gp_spoll:
        mov     ah, 05h
        call    gg_call
        jc      .e
        push    es
        mov     es, [ioseg]
        mov     [es:2], al
        pop     es
        mov     cx, 1
        xor     al, al
        ret
.e:     mov     al, ah
        xor     cx, cx
        ret

gp_clear:
        mov     ah, 06h
        call    gg_call
        jmp     gp_res0
gp_trigger:
        mov     ah, 07h
        call    gg_call
        jmp     gp_res0
gp_local:
        mov     ah, 09h
        call    gg_call
        jmp     gp_res0
gp_remote:
        mov     ah, 08h
        call    gg_call
        jmp     gp_res0

gp_scan:
        push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     bl, 1
.l:     cmp     bl, 21
        je      .n
        cmp     bl, [nano]
        je      .n
        mov     ah, 05h
        call    gg_call
        jc      .n
        mov     al, bl
        stosb
.n:     inc     bl
        cmp     bl, 31
        jb      .l
        mov     cx, di
        sub     cx, 2
        pop     es
        xor     al, al
        ret

gp_res0:                                ; driver CF/AX, no data
        jc      .e
        xor     al, al
.e:     xor     cx, cx
        ret

gp_resc:                                ; driver CF/AX, CX = bytes read
        jc      .e
        xor     al, al
        ret
.e:     xor     cx, cx
        ret
