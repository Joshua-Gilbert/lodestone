; =====================================================================
;  EXEC.INC - the Executive (Grid-OS 0.1's screen, now running programs)
; =====================================================================
%include "EXECRUN.INC"

; ---------------------------------------------------------------------
main:   cmp     byte [mflag], 0
        je      .nomouse
        call    act_now
        call    mouse_event
.nomouse:
        mov     ah, 1
        int     16h
        jz      .nokey
        call    act_now
        xor     ah, ah
        int     16h
        call    key
        jmp     main
.nokey: push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        mov     bx, ax                  ; idle 5 minutes: the screen saver
        sub     bx, [lastact]
        cmp     bx, 8000h               ; (the clock went back at midnight)
        jb      .sv
        mov     [lastact], ax
        jmp     .ck
.sv:    cmp     bx, SAVER_T
        jb      .ck
        call    saver
        jmp     main
.ck:    mov     bx, ax
        sub     bx, [lasttick]
        cmp     bx, 9                   ; ~0.5 s
        jb      .idle
        mov     [lasttick], ax
        call    clock_tick
.idle:  sti
        hlt                             ; sleep until the next interrupt
        jmp     main

; =====================================================================
; keyboard
; =====================================================================
key:    cmp     byte [helpopen], 0
        je      .nohelp
        jmp     close_help
.nohelp:
        cmp     byte [msgshown], 0
        je      .nomsg
        mov     byte [msgshown], 0
        push    ax
        call    hide_cursor
        call    draw_prompt_default
        call    show_cursor
        pop     ax
        cmp     al, 0Dh
        jne     .nomsg
        ret
.nomsg: cmp     ah, 48h
        je      .up
        cmp     ah, 50h
        je      .down
        cmp     ah, 49h
        je      .pgup
        cmp     ah, 51h
        je      .pgdn
        cmp     ah, 47h
        je      .home
        cmp     ah, 4Fh
        je      .end
        cmp     al, 0Dh
        je      confirm
        cmp     ah, 3Bh                 ; F1
        je      open_help
        or      al, al
        jnz     .x
        cmp     ah, 35h                 ; CODE-/ or CODE-?
        je      open_help
        cmp     ah, 20h                 ; CODE-D
        je      boot_rom
        cmp     ah, 13h                 ; CODE-R
        je      reboot
        cmp     ah, 2Eh                 ; CODE-C
        je      run_shell
        cmp     ah, 1Eh                 ; CODE-A
        je      run_claude
        cmp     ah, 3Fh                 ; F5
        je      refresh
.x:     ret
.up:    mov     ax, -1
        jmp     sel_move
.down:  mov     ax, 1
        jmp     sel_move
.pgup:  mov     ax, -LIST_N
        jmp     sel_move
.pgdn:  mov     ax, LIST_N
        jmp     sel_move
.home:  mov     ax, -30000
        jmp     sel_move
.end:   mov     ax, 30000
        jmp     sel_move

; AX = signed delta
sel_move:
        mov     cx, [nent]
        jcxz    .x
        mov     bx, [sel]
        add     ax, bx
        jns     .p
        xor     ax, ax
.p:     cmp     ax, cx
        jb      .in
        mov     ax, cx
        dec     ax
.in:    cmp     ax, bx
        je      .x
        jmp     select_ax
.x:     ret

; select entry AX (redraws what changed)
select_ax:
        mov     bx, [sel]
        mov     [sel], ax
        mov     cx, [top]
        cmp     ax, cx
        jb      .scroll_up
        add     cx, LIST_N
        cmp     ax, cx
        jae     .scroll_dn
        call    hide_cursor
        mov     ax, bx
        call    draw_row
        mov     ax, [sel]
        call    draw_row
        jmp     .form
.scroll_up:
        mov     [top], ax
        jmp     .full
.scroll_dn:
        sub     ax, LIST_N - 1
        mov     [top], ax
.full:  call    hide_cursor
        call    draw_list
.form:  call    draw_form
        jmp     show_cursor

boot_rom:
        call    mouse_off
        mov     ax, 0003h
        int     10h
        mov     si, s_bootrom
        call    bios_print
        int     19h                     ; BIOS boot loop: EPROM first

reboot: call    mouse_off
        push    0
        pop     ds
        mov     word [472h], 1234h      ; warm boot
        jmp     0F000h:0FFF0h

; =====================================================================
; mouse (Microsoft serial protocol, 1200 7N1) - COM2 first, then COM1
; =====================================================================
mouse_init:
        mov     word [mbase], 2F8h
        mov     byte [mirq], 3
        call    mouse_probe
        jnc     .found
        mov     word [mbase], 3F8h
        mov     byte [mirq], 4
        call    mouse_probe
        jnc     .found
        mov     word [mbase], 0
        ret
.found: mov     ax, [mbase]
        mov     [mfound], ax
mouse_hook:
        cli
        xor     ax, ax
        mov     es, ax
        mov     bl, [mirq]
        xor     bh, bh
        add     bx, 8
        shl     bx, 2                   ; IVT slot of IRQ3/4 (INT 0Bh/0Ch)
        mov     ax, [es:bx]
        mov     [oldvec], ax
        mov     ax, [es:bx+2]
        mov     [oldvec+2], ax
        mov     word [es:bx], mouse_isr
        mov     [es:bx+2], cs
        mov     [vecslot], bx
        mov     dx, [mbase]
        inc     dx
        mov     al, 1                   ; IER: received-data interrupt
        out     dx, al
        add     dx, 3
        mov     al, 0Bh                 ; MCR: DTR + RTS + OUT2 (IRQ gate)
        out     dx, al
        mov     cl, [mirq]
        mov     ah, 1
        shl     ah, cl
        not     ah
        in      al, 21h
        and     al, ah
        out     21h, al
        mov     dx, [mbase]
        in      al, dx                  ; clear any pending byte
        sti
        push    cs
        pop     es
        ret

; CF clear if a Microsoft mouse answers 'M' at [mbase]
mouse_probe:
        mov     dx, [mbase]
        add     dx, 7
        mov     al, 5Ah
        out     dx, al
        jmp     short $+2
        in      al, dx
        cmp     al, 5Ah
        jne     .no
        mov     dx, [mbase]
        inc     dx
        xor     al, al
        out     dx, al                  ; IER off
        add     dx, 2
        mov     al, 80h
        out     dx, al                  ; DLAB
        mov     dx, [mbase]
        mov     al, 96                  ; 1200 baud
        out     dx, al
        inc     dx
        xor     al, al
        out     dx, al
        add     dx, 2
        mov     al, 02h                 ; 7N1
        out     dx, al
        inc     dx
        xor     al, al
        out     dx, al                  ; DTR/RTS off: mouse powers down
        mov     cx, 3
        call    wait_ticks
        call    uart_drain
        mov     dx, [mbase]
        add     dx, 4
        mov     al, 03h
        out     dx, al                  ; DTR/RTS on: mouse sends 'M'
        call    tick
        mov     si, ax
.poll:  mov     dx, [mbase]
        add     dx, 5
        in      al, dx
        test    al, 1
        jz      .t
        mov     dx, [mbase]
        in      al, dx
        cmp     al, 'M'
        je      .yes
.t:     call    tick
        sub     ax, si
        cmp     ax, 6
        jb      .poll
.no:    stc
        ret
.yes:   clc
        ret

uart_drain:
        mov     cx, 16
.d:     mov     dx, [mbase]
        add     dx, 5
        in      al, dx
        test    al, 1
        jz      .x
        mov     dx, [mbase]
        in      al, dx
        loop    .d
.x:     ret

mouse_off:
        cmp     word [mbase], 0
        je      .x
        cli
        mov     dx, [mbase]
        inc     dx
        xor     al, al
        out     dx, al
        add     dx, 3
        out     dx, al
        mov     cl, [mirq]
        mov     ah, 1
        shl     ah, cl
        in      al, 21h
        or      al, ah
        out     21h, al
        xor     ax, ax
        mov     es, ax
        mov     bx, [vecslot]
        mov     ax, [oldvec]
        mov     [es:bx], ax
        mov     ax, [oldvec+2]
        mov     [es:bx+2], ax
        mov     word [mbase], 0
        sti
.x:     ret

mouse_isr:
        push    ax
        push    bx
        push    dx
.rd:    mov     dx, [cs:mbase]
        add     dx, 5
        in      al, dx
        test    al, 1
        jz      .done
        mov     dx, [cs:mbase]
        in      al, dx
        test    al, 40h                 ; first byte of a packet
        jz      .nf
        mov     byte [cs:midx], 0
.nf:    mov     bl, [cs:midx]
        cmp     bl, 3
        jae     .rd
        xor     bh, bh
        mov     [cs:mpkt+bx], al
        inc     bl
        mov     [cs:midx], bl
        cmp     bl, 3
        jne     .rd
        cmp     byte [cs:mpkt], 40h     ; packet must start with a sync byte
        jb      .rd
        mov     al, [cs:mpkt]           ; dx = (b0 & 3) << 6 | b1
        mov     ah, al
        and     al, 3
        shl     al, 6
        or      al, [cs:mpkt+1]
        cbw
        add     ax, [cs:mx]
        jns     .x1
        xor     ax, ax
.x1:    cmp     ax, 639
        jbe     .x2
        mov     ax, 639
.x2:    mov     [cs:mx], ax
        mov     al, [cs:mpkt]           ; dy = (b0 & 0Ch) << 4 | b2
        and     al, 0Ch
        shl     al, 4
        or      al, [cs:mpkt+2]
        cbw
        add     ax, [cs:my]
        jns     .y1
        xor     ax, ax
.y1:    cmp     ax, 399
        jbe     .y2
        mov     ax, 399
.y2:    mov     [cs:my], ax
        mov     al, [cs:mpkt]           ; buttons: 20h left, 10h right
        xor     bl, bl
        test    al, 20h
        jz      .b1
        or      bl, 1
.b1:    test    al, 10h
        jz      .b2
        or      bl, 2
.b2:    mov     [cs:mb], bl
        mov     byte [cs:mflag], 1
        jmp     .rd
.done:  mov     al, 20h
        out     20h, al
        pop     dx
        pop     bx
        pop     ax
        iret

; main-loop side of the mouse: move the cursor, handle clicks
mouse_event:
        cli
        mov     byte [mflag], 0
        mov     ax, [mx]
        mov     bx, [my]
        mov     cl, [mb]
        sti
        cmp     ax, [cur_x]
        jne     .mv
        cmp     bx, [cur_y]
        je      .btn
.mv:    push    cx
        cli
        mov     ax, [mx]                ; freshest position
        mov     bx, [my]
        sti
        call    move_cursor             ; flicker-free: never erased first
        pop     cx
.btn:   mov     ch, [oldmb]
        mov     [oldmb], cl
        test    cl, 1
        jz      .x
        test    ch, 1
        jnz     .x                      ; only on press
        ; click
        cmp     byte [helpopen], 0
        je      .nh
        jmp     close_help
.nh:    cmp     byte [msgshown], 0
        je      .nm
        mov     byte [msgshown], 0
        call    hide_cursor
        call    draw_prompt_default
        call    show_cursor
        ret
.nm:    mov     ax, [my]
        cmp     ax, BAND_Y
        jb      .notband
        jmp     open_help               ; click the prompt band = help
.notband:
        sub     ax, LIST_Y
        jb      .x
        shr     ax, 4
        cmp     ax, LIST_N
        jae     .x
        add     ax, [top]
        cmp     ax, [nent]
        jae     .x
        cmp     ax, [sel]
        je      confirm                 ; click the selected file = confirm
        jmp     select_ax
.x:     ret

; arrow cursor: 13 rows of (shape, spare); drawn by inverting the shape
cur_shape:
        db 10000000b, 00000000b
        db 11000000b, 00000000b
        db 11100000b, 01000000b
        db 11110000b, 01100000b
        db 11111000b, 01110000b
        db 11111100b, 01111000b
        db 11111110b, 01111100b
        db 11111111b, 01111110b
        db 11111111b, 01110000b
        db 11111000b, 01010000b
        db 11011100b, 00001000b
        db 10011100b, 00001000b
        db 00001100b, 00000000b

show_cursor:
        cmp     word [mbase], 0
        je      .x
        cmp     byte [curvis], 0
        jne     .x
        pusha
        push    es
        push    cs
        pop     es
        mov     ax, [mx]
        mov     bx, [my]
        mov     [cnew_x], ax
        mov     [cnew_y], bx
        shr     ax, 3
        mov     [cnew_xb], ax
        call    move_cursor.rect
        mov     byte [cflags], 2
        call    compose
        mov     si, new_save
        mov     di, cur_save
        mov     cx, 26
        rep     movsb
        mov     ax, [cnew_x]
        mov     [cur_x], ax
        mov     ax, [cnew_y]
        mov     [cur_y], ax
        mov     ax, [cnew_xb]
        mov     [cur_xb], ax
        mov     byte [curvis], 1
        pop     es
        popa
.x:     ret

; move_cursor: AX = new x, BX = new y.  The old and new cursor areas are
; composed in RAM and every screen byte is written once, so there is no
; moment without a cursor (the old erase-then-draw flickered on the plasma).
move_cursor:
        cmp     byte [curvis], 0
        jne     .vis
        jmp     show_cursor
.vis:   pusha
        push    es
        push    cs
        pop     es
        mov     [cnew_x], ax
        mov     [cnew_y], bx
        shr     ax, 3
        mov     [cnew_xb], ax
        sub     ax, [cur_xb]            ; overlapping areas?
        jns     .a1
        neg     ax
.a1:    cmp     ax, 2
        jae     .disj
        mov     ax, bx
        sub     ax, [cur_y]
        jns     .a2
        neg     ax
.a2:    cmp     ax, 13
        jae     .disj
        mov     ax, [cnew_xb]           ; union of both areas
        mov     dx, [cur_xb]
        cmp     ax, dx
        jbe     .u1
        xchg    ax, dx
.u1:    mov     [ux0], ax
        sub     dx, ax
        add     dx, 2
        mov     cx, 80
        sub     cx, ax
        cmp     dx, cx
        jbe     .u2
        mov     dx, cx
.u2:    mov     [uw], dx
        mov     ax, [cnew_y]
        mov     dx, [cur_y]
        cmp     ax, dx
        jbe     .u3
        xchg    ax, dx
.u3:    mov     [uy0], ax
        sub     dx, ax
        add     dx, 13
        mov     cx, 400
        sub     cx, ax
        cmp     dx, cx
        jbe     .u4
        mov     dx, cx
.u4:    mov     [uh], dx
        mov     byte [cflags], 3
        call    compose
        jmp     .done
.disj:  mov     ax, [cnew_xb]           ; far apart: draw new, then erase old
        mov     bx, [cnew_y]
        call    .rect
        mov     byte [cflags], 2
        call    compose
        mov     ax, [cur_xb]
        mov     bx, [cur_y]
        call    .rect
        mov     byte [cflags], 1
        call    compose
.done:  mov     si, new_save
        mov     di, cur_save
        mov     cx, 26
        rep     movsb
        mov     ax, [cnew_x]
        mov     [cur_x], ax
        mov     ax, [cnew_y]
        mov     [cur_y], ax
        mov     ax, [cnew_xb]
        mov     [cur_xb], ax
        pop     es
        popa
        ret
.rect:  mov     [ux0], ax               ; AX = byte col, BX = y
        mov     cx, 80
        sub     cx, ax
        cmp     cx, 2
        jbe     .w
        mov     cx, 2
.w:     mov     [uw], cx
        mov     [uy0], bx
        mov     cx, 400
        sub     cx, bx
        cmp     cx, 13
        jbe     .h
        mov     cx, 13
.h:     mov     [uh], cx
        ret

; compose the area (ux0, uy0, uw, uh) in ubuf:  cflags bit 0 = restore the
; old cursor's background, bit 1 = save under and draw the new cursor
compose:
        pusha
        push    es
        push    VSEG
        pop     es
        xor     bp, bp                  ; 1. screen -> ubuf
.r1:    cmp     bp, [uh]
        jae     .r1d
        mov     bx, [uy0]
        add     bx, bp
        shl     bx, 1
        mov     si, [rowtab+bx]
        add     si, [ux0]
        mov     di, bp
        shl     di, 2
        add     di, ubuf
        mov     cx, [uw]
.c1:    mov     al, [es:si]
        mov     [di], al
        inc     si
        inc     di
        loop    .c1
        inc     bp
        jmp     .r1
.r1d:   test    byte [cflags], 1        ; 2. old background back into ubuf
        jz      .noold
        xor     bp, bp
.r2:    mov     ax, [cur_y]
        add     ax, bp
        cmp     ax, 400
        jae     .noold
        sub     ax, [uy0]
        shl     ax, 2
        add     ax, ubuf
        mov     di, ax
        mov     bx, bp
        shl     bx, 1
        mov     dx, [cur_xb]
        call    .old1
        inc     dx
        inc     bx
        call    .old1
        inc     bp
        cmp     bp, 13
        jb      .r2
.noold: test    byte [cflags], 2        ; 3. save under + draw new cursor
        jz      .nonew
        mov     cx, [cnew_x]
        and     cl, 7
        xor     bp, bp
.r3:    mov     ax, [cnew_y]
        add     ax, bp
        cmp     ax, 400
        jae     .nonew
        sub     ax, [uy0]
        shl     ax, 2
        add     ax, ubuf
        mov     si, [cnew_xb]
        sub     si, [ux0]
        add     si, ax
        mov     bx, bp
        shl     bx, 1
        mov     dh, [cur_shape+bx]
        xor     dl, dl
        shr     dx, cl                  ; arrow shape
        mov     al, [si]                ; invert what is underneath
        mov     [new_save+bx], al
        xor     al, dh
        mov     [si], al
        cmp     word [cnew_xb], 79
        jae     .n2
        mov     al, [si+1]
        mov     [new_save+bx+1], al
        xor     al, dl
        mov     [si+1], al
.n2:    inc     bp
        cmp     bp, 13
        jb      .r3
.nonew: xor     bp, bp                  ; 4. ubuf -> screen, once
.r4:    cmp     bp, [uh]
        jae     .r4d
        mov     bx, [uy0]
        add     bx, bp
        shl     bx, 1
        mov     di, [rowtab+bx]
        add     di, [ux0]
        mov     si, bp
        shl     si, 2
        add     si, ubuf
        mov     cx, [uw]
.c4:    mov     al, [si]
        mov     [es:di], al
        inc     si
        inc     di
        loop    .c4
        inc     bp
        jmp     .r4
.r4d:   pop     es
        popa
        ret
.old1:  cmp     dx, 80                  ; DX = byte col, DI = ubuf row, BX = save index
        jae     .ox
        mov     si, dx
        sub     si, [ux0]
        cmp     si, [uw]
        jae     .ox
        add     si, di
        mov     al, [cur_save+bx]
        mov     [si], al
.ox:    ret

hide_cursor:
        cmp     byte [curvis], 0
        je      .x
        pusha
        push    es
        push    VSEG
        pop     es
        xor     si, si
.row:   mov     bx, [cur_y]
        add     bx, si
        cmp     bx, 400
        jae     .done
        shl     bx, 1
        mov     di, [rowtab+bx]
        add     di, [cur_xb]
        mov     bx, si
        shl     bx, 1
        mov     al, [cur_save+bx]
        mov     [es:di], al
        cmp     word [cur_xb], 79
        jae     .nx
        mov     al, [cur_save+bx+1]
        mov     [es:di+1], al
.nx:    inc     si
        cmp     si, 13
        jb      .row
.done:  mov     byte [curvis], 0
        pop     es
        popa
.x:     ret

; =====================================================================
; help window (minimal: 1-px frame, inverse title strip, save-under)
; =====================================================================
HW_X    equ 16                  ; byte column
HW_W    equ 48                  ; bytes
HW_Y    equ 64
HW_H    equ 232

open_help:
        cmp     byte [helpopen], 0
        jne     .x
        call    hide_cursor
        push    ds                      ; save what is underneath
        push    es
%ifndef NOTC
        mov     byte [tc_drv], 0FFh     ; in the disk cache's memory, which
        mov     byte [tc_lock], 1       ; the disk does without meanwhile
        mov     es, [tc_seg]
        xor     di, di
%else
        push    ds
        pop     es
        mov     di, savebuf
%endif
        mov     dx, HW_Y
        mov     cx, HW_H
.sv:    mov     bx, dx
        shl     bx, 1
        mov     si, [rowtab+bx]
        add     si, HW_X
        push    cx
        push    ds
        push    VSEG
        pop     ds
        mov     cx, HW_W
        rep     movsb
        pop     ds
        pop     cx
        inc     dx
        loop    .sv
        pop     es
        pop     ds
        ; body
        mov     dx, HW_Y
        mov     cx, HW_H
        mov     bx, HW_X
        mov     bp, HW_W
        xor     al, al
        call    fill_band
        mov     dx, HW_Y                ; title strip
        mov     cx, 20
        mov     al, 0FFh
        call    fill_band
        mov     si, s_hlptitle
        mov     bx, HW_X + 2
        mov     dx, HW_Y + 4
        mov     ah, 0FFh
        call    puts
        ; frame
        mov     dx, HW_Y + HW_H - 1
        mov     bx, HW_X
        mov     cx, HW_W
        call    hline
        mov     ax, HW_X * 8
        mov     dx, HW_Y
        mov     cx, HW_H
        call    vline
        mov     ax, (HW_X + HW_W) * 8 - 1
        call    vline
        ; text
        mov     si, help_text
        mov     dx, HW_Y + 28
.ln:    cmp     byte [si], 0FFh
        je      .done
        mov     bx, HW_X + 3
        xor     ah, ah
        call    puts
        add     dx, 16
        jmp     .ln
.done:  mov     byte [helpopen], 1
        call    show_cursor
.x:     ret

close_help:
        call    hide_cursor
        push    es
        push    VSEG
        pop     es
%ifndef NOTC
        xor     si, si
%else
        mov     si, savebuf
%endif
        mov     dx, HW_Y
        mov     cx, HW_H
.rs:    mov     bx, dx
        shl     bx, 1
        mov     di, [rowtab+bx]
        add     di, HW_X
        push    cx
        mov     cx, HW_W
%ifndef NOTC
        push    ds
        mov     ds, [tc_seg]
        rep     movsb
        pop     ds
%else
        rep     movsb
%endif
        pop     cx
        inc     dx
        loop    .rs
        pop     es
%ifndef NOTC
        mov     byte [tc_lock], 0       ; the disk cache has it back
%endif
        mov     byte [helpopen], 0
        jmp     show_cursor

; =====================================================================
; screen layout
; =====================================================================
draw_all:
        call    clear_screen
        call    draw_clock
        mov     si, s_brand
        mov     dx, 0
        call    center
        mov     dx, RULE1
        xor     bx, bx
        mov     cx, 80
        call    hline
        call    draw_list
        mov     dx, RULE2
        xor     bx, bx
        mov     cx, 80
        call    hline
        mov     si, s_lbl_dev
        mov     bx, TCOL
        mov     dx, FORM_Y
        xor     ah, ah
        call    puts
        mov     si, s_lbl_sub
        mov     dx, FORM_Y + 16
        call    puts
        mov     si, s_lbl_tit
        mov     dx, FORM_Y + 36
        call    puts
        mov     si, s_lbl_kind
        mov     dx, FORM_Y + 56
        call    puts
        mov     si, s_lbl_size
        mov     dx, FORM_Y + 72
        call    puts
        call    draw_form
        mov     si, infobuf
        mov     dx, INFO_Y
        call    center
        mov     dx, INFO_Y - 4
        mov     bx, 1
        mov     cx, 78
        call    hline_dots
        jmp     draw_prompt_default

draw_prompt_default:
        call    band_clear
        mov     si, s_prompt1
        mov     dx, BAND_Y + 4
        call    band_center
        mov     si, s_prompt2
        mov     dx, BAND_Y + 20
        jmp     band_center

band_clear:
        mov     dx, BAND_Y
        mov     cx, 400 - BAND_Y
        xor     bx, bx
        mov     bp, 80
        mov     al, 0FFh
        jmp     fill_band

band_center:                            ; SI = text, DX = y (inverse)
        call    strlen
        mov     bx, 80
        sub     bx, cx
        shr     bx, 1
        mov     ah, 0FFh
        jmp     puts

center: call    strlen                  ; SI = text, DX = y
        mov     bx, 80
        sub     bx, cx
        shr     bx, 1
        xor     ah, ah
        jmp     puts

draw_list:
        mov     cx, LIST_N
        mov     ax, [top]
.l:     push    ax
        push    cx
        call    draw_row
        pop     cx
        pop     ax
        inc     ax
        loop    .l
        cmp     word [nent], 0
        jne     .x
        mov     si, s_empty
        mov     dx, LIST_Y + 16
        call    center
.x:     ret

; draw list row for entry AX (if visible)
draw_row:
        mov     bx, ax
        sub     ax, [top]
        jb      .x
        cmp     ax, LIST_N
        jae     .x
        shl     ax, 4
        add     ax, LIST_Y
        mov     dx, ax                  ; DX = y
        push    bx
        xor     al, al
        cmp     bx, [sel]
        jne     .f
        cmp     word [nent], 0
        je      .f
        mov     al, 0FFh
.f:     mov     [rowmask], al
        push    dx
        mov     cx, 16
        mov     bx, 1
        mov     bp, 78
        call    fill_band
        pop     dx
        pop     bx
        cmp     bx, [nent]
        jae     .x
        call    ent_ptr                 ; SI -> directory entry
        mov     di, tmp
        call    sb_title
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, TCOL
        mov     ah, [rowmask]
        call    puts
        pop     si
        ; date
        mov     di, tmp
        mov     ax, [si+24]
        call    sb_date
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, 40
        mov     ah, [rowmask]
        call    puts
        pop     si
        ; size (files only)
        test    byte [si+11], 10h
        jnz     .nosz
        mov     di, tmp
        mov     ax, [si+28]
        mov     cx, [si+30]
        call    sb_u32
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, 60
        call    strlen
        sub     bx, cx
        mov     ah, [rowmask]
        call    puts
        pop     si
.nosz:  call    kind_of
        call    strlen
        mov     bx, KEND
        sub     bx, cx
        mov     ah, [rowmask]
        call    puts
.x:     ret

; form under the list for the selected entry
draw_form:
        ; clear value area (cols 12..79 of the five form rows)
        mov     dx, FORM_Y
        mov     cx, 88
        mov     bx, 12
        mov     bp, 67
        xor     al, al
        call    fill_band
        mov     ah, 19h
        int     21h
        mov     si, s_dev_a
        add     al, 'A'
        mov     [s_dev_a + 7], al
        mov     bx, 14
        mov     dx, FORM_Y
        xor     ah, ah
        call    puts
        mov     si, subject
        cmp     word [si], '\'
        jne     .sub
        mov     si, s_root
.sub:   mov     dx, FORM_Y + 16
        call    puts
        ; title box
        mov     dx, FORM_Y + 33
        mov     bx, 13
        mov     cx, 28
        call    hline
        mov     dx, FORM_Y + 54
        call    hline
        mov     ax, 13 * 8
        mov     dx, FORM_Y + 33
        mov     cx, 22
        call    vline
        mov     ax, 41 * 8 - 1
        call    vline
        cmp     word [nent], 0
        je      .x
        mov     bx, [sel]
        call    ent_ptr
        mov     di, tmp
        call    sb_title
        mov     byte [di], 0
        push    si
        mov     si, tmp
        mov     bx, 14
        mov     dx, FORM_Y + 36
        xor     ah, ah
        call    puts
        pop     si
        call    kind_of
        mov     bx, 14
        mov     dx, FORM_Y + 56
        xor     ah, ah
        call    puts
        mov     bx, [sel]
        call    ent_ptr
        mov     di, tmp
        test    byte [si+11], 10h
        jnz     .dir
        mov     ax, [si+28]
        mov     cx, [si+30]
        call    sb_u32
        push    si
        mov     si, s_bytes
        call    sb_str
        pop     si
        push    si
        mov     si, s_dated
        jmp     .dt
.dir:   push    si
        mov     si, s_dated + 3
.dt:    call    sb_str
        pop     si
        mov     ax, [si+24]
        call    sb_date
        mov     byte [di], 0
        mov     si, tmp
        mov     bx, 14
        mov     dx, FORM_Y + 72
        xor     ah, ah
        call    puts
.x:     ret

; =====================================================================
; clock (RTC through INT 1Ah)
; =====================================================================
read_clock:
        mov     ah, 2
        int     1Ah
        mov     [rtc_h], ch
        mov     [rtc_m], cl
        mov     ah, 4
        int     1Ah
        mov     [rtc_y], cl
        mov     [rtc_mo], dh
        mov     [rtc_d], dl
        ret

clock_tick:
        mov     al, [rtc_m]
        push    ax
        call    read_clock
        pop     ax
        cmp     al, [rtc_m]
        je      .x
        call    hide_cursor
        call    draw_clock
        call    show_cursor
.x:     ret

draw_clock:
        mov     dx, 0
        mov     cx, 16
        mov     bx, 1
        mov     bp, 11
        xor     al, al
        call    fill_band
        mov     bx, 67
        call    fill_band
        mov     di, tmp
        call    sb_dmy
        mov     si, tmp
        mov     bx, 1
        xor     dx, dx
        xor     ah, ah
        call    puts
        mov     di, tmp
        call    sb_hm
        mov     si, tmp
        call    strlen
        mov     bx, 79
        sub     bx, cx
        xor     dx, dx
        xor     ah, ah
        jmp     puts

; "4-Oct-26" at DI (NUL-terminated)
sb_dmy: mov     al, [rtc_d]
        call    bcd
        call    sb_u16
        mov     al, '-'
        stosb
        mov     al, [rtc_mo]
        call    bcd
        dec     ax
        cmp     ax, 11
        jbe     .mo
        xor     ax, ax
.mo:    imul    si, ax, 3
        add     si, months
        movsw
        movsb
        mov     al, '-'
        stosb
        mov     al, [rtc_y]
        call    bcd
        call    sb_2d
        mov     byte [di], 0
        ret

; "5:31 pm" at DI (NUL-terminated)
sb_hm:  mov     al, [rtc_h]
        call    bcd
        mov     si, s_am
        cmp     ax, 12
        jb      .am
        mov     si, s_pm
        sub     ax, 12
.am:    or      ax, ax
        jnz     .h
        mov     ax, 12
.h:     push    si
        call    sb_u16
        mov     al, ':'
        stosb
        mov     al, [rtc_m]
        call    bcd
        call    sb_2d
        pop     si
        call    sb_str
        mov     byte [di], 0
        ret

bcd:    mov     ah, al                  ; AL = BCD -> AX = binary
        shr     ah, 4
        and     al, 0Fh
        aad
        xor     ah, ah
        ret

; insertion sort of entlist: "..", then subjects, then files, by name
sort_dir:
        mov     cx, [nent]
        cmp     cx, 2
        jb      .x
        mov     bx, 2                   ; byte index i
.i:     mov     dx, [entlist+bx]        ; key
        mov     bp, bx
.j:     or      bp, bp
        jz      .put
        mov     si, [entlist+bp-2]
        mov     di, dx
        call    ent_cmp
        jbe     .put                    ; prev <= key
        mov     ax, [entlist+bp-2]
        mov     [entlist+bp], ax
        sub     bp, 2
        jmp     .j
.put:   mov     [entlist+bp], dx
        add     bx, 2
        mov     ax, [nent]
        shl     ax, 1
        cmp     bx, ax
        jb      .i
.x:     ret

; compare entries SI and DI: flags as for SI - DI
ent_cmp:
        push    cx
        push    si
        push    di
        call    .rank
        mov     ah, al
        xchg    si, di
        call    .rank
        xchg    si, di
        cmp     ah, al
        jne     .x
        mov     cx, 11
        repe    cmpsb
.x:     pop     di
        pop     si
        pop     cx
        ret
.rank:  mov     al, 0
        cmp     word [si], '..'
        je      .r
        mov     al, 1
        test    byte [si+11], 10h
        jnz     .r
        mov     al, 2
.r:     ret

ent_ptr:                                ; BX = index -> SI = entry
        push    bx
        shl     bx, 1
        mov     si, [entlist+bx]
        pop     bx
        ret

; append the entry's title (name without trailing spaces) at DI
sb_title:
        push    si
        mov     cx, 8
.c:     lodsb
        cmp     al, ' '
        je      .x
        stosb
        loop    .c
.x:     pop     si
        ret

; SI = entry -> SI = kind string (entry pointer lost; callers re-fetch)
kind_of:
        test    byte [si+11], 10h
        jz      .file
        mov     si, k_subject
        ret
.file:  push    dx
        call    .look
        pop     dx
        ret
.look:  mov     ax, [si+8]
        mov     dl, [si+10]
        mov     bx, kinds
.k:     cmp     byte [bx], 0
        je      .raw
        cmp     ax, [bx]
        jne     .n
        cmp     dl, [bx+2]
        jne     .n
        mov     si, [bx+3]
        ret
.n:     add     bx, 5
        jmp     .k
.raw:   mov     si, kindbuf             ; unknown extension: show it
        mov     [si], ax
        mov     [si+2], dl
        mov     byte [si+3], 0
        cmp     byte [si], ' '
        jne     .r
        mov     si, k_file
.r:     ret

; =====================================================================
; system information line
; =====================================================================
sysinfo:
        int     12h
        mov     [convkb], ax
        mov     ax, 0E440h
        int     15h
        jnc     .e1
        xor     cx, cx
.e1:    mov     [emskb], cx
        mov     ax, 0E441h
        int     15h
        jnc     .e2
        xor     cx, cx
.e2:    mov     [extkb], cx
        int     11h
        mov     [equip], ax
        mov     dx, 7F8h
        in      al, dx
        mov     [panel], al
        push    ds
        mov     ax, 0F000h
        mov     ds, ax
        mov     si, 0FFF5h
        push    cs
        pop     es
        mov     di, biosdate
        mov     cx, 8
        rep     movsb
        pop     ds
        ret

build_info:
        mov     di, infobuf
        mov     si, s_cpu
        call    sb_str
        test    byte [equip], 2
        jz      .nf
        mov     si, s_fpu
        call    sb_str
.nf:    mov     si, s_gap
        call    sb_str
        mov     ax, [convkb]
        call    sb_u16
        mov     si, s_k
        call    sb_str
        mov     ax, [emskb]
        mov     si, s_ems
        or      ax, ax
        jnz     .m
        mov     ax, [extkb]
        mov     si, s_ext
.m:     push    si
        push    ax
        mov     si, s_plus
        call    sb_str
        pop     ax
        call    sb_u16
        pop     si
        call    sb_str
        mov     si, s_gap
        call    sb_str
        mov     al, [panel]
        and     al, 0Fh
        mov     si, s_plasma
        cmp     al, 0Dh
        je      .p
        mov     si, s_lcd
        cmp     al, 0Fh
        je      .p
        mov     si, s_panel
.p:     call    sb_str
        mov     si, s_gap
        call    sb_str
        mov     si, s_nomouse
        mov     ax, [mbase]
        or      ax, ax
        jz      .mo
        mov     si, s_mouse2
        cmp     ax, 2F8h
        je      .mo
        mov     si, s_mouse1
.mo:    call    sb_str
        mov     si, s_gap
        call    sb_str
        mov     si, s_bios
        call    sb_str
        mov     si, biosdate
        mov     cx, 8
        rep     movsb
        mov     byte [di], 0
        ret

; =====================================================================
; drawing primitives
; =====================================================================
mkrows: xor     bx, bx
        mov     di, rowtab
.l:     mov     ax, bx
        and     ax, 3
        shl     ax, 13
        mov     dx, bx
        shr     dx, 2
        imul    dx, dx, 80
        add     ax, dx
        mov     [di], ax
        add     di, 2
        inc     bx
        cmp     bx, 400
        jb      .l
        ret

clear_screen:
        push    es
        push    VSEG
        pop     es
        xor     di, di
        mov     cx, 16384
        xor     ax, ax
        rep     stosw
        pop     es
        ret

; DX = y, CX = rows, BX = byte column, BP = width in bytes, AL = value
fill_band:
        pusha
        push    es
        push    VSEG
        pop     es
.r:     mov     si, dx
        shl     si, 1
        mov     di, [rowtab+si]
        add     di, bx
        push    cx
        mov     cx, bp
        rep     stosb
        pop     cx
        inc     dx
        loop    .r
        pop     es
        popa
        ret

; DX = y, BX = byte column, CX = width in bytes
hline:  pusha
        mov     bp, cx
        mov     cx, 1
        mov     al, 0FFh
        call    fill_band
        popa
        ret

; dotted rule: DX = y, BX = column, CX = width
hline_dots:
        pusha
        mov     bp, cx
        mov     cx, 1
        mov     al, 0AAh
        call    fill_band
        popa
        ret

; AX = pixel x, DX = y0, CX = height
vline:  pusha
        push    es
        push    VSEG
        pop     es
        mov     bx, ax
        shr     bx, 3
        and     al, 7
        mov     ah, 80h
        push    cx
        mov     cl, al
        shr     ah, cl
        pop     cx
.r:     mov     si, dx
        shl     si, 1
        mov     di, [rowtab+si]
        or      [es:di+bx], ah
        inc     dx
        loop    .r
        pop     es
        popa
        ret

; AL = char, BX = column, DX = y (multiple of 4), AH = 00 normal / FF inverse
putc:   pusha
        push    es
        push    VSEG
        pop     es
        cmp     al, 32
        jb      .bad
        cmp     al, 127
        jbe     .ok
.bad:   mov     al, '?'
.ok:    mov     cl, ah
        xor     ah, ah
        sub     al, 32
        shl     ax, 4
        add     ax, font
        mov     si, ax
        mov     di, dx
        shl     di, 1
        mov     di, [rowtab+di]
        add     di, bx
        mov     ah, cl
%assign r 0
%rep 16
        lodsb
        xor     al, ah
        mov     [es:di + (r & 3) * 2000h + (r >> 2) * 80], al
%assign r r + 1
%endrep
        pop     es
        popa
        ret

; SI = ASCIIZ, BX = column, DX = y, AH = mask.  Returns SI past the NUL.
puts:   push    bx
.l:     lodsb
        or      al, al
        jz      .x
        cmp     bx, 80
        jae     .l
        call    putc
        inc     bx
        jmp     .l
.x:     pop     bx
        ret

strlen: push    si                      ; SI -> CX = length
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .x
        inc     cx
        jmp     .l
.x:     pop     si
        ret

; text builders: append at DI
sb_str: lodsb
        or      al, al
        jz      .x
        stosb
        jmp     sb_str
.x:     ret

sb_u16: xor     cx, cx                  ; AX unsigned
sb_u32: push    bx                      ; CX:AX unsigned
        push    dx
        push    si
        mov     si, sp
        mov     bx, 10
.d:     push    ax
        mov     ax, cx
        xor     dx, dx
        div     bx
        mov     cx, ax
        pop     ax
        div     bx
        push    dx
        mov     dx, cx
        or      dx, ax
        jnz     .d
.p:     cmp     sp, si
        je      .x
        pop     ax
        add     al, '0'
        stosb
        jmp     .p
.x:     pop     si
        pop     dx
        pop     bx
        ret

sb_2d:  aam                             ; AL (0..99) as two digits
        xchg    al, ah
        add     ax, '00'
        stosw
        ret

; AX = DOS date -> "4-Oct-26"
sb_date:
        push    ax
        and     ax, 1Fh
        call    sb_u16
        mov     al, '-'
        stosb
        pop     ax
        push    ax
        shr     ax, 5
        and     ax, 0Fh
        dec     ax
        cmp     ax, 11
        jbe     .m
        xor     ax, ax
.m:     push    si
        imul    si, ax, 3
        add     si, months
        movsw
        movsb
        pop     si
        mov     al, '-'
        stosb
        pop     ax
        shr     ax, 9
        add     ax, 80
        cmp     ax, 100
        jb      .y
        sub     ax, 100
.y:     jmp     sb_2d

bios_print:
        lodsb
        or      al, al
        jz      .x
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     bios_print
.x:     ret

tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

wait_ticks:
        call    tick
        mov     bx, ax
.w:     call    tick
        sub     ax, bx
        cmp     ax, cx
        jb      .w
        ret

; =====================================================================
; data
; =====================================================================
s_brand     db 'Grid-OS 0.2.2',0
s_prompt1   db 'Select a file and confirm',0
s_prompt2   db 'Or press CODE-? for help',0
s_anykey    db 'Press any key',0
s_notyet    db ' - running programs arrives in Grid-OS 0.2',0
s_sp2       db '  ',0
s_empty     db '(no files)',0
s_lbl_dev   db 'Device',0
s_lbl_sub   db 'Subject',0
s_lbl_tit   db 'Title',0
s_lbl_kind  db 'Kind',0
s_lbl_size  db 'Size',0
s_dev_a     db 'Floppy A:',0
s_root      db 'Root',0
s_bytes     db ' bytes',0
s_dated     db '   dated ',0
s_hlptitle  db 'Grid-OS 0.2.2 Help',0
help_text   db 'Up / Down, PgUp / PgDn   choose a file',0
            db 'Home / End               first / last',0
            db 'Mouse                    point and click',0
            db 'Return or click again    run it / open it',0
            db 'CODE-?  or  F1           this help',0
            db 'CODE-D                   boot GRiD MS-DOS',0
            db 'CODE-A                   Claude',0
            db 'CODE-C                   command prompt',0
            db 'F5                       after a disk swap',0
            db 'CODE-R                   restart',0
            db '5 minutes idle           screen saver',0
            db 'CODE is the Alt key.  Any key closes.',0
            db 0FFh
s_nohires   db 'Grid-OS needs the GRiD 640x400 panel (BIOS mode 40h).',13,10
            db 'Press a key to restart.',13,10,0
s_bootrom   db 'Grid-OS: booting from the EPROM...',13,10,0
s_cpu       db '80286',0
s_fpu       db '+80287',0
s_gap       db '   ',0
s_k         db 'K',0
s_plus      db ' + ',0
s_ems       db 'K EMS',0
s_ext       db 'K ext',0
s_plasma    db 'Plasma 640x400',0
s_lcd       db 'LCD 640x400',0
s_panel     db 'Panel',0
s_mouse1    db 'Mouse COM1',0
s_mouse2    db 'Mouse COM2',0
s_nomouse   db 'No mouse',0
s_bios      db 'BIOS ',0
s_am        db ' am',0
s_pm        db ' pm',0
months      db 'JanFebMarAprMayJunJulAugSepOctNovDec'
k_subject   db 'Subject',0
k_file      db 'File',0
k_run       db 'Run',0
k_system    db 'System',0
k_text      db 'Text',0
k_data      db 'Data',0
k_batch     db 'Batch',0
k_settings  db 'Settings',0
k_font      db 'Font',0
k_profile   db 'Profile',0
k_source    db 'Source',0
kinds       db 'COM'
            dw k_run
            db 'EXE'
            dw k_run
            db 'RUN'
            dw k_run
            db 'SYS'
            dw k_system
            db 'TXT'
            dw k_text
            db 'DOC'
            dw k_text
            db 'BIN'
            dw k_data
            db 'DAT'
            dw k_data
            db 'BAT'
            dw k_batch
            db 'CFG'
            dw k_settings
            db 'INI'
            dw k_settings
            db 'EMS'
            dw k_settings
            db 'TYP'
            dw k_font
            db 'PRO'
            dw k_profile
            db 'ASM'
            dw k_source
            db 'INC'
            dw k_source
            db 'C  '
            dw k_source
            db 'H  '
            dw k_source
            db 0


lasttick    dw 0
mx          dw 320
my          dw 200
mb          db 0
oldmb       db 0
mflag       db 0
midx        db 3
mpkt        db 0, 0, 0
mbase       dw 0
mirq        db 0
vecslot     dw 0
oldvec      dw 0, 0
curvis      db 0
helpopen    db 0
msgshown    db 0
sel         dw 0
top         dw 0
nent        dw 0


section .bss
rowmask     resb 1
rtc_h       resb 1
rtc_m       resb 1
rtc_y       resb 1
rtc_mo      resb 1
rtc_d       resb 1
panel       resb 1
convkb      resw 1
emskb       resw 1
extkb       resw 1
equip       resw 1
cur_x       resw 1
cur_y       resw 1
cur_xb      resw 1
cur_save    resb 26
new_save    resb 26
ubuf        resb 4 * 26
cnew_x      resw 1
cnew_y      resw 1
cnew_xb     resw 1
ux0         resw 1
uy0         resw 1
uw          resw 1
uh          resw 1
cflags      resb 1
biosdate    resb 8
kindbuf     resb 4
tmp         resb 96
msgbuf      resb 128
infobuf     resb 128
rowtab      resw 400
entlist     resw MAXENT
%ifdef NOTC
savebuf     resb HW_W * HW_H
%elif HW_W * HW_H > TC_SECS * 512
%error the help window does not fit in the disk cache
%endif
section .text
