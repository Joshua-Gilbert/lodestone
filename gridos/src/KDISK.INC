; =====================================================================
;  KDISK.INC - floppies A: and B: through BIOS INT 13h: mounting (BPB),
;  media changes, the FAT12 cache, sector buffers, transfers split at
;  track ends and 64 KB DMA boundaries, and critical errors (INT 24h).
; =====================================================================
; drive table entry
D_UNIT  equ 0                   ; BIOS unit
D_MNT   equ 1                   ; mounted
D_SPC   equ 2                   ; sectors per cluster
D_NFAT  equ 3
D_RSV   equ 4                   ; reserved sectors = first FAT
D_NROOT equ 6
D_TOT   equ 8
D_SPF   equ 10
D_SPT   equ 12
D_HEADS equ 14
D_ROOT  equ 16                  ; root directory LBA
D_RSEC  equ 18                  ; root directory sectors
D_DATA  equ 20                  ; LBA of cluster 2
D_NCL   equ 22                  ; highest cluster + 1
D_CWD   equ 24                  ; current directory (cluster, 0 = root)
D_SHIFT equ 26                  ; log2(sectors per cluster)
D_PRES  equ 27                  ; drive exists
D_HINT  equ 28                  ; where to look for a free cluster
D_MEDIA equ 30
D_CHK   equ 31                  ; check it is the same disk at the next access
DRVSZ   equ 32
NDRV    equ 2
CWDLEN  equ 68
MAXSPF  equ 12                  ; FAT sectors we can cache (all 12-bit values fit)
NBUF    equ 5                   ; 4 for directories and system, 1 for data
TC_SECS equ 36                  ; cylinder cache: 2 heads x up to 18 sectors
TC_PARAS equ TC_SECS * 32

section .bss
drvtab      resb DRVSZ * NDRV
cwdstr      resb CWDLEN * NDRV  ; "\DIR\SUB" per drive
cur_drv     resb 1
act         resb 1              ; drive being worked on
actp        resw 1              ; -> its drvtab entry
fat_drv     resb 1              ; whose FAT is in fatbuf (FFh: none)
fat_dirty   resb 1
            alignb 2
fat_dmask   resw 1              ; which FAT sectors changed (bit n = sector n)
; the cylinder cache: places [tc_lo, tc_hi) of the cylinder starting at
; LBA tc_cyl on drive tc_drv (place = head * sectors per track + sector,
; from 0), each at place * 512 in the block at tc_seg:0 (KMEM puts it in
; one 64 KB page).  Filled by reads that straddle a DMA boundary and by
; read-ahead; writes update what it holds.  With EMS it is two pages of
; EMS instead, in the frame only while tc_piece runs (KEMS.INC: ems_tc).
tc_seg      resw 1              ; 0: no cache
tc_cyl      resw 1
tc_drv      resb 1              ; FFh: empty
tc_lo       resb 1
tc_hi       resb 1
tc_lock     resb 1              ; 1: its memory is lent out (help window)
tc_bad_drv  resb 1              ; read-ahead failed on this drive's
            alignb 2
tc_bad_cyl  resw 1              ;   cylinder: none there
io_spec     resb 1              ; 1: this BIOS call is read-ahead
            alignb 2
io_ra       resw 1              ; read-ahead allowed past this transfer (sectors)
io_drv      resb 1
io_op       resb 1
io_err      resb 1
buf_drv     resb NBUF
            alignb 2
buf_lba     resw NBUF
buf_age     resw NBUF
buf_clock   resw 1
            alignb 16
bounce      resb 512
BPBLEN      equ 51                      ; boot sector 0Bh-3Dh
bootcopy    resb BPBLEN * NDRV
bufs        resb 512 * NBUF
fatbuf      resb 512 * MAXSPF
section .text

drv_init:
        int     11h
        xor     cx, cx
        test    al, 1
        jz      .n
        mov     cl, al
        shr     cl, 6
        inc     cl                      ; floppy drives
.n:     mov     di, drvtab
        xor     bx, bx
.d:     mov     [di+D_UNIT], bl
        cmp     bl, cl
        jae     .np
        mov     byte [di+D_PRES], 1
