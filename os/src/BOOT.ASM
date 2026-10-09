; =====================================================================
;  Lodestone floppy boot sector  (BOOT.ASM)            nasm -f bin
;  Loads A:\LODE.SYS (any size up to ~500 KB, fragmented or not) to
;  1000:0000 by following its FAT12 chain, reading whole runs of
;  sectors per INT 13h call (split only at track ends and 64 KB DMA
;  boundaries), then jumps to 1000:0000 with DL = boot drive and
;  DS:SI -> this boot sector (BPB).  Works with any standard FAT12
;  floppy BPB: LODEBOOT.COM keeps the disk's own BPB and adds this code.
; =====================================================================
cpu 286
org 7C00h
KSEG    equ 1000h           ; kernel load segment
BUF     equ 07E0h           ; root dir / FAT buffer segment (0:7E00)

        jmp     short start
        nop
oem     db 'LODESTON'
bps     dw 512              ; ---- BPB (replaced by the disk's own) ----
spc     db 1
rsv     dw 1
nfat    db 2
nroot   dw 224
tots    dw 2880
media   db 0F0h
spf     dw 9
spt     dw 18
heads   dw 2
hidden  dd 0
tots32  dd 0
drive   db 0
        db 0
        db 29h
        dd 0
        db 'LODESTONE  '
        db 'FAT12   '

start:  cli
        xor     ax, ax
        mov     ds, ax
        mov     ss, ax
        mov     sp, 7C00h
        sti
        cld
        mov     [drive], dl
        mov     al, [nfat]
        cbw
        mul     word [spf]
        add     ax, [rsv]               ; AX = root directory LBA
        mov     cx, [nroot]
        add     cx, 15
        shr     cx, 4                   ; CX = root directory sectors
        mov     bx, ax
        add     bx, cx
        mov     [datalba], bx
        push    BUF
        pop     es
        call    read_run                ; root dir -> 0:7E00
        push    ds
        pop     es
        mov     di, 7E00h
        mov     dx, [nroot]
.find:  mov     si, kname
        mov     cx, 11
        push    di
        repe    cmpsb
        pop     di
        je      .found
        add     di, 32
        dec     dx
        jnz     .find
        mov     si, m_nofile
        jmp     fail
.found: mov     ax, [di+26]             ; first cluster
        mov     [clu], ax
        mov     ax, [rsv]
        mov     cx, [spf]
        push    BUF
        pop     es
        call    read_run                ; FAT -> 0:7E00
        push    KSEG
        pop     es
.chain: mov     ax, [clu]
        mov     si, ax                  ; SI = first cluster of this run
        mov     cx, 1
.ext:   call    nextclu
        cmp     ax, 0FF8h
        jae     .last
        mov     dx, si
        add     dx, cx
        cmp     ax, dx
        jne     .brk
        inc     cx
        jmp     .ext
.brk:   mov     [clu], ax
        call    rdclus
        jmp     .chain
.last:  call    rdclus
        mov     dl, [drive]
        mov     si, 7C00h
        jmp     KSEG:0000h

; read CX clusters starting at cluster SI to ES (advances ES)
rdclus: mov     ax, si
        dec     ax
        dec     ax
        mov     bl, [spc]
        xor     bh, bh
        mul     bx
        add     ax, [datalba]
        xchg    ax, cx
        mul     bx
        xchg    ax, cx                  ; CX = sectors
        ; fall through
; read CX sectors from LBA AX to ES:0000; returns ES advanced
read_run:
.next:  jcxz    .done
        push    ax
        push    cx
        xor     dx, dx
        div     word [spt]
        mov     bx, [spt]
        sub     bx, dx                  ; sectors left in this track
        inc     dx
        push    dx                      ; sector (1-based)
        xor     dx, dx
        div     word [heads]
        mov     ch, al                  ; cylinder
        mov     dh, dl                  ; head
        pop     ax
        mov     cl, al                  ; sector
        mov     ax, es                  ; sectors to next 64 KB boundary
        and     ax, 0FFFh
        neg     ax
        add     ax, 1000h
        shr     ax, 5
        cmp     bx, ax
        jbe     .b1
        mov     bx, ax
.b1:    pop     ax                      ; remaining
        push    ax
        cmp     bx, ax
        jbe     .b2
        mov     bx, ax
.b2:    mov     dl, [drive]
        mov     di, 4
.try:   mov     ax, bx
        mov     ah, 2
        push    bx
        xor     bx, bx
        int     13h
        pop     bx
        jnc     .ok
        xor     ah, ah
        int     13h
        dec     di
        jnz     .try
        mov     si, m_disk
        jmp     fail
.ok:    pop     cx
        pop     ax
        add     ax, bx
        sub     cx, bx
        shl     bx, 5
        mov     dx, es
        add     dx, bx
        mov     es, dx
        jmp     .next
.done:  ret

; AX = cluster -> AX = next cluster (FAT12 at 0:7E00)
nextclu:
        mov     bx, ax
        shr     bx, 1
        add     bx, ax
        mov     bx, [7E00h+bx]
        test    al, 1
        jz      .even
        shr     bx, 4
.even:  and     bx, 0FFFh
        mov     ax, bx
        ret

fail:   lodsb
        or      al, al
        jz      .k
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     fail
.k:     xor     ah, ah
        int     16h
        int     19h

kname   db 'LODE    SYS'
m_nofile db 'Lodestone: no LODE.SYS on this disk',13,10,0
m_disk  db 'Lodestone: disk read error',13,10,0
datalba dw 0
clu     dw 0
        times 510-($-$$) db 0
        dw 0AA55h
