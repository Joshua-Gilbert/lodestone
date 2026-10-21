; =====================================================================
;  INT 33h: the Microsoft mouse API for DOS programs, on the UI's own
;  serial-mouse driver (mouse_isr feeds it every packet).
;
;  The mouse stays off while a DOS program runs, until the program asks
;  for it (function 0 or 21h): a program that drives COM1/COM2 itself is
;  left alone.  The pointer is drawn the Microsoft way, (screen AND screen
;  mask) XOR cursor mask, in text modes 0-3 and 7 (one cell) and in the
;  graphics modes 4/5 and 6 (CGA) and 40h (GRiD 640 x 400).  A byte the
;  program has written over since the pointer was drawn is left as it is
;  when the pointer goes.  The event handler (0Ch, 14h) is called after
;  the interrupt is acknowledged, with interrupts on, and only while the
;  program that set it is still in memory.
;
;  Functions: 00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0F 10 13 14 15 16 17
;  1A 1B 1D 1E 1F 20 21 24 26; others return with the registers as they
;  were.  Coordinates are virtual, as Microsoft's: x 0-639 in every mode,
;  y 0-199 (0-399 in mode 40h; rows x 8 in text).  8 mickeys per 8 pixels
;  across, 16 down, as Microsoft's defaults.
; =====================================================================

section uibss
m33_st:                         ; (15h-17h save and restore from here)
m33_btn     resw 1              ; (then x, y: 03h answers the three)
m33_x       resw 1
m33_y       resw 1
m33_xmin    resw 1
m33_xmax    resw 1
m33_ymin    resw 1
m33_ymax    resw 1
m33_rx      resw 1              ; mickeys per 8 pixels
m33_ry      resw 1
m33_remx    resw 1              ; what didn't make a whole pixel (x 8)
m33_remy    resw 1
m33_mx      resw 1              ; mickeys since 0Bh last read them
m33_my      resw 1
m33_cnt     resw 1              ; 0: the pointer shows; -n: hidden n times
m33_np      resw 2              ; presses of each button since asked,
m33_px      resw 2              ;  and where the last one was
m33_py      resw 2
m33_nr      resw 2              ; releases
m33_rlx     resw 2
m33_rly     resw 2
m33_hx      resw 1              ; hot spot
m33_hy      resw 1
m33_gm      resw 32             ; graphics: screen mask, then cursor mask
m33_ts      resw 1              ; text: screen mask, cursor mask
m33_tc      resw 1
m33_hmask   resw 1              ; event handler: condition mask,
m33_hoff    resw 1              ;  address,
m33_hseg    resw 1
m33_hpsp    resw 1              ;  and the program that set it
m33_sens    resw 3
m33_st_end:
M33_ST      equ m33_st_end - m33_st
m33_dx      resw 1              ; this packet's motion (from mouse_isr)
m33_dy      resw 1
m33_ev      resb 1              ; conditions for the event handler
m33_busy    resb 1              ; the event handler is running
m33_dn      resb 1              ; the pointer is drawn:
m33_dmode   resb 1              ;  in this mode,
m33_dseg    resw 1              ;  this segment,
m33_dpos    resw 1              ;  text: the cell; graphics: left byte
m33_drow    resw 1              ;  graphics: top row
m33_save    resb 48             ; what was there (graphics: 16 rows x 3)
m33_drawn   resb 48             ; what we put there
m33_tmp     resb 6              ; one row's AND and XOR bytes
m33_lb      resw 1              ; the pointer's left byte (column)
m33_rows    resw 1
m33_sh      resb 1              ; its shift within that byte
m33_bk      resb 1              ; 1: 2 banks, 2: 4 banks
m33_und     resb 1              ; 1: taking it away

section ui
M3_DI        equ 0               ; the caller's registers on our stack
M3_SI        equ 2
M3_BX        equ 8
M3_DX        equ 10
M3_CX        equ 12
M3_AX        equ 14
M3_ES        equ 16