.np:    mov     si, bx
        imul    si, si, CWDLEN
        mov     byte [cwdstr+si], '\'
        add     di, DRVSZ
        inc     bx
        cmp     bx, NDRV
        jb      .d
        mov     byte [fat_drv], 0FFh
        mov     byte [tc_drv], 0FFh
        mov     byte [tc_bad_drv], 0FFh
        mov     byte [de_drv], 0FFh     ; (KFAT's last root sector: none)
        mov     di, buf_drv
        mov     cx, NBUF
        mov     al, 0FFh
        rep     stosb
        mov     al, [bootdrv]
        cmp     al, NDRV
        jb      .b
        xor     al, al
.b:     mov     [cur_drv], al
        cmp     byte [bootdrv], NDRV    ; booted from a floppy: we have its BPB
        jae     .x
        call    use_drive
        mov     si, bootbpb
        call    mount_bpb
.x:     ret

; AL = drive -> [act], [actp], SI = drive table entry
use_drive:
        push    ax
        mov     [act], al
        mov     ah, DRVSZ
        mul     ah
        add     ax, drvtab
        mov     si, ax
        mov     [actp], ax
        pop     ax
        ret

drv_present:                            ; AL = drive: CF if no such drive
        cmp     al, NDRV
        jae     .no
        push    si
        call    use_drive
        cmp     byte [si+D_PRES], 0
        pop     si
        je      .no
        clc
        ret
.no:    stc
        ret

; boot sector at SI (BPB at +0Bh) -> drive [actp] mounted.  CF: AX = 26
mount_bpb:
        push    bx
        push    cx
        push    dx
        push    di
        mov     di, [actp]
        cmp     word [si+0Bh], 512
        jne     .bad
        mov     al, [si+0Dh]            ; sectors per cluster: a power of 2
        or      al, al
        jz      .bad
        xor     cl, cl
.p:     shr     al, 1
        jc      .pe
        inc     cl
        jmp     .p
.pe:    or      al, al
        jnz     .bad
        mov     [di+D_SHIFT], cl
        mov     al, [si+0Dh]
        mov     [di+D_SPC], al
        mov     ax, [si+0Eh]
        or      ax, ax
        jz      .bad
        mov     [di+D_RSV], ax
        mov     al, [si+10h]
        or      al, al
        jz      .bad
        cmp     al, 2
        ja      .bad
        mov     [di+D_NFAT], al
        mov     ax, [si+11h]
        or      ax, ax
        jz      .bad
        mov     [di+D_NROOT], ax
        mov     ax, [si+13h]
        or      ax, ax
        jz      .bad
        mov     [di+D_TOT], ax
        mov     al, [si+15h]
        mov     [di+D_MEDIA], al
        mov     ax, [si+16h]
        or      ax, ax
        jz      .bad
        cmp     ax, MAXSPF
        ja      .bad
        mov     [di+D_SPF], ax
        mov     ax, [si+18h]
        or      ax, ax
        jz      .bad
        cmp     ax, 63
        ja      .bad
        mov     [di+D_SPT], ax
        mov     ax, [si+1Ah]
        or      ax, ax
        jz      .bad
        cmp     ax, 2
        ja      .bad
        mov     [di+D_HEADS], ax
        mov     al, [di+D_NFAT]
        xor     ah, ah
        mul     word [di+D_SPF]
        add     ax, [di+D_RSV]
        mov     [di+D_ROOT], ax
        mov     bx, ax
        mov     ax, [di+D_NROOT]
        add     ax, 15
        shr     ax, 4
        mov     [di+D_RSEC], ax
        add     ax, bx
        mov     [di+D_DATA], ax
        mov     bx, ax
        mov     ax, [di+D_TOT]
        sub     ax, bx
        jbe     .bad
        mov     cl, [di+D_SHIFT]
        shr     ax, cl
        add     ax, 2
        cmp     ax, 4087
        jbe     .nc
        mov     ax, 4087                ; FAT12 limit
.nc:    mov     [di+D_NCL], ax
        mov     word [di+D_HINT], 2
        mov     word [di+D_CWD], 0
        mov     byte [di+D_MNT], 1
        push    si                      ; keep the BPB to know the disk again
        push    es
        push    cs
        pop     es
        add     si, 0Bh
        mov     al, [act]
        mov     ah, BPBLEN
        mul     ah
        add     ax, bootcopy
        mov     di, ax
        mov     cx, BPBLEN
        rep     movsb
        pop     es
        pop     si
        mov     al, [act]               ; (nothing cached from before)
        call    buf_inval
        clc
        jmp     .x
.bad:   mov     ax, 26                  ; unknown media
        stc
.x:     pop     di
        pop     dx
        pop     cx
        pop     bx
        ret

; The change line says the disk may have changed: is it the same one?
; Same boot sector BPB and, if our FAT cache is this drive's and clean,
; the same first FAT sector.  CF if different (or unreadable).
same_disk:
        push    ax
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    es
        push    cs
        pop     es
        mov     bx, bounce
        mov     al, [act]
        xor     dx, dx
        mov     cx, 1
        mov     ah, 2
        call    disk_io_raw
        jc      .diff
        mov     al, [act]
        mov     ah, BPBLEN
        mul     ah
        add     ax, bootcopy
        mov     di, ax
        mov     si, bounce + 0Bh
        mov     cx, BPBLEN
        repe    cmpsb
        jne     .diff
        mov     al, [act]
        cmp     [fat_drv], al
        jne     .same                   ; (nothing cached to compare)
        cmp     byte [fat_dirty], 0     ; ours is newer than the disk's
        jne     .same
        mov     si, [actp]
        mov     dx, [si+D_RSV]
        mov     bx, bounce
        mov     cx, 1
        mov     ah, 2
        call    disk_io_raw
        jc      .diff
        mov     si, bounce
        mov     di, fatbuf
        mov     cx, 256
        repe    cmpsw
        jne     .diff
.same:  mov     al, [act]               ; whatever is cached gets read again
        call    buf_inval
        cmp     [fat_drv], al
        jne     .sm
        cmp     byte [fat_dirty], 0
        jne     .sm
        mov     byte [fat_drv], 0FFh
.sm:    clc
        jmp     .x
.diff:  stc
.x:     pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

; get drive AL ready: present, media change noticed, mounted.  Sets
; [act]/[actp], SI = entry.  CF: AX = error.
drv_ready:
        cmp     al, NDRV
        jae     .inv
        call    use_drive
        cmp     byte [si+D_PRES], 0
        je      .inv
        push    ax
        push    dx
        cmp     byte [si+D_CHK], 0      ; (after INT 21h 0Dh: a program may
        mov     byte [si+D_CHK], 0      ;  have used the disk, and its change
        jne     .chg                    ;  line, behind our back)
        mov     dl, [si+D_UNIT]
        mov     ah, 16h                 ; disk change line
        int     13h
        jnc     .same
        cmp     ah, 6
        jne     .same
.chg:   cmp     byte [si+D_MNT], 0
        je      .same
        mov     al, [act]               ; sectors cached from it are suspect
        call    buf_inval               ; (and same_disk must see the disk)
        call    same_disk               ; (drives without a change line
        jnc     .same                   ; report a change every time)
        mov     al, [act]
        call    unmount
.same:  pop     dx
        pop     ax
        cmp     byte [si+D_MNT], 0
        jne     .ok
        push    bx
        push    cx
        push    dx
        push    es
        push    cs
        pop     es
        mov     bx, bounce
        mov     al, [act]
        xor     dx, dx
        mov     cx, 1
        mov     ah, 2
        call    disk_io_raw             ; no BPB yet: use a 9-sector guess
        pop     es
        pop     dx
        pop     cx
        pop     bx
        jc      .x
        push    si
        mov     si, bounce
        call    mount_bpb
        pop     si
        jc      .x
.ok:    clc
.x:     ret
.inv:   mov     ax, 15                  ; invalid drive
        stc
        ret

; drive AL: forget everything about the disk in it
unmount:
        push    ax
        push    bx
        push    si
        call    use_drive
        mov     byte [si+D_MNT], 0
        mov     word [si+D_CWD], 0
        mov     bl, al
        xor     bh, bh
        imul    bx, bx, CWDLEN
        mov     word [cwdstr+bx], '\'
        cmp     [fat_drv], al
        jne     .b
        mov     byte [fat_drv], 0FFh
        mov     byte [fat_dirty], 0
        mov     word [fat_dmask], 0
.b:     call    buf_inval
        pop     si
        pop     bx
        pop     ax
        ret

; INT 21h 0Dh: write back and forget the cached FAT and sectors (the
; next access reads the disk again; mounts and directories stay)
; CF if changed FAT sectors couldn't be written; everything is forgotten
; either way.  The FAT is only written if its disk is still in the drive.
disk_reset:
        mov     al, [fat_drv]
        cmp     al, 0FFh
        je      .w
        cmp     byte [fat_dirty], 0
        je      .w
        call    drv_ready               ; (a different disk: its FAT is
        jnc     .w                      ;  dropped, not written; and if
        jmp     short .f                ;  we can't tell, not written)
.w:     call    fat_flush
.f:     pushf
        mov     byte [fat_drv], 0FFh
        mov     byte [fat_dirty], 0
        mov     word [fat_dmask], 0
        mov     al, 0
        call    buf_inval
        mov     al, 1
        call    buf_inval
        mov     byte [drvtab + D_CHK], 1
        mov     byte [drvtab + DRVSZ + D_CHK], 1
        popf
        ret

; ---------------------------------------------------------------------
;  FAT cache (one drive at a time) - [act] must be the drive
; ---------------------------------------------------------------------
fat_load:
        mov     al, [act]
        cmp     [fat_drv], al
        je      .ok
        call    fat_flush
        jc      .x
        push    bx
        push    cx
        push    dx
        push    si
        push    es
        mov     byte [fat_drv], 0FFh    ; nobody's while it loads
        mov     al, [act]
        call    use_drive
        mov     dx, [si+D_RSV]
        mov     cx, [si+D_SPF]
        push    cs
        pop     es
        mov     bx, fatbuf
        mov     ah, 2
        call    disk_io
        pop     es
        pop     si
        pop     dx
        pop     cx
        pop     bx
        jc      .x
        mov     al, [act]
        mov     [fat_drv], al
.ok:    clc
.x:     ret

; write the FAT sectors that changed (runs of them) to every FAT copy
fat_flush:
        cmp     byte [fat_dirty], 0
        je      .ok
        cmp     byte [fat_drv], 0FFh
        je      .ok
        pusha
        push    es
        push    cs
        pop     es
        mov     al, [act]
        push    ax
        mov     al, [fat_drv]
        call    use_drive
        mov     dx, [si+D_RSV]          ; this copy's first sector
        mov     cl, [si+D_NFAT]
        xor     ch, ch
.c:     push    cx
        xor     bx, bx                  ; sector of the FAT
.k:     cmp     bx, [si+D_SPF]
        jae     .cd
        call    .dirty
        jnz     .run
        inc     bx
        jmp     .k
.run:   mov     di, bx                  ; [BX, DI) changed
.r:     inc     di
        cmp     di, [si+D_SPF]
        jae     .w
        xchg    bx, di
        call    .dirty
        xchg    bx, di
        jnz     .r
.w:     push    dx
        push    bx
        mov     cx, di
        sub     cx, bx
        add     dx, bx
        shl     bx, 9
        add     bx, fatbuf
        mov     al, [fat_drv]
        mov     ah, 3
        call    disk_io
        pop     bx
        pop     dx
        jc      .e
        mov     bx, di
        jmp     .k
.cd:    pop     cx
        add     dx, [si+D_SPF]
        loop    .c
        mov     byte [fat_dirty], 0
        mov     word [fat_dmask], 0
        pop     ax
        call    use_drive
        pop     es
        popa
.ok:    clc
        ret
.e:     mov     [io_err], al
        pop     cx
        pop     ax
        call    use_drive
        pop     es
        popa
        mov     al, [io_err]
        xor     ah, ah
        stc
        ret
; ZF clear if FAT sector BX changed
.dirty: push    ax
        push    cx
        mov     cl, bl
        mov     ax, 1
        shl     ax, cl
        test    [fat_dmask], ax
        pop     cx
        pop     ax
        ret

; AX = cluster -> AX = its FAT entry
fat_get:
        push    bx
        mov     bx, ax
        shr     bx, 1
        add     bx, ax
        test    al, 1
        mov     ax, [fatbuf+bx]
        jz      .e
        shr     ax, 4
.e:     and     ax, 0FFFh
        pop     bx
        ret

; FAT entry AX := DX
fat_set:
        push    ax
        push    bx
        push    dx
        mov     bx, ax
        shr     bx, 1
        add     bx, ax
        and     dx, 0FFFh
        test    al, 1
        jz      .e
        shl     dx, 4
        and     word [fatbuf+bx], 000Fh
        jmp     .s
.e:     and     word [fatbuf+bx], 0F000h
.s:     or      [fatbuf+bx], dx
        mov     byte [fat_dirty], 1
        push    cx                      ; its sector(s) changed: bytes BX, BX+1
        mov     cl, bh
        shr     cl, 1
        mov     dx, 1
        shl     dx, cl
        or      [fat_dmask], dx
        inc     bx
        mov     cl, bh
        shr     cl, 1
        mov     dx, 1
        shl     dx, cl
        or      [fat_dmask], dx
        pop     cx
        pop     dx
        pop     bx
        pop     ax
        ret

; cluster AX -> LBA AX of its first sector
clu2lba:
        push    cx
        push    si
        mov     si, [actp]
        sub     ax, 2
        mov     cl, [si+D_SHIFT]
        shl     ax, cl
        add     ax, [si+D_DATA]
        pop     si
        pop     cx
        ret

; new cluster, marked as the end of a chain and linked after DX (0: none).
; -> AX.  CF: AX = 39 (disk full)
clu_alloc:
        push    bx
        push    cx
        push    si
        mov     si, [actp]
        mov     bx, [si+D_HINT]
        mov     cx, [si+D_NCL]
        sub     cx, 2
.l:     cmp     bx, [si+D_NCL]
        jb      .t
        mov     bx, 2
.t:     mov     ax, bx
        call    fat_get
        or      ax, ax
        jz      .got
        inc     bx
        loop    .l
        mov     ax, 39
        stc
        jmp     .x
.got:   mov     ax, bx
        push    dx
        mov     dx, 0FFFh
        call    fat_set
        pop     dx
        or      dx, dx
        jz      .nl
        xchg    ax, dx
        call    fat_set                 ; prev -> new
        xchg    ax, dx
.nl:    inc     bx
        mov     [si+D_HINT], bx
        clc
.x:     pop     si
        pop     cx
        pop     bx
        ret

; how many free clusters in a row from cluster AX, at most CX -> CX.
; (A tight loop: it runs between two disk writes.)
free_run:
        push    ax
        push    bx
        push    dx
        push    si
        mov     si, [actp]
        mov     dx, [si+D_NCL]
        sub     dx, ax                  ; clusters left on the disk
        jbe     .none
        cmp     cx, dx
        jbe     .c
        mov     cx, dx
.c:     jcxz    .none
        mov     dx, cx                  ; wanted
        mov     bx, ax
        shr     bx, 1
        add     bx, ax
        add     bx, fatbuf              ; entry AX
        test    al, 1
        jnz     .odd
.even:  test    word [bx], 0FFFh
        jnz     .stop
        dec     cx
        jz      .stop
        inc     bx                      ; the odd one: same 3 bytes
.odd:   test    word [bx], 0FFF0h
        jnz     .stop
        add     bx, 2                   ; the next even one
        dec     cx
        jnz     .even
.stop:  sub     dx, cx                  ; free ones found
        mov     cx, dx
        jmp     .x
.none:  xor     cx, cx
.x:     pop     si
        pop     dx
        pop     bx
        pop     ax
        ret

; free the chain starting at AX
free_chain:
        push    ax
        push    bx
        push    dx
.l:     cmp     ax, 2
        jb      .x
        cmp     ax, 0FF0h
        jae     .x
        mov     bx, ax
        call    fat_get
        xchg    ax, bx
        xor     dx, dx
        call    fat_set
        mov     ax, bx
        jmp     .l
.x:     pop     dx
        pop     bx
        pop     ax
        ret

; ---------------------------------------------------------------------
;  sector buffers (write-through)
; ---------------------------------------------------------------------
; AL = drive, DX = LBA -> SI = buffer with that sector.  CF: AX = error
; buf_get is for directory and system sectors: a miss takes the oldest of
; the first NBUF-1 buffers.  buf_getd is for file data: a miss takes the
; last buffer, so reading or writing part-sectors of a file never pushes
; directory sectors out (a search then finds the whole of a short root
; still buffered).  Either finds a sector in any buffer.
buf_getd:
        push    bx
        push    cx
        mov     cx, 1
        jmp     short buf_get.s
buf_get:
        push    bx
        push    cx
        xor     cx, cx
.s:     xor     bx, bx
.f:     cmp     [buf_drv+bx], al
        jne     .n
        push    bx
        shl     bx, 1
        cmp     [buf_lba+bx], dx
        pop     bx
        je      .hit
.n:     inc     bx
        cmp     bx, NBUF
        jb      .f
        ; miss: file data takes the data buffer; anything else the oldest
        ; (or an empty one) of the others
        mov     bx, NBUF - 1
        jcxz    .lru
        jmp     short .take
.lru:   xor     bx, bx
        mov     cx, 1
.o:     cmp     cx, NBUF - 1
        jae     .take
        push    ax
        mov     si, cx
        shl     si, 1
        mov     ax, [buf_age+si]
        mov     si, bx
        shl     si, 1
        cmp     ax, [buf_age+si]
        pop     ax
        jae     .on
        mov     bx, cx
.on:    inc     cx
        jmp     .o
.take:  mov     byte [buf_drv+bx], 0FFh
        push    ax
        push    dx
        push    es
        push    bx
        mov     si, bx
        shl     si, 9
        add     si, bufs
        push    cs
        pop     es
        mov     bx, si
        mov     cx, 1
        mov     ah, 2
        call    disk_io
        pop     bx
        pop     es
        pop     dx
        jc      .err
        pop     ax
        mov     [buf_drv+bx], al
        push    bx
        shl     bx, 1
        mov     [buf_lba+bx], dx
        pop     bx
.hit:   inc     word [buf_clock]
        mov     cx, [buf_clock]
        push    bx
        shl     bx, 1
        mov     [buf_age+bx], cx
        pop     bx
        mov     si, bx
        shl     si, 9
        add     si, bufs
        clc
        pop     cx
        pop     bx
        ret
.err:   add     sp, 2
        pop     cx
        pop     bx
        stc
        ret

; is sector DX of drive AL in a buffer?  ZF if so.  Keeps all registers
buf_has:
        push    bx
        push    si
        xor     bx, bx
.l:     cmp     [buf_drv+bx], al
        jne     .n
        mov     si, bx
        shl     si, 1
        cmp     [buf_lba+si], dx
        je      .x
.n:     inc     bx
        cmp     bx, NBUF
        jb      .l
        or      sp, sp                  ; (NZ)
.x:     pop     si
        pop     bx
        ret

; write the buffer holding address SI back to its sector.  CF: AX = error
; (and the buffer forgotten: it holds what the disk doesn't, and a later
; write of the sector would carry it there, e.g. a DELETE refused by a
; write-protected disk done after all once the tab is off)
buf_put:
        push    bx
        push    cx
        push    dx
        push    es
        mov     bx, si
        sub     bx, bufs
        shr     bx, 9
        mov     al, [buf_drv+bx]
        push    bx
        shl     bx, 1
        mov     dx, [buf_lba+bx]
        pop     bx
        push    bx                      ; (the buffer's number)
        shl     bx, 9
        add     bx, bufs                ; the buffer's start
        push    cs
        pop     es
        mov     cx, 1
        mov     ah, 3
        call    disk_io
        pop     bx
        jnc     .ok
        mov     byte [buf_drv+bx], 0FFh ; (CF stays set)
.ok:    pop     es
        pop     dx
        pop     cx
        pop     bx
        ret

; forget drive AL's buffers (and the track cache if it is that drive's)
buf_inval:
        cmp     [tc_drv], al
        jne     .tc
        mov     byte [tc_drv], 0FFh
.tc:    push    bx
        xor     bx, bx
.l:     cmp     [buf_drv+bx], al
        jne     .n
        mov     byte [buf_drv+bx], 0FFh
.n:     inc     bx
        cmp     bx, NBUF
        jb      .l
        pop     bx
        ret

; forget drive AL's buffers for LBAs DX .. DX+CX-1
buf_inval_range:
        push    bx
        push    si
        xor     bx, bx
.l:     cmp     [buf_drv+bx], al
        jne     .n
        mov     si, bx
        shl     si, 1
        mov     si, [buf_lba+si]
        sub     si, dx
        cmp     si, cx
        jae     .n
        mov     byte [buf_drv+bx], 0FFh
.n:     inc     bx
        cmp     bx, NBUF
        jb      .l
        pop     si
        pop     bx
        ret

; ---------------------------------------------------------------------
;  transfers.  AL = drive, AH = 2 read / 3 write, DX = LBA, CX = sectors,
;  ES:BX = memory.  Split at track ends and 64 KB DMA boundaries; a
;  sector straddling a boundary goes through the bounce buffer.
;  Errors go to INT 24h; CF: AX = DOS error code.
; ---------------------------------------------------------------------
disk_io:
        mov     byte [io_crit], 1
        jmp     dio
disk_io_raw:                            ; the same without INT 24h (mounting)
        mov     byte [io_crit], 0
dio:    push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    es
        mov     [io_drv], al
        mov     [io_op], ah
        push    ax
        call    use_drive_keep
        pop     ax
.loop:  or      cx, cx
        jnz     .more
        jmp     .ok
.more:  mov     [io_lba], dx
        mov     [io_left], cx
        ; CHS
        mov     ax, dx
        xor     dx, dx
        mov     di, [io_geo_spt]
        div     di                      ; AX = track, DX = sector - 1
        mov     si, di
        sub     si, dx                  ; sectors left in the track
        mov     [io_s0], dl
        inc     dl
        mov     [io_sec], dl
        xor     dx, dx
        div     word [io_geo_heads]     ; AX = cylinder, DX = head
        mov     [io_cyl], ax
        mov     [io_head], dl
%ifndef NOTC
        mov     al, dl                  ; place in the cylinder
        mul     byte [io_geo_spt]
        add     al, [io_s0]
        mov     [io_ci], al
        xor     ah, ah
        mov     di, [io_lba]
        sub     di, ax
        mov     [io_cl], di             ; the cylinder's first LBA
        mov     ax, si                  ; this track's piece
        cmp     ax, cx
        jbe     .pc
        mov     ax, cx
.pc:    mov     [io_pc], ax
.tcp:   call    tc_piece                ; through the track cache?  (KEMS.INC:
                                        ;  ems_tc, the cache's pages in first)
        jc      .err
        or      al, al
        jnz     .adv
%endif
        ; room before the next 64 KB boundary
        mov     ax, es
        shl     ax, 4
        add     ax, bx
        neg     ax
        jz      .r128
        shr     ax, 9
        jmp     .room
.r128:  mov     ax, 128
.room:  cmp     si, ax
        jbe     .s1
        mov     si, ax
.s1:    cmp     si, cx
        jbe     .s2
        mov     si, cx
.s2:    mov     [io_n], si
        or      si, si
        jnz     .direct
        ; bounce one sector
        mov     word [io_n], 1
        cmp     byte [io_op], 3
        jne     .bread
        push    ds
        push    es
        push    cx
        mov     si, bx
        push    es
        pop     ds
        push    cs
        pop     es
        mov     di, bounce
        mov     cx, 256
        rep     movsw
        pop     cx
        pop     es
        pop     ds
.bread: push    es
        push    bx
        push    cs
        pop     es
        mov     bx, bounce
        call    .bios
        pop     bx
        pop     es
        jc      .err
        cmp     byte [io_op], 2
        jne     .adv
        push    cx
        mov     di, bx
        mov     si, bounce
        mov     cx, 256
        rep     movsw
        pop     cx
        jmp     .adv
.direct:
        call    .bios
        jc      .err
.adv:   mov     ax, [io_n]
        mov     dx, [io_lba]
        add     dx, ax
        mov     cx, [io_left]
        sub     cx, ax
        shl     ax, 5                   ; paragraphs
        mov     si, es
        add     si, ax
        mov     es, si
        jmp     .loop
.ok:    clc
.x:     mov     word [io_ra], 0         ; (read-ahead is per transfer)
        pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        ret
.err:   mov     ah, 0
        stc
        jmp     .x

; one INT 13h call for [io_n] sectors at ES:BX, with retries and INT 24h.
; [io_ign] = 1 if INT 24h said to ignore an error (the data is not good)
.bios:  mov     byte [io_ign], 0
.bios1: mov     byte [io_try], 3
        cmp     byte [io_spec], 0       ; (read-ahead gets one try)
        je      .again
        mov     byte [io_try], 1
.again: mov     ax, [io_cyl]
        mov     ch, al
        mov     cl, ah
        shl     cl, 6
        or      cl, [io_sec]
        mov     dh, [io_head]
        mov     dl, [io_unit]
        mov     al, [io_n]
        mov     ah, [io_op]
        push    bx
        int     13h
        pop     bx
        jnc     .bok
        mov     [io_bios], ah
        xor     ah, ah
        mov     dl, [io_unit]
        int     13h                     ; reset, then try again
        dec     byte [io_try]
        jnz     .again
        ; A read of several sectors that keeps failing: one sector at a
        ; time before giving up.  A weak drive head often can't get a whole
        ; track through without a CRC error, yet reads every sector of it
        ; on its own (the 1520's side 0, inner tracks).  Not for
        ; read-ahead, which is only a guess.
        cmp     byte [io_op], 2
        jne     .bcrit
        cmp     word [io_n], 1
        jbe     .bcrit
        cmp     byte [io_spec], 0
        jne     .bcrit
        call    .bysec
        jnc     .bok
.bcrit: cmp     byte [io_crit], 0
        je      .bfail
        call    crit_disk               ; AL = action
        cmp     al, 1
        je      .bios
        or      al, al
        jz      .bign                   ; ignore
.bfail: call    .wfail
        mov     al, [io_bios]
        call    bios2dos
        stc
        ret
.bign:  mov     byte [io_ign], 1
        call    .wfail
.bok:   clc
        ret
; the [io_n] sectors at ES:BX read one by one, 3 tries each.  CF if one
; can't be read ([io_bios] = its error).  Keeps BX, ES
.bysec: push    es
        mov     byte [io_bi], 0
.bs:    mov     byte [io_try], 3
.bs1:   mov     ax, [io_cyl]
        mov     ch, al
        mov     cl, ah
        shl     cl, 6
        mov     al, [io_sec]
        add     al, [io_bi]
        or      cl, al
        mov     dh, [io_head]
        mov     dl, [io_unit]
        mov     ax, 0201h
        push    bx
        int     13h
        pop     bx
        jnc     .bsok
        mov     [io_bios], ah
        xor     ah, ah
        mov     dl, [io_unit]
        int     13h
        dec     byte [io_try]
        jnz     .bs1
        pop     es
        stc
        ret
.bsok:  mov     ax, es                  ; the next sector's place (the
        add     ax, 20h                 ;  piece never crosses 64 KB)
        mov     es, ax
        inc     byte [io_bi]
        mov     al, [io_bi]
        cmp     al, [io_n]
        jb      .bs
        pop     es
        clc
        ret
; a write that didn't happen: what the cache was given for it is wrong
.wfail: cmp     byte [io_op], 3
        jne     .wx
        mov     byte [tc_drv], 0FFh
.wx:    ret

%ifndef NOTC
; ---------------------------------------------------------------------
;  the cylinder cache.  Called by dio for each piece of a transfer: the
;  sectors [io_s0, io_s0 + io_pc) of one track, which are [io_ci, ...) of
;  the cylinder starting at LBA io_cl; memory ES:BX.
;  -> AL = 1 done here ([io_n] = sectors done), AL = 0 not (dio goes to
;  the disk directly).  CF: AL = error.  Keeps BX, CX, SI, ES.
;  Reads come from the cache when it has them.  Otherwise they are read
;  into it when the piece straddles a DMA boundary (one BIOS call, not
;  three), or when the caller allows read-ahead ([io_ra]) and this is the
;  transfer's last piece: then the rest of the track comes too and, on
;  head 0, the other head's track, so a file read in order costs one
;  pass over each cylinder whatever size its reads are.  Read-ahead is a
;  guess: if it fails, just the piece is read (with the usual INT 24h).
;  Writes drop a cached copy of the cylinder.
; ---------------------------------------------------------------------
tc_piece:
        cmp     word [tc_seg], 0
        je      .no
        cmp     byte [tc_lock], 0
        jne     .no
        cmp     word [io_geo_cyl], TC_SECS
        ja      .no
        push    cx
        cmp     byte [io_op], 2
        jne     .wr
        ; --- read: cached?
        call    tc_mine
        jne     .miss
        mov     al, [io_ci]
        cmp     al, [tc_lo]
        jb      .miss
        mov     ah, [tc_hi]
        sub     ah, al
        jbe     .miss
        mov     al, ah                  ; cached from here on
        xor     ah, ah
        cmp     ax, [io_pc]
        jbe     .h1
        mov     ax, [io_pc]
.h1:    mov     [io_n], ax
        call    tc_out
        jmp     .done
.miss:  mov     word [io_m2], 0
        mov     ax, [io_pc]
        mov     cx, [io_ra]
        jcxz    .nora
        cmp     ax, [io_left]           ; (the last piece only)
        jne     .nora
        push    ax                      ; not where read-ahead failed before
        mov     al, [io_drv]
        cmp     al, [tc_bad_drv]
        jne     .rok
        mov     ax, [io_cl]
        cmp     ax, [tc_bad_cyl]
.rok:   pop     ax
        je      .nora
        add     cx, ax                  ; the piece and what may follow it
        mov     ax, [io_geo_spt]
        sub     al, [io_s0]             ; to the end of this track
        cmp     cx, ax
        ja      .two
        mov     ax, cx
        jmp     .ra
.two:   cmp     byte [io_head], 0       ; on to head 1?
        jne     .ra
        cmp     word [io_geo_heads], 2
        jne     .ra
        sub     cx, ax
        cmp     cx, [io_geo_spt]
        jbe     .t2
        mov     cx, [io_geo_spt]
.t2:    mov     [io_m2], cx
.ra:    cmp     ax, [io_pc]
        ja      .spec
        cmp     word [io_m2], 0
        jne     .spec
.nora:  mov     word [io_m2], 0
        call    tc_room                 ; straddles a DMA boundary?
        cmp     ax, [io_pc]
        jae     .not
        mov     ax, [io_pc]
        call    tc_fill
        jc      .err
        jmp     .out
.spec:  mov     cl, [io_crit]           ; read-ahead: one try, no INT 24h
        mov     byte [io_crit], 0
        mov     byte [io_spec], 1
        call    tc_fill
        mov     [io_crit], cl
        mov     byte [io_spec], 0
        jnc     .out
        mov     al, [io_drv]            ; failed: no more guessing on this
        mov     [tc_bad_drv], al        ; cylinder; just the piece, then
        mov     ax, [io_cl]
        mov     [tc_bad_cyl], ax
        jmp     .nora
.out:   mov     ax, [io_pc]
        mov     [io_n], ax
        call    tc_out
        jmp     .done
        ; --- write: what the cache holds of these sectors gets the new
        ; data too (a failed write empties the cache: dio.bios).  Only the
        ; cached part is copied, so a long write elsewhere costs nothing.
.wr:    call    tc_mine
        jne     .not
        mov     al, [io_ci]             ; [AL, AH) = cached part of the piece
        mov     ah, al
        add     ah, [io_pc]
        cmp     al, [tc_lo]
        jae     .w1
        mov     al, [tc_lo]
.w1:    cmp     ah, [tc_hi]
        jbe     .w2
        mov     ah, [tc_hi]
.w2:    cmp     al, ah
        jae     .not
        call    tc_upd
        jmp     .not
.done:  pop     cx
        mov     al, 1
        clc
        ret
.not:   pop     cx
.no:    xor     al, al
        clc
        ret
.err:   pop     cx
        stc
        ret

; read AX sectors from io_ci into the cache, then [io_m2] from the start
; of head 1 after them (that part only if it can: it is never needed).
; CF: AL = error
tc_fill:
        push    cx
        mov     cl, [tc_drv]            ; (what it held, to merge with)
        mov     byte [tc_drv], 0FFh
        mov     [io_n], ax
        call    tc_bios
        jc      .x
        cmp     byte [io_ign], 0
        jne     .ok                     ; (bad data: not kept)
        mov     ax, [io_n]
        call    tc_keep
        mov     cx, [io_m2]
        jcxz    .ok
        mov     al, [io_crit]
        push    ax
        mov     al, [io_ci]
        push    ax
        mov     byte [io_crit], 0
        mov     byte [io_head], 1
        mov     byte [io_sec], 1
        mov     al, [io_geo_spt]
        mov     [io_ci], al
        cmp     [tc_hi], al             ; head 1's places are about to be
        jbe     .h1                     ; overwritten: kept only once read
        mov     [tc_hi], al
.h1:    mov     [io_n], cx
        mov     cl, [tc_drv]
        call    tc_bios
        jc      .h0
        mov     ax, [io_n]
        call    tc_keep
.h0:    pop     ax
        mov     [io_ci], al
        pop     ax
        mov     [io_crit], al
        mov     byte [io_head], 0
        mov     al, [io_s0]
        inc     al
        mov     [io_sec], al
.ok:    clc
.x:     pop     cx
        ret

; places [AL, AH) of the cache := the same sectors of the piece at ES:BX
; (the piece starts at place io_ci)
tc_upd: push    cx
        push    dx
        push    si
        push    di
        push    ds
        push    es
        mov     ch, ah
        sub     ch, al
        xor     cl, cl                  ; words
        mov     dh, al
        sub     dh, [io_ci]
        shl     dh, 1
        xor     dl, dl                  ; (place - io_ci) * 512
        mov     si, bx
        add     si, dx
        mov     ah, al
        shl     ah, 1
        xor     al, al
        mov     di, ax                  ; place * 512
        push    es
        mov     es, [tc_seg]
        pop     ds
        cld
        rep     movsw
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        ret

; ZF if the cache holds (part of) this cylinder of this drive
tc_mine:
        push    ax
        mov     al, [io_drv]
        cmp     al, [tc_drv]
        jne     .x
        mov     ax, [io_cl]
        cmp     ax, [tc_cyl]
.x:     pop     ax
        ret

; AX = whole sectors from ES:BX to the next 64 KB boundary
tc_room:
        mov     ax, es
        shl     ax, 4
        add     ax, bx
        neg     ax
        jz      .all
        shr     ax, 9
        ret
.all:   mov     ax, 128
        ret

; [io_n] sectors between the cache (from place io_ci) and the disk.
; Keeps all but AX
tc_bios:
        push    bx
        push    cx
        push    dx
        push    es
        mov     es, [tc_seg]
        mov     bh, [io_ci]
        shl     bh, 1
        xor     bl, bl
        call    dio.bios
        pop     es
        pop     dx
        pop     cx
        pop     bx
        ret

; the cache now holds AX sectors from place io_ci of this cylinder.
; CL = the drive it held before: if that was this cylinder too and the
; two runs touch, it keeps both
tc_keep:
        push    ax
        push    dx
        mov     dl, [io_ci]
        mov     dh, dl
        add     dh, al                  ; [DL, DH)
        cmp     cl, [io_drv]
        jne     .new
        mov     ax, [io_cl]
        cmp     ax, [tc_cyl]
        jne     .new
        cmp     dl, [tc_hi]
        ja      .new
        cmp     dh, [tc_lo]
        jb      .new
        cmp     dl, [tc_lo]
        jbe     .l
        mov     dl, [tc_lo]
.l:     cmp     dh, [tc_hi]
        jae     .new
        mov     dh, [tc_hi]
.new:   mov     [tc_lo], dl
        mov     [tc_hi], dh
        mov     ax, [io_cl]
        mov     [tc_cyl], ax
        mov     al, [io_drv]
        mov     [tc_drv], al
        pop     dx
        pop     ax
        ret

; copy [io_n] sectors: cache (place io_ci) -> ES:BX
tc_out: push    cx
        push    si
        push    di
        push    ds
        mov     di, bx
        mov     ch, [io_n]
        xor     cl, cl                  ; words
        mov     ah, [io_ci]
        shl     ah, 1
        xor     al, al
        mov     si, ax
        mov     ds, [tc_seg]
        cld
        rep     movsw
        pop     ds
        pop     di
        pop     si
        pop     cx
        ret
%endif

section .bss
io_crit     resb 1
io_ign      resb 1
io_s0       resb 1              ; sector in the track (0-based)
io_ci       resb 1              ; place in the cylinder (0-based)
            alignb 2
io_cl       resw 1              ; the cylinder's first LBA
io_pc       resw 1              ; sectors of this piece
io_m2       resw 1              ; read-ahead on head 1
io_geo_cyl  resw 1              ; sectors per cylinder
io_try      resb 1
io_bi       resb 1              ; sector being read on its own (dio.bysec)
io_bios     resb 1
io_sec      resb 1
io_head     resb 1
io_unit     resb 1
            alignb 2
io_cyl      resw 1
io_lba      resw 1
io_left     resw 1
io_n        resw 1
io_geo_spt  resw 1
io_geo_heads resw 1
section .text

; geometry and unit of drive [io_drv] (before mounting: 18 x 2 guess)
use_drive_keep:
        push    si
        push    dx
        mov     al, [io_drv]
        mov     ah, DRVSZ
        mul     ah
        add     ax, drvtab
        mov     si, ax
        mov     al, [si+D_UNIT]
        mov     [io_unit], al
        mov     word [io_geo_cyl], 0FFFFh ; (guessed geometry: no cache)
        mov     ax, 18
        mov     dx, 2
        cmp     byte [si+D_MNT], 0
        je      .g
        mov     ax, [si+D_SPT]
        mov     dx, [si+D_HEADS]
        push    ax
        mul     dl
        mov     [io_geo_cyl], ax
        pop     ax
.g:     mov     [io_geo_spt], ax
        mov     [io_geo_heads], dx
        pop     dx
        pop     si
        ret

; BIOS status AL -> INT 24h code AL
bios_crit:
        cmp     al, 03h
        je      .wp
        cmp     al, 80h
        je      .nr
        cmp     al, 04h
        je      .snf
        cmp     al, 02h
        je      .snf
        cmp     al, 10h
        je      .crc
        cmp     al, 40h
        je      .seek
        cmp     al, 0Ch
        je      .med
        mov     al, 0Ch
        ret
.wp:    xor     al, al
        ret
.nr:    mov     al, 2
        ret
.snf:   mov     al, 8
        ret
.crc:   mov     al, 4
        ret
.seek:  mov     al, 6
        ret
.med:   mov     al, 7
        ret

; BIOS status AL -> DOS error AX
bios2dos:
        call    bios_crit
        xor     ah, ah
        add     ax, 19
        ret

; INT 24h for the failed transfer -> AL = 0 ignore, 1 retry, 3 fail
; (abort ends the program here and doesn't come back)
crit_disk:
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    bp
        push    ds
        push    es
        mov     al, [io_bios]
        call    bios_crit
        xor     ah, ah
        mov     di, ax
        mov     ah, 38h | 06h           ; ignore, retry, fail allowed; data area
        cmp     byte [io_op], 3
        jne     .r
        or      ah, 1                   ; a write
.r:     mov     al, [io_drv]
        mov     bp, cs
        mov     si, crit_dev
        int     24h
        pop     es
        pop     ds
        pop     bp
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        cmp     al, 2
        je      .abort
        cmp     al, 3
        jbe     .x
        mov     al, 3
.x:     ret
.abort: mov     ax, [cur_psp]
        cmp     ax, [root_psp]
        je      .fail
        mov     byte [term_type], 2
        xor     al, al
        jmp     terminate               ; doesn't return
.fail:  mov     al, 3
        ret

crit_dev:                               ; a block device header for INT 24h
        dd 0FFFFFFFFh
        dw 0000h
        dw 0, 0
        db 1, 'GRIDOS '

; INT 21h 36h: free space.  DL = drive (0 = current)
f_36:   mov     al, [bp+F_DX]
        or      al, al
        jnz     .d
        mov     al, [cur_drv]
        inc     al
.d:     dec     al
        call    drv_ready
        jc      .bad
        call    fat_load
        jc      .bad
        mov     si, [actp]
        xor     bx, bx
        mov     cx, 2
.l:     cmp     cx, [si+D_NCL]
        jae     .done
        mov     ax, cx
        call    fat_get
        or      ax, ax
        jnz     .n
        inc     bx
.n:     inc     cx
        jmp     .l
.done:  mov     [bp+F_BX], bx
        mov     al, [si+D_SPC]
        xor     ah, ah
        mov     [bp+F_AX], ax
        mov     word [bp+F_CX], 512
        mov     ax, [si+D_NCL]
        sub     ax, 2
        mov     [bp+F_DX], ax
        jmp     done
.bad:   mov     word [bp+F_AX], 0FFFFh
        jmp     done
