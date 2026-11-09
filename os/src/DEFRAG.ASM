; DEFRAG.COM - Lodestone disk defragmenter, and the Executive's screen saver
;
;   DEFRAG [A:|B:|C:]      tidy the floppy in drive A: or B: (BIOS unit 0
;                          or 1), or the hard disk C: (the current drive
;                          if none is given; M:, the temporary disk in
;                          memory, has nothing to tidy)
;   DEFRAG [A:|B:|C:] /T   test the free space; mark bad clusters
;   DEFRAG /S [M=ssss:oooo] [F=ssss:oooo]
;                          screen-saver mode, started by the Executive when
;                          the screen saver starts (the delay set in System).  Any key, or the Executive's mouse
;                          flag at ssss:oooo turning non-zero, stops it.
;                          F=: the screen font in use (1,536 bytes, codes
;                          32-127), so the map has the Executive's font.
;
; Floppies (FAT12) go through INT 13h, a track at a time.  C: (FAT16, up
; to 2 GB: sector numbers are 32 bits, BP the high word) goes through the
; kernel's INT 25h/26h, 18 sectors at a time; it has no change line.  The
; FAT, the map of the clusters' owners and the root's two copies are
; memory sized to the disk (C:: about 200 KB more while it runs; nothing
; stays behind).
;
; Every cluster of the disk is on the 640x400 screen, a cell each, or (on
; a disk of more than 2,880) a cell for several, showing the most
; important state among them.  It then
;  1. squeezes the deleted entries out of the root directory.  Sectors are
;     written lowest first, so an entry is in its new place before its old
;     place is overwritten: a power cut can at worst leave an entry twice,
;     and the next run removes the second copy;
;  2. joins up fragmented files and moves files forward into the gaps, so
;     each file is in one piece and the free space ends up at the end.
; A file only ever moves whole, like this:
;     copy its data into clusters that are free on the disk, read it back
;     and compare; FAT: add the new chain (the old one untouched); the
;     directory entry: point it at the new chain (one sector - the switch);
;     FAT: free the old chain.
; A power cut or a pulled disk therefore leaves the old file or the new one,
; never a damaged one - at worst some lost clusters.  On a floppy the change
; line is checked before every disk access, and it stops if the disk has
; changed.
; It writes only under Lodestone (GRiD MS-DOS keeps its own copies of the FAT
; and directories).  Elsewhere, or on a write-protected disk, or if the disk
; needs CHKDSK, it only shows the map.
;
; Old disks wear, so a disk error doesn't stop it:
;   - a copy that won't write or read back right: the copy is abandoned
;     (nothing switched), its clusters are tested one sector at a time, and
;     the failing ones are marked bad (FF7h, FAT16 FFF7h) in the FAT.  A spot that fails
;     as part of a run but passes alone is marked the second time;
;   - a file sector that can't be read (after 4 tries each): the file stays
;     where it is, the rest goes on;
;   - 8 failures in a row: two test writes near the start.  If they work,
;     files moved out of the way go just past themselves from then on, not
;     to the far end; if they fail too, it stops ("Writes fail everywhere").
; DEFRAG /T tests the free space instead (a pattern written and read back,
; track by track) and marks the bad clusters.  Each run that marked or
; moved anything, or failed, adds a line to DEFRAG.TXT on that disk (through the
; kernel), with up to 8 disk errors: "Disk error 10h reading cylinder c
; side h sector s" (C:: "... sector n") - where the failing request started.
;
; Exit code: 0 the disk is in order, 1 stopped by a key or the mouse,
; 2 couldn't (write-protected, disk changed, disk error, needs CHKDSK, ...),
; 3 (/S only) the disk couldn't be read at all (an empty drive): nothing
; shown.
cpu 286
org 100h

VSEG    equ 0B800h
MAXF    equ 240                 ; files we can move
FSZ     equ 32                  ; file record
MAXSPF  equ 256                 ; FAT sectors that can hold entries (FAT16:
                                ;  65,536); a bigger FAT's rest is unused
MAXRS   equ 32                  ; root directory sectors (512 entries)
MAXDQ   equ 64                  ; subdirectories
BUFA    equ 0                   ; in the DMA buffer segment: 18 sectors each
BUFB    equ 2400h
MAP_Y   equ 24
LEG_Y   equ 316
STAT_Y  equ 336
BAND_Y  equ 360
; owner codes (files are 1..MAXF)
O_LOST  equ 0FBh
O_BAD   equ 0FCh
O_DIR   equ 0FDh
O_FIX   equ 0FEh                ; system files: never moved
; cell patterns
P_FREE  equ 0
P_FILE  equ 1
P_FRAG  equ 2
P_DIR   equ 3
P_BAD   equ 4
P_LOST  equ 5
P_READ  equ 6
P_WRITE equ 7
; file record
F_NAME  equ 0                   ; 11 bytes
F_ATTR  equ 11
F_DLBA  equ 12                  ; sector holding its directory entry
F_DOFF  equ 14                  ; and the entry's offset in it
F_DLBAH equ 22                  ; (the sector's high word)
F_START equ 16
F_NCL   equ 18
F_FLAGS equ 20
FL_FRAG equ 1                   ; not in one piece
FL_OUT  equ 2                   ; moved out of the way once already
FL_STUCK equ 4                  ; can't be read: stays where it is

; =====================================================================
start:  cld
        mov     bx, rootbuf + MAXRS * 1024 + 15 ; what we use (the root's
                                                ;  two copies: the most, until
                                                ;  the disk says)
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        jc      nomem
        mov     sp, stack_top
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        call    args
        cmp     byte [unitset], 0               ; no drive given: the current
        jne     .u                              ; one
        mov     ah, 19h
        int     21h
        mov     [unit], al
.u:     cmp     byte [unit], 12                 ; M:: in memory, nothing to
        je      memdrv                          ;  tidy
        int     11h                             ; is there such a drive?
        xor     cl, cl
        test    al, 1
        jz      .un
        mov     cl, al
        shr     cl, 6
        inc     cl
.un:    cmp     byte [unit], 2                  ; C:: is it there?  (IOCTL
        jne     .ul                             ;  "removable?": CF if not)
        mov     ax, 4408h
        mov     bl, 3
        int     21h
        mov     cl, 3
        jnc     .ul
        xor     cl, cl
.ul:    mov     al, [unit]
        add     al, 'A'
        mov     [lt_drive], al
        mov     [lt_band1], al
        mov     [lt_band1t], al
        mov     [lt_band1s], al
        mov     [lt_open], al
        mov     [s_logf], al
        mov     [lt_nodrv], al
        sub     al, 'A'
        cmp     al, cl
        jae     nodrv
        mov     bx, 900h                        ; 36 KB: an 18 KB window in
        mov     ah, 48h                         ; it doesn't cross 64 KB
        int     21h
        jc      nomem
        mov     dx, ax
        shl     ax, 4
        cmp     ax, 0B800h
        jbe     .seg
        add     dx, 0FFFh
        and     dx, 0F000h
.seg:   mov     [bseg], dx
        mov     ax, 0F000h                      ; Lodestone?  (its own call)
        int     21h
        cmp     ax, 4F47h
        jne     .ro
        mov     byte [lodestone], 1
.ro:    push    ds
        xor     ax, ax
        mov     ds, ax
        mov     al, [449h]
        pop     ds
        mov     [oldmode], al
        mov     ax, 0040h                       ; the GRiD's 640x400 mode
        int     10h
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     al, [449h]
        pop     ds
        cmp     al, 40h
        jne     nogfx
        call    mkrows
        mov     dx, crit                        ; a critical error (only the
        mov     ax, 2524h                       ; log file write can cause
        int     21h                             ; one): fail, no prompt
        mov     [sp0], sp
        jmp     main
crit:   mov     al, 83h                 ; (Fail, nobody asked: the kernel
        iret                            ;  drops nothing, its rule 4)

nomem:  mov     dx, s_nomem
        jmp     short txtfail
nodrv:  mov     dx, s_nodrv
        jmp     short txtfail
memdrv: mov     dx, s_memdrv                    ; (in order: exit code 0)
        mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h
nogfx:  mov     ax, 0003h
        int     10h
        mov     dx, s_nogfx
txtfail:
        mov     ah, 9
        int     21h
        mov     ax, 4C02h
        int     21h

; command tail: /S, M=ssss:oooo, F=ssss:oooo
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        add     bx, si
        mov     byte [bx], 13                   ; (the end, whatever it held)
.l:     lodsb
        cmp     al, 13
        je      .x
        cmp     al, '/'
        jne     .m
        lodsb
        cmp     al, 13
        je      .x
        and     al, 0DFh
        cmp     al, 'T'
        je      .t
        cmp     al, 'S'
        jne     .l
        mov     byte [saver], 1
        jmp     .l
.t:     mov     byte [testmode], 1
        jmp     .l
.m:     and     al, 0DFh
        cmp     byte [si], ':'                  ; A:, B: or C: (any letter:
        jne     .m2                             ;  the others are refused)
        sub     al, 'A'
        cmp     al, 25
        ja      .l
        mov     [unit], al
        mov     byte [unitset], 1
        inc     si
        jmp     .l
.m2:    cmp     al, 'F'
        je      .f
        cmp     al, 'M'
        jne     .l
        cmp     byte [si], '='
        jne     .l
        inc     si
        call    hex
        mov     [mptr+2], dx
        cmp     byte [si], ':'
        jne     .x
        inc     si
        call    hex
        mov     [mptr], dx
        mov     byte [mouse], 1
        jmp     .l
.f:     cmp     byte [si], '='          ; F=ssss:oooo: that font, for ours
        jne     .l
        inc     si
        call    hex
        cmp     byte [si], ':'
        jne     .x
        inc     si
        push    dx                      ; (the segment: hex uses AL)
        call    hex
        pop     ax
        push    ds
        push    es
        push    si
        push    cs
        pop     es
        mov     ds, ax
        mov     si, dx
        mov     di, font
        mov     cx, 96 * 16 / 2
        cld
        rep     movsw
        pop     si
        pop     es
        pop     ds
        jmp     .l
.x:     ret
hex:    xor     dx, dx                          ; SI -> DX, SI past the digits
.h:     mov     al, [si]
        sub     al, '0'
        cmp     al, 10
        jb      .d
        and     al, 0DFh
        sub     al, 7
        cmp     al, 10
        jb      .x
        cmp     al, 16
        jae     .x
.d:     shl     dx, 4
        or      dl, al
        inc     si
        jmp     .h
.x:     ret

; =====================================================================
main:   call    clear_screen
        mov     si, s_title
        xor     dx, dx
        xor     ah, ah
        call    center
        mov     si, s_drive
        mov     bx, 1
        call    puts
        mov     dx, 19
        xor     bx, bx
        mov     cx, 80
        call    hline
        mov     si, s_band1
        cmp     byte [testmode], 0
        je      .b0
        mov     si, s_band1t
.b0:    cmp     byte [saver], 0
        je      .b
        mov     si, s_band1s
.b:     mov     di, s_band2
        call    band
        mov     si, s_reading
        call    status
        mov     ax, 0D00h                       ; the kernel's FAT and
        int     21h                             ; directories to the disk
        cmp     byte [lodestone], 0
        je      .rd
        cmp     al, 0FFh                        ; (it couldn't write them)
        jne     .of
        mov     word [ronly_why], s_nosave
        mov     byte [ronly], 1
.of:    mov     ax, 0F001h                      ; files open on it?  (a batch
        mov     dl, [unit]                      ;  file, or the program that
        int     21h                             ;  started this one)
        jcxz    .rd
        mov     word [ronly_why], s_open
        mov     byte [ronly], 1
.rd:    mov     word [ww], s_rderr
        call    read_disk
        jc      .rerr
        call    draw_frame
        call    pack_root
        mov     word [ww], s_chkdsk
        call    walk
        jnc     .walked
        mov     si, [ww]
        jmp     short .rodraw
.walked:
        call    draw_map
        cmp     byte [ronly], 0
        je      .work
        mov     si, [ronly_why]
        jmp     short .ro
.rodraw:
        call    draw_map
.ro:    mov     byte [result], 2
        jmp     finish_msg
.rerr:  cmp     byte [saver], 0                 ; the screen saver going round
        je      .rem                            ;  the disks: none to read
        mov     byte [result], 3                ;  here (an empty drive):
        jmp     out                             ;  on to the next, at once
.rem:   mov     si, [ww]
        mov     byte [result], 2
        jmp     finish_msg

.work:  mov     byte [writing], 1
        cmp     byte [testmode], 0
        je      .tidy
        mov     si, s_testing
        call    status
        call    surface
        mov     di, msgbuf                      ; "Free space tested: 1033 KB,
        mov     si, s_tested                    ;  17 bad clusters marked"
        call    sb_str
        mov     ax, [ntsec]
        mov     dx, [ntsec+2]
        shr     dx, 1
        rcr     ax, 1
        call    sb_u32
        mov     si, s_kbc
        call    sb_str
        mov     ax, [nerrs]
        mov     si, s_err
        call    sb_count
        mov     si, s_comma
        call    sb_str
        mov     ax, [nbadm]
        mov     si, s_badc
        call    sb_count
        mov     si, s_marked
        call    sb_str
        mov     byte [di], 0
        mov     si, msgbuf
        mov     byte [result], 0
        mov     byte [logit], 1
        jmp     finish_msg
.tidy:
        cmp     byte [fdany], 0
        je      .wr
        mov     si, s_fatsync
        call    status
        call    fat_flush
        jc      stop2
.wr:    call    write_root
        call    tidy
        call    sb_done
        mov     si, msgbuf
        mov     byte [result], 0
        xor     bx, bx                          ; any file we couldn't read
        xor     ax, ax                          ; or join?
        xor     dx, dx
.lf:    cmp     bx, [nfiles]
        jae     .lfx
        call    rec_of
        test    byte [di+F_FLAGS], FL_STUCK
        jz      .lf1
        inc     dx
.lf1:   test    byte [di+F_FLAGS], FL_FRAG
        jz      .lfn
        inc     ax
.lfn:   inc     bx
        jmp     .lf
.lfx:   or      dx, dx
        jz      .lfy
        mov     di, msgbuf                      ; "Done - 1 file couldn't be
        push    dx                              ; read, left as it is"
        mov     si, s_unr1
        call    sb_str
        pop     ax
        mov     si, s_file
        call    sb_count
        mov     si, s_unread
        call    sb_str
        mov     byte [di], 0
        mov     si, msgbuf
        mov     byte [result], 2
        mov     byte [logit], 1
        jmp     .fin
.lfy:   or      ax, ax
        jz      .fin
        mov     di, msgbuf
        push    ax
        mov     si, s_left1
        call    sb_str
        pop     ax
        mov     si, s_file
        call    sb_count
        mov     si, s_left2
        call    sb_str
        mov     byte [di], 0
        mov     si, msgbuf
        mov     byte [result], 2
.fin:   jmp     finish_msg

; ---------------------------------------------------------------------
; the end: SI = message.  Saver: a few seconds, then out.  Otherwise
; wait for a key.
finish_msg:
        mov     sp, [sp0]
        call    status
        push    si
        mov     ah, 0Dh                         ; the kernel reads it all
        int     21h                             ; again (and checks it is
        pop     si                              ; still the same disk)
        cmp     byte [logit], 0
        je      .nl
        call    log_all
.nl:    cmp     byte [saver], 0
        je      .key
        mov     si, s_band1s
        mov     di, s_band2
        call    band
        mov     cx, 73                          ; ~4 s
        call    pause
        jc      stop1
        jmp     out
.key:   mov     si, s_band1
        mov     di, s_anykey
        call    band
.k:     call    disturbed
        jnc     .k
        call    eat_key
        jmp     out

; stopped by a key or the mouse (only ever at a safe point)
stop1:  mov     sp, [sp0]
        call    eat_key
        mov     ah, 0Dh
        int     21h
        mov     byte [result], 1
        cmp     byte [logit], 0
        je      .nl
        mov     si, s_stopped
        call    log_all
        mov     byte [logit], 0
.nl:
        cmp     byte [saver], 0
        jne     out
        call    draw_map
        mov     si, s_stopped
        mov     byte [result], 1
        jmp     finish_msg
out:    cmp     byte [saver], 0                 ; (the Executive sets its own)
        jne     .x
        mov     al, [oldmode]
        xor     ah, ah
        int     10h
.x:     mov     al, [result]
        mov     ah, 4Ch
        int     21h

; a disk error or a changed disk while writing: stop, say why
stop2:  mov     sp, [sp0]
        mov     byte [result], 2
        cmp     ah, 3                           ; (these two: no log - the
        mov     si, s_wprot                     ;  disk can't take it, or
        je      .q                              ;  it is another disk)
        cmp     ah, 6
        mov     si, s_changed
        je      .q
        mov     byte [logit], 1
        cmp     ah, 0FEh
        mov     si, s_entry
        je      .m
        cmp     ah, 0FDh
        mov     si, s_toobad
        je      .m
        ; "Disk error 10h writing cylinder 72 side 1 sector 5 - stopped,
        ; files fine"
        mov     di, msgbuf
        mov     al, [er_op]
        mov     ah, [er_code]
        mov     dx, [er_lba]
        mov     bp, [er_lba+2]
        call    sb_where
        mov     si, s_derr2
        call    sb_str
        mov     byte [di], 0
        mov     si, msgbuf
.m:     jmp     finish_msg
.q:     mov     byte [logit], 0
        jmp     finish_msg

; AL = op (2 read, 3 write, FFh read back different), AH = BIOS code,
; BP:DX = sector: "Disk error 10h writing cylinder 72 side 1 sector 5" (a
; floppy) or "... sector 85174" (C:) at DI
sb_where:
        push    dx
        mov     si, s_rbdiff
        cmp     al, 0FFh
        je      .w
        push    ax
        mov     si, s_derr
        call    sb_str
        pop     ax
        push    ax
        mov     al, ah
        call    sb_hex2
        pop     ax
        mov     si, s_reading2
        cmp     al, 2
        je      .w
        mov     si, s_writing
.w:     call    sb_str
        cmp     byte [unit], 2
        jne     .f
        mov     si, s_sector + 1
        call    sb_str
        pop     ax
        mov     dx, bp
        jmp     sb_u32
.f:     mov     si, s_cyl
        call    sb_str
        mov     ax, [spt]
        mul     word [heads]
        mov     cx, ax
        pop     ax
        xor     dx, dx
        div     cx                              ; AX = cylinder
        push    dx
        call    sb_u16
        mov     si, s_side
        call    sb_str
        pop     ax
        xor     dx, dx
        div     word [spt]                      ; AX = side, DX = sector-1
        push    dx
        call    sb_u16
        mov     si, s_sector
        call    sb_str
        pop     ax
        inc     ax
        jmp     sb_u16

; remember this disk error for the log (the first 8 of a run)
note_err:
        push    ax
        push    bx
        inc     word [nerrs]                    ; (all of them; the first 8
        mov     bx, [nev]                       ;  are kept for the log)
        cmp     bx, 8
        jae     .x
        inc     word [nev]
        shl     bx, 3
        mov     al, [er_op]
        mov     [evs+bx], al
        mov     al, [er_code]
        mov     [evs+bx+1], al
        mov     ax, [er_lba]
        mov     [evs+bx+2], ax
        mov     ax, [er_lba+2]
        mov     [evs+bx+4], ax
.x:     pop     bx
        pop     ax
        ret

eat_key:
        mov     ah, 1
        int     16h
        jz      .x
        xor     ah, ah
        int     16h
        jmp     eat_key
.x:     ret

; key or mouse?  CF if so
disturbed:
        push    ax
        push    bx
        push    es
        mov     ah, 1
        int     16h
        jnz     .yes
        cmp     byte [mouse], 0
        je      .no
        les     bx, [mptr]
        cmp     byte [es:bx], 0
        jne     .yes
.no:    pop     es
        pop     bx
        pop     ax
        clc
        ret
.yes:   pop     es
        pop     bx
        pop     ax
        stc
        ret

; CX ticks, or until disturbed (CF)
pause:  push    cx
        call    tick
        mov     bx, ax
        pop     cx
.w:     call    disturbed
        jc      .x
        call    tick
        sub     ax, bx
        cmp     ax, cx
        jb      .w
        clc
.x:     ret
tick:   push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

; =====================================================================
;  reading the disk
; =====================================================================
read_disk:
        cmp     byte [unit], 2                  ; C: only through Lodestone's
        jne     .rd0                            ;  INT 25h (DOS 3's has no
        cmp     byte [lodestone], 0                ;  32-bit form)
        je      .bad
.rd0:   xor     bp, bp                          ; (all in the first 64K sectors)
        mov     word [spt], 18                  ; (for sector 0 itself)
        mov     word [heads], 2
        xor     dx, dx
        mov     cx, 1
        mov     di, bootsec
        call    rd_near
        jc      .x
        ; the layout: 512-byte sectors, clusters of 1, 2, 4 .. 64 of them
        cmp     word [bootsec+0Bh], 512
        jne     .bad
        mov     al, [bootsec+0Dh]
        or      al, al
        jz      .bad
        cmp     al, 64
        ja      .bad
        mov     ah, al
        dec     ah
        test    al, ah
        jnz     .bad
        xor     ah, ah
        mov     [spc], ax
        shl     ax, 9
        mov     [cbytes], ax
        mov     ax, 0FFFFh
        xor     dx, dx
        div     word [spc]
        mov     [rcap], ax
        cmp     byte [unit], 2                  ; C:: the kernel goes by CHS;
        jne     .fg                             ;  our "track" is 18 sectors
        mov     word [heads], 1
        jmp     short .lay
.fg:    mov     ax, [bootsec+18h]               ; a floppy: its geometry
        or      ax, ax
        jz      .bad
        cmp     ax, 18
        ja      .bad
        mov     [spt], ax
        mov     ax, [bootsec+1Ah]
        or      ax, ax
        jz      .bad
        cmp     ax, 2
        ja      .bad
        mov     [heads], ax
.lay:   mov     ax, [bootsec+0Eh]
        or      ax, ax
        jz      .bad
        mov     [rsv], ax
        mov     al, [bootsec+10h]
        xor     ah, ah
        or      ax, ax
        jz      .bad
        cmp     ax, 2
        ja      .bad
        mov     [nfat], ax
        mov     ax, [bootsec+16h]
        or      ax, ax
        jz      .bad
        mov     [spf], ax
        cmp     ax, MAXSPF
        jbe     .fs
        mov     ax, MAXSPF
.fs:    mov     [fsec], ax
        mov     ax, [spf]
        mul     word [nfat]
        jc      .bad
        add     ax, [rsv]
        jc      .bad
        mov     [rootlba], ax
        mov     ax, [bootsec+11h]
        or      ax, ax
        jz      .bad
        cmp     ax, MAXRS * 16
        ja      .bad
        mov     [nroot], ax
        add     ax, 15
        shr     ax, 4
        mov     [rsec], ax
        shl     ax, 9                           ; the root's two copies, from
        add     ax, rootbuf                     ;  rootbuf: memory for that
        mov     [rnew], ax                      ;  much (and no more)
        mov     bx, [rsec]
        shl     bx, 9
        add     bx, ax
        add     bx, 15
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     ax, [rsec]
        add     ax, [rootlba]
        jc      .bad
        mov     [datalba], ax
        mov     ax, [bootsec+13h]               ; the size: 16 bits, or 32
        xor     dx, dx                          ;  (DOS 4)
        or      ax, ax
        jnz     .t16
        mov     ax, [bootsec+20h]
        mov     dx, [bootsec+22h]
.t16:   cmp     byte [unit], 2
        je      .tot
        or      dx, dx                          ; a floppy: at most 84
        jnz     .bad                            ;  cylinders
        push    ax
        mov     ax, [spt]
        mul     word [heads]
        mov     cx, 84
        mul     cx
        pop     cx
        or      dx, dx
        jnz     .t84
        cmp     cx, ax
        ja      .bad
.t84:   mov     ax, cx
        xor     dx, dx
.tot:   sub     ax, [datalba]                   ; -> clusters
        sbb     dx, 0
        jb      .bad
        mov     cx, ax
        or      cx, dx
        jz      .bad
        cmp     dx, [spc]
        jae     .bad
        div     word [spc]
        cmp     ax, 65524
        ja      .bad
        add     ax, 2
        mov     [ncl], ax
        cmp     ax, 4085 + 2                    ; FAT12 or FAT16, by the count
        jb      .f12                            ;  (as DOS), and the FAT holds
        mov     byte [fat16], 1                 ;  them all
        mov     bx, [spf]
        cmp     bx, 256
        jae     .map
        xchg    bl, bh                          ; (256 entries a sector)
        cmp     bx, ax
        jb      .bad
        jmp     short .map
.f12:   mov     bx, [spf]
        cmp     bx, 13
        jae     .map
        shl     bx, 9
        mov     cx, ax
        shr     cx, 1
        add     cx, ax
        inc     cx
        cmp     cx, bx
        ja      .bad
.map:   mov     ax, [ncl]                       ; the map: 80 x 36 cells at
        sub     ax, 2                           ;  most, [cpc] clusters each,
        push    ax                              ;  8 or 16 pixels high
        xor     dx, dx
        add     ax, 80 * 36 - 1
        adc     dx, 0
        mov     cx, 80 * 36
        div     cx
        mov     [cpc], ax
        pop     ax
        xor     dx, dx
        add     ax, [cpc]
        adc     dx, 0
        sub     ax, 1
        sbb     dx, 0
        div     word [cpc]                      ; cells
        add     ax, 79
        xor     dx, dx
        mov     bx, 80
        div     bx
        mov     word [ch_h], 16
        cmp     ax, 18
        jbe     .chl
        mov     word [ch_h], 8
.chl:   cmp     byte [unit], 2                  ; C:: a fixed disk
        je      .fat
        ; does the drive have a change line?  (Without one the BIOS says
        ; "changed" every time, and we could not notice a swap.)
        mov     ah, 16h
        mov     dl, [unit]
        int     13h
        jnc     .cl
        mov     ax, [spt]                       ; a step clears it
        mul     word [heads]
        mov     dx, ax
        mov     cx, 1
        mov     di, dirsec
        call    rd_near
        jc      .x
        xor     bp, bp
        mov     ah, 16h
        mov     dl, [unit]
        int     13h
        jnc     .cl
        mov     word [ronly_why], s_nochg
        mov     byte [ronly], 1
        jmp     short .fat
.cl:    mov     byte [cl_ok], 1
.fat:   cmp     byte [lodestone], 0
        jne     .rd
        mov     word [ronly_why], s_notgos
        mov     byte [ronly], 1
.rd:    mov     bx, [fsec]                      ; the FAT and the map of
        shl     bx, 5                           ; the clusters: memory of
        mov     ah, 48h                         ; their own, as big as this
        int     21h                             ; disk needs
        jc      .mem
        mov     [fseg], ax
        mov     bx, [ncl]
        add     bx, 15
        rcr     bx, 1                           ; (17 bits)
        shr     bx, 3
        mov     ah, 48h
        int     21h
        jc      .mem
        mov     [oseg], ax
        mov     dx, [rsv]                       ; the first FAT
        mov     cx, [fsec]
        mov     es, [fseg]
        xor     di, di
        call    rd_near
        jc      .x
        xor     bp, bp
        cmp     word [nfat], 2                  ; the second FAT, a piece at
        jb      .root                           ; a time: where it differs
        xor     bx, bx                          ; from the first, the first
.f2:    mov     cx, [fsec]                      ; is written over it (an
        sub     cx, bx                          ; earlier power cut)
        jbe     .root
        cmp     cx, [rsec]
        jbe     .f2r
        mov     cx, [rsec]
.f2r:   push    cx
        push    bx
        mov     dx, [rsv]
        add     dx, [spf]
        add     dx, bx
        mov     di, [rnew]
        call    rd_near
        pop     bx
        pop     cx
        jc      .x
        xor     bp, bp
        mov     si, [rnew]
.f2c:   push    cx
        push    si
        mov     ax, bx
        shl     ax, 5
        add     ax, [fseg]
        mov     es, ax
        xor     di, di
        mov     cx, 256
        repe    cmpsw
        pop     si
        pop     cx
        je      .f2n
        mov     ax, bx
        call    fd_mark
.f2n:   add     si, 512
        inc     bx
        loop    .f2c
        push    cs
        pop     es
        jmp     .f2
.mem:   mov     word [ww], s_mem
        stc
        ret
.root:  mov     dx, [rootlba]                   ; the root directory
        mov     cx, [rsec]
        mov     di, rootbuf
        call    rd_near
        jc      .x
        clc
.x:     ret
.bad:   mov     ah, 0FEh                        ; (not a disk we know)
        stc
        ret

; =====================================================================
;  the root directory: deleted entries out (in memory; write_root
;  writes it).  Also drops an exact second copy of an entry, which a
;  power cut during an earlier run can leave, with its long-name parts.
; =====================================================================
pack_root:
        mov     si, rootbuf
        mov     di, [rnew]
        xor     bx, bx                          ; entry index
        mov     byte [lfn_open], 0
.l:     cmp     bx, [nroot]
        jae     .end
        cmp     byte [si], 0
        je      .end
        cmp     byte [si], 0E5h
        jne     .live
        inc     word [removed]                  ; deleted; any long-name
        call    drop_lfn                        ; parts before it were its
        jmp     .n
.live:  cmp     byte [si+11], 0Fh
        jne     .sfn
        cmp     byte [lfn_open], 0              ; a long-name part: keep it
        jne     .cp                             ; with the run it starts or
        mov     [lfn_start], di                 ; continues
        mov     byte [lfn_open], 1
        jmp     .cp
.sfn:   call    is_dup
        je      .dup
        cmp     byte [lfn_open], 0
        je      .cpz
        call    lfn_ok                          ; long-name parts not made
        je      .cpz                            ; for this name: leftovers
        call    drop_lfn
        jmp     .cpz
.dup:   call    drop_lfn                        ; a second copy (left by a
        inc     word [removed]                  ; power cut): drop it and
        jmp     .n                              ; its long-name parts
.cpz:   mov     byte [lfn_open], 0
.cp:    push    si
        mov     cx, 16
        rep     movsw
        pop     si
.n:     add     si, 32
        inc     bx
        jmp     .l
.end:   call    drop_lfn                        ; (parts with no name after)
        mov     [oldused], bx
        ; Past the end marker everything must be zeros.  A power cut while
        ; an earlier run was writing the packed root can leave old entries
        ; there: hidden now, but DOS shows them again as soon as it uses
        ; the end slot for a new file - old copies pointing at clusters
        ; that have since been reused.  They go (zeros written over them).
.st:    cmp     bx, [nroot]
        jae     .z
        push    di
        mov     di, si
        mov     cx, 16
        xor     ax, ax
        repe    scasw
        pop     di
        je      .sn
        inc     word [removed]
        lea     ax, [bx+1]
        mov     [oldused], ax
.sn:    add     si, 32
        inc     bx
        jmp     .st
.z:     mov     cx, [rsec]                      ; the rest: zeros
        shl     cx, 9
        add     cx, [rnew]
        sub     cx, di
        xor     al, al
        rep     stosb
        ret

; forget the open run of long-name parts (if any): DI back to its start
drop_lfn:
        cmp     byte [lfn_open], 0
        je      .x
        mov     ax, di
        sub     ax, [lfn_start]
        shr     ax, 5
        add     [removed], ax
        mov     di, [lfn_start]
        mov     byte [lfn_open], 0
.x:     ret

; do the open run's long-name parts carry the checksum of the short name
; at SI?  ZF if so
lfn_ok: push    bx
        push    cx
        xor     al, al                          ; the checksum
        xor     bx, bx
.c:     ror     al, 1
        add     al, [si+bx]
        inc     bx
        cmp     bx, 11
        jb      .c
        mov     bx, [lfn_start]
.l:     cmp     bx, di
        jae     .yes
        cmp     [bx+13], al
        jne     .no
        add     bx, 32
        jmp     .l
.yes:   cmp     al, al
.no:    pop     cx
        pop     bx
        ret

; SI = short-name entry: is there one already in [rnew] with the same
; name and first cluster?  ZF if so
is_dup: push    bx
        push    cx
        mov     bx, [rnew]
.l:     cmp     bx, di
        jae     .no
        cmp     byte [bx+11], 0Fh
        je      .n
        mov     ax, [bx+26]
        cmp     ax, [si+26]
        jne     .n
        push    si
        push    di
        mov     di, bx
        mov     cx, 11
        repe    cmpsb
        pop     di
        pop     si
        je      .yes
.n:     add     bx, 32
        jmp     .l
.no:    or      sp, sp
.yes:   pop     cx
        pop     bx
        ret

; write the sectors of the packed root that changed, lowest first
write_root:
        cmp     word [removed], 0
        je      .x
        mov     di, msgbuf
        mov     si, s_rootp1
        call    sb_str
        mov     ax, [removed]
        call    sb_u16
        mov     si, s_rootp2
        call    sb_str
        mov     byte [di], 0
        mov     si, msgbuf
        call    status
        mov     ax, [oldused]                   ; sectors up to the old end
        shr     ax, 4
        inc     ax
        cmp     ax, [rsec]
        jbe     .n
        mov     ax, [rsec]
.n:     mov     [rp_n], ax
        mov     word [rp_lo], 0FFFFh            ; the first and last that
        mov     word [rp_hi], 0                 ; changed
        xor     bx, bx
.s:     cmp     bx, [rp_n]
        jae     .w
        mov     si, bx
        shl     si, 9
        lea     di, [rootbuf+si]
        add     si, [rnew]
        mov     cx, 256
        repe    cmpsw
        je      .same
        cmp     word [rp_lo], 0FFFFh
        jne     .hi
        mov     [rp_lo], bx
.hi:    mov     [rp_hi], bx
.same:  inc     bx
        jmp     .s
.w:     mov     dx, [rp_lo]                     ; one write, lowest sector
        cmp     dx, 0FFFFh                      ; first: an entry is in its
        je      .done                           ; new place before its old
        mov     cx, [rp_hi]                     ; place is overwritten
        sub     cx, dx
        inc     cx
        mov     si, dx
        shl     si, 9
        add     si, [rnew]
        add     dx, [rootlba]
        xor     bp, bp
        call    wv_near
        jc      stop2
        mov     byte [logit], 1
.done:  mov     si, [rnew]                      ; it is the root now
        mov     di, rootbuf
        mov     cx, [rsec]
        shl     cx, 8
        rep     movsw
.x:     ret

; =====================================================================
;  walking the directories: every chain checked and its clusters given
;  an owner.  CF if the disk needs CHKDSK (a broken or cross-linked
;  chain, a wrong length) or has more than we can hold.
; =====================================================================
walk:   mov     es, [oseg]
        xor     di, di
        mov     cx, [ncl]
        xor     al, al
        rep     stosb
        push    cs
        pop     es
        xor     bx, bx
.r:     cmp     bx, [nroot]
        jae     .subs
        mov     si, bx
        shl     si, 5
        add     si, [rnew]
        cmp     byte [si], 0
        je      .subs
        mov     ax, bx
        shr     ax, 4
        add     ax, [rootlba]
        mov     [e_lba], ax
        mov     word [e_lba+2], 0
        mov     ax, bx
        and     ax, 15
        shl     ax, 5
        mov     [e_off], ax
        push    bx
        call    take
        pop     bx
        jc      .err
        inc     bx
        jmp     .r
.subs:  xor     bx, bx
.q:     cmp     bx, [ndq]
        jae     .lost
        push    bx
        shl     bx, 1
        mov     ax, [dirq+bx]
        call    walk_dir
        pop     bx
        jc      .err
        inc     bx
        jmp     .q
.lost:  mov     es, [oseg]                      ; used but nobody's: lost
        mov     ax, 2                           ; (or bad)
.l:     cmp     ax, [ncl]
        jae     .ok
        mov     bx, ax
        cmp     byte [es:bx], 0
        jne     .n
        push    ax
        call    fat_get
        mov     dx, ax
        pop     ax
        or      dx, dx
        jz      .n
        mov     byte [es:bx], O_LOST
        cmp     dx, 0FFF7h
        jne     .n
        mov     byte [es:bx], O_BAD
.n:     inc     ax
        jmp     .l
.ok:    push    cs
        pop     es
        clc
        ret
.err:   stc
        ret

; the entries of the subdirectory starting at cluster AX
walk_dir:
.c:     mov     [wd_cl], ax
        xor     cx, cx
.s:     mov     ax, [wd_cl]
        call    clu_lba
        add     dx, cx
        adc     bp, 0
        mov     [e_lba], dx
        mov     [e_lba+2], bp
        push    cx
        mov     cx, 1
        mov     di, dirsec
        call    rd_near
        pop     cx
        jc      .rerr
        xor     bx, bx
.e:     mov     si, bx
        shl     si, 5
        add     si, dirsec
        cmp     byte [si], 0
        je      .end
        mov     ax, bx
        shl     ax, 5
        mov     [e_off], ax
        push    bx
        push    cx
        call    take
        pop     cx
        pop     bx
        jc      .err
        inc     bx
        cmp     bx, 16
        jb      .e
        inc     cx
        cmp     cx, [spc]
        jb      .s
        mov     ax, [wd_cl]
        call    fat_get
        cmp     ax, 0FFF8h
        jb      .c
.end:   clc
        ret
.rerr:  mov     word [ww], s_rderr
.err:   stc
        ret

; one directory entry at SI ([e_lba]/[e_off] say where).  CF: trouble
take:   mov     al, [si]
        cmp     al, 0E5h
        je      .ok
        cmp     al, '.'                         ; "." and ".."
        je      .ok
        mov     al, [si+11]
        cmp     al, 0Fh                         ; long-name part
        je      .ok
        test    al, 08h                         ; volume label
        jnz     .ok
        test    al, 10h
        jnz     .dir
        ; a file: how many clusters its size needs
        mov     ax, [si+28]
        mov     dx, [si+30]
        mov     bx, [cbytes]                    ; (keeps DIV in range)
        dec     bx
        cmp     dx, bx
        jae     .bad
        add     ax, [cbytes]
        adc     dx, 0
        sub     ax, 1
        sbb     dx, 0
        div     word [cbytes]
        mov     [need], ax
        mov     ax, [si+26]
        or      ax, ax
        jnz     .has
        cmp     word [need], 0                  ; empty and no clusters
        je      .ok
        jmp     .bad
.has:   mov     dl, O_FIX                       ; system files stay put
        test    byte [si+11], 04h
        jnz     .mark
        mov     bx, [nfiles]
        cmp     bx, MAXF
        jae     .many
        mov     dl, bl
        inc     dl
.mark:  call    chain_mark
        jc      .bad
        cmp     cx, [need]
        jne     .bad
        cmp     dl, O_FIX
        je      .ok
        mov     di, [nfiles]                    ; the record
        shl     di, 5
        add     di, files
        push    si
        mov     cx, 11
        rep     movsb
        pop     si
        sub     di, 11
        mov     al, [si+11]
        mov     [di+F_ATTR], al
        mov     ax, [e_lba]
        mov     [di+F_DLBA], ax
        mov     ax, [e_lba+2]
        mov     [di+F_DLBAH], ax
        mov     ax, [e_off]
        mov     [di+F_DOFF], ax
        mov     ax, [si+26]
        mov     [di+F_START], ax
        mov     ax, [need]
        mov     [di+F_NCL], ax
        mov     al, [cm_frag]
        mov     [di+F_FLAGS], al
        add     byte [nfrag], al
        inc     word [nfiles]
.ok:    clc
        ret
.dir:   mov     ax, [si+26]
        mov     dl, O_DIR
        call    chain_mark
        jc      .bad
        jcxz    .bad
        mov     bx, [ndq]
        cmp     bx, MAXDQ
        jae     .many
        shl     bx, 1
        mov     ax, [si+26]
        mov     [dirq+bx], ax
        inc     word [ndq]
        clc
        ret
.many:  mov     word [ww], s_many
.bad:   stc
        ret

; follow the chain from AX, giving its clusters owner DL -> CX clusters,
; [cm_frag] = 1 if not in one piece.  CF if broken, cross-linked, looped
chain_mark:
        push    es
        mov     es, [oseg]
        xor     cx, cx
        mov     byte [cm_frag], 0
.l:     cmp     ax, 2
        jb      .bad
        cmp     ax, [ncl]
        jae     .bad
        mov     bx, ax
        cmp     byte [es:bx], 0
        jne     .bad
        mov     [es:bx], dl
        inc     cx
        call    fat_get
        cmp     ax, 0FFF8h
        jae     .end
        cmp     ax, 0FFF0h
        jae     .bad
        inc     bx
        cmp     ax, bx
        je      .l
        mov     byte [cm_frag], 1
        jmp     .l
.end:   pop     es
        clc
        ret
.bad:   pop     es
        stc
        ret

; =====================================================================
;  /T: every free sector is written with a pattern and read back, a run
;  of free sectors in a track at a time; a run that fails is tried sector
;  by sector, and the clusters of the sectors that fail are marked bad
;  (FF7h).  Only free clusters are written, and the FAT only gains bad
;  marks, so nothing that holds data is touched.
; =====================================================================
surface:
        push    es                              ; the pattern in buffer A
        mov     es, [bseg]
        mov     di, BUFA
        mov     cx, 18 * 256
        mov     ax, 0B66Dh
        rep     stosw
        pop     es
        mov     ax, [ncl]
        sub     ax, 2
        mul     word [spc]
        add     ax, [datalba]
        adc     dx, 0
        mov     [dend], ax                      ; end of the data area
        mov     [dend+2], dx
        mov     ax, [datalba]
        mov     [sl], ax
.trk:   mov     dx, [sl]                        ; a track from [sl]: its
        mov     bp, [sl+2]                      ;  first [tn] sectors (to
        mov     cx, [dend]                      ;  its end, or the data's)
        mov     ax, [dend+2]
        sub     cx, dx
        sbb     ax, bp
        jb      .done
        jnz     .far
        or      cx, cx
        jnz     .tn
        jmp     .done
.far:   mov     cx, 0FFFFh
.tn:    call    disturbed                       ; (only free space written)
        jc      stop1
        call    trk_n
        mov     [tn], ax
        mov     word [tbad], 0
        mov     word [tfree], 0
        xor     si, si                          ; (sectors into it)
.s:     cmp     si, [tn]
        jae     .tdone
        call    .at
        call    sec_free
        je      .run
        inc     si
        jmp     .s
.run:   mov     di, si                          ; a run of free sectors
.r:     inc     si
        cmp     si, [tn]
        jae     .rr
        call    .at
        call    sec_free
        je      .r
.rr:    mov     cx, si
        sub     cx, di                          ; CX of them, from DI
        add     [tfree], cx
        push    si
        mov     si, di
        call    .at
        mov     bl, P_READ
        call    draw_lbas
        mov     al, cl
        call    wv_buf
        jnc     .ok
        cmp     ah, 3
        je      stop2
        cmp     ah, 6
        je      stop2
        call    note_err
.one:   mov     al, 1                           ; sector by sector
        call    wv_buf
        jnc     .on
        cmp     ah, 3
        je      stop2
        cmp     ah, 6
        je      stop2
        call    mark_bad                        ; (BP:DX = its sector)
        inc     word [tbad]
        jmp     short .on1
.on:    add     word [ntsec], 1
        adc     word [ntsec+2], 0
.on1:   add     dx, 1
        adc     bp, 0
        loop    .one
        pop     si
        jmp     .s
.ok:    add     [ntsec], cx                     ; tested; back to free
        adc     word [ntsec+2], 0
        mov     bl, P_FREE
        call    draw_lbas
        pop     si
        jmp     .s
.tdone: cmp     word [tbad], 0
        je      .tok
        call    fat_flush
        jc      stop2
        mov     ax, [tbad]                      ; a whole first few tracks
        cmp     ax, [tfree]                     ; bad: more likely the drive
        jb      .tok1                           ; than the disk - stop
        mov     ax, [ntsec]
        or      ax, [ntsec+2]
        jnz     .tok1
        inc     byte [allbad]
        cmp     byte [allbad], 3
        jb      .next
        mov     ah, 0FDh
        jmp     stop2
.tok:   cmp     word [tfree], 0
        je      .next
.tok1:  mov     byte [allbad], 0
.next:  mov     ax, [tn]
        add     [sl], ax
        adc     word [sl+2], 0
        jmp     .trk
.done:  jmp     draw_map                        ; (cells of several clusters
                                                ;  were shown as free)
.at:    mov     dx, [sl]                        ; BP:DX = [sl] + SI
        mov     bp, [sl+2]
        add     dx, si
        adc     bp, 0
        ret

; Eight writes failed in a row.  Try a free cluster near the start of
; the disk (where it has surely been written before), then one further
; on.  If either takes a write, the drive is fine and only a stretch of
; the disk is bad: carry on, from now on moving files out of the way
; only just past themselves.  CF if neither: the drive.
probe:  push    bx
        push    cx
        push    dx
        mov     ax, 2
        mov     bx, 2
.p:     push    bx
        mov     cx, 1
        call    find_from
        pop     bx
        jc      .no
        mov     [pr_cl], ax
        call    clu_lba
        mov     al, 1
        call    wv_buf
        jnc     .yes
        cmp     ah, 6
        je      .no
        call    mark_bad                        ; (BP:DX = its sector)
        mov     ax, [pr_cl]
        add     ax, 200
        dec     bx
        jnz     .p
.no:    stc
        jmp     short .x
.yes:   mov     word [failrun], 0
        mov     byte [nearmode], 1
        clc
.x:     pop     dx
        pop     cx
        pop     bx
        ret

; is sector BP:DX in a free cluster?  ZF if so
sec_free:
        push    ax
        push    bx
        push    dx
        call    sec_clu
        call    own_z
        pop     dx
        pop     bx
        pop     ax
        ret
; sector BP:DX -> its cluster BX (AX, DX lost)
sec_clu:
        mov     ax, dx
        mov     dx, bp
        sub     ax, [datalba]
        sbb     dx, 0
        div     word [spc]
        add     ax, 2
        mov     bx, ax
        ret

; sector BP:DX failed: its cluster is marked bad (in memory; fat_flush
; writes it), and (a floppy) counted for its cylinder
mark_bad:
        pusha
        cmp     byte [unit], 2
        je      .c
        mov     cx, dx                          ; (its sector)
        mov     ax, [spt]
        mul     word [heads]
        xchg    ax, cx
        xor     dx, dx
        div     cx
        cmp     ax, 84
        jae     .c0
        mov     bx, ax
        cmp     byte [badcyl+bx], 255
        je      .c0
        inc     byte [badcyl+bx]
.c0:    popa
        pusha
.c:     call    sec_clu
        call    own
        cmp     al, O_BAD
        je      .x
        mov     al, O_BAD
        call    own_set
        mov     ax, bx
        mov     dx, 0FFF7h
        call    fat_set
        call    draw_cell
        inc     word [nbadm]
        inc     word [mv_mark]
        mov     byte [logit], 1
.x:     popa
        ret

; =====================================================================
;  tidying.  1: join up every fragmented file (into the lowest gap it
;  fits).  2: walk the gaps from the start of the disk; fill each with the
;  biggest file after it that fits.  When none fits, move the file just
;  after the gap out of the way to the end (once per file): the gap grows,
;  and that file often comes straight back into it, slid forward.
;  Every move either joins a file or moves one nearer the start, apart
;  from the one-off moves out of the way, so this always ends.
; =====================================================================
tidy:   xor     bx, bx
.f:     cmp     bx, [nfiles]
        jae     .gaps
        call    rec_of
        test    byte [di+F_FLAGS], FL_FRAG
        jz      .fn
        mov     cx, [di+F_NCL]
        call    find_low
        jc      .fn
        mov     si, di
        mov     word [mv_msg], s_join
        push    bx
        call    move
        pop     bx
        jnc     .fn
        call    rec_of                          ; failed: again, somewhere
        test    byte [di+F_FLAGS], FL_STUCK     ; else (unless it can't be
        jz      .f                              ; read)
.fn:    inc     bx
        jmp     .f
.gaps:  mov     word [gp], 2
.g:     mov     ax, [gp]                        ; the next free cluster
.g1:    cmp     ax, [ncl]
        jae     .x
        mov     bx, ax
        call    own_z
        je      .g2
        inc     ax
        jmp     .g1
.g2:    mov     [gs_], ax
.g3:    inc     ax                              ; the end of the gap
        cmp     ax, [ncl]
        jae     .x                              ; (free to the end: done)
        mov     bx, ax
        call    own_z
        je      .g3
        mov     [ge], ax
        sub     ax, [gs_]
        mov     [glen], ax
        ; the biggest file that fits, starting after the gap
        mov     word [best], 0FFFFh
        mov     word [bestn], 0
        xor     bx, bx
.c:     cmp     bx, [nfiles]
        jae     .cx
        call    rec_of
        test    byte [di+F_FLAGS], FL_FRAG | FL_STUCK
        jnz     .cn
        mov     ax, [di+F_START]
        cmp     ax, [ge]
        jb      .cn
        mov     ax, [di+F_NCL]
        cmp     ax, [glen]
        ja      .cn
        cmp     ax, [bestn]
        jb      .cn
        jne     .cb
        mov     dx, [di+F_START]                ; same size: the later one
        mov     si, [best]
        shl     si, 5
        cmp     dx, [files+si+F_START]
        jbe     .cn
.cb:    mov     [bestn], ax
        mov     [best], bx
.cn:    inc     bx
        jmp     .c
.cx:    cmp     word [best], 0FFFFh
        je      .none
        mov     bx, [best]
        call    rec_of
        mov     si, di
        mov     ax, [gs_]
        mov     word [mv_msg], s_fwd
        call    move
        jmp     .g                              ; ([gp] stays: the same gap)
.none:  ; nothing fits: the file right after the gap, out of the way
        mov     bx, [ge]
        call    own
        or      al, al
        jz      .skip
        cmp     al, MAXF
        ja      .skip                           ; (directory, system, bad)
        dec     al
        xor     ah, ah
        mov     bx, ax
        call    rec_of
        test    byte [di+F_FLAGS], FL_OUT | FL_FRAG | FL_STUCK
        jnz     .skip
        mov     ax, [di+F_START]
        cmp     ax, [ge]
        jne     .skip
        mov     cx, [di+F_NCL]
        cmp     byte [nearmode], 0
        jne     .near
        call    find_high                       ; as far on as possible
        jc      .skip
        cmp     ax, [ge]                        ; (only further on)
        jbe     .skip
        jmp     short .go
.near:  mov     ax, [di+F_START]                ; (the far end proved bad:
        add     ax, cx                          ;  the first room after it)
        call    find_from
        jc      .skip
.go:
        mov     si, di
        mov     word [mv_msg], s_out
        push    di
        call    move
        pop     di
        jc      .g
        or      byte [di+F_FLAGS], FL_OUT
        jmp     .g
.skip:  mov     ax, [ge]                        ; this gap stays
        mov     [gp], ax
        jmp     .g
.x:     ret

rec_of: mov     di, bx                          ; file BX -> DI
        shl     di, 5
        add     di, files
        ret

; CX clusters free in a row, the lowest such -> AX.  CF if none
find_low:
        mov     ax, 2
; (the same, from cluster AX on)
find_from:
        push    bx
        xor     dx, dx
.l:     cmp     ax, [ncl]
        jae     .none
        mov     bx, ax
        call    own_z
        jne     .br
        inc     dx
        cmp     dx, cx
        jae     .got
        inc     ax
        jmp     .l
.br:    xor     dx, dx
        inc     ax
        jmp     .l
.got:   sub     ax, cx
        inc     ax
        pop     bx
        clc
        ret
.none:  pop     bx
        stc
        ret

; the same, as far towards the end of the disk as possible
find_high:
        push    bx
        mov     ax, [ncl]
        dec     ax
        xor     dx, dx
.l:     cmp     ax, 2
        jb      .none
        mov     bx, ax
        call    own_z
        jne     .br
        inc     dx
        cmp     dx, cx
        jae     .got
        dec     ax
        jmp     .l
.br:    xor     dx, dx
        dec     ax
        jmp     .l
.got:   pop     bx
        clc
        ret
.none:  pop     bx
        stc
        ret

; =====================================================================
;  moving file SI (record) whole to the free clusters from AX
; =====================================================================
move:   mov     [mv_rec], si
        mov     [mv_d], ax
        mov     di, msgbuf                      ; "Moving LODE.SYS forward"
        mov     si, s_moving
        call    sb_str
        mov     si, [mv_rec]
        call    sb_name
        mov     si, [mv_msg]
        call    sb_str
        mov     byte [di], 0
        mov     si, msgbuf
        call    status
        mov     si, [mv_rec]
        ; 1. copy, a track at most at a time; read back and compare
        mov     ax, [si+F_START]
        mov     [mv_s], ax
        mov     ax, [si+F_NCL]
        mov     [mv_left], ax
        mov     ax, [mv_d]
        call    clu_lba
        mov     [mv_dl], dx
        mov     [mv_dl+2], bp
.run:   mov     ax, [mv_s]                      ; a run of touching clusters
        mov     [mv_rs], ax
        mov     cx, 1
.rc:    cmp     cx, [mv_left]
        jae     .rce
        cmp     cx, [rcap]                      ; (its sectors in 16 bits)
        jae     .rce
        mov     ax, [mv_rs]
        add     ax, cx
        dec     ax
        push    cx
        call    fat_get
        pop     cx
        mov     dx, [mv_rs]
        add     dx, cx
        cmp     ax, dx
        jne     .rce
        inc     cx
        jmp     .rc
.rce:   mov     [mv_rl], cx
        mov     ax, cx
        mul     word [spc]
        mov     [mv_sl], ax
        mov     ax, [mv_rs]
        call    clu_lba
        mov     [mv_sa], dx
        mov     [mv_sa+2], bp
.ch:    cmp     word [mv_sl], 0
        je      .nrun
        call    disturbed                       ; nothing changed yet
        jc      stop1
        mov     cx, [mv_sl]
        mov     dx, [mv_sa]
        mov     bp, [mv_sa+2]
        call    trk_n
        mov     cx, ax
        mov     dx, [mv_dl]
        mov     bp, [mv_dl+2]
        call    trk_n
        mov     [mv_n], ax
        mov     dx, [mv_sa]
        mov     bp, [mv_sa+2]
        mov     cx, ax
        mov     bl, P_READ
        call    draw_lbas
        mov     es, [bseg]
        mov     bx, BUFA
        mov     al, [mv_n]
        mov     ah, 2
        call    bios
        push    cs
        pop     es
        jc      .rdbad
.wrc:   mov     dx, [mv_dl]
        mov     bp, [mv_dl+2]
        mov     al, [mv_n]
        call    wv_buf
        jc      .wrbad
        mov     word [failrun], 0
        mov     cx, [mv_n]
        mov     bl, P_WRITE
        call    draw_lbas
        mov     ax, [mv_n]
        add     [mv_sa], ax
        adc     word [mv_sa+2], 0
        add     [mv_dl], ax
        adc     word [mv_dl+2], 0
        sub     [mv_sl], ax
        jmp     .ch

; A read failed: each sector again, on its own, a few times over (a weak
; sector often reads in the end - and then the file is rescued onto good
; ground).  Only if one really can't be read does the file stay where
; it is (left out from now on).  Nothing has been written for this move.
.rdbad: cmp     ah, 6
        je      stop2
        call    note_err
        xor     cx, cx
.rs:    cmp     cx, [mv_n]
        jae     .wrc                            ; all read: carry on
        mov     byte [rtry], 4
.rr:    mov     es, [bseg]
        mov     bx, cx
        shl     bx, 9
        add     bx, BUFA
        mov     dx, [mv_sa]
        mov     bp, [mv_sa+2]
        add     dx, cx
        adc     bp, 0
        mov     ax, 0201h
        push    cx
        call    bios
        pop     cx
        push    cs
        pop     es
        jnc     .rn
        cmp     ah, 6
        je      stop2
        dec     byte [rtry]
        jnz     .rr
        mov     si, [mv_rec]
        or      byte [si+F_FLAGS], FL_STUCK
        jmp     .abandon
.rn:    inc     cx
        jmp     .rs
; The free space it was copying into has a bad spot: find the sectors,
; one at a time, and mark their clusters bad (FF7h, as FORMAT/CHKDSK do),
; then choose again.  No limit - old disks wear - except when writes fail
; eight times running with not one working in between: that is the
; drive, not the disk.
.wrbad: cmp     ah, 3
        je      stop2
        cmp     ah, 6
        je      stop2
        mov     [mv_err], ax
        call    note_err
        inc     word [failrun]
        cmp     word [failrun], 8
        jb      .wb1
        call    probe                           ; eight in a row: is it the
        jnc     .wb1                            ; drive, or a bad stretch?
        mov     ah, 0FDh
        jmp     stop2
.wb1:   mov     word [mv_mark], 0
        xor     cx, cx
.ts:    cmp     cx, [mv_n]
        jae     .tsd
        push    cx
        mov     dx, [mv_dl]
        mov     bp, [mv_dl+2]
        add     dx, cx
        adc     bp, 0
        mov     al, 1
        call    wv_buf
        jnc     .tn
        cmp     ah, 3
        je      stop2
        cmp     ah, 6
        je      stop2
        call    mark_bad                        ; (BP:DX = its sector)
.tn:    pop     cx
        inc     cx
        jmp     .ts
.tsd:   cmp     word [mv_mark], 0
        jne     .mk
        mov     dx, [mv_dl]                     ; every sector went through on
        mov     bp, [mv_dl+2]                   ; its own: the second time at
        cmp     dx, [weak_lba]                  ; this place, it is weak -
        jne     .wk                             ; mark them all
        cmp     bp, [weak_lba+2]
.wk:    mov     [weak_lba], dx
        mov     [weak_lba+2], bp
        jne     .abandon
        mov     cx, [mv_n]
.ma:    call    mark_bad
        add     dx, 1
        adc     bp, 0
        loop    .ma
.mk:    call    fat_flush
        jc      stop2
.abandon:
        call    draw_map
        stc
        ret

.nrun:  mov     ax, [mv_rl]
        sub     [mv_left], ax
        jz      .copied
        mov     ax, [mv_rs]
        add     ax, [mv_rl]
        dec     ax
        call    fat_get
        mov     [mv_s], ax
        jmp     .run
        ; 2. its directory entry: still the one we know?  (Before any
        ;    write for this move: if not, stop with nothing written.)
.copied:
        mov     si, [mv_rec]
        mov     dx, [si+F_DLBA]
        mov     bp, [si+F_DLBAH]
        mov     cx, 1
        mov     di, dirsec
        call    rd_near
        jc      stop2
        mov     si, [mv_rec]
        mov     bx, [si+F_DOFF]
        mov     ax, [si+F_START]
        cmp     [dirsec+bx+26], ax
        jne     .lost
        lea     di, [dirsec+bx]
        mov     cx, 11
        repe    cmpsb
        jne     .lost
        ; 3. the FAT gets the new chain; the old one is untouched
        mov     si, [mv_rec]
        mov     ax, [mv_d]
        mov     cx, [si+F_NCL]
.nc:    mov     dx, ax
        inc     dx
        cmp     cx, 1
        jne     .nc1
        mov     dx, 0FFFFh
.nc1:   call    fat_set
        inc     ax
        loop    .nc
        call    fat_flush
        jc      stop2
        ; 4. the switch: the directory entry points at the new chain
        mov     si, [mv_rec]
        mov     bx, [si+F_DOFF]
        mov     ax, [mv_d]
        mov     [dirsec+bx+26], ax
        mov     dx, [si+F_DLBA]
        mov     bp, [si+F_DLBAH]
        mov     cx, 1
        mov     si, dirsec
        call    wv_near
        jc      stop2
        ; 5. the old chain is freed
        mov     si, [mv_rec]
        mov     ax, [si+F_START]
.fr:    push    ax
        call    fat_get
        mov     cx, ax
        pop     ax
        xor     dx, dx
        call    fat_set
        mov     bx, ax
        push    ax
        xor     al, al
        call    own_set
        pop     ax
        push    cx
        call    draw_cell
        pop     ax
        cmp     ax, 0FFF8h
        jb      .fr
        call    fat_flush
        jc      stop2
        ; ours now
        mov     si, [mv_rec]
        mov     ax, [mv_d]
        mov     [si+F_START], ax
        and     byte [si+F_FLAGS], ~FL_FRAG
        mov     dx, si
        sub     dx, files
        shr     dx, 5
        inc     dx                              ; owner code
        mov     cx, [si+F_NCL]
.ow:    mov     bx, ax
        push    ax
        mov     al, dl
        call    own_set
        pop     ax
        push    ax
        push    cx
        push    dx
        call    draw_cell
        pop     dx
        pop     cx
        pop     ax
        inc     ax
        loop    .ow
        mov     byte [logit], 1
        clc
        ret
.lost:  mov     ah, 0FEh                        ; the entry isn't what we
        jmp     stop2                           ; read: stop

; =====================================================================
;  the FAT in memory
; =====================================================================
; cluster AX -> ES:BX = its entry in [fseg].  FAT12: ZF if it is in the
; low 12 bits of the word.  Keeps AX
fat_at: mov     bx, ax
        cmp     byte [fat16], 0
        je      .12
        shr     bx, 3                           ; FAT16: AX * 2 bytes on
        add     bx, [fseg]
        mov     es, bx
        mov     bx, ax
        and     bx, 7
        shl     bx, 1
        ret
.12:    mov     es, [fseg]                      ; FAT12: AX * 1.5
        shr     bx, 1
        add     bx, ax
        test    al, 1
        ret

; cluster AX -> AX, as FAT16's: FAT12's FF0h-FFFh come back as FFF0h-FFFFh
fat_get:
        push    bx
        push    es
        push    ax
        call    fat_at
        pop     ax
        cmp     byte [fat16], 0
        jne     .16
        test    al, 1
        mov     ax, [es:bx]
        jz      .e
        shr     ax, 4
.e:     and     ah, 0Fh
        cmp     ax, 0FF0h
        jb      .x
        or      ah, 0F0h
        jmp     short .x
.16:    mov     ax, [es:bx]
.x:     pop     es
        pop     bx
        ret

; cluster AX := DX (FAT12: its low 12 bits), its FAT sector marked to write
fat_set:
        pusha
        push    es
        call    fat_at
        cmp     byte [fat16], 0
        jne     .16
        and     dx, 0FFFh
        test    al, 1
        jz      .e
        shl     dx, 4
        and     word [es:bx], 000Fh
        jmp     short .s
.e:     and     word [es:bx], 0F000h
.s:     or      [es:bx], dx
        mov     ax, bx                          ; its sector(s)
        shr     ax, 9
        call    fd_mark
        lea     ax, [bx+1]
        shr     ax, 9
        jmp     short .m
.16:    mov     [es:bx], dx
        mov     al, ah                          ; (256 entries a sector)
        xor     ah, ah
.m:     call    fd_mark
        pop     es
        popa
        ret

; FAT sector AX changed (AX lost)
fd_mark:
        push    bx
        push    cx
        mov     bx, ax
        mov     cl, al
        and     cl, 7
        shr     bx, 3
        mov     al, 1
        shl     al, cl
        or      [fdirty+bx], al
        mov     byte [fdany], 1
        pop     cx
        pop     bx
        ret

; the changed FAT sectors to every copy (runs; read back).  CF: AH = error
fat_flush:
        cmp     byte [fdany], 0
        je      .ok
        mov     word [fk], 0
.copy:  xor     bx, bx
.s:     cmp     bx, [fsec]
        jae     .next
        call    .dirty
        jz      .sk
        mov     [fs_], bx
.e:     inc     bx
        cmp     bx, [fsec]
        jae     .run
        call    .dirty
        jnz     .e
.run:   push    bx
        mov     cx, bx
        sub     cx, [fs_]
        mov     ax, [fk]
        mul     word [spf]
        add     ax, [rsv]
        add     ax, [fs_]
        mov     dx, ax
        xor     bp, bp
        mov     ax, [fs_]                       ; from [fseg] + its offset
        shl     ax, 5
        add     ax, [fseg]
        mov     es, ax
        xor     si, si
        call    wv_near
        pop     bx
        jc      .x
        jmp     .s
.sk:    inc     bx
        jmp     .s
.next:  inc     word [fk]
        mov     ax, [fk]
        cmp     ax, [nfat]
        jb      .copy
        mov     di, fdirty                      ; all written
        mov     cx, 16
        xor     ax, ax
        rep     stosw
        mov     [fdany], al
.ok:    clc
.x:     ret
.dirty: push    ax                              ; sector BX changed?  NZ
        push    bx
        push    cx
        mov     cl, bl
        and     cl, 7
        shr     bx, 3
        mov     al, 1
        shl     al, cl
        test    [fdirty+bx], al
        pop     cx
        pop     bx
        pop     ax
        ret

; the owner of cluster BX -> AL; := AL; ZF if it has none (free).  Keep
; all else
own:    push    ds
        mov     ds, [oseg]
        mov     al, [bx]
        pop     ds
        ret
own_set:
        push    ds
        mov     ds, [oseg]
        mov     [bx], al
        pop     ds
        ret
own_z:  push    ds
        mov     ds, [oseg]
        cmp     byte [bx], 0
        pop     ds
        ret

; =====================================================================
;  disk access.  Everything goes through the DMA-safe buffers in [bseg].
; =====================================================================
; cluster AX -> its first sector BP:DX (AX lost)
clu_lba:
        sub     ax, 2
        mul     word [spc]
        add     ax, [datalba]
        adc     dx, 0
        mov     bp, dx
        mov     dx, ax
        ret

; AX = min(CX, sectors left in BP:DX's track)
trk_n:  push    dx
        push    dx
        mov     ax, bp
        xor     dx, dx
        div     word [spt]
        pop     ax
        div     word [spt]
        mov     ax, [spt]
        sub     ax, dx
        cmp     ax, cx
        jbe     .x
        mov     ax, cx
.x:     pop     dx
        ret

; AH = 2/3, AL = count, BP:DX = sector, ES:BX = buffer.  A floppy: the
; change line first (a changed disk: AH = 6, nothing done), 3 tries.  C::
; the kernel's INT 25h/26h (it tries twice).  CF: AH = BIOS error
bios:   push    cx
        push    dx
        mov     [b_op], ax
        mov     [b_lba], dx
        mov     [b_lba+2], bp
        cmp     byte [unit], 2
        jne     .fl
        mov     [pk_lba], dx                    ; the packet: sector, count,
        mov     [pk_lba+2], bp                  ;  buffer
        xor     ah, ah
        mov     [pk_n], ax
        mov     [pk_buf], bx
        mov     [pk_buf+2], es
        mov     al, 2
        mov     cx, 0FFFFh
        mov     bx, pk_lba
        cmp     byte [b_op+1], 3
        je      .w
        int     25h
        jmp     short .hx
.w:     int     26h
.hx:    pop     cx                              ; (the flags left behind)
        mov     bx, [pk_buf]
        jnc     .x
        jmp     short .e
.fl:    mov     byte [b_try], 3
.t:     cmp     byte [cl_ok], 0
        je      .go
        mov     ah, 16h
        mov     dl, [unit]
        int     13h
        mov     ah, 6
        jc      .e
.go:    mov     ax, [b_lba]
        xor     dx, dx
        div     word [spt]
        mov     cl, dl
        inc     cl                              ; sector
        xor     dx, dx
        div     word [heads]
        mov     dh, dl                          ; head
        mov     ch, al                          ; cylinder
        mov     dl, [unit]
        mov     ax, [b_op]
        int     13h
        jnc     .x
        cmp     ah, 3                           ; write-protected
        je      .e
        cmp     ah, 6                           ; changed
        je      .e
        dec     byte [b_try]
        jz      .e
        cmp     byte [cl_ok], 0                 ; changed?  (before the
        je      .rs                             ;  reset, which may step
        mov     ah, 16h                         ;  the head and clear it)
        mov     dl, [unit]
        int     13h
        mov     ah, 6
        jc      .e
.rs:    xor     ax, ax
        mov     dl, [unit]
        int     13h
        jmp     .go
.e:     mov     [er_code], ah
        mov     al, [b_op+1]
        mov     [er_op], al
        push    ax
        mov     ax, [b_lba]
        mov     [er_lba], ax
        mov     ax, [b_lba+2]
        mov     [er_lba+2], ax
        pop     ax
        stc
.x:     pop     dx
        pop     cx
        ret

; read CX sectors from BP:DX to ES:DI (split at tracks).  CF: AH = error.
; ES = CS after
rd_near:
        mov     [xseg], es
.l:     jcxz    .ok
        call    trk_n
        push    cx
        push    dx
        push    ax
        mov     es, [bseg]
        mov     bx, BUFA
        mov     ah, 2
        call    bios
        pop     cx                              ; (n)
        jc      .err
        push    ds
        push    di
        mov     es, [xseg]
        mov     ds, [bseg]
        mov     si, BUFA
        shl     cx, 8
        rep     movsw
        pop     di
        pop     ds
        pop     dx
        pop     cx
        call    trk_n                           ; n again
        add     dx, ax
        adc     bp, 0
        sub     cx, ax
        shl     ax, 5
        add     [xseg], ax
        jmp     .l
.ok:    push    cs
        pop     es
        clc
        ret
.err:   pop     dx
        pop     cx
        push    cs
        pop     es
        stc
        ret

; write CX sectors from ES:SI to BP:DX (split at tracks), each read back
; and compared.  CF: AH = error (0FFh: read back different).  ES = CS after
wv_near:
        mov     [xseg], es
.l:     jcxz    .ok
        call    trk_n
        push    cx
        push    dx
        push    ax
        mov     cx, ax
        shl     cx, 8
        mov     es, [bseg]                      ; into buffer A
        mov     di, BUFA
        push    ds
        push    si
        mov     ds, [xseg]
        rep     movsw
        pop     si
        pop     ds
        pop     ax
        mov     [wv_cnt], ax
        call    wv_buf                          ; (AH: the error, if any)
        pop     dx
        pop     cx
        jc      .err
        mov     ax, [wv_cnt]
        add     dx, ax
        adc     bp, 0
        sub     cx, ax
        shl     ax, 5
        add     [xseg], ax
        jmp     .l
.ok:    push    cs
        pop     es
        clc
        ret
.err:   push    cs
        pop     es
        stc
        ret

; write AL sectors from buffer A to BP:DX, read them back into buffer B
; and compare.  CF: AH = error
wv_buf: push    cx
        push    si
        push    di
        mov     [wv_n], al
        mov     es, [bseg]
        mov     bx, BUFA
        mov     ah, 3
        call    bios
        jc      .x
        mov     bx, BUFB
        mov     al, [wv_n]
        mov     ah, 2
        call    bios
        jc      .x
        push    ds
        mov     cl, [wv_n]
        xor     ch, ch
        shl     cx, 8
        mov     ds, [bseg]
        mov     si, BUFA
        mov     di, BUFB
        repe    cmpsw
        pop     ds
        je      .x
        mov     byte [er_op], 0FFh              ; read back different
        mov     [er_lba], dx
        mov     [er_lba+2], bp
        mov     ah, 0FFh
        stc
.x:     push    cs
        pop     es
        pop     di
        pop     si
        pop     cx
        ret

; =====================================================================
;  the screen
; =====================================================================
draw_frame:                                     ; legend and its rule
        mov     dx, LEG_Y - 3
        mov     bx, 1
        mov     cx, 78
        call    hline_dots
        mov     si, legend
        mov     bx, LEG_X
.l:     lodsb
        cmp     al, 0FFh
        je      .x
        push    bx
        mov     dx, LEG_Y + 4
        mov     cx, 8
        mov     di, bx
        mov     bl, al
        call    draw_pat_at
        pop     bx
        add     bx, 2
        mov     dx, LEG_Y
        xor     ah, ah
        call    strlen
        push    cx
        call    puts
        pop     cx
        add     bx, cx
        add     bx, 3
        jmp     .l
.x:     ret

draw_map:
        mov     ax, 2
.l:     cmp     ax, [ncl]
        jae     .x
        call    draw_cell
        add     ax, [cpc]
        jmp     .l
.x:     ret

; the cell of cluster AX: the most important state among its clusters (a
; cell is [cpc] clusters).  Keeps all but BX
draw_cell:
        push    ax
        push    cx
        push    dx
        push    si
        push    ds
        sub     ax, 2
        xor     dx, dx
        div     word [cpc]
        push    ax                              ; the cell
        mul     word [cpc]
        add     ax, 2
        mov     si, ax                          ; its first cluster
        mov     cx, [cpc]
        xor     dx, dx                          ; DL: the rank so far, DH:
.c:     cmp     si, [ncl]                       ;  its pattern
        jae     .d
        mov     ds, [oseg]
        mov     bl, [si]
        push    cs
        pop     ds
        mov     bh, P_FREE
        or      bl, bl
        jz      .p
        mov     bh, P_LOST
        cmp     bl, O_LOST
        je      .p
        mov     bh, P_BAD
        cmp     bl, O_BAD
        je      .p
        mov     bh, P_DIR
        cmp     bl, O_DIR
        jae     .p
        dec     bl                              ; a file
        xor     bh, bh
        shl     bx, 5
        test    byte [files+bx+F_FLAGS], FL_FRAG
        mov     bh, P_FILE
        jz      .p
        mov     bh, P_FRAG
.p:     mov     bl, bh
        xor     bh, bh
        mov     al, [rank+bx]
        cmp     al, dl
        jb      .n
        mov     dl, al
        mov     dh, bl
.n:     inc     si
        loop    .c
.d:     pop     ax
        mov     bl, dh
        call    draw_pat_c
        pop     ds
        pop     si
        pop     dx
        pop     cx
        pop     ax
        ret
rank:   db 0, 3, 5, 2, 4, 1                     ; free, file, in pieces, dir,
                                                ;  bad, lost

; cluster AX in pattern BL (its cell)
draw_pat:
        push    ax
        push    dx
        sub     ax, 2
        xor     dx, dx
        div     word [cpc]
        call    draw_pat_c
        pop     dx
        pop     ax
        ret
; cell AX in pattern BL
draw_pat_c:
        push    ax
        push    cx
        push    dx
        push    di
        xor     dx, dx
        mov     cx, 80
        div     cx                              ; AX = row, DX = column
        mov     di, dx
        mul     word [ch_h]
        add     ax, MAP_Y
        mov     dx, ax
        mov     cx, [ch_h]
        call    draw_pat_at
        pop     di
        pop     dx
        pop     cx
        pop     ax
        ret
; pattern BL at byte column DI, from y DX, CX rows (8 or 16)
draw_pat_at:
        pusha
        push    es
        push    VSEG
        pop     es
        xor     bh, bh
        shl     bx, 3
        add     bx, pats
        xor     si, si                          ; row in the cell
.r:     mov     ax, si
        cmp     cx, 16
        jne     .h
        shr     ax, 1
.h:     push    bx
        add     bx, ax
        mov     al, [bx]
        pop     bx
        push    si
        mov     si, dx
        add     si, si
        mov     si, [rowtab+si]
        add     si, di
        mov     [es:si], al
        pop     si
        inc     dx
        inc     si
        cmp     si, cx
        jb      .r
        pop     es
        popa
        ret

; sectors BP:DX.. (CX of them): their clusters in pattern BL
draw_lbas:
        pusha
        mov     ax, dx
        mov     dx, bp
        sub     ax, [datalba]
        sbb     dx, 0
        push    ax
        push    dx
        div     word [spc]
        mov     si, ax                          ; first cluster - 2
        pop     dx
        pop     ax
        add     ax, cx
        adc     dx, 0
        sub     ax, 1
        sbb     dx, 0
        div     word [spc]
        mov     cx, ax                          ; last cluster - 2
.l:     mov     ax, si
        add     ax, 2
        call    draw_pat
        inc     si
        cmp     si, cx
        jbe     .l
        popa
        ret

; SI = text: the status line
status: pusha
        mov     dx, STAT_Y
        mov     cx, 16
        xor     bx, bx
        mov     bp, 80
        xor     al, al
        call    fill_band
        xor     ah, ah
        call    center
        popa
        ret

; the inverse band: SI line 1, DI line 2
band:   pusha
        push    di
        mov     dx, BAND_Y
        mov     cx, 400 - BAND_Y
        xor     bx, bx
        mov     bp, 80
        mov     al, 0FFh
        call    fill_band
        mov     dx, BAND_Y + 4
        mov     ah, 0FFh
        call    center
        pop     si
        mov     dx, BAND_Y + 20
        mov     ah, 0FFh
        call    center
        popa
        ret

; "Disk in order: 14 files, 1,063 KB free in one piece" into msgbuf
sb_done:
        mov     di, msgbuf
        mov     si, s_done1
        call    sb_str
        mov     ax, [nfiles]
        mov     si, s_file
        call    sb_count
        mov     si, s_comma
        call    sb_str
        xor     cx, cx                          ; free clusters and pieces
        xor     dx, dx
        mov     ax, 2
        mov     bl, 1                           ; (previous was used)
        mov     es, [oseg]
.l:     cmp     ax, [ncl]
        jae     .t
        mov     si, ax
        cmp     byte [es:si], 0
        jne     .u
        inc     cx
        or      bl, bl
        jz      .n
        inc     dx
        xor     bl, bl
        jmp     .n
.u:     mov     bl, 1
.n:     inc     ax
        jmp     .l
.t:     push    cs
        pop     es
        push    dx
        mov     ax, cx
        mul     word [spc]
        shr     dx, 1
        rcr     ax, 1
        call    sb_u32
        pop     ax
        mov     si, s_done3                     ; " KB free in one piece"
        cmp     ax, 1
        jbe     .p
        mov     si, s_done4                     ; " KB free in "
        push    ax
        call    sb_str
        pop     ax
        mov     si, s_piece
        call    sb_count
        jmp     short .lost
.p:     call    sb_str
.lost:  xor     ax, ax                          ; lost clusters (CHKDSK)
        mov     si, 2
        mov     es, [oseg]
.lc:    cmp     si, [ncl]
        jae     .lx
        cmp     byte [es:si], O_LOST
        jne     .ln
        inc     ax
.ln:    inc     si
        jmp     .lc
.lx:    push    cs
        pop     es
        or      ax, ax
        jz      .bm
        push    ax
        mov     si, s_comma
        call    sb_str
        pop     ax
        mov     si, s_lostc
        call    sb_count
.bm:    mov     ax, [nbadm]
        or      ax, ax
        jz      .z
        push    ax
        mov     si, s_comma
        call    sb_str
        pop     ax
        mov     si, s_badc
        call    sb_count
        mov     si, s_marked
        call    sb_str
.z:     mov     byte [di], 0
        ret

; AX and the word at SI: "1 file", "2 files"
sb_count:
        push    ax
        push    si
        call    sb_u16
        pop     si
        call    sb_str
        pop     ax
        cmp     ax, 1
        je      .x
        mov     al, 's'
        stosb
.x:     ret

; the 11-byte name at SI as NAME.EXT, at DI
sb_name:
        mov     cx, 8                   ; (as the kernel's, MS-DOS's: each
        rep     movsb                   ;  part's trailing spaces dropped,
.nt:    cmp     byte [di-1], ' '        ;  not those inside)
        jne     .e0
        dec     di
        inc     cx
        cmp     cx, 8
        jb      .nt
.e0:    cmp     word [si], '  '
        jne     .e
        cmp     byte [si+2], ' '
        je      .x
.e:     mov     al, '.'
        stosb
        mov     cx, 3
        rep     movsb
.et:    cmp     byte [di-1], ' '
        jne     .x
        dec     di
        jmp     .et
.x:     ret

sb_str: lodsb
        or      al, al
        jz      .x
        stosb
        jmp     sb_str
.x:     ret
sb_hex2:                                        ; AL as 2 hex digits
        push    ax
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .s
        add     al, 7
.s:     stosb
        ret
sb_2d:  aam                                     ; AL (0..99) as 2 digits
        add     ax, 3030h
        xchg    al, ah
        stosw
        ret

; the message SI, the disk errors noted, and (after /T) the cylinders
; with bad sectors
log_all:
        call    log_line
        xor     bx, bx
.e:     cmp     bx, [nev]
        jae     .t
        push    bx
        shl     bx, 3
        mov     di, msgbuf
        mov     ax, 2020h
        stosw
        mov     al, [evs+bx]
        mov     ah, [evs+bx+1]
        mov     dx, [evs+bx+2]
        mov     bp, [evs+bx+4]
        call    sb_where
        mov     byte [di], 0
        mov     si, msgbuf
        call    log_line
        pop     bx
        inc     bx
        jmp     .e
.t:     cmp     byte [testmode], 0
        je      .x
        xor     bx, bx                          ; "  bad sectors on cylinder
.c0:    mov     di, msgbuf                      ;  (count): 63(4) 64(12) ..."
        mov     si, s_bycyl
        call    sb_str
        xor     cx, cx                          ; (any on this line)
.c:     cmp     bx, 84
        jae     .cl
        cmp     byte [badcyl+bx], 0
        je      .cn
        inc     cx
        push    cx
        push    bx
        mov     ax, bx
        call    sb_u16
        mov     al, '('
        stosb
        pop     bx
        push    bx
        mov     al, [badcyl+bx]
        xor     ah, ah
        call    sb_u16
        mov     ax, 2029h
        stosw
        pop     bx
        pop     cx
        cmp     di, msgbuf + 70
        jb      .cn
        inc     bx
        mov     byte [di], 0
        push    bx
        mov     si, msgbuf
        call    log_line
        pop     bx
        jmp     .c0
.cn:    inc     bx
        jmp     .c
.cl:    jcxz    .x
        mov     byte [di], 0
        mov     si, msgbuf
        call    log_line
.x:     ret

; SI = message: "2026-10-05 15:20  message" added to A:\DEFRAG.TXT through
; the kernel (a failure just means no log line)
log_line:
        push    si
        mov     di, logbuf
        mov     ah, 2Ah
        int     21h
        push    dx
        mov     ax, cx
        call    sb_u16
        mov     al, '-'
        stosb
        pop     dx
        push    dx
        mov     al, dh
        call    sb_2d
        mov     al, '-'
        stosb
        pop     dx
        mov     al, dl
        call    sb_2d
        mov     al, ' '
        stosb
        mov     ah, 2Ch
        int     21h
        push    cx
        mov     al, ch
        call    sb_2d
        mov     al, ':'
        stosb
        pop     cx
        mov     al, cl
        call    sb_2d
        mov     ax, 2020h
        stosw
        pop     si
.c:     lodsb                                   ; (msgbuf's 95 fit)
        or      al, al
        jz      .e
        stosb
        cmp     di, logbuf + 126
        jb      .c
.e:     mov     ax, 0A0Dh
        stosw
        mov     dx, s_logf
        mov     ax, 3D01h
        int     21h
        jnc     .op
        mov     dx, s_logf
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
.op:    mov     bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        mov     cx, di
        sub     cx, logbuf
        mov     dx, logbuf
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret
sb_u16: xor     dx, dx                          ; AX, decimal
sb_u32: xor     cx, cx                          ; DX:AX, decimal
        mov     bx, 10
.d:     push    ax
        mov     ax, dx
        xor     dx, dx
        div     bx
        mov     si, ax                          ; (the high part / 10)
        pop     ax
        div     bx
        push    dx
        inc     cx
        mov     dx, si
        or      si, ax
        jnz     .d
.p:     pop     ax
        add     al, '0'
        stosb
        loop    .p
        ret

; ---------------------------------------------------------------------
; drawing primitives (as the Executive's)
mkrows: xor     bx, bx
        mov     di, rowtab
.l:     mov     ax, bx
        and     ax, 3
        shl     ax, 13
        mov     dx, bx
        shr     dx, 2
        imul    dx, dx, 80
        add     ax, dx
        mov     [di], ax
        add     di, 2
        inc     bx
        cmp     bx, 400
        jb      .l
        ret

clear_screen:
        push    es
        push    VSEG
        pop     es
        xor     di, di
        mov     cx, 16384
        xor     ax, ax
        rep     stosw
        pop     es
        ret

; DX = y, CX = rows, BX = byte column, BP = width in bytes, AL = value
fill_band:
        pusha
        push    es
        push    VSEG
        pop     es
.r:     mov     si, dx
        shl     si, 1
        mov     di, [rowtab+si]
        add     di, bx
        push    cx
        mov     cx, bp
        rep     stosb
        pop     cx
        inc     dx
        loop    .r
        pop     es
        popa
        ret

hline:  pusha                                   ; DX = y, BX, CX = width
        mov     bp, cx
        mov     cx, 1
        mov     al, 0FFh
        call    fill_band
        popa
        ret
hline_dots:
        pusha
        mov     bp, cx
        mov     cx, 1
        mov     al, 0AAh
        call    fill_band
        popa
        ret

; AL = char, BX = column, DX = y (a multiple of 4), AH = 00 / FF inverse
putc:   pusha
        push    es
        push    VSEG
        pop     es
        cmp     al, 32
        jb      .bad
        cmp     al, 127
        jbe     .ok
.bad:   mov     al, '?'
.ok:    mov     cl, ah
        xor     ah, ah
        sub     al, 32
        shl     ax, 4
        add     ax, font
        mov     si, ax
        mov     di, dx
        shl     di, 1
        mov     di, [rowtab+di]
        add     di, bx
        mov     ah, cl
%assign r 0
%rep 16
        lodsb
        xor     al, ah
        mov     [es:di + (r & 3) * 2000h + (r >> 2) * 80], al
%assign r r + 1
%endrep
        pop     es
        popa
        ret

; SI = ASCIIZ, BX = column, DX = y, AH = mask.  SI ends past the NUL
puts:   push    bx
.l:     lodsb
        or      al, al
        jz      .x
        cmp     bx, 80
        jae     .l
        call    putc
        inc     bx
        jmp     .l
.x:     pop     bx
        ret

strlen: push    si
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .x
        inc     cx
        jmp     .l
.x:     pop     si
        ret

center: push    ax                              ; SI, DX = y, AH = mask
        call    strlen
        mov     bx, 80
        sub     bx, cx
        jnc     .c
        xor     bx, bx                          ; (longer than the line)
.c:     shr     bx, 1
        pop     ax
        jmp     puts

; =====================================================================
; cell patterns, 8 rows (doubled for 16-pixel cells)
pats:   db 000h,000h,038h,038h,038h,000h,000h,000h      ; free (3x3: lone
                                                        ;  plasma dots fire badly)
        db 0FEh,0FEh,0FEh,0FEh,0FEh,0FEh,0FEh,000h      ; file
        db 0AAh,054h,0AAh,054h,0AAh,054h,0AAh,000h      ; fragmented
        db 0FEh,082h,082h,082h,082h,082h,0FEh,000h      ; directory/system
        db 082h,044h,028h,010h,028h,044h,082h,000h      ; bad
        db 000h,044h,000h,010h,000h,044h,000h,000h      ; lost
        db 0FEh,082h,0BAh,0BAh,0BAh,082h,0FEh,000h      ; being read
        db 0FEh,0FEh,0C6h,0C6h,0C6h,0FEh,0FEh,000h      ; being written

LEG_X   equ 9
legend: db P_FILE, 'file', 0
        db P_FRAG, 'in pieces', 0
        db P_FREE, 'free', 0
        db P_DIR, 'directory', 0
        db P_BAD, 'bad', 0
        db P_LOST, 'lost', 0
        db 0FFh

s_title   db 'Lodestone Defrag', 0
s_drive   db 'Drive '
lt_drive  db 'A:', 0
s_band1   db 'Defragmenting drive '
lt_band1  db 'A:', 0
s_band1t  db 'Testing drive '
lt_band1t db 'A:', 0
s_band1s  db 'Screen saver - tidying drive '
lt_band1s db 'A:', 0
s_band2   db 'Press any key to stop', 0
s_anykey  db 'Press any key', 0
s_reading db 'Reading the disk', 0
s_rootp1  db 'Tidying the root directory (', 0
s_rootp2  db ' deleted)', 0
s_moving  db 'Moving ', 0
s_join    db ' into one piece', 0
s_fwd     db ' forward', 0
s_out     db ' out of the way', 0
s_done1   db 'Disk in order: ', 0
s_file    db ' file', 0
s_comma   db ', ', 0
s_piece   db ' piece', 0
s_lostc   db ' lost cluster', 0
s_done3   db ' KB free in one piece', 0
s_done4   db ' KB free in ', 0
s_fatsync db 'Making the two FAT copies match', 0
s_stopped db 'Stopped - the disk is fine as it is', 0
s_rderr   db 'Cannot read this disk', 0
s_mem     db 'Not enough memory for this disk', 0
s_nosave  db 'Lodestone could not save its changes - map only', 0
s_open    db 'Files are open on drive '
lt_open   db 'A: - map only', 0
s_many    db 'Too many files or directories for DEFRAG - map only', 0
s_left1   db 'Done, but ', 0
s_left2   db ' still in pieces (not enough room)', 0
s_chkdsk  db 'This disk needs CHKDSK first - map only', 0
s_nochg   db 'This drive has no change line - map only', 0
s_notgos  db 'Defragmenting needs Lodestone - map only', 0
s_wprot   db 'The disk is write-protected - map only', 0
s_changed db 'The disk was changed - stopped', 0
s_derr    db 'Disk error ', 0
s_reading2 db 'h reading ', 0
s_writing db 'h writing ', 0
s_rbdiff  db 'Read back different at ', 0
s_cyl     db 'cylinder ', 0
s_side    db ' side ', 0
s_sector  db ' sector ', 0
s_derr2   db ' - stopped, files fine', 0
s_entry   db 'A directory entry changed under DEFRAG - stopped', 0
s_testing db 'Testing the free space, cylinder by cylinder', 0
s_tested  db 'Free space tested: ', 0
s_kbc     db ' KB, ', 0
s_bycyl   db '  bad sectors on cylinder (count): ', 0
s_toobad  db 'Writes fail everywhere - stopped (the drive?), files fine', 0
s_unr1    db 'Done - ', 0
s_unread  db " couldn't be read, left as it is", 0
s_badc    db ' bad cluster', 0
s_err     db ' disk error', 0
s_marked  db ' marked', 0
s_logf    db 'A:\DEFRAG.TXT', 0
s_nomem   db 'DEFRAG: not enough memory', 13, 10, '$'
s_memdrv  db 'DEFRAG: M: is the temporary disk, in memory: nothing to tidy', 13, 10, '$'
s_nodrv   db 'DEFRAG: there is no drive '
lt_nodrv  db 'A:', 13, 10, '$'
s_nogfx   db 'DEFRAG needs the GRiD 640x400 screen', 13, 10, '$'

%include "FONT.INC"

; =====================================================================
        alignb  2
section .bss
bss_start:
bseg    resw 1
sp0     resw 1
mptr    resw 2
saver   resb 1
unit    resb 1                          ; BIOS floppy unit: 0 = A:, 1 = B:
unitset resb 1
mouse   resb 1
lodestone  resb 1
ronly   resb 1
cl_ok   resb 1
writing resb 1
result  resb 1
lfn_open resb 1
cm_frag resb 1
b_try   resb 1
wv_n    resb 1
rtry    resb 1
logit   resb 1
flaky   resb 1
er_code resb 1
er_op   resb 1
        alignb 2
wv_cnt  resw 1
nev     resw 1
nerrs   resw 1
evs     resb 8 * 8
testmode resb 1
nearmode resb 1
        alignb 2
pr_cl   resw 1
allbad  resb 1
        alignb 2
badcyl  resb 84
dend    resw 2
sl      resw 2
tn      resw 1
tbad    resw 1
tfree   resw 1
ntsec   resw 2
failrun resw 1
weak_lba resw 2
er_lba  resw 2
mv_err  resw 1
mv_mark resw 1
nbadm   resw 1
logbuf  resb 128
        alignb 2
ronly_why resw 1
ww      resw 1
oldmode resb 1
        alignb 2
b_op    resw 1
b_lba   resw 2
pk_lba  resw 2                          ; INT 25h/26h's packet
pk_n    resw 1
pk_buf  resw 2
rcap    resw 1                          ; clusters a copy run (sectors < 64K)
spt     resw 1
heads   resw 1
spc     resw 1
cbytes  resw 1
rsv     resw 1
nfat    resw 1
spf     resw 1
fsec    resw 1                          ; of them: those we hold (<= 256)
nroot   resw 1
rsec    resw 1
rootlba resw 1
datalba resw 1
ncl     resw 1
rnew    resw 1                          ; the root as it will be
ch_h    resw 1
fdirty  resb 32                         ; FAT sectors to write (bits)
fdany   resb 1
fat16   resb 1
fseg    resw 1                          ; the FAT
oseg    resw 1                          ; each cluster's owner
xseg    resw 1
cpc     resw 1                          ; clusters a map cell
fk      resw 1
fs_     resw 1
removed resw 1
oldused resw 1
lfn_start resw 1
rp_n    resw 1
rp_lo   resw 1
rp_hi   resw 1
nfiles  resw 1
nfrag   resw 1
ndq     resw 1
e_lba   resw 2
e_off   resw 1
wd_cl   resw 1
need    resw 1
gp      resw 1
gs_     resw 1
ge      resw 1
glen    resw 1
best    resw 1
bestn   resw 1
mv_msg  resw 1
mv_rec  resw 1
mv_d    resw 1
mv_s    resw 1
mv_left resw 1
mv_dl   resw 2
mv_rs   resw 1
mv_rl   resw 1
mv_sl   resw 1
mv_sa   resw 2
mv_n    resw 1
dirq    resw MAXDQ
rowtab  resw 400
msgbuf  resb 96
bootsec resb 512
dirsec  resb 512
files   resb FSZ * MAXF
bss_end:
        resb 1024
stack_top:
rootbuf:                                ; the root, and then [rnew]: [rsec]
                                        ;  sectors each
