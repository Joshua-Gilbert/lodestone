; =====================================================================
;  LODE.PIC - Lodestone's start-up picture
;  nasm -f bin -o LODE.PIC SPLASH.ASM
;
;  Fig. 1 of F. A. Annett, Electrical Machinery (McGraw-Hill, 1921):
;  "Lodestone attracting some iron nails" (public domain), drawn from
;  vectors in mode 40h.  It is the plate as printed, in one colour: the
;  paper lit, the stone dark, and every nail lit where it lies on the stone
;  and dark where it crosses the paper.  The stone is an outline filled row
;  by row; a nail is a line 3 pixels wide with a point and a head.  Beside
;  it the title, LODESTONE, underlined.
;
;  SPLASH.INC holds the drawing: 4 bytes a nail.  splash/mksplash.py makes
;  it from splash/trace.txt, and draws the same picture, bit for bit as
;  this does, for the tests.
;
;  The kernel's bootstrap (KSPLASH.INC, never resident) reads this file
;  into free memory at the end of start-up, unless SPLASH=0 in \LODE.INI,
;  checks the signature and length below and calls it far at offset 0.
;  It draws, waits 2 seconds or for a key (which it takes), and returns;
;  nothing of it stays.  Its scratch is the rest of its segment, after
;  the file.
;
;  For pcemu's tests it marks its start, the end of the drawing and its
;  end with INT 1Ah AH=0, BX = BEF0h / BEF2h / BEF1h (BENCH's way of
;  marking time; the BIOS ignores BX).
; =====================================================================
cpu 286
org 0

        jmp     short sp_main
        db      'LODEPIC', 1            ; (KSPLASH.INC checks this, and that
        dw      pic_end                 ;  it read exactly this many bytes)

SP_HOLD equ 36                          ; 2 seconds, in 18.2 Hz ticks
SP_VSEG equ 0B800h

sp_main:
        pusha
        push    ds
        push    es
        push    cs
        pop     ds
        cld
        call    sp_show
        pop     es
        pop     ds
        popa
        retf

; the picture, then 2 seconds or a key.  DS = CS.
sp_show:
        mov     bx, 0BEF0h              ; (mark: the picture starts)
        call    sp_tick
        mov     ax, 0040h
        int     10h
        push    ds
        push    0
        pop     ds
        cmp     byte [449h], 40h
        pop     ds
        jne     .x                      ; no 640x400: no picture (the
        call    sp_rows                 ;  Executive says why)
        call    sp_stone
        push    SP_VSEG
        pop     es
        call    sp_plate
        call    sp_nails
        call    sp_titles
        mov     bx, 0BEF2h              ; (mark: drawn)
        call    sp_tick
        call    sp_hold
.x:     mov     bx, 0BEF1h              ; (mark: gone)

; INT 1Ah's ticks with BX = a mark.  The day's rollover flag it hands back
; is put back for the kernel's clock.
sp_tick:
        xor     ah, ah
        int     1Ah
        or      al, al
        jz      .x
        push    ds
        push    0
        pop     ds
        mov     [470h], al
        pop     ds
.x:     ret

