; CHKDSK.COM - checks a disk's FAT file system (DOS 3.30's CHKDSK) for Lodestone
;
;   CHKDSK [d:] [/F] [/V]
;
;   d:   A: or B: (a floppy, FAT12), C: (the hard disk, FAT16) or M: (the
;        temporary disk); the current drive if none is given
;   /F   write the corrections (not on M:, whose sectors the kernel keeps
;        in its buffers where only its own writes reach them)
;   /V   every file and directory's name as it goes
;
; Every file's chain of clusters is followed from its directory entry:
;   - a cluster in two chains: "Is cross linked on cluster n" (reported,
;     both files left as they are);
;   - a chain that runs into a free, bad or impossible cluster, or back
;     into itself: "Has invalid cluster, file truncated" (it ends there);
;   - a first cluster that is no cluster: "First cluster number is
;     invalid, entry truncated" (the file empty);
;   - a chain shorter than the size: "Allocation error, size adjusted"
;     (the size cut to the chain); longer: the size kept, the chain cut
;     and the rest lost, as below;
;   - a directory: its own chain the same way; "." and ".." pointing at it
;     and at its parent (corrected), a first cluster that is no cluster
;     (the entry removed).
; Then the lost clusters, in use in the FAT and in no chain: "n lost
; clusters found in m chains"; with /F they become FILE0000.CHK, ...
; in the root, or are freed (Y/N).  The two FAT copies must be the same;
; /F writes both.  Without /F nothing is written, and it says what /F
; would do.  The figures, as DOS's: total, hidden files, directories,
; user files, bad sectors, free; then the memory.
;
; Floppies are read through INT 13h (a track at a time), C: through the
; kernel's INT 25h/26h (DOS 4's packet form), M: from its EMS pages
; (INT 67h 5Bh says which handle; 44h maps them, 4Eh puts the map back).
; INT 21h 0Dh first, so the kernel's own changes are on the disk, and
; after /F's writes to a floppy, so it reads the disk again (INT 26h
; tells it for C:).  With /F, files open on the drive refuse it.
;
; Exit code: 0 no errors, 1 errors found (corrected with /F), 2 couldn't
; check (no such drive, not a FAT disk, a read error, ...), 3 Ctrl-C.
; Needs Lodestone.
cpu 286
org 100h

TRIES   equ 3
MAXSPT  equ 18
MAXDEPTH equ 32
LOSTA   equ 0FFFEh                      ; owner marks of lost clusters: a
LOSTB   equ 0FFFDh                      ;  chain's head, one pointed to
EOC     equ 0FFFFh                      ; (FAT12's are made FAT16's here)

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     ax, [2]                 ; the memory free for programs:
        mov     bx, cs                  ;  ours, from the PSP to the top
        sub     ax, bx
        mov     cx, 16
        mul     cx
        mov     [memfree], ax
        mov     [memfree+2], dx
        mov     bx, prog_end + 15
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     dx, ctrlc
        mov     ax, 2523h
        int     21h
        mov     dx, crit
        mov     ax, 2524h
        int     21h
        mov     ah, 19h                 ; the current drive, unless one is
        int     21h                     ;  given
        mov     [drv], al
        call    args
        jc      fail
        mov     al, [drv]
        add     al, 'A'
        mov     [s_d1], al
        mov     [s_d2], al
        mov     [s_d3], al
        mov     [s_d4], al
        mov     [path], al              ; "A:\"
        mov     word [path+1], '\' << 8 | ':'
        mov     ax, 0F000h              ; Lodestone?
        int     21h
        cmp     ax, 4F47h
        mov     dx, s_notlode
        jne     fail
        call    which                   ; the drive's kind
        jc      fail
        cmp     byte [fix], 0
        je      .go
        cmp     byte [kind], K_M
        mov     dx, s_nofm
        je      fail
        mov     ax, 0F001h              ; files open on it?
        mov     dl, [drv]
        int     21h
        mov     dx, s_open
        or      cx, cx
        jnz     fail
.go:    mov     ah, 0Dh                 ; the kernel's changes on the disk
        int     21h
        call    tbuf_set
        call    boot                    ; its BPB
        jc      fail
        call    alloc                   ; FAT, owners, root in memory
        jc      fail
        call    rd_fat
        jc      fail
        call    rd_root
        jc      fail
        call    volume
        call    walk_root
        call    lost
        cmp     byte [fatdiff], 0
        je      .w
        mov     dx, s_fats
        call    report0
.w:     cmp     byte [fix], 0
        je      .fig
        call    write_back
        jc      fail
        cmp     byte [kind], K_FL
        jne     .fig
        mov     ah, 0Dh                 ; the kernel reads the floppy again
        int     21h
.fig:   call    figures
        xor     al, al
        cmp     word [nerr], 0
        je      .x
        mov     al, 1
.x:     mov     ah, 4Ch
        int     21h

fail:   call    print
        mov     ax, 4C02h
        int     21h
ctrlc:  push    cs
        pop     ds
        call    ctx_back
        mov     ax, 4C03h
        int     21h
crit:   mov     al, 3
        iret

K_FL    equ 0                           ; kinds of drive
K_HD    equ 1
K_M     equ 2

; ---------------------------------------------------------------------
; command tail: d:, /F, /V.  CF: DX = message
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
        je      .sw
        cmp     byte [si], ':'
        jne     .bad
        and     al, 0DFh
        sub     al, 'A'
        cmp     al, 25
        ja      .bad
        mov     [drv], al
        inc     si
        jmp     .l
.sw:    lodsb
        and     al, 0DFh
        cmp     al, 'F'
        je      .f
        cmp     al, 'V'
        jne     .bad
        mov     byte [verbose], 1
        jmp     .l
.f:     mov     byte [fix], 1
        jmp     .l
.ok:    clc
        ret
.bad:   mov     dx, s_badsw
        stc
        ret

; the drive [drv] -> [kind] (and [unit], [mhand]).  CF: DX = message
which:  mov     al, [drv]
        cmp     al, 1
        ja      .c
        mov     [unit], al              ; A: or B:: a BIOS unit there?
        mov     byte [kind], K_FL
        int     11h
        xor     cl, cl
        test    al, 1
        jz      .n
        mov     cl, al
        shr     cl, 6
        inc     cl
.n:     cmp     [unit], cl
        jae     .inv
        clc
        ret
.c:     cmp     al, 2
        jne     .m
        mov     byte [kind], K_HD       ; C:: there if DOS knows it
        mov     ah, 36h
        mov     dl, 3
        int     21h
        cmp     ax, 0FFFFh
        je      .inv
        clc
        ret
.m:     cmp     al, 12
        jne     .r
        mov     byte [kind], K_M        ; M:: its EMS handle
        mov     ax, 5B4Dh
        xor     bl, bl
        xor     cx, cx
        int     67h
        or      ah, ah
        jnz     .inv
        jcxz    .inv
        mov     [mhand], si
        mov     ah, 41h                 ; the page frame
        int     67h
        or      ah, ah
        jnz     .inv
        mov     [frame], bx
        clc
        ret
