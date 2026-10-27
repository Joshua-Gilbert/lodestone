; MTIRQK.COM - for test_mt.py: a key read through DOS from an interrupt's
; handler, its IRQ still in service (M9b: mt_can reads the PIC).
;   MTIRQK FILE
; Hooks IRQ 7 (INT 0Fh) and unmasks it, then waits (HLT) for its handler
; to have run: STI, a key read through DOS (AH=08h) before its EOI, as a
; handler that prompts the user would.  Then FILE gets the key (its
; character, one byte), IRQ 7's mask bit and its vector put back.  The
; test raises the IRQ itself, in front or while a task behind runs.
; nasm -f bin -o MTIRQK.COM MTIRQK.ASM
cpu 286
org 100h
        mov     si, 81h
.b:     lodsb
        cmp     al, ' '
        je      .b
        dec     si
        mov     di, fname
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        stosb
        jmp     .n
.ne:    mov     byte [di], 0
        mov     ax, 350Fh
        int     21h
        mov     [old], bx
        mov     [old+2], es
        mov     ax, 250Fh
        mov     dx, irq7
        int     21h
        in      al, 21h
        mov     [mask], al
        and     al, 7Fh
        out     21h, al
.w:     sti
        hlt
        cmp     byte [done], 0
        je      .w
        mov     ah, [mask]              ; (IRQ 7's mask bit as it was)
        and     ah, 80h
        in      al, 21h
        and     al, 7Fh
        or      al, ah
        out     21h, al
        push    ds
        lds     dx, [old]
        mov     ax, 250Fh
        int     21h
        pop     ds
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .x
        xchg    bx, ax
        mov     ah, 40h
        mov     cx, 1
        mov     dx, key
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

irq7:   sti
        push    ax
        push    ds
        push    cs
        pop     ds
        mov     ah, 8                   ; a key, through DOS, IRQ 7 in service
        int     21h
        mov     [key], al
        mov     al, 20h
        out     20h, al
        mov     byte [done], 1
        pop     ds
        pop     ax
        iret

old     dd      0
done    db      0
mask    db      0
key     db      0
fname   times   70 db 0