int33_ui:
        push    ds
        push    es
        pusha
        mov     bp, sp
        push    cs
        pop     ds
        cli
        cld                             ; (the caller's DF may be set)
        cmp     word [mfound], 0
        jne     .go
        or      ax, ax                  ; no mouse: only the resets answer
        je      .go
        cmp     ax, 21h
        jne     .x
.go:    cmp     ax, M33_N
        jae     .x
        mov     bx, ax
        add     bx, bx
        call    [m33_tab + bx]
.x:     popa
        pop     es
        pop     ds
        iret

m33_tab:
        dw f33_00, f33_01, f33_02, f33_03, f33_04, f33_05, f33_06, f33_07
        dw f33_08, f33_09, f33_0A, f33_0B, f33_0C, f33_nop, f33_nop, f33_0F
        dw f33_02, f33_nop, f33_nop, f33_nop, f33_14, f33_15, f33_16, f33_17
        dw f33_nop, f33_nop, f33_1A, f33_1B, f33_nop, f33_nop, f33_1E, f33_1F
        dw f33_nop, f33_00, f33_nop, f33_nop, f33_24, f33_nop, f33_26
M33_N       equ ($ - m33_tab) / 2

; our INT 33h in the vector table (at start-up, and when the block moves)
m33_hook:
        push    es
        xor     ax, ax
        mov     es, ax
        cli
        mov     word [es:33h * 4], int33_ui
        mov     [es:33h * 4 + 2], cs
        sti
        pop     es
        ret

; a DOS program has ended: the pointer goes, the event handler is forgotten
m33_end:
        cli
        call    m33_undraw
        mov     word [m33_cnt], -1
        call    m33_forget
        sti
        ret

; the event handler forgotten, none pending or running.  AX = 0
m33_forget:
        xor     ax, ax
        mov     [m33_hmask], ax
        mov     [m33_hseg], ax
        mov     [m33_hpsp], ax
        mov     [m33_ev], al
        mov     [m33_busy], al
        ret

; from the kernel, far, when the program at BX ends (not a TSR): if the
; event handler is that program's, it goes (a program may end inside its
; handler, so m33_busy is cleared too).  A shell's next program can be
; loaded at the same segment, so the owner check alone can't tell.
m33_gone:
        push    ds
        push    cs
        pop     ds
        pushf
        cli
        cmp     bx, [m33_hpsp]
        jne     .x
        call    m33_forget
.x:     popf
        pop     ds
        retf

; 00h reset / 21h software reset: AX = FFFFh and BX = 2 buttons, or 0
f33_00: xor     ax, ax
        cmp     [mfound], ax
        jne     .yes
        mov     [bp + M3_AX], ax
        mov     [bp + M3_BX], ax
        ret
.yes:   cmp     [mbase], ax
        jne     .on
        call    mouse_on                ; (it turns interrupts on)
        cli
.on:    call    m33_soft
        mov     word [bp + M3_AX], 0FFFFh
        mov     word [bp + M3_BX], 2
f33_nop:
        ret

; the driver's state as after a reset, for the current screen mode
m33_soft:
        call    m33_undraw
        push    es
        push    cs
        pop     es
        mov     di, m33_st
        mov     cx, M33_ST / 2
        xor     ax, ax
        rep     stosw
        mov     si, m33_arrow
        mov     di, m33_gm
        mov     cx, 32 + 2
        rep     movsw                   ; (the arrow, then 77FFh, 7700h)
        pop     es
        call    m33_forget              ; (the handler went with m33_st too)
        mov     word [m33_cnt], -1
        mov     word [m33_xmax], 639
        call    m33_maxy
        mov     [m33_ymax], ax
        inc     ax
        shr     ax, 1
        mov     [m33_y], ax
        mov     word [m33_x], 320
        mov     word [m33_rx], 8
        mov     word [m33_ry], 16
        mov     ax, 50
        mov     [m33_sens], ax
        mov     [m33_sens + 2], ax
        mov     [m33_sens + 4], ax
        ret

; AX = the largest y in the current mode
m33_maxy:
        push    es
        xor     ax, ax
        mov     es, ax
        mov     al, [es:449h]
        cmp     al, 40h
        je      .g4
        cmp     al, 7
        je      .t
        cmp     al, 3
        ja      .cga
