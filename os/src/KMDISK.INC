; =====================================================================
;  KMDISK.INC - M:, the temporary disk: a RAM disk in EMS, as GRiD's
;  Temporary Disk and Microsoft's RAMDrive, on the kernel's own FAT12.
;
;  Drive 12 (M:), FAT12 with 512-byte sectors, two to a cluster, one
;  FAT, in pages of Lodestone's own EMS manager: a handle of its own with
;  owner 0 (the installer runs in the EMS frame, no program's memory),
;  which no program's exit frees and INT 67h counts as used.  (Not handle
;  0: LIM lets any program empty that one, and EMSTEST does.)  The
;  kernel's FAT engine does the rest; M: has only a sector routine of
;  its own (md_dio, as hd_dio is C:'s), which writes a window's page
;  register itself (never INT 67h), copies, and puts it back.  M: never
;  reaches the disk cache (dio's call to tc_piece comes after the hook).
;  Its directory sectors pass through the sector buffers like every
;  drive's (the kernel edits them there), keyed 0Ch: a floppy's key never
;  has a high part, and C:'s always has bit 1 set, so none is M:'s.
;
;  Nothing of it is in memory without EMS, and nothing while M: is off:
;    - the installer (md_entry) and the resident part's image live in
;      the disk cache's second EMS page, past the cache's 2 KB in it
;      (ems_init copies them there; the cache only ever uses 18 KB);
;    - they are reached through INT 67h AH=5Bh with AL='M' (5Bh is an
;      OS function: programs still get A4h for any other AL), by 26
;      bytes at KSEG:0012h, where `start' was.  `start' only ever runs in
;      the load image (the boot sector jumps to 1000:0000; a warm
;      restart loads the file again), so those bytes are free after it;
;    - while M: is on, its resident part (md_res: the hooks, md_dio,
;      M:'s drive table entry and current directory) is a block of its
;      own (owner 8, "MD"), split off the end of the master environment's
;      512 bytes: the environment keeps the rest (its MCB says how much,
;      for programs that add to it), and DOS programs never got that
;      memory, so they get just as much as before.  Off: the block goes
;      and the environment has its 512 bytes again;
;    - at start-up init's last jump goes to md_boot, in the load image,
;      which reads MDISK= in \LODE.INI and asks for M: (256 KB without
;      such a line).
;  (md_boot runs in the load image after ui_load: the UI block's BSS has
;  covered the image's first 4.8 KB by then, the start-ups and the
;  template, from 22 KB in, are still there.)
;  INT 67h AH=5Bh AL='M' (with EMS and the disk cache in it):
;    BL=0  -> BX = the setting in KB (0 off, FFFFh all free), CX = M:'s
;             size in KB (0: none), DX = the most "all free" would give,
;             SI = M:'s EMS handle (0: none)
;    BL=1  CX = KB (0 off, FFFFh all free): M: made again at that size,
;             empty (as big as fits when EMS is short) -> CX = its KB
;    BL=2  the same at start-up, keeping M:'s files if they outlived a
;          warm restart (the same pages, its boot sector as made, a sane
;          FAT)
;    -> AH = 0, or 80h: a file on M: is open, or the call came from
;       inside INT 21h (nothing changed); 81h: no room to split off the
;       environment (M: off); 82h: no EMS pages (or no handle) free (M:
;       off).  The setting is kept either way (but for 80h).
;  (A caller's stack must not be in the page frame's first two windows,
;  which the installer uses: only Lodestone calls this, and MDTEST.)
; =====================================================================
%ifndef NOTC
MD_DRV  equ 12                          ; M:
                                        ; (MD_TPG, LODE.ASM: the template's
                                        ;  place in the cache's second page,
                                        ;  past the cache's 2 KB there)
MD_SCR  equ 3800h                       ; and 512 bytes there to build a sector
MD_W1   equ EMS_FRAME + 400h            ; window 1: M:'s first page meanwhile
MD_P1   equ EMS_PORT + 4000h
MD_STUB equ 12h                         ; the stub's place in the kernel
%ifndef MD_SHIFT
MD_SHIFT equ 1                          ; clusters: 2 ^ this sectors
%endif
MD_IBUF equ 0F000h                      ; md_boot: LODE.INI, past the load image

; =====================================================================
;  the resident part: assembled here and moved to wherever its block is
;  (md_relp, md_relm: the words that change with it).  Only its near
;  jumps to the kernel and its own two tables' addresses depend on that.
; =====================================================================
%assign MD_NRM 0
%macro KJMP 1                           ; JMP NEAR to the kernel (- the move)
        jmp     near %1
..@md_rm%[MD_NRM]:
%assign MD_NRM MD_NRM+1
%endmacro
%assign MD_NRP 0
%macro MADR 1+                          ; ends in an address in md_res (+ it)
        %1
..@md_rp%[MD_NRP]:
%assign MD_NRP MD_NRP+1
%endmacro
%assign MD_NRH 0
%macro HADR 1+                          ; ends in an address in handle 0's
        %1                              ;  record (+ 4 * M:'s handle)
..@md_rh%[MD_NRH]:
%assign MD_NRH MD_NRH+1
%endmacro

section mdt
md_tstart:                              ; (the template: from here)
md_res:
md_dt:  times DRVSZ db 0                ; M:'s drive table entry
md_cwd: times CWDLEN db 0               ; its current directory

; use_drive: M:'s entry
md_use: cmp     al, MD_DRV
        jne     .t
        mov     [act], al
        MADR    mov si, md_dt
        mov     [actp], si
        ret
.t:     times use_drive.hk - use_drive db 90h
        KJMP    use_drive.hk

; drv_present (so drv_ready, INT 21h 0Eh, 29h, 47h, 4Fh, 4408h too): M: is
; there (on to use_drive with CF clear)
md_pres: cmp    al, MD_DRV
        jne     .t
        KJMP    drv_present.hk
.t:     times drv_present.hk - drv_present db 90h
        KJMP    drv_present.hk

; cwd_of: M:'s current directory
md_cwdh: cmp    al, MD_DRV
        jne     .t
        MADR    mov di, md_cwd
        ret
.t:     times cwd_of.hk - cwd_of db 90h
        KJMP    cwd_of.hk


; dio for M:: AH = 2 read / 3 write, DX = sector, CX = sectors, ES:BX =
; memory.  A piece at a time, each within one page: the page into a window
; the memory isn't in (3, or 0 when the memory starts from E800h up to
; F000h: a piece is 16 KB at most), copied, the window as it was.  The
; register is read and written with interrupts off, so nothing sees it
; half changed; the copy runs with them on (an interrupt handler that maps
; pages puts them back, as LIM asks).  CF: AX = 27 (a sector past M:'s
; pages: never, unless the FAT is damaged; or M:'s handle isn't M:'s any
; more: a program closed it by mistake, and another may have it now)
md_dio: cmp     al, MD_DRV
        je      .m
.t:     times dio.hk - dio db 90h
        KJMP    dio.hk
.m:     pusha
        push    es
        push    ds
        mov     bp, ax                  ; (BP: AH = 2 read, 3 write)
        mov     ax, bx                  ; ES:BX with BX < 16: the pieces are
        shr     ax, 4                   ;  whole sectors, so BX stays and ES
        mov     di, es                  ;  moves on
        add     ax, di
        mov     es, ax
        and     bx, 15
        jmp     .chk
.l:     mov     si, dx
        and     si, 31                  ; SI = the sector in its page
        mov     ax, 32
        sub     ax, si
        cmp     ax, cx
        jb      .n
        mov     ax, cx                  ; AX = sectors this time
.n:     sub     cx, ax
        push    cx                      ; (what is left,
        mov     di, dx
        add     dx, ax
        push    dx                      ;  the next sector,
        mov     cx, ax
        shl     ax, 5
        mov     dx, es
        add     ax, dx
        push    ax                      ;  the next piece's memory)
        HADR    mov ax, [ems_h + 2]     ; the handle still M:'s (owner 0)?
        or      ax, ax
        jnz     .bad
        shr     di, 5                   ; the page: one of M:'s handle's?
        HADR    mov ax, [ems_h + 1]     ; (AH: the owner's low byte, 0)
        cmp     di, ax
        jae     .bad
        HADR    mov al, [ems_h]         ; (its run in ems_ltab)
        add     di, ax
        mov     al, [ems_ltab + di]     ; its register value
        shl     si, 9                   ; its offset in the window
        xchg    cl, ch                  ; CX = words
        mov     di, es                  ; the window
        sub     di, 0E800h
        cmp     di, 800h
        mov     dx, EMS_PORT + 0C000h
        mov     di, EMS_FRAME + 0C00h
        jae     .w
        mov     dh, EMS_PORT >> 8
        mov     di, EMS_FRAME
.w:     cli
        mov     ah, al
        in      al, dx
        xchg    al, ah
        out     dx, al                  ; ours in, AH = what was there
        sti
        push    ax
        mov     ds, di                  ; read: the page -> memory
        mov     di, bx
        test    bp, 100h
        jz      .cp
        push    ds                      ; write: the other way
        push    es
        pop     ds
        pop     es
        xchg    si, di
.cp:    rep     movsw
        pop     ax
        mov     al, ah
        out     dx, al                  ; the window as it was
        push    cs
        pop     ds
        pop     es
        pop     dx
        pop     cx
.chk:   jcxz    .ok
        jmp     .l
.bad:   add     sp, 6
        stc
        db      0B0h                    ; (MOV AL, imm8: over the CLC)
.ok:    clc
        mov     word [io_ra], 0         ; (read-ahead is per transfer)
        pop     ds
        pop     es
        popa
        jnc     .x
        mov     ax, 27                  ; sector not found
.x:     ret
md_res_end:
MD_PARAS equ (md_res_end - md_res + 15) / 16

; =====================================================================
;  the installer: in the disk cache's second page, run in window 0
;  (CS = E000h) by md_stub, inside INT 67h (ems_gen: DS = KSEG, BP = the
;  caller's registers as INT 21h's frame, interrupts off).  DS stays the
;  kernel's throughout: the installer's own data is reached through CS.
;  DX (window 0's port) is md_stub's: kept.  -> AH
; =====================================================================
md_entry:
        push    dx
        cld
        mov     bl, [bp+F_BX]
        or      bl, bl
        jnz     .set
        mov     ax, [cs:md_kb]          ; 0: how things are
        mov     [bp+F_BX], ax
        mov     al, [cs:md_pg]
        call    md_kbof
        mov     [bp+F_CX], ax
        mov     al, [ems42 + 1]         ; (the pages there are for programs)
        sub     al, [ems_used]
        add     al, [cs:md_pg]
        call    md_kbof
        mov     [bp+F_DX], ax
        xor     ax, ax
        cmp     [cs:md_pg], al
        je      .q
        mov     ax, [cs:md_h]
.q:     mov     [bp+F_SI], ax
        xor     ah, ah
        jmp     short .x
.set:   mov     ah, 80h                 ; (called inside INT 21h, as from a
        cmp     byte [indos], 0         ;  handler: not now, M:'s directory
        jne     .s                      ;  may be at work)
        mov     [cs:md_mode], bl
        mov     cx, [bp+F_CX]
        call    md_make
.s:     push    ax
        cmp     byte [cs:md_mode], 2    ; at start-up with no M: (off, or no
        jne     .w                      ;  room for it): no old M: may come
        cmp     byte [cs:md_pg], 0      ;  back at a later one
        jne     .w
        call    md_wipe
.w:     cmp     byte [cs:md_pg], 0      ; M: off now, and it was the current
        jne     .c                      ;  drive: the one Lodestone started from
        cmp     byte [cur_drv], MD_DRV
        jne     .c
        mov     al, [bootdrv]           ; (A:, B:, or from the ROM R:)
.cd:    mov     [cur_drv], al
.c:     mov     al, [cs:md_pg]
        call    md_kbof
        mov     [bp+F_CX], ax
        pop     ax
.x:     pop     dx
        retf

; AL pages -> AX KB
md_kbof:
        xor     ah, ah
        shl     ax, 4
        ret

; M: at CX KB (0 off, FFFFh all free) -> AH
md_make:
        cmp     byte [cs:md_pg], 0
        je      .off
        call    md_open                 ; a file on M: open: no change
        mov     ah, 80h
        jnz     .r
        call    md_down
.off:   mov     [cs:md_kb], cx
        xor     ah, ah
        jcxz    .r                      ; (off: that's all)
        mov     al, [ems42 + 1]         ; the pages: CX / 16 (one at least),
        sub     al, [ems_used]          ;  as many as are free at most
        mov     ah, 82h
        jz      .r
        xor     ah, ah
        shr     cx, 4
        jnz     .c
        inc     cx
.c:     cmp     cx, ax
        jbe     .p
        mov     cx, ax
.p:     mov     bx, cx                  ; a handle of its own gets them
        mov     ah, 43h
        int     67h
        or      ah, ah
        mov     ah, 82h                 ; (no handle free either: as no pages)
        jnz     .r
        xor     ah, ah
        mov     [cs:md_h], dx
        call    md_split                ; and the resident part its block
        jnc     .in
        push    ax
        mov     dx, [cs:md_h]           ; (no room: the pages back)
        mov     ah, 45h
        int     67h
        pop     ax
.r:     ret
.in:    call    md_rec
        mov     al, [si+1]
        mov     [cs:md_pg], al
        call    md_load
        call    md_disk
        call    md_hook
        xor     ah, ah
        ret

; At start-up without M:: the first free page, where M: would start, loses
; an old M:'s boot sector.  Otherwise a disk left there (by a start-up with
; MDISK=0, say) could be taken for M: at a later start-up, after programs
; had used its pages.  (A disk turned off while running is cleared by
; md_down.)  All registers kept
md_wipe:
        pusha
        push    es
        push    ds
        mov     al, [ems42 + 1]
        sub     al, [ems_used]
        jbe     .r                      ; (no page free)
        xor     bx, bx
        mov     bl, [ems_used]
        mov     dx, MD_P1               ; it in window 1 meanwhile
        in      al, dx
        mov     ah, al
        mov     al, [ems_ltab + bx]
        out     dx, al
        mov     bx, MD_W1
        mov     es, bx
        push    cs
        pop     ds
        mov     si, md_bs0              ; an M:'s boot sector starts so
        xor     di, di
        mov     cx, 11
        repe    cmpsb
        jne     .o
        mov     word [es:0], 0
.o:     mov     al, ah
        out     dx, al
.r:     pop     ds
        pop     es
        popa
        ret

; SI = M:'s handle's record
md_rec: mov     si, [cs:md_h]
        shl     si, 2
        add     si, ems_h
        ret

; any file on M: open?  NZ if so (BX, CX kept)
md_open:
        mov     si, sft
        mov     di, NSFT
.l:     cmp     byte [si+S_REF], 0      ; (a closed one keeps its mode, drive)
        je      .n
        test    byte [si+S_FLAGS], SF_DEV
        jnz     .n
        cmp     byte [si+S_DRV], MD_DRV
        jne     .n
        or      si, si                  ; (NZ)
        ret
.n:     add     si, SFT_SZ
        dec     di
        jnz     .l
        ret                             ; (ZF)

; the master environment's block (the arena's first): its own part kept,
; the end split off as M:'s block (MD_PARAS) -> [md_mseg].  CF: AH = 81h
md_split:
        mov     ax, [first_mcb]
        mov     es, ax
        inc     ax
        mov     [cs:md_env], ax
        mov     bx, [es:3]
        mov     [cs:md_envp], bx
        mov     es, [root_psp]          ; (the root's environment?)
        cmp     ax, [es:2Ch]
        jne     .no
        mov     es, ax                  ; its strings: up to the double NUL
        xor     di, di
        xor     al, al
        mov     cx, bx
        shl     cx, 4
.s:     repne   scasb
        jne     .no
        scasb
        jne     .s
        sub     bx, MD_PARAS + 1        ; BX = what it keeps: room for them?
        jbe     .no
        mov     ax, bx
        shl     ax, 4
        cmp     ax, di
        jb      .no
        mov     ah, 4Ah                 ; (ES = it)
        int     21h
        jc      .no
        push    bx
        mov     bx, MD_PARAS
        mov     ah, 48h
        int     21h
        pop     bx
        jc      .back
        mov     [cs:md_mseg], ax        ; right after it?
        mov     dx, es
        add     dx, bx
        inc     dx
        cmp     ax, dx
        je      .ok
        mov     es, ax                  ; (somewhere else: no)
        mov     ah, 49h
        int     21h
        mov     es, [cs:md_env]
.back:  mov     bx, [cs:md_envp]
        mov     ah, 4Ah
        int     21h
.no:    mov     ah, 81h
        stc
        ret
.ok:    dec     ax
        mov     es, ax
        mov     word [es:1], 8          ; the system's, called MD
        mov     word [es:8], 'MD'
        clc
        ret

; the resident part into its block, moved there, with M:'s entry and "\"
md_load:
        call    md_geom
        mov     es, [cs:md_mseg]
        mov     ax, es                  ; how far it moves: its block's offset
        sub     ax, KSEG                ;  from KSEG, less where it is here
        shl     ax, 4
        sub     ax, md_res
        mov     [cs:md_delta], ax
        xchg    ax, dx
        push    ds
        push    cs
        pop     ds
        mov     si, md_res
        xor     di, di
        mov     cx, md_res_end - md_res
        rep     movsb
        mov     si, md_relp             ; + that
.p:     lodsw
        cmp     ax, 0FFFFh
        je      .m
        xchg    ax, bx
        add     [es:bx], dx
        jmp     .p
.m:     lodsw                           ; - that (md_relm follows)
        cmp     ax, 0FFFFh
        je      .h
        xchg    ax, bx
        sub     [es:bx], dx
        jmp     .m
.h:     mov     dx, [md_h]              ; + its handle's record (md_relh)
        shl     dx, 2
.hl:    lodsw
        cmp     ax, 0FFFFh
        je      .g
        xchg    ax, bx
        add     [es:bx], dx
        jmp     .hl
.g:     mov     si, md_dte
        mov     di, md_dt - md_res
        mov     cx, DRVSZ
        rep     movsb
        mov     word [es:md_cwd - md_res], '\'
        pop     ds
        ret

; M:'s geometry from [md_pg] pages: md_dte, its drive table entry, and at
; E000:MD_SCR its boot sector (a signature, the BPB, its pages' registers,
; a checksum)
md_geom:
        push    es
        push    cs
        pop     es
        mov     di, md_dte
        mov     cx, DRVSZ
        xor     al, al
        rep     stosb
        mov     al, [cs:md_pg]
        xor     ah, ah
        shl     ax, 5
        mov     [cs:md_dte + D_TOT], ax ; sectors: 32 a page
        shr     ax, MD_SHIFT
        add     ax, 2                   ; the FAT: 1.5 bytes a cluster (no more
        imul    ax, ax, 3               ;  than there are sectors for), whole
        add     ax, 1023                ;  sectors
        shr     ax, 10
        mov     [cs:md_dte + D_SPF], ax
        inc     ax
        mov     [cs:md_dte + D_ROOT], ax
        mov     bx, 64                  ; the root: 64 entries, 128 from 256 KB
        cmp     byte [cs:md_pg], 16
        jb      .r
        shl     bx, 1
.r:     mov     [cs:md_dte + D_NROOT], bx
        shr     bx, 4
        mov     [cs:md_dte + D_RSEC], bx
        add     ax, bx
        mov     [cs:md_dte + D_DATA], ax
        neg     ax
        add     ax, [cs:md_dte + D_TOT]
        shr     ax, MD_SHIFT            ; clusters
        inc     ax
        inc     ax
        mov     [cs:md_dte + D_NCL], ax
        mov     byte [cs:md_dte + D_UNIT], 80h + MD_DRV ; (fixed: no change line)
        mov     byte [cs:md_dte + D_MNT], 1
        mov     byte [cs:md_dte + D_SPC], 1 << MD_SHIFT
        mov     byte [cs:md_dte + D_SHIFT], MD_SHIFT
        mov     byte [cs:md_dte + D_NFAT], 1
        mov     byte [cs:md_dte + D_RSV], 1
        mov     byte [cs:md_dte + D_SPT], 255   ; (write runs: no tracks)
        mov     byte [cs:md_dte + D_HEADS], 1
        mov     byte [cs:md_dte + D_PRES], 1
        mov     byte [cs:md_dte + D_HINT], 2
        mov     byte [cs:md_dte + D_MEDIA], 0F8h
        mov     di, MD_SCR              ; the boot sector
        mov     cx, 256
        xor     ax, ax
        rep     stosw
        push    ds
        push    cs
        pop     ds
        mov     di, MD_SCR
        mov     si, md_bs0
        mov     cl, md_bs0e - md_bs0
        rep     movsb
        pop     ds
        mov     ax, [cs:md_dte + D_NROOT]
        mov     [cs:MD_SCR + 11h], ax
        mov     ax, [cs:md_dte + D_TOT]
        mov     [cs:MD_SCR + 13h], ax
        mov     ax, [cs:md_dte + D_SPF]
        mov     [cs:MD_SCR + 16h], ax
        mov     di, MD_SCR + 40h        ; its pages, as their registers show
        mov     al, [cs:md_pg]          ;  them
        stosb
        mov     cl, al
        xor     ch, ch
        call    md_rec
        xor     bx, bx
        mov     bl, [si]
.pl:    mov     al, [ems_ltab + bx]
        stosb
        inc     bx
        loop    .pl
        push    ds                      ; a checksum: the words sum to "MD"
        push    cs
        pop     ds
        mov     si, MD_SCR
        mov     cx, 255
        mov     dx, 'MD'
.ck:    lodsw
        sub     dx, ax
        loop    .ck
        mov     [si], dx
        pop     ds
        pop     es
        ret
md_bs0: db      0EBh, 3Ch, 90h, 'LODE M: '      ; (a boot sector's look)
        dw      512                             ; 0Bh bytes a sector
        db      1 << MD_SHIFT                   ; 0Dh sectors a cluster
        dw      1                               ; 0Eh reserved
        db      1                               ; 10h FATs
        dw      0, 0                            ; 11h root entries, sectors
        db      0F8h                            ; 15h media
        dw      0, 255, 1                       ; 16h FAT sectors, track, heads
md_bs0e:

; M: on its pages: kept at start-up if it is the disk this would make (its
; boot sector, byte for byte: the same pages) with a FAT that can be one,
; else made new (its boot sector, FAT and root; the files' space as it
; was).  Its first page in window 1 meanwhile.
md_disk:
        call    md_w1
        push    ax
        push    es
        mov     ax, MD_W1
        mov     es, ax
        cmp     byte [cs:md_mode], 2
        jne     .new
        push    ds                      ; the same disk?
        push    cs
        pop     ds
        mov     si, MD_SCR
        xor     di, di
        mov     cx, 256
        repe    cmpsw
        pop     ds
        jne     .new
        call    md_fatok
        jnc     .x
.new:   xor     di, di                  ; a new one
        mov     cx, [cs:md_dte + D_DATA]
        xchg    cl, ch                  ; (words)
        xor     ax, ax
        rep     stosw
        push    ds
        push    cs
        pop     ds
        mov     si, MD_SCR
        xor     di, di
        mov     cx, 256
        rep     movsw
        pop     ds
        mov     word [es:200h], 0FFF8h  ; FAT: F8h FFh FFh
        mov     byte [es:202h], 0FFh
.x:     pop     es
        pop     ax
        mov     al, ah
        out     dx, al
        ret

; M:'s first page into window 1 -> AH = what window 1 had, DX = its port.
; BX, SI changed
md_w1:  mov     dx, MD_P1
        in      al, dx
        mov     ah, al
        call    md_rec
        xor     bx, bx
        mov     bl, [si]
        mov     al, [ems_ltab + bx]
        out     dx, al
        ret

; is the FAT at ES:200h one?  Entry 0 F8h FFh FFh, every other free, an
; end, bad, or one of M:'s clusters.  CF if not
md_fatok:
        cmp     word [es:200h], 0FFF8h
        jne     .no
        cmp     byte [es:202h], 0FFh
        jne     .no
        mov     cx, [cs:md_dte + D_NCL]
        mov     bx, 2
.l:     cmp     bx, cx
        jae     .ok                     ; (CF clear)
        mov     si, bx
        shr     si, 1
        add     si, bx
        mov     ax, [es:200h + si]
        test    bl, 1
        jz      .e
        shr     ax, 4
.e:     and     ax, 0FFFh
        jz      .n                      ; free
        cmp     ax, 0FF7h
        jae     .n                      ; bad, or an end
        cmp     ax, 2
        jb      .no
        cmp     ax, cx
        jae     .no
.n:     inc     bx
        jmp     .l
.no:    stc
.ok:    ret

; the hooks in: each place's first bytes to its .t (KHD.INC's jump there
; made relative to its new place), a jump to the hook at the place; and
; INT 21h 0Eh counts to M: at least (what it said is kept for M: off)
md_hook:
        mov     al, [lastdrv]
        mov     [cs:md_ld], al
        cmp     al, MD_DRV + 1
        jae     .ld
        mov     byte [lastdrv], MD_DRV + 1
.ld:    mov     si, md_hooks
.l:     mov     di, [cs:si]             ; the place
        or      di, di
        jz      .x
        mov     bx, [cs:si+6]           ; its .t
        or      bx, bx
        jz      .keep
        add     bx, [cs:md_delta]
        mov     cx, [cs:si+2]
        sub     cx, di
        push    di
        push    bx
.c:     mov     al, [di]
        mov     [bx], al
        inc     di
        inc     bx
        loop    .c
        pop     bx
        pop     di
        cmp     byte [bx], 0E9h         ; (the place - .t further for it)
        jne     .j
        mov     ax, di
        sub     ax, bx
        add     [bx+1], ax
        jmp     short .j
.keep:  mov     ax, [di]                ; (no .t: the bytes kept)
        mov     [cs:md_keep], ax
        mov     al, [di+2]
        mov     [cs:md_keep+2], al
.j:     mov     byte [di], 0E9h         ; JMP NEAR the hook
        mov     ax, [cs:si+4]
        add     ax, [cs:md_delta]
        sub     ax, di
        sub     ax, 3
        mov     [di+1], ax
        add     si, 8
        jmp     .l
.x:     ret

; and out again: each place's bytes back from its .t (or md_keep)
md_unhook:
        mov     al, [cs:md_ld]
        mov     [lastdrv], al
        mov     si, md_hooks
.l:     mov     di, [cs:si]
        or      di, di
        jz      .x
        mov     bx, [cs:si+6]
        or      bx, bx
        jz      .keep
        add     bx, [cs:md_delta]
        mov     cx, [cs:si+2]
        sub     cx, di
        push    di
        push    bx
.c:     mov     al, [bx]
        mov     [di], al
        inc     di
        inc     bx
        loop    .c
        pop     bx
        pop     di
        cmp     byte [di], 0E9h
        jne     .n
        mov     ax, bx
        sub     ax, di
        add     [di+1], ax
        jmp     short .n
.keep:  mov     ax, [cs:md_keep]
        mov     [di], ax
        mov     al, [cs:md_keep+2]
        mov     [di+2], al
.n:     add     si, 8
        jmp     .l
.x:     ret

; M: off: the hooks out, its block gone (the environment whole again), the
; kernel's memory of the drive forgotten, its pages back.  CX kept
md_down:
        push    cx
        call    md_unhook
        mov     es, [cs:md_mseg]
        mov     ah, 49h
        int     21h
        mov     es, [cs:md_env]
        mov     bx, [cs:md_envp]
        mov     ah, 4Ah
        int     21h
        mov     al, MD_DRV
        mov     di, buf_drv             ; its sectors in the buffers
        mov     cx, NBUF
.b:     cmp     [di], al
        jne     .bn
        mov     byte [di], 0FFh
.bn:    inc     di
        loop    .b
        cmp     [fat_drv], al           ; its FAT
        jne     .f
        mov     byte [fat_drv], 0FFh
        mov     byte [fat_dirty], 0
        mov     word [fat_dmask], 0
.f:     cmp     [de_drv], al            ; its root sector
        jne     .d
        mov     byte [de_drv], 0FFh
.d:     call    md_rec                  ; its pages, if they are still M:'s
        cmp     word [si+2], 0          ;  (a program may have closed the
        jne     .g                      ;  handle by mistake, and another
        mov     al, [si+1]              ;  have it now: theirs, then)
        cmp     al, [cs:md_pg]
        jne     .g
        call    md_w1                   ; its boot sector's first word cleared:
        push    es                      ;  a warm restart doesn't take what
        mov     bx, MD_W1               ;  these pages hold next for M:
        mov     es, bx
        mov     word [es:0], 0
        pop     es
        mov     al, ah
        out     dx, al
        mov     dx, [cs:md_h]
        mov     ah, 45h
        int     67h
.g:     mov     byte [cs:md_pg], 0
        pop     cx
        ret

; the places hooked: the kernel's place, its .hk (0: none, the hook doesn't
; go on: the bytes are kept in md_keep), the hook, its .t (in md_res)
md_hooks:
        dw      use_drive, use_drive.hk, md_use, md_use.t
        dw      drv_present, drv_present.hk, md_pres, md_pres.t
        dw      cwd_of, cwd_of.hk, md_cwdh, md_cwdh.t
        dw      dio, dio.hk, md_dio, md_dio.t
        dw      0

; ---- the installer's own (here, in EMS) ----
md_kb       dw  0                       ; the setting: KB (0 off, FFFFh all)
md_pg       db  0                       ; M:'s pages (0: off)
md_h        dw  0                       ;  in this handle
md_mode     db  0                       ; 1 set, 2 at start-up
md_mseg     dw  0                       ; its block
md_delta    dw  0                       ; md_res's move: its block's offset from
                                        ;  KSEG - md_res
md_env      dw  0                       ; the master environment
md_envp     dw  0                       ;  and its size before the split
md_keep     times 3 db 0                ; (a place hooked without a .t: none now)
md_ld       db  0                       ; INT 21h 0Eh's count before M:
md_dte      times DRVSZ db 0            ; M:'s drive table entry, made here

; the words in md_res that move with it (from md_res), each list ended
; by FFFFh: its own addresses (+), its near jumps to the kernel (-)
md_relp:
%assign i 0
%rep MD_NRP
        dw      ..@md_rp%[i] - 2 - md_res
%assign i i+1
%endrep
        dw      0FFFFh
md_relm:
%assign i 0
%rep MD_NRM
        dw      ..@md_rm%[i] - 2 - md_res
%assign i i+1
%endrep
        dw      0FFFFh
md_relh:                                ; (and in handle 0's record: + 4 * M:'s)
%assign i 0
%rep MD_NRH
        dw      ..@md_rh%[i] - 2 - md_res
%assign i i+1
%endrep
        dw      0FFFFh
md_tend:
MD_TLEN equ md_tend - md_tstart
[absolute 0]
        times MD_SCR - MD_TPG - MD_TLEN resb 1  ; (it fits before the scratch)
section mdt
; each place must have room for the jump: 3 bytes or more (whole
; instructions that don't jump, or KHD.INC's jump), and the stub must fit
; where `start' was
[absolute 0]
        times (use_drive.hk - use_drive) - 3 resb 1
        times (drv_present.hk - drv_present) - 3 resb 1
        times (cwd_of.hk - cwd_of) - 3 resb 1
        times 128 - (init.go + 2 - start) resb 1        ; (init's JMP SHORT reaches 0)

; =====================================================================
;  start-up (section boot, in the load image: CS = 1000h)
; =====================================================================
section boot
; INT 67h 5Bh, at KSEG:0012h (copied there by ems_init): AL = 'M': the
; installer, in window 0 for the time; anything else: A4h, as before
md_stub:
        cmp     al, 'M'
        jne     .no
        mov     dx, EMS_PORT
        in      al, dx
        push    ax
        mov     al, [ems_tcpg + 1]
        out     dx, al
        call    EMS_FRAME:md_entry
        pop     cx
        xchg    ax, cx
        out     dx, al
        xchg    ax, cx
        ret
.no:    mov     ah, 0A4h
        ret
md_stub_end:
[absolute 0]
        times (init - start - MD_STUB) - (md_stub_end - md_stub) resb 1
section boot

; init's last jump, through KSEG:0000 (CS = 1000h): MDISK= in \LODE.INI
; (KB, 0 off, ALL; no line or a bad value: 256), then M:, then the UI
md_boot:
        cli
        mov     ax, KSEG
        mov     ds, ax
        mov     ss, [ui_seg]            ; (run_ui's stack: nothing on it yet)
        mov     sp, ui_stack_top
        sti
        cld
        mov     es, ax                  ; KSEG:0000 as `start' left it (kept
        mov     si, MDB(md_s0)          ;  here: by now the UI's BSS is over
        xor     di, di                  ;  the load image's start)
        push    cs
        pop     ds
        movsw
        movsw
        movsb
        call    ini_read                ; (KROM.INC: LODE.INI's, both)
        mov     cx, 256
.line:  mov     di, MDB(s_mdeq)         ; "MDISK=" (any case)?
.c:     mov     al, [di]
        or      al, al
        jz      .hit
        mov     ah, [si]
        and     ax, 0DFDFh
        cmp     al, ah
        jne     .next
        inc     si
        inc     di
        jmp     .c
.hit:   mov     ax, [si]                ; "ALL"
        and     ax, 0DFDFh
        cmp     ax, 'AL'
        jne     .num
        mov     al, [si+2]
        and     al, 0DFh
        cmp     al, 'L'
        jne     .go
        mov     cx, 0FFFFh
        jmp     short .go
.num:   xor     bx, bx                  ; a number (no digit: 256)
        xor     dx, dx
.d:     lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .dn
        inc     dx
        cbw
        imul    bx, bx, 10
        add     bx, ax
        cmp     bx, 6000                ; (more than there can be: all)
        jb      .d
        mov     bx, 0FFFFh
.dn:    or      dx, dx
        jz      .go
        mov     cx, bx
        jmp     short .go
.next:  lodsb
        or      al, al
        jz      .go
        cmp     al, 10
        jne     .next
        jmp     .line
.go:    mov     ax, 5B4Dh               ; M:, keeping what it holds if it can
        mov     bl, 2
        int     67h
        jmp     KSEG:run_ui
md_s0   db      0, 0, 0, 0, 0               ; (ems_init: KSEG:0000's 5 bytes)
s_mdeq  db      'MDISK', 1Dh, 0         ; (as "MDISK=" AND 0DFh)

%endif
