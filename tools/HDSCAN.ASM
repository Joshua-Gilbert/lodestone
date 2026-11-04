; =====================================================================
;  HDSCAN.COM 1.1  -  the GRiDCase 1520's internal hard disk: what's on
;                     it, and a read of every sector (read-only)
;  Build:  nasm -f bin -o HDSCAN.COM HDSCAN.ASM   (needs io.inc,
;          timing.inc and ata.inc from the same folder)
;  Run  :  HDSCAN         report on screen and to A:\HDSCAN.TXT, the first
;                         partition's boot sector to A:\HDBOOT.BIN
;
;  The 1520's BIOS leaves a drive it doesn't know switched off (HDPROBE),
;  so this reads it through its own registers (1F0h-1F7h), as HDPROBE
;  does:
;   1. the drive: IDENTIFY, the geometry, heads to track 0
;   2. the partition table (sector 0)
;   3. each FAT partition (12 or 16 bit): its boot sector, every directory
;      and file (as DIR /S), the totals, and from the FAT the free and
;      bad-marked space
;   4. every sector of the disk, a track a command; a track with an error
;      is read again a sector at a time to name the bad ones.  Any key
;      stops it
;  Read-only: the commands sent are ECh (identify), 91h (geometry), 10h
;  (recalibrate) and 20h (read).  IRQ 14 is masked meanwhile.
; =====================================================================
cpu 286
org 100h

start:  cld
        mov     sp, stack_top
        mov     bx, (prog_end - start + 100h + 15) / 16
        mov     ah, 4Ah                 ; shrink to our image
        int     21h
        mov     ax, 0F012h              ; multitasking (MT_LIST) with other
        xor     cx, cx                  ;  tasks there?  They may be using C:,
        int     21h                     ;  and this talks to the drive itself
        jc      .one                    ;  (CF: multitasking off)
        cmp     cx, 1
        jbe     .one
        mov     dx, s_tasks
        mov     ah, 9
        int     21h
        mov     ax, 4C01h
        int     21h
.one:
        call    log_open
        mov     dx, s_title
        call    puts
        cmp     word [fh], 0
        jne     .fok
        mov     dx, s_nofile
        call    puts
.fok:   call    pit_init
        in      al, 0A1h                ; IRQ 14 off while we work
        mov     [pic2], al
        or      al, 40h
        out     0A1h, al
        call    drive
        jc      .end
        call    commit
        call    parts
        call    commit
        call    sweep
.end:   mov     dx, HD + 7              ; (any interrupt the drive raised)
        in      al, dx
        mov     al, [pic2]
        out     0A1h, al
        call    pit_done
        mov     dx, s_done
        call    puts
        call    log_close
        mov     ah, 8
        int     21h
        mov     ax, 4C00h
        int     21h

; =====================================================================
; 1. the drive.  CF: it can't be used (said why)
; =====================================================================
drive:  mov     dx, s_drive
        call    puts
        mov     dx, HD + 6
        mov     al, 0A0h
        mov     [r_sdh], al
        out     dx, al
        call    short_wait
        mov     cx, 31 * 18
        call    wait_rdy
        jc      .nrdy
        mov     al, 0ECh
        call    ata_cmd
        jc      .nrdy
        call    wait_drq
        jc      .nrdy
        test    al, 08h
        jz      .noid
        mov     di, secbuf
        call    insec
        mov     dx, s_ind
        call    puts
        mov     si, secbuf + 27 * 2
        mov     cx, 20
        call    pstr
        mov     ax, [secbuf + 1 * 2]
        mov     [cyls], ax
        mov     ax, [secbuf + 3 * 2]
        mov     [heads], ax
        mov     ax, [secbuf + 6 * 2]
        mov     [spt], ax
        mov     ax, [heads]             ; a geometry we can use?
        dec     ax
        cmp     ax, 15
        ja      .badg
        mov     ax, [spt]
        dec     ax
        cmp     ax, 62
        ja      .badg
        cmp     word [cyls], 0
        je      .badg
        mov     al, [spt]               ; sectors a cylinder, and in all
        mul     byte [heads]
        mov     [hs], ax
        mul     word [cyls]
        mov     [total], ax
        mov     [total+2], dx
        mov     dx, s_comma
        call    puts
        mov     ax, [cyls]
        call    pdec
        mov     dx, s_x
        call    puts
        mov     ax, [heads]
        call    pdec
        mov     dx, s_x
        call    puts
        mov     ax, [spt]
        call    pdec
        mov     dx, s_eq
        call    puts
        mov     ax, [total]
        mov     dx, [total+2]
        call    pmb
        call    crlf
        ; the geometry, as the BIOS sets it, and the heads to track 0
        mov     al, [heads]
        dec     al
        or      al, 0A0h
        mov     [r_sdh], al
        mov     al, [spt]
        mov     [r_cnt], al
        mov     al, 91h
        call    ata_cmd
        call    short_wait
        mov     cx, 5 * 18
        call    wait_nb
        mov     byte [r_sdh], 0A0h
        mov     al, 10h
        call    ata_cmd
        jc      .stuck
        call    short_wait
        mov     cx, 31 * 18
        call    wait_nb
        jc      .stuck
        test    al, 01h
        jnz     .stuck
        mov     dx, s_recok
        call    puts
        clc
        ret
.stuck: mov     dx, s_stuck
        jmp     .no
.nrdy:  mov     dx, s_nrdy
        jmp     .no
.noid:  mov     dx, s_noid
        jmp     .no
