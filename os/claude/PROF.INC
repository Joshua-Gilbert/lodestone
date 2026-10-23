; =====================================================================
;  PROF.INC - where CLAUDE's time goes, on the 1520 (nasm -dPROFILE:
;  CLAUDEP.COM).  PROF n (GLP.INC) moves the time from then on to bucket
;  n, timed on the PIT (channel 0 in mode 2 while CLAUDE runs: 838 ns a
;  count, with the BIOS tick above it).  At the end CLAUDE writes
;  CLPROF.TXT in the current directory: each bucket's total, how many
;  times it was entered, and the mean.  PROF itself costs ~30 us a switch,
;  counted in the bucket after it.
; =====================================================================
PB_N    equ 15
PS_N    equ 8                           ; how deep PROF n ... PROF 0 nest

prof_names:
        dw pn0, pn1, pn2, pn3, pn4, pn5, pn6, pn7, pn8, pn9, pn10, pn11, pn12, pn13, pn14
pn0     db 'other (the main loop itself)$'
pn1     db 'GPIB write (INT 60h 02h)$'
pn2     db 'GPIB read (INT 60h 03h)$'
pn3     db 'GPIB polls (05h, 0Bh)$'
pn4     db 'frame check (Fletcher)$'
pn5     db 'frame copies (REP MOVSW)$'
pn6     db 'DOS open / create$'
pn7     db 'DOS seek$'
pn8     db 'DOS read / write$'
pn9     db 'DOS close$'
pn10    db 'HLT, waiting$'
pn11    db 'link logic (frames, answers)$'
pn12    db 'keys$'
pn13    db 'requests (but their DOS calls)$'
pn14    db 'ticks, the screen$'
s_prof  db 'CLPROF.TXT', 0
s_ph    db 'CLAUDE profile (PIT counts of 838 ns)', 13, 10
        db 'bucket                            total ms   times   mean us', 13, 10, '$'

prof_start:                             ; PIT channel 0 to mode 2, the clock on
        push    es
        push    ds
        pop     es
        mov     di, prof_acc
        mov     cx, (PB_N + 1) * 3
        xor     ax, ax
        rep     stosw
        pop     es
        cli
        mov     al, 34h
        out     43h, al
        xor     al, al
        out     40h, al
        jmp     short $+2
        out     40h, al
        sti
        call    prof_now
        mov     [prof_t0], ax
        mov     [prof_t0+2], dx
        mov     byte [prof_cur], 0
        mov     byte [prof_sp], 0
        ret

prof_rebase:                            ; the clock was set: time from here on
        push    ax
        push    dx
        call    prof_now
        mov     [prof_t0], ax
        mov     [prof_t0+2], dx
        pop     dx
        pop     ax
        ret

prof_now:                               ; DX:AX = the BIOS tick, the PIT count
        push    bx                      ;  (mode 2: down from 65536 a tick)
        push    cx
        push    ds
        mov     ax, 40h
        mov     ds, ax
.r:     mov     bx, [6Ch]
        pushf
        cli
        xor     al, al
        out     43h, al
        jmp     short $+2
        in      al, 40h
        mov     cl, al
        jmp     short $+2
        in      al, 40h
        mov     ch, al
        mov     al, 0Ah                 ; the PIC's IRR: a tick not yet counted
        out     20h, al                 ;  (the count wrapped, IRQ 0 waits:
        jmp     short $+2               ;  interrupts off, or here)
        in      al, 20h
        popf
        cmp     bx, [6Ch]
        jne     .r
        test    al, 1
        jz      .t
        cmp     ch, 80h                 ; (just reloaded: high)
        jb      .t
        inc     bx
.t:     mov     ax, cx
        neg     ax
        mov     dx, bx
        pop     ds
        pop     cx
        pop     bx
        ret

prof_sw:                                ; AL = the bucket from now on, 0: back
        push    bx
        push    cx
        push    dx
        push    si
        mov     cl, al
        call    prof_now
        mov     si, ax
        mov     bx, dx
        sub     ax, [prof_t0]
        sbb     dx, [prof_t0+2]
        jns     .f
        xor     ax, ax                  ; (backwards: a tick lost; none of it)
        xor     dx, dx
.f:     mov     [prof_t0], si
        mov     [prof_t0+2], bx
        mov     bl, [prof_cur]
        xor     bh, bh
        shl     bx, 2
        add     [prof_acc+bx], ax
        adc     [prof_acc+bx+2], dx
        or      cl, cl                  ; 0: the bucket before
        jnz     .push
        mov     bl, [prof_sp]
        or      bl, bl
        jz      .set                    ; (none: 0)
        dec     bl
        mov     [prof_sp], bl
        xor     bh, bh
        mov     cl, [prof_stk+bx]
        jmp     short .set