.t:     mov     al, [es:484h]           ; rows - 1 (0 if the BIOS doesn't say)
        cmp     al, 24
        jb      .cga
        cmp     al, 49
        ja      .cga
        inc     ax
        shl     ax, 3
        dec     ax
        pop     es
        ret
.g4:    mov     ax, 399
        pop     es
        ret
.cga:   mov     ax, 199
        pop     es
        ret

f33_01: cmp     word [m33_cnt], 0
        je      .x
        inc     word [m33_cnt]
        jnz     .x
        call    m33_draw
.x:     ret

f33_02: cmp     word [m33_cnt], 0       ; (and 10h: conditional off)
        jne     .d
        call    m33_undraw
.d:     cmp     word [m33_cnt], -32000
        jl      .x
        dec     word [m33_cnt]
.x:     ret

f33_03: mov     si, m33_btn         ; buttons, x, y
; three words at SI -> the caller's BX, CX, DX
m33_out3:
        lodsw
        mov     [bp + M3_BX], ax
        lodsw
        mov     [bp + M3_CX], ax
        lodsw
        mov     [bp + M3_DX], ax
        ret

f33_04: mov     ax, [bp + M3_CX]
        mov     [m33_x], ax
        mov     ax, [bp + M3_DX]
        mov     [m33_y], ax
        call    m33_clamp
        jmp     m33_redraw

; 05h presses / 06h releases of button BX
f33_05: mov     si, m33_np
        jmp     short f33_pr
f33_06: mov     si, m33_nr
f33_pr: mov     ax, [m33_btn]
        mov     [bp + M3_AX], ax
        mov     bx, [bp + M3_BX]
        xor     ax, ax
        xor     cx, cx
        xor     dx, dx
        cmp     bx, 1
        ja      .out
        add     bx, bx
        add     si, bx
        xchg    ax, [si]                ; the count, now 0
        mov     cx, [si + 4]
        mov     dx, [si + 8]
.out:   mov     [bp + M3_BX], ax
        mov     [bp + M3_CX], cx
        mov     [bp + M3_DX], dx
        ret

f33_07: mov     si, m33_xmin
        jmp     short f33_rng
f33_08: mov     si, m33_ymin
f33_rng:
        mov     ax, [bp + M3_CX]
        mov     dx, [bp + M3_DX]
        cmp     ax, dx
        jle     .o
        xchg    ax, dx
.o:     mov     [si], ax
        mov     [si + 2], dx
        call    m33_clamp
        jmp     m33_redraw

; 09h graphics pointer: BX, CX = hot spot, ES:DX = screen mask, cursor mask
f33_09: call    m33_undraw
        mov     ax, [bp + M3_BX]
        mov     [m33_hx], ax
        mov     ax, [bp + M3_CX]
        mov     [m33_hy], ax
        push    ds
        push    es
        push    cs
        pop     es
        mov     si, [bp + M3_DX]
        mov     ds, [bp + M3_ES]
        mov     di, m33_gm
        mov     cx, 32
        rep     movsw
        pop     es
        pop     ds
        jmp     m33_redraw

; 0Ah text pointer: BX = 0, CX = screen mask, DX = cursor mask (BX = 1, a
; hardware cursor, is taken as the software one with the default masks)
f33_0A: call    m33_undraw
        mov     ax, 77FFh
        mov     dx, 7700h
        cmp     word [bp + M3_BX], 0
        jne     .s
        mov     ax, [bp + M3_CX]
        mov     dx, [bp + M3_DX]
.s:     mov     [m33_ts], ax
        mov     [m33_tc], dx
        jmp     m33_redraw

f33_0B: xor     ax, ax
        xchg    ax, [m33_mx]
        mov     [bp + M3_CX], ax
        xor     ax, ax
        xchg    ax, [m33_my]
        mov     [bp + M3_DX], ax
        ret

; 0Ch event handler: CX = conditions, ES:DX = the routine
f33_0C: call    m33_psp                 ; (first: INT 21h turns interrupts on)
        mov     ax, [bp + M3_DX]
        mov     [m33_hoff], ax
        mov     ax, [bp + M3_ES]
        mov     [m33_hseg], ax
        mov     [m33_hpsp], bx
        mov     ax, [bp + M3_CX]
        mov     [m33_hmask], ax
        mov     byte [m33_ev], 0
        ret

; BX = the program calling (interrupts off again)
m33_psp:
        mov     ah, 62h
        int     21h
        cli
        ret

; 14h swap event handlers: the old one back in CX, ES:DX
f33_14: call    m33_psp
        mov     [m33_hpsp], bx
        mov     byte [m33_ev], 0
        mov     ax, [bp + M3_CX]
        xchg    ax, [m33_hmask]
        mov     [bp + M3_CX], ax
        mov     ax, [bp + M3_DX]
        xchg    ax, [m33_hoff]
        mov     [bp + M3_DX], ax
        mov     ax, [bp + M3_ES]
        xchg    ax, [m33_hseg]
        mov     [bp + M3_ES], ax
        ret

f33_0F: mov     ax, [bp + M3_CX]
        or      ax, ax
        jz      .y
        mov     [m33_rx], ax
.y:     mov     ax, [bp + M3_DX]
        or      ax, ax
        jz      .x
        mov     [m33_ry], ax
.x:     ret

f33_15: mov     word [bp + M3_BX], M33_ST
        ret

; 16h save the state to ES:DX / 17h restore it from there
f33_16: push    es
        mov     di, [bp + M3_DX]
        mov     es, [bp + M3_ES]
        mov     si, m33_st
        mov     cx, M33_ST / 2
        rep     movsw
        pop     es
        ret

f33_17: call    m33_undraw
        push    ds
        push    es
        push    cs
        pop     es
        mov     si, [bp + M3_DX]
        mov     ds, [bp + M3_ES]
        mov     di, m33_st
        mov     cx, M33_ST / 2
        rep     movsw
        pop     es
        pop     ds
        mov     byte [m33_ev], 0
        jmp     m33_redraw

f33_1A: mov     ax, [bp + M3_BX]
        mov     [m33_sens], ax
        mov     ax, [bp + M3_CX]
        mov     [m33_sens + 2], ax
        mov     ax, [bp + M3_DX]
        mov     [m33_sens + 4], ax
        ret

f33_1B: mov     si, m33_sens
        jmp     m33_out3

f33_1E: mov     word [bp + M3_BX], 0     ; display page 0
        ret

f33_1F: mov     word [bp + M3_AX], 0FFFFh ; (can't be disabled)
        ret

f33_24: mov     word [bp + M3_BX], 0626h ; version 6.26, a serial mouse
        mov     ah, 2
        mov     al, [mirq]
        mov     [bp + M3_CX], ax
        ret

f33_26: mov     word [bp + M3_BX], 0
        mov     ax, [m33_xmax]
        mov     [bp + M3_CX], ax
        mov     ax, [m33_ymax]
        mov     [bp + M3_DX], ax
        ret

; the position within the ranges
m33_clamp:
        mov     ax, [m33_x]
        mov     cx, [m33_xmin]
        mov     dx, [m33_xmax]
        call    .one
        mov     [m33_x], ax
        mov     ax, [m33_y]
        mov     cx, [m33_ymin]
        mov     dx, [m33_ymax]
        call    .one
        mov     [m33_y], ax
        ret
.one:   cmp     ax, cx
        jge     .lo
        mov     ax, cx
.lo:    cmp     ax, dx
        jle     .hi
        mov     ax, dx
.hi:    ret

; ---------------------------------------------------------------------
; from mouse_isr, interrupts off: [m33_dx], [m33_dy] and [mb] are a new
; packet.  Moves, counts the buttons, redraws the pointer.
m33_pkt:
        pusha
        push    ds
        push    es
        push    cs
        pop     ds
        push    word [m33_x]
        push    word [m33_y]
        mov     ax, [m33_dx]
        add     [m33_mx], ax
        mov     bx, [m33_rx]
        mov     si, m33_remx
        mov     di, m33_x
        mov     cx, [m33_xmin]
        mov     dx, [m33_xmax]
        call    m33_step
        mov     ax, [m33_dy]
        add     [m33_my], ax
        mov     bx, [m33_ry]
        mov     si, m33_remy
        mov     di, m33_y
        mov     cx, [m33_ymin]
        mov     dx, [m33_ymax]
        call    m33_step
        mov     al, [mb]
        mov     ah, [m33_btn]
        mov     [m33_btn], al
        xor     ah, al                  ; AH = the buttons that changed
        xor     bx, bx                  ; button 0: conditions 2 / 4
        mov     dl, 2
.b:     test    ah, 1
        jz      .nb
        mov     si, m33_np
        test    al, 1
        jnz     .p
        mov     si, m33_nr
        shl     dl, 1
.p:     or      [m33_ev], dl
        inc     word [si + bx]
        mov     cx, [m33_x]
        mov     [si + bx + 4], cx
        mov     cx, [m33_y]
        mov     [si + bx + 8], cx
.nb:    shr     ax, 1                   ; next button (AL and AH both)
        add     bx, 2
        mov     dl, 8                   ; button 1: conditions 8 / 10h
        cmp     bx, 4
        jb      .b
        pop     dx
        pop     cx
        cmp     cx, [m33_x]
        jne     .mv
        cmp     dx, [m33_y]
        je      .x
.mv:    or      byte [m33_ev], 1
        cmp     word [m33_cnt], 0
        jne     .x
        call    m33_undraw
        call    m33_draw
.x:     pop     es
        pop     ds
        popa
        ret

; AX mickeys, BX mickeys per 8 pixels, [SI] the remainder, [DI] the
; position, CX..DX its range
m33_step:
        push    dx
        shl     ax, 3
        add     ax, [si]
        cwd
        idiv    bx
        mov     [si], dx
        add     ax, [di]
        pop     dx
        call    m33_clamp.one
        mov     [di], ax
        ret

; the end of mouse_isr, after the EOI: the program's event handler, if
; something it asked about happened
m33_call:
        cmp     byte [cs:m33_ev], 0
        je      .r
        cmp     byte [cs:m33_busy], 0
        jne     .r
        pusha
        push    ds
        push    es
        push    cs
        pop     ds
        mov     al, [m33_ev]
        mov     byte [m33_ev], 0
        and     al, [m33_hmask]
        jz      .x
        cmp     word [m33_hseg], 0
        je      .x
        mov     bx, [m33_hpsp]          ; is its program still there?
        or      bx, bx
        jz      .gone
        dec     bx
        mov     es, bx
        inc     bx
        cmp     [es:1], bx
        jne     .gone
        mov     byte [m33_busy], 1
        xor     ah, ah
        mov     bx, [m33_btn]
        mov     cx, [m33_x]
        mov     dx, [m33_y]
        mov     si, [m33_mx]
        mov     di, [m33_my]
        sti
        call    far [cs:m33_hoff]
        cli
        mov     byte [cs:m33_busy], 0
        jmp     short .x
.gone:  mov     word [m33_hmask], 0
.x:     pop     es
        pop     ds
        popa
.r:     ret

; ---------------------------------------------------------------------
;  the pointer on the program's screen (interrupts off, DS = CS)
; ---------------------------------------------------------------------
m33_none:
        ret
m33_redraw:
        call    m33_undraw
        cmp     word [m33_cnt], 0
        jne     m33_none
; draw it at m33_x, m33_y in the current mode
m33_draw:
        pusha
        push    es
        xor     ax, ax
        mov     es, ax
        mov     al, [es:449h]
        mov     [m33_dmode], al
        call    m33_gparm
        jnc     .gfx
        cmp     al, 7
        je      .mono
        cmp     al, 3
        ja      .x                      ; (a mode we can't draw in)
        mov     cx, 0B800h
        jmp     short .text
.mono:  mov     cx, 0B000h
.text:  mov     [m33_dseg], cx
        mov     bx, [es:44Ah]           ; columns
        mov     ax, [m33_y]
        shr     ax, 3                   ; row
        mul     bx
        mov     di, ax
        mov     ax, [m33_x]
        shr     ax, 3                   ; 80 columns: x / 8
        cmp     bl, 40
        ja      .c
        shr     ax, 1                   ; 40: x / 16
.c:     cmp     ax, bx
        jae     .x
        add     di, ax
        add     di, di
        add     di, [es:44Eh]           ; the page
        mov     [m33_dpos], di
        mov     es, cx
        mov     ax, [es:di]
        mov     [m33_save], ax
        and     ax, [m33_ts]
        xor     ax, [m33_tc]
        mov     [es:di], ax
        mov     [m33_drawn], ax
        mov     byte [m33_dn], 1
.x:     pop     es
        popa
        ret
.gfx:   mov     ax, [m33_x]             ; the left edge as a bit number: x
        sub     ax, [m33_hx]            ;  and the hot spot are in virtual
        or      cl, cl                  ;  pixels, one bit each (in modes
        jz      .b                      ;  4/5 two make a pixel: the mask
        and     al, 0FEh                ;  starts on a whole one)
.b:     mov     [m33_dpos], ax
        mov     ax, [m33_y]
        sub     ax, [m33_hy]
        mov     [m33_drow], ax
        mov     word [m33_dseg], 0B800h
        mov     byte [m33_dn], 1
        xor     al, al
        call    m33_gfx
        jmp     short .x

; take the pointer away (if the mode is still the one it was drawn in)
m33_undraw:
        cmp     byte [m33_dn], 0
        je      m33_none
        pusha
        push    es
        mov     byte [m33_dn], 0
        xor     ax, ax
        mov     es, ax
        mov     al, [es:449h]
        cmp     al, [m33_dmode]
        jne     .x                      ; (the program changed modes)
        call    m33_gparm
        jnc     .gfx
        mov     es, [m33_dseg]
        mov     di, [m33_dpos]
        mov     ax, [es:di]
        cmp     ax, [m33_drawn]
        jne     .x                      ; (written over since)
        mov     ax, [m33_save]
        mov     [es:di], ax
.x:     pop     es
        popa
        ret
.gfx:   mov     al, 1
        call    m33_gfx
        jmp     short .x

; AL = mode -> CF clear for a graphics mode we draw in: CL = 1 if 2 bits a
; pixel, CH = 1 for 2 banks, 2 for 4, BP = rows
m33_gparm:
        mov     bp, 200
        mov     cx, 0101h
        cmp     al, 4
        je      .y
        cmp     al, 5
        je      .y
        dec     cx                      ; CL = 0
        cmp     al, 6
        je      .y
        cmp     al, 40h
        stc
        jne     .n
        mov     ch, 2
        mov     bp, 400
.y:     clc
.n:     ret

; draw (AL = 0) or take away (AL = 1) the graphics pointer: m33_dpos =
; bit number of its left edge in a row, m33_drow = its top row; CL, CH, BP
; from m33_gparm
m33_gfx:
        mov     [m33_und], al
        mov     [m33_bk], ch
        mov     [m33_rows], bp
        mov     es, [m33_dseg]
        mov     ax, [m33_dpos]
        mov     bl, al
        and     bl, 7
        mov     [m33_sh], bl
        sar     ax, 3
        mov     [m33_lb], ax            ; the left byte's column (may be < 0)
        xor     si, si                  ; SI = row 0..15
.row:   mov     ax, [m33_drow]
        add     ax, si
        js      .next
        cmp     ax, [m33_rows]
        jge     .next
        mov     cl, [m33_bk]            ; the row's address:
        mov     bx, ax
        shr     ax, cl
        mov     dx, 80
        mul     dx                      ;  (y >> banks) * 80
        mov     di, ax
        mov     ax, 1
        shl     ax, cl
        dec     ax
        and     bx, ax
        shl     bx, 13                  ;  + (y & (banks - 1)) * 2000h
        add     di, bx
        add     di, [m33_lb]
        cmp     byte [m33_und], 0
        jne     .put
        mov     bx, si                  ; this row's 3 AND and 3 XOR bytes
        add     bx, bx
        mov     ax, [m33_gm + bx]
        not     ax
        mov     dx, [m33_gm + 32 + bx]
        xor     bx, bx
        mov     cl, [m33_sh]
        or      cl, cl
        jz      .sd
.sh:    shr     ax, 1
        rcr     bl, 1
        shr     dx, 1
        rcr     bh, 1
        dec     cl
        jnz     .sh
.sd:    not     ax
        not     bl
        mov     [m33_tmp], ah
        mov     [m33_tmp + 1], al
        mov     [m33_tmp + 2], bl
        mov     [m33_tmp + 3], dh
        mov     [m33_tmp + 4], dl
        mov     [m33_tmp + 5], bh
.put:   mov     bx, si                  ; BX = row * 3 + byte
        add     bx, si
        add     bx, si
        xor     cx, cx                  ; CX = byte 0..2
.byte:  mov     ax, [m33_lb]
        add     ax, cx
        js      .nb
        cmp     ax, 80
        jge     .nb
        push    di
        add     di, cx
        mov     al, [es:di]
        cmp     byte [m33_und], 0
        jne     .rest
        mov     [m33_save + bx], al
        push    bx
        mov     bx, cx
        and     al, [m33_tmp + bx]
        xor     al, [m33_tmp + 3 + bx]
        pop     bx
        mov     [es:di], al
        mov     [m33_drawn + bx], al
        jmp     short .bd
.rest:  cmp     al, [m33_drawn + bx]
        jne     .bd                     ; (written over since)
        mov     al, [m33_save + bx]
        mov     [es:di], al
.bd:    pop     di
.nb:    inc     bx
        inc     cx
        cmp     cx, 3
        jb      .byte
.next:  inc     si
        cmp     si, 16
        jb      .row
        ret

; Microsoft's arrow (hot spot 0, 0), then the text masks (inverse cell)
m33_arrow:
        dw 3FFFh, 1FFFh, 0FFFh, 07FFh, 03FFh, 01FFh, 00FFh, 007Fh
        dw 003Fh, 001Fh, 01FFh, 10FFh, 30FFh, 0F87Fh, 0F87Fh, 0FC7Fh
        dw 0000h, 4000h, 6000h, 7000h, 7800h, 7C00h, 7E00h, 7F00h
        dw 7F80h, 7C00h, 6C00h, 4600h, 0600h, 0300h, 0300h, 0000h
        dw 77FFh, 7700h