.badg:  mov     dx, s_badg
.no:    call    puts
        stc
        ret

; =====================================================================
; 2. the partition table, and 3. each FAT partition
; =====================================================================
parts:  mov     dx, s_parts
        call    puts
        xor     ax, ax
        xor     dx, dx
        mov     di, mbrbuf
        call    read_lba
        jc      .x
        cmp     word [mbrbuf + 510], 0AA55h
        je      .pt
        mov     dx, s_nopt
        jmp     puts
.pt:    mov     si, mbrbuf + 446
        mov     bl, '1'
.e:     cmp     byte [si + 4], 0
        je      .nx
        mov     dx, s_ind
        call    puts
        mov     al, bl
        call    putc
        mov     dx, s_ptt
        call    puts
        mov     al, [si + 4]
        call    phex8
        mov     dx, s_ptb
        call    puts
        mov     al, [si]
        call    phex8
        mov     dx, s_ptf
        call    puts
        mov     ax, [si + 8]
        mov     dx, [si + 10]
        xor     cl, cl
        call    pdec32
        mov     dx, s_comma
        call    puts
        mov     ax, [si + 12]
        mov     dx, [si + 14]
        xor     cl, cl
        call    pdec32
        mov     dx, s_pts
        call    puts
        mov     ax, [si + 12]
        mov     dx, [si + 14]
        call    pmb
        call    isfat
        mov     dx, s_ptfat
        je      .p
        mov     dx, s_ptoth
.p:     call    puts
.nx:    add     si, 16
        inc     bl
        cmp     bl, '5'
        jb      .e
        ; each FAT partition in turn
        mov     si, mbrbuf + 446
        mov     byte [pno], '1'
.v:     call    isfat
        jne     .vn
        push    si
        call    vol
        call    commit
        pop     si
.vn:    add     si, 16
        inc     byte [pno]
        cmp     byte [pno], '5'
        jb      .v
.x:     ret

; ZF: the partition entry at SI is FAT (01h, 04h, 06h, 0Eh)
isfat:  mov     al, [si + 4]
        cmp     al, 01h
        je      .x
        cmp     al, 04h
        je      .x
        cmp     al, 06h
        je      .x
        cmp     al, 0Eh
.x:     ret

; the FAT partition at SI (an entry of the table)
vol:    mov     dx, s_vol
        call    puts
        mov     al, [pno]
        call    putc
        mov     dx, s_vol2
        call    puts
        mov     ax, [si + 8]
        mov     dx, [si + 10]
        mov     [p_lba], ax
        mov     [p_lba+2], dx
        mov     di, bootbuf
        call    read_lba
        jnc     .rd
        ret
.rd:    cmp     byte [bootdone], 0      ; (the first one to A:\HDBOOT.BIN)
        jne     .bs
        mov     byte [bootdone], 1
        mov     dx, n_boot
        mov     si, bootbuf
        call    save512
.bs:    cmp     word [bootbuf + 0Bh], 512  ; a BPB we can use?
        jne     .nobpb
        mov     al, [bootbuf + 0Dh]     ; sectors a cluster: 1, 2, 4 .. 64
        or      al, al
        jz      .nobpb
        cmp     al, 64
        ja      .nobpb
        mov     ah, al
        dec     ah
        test    al, ah
        jnz     .nobpb
        mov     al, [bootbuf + 10h]     ; 1 or 2 FATs
        dec     al
        cmp     al, 1
        ja      .nobpb
        cmp     word [bootbuf + 0Eh], 0
        je      .nobpb
        cmp     word [bootbuf + 16h], 0
        je      .nobpb
        cmp     word [bootbuf + 11h], 0
        jne     .bpb
.nobpb: mov     dx, s_nobpb
        jmp     puts
.bpb:   ; who formatted it, and its label and serial number
        mov     dx, s_oem
        call    puts
        mov     si, bootbuf + 3
        mov     cx, 8
        call    pchars
        mov     al, '"'
        call    putc
        cmp     byte [bootbuf + 26h], 29h
        jne     .nol
        mov     dx, s_lbl
        call    puts
        mov     si, bootbuf + 2Bh
        mov     cx, 11
        call    pchars
        mov     dx, s_ser
        call    puts
        mov     ax, [bootbuf + 29h]
        call    phex16
        mov     al, '-'
        call    putc
        mov     ax, [bootbuf + 27h]
        call    phex16
.nol:   call    crlf
        ; where things are
        xor     ax, ax
        mov     al, [bootbuf + 0Dh]
        mov     [spc], ax
        shl     ax, 4
        mov     [epc], ax               ; directory entries a cluster
        mov     ax, [p_lba]
        mov     dx, [p_lba+2]
        add     ax, [bootbuf + 0Eh]
        adc     dx, 0
        mov     [fat_lba], ax
        mov     [fat_lba+2], dx
        mov     ax, [bootbuf + 16h]     ; the FATs
        xor     cx, cx
        mov     cl, [bootbuf + 10h]
        mul     cx
        add     ax, [fat_lba]
        adc     dx, [fat_lba+2]
        mov     [root_lba], ax
        mov     [root_lba+2], dx
        mov     cx, [bootbuf + 11h]     ; the root directory
        mov     [rootents], cx
        add     cx, 15
        shr     cx, 4
        add     ax, cx
        adc     dx, 0
        mov     [data_lba], ax
        mov     [data_lba+2], dx
        sub     ax, [p_lba]             ; -> sectors before the data
        sbb     dx, [p_lba+2]
        mov     bx, ax
        mov     ax, [bootbuf + 13h]     ; its size: 16 bits, or 32 (DOS 4)
        xor     dx, dx
        or      ax, ax
        jnz     .t16
        mov     ax, [bootbuf + 20h]
        mov     dx, [bootbuf + 22h]