.push:  mov     bl, [prof_sp]
        cmp     bl, PS_N
        jae     .cnt                    ; (too deep: no way back past here)
        xor     bh, bh
        mov     al, [prof_cur]
        mov     [prof_stk+bx], al
        inc     byte [prof_sp]
.cnt:   mov     bl, cl
        xor     bh, bh
        shl     bx, 1
        inc     word [prof_cnt+bx]
.set:   mov     [prof_cur], cl
        pop     si
        pop     dx
        pop     cx
        pop     bx
        ret

; OP 31h (CLAUDEP only; gridlink.bench --prof): AL = 0 starts the counts
; again from now, 1 writes CLPROF.TXT now and keeps it (the end doesn't
; write it again), so the file covers just what came between
prof_window:
        or      al, al
        jnz     .w
        push    es
        push    ds
        pop     es
        mov     di, prof_acc
        mov     cx, (PB_N + 1) * 3
        xor     ax, ax
        rep     stosw
        pop     es
        mov     byte [prof_kept], 0
        jmp     prof_rebase
.w:     PROF    15                      ; (the stretch up to here counted)
        PROF    0
        mov     byte [prof_kept], 1
        jmp     prof_write

; the PIT back to mode 3, and CLPROF.TXT written
prof_end:
        PROF    15                      ; (the last stretch counted: in no bucket)
        cli
        mov     al, 36h
        out     43h, al
        xor     al, al
        out     40h, al
        jmp     short $+2
        out     40h, al
        sti
        cmp     byte [prof_kept], 0     ; (a window's file is kept)
        jne     prof_write.x
prof_write:
        push    ds
        pop     es
        mov     di, prof_txt
        mov     si, s_ph
        call    prof_cpy
        xor     bx, bx
.b:     push    bx
        shl     bx, 1
        mov     si, [prof_names+bx]
        mov     cx, di
        call    prof_cpy
        sub     cx, di
        add     cx, 34                  ; pad the name to 34
        jle     .np
        mov     al, ' '
        rep     stosb
.np:    pop     bx
        push    bx
        mov     si, bx
        shl     si, 2
        mov     ax, [prof_acc+si]       ; total ms = counts / 1193
        mov     dx, [prof_acc+si+2]
        mov     cx, 1193
        call    prof_div32
        mov     cx, 8
        call    prof_dec32
        shl     bx, 1
        mov     ax, [prof_cnt+bx]
        xor     dx, dx
        mov     cx, 8
        call    prof_dec32
        mov     cx, [prof_cnt+bx]       ; mean us = counts / times * 838 / 1000
        mov     ax, [prof_acc+si]
        mov     dx, [prof_acc+si+2]
        jcxz    .z
        call    prof_div32
        or      dx, dx
        jnz     .big
        mov     cx, 838
        mul     cx
        mov     cx, 1000
        call    prof_div32
        jmp     short .pr
.big:   mov     ax, 0FFFFh
        xor     dx, dx
        jmp     short .pr
.z:     xor     ax, ax
        xor     dx, dx
.pr:    mov     cx, 10
        call    prof_dec32
        mov     ax, 0A0Dh
        stosw
        pop     bx
        inc     bx
        cmp     bx, PB_N
        jb      .b
        mov     dx, s_prof
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
        mov     bx, ax
        mov     cx, di
        mov     dx, prof_txt
        sub     cx, dx
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret

prof_cpy:                               ; '$'-ended DS:SI -> ES:DI
        lodsb
        cmp     al, '$'
        je      .x
        stosb
        jmp     prof_cpy
.x:     ret

prof_div32:                             ; DX:AX / CX -> DX:AX (CX nonzero)
        push    bx
        mov     bx, ax
        mov     ax, dx
        xor     dx, dx
        div     cx
        xchg    ax, bx
        div     cx
        mov     dx, bx
        pop     bx
        ret

prof_dec32:                             ; DX:AX in CX columns, right-aligned
        push    bx
        push    si
        mov     si, di
        add     di, cx
        push    di
.d:     push    cx
        mov     cx, 10
        call    prof_div32r             ; DX:AX / 10, BX = the remainder
        pop     cx
        add     bl, '0'
        dec     di
        mov     [di], bl
        dec     cx
        mov     bx, ax
        or      bx, dx
        jnz     .d
        jcxz    .x
.sp:    dec     di
        mov     byte [di], ' '
        loop    .sp
.x:     pop     di
        pop     si
        pop     bx
        ret

prof_div32r:                            ; DX:AX / CX -> DX:AX, BX = remainder
        mov     bx, ax
        mov     ax, dx
        xor     dx, dx
        div     cx
        xchg    ax, bx
        div     cx
        xchg    dx, bx
        ret
