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
; (reply_busy first: txq_put doesn't read it, and returns to our caller)
reply:  push    es
        mov     dx, [ioseg]
        mov     es, dx
        mov     ah, al
        mov     al, [rq_id]
        mov     [es:0], ax
        pop     es
        add     cx, 2
        mov     al, G_REPLY
        xor     si, si
        mov     byte [reply_busy], 1
        jmp     txq_put
        times   ($ - $$) & 1 db 90h       ; (what follows even, as before)

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
op_dir: call    find_first
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

; DIR's and STAT's: FIND FIRST of the path (reqbuf+2) into our DTA ->
; CF/AX as DOS's
find_first:
        mov     dx, dta
        mov     ah, 1Ah
        int     21h
        mov     dx, reqbuf+2
        mov     cx, 16h                 ; directories, hidden, system too
        mov     ah, 4Eh
        int     21h
        ret

; offset (4), length (2), path
op_read:
        mov     dx, reqbuf+8
        mov     ax, 3D00h
        PROF    6
        int     21h
        PROF    0
        jc      .err
        mov     bx, ax
%ifdef RCON
        call    ops_nodev
        jc      .err
%endif
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
.wr:
%ifdef RCON
        call    ops_nodev
        jc      op_read.err
%endif
        mov     cx, [wr_len]
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
        jc      op_read.err             ; (the close's flush failed)
        push    es
        mov     es, [ioseg]
        mov     ax, [wr_done]
        mov     [es:2], ax
        pop     es
        xor     al, al
        mov     cx, 2
        jmp     reply

op_delete:
        mov     ah, 41h
        jmp     short op_path
op_rename:                              ; (the new name after the old one's NUL)
        mov     si, reqbuf+2
        call    skipz
        mov     di, si
        mov     ah, 56h
        jmp     short op_path
op_mkdir:
        mov     ah, 39h
        jmp     short op_path
op_rmdir:
        mov     ah, 3Ah
        ; (falls through)
; AH = DOS's call on the path, DS:DX = reqbuf+2 (RENAME: and ES:DI) -> no data
op_path:
        mov     dx, reqbuf+2
        int     21h
        jmp     dos_result

op_stat:
        call    find_first
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

; each: BL = the address; the driver's AH, then gp_go (no data) or gp_in
; (a read into ioseg:2, AL = EOI from the flags)
gp_write:
        mov     si, reqbuf+9
        mov     cx, [gp_dlen]
        mov     al, [reqbuf+4]
        and     al, 1
        mov     ah, 02h
gp_go:  call    gg_call
gp_res0:                                ; driver CF/AX, no data
        jc      .e
        xor     al, al
.e:     xor     cx, cx
        ret

gp_clear:
        mov     ah, 06h
        jmp     short gp_go
gp_trigger:
        mov     ah, 07h
        jmp     short gp_go
gp_local:
        mov     ah, 09h
        jmp     short gp_go
gp_remote:
        mov     ah, 08h
        jmp     short gp_go

gp_read:
        mov     cx, [gp_max]
        mov     ah, 03h
        jmp     short gp_in
gp_query:
        mov     si, reqbuf+9
        mov     cx, [gp_dlen]
        mov     dx, [gp_max]
        mov     ah, 04h
gp_in:  push    es
        mov     es, [ioseg]
        mov     di, 2
        mov     al, [reqbuf+4]
        and     al, 1
        call    gg_call
        pop     es
gp_resc:                                ; driver CF/AX, CX = bytes read
        jc      gp_res0.e
        xor     al, al
        ret

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
        jmp     short gp_res0.e

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