.t16:   sub     ax, bx
        sbb     dx, 0
        jc      .nobpb
        mov     cx, [spc]
        call    ldiv
        or      dx, dx                  ; (more than 65535: not FAT12/16)
        jnz     .nobpb
        mov     [clusters], ax
        mov     byte [fat16], 0
        cmp     ax, 4085
        jb      .f12
        mov     byte [fat16], 1
.f12:   ; "FAT16, 4 sectors (2 KB) a cluster, 59321 clusters; 2 FATs of
        ; 232 sectors; 512 root entries"
        mov     dx, s_fat12
        cmp     byte [fat16], 0
        je      .ft
        mov     dx, s_fat16
.ft:    call    puts
        mov     ax, [spc]
        call    pdec
        mov     dx, s_spc
        call    puts
        mov     ax, [spc]
        shr     ax, 1
        jz      .half
        call    pdec
        mov     dx, s_kbc
        jmp     .kb
.half:  mov     dx, s_halfk
.kb:    call    puts
        mov     ax, [clusters]
        call    pdec
        mov     dx, s_clus
        call    puts
        mov     al, [bootbuf + 10h]
        xor     ah, ah
        call    pdec
        mov     dx, s_fats
        call    puts
        mov     ax, [bootbuf + 16h]
        call    pdec
        mov     dx, s_fats2
        call    puts
        mov     ax, [rootents]
        call    pdec
        mov     dx, s_roots
        call    puts
        ; every directory, from the root
        xor     ax, ax
        mov     [n_dirs], ax
        mov     [n_files], ax
        mov     [n_bytes], ax
        mov     [n_bytes+2], ax
        mov     [n_del], ax
        mov     [depth], ax
        mov     word [dir_at+2], 0FFFFh ; (the caches: nothing yet)
        mov     word [fat_at+2], 0FFFFh
        mov     al, [drvl]              ; C: for the first, then D:..
        inc     byte [drvl]
        mov     [pathbuf], al
        mov     word [pathbuf+1], ':\'
        mov     byte [pathbuf+3], 0
        mov     word [plen], 3
        xor     ax, ax                  ; (the root)
        call    walk
        ; altogether
        mov     dx, s_all
        call    puts
        mov     ax, [n_dirs]
        call    pdec
        mov     dx, s_all2
        call    puts
        mov     ax, [n_files]
        call    pdec
        mov     dx, s_all3
        call    puts
        mov     ax, [n_bytes]
        mov     dx, [n_bytes+2]
        xor     cl, cl
        call    pdec32
        mov     dx, s_all4
        call    puts
        cmp     word [n_del], 0
        je      .nd
        mov     dx, s_del
        call    puts
        mov     ax, [n_del]
        call    pdec
        mov     dx, s_del2
        call    puts
.nd:    call    crlf
        ; the FAT: free clusters, and those the format marked bad
        xor     ax, ax
        mov     [n_free], ax
        mov     [n_badc], ax
        mov     cx, [clusters]
        mov     ax, 2
.fl:    push    ax
        call    fat_next
        or      ax, ax
        jnz     .fu
        inc     word [n_free]
.fu:    cmp     ax, 0FFF7h
        jne     .fn
        inc     word [n_badc]
.fn:    pop     ax
        inc     ax
        loop    .fl
        mov     dx, s_free
        call    puts
        mov     ax, [n_free]
        mul     word [spc]
        shr     dx, 1
        rcr     ax, 1
        xor     cl, cl
        call    pdec32
        mov     dx, s_free2
        call    puts
        mov     ax, [n_free]
        call    pdec
        mov     dx, s_free3
        call    puts
        mov     ax, [n_badc]
        call    pdec
        mov     dx, s_free4
        jmp     puts

; ---------------------------------------------------------------------
; the directory whose first cluster is AX (0: the root), named by pathbuf,
; and after it each of its subdirectories in turn (as DIR /S)
; ---------------------------------------------------------------------
walk:   mov     bx, [depth]
        cmp     bx, MAXDEPTH
        jb      .ok
        mov     dx, s_deep
        jmp     puts
.ok:    shl     bx, 1
        mov     [lvl_start + bx], ax
        mov     ax, [plen]
        mov     [lvl_plen + bx], ax
        inc     word [n_dirs]
        call    crlf
        mov     dx, s_ind
        call    puts
        mov     dx, pathbuf
        call    putz
        call    crlf
        ; pass 1: the entries
        xor     ax, ax
        mov     [d_files], ax
        mov     [d_bytes], ax
        mov     [d_bytes+2], ax
        mov     [lvl_idx + bx], ax