.r:     cmp     al, 17
        mov     dx, s_rom
        je      .x
.inv:   mov     dx, s_baddrv
.x:     stc
        ret

; a track's buffer that doesn't cross a 64 KB DMA boundary
tbuf_set:
        mov     ax, cs
        shl     ax, 4
        add     ax, tb1
        mov     word [tbuf], tb1
        cmp     ax, 10000h - MAXSPT * 512
        jbe     .x
        mov     word [tbuf], tb2
.x:     ret

; ---------------------------------------------------------------------
; the boot sector's BPB -> the layout.  CF: DX = message
boot:   xor     ax, ax
        xor     dx, dx
        cmp     byte [kind], K_FL       ; (a floppy's geometry: a guess
        jne     .r                      ;  that reads sector 1 of any)
        mov     word [spt], 9
        mov     word [heads], 2
.r:     mov     cx, 1
        push    ds
        pop     es
        mov     bx, secbuf
        call    rdsec
        mov     dx, s_rderr
        jc      .x
        mov     si, secbuf
        mov     dx, s_nondos
        cmp     word [si+0Bh], 512
        jne     .bad
        mov     al, [si+0Dh]            ; sectors a cluster: a power of 2
        or      al, al
        jz      .bad
        xor     cl, cl
.p:     shr     al, 1
        jc      .pe
        inc     cl
        jmp     .p
.pe:    or      al, al
        jnz     .bad
        cmp     cl, 6
        ja      .bad
        mov     [shift], cl
        mov     al, [si+0Dh]
        xor     ah, ah
        mov     [spc], ax
        shl     ax, 9
        mov     [csize], ax
        mov     ax, [si+0Eh]
        or      ax, ax
        jz      .bad
        mov     [rsv], ax
        mov     al, [si+10h]
        xor     ah, ah
        or      al, al
        jz      .bad
        cmp     al, 2
        ja      .bad
        mov     [nfat], ax
        mov     ax, [si+11h]
        or      ax, ax
        jz      .bad
        cmp     ax, 4096
        ja      .bad
        mov     [nroot], ax
        add     ax, 15
        shr     ax, 4
        mov     [rsecs], ax
        mov     ax, [si+16h]
        or      ax, ax
        jz      .bad
        cmp     ax, 256
        ja      .bad
        mov     [spf], ax
        mul     word [nfat]
        add     ax, [rsv]
        mov     [rootlba], ax
        add     ax, [rsecs]
        mov     [datalba], ax
        mov     ax, [si+13h]            ; sectors: 16 bits, or 32
        xor     dx, dx
        or      ax, ax
        jnz     .t
        mov     ax, [si+20h]
        mov     dx, [si+22h]
.t:     sub     ax, [datalba]
        sbb     dx, 0
        jb      .bad
        mov     cl, [shift]             ; data clusters (FAT16: 65,524 at
.sh:    or      cl, cl                  ;  most)
        jz      .she
        shr     dx, 1
        rcr     ax, 1
        dec     cl
        jmp     .sh
.she:   or      dx, dx
        jnz     .bad
        cmp     ax, 65524
        ja      .bad
        cmp     ax, 1
        jb      .bad
        mov     [nclus], ax
        add     ax, 2
        mov     [ncl], ax
        cmp     ax, 4085 + 2            ; FAT16 from 4085 clusters
        jb      .f12
        mov     byte [fat16], 1
        mov     bx, [spf]               ; its FAT must hold them
        shl     bx, 8
        jc      .geo
        cmp     bx, ax
        jb      .bad
        jmp     short .geo
.f12:   mov     bx, ax                  ; FAT12: 1.5 bytes each
        shr     bx, 1
        add     bx, ax
        mov     cx, [spf]
        shl     cx, 9
        cmp     cx, bx
        jb      .bad
.geo:   cmp     byte [kind], K_FL
        jne     .ext
        mov     ax, [si+18h]            ; a floppy's own geometry
        or      ax, ax
        jz      .bad
        cmp     ax, MAXSPT
        ja      .bad
        mov     [spt], ax
        mov     ax, [si+1Ah]
        or      ax, ax
        jz      .bad
        cmp     ax, 2
        ja      .bad
        mov     [heads], ax
.ext:   cmp     byte [si+26h], 29h      ; DOS 4's serial number
        jne     .ok
        mov     ax, [si+27h]
        mov     [ser], ax
        mov     ax, [si+29h]
        mov     [ser+2], ax
        mov     byte [hasser], 1
.ok:    clc
.x:     ret
.bad:   stc
        ret

; memory: the FAT, the owners (a word a cluster), the root.  CF: DX
alloc:  mov     bx, [spf]
        shl     bx, 5
        call    .get
        jc      .x
        mov     [fatseg], ax
        mov     bx, [ncl]
        add     bx, 7
        shr     bx, 3
        call    .get
        jc      .x
        mov     [ownseg], ax            ; (all 0: nobody's)
        mov     dx, ax
.z:     or      bx, bx                  ; (BX: its paragraphs, 32 KB at a
        jz      .zd                     ;  time)
        mov     cx, bx
        cmp     cx, 800h
        jbe     .zs
        mov     cx, 800h
.zs:    sub     bx, cx
        mov     es, dx
        add     dx, cx
        shl     cx, 3
        xor     di, di
        xor     ax, ax
        rep     stosw
        jmp     .z
.zd:    mov     bx, [rsecs]
        shl     bx, 5
        call    .get
        jc      .x
        mov     [rootseg], ax
        push    ds
        pop     es
        clc
.x:     ret
.get:   mov     ah, 48h
        int     21h
        mov     dx, s_nomem
        ret

; the first FAT (the second if it can't be read), and are they alike?
; CF: DX = message
rd_fat: mov     ax, [rsv]
        call    .one
        jnc     .cmp
        cmp     word [nfat], 2
        jb      .bad
        mov     ax, [rsv]
        add     ax, [spf]
        call    .one
        jc      .bad
        mov     byte [fatdiff], 1       ; (/F writes both)
        clc
        ret
.bad:   mov     dx, s_fatbad
        stc
        ret
.one:   xor     dx, dx
        mov     cx, [spf]
        xor     bx, bx
        mov     es, [fatseg]
        call    rdsec
        push    ds
        pop     es
        ret
.cmp:   cmp     word [nfat], 2          ; the second, a sector at a time
        jb      .ok
        xor     bp, bp
.c:     cmp     bp, [spf]
        jae     .ok
        mov     ax, [rsv]
        add     ax, [spf]
        add     ax, bp
        xor     dx, dx
        mov     cx, 1
        mov     bx, secbuf
        call    rdsec
        jc      .df
        push    ds
        mov     si, secbuf
        mov     ax, bp
        shl     ax, 5
        add     ax, [fatseg]
        mov     es, ax
        xor     di, di
        mov     cx, 256
        repe    cmpsw
        push    ds
        pop     es
        pop     ds
        jne     .df
        inc     bp
        jmp     .c
.df:    mov     byte [fatdiff], 1
.ok:    clc
        ret

; the root directory.  CF: DX = message
rd_root:
        mov     ax, [rootlba]
        xor     dx, dx
        mov     cx, [rsecs]
        xor     bx, bx
        mov     es, [rootseg]
        call    rdsec
        push    ds
        pop     es
        mov     dx, s_rderr
        ret

; "Volume LODESTONE created 11-07-2026 6:04a" and the serial number
volume: mov     es, [rootseg]
        xor     di, di
        mov     cx, [nroot]
.l:     cmp     byte [es:di], 0
        je      .ser
        cmp     byte [es:di], 0E5h
        je      .n
        mov     al, [es:di+11]
        cmp     al, 0Fh
        je      .n
        test    al, 8
        jnz     .lab
.n:     add     di, 32
        jnz     .nn                     ; (past 64 KB: the next segment)
        mov     ax, es
        add     ax, 1000h
        mov     es, ax
.nn:    loop    .l
        jmp     .ser
.lab:   mov     dx, s_vol
        call    print
        mov     cx, 11
.c:     mov     al, [es:di]
        call    putc
        inc     di
        loop    .c
        sub     di, 11
        mov     dx, s_created
        call    print
        mov     ax, [es:di+18h]         ; the date: mm-dd-yyyy
        push    ax
        shr     ax, 5
        and     ax, 15
        call    p2
        mov     al, '-'
        call    putc
        pop     ax
        push    ax
        and     ax, 31
        call    p2
        mov     al, '-'
        call    putc
        pop     ax
        shr     ax, 9
        add     ax, 1980
        xor     dx, dx
        call    pdec
        mov     al, ' '
        call    putc
        mov     ax, [es:di+16h]         ; the time: h:mma
        shr     ax, 11
        mov     bl, 'a'
        cmp     ax, 12
        jb      .am
        mov     bl, 'p'
        sub     ax, 12
.am:    or      ax, ax
        jnz     .h
        mov     ax, 12
.h:     xor     dx, dx
        call    pdec
        mov     al, ':'
        call    putc
        mov     ax, [es:di+16h]
        shr     ax, 5
        and     ax, 63
        call    p2
        mov     al, bl
        call    putc
        mov     dx, s_crlf
        call    print
.ser:   push    ds
        pop     es
        cmp     byte [hasser], 0
        je      .x
        mov     dx, s_ser
        call    print
        mov     ax, [ser+2]
        call    phex
        mov     al, '-'
        call    putc
        mov     ax, [ser]
        call    phex
        mov     dx, s_crlf
        call    print
.x:     ret

; ---------------------------------------------------------------------
;  sectors: DX:AX = sector, CX = sectors, ES:BX = memory.  CF: an error
; ---------------------------------------------------------------------
rdsec:  mov     byte [xop], 2
        jmp     short xsec
wrsec:  mov     byte [xop], 3
xsec:   pusha
        push    es
        cmp     byte [kind], K_HD
        je      .hd
        cmp     byte [kind], K_M
        je      .m
        call    fl_io
        jmp     short .x
.hd:    call    hd_io
        jmp     short .x
.m:     call    md_io
.x:     pop     es
        popa
        ret

; a floppy: a track at a time through tbuf
fl_io:  or      cx, cx
        jz      .ok
        push    cx
        push    ax                      ; (DX is 0: 16-bit sectors)
        xor     dx, dx
        div     word [spt]
        mov     [f_sct], dl             ; the sector in the track, from 0
        mov     si, [spt]
        sub     si, dx                  ; SI = sectors to the track's end
        xor     dx, dx
        div     word [heads]
        mov     [f_cyl], al
        mov     [f_head], dl
        cmp     si, cx
        jbe     .n
        mov     si, cx
.n:     mov     [f_n], si
        cmp     byte [xop], 3
        jne     .io
        push    ds                      ; a write: ours to tbuf first
        push    es
        mov     di, [tbuf]
        push    es
        pop     ds
        push    cs
        pop     es
        mov     si, bx
        mov     cx, [cs:f_n]
        shl     cx, 8
        rep     movsw
        pop     es
        pop     ds
.io:    mov     bp, TRIES
.t:     push    es
        push    bx
        push    cs
        pop     es
        mov     bx, [tbuf]
        mov     al, [f_n]
        mov     ah, [xop]
        mov     ch, [f_cyl]
        mov     cl, [f_sct]
        inc     cl
        mov     dh, [f_head]
        mov     dl, [unit]
        int     13h
        pop     bx
        pop     es
        jnc     .done
        cmp     ah, 03h                 ; write-protected: no more tries
        je      .err
        push    ax
        xor     ah, ah
        mov     dl, [unit]
        int     13h
        pop     ax
        dec     bp
        jnz     .t
.err:   mov     [bstat], ah
        pop     ax
        pop     cx
        stc
        ret
.done:  cmp     byte [xop], 2
        jne     .adv
        mov     di, bx                  ; a read: tbuf to ours
        mov     si, [tbuf]
        mov     cx, [f_n]
        shl     cx, 8
        rep     movsw
.adv:   pop     ax
        pop     cx
        mov     si, [f_n]
        add     ax, si
        sub     cx, si
        shl     si, 5
        mov     dx, es
        add     dx, si
        mov     es, dx
        xor     dx, dx
        jmp     fl_io
.ok:    clc
        ret

; C: through the kernel's INT 25h/26h, 64 sectors at a time
hd_io:  jcxz    .ok
        mov     si, cx
        cmp     si, 64
        jbe     .n
        mov     si, 64
.n:     mov     [pk_lba], ax
        mov     [pk_lba+2], dx
        mov     [pk_n], si
        mov     [pk_buf], bx
        mov     [pk_buf+2], es
        pusha
        push    es
        mov     al, 2
        mov     cx, 0FFFFh
        mov     bx, pk_lba
        cmp     byte [xop], 3
        je      .w
        int     25h
        jmp     short .d
.w:     int     26h
.d:     inc     sp                      ; (the flags it left; INC keeps CF)
        inc     sp
        pop     es
        popa
        jc      .err
        add     ax, si
        adc     dx, 0
        sub     cx, si
        shl     si, 5
        mov     di, es
        add     di, si
        mov     es, di
        jmp     hd_io
.err:   stc
        ret
.ok:    clc
        ret

; M:: each sector from its EMS page (reads only), the map put back after
md_io:  push    ax
        push    es
        push    ds
        pop     es
        mov     di, ctx
        mov     ax, 4E00h
        int     67h
        pop     es
        mov     byte [ctxset], 1
        or      ah, ah
        pop     ax
        jnz     .err
.l:     jcxz    .ok
        push    ax
        push    cx
        push    bx
        mov     bx, ax
        shr     bx, 5                   ; its page
        mov     dx, [mhand]
        mov     ax, 4400h
        int     67h
        pop     bx
        or      ah, ah
        pop     cx
        pop     ax
        jnz     .err
        push    ax
        push    cx
        push    ds
        and     ax, 31
        shl     ax, 9
        mov     si, ax
        mov     di, bx
        mov     ds, [frame]
        mov     cx, 256
        rep     movsw
        pop     ds
        pop     cx
        pop     ax
        inc     ax
        dec     cx
        mov     dx, es
        add     dx, 32
        mov     es, dx
        jmp     .l
.ok:    call    ctx_back
        clc
        ret
.err:   call    ctx_back
        stc
        ret

; the EMS map as it was (M:)
ctx_back:
        cmp     byte [ctxset], 0
        je      .x
        mov     byte [ctxset], 0
        pusha
        mov     si, ctx
        mov     ax, 4E01h
        int     67h
        popa
.x:     ret

; cluster AX -> DX:AX = its first sector
clu_lba:
        sub     ax, 2
        mul     word [spc]
        add     ax, [datalba]
        adc     dx, 0
        ret

; ---------------------------------------------------------------------
;  the FAT and the owners, in memory (ES kept)
; ---------------------------------------------------------------------
; FAT entry AX -> AX (FAT12's as FAT16's: FF0h-FFFh are FFF0h-FFFFh)
getfat: push    es
        push    bx
        cmp     byte [fat16], 0
        je      .12
        mov     bx, ax
        shr     bx, 3
        add     bx, [fatseg]
        mov     es, bx
        mov     bx, ax
        and     bx, 7
        shl     bx, 1
        mov     ax, [es:bx]
        jmp     short .x
.12:    mov     es, [fatseg]
        mov     bx, ax
        shr     bx, 1
        add     bx, ax
        test    al, 1
        mov     ax, [es:bx]
        jz      .e
        shr     ax, 4
.e:     and     ax, 0FFFh
        cmp     ax, 0FF0h
        jb      .x
        or      ax, 0F000h
.x:     pop     bx
        pop     es
        ret

; FAT entry AX <- DX; its sectors marked to be written
setfat: pusha
        push    es
        cmp     byte [fat16], 0
        je      .12
        mov     bx, ax
        shr     bx, 3
        add     bx, [fatseg]
        mov     es, bx
        mov     bx, ax
        and     bx, 7
        shl     bx, 1
        mov     [es:bx], dx
        mov     bx, ax
        shr     bx, 8
        call    fdirty
        jmp     short .x
.12:    mov     es, [fatseg]
        mov     bx, ax
        shr     bx, 1
        add     bx, ax
        and     dx, 0FFFh
        mov     cx, [es:bx]
        test    al, 1
        jz      .ev
        and     cx, 000Fh
        shl     dx, 4
        jmp     short .s
.ev:    and     cx, 0F000h
.s:     or      cx, dx
        mov     [es:bx], cx
        push    bx
        shr     bx, 9
        call    fdirty
        pop     bx
        inc     bx
        shr     bx, 9
        call    fdirty
.x:     mov     byte [changed], 1
        pop     es
        popa
        ret
fdirty: mov     cx, bx                  ; FAT sector BX to be written
        and     cl, 7
        mov     al, 1
        shl     al, cl
        shr     bx, 3
        or      [fatdirty+bx], al
        ret

; owner of cluster AX -> AX; setown: AX's owner <- DX
own_at: mov     bx, ax
        shr     bx, 3
        add     bx, [ownseg]
        mov     es, bx
        mov     bx, ax
        and     bx, 7
        shl     bx, 1
        ret
getown: push    es
        push    bx
        call    own_at
        mov     ax, [es:bx]
        pop     bx
        pop     es
        ret
setown: push    es
        push    bx
        call    own_at
        mov     [es:bx], dx
        pop     bx
        pop     es
        ret

; ---------------------------------------------------------------------
;  the directories
; ---------------------------------------------------------------------
walk_root:
        mov     word [pathlen], 3
        mov     word [curdir], 0
        mov     word [parent], 0
        mov     word [ri], 0
.l:     mov     ax, [ri]
        cmp     ax, [nroot]
        jae     .x
        shl     ax, 1                   ; entry i: 32 bytes, 2 paragraphs
        add     ax, [rootseg]
        mov     es, ax
        xor     di, di
        cmp     byte [es:di], 0
        je      .x
        mov     byte [inroot], 1
        call    entry
        cmp     byte [emod], 0
        je      .c
        push    ax
        mov     ax, [ri]                ; its sector to be written
        shr     ax, 4
        call    rdirty
        pop     ax
.c:     or      ax, ax
        jz      .n
        xor     dx, dx                  ; a directory: into it
        push    word [ri]
        call    walk_sub
        pop     word [ri]
        mov     word [pathlen], 3
        mov     byte [path+3], 0
.n:     inc     word [ri]
        jmp     .l
.x:     push    ds
        pop     es
        ret

; root sector AX to be written (with /F)
rdirty: push    bx
        push    cx
        mov     bx, ax
        mov     cl, al
        and     cl, 7
        mov     al, 1
        shl     al, cl
        shr     bx, 3
        or      [rootdirty+bx], al
        pop     cx
        pop     bx
        ret

; the subdirectory whose chain starts at AX, its parent's at DX; the
; path to it at path, [pathlen] its end (the "\" after it)
walk_sub:
        cmp     word [depth], MAXDEPTH
        jae     .deep
        inc     word [depth]
        push    word [curdir]
        push    word [parent]
        push    word [pathlen]
        mov     [curdir], ax
        mov     [parent], dx
        mov     [dcl], ax               ; (the cluster being read)
        mov     word [dent], 0          ; (entries so far)
.cl:    mov     word [dsec], 0
.sec:   call    dread
        jc      .done
        mov     word [dix], 0
.ent:   mov     di, [dix]
        shl     di, 5
        add     di, secbuf
        push    ds
        pop     es
        cmp     byte [di], 0
        je      .done
        mov     byte [inroot], 0
        mov     ax, [dent]
        cmp     ax, 2
        jae     .e
        call    dots                    ; "." and ".."
        jmp     short .nx
.e:     push    word [pathlen]          ; (ours, as entry may move it)
        call    entry
        pop     bx
        or      ax, ax
        jz      .nx
        push    bx
        push    ax
        call    dwrite                  ; (a change, before it's read over)
        pop     ax
        push    word [dcl]              ; into it
        push    word [dsec]
        push    word [dix]
        push    word [dent]
        mov     dx, [curdir]
        call    walk_sub
        pop     word [dent]
        pop     word [dix]
        pop     word [dsec]
        pop     word [dcl]
        pop     bx
        mov     [pathlen], bx           ; the path ours again
        mov     byte [path+bx], 0
        call    dread                   ; (and the sector)
        jc      .done
.nx:    inc     word [dent]
        inc     word [dix]
        cmp     word [dix], 16
        jb      .ent
        call    dwrite
        inc     word [dsec]
        mov     ax, [dsec]
        cmp     ax, [spc]
        jb      .sec
        mov     ax, [dcl]               ; the next cluster of it
        call    getfat
        cmp     ax, 2
        jb      .done
        cmp     ax, [ncl]
        jae     .done
        mov     [dcl], ax
        jmp     .cl
.done:  call    dwrite
        pop     word [pathlen]
        mov     bx, [pathlen]
        mov     byte [path+bx], 0
        pop     word [parent]
        pop     word [curdir]
        dec     word [depth]
.deep:  ret

; the directory's sector [dsec] of cluster [dcl] -> secbuf.  CF: it can't
; be read (said)
dread:  mov     byte [smod], 0
        mov     ax, [dcl]
        call    clu_lba
        add     ax, [dsec]
        adc     dx, 0
        mov     cx, 1
        push    ds
        pop     es
        mov     bx, secbuf
        call    rdsec
        jnc     .x
        mov     dx, s_dread             ; (the path: the directory's)
        call    report
        stc
.x:     ret

; secbuf back to the disk if it changed (with /F)
dwrite: cmp     byte [smod], 0
        je      .x
        mov     byte [smod], 0
        cmp     byte [fix], 0
        je      .x
        mov     ax, [dcl]
        call    clu_lba
        add     ax, [dsec]
        adc     dx, 0
        mov     cx, 1
        push    ds
        pop     es
        mov     bx, secbuf
        call    wrsec
        jnc     .x
        mov     byte [wfail], 1
.x:     ret

; "." (entry 0) and ".." (1) of the directory [curdir], at ES:DI
dots:   mov     si, s_dot
        cmp     word [dent], 0
        je      .n
        mov     si, s_dotdot
.n:     push    di
        mov     cx, 11
        repe    cmpsb
        pop     di
        jne     .miss
        mov     ax, [curdir]
        cmp     word [dent], 0
        je      .c
        mov     ax, [parent]
.c:     cmp     [es:di+1Ah], ax
        je      .x
        mov     [es:di+1Ah], ax         ; pointing elsewhere: put right
        mov     byte [smod], 1
.miss:  mov     dx, s_dots
        call    report
.x:     ret

; the entry at ES:DI, in the directory [curdir] (the root: [inroot]).
; -> [emod] if it changed, AX = a subdirectory's first cluster to go into
; (0: none), [pathlen] past its "\"
entry:  mov     byte [emod], 0
        xor     ax, ax
        cmp     byte [es:di], 0E5h      ; deleted
        je      .x0
        mov     al, [es:di+11]
        cmp     al, 0Fh                 ; (a long name's piece)
        je      .x0
        test    al, 8                   ; the label
        jnz     .x0
        cmp     byte [es:di], '.'       ; (dots outside their places)
        je      .x0
        inc     word [fid]
        call    name                    ; its path
        cmp     byte [verbose], 0
        je      .nv
        call    ppath
        mov     dx, s_crlf
        call    print
.nv:    mov     ax, [es:di+1Ah]
        test    byte [es:di+11], 10h
        jnz     .dir
        ; ---- a file
        mov     cx, [es:di+1Ch]         ; its size
        or      cx, [es:di+1Eh]
        or      ax, ax
        jnz     .f1
        jcxz    .cnt0                   ; empty, as it should be
        jmp     short .first
.f1:    call    inuse
        jnc     .fc
.first: mov     dx, s_first             ; no cluster: the file empty
        call    report
        xor     ax, ax
        mov     [es:di+1Ah], ax
        mov     [es:di+1Ch], ax
        mov     [es:di+1Eh], ax
        call    emodded
.cnt0:  xor     ax, ax
        jmp     .count
.fc:    call    chain                   ; -> AX clusters, [crossed]
        cmp     byte [crossed], 0
        jne     .count
        push    ax
        mov     ax, [es:di+1Ch]         ; the clusters its size needs
        mov     dx, [es:di+1Eh]
        add     ax, [csize]
        adc     dx, 0
        jc      .big
        sub     ax, 1
        sbb     dx, 0
        cmp     dx, [csize]
        jae     .big
        div     word [csize]
        jmp     short .nd
.big:   mov     ax, 0FFFFh
.nd:    mov     cx, ax                  ; CX = needed
        pop     ax                      ; AX = in the chain
        cmp     ax, cx
        je      .count
        push    ax
        push    cx
        pushf
        mov     dx, s_alloc
        call    report
        popf
        pop     cx
        pop     ax
        jb      .short
        push    cx                      ; longer: cut after CX clusters
        call    cut
        pop     ax
        jmp     short .count
.short: push    ax                      ; shorter: the size to the chain
        mul     word [csize]
        mov     [es:di+1Ch], ax
        mov     [es:di+1Eh], dx
        call    emodded
        pop     ax
.count: mul     word [csize]            ; AX clusters -> the tallies
        mov     bx, nuser
        test    byte [es:di+11], 2
        jz      .ct
        mov     bx, nhid
.ct:    inc     word [bx]
        add     [bx+2], ax
        adc     [bx+4], dx
.x0:    xor     ax, ax
        ret
        ; ---- a directory
.dir:   call    inuse
        jc      .dbad
        push    ax
        call    chain
        mul     word [csize]
        inc     word [ndir]
        add     [ndir+2], ax
        adc     [ndir+4], dx
        pop     ax
        cmp     byte [crossed], 0
        jne     .x0
        cmp     byte [loopy], 0         ; (its first cluster was its own)
        jne     .x0
        mov     si, [nameend]           ; the path on: "\NAME\"
        mov     byte [path+si], '\'
        inc     si
        mov     byte [path+si], 0
        mov     [pathlen], si
        ret
.dbad:  mov     dx, s_baddir            ; no cluster: the entry goes
        call    report
        mov     byte [es:di], 0E5h
        call    emodded
        jmp     .x0

emodded:
        mov     byte [emod], 1
        mov     byte [smod], 1
        ret

; follow the chain from cluster AX for the entry [fid], each cluster
; marked as its.  -> AX = clusters; [crossed] if it ran into another's
; (said); its end put right in the FAT if it ran into a free, bad or
; impossible one, or back into itself (said: [loopy] if at its start)
chain:  mov     byte [crossed], 0
        mov     byte [loopy], 0
        xor     cx, cx                  ; CX = clusters
        xor     si, si                  ; SI = the one before
.l:     push    ax
        call    getown
        mov     bx, ax
        pop     ax
        or      bx, bx
        jz      .mine
        cmp     bx, LOSTB               ; (lost ones are nobody's yet)
        jae     .mine
        cmp     bx, [fid]
        je      .loop
        push    cx
        push    ax
        mov     dx, s_cross
        call    report_n
        pop     ax
        pop     cx
        mov     byte [crossed], 1
        jmp     short .x
.loop:  or      si, si
        jnz     .lp
        mov     byte [loopy], 1
.lp:    mov     dx, s_inval
        push    cx
        call    report
        pop     cx
        mov     ax, si
        mov     dx, EOC
        call    setfat
        jmp     short .x
.mine:  mov     dx, [fid]
        call    setown
        inc     cx
        mov     si, ax
        call    getfat
        cmp     ax, 0FFF8h
        jae     .x
        call    inuse                   ; the next: a cluster, in use?
        jnc     .l
.bad:   push    cx
        mov     dx, s_inval
        call    report
        pop     cx
        mov     ax, si
        mov     dx, EOC
        call    setfat
.x:     mov     ax, cx
        ret

; cluster AX: a cluster of the disk, in use in the FAT (not free, not
; bad)?  CF if not.  All kept
inuse:  cmp     ax, 2
        jb      .no
        cmp     ax, [ncl]
        jae     .no
        push    ax
        call    getfat
        or      ax, ax
        jz      .n2
        cmp     ax, 0FFF7h
        je      .n2
        pop     ax
        clc
        ret
.n2:    pop     ax
.no:    stc
        ret

; the chain of the entry at ES:DI to CX clusters (0: none); the rest is
; nobody's (lost, found below)
cut:    mov     ax, [es:di+1Ah]
        jcxz    .all
.k:     dec     cx
        jz      .end
        call    getfat
        jmp     .k
.end:   push    ax
        call    getfat
        mov     bx, ax                  ; BX = the rest
        pop     ax
        mov     dx, EOC
        call    setfat
        mov     ax, bx
        jmp     short .free
.all:   xor     dx, dx
        mov     [es:di+1Ah], dx
        call    emodded
.free:  cmp     ax, 2                   ; the rest: nobody's
        jb      .x
        cmp     ax, [ncl]
        jae     .x
        push    ax
        call    getown
        cmp     ax, [fid]
        pop     ax
        jne     .x
        xor     dx, dx
        call    setown
        call    getfat
        jmp     .free
.x:     ret

; the 8.3 name at ES:DI onto path at [pathlen] -> [nameend] (ASCIIZ)
name:   push    di
        mov     si, [pathlen]
        mov     cx, 8
        xor     bx, bx
.b:     mov     al, [es:di+bx]
        cmp     al, ' '
        je      .be
        cmp     bx, 0
        jne     .bp
        cmp     al, 05h                 ; (E5h as a first character)
        jne     .bp
        mov     al, 0E5h
.bp:    mov     [path+si], al
        inc     si
        inc     bx
        loop    .b
.be:    cmp     byte [es:di+8], ' '
        je      .z
        mov     byte [path+si], '.'
        inc     si
        mov     bx, 8
.x:     mov     al, [es:di+bx]
        cmp     al, ' '
        je      .z
        mov     [path+si], al
        inc     si
        inc     bx
        cmp     bx, 11
        jb      .x
.z:     mov     byte [path+si], 0
        mov     [nameend], si
        pop     di
        ret

; an error: "Errors found, F parameter not specified" the first time
; without /F, the path, the message at DX.  report_n: and the number AX.
; report0: no path.  ES, DI kept
report0:
        mov     byte [nopath], 1
report: mov     word [rnum], 0FFFFh
        jmp     short rep_
report_n:
        mov     [rnum], ax
rep_:   push    es
        push    di
        push    dx
        call    err_hdr
.h:     cmp     byte [nopath], 0
        jne     .m
        call    ppath
        mov     dx, s_crlf
        call    print
.m:     mov     byte [nopath], 0
        pop     dx
        call    print
        mov     ax, [rnum]
        cmp     ax, 0FFFFh
        je      .e
        xor     dx, dx
        call    pdec
.e:     mov     dx, s_crlf
        call    print
        pop     di
        pop     es
        ret

; one more error; without /F, the first time: "Errors found, F parameter
; not specified".  DX changed
err_hdr:
        inc     word [nerr]
        cmp     byte [fix], 0
        jne     .x
        cmp     byte [hdr], 0
        jne     .x
        mov     byte [hdr], 1
        mov     dx, s_nofix
        call    print
.x:     ret

; the path (ASCIIZ, it may hold a $)
ppath:  push    si
        mov     si, path
.l:     lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     .l
.x:     pop     si
        ret

; ---------------------------------------------------------------------
; lost clusters: in use in the FAT, in no chain
lost:   mov     ax, 2                   ; mark them
.m:     cmp     ax, [ncl]
        jae     .md
        push    ax
        call    getfat
        mov     bx, ax
        pop     ax
        or      bx, bx
        jz      .mn
        cmp     bx, 0FFF7h
        je      .mn
        push    ax
        call    getown
        mov     bx, ax
        pop     ax
        or      bx, bx
        jnz     .mn
        mov     dx, LOSTA
        call    setown
        inc     word [nlost]
.mn:    inc     ax
        jmp     .m
.md:    cmp     word [nlost], 0
        jne     .heads
        ret
.heads: mov     ax, 2                   ; one another points to: not a head
.h:     cmp     ax, [ncl]
        jae     .hd
        push    ax
        call    getown
        cmp     ax, LOSTB
        pop     ax
        jb      .hn
        push    ax
        call    getfat
        cmp     ax, 2
        jb      .hp
        cmp     ax, [ncl]
        jae     .hp
        push    ax
        call    getown
        cmp     ax, LOSTA
        pop     ax
        jne     .hp
        mov     dx, LOSTB
        call    setown
.hp:    pop     ax
.hn:    inc     ax
        jmp     .h
.hd:    mov     ax, 2                   ; the chains: their heads
.c:     cmp     ax, [ncl]
        jae     .cd
        push    ax
        call    getown
        cmp     ax, LOSTA
        pop     ax
        jne     .cn
        inc     word [nchains]
.cn:    inc     ax
        jmp     .c
.cd:    call    err_hdr                 ; "   n lost clusters found in m chains."
        mov     dx, s_crlf
        call    print
        mov     ax, [nlost]
        xor     dx, dx
        mov     cx, 4
        call    pdecw
        mov     dx, s_lost2
        call    print
        mov     ax, [nchains]
        xor     dx, dx
        call    pdec
        mov     dx, s_lost3
        call    print
        mov     ax, [nlost]
        mul     word [csize]
        mov     [lostb], ax
        mov     [lostb+2], dx
        cmp     byte [fix], 0
        jne     .ask
        mov     dx, s_would
        jmp     .bytes
.ask:   mov     dx, s_conv              ; "Convert lost chains to files (Y/N)?"
        call    print
        call    getkey
        push    ax
        cmp     al, ' '
        jb      .ne
        call    putc
.ne:    mov     dx, s_crlf
        call    print
        pop     ax
        and     al, 0DFh
        cmp     al, 'Y'
        je      .conv
        call    free_lost
        mov     dx, s_freed
.bytes: push    dx
        mov     ax, [lostb]
        mov     dx, [lostb+2]
        mov     cx, 10
        call    pdecw
        pop     dx
        jmp     print
.conv:  mov     ax, 2                   ; each head: FILEnnnn.CHK
.v:     cmp     ax, [ncl]
        jae     .vd
        push    ax
        call    getown
        cmp     ax, LOSTA
        pop     ax
        jne     .vn
        push    ax
        call    chk_file
        pop     ax
        jc      .vd                     ; (the root is full)
.vn:    inc     ax
        jmp     .v
.vd:    jmp     free_lost               ; (what no head reached: freed)

; the lost clusters still nobody's: free
free_lost:
        mov     ax, 2
.l:     cmp     ax, [ncl]
        jae     .x
        push    ax
        call    getown
        cmp     ax, LOSTB
        pop     ax
        jb      .n
        xor     dx, dx
        call    setown
        call    setfat
.n:     inc     ax
        jmp     .l
.x:     ret

; the lost chain from cluster AX into the root as FILEnnnn.CHK.  CF: the
; root is full (said)
chk_file:
        push    ax
        call    root_free               ; ES:DI = a free entry
        jc      .full
.nm:    mov     ax, [chkn]              ; a name not there yet
        inc     word [chkn]
        call    chk_name
        call    root_has
        jnc     .nm
        mov     si, chkname             ; the entry
        push    di
        mov     cx, 11
        rep     movsb
        pop     di
        xor     ax, ax
        mov     cx, 21
        push    di
        add     di, 11
        rep     stosb
        pop     di
        mov     ah, 2Ch                 ; its time and date: now
        int     21h
        mov     al, cl
        xor     ah, ah
        shl     ax, 5
        mov     bl, dh
        shr     bl, 1
        xor     bh, bh
        or      ax, bx
        mov     bl, ch
        shl     bx, 11
        or      ax, bx
        mov     [es:di+16h], ax
        mov     ah, 2Ah
        int     21h
        sub     cx, 1980
        shl     cx, 9
        mov     al, dh
        xor     ah, ah
        shl     ax, 5
        or      ax, cx
        or      al, dl
        mov     [es:di+18h], ax
        pop     ax
        mov     [es:di+1Ah], ax
        mov     word [pathlen], 3       ; (its path, should its chain be
        push    ax                      ;  said to be wrong)
        call    name
        pop     ax
        inc     word [fid]
        push    es
        push    di
        call    chain                   ; (now its)
        pop     di
        pop     es
        push    ax
        mul     word [csize]
        mov     [es:di+1Ch], ax
        mov     [es:di+1Eh], dx
        inc     word [nuser]
        add     [nuser+2], ax
        adc     [nuser+4], dx
        pop     ax
        mov     ax, [rfree]             ; its sector to be written
        shr     ax, 4
        call    rdirty
        mov     byte [changed], 1
        clc
        ret
.full:  pop     ax
        mov     dx, s_rootf
        call    print
        stc
        ret

; a free root entry -> ES:DI, [rfree] its number.  CF: none
root_free:
        xor     ax, ax
.l:     cmp     ax, [nroot]
        jae     .no
        push    ax
        shl     ax, 1
        add     ax, [rootseg]
        mov     es, ax
        pop     ax
        xor     di, di
        cmp     byte [es:di], 0
        je      .y
        cmp     byte [es:di], 0E5h
        je      .y
        inc     ax
        jmp     .l
.y:     mov     [rfree], ax
        clc
        ret
.no:    stc
        ret

; chkname = "FILEnnnnCHK" for AX
chk_name:
        push    di
        mov     di, chkname + 7
        mov     bx, 10
        mov     cx, 4
.d:     xor     dx, dx
        div     bx
        add     dl, '0'
        mov     [di], dl
        dec     di
        loop    .d
        pop     di
        ret

; is chkname in the root?  CF: no.  ES, DI kept
root_has:
        push    es
        push    di
        xor     ax, ax
.l:     cmp     ax, [nroot]
        jae     .no
        push    ax
        shl     ax, 1
        add     ax, [rootseg]
        mov     es, ax
        pop     ax
        xor     di, di
        cmp     byte [es:di], 0
        je      .no
        mov     si, chkname
        mov     cx, 11
        repe    cmpsb
        je      .y
        inc     ax
        jmp     .l
.y:     clc
        jmp     short .x
.no:    stc
.x:     pop     di
        pop     es
        ret

; ---------------------------------------------------------------------
; /F: the FAT (both copies) and the root's sectors that changed.  CF: DX
write_back:
        cmp     byte [wfail], 0
        jne     .err
        mov     word [k], 0             ; each copy
.c:     mov     ax, [k]
        cmp     ax, [nfat]
        jae     .r
        xor     bp, bp                  ; each sector
.s:     cmp     bp, [spf]
        jae     .cn
        cmp     byte [fatdiff], 0
        jne     .w
        mov     bx, bp
        mov     cx, bx
        and     cl, 7
        mov     al, 1
        shl     al, cl
        shr     bx, 3
        test    [fatdirty+bx], al
        jz      .sn
.w:     mov     ax, [k]
        mul     word [spf]
        add     ax, [rsv]
        add     ax, bp
        xor     dx, dx
        mov     bx, bp
        shl     bx, 5
        add     bx, [fatseg]
        mov     es, bx
        xor     bx, bx
        mov     cx, 1
        call    wrsec
        jc      .err
.sn:    inc     bp
        jmp     .s
.cn:    inc     word [k]
        jmp     .c
.r:     xor     bp, bp                  ; the root
.rs:    cmp     bp, [rsecs]
        jae     .ok
        mov     bx, bp
        mov     cx, bx
        and     cl, 7
        mov     al, 1
        shl     al, cl
        shr     bx, 3
        test    [rootdirty+bx], al
        jz      .rn
        mov     ax, [rootlba]
        add     ax, bp
        xor     dx, dx
        mov     bx, bp
        shl     bx, 5
        add     bx, [rootseg]
        mov     es, bx
        xor     bx, bx
        mov     cx, 1
        call    wrsec
        jc      .err
.rn:    inc     bp
        jmp     .rs
.ok:    push    ds
        pop     es
        clc
        ret
.err:   push    ds
        pop     es
        mov     dx, s_wperr
        cmp     byte [bstat], 3
        je      .e
        mov     dx, s_wrerr
.e:     stc
        ret

; ---------------------------------------------------------------------
;    1457664 bytes total disk space
;      47104 bytes in 2 hidden files
;       2048 bytes in 2 directories
;     123904 bytes in 14 user files
;       1024 bytes in bad sectors
;    1283584 bytes available on disk
;
;     655360 bytes total memory
;     601408 bytes free
figures:
        xor     bx, bx                  ; bad and free clusters
        xor     si, si
        mov     ax, 2
.l:     cmp     ax, [ncl]
        jae     .ld
        push    ax
        call    getfat
        cmp     ax, 0FFF7h
        jne     .lf
        inc     bx
.lf:    or      ax, ax
        jnz     .ln
        inc     si
.ln:    pop     ax
        inc     ax
        jmp     .l
.ld:    push    si
        push    bx
        mov     dx, s_crlf
        call    print
        mov     ax, [nclus]
        mul     word [csize]
        mov     cx, 10
        call    pdecw
        mov     dx, s_total
        call    print
        mov     si, nhid
        mov     dx, s_hid
        call    tally
        mov     si, ndir
        mov     dx, s_dirs
        call    tally
        mov     si, nuser
        mov     dx, s_user
        call    tally
        pop     ax
        or      ax, ax
        jz      .nb
        mul     word [csize]
        mov     cx, 10
        call    pdecw
        mov     dx, s_badb
        call    print
.nb:    pop     ax
        mul     word [csize]
        mov     cx, 10
        call    pdecw
        mov     dx, s_avail
        call    print
        mov     dx, s_crlf
        call    print
        int     12h                     ; the memory
        mov     cx, 1024
        mul     cx
        mov     cx, 10
        call    pdecw
        mov     dx, s_mem
        call    print
        mov     ax, [memfree]
        mov     dx, [memfree+2]
        mov     cx, 10
        call    pdecw
        mov     dx, s_memf
        jmp     print

; "    xxxxx bytes in n hidden files", if there are any: SI = the count
; and its bytes, DX = the words after
tally:  cmp     word [si], 0
        je      .x
        push    dx
        mov     ax, [si+2]
        mov     dx, [si+4]
        mov     cx, 10
        call    pdecw
        mov     dx, s_in
        call    print
        mov     ax, [si]
        xor     dx, dx
        call    pdec
        pop     dx
        call    print
.x:     ret

; ---------------------------------------------------------------------
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
; AX in 2 digits
p2:     push    ax
        aam
        add     ax, '00'
        xchg    al, ah
        call    putc
        xchg    al, ah
        call    putc
        pop     ax
        ret
; DX:AX in decimal: pdec as it is, pdecw right-aligned in CX places
pdec:   xor     cx, cx
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
phex:   mov     cx, 4
.l:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     call    putc
        pop     ax
        loop    .l
        ret

; ---------------------------------------------------------------------
s_dot   db '.          '
s_dotdot db '..         '
chkname db 'FILE0000CHK'
s_nofix db 'Errors found, F parameter not specified', 13, 10
        db 'Corrections will not be written to disk', 13, 10, 13, 10, '$'
s_alloc db '   Allocation error, size adjusted$'
s_inval db '   Has invalid cluster, file truncated$'
s_first db '   First cluster number is invalid, entry truncated$'
s_cross db '   Is cross linked on cluster $'
s_dots  db '   Invalid sub-directory entry$'
s_baddir db '   Invalid sub-directory entry, removed$'
s_dread db '   Cannot read this directory$'
s_fats  db 'The two copies of the File Allocation Table differ$'
s_lost2 db ' lost clusters found in $'
s_lost3 db ' chains.', 13, 10, '$'
s_conv  db 'Convert lost chains to files (Y/N)? $'
s_would db ' bytes disk space would be freed', 13, 10, '$'
s_freed db ' bytes disk space freed', 13, 10, '$'
s_rootf db 'Insufficient room in root directory', 13, 10
        db '   Erase files in root and repeat CHKDSK', 13, 10, '$'
s_vol   db ' Volume $'
s_created db ' created $'
s_ser   db ' Volume Serial Number is $'
s_total db ' bytes total disk space', 13, 10, '$'
s_in    db ' bytes in $'
s_hid   db ' hidden files', 13, 10, '$'
s_dirs  db ' directories', 13, 10, '$'
s_user  db ' user files', 13, 10, '$'
s_badb  db ' bytes in bad sectors', 13, 10, '$'
s_avail db ' bytes available on disk', 13, 10, '$'
s_mem   db ' bytes total memory', 13, 10, '$'
s_memf  db ' bytes free', 13, 10, '$'
s_badsw db 'Invalid parameter', 13, 10, '$'
s_baddrv db 'Invalid drive specification', 13, 10, '$'
s_rom   db 'CHKDSK: R: is the ROM, made whole; nothing to check', 13, 10, '$'
s_notlode db 'CHKDSK: needs Lodestone (other DOSes have their own CHKDSK)', 13, 10, '$'
s_nofm  db 'CHKDSK /F: not on M: (CHKDSK M: checks it)', 13, 10, '$'
s_open  db 'Files are open on drive '
s_d1    db 'A: (a batch file or a program running from it): no /F', 13, 10, '$'
s_rderr db 'Cannot read drive '
s_d2    db 'A:', 13, 10, '$'
s_nondos db 'Probable non-DOS disk in drive '
s_d3    db 'A:', 13, 10, '$'
s_fatbad db 'File allocation table bad, drive '
s_d4    db 'A:', 13, 10, '$'
s_nomem db 'Insufficient memory', 13, 10, '$'
s_wperr db 'Write protect error: nothing corrected', 13, 10, '$'
s_wrerr db 'Disk error writing the corrections', 13, 10, '$'
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
drv     resb 1
unit    resb 1
kind    resb 1
fix     resb 1
verbose resb 1
fat16   resb 1
fatdiff resb 1
hasser  resb 1
xop     resb 1
bstat   resb 1
ctxset  resb 1
inroot  resb 1
emod    resb 1
smod    resb 1
crossed resb 1
loopy   resb 1
hdr     resb 1
nopath  resb 1
changed resb 1
wfail   resb 1
f_sct   resb 1
f_cyl   resb 1
f_head  resb 1
        alignb 2
f_n     resw 1
memfree resw 2
mhand   resw 1
frame   resw 1
tbuf    resw 1
spt     resw 1
heads   resw 1
spc     resw 1
shift   resw 1
csize   resw 1
rsv     resw 1
nfat    resw 1
nroot   resw 1
rsecs   resw 1
spf     resw 1
rootlba resw 1
datalba resw 1
nclus   resw 1
ncl     resw 1
ser     resw 2
fatseg  resw 1
ownseg  resw 1
rootseg resw 1
pk_lba  resw 2                          ; INT 25h/26h's packet
pk_n    resw 1
pk_buf  resw 2
pathlen resw 1
nameend resw 1
curdir  resw 1
parent  resw 1
depth   resw 1
ri      resw 1
dcl     resw 1
dsec    resw 1
dix     resw 1
dent    resw 1
fid     resw 1
nerr    resw 1
rnum    resw 1
nlost   resw 1
nchains resw 1
lostb   resw 2
chkn    resw 1
rfree   resw 1
k       resw 1
nhid    resw 3                          ; count, bytes (dword)
ndir    resw 3
nuser   resw 3
ctx     resb 16
numbuf  resb 14
fatdirty resb 32                        ; a bit a FAT sector
rootdirty resb 32                       ; a bit a root sector
path    resb 3 + MAXDEPTH * 13 + 16
        alignb 2
secbuf  resb 512
        alignb 16
tb1     resb MAXSPT * 512
tb2     resb MAXSPT * 512
        resb 1024
stack_top:
bss_end:
prog_end:
