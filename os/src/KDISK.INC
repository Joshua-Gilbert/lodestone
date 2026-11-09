; =====================================================================
;  KDISK.INC - floppies A: and B: through BIOS INT 13h: mounting (BPB),
;  media changes, the FAT12 cache, sector buffers, transfers split at
;  track ends and 64 KB DMA boundaries, and critical errors (INT 24h).
;  Drive C: is the internal hard disk when KHD.INC finds one: it hooks
;  the places marked "KHD.INC" (their first instructions up to the .hk
;  label are copied out and replaced by a jump, so they must not jump).
;  Sector numbers are 16 bits but for the hard disk's: there a 32-bit
;  number's high part rides in [lba_hi] from clu2lba (and dent_buf) into
;  buf_get/buf_getd/disk_io, which use it and set it back to 0, and
;  buf_inval_range, which leaves it; and in a sector buffer's "drive"
;  byte, as the drive + 4 * the high part.  All of that is KHD.INC's:
;  for the floppies it stays 0.  FAT entries come out as FAT16's: ends
;  from 0FFF0h.
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
D_PRES  equ 27                  ; drive exists (3: a floppy with no change line)
D_HINT  equ 28                  ; where to look for a free cluster
D_MEDIA equ 30
D_CHK   equ 31                  ; check it is the same disk at the next access
                                ;  (2: and find its current directory again)
DRVSZ   equ 32
NDRV    equ 3                   ; A:, B: and C: (only with KHD.INC's hard disk)
NFLOP   equ 2
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
fk_dirty    resb 1              ; fat_keep: the two as they were
fat_sv      resb 1              ; bit n: fat_sum's for floppy n is known
cwd_redo    resb 1              ; 1: this drv_ready calls cwd_find (2: and its
                                ;  mount may keep unmount's number, rule 9; the name
cwd_nmk     resb 11             ;  kept), and cwd_find's nm11
sd_err      resb 1              ; same_disk: 1 if a read failed (not another
            alignb 2            ;  disk: its sector at sd_lba); 2 while it runs
sd_lba      resw 1
mgen        resw NFLOP          ; each floppy's mount (an SFT's S_GEN: its low
                                ;  byte, rule 9; all of a task's, KMT.INC)
cl_tick     resd NFLOP          ; the BIOS tick of each floppy's last use by
                                ;  a handle call (sft_chk: no change line)
fat_ncl     resw 1              ; the cached FAT's D_NCL (fat_get, fat_set)
fat_dmask   resw 1              ; which FAT sectors changed (bit n = sector n)
fk_dmask    resw 1
fat_sum     resw 2 * NFLOP      ; each floppy's FAT sector 0 as its disk last
                                ;  had it (sec_sum: read or written there):
                                ;  same_disk's, kept when the cache goes
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
io_err      resb 1
buf_drv     resb NBUF
            alignb 2
buf_lba     resw NBUF
buf_age     resw NBUF
buf_clock   resw 1
lba_hi      resw 1              ; the next sector number's high part (above)
            alignb 16
bounce      resb 512
BPBLEN      equ 51                      ; boot sector 0Bh-3Dh
bootcopy    resb BPBLEN * NFLOP
bufs        resb 512 * NBUF
fatbuf      resb 512 * MAXSPF
section .text

section ovl
drv_init:
        int     11h
        xor     cx, cx
        test    al, 1
        jz      .n
        mov     cl, al
        shr     cl, 6
        and     cl, 1                   ; (no more than NFLOP: C: isn't one)
        inc     cl                      ; floppy drives
.n:     mov     di, drvtab
        xor     bx, bx
.d:     mov     [di+D_UNIT], bl
        cmp     bl, cl
        jae     .np
        mov     byte [di+D_PRES], 1
        push    cx                      ; a change line?  (AH=15h: 2.  1 for
        mov     ah, 15h                 ;  none, and an XT BIOS's "no such
        mov     dl, bl                  ;  call": D_PRES 3, sft_chk's 2 s,
                                        ;  till AH=16h says "not changed")
        int     13h
        pop     cx
        cmp     ah, 1
        jne     .np
        mov     byte [di+D_PRES], 3
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
section .text

; AL = drive -> [act], [actp], SI = drive table entry
use_drive:
        push    ax
        mov     [act], al
.hk:                                    ; (KMDISK.INC: M:'s entry)
        mov     ah, DRVSZ
        mul     ah
        add     ax, drvtab
        mov     si, ax
        mov     [actp], ax
        pop     ax
        ret

; AL = drive -> SI = its entry ([act], [actp]).  CF if there is no such drive
; (KMDISK.INC: M: is one)
drv_present:
        cmp     al, NDRV
        cmc
.hk:    jc      .no
        call    use_drive
        cmp     byte [si+D_PRES], 1     ; (CF if 0)
.no:    ret

        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
; AL = drive -> DI = its current directory ("\DIR\SUB").  AH changed
; (KMDISK.INC: M:'s)
cwd_of: xor     ah, ah
        imul    di, ax, CWDLEN
.hk:    add     di, cwdstr
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
        call    bpb_slot
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

; drive [act]'s kept BPB -> DI, CX = its length.  AX changed
bpb_slot:
        mov     al, [act]
        mov     ah, BPBLEN
        mul     ah
        add     ax, bootcopy
        mov     di, ax
        mov     cx, BPBLEN
        ret

; sector DX of drive [act] into bounce: crit_bounce with INT 24h, as
; MS-DOS's when it mounts (Retry, Fail), raw_bounce without.  CF: AX =
; error.  AX, BX, CX changed
crit_bounce:
        mov     byte [io_crit], 2
        jmp     short raw_bounce.go
raw_bounce:
        mov     byte [io_crit], 0
.go:    push    es
        push    cs
        pop     es
        mov     bx, bounce
        mov     al, [act]
        mov     cx, 1
        mov     ah, 2
        call    dio
        pop     es
        ret

; ---------------------------------------------------------------------
;  Writes that fail (INT 24h Fail or Abort, a write-protected disk, a
;  bad sector, a disk taken out), and what the disk is left with:
;  1. The FAT cache is one disk's.  same_disk takes the disk in the drive
;     for it only with the same BPB (serial and label included) and the
;     same FAT sector 0 as that disk last had (fat_sum, each floppy's: as
;     read, or as written by copy 1; while a flush is part done, the
;     cache's own sector 0 may be that disk's too).  A changed cache never
;     vouches for a disk.  A read that fails there is INT 24h's for that
;     read, not another disk.  INT 21h 0Dh forgets a floppy's sum when it
;     has nothing to go and no file open (a program may rewrite the disk
;     then: CHKDSK /F, DEFRAG), and its current directory is found again
;     by name at the next access, as after any mount of another disk
;     (cwd_find).  (Kept, a rewrite would be another disk: 0Dh is all a
;     DOS program tells of one.  A copy of the disk put in then is taken
;     for it.)  With a file open it is kept: another disk with the same
;     BPB put in is "Invalid disk change", not the same disk; a rewrite
;     with a file open is too.  Taken with no sum compared, its current
;     directory is found again by name too.
;  2. A chain goes to the disk before the entry that names it; an entry
;     before the frees it lets go of (do_create, a truncating write,
;     DELETE, RMDIR); dir_slot zeroes a directory's new cluster before it
;     links it in.  So the disk's FAT and directory agree after any one
;     failure, or differ by lost clusters only.
;  3. A failed flush keeps the cache changed: on the same disk its
;     sectors go out at the next flush.  Each copy goes as one transfer
;     (from the first changed sector to the last), so a failure leaves at
;     most one half-written run.
;  4. Another disk in the drive while the old one has business going (the
;     cache changed, or a file open on it, as MS-DOS 3.30): INT 24h 0Fh,
;     "Invalid disk change", a write's (drv_ready); Retry looks again, so
;     the right disk back goes on as if nothing happened.  Fail or Abort:
;     the old disk's cache dropped and the call fails (drv_ready's 34: a
;     path call's 3, as MS-DOS's measured; a handle call's 5, sft_chk,
;     its documented code, assumed; 59h says the same, MS-DOS's maybe 83);
;     a changed cache dropped otherwise (INT 21h 0Dh or a screen capture's reset
;     after a failed flush): the drive's open files with changes pending
;     are SF_LOST (sft_pend): their writes and close refused (5), their
;     entries as the disk has them.  With nothing open and nothing to go
;     another disk is just mounted.  A transfer the BIOS fails with 06h
;     (changed under it; read-ahead's and the cylinder cache's too) isn't
;     tried again on the disk in, nor read another way: the same disk goes
;     on with it, another is INT 24h 0Fh there and then (chg_ask), Retry
;     looks again, Fail the same as here, the call's other transfers
;     failed with it (dio: none to an unmounted floppy).  That is asked
;     with nothing open too: the rest of the call would go on with the old
;     disk's chains and directory clusters on the new one (a search, DIR's
;     next sector, a mount's FAT after its boot sector), so a quiet mount
;     there would mix the two disks' data.  (MS-DOS's driver refuses a
;     changed volume only while files are open, and reads on, mixed.)
;     Fail's unmount leaves the files to the next mount (rule 9).
;  5. A write that fails gives back what it took: file_write its clusters
;     (fat_keep/fat_back), dir_slot and MKDIR theirs.
;  6. A buffer whose write failed is the disk's no more: forgotten at
;     Fail (buf_put), all the drive's at Abort (crit_disk; C:'s with high
;     parts too: buf_inval looks at the drive bits).
;  7. Chain walks stop on an entry below 2 (free, reserved) as a broken
;     chain, never as its end: fat_get gives 1 for reserved and bad ones
;     (FF0h-FF7h), a link past the disk's end and a cluster past it; a
;     directory longer than the disk (a loop) is 5 (dir_entry).
;  8. A path call flushes its own drive's FAT only (fat_flush_act).
;  9. Each floppy mount has a number (mgen: 16 bits), its low byte kept
;     in the SFT of a file opened on it (S_GEN).  A mount after unmount
;     (D_CHK 3: no other mounted since) that finds the disk unmount let go
;     (same_disk, as Retry takes it, its FAT sector 0 compared: a BPB alone
;     is all two disks MS-DOS formatted, or copied, have) keeps the
;     number, and its files read on, as MS-DOS's after a Fail with the
;     volume back (those whose
;     changes were dropped are SF_LOST already, rule 4); any other mount
;     takes the next number, the old one's files SF_LOST (drv_ready), so
;     the byte coming round again is never theirs.  (A mount that fails
;     leaves that to the next look, as does a read that fails as it looks,
;     INT 24h's first.)  Read, write, commit and close with
;     changes of a file another mount's, or SF_LOST, are refused (5,
;     sft_chk); each first looks at the drive (drv_ready; without a change
;     line, only if unused for ~2 s: D_PRES 3 from AH=15h's answer, taken
;     back at the first "not changed" from AH=16h, which such a drive
;     never gives).  A close without changes just lets the file go; the
;     last close of a changed one writes it while it is still open (so
;     another disk in by then is "Invalid disk change", Retry writes it).
;     Each task's current directories are its own, of the mount they were
;     found on (KMT.INC: TX_MG): another mount's, found again by name.
; ---------------------------------------------------------------------
; The change line says the disk may have changed: is it the same one?
; Same boot sector BPB and, if our FAT cache is this drive's, a first FAT
; sector as that disk last had it (rule 1).  CF if different (or
; unreadable).  With no sum to compare, cwd_redo: the current directory
; is found again by name (drv_ready).  Nothing cached is dropped (the
; caller's: drv_ready, chg_ask)
same_disk:
        pusha
        push    es
        push    cs
        pop     es
        mov     byte [sd_err], 2        ; (its reads: no 06h handling, dio.st)
        xor     dx, dx
        call    raw_bounce
        jc      .rerr
        call    bpb_slot
        mov     si, bounce + 0Bh
        repe    cmpsb
        jne     .diff
        mov     cl, [act]               ; (rule 1: each floppy's own sum)
        mov     al, 1
        shl     al, cl
        mov     si, [actp]
        test    [fat_sv], al
        jnz     .sum
        mov     byte [cwd_redo], 1      ; (nothing known to compare: maybe a
        mov     byte [si+D_CHK], 2      ;  copy of it, its directories not
        jmp     short .same             ;  where they were, rule 1: this
.sum:                                   ;  call's, or the next, chg_ask's)
        mov     dx, [si+D_RSV]
        call    raw_bounce
        jc      .rerr
        mov     si, bounce
        call    sec_sum
        mov     bl, [act]
        xor     bh, bh
        shl     bx, 2
        cmp     ax, [fat_sum+bx]
        jne     .cur
        cmp     dx, [fat_sum+bx+2]
        je      .same
.cur:   mov     cl, [act]
        cmp     [fat_drv], cl           ; (a flush part done: its sector 0
        jne     .diff                   ;  may be the cache's already)
        cmp     byte [fat_dirty], 0
        je      .diff
        push    dx
        push    ax
        mov     si, fatbuf
        call    sec_sum
        pop     cx
        pop     bx
        cmp     ax, cx
        jne     .diff
        cmp     dx, bx
        jne     .diff
.same:  xor     al, al                  ; (CF clear)
        jmp     short .x
.rerr:  mov     [sd_lba], dx            ; a read error, not another disk:
        mov     al, 1                   ;  drv_ready asks about it as such
        db      3Dh                     ; (CMP AX, imm16: skips the next)
.diff:  mov     al, 0
        stc
.x:     mov     [sd_err], al
        pop     es
        popa
        ret

; get drive AL ready: present, media change noticed, mounted.  Sets
; [act]/[actp], SI = entry.  CF: AX = error.
drv_ready:
        call    drv_present
        jc      .inv
        push    ax
        push    dx
        mov     byte [cwd_redo], 0
        test    byte [si+D_UNIT], 80h   ; (the hard disk: never changes)
        jnz     .same
        xor     al, al                  ; (after INT 21h 0Dh: a program may
        xchg    al, [si+D_CHK]          ;  have used the disk, and its change
        cmp     al, 2                   ;  line, behind our back, and moved
        jb      .c1                     ;  the current directory: 2; 3 after
        dec     ax                      ;  unmount, rule 9: cwd_redo 2)
        mov     [cwd_redo], al
.c1:    or      al, al
        jnz     .chg
        mov     dl, [si+D_UNIT]
        mov     ah, 16h                 ; disk change line
        int     13h
        jnc     .nc
        cmp     ah, 6
        jne     .same
.chg:   cmp     byte [si+D_MNT], 0
        je      .same
.ck:    mov     al, [act]               ; sectors cached from it are suspect
        call    buf_inval               ; (and same_disk must see the disk)
        call    same_disk               ; (drives without a change line
        jc      .nsd                    ; report a change every time)
        call    buf_inval               ; the same: whatever is cached gets
        cmp     [fat_drv], al           ;  read again (same_disk's reads may
        jne     .same                   ;  have filled the cylinder cache)
        cmp     byte [fat_dirty], 0
        jne     .same
        mov     byte [fat_drv], 0FFh
        jmp     short .same
.nsd:   cmp     byte [sd_err], 0        ; it couldn't be read: INT 24h for
        je      .other                  ;  that read, Retry looks again
        push    bx                      ;  (rule 1: not another disk)
        push    cx
        mov     dx, [sd_lba]
        call    crit_bounce
        pop     cx
        pop     bx
        jnc     .ck
        pop     dx                      ; (Fail: the call fails, the drive
        add     sp, 2                   ;  looked at again next time: .mf)
        jmp     .mf
.other: mov     al, [act]               ; another disk, and the old one has
        call    drv_pend                ;  changes to go or files open: INT
        jnc     .um                     ;  24h 0Fh, "Invalid disk change",
        mov     ah, 3                   ;  as MS-DOS (rule 4; Retry looks
        mov     [io_drv], ax            ;  again: the right one back, nothing
        mov     byte [io_bios], 6       ;  lost; a write's, as MS-DOS's:
        mov     byte [io_crit], 2       ;  io_op 3, after io_drv)
        call    crit_disk
        cmp     al, 1
        je      .ck
        mov     al, [act]               ; Fail: the old disk's changes
        call    unmount                 ;  dropped, its files refused, and
        pop     dx                      ;  the call fails (34, as MS-DOS);
        pop     ax                      ;  the next one mounts the disk in
        mov     ax, 34
        stc
        ret
.um:    mov     byte [cwd_redo], 1      ; nothing to go: the disk in is
        mov     al, [act]               ;  mounted, the current directory
        call    unmount                 ;  found again by its name (as
                                        ;  MS-DOS's FATREAD_CDS: cwd_find)
        jmp     short .same
.nc:    mov     byte [si+D_PRES], 1     ; "not changed": a change line, what-
                                        ;  ever AH=15h said (D_PRES 3 only
                                        ;  skips looks: sft_chk, cl_fresh)
.same:  pop     dx
        pop     ax
        cmp     byte [si+D_MNT], 0
        jne     .rd
        push    bx
        push    cx
        push    dx
        cmp     al, NFLOP               ; a floppy's new mount (rule 9): the
        jae     .m                      ;  disk unmount let go back, the
        cmp     byte [cwd_redo], 2      ;  same as Retry would take (no other
        jne     .ng                     ;  mounted since), keeps its number
.sd:    call    same_disk               ;  and files; else a new number, the
        jc      .sde                    ;  old one's files SF_LOST (so the
        cmp     byte [cwd_redo], 2      ;  number come round again, in the
        je      .m                      ;  SFT's byte, is never theirs).
                                        ; (no sum compared, 1: the BPB alone
                                        ;  is all a disk copied or formatted
                                        ;  by MS-DOS has, another disk then)
.ng:    cbw
        mov     bx, ax                  ;  SFT's byte, is never theirs)
        add     bx, bx
        inc     word [mgen+bx]
        call    sft_lose
.m:     xor     dx, dx
        call    crit_bounce             ; no BPB yet: use a 9-sector guess
.m3:    pop     dx
        pop     cx
        pop     bx
        jc      .mf
        push    si
        mov     si, bounce
        call    mount_bpb
        pop     si
        jc      .mf
.rd:    cmp     byte [cwd_redo], 0
        je      .ok
        call    cwd_find
.ok:    clc
.x:     ret
.mf:    push    ax                      ; not mounted: what this look had to
        mov     al, [cwd_redo]          ;  settle is the next one's (the
        inc     ax                      ;  current directory, and the mount
        or      [si+D_CHK], al          ;  number, rule 9)
        pop     ax
        stc
        ret
.sde:   cmp     byte [sd_err], 0        ; unreadable: INT 24h for that read
        je      .ng                     ;  (rule 1: not another disk), Retry
        mov     dx, [sd_lba]            ;  looks again, Fail leaves it all
        call    crit_bounce             ;  to the next look (.mf: D_CHK 3)
        jnc     .sd
        jmp     short .m3
.inv:   mov     ax, 15                  ; invalid drive
        stc
        ret

; drive AL: forget everything about the disk in it (its current
; directory's name kept, found again at the next mount).  A floppy's mount
; number and files are the next mount's to settle (D_CHK 3, rule 9)
unmount:
        push    ax
        push    si
        call    use_drive
        mov     byte [si+D_MNT], 0
        mov     word [si+D_CWD], 0      ; (its current directory's name kept,
        mov     byte [si+D_CHK], 3      ;  found at the next mount: cwd_find)
        cmp     al, NFLOP
        jb      .g
        call    sft_lose
.g:     call    fat_drop                ; (its changes dropped: the files
        call    buf_inval               ;  with changes pending SF_LOST)
        pop     si
        pop     ax
        ret

; checksum of the 512 bytes at SI (Fletcher's, two words) -> DX:AX.
; CX, SI changed
sec_sum:
        xor     ax, ax
        cwd
        mov     cx, 256
.l:     add     ax, [si]
        add     dx, ax
        inc     si
        inc     si
        loop    .l
        ret

; drive AL still has its disk's business going: the FAT cached changed,
; or a file open on this mount (not SF_LOST; as MS-DOS 3.30, which asks
; for the volume while files are open on it)?  CF if so.  All kept
drv_pend:
        cmp     al, [fat_drv]
        jne     .f
        cmp     byte [fat_dirty], 1
        cmc
        jc      .x
.f:     push    ax
        push    bx
        push    cx
        call    gen_of                  ; AH = this mount's (rule 9)
        mov     bx, sft
        mov     cx, NSFT
.l:     cmp     byte [bx+S_REF], 0
        je      .n
        test    byte [bx+S_FLAGS], SF_DEV | SF_LOST
        jnz     .n
        cmp     [bx+S_DRV], al
        jne     .n
        cmp     [bx+S_GEN], ah
        stc
        je      .y
.n:     add     bx, SFT_SZ
        loop    .l
        clc
.y:     pop     cx
        pop     bx
        pop     ax
.x:     ret

; drive AL -> AH = its mount's number (a floppy's mgen; 0 for the rest)
gen_of: mov     ah, 0
        cmp     al, NFLOP
        jae     .x
        push    bx
        mov     bl, al
        xor     bh, bh
        add     bx, bx
        mov     ah, [mgen+bx]
        pop     bx
.x:     ret

; drive [act], mounted afresh (another disk, nothing of the old one's to
; go): its current directory as its name says, if this disk has it, else
; the root (MS-DOS's FATREAD_CDS).  nm11 kept (a resolve's r_name, maybe).
; All kept
cwd_find:
        pusha
        push    es
        push    cs
        pop     es
        mov     byte [cwd_redo], 0
        mov     si, nm11
        mov     di, cwd_nmk
        mov     cx, 11
        rep     movsb
        call    fat_load
        jc      .root
        mov     al, [act]
        call    cwd_of
        lea     si, [di+1]              ; (past its '\')
        xor     ax, ax
.c:     cmp     byte [si], 0
        je      .end
        push    ax
        call    parse_comp
        pop     ax
        jc      .root
        push    si
        call    dir_find
        pop     si
        jc      .root
        test    byte [de+11], A_DIR
        jz      .root
        mov     ax, [de+26]
        cmp     byte [si], '\'
        jne     .c
        inc     si
        jmp     .c
.root:  mov     al, [act]
        call    cwd_of
        mov     word [di], '\'
        xor     ax, ax                  ; (the root: D_CWD 0 too, whatever
.end:   mov     si, [actp]              ;  it held, the same disk's or not)
        mov     [si+D_CWD], ax
        mov     byte [si+D_CHK], 0      ; (found: no more to do)
        mov     si, cwd_nmk
        mov     di, nm11
        mov     cx, 11
        rep     movsb
        pop     es
        popa
        ret

; drive AL's open files with changes pending (SF_DIRTY, not SF_LOST): AH
; ORed into their flags, their place in the chain forgotten.  CF if any.
; sft_lose: all its files (not SF_LOST), SF_LOST (unmount).  All kept
sft_lose:
        push    ax
        push    dx
        mov     ah, SF_LOST
        mov     dx, (SF_LOST | SF_DEV) << 8     ; (DL: none needed)
        jmp     short sft_pend.go
sft_pend:
        push    ax
        push    dx
        mov     dx, (SF_LOST | SF_DEV) << 8 | SF_DIRTY
.go:    push    bx
        push    cx
        mov     bx, sft
        mov     cx, NSFT                ; (CH: one found)
.l:     cmp     byte [bx+S_REF], 0
        je      .n
        cmp     [bx+S_DRV], al
        jne     .n
        test    [bx+S_FLAGS], dh        ; (DH: none of these)
        jnz     .n
        or      dl, dl
        jz      .y
        test    [bx+S_FLAGS], dl        ; (DL: this one)
        jz      .n
.y:     or      [bx+S_FLAGS], ah
        mov     word [bx+S_CCL], 0
        mov     ch, 1
.n:     add     bx, SFT_SZ
        dec     cl
        jnz     .l
        neg     ch
        pop     cx
        pop     bx
        pop     dx
        pop     ax
        ret

; drive AL's cached FAT dropped, changes and all (rule 4): its open files
; with changes pending SF_LOST.  Nothing if the cache isn't AL's.  All kept
fat_drop:
        cmp     al, [fat_drv]
        jne     fat_forget.x
        cmp     byte [fat_dirty], 0
        je      fat_forget
        push    ax
        mov     ah, SF_LOST
        call    sft_pend
        pop     ax
; the cached FAT is nobody's, and what fat_keep kept of it: a write that
; fails after its disk went (chg_ask's Fail) gives back into the cache
; nobody's (file_write's fat_back), and the next disk's FAT mustn't come
; in "changed" (flags kept)
fat_forget:
        push    ax
        mov     ax, 0
        mov     [fat_dirty], ax         ; (and fk_dirty)
        mov     [fat_dmask], ax
        mov     [fk_dmask], ax
        mov     byte [fat_drv], 0FFh
        pop     ax
.x:     ret
        times   -(fk_dirty - fat_dirty != 1) db 0

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
        mov     al, [fat_drv]           ; (a flush refused, or not tried:
        call    fat_drop                ;  its files' changes lost, rule 4)
        mov     al, 0
        call    .one
        mov     al, 1
        call    .one
        popf
        ret
; floppy AL: looked at again at the next access, its current directory
; found again by name (a program may rewrite the disk now: CHKDSK /F,
; DEFRAG); with no changes to go, its FAT sector 0 sum forgotten too, so
; the same disk rewritten is still the same disk (rule 1)
.one:   pusha
        call    buf_inval
        mov     cl, al
        call    drv_pend                ; (a file open on it: kept, so that
        jc      .o1                     ;  another disk put in isn't taken
                                        ;  for it on its BPB alone)
        mov     ah, 0FEh
        rol     ah, cl
        and     [fat_sv], ah
.o1:    mov     al, DRVSZ
        mul     cl
        xchg    bx, ax
        or      byte [drvtab+bx+D_CHK], 2   ; (3 kept: rule 9)
        popa
        ret

        times ($ - $$) & 1 db 90h       ; (hot: fat_load even)
; ---------------------------------------------------------------------
;  FAT cache (one drive at a time) - [act] must be the drive
; ---------------------------------------------------------------------
fat_load:
        mov     al, [act]
.hk:                                    ; (KHD.INC: C:'s is always there)
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
        mov     dx, [si+D_NCL]
        mov     [fat_ncl], dx
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
        call    fat_sum0
.ok:    clc
.x:     ret
; fat_sum: the cache's sector 0, as its disk has it now (a floppy's;
; C: and M: never change).  All kept
fat_sum0:
        pusha
        mov     bl, [fat_drv]
        cmp     bl, NFLOP
        jae     .x
        mov     cl, bl
        mov     al, 1
        shl     al, cl
        or      [fat_sv], al
        xor     bh, bh
        shl     bx, 2
        mov     si, fatbuf
        call    sec_sum
        mov     [fat_sum+bx], ax
        mov     [fat_sum+bx+2], dx
.x:     popa
        ret

; write the FAT sectors that changed to every FAT copy: each copy in one
; transfer, from the first changed sector to the last (rule 3)
; (KHD.INC: C:'s changed ones first)
fat_flush:
        cmp     byte [fat_dirty], 0
.hk:
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
        xor     bx, bx                  ; [BX, DI): the first changed sector
        mov     ax, [fat_dmask]         ;  to the last
        or      ax, ax
        jz      .cl
.lo:    shr     ax, 1
        jc      .hi
        inc     bx
        jmp     .lo
.hi:    lea     di, [bx+1]
.h:     or      ax, ax
        jz      .sp
        shr     ax, 1
        inc     di
        jmp     .h
.sp:    mov     ax, [si+D_SPF]          ; (never past the copy's end: a
        cmp     di, ax                  ;  cluster past D_NCL marks none,
        jbe     .sp1                    ;  fat_set, but keep to the FAT)
        mov     di, ax
.sp1:   cmp     bx, di
        jae     .cl
        mov     cl, [si+D_NFAT]
        xor     ch, ch
.c:     push    cx
        push    dx
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
        call    fat_sum0                ; (the disk's sector 0 is the cache's
        pop     cx                      ;  once copy 1 is out: a later copy's
        add     dx, [si+D_SPF]          ;  failure leaves it so)
        loop    .c
.cl:    mov     byte [fat_dirty], 0
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
        mov     al, [io_err]            ; (still changed: its sectors go out
                                        ;  at the next flush.  It holds only
                                        ;  clusters taken, and frees whose
                                        ;  entry is on the disk already: the
                                        ;  kernel writes a chain before the
                                        ;  entry that names it, and an entry
                                        ;  before the frees it lets go of)
        xor     ah, ah
        stc
        ret

; which FAT sectors changed, kept (fat_keep) and put back (fat_back): for a
; cluster taken and given back after a failed write, which leaves the FAT
; as it was.  Else a write-protected disk's FAT stayed "changed" and every
; other drive's FAT load (it flushes first) failed with error 19
fat_keep:
        push    ax
        mov     al, [fat_dirty]
        mov     [fk_dirty], al
        mov     ax, [fat_dmask]
        mov     [fk_dmask], ax
        pop     ax
        ret
fat_back:
        push    ax
        mov     al, [fk_dirty]
        mov     [fat_dirty], al
        mov     ax, [fk_dmask]
        mov     [fat_dmask], ax
        pop     ax
        ret

; drive AL's FAT to disk, if it is the one cached (KHD.INC: and C:'s);
; that drive's alone (rule 8: not fat_flush's hook, C:'s first)
fat_flush_drv:
        cmp     al, [fat_drv]
.hk:
        je      .f
        clc
        ret
.f:     cmp     byte [fat_dirty], 0
        jmp     fat_flush.hk
; [act]'s FAT to disk (a path call's).  AL changed
fat_flush_act:
        mov     al, [act]
        jmp     fat_flush_drv

        times ($ - $$) & 1 db 90h       ; (hot: even)
; AX = cluster -> AX = its FAT entry, as FAT16's (FF8h-FFFh: FFF8h-
; FFFFh).  Reserved and bad (FF0h-FF7h), a link past the disk's end, and
; a cluster past it: 1, a broken chain (rule 7)
fat_get:
        push    bx
        mov     bx, ax
.hk:                                    ; (KHD.INC: C:'s FAT16)
        cmp     ax, [fat_ncl]
        jae     .brk
        shr     bx, 1
        add     bx, ax
        test    al, 1
        mov     ax, [fatbuf+bx]
        jz      .e
        shr     ax, 4
.e:     and     ax, 0FFFh
        cmp     ax, [fat_ncl]           ; (a link past the end: broken)
        jb      .x
        or      ah, 0F0h
        cmp     ax, 0FFF8h
        jae     .x
.brk:   mov     ax, 1
.x:     pop     bx
        ret
        times ($ + 1 - $$) & 1 db 90h   ; (hot: fat_set.one even)

; FAT entry AX := DX (none past the disk's end)
fat_set:
        push    ax
        push    bx
        push    dx
.hk:                                    ; (KHD.INC: C:'s FAT16)
        cmp     ax, [fat_ncl]
        jae     .nx
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
        inc     bx
        test    bx, 511
        jnz     .one
        mov     dl, 3                   ; (BX+1 starts the next sector)
.one:   shl     dx, cl
        or      [fat_dmask], dx
        pop     cx
.nx:    pop     dx
        pop     bx
        pop     ax
        ret

        times ($ - $$) & 1 db 90h       ; (hot: even)
; cluster AX -> LBA AX of its first sector (KHD.INC: [lba_hi] the high
; part of C:'s)
clu2lba:
        push    cx
        push    si
        mov     si, [actp]
.hk:
        sub     ax, 2
        mov     cl, [si+D_SHIFT]
        shl     ax, cl
        add     ax, [si+D_DATA]
        mov     word [lba_hi], 0        ; (a floppy's: none, whatever an
        pop     si                      ;  abort on C: may have left)
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
        mov     dx, 0FFFFh
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
.hk:                                    ; (KHD.INC: C:'s FAT16)
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

; free the chain starting at AX (a loop ends at the first cluster freed)
free_chain:
        push    ax
        push    bx
        push    dx
.l:     cmp     ax, 2
        jb      .x
        cmp     ax, 0FFF0h
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
; (KHD.INC: for C:, AL becomes the drive + 4 * [lba_hi] first)
; buf_get is for directory and system sectors: a miss takes the oldest of
; the first NBUF-1 buffers.  buf_getd is for file data: a miss takes the
; last buffer, so reading or writing part-sectors of a file never pushes
; directory sectors out (a search then finds the whole of a short root
; still buffered).  Either finds a sector in any buffer.
buf_getd:
        push    bx
        push    cx
        mov     cx, 1
.hk:
        jmp     short buf_get.s
        times ($ - $$) & 1 db 90h       ; (hot: even)
buf_get:
        push    bx
        push    cx
        xor     cx, cx
.hk:
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
.hit:   mov     word [io_ra], 0         ; (read-ahead is per transfer: a hit
        inc     word [buf_clock]        ;  made none, so the caller's goes)
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
        mov     byte [buf_drv+bx], 0FFh ; (CF stays set: not the disk's now)
.ok:    pop     es
        pop     dx
        pop     cx
        pop     bx
        ret

; forget drive AL's buffers (and the track cache if it is that drive's;
; C:'s with any high part: 2 + 4n, as KHD.INC keys them; M:'s 12 and
; R:'s 17 are their own)
buf_inval:
        cmp     [tc_drv], al
        jne     .tc
        mov     byte [tc_drv], 0FFh
.tc:    push    bx
        push    cx
        xor     bx, bx
.l:     mov     cl, [buf_drv+bx]
        mov     ch, cl
        and     ch, 0F3h                ; (2, 6, 10, 14: C:'s)
        cmp     ch, 2
        jne     .c
        mov     cl, ch
.c:     cmp     cl, al
        jne     .n
        mov     byte [buf_drv+bx], 0FFh
.n:     inc     bx
        cmp     bx, NBUF
        jb      .l
        pop     cx
        pop     bx
        ret

; forget drive AL's buffers for LBAs DX .. DX+CX-1 (KHD.INC: C:'s with
; [lba_hi])
buf_inval_range:
        push    bx
        push    si
        xor     bx, bx
.hk:
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

; AX = whole sectors from ES:BX to the next 64 KB boundary (dio's DMA
; split, and the track cache's)
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

        times ($ - $$) & 1 db 90h       ; (hot: even)
; ---------------------------------------------------------------------
;  transfers.  AL = drive, AH = 2 read / 3 write, DX = LBA, CX = sectors,
;  ES:BX = memory.  Split at track ends and 64 KB DMA boundaries; a
;  sector straddling a boundary goes through the bounce buffer.
;  Errors go to INT 24h; CF: AX = DOS error code.
; ---------------------------------------------------------------------
disk_io:
        mov     byte [io_crit], 1       ; (raw_bounce: 0, crit_bounce: 2)
dio:    push    bx
        push    cx
        push    dx
.hk:                                    ; (KHD.INC: C:'s transfers)
        push    si
        push    di
        push    es
        mov     [io_drv], al
        mov     [io_op], ah
        push    ax
        call    use_drive_keep          ; (ZF: not mounted)
        pop     ax
        jnz     .loop
        cmp     byte [io_crit], 1       ; (a transfer to the disk that was
        jne     .loop                   ;  there, after chg_ask's Fail: none
        mov     ax, 34                  ;  till the next call mounts the one
        stc                             ;  in, rule 4)
        jmp     .x
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
                                        ;  ems_tc, the cache's pages in first,
        jc      .err                    ;  gives a failed read back as dio's:
        cmp     byte [io_chg], 0        ;  not one the disk changed under)
        jne     .err
        or      al, al
        jnz     .adv
%endif
        call    tc_room                 ; room before the next 64 KB boundary
        cmp     si, ax
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
.err:   cmp     byte [io_chg], 0        ; the disk changed under it: the same
        je      .e0                     ;  one back goes on with this piece
        call    chg_ask                 ;  (its state as it was, rule 4)
        jc      .x
        mov     dx, [io_lba]
        mov     cx, [io_left]
        jmp     .loop
.e0:    mov     ah, 0
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
        call    .st
        je      .bfail                  ; (06h: not tried again, chg_ask)
.rs:    xor     ah, ah
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
        cmp     byte [io_chg], 0
        jne     .bfail
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
.bign:  cmp     byte [io_crit], 2       ; (mounting: no Ignore was offered;
        je      .bfail                  ;  Fail, as MS-DOS, not a stale BPB)
        mov     byte [io_ign], 1
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
        call    .st
        je      .bse
        xor     ah, ah
        mov     dl, [io_unit]
        int     13h
        dec     byte [io_try]
        jnz     .bs1
.bse:   pop     es
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
; BIOS status AH into [io_bios]: 06h, the disk changed (an AT BIOS's change
; line) under a transfer to a disk known, read-ahead and the cylinder
; cache's own reads too, is not tried again on whatever disk is in now
; (the line is reset): io_chg, ZF; dio asks for the disk (chg_ask).  A
; mount's reads (io_crit 2) and same_disk's (sd_err 2) go on: the disk
; is being looked at
.st:    mov     [io_bios], ah
        cmp     ah, 6
        jne     .stx
        cmp     byte [io_crit], 2
        je      .sty
        cmp     byte [sd_err], 2
        je      .sty
        mov     [io_chg], ah
        cmp     ah, ah                  ; (ZF)
.stx:   ret
.sty:   or      ah, ah                  ; (NZ: 6)
        ret
; a write that didn't happen: what the cache was given for it is wrong
.wfail: cmp     byte [io_op], 3
        jne     .wx
        mov     byte [tc_drv], 0FFh
.wx:    ret
        times ($ - $$) & 1 db 90h       ; (hot: tc_piece even)

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
        cmp     byte [io_chg], 0        ; (the disk changed: not the piece
        jne     .err                    ;  read on whatever is in, dio.st)
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
        times ($ - $$) & 1 db 90h       ; (hot: what follows even)
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
.ok:    cmp     byte [io_chg], 1        ; (CF if head 1's read found the disk
        cmc                             ;  changed: dio.st)
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
        times ($ - $$) & 1 db 90h       ; (hot: tc_mine even)

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
io_ra       resw 1              ; read-ahead allowed past this transfer (sectors)
io_spec     resb 1              ; 1: this BIOS call is read-ahead
io_drv      resb 1
io_op       resb 1
IO_LEN      equ $ - io_crit     ; (a transfer's state: chg_ask keeps it in io_sv)
io_chg      resb 1              ; 1: the BIOS said 06h (dio.st)
io_sv       resb IO_LEN
section .text

; geometry and unit of drive [io_drv] (before mounting: 18 x 2 guess;
; ZF then)
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
        cmp     byte [si+D_MNT], 0      ; (ZF: not mounted)
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
        cmp     al, 06h                 ; (drv_ready's: another disk in, the
        je      .chg                    ;  old one's changes still to go)
        mov     al, 0Ch
        ret
.chg:   mov     al, 0Fh                 ; invalid disk change
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

; dio: the BIOS said the disk changed (06h: io_chg) under this transfer to
; a disk known.  As MS-DOS's driver and INT 24h: the same disk in the
; drive (same_disk: its buffers, cached FAT and files go on as they were)
; goes on with the piece, NC.  Another, or none to read: INT 24h 0Fh,
; "Invalid disk change" (Retry, Fail; the transfer's read or write), and
; Retry looks again, so the right one back goes on.  Fail: the old disk's
; changes dropped and its files refused (unmount, rule 4), its directory
; found again by name at the next call, which mounts the disk in; this
; call's transfers fail till then (dio): CF, AX = 34.  The transfer's
; state (io_*) is kept across the looks, transfers themselves.  AX changed
chg_ask:
        pusha
        push    es
        push    ds
        pop     es
        mov     byte [io_chg], 0
        mov     si, io_crit
        mov     di, io_sv
        call    .cp
        push    word [act]
        mov     al, [io_drv]
        call    use_drive
.ck:    cmp     [tc_drv], al            ; (the disk, not what the cylinder
        jne     .c1                     ;  cache holds of it)
        mov     byte [tc_drv], 0FFh
.c1:    call    same_disk
        jnc     .ok
        call    .back                   ; (io_bios 6, the transfer's drive
        mov     byte [io_crit], 2       ;  and read or write)
        call    crit_disk
        cmp     al, 1
        mov     al, [act]
        je      .ck
        call    unmount
        stc
.ok:    call    .back                   ; (flags kept)
        pop     ax
        pushf
        call    use_drive
        popf
        pop     es
        popa
        mov     ax, 34
        ret
.back:  mov     si, io_sv
        mov     di, io_crit
.cp:    mov     cx, IO_LEN
        rep     movsb
        ret
        times ($ - $$) & 1 db 90h       ; (crit_disk even, as it was)

; INT 24h for the failed transfer -> AL = 0 ignore, 1 retry, 3 fail
; (abort ends the program here and doesn't come back; while EXEC loads one
; it fails instead: the caller is cur_psp still, and f_4B gives back what
; the new program had.  Outside INT 21h (InDOS 0: C:'s INT 25h/26h) no
; EXEC loads: Abort ends the program.  Inside, "EXEC loads" is the outer
; call's AH, read at its frame's fixed place, not through BP: an INT 24h
; handler's own call is nested on the other stack, and KMT's close_all may
; run with BP no frame.  Under MT that place is the running task's own: a
; task switched inside INT 21h takes its slice of the kernel stack along)
crit_disk:
        test    byte [cap_req], 2       ; a screen capture: just fail
        jnz     .fail
        pusha
        push    ds
        push    es
        mov     al, [io_bios]
        call    bios_crit
        xor     ah, ah
        mov     di, ax
        mov     ah, 38h | 06h           ; ignore, retry, fail allowed; data area
        cmp     byte [io_crit], 2
        jne     .m
        mov     ah, 18h | 02h           ; mounting: retry, fail; the FAT's, as
.m:                                     ;  MS-DOS (no data to ignore)
        cmp     byte [io_op], 3
        jne     .r
        or      ah, 1                   ; a write
.r:     mov     al, [io_drv]
        mov     bp, cs
.c24:   mov     si, crit_dev            ; (multitasking: a far call, KMT.INC)
        int     24h
        mov     bp, sp
        mov     [bp+18], al             ; (AL, the answer, into pusha's frame)
        pop     es
        pop     ds
        popa
        cmp     al, 2
        je      .abort
        cmp     al, 3
        jbe     .x
.fail:  mov     al, 3
.x:     ret
.abort: mov     al, [io_drv]
        cmp     byte [io_bios], 6       ; an invalid disk change: the old
        jne     .ab0                    ;  disk's changes dropped (rule 4)
        call    unmount                 ;  before terminate's closes
.ab0:   cmp     byte [io_op], 3         ; a write: the drive's buffers are
        jne     .ab                     ;  the disk's no more (the one it
                                        ;  wrote never returns to buf_put):
        call    buf_inval               ;  read again (write-through: none
.ab:    cmp     byte [term_now], 0      ;  holds anything else).  In a
        jne     .fail                   ;  terminate's closes: Fail (else
        cmp     byte [indos], 0         ;  each Abort terminated again)
                                        ; (outside INT 21h the place holds
        je      .t                      ;  the last call's, maybe another
        cmp     byte [kstack_top - F_SIZE + F_AX + 1], 4Bh      ; task's)
        je      .fail
.t:     mov     ax, [cur_psp]
        cmp     ax, [root_psp]
        je      .fail
        mov     ax, 0200h               ; (a critical error, code 0; DS = KSEG,
        jmp     terminate.ah            ;  as above).  Doesn't return

crit_dev:                               ; a block device header for INT 24h
        dd 0FFFFFFFFh
        dw 0000h
        dw 0, 0
        db 1, 'LODE   '

; AL = a drive as INT 21h numbers them (0 = the current one, 1 = A:)
; -> AL = 0 for A:
drv_dflt:
        or      al, al
        jnz     .d
        mov     al, [cur_drv]
        inc     al
.d:     dec     al
        ret

; INT 21h 36h: free space.  DL = drive (0 = current)
f_36:   mov     al, [bp+F_DX]
.hk:                                    ; (KHD.INC: C:'s, counted once)
        call    drv_dflt
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
