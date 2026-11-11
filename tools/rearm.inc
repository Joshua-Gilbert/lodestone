; d_rearm: the resident GRIDGPIB driver back in charge at a tool's exit
; The tools reset the 7210 themselves, which clears IMR2, so the
; driver's SRQ interrupt (Lodestone's INT 60h AH=0Eh, IRQ 5) stays off
; until its next chip init: CLAUDE then woke on the 55 ms tick, and
; RCON saw the Pi's ring only at its next poll.  AH=01h runs that init
; (the chip as the driver sets it, IMR2 from its own record, IFC, REN).
; The driver is looked for as the tools find it, 'GRIDGPIB' at the entry
; + 2 of INT 60h-66h; none there, nothing done.  Called with DS = CS;
; AX, BX, CX, SI and DI not kept.
d_rearm:
        push    es
        cld
        mov     al, 60h
.f:     push    ax
        mov     ah, 35h
        int     21h
        lea     di, [bx+2]
        mov     si, d_sig
        mov     cx, 8
        repe    cmpsb
        pop     ax
        je      .got
        inc     al
        cmp     al, 67h
        jb      .f
        pop     es
        ret
.got:   mov     [d_vec], bx             ; (called as INT nn would be: no
        mov     [d_vec+2], es           ;  code patched, so nothing stale in
        mov     ah, 01h                 ;  the 286's prefetch queue)
        pushf
        call    far [d_vec]
        pop     es
        ret

d_sig   db 'GRIDGPIB'
d_vec   dd 0
