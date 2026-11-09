; FORMAT.COM - formats a floppy or the hard disk for Lodestone (DOS 3.30's
; FORMAT, for A:, B: and C:)
;
;   FORMAT d: [/V[:label]] [/S] [/Q] [/F:size] [/N:sectors /T:tracks] [/4]
;   FORMAT C: [/V[:label]] [/Q]
;
;   d:          A: (the GRiD's own drive, BIOS unit 0) or B: (the external
;               one, unit 1).  M: and R: are refused.
;   /V          ask for a volume label once the disk is formatted;
;   /V:label    that label (11 characters at most, no spaces)
;   /S          make the disk start Lodestone: LODE.SYS, LODEMT.SYS, LODE.PIC
;               and LCMD.COM copied from the root of the drive Lodestone
;               started from (R: from the ROM), read before the new disk
;               goes in, so a one-drive machine formats its own boot disk.
;               Every disk gets the Lodestone boot sector (BOOT.BIN); one
;               without LODE.SYS says so when started from
;   /Q          quick: a disk formatted before keeps its tracks and gets an
;               empty FAT and root (clusters marked bad stay bad)
;   /F:size     360, 720, 1200 or 1440 (1.2 and 1.44 too, a K or M after
;               any); by default the drive's own: 1.44 MB in the 1520's
;   /N:9 /T:80  the same by sectors per track and tracks (cylinders)
;   /4          360 KB in a 1.2 MB drive
;
; A 1.44 MB drive takes 720 KB and 1.44 MB disks, a 720 KB drive 720 KB,
; a 1.2 MB drive 360 KB and 1.2 MB.  Each track is formatted and verified;
; one that fails is tried sector by sector and the clusters of the bad
; sectors are marked bad (FF7h) in the FAT.  A bad sector in the boot
; sector, the FATs or the root, the first 33 of a 1.44 MB disk, makes the
; disk unusable.  The BIOS's own calls do the work (INT 13h 18h, the media
; type, with 17h for a BIOS without it; 05h, 04h, 03h), then the kernel is
; told (INT 21h 0Dh): the new boot sector's serial number is its sign that
; this is another disk, so nothing it remembers of the old one is used.
;
; It asks for the disk ("Insert new diskette...") and, after each, whether
; to format another; the answers come through DOS, so FORMAT A: < ANS.TXT
; (a CR, then N) runs from a batch file without anyone there.  Esc or
; Ctrl-C at a prompt, or Esc while it formats, stops it.
;
; C:, after MS-DOS's warning ("Proceed with Format (Y/N)?"; N: exit code
; 5), keeps its partition.  The kernel's C: (it found a FAT16 file system
; there at start-up) also keeps its layout, so the kernel's tables stay
; right: through the kernel's INT 25h/26h, which forget the FAT window,
; the free count and the sectors written; the current directory is set
; back to the root.  A drive the kernel has no C: on gets a new FAT16
; layout (MS-DOS 4's cluster sizes, 512 root entries) in its first
; partition of type 04h, 06h or 0Eh, as the kernel will choose it,
; through the drive's own registers, as KHD.INC drives them (IRQ 14
; masked meanwhile); it then says to restart Lodestone, to use it.  The
; partition's entry must start past the partition table and end on the
; drive, and the layout is one the kernel takes (65,518 clusters at most).
; MS-DOS's warning wants Y or N and Enter.  Unless /Q (C:'s own: the old FAT's bad clusters kept)
; every sector is read first, the system area's all good or nothing is
; written, a data sector that fails making its cluster bad (FFF7h); Esc
; then stops it with the disk as it was.  /S, /F, /N, /T and /4 are the
; floppies'.  (Sectors the kernel holds of the data area, old directory
; sectors, are never read before being written again: a new directory's
; cluster is written whole.)
;
; Exit code (MS-DOS's): 0 formatted, 3 stopped by Esc or Ctrl-C, 4 it
; couldn't (the disk last tried: write-protected, no disk, track 0 bad,
; a bad switch ...), 5 N at C:'s warning.  Needs Lodestone: other DOSes
; keep their own copies of the FAT and directories, and have their own
; FORMAT.  With multitasking it must be the only task (Shift-Return, no
; others): another could be using the drive, the BIOS's diskette table
; (INT 1Eh) is everyone's, and each task keeps its own current
; directories, which a format leaves pointing at nothing.
cpu 286
org 100h

TRIES   equ 3                           ; for each BIOS call (a reset between)
MAXSPT  equ 18
MAXSPF  equ 9                           ; FAT sectors (1.44 MB's)
NSYS    equ 4                           ; system files for /S

; a media record (m_*): its fields
M_CYLS  equ 0                           ; cylinders
M_SPT   equ 1                           ; sectors per track
M_SPC   equ 2                           ; sectors per cluster
M_SHIFT equ 3                           ; log2 of that
M_SPF   equ 4                           ; sectors per FAT
M_MEDIA equ 5                           ; media byte
M_ROOT  equ 6                           ; root entries (word)
M_TOT   equ 8                           ; sectors (word)
M_T17   equ 10                          ; INT 13h 17h's type (0: none)
M_NAME  equ 11                          ; -> "1.44M$"
M_BIT   equ 13                          ; its bit in takes
M_KB    equ 14                          ; its size in KB (word)

start:  mov     sp, stack_top
        cld
        mov     di, bss_start           ; (a .COM's memory isn't cleared)
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     bx, prog_end + 15
        shr     bx, 4
        mov     ah, 4Ah                 ; room for the system files (/S)
        int     21h
        mov     dx, ctrlc
        mov     ax, 2523h
        int     21h
        mov     dx, crit                ; a critical error (only /S's
        mov     ax, 2524h               ;  writes through DOS can cause
        int     21h                     ;  one): Fail, no prompt
        mov     byte [unit], 0FFh
        call    args                    ; (DX = a message if they're wrong)
        jc      fail_msg
        cmp     byte [unit], 0FFh
        mov     dx, s_nodrv
        je      fail_msg
        mov     al, [unit]
        add     al, 'A'
        mov     [s_d1], al
        mov     [s_d2], al
        mov     [s_d3], al
        cmp     byte [unit], 2          ; C:, the hard disk
        je      hd_main
        cmp     byte [unit], 1          ; A: or B: only
        mov     dx, s_notfl
        ja      fail_msg
        int     11h                     ; is there such a drive?
        xor     cl, cl
        test    al, 1
        jz      .nd
        mov     cl, al
        shr     cl, 6
        inc     cl
.nd:    cmp     [unit], cl
        mov     dx, s_baddrv
        jae     fail_msg
        mov     ax, 0F000h              ; Lodestone?  (its own call)
        int     21h
        cmp     ax, 4F47h
        mov     dx, s_notlode
        jne     fail_msg
        call    alone
        jc      fail_msg
        call    kind                    ; what the drive takes, which format
        jc      fail_msg
        cmp     byte [label], 0         ; /V:label: is it a good one?
        je      .lb
        mov     si, label
        call    chk_label
        mov     dx, s_badlab
        jc      fail_msg
.lb:    cmp     byte [sys], 0
        je      .buf
        call    load_sys                ; /S: read them now (one drive)
        jc      fail_msg
.buf:   mov     ax, cs                  ; a track's buffer that doesn't
        shl     ax, 4                   ;  cross a 64 KB DMA boundary
        add     ax, tb1
        mov     word [tbuf], tb1
        cmp     ax, 10000h - MAXSPT * 512
        jbe     another
        mov     word [tbuf], tb2

; ---------------------------------------------------------------------
another:
        mov     byte [result], 4
        call    flush_keys              ; (keys typed before it: not these)
        mov     dx, s_insert
        call    print
.k:     call    getkey
        cmp     al, 13
        je      .go
        cmp     al, 27
        je      stopped
        cmp     al, 3
        je      stopped
        cmp     al, 1Ah                 ; (the end of a file it reads)
        je      stopped
        jmp     .k
.go:    mov     dx, s_crlf
        call    print
        call    one_disk                ; DX = what went wrong (CF)
        jnc     .ok
        call    print
        mov     dx, s_term
        call    print
        jmp     short .again
.ok:    mov     byte [result], 0
.again: call    flush_keys
        mov     dx, s_again
        call    print
        call    getkey
        push    ax
        cmp     al, ' '
        jb      .nb
        mov     dl, al
        mov     ah, 2
        int     21h
.nb:    mov     dx, s_crlf
        call    print
        pop     ax
        and     al, 0DFh
        cmp     al, 'Y'
        je      another
        mov     al, [result]
quit:   mov     ah, 4Ch
        int     21h

stopped:
        mov     dx, s_crlf
        call    print
stop3:  call    dpt_back
        call    irq_back
        mov     ax, 4C03h
        int     21h

fail_msg:
        call    print
        call    irq_back
        mov     ax, 4C04h
        int     21h


; multitasking: FORMAT must be the only task (another could be using the
; drive, the BIOS's diskette table is everyone's, and each task keeps its
; own current directories).  CF: DX
alone:  mov     ax, 0F012h              ; (CF: multitasking is off)
        xor     cx, cx
        int     21h
        jc      .y
        cmp     cx, 1
        jbe     .y
        mov     dx, s_tasks
        stc
        ret
.y:     clc
        ret

; Ctrl-C (through DOS, at a prompt): the BIOS's table back, exit code 3
ctrlc:  push    cs
        pop     ds
        jmp     stop3
crit:   mov     al, 83h                 ; (Fail, nobody asked: the kernel
        iret                            ;  drops nothing, its rule 4)

; ---------------------------------------------------------------------
; one disk, from the drive's first touch to the figures.  CF: DX = why
one_disk:
        mov     ax, 0D00h               ; the kernel's own changes to the
        int     21h                     ;  disk out first, before ours
        mov     ax, 0F001h              ; files open on it?  (a batch file
        mov     dl, [unit]              ;  run from it, a program's)
        int     21h
        mov     dx, s_open
        jcxz    .no
        stc
        ret
.no:    mov     si, [med]
        call    geometry
        call    new_fat
        cmp     byte [quick], 0
        je      .full
        call    old_disk                ; /Q: what's there, its bad clusters
        jc      .x
        mov     dx, s_qfmt
        call    print
        jmp     short .q
.full:  mov     dx, s_fmt
        call    print
        mov     si, [med]
        mov     dx, [si+M_NAME]
        call    print
        mov     dx, s_crlf
        call    print
        call    tracks
        jc      .x
.q:     mov     dx, s_done
        call    print
        cmp     byte [askv], 0          ; /V: the label now
        je      .w
        call    ask_label
.w:     call    serial
        call    boot_sec
        call    write_sys
        jc      .x
        mov     ax, 0D00h               ; the kernel forgets the old disk
        int     21h                     ;  (its BPB differs: the serial)
        mov     al, [unit]              ; and the drive's current directory
        add     al, 'A'                 ;  is its root (now, before a
        mov     ah, ':'                 ;  program asks for it, INT 21h
        mov     [path], ax              ;  47h, and is given the old one)
        mov     word [path+2], '\'
        mov     dx, path
        mov     ah, 3Bh
        int     21h
        mov     word [sysc], 0
        cmp     byte [sys], 0
        je      .fig
        call    copy_sys
        jc      .x
        mov     dx, s_sysok
        call    print
.fig:   call    figures
        clc
.x:     ret

; ---------------------------------------------------------------------
; the drive's kind (INT 13h 08h) -> [dkind]; the format asked for, or the
; drive's own -> [med].  CF: DX = message
kind:   mov     dl, [unit]
        mov     ah, 08h
        push    es
        int     13h
        pop     es
        mov     al, bl
        jnc     .k
        xor     al, al
.k:     cmp     al, 4
        jbe     .k2
        xor     al, al
.k2:    mov     [dkind], al             ; (0: unknown, takes any)
        mov     si, [med]
        or      si, si
        jnz     .chk
        mov     si, m_1440              ; the drive's own
        cmp     al, 3
        jne     .k3
        mov     si, m_720
.k3:    cmp     al, 2
        jne     .k4
        mov     si, m_1200
.k4:    cmp     al, 1
        jne     .k5
        mov     si, m_360
.k5:    mov     [med], si
.chk:   cmp     al, 0
        je      .ok
        mov     bl, al                  ; what this kind takes: a bit
        xor     bh, bh                  ;  per media record
        mov     al, [takes+bx-1]
        test    al, [si+M_BIT]
        jz      .no
.ok:    clc
        ret
.no:    mov     dx, s_nosup
        stc
        ret

; the media record at SI -> the disk's layout
geometry:
        mov     al, [si+M_SPF]
        xor     ah, ah
        shl     ax, 1
        inc     ax
        mov     [rootlba], ax           ; boot sector, 2 FATs
        mov     ax, [si+M_ROOT]
        add     ax, 15
        shr     ax, 4
        add     ax, [rootlba]
        mov     [datalba], ax
        mov     bx, [si+M_TOT]
        sub     bx, ax
        mov     cl, [si+M_SHIFT]
        shr     bx, cl
        mov     [nclus], bx             ; data clusters
        add     bx, 2
        mov     [ncl], bx               ; highest cluster + 1
        mov     al, [si+M_SPC]
        xor     ah, ah
        shl     ax, 9
        mov     [csize], ax
        mov     word [nbad], 0
        ret

; an empty FAT: the media byte, FFh, FFh
new_fat:
        mov     di, fat
        mov     cx, MAXSPF * 512 / 2
        xor     ax, ax
        rep     stosw
        mov     si, [med]
        mov     al, [si+M_MEDIA]
        mov     [fat], al
        mov     word [fat+1], 0FFFFh
        ret

; ---------------------------------------------------------------------
; format and verify every track.  CF: DX = why
tracks: mov     byte [dptset], 0
        mov     bp, TRIES               ; the media type: INT 13h 18h
.mt:    mov     si, [med]
        mov     ch, [si+M_CYLS]
        dec     ch
        mov     cl, [si+M_SPT]
        mov     dl, [unit]
        mov     ah, 18h
        push    es
        int     13h
        jnc     .mtok
        pop     es
        cmp     ah, 0Ch                 ; the drive can't
        je      .nosup
        cmp     ah, 1                   ; no such call: 17h, if there is
        je      .t17                    ;  a type for it
        call    reset
        dec     bp
        jnz     .mt
        cmp     ah, 80h
        je      .nrdy
        jmp     short .tk               ; (go on: the BIOS will say)
.mtok:  mov     [dpt1], di              ; INT 1Eh -> the table it gives
        mov     [dpt1+2], es            ;  (the old one back at the end)
        pop     es
        mov     ax, 351Eh
        int     21h
        mov     [dpt0], bx
        mov     [dpt0+2], es
        push    cs
        pop     es
        push    ds
        lds     dx, [dpt1]
        mov     ax, 251Eh
        int     21h
        pop     ds
        mov     byte [dptset], 1
        jmp     short .tk
.t17:   mov     si, [med]               ; (360 KB: 1 in its own drive, 2
        mov     al, [si+M_T17]          ;  in a 1.2 MB one)
        or      al, al
        jz      .tk
        cmp     byte [dkind], 2
        jne     .t1
        cmp     al, 1
        jne     .t1
        inc     ax
.t1:    mov     dl, [unit]
        mov     ah, 17h
        int     13h
.tk:    mov     byte [cyl], 0
.cl:    mov     byte [head], 0
.hl:    call    status
        call    esc_key
        jc      .esc
        call    one_track
        jc      .x
        inc     byte [head]
        cmp     byte [head], 2
        jb      .hl
        inc     byte [cyl]
        mov     al, [cyl]
        mov     si, [med]
        cmp     al, [si+M_CYLS]
        jb      .cl
        mov     dx, s_crlf
        call    print
        call    dpt_back
        clc
        ret
.esc:   mov     dx, s_crlf
        call    print
        jmp     stop3
.nosup: mov     dx, s_nosup
        stc
        ret
.nrdy:  mov     dx, s_nrdy
.x:     push    dx
        mov     dx, s_crlf
        call    print
        call    dpt_back
        pop     dx
        stc
        ret

; INT 1Eh back as it was
dpt_back:
        cmp     byte [dptset], 0
        je      .x
        mov     byte [dptset], 0
        push    ds
        mov     dx, [dpt0]
        mov     ds, [dpt0+2]
        mov     ax, 251Eh
        int     21h
        pop     ds
.x:     ret

; format track [cyl]/[head] and verify it; a bad one sector by sector.
; CF: DX = why it has to stop
one_track:
        mov     di, [tbuf]              ; the sectors' IDs: C, H, R, N
        mov     si, [med]
        mov     cl, [si+M_SPT]
        xor     ch, ch
        mov     bl, 1
.id:    mov     al, [cyl]
        mov     ah, [head]
        stosw
        mov     al, bl
        mov     ah, 2                   ; 512 bytes
        stosw
        inc     bl
        loop    .id
        mov     bp, TRIES
.f:     mov     si, [med]
        mov     al, [si+M_SPT]
        mov     ah, 05h
        call    bios_trk
        jnc     .v
        call    fatal                   ; write-protected, no disk
        jc      .x
        call    reset
        dec     bp
        jnz     .f
        jmp     short .bad              ; it won't format: every sector
.v:     mov     bp, TRIES
.vl:    mov     si, [med]
        mov     al, [si+M_SPT]
        mov     ah, 04h
        call    bios_trk
        jnc     .ok
        call    reset
        dec     bp
        jnz     .vl
.bad:   mov     byte [sct], 1           ; sector by sector
.bs:    mov     bp, TRIES
.bt:    mov     ax, 0401h
        mov     cl, [sct]
        call    bios_at
        jnc     .bn
        call    reset
        dec     bp
        jnz     .bt
        call    trk_lba                 ; AX = the track's first LBA
        mov     bl, [sct]
        dec     bl
        xor     bh, bh
        add     ax, bx
        call    mark_bad
        jc      .x
.bn:    inc     byte [sct]
        mov     al, [sct]
        mov     si, [med]
        cmp     al, [si+M_SPT]
        jbe     .bs
.ok:    clc
.x:     ret

; AH = call, AL = sectors, at [cyl]/[head] from sector 1 (CL: bios_at),
; ES:BX = the track buffer.  CF: AH = the BIOS's error
bios_trk:
        mov     cl, 1
bios_at:
        push    es
        push    cs
        pop     es
        mov     bx, [tbuf]
        mov     ch, [cyl]
        mov     dh, [head]
        mov     dl, [unit]
        int     13h
        pop     es
        ret

; the BIOS's error AH: one to stop at?  CF: DX = why
fatal:  mov     dx, s_wprot
        cmp     ah, 03h
        je      .y
        mov     dx, s_nrdy
        cmp     ah, 80h
        je      .y
        clc
        ret
.y:     stc
        ret

reset:  push    ax
        mov     dl, [unit]
        xor     ah, ah
        int     13h
        pop     ax
        ret

; [cyl]/[head] -> AX = its first LBA
trk_lba:
        mov     al, [cyl]
        xor     ah, ah
        shl     ax, 1
        add     al, [head]
        mov     si, [med]
        mov     bl, [si+M_SPT]
        xor     bh, bh
        mul     bx
        ret

; LBA AX can't be read: its cluster is bad.  CF: DX = why (the system
; area: the disk is no good)
mark_bad:
        sub     ax, [datalba]
        jb      .t0
        mov     si, [med]
        mov     cl, [si+M_SHIFT]
        shr     ax, cl
        add     ax, 2
        cmp     ax, [ncl]               ; (past the last whole cluster:
        jae     .x                      ;  nobody's)
        call    get12
        cmp     dx, 0FF7h
        je      .x
        mov     dx, 0FF7h
        call    set12
        inc     word [nbad]
.x:     clc
        ret
.t0:    mov     dx, s_trk0
        stc
        ret

; FAT12 entry AX of fat: get12 -> DX, set12 <- DX
get12:  mov     bx, ax
        shr     bx, 1
        add     bx, ax
        mov     dx, [fat+bx]
        test    al, 1
        jz      .e
        shr     dx, 4
.e:     and     dx, 0FFFh
        ret
set12:  push    cx
        mov     bx, ax
        shr     bx, 1
        add     bx, ax
        mov     cx, [fat+bx]
        test    al, 1
        jz      .e
        and     cx, 000Fh
        shl     dx, 4
        jmp     short .s
.e:     and     cx, 0F000h
.s:     or      cx, dx
        mov     [fat+bx], cx
        pop     cx
        ret

; "Head: 1   Cylinder: 40"
status: mov     dx, s_cr
        call    print
        mov     dx, s_head
        call    print
        mov     al, [head]
        add     al, '0'
        call    putc
        mov     dx, s_cyl
        call    print
        mov     al, [cyl]
        xor     ah, ah
        cmp     al, 10
        jae     .p
        push    ax
        mov     al, ' '
        call    putc
        pop     ax
.p:     xor     dx, dx
        jmp     pdec

; Esc (or Ctrl-C) waiting in the BIOS's buffer?  CF if so (taken out);
; any other key stays there
esc_key:
        mov     ah, 1                   ; (any other key taken out, so one
        int     16h                     ;  typed by mistake can't hide an
        jz      .n                      ;  Esc behind it)
        xor     ah, ah
        int     16h
        cmp     al, 27
        je      .y
        cmp     al, 3
        jne     esc_key
.y:     stc
        ret
.n:     clc
        ret

; ---------------------------------------------------------------------
; /Q: the disk's boot sector must be one of ours, of the format asked
; for (or by default, whatever it is); its FAT's bad clusters are kept.
; CF: DX = why
old_disk:
        mov     byte [cyl], 0
        mov     byte [head], 0
        mov     bp, TRIES
.r:     mov     ax, 0201h
        call    bios_trk
        jnc     .rd
        call    fatal
        jc      .x
        call    reset
        dec     bp
        jnz     .r
        jmp     .no
.rd:    mov     si, [tbuf]
        cmp     word [si+510], 0AA55h
        jne     .no
        cmp     word [si+0Bh], 512
        jne     .no
        mov     bx, media_tab           ; which of ours is it?
.m:     mov     di, [bx]
        or      di, di
        jz      .no
        mov     al, [di+M_SPC]
        cmp     al, [si+0Dh]
        jne     .mn
        mov     ax, [di+M_ROOT]
        cmp     ax, [si+11h]
        jne     .mn
        mov     ax, [di+M_TOT]
        cmp     ax, [si+13h]
        jne     .mn
        mov     al, [di+M_SPF]
        xor     ah, ah
        cmp     ax, [si+16h]
        jne     .mn
        mov     al, [di+M_SPT]
        cmp     ax, [si+18h]
        jne     .mn
        cmp     word [si+0Eh], 1        ; one reserved sector, 2 FATs,
        jne     .no                     ;  2 heads
        cmp     byte [si+10h], 2
        jne     .no
        cmp     word [si+1Ah], 2
        jne     .no
        jmp     short .found
.mn:    inc     bx
        inc     bx
        jmp     .m
.found: cmp     byte [medset], 0        ; a format asked for: this one?
        je      .use
        cmp     di, [med]
        mov     dx, s_qdiff
        jne     .x1
.use:   mov     [med], di
        mov     si, di
        call    geometry
        call    new_fat
        mov     bp, TRIES               ; its first FAT (one track holds
.f:     mov     si, [med]               ;  it in every format)
        mov     al, [si+M_SPF]
        mov     ah, 02h
        mov     cl, 2
        call    bios_at
        jnc     .fr
        call    reset
        dec     bp
        jnz     .f
        jmp     short .no
.fr:    mov     ax, 2                   ; its bad clusters, ours too
.b:     push    ax
        mov     bx, ax
        shr     bx, 1
        add     bx, ax
        add     bx, [tbuf]
        mov     dx, [bx]
        test    al, 1
        jz      .be
        shr     dx, 4
.be:    and     dx, 0FFFh
        cmp     dx, 0FF7h
        jne     .bn
        mov     dx, 0FF7h
        call    set12
        inc     word [nbad]
.bn:    pop     ax
        inc     ax
        cmp     ax, [ncl]
        jb      .b
        clc
        ret
.no:    mov     dx, s_qbad
.x1:    stc
.x:     ret

; ---------------------------------------------------------------------
; /V: "Volume label (11 characters, ENTER for none)? "
ask_label:
        mov     dx, s_vask
        call    print
        mov     byte [kbuf], 12
        mov     dx, kbuf
        mov     ah, 0Ah
        int     21h
        mov     dx, s_crlf
        call    print
        mov     cl, [kbuf+1]
        xor     ch, ch
        mov     si, kbuf+2
        mov     di, label
        rep     movsb
        mov     byte [di], 0
        mov     si, label
        call    chk_label
        jnc     .x
        mov     dx, s_badlab
        call    print
        jmp     ask_label
.x:     ret

; the label at SI (ASCIIZ): upper case, characters a label may have, 11
; at most.  CF if not.  All spaces is none ([label] = 0)
chk_label:
        push    si
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .e
        inc     cx
        cmp     cx, 11
        ja      .bad
        cmp     al, 'a'
        jb      .u
        cmp     al, 'z'
        ja      .u
        sub     al, 20h
        mov     [si-1], al
.u:     cmp     al, ' '
        jb      .bad
        cmp     al, 80h
        jae     .l
        mov     di, badch
        push    cx
        mov     cx, badch_n
        push    es
        push    cs
        pop     es
        repne   scasb
        pop     es
        pop     cx
        je      .bad
        jmp     .l
.e:     pop     si
        push    si                      ; nothing but spaces: none
.sp:    lodsb
        or      al, al
        jz      .none
        cmp     al, ' '
        je      .sp
        pop     si
        clc
        ret
.none:  pop     si
        mov     byte [si], 0
        clc
        ret
.bad:   pop     si
        stc
        ret

; the volume's serial number, from the date and the time (as MS-DOS 4)
serial: mov     ah, 2Ah
        int     21h
        push    cx
        push    dx
        mov     ah, 2Ch
        int     21h
        pop     ax
        add     ax, dx                  ; month/day + seconds/hundredths
        pop     bx
        add     bx, cx                  ; year + hour/minute
        inc     word [nfmt]             ; (and how many this run: never
        add     ax, [nfmt]              ;  twice the same)
        mov     [ser], ax
        mov     [ser+2], bx
        ret

; the boot sector: BOOT.BIN with this disk's BPB, serial and label
boot_sec:
        mov     si, bootbin
        mov     di, bootsec
        mov     cx, 256
        rep     movsw
        mov     si, [med]
        mov     al, [si+M_SPC]
        mov     [bootsec+0Dh], al
        mov     ax, [si+M_ROOT]
        mov     [bootsec+11h], ax
        mov     ax, [si+M_TOT]
        mov     [bootsec+13h], ax
        mov     al, [si+M_MEDIA]
        mov     [bootsec+15h], al
        mov     al, [si+M_SPF]
        xor     ah, ah
        mov     [bootsec+16h], ax
        mov     al, [si+M_SPT]
        mov     [bootsec+18h], ax
        mov     word [bootsec+1Ah], 2
        mov     word [bootsec+0Eh], 1
        mov     byte [bootsec+10h], 2
        mov     byte [bootsec+24h], 0
; the boot sector's serial and label, and the label's root entry (C:'s too)
bs_tail:
        mov     byte [bootsec+26h], 29h
        mov     ax, [ser]
        mov     [bootsec+27h], ax
        mov     ax, [ser+2]
        mov     [bootsec+29h], ax
        mov     di, bootsec+2Bh
        mov     si, s_noname
        cmp     byte [label], 0
        je      .n
        mov     si, label
.n:     call    pad11
        mov     di, dirent              ; the label's root entry
        mov     si, label
        call    pad11
        mov     byte [dirent+11], 08h
        mov     ah, 2Ch                 ; its time and date
        int     21h
        mov     al, cl                  ; hh:mm:ss -> hhhhhmmmmmmsssss
        xor     ah, ah
        shl     ax, 5
        mov     bl, dh
        shr     bl, 1
        xor     bh, bh
        or      ax, bx
        mov     bl, ch
        shl     bx, 11
        or      ax, bx
        mov     [dirent+16h], ax
        mov     ah, 2Ah
        int     21h
        sub     cx, 1980                ; yyyyyyymmmmddddd
        shl     cx, 9
        mov     al, dh
        xor     ah, ah
        shl     ax, 5
        or      ax, cx
        or      al, dl
        mov     [dirent+18h], ax
        ret

; ASCIIZ at SI -> 11 characters at DI, spaces after
pad11:  mov     cx, 11
.l:     lodsb
        or      al, al
        jz      .s
        stosb
        loop    .l
        ret
.s:     mov     al, ' '
        rep     stosb
        ret

; the boot sector, both FATs and the root, a track at a time.  CF: DX
write_sys:
        xor     ax, ax                  ; AX = LBA
.t:     cmp     ax, [datalba]
        jae     .ok
        mov     [lba], ax
        mov     si, [med]               ; (cylinder, head, sector)
        mov     bl, [si+M_SPT]
        div     bl
        mov     [sct], ah
        inc     byte [sct]
        mov     ah, al
        shr     al, 1
        mov     [cyl], al
        and     ah, 1
        mov     [head], ah
        mov     cl, [si+M_SPT]          ; sectors to the track's end, or
        sub     cl, [sct]               ;  to the data
        inc     cl
        xor     ch, ch
        mov     ax, [datalba]
        sub     ax, [lba]
        cmp     cx, ax
        jbe     .n
        mov     cx, ax
.n:     mov     [nsec], cx
        mov     di, [tbuf]
        mov     ax, [lba]
.g:     call    gen
        inc     ax
        add     di, 512
        loop    .g
        mov     bp, TRIES
.w:     mov     al, [nsec]
        mov     ah, 03h
        mov     cl, [sct]
        call    bios_at
        jnc     .wn
        call    fatal
        jc      .x
        call    reset
        dec     bp
        jnz     .w
        mov     dx, s_trk0
        stc
        ret
.wn:    mov     ax, [lba]
        add     ax, [nsec]
        jmp     .t
.ok:    clc
.x:     ret

; sector AX of the system area -> 512 bytes at DI
gen:    pusha
        push    di
        push    ax
        mov     cx, 256
        xor     ax, ax
        rep     stosw
        pop     ax
        pop     di
        mov     si, bootsec
        or      ax, ax
        jz      .cp
        cmp     ax, [rootlba]
        jae     .root
        dec     ax                      ; a FAT's: the same in both
        mov     si, [med]
        mov     bl, [si+M_SPF]
        div     bl
        mov     al, ah
        xor     ah, ah
        shl     ax, 9
        add     ax, fat
        mov     si, ax
.cp:    mov     cx, 256
        rep     movsw
.x:     popa
        ret
.root:  jne     .x                      ; (the root's first: the label)
        cmp     byte [label], 0
        je      .x
        mov     si, dirent
        mov     cx, 16
        rep     movsw
        jmp     .x

; ---------------------------------------------------------------------
; /S: the system files from the start-up drive's root, into memory.
; CF: DX = why
load_sys:
        mov     ax, 3305h               ; the drive Lodestone started
        int     21h                     ;  from (DL: 1 = A:)
        add     dl, 'A' - 1
        mov     bx, sysrec
        mov     si, sysnames
.f:     mov     [bx+R_NAME], si
        mov     [bx+R_PATH], dl
        push    dx
        push    si
        lea     di, [bx+R_PATH+3]       ; "X:\NAME"
        mov     byte [bx+R_PATH+1], ':'
        mov     byte [bx+R_PATH+2], '\'
.c:     lodsb
        mov     [di], al
        inc     di
        or      al, al
        jnz     .c
        lea     dx, [bx+R_PATH]
        mov     ax, 3D00h
        int     21h
        jc      .miss
        mov     [handle], ax
        push    bx
        mov     bx, ax
        mov     ax, 5700h               ; its time and date
        int     21h
        pop     bx
        mov     [bx+R_TIME], cx
        mov     [bx+R_DATE], dx
        push    bx
        mov     bx, [handle]
        mov     ax, 4202h               ; its size
        xor     cx, cx
        xor     dx, dx
        int     21h
        push    ax
        push    dx
        mov     ax, 4200h
        xor     cx, cx
        xor     dx, dx
        int     21h
        pop     dx
        pop     ax
        pop     bx
        mov     [bx+R_SIZE], ax
        mov     [bx+R_SIZE+2], dx
        add     ax, 15                  ; its memory
        adc     dx, 0
        mov     cx, 16
        div     cx
        push    bx
        mov     bx, ax
        mov     ah, 48h
        int     21h
        pop     bx
        jc      .mem
        mov     [bx+R_SEG], ax
        mov     ah, 3Fh
        call    xfer
        pushf
        push    bx
        mov     bx, [handle]
        mov     ah, 3Eh
        int     21h
        pop     bx
        popf
        jc      .rerr
        jmp     short .nx
.miss:  cmp     bx, sysrec              ; LODE.SYS must be there; the
        je      .nosys                  ;  others when they are
        mov     word [bx+R_NAME], 0
.nx:    pop     si
        pop     dx
.sk:    lodsb                           ; the next name
        or      al, al
        jnz     .sk
        add     bx, RSZ
        cmp     bx, sysrec + NSYS * RSZ
        jb      .f
        clc
        ret
.nosys: mov     dx, s_nosys
        jmp     short .e
.mem:   push    bx
        mov     bx, [handle]
        mov     ah, 3Eh
        int     21h
        pop     bx
        mov     dx, s_sysmem
        jmp     short .e
.rerr:  mov     dx, s_sysrd
.e:     pop     si
        pop     si
        stc
        ret

; the file record BX's memory to or from [handle]: AH = 3Fh read, 40h
; write, 32 KB at a time.  CF if it fails or comes up short
xfer:   pusha
        push    ds
        mov     [xop], ah
        mov     si, [bx+R_SIZE]
        mov     di, [bx+R_SIZE+2]
        mov     bp, [bx+R_SEG]
        mov     bx, [handle]
.l:     mov     cx, 8000h
        or      di, di
        jnz     .n
        cmp     si, cx
        jae     .n
        mov     cx, si
        jcxz    .ok
.n:     mov     ah, [cs:xop]
        mov     ds, bp
        xor     dx, dx
        int     21h
        push    cs
        pop     ds
        jc      .x
        cmp     ax, cx
        stc
        jne     .x
        sub     si, cx
        sbb     di, 0
        add     bp, 800h
        jmp     .l
.ok:    clc
.x:     pop     ds
        popa
        ret

; /S: the files onto the new disk, through DOS; [sysc] = their clusters.
; CF: DX = why
copy_sys:
        mov     bx, sysrec
.f:     cmp     word [bx+R_NAME], 0
        je      .nx
        mov     si, [bx+R_NAME]         ; "A:\NAME"
        mov     di, path
        mov     al, [unit]
        add     al, 'A'
        stosb
        mov     ax, '\' << 8 | ':'
        stosw
.c:     lodsb
        stosb
        or      al, al
        jnz     .c
        mov     dx, path
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .err
        mov     [handle], ax
        mov     ah, 40h
        call    xfer
        pushf
        push    bx
        mov     cx, [bx+R_TIME]
        mov     dx, [bx+R_DATE]
        mov     bx, [handle]
        mov     ax, 5701h
        int     21h
        mov     ah, 3Eh
        int     21h
        pop     bx
        popf
        jc      .err
        mov     ax, [bx+R_SIZE]         ; its clusters
        mov     dx, [bx+R_SIZE+2]
        add     ax, [csize]
        adc     dx, 0
        sub     ax, 1
        sbb     dx, 0
        div     word [csize]
        add     [sysc], ax
.nx:    add     bx, RSZ
        cmp     bx, sysrec + NSYS * RSZ
        jb      .f
        clc
        ret
.err:   mov     dx, s_syswr
        stc
        ret

; ---------------------------------------------------------------------
;    1457664 bytes total disk space
;      78848 bytes used by system
;       1024 bytes in bad sectors
;    1378816 bytes available on disk
;
; Volume Serial Number is 1A2B-3C4D
figures:
        mov     dx, s_crlf
        call    print
        mov     ax, [nclus]
        mov     bx, ax                  ; BX = clusters free
        mov     dx, s_total
        call    fig
        mov     ax, [sysc]
        sub     bx, ax
        or      ax, ax
        jz      .b
        mov     dx, s_used
        call    fig
.b:     mov     ax, [nbad]
        sub     bx, ax
        or      ax, ax
        jz      .a
        mov     dx, s_bad
        call    fig
.a:     mov     ax, bx
        mov     dx, s_avail
        call    fig
        mov     dx, s_ser
        call    print
        mov     ax, [ser+2]
        call    phex
        mov     al, '-'
        call    putc
        mov     ax, [ser]
        call    phex
        mov     dx, s_crlf
        jmp     print

; AX clusters, in bytes in 10 places, then the text at DX
fig:    push    bx
        push    dx
        mul     word [csize]
        mov     cx, 10
        call    pdecw
        pop     dx
        call    print
        pop     bx
        ret

; ---------------------------------------------------------------------
; command tail: d:, /V[:label] /S /Q /F:size /N:n /T:n /4.  CF: DX = why
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
        mov     byte [ntr], 80
.l:     lodsb
        cmp     al, 13
        je      .end
        cmp     al, ' '
        je      .l
        cmp     al, 9
        je      .l
        cmp     al, '/'
        je      .sw
        cmp     byte [si], ':'          ; a drive
        jne     .bad
        and     al, 0DFh
        sub     al, 'A'
        cmp     al, 25
        ja      .bad
        cmp     byte [unit], 0FFh
        jne     .bad
        mov     [unit], al
        inc     si
        jmp     .l
.sw:    lodsb
        and     al, 0DFh
        cmp     al, 'V'
        je      .v
        cmp     al, 'S'
        je      .s
        cmp     al, 'Q'
        je      .q
        cmp     al, 'F'
        je      .f
        cmp     al, 'N'
        je      .n
        cmp     al, 'T'
        je      .t
        cmp     al, '4' & 0DFh
        je      .4
        jmp     .bad
.s:     mov     byte [sys], 1
        jmp     .l
.q:     mov     byte [quick], 1
        jmp     .l
.4:     mov     word [med], m_360
        mov     byte [medset], 1
        jmp     .l
.v:     cmp     byte [si], ':'
        je      .vl
        mov     byte [askv], 1
        jmp     .l
.vl:    inc     si                      ; /V:label, to a space or a /
        mov     di, label
        mov     cx, 12
.vc:    lodsb
        cmp     al, ' '
        jbe     .ve
        cmp     al, '/'
        je      .ve
        stosb
        loop    .vc
        mov     dx, s_badlab            ; (more than 11)
        stc
        ret
.ve:    dec     si
        mov     byte [di], 0
        mov     byte [askv], 0
        jmp     .l
.f:     call    colnum                  ; /F:1440, 1.44, 1.44M, 720K ...
        jc      .bad
        cmp     ax, 1
        jne     .f2
        mov     ax, 1200                ; 1.2 or 1.44
        cmp     dl, 2
        je      .f2
        mov     ax, 1440
        cmp     dl, 44
        jne     .bad
.f2:    call    skipkm
        mov     bx, media_tab
.fl:    mov     di, [bx]
        or      di, di
        jz      .bad
        cmp     ax, [di+M_KB]
        je      .fs
        inc     bx
        inc     bx
        jmp     .fl
.fs:    mov     [med], di
        mov     byte [medset], 1
        jmp     .l
.n:     call    colnum
        jc      .bad
        mov     [nspt], al
        call    .nt
        jmp     .l
.t:     call    colnum
        jc      .bad
        mov     byte [tset], 1
        mov     [ntr], al
        call    .nt
        jmp     .l
.nt:    cmp     byte [nspt], 0          ; /N and /T: the record with both
        je      .ntx
        mov     bx, media_tab
.ntl:   mov     di, [bx]
        or      di, di
        jz      .ntb
        mov     al, [nspt]
        cmp     al, [di+M_SPT]
        jne     .ntn
        mov     al, [ntr]
        cmp     al, [di+M_CYLS]
        je      .nts
.ntn:   inc     bx
        inc     bx
        jmp     .ntl
.nts:   mov     [med], di
        mov     byte [medset], 1
.ntx:   ret
.ntb:   mov     word [med], m_none      ; (refused at the end)
        mov     byte [medset], 1
        ret
.end:   mov     al, [nspt]              ; /N without /T, or /T without /N
        or      al, al
        jz      .e1
        mov     al, 1
.e1:    cmp     al, [tset]
        jne     .bad
        cmp     word [med], m_none
        mov     dx, s_nosup
        je      .x
        clc
        ret
.bad:   mov     dx, s_badsw
.x:     stc
        ret

; ":nnn[.dd]" at SI -> AX = nnn, DL = dd (0 if none), SI past it.  CF if
; no number
colnum: cmp     byte [si], ':'
        jne     .bad
        inc     si
        call    num
        jc      .bad
        push    ax
        xor     dl, dl
        cmp     byte [si], '.'
        jne     .x
        inc     si
        call    num
        jc      .b2
        mov     dl, al
.x:     pop     ax
        clc
        ret
.b2:    pop     ax
.bad:   stc
        ret
num:    xor     ax, ax
        xor     cx, cx
.l:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .e
        imul    ax, ax, 10
        xor     bh, bh
        add     ax, bx
        inc     si
        inc     cx
        jmp     .l
.e:     cmp     cx, 1                   ; CF: no digits
        ret
skipkm: mov     bl, [si]                ; a K, KB, M or MB after a size
        and     bl, 0DFh
        cmp     bl, 'K'
        je      .s
        cmp     bl, 'M'
        jne     .x
.s:     inc     si
        mov     bl, [si]
        and     bl, 0DFh
        cmp     bl, 'B'
        jne     .x
        inc     si
.x:     ret

; =====================================================================
;  C:, the hard disk.  Path A: the kernel has C: (IOCTL 4408h says so):
;  its partition and its layout as they are, so the kernel's drive table
;  stays right with no restart, through its INT 25h/26h.  Path B: an AT
;  drive answers but the kernel found no file system on it: FORMAT drives
;  the registers itself, as KHD.INC does, and makes a new FAT16 layout in
;  the first partition of type 04h, 06h or 0Eh (the one the kernel will
;  take); it then says to restart Lodestone, to use it.  Either way the disk is
;  read through before anything is written, so Esc there leaves it as it
;  was.
; =====================================================================
HCH     equ 64                          ; sectors a transfer (32 KB)
BADMAX  equ 2048                        ; bad clusters kept
MAXCL   equ 65518                       ; clusters the kernel's C: takes (KHD.INC)

hd_main:
        mov     dx, s_badsw             ; /S, /F, /N, /T, /4: floppies'
        mov     al, [sys]
        or      al, [medset]
        or      al, [nspt]
        or      al, [tset]
        jnz     fail_msg
        mov     ax, 0F000h              ; Lodestone?
        int     21h
        cmp     ax, 4F47h
        mov     dx, s_notlode
        jne     fail_msg
        call    alone
        jc      fail_msg
        cmp     byte [label], 0
        je      .lb
        mov     si, label
        call    chk_label
        mov     dx, s_badlab
        jc      fail_msg
.lb:    mov     bx, HCH * 32            ; the transfer buffer
        mov     ah, 48h
        int     21h
        mov     dx, s_hdmem
        jc      fail_msg
        mov     [bseg], ax
        mov     ax, 4408h               ; C: there?  (IOCTL "removable":
        mov     bl, 3                   ;  CF if there's no such drive)
        int     21h
        mov     byte [hpath], 1
        jnc     .a
        mov     byte [hpath], 2
        call    own_setup
        jmp     short .s
.a:     call    kern_setup
.s:     jc      fail_msg
        call    hd_warn                 ; Y, or it ends there (5, 3)
        mov     word [nbad], 0
        call    hd_scan
        jc      .fail
        mov     dx, s_done
        call    print
        cmp     byte [askv], 0
        je      .w
        call    ask_label
.w:     call    serial
        call    hd_boot
        call    hd_sys
        pushf
        call    hd_cd
        popf
        jc      .fail
        mov     word [sysc], 0
        call    figures
        cmp     byte [hpath], 2
        jne     .ok
        mov     dx, s_restart
        call    print
.ok:    call    irq_back
        mov     ax, 4C00h
        int     21h
.fail:  call    print
        mov     dx, s_term
        call    print
        call    irq_back
        mov     ax, 4C04h
        int     21h

; path A, once anything is written (even part of it): the kernel's current
; directory of C: its root again (the old one may now be free clusters)
hd_cd:  cmp     byte [hpath], 1
        jne     .x
        push    dx
        mov     word [path], 'C:'
        mov     word [path+2], '\'
        mov     dx, path
        mov     ah, 3Bh
        int     21h
        pop     dx
.x:     ret

; "Proceed with Format (Y/N)?": Y goes on; N ends it (5), Esc, Ctrl-C 3
; (Y or N, then Enter, as MS-DOS: a key pressed by mistake can be taken
; back with Backspace)
hd_warn:
        call    flush_keys
        mov     dx, s_hdwarn
        call    print
        xor     bl, bl                  ; BL = the answer so far
.k:     call    getkey
        cmp     al, 27
        je      .esc
        cmp     al, 3
        je      .esc
        cmp     al, 1Ah
        je      .esc
        cmp     al, 13
        je      .cr
        cmp     al, 8
        je      .bs
        or      bl, bl
        jnz     .k
        mov     ah, al
        and     ah, 0DFh
        cmp     ah, 'Y'
        je      .a
        cmp     ah, 'N'
        jne     .k
.a:     mov     bl, ah
        call    putc
        jmp     .k
.bs:    or      bl, bl
        jz      .k
        xor     bl, bl
        mov     dx, s_bs
        call    print
        jmp     .k
.cr:    or      bl, bl
        jz      .k
        mov     dx, s_crlf
        call    print
        cmp     bl, 'Y'
        je      .y
        mov     ax, 4C05h
        int     21h
.esc:   jmp     stopped
.y:     ret

; path A: no files open on C:, its boot sector read, its layout.  CF: DX
kern_setup:
        mov     ax, 0F001h
        mov     dl, 2
        int     21h
        mov     dx, s_open
        jcxz    .rd
        stc
        ret
.rd:    xor     ax, ax
        xor     dx, dx
        mov     cx, 1
        call    hd_rd
        mov     dx, s_hdboot
        jc      .x
        push    ds
        mov     ds, [bseg]
        xor     si, si
        mov     di, bootsec
        mov     cx, 256
        rep     movsw
        pop     ds
        jmp     hd_layout
.x:     ret

; path B: alone (no other task may be using the drive), the drive, its
; partition, a new layout in bootsec.  CF: DX
own_setup:
        call    irq_off                 ; (no IRQ 14 for the BIOS to miss)
        call    ata_init
        mov     dx, s_nohd
        jc      .x
        xor     ax, ax                  ; the partition table
        mov     [plba], ax
        mov     [plba+2], ax
        xor     dx, dx
        mov     cx, 1
        call    hd_rd
        mov     dx, s_nohd
        jc      .x
        push    ds
        mov     ds, [bseg]
        mov     dx, s_nopart
        cmp     word [510], 0AA55h
        jne     .np
        mov     si, 446
        mov     cx, 4
.p:     mov     al, [si+4]
        cmp     al, 04h
        je      .fp
        cmp     al, 06h
        je      .fp
        cmp     al, 0Eh
        je      .fp
        add     si, 16
        loop    .p
.np:    pop     ds
        stc
        ret
.fp:    mov     ax, [si+8]
        mov     bx, [si+10]
        mov     cx, [si+12]
        mov     dx, [si+14]
        pop     ds
        mov     [plba], ax
        mov     [plba+2], bx
        mov     [psize], cx
        mov     [psize+2], dx
        mov     dx, s_badpart           ; a sane entry: past the partition
        or      bx, bx                  ;  table, and on the drive
        jnz     .p1
        or      ax, ax
        jz      .x1
.p1:    add     ax, cx                  ; its end, against the drive's size
        adc     bx, [psize+2]
        jc      .x1
        cmp     bx, [hsize+2]
        ja      .x1
        jb      .p2
        cmp     ax, [hsize]
        ja      .x1
.p2:
        mov     di, bootsec             ; a new BPB
        mov     cx, 256
        xor     ax, ax
        rep     stosw
        mov     dx, s_hdbig             ; 2 GB at most (FAT16's 64 KB
        cmp     word [psize+2], 40h     ;  clusters)
        jb      .sz
        ja      .x1
        cmp     word [psize], 0
        jne     .x1
.sz:    mov     al, 4                   ; clusters by the size, as MS-DOS 4
        mov     bx, 4                   ;  and 5: up to 128 MB 2 KB, then
.t:     cmp     [psize+2], bx           ;  twice as big for each doubling
        jb      .fit
        ja      .up
        cmp     word [psize], 0
        je      .fit
.up:    shl     al, 1
        shl     bx, 1
        jmp     .t
.fit:   mov     [bootsec+0Dh], al
        mov     word [bootsec+16h], 1   ; sectors a FAT: grown till it holds
.f:     mov     ax, [psize]             ;  every cluster
        mov     dx, [psize+2]
        mov     bx, [bootsec+16h]
        shl     bx, 1
        add     bx, 1 + 32              ; boot sector, 2 FATs, 512 entries
        sub     ax, bx
        sbb     dx, 0
        jb      .small
        mov     cl, [bootsec+0Dh]
.sh:    shr     cl, 1
        jc      .shd
        shr     dx, 1
        rcr     ax, 1
        jmp     .sh
.shd:   or      dx, dx                  ; DX:AX = clusters: more than the
        jnz     .more                   ;  kernel's C: takes (65,518)?
        cmp     ax, MAXCL
        jbe     .few
.more:  cmp     word [bootsec+16h], 256 ; (the FAT not at its biggest yet:
        jae     .dbl                    ;  so big, it leaves fewer)
        mov     word [bootsec+16h], 256
        jmp     .f
.dbl:   cmp     byte [bootsec+0Dh], 64  ; then bigger clusters
        jae     .big
        shl     byte [bootsec+0Dh], 1
        mov     word [bootsec+16h], 1
        jmp     .f
.few:   cmp     ax, 4085                ; FAT16 (the kernel's C: is)
        jae     .ok
        cmp     byte [bootsec+0Dh], 1   ; smaller clusters for a small disk
        je      .small
        shr     byte [bootsec+0Dh], 1
        jmp     .f
.ok:    add     ax, 2 + 255             ; its FAT's sectors (65,526 + 255
        mov     al, ah                  ;  can carry)
        mov     ah, 0
        adc     ah, 0
        cmp     ax, [bootsec+16h]
        jbe     .done
        mov     [bootsec+16h], ax
        jmp     .f
.small: mov     dx, s_hdsmall
        stc
        ret
.big:   mov     dx, s_hdbig
.x1:    stc
.x:     ret
.done:  mov     word [bootsec+0Bh], 512
        mov     word [bootsec+0Eh], 1
        mov     byte [bootsec+10h], 2
        mov     word [bootsec+11h], 512
        mov     byte [bootsec+15h], 0F8h
        mov     ax, [hspt]
        mov     [bootsec+18h], ax
        mov     ax, [hheads]
        mov     [bootsec+1Ah], ax
        mov     ax, [plba]
        mov     [bootsec+1Ch], ax
        mov     ax, [plba+2]
        mov     [bootsec+1Eh], ax
        mov     ax, [psize]
        mov     dx, [psize+2]
        or      dx, dx
        jnz     .t32
        mov     [bootsec+13h], ax
        jmp     short hd_layout
.t32:   mov     [bootsec+20h], ax
        mov     [bootsec+22h], dx
        ; (on into hd_layout)

; bootsec's BPB -> rootlba, datalba, nclus, ncl, csize, hshift, htot,
; dsecs (the data's sectors): a FAT16 one the kernel takes.  CF: DX
hd_layout:
        mov     dx, s_hdfs
        cmp     word [bootsec+0Bh], 512
        jne     .bad
        mov     al, [bootsec+0Dh]       ; 1, 2, 4 .. 64
        or      al, al
        jz      .bad
        cmp     al, 64
        ja      .bad
        mov     ah, al
        dec     ah
        test    al, ah
        jnz     .bad
        xor     cl, cl
.l2:    shr     al, 1
        jc      .l2d
        inc     cl
        jmp     .l2
.l2d:   mov     [hshift], cl
        mov     al, [bootsec+0Dh]
        xor     ah, ah
        shl     ax, 9
        mov     [csize], ax
        mov     ax, [bootsec+0Eh]       ; reserved, FATs, root
        or      ax, ax
        jz      .bad
        mov     cl, [bootsec+10h]
        dec     cl
        cmp     cl, 1
        ja      .bad
        mov     cx, [bootsec+16h]
        or      cx, cx
        jz      .bad
        cmp     cx, 256
        ja      .bad
        cmp     byte [bootsec+10h], 2
        jne     .f1
        shl     cx, 1
.f1:    add     ax, cx
        mov     [rootlba], ax
        mov     bx, [bootsec+11h]
        or      bx, bx
        jz      .bad
        cmp     bx, 4096
        ja      .bad
        add     bx, 15
        shr     bx, 4
        add     ax, bx
        mov     [datalba], ax
        mov     ax, [bootsec+13h]       ; sectors: 16 bits, else 32
        xor     dx, dx
        or      ax, ax
        jnz     .tt
        mov     ax, [bootsec+20h]
        mov     dx, [bootsec+22h]
.tt:    mov     [htot], ax
        mov     [htot+2], dx
        sub     ax, [datalba]
        sbb     dx, 0
        jb      .bad
        mov     [dsecs], ax
        mov     [dsecs+2], dx
        mov     cl, [hshift]
        or      cl, cl
        jz      .cd
.cs:    shr     dx, 1
        rcr     ax, 1
        dec     cl
        jnz     .cs
.cd:    or      dx, dx
        jnz     .bad
        cmp     ax, 4085
        jb      .bad
        cmp     ax, MAXCL
        ja      .bad
        mov     [nclus], ax
        add     ax, 2
        mov     [ncl], ax
        add     ax, 255                 ; the FAT holds them all
        mov     al, ah
        mov     ah, 0
        adc     ah, 0
        cmp     ax, [bootsec+16h]
        ja      .bad
        clc
        ret
.bad:   stc
        ret

; ---------------------------------------------------------------------
; read the disk before anything is written: the system area (it must all
; be good), then the data, a bad sector making its cluster bad.  /Q: the
; old FAT's bad clusters instead (path A; path B has no FAT to keep).
; Esc stops it, nothing written.  CF: DX
hd_scan:
        cmp     byte [quick], 0
        je      .full
        cmp     byte [hpath], 1
        jne     .qx
        mov     ax, [bootsec+0Eh]       ; the first FAT, HCH sectors at a time
        mov     [scur], ax
        xor     bx, bx                  ; BX = the cluster of an entry
.qf:    mov     ax, [bootsec+0Eh]
        add     ax, [bootsec+16h]
        sub     ax, [scur]
        jbe     .qx
        mov     cx, HCH
        cmp     ax, cx
        jae     .qn
        mov     cx, ax
.qn:    push    bx
        push    cx
        mov     ax, [scur]
        xor     dx, dx
        call    hd_rd
        pop     cx
        pop     bx
        mov     dx, s_hdfat
        jc      .x
        add     [scur], cx
        shl     cx, 8                   ; entries
        push    es
        mov     es, [bseg]
        xor     si, si
.qe:    cmp     bx, [ncl]
        jae     .qd
        cmp     word [es:si], 0FFF7h
        jne     .qnx
        cmp     bx, 2
        jb      .qnx
        push    bx
        mov     ax, bx
        call    add_bad
        pop     bx
        jc      .qerr
.qnx:   inc     bx
        inc     si
        inc     si
        loop    .qe
        pop     es
        jmp     .qf
.qd:    pop     es
.qx:    clc
        ret
.qerr:  pop     es
        ret
.full:  xor     ax, ax                  ; the system area
        mov     [scur], ax
        mov     [scur+2], ax
.sa:    mov     cx, [datalba]
        sub     cx, [scur]
        jbe     .data
        cmp     cx, HCH
        jbe     .san
        mov     cx, HCH
.san:   mov     ax, [scur]
        xor     dx, dx
        call    hd_vf1                  ; (sector by sector if need be)
        mov     dx, s_hd0
        jc      .x
        add     [scur], cx
        jmp     .sa
.data:  mov     word [pct], 0FFFFh
.dl:    call    hd_pct
        call    esc_key
        jc      .esc
        mov     ax, [htot]              ; sectors left
        mov     dx, [htot+2]
        sub     ax, [scur]
        sbb     dx, [scur+2]
        mov     cx, HCH
        or      dx, dx
        jnz     .dn
        or      ax, ax
        jz      .dd
        cmp     ax, cx
        jae     .dn
        mov     cx, ax
.dn:    mov     ax, [scur]
        mov     dx, [scur+2]
        call    hd_vf
        jnc     .dg
        mov     [nsec], cx              ; one at a time
        mov     word [lba], 0
.ds:    mov     ax, [scur]
        mov     dx, [scur+2]
        add     ax, [lba]
        adc     dx, 0
        push    ax
        push    dx
        mov     cx, 1
        call    hd_vf
        pop     dx
        pop     ax
        jnc     .dsn
        sub     ax, [datalba]           ; its cluster
        sbb     dx, 0
        mov     cl, [hshift]
        or      cl, cl
        jz      .dsc
.dss:   shr     dx, 1
        rcr     ax, 1
        dec     cl
        jnz     .dss
.dsc:   add     ax, 2
        cmp     ax, [ncl]               ; (past the last whole cluster)
        jae     .dsn
        call    add_bad
        jc      .x
.dsn:   inc     word [lba]
        mov     cx, [lba]
        cmp     cx, [nsec]
        jb      .ds
.dg:    add     [scur], cx
        adc     word [scur+2], 0
        jmp     .dl
.dd:    mov     dx, s_crlf
        call    print
        clc
        ret
.esc:   mov     dx, s_crlf
        call    print
        mov     dx, s_hdesc
        call    print
        jmp     stop3
.x:     ret

; CX sectors from DX:AX verified, one at a time when the run fails.  CF if
; any fails (the system area: no good)
hd_vf1: call    hd_vf
        jnc     .x
        push    cx
.l:     push    ax
        push    dx
        push    cx
        mov     cx, 1
        call    hd_vf
        pop     cx
        pop     dx
        pop     ax
        jc      .bad
        add     ax, 1
        adc     dx, 0
        loop    .l
        pop     cx
        clc
.x:     ret
.bad:   pop     cx
        stc
        ret

; cluster AX is bad: into the list (once; they come in order).  CF: DX
add_bad:
        mov     bx, [nbad]
        or      bx, bx
        jz      .a
        shl     bx, 1
        cmp     [badl+bx-2], ax
        je      .x
        cmp     word [nbad], BADMAX
        jae     .full
.a:     mov     bx, [nbad]
        shl     bx, 1
        mov     [badl+bx], ax
        inc     word [nbad]
.x:     clc
        ret
.full:  mov     dx, s_hdmany
        stc
        ret

; "nn percent of disk formatted", when it changes
hd_pct: mov     ax, [scur]              ; done = scur - datalba, of dsecs
        mov     dx, [scur+2]
        sub     ax, [datalba]
        sbb     dx, 0
        mov     bx, [dsecs]
        mov     cx, [dsecs+2]
.n:     jcxz    .d                      ; (both halved till the total is 16
        shr     cx, 1                   ;  bits)
        rcr     bx, 1
        shr     dx, 1
        rcr     ax, 1
        jmp     .n
.d:     or      bx, bx
        jz      .x
        mov     cx, 100
        mul     cx
        div     bx
        cmp     ax, [pct]
        je      .x
        mov     [pct], ax
        push    ax
        mov     dx, s_cr
        call    print
        pop     ax
        xor     dx, dx
        mov     cx, 3
        call    pdecw
        mov     dx, s_pct
        call    print
.x:     ret

; ---------------------------------------------------------------------
; the boot sector: a stub that says the disk starts nothing, the BPB as
; it is in bootsec, the serial, the label
hd_boot:
        cmp     byte [hpath], 1         ; path A: the old boot sector's
        jne     .k                      ;  BPB.  (No DOS 4 BPB there: 1Eh-23h
        cmp     byte [bootsec+26h], 29h ;  were boot code, not the hidden
        je      .k                      ;  sectors' high word and the 32-bit
        mov     di, bootsec + 1Eh       ;  total)
        mov     cx, 6
        xor     al, al
        rep     stosb
.k:     mov     si, bootsec + 0Bh       ; the BPB, 0Bh-23h, kept
        mov     di, tb1
        mov     cx, 25
        rep     movsb
        mov     si, hdstub
        mov     di, bootsec
        mov     cx, 256
        rep     movsw
        mov     si, tb1
        mov     di, bootsec + 0Bh
        mov     cx, 25
        rep     movsb
        mov     byte [bootsec+24h], 80h
        call    bs_tail
        mov     si, s_fat16
        mov     di, bootsec + 36h
        mov     cx, 8
        rep     movsb
        ret

; the boot sector, every FAT, the root.  CF: DX
hd_sys: call    zchunk
        push    es
        mov     es, [bseg]
        xor     di, di
        mov     si, bootsec
        mov     cx, 256
        rep     movsw
        pop     es
        xor     ax, ax
        xor     dx, dx
        mov     cx, 1
        call    hd_wr
        jc      .err
        mov     al, [bootsec+10h]       ; the FATs
        mov     [hk], al
        mov     ax, [bootsec+0Eh]
        mov     [scur], ax
.fk:    xor     bx, bx                  ; BX = this copy's sector
.fc:    mov     cx, [bootsec+16h]
        sub     cx, bx
        jbe     .fn
        cmp     cx, HCH
        jbe     .fg
        mov     cx, HCH
.fg:    call    fatchunk
        mov     ax, [scur]
        add     ax, bx
        xor     dx, dx
        call    hd_wr
        jc      .err
        add     bx, cx
        jmp     .fc
.fn:    mov     ax, [bootsec+16h]
        add     [scur], ax
        dec     byte [hk]
        jnz     .fk
        mov     ax, [rootlba]           ; the root (the label first)
        mov     [scur], ax
.rc:    mov     cx, [datalba]
        sub     cx, [scur]
        jbe     .ok
        cmp     cx, HCH
        jbe     .rg
        mov     cx, HCH
.rg:    call    zchunk
        mov     ax, [scur]
        cmp     ax, [rootlba]
        jne     .rw
        cmp     byte [label], 0
        je      .rw
        push    cx
        push    es
        mov     es, [bseg]
        xor     di, di
        mov     si, dirent
        mov     cx, 16
        rep     movsw
        pop     es
        pop     cx
.rw:    mov     ax, [scur]
        xor     dx, dx
        call    hd_wr
        jc      .err
        add     [scur], cx
        jmp     .rc
.ok:    clc
        ret
.err:   mov     dx, s_hdwr
        stc
        ret

; the transfer buffer: 0s (all HCH sectors)
zchunk: pusha
        push    es
        mov     es, [bseg]
        xor     di, di
        mov     cx, HCH * 256
        xor     ax, ax
        rep     stosw
        pop     es
        popa
        ret

; FAT sectors BX .. BX+CX-1 into the buffer: FFF8h FFFFh (the media),
; FFF7h for the bad clusters, 0 for the rest
fatchunk:
        pusha
        call    zchunk
        push    es
        mov     es, [bseg]
        or      bx, bx
        jnz     .b
        mov     al, [bootsec+15h]
        mov     ah, 0FFh
        mov     [es:0], ax
        mov     word [es:2], 0FFFFh
.b:     mov     dx, bx                  ; [DX, DI): the sectors here
        mov     di, bx
        add     di, cx
        xor     si, si
.l:     cmp     si, [nbad]
        jae     .x
        mov     bx, si
        shl     bx, 1
        mov     ax, [badl+bx]
        mov     bl, ah                  ; its FAT sector
        xor     bh, bh
        cmp     bx, dx
        jb      .n
        cmp     bx, di
        jae     .n
        sub     bx, dx
        shl     bx, 9
        xor     ah, ah
        shl     ax, 1
        add     bx, ax
        mov     word [es:bx], 0FFF7h
.n:     inc     si
        jmp     .l
.x:     pop     es
        popa
        ret

; ---------------------------------------------------------------------
; CX sectors (HCH at most) at sector DX:AX of the partition, to or from
; [bseg]:0 (hd_vf: read and not kept, or verified by the drive).  CF if
; it failed.  Keeps all registers
hd_rd:  push    bx
        mov     bx, 0220h
        jmp     short hd_io
hd_vf:  push    bx
        mov     bx, 0240h
        jmp     short hd_io
hd_wr:  push    bx
        mov     bx, 0330h
hd_io:  pusha
        cmp     byte [hpath], 1
        jne     .own
        mov     [pk_lba], ax            ; path A: the kernel's INT 25h/26h,
        mov     [pk_lba+2], dx          ;  DOS 4's packet
        mov     [pk_n], cx
        mov     word [pk_buf], 0
        mov     ax, [bseg]
        mov     [pk_buf+2], ax
        mov     al, 2
        mov     cx, 0FFFFh
        cmp     bh, 3
        mov     bx, pk_lba
        je      .w
        int     25h
        jmp     short .k
.w:     int     26h
.k:     pop     bx                      ; (the flags INT 25h/26h leave)
        popa
        pop     bx
        ret
.own:   add     ax, [plba]              ; path B: the drive itself
        adc     dx, [plba+2]
        call    ata_xfer
        popa
        pop     bx
        ret

; the boot sector of a disk formatted here: it starts nothing
hdstub: jmp     short .go
        nop
        db      'LODESTON'
        times   3Eh - ($ - hdstub) db 0
.go:    cli
        xor     ax, ax
        mov     ss, ax
        mov     sp, 7C00h
        mov     ds, ax
        sti
        cld
        mov     si, 7C00h + hs_msg - hdstub
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
hs_msg  db      'This disk starts nothing: Lodestone starts from its ROM or a floppy.', 13, 10
        db      'Press a key.', 13, 10, 0
        times   510 - ($ - hdstub) db 0
        dw      0AA55h

; ---------------------------------------------------------------------
; ---------------------------------------------------------------------
; stdin the keyboard: drop keys typed before a question
flush_keys:
        mov     ax, 4400h
        xor     bx, bx
        int     21h
        jc      .x
        and     dl, 81h                 ; a device, the console's input
        cmp     dl, 81h
        jne     .x
.l:     mov     ah, 1
        int     16h
        jz      .x
        xor     ah, ah
        int     16h
        jmp     .l
.x:     ret

; a key through DOS (no echo; Ctrl-C stops), AL
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

; DX:AX in decimal: pdec as it is, pdecw right-aligned in CX places
pdec:   xor     cx, cx
pdecw:  pusha
        mov     di, numbuf + 12
        mov     bx, 10
.d:     push    ax                      ; DX:AX / 10, the remainder to DI
        mov     ax, dx
        xor     dx, dx
        div     bx
        mov     si, ax                  ; the high quotient
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
        sub     ax, di                  ; digits
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

; AX in 4 hex digits
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
; the formats: cylinders, sectors per track, per cluster, its log2,
; sectors per FAT, media byte, root entries, sectors, INT 13h 17h's type,
; the name, its bit in takes, its size in KB
%macro media 12
        db      %1, %2, %3, %4, %5, %6
        dw      %7, %8
        db      %9
        dw      %10
        db      %11
        dw      %12
%endmacro
m_360:  media   40,  9, 2, 1, 2, 0FDh, 112,  720, 1, n_360,  1, 360
m_720:  media   80,  9, 2, 1, 3, 0F9h, 112, 1440, 4, n_720,  2, 720
m_1200: media   80, 15, 1, 0, 7, 0F9h, 224, 2400, 3, n_1200, 4, 1200
m_1440: media   80, 18, 1, 0, 9, 0F0h, 224, 2880, 0, n_1440, 8, 1440
m_none: media    0,  0, 1, 0, 1, 0,      0,    0, 0, n_1440, 0, 0   ; (/N, /T: none)
media_tab dw m_360, m_720, m_1200, m_1440, 0
; the formats each kind of drive (INT 13h 08h's BL, 1-4) takes
takes   db      1, 1 | 4, 2, 2 | 8
n_360   db '360K$'
n_720   db '720K$'
n_1200  db '1.2M$'
n_1440  db '1.44M$'

; the system files (/S), in the order they go on: LODE.SYS first
sysnames db 'LODE.SYS', 0, 'LODEMT.SYS', 0, 'LODE.PIC', 0, 'LCMD.COM', 0
R_NAME  equ 0                           ; -> its name (0: not there)
R_SEG   equ 2                           ; its memory
R_SIZE  equ 4                           ; dword
R_TIME  equ 8
R_DATE  equ 10
R_PATH  equ 12                          ; "X:\NAME", 0 (16)
RSZ     equ 28

badch   db '"*+,./:;<=>?[\]|()&^'
badch_n equ $ - badch
s_noname db 'NO NAME', 0

s_insert db 13, 10, 'Insert new diskette for drive '
s_d1    db 'A:', 13, 10, 'and strike ENTER when ready (Esc: quit)$'
s_fmt   db 'Formatting $'
s_qfmt  db 'QuickFormatting', 13, 10, '$'
s_head  db 'Head: $'
s_cyl   db '   Cylinder: $'
s_done  db 'Format complete', 13, 10, '$'
s_sysok db 'System transferred', 13, 10, '$'
s_vask  db 13, 10, 'Volume label (11 characters, ENTER for none)? $'
s_badlab db 'Invalid characters in volume label', 13, 10, '$'
s_total db ' bytes total disk space', 13, 10, '$'
s_used  db ' bytes used by system', 13, 10, '$'
s_bad   db ' bytes in bad sectors', 13, 10, '$'
s_avail db ' bytes available on disk', 13, 10, '$'
s_ser   db 13, 10, 'Volume Serial Number is $'
s_again db 13, 10, 'Format another (Y/N)? $'
s_term  db 'Format terminated', 13, 10, '$'
s_wprot db 'Write protect error', 13, 10, '$'
s_nrdy  db 'Not ready - no disk in drive '
s_d2    db 'A:?', 13, 10, '$'
s_trk0  db 'Invalid media or Track 0 bad - disk unusable', 13, 10, '$'
s_qbad  db 'Invalid existing format.', 13, 10
        db 'This disk cannot be QuickFormatted (FORMAT without /Q formats it).', 13, 10, '$'
s_qdiff db 'Existing format differs from that specified.', 13, 10
        db 'This disk cannot be QuickFormatted (FORMAT without /Q formats it).', 13, 10, '$'
s_open  db 'Files are open on drive '
s_d3    db 'A: (a batch file or a program running from it)', 13, 10, '$'
s_nodrv db 'FORMAT: which drive?  FORMAT A: [/V[:label]] [/S] [/Q] [/F:size]', 13, 10, '$'
s_notfl db 'FORMAT: floppies (A:, B:) and the hard disk (C:) only', 13, 10, '$'
s_baddrv db 'Invalid drive specification', 13, 10, '$'
s_badsw db 'Invalid parameter', 13, 10, '$'
s_nosup db 'Parameters not supported by drive', 13, 10, '$'
s_notlode db 'FORMAT: needs Lodestone (other DOSes have their own FORMAT)', 13, 10, '$'
s_nosys db 'Cannot find the system: no LODE.SYS on the start-up drive', 13, 10, '$'
s_sysmem db 'Insufficient memory for system transfer', 13, 10, '$'
s_sysrd db 'Cannot read the system files', 13, 10, '$'
s_syswr db 'Cannot write the system files', 13, 10, '$'
s_hdwarn db 'WARNING, ALL DATA ON NON-REMOVABLE DISK', 13, 10
        db 'DRIVE C: WILL BE LOST!', 13, 10
        db 'Proceed with Format (Y/N)? $'
s_pct   db ' percent of disk formatted$'
s_hdesc db 'Stopped: nothing written', 13, 10, '$'
s_restart db 13, 10, 'Restart Lodestone to use C:', 13, 10, '$'
s_hdmem db 'Insufficient memory', 13, 10, '$'
s_hdboot db 'C:', 39, 's boot sector cannot be read', 13, 10, '$'
s_hdfs  db 'C:', 39, 's layout is not a FAT16 one Lodestone uses', 13, 10, '$'
s_hdfat db 'C:', 39, 's FAT cannot be read (FORMAT without /Q formats it)', 13, 10, '$'
s_hd0   db 'Invalid media or Track 0 bad - disk unusable', 13, 10
        db '(the boot sector, a FAT or the root cannot be read)', 13, 10, '$'
s_hdmany db 'Too many bad sectors - disk unusable', 13, 10, '$'
s_hdwr  db 'Disk error writing C:', 13, 10, '$'
s_nohd  db 'No hard disk answers', 13, 10, '$'
s_nopart db 'C: has no FAT16 partition (type 04h, 06h or 0Eh): FDISK it first', 13, 10, '$'
s_hdbig db 'C:', 39, 's partition is too big for FAT16 (2 GB at most)', 13, 10, '$'
s_hdsmall db 'C:', 39, 's partition is too small for FAT16', 13, 10, '$'
s_fat16 db 'FAT16   '
s_tasks db 'FORMAT: other tasks are running, or FORMAT runs as one (Shift-Return', 13, 10
        db 'with no other tasks: alone)', 13, 10, '$'
s_badpart db 'C:', 39, 's partition entry is wrong (it starts at 0, or runs past the', 13, 10
        db 'end of the drive): FDISK it again', 13, 10, '$'
s_bs    db 8, ' ', 8, '$'
s_cr    db 13, '$'
s_crlf  db 13, 10, '$'

section .bss                            ; (ATAIO.INC's variables in the
bss_start:                              ;  cleared part)
section .text
%include "ATAIO.INC"

        alignb 2
bootbin incbin "BOOT.BIN"

        alignb 2
section .bss
unit    resb 1
dkind   resb 1
sys     resb 1
quick   resb 1
askv    resb 1
medset  resb 1
nspt    resb 1
ntr     resb 1
dptset  resb 1
tset    resb 1
result  resb 1
cyl     resb 1
head    resb 1
sct     resb 1
xop     resb 1
        alignb 2
med     resw 1
tbuf    resw 1
rootlba resw 1
datalba resw 1
nclus   resw 1
ncl     resw 1
csize   resw 1
nbad    resw 1
sysc    resw 1
lba     resw 1
nsec    resw 1
handle  resw 1
nfmt    resw 1
ser     resw 2
dpt0    resw 2
dpt1    resw 2
label   resb 14
kbuf    resb 16
dirent  resb 32
numbuf  resb 14
path    resb 20
hpath   resb 1                          ; C:: 1 the kernel's, 2 our own
hshift  resb 1
hk      resb 1
        alignb 2
bseg    resw 1
plba    resw 2
psize   resw 2
htot    resw 2
dsecs   resw 2
scur    resw 2
pct     resw 1
pk_lba  resw 2                          ; INT 25h/26h's packet
pk_n    resw 1
pk_buf  resw 2
badl    resw BADMAX
sysrec  resb NSYS * RSZ
bootsec resb 512
fat     resb MAXSPF * 512
        alignb 16
tb1     resb MAXSPT * 512
tb2     resb MAXSPT * 512
        resb 512
stack_top:
bss_end:
prog_end:
