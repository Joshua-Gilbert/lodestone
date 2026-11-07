; FDISK.COM - the hard disk's partition table (DOS 3.30's FDISK) for Lodestone
;
;   FDISK               the menu: create the DOS partition, set the active
;                       one, delete a DOS partition, show them
;   FDISK /STATUS       show them and end
;   FDISK /PRI[:mb]     make the DOS partition (the biggest it can be, or
;                       mb MB) and make it active, with no questions
;
; The disk is the AT-bus drive at 1F0h, C: when it holds a FAT16 file
; system (KHD.INC), driven here through its own registers (ATAIO.INC), as
; FORMAT does on a disk the kernel has no C: on: FDISK reads and writes
; sector 0 only.  The DOS partition it makes is the kind the kernel's C:
; takes: type 04h (under 32 MB) or 06h, from the first free cylinder (the
; first starts at head 1 of cylinder 0, as MS-DOS, past the table's own
; track), to a cylinder's end, 3 MB to 2,047 MB (FAT16 as FORMAT makes
; it); one at a time (the kernel uses only the first).  A disk with no
; table (no 55AAh) gets one, with code that says it starts nothing.
; Deleting takes DOS partitions only (01h, 04h, 06h, 0Eh); other systems'
; are shown and left alone.  Questions want an answer and Enter, read
; through DOS (FDISK < ANS.TXT works); Esc goes back.
;
; Each change is written at once.  If the kernel had C: when FDISK
; started, its tables no longer describe the disk: FDISK then restarts
; Lodestone as it ends (the disks' changes written first).  Without a C:,
; FORMAT C: comes next, then a restart.  With multitasking it must be the
; only task: another could be using the disk.
;
; Exit code: 0 done (or nothing asked), 1 couldn't (no disk, a read or
; write error, refused), 3 Ctrl-C.  Needs Lodestone.
cpu 286
org 100h

MINSEC  equ 3 * 2048                    ; the DOS partition: 3 MB at least
MAXSEC  equ 2047 * 2048                 ;  and 2,047 MB at most

; a partition entry
P_BOOT  equ 0                           ; 80h: active
P_SCHS  equ 1
P_TYPE  equ 4
P_ECHS  equ 5
P_LBA   equ 8                           ; dword
P_SIZE  equ 12                          ; dword

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     bx, prog_end + 15
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     dx, ctrlc
        mov     ax, 2523h
        int     21h
        call    args
        jc      fail
        mov     ax, 0F000h              ; Lodestone?
        int     21h
        cmp     ax, 4F47h
        mov     dx, s_notlode
        jne     fail
        mov     ax, 0F012h              ; the only task?  (CF: no
        xor     cx, cx                  ;  multitasking)
        int     21h
        jc      .one
        cmp     cx, 1
        mov     dx, s_tasks
        ja      fail
.one:   mov     ax, 4408h               ; has the kernel a C:?  (then a
        mov     bl, 3                   ;  change means a restart)
        int     21h
        cmc
        sbb     al, al
        mov     [hasc], al
        mov     bx, 32                  ; the transfer buffer: a sector
        mov     ah, 48h
        int     21h
        mov     dx, s_nomem
        jc      fail
        mov     [bseg], ax
        call    irq_off
        call    ata_init
        mov     dx, s_nohd
        jc      fail
        call    rd_mbr
        jc      fail
        cmp     byte [status], 0
        je      .pri
        call    show
        jmp     done
.pri:   cmp     byte [pri], 0
        je      menu
        call    create                  ; /PRI: no questions
        jc      fail
        jmp     done

; ---------------------------------------------------------------------
menu:   mov     dx, s_menu
        call    print
        mov     dx, s_choice
        call    print
        call    getline
        jc      done                    ; (Esc: the end)
        mov     al, [line]
        cmp     al, '1'
        je      .c
        cmp     al, '2'
        je      .a
        cmp     al, '3'
        je      .d
        cmp     al, '4'
        je      .s
        jmp     menu
.c:     call    create
        jmp     short .r
.a:     call    activate
        jmp     short .r
.d:     call    delete
        jmp     short .r
