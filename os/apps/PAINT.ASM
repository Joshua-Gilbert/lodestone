; =====================================================================
;  PAINT.RUN - Paint: drawing on the whole screen, and the BMP viewer
;  python3 mkrun.py apps/PAINT.ASM apps/PAINT.RUN
;
;  The picture is the whole 640 x 400 screen, in the format of the
;  kernel's Shift-PrtSc pictures (1 bit, bottom line first, 80 bytes a
;  line, bit set = lit), so every SCREENnn.BMP opens as it was taken and
;  every picture Paint saves is one.  Started on a file (Return on a .BMP
;  in the Executive) it shows it, and clicks don't draw until Return or
;  a tool's key; started alone it is a dark page to draw on.
;
;  Two 32,000-byte blocks from UI_ALLOC hold the picture in file order:
;  C, as the screen shows it between strokes, and U, as it was before the
;  last stroke.  A stroke swaps them (U: the picture before it; C: free
;  meanwhile), draws on the screen, and copies the screen into C when the
;  button comes up.  Undo swaps them back and shows C; again is redo.
;  Saving writes the header and C; loading reads the file into U and
;  places it in C.  After the screen saver the redraw routine shows C.
;
;  The mouse: the core's INT 33h, which follows every packet.  A press
;  comes from UI_EVENT (the core's pointer shows while it waits, and the
;  clock, the saver and the windows work as everywhere); the stroke then
;  follows the button and the position with function 3 until the
;  button comes up.  Function 0Fh makes it move as the core's pointer
;  does, and function 4 puts it where the press was.
;
;  Every write to the screen is  AND NOT (mask AND A), then XOR (mask AND
;  pattern AND X):  ink is A = X = FFh, erasing A = FFh, X = 0, and the
;  rubber band (XOR) A = 0, X = FFh.  One loop for all three, and no code
;  patched (the emulator would keep running an old copy of it).
;
;  The band: the core redraws its prompt band after the saver, over the
;  picture.  Paint puts lines 360-399 back from C after every key and
;  every dialog; after the saver in its own wait, the redraw routine puts
;  a key of its own (K_MEND) in the BIOS's buffer, so the wait ends and
;  the band is mended at once.  (A BIOS without INT 16h AH=05h: the band
;  stays until the next key.)  Design: docs/lodestone-paint.md.
;
;  With MULTITASK=1 Paint is a window .RUN (RF_WIN): a window beside the
;  others, its inside (the canvas) a 1:1 view of the 640 x 400 picture,
;  moved by the arrows, PgUp, PgDn and Ctrl-Left/Right.  It still draws
;  in screen co-ordinates: only blit_view (C to the canvas) and
;  commit_view (U and the canvas into C) know where the view is.  A
;  stroke's points are clamped to the canvas, fills follow the picture's
;  lines (pph), and the mouse is UI_MOUSE (a core from API 8 on).  No
;  band to mend: a window never covers the band (zoomed, Paint in front draws over it: below).  A drag on the window's
;  frame moves the view (pan).  CODE-F zooms: the window made the whole
;  screen in place (no title), ses 0, and the whole screen's paths as
;  without windows; CODE-F again, the window as it was (k_zoom).
; =====================================================================
%include "UIAPI.INC"
%include "WINPOS.INC"
RUN_API equ 6                           ; (the tools' window moves and closes)
RUN_FLAGS equ RF_WIN                    ; (with MULTITASK=1, a window; without,
                                        ;  the whole screen as ever)
        org     RUN_ORG

VSEG    equ 0B800h
PIC     equ 32000                       ; the picture: 400 lines of 80 bytes
HDRN    equ 146                         ; header bytes read: up to a V5
                                        ;  header and its first two colours
K_MEND  equ 0FF00h                      ; (the redraw routine's key)
NTOOL   equ 6
T_TOP   equ W_TOP + 7 * 16 + 2          ; the patterns in the tools' window

start:  mov     di, fname               ; the argument: the picture to show
        call    UI_SBSTR
        mov     byte [di], 0
        mov     bx, PIC / 16
        call    UI_ALLOC
        jc      nomem
        mov     [segc], ax
        call    UI_ALLOC
        jc      nomem
        mov     [segu], ax
        mov     di, rowoff              ; line y -> its offset on the screen
        xor     dx, dx
.row:   mov     ax, dx
        and     ax, 3
        ror     ax, 3                   ; (bank: bits 0-1 to 13-14)
        mov     bx, dx
        shr     bx, 2
        imul    bx, bx, 80
        add     ax, bx
        stosw
        inc     dx
        cmp     dx, 400
        jb      .row
        mov     di, popc + 1            ; bits set in each byte value
.pc:    mov     ax, di
        sub     ax, popc
        mov     bx, ax
        shr     bx, 1
        and     al, 1
        add     al, [popc + bx]
        stosb
        cmp     di, popc + 256
        jb      .pc
        mov     ax, 0F01Dh              ; a window .RUN's session? (MT_WIN, as
        stc                             ;  Write: it fails with the switch off)
        int     21h
        jc      .i33
        inc     byte [ses]
        mov     [sp0], sp               ; (its stack's top: w_zoom's test)
        mov     word [kt_xfer], K_CODE_X        ; (CODE-T is the tasks')
        mov     byte [h_xfer + 5], 'X'
        mov     word [kh_view + 4], h_view      ; the view's keys in the help
        mov     word [kh_view + 10], h_view2
        mov     word [kh_view + 16], h_pan
        mov     word [kh_zoom + 4], h_zoom
        WIN_STAGGER                     ; (a second Paint not right over it)
        call    UI_VERSION
        cmp     ax, 8                   ; UI_MOUSE (API 8) for strokes; an
        jb      .i33                    ;  older core: INT 33h as full screen
        inc     byte [umouse]
        jmp     short .m
.i33:   xor     ax, ax                  ; the mouse: reset, and 1:1 as the
        int     33h                     ;  core's pointer moves
        mov     ax, 0Fh
        mov     cx, 8
        mov     dx, cx
        int     33h
.m:     mov     byte [bsize], 2
        call    full                    ; the canvas: the whole screen
        cmp     byte [fname], 0
        je      .new
        mov     si, fname
        call    load
        jnc     .view
        call    load_err                ; (over the Executive; C was never
        jmp     main.bye                ;  shown, so no redraw routine yet)
.view:  inc     byte [view]
        jmp     short .show
.new:   mov     es, [segc]              ; a dark page
        xor     di, di
        mov     cx, PIC / 2
        xor     ax, ax
        rep     stosw
        push    ds
        pop     es
.show:  mov     es, [segu]              ; U = C: nothing to undo yet
        push    ds
        mov     ds, [segc]
        xor     si, si
        xor     di, di
        mov     cx, PIC / 2
        rep     movsw
        pop     ds
        push    ds
        pop     es
        cmp     byte [ses], 0
        je      .full
        call    title                   ; a window: the view centred on the
        call    geom                    ;  picture, then opened (its W_DRAW,
        mov     ax, 80                  ;  w_draw, shows C)
        sub     ax, [cw]
        shr     ax, 1
        mov     [vx], ax
        mov     ax, 400
        sub     ax, [chh]
        shr     ax, 1
        mov     [vy], ax
        mov     si, win
        call    UI_WOPEN
        inc     byte [wopen]
        call    status
        jmp     short main
.full:  mov     si, redraw
        call    UI_SETREDRAW
        call    UI_CLS                  ; (no title: no clock over it)
        call    blit_all
        cmp     byte [view], 0
        jne     main
        mov     si, s_hint              ; the key or click that ends the hint
        call    UI_MSG                  ;  counts (but ESC: only the hint)
        cmp     ax, K_ESC
        je      main
        cmp     ax, EV_CLICK            ; (a click on the band, where the
        jne     .hk                     ;  hint is: only the hint too)
        cmp     cx, SCR_BAND_Y
        jae     main
.hk:    pusha                           ; (band_fix changes AX, CX)
        call    band_fix
        popa
        jmp     short main.got
main:   cmp     byte [ses], 0           ; (a window: no band to mend)
        jne     .q
        cmp     byte [tz], 0            ; (zoomed, drawn again while a question
        je      .bf                     ;  of Paint's waited: the band kept, the
        call    w_zoom.f                ;  title perhaps on: all of it now)
.bf:    call    band_fix
.q:     cmp     byte [quit], 0
        jne     .bye
        mov     byte [in_ev], 1
        call    UI_EVENT
        mov     byte [in_ev], 0
.got:   cmp     ax, EV_CLICK
        jne     .key
        cmp     bx, [clx0]              ; (in a window: on the canvas only;
        jl      .pan                    ;  on its frame, the view dragged)
        cmp     bx, [clx1]
        jg      .pan
        cmp     cx, [cly0]
        jl      .pan
        cmp     cx, [cly1]
        jg      .pan
        cmp     byte [view], 0
        jne     main
        call    stroke
        jmp     main
.pan:   call    pan
        jmp     main
.key:   cmp     ax, EV_MOVED            ; the window moved or resized: drawn
        je      .st                     ;  there already (w_draw), the view
        cmp     ax, EV_SIZE             ;  perhaps moved into the picture
        je      .st
        call    do_key
        jmp     main
.st:    call    status
        jmp     main
.bye:   cmp     byte [wopen], 0
        je      .bm
        call    UI_WCLOSE
.bm:    cmp     byte [umouse], 0
        jne     .b0
        xor     ax, ax                  ; the driver as a reset leaves it
        int     33h
.b0:    xor     ax, ax                  ; (the Executive reads the list again)
        ret
nomem:  mov     si, s_nomem
        call    UI_MSG
        mov     ax, 8
        ret

; a key (AX): letters as capitals, 1-8 the pattern, else the key table
do_key: cmp     al, 'a'
        jb      .d
        cmp     al, 'z'
        ja      .d
        sub     al, 20h
.d:     cmp     al, '1'
        jb      .t
        cmp     al, '8'
        ja      .t
        sub     al, '1'
        mov     [patn], al
        jmp     k_edit
.t:     mov     si, keys
        jmp     UI_DISPATCH

; ---------------------------------------------------------------------
;  strokes
; ---------------------------------------------------------------------
; a press at BX, CX: follow the button until it comes up
stroke: cmp     byte [mend], 0          ; a press right after the saver, before
        jne     .fix                    ;  the band was mended, or zoomed (the
        cmp     byte [ses], 0           ;  band back over it as the focus came
        jne     .go                     ;  back, while it waited): mend it
        cmp     byte [wopen], 0         ;  first (the commit would keep it)
        je      .go
.fix:   pusha
        call    band_fix
        xor     ax, ax                  ; (and the clock's lines: zoomed,
        mov     cx, 16                  ;  another session's clock may be
        call    blit                    ;  over them)
        popa
.go:    mov     dx, cx                  ; the driver's position: the press
        mov     cx, bx                  ;  (UI_MOUSE's is the core's: as it)
        cmp     byte [umouse], 0
        jne     .c
        mov     ax, 4
        int     33h
.c:     call    clamp
        mov     [x0], cx
        mov     [y0], dx
        mov     [lx], cx
        mov     [ly], dx
        cmp     byte [ses], 0           ; U: the picture before this stroke
        je      .sw                     ;  (a window: U = C, copied where
        call    sync_u                  ;  they may differ; else a swap)
        jmp     short .s
.sw:    mov     ax, [segc]
        xchg    ax, [segu]
        mov     [segc], ax
.s:     push    es
        push    VSEG
        pop     es
        mov     byte [phase], 0
        mov     cx, [x0]
        mov     dx, [y0]
        call    tool_do
.l:     call    sample                  ; BX = buttons, CX = x, DX = y
        cmp     cx, [lx]
        jne     .mv
        cmp     dx, [ly]
        je      .up
.mv:    mov     byte [phase], 1
        call    tool_do
        mov     [lx], cx
        mov     [ly], dx
.up:    test    bl, 1
        jnz     .l
        mov     byte [phase], 2
        mov     cx, [lx]
        mov     dx, [ly]
        call    tool_do
        pop     es
        mov     byte [changed], 1
        jmp     commit

; the mouse at the next interrupt -> BX = buttons, CX = x, DX = y, the
; point clamped to the canvas: the core's UI_MOUSE (a window, API 8), or
; the driver's function 3
smouse: call    UI_MOUSE                ; AX = buttons, BX = x, CX = y
        jnc     .m
        xor     ax, ax                  ; (no mouse: the button is up, at the
        mov     bx, [lx]                ;  last point)
        mov     cx, [ly]
.m:     mov     dx, cx
        mov     cx, bx
        xchg    bx, ax
        jmp     short clamp
sample: cmp     byte [umouse], 0
        jne     smouse
        sti
        hlt
        mov     ax, 3
        int     33h
        ; (falls through)

; CX, DX into the canvas (clx0-clx1, cly0-cly1)
clamp:  cmp     cx, [clx0]
        jge     .x0
        mov     cx, [clx0]
.x0:    cmp     cx, [clx1]
        jle     .x1
        mov     cx, [clx1]
.x1:    cmp     dx, [cly0]
        jge     .y0
        mov     dx, [cly0]
.y0:    cmp     dx, [cly1]
        jle     .y1
        mov     dx, [cly1]
.y1:    ret

tool_do:
        pusha
        mov     bx, [tool]
        add     bx, bx
        call    [tools + bx]
        popa
        ret

; the tools: [phase] 0 at the press (CX, DX), 1 at each move (CX, DX the
; new point, lx, ly the last), 2 when the button comes up (CX, DX = lx,
; ly).  ES = the screen.
t_pencil:
        mov     si, plot
        mov     di, pats                ; (solid)
        mov     ax, 0FFFFh
        jmp     short free
t_brush:
        call    curpat
        mov     si, dot
        mov     ax, 0FFFFh
        mov     bl, 2                   ; 2, 4, 6 or 8 pixels square
        jmp     short sized
t_erase:
        mov     di, pats
        mov     si, dot
        mov     ax, 0FF00h
        mov     bl, 4                   ; 4 to 16
sized:  push    ax
        mov     al, [bsize]
        mul     bl
        mov     [dside], ax
        pop     ax
free:   call    set_op
        mov     [dotfn], si
        cmp     byte [phase], 1
        jb      .first
        ja      .x
        mov     ax, [lx]
        mov     bx, [ly]
        jmp     line                    ; the last point to this one
.first: jmp     si
.x:     ret

t_line: mov     si, line
        jmp     short shape
t_rect: mov     si, frame
        jmp     short shape
t_fill: mov     si, frame               ; (its outline while it moves)
shape:  mov     di, pats
        mov     ax, 00FFh               ; XOR, solid
        call    set_op
        mov     word [dotfn], plot
        mov     ax, [x0]
        mov     bx, [y0]
        cmp     byte [phase], 1
        jb      .new                    ; the first: just the point
        push    cx
        push    dx
        mov     cx, [lx]                ; the old one off
        mov     dx, [ly]
        call    si
        pop     dx
        pop     cx
        cmp     byte [phase], 1
        ja      .ink
.new:   jmp     si                      ; the new one on
.ink:   mov     di, pats
        cmp     word [tool], 5
        jne     .solid
        call    curpat
.solid: mov     ax, 0FFFFh
        call    set_op
        mov     ax, [x0]
        cmp     word [tool], 5
        jne     .new
        jmp     fillrect

; the drawing op: AH = A, AL = X, DI = the pattern
set_op: mov     [opa], ah
        mov     [opx], al
        mov     [cpat], di
        ret

; -> DI = the chosen pattern, at the canvas's phase (pph: picture line
; minus screen line, 0-7; each pattern is there twice over)
curpat: mov     di, [patn]
        and     di, 7
        shl     di, 4
        add     di, [pph]
        add     di, pats
        ret

; ---------------------------------------------------------------------
;  drawing (ES = the screen; every routine keeps every register)
; ---------------------------------------------------------------------
; the pixel CX, DX
; (solid: the pencil, lines and outlines never take a pattern).  PIXEL
; changes AX, BX, DI; line has it inline
%macro PIXEL 0
        mov     bx, dx
        add     bx, bx
        mov     di, [rowoff + bx]
        mov     bx, cx
        shr     bx, 3
        add     di, bx
        mov     bx, cx
        and     bx, 7
        mov     al, [bitm + bx]
        mov     ah, al
        and     al, [opx]
        and     ah, [opa]
        not     ah
        and     [es:di], ah
        xor     [es:di], al
%endmacro
        times   ($ - $$) & 1 db 90h     ; (hot: even)
plot:   push    ax
        push    bx
        push    di
        PIXEL
        pop     di
        pop     bx
        pop     ax
        ret

; from AX, BX to CX, DX: [dotfn] at each point (Bresenham: the steps
; along and across are set up first, so the loop never asks which way)
        times   ($ - $$) & 1 db 90h     ; (hot: even)
line:   pusha
        push    cx
        push    dx
        mov     cx, ax                  ; CX, DX: the point
        mov     dx, bx
        pop     bx
        pop     ax
        sub     ax, cx                  ; AX = x1 - x0, BX = y1 - y0
        sub     bx, dx
        mov     si, 1
        or      ax, ax
        jns     .xp
        neg     ax
        neg     si
.xp:    mov     di, 1
        or      bx, bx
        jns     .yp
        neg     bx
        neg     di
.yp:    mov     bp, 0                   ; (3 bytes, as fast as XOR: the
        cmp     ax, bx                  ;  loop's labels even)
        jae     .xm
        xchg    ax, bx                  ; y the longer: along y, across x
        mov     [mjx], bp
        mov     [mjy], di
        mov     [mnx], si
        mov     [mny], bp
        jmp     short .go
.xm:    mov     [mjx], si
        mov     [mjy], bp
        mov     [mnx], bp
        mov     [mny], di
.go:    mov     si, ax                  ; AX = steps along, BX = across
        inc     si                      ; (points: one more)
        mov     bp, ax
        shr     bp, 1
        cmp     word [dotfn], plot
        je      .px
.l:     call    [dotfn]                 ; (the brush and the eraser)
        sub     bp, bx
        jns     .al
        add     bp, ax
        add     cx, [mnx]
        add     dx, [mny]
.al:    add     cx, [mjx]
        add     dx, [mjy]
        dec     si
        jnz     .l
        popa
        ret
.px:    mov     [mlen], ax              ; one pixel wide: inline
        mov     [macr], bx
.p:     PIXEL
        sub     bp, [macr]
        jns     .pa
        add     bp, [mlen]
        add     cx, [mnx]
        add     dx, [mny]
.pa:    add     cx, [mjx]
        add     dx, [mjy]
        dec     si
        jnz     .p
        popa
        ret

; AX, BX, CX, DX in order: x0 <= x1 (AX, CX), y0 <= y1 (BX, DX)
order:  cmp     ax, cx
        jbe     .y
        xchg    ax, cx
.y:     cmp     bx, dx
        jbe     .x
        xchg    bx, dx
.x:     ret

; the rectangle between corners AX, BX and CX, DX, filled with the
; pattern: its edge masks and first byte worked out once, then each line
; the left byte through its mask, the bytes between whole (a word at a
; time, unless XOR), the right byte through its mask
        times   ($ - $$) & 1 db 90h     ; (hot: even)
fillrect:
        pusha
        call    order
        push    dx
        mov     dx, bx                  ; DX = the line
        mov     bp, cx
        mov     cl, al
        and     cl, 7
        mov     bl, 0FFh
        shr     bl, cl                  ; BL: the left mask
        mov     cx, bp
        and     cl, 7
        xor     cl, 7
        mov     bh, 0FFh
        shl     bh, cl                  ; BH: the right mask
        shr     ax, 3
        shr     bp, 3
        sub     bp, ax                  ; BP: bytes after the first
        jnz     .two
        and     bl, bh                  ; (one byte: both masks)
.two:   mov     [fr_x], ax
        mov     [fr_m], bx
        pop     si                      ; SI = the last line
.row:   mov     bx, dx
        add     bx, bx
        mov     di, [rowoff + bx]
        add     di, [fr_x]
        mov     bx, dx
        and     bx, 7
        add     bx, [cpat]
        mov     ah, [bx]
        and     ah, [opx]               ; AH: the pattern's bits as put in
        mov     bx, [fr_m]
        mov     al, bl
        call    .put
        mov     cx, bp
        jcxz    .next
        inc     di
        dec     cx
        jz      .last
        mov     al, ah
        cmp     byte [opa], 0
        je      .xor
        shr     cx, 1
        rep     stosw
        jnc     .last
        stosb
        jmp     short .last
.xor:   xor     [es:di], al
        inc     di
        loop    .xor
.last:  mov     al, bh
        call    .put
.next:  inc     dx
        cmp     dx, si
        jbe     .row
        popa
        ret
.put:   mov     cl, al                  ; mask AL at ES:DI
        and     cl, [opa]
        not     cl
        and     [es:di], cl
        and     al, ah
        xor     [es:di], al
        ret

; its outline, each pixel once (the rubber band XORs it)
        times   ($ - $$) & 1 db 90h     ; (hot: even)
frame:  pusha
        call    order
        mov     si, dx                  ; SI = y1
        mov     di, bx                  ; DI = y0
        mov     dx, bx
        call    fillrect                ; the top
        cmp     si, di
        je      .x
        mov     bx, si
        mov     dx, si
        call    fillrect                ; the bottom
        mov     bx, cx                  ; the sides between: BX = x1,
        mov     cx, ax                  ;  CX = x0
        mov     dx, di
.s:     inc     dx
        cmp     dx, si
        jae     .x
        call    plot
        cmp     bx, cx
        je      .s
        xchg    bx, cx
        call    plot
        xchg    bx, cx
        jmp     .s
.x:     popa
        ret
; the brush or the eraser at CX, DX: a square of [dside], cut at the edges
        times   ($ - $$) & 1 db 90h     ; (hot: even)
dot:    pusha
        mov     si, [dside]
        dec     si
        mov     bx, si
        shr     bx, 1
        mov     ax, cx
        sub     ax, bx                  ; AX, CX: its left and right, centred
        mov     cx, ax
        add     cx, si
        cmp     ax, [clx0]              ;  then cut at the canvas's edges
        jge     .x0                     ;  (signed)
        mov     ax, [clx0]
.x0:    cmp     cx, [clx1]
        jle     .x1
        mov     cx, [clx1]
.x1:    sub     dx, bx                  ; BX, DX: its top and bottom, the same
        mov     bx, dx
        add     dx, si
        cmp     bx, [cly0]
        jge     .y0
        mov     bx, [cly0]
.y0:    cmp     dx, [cly1]
        jle     .y1
        mov     dx, [cly1]
.y1:    call    fillrect
        popa
        ret


; ---------------------------------------------------------------------
;  the picture: C to the screen, the screen to C
; ---------------------------------------------------------------------
        times   ($ - $$) & 1 db 90h     ; (hot: even)
band_fix:
        mov     byte [mend], 0
        mov     ax, SCR_BAND_Y
        mov     cx, 400 - SCR_BAND_Y
        jmp     short blit
blit_all:
        xor     ax, ax
        mov     cx, 400
blit:   pusha                           ; lines AX .. AX + CX - 1 from C
        push    ds
        push    es
        push    VSEG
        pop     es
        mov     bx, ax
        add     bx, bx
        imul    si, ax, -80
        add     si, 399 * 80
        mov     dx, cx
        mov     ds, [segc]
.l:     mov     di, [cs:rowoff + bx]
        mov     cx, 40
        rep     movsw
        sub     si, 160
        add     bx, 2
        dec     dx
        jnz     .l
        pop     es
        pop     ds
        popa
        ret

        times   ($ - $$) & 1 db 90h     ; (hot: even)
commit: cmp     byte [ses], 0           ; (a window: its view of it)
        jne     commit_view
        pusha                           ; the screen into C
        push    ds
        push    es
        mov     es, [segc]
        push    VSEG
        pop     ds
        xor     di, di
        mov     bx, 399 * 2
.l:     mov     si, [cs:rowoff + bx]
        mov     cx, 40
        rep     movsw
        sub     bx, 2
        jns     .l
        pop     es
        pop     ds
        popa
        ret

; ---------------------------------------------------------------------
;  a window (MULTITASK=1): the canvas, a view of the picture
; ---------------------------------------------------------------------
; the canvas from the window as it is now: its first byte column cx0, cw
; bytes, its first line cy0, chh lines (inside the frame, under the title
; strip: win_paint's); clx0-clx1, cly0-cly1 its pixels; the view (vx
; bytes, vy lines into the picture) kept inside the picture; pph the
; fills' phase.  w_draw: the window's contents (W_DRAW, BX = the window;
; from any session's redraw), the view drawn again
w_draw: cmp     byte [ses], 0           ; (zoomed: the whole screen)
        je      w_zoom
        call    geom
        jmp     short blit_view
geom:   pusha
        mov     ax, [win + W_COL]
        inc     ax
        mov     [cx0], ax
        shl     ax, 3
        mov     [clx0], ax
        mov     cx, [win + W_W]
        sub     cx, 2
        mov     [cw], cx
        shl     cx, 3
        add     ax, cx
        dec     ax
        mov     [clx1], ax
        mov     ax, [win + W_Y]
        add     ax, 20
        mov     [cy0], ax
        mov     [cly0], ax
        mov     cx, [win + W_H]
        sub     cx, 21
        mov     [chh], cx
        add     ax, cx
        dec     ax
        mov     [cly1], ax
        mov     ax, 80
        sub     ax, [cw]
        cmp     [vx], ax
        jbe     .x
        mov     [vx], ax
.x:     mov     ax, 400
        sub     ax, [chh]
        cmp     [vy], ax
        jbe     .y
        mov     [vy], ax
.y:     mov     ax, [vy]                ; picture line - screen line, mod 8
        sub     ax, [cy0]
        and     ax, 7
        mov     [pph], ax
        popa
        ret

; CX bytes DS:SI to ES:DI, a word at a time
%macro MOVSN 0
        shr     cx, 1
        rep     movsw
        adc     cx, cx
        rep     movsb
%endmacro
; the same with the screen's side (%1: SI or DI) on a whole word: a byte
; first if it is odd (a word across two costs the screen two accesses;
; RAM's side odd costs much less).  CX > 0
%macro MOVSV 1
        test    %1, 1
        jz      %%w
        movsb
        dec     cx
%%w:    MOVSN
%endmacro

; C's view to the canvas
        times   ($ - $$) & 1 db 90h     ; (hot: even)
blit_view:
        pusha
        push    ds
        push    es
        push    VSEG
        pop     es
        mov     bx, [cy0]
        add     bx, bx
        mov     ax, 399
        sub     ax, [vy]
        imul    si, ax, 80
        add     si, [vx]                ; SI = the view's first line in C
        mov     dx, [chh]
        mov     bp, [cw]
        mov     ax, [cx0]
        mov     ds, [segc]
.l:     mov     di, [cs:rowoff + bx]
        add     di, ax
        mov     cx, bp
        MOVSV   di
        sub     si, bp
        sub     si, 80                  ; (the line above it in the file)
        add     bx, 2
        dec     dx
        jnz     .l
        pop     es
        pop     ds
        popa
        ret

; a stroke's end in a window: the canvas into C at the view (C is the
; picture outside it: the stroke began with U = C, sync_u); then C and U
; may differ only there (D: lines dy0-dy1, bytes dx0-dx1, as picture's)
        times   ($ - $$) & 1 db 90h     ; (hot: even)
commit_view:
        pusha
        push    ds
        push    es
        mov     ax, [vy]
        mov     [dy0], ax
        add     ax, [chh]
        mov     [dy1], ax
        mov     ax, [vx]
        mov     [dx0], ax
        add     ax, [cw]
        mov     [dx1], ax
        mov     es, [segc]
        mov     bx, [cy0]
        add     bx, bx
        mov     ax, 399
        sub     ax, [vy]
        imul    di, ax, 80
        add     di, [vx]                ; DI = the view's first line in C
        mov     dx, [chh]
        mov     bp, [cw]
        mov     ax, [cx0]
        push    VSEG
        pop     ds
.l:     mov     si, [cs:rowoff + bx]
        add     si, ax
        mov     cx, bp
        MOVSV   si
        sub     di, bp
        sub     di, 80                  ; (the line above it in the file)
        add     bx, 2
        dec     dx
        jnz     .l
        pop     es
        pop     ds
        popa
        ret

; a stroke's start in a window: U = C (copied where they may differ, D),
; so that U is the picture before it; then D is empty
        times   ($ - $$) & 1 db 90h     ; (hot: even)
sync_u: pusha
        push    ds
        push    es
        mov     dx, [dy1]
        sub     dx, [dy0]               ; DX = its lines
        jbe     .x
        mov     ax, 399
        sub     ax, [dy0]
        imul    si, ax, strict word 80  ; (imm16: as fast, the loop's label even)
        add     si, [dx0]
        mov     bp, [dx1]
        sub     bp, [dx0]               ; BP = its bytes a line
        mov     es, [segu]
        mov     ds, [segc]
.l:     mov     di, si
        mov     cx, bp
        MOVSN
        sub     si, bp
        sub     si, 80
        dec     dx
        jnz     .l
        mov     word [cs:dy1], 0        ; (empty: dy1 <= dy0)
.x:     pop     es
        pop     ds
        popa
        ret

; the band (a window): the hint, and where the view is
status: cmp     byte [ses], 0
        je      .x
        mov     di, stat
        mov     si, s_left
        call    UI_SBSTR
        mov     ax, [vx]
        shl     ax, 3
        call    UI_SBU16
        mov     si, s_top
        call    UI_SBSTR
        mov     ax, [vy]
        call    UI_SBU16
        mov     si, s_of
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, s_hint
        mov     di, stat
        jmp     UI_BAND
.x:     ret

; the arrows: the view 16 pixels; PgUp, PgDn and Ctrl-Left/Right a
; canvas's height or width (a window only)
k_up:   mov     ax, -16
        jmp     short vmove
k_down: mov     ax, 16
        jmp     short vmove
k_pgup: mov     ax, [chh]
        neg     ax
        jmp     short vmove
k_pgdn: mov     ax, [chh]
vmove:  mov     bx, vy
        jmp     short move
k_left: mov     ax, -2                  ; (whole bytes: 16 pixels)
        jmp     short hmove
k_right:
        mov     ax, 2
        jmp     short hmove
k_cleft:
        mov     ax, [cw]
        neg     ax
        jmp     short hmove
k_cright:
        mov     ax, [cw]
hmove:  mov     bx, vx
move:   cmp     byte [ses], 0
        je      .x
        add     ax, [bx]
        jns     .p
        xor     ax, ax
.p:     mov     [bx], ax
        call    geom                    ; (kept inside the picture there)
        call    blit_view
        jmp     status
.x:     ret

; a press at BX, CX off the canvas: on the window's frame under its title
; strip (a byte's width at the sides, the line below), the view follows
; the drag, as a hand moving the picture, until the button comes up.
; (KMW gives Paint only clicks on its windows, and on the band: so off the
; canvas and not below the frame is the frame; the title strip is KMW's)
pan:    cmp     byte [ses], 0           ; (zoomed or the whole screen: no
        je      move.x                  ;  frame)
        mov     ax, [cly1]
        inc     ax
        cmp     cx, ax
        jg      move.x
        mov     [x0], bx
        mov     [y0], cx
        mov     [lx], bx
        mov     [ly], cx
        mov     ax, [vx]
        mov     [pvx], ax
        mov     ax, [vy]
        mov     [pvy], ax
        mov     dx, cx                  ; (the driver's position: the press,
        mov     cx, bx                  ;  as stroke's)
        cmp     byte [umouse], 0
        jne     .l
        mov     ax, 4
        int     33h
.l:     mov     di, clx0                ; sample's clamp off (geom puts the
        mov     ax, 8000h               ;  canvas's limits back)
        stosw
        dec     ax
        stosw
        inc     ax
        stosw
        dec     ax
        stosw
        call    sample                  ; BX = buttons, CX = x, DX = y
        mov     [lx], cx
        mov     [ly], dx
        mov     ax, [x0]                ; the view where it was, less the drag
        sub     ax, cx                  ;  (across: to the nearest byte)
        add     ax, 4
        sar     ax, 3
        add     ax, [pvx]
        jns     .h
        xor     ax, ax
.h:     mov     si, [vx]
        mov     [vx], ax
        mov     ax, [y0]
        sub     ax, dx
        add     ax, [pvy]
        jns     .v
        xor     ax, ax
.v:     mov     di, [vy]
        mov     [vy], ax
        call    geom                    ; (kept inside the picture)
        cmp     si, [vx]
        jne     .d
        cmp     di, [vy]
        je      .u
.d:     call    blit_view
.u:     test    bl, 1
        jnz     .l
        jmp     status

; the canvas the whole screen (the picture's lines its own: pph 0)
full:   xor     ax, ax
        mov     [clx0], ax
        mov     [cly0], ax
        mov     [pph], ax
        mov     word [clx1], 639
        mov     word [cly1], 399
        ret

; CODE-F (a window): the whole screen, 640 x 400 as without windows, and
; back.  The window itself made so, in place (no title, nothing to move,
; close or size: zwin); zoomed, ses is 0, so strokes, undo and the band
; are the whole screen's (the swap and commit, band_fix), the view kept
; for the way back.  Back: closed (the screen drawn again without it, the
; title's clock too), as it was, opened again
k_zoom: cmp     byte [wopen], 0
        je      .x
        mov     cx, 7
        cmp     byte [ses], 0
        je      .out
        mov     si, win
        mov     di, wsave
        rep     movsw
        mov     si, zwin
        mov     di, win
        mov     cl, 7
        rep     movsw
        dec     byte [ses]
        call    full
        mov     si, s_hint              ; (the band, if the focus brings it
        mov     di, s_zband             ;  back: a key or a click mends it)
        call    UI_BAND
        jmp     short w_zoom.f
.out:   call    UI_WCLOSE
        mov     si, wsave
        mov     di, win
        rep     movsw
        inc     byte [ses]
        call    d_all                   ; (the strokes zoomed: C and U apart
        mov     si, win                 ;  anywhere)
        call    UI_WOPEN
        jmp     status
.x:     ret

; W_DRAW zoomed: the picture.  On Paint's own stack (its session's
; redraw, or k_zoom) UI_CLS first, then all of it, the band's lines too:
; its session's title off, so no clock drawn over the picture (the
; Executive's redraw, the base, puts it on).  From another session's
; redraw (that one in front, over it) the window only, above the band:
; the band is that one's (zwin stops there, so KMW gives clicks on the
; band to the one in front, and the Executive's questions show there).
; Not in main's wait (a question, a form, a message of Paint's waiting in
; the band) the window only too, and main draws all of it after (tz).
; (SP alone: every redraw runs on the UI's SS, a session's stack or the
; core's; the saver on a task's stack draws no windows)
w_zoom: cmp     sp, run_bss_end
        jb      .o
        cmp     sp, [sp0]
        jae     .o
        cmp     byte [in_ev], 0         ; (not in main's wait: a question of
        jne     .f                      ;  Paint's waits in the band; main
        mov     byte [tz], 1            ;  draws all of it after: tz)
        jmp     short .o
.f:     mov     byte [tz], 0
        call    UI_CLS
        jmp     blit_all
.o:     xor     ax, ax
        mov     cx, SCR_BAND_Y
        jmp     blit

; the window's title: "Paint", or "Paint: NAME.BMP" (ES = DS)
title:  mov     di, wtitle
        mov     si, s_paint
        call    UI_SBSTR
        cmp     byte [fname], 0
        je      .z
        mov     si, s_colon
        call    UI_SBSTR
        mov     si, fname               ; the name as DOS keeps it: 8 and 3
        call    base_name               ;  at most (a longer one typed in
        mov     cx, 8                   ;  Transfer is cut), in capitals, as
.n:     lodsb                           ;  the Executive's list
        or      al, al
        jz      .z
        cmp     al, '.'
        je      .d
        jcxz    .n                      ; (past 8: dropped)
        call    .up
        dec     cx
        jmp     .n
.d:     stosb
        mov     cx, 3
.e:     lodsb
        or      al, al
        jz      .z
        call    .up
        loop    .e
.z:     mov     byte [di], 0
        ret
.up:    cmp     al, 'a'                 ; AL in capitals, stored
        jb      .s
        cmp     al, 'z'
        ja      .s
        sub     al, 20h
.s:     stosb
        ret

; the core's redraw (after the saver): the picture; in Paint's own wait,
; its key, so the wait ends and the band goes
redraw: call    blit_all
        mov     byte [mend], 1          ; (the core's band goes over it next)
        cmp     byte [in_ev], 0
        je      .x
        mov     ah, 11h                 ; (only into an empty buffer: a key
        int     16h                     ;  typed ahead ends the wait itself,
        jnz     .x                      ;  and K_MEND never reaches a dialog)
        mov     ah, 5
        mov     cx, K_MEND
        int     16h
.x:     ret

; ---------------------------------------------------------------------
;  keys
; ---------------------------------------------------------------------
k_edit: mov     byte [view], 0
        ret

k_tool: mov     di, toolch              ; AL = its letter
        mov     cx, NTOOL
        repne   scasb
        sub     di, toolch + 1
        mov     [tool], di
        jmp     k_edit

k_less: cmp     byte [bsize], 1
        je      .x
        dec     byte [bsize]
.x:     ret
k_more: cmp     byte [bsize], 4
        je      k_less.x
        inc     byte [bsize]
        ret

k_help: mov     si, keys
        mov     di, s_helpt
        jmp     UI_HELP

k_undo: mov     ax, [segc]
        xchg    ax, [segu]
        mov     [segc], ax
        mov     byte [changed], 1
        ; (falls through)

; C shown: the whole screen, or the window's view
show:   cmp     byte [ses], 0
        jne     blit_view
        jmp     blit_all

; Erase (C = 0) and Invert (C = NOT U), after the swap a stroke makes
k_erase:
        xor     bx, bx
        jmp     short whole
k_inv:  mov     bx, 0FFFFh
whole:  mov     ax, [segc]
        xchg    ax, [segu]
        mov     [segc], ax
        push    ds
        push    es
        mov     es, ax
        mov     ds, [segu]
        xor     si, si
        xor     di, di
        mov     cx, PIC / 2
.l:     lodsw
        and     ax, bx
        xor     ax, bx
        stosw
        loop    .l
        pop     es
        pop     ds
        mov     byte [changed], 1
        call    d_all
        call    k_edit
        jmp     show

; D the whole picture: C and U may differ anywhere
d_all:  mov     word [dy0], 0
        mov     word [dy1], 400
        mov     word [dx0], 0
        mov     word [dx1], 80
        ret

; Transfer: save it as the name in the form (the picture's own first)
k_xfer: mov     di, t_name
        mov     si, fname
        call    UI_SBSTR
        mov     byte [di], 0
.f:     mov     si, xfer_form
        call    UI_FORM
        jc      .x
        cmp     byte [t_name], 0
        je      .f
        mov     si, t_name              ; no extension: .BMP
        call    base_name
.e:     lodsb
        cmp     al, '.'
        je      .ok
        or      al, al
        jnz     .e
        lea     di, [si-1]
        mov     si, s_bmp
        call    UI_SBSTR
        mov     byte [di], 0
.ok:    mov     si, t_name
        call    save
        jc      .x
        mov     di, fname
        mov     si, t_name
        call    UI_SBSTR
        mov     byte [di], 0
        mov     byte [changed], 0
        cmp     byte [wopen], 0         ; a window: its title the new name
        je      .x                      ;  (closed and opened again, as
        call    title                   ;  Write's; zoomed, no title: it
        cmp     byte [ses], 0           ;  shows on the way back)
        je      .x
        call    UI_WCLOSE
        mov     si, win
        call    UI_WOPEN
.x:     ret

; CODE-Q: save and quit
k_quit: mov     si, s_quitq
        call    UI_ASK
        jc      .x
        cmp     byte [changed], 0
        je      .bye
        cmp     byte [fname], 0
        jne     .sv
        call    k_xfer
        cmp     byte [changed], 0
        jne     .x
        jmp     short .bye
.sv:    mov     si, fname
        call    save
        jc      .x
.bye:   mov     byte [quit], 1
.x:     ret

; ESC: quit; with changes, only when confirmed
k_esc:  cmp     byte [changed], 0
        je      k_quit.bye
        mov     si, s_cancelq
        call    UI_ASK
        jnc     k_quit.bye
        ret

; Tab: the tools and patterns, a window; a key or a click picks
k_tools:
        mov     si, twin
        call    UI_WOPEN
.l:     call    UI_EVENT
        cmp     ax, EV_MOVED
        je      .l
        cmp     ax, EV_CLICK
        je      .click
        cmp     ax, K_ESC
        je      .x
        cmp     ax, K_TAB
        je      .x
        push    ax                      ; another key: the window goes first
        call    UI_WCLOSE               ;  (U, I, CODE-E show the whole
        pop     ax                      ;  picture: its save-under is older)
        jmp     do_key
.click: mov     ax, cx                  ; the line clicked
        sub     ax, [twin + W_Y]
        sub     ax, W_TOP
        jb      .x
        shr     ax, 4
        shr     bx, 3                   ; the byte column, from the window's
        sub     bx, [twin + W_COL]
        jb      .x
        cmp     bx, [twin + W_W]
        jae     .x
        cmp     ax, NTOOL
        jae     .pat
        mov     [tool], ax
        jmp     short .ed
.pat:   cmp     ax, 7
        jne     .x
        sub     bx, 2
        jb      .x
        xchg    ax, bx
        mov     bl, 3
        div     bl
        cmp     al, 8
        jae     .x
        mov     [patn], al
.ed:    call    k_edit
.x:     jmp     UI_WCLOSE

; the tools' window's contents (BX = the window)
t_draw: mov     al, [bsize]
        add     al, '0'
        mov     [s_szn], al
        mov     dx, [bx + W_Y]
        add     dx, W_TOP
        mov     cx, [bx + W_COL]
        add     cx, 2
        mov     si, tnames
        xor     bp, bp
.l:     xor     ah, ah
        cmp     bp, [tool]
        jne     .n
        dec     ah
.n:     push    bx
        mov     bx, cx
        call    UI_PUTS
        pop     bx
        add     dx, 16
        inc     bp
        cmp     bp, 7
        jb      .l
        push    es                      ; the patterns, the chosen one framed
        push    VSEG
        pop     es
        add     dx, 2
        shl     cx, 3
        xor     bp, bp
.p:     mov     di, bp
        shl     di, 4
        add     di, pats
        mov     ax, 0FFFFh
        call    set_op
        mov     ax, cx
        mov     bx, dx
        push    cx
        push    dx
        add     cx, 15
        add     dx, 11
        call    fillrect
        cmp     bp, [patn]
        jne     .np
        mov     di, pats
        push    ax
        mov     ax, 0FFFFh
        call    set_op
        pop     ax
        sub     ax, 2
        sub     bx, 2
        add     cx, 2
        add     dx, 2
        call    frame
.np:    pop     dx
        pop     cx
        add     cx, 24
        inc     bp
        cmp     bp, 8
        jb      .p
        pop     es
        ret

; ---------------------------------------------------------------------
;  files
; ---------------------------------------------------------------------
; read the BMP at SI into C.  CF: AX = DOS error, or 0FFFFh: not a 1-bit
; BMP of at most 640 x 400 (nothing shown, C and U as they were)
load:   call    UI_CRITERR
        mov     dx, si
        mov     ax, 3D00h
        int     21h
        jc      .ret
        xchg    bx, ax                  ; BX = the file
        mov     dx, hdr
        mov     cx, HDRN
        mov     ah, 3Fh
        int     21h
        jc      .err
        mov     si, hdr
        mov     cx, [si + 14]           ; the info header's size: 40 or
        cmp     cx, 40                  ;  more, and the two colours read
        jb      .bad
        add     cx, 14 + 8
        jc      .bad
        cmp     cx, ax
        ja      .bad
        cmp     word [si], 'BM'
        jne     .bad
        mov     ax, [si + 16]           ; (the size's high word)
        or      ax, [si + 20]           ; width < 64K
        or      ax, [si + 12]           ; pixels within 64K of the start
        or      ax, [si + 30]           ; compression 0
        or      ax, [si + 32]
        jnz     .bad
        cmp     word [si + 28], 1       ; 1 bit
        jne     .bad
        mov     ax, [si + 18]           ; the width: 1 to 640
        dec     ax
        cmp     ax, 640
        jae     .bad
        inc     ax
        mov     [pw], ax
        mov     ax, [si + 22]           ; the height: 1 to 400 lines,
        mov     dx, 80                  ;  bottom up (+80 in C a line)
        cmp     word [si + 24], 0
        je      .h
        cmp     word [si + 24], 0FFFFh
        jne     .bad
        neg     ax                      ;  or top down (-80)
        neg     dx
.h:     dec     ax
        cmp     ax, 400
        jae     .bad
        inc     ax
        mov     [ph], ax
        mov     [pstep], dx
        add     si, [si + 14]           ; the colours: the kernel's own
        add     si, 14                  ;  (dark red, orange): as saved
        mov     di, bmphdr + 54
        mov     cx, 4
        mov     byte [ours], 0
        repe    cmpsw
        je      .our
        inc     byte [ours]             ; (another program's)
.our:
        mov     ax, [pw]                ; a line in the file: whole dwords
        add     ax, 31
        and     al, 0E0h
        shr     ax, 3
        mov     [pstr], ax
        mul     word [ph]               ; (at most 32,000 bytes)
        mov     [plen], ax
        mov     dx, [hdr + 10]          ; to the pixels
        xor     cx, cx
        mov     ax, 4200h
        int     21h
        jc      .err
        mov     cx, [plen]
        push    ds
        mov     ds, [segu]
        xor     dx, dx
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .err
        cmp     ax, [plen]
        jne     .bad                    ; (cut short)
        mov     ah, 3Eh
        int     21h
        mov     byte [inv], 0
        call    place
        cmp     byte [ours], 0
        je      .ok
        push    ds                      ; another program's: the colour
        mov     ds, [segc]              ;  most of it has is dark
        xor     si, si
        mov     bx, popc
        xor     cx, cx                  ; DX:CX = bits set
        xor     dx, dx
        xor     ah, ah
.c:     lodsb
        cs      xlatb
        add     cx, ax
        adc     dx, 0
        cmp     si, PIC
        jb      .c
        pop     ds
        shl     cx, 1                   ; more than half of it lit: the
        rcl     dx, 1                   ;  other way round
        mov     si, cx
        mov     di, dx
        mov     ax, [pw]
        mul     word [ph]
        cmp     di, dx
        jb      .ok
        ja      .flip
        cmp     si, ax
        jbe     .ok
.flip:  mov     byte [inv], 0FFh
        call    place
.ok:    clc
.ret:   ret
.bad:   mov     ax, 0FFFFh
.err:   push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        stc
        ret

; U (the file's lines) into C, centred on a dark page, each byte XORed
; with [inv], the bits past the width cleared
place:  pusha
        push    es
        mov     es, [segc]
        xor     di, di
        mov     cx, PIC / 2
        xor     ax, ax
        rep     stosw
        mov     ax, [pw]
        add     ax, 7
        shr     ax, 3
        mov     bp, ax                  ; BP = bytes a line
        mov     di, 80
        sub     di, ax
        shr     di, 1                   ; DI = its left byte
        mov     ax, 400
        sub     ax, [ph]
        shr     ax, 1                   ; AX = its top line on the screen
        cmp     word [pstep], 0
        jl      .td
        add     ax, [ph]                ; bottom up: the file starts with
        dec     ax                      ;  its last line
.td:    neg     ax                      ; C: (399 - y) x 80
        add     ax, 399
        imul    ax, ax, 80
        add     di, ax
        mov     cl, [pw]                ; the last byte's mask
        and     cl, 7
        mov     dl, 0FFh
        jz      .m
        neg     cl
        add     cl, 8
        shl     dl, cl
.m:     mov     dh, [inv]
        mov     bx, [ph]
        xor     si, si
        push    ds
        mov     ds, [segu]
.l:     push    si
        push    di
        mov     cx, bp
.b:     lodsb
        xor     al, dh
        stosb
        loop    .b
        and     [es:di-1], dl
        pop     di
        pop     si
        add     si, [cs:pstr]
        add     di, [cs:pstep]
        dec     bx
        jnz     .l
        pop     ds
        pop     es
        popa
        ret

load_err:                               ; AX = what load said
        mov     di, msgb
        mov     si, s_notpic
        inc     ax
        jz      .s
        dec     ax
        mov     si, s_cantread
        call    UI_SBSTR
        call    UI_SBERR
        jmp     short .z
.s:     call    UI_SBSTR
.z:     mov     byte [di], 0
        mov     si, msgb
        jmp     UI_MSG

; save the picture to the file SI: first to NAME.$$$ beside it, then that
; takes the name (as Write does).  CF if it couldn't (and said why)
save:   mov     [sv_name], si
        mov     di, tmpname
        call    UI_SBSTR
        mov     byte [di], 0
        mov     si, tmpname
        call    base_name
.e:     mov     al, [si]
        or      al, al
        jz      .noext
        cmp     al, '.'
        je      .dot
        inc     si
        jmp     .e
.noext: mov     byte [si], '.'
.dot:   lea     di, [si+1]
        mov     si, s_dollar
        cmp     word [di], '$$'         ; (saving to a .$$$ itself: not that)
        jne     .sd
        cmp     byte [di+2], '$'
        jne     .sd
        mov     si, s_dollar1
.sd:    call    UI_SBSTR
        mov     byte [di], 0
        call    UI_CRITERR
        mov     dx, tmpname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      io_error
        xchg    bx, ax                  ; BX = the file
        mov     dx, bmphdr
        mov     cx, 62
        call    .w
        jc      .werr
        mov     ax, [segc]
        push    ds
        mov     ds, ax
        xor     dx, dx
        mov     cx, PIC
        call    .w
        pop     ds
        jc      .werr
        mov     ah, 3Eh
        int     21h
        jc      .werr2
        mov     dx, [sv_name]           ; the old one goes, the new one takes
        mov     ah, 41h                 ;  its name
        int     21h
        jnc     .ren
        cmp     ax, 2                   ; (not there: a new file)
        jne     .werr2
.ren:   mov     dx, tmpname
        mov     di, [sv_name]
        mov     ah, 56h
        int     21h
        jc      io_error
        ret
.w:     mov     ah, 40h                 ; CX bytes at DS:DX; CF: AX = error
        int     21h
        jc      .wx
        cmp     ax, cx
        mov     ax, 39                  ; (short: the disk is full)
        jne     .wf
        ret
.wf:    stc
.wx:    ret
.werr:  push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
.werr2: push    ax
        mov     dx, tmpname
        mov     ah, 41h
        int     21h
        pop     ax
        ; (falls through)

; AX = DOS error: say so (CF stays set)
io_error:
        mov     di, msgb
        mov     si, s_ioerr
        call    UI_SBSTR
        call    UI_SBERR
        mov     byte [di], 0
        mov     si, msgb
        call    UI_MSG
        stc
        ret

; SI = path -> SI = its file name (after the last \ or :)
base_name:
        push    ax
        mov     ax, si
.l:     cmp     byte [si], 0
        je      .x
        cmp     byte [si], '\'
        je      .s
        cmp     byte [si], ':'
        jne     .n
.s:     lea     ax, [si+1]
.n:     inc     si
        jmp     .l
.x:     mov     si, ax
        pop     ax
        ret

; ---------------------------------------------------------------------
;  data
; ---------------------------------------------------------------------
tools   dw t_pencil, t_brush, t_erase, t_line, t_rect, t_fill
toolch  db 'PBELRF'
bitm    db 80h, 40h, 20h, 10h, 8, 4, 2, 1
; the patterns, each twice over (a fill starts at pph, 0-7, into it)
%macro PAT 8
        db %1, %2, %3, %4, %5, %6, %7, %8, %1, %2, %3, %4, %5, %6, %7, %8
%endmacro
pats:   PAT 0FFh, 0FFh, 0FFh, 0FFh, 0FFh, 0FFh, 0FFh, 0FFh  ; 1 solid
        PAT 0DDh, 77h, 0DDh, 77h, 0DDh, 77h, 0DDh, 77h      ; 2 dark grey
        PAT 0AAh, 55h, 0AAh, 55h, 0AAh, 55h, 0AAh, 55h      ; 3 grey
        PAT 88h, 22h, 88h, 22h, 88h, 22h, 88h, 22h          ; 4 light grey
        PAT 80h, 0, 8, 0, 80h, 0, 8, 0                      ; 5 dots
        PAT 0FFh, 0, 0, 0, 0FFh, 0, 0, 0                    ; 6 lines across
        PAT 88h, 88h, 88h, 88h, 88h, 88h, 88h, 88h          ; 7 lines down
        PAT 80h, 40h, 20h, 10h, 8, 4, 2, 1                  ; 8 slant
; the kernel's Shift-PrtSc header (KCORE.INC bmp_hdr): Paint's pictures
; are its pictures
bmphdr  db 'BM'
        dd 62 + PIC, 0, 62              ; size, -, where the pixels start
        dd 40, 640, 400                 ; BITMAPINFOHEADER
        dw 1, 1                         ; 1 plane, 1 bit
        dd 0, PIC, 0, 0, 2, 0
        db 2, 8, 36, 0, 40, 120, 255, 0 ; dark red, the plasma's orange (B, G, R)

twin    dw 26, 100, 28, T_TOP + 22, s_tools, t_draw, WF_MOVE | WF_CLOSE
win     dw 2, SCR_TOP + 8, 76, SCR_BAND_Y - SCR_TOP - 8, wtitle, w_draw
        dw WF_MOVE | WF_CLOSE | WF_SIZE
zwin    dw 0, 0, 80, SCR_BAND_Y, 0, w_draw, 0   ; (zoomed: the whole screen
                                        ;  but the band, which Paint in
                                        ;  front draws over: w_zoom, main)
xfer_form:
        dw s_xfert, s_xferp, 60, 8, 1
        dw l_file, FT_TEXT + (40 << 8), t_name, 70

keys:   KEY(K_NONE,      0,       h_mouse)
        KEY(K_TAB,       k_tools, h_tab)
        KEY('P',         k_tool,  h_pbe)
        KEY('B',         k_tool,  0)
        KEY('E',         k_tool,  0)
        KEY('L',         k_tool,  h_lrf)
        KEY('R',         k_tool,  0)
        KEY('F',         k_tool,  0)
        KEY(K_NONE,      0,       h_pat)
        KEY('[',         k_less,  h_size)
        KEY(']',         k_more,  0)
kh_view equ $                           ; (a window: h_view, h_view2, h_pan)
        KEY(K_NONE,      0,       0)
        KEY(K_NONE,      0,       0)
        KEY(K_NONE,      0,       0)
        KEY(K_UP,        k_up,    0)
        KEY(K_DOWN,      k_down,  0)
        KEY(K_PGUP,      k_pgup,  0)
        KEY(K_PGDN,      k_pgdn,  0)
        KEY(K_LEFT,      k_left,  0)
        KEY(K_RIGHT,     k_right, 0)
        KEY(K_CLEFT,     k_cleft, 0)
        KEY(K_CRIGHT,    k_cright, 0)
kh_zoom equ $                           ; (a window: h_zoom)
        KEY(K_CODE_F,    k_zoom,  0)
        KEY('U',         k_undo,  h_undo)
        KEY(K_CODE_Z,    k_undo,  0)
        KEY('I',         k_inv,   h_inv)
        KEY(K_CODE_E,    k_erase, h_erase)
        KEY(K_ENTER,     k_edit,  h_enter)
kt_xfer equ $                           ; (with MULTITASK=1: K_CODE_X)
        KEY(K_CODE_T,    k_xfer,  h_xfer)
        KEY(K_CODE_Q,    k_quit,  h_quit)
        KEY(K_ESC,       k_esc,   h_esc)
        KEY(K_F1,        k_help,  0)
        KEY(K_CODE_HELP, k_help,  h_help)
        dw 0

h_mouse     db 'Mouse                    draw with the tool',0
h_tab       db 'Tab                      tools and patterns',0
h_pbe       db 'P  B  E                  pencil, brush, eraser',0
h_lrf       db 'L  R  F                  line, box, filled box',0
h_pat       db '1 to 8                   pattern',0
h_size      db '[  ]                     brush smaller, bigger',0
h_view      db 'Arrows  PgUp  PgDn       move the view',0
h_view2     db 'Ctrl-Left  Ctrl-Right    a view to the left, right',0
h_pan       db 'A drag on the frame      move the view',0
h_zoom      db 'CODE-F                   the whole screen, and back',0
h_undo      db 'U or CODE-Z              undo (again: redo)',0
h_inv       db 'I                        invert the picture',0
h_erase     db 'CODE-E                   erase the picture',0
h_enter     db 'Return                   draw on a picture shown',0
h_xfer      db 'CODE-T                   Transfer: save as',0
h_quit      db 'CODE-Q                   save and quit',0
h_esc       db 'ESC                      quit',0
h_help      db 'CODE-? or F1             this help',0
tnames      db 'P  Pencil',0
            db 'B  Brush',0
            db 'E  Eraser',0
            db 'L  Line',0
            db 'R  Box',0
            db 'F  Filled box',0
            db '[ ] Size '
s_szn       db '2',0
s_tools     db 'Tools',0
s_paint     db 'Paint',0
s_colon     db ': ',0
s_left      db 'View: from ',0
s_top       db ', ',0
s_of        db ' of 640 x 400',0
s_helpt     db 'Paint Commands',0
s_hint      db 'Paint: draw with the mouse.  Tab: tools.  CODE-?: help',0
s_zband     db 'The whole picture.  CODE-F: back to the window',0
s_nomem     db 'Paint needs 63 KB of memory',0
s_notpic    db 'Paint shows 1-bit BMP pictures up to 640 x 400',0
s_cantread  db "Can't read the picture: ",0
s_ioerr     db "Can't save: ",0
s_quitq     db 'Quit: Confirm to save and exit',0
s_cancelq   db 'Cancel: Confirm to quit without saving',0
s_xfert     db 'Transfer',0
s_xferp     db 'Transfer: Fill in form and confirm',0
l_file      db 'File',0
s_bmp       db '.BMP',0
s_dollar    db '$$$',0
s_dollar1   db '$$1',0

; the hot code on even offsets (EVEN.INC: the 286 fetches a word at a
; time; a .RUN loads on a paragraph)
%include "EVEN.INC"
        EVEN    plot, line, line.l, line.al, line.p, line.pa
        EVEN    fillrect, fillrect.row, fillrect.xor, fillrect.last, fillrect.put
        ; (fillrect.next stays odd: even, the wide fills' path through
        ;  .last would run a NOP each line; it is jcxz's only for 1 byte)
        EVEN    frame, frame.s, dot, blit.l, commit.l
        EVEN    blit_view, blit_view.l, commit_view, commit_view.l, sync_u, sync_u.l

section .bss
rowoff      resw 400                    ; line y -> its offset on the screen
popc        resb 256                    ; bits set in each byte value
hdr         resb HDRN
fname       resb 80                     ; the picture's file ("": new)
t_name      resb 80                     ; (the Transfer form's)
tmpname     resb 84
msgb        resb 128                    ; messages
sv_name     resw 1
segc        resw 1                      ; C: the picture as shown
segu        resw 1                      ; U: as it was before the last stroke
tool        resw 1
patn        resw 1
bsize       resb 1
view        resb 1                      ; showing a file: clicks don't draw
changed     resb 1
quit        resb 1
in_ev       resb 1                      ; in Paint's own UI_EVENT
mend        resb 1                      ; the core's band may be over the picture
phase       resb 1
opa         resb 1
opx         resb 1
inv         resb 1
ours        resb 1
cpat        resw 1
dotfn       resw 1
dside       resw 1
x0          resw 1
y0          resw 1
lx          resw 1
ly          resw 1
mjx         resw 1
mjy         resw 1
mnx         resw 1
mny         resw 1
clx0        resw 1                      ; the canvas: its left, right, top and
clx1        resw 1                      ;  bottom pixels (the whole screen,
cly0        resw 1                      ;  or a window's inside)
cly1        resw 1
pph         resw 1                      ; a fill's pattern phase (0-7)
cx0         resw 1                      ; a window's canvas: its first byte
cw          resw 1                      ;  column, its width in bytes, its
cy0         resw 1                      ;  first line, its lines
chh         resw 1
dy0         resw 1                      ; D, where C and U may differ (a
dy1         resw 1                      ;  window): the picture's lines dy0
dx0         resw 1                      ;  to dy1 - 1, bytes dx0 to dx1 - 1;
dx1         resw 1                      ;  empty if dy1 <= dy0
vx          resw 1                      ; the view: its left byte and top line
vy          resw 1                      ;  in the picture
pvx         resw 1                      ; (pan: the view at the press)
pvy         resw 1
wsave       resw 7                      ; (zoomed: the window as it was)
sp0         resw 1                      ; the session's stack's top
tz          resb 1                      ; (zoomed: drawn while a question waited)
ses         resb 1                      ; a window .RUN's session (MULTITASK=1)
umouse      resb 1                      ; strokes by UI_MOUSE
wopen       resb 1                      ; the window is open
wtitle      resb 24                     ; ("Paint: " and an 8.3 name at most)
stat        resb 40                     ; the band's second line
fr_x        resw 1                      ; (fillrect: the first byte, the masks)
fr_m        resw 1
mlen        resw 1                      ; (line: steps along, across)
macr        resw 1
pw          resw 1
ph          resw 1
pstr        resw 1
pstep       resw 1
plen        resw 1
run_bss_end:
