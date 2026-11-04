; CRASHME.COM - for the CRASHLOG test: R a jump to the BIOS's reset (as a
; wild jump would), W the same with 40:72h = 1234h (a restart asked for:
; not caught), X INT 06h's handler entered as an invalid opcode would
; enter it (a frame of flags, CS, IP, then through the vector: pcemu's
; unicorn takes any INT 6 as its own invalid instruction); on the 1520
; only: S a CPU shutdown (a PUSH with SP = 1: the 286 shuts down), K the
; keyboard controller's reset line (command FEh)
        cpu     286
        org     100h
        mov     si, 81h
.s:     lodsb
        cmp     al, ' '
        je      .s
        and     al, 0DFh
        cmp     al, 'X'
        je      .x
        cmp     al, 'S'
        je      .sd
        cmp     al, 'K'
        je      .kb
        cmp     al, 'W'
        jne     .r
        xor     ax, ax
        mov     ds, ax
        mov     word [472h], 1234h
.r:     cli
        jmp     0F000h:0E05Bh
.sd:    cli                             ; (no interrupt in between)
        mov     sp, 1
        push    ax                      ; (the 286 shuts down here)
        jmp     .r
.kb:    cli
.kw:    in      al, 64h                 ; (its input buffer empty)
        test    al, 2
        jnz     .kw
        mov     al, 0FEh
        out     64h, al
.kh:    hlt
        jmp     .kh
.x:     mov     ax, 1234h
        mov     bx, 5678h
        push    ds
        xor     cx, cx
        mov     ds, cx
        les     cx, [6 * 4]
        pop     ds
        mov     [vec], cx
        mov     [vec + 2], es
        pushf
        call    far [vec]
        int     20h
vec     dd      0