.s:     call    show
.r:     jnc     menu
        call    print                   ; (DX: why)
        mov     byte [result], 1
        jmp     menu

; the end: a restart if the kernel's C: is no longer what it was
done:   cmp     byte [changed], 0
        je      .x
        cmp     byte [hasc], 0
        jne     .rs
        mov     dx, s_next              ; "FORMAT C: next, then restart"
        call    print
.x:     call    irq_back
        mov     al, [result]
        mov     ah, 4Ch
        int     21h
.rs:    mov     dx, s_rest              ; "Lodestone restarts now"
        call    print
        mov     ah, 0Dh                 ; (the disks' changes written)
        int     21h
        mov     ah, 1                   ; a moment to read it: a key, or
        call    ticks                   ;  about 3 s
        mov     bx, ax
.w:     mov     ah, 1
        int     16h
        jnz     .go
        call    ticks
        sub     ax, bx
        cmp     ax, 55
        jb      .w
.go:    cli                             ; as the Executive's restart
        push    0
        pop     ds
        mov     word [472h], 1234h      ; (a warm boot)
        jmp     0F000h:0FFF0h

fail:   call    print
        call    irq_back
        mov     ax, 4C01h
        int     21h
ctrlc:  push    cs
        pop     ds
        cmp     byte [changed], 0       ; (a change made: as at the end)
        je      .x
        cmp     byte [hasc], 0
        jne     done.rs
.x:     call    irq_back
        mov     ax, 4C03h
        int     21h

ticks:  push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

; command tail: /STATUS, /PRI[:mb].  CF: DX
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
.l:     lodsb
        cmp     al, 13
        je      .ok
        cmp     al, ' '
        je      .l
        cmp     al, 9
        je      .l
        cmp     al, '/'
        jne     .bad
        mov     di, w_status            ; /STATUS
        call    word_is
        jnc     .st
        mov     di, w_pri               ; /PRI
        call    word_is
        jc      .bad
        mov     byte [pri], 1
        cmp     byte [si], ':'
        jne     .l
        inc     si
        call    num
        jc      .bad
        or      ax, ax
        jz      .bad
        mov     [primb], ax
        jmp     .l
.st:    mov     byte [status], 1
        jmp     .l
.ok:    mov     al, [status]
        and     al, [pri]
        jnz     .bad
        clc
        ret
.bad:   mov     dx, s_badsw
        stc
        ret

; the word at DI (upper case, 0 at its end) at SI?  SI past it if so; CF
; if not (SI kept)
word_is:
        push    si
.l:     mov     al, [di]
        or      al, al
        jz      .y
        mov     ah, [si]
        and     ah, 0DFh
        cmp     ah, al
        jne     .n
        inc     si
        inc     di
        jmp     .l
.y:     pop     ax
        clc
        ret
.n:     pop     si
        stc
        ret

; digits at SI -> AX (up to 65535), SI past them.  CF: none or too big
num:    xor     ax, ax
        xor     cx, cx
.l:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .e
        mov     bh, 0
        mov     dx, 10
        mul     dx
        jc      .big
        add     ax, bx
        jc      .big
        inc     si
        inc     cx
        jmp     .l
.e:     cmp     cx, 1
        ret
.big:   stc
        ret

; ---------------------------------------------------------------------
; sector 0 -> mbr (no table: an empty one, with our code).  CF: DX
rd_mbr: xor     ax, ax
        xor     dx, dx
        mov     cx, 1
        mov     bl, 20h
        call    ata_xfer
        mov     dx, s_rderr
        jc      .x
        push    ds
        mov     ds, [bseg]
        xor     si, si
        mov     di, mbr
        mov     cx, 256
        push    cs
        pop     es
        rep     movsw
        pop     ds
        cmp     word [mbr+510], 0AA55h
        je      .ok
        mov     si, mbrstub             ; none: an empty table, our code
        mov     di, mbr
        mov     cx, 256
        rep     movsw
        mov     byte [newtab], 1
.ok:    clc
.x:     ret

; mbr -> sector 0, and read back.  CF: DX
wr_mbr: push    es
        mov     es, [bseg]
        mov     si, mbr
        xor     di, di
        mov     cx, 256
        rep     movsw
        pop     es
        xor     ax, ax
        xor     dx, dx
        mov     cx, 1
        mov     bl, 30h
        call    ata_xfer
        mov     dx, s_wrerr
        jc      .x
        mov     byte [changed], 1
        xor     ax, ax                  ; (read back: as written?)
        xor     dx, dx
        mov     cx, 1
        mov     bl, 20h
        call    ata_xfer
        mov     dx, s_wrerr
        jc      .x
        push    ds
        mov     ds, [bseg]
        xor     si, si
        mov     di, mbr
        mov     cx, 256
        push    cs
        pop     es
        repe    cmpsw
        pop     ds
        mov     dx, s_wrerr
        jne     .bad
        mov     byte [newtab], 0
        clc
.x:     ret
.bad:   stc
        ret

; entry n (AL, 0-3) -> SI
ent:    xor     ah, ah
        shl     ax, 4
        add     ax, mbr + 446
        mov     si, ax
        ret

; the entry at SI's type AL: a DOS one (01h, 04h, 06h, 0Eh)?  ZF if so
is_dos: cmp     al, 04h
        je      .x
        cmp     al, 06h
        je      .x
        cmp     al, 0Eh
        je      .x
        cmp     al, 01h
.x:     ret

; ---------------------------------------------------------------------
; "Partition  Status  Type      Start   End   Size"
show:   mov     dx, s_head
        call    print
        mov     byte [shown], 0
        xor     bx, bx                  ; BL = the entry, BH = C:'s found
.l:     mov     al, bl
        call    ent
        mov     al, [si+P_TYPE]
        or      al, al
        jz      .n
        inc     byte [shown]
        mov     dx, s_sp4               ; " C: 1" for the one C: is
        call    is_c
        jne     .nc
        mov     dx, s_cc
.nc:    call    print
        mov     al, bl
        add     al, '1'
        call    putc
        mov     dx, s_sp8
        call    print
        mov     al, ' '
        cmp     byte [si+P_BOOT], 80h
        jne     .a
        mov     al, 'A'
.a:     call    putc
        mov     dx, s_sp4
        call    print
        mov     al, [si+P_TYPE]         ; its type
        mov     dx, s_tdos
        call    is_dos
        je      .t
        mov     dx, s_text
        cmp     al, 05h
        je      .t
        cmp     al, 0Fh
        je      .t
        mov     dx, s_tnon
.t:     call    print
        mov     ax, [si+P_LBA]          ; first and last cylinder
        mov     dx, [si+P_LBA+2]
        call    cyl_of
        mov     cx, 7
        call    pdecw
        mov     ax, [si+P_LBA]
        mov     dx, [si+P_LBA+2]
        add     ax, [si+P_SIZE]
        adc     dx, [si+P_SIZE+2]
        sub     ax, 1
        sbb     dx, 0
        call    cyl_of
        mov     cx, 7
        call    pdecw
        mov     ax, [si+P_SIZE]         ; its size
        mov     dx, [si+P_SIZE+2]
        call    mb_of
        mov     cx, 7
        call    pdecw
        mov     dx, s_mb
        call    print
.n:     inc     bl
        cmp     bl, 4
        jb      .l
        cmp     byte [shown], 0
        jne     .tot
        mov     dx, s_none
        call    print
.tot:   mov     dx, s_total             ; "Total disk space is 116 MB (..)"
        call    print
        mov     ax, [hsize]
        mov     dx, [hsize+2]
        call    mb_of
        xor     cx, cx
        call    pdecw
        mov     dx, s_mbc
        call    print
        mov     ax, [hcyls]
        call    pnum
        mov     dx, s_cyls
        call    print
        mov     ax, [hheads]
        call    pnum
        mov     dx, s_heads
        call    print
        mov     ax, [hspt]
        call    pnum
        mov     dx, s_spt
        call    print
        clc
        ret

; is entry BL (SI) the one the kernel takes as C: (the first of type 04h,
; 06h or 0Eh)?  ZF if so
is_c:   push    ax
        push    bx
        push    si
        mov     bh, bl
        xor     bl, bl
.l:     mov     al, bl
        call    ent
        mov     al, [si+P_TYPE]
        cmp     al, 01h                 ; (01h: FAT12, not the kernel's)
        je      .n
        call    is_dos
        je      .f
.n:     inc     bl
        cmp     bl, 4
        jb      .l
        or      sp, sp                  ; (NZ: none)
        jmp     short .x
.f:     cmp     bl, bh
.x:     pop     si
        pop     bx
        pop     ax
        ret

; DX:AX sectors -> DX:AX = its cylinder (DX 0)
cyl_of: push    bx
        mov     bx, [hhs]
        cmp     dx, bx                  ; (past 65,535 cylinders: as many)
        jae     .big
        div     bx
        xor     dx, dx
        pop     bx
        ret
.big:   mov     ax, 0FFFFh
        xor     dx, dx
        pop     bx
        ret

; DX:AX sectors -> DX:AX MB (rounded down)
mb_of:  mov     cx, 11
.l:     shr     dx, 1
        rcr     ax, 1
        loop    .l
        ret

; ---------------------------------------------------------------------
; the DOS partition: the biggest free cylinders, all of them ([primb] 0
; or Y) or so many MB.  CF: DX
create: mov     dx, s_hasdos            ; one DOS partition (the kernel
        xor     bl, bl                  ;  uses the first)
.e:     mov     al, bl
        call    ent
        mov     al, [si+P_TYPE]
        or      al, al
        jz      .en
        call    is_dos
        je      .no
.en:    inc     bl
        cmp     bl, 4
        jb      .e
        mov     dx, s_nofree            ; a free entry
        mov     bl, 0FFh
        xor     cl, cl
.f:     mov     al, cl
        call    ent
        cmp     byte [si+P_TYPE], 0
        jne     .fn
        mov     bl, cl
        jmp     short .ff
.fn:    inc     cl
        cmp     cl, 4
        jb      .f
.ff:    cmp     bl, 0FFh
        je      .no
        mov     [slot], bl
        call    gap                     ; the free cylinders: fstart, fcyls
        mov     dx, s_nospace
        jc      .no
        call    span                    ; fstart .. its end: sectors (capped)
        mov     dx, s_nospace
        cmp     word [fsecs+2], MINSEC >> 16
        ja      .big
        jb      .no
        cmp     word [fsecs], MINSEC & 0FFFFh
        jb      .no
.big:   cmp     byte [pri], 0           ; /PRI: no questions, and active
        je      .ask
        mov     byte [act], 1
        mov     ax, [primb]
        or      ax, ax
        jz      .all
        jmp     short .size
.ask:   mov     dx, s_qmax              ; "Use the largest size, n MB, and
        call    print                   ;  make it active (Y/N)?"
        mov     ax, [fsecs]
        mov     dx, [fsecs+2]
        call    mb_of
        xor     cx, cx
        call    pdecw
        mov     dx, s_qmax2
        call    print
        call    getyn
        jc      .back
        cmp     al, 'Y'
        je      .all
.mbq:   mov     dx, s_qsize             ; "Size in MB (3-n)? "
        call    print
        mov     ax, [fsecs]
        mov     dx, [fsecs+2]
        call    mb_of
        xor     cx, cx
        call    pdecw
        mov     dx, s_qsize2
        call    print
        call    getline
        jc      .back
        mov     si, line
        call    num
        jc      .mbq
        cmp     byte [si], 0
        jne     .mbq
.size:  cmp     ax, 3                   ; n MB: whole cylinders, from fstart
        jb      .bad
        mov     cx, 2048
        mul     cx                      ; DX:AX sectors wanted
        cmp     dx, [fsecs+2]
        ja      .bad
        jb      .cy
        cmp     ax, [fsecs]
        ja      .bad
.cy:    call    cyls_for                ; -> fsecs to the end of a cylinder
        jmp     short .mk
.bad:   mov     dx, s_badsize
        cmp     byte [pri], 0
        jne     .no
        call    print
        jmp     .mbq
.all:   mov     byte [act], 1
.mk:    mov     al, [slot]
        call    ent
        mov     di, si
        mov     ax, [fstart]            ; the entry
        mov     [di+P_LBA], ax
        mov     ax, [fstart+2]
        mov     [di+P_LBA+2], ax
        mov     ax, [fsecs]
        mov     [di+P_SIZE], ax
        mov     ax, [fsecs+2]
        mov     [di+P_SIZE+2], ax
        mov     byte [di+P_TYPE], 06h   ; 04h under 32 MB
        or      ax, ax
        jnz     .ty
        mov     byte [di+P_TYPE], 04h
.ty:    mov     byte [di+P_BOOT], 0
        cmp     byte [act], 0
        je      .chs
        call    no_active
        mov     byte [di+P_BOOT], 80h
.chs:   mov     ax, [di+P_LBA]
        mov     dx, [di+P_LBA+2]
        lea     bx, [di+P_SCHS]
        call    chs
        mov     ax, [di+P_LBA]
        mov     dx, [di+P_LBA+2]
        add     ax, [di+P_SIZE]
        adc     dx, [di+P_SIZE+2]
        sub     ax, 1
        sbb     dx, 0
        lea     bx, [di+P_ECHS]
        call    chs
        call    wr_mbr
        jc      .no
        mov     dx, s_made
        call    print
        clc
        ret
.back:  clc
        ret
.no:    stc
        ret

; every entry not active
no_active:
        push    si
        mov     si, mbr + 446
.l:     mov     byte [si+P_BOOT], 0
        add     si, 16
        cmp     si, mbr + 446 + 64
        jb      .l
        pop     si
        ret

; the free cylinders: the longest run no partition holds -> fstart (its
; first sector: cylinder 0's is head 1's, past the table's track), fend
; (its last cylinder + 1).  CF: none
gap:    xor     ax, ax                  ; AX = a cylinder to try from: 0,
        mov     word [bestn], 0         ;  then each partition's end
        mov     byte [gi], 0FFh
.try:   call    free_from               ; -> CX = free cylinders from AX
        cmp     cx, [bestn]
        jbe     .nx
        mov     [bestn], cx
        mov     [bestc], ax
.nx:    inc     byte [gi]               ; the next partition's end
        cmp     byte [gi], 4
        jae     .done
        mov     al, [gi]
        call    ent
        cmp     byte [si+P_TYPE], 0
        je      .nx
        mov     ax, [si+P_LBA]
        mov     dx, [si+P_LBA+2]
        add     ax, [si+P_SIZE]
        adc     dx, [si+P_SIZE+2]
        add     ax, [hhs]               ; (to the next whole cylinder)
        adc     dx, 0
        sub     ax, 1
        sbb     dx, 0
        call    cyl_of
        jmp     .try
.done:  cmp     word [bestn], 0
        je      .none
        mov     ax, [bestc]
        add     ax, [bestn]
        mov     [fend], ax
        mov     ax, [bestc]
        mul     word [hhs]
        or      dx, dx                  ; cylinder 0: from head 1
        jnz     .s
        or      ax, ax
        jnz     .s
        mov     ax, [hspt]
.s:     mov     [fstart], ax
        mov     [fstart+2], dx
        clc
        ret
.none:  stc
        ret

; cylinder AX: how many free from it (none if it is in a partition) -> CX
free_from:
        push    ax
        mov     cx, [hcyls]
        sub     cx, ax
        jbe     .zero
        mov     [ffc], ax
        add     ax, cx
        mov     [ffe], ax               ; [ffc, ffe): free so far
        xor     bl, bl
.l:     mov     al, bl
        call    ent
        cmp     byte [si+P_TYPE], 0
        je      .n
        mov     ax, [si+P_LBA]          ; its cylinders [a, b)
        mov     dx, [si+P_LBA+2]
        call    cyl_of
        mov     di, ax
        mov     ax, [si+P_LBA]
        mov     dx, [si+P_LBA+2]
        add     ax, [si+P_SIZE]
        adc     dx, [si+P_SIZE+2]
        add     ax, [hhs]
        adc     dx, 0
        sub     ax, 1
        sbb     dx, 0
        call    cyl_of                  ; AX = b
        cmp     ax, [ffc]               ; ends before: no matter
        jbe     .n
        cmp     di, [ffc]               ; holds ffc: none free
        ja      .cut
        xor     cx, cx
        jmp     short .x
.cut:   cmp     di, [ffe]               ; starts inside: free up to it
        jae     .n
        mov     [ffe], di
.n:     inc     bl
        cmp     bl, 4
        jb      .l
        mov     cx, [ffe]
        sub     cx, [ffc]
        jmp     short .x
.zero:  xor     cx, cx
.x:     pop     ax
        ret

; fstart .. fend's sectors -> fsecs, at most MAXSEC (to a cylinder's end)
span:   mov     ax, [fend]
        mul     word [hhs]
        sub     ax, [fstart]
        sbb     dx, [fstart+2]
        mov     [fsecs], ax
        mov     [fsecs+2], dx
        cmp     dx, MAXSEC >> 16
        jb      .x
        ja      .cap
        cmp     ax, MAXSEC & 0FFFFh
        jbe     .x
.cap:   mov     ax, MAXSEC & 0FFFFh
        mov     dx, MAXSEC >> 16
        jmp     cyls_for
.x:     ret

; DX:AX sectors wanted from fstart -> fsecs: to the end of the cylinder
; they end in (and no further than fsecs allowed)
cyls_for:
        add     ax, [fstart]            ; the end, as a sector
        adc     dx, [fstart+2]
        sub     ax, 1
        sbb     dx, 0
        div     word [hhs]              ; its cylinder (< fend: < 65,536)
        inc     ax
        mul     word [hhs]              ; its end
        sub     ax, [fstart]
        sbb     dx, [fstart+2]
        cmp     dx, MAXSEC >> 16        ; (past the cap: a cylinder less)
        jb      .ok
        ja      .less
        cmp     ax, MAXSEC & 0FFFFh
        jbe     .ok
.less:  sub     ax, [hhs]
        sbb     dx, 0
.ok:    mov     [fsecs], ax
        mov     [fsecs+2], dx
        ret

; DX:AX = a sector -> its CHS at BX (head, sector | cylinder's high bits,
; cylinder's low byte); past cylinder 1023: 1023, the last head and sector
chs:    push    cx
        push    dx
        push    ax
        div     word [hhs]              ; AX = cylinder, DX = the rest
        cmp     ax, 1023
        ja      .max
        push    ax
        mov     ax, dx
        xor     dx, dx
        div     word [hspt]
        mov     [bx], al                ; head
        inc     dl                      ; sector
        pop     ax
        mov     cl, ah
        shl     cl, 6
        or      dl, cl
        mov     [bx+1], dl
        mov     [bx+2], al
        jmp     short .x
.max:   mov     al, [hheads]
        dec     al
        mov     [bx], al
        mov     al, [hspt]
        or      al, 0C0h
        mov     [bx+1], al
        mov     byte [bx+2], 0FFh
.x:     pop     ax
        pop     dx
        pop     cx
        ret

; ---------------------------------------------------------------------
; set the active partition.  CF: DX
activate:
        call    show
        mov     dx, s_qact
        call    pick
        jc      .x
        or      si, si
        jz      .x
        cmp     byte [si+P_TYPE], 0
        mov     dx, s_noent
        je      .no
        call    no_active
        mov     byte [si+P_BOOT], 80h
        call    wr_mbr
        jc      .x
        mov     dx, s_actd
        call    print
        clc
.x:     ret
.no:    stc
        ret

; delete a DOS partition.  CF: DX
delete: call    show
        mov     dx, s_qdel
        call    pick
        jc      .x
        or      si, si
        jz      .x
        mov     al, [si+P_TYPE]
        mov     dx, s_noent
        or      al, al
        jz      .no
        call    is_dos
        mov     dx, s_notdos
        jne     .no
        mov     dx, s_qsure             ; "Its data will be lost. Delete
        call    print                   ;  it (Y/N)?"
        call    getyn
        jc      .back
        cmp     al, 'Y'
        jne     .back
        push    si
        mov     di, si
        mov     cx, 8
        xor     ax, ax
        rep     stosw
        pop     si
        call    wr_mbr
        jc      .x
        mov     dx, s_deld
        call    print
.back:  clc
.x:     ret
.no:    stc
        ret

; the question at DX, a partition's number 1-4 -> SI its entry (0: Esc).
; CF: a bad number (DX)
pick:   call    print
        call    getline
        jc      .esc
        mov     al, [line]
        sub     al, '1'
        cmp     al, 3
        ja      .bad
        cmp     byte [line+1], 0
        jne     .bad
        call    ent
        clc
        ret
.bad:   mov     dx, s_badnum
        stc
        ret
.esc:   xor     si, si                  ; (Esc: SI 0)
        clc
        ret

; ---------------------------------------------------------------------
; a line through DOS (keys, or a file): letters and digits, Backspace,
; Enter -> line (ASCIIZ, upper case).  CF: Esc, Ctrl-Z (a file's end)
getline:
        xor     bx, bx
.k:     call    getkey
        cmp     al, 13
        je      .cr
        cmp     al, 27
        je      .esc
        cmp     al, 1Ah
        je      .esc
        cmp     al, 8
        je      .bs
        cmp     al, ' '
        jbe     .k
        cmp     bx, 15
        jae     .k
        cmp     al, 'a'
        jb      .u
        cmp     al, 'z'
        ja      .u
        sub     al, 20h
.u:     mov     [line+bx], al
        inc     bx
        call    putc
        jmp     .k
.bs:    or      bx, bx
        jz      .k
        dec     bx
        mov     dx, s_bs
        call    print
        jmp     .k
.cr:    mov     byte [line+bx], 0
        mov     dx, s_crlf
        call    print
        clc
        ret
.esc:   mov     dx, s_crlf
        call    print
        stc
        ret

; Y or N and Enter -> AL.  CF: Esc
getyn:  call    getline
        jc      .x
        mov     al, [line]
        cmp     byte [line+1], 0
        jne     getyn.r
        cmp     al, 'Y'
        je      .ok
        cmp     al, 'N'
        je      .ok
.r:     mov     dx, s_yn
        call    print
        jmp     getyn
.ok:    clc
.x:     ret

; a key through DOS (Ctrl-C: INT 23h)
getkey: mov     ah, 08h
        int     21h
        ret

print:  mov     ah, 9
        int     21h
        ret
putc:   push    ax
        push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        pop     ax
        ret
pnum:   xor     dx, dx
        xor     cx, cx
; DX:AX in decimal, right-aligned in CX places
pdecw:  pusha
        mov     di, numbuf + 12
        mov     bx, 10
.d:     push    ax
        mov     ax, dx
        xor     dx, dx
        div     bx
        mov     si, ax
        pop     ax
        div     bx
        add     dl, '0'
        dec     di
        mov     [di], dl
        mov     dx, si
        mov     si, ax
        or      si, dx
        jnz     .d
        mov     ax, numbuf + 12
        sub     ax, di
.p:     cmp     ax, cx
        jae     .o
        dec     di
        mov     byte [di], ' '
        inc     ax
        jmp     .p
.o:     mov     byte [numbuf + 12], '$'
        mov     dx, di
        call    print
        popa
        ret

; ---------------------------------------------------------------------
; a new table's sector 0: code that says the disk starts nothing
mbrstub:
        cli
        xor     ax, ax
        mov     ss, ax
        mov     sp, 7C00h
        mov     ds, ax
        sti
        cld
        mov     si, 7C00h + ms_msg - mbrstub
.l:     lodsb
        or      al, al
        jz      .k
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     .l
.k:     xor     ah, ah
        int     16h
        int     19h
ms_msg  db      'This disk starts nothing: Lodestone starts from its ROM or a floppy.', 13, 10
        db      'Press a key.', 13, 10, 0
        times   446 - ($ - mbrstub) db 0
        times   64 db 0
        dw      0AA55h

w_status db 'STATUS', 0
w_pri   db 'PRI', 0
s_menu  db 13, 10, 'FDISK - the hard disk', 39, 's partitions', 13, 10, 13, 10
        db '   1. Create the DOS partition', 13, 10
        db '   2. Set the active partition', 13, 10
        db '   3. Delete a DOS partition', 13, 10
        db '   4. Show the partitions', 13, 10, 13, 10, '$'
s_choice db 'Enter choice (Esc: the end): $'
s_head  db 13, 10, 'Partition  Status  Type        Start    End   Size', 13, 10, '$'
s_cc    db ' C: $'
s_sp4   db '    $'
s_sp8   db '        $'
s_tdos  db 'PRI DOS  $'
s_text  db 'EXT DOS  $'
s_tnon  db 'Non-DOS  $'
s_mb    db ' MB', 13, 10, '$'
s_none  db '    (no partitions)', 13, 10, '$'
s_total db 13, 10, 'Total disk space is $'
s_mbc   db ' MB ($'
s_cyls  db ' cylinders, $'
s_heads db ' heads, $'
s_spt   db ' sectors a track)', 13, 10, '$'
s_qmax  db 13, 10, 'Use the largest size, $'
s_qmax2 db ' MB, and make it active (Y/N)? $'
s_qsize db 'Size of the DOS partition in MB (3-$'
s_qsize2 db ')? $'
s_badsize db 'That size does not fit', 13, 10, '$'
s_made  db 'DOS partition created', 13, 10, '$'
s_qact  db 13, 10, 'Make which partition active (1-4)? $'
s_actd  db 'Active partition set', 13, 10, '$'
s_qdel  db 13, 10, 'Delete which DOS partition (1-4)? $'
s_qsure db 'The data in it will be lost.  Delete it (Y/N)? $'
s_deld  db 'DOS partition deleted', 13, 10, '$'
s_yn    db 'Y or N, then Enter: $'
s_bs    db 8, ' ', 8, '$'
s_badnum db 'No such partition (1-4)', 13, 10, '$'
s_noent db 'That partition is empty', 13, 10, '$'
s_notdos db 'Not a DOS partition: FDISK leaves other systems', 39, ' alone', 13, 10, '$'
s_hasdos db 'There is a DOS partition already (delete it first)', 13, 10, '$'
s_nofree db 'No partition table entry is free', 13, 10, '$'
s_nospace db 'No room for a DOS partition (3 MB at least)', 13, 10, '$'
s_next  db 13, 10, 'The partition table is written.  FORMAT C: next, then restart Lodestone.', 13, 10, '$'
s_rest  db 13, 10, 'The partition table has changed under C:: Lodestone restarts now.', 13, 10, '$'
s_badsw db 'Invalid parameter (FDISK, FDISK /STATUS, FDISK /PRI[:mb])', 13, 10, '$'
s_notlode db 'FDISK: needs Lodestone', 13, 10, '$'
s_tasks db 'FDISK: other tasks are running, or FDISK runs as one (Shift-Return', 13, 10
        db 'with no other tasks: alone)', 13, 10, '$'
s_nomem db 'Insufficient memory', 13, 10, '$'
s_nohd  db 'FDISK: no hard disk answers', 13, 10, '$'
s_rderr db 'FDISK: the partition table cannot be read', 13, 10, '$'
s_wrerr db 'FDISK: the partition table could not be written', 13, 10, '$'
s_crlf  db 13, 10, '$'

%include "ATAIO.INC"

        alignb 2
section .bss
bss_start:
status  resb 1
pri     resb 1
hasc    resb 1
changed resb 1
newtab  resb 1
result  resb 1
shown   resb 1
slot    resb 1
act     resb 1
gi      resb 1
        alignb 2
primb   resw 1
bseg    resw 1
bestn   resw 1
bestc   resw 1
ffc     resw 1
ffe     resw 1
fend    resw 1
fstart  resw 2
fsecs   resw 2
numbuf  resb 14
line    resb 16
        alignb 2
mbr     resb 512
        resb 1024
stack_top:
bss_end:
prog_end:
