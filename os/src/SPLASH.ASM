; =====================================================================
;  LODE.PIC - Lodestone's start-up picture
;  nasm -f bin -o LODE.PIC SPLASH.ASM
;
;  A terrella, the "little earth" William Gilbert describes in De
;  Magnete (1600): a lodestone turned into a sphere.  Here it turns on a
;  rod set 25 degrees from upright, shaded with rings open to one side,
;  in a dipole's lines of force.  The drawing is Lodestone's own, not
;  one of the book's woodcuts.  Under it the title, LODESTONE,
;  underlined.  Drawn from vectors in mode 40h, in one colour: the
;  screen dark, everything drawn lit.
;
;  SPLASH.INC holds the drawing as a list of paths: a pen, a first point
;  and a step to each next one.  splash/mksplash.py makes it, and draws
;  the same picture, bit for bit as this does, for the tests.
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
        push    cs
        pop     es
        cld
        mov     di, SP_ROW              ; each row's offset in the screen:
        xor     ax, ax                  ;  (y & 3) * 2000h + (y >> 2) * 80
        mov     cx, 400
.r:     stosw
        add     ax, 2000h
        jns     .k
        add     ax, 80 - 8000h
.k:     loop    .r
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
        push    0
        pop     es
        cmp     byte [es:449h], 40h
        jne     .x                      ; no 640x400: no picture (the
        push    SP_VSEG                 ;  Executive says why)
        pop     es
        call    sp_draw
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
        push    0
        pop     es
        mov     [es:470h], al
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

; every path of the drawing (SPLASH.INC): a header byte, its steps (a
; byte), its first point, then each step (dx, dy: signed bytes); a header
; of 0 ends the list.  The header: SP_PATH, always; SP_THICK, the pen
; that lights 2 x 2 pixels at each point (else 1); SP_REL, the first
; point is a step (signed bytes) from the last path's first point (else
; it is words); SP_MX and SP_MY, the mirrorings it is also drawn with,
; each pixel mirrored about the stone's centre (sp_plot); SP_TURN, only
; both, which is the path turned half round.  Every point mksplash.py
; draws is on the screen (it checks), so none is clipped.
; DS = CS, ES = the screen.
sp_draw:
        mov     si, sp_paths
.p:     lodsw                           ; its header and its steps
        or      al, al
        jz      sp_path.x
        mov     [sp_hdr], ax            ; (and sp_n, the byte after)
        mov     bl, SP_MX               ; the mirrorings are tried in steps
        test    al, SP_TURN             ;  of SP_MX: none, MX, MY, both;
        jz      .m                      ;  turned, in one step of both
        mov     bl, SP_MX + SP_MY
.m:     mov     [sp_step], bl
        test    al, SP_REL
        jz      .abs
        lodsb                           ; a step from the last first point
        cbw
        add     [sp_fx], ax
        lodsb
        cbw
        add     [sp_fy], ax
        jmp     short .got
.abs:   lodsw
        mov     [sp_fx], ax
        lodsw
        mov     [sp_fy], ax
.got:   xor     al, al                  ; first as it is
.pass:  mov     [sp_flip], al
        push    si
        call    sp_path                 ; (SI: past the path)
        mov     al, [sp_flip]
.nx:    add     al, [sp_step]           ; the next mirroring it has
        jc      .done
        mov     ah, al
        and     ah, [sp_hdr]
        cmp     ah, al
        jne     .nx
        pop     si                      ; the path again
        jmp     .pass
.done:  pop     ax
        jmp     .p

; the steps at SI from the path's first point; SI moves past them
sp_path:
        mov     cx, [sp_fx]
        mov     dx, [sp_fy]
        mov     al, [sp_n]
        cbw                             ; (mksplash.py keeps it below 128)
        xchg    ax, bp
.s:     lodsb                           ; a step
        cbw
        xchg    ax, bx
        lodsb
        cbw
        pusha
        call    sp_line
        popa
        add     cx, bx                  ; on from its end
        add     dx, ax
        dec     bp
        jnz     .s
.x:     ret

; a line from (CX, DX) on by (BX, AX), Bresenham's way: along its longer
; axis (the major), and across it (the minor) whenever the error, from
; half the major length, falls below 0.  A steep line is drawn with x and
; y swapped (sp_sw), and sp_plot swaps them back.  All registers lost.
sp_line:
        mov     si, 1                   ; SI, DI: the steps' signs
        or      bx, bx
        jns     .a
        neg     bx
        neg     si
.a:     mov     di, 1
        or      ax, ax
        jns     .b
        neg     ax
        neg     di
.b:     cmp     bx, ax
        sbb     bp, bp                  ; steep: -1
        jz      .c
        xchg    ax, bx
        xchg    cx, dx
        xchg    si, di
.c:     mov     [sp_sw], bp
        mov     [sp_min], ax
        mov     bp, bx                  ; BX: the major length; BP: points
        inc     bp
        mov     ax, bx
        shr     ax, 1                   ; AX: the error
.l:     call    sp_plot
        sub     ax, [sp_min]
        jge     .k
        add     ax, bx
        add     dx, di                  ; the minor step
.k:     add     cx, si                  ; the major step
        dec     bp
        jnz     .l
        ret

; the point (CX, DX), or (DX, CX) if sp_sw, with the path's pen: 1
; pixel, or 2 x 2 (SP_THICK), mirrored as sp_flip says (about the
; stone's centre: x is 2 CX - x, y is 2 CY - y, less 1 for the 2 x 2
; pen, whose pixels reach 1 right and 1 down).  A row's pixels are put in
; with one word: the one or two bits, from x's on.
sp_plot:
        pusha
        cmp     byte [sp_sw], 0
        je      .a
        xchg    cx, dx
.a:     mov     bx, [sp_hdr]
        and     bx, SP_THICK            ; BX: 1 for the 2 x 2 pen
        mov     al, [sp_flip]
        test    al, SP_MX
        jz      .b
        neg     cx
        add     cx, SP_CX2
        sub     cx, bx
.b:     test    al, SP_MY
        jz      .c
        neg     dx
        add     dx, SP_CY2
        sub     dx, bx
.c:     mov     di, dx
        add     di, di                  ; DI: the row's place in SP_ROW
        mov     dx, cx
        shr     dx, 3                   ; DX: x's byte in the row
        and     cl, 7
        imul    ax, bx, 4000h
        or      ah, 80h
        shr     ax, cl
        xchg    al, ah
.r:     mov     si, [SP_ROW + di]
        add     si, dx
        or      [es:si], ax
        inc     di
        inc     di
        dec     bx                      ; 2 x 2: the next row too
        jz      .r
        popa
        ret

%include "SPLASH.INC"
            align 2
pic_end:                                ; the file ends here; then scratch:
SP_ROW  equ pic_end                     ; per row: its offset in the screen
sp_hdr  equ pic_end + 800               ; the path's header
sp_n    equ pic_end + 801               ;  and its steps
sp_step equ pic_end + 802               ; the step its mirrorings are tried in
sp_flip equ pic_end + 803               ;  and the one being drawn
sp_fx   equ pic_end + 804               ; its first point, as in SPLASH.INC
sp_fy   equ pic_end + 806
sp_sw   equ pic_end + 808               ; a line: steep, x and y swapped
sp_min  equ pic_end + 810               ;  and its minor length