; 2 seconds, or a key (taken: it only ends the picture).  Keys typed
; before it (spare F taps from choosing the floppy at the BIOS's prompt)
; go first, or they would end it at once.
sp_hold:
.fl:    mov     ah, 1
        int     16h
        jz      .t
        xor     ah, ah
        int     16h
        jmp     .fl
.t:     push    ds
        push    0
        pop     ds
        mov     bp, [46Ch]              ; the BIOS's tick count
.w:     mov     ah, 1
        int     16h
        jnz     .key
        mov     ax, [46Ch]
        sub     ax, bp
        cmp     ax, SP_HOLD
        jae     .x
        sti
        hlt
        jmp     .w
.key:   xor     ah, ah
        int     16h
.x:     pop     ds
        ret

; SP_ROW[y] = (y & 3) * 2000h + (y >> 2) * 80
sp_rows:
        xor     bx, bx
        mov     di, SP_ROW
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

; the stone's rows from its outline: every edge that isn't level marks
; its rows y0 <= y < y1 from its upper end (x0, y0), at
; x = x0 + (x1 - x0) * (y - y0) / (y1 - y0) (IDIV: towards 0); each row
; keeps its least x, and its greatest + 1
sp_stone:
        push    ds
        pop     es
        mov     di, SP_XL
        mov     ax, 7FFFh
        mov     cx, 400
        rep     stosw
        xor     ax, ax                  ; (SP_XE follows)
        mov     cx, 400
        rep     stosw
        mov     si, (sp_poly)
        lodsw
        mov     bx, ax                  ; (BX, DX): this vertex
        lodsw
        mov     dx, ax
        mov     cx, SP_NV
.e:     push    cx
        lodsb                           ; the next one
        cbw
        add     ax, bx
        mov     cx, ax
        lodsb
        cbw
        add     ax, dx
        push    si
        push    cx
        push    ax
        xchg    ax, bx                  ; AX, BX = x0, y0; CX, DX = x1, y1
        xchg    bx, dx
        call    sp_edge
        pop     dx
        pop     bx
        pop     si
        pop     cx
        loop    .e
        ret

; one edge: AX, BX = x0, y0; CX, DX = x1, y1
sp_edge:
        cmp     bx, dx
        je      .x                      ; level
        jl      .o
        xchg    ax, cx                  ; from the upper end
        xchg    bx, dx
.o:     mov     [(sp_ex)], ax
        sub     cx, ax
        mov     [(sp_edx)], cx       ; x1 - x0
        sub     dx, bx
        mov     [(sp_edy)], dx       ; y1 - y0 (> 0)
        mov     di, bx
        shl     di, 1                   ; DI: y's entries
        xor     si, si                  ; SI = y - y0
.r:     mov     ax, [(sp_edx)]
        imul    si
        idiv    word [(sp_edy)]
        add     ax, [(sp_ex)]
        cmp     ax, [SP_XL + di]
        jge     .l
        mov     [SP_XL + di], ax
.l:     inc     ax
        cmp     ax, [SP_XE + di]
        jle     .n
        mov     [SP_XE + di], ax
.n:     add     di, 2
        inc     si
        cmp     si, [(sp_edy)]
        jb      .r
.x:     ret

; the plate: its rows lit from SP_PX for SP_PW pixels, but for the stone
sp_plate:
        mov     dx, SP_PY
.r:     mov     si, dx
        shl     si, 1
        mov     di, [SP_ROW + si]
        mov     ax, SP_PX
        mov     cx, SP_PX + SP_PW - 1
        mov     bl, 1
        call    sp_span
        mov     ax, [SP_XL + si]        ; the stone on this row, in the plate
        mov     cx, [SP_XE + si]
        dec     cx
        cmp     ax, SP_PX
        jge     .a
        mov     ax, SP_PX
.a:     cmp     cx, SP_PX + SP_PW - 1
        jle     .b
        mov     cx, SP_PX + SP_PW - 1
.b:     cmp     ax, cx
        jg      .n                      ; (none)
        xor     bl, bl
        call    sp_span
.n:     inc     dx
        cmp     dx, SP_PY + SP_PH
        jb      .r
        ret

; pixels AX to CX (CX >= AX) of the screen row at ES:DI: lit if BL, or dark
sp_span:
        pusha
        mov     si, ax
        mov     dx, cx
        mov     cl, al
        and     cl, 7
        mov     bh, 0FFh
        shr     bh, cl                  ; BH: the first byte's pixels
        mov     cl, dl
        and     cl, 7
        mov     ah, 7Fh
        shr     ah, cl
        not     ah                      ; AH: the last byte's
        shr     si, 3
        shr     dx, 3
        mov     cx, dx
        sub     cx, si                  ; CX: bytes after the first
        add     di, si
        mov     al, bh
        or      cx, cx
        jnz     .m
        and     al, ah                  ; one byte: both
        call    sp_put
        popa
        ret
.m:     call    sp_put
        inc     di
        dec     cx                      ; whole bytes between
        jz      .last
        xor     al, al
        or      bl, bl
        jz      .f
        dec     al
.f:     rep     stosb
.last:  mov     al, ah
        call    sp_put
        popa
        ret

; the pixels AL at ES:DI: lit if BL, or dark
sp_put: or      bl, bl
        jz      .d
        or      [es:di], al
        ret
.d:     not     al
        and     [es:di], al
        ret

; A nail's pixel (CX, DX): lit on the stone, dark on the paper.  Straight
; through, no branches: whether it is on the stone is two compares made
; into a mask (x >= the row's left end, x < its right end + 1).  Every
; point mksplash.py draws is on the screen (it checks), so none is
; clipped.  DS = CS, ES = the screen; AX, BX, SI, DI lost.
%macro NPIX 0
        mov     bx, dx
        add     bx, bx
        mov     di, cx
        shr     di, 3
        add     di, [SP_ROW + bx]
        mov     si, cx
        and     si, 7
        mov     al, [(sp_bit) + si]
        cmp     cx, [SP_XL + bx]        ; CF: left of the stone
        cmc
        sbb     ah, ah                  ; FFh: not left of it
        cmp     cx, [SP_XE + bx]        ; CF: not right of it
        sbb     bl, bl
        and     ah, bl                  ; FFh: on it
        mov     bl, al
        not     bl
        and     bl, [es:di]
        and     al, ah
        or      al, bl
        mov     [es:di], al
%endmacro

; a lit pixel (CX, DX), the same way; AX, BX, SI, DI lost
%macro LPIX 0
        mov     bx, dx
        add     bx, bx
        mov     di, cx
        shr     di, 3
        add     di, [SP_ROW + bx]
        mov     si, cx
        and     si, 7
        mov     al, [(sp_bit) + si]
        or      [es:di], al
%endmacro

; every nail: 4 bytes each, by head row (SPLASH.INC)
sp_nails:
        mov     si, (sp_ndata)
        xor     dx, dx                  ; DX: the last head's row
        mov     cx, SP_NN
.n:     push    cx
        lodsb                           ; x: its low byte
        mov     bl, al
        lodsb                           ; its bit 8, rows down from the last
        mov     bh, 0
        test    al, 80h
        jz      .y
        inc     bh
.y:     and     ax, 7Fh
        add     dx, ax
        mov     [(sp_x0)], bx        ; the head
        mov     [(sp_y0)], dx
        lodsb                           ; the point
        cbw
        add     ax, bx
        mov     [(sp_x1)], ax
        lodsb
        cbw
        add     ax, dx
        mov     [(sp_y1)], ax
        push    si
        push    dx
        call    sp_nail
        pop     dx
        pop     si
        pop     cx
        loop    .n
        ret

; a nail from its head (sp_x0, sp_y0) to its point (sp_x1, sp_y1).  The
; shank, Bresenham's way from the head: 3 pixels wide across the line's
; minor axis, 2 for the last SP_TAPER - 1 points and 1 for the last.  The
; steps are vectors set up first, so the loop never asks which way the
; line runs.  Then the head: across the shank, 5 long and 2 deep, the
; second row or column further from the point.
sp_nail:
        call    sp_setup
        mov     cx, [(sp_x0)]
        mov     dx, [(sp_y0)]
.p:     NPIX                            ; the point
        cmp     bp, 1
        jbe     .s
        add     cx, [(sp_ox)]        ; beside it
        add     dx, [(sp_oy)]
        NPIX
        sub     cx, [(sp_ox)]
        sub     dx, [(sp_oy)]
        cmp     bp, SP_TAPER
        jbe     .s
        sub     cx, [(sp_ox)]        ; and on its other side
        sub     dx, [(sp_oy)]
        NPIX
        add     cx, [(sp_ox)]
        add     dx, [(sp_oy)]
.s:     mov     ax, [(sp_err)]
        sub     ax, [(sp_min)]
        jge     .ok
        add     ax, [(sp_maj)]
        add     cx, [(sp_nx)]        ; the minor step
        add     dx, [(sp_ny)]
.ok:    mov     [(sp_err)], ax
        add     cx, [(sp_mx)]        ; the major step
        add     dx, [(sp_my)]
        dec     bp
        jnz     .p
        mov     bx, 1                   ; the head: back from the point
        mov     ax, [(sp_x1)]
        cmp     ax, [(sp_x0)]
        jle     .hx
        neg     bx
.hx:    mov     [(sp_hsx)], bx
        mov     bx, 1
        mov     ax, [(sp_y1)]
        cmp     ax, [(sp_y0)]
        jle     .hy
        neg     bx
.hy:    mov     [(sp_hsy)], bx
        mov     bp, -2
.k:     mov     cx, [(sp_x0)]
        mov     dx, [(sp_y0)]
        cmp     word [(sp_ox)], 0
        je      .sh
        add     cx, bp                  ; steep: a row across
        call    sp_npx
        add     dx, [(sp_hsy)]
        call    sp_npx
        jmp     short .nk
.sh:    add     dx, bp                  ; shallow: a column across
        call    sp_npx
        add     cx, [(sp_hsx)]
        call    sp_npx
.nk:    inc     bp
        cmp     bp, 2
        jle     .k
        ret

sp_npx: NPIX
        ret

; Bresenham's set-up for a line from (sp_x0, sp_y0) to (sp_x1, sp_y1):
; BP = its points; sp_maj, sp_min = its lengths along and across; sp_err;
; the major step (sp_mx, sp_my), the minor (sp_nx, sp_ny) and the step
; across the line (sp_ox, sp_oy: (1, 0) if it is steep, more down than
; across, or else (0, 1))
sp_setup:
        xor     ax, ax
        mov     [(sp_mx)], ax
        mov     [(sp_my)], ax
        mov     [(sp_nx)], ax
        mov     [(sp_ny)], ax
        mov     [(sp_ox)], ax
        mov     [(sp_oy)], ax
        mov     ax, [(sp_x1)]
        sub     ax, [(sp_x0)]
        mov     bx, 1
        jge     .xp
        neg     ax
        neg     bx
.xp:    mov     cx, ax                  ; CX = |dx|, BX = its sign
        mov     ax, [(sp_y1)]
        sub     ax, [(sp_y0)]
        mov     dx, 1
        jge     .yp
        neg     ax
        neg     dx                      ; AX = |dy|, DX = its sign
.yp:    cmp     ax, cx
        jle     .sh
        xchg    ax, cx                  ; steep: down is the major step
        mov     [(sp_my)], dx
        mov     [(sp_nx)], bx
        mov     word [(sp_ox)], 1
        jmp     short .l
.sh:    mov     [(sp_mx)], bx        ; shallow: across is
        mov     [(sp_ny)], dx
        mov     word [(sp_oy)], 1
.l:     mov     [(sp_min)], ax
        mov     [(sp_maj)], cx
        mov     bp, cx
        shr     cx, 1
        mov     [(sp_err)], cx
        inc     bp
        ret

; a stroke of the title, from (sp_x0, sp_y0) to (sp_x1, sp_y1): 2 x 2 lit
; at each point
sp_line:
        call    sp_setup
        mov     cx, [(sp_x0)]
        mov     dx, [(sp_y0)]
.p:     LPIX
        inc     cx
        LPIX
        inc     dx
        LPIX
        dec     cx
        LPIX
        dec     dx
        mov     ax, [(sp_err)]
        sub     ax, [(sp_min)]
        jge     .ok
        add     ax, [(sp_maj)]
        add     cx, [(sp_nx)]
        add     dx, [(sp_ny)]
.ok:    mov     [(sp_err)], ax
        add     cx, [(sp_mx)]
        add     dx, [(sp_my)]
        dec     bp
        jnz     .p
        ret

; the title: each letter's strokes (x, y bytes; 0FFh lifts the pen, 0FEh
; ends it) at SP_TX + its place * SP_TADV, SP_TY; then the rule
sp_titles:
        mov     word [(sp_gx)], SP_TX
        mov     si, (sp_title)
        lodsb
        xor     ah, ah
        mov     cx, ax
.l:     push    cx
        lodsw
        push    si
        xchg    ax, si
.s:     call    .pt                     ; a stroke's first point
        jc      .g
        mov     [(sp_x1)], ax
        mov     [(sp_y1)], dx
.q:     call    .pt                     ; to the next, until the pen lifts
        jc      .g
        mov     cx, [(sp_x1)]
        mov     [(sp_x0)], cx
        mov     cx, [(sp_y1)]
        mov     [(sp_y0)], cx
        mov     [(sp_x1)], ax
        mov     [(sp_y1)], dx
        push    si
        call    sp_line
        pop     si
        jmp     .q
.g:     cmp     al, 0FEh                ; (the pen lifted: a new stroke)
        jne     .s
        pop     si
        add     word [(sp_gx)], SP_TADV
        pop     cx
        loop    .l
        mov     di, [SP_ROW + 2 * SP_RY]
        mov     ax, SP_RX0
        mov     cx, SP_RX1
        mov     bl, 1
        jmp     sp_span
; a glyph's next point -> AX, DX on the screen; or CF and AL = 0FFh / 0FEh
.pt:    lodsb
        cmp     al, 0FEh
        jae     .e
        xor     ah, ah
        add     ax, [(sp_gx)]
        push    ax
        lodsb
        xor     ah, ah
        add     ax, SP_TY
        xchg    ax, dx
        pop     ax
        clc
        ret
.e:     stc
        ret

sp_bit  db      80h, 40h, 20h, 10h, 8, 4, 2, 1
            align 2
sp_x0   dw      0                       ; a line: from
sp_y0   dw      0
sp_x1   dw      0                       ;  to
sp_y1   dw      0
sp_mx   dw      0                       ; its major step
sp_my   dw      0
sp_nx   dw      0                       ; its minor step
sp_ny   dw      0
sp_ox   dw      0                       ; across it
sp_oy   dw      0
sp_maj  dw      0
sp_min  dw      0
sp_err  dw      0
sp_hsx  dw      0                       ; a nail's head: back from the point
sp_hsy  dw      0
sp_ex   dw      0                       ; an edge of the stone
sp_edx  dw      0
sp_edy  dw      0
sp_gx   dw      0                       ; the title's letter, at
%include "SPLASH.INC"
            align 16
pic_end:                                ; the file ends here; then scratch:
SP_ROW  equ pic_end                     ; per row: its offset in the screen
SP_XL   equ SP_ROW + 800                ; per row: the stone's left x, and
SP_XE   equ SP_XL + 800                 ;  its right x + 1 (7FFFh, 0: none)
