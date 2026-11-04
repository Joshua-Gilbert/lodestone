; CRASHME.COM - for the CRASHLOG test: R a jump to the BIOS's reset (as a
; wild jump would), W the same with 40:72h = 1234h (a restart asked for:
; not caught), X INT 06h's handler entered as an invalid opcode would
; enter it (a frame of flags, CS, IP, then through the vector: pcemu's
; unicorn takes any INT 6 as its own invalid instruction)
        cpu     286
        org     100h
        mov     si, 81h
.s:     lodsb
        cmp     al, ' '
        je      .s
        and     al, 0DFh
        cmp     al, 'X'
        je      .x
        cmp     al, 'W'
        jne     .r
        xor     ax, ax
        mov     ds, ax
        mov     word [472h], 1234h
.r:     cli
        jmp     0F000h:0E05Bh
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