.p1:    call    dir_ent
        jc      .p1e
        mov     al, [si]
        or      al, al
        jz      .p1e                    ; (the end of the directory)
        cmp     al, 0E5h
        je      .del
        mov     al, [si + 11]
        cmp     al, 0Fh                 ; (a long name's piece)
        je      .n1
        test    al, 08h
        jnz     .lbl
        cmp     byte [si], '.'
        je      .n1
        call    pent
        test    byte [si + 11], 10h
        jnz     .n1
        inc     word [d_files]
        mov     ax, [si + 1Ch]
        add     [d_bytes], ax
        mov     ax, [si + 1Eh]
        adc     [d_bytes+2], ax
        jmp     .n1
.lbl:   mov     dx, s_vlab
        call    puts
        mov     cx, 11
        call    pchars
        mov     al, '"'
        call    putc
        call    crlf
        jmp     .n1
.del:   inc     word [n_del]
.n1:    inc     word [lvl_idx + bx]
        jmp     .p1
.p1e:   mov     dx, s_dtot
        call    puts
        mov     ax, [d_files]
        call    pdec
        add     [n_files], ax
        mov     dx, s_dtot2
        call    puts
        mov     ax, [d_bytes]
        mov     dx, [d_bytes+2]
        add     [n_bytes], ax
        adc     [n_bytes+2], dx
        xor     cl, cl
        call    pdec32
        mov     dx, s_dtot3
        call    puts
        call    commit                  ; (on the floppy as it goes)
        ; pass 2: into each subdirectory
        mov     word [lvl_idx + bx], 0
.p2:    call    dir_ent
        jc      .x
        mov     al, [si]
        or      al, al
        jz      .x
        cmp     al, 0E5h
        je      .n2
        cmp     al, '.'
        je      .n2
        mov     al, [si + 11]
        cmp     al, 0Fh
        je      .n2
        test    al, 08h
        jnz     .n2
        test    al, 10h
        jz      .n2
        mov     ax, [si + 1Ah]          ; its first cluster
        cmp     ax, 2
        jb      .n2
        cmp     word [plen], PATHMAX - 14
        ja      .n2
        call    pappend
        inc     word [depth]
        call    walk
        dec     word [depth]
        mov     bx, [depth]
        shl     bx, 1
        mov     ax, [lvl_plen + bx]     ; the name off again
        mov     [plen], ax
        mov     di, pathbuf
        add     di, ax
        mov     byte [di], 0
.n2:    inc     word [lvl_idx + bx]
        jmp     .p2
.x:     ret

; "\NAME.EXT" of the entry at SI onto pathbuf
pappend:
        push    ax
        mov     di, pathbuf
        add     di, [plen]
        cmp     byte [di - 1], '\'
        je      .n
        mov     byte [di], '\'
        inc     di
.n:     mov     cx, 8
        push    si
.a:     lodsb
        cmp     al, ' '
        je      .e
        stosb
        loop    .a
.e:     pop     si
        cmp     byte [si + 8], ' '
        je      .z
        mov     al, '.'
        stosb
        push    si
        add     si, 8
        mov     cx, 3
.b:     lodsb
        cmp     al, ' '
        je      .f
        stosb
        loop    .b
.f:     pop     si
.z:     mov     byte [di], 0
        sub     di, pathbuf
        mov     [plen], di
        pop     ax
        ret

; entry lvl_idx of the directory lvl_start, at this depth (BX = depth * 2)
; -> SI.  CF: past its end, or unreadable.  BX kept
dir_ent:
        push    bx
        mov     ax, [lvl_start + bx]
        mov     cx, [lvl_idx + bx]
        cmp     cx, 8192                ; (a chain gone round in a loop)
        jae     .end
        or      ax, ax
        jnz     .sub
        cmp     cx, [rootents]          ; the root: a fixed place
        jae     .end
        mov     ax, cx
        shr     ax, 4
        xor     dx, dx
        add     ax, [root_lba]
        adc     dx, [root_lba+2]
        jmp     .rd
.sub:   push    ax                      ; a subdirectory: cluster i / epc
        mov     ax, cx                  ;  of its chain
        xor     dx, dx
        div     word [epc]
        mov     cx, ax                  ; (clusters to follow)
        mov     bx, dx                  ; (entry in that cluster)
        pop     ax
        jcxz    .c
.f:     call    fat_next
        cmp     ax, 2
        jb      .end
        cmp     ax, 0FFF0h
        jae     .end
        loop    .f
.c:     sub     ax, 2                   ; -> its first sector, plus
        mul     word [spc]
        add     ax, [data_lba]
        adc     dx, [data_lba+2]
        shr     bx, 4
        add     ax, bx
        adc     dx, 0
.rd:    cmp     ax, [dir_at]            ; (still in the buffer?)
        jne     .r
        cmp     dx, [dir_at+2]
        je      .in
.r:     mov     di, dirbuf
        call    read_lba
        jc      .bad
        mov     [dir_at], ax
        mov     [dir_at+2], dx
.in:    pop     bx
        mov     si, [lvl_idx + bx]
        and     si, 15
        shl     si, 5
        add     si, dirbuf
        clc
        ret
.bad:   mov     word [dir_at+2], 0FFFFh
.end:   pop     bx
        stc
        ret

; AX = a cluster -> AX = the next in its chain (FAT12's FF0h-FFFh as
; FFF0h-FFFFh: FFF7h bad, FFF8h on the end).  BX, CX, DX kept
fat_next:
        push    bx
        push    cx
        push    dx
        mov     cx, ax
        xor     dx, dx
        cmp     byte [fat16], 0
        je      .f12
        shl     ax, 1                   ; FAT16: 2 bytes a cluster
        rcl     dx, 1
        call    fat_word
        jmp     .x
.f12:   shr     ax, 1                   ; FAT12: 1.5
        add     ax, cx
        call    fat_word
        test    cl, 1
        jz      .ev
        shr     ax, 4
        jmp     .w
.ev:    and     ax, 0FFFh
.w:     cmp     ax, 0FF0h
        jb      .x
        or      ax, 0F000h
.x:     pop     dx
        pop     cx
        pop     bx
        ret

; the word at byte DX:AX of the FAT -> AX (an unreadable sector: FFFFh)
fat_word:
        push    ax
        push    dx
        call    fat_byte
        mov     bl, al
        pop     dx
        pop     ax
        add     ax, 1
        adc     dx, 0
        call    fat_byte
        mov     ah, al
        mov     al, bl
        ret

; the byte at DX:AX of the FAT -> AL.  BX, CX, DI kept
fat_byte:
        push    bx
        push    cx
        push    di
        mov     bx, ax
        and     bx, 511
        mov     cx, 9                   ; -> its sector
.s:     shr     dx, 1
        rcr     ax, 1
        loop    .s
        add     ax, [fat_lba]
        adc     dx, [fat_lba+2]
        cmp     ax, [fat_at]
        jne     .r
        cmp     dx, [fat_at+2]
        je      .in
.r:     mov     di, fatbuf
        call    read_lba
        jc      .bad
        mov     [fat_at], ax
        mov     [fat_at+2], dx
.in:    mov     al, [fatbuf + bx]
.x:     pop     di
        pop     cx
        pop     bx
        ret
.bad:   mov     word [fat_at+2], 0FFFFh
        mov     al, 0FFh
        jmp     .x

; one directory entry (SI): "  COMMAND  COM      47845  1991-04-09 05:00  r h s"
pent:   pusha
        mov     dx, s_ind2
        call    puts
        mov     al, [si]
        cmp     al, 05h                 ; (05h stands for E5h)
        jne     .f
        mov     al, 0E5h
.f:     call    pch
        push    si
        inc     si
        mov     cx, 7
        call    pchars0
        mov     al, ' '
        call    putc
        mov     cx, 3
        call    pchars0
        pop     si
        test    byte [si + 11], 10h
        jz      .file
        mov     dx, s_dirm
        call    puts
        jmp     .date
.file:  mov     ax, [si + 1Ch]
        mov     dx, [si + 1Eh]
        mov     cl, 11
        call    pdec32
.date:  mov     dx, s_2sp
        call    puts
        mov     bx, [si + 18h]          ; yyyy-mm-dd
        mov     ax, bx
        shr     ax, 9
        add     ax, 1980
        call    pdec
        mov     al, '-'
        call    putc
        mov     ax, bx
        shr     ax, 5
        and     al, 15
        call    p2z
        mov     al, '-'
        call    putc
        mov     al, bl
        and     al, 31
        call    p2z
        mov     al, ' '
        call    putc
        mov     bx, [si + 16h]          ; hh:mm
        mov     al, bh
        shr     al, 3
        call    p2z
        mov     al, ':'
        call    putc
        mov     ax, bx
        shr     ax, 5
        and     al, 63
        call    p2z
        mov     bl, [si + 11]           ; read-only, hidden, system
        mov     si, s_attrs
        mov     cx, 3
.a:     shr     bl, 1
        jnc     .na
        mov     al, ' '
        call    putc
        mov     al, [si]
        call    putc
.na:    inc     si
        loop    .a
        call    crlf
        popa
        ret

; =====================================================================
; 4. every sector
; =====================================================================
sweep:  mov     dx, s_sweep
        call    puts
        call    tick
        mov     [t_start], ax
        mov     [t_blk], ax
        xor     ax, ax
        mov     [c_cyl], ax
        mov     [n_bad], ax
        mov     [n_rd], ax
        mov     [n_rd+2], ax
        mov     [blk_bad], ax
        mov     [blk_cyl], ax
        mov     byte [n_busy], 0
.cyl:   mov     ah, 1                   ; a key stops it
        int     16h
        jz      .go
        xor     ah, ah
        int     16h
        mov     byte [f_key], 1
        mov     dx, s_key
        jmp     .stop
.go:    mov     byte [c_head], 0
.trk:   mov     ax, [c_cyl]             ; the whole track: sectors 1..spt
        mov     [r_cyl], ax
        mov     al, [c_head]
        or      al, 0A0h
        mov     [r_sdh], al
        mov     byte [r_sec], 1
        mov     al, [spt]
        mov     [r_cnt], al
        mov     al, 20h
        call    ata_cmd
        jc      .busy
        mov     cx, [spt]
.sec:   call    wait_sec
        jc      .terr
        mov     di, secbuf
        call    insec
        add     word [n_rd], 1
        adc     word [n_rd+2], 0
        loop    .sec
        mov     byte [n_busy], 0
        jmp     .nh
.terr:  cmp     al, 0FFh
        je      .busy
        call    retrack                 ; an error: a sector at a time
        cmp     word [n_bad], MAXBAD
        jb      .nh
        mov     dx, s_many
        jmp     .stop
.busy:  mov     dx, s_tbusy
        call    pwhere
        call    crlf
        inc     byte [n_busy]
        cmp     byte [n_busy], 3
        jb      .nh
        mov     dx, s_gone
        jmp     .stop
.nh:    inc     byte [c_head]
        mov     al, [c_head]
        cmp     al, [heads]
        jb      .trk
        inc     word [c_cyl]
        mov     ax, [c_cyl]             ; every 100 cylinders, and the last
        cmp     ax, [cyls]
        je      .blk
        xor     dx, dx
        mov     cx, 100
        div     cx
        or      dx, dx
        jnz     .cyl
.blk:   call    pblock
        mov     ax, [c_cyl]
        cmp     ax, [cyls]
        jb      .cyl
        mov     dx, s_swdone
        jmp     .sum
.stop:  call    puts                    ; stopped: say where
        mov     ax, [c_cyl]
        call    pdec
        call    crlf
        mov     dx, s_swpart
.sum:   ; "All 762 cylinders read in 152.3 s (795 KB/s): 0 bad sectors."
        call    puts
        call    tick
        sub     ax, [t_start]
        push    ax
        call    psecs
        mov     dx, s_rate
        call    puts
        pop     ax                      ; KB/s = sectors * 5 / tenths of a s
        mov     cx, 100
        mul     cx
        mov     cx, 182
        div     cx
        or      ax, ax
        jnz     .t
        inc     ax
.t:     mov     bx, ax
        mov     ax, [n_rd]
        mov     dx, [n_rd+2]
        mov     cx, 5
        call    mul32
        mov     cx, bx
        call    ldiv
        xor     cl, cl
        call    pdec32
        mov     dx, s_rate2
        call    puts
        mov     ax, [n_bad]
        call    pdec
        mov     dx, s_badsum
        call    puts
        mov     dx, s_dirty
        cmp     word [n_bad], 0
        jne     .v
        mov     dx, s_vkey
        cmp     byte [f_key], 0
        jne     .v
        mov     dx, s_clean
.v:     cmp     byte [n_busy], 3
        jb      .vp
        mov     dx, s_vgone
.vp:    jmp     puts

; the track c_cyl / c_head again, a sector at a time: each one that
; doesn't read, named
retrack:
        mov     byte [c_sec], 1
.s:     mov     ax, [c_cyl]
        mov     [r_cyl], ax
        mov     al, [c_head]
        or      al, 0A0h
        mov     [r_sdh], al
        mov     al, [c_sec]
        mov     [r_sec], al
        mov     byte [r_cnt], 1
        mov     al, 20h
        call    ata_cmd
        jc      .busy
        call    wait_sec
        jc      .bad
        mov     di, secbuf
        call    insec
        add     word [n_rd], 1
        adc     word [n_rd+2], 0
        jmp     .n
.busy:  mov     al, 0FFh
.bad:   inc     word [n_bad]
        inc     word [blk_bad]
        push    ax
        mov     dx, s_bad
        call    pwhere
        mov     dx, s_rs
        call    puts
        mov     al, [c_sec]
        xor     ah, ah
        call    pdec
        mov     dx, s_lba               ; (LBA, as the partitions count)
        call    puts
        mov     ax, [c_cyl]
        mul     word [hs]
        mov     bx, ax
        mov     al, [c_head]
        mul     byte [spt]
        add     ax, bx
        adc     dx, 0
        mov     bl, [c_sec]
        dec     bl
        xor     bh, bh
        add     ax, bx
        adc     dx, 0
        xor     cl, cl
        call    pdec32
        mov     al, ')'
        call    putc
        pop     ax
        cmp     al, 0FFh
        je      .nb
        mov     dx, HD + 1
        in      al, dx
        call    perr
        jmp     .n
.nb:    mov     dx, s_busy
        call    puts
.n:     inc     byte [c_sec]
        mov     al, [c_sec]
        cmp     al, [spt]
        jbe     .s
        ret

; DX = what, then " cylinder C head H"
pwhere: call    puts
        mov     dx, s_cyl
        call    puts
        mov     ax, [c_cyl]
        call    pdec
        mov     dx, s_head
        call    puts
        mov     al, [c_head]
        xor     ah, ah
        jmp     pdec

; "  cylinders 100-199: ok (24.5 s)", or "3 bad sectors"
pblock: mov     dx, s_blk
        call    puts
        mov     ax, [blk_cyl]
        mov     cl, 3
        call    pdecw
        mov     al, '-'
        call    putc
        mov     ax, [c_cyl]
        dec     ax
        mov     cl, 3
        call    pdecw
        mov     dx, s_colon
        call    puts
        mov     dx, s_ok
        mov     ax, [blk_bad]
        or      ax, ax
        jz      .ok
        call    pdec
        mov     dx, s_nbad
.ok:    call    puts
        mov     dx, s_open
        call    puts
        call    tick
        sub     ax, [t_blk]
        call    psecs
        mov     al, ')'
        call    putc
        call    crlf
        call    commit
        call    tick
        mov     [t_blk], ax
        mov     ax, [c_cyl]
        mov     [blk_cyl], ax
        mov     word [blk_bad], 0
        ret

; AX ticks -> "24.5 s"
psecs:  mov     cx, 100
        mul     cx
        mov     cx, 182
        div     cx                      ; tenths
        xor     dx, dx
        mov     cx, 10
        div     cx
        call    pdec
        mov     al, '.'
        call    putc
        mov     al, dl
        add     al, '0'
        call    putc
        mov     dx, s_sec
        jmp     puts

; =====================================================================
; the drive (more in ata.inc)
; =====================================================================
; read sector DX:AX (counted from 0, as the partition table does) to DI.
; CF: it can't be (said so).  All registers kept
read_lba:
        pusha
        mov     [cur_lba], ax
        mov     [cur_lba+2], dx
        push    di
        mov     cx, [hs]
        call    ldiv                    ; DX:AX = cylinder, BX = the rest
        mov     [r_cyl], ax
        mov     ax, bx
        xor     dx, dx
        div     word [spt]              ; AX = head, DX = sector - 1
        or      al, 0A0h
        mov     [r_sdh], al
        inc     dx
        mov     [r_sec], dl
        mov     byte [r_cnt], 1
        mov     al, 20h
        call    ata_cmd
        pop     di
        jc      .busy
        call    wait_sec
        jc      .bad
        call    insec
        popa
        clc
        ret
.bad:   cmp     al, 0FFh
        je      .busy
        mov     dx, s_rdbad
        call    plba
        mov     dx, HD + 1
        in      al, dx
        call    perr
        jmp     .x
.busy:  mov     dx, s_rdbad
        call    plba
        mov     dx, s_busy
        call    puts
.x:     popa
        stc
        ret

plba:   call    puts
        mov     ax, [cur_lba]
        mov     dx, [cur_lba+2]
        xor     cl, cl
        jmp     pdec32

; the next sector of a read: BSY clear (10 s), then DRQ.  CF: an error
; (AL = status) or no answer (AL = FFh).  CX kept
wait_sec:
        push    bx
        push    cx
        push    dx
        mov     dx, HD + 7
        in      al, dx
        test    al, 80h
        jz      .nb
        call    tick
        mov     bx, ax
.l:     in      al, dx
        test    al, 80h
        jz      .nb
        push    ax
        call    tick
        sub     ax, bx
        cmp     ax, 10 * 18
        pop     ax
        jb      .l
        mov     al, 0FFh
        jmp     .e
.nb:    test    al, 01h
        jnz     .e
        test    al, 08h
        jnz     .x                      ; (CF clear)
        call    tick                    ; neither: give DRQ a moment
        mov     bx, ax
.d:     in      al, dx
        test    al, 89h
        jz      .w
        test    al, 80h
        jz      .nb
.w:     push    ax
        call    tick
        sub     ax, bx
        cmp     ax, 18
        pop     ax
        jb      .d
.e:     stc
.x:     pop     dx
        pop     cx
        pop     bx
        ret

; 256 words from the drive to DI (DI moves on)
insec:  push    cx
        push    dx
        mov     cx, 256
        mov     dx, HD
        rep     insw
        pop     dx
        pop     cx
        ret

; =====================================================================
; printing
; =====================================================================
; DX:AX in decimal, right-aligned in CL columns (0: as long as it is)
pdec32: pusha
        mov     di, numbuf + 11
        mov     byte [di], '$'
        push    cx
        mov     cx, 10
.d:     call    ldiv
        dec     di
        add     bl, '0'
        mov     [di], bl
        mov     si, ax
        or      si, dx
        jnz     .d
        pop     cx
        mov     ax, numbuf + 11
        sub     ax, di
        xor     ch, ch
.p:     cmp     ax, cx
        jae     .o
        push    ax
        mov     al, ' '
        call    putc
        pop     ax
        inc     ax
        jmp     .p
.o:     mov     dx, di
        call    puts
        popa
        ret

; DX:AX sectors -> "121 MB" (MB as 1953 sectors, as HDPROBE), or KB
pmb:    push    bx
        push    cx
        cmp     dx, 2
        jb      .kb
        mov     cx, 1953
        call    ldiv
        call    pdec
        mov     dx, s_mb
        jmp     .x
.kb:    shr     dx, 1
        rcr     ax, 1
        call    pdec
        mov     dx, s_kb
.x:     call    puts
        pop     cx
        pop     bx
        ret

; AL (0-99) as two digits
p2z:    push    ax
        aam
        xchg    al, ah
        add     al, '0'
        call    putc
        mov     al, ah
        add     al, '0'
        call    putc
        pop     ax
        ret

; CX characters at SI (SI moves on), control characters as '?'
; (pchars0: the same; pch: AL alone)
pchars:
pchars0:
        lodsb
        call    pch
        loop    pchars0
        ret
pch:    cmp     al, ' '
        jae     .p
        mov     al, '?'
.p:     jmp     putc

; DS:DX ASCIIZ
putz:   pusha
        mov     si, dx
.l:     lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     .l
.x:     popa
        ret

; 512 bytes at SI to the file named at DX; quietly skipped if it can't be
save512:
        pusha
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
        mov     bx, ax
        mov     dx, si
        mov     cx, 512
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     popa
        ret

%include "io.inc"
%include "timing.inc"
%include "ata.inc"

; =====================================================================
; data
; =====================================================================
MAXDEPTH equ 24
PATHMAX  equ 128
MAXBAD   equ 100

s_tasks db 'HDSCAN: other tasks are running, and may be using the hard disk.',13,10
        db 'End them first, then run HDSCAN with Shift-Return in the Executive.',13,10,'$'
s_title db 'HDSCAN 1.1 - the GRiDCase 1520',39,'s internal hard disk: what',39,'s on it, and every',13,10
        db 'sector read (read-only)',13,10,'$'
s_nofile db '  (A:\HDSCAN.TXT could not be made: screen only)',13,10,'$'
s_drive db 13,10,'[1] THE DRIVE',13,10,'$'
s_nrdy  db '  It doesn',39,'t answer, or isn',39,'t ready in 31 s: run HDPROBE.',13,10,'$'
s_noid  db '  It won',39,'t identify itself: run HDPROBE.',13,10,'$'
s_badg  db 13,10,'  Its geometry doesn',39,'t make sense: run HDPROBE.',13,10,'$'
s_stuck db '  The heads won',39,'t go to track 0: stuck again?  HDPROBE /X may free them.',13,10,'$'
s_recok db '  Geometry set, heads to track 0: ok',13,10,'$'
s_comma db ', $'
s_x     db ' x $'
s_eq    db ' = $'
s_parts db 13,10,'[2] PARTITIONS (sector 0)',13,10,'$'
s_nopt  db '  No partition table (sector 0 doesn',39,'t end 55 AA).',13,10,'$'
s_ptt   db ': type $'
s_ptb   db '  boot $'
s_ptf   db '  from sector $'
s_pts   db ' sectors = $'
s_ptfat db '  FAT',13,10,'$'
s_ptoth db '  (not FAT: not looked into)',13,10,'$'
s_vol   db 13,10,'[3] PARTITION $'
s_vol2  db ': WHAT',39,'S ON IT',13,10,'$'
s_nobpb db '  Its boot sector doesn',39,'t describe a FAT disk we can read.',13,10,'$'
s_oem   db '  Formatted by "$'
s_lbl   db '   label "$'
s_ser   db '"   serial $'
s_fat12 db '  FAT12, $'
s_fat16 db '  FAT16, $'
s_spc   db ' sector(s) ($'
s_kbc   db ' KB) a cluster, $'
s_halfk db '0.5 KB) a cluster, $'
s_clus  db ' clusters; $'
s_fats  db ' FAT(s) of $'
s_fats2 db ' sectors; $'
s_roots db ' root entries',13,10,'$'
s_deep  db '  (directories nested too deep: not followed)',13,10,'$'
s_vlab  db '    volume label "$'
s_dirm  db '      <DIR>$'
s_2sp   db '  $'
s_attrs db 'rhs'
s_dtot  db '    $'
s_dtot2 db ' file(s), $'
s_dtot3 db ' bytes',13,10,'$'
s_all   db 13,10,'  Altogether: $'
s_all2  db ' directories, $'
s_all3  db ' files, $'
s_all4  db ' bytes.$'
s_del   db '  ($'
s_del2  db ' deleted entries.)$'
s_free  db '  Free: $'
s_free2 db ' KB ($'
s_free3 db ' clusters).  Marked bad by its format: $'
s_free4 db ' clusters.',13,10,'$'
s_sweep db 13,10,'[4] EVERY SECTOR (a track a read; any key stops)',13,10,'$'
s_blk   db '  cylinders $'
s_colon db ': $'
s_ok    db 'ok$'
s_nbad  db ' bad sector(s)$'
s_open  db '  ($'
s_sec   db ' s$'
s_tbusy db '  no answer:$'
s_bad   db '  bad:$'
s_cyl   db ' cylinder $'
s_head  db ' head $'
s_rs    db ' sector $'
s_lba   db ' (sector $'
s_busy  db ': no answer in time',13,10,'$'
s_rdbad db '  sector $'
s_key   db '  Stopped (a key) at cylinder $'
s_many  db '  Too many bad sectors: stopped at cylinder $'
s_gone  db '  The drive stopped answering: stopped at cylinder $'
s_swdone db 13,10,'  All read in $'
s_swpart db 13,10,'  Read until then in $'
s_rate  db ' ($'
s_rate2 db ' KB/s): $'
s_badsum db ' bad sector(s).',13,10,'$'
s_clean db '  Every sector reads: the surface and the heads are fine.',13,10,'$'
s_dirty db '  Some sectors don',39,'t read (above): their clusters should be marked bad',13,10
        db '  before the disk holds anything.',13,10,'$'
s_vkey  db '  None bad so far; the rest wasn',39,'t read.',13,10,'$'
s_vgone db '  It stopped answering part way: stuck again?  HDPROBE /X, then HDSCAN.',13,10,'$'
s_ind   db '  $'
s_ind2  db '    $'
s_mb    db ' MB$'
s_kb    db ' KB$'
s_done  db 13,10,'Done.  Press any key.',13,10,'$'
s_crlf  db 13,10,'$'
n_log   db 'A:\HDSCAN.TXT',0
n_boot  db 'A:\HDBOOT.BIN',0

fh      dw 0
bufn    dw 0
pitset  db 0
pic2    db 0
pno     db 0
drvl    db 'C'
bootdone db 0
fat16   db 0
c_head  db 0
c_sec   db 0
n_busy  db 0
f_key   db 0
        align 2
cyls    dw 0
heads   dw 0
spt     dw 0
hs      dw 0
total   dd 0
cur_lba dd 0
p_lba   dd 0
fat_lba dd 0
root_lba dd 0
data_lba dd 0
dir_at  dd 0
fat_at  dd 0
spc     dw 0
epc     dw 0
rootents dw 0
clusters dw 0
depth   dw 0
plen    dw 0
n_dirs  dw 0
n_files dw 0
n_bytes dd 0
n_del   dw 0
n_free  dw 0
n_badc  dw 0
d_files dw 0
d_bytes dd 0
c_cyl   dw 0
n_bad   dw 0
n_rd    dd 0
blk_bad dw 0
blk_cyl dw 0
t_start dw 0
t_blk   dw 0
lvl_start times MAXDEPTH dw 0
lvl_idx  times MAXDEPTH dw 0
lvl_plen times MAXDEPTH dw 0
numbuf  times 12 db 0
pathbuf times PATHMAX + 2 db 0
        align 2
mbrbuf  times 512 db 0
bootbuf times 512 db 0
dirbuf  times 512 db 0
fatbuf  times 512 db 0
secbuf  times 512 db 0
fbuf    times 512 db 0
        times 1024 db 0
stack_top:
prog_end:
