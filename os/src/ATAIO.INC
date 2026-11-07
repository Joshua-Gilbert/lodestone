; =====================================================================
;  ATAIO.INC - the AT-bus hard disk at 1F0h, driven through its registers
;  as the kernel drives it (KHD.INC: IDENTIFY's geometry, INITIALIZE
;  DEVICE PARAMETERS, CHS, polled READ/WRITE/VERIFY SECTORS), for the
;  programs that use the disk when the kernel has no C: on it (FORMAT's
;  path B) or must see past it (FDISK).  The includer defines bseg: the
;  segment of the transfer buffer (64 sectors at most a command).
; =====================================================================
HD      equ 1F0h

; the drive's registers (path B).  ata_init: drive 0 there and ready,
; IDENTIFY's geometry, INITIALIZE DEVICE PARAMETERS.  CF if not
ata_init:
        mov     dx, HD + 6
        mov     al, 0A0h
        out     dx, al
        mov     dx, HD + 7
        in      al, dx
        cmp     al, 0FFh                ; (nobody on the bus)
        je      .no
        mov     ah, 40h
        call    ata_wait
        jc      .no
        mov     dx, HD + 7
        mov     al, 0ECh                ; IDENTIFY
        out     dx, al
        mov     ah, 08h
        call    ata_wait
        jc      .no
        test    al, 01h
        jnz     .no
        test    al, 08h
        jz      .no
        push    es
        mov     es, [bseg]
        xor     di, di
        mov     cx, 256
        mov     dx, HD
        rep     insw
        mov     ax, [es:3*2]            ; heads 1-16, sectors 1-63
        mov     cx, [es:6*2]
        mov     bx, [es:1*2]            ; (cylinders)
        pop     es
        mov     [hcyls], bx
        dec     ax
        cmp     ax, 15
        ja      .no
        dec     cx
        cmp     cx, 62
        ja      .no
        inc     cx
        mov     [hspt], cx
        inc     ax
        mov     [hheads], ax
        mul     cx
        mov     [hhs], ax
        mul     word [hcyls]            ; the drive's sectors
        mov     [hsize], ax
        mov     [hsize+2], dx
        mov     ax, [hheads]
        dec     ax
        or      al, 0A0h
        mov     dx, HD + 6
        out     dx, al
        mov     dx, HD + 2
        mov     al, cl
        out     dx, al
        mov     dx, HD + 7
        mov     al, 91h
        out     dx, al
        mov     ah, 0
        call    ata_wait
        jc      .no
        test    al, 01h
        jnz     .no
        clc
        ret
.no:    stc
        ret

; until the drive isn't busy and shows the bits AH (or ERR), 5 s at most.
; AL = the status.  CF: it didn't
ata_wait:
        push    bx
        push    cx
        push    dx
        push    si
        push    ds
        xor     bx, bx
        mov     ds, bx
        mov     bx, [46Ch]              ; BX = the tick last seen, SI = ticks
        pop     ds                      ;  gone by (the count goes back to 0
        xor     si, si                  ;  at midnight: never a difference)
        mov     dx, HD + 7
.l:     in      al, dx
        test    al, 80h
        jnz     .t
        test    al, 01h
        jnz     .ok
        mov     cl, al
        and     cl, ah
        cmp     cl, ah
        je      .ok
.t:     push    ds
        xor     cx, cx
        mov     ds, cx
        mov     cx, [46Ch]
        pop     ds
        cmp     cx, bx
        je      .l
        mov     bx, cx
        inc     si
        cmp     si, 91
        jb      .l
        stc
        jmp     short .x
.ok:    clc
.x:     pop     si
        pop     dx
        pop     cx
        pop     bx
        ret

; command BL (20h read, 30h write, 40h verify) for CX sectors (1-HCH) from
; the drive's sector DX:AX, data at [bseg]:0.  CF if it failed
ata_xfer:
        push    es
        push    ds
        mov     es, [bseg]
        push    cx
        div     word [hhs]              ; -> AX = cylinder, DX = the rest
        push    ax
        mov     ax, dx
        xor     dx, dx
        div     word [hspt]             ; -> AX = head, DX = sector - 1
        mov     bh, al
        inc     dl
        push    dx
        mov     ah, 40h
        call    ata_wait
        pop     dx
        pop     si                      ; SI = cylinder
        pop     cx
        jc      .x
        push    dx
        mov     dx, HD + 2
        mov     al, cl
        out     dx, al
        pop     ax                      ; the sector
        inc     dx
        out     dx, al
        inc     dx
        mov     ax, si
        out     dx, al
        inc     dx
        mov     al, ah
        out     dx, al
        inc     dx
        mov     al, bh
        or      al, 0A0h
        out     dx, al
        inc     dx
        mov     al, bl
        out     dx, al
        cmp     bl, 40h
        je      .end
        xor     di, di
        xor     si, si
.s:     push    cx
        mov     ah, 08h                 ; each sector's DRQ
        call    ata_wait
        jc      .sx
        test    al, 01h
        jnz     .sf
        test    al, 08h
        jz      .sf
        mov     cx, 256
        mov     dx, HD
        cmp     bl, 30h
        je      .o
        rep     insw
        jmp     short .sn
.o:     push    es
        pop     ds
        rep     outsw
        push    ss                      ; (DS back: a .COM's SS is its DS)
        pop     ds
.sn:    pop     cx
        loop    .s
.end:   mov     ah, 0                   ; the command's end (ERR, or write
        call    ata_wait                ;  fault)
        jc      .x
        test    al, 21h
        jz      .x
        stc
        jmp     short .x
.sf:    stc
.sx:    pop     cx
.x:     pop     ds
        pop     es
        ret


; IRQ 14 (the hard disk's) masked at the second PIC, as the kernel does
; when it drives the disk; irq_back: as it was
irq_off:
        cmp     byte [irqset], 0
        jne     .x
        in      al, 0A1h
        mov     [irq0], al
        or      al, 40h
        out     0A1h, al
        mov     byte [irqset], 1
.x:     ret

irq_back:
        cmp     byte [irqset], 0
        je      .x
        mov     byte [irqset], 0
        mov     al, [irq0]
        out     0A1h, al
.x:     ret

section .bss
hspt    resw 1                          ; IDENTIFY's geometry
hheads  resw 1
hhs     resw 1                          ; heads * sectors
hcyls   resw 1
hsize   resw 2                          ; the drive's sectors
irqset  resb 1
irq0    resb 1                          ; the second PIC's mask as it was
section .text
