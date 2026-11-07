; =====================================================================
;  KROM.INC - R:, Lodestone's ROM, and booting from it
;
;  The ROM is a 128 KB FAT12 volume in GRiD's own ROM format (built by
;  tools/mkrom.py: the kernel first, unused clusters marked bad, the
;  trailer in its last 256 bytes, ROM id 'LO').  The 1520's BIOS boots
;  the LAST bootable image it finds (GridBootRom counts down), copying
;  it to 8000:0000; ROMBOOT.ASM, its boot sector, copies LODE.SYS from
;  there to 1000:0000 and starts it with DL = R: (17).
;
;  R: is drive 17, read-only, whether Lodestone started from the ROM or
;  from a floppy.  Nothing is copied out of the ROM: R:'s sector routine
;  maps the image into A000-BFFF with the BIOS's own calls (INT 15h
;  E403/E404, as GRIDPROBE does on the 1520), copies a piece of at most
;  R_PIECE sectors with interrupts off (video memory is hidden while the
;  ROM is there, so nothing may draw), and maps it out again.  A
;  destination under the window itself goes through the kernel's bounce
;  buffer a sector at a time.  Writes fail (write-protected).  No EMS
;  is used, so R: is the same with or without it.
;
;  Resident (only when the ROM is there): the module below, placed after
;  whatever modules the start-up kept (EMS's, C:'s) and relocated there:
;  the BIOS's 5 paragraphs of ROM data (E401's), R:'s drive table entry
;  and current directory, and the hooks into use_drive, drv_present,
;  cwd_of and dio, as M:'s (KMDISK.INC), which chains after them; with
;  ROM 2, f_36's too (INT 21h 36h: R:'s answer, not walking the gap).
;
;  Booted from the ROM (in the load image, never kept):
;    - rom_menu, before anything else: with a Shift key held, a menu:
;      Lodestone, Lodestone with the ROM's own settings, GRiD MS-DOS (an
;      other bootable image in the sockets), or the floppy in A:;
;    - rs_boot, once INT 21h works (KSPLASH.INC's sp_boot calls it): the
;      current drive C: (or R: without the hard disk), PATH C:\LODE;R:\
;      (programs copied to C:\LODE are used before the ROM's), screen
;      captures on C: (capdrv; A: without it), and the drive of the
;      settings that go over the ROM's (setdrv: C:, else A: when it has a
;      LODE.INI).
;  Settings: INT 21h 3305h gives DL = the boot drive and DH = setdrv (0:
;  none).  Every reader reads both: the boot drive's LODE.INI (on R:, the
;  defaults burned in) and DH's (the changes).  ini_read (here, for the
;  start-up's readers, which take the first match) puts DH's first.
; =====================================================================
R_DRV   equ 17                          ; R:
R_ID    equ 4F4Ch                       ; the ROM's id in its trailer: 'LO'
R_SECS  equ 256                         ; 128 KB
R_PIECE equ 8                           ; sectors copied with interrupts off
R_PLEN  equ 5                           ; r_dio.lp's bytes, r_patch without ROM 2
R_WIN   equ 0A000h                      ; the BIOS's window
R_DATA  equ 4                           ; mkrom.py's layout: the root at 2-3,
R_ROOT  equ 2                           ;  32 entries; data (cluster 2) at 4;
R_NROOT equ 32                          ;  clusters 2-253 (253: the trailer's)
R_NCL   equ R_SECS - R_DATA + 2         ; (the highest cluster + 1: 254)
; ROM 2 (mkrom.py --data: id 'LJ', system type 2) joined to R:: one
; volume, its FAT 2 sectors (1: ROM 1's, 2: ROM 2's), its root ROM 1's 32
; entries then ROM 2's (3-6), then ROM 1's clusters 2-253, a gap (254-341,
; bad), ROM 2's as 342-593.  mkrom writes ROM 2 as that second half, so
; all but ROM 1's root (its empties made deleted, .fix) are plain copies.
; ROM 2 alone: R:'s FAT sector 1 is ROM 2's spare R2_P1, its root 5-6.
R_ID2   equ 4A4Ch                       ; 'LJ' (an 'L2' ROM 2, before O10: none)
R_OFF   equ 340                         ; ROM 2's cluster n is R:'s n + 340:
        times -((R_OFF + 2) * 3 / 2 < 512) db 0  ;  its entries all in sector 2
R2_ROOT equ 3
R2_DATA equ 7
R2_NCL  equ R_NCL + R_OFF               ; 594
R2_SECS equ R2_DATA - 2 + R2_NCL        ; 599
R_END1  equ R2_DATA + R_NCL - 2         ; 259: past ROM 1's clusters (the gap)
R2_P1   equ R_SECS - 2                  ; 254 (mkrom.py's P1_AT)
INI_BUF equ 0F000h                      ; ini_read: the settings, in the load
                                        ;  image's segment (KSPLASH's SP_BUF)

; ---------------------------------------------------------------------
;  the resident part: assembled from 0, moved to its place and relocated
;  there (r_relp: its own addresses, + the place; r_relm: its near jumps
;  to the kernel, - the place)
; ---------------------------------------------------------------------
%assign R_NRM 0
%macro RKJMP 1                          ; JMP NEAR to the kernel
        jmp     near %1
..@r_rm%[R_NRM]:
%assign R_NRM R_NRM+1
%endmacro
%assign R_NRP 0
%macro RADR 1+                          ; ends in an address in the module
        %1
..@r_rp%[R_NRP]:
%assign R_NRP R_NRP+1
%endmacro

section rmt
R_TBL   equ     80 + CWDLEN             ; (r_tbl and r_cwd: not in the file,
%if R_TBL != R_ZERO                     ;  the section starts past them:
%error "R_ZERO: R_TBL"                  ;  LODE.ASM's vstart; rom_init: zeros)
%endif
r_tstart equ    $ - R_TBL
r_tbl   equ     r_tstart                ; the BIOS's ROM data (E401): first,
                                        ;  so it starts on a paragraph
r_cwd   equ     r_tbl + 80              ; R:'s current directory ("\")
r_dt:   db      80h + R_DRV, 1, 1, 1    ; R:'s drive table entry (D_UNIT: fixed,
        dw      1, R_NROOT, R_SECS, 1   ;  no change line; D_SPT: no tracks),
        dw      255, 1, R_ROOT, R_NROOT / 16    ; ROM 1's alone (rom_init:
        dw      R_DATA, R_NCL, 0        ;  with ROM 2)
        db      0, 1
        dw      2
        db      0F8h, 0
%if $ - r_dt != DRVSZ
%error "r_dt: DRVSZ"
%endif
r_tseg  dw      0                       ; r_tbl's segment
r_img   db      0                       ; R:'s image (E402's ordinal)
r_img2  db      0FFh                    ; ROM 2's, joined to it (FFh: none)
r_cur   db      0                       ; the image a piece is read from

; use_drive: R:'s entry
r_use:  cmp     al, R_DRV
        jne     .t
        mov     [act], al
        RADR    mov si, r_dt
        mov     [actp], si
        ret
.t:     times use_drive.hk - use_drive db 90h
        RKJMP   use_drive.hk

; drv_present: R: is there (on to use_drive with CF clear)
r_pres: cmp     al, R_DRV
        jne     .t
        RKJMP   drv_present.hk
.t:     times drv_present.hk - drv_present db 90h
        RKJMP   drv_present.hk

; cwd_of: R:'s current directory
r_cwdh: cmp     al, R_DRV
        jne     .t
        RADR    mov di, r_cwd
        ret
.t:     times cwd_of.hk - cwd_of db 90h
        RKJMP   cwd_of.hk

; dio for R:: AH = 2 read (3, write: AX = 19, write-protected), DX =
; sector, CX = sectors, ES:BX = memory.  CF: AX = 27 past the ROM's end.
; A piece at a time: mapped, copied with interrupts off, mapped out.
r_dio:  cmp     al, R_DRV
        je      .r
.t:     times dio.hk - dio db 90h
        RKJMP   dio.hk
.r:     cmp     ah, 2
        je      .rd
        mov     ax, 19                  ; (no INT 24h: it's a ROM, retrying
        stc                             ;  won't help)
        ret
.rd:    pusha
        push    es
        push    ds
        mov     ax, dx
        add     ax, cx
        jc      .bad
        RADR    cmp ax, [r_dt + D_TOT]
        ja      .bad
        mov     ax, bx                  ; ES:BX with BX < 16
        shr     ax, 4
        mov     si, es
        add     ax, si
        mov     es, ax
        and     bx, 15
        mov     bp, dx                  ; BP = R:'s sector
.l:     jcxz    .ok
.lp:    call    .map                    ; -> DX = the image's, SI = how many
        jc      .bad                    ;  in a row there (without ROM 2, these
.lpe:                                   ;  5 bytes are r_patch: rom_init)
        times   -(.lpe - .lp != R_PLEN) db 0
        db      0C7h, 0C7h              ; MOV DI, R_PIECE: DI = sectors this
        dw      R_PIECE                 ;  time (4 bytes: what follows even)
        cmp     cx, di
        jae     .n0
        mov     di, cx
.n0:    cmp     si, di
        jae     .n
        mov     di, si
.n:     mov     ax, es                  ; under the window (A000-BFFF)?
        cmp     ax, R_WIN + 2000h
        jae     .dir
        mov     si, di
        shl     si, 5
        add     si, ax
        inc     si                      ; (BX may be up to 15 on)
        cmp     si, R_WIN
        jbe     .dir
        mov     di, 1                   ; then a sector at a time, through
        push    es                      ;  the kernel's bounce buffer
        push    bx
        push    cs
        pop     es
        mov     bx, bounce
        call    .piece
        pop     bx
        pop     es
        push    di
        push    cx
        mov     si, bounce
        mov     di, bx
        mov     cx, 256
        rep     movsw
        pop     cx
        pop     di
        jmp     short .nx
.dir:   call    .piece
.nx:    add     bp, di                  ; on: the sectors, the memory
        sub     cx, di
        shl     di, 5
        mov     ax, es
        add     ax, di
        mov     es, ax
        jmp     .l
.bad:   stc
        db      0B0h                    ; (MOV AL, imm8: over the CLC)
.ok:    clc
        mov     word [io_ra], 0         ; (read-ahead is per transfer)
        pop     ds
        pop     es
        popa
        jnc     .x
        mov     ax, 27                  ; sector not found
.x:     ret

; DI sectors from sector DX to ES:BX, the ROM mapped meanwhile and
; interrupts off (DS = KSEG; everything kept).  The 1520's BIOS (F000:
; D9D6 keeps SI and DI; E403 at DBC4 changes AX, BX, CL and DH, E404 at
; DBF5 AX): neither touches ES or DS
.piece: pushf
        pusha
        push    ds
        push    dx                      ; (the sector,
        push    di                      ;  the count,
        push    bx                      ;  the place)
        RADR    mov ax, [r_tseg]
        RADR    mov dl, [r_cur]         ; (the image .map or .made chose)
        cli
        mov     ds, ax
        mov     ax, 0E403h              ; the image into A000-BFFF
        int     15h
        mov     bp, ds                  ; (for E404)
        pop     di
        pop     cx                      ; sectors
        pop     ax
        shl     ax, 5
        add     ax, R_WIN
        mov     ds, ax
        xor     si, si
        xchg    cl, ch                  ; words
        rep     movsw
        mov     ds, bp
        mov     ax, 0E404h              ; and out again: video memory back
        int     15h
        pop     ds
        popa
        popf
        ret

; (from here on, only with ROM 2: without it the module ends here)
..@r_made:
        times   ($ - r_tstart) & 1 db 90h       ; (hot: .map even)
; R:'s sector BP -> DX = the image's sector, [r_cur] = the image, SI = how
; many go on in a row there.  CF: the gap (R:'s 259-342, clusters 254-337:
; bad, on no ROM; 343-346, clusters 338-341, read ROM 2's sectors 0-3).  Without ROM 2, .lp's
; call is r_patch instead
.map:   mov     dx, bp
        cmp     bp, R2_DATA
        jb      .lo
        sub     dx, R2_DATA - R_DATA    ; ROM 1's clusters, then ROM 2's
        RADR    mov al, [r_img]
        mov     si, R_END1
        cmp     bp, si
        jb      .m0
        sub     dx, R_OFF               ; (CF: below ROM 2's, the gap)
        RADR    mov al, [r_img2]
        jnc     .m1                     ; (SI = 259: more than ROM 2's sectors)
        ret
        times   ($ - r_tstart) & 1 db 90h       ; (hot: .m0, .m1 even)
.m0:    sub     si, bp
.m1:    RADR    mov [r_cur], al
        ret                             ; (CF clear)
; sectors 0-6: r_lo's image and sector, one at a time; 3-4, ROM 1's root,
; with its empty entries made deleted ones so that a search goes on to ROM
; 2's (.fix)
.lo:    mov     si, bp
        shl     si, 1
        RADR    mov ax, [si + r_lo]
        mov     dl, ah                  ; (DH 0: BP < 7)
        RADR    mov [r_cur], al
        mov     si, 1
        lea     ax, [bp - R2_ROOT]
        cmp     ax, 2
        jb      .fx
        ret                             ; (CF clear)
.fx:    pop     ax                      ; (not back to .lp)
        mov     ax, es                  ; one sector into memory below the
        cmp     ax, R_WIN - 20h         ;  window (the kernel's buffers)
        jae     .bad
        mov     di, 1
        call    .piece
        push    cx
        mov     si, bx
        mov     cx, 16
.e:     cmp     byte [es:si], 0         ; empty -> deleted
        jne     .en
        mov     byte [es:si], 0E5h
.en:    add     si, 32
        loop    .e
        pop     cx
        jmp     .nx

; f_36 (INT 21h 36h, only with ROM 2): R:'s answer without walking its FAT:
; nothing free, and the clusters the ROMs have (r_tot: the gap left out)
        times   ($ - r_tstart) & 1 db 90h       ; (r_f36 even)
r_f36:  mov     al, [bp+F_DX]
        or      al, al
        jnz     .d
        mov     al, [cur_drv]
        inc     al
.d:     cmp     al, R_DRV + 1
        je      .r
.t:     times f_36.hk - f_36 db 90h
        RKJMP   f_36.hk
.r:     xor     ax, ax
        mov     [bp+F_BX], ax           ; 0 free
        inc     ax
        mov     [bp+F_AX], ax           ; a sector a cluster, of 512 bytes
        mov     word [bp+F_CX], 512
        RADR    mov ax, [r_tot]
        mov     [bp+F_DX], ax
        RKJMP   done
r_tot   dw      0                       ; (rom_init: 504, ROM 2 alone 252)
r_lo:   times 7 dw 0                    ; R:'s sectors 0-6: the image, its sector
                                        ;  (rom_init)
r_tend:
R_TLEN  equ r_tend - r_tstart
R_TLEN1 equ ..@r_made - r_tstart          ; (without ROM 2: .map not kept)
        times   -(R_TLEN > 39 * 16) db 0        ; (39 paragraphs, 29 alone: one
        times   -(R_TLEN1 > 29 * 16) db 0       ;  byte more costs DOS programs
                                                ;  one more)
        times   -(((r_dio.n0 - r_tstart) | (r_dio.n - r_tstart) | (r_dio.dir - r_tstart) \
                | (r_dio.piece - r_tstart)) & 1) db 0   ; (hot, even: the module
                                                ;  goes on a paragraph)

; the words that move with it (from r_tstart), each list ended by FFFFh
r_relp:
%assign i 0
%rep R_NRP
        dw      ..@r_rp%[i] - 2 - r_tstart
%assign i i+1
%endrep
        dw      0FFFFh
r_relm:
%assign i 0
%rep R_NRM
        dw      ..@r_rm%[i] - 2 - r_tstart
%assign i i+1
%endrep
        dw      0FFFFh
; the places hooked: the kernel's place, its .hk, the hook, its .t
r_hooks:
        dw      use_drive, use_drive.hk, r_use, r_use.t
        dw      drv_present, drv_present.hk, r_pres, r_pres.t
        dw      cwd_of, cwd_of.hk, r_cwdh, r_cwdh.t
        dw      dio, dio.hk, r_dio, r_dio.t
        dw      0
r_hooks2:                               ; (only with ROM 2)
        dw      f_36, f_36.hk, r_f36, r_f36.t
        dw      0
%define RTB(x) (section.rmt.start + ((x) - section.rmt.vstart))   ; (in the load image)

; =====================================================================
;  start-up, in the load image (CS = 1000h)
; =====================================================================
section boot

; hd_init's last jump (DS = ES = KSEG): is Lodestone's ROM in a socket?
; Then the module goes after what is kept so far ([kern_top]), and R: is
; hooked in.  On to KSPLASH.INC either way.
rom_init:
        cld
        push    ds                      ; (hd_init may leave ES elsewhere)
        pop     es
        mov     ax, [kern_top]          ; (the end + 15: on a paragraph)
        and     al, 0F0h
        mov     [cs:MDB(r_place)], ax
        mov     di, ax                  ; the module there (its BIOS data
        xor     ax, ax                  ;  must be where it stays)
        mov     cx, R_TBL / 2
        rep     stosw
        mov     byte [di - CWDLEN], '\'
        mov     si, RTB(r_tstart + R_TBL)
        mov     cx, R_TLEN - R_TBL
        push    ds
        push    cs
        pop     ds
        rep     movsb
        pop     ds
        mov     bx, [cs:MDB(r_place)]
        shr     bx, 4
        add     bx, KSEG
        mov     [cs:MDB(r_seg)], bx
        mov     ax, 0E400h              ; the BIOS's ROM calls: there?  (no
        int     15h                     ;  more than 5 paragraphs of data)
        jc      .no
        or      ah, ah
        jnz     .no
        cmp     bx, 5
        ja      .no
        push    ds
        mov     ds, [cs:MDB(r_seg)]
        mov     ax, 0E401h              ; the images
        int     15h
        pop     ds
        jc      .no
        or      al, al
        jz      .no
        mov     [cs:MDB(r_cnt)], al
        mov     cx, R_ID                ; ROM 1 (system type 1)
        mov     ah, 1
        call    r_find
        mov     [cs:MDB(r_i1)], al
        mov     cx, R_ID2               ; ROM 2, a data ROM (type 2)
        mov     ah, 2
        call    r_find                  ; AL = ROM 2's image (FFh: none)
        mov     ah, [cs:MDB(r_i1)]      ; AH = R:'s: ROM 1's, else ROM 2's
        cmp     ah, 0FFh                ;  alone (then both: R:'s the same
        jne     .got                    ;  volume, its FAT sector 1 R2_P1)
        cmp     al, 0FFh
        je      .no
        mov     ah, al
.got:   mov     di, [cs:MDB(r_place)]   ; its data
        mov     [di + r_img - r_tstart], ah
        mov     [di + r_img2 - r_tstart], al
        mov     [di + r_cur - r_tstart], ah     ; (without ROM 2, for good)
        mov     ax, [cs:MDB(r_seg)]
        mov     [di + r_tseg - r_tstart], ax
        lea     bx, [di + r_dt - r_tstart]
        cmp     byte [di + r_img2 - r_tstart], 0FFh
        jne     .two
        push    di                      ; no ROM 2: r_dio.lp's call of .map
        add     di, r_dio.lp - r_tstart ;  (not kept) becomes r_patch
        mov     si, MDB(r_patch)
        mov     cx, R_PLEN
        push    ds
        pop     es                      ; (r_find's E402 left ES A000h)
        push    cs
        pop     ds
        rep     movsb
        push    es
        pop     ds
        pop     di
        jmp     short .one
.two:   mov     word [bx + D_TOT], R2_SECS      ; ROM 2 joined: the volume
        mov     byte [bx + D_SPF], 2            ;  r_dio makes of the two
        mov     byte [bx + D_ROOT], R2_ROOT
        mov     byte [bx + D_NROOT], 2 * R_NROOT
        mov     byte [bx + D_RSEC], 2 * R_NROOT / 16
        mov     byte [bx + D_DATA], R2_DATA
        mov     word [bx + D_NCL], R2_NCL
        push    ds
        pop     es                      ; (r_find's E402 left ES A000h)
        push    di                      ; r_lo: R:'s sectors 0-6
        mov     bx, [di + r_img - r_tstart]     ; (BL R:'s image, BH ROM 2's)
        add     di, r_lo - r_tstart
        mov     si, MDB(r_losec)
        mov     dx, R_LO2
        mov     cx, 7
.lf:    mov     ah, [cs:si]
        inc     si
        mov     al, bl
        shr     dx, 1
        jnc     .lw
        mov     al, bh
.lw:    stosw
        loop    .lf
        pop     di
        mov     word [di + r_tot - r_tstart], 2 * (R_NCL - 2)   ; (36h's total)
        cmp     byte [cs:MDB(r_i1)], 0FFh
        jne     .one
        mov     word [di + r_tot - r_tstart], R_NCL - 2
        mov     byte [di + r_lo - r_tstart + 3], R2_P1  ; ROM 2 alone: R:'s
        lea     bx, [di + r_dt - r_tstart]      ;  FAT sector 1 its spare, its
        mov     byte [bx + D_ROOT], R2_ROOT + 2 ;  root ROM 2's half alone
        mov     byte [bx + D_NROOT], R_NROOT
        mov     byte [bx + D_RSEC], R_NROOT / 16
.one:
        mov     si, RTB(r_relp)         ; its own addresses: + its place
.rp:    mov     bx, [cs:si]
        cmp     bx, 0FFFFh
        je      .rm
        add     bx, di
        add     [bx], di
        inc     si
        inc     si
        jmp     .rp
.rm:    mov     si, RTB(r_relm)         ; its jumps to the kernel: - its place
.rm2:   mov     bx, [cs:si]
        cmp     bx, 0FFFFh
        je      .hk
        add     bx, di
        sub     [bx], di
        inc     si
        inc     si
        jmp     .rm2
.hk:    mov     si, RTB(r_hooks)        ; hooked: each place's first bytes
.h:     mov     di, [cs:si]             ;  to its .t (a jump there, C:'s,
        or      di, di                  ;  made relative to its new place),
        jz      .hd                     ;  and a jump to the hook at the place
        mov     bx, [cs:si+6]
        add     bx, [cs:MDB(r_place)]
        mov     cx, [cs:si+2]
        sub     cx, di
        push    di
        push    bx
.cp:    mov     al, [di]
        mov     [bx], al
        inc     di
        inc     bx
        loop    .cp
        pop     bx
        pop     di
        cmp     byte [bx], 0E9h
        jne     .j
        mov     ax, di
        sub     ax, bx
        add     [bx+1], ax
.j:     mov     byte [di], 0E9h         ; JMP NEAR the hook
        mov     ax, [cs:si+4]
        add     ax, [cs:MDB(r_place)]
        sub     ax, di
        sub     ax, 3
        mov     [di+1], ax
        add     si, 8
        jmp     .h
.hd:    cmp     si, RTB(r_hooks2)       ; then, with ROM 2, r_hooks2 (f_36)
        jae     .hn
        mov     di, [cs:MDB(r_place)]
        cmp     byte [di + r_img2 - r_tstart], 0FFh
        je      .hn
        mov     si, RTB(r_hooks2)
        jmp     .h
.hn:    mov     byte [lastdrv], R_DRV + 1       ; INT 21h 0Eh: to R:
        mov     ax, [cs:MDB(r_place)]   ; the arena above it
        mov     di, ax
        mov     cx, R_TLEN + 15
        cmp     byte [di + r_img2 - r_tstart], 0FFh
        jne     .kt
        mov     cx, R_TLEN1 + 15            ; (no ROM 2: what joins it not kept)
.kt:    add     ax, cx
        mov     [kern_top], ax
.no:    jmp     sp_hook                 ; (KSPLASH.INC: then KSEG:init)

; CX = an id, AH = a system type -> AL = the first image with both whose
; boot sector is Lodestone's (rom_check), FFh if none
r_find: mov     byte [cs:MDB(r_imgi)], 0
.l:     mov     al, [cs:MDB(r_imgi)]
        cmp     al, [cs:MDB(r_cnt)]
        jae     .none
        push    ax
        push    cx
        mov     dl, al
        push    ds
        mov     ds, [cs:MDB(r_seg)]
        mov     ax, 0E402h              ; BX = its id, DH = its system type
        int     15h
        pop     ds
        pop     cx
        pop     ax
        jc      .n
        cmp     bx, cx
        jne     .n
        cmp     dh, ah
        jne     .n
        push    ax
        push    cx
        call    rom_check               ; really ours?
        pop     cx
        pop     ax
        jnc     .y
.n:     inc     byte [cs:MDB(r_imgi)]
        jmp     .l
.y:     mov     al, [cs:MDB(r_imgi)]
        ret
.none:  mov     al, 0FFh
        ret

; Is image [r_imgi] Lodestone's ROM?  Its boot sector says "LODE ROM" and
; has the layout R: assumes.  CF if not.  (Interrupts off while it is in.)
rom_check:
        push    ds
        push    es
        mov     ds, [cs:MDB(r_seg)]
        mov     dl, [cs:MDB(r_imgi)]
        cli
        mov     ax, 0E403h
        int     15h
        mov     ax, R_WIN
        mov     es, ax
        mov     si, MDB(r_sig)
        xor     di, di
        mov     cx, r_sige - r_sig
        push    ds
        push    cs
        pop     ds
        repe    cmpsb
        pop     ds
        pushf
        mov     ax, 0E404h
        int     15h
        popf
        sti
        pop     es
        pop     ds
        je      .y
        stc
        ret
.y:     clc
        ret

r_place dw      0                       ; the module's offset in KSEG
r_seg   dw      0                       ; its BIOS data's segment
r_imgi  db      0
r_cnt   db      0
r_i1    db      0                       ; ROM 1's image (FFh: none)
r_noov  db      0                       ; 1: the ROM's settings only (the menu)
r_losec db      0, 1, 1, 2, 3, 2, 3     ; R:'s sectors 0-6: the image's sector,
R_LO2   equ     01100100b               ;  ROM 2's for 2, 5 and 6, else ROM 1's
; r_dio.lp without ROM 2: .map's answer, DX = R:'s sector, SI = no end to
; the run (r_cur is R:'s image)
r_patch:
        mov     dx, bp
        mov     si, 0FFFFh
        times   -($ - r_patch != R_PLEN) db 0
; the boot sector's start as mkrom.py makes it: jump, "LODE ROM", 512
; bytes a sector, 1 a cluster, 1 reserved, 1 FAT, 32 root entries, 256
; sectors, F8h, 1 sector a FAT
r_sig   db      0EBh, 3Ch, 90h, 'LODE ROM'
        dw      512
        db      1
        dw      1
        db      1
        dw      R_NROOT, R_SECS
        db      0F8h
        dw      1
r_sige:

; ---------------------------------------------------------------------
;  rom_menu: `start' jumps here (DS = 1000h, ES = KSEG, the boot stack);
;  then on to KEMS.INC's ems_init.  Booted from the ROM with a Shift key
;  held: the menu.  Nothing has been hooked yet, so GRiD MS-DOS and the
;  floppy can still be started as the BIOS would.
; ---------------------------------------------------------------------
rom_menu:
        cmp     byte [cs:bootdrv], R_DRV
        jne     .go
        push    es
        push    0
        pop     es
        test    byte [es:417h], 03h     ; a Shift key held?
        pop     es
        jz      .go
        pusha
        push    ds
        push    es
        push    cs
        pop     ds
        call    rm_dosimg               ; another bootable image: GRiD MS-DOS?
        mov     [MDB(rm_dos)], al
.show:  mov     si, MDB(s_rm1)
        call    rm_puts
        cmp     byte [MDB(rm_dos)], 0FFh
        je      .nd
        mov     si, MDB(s_rm3)
        call    rm_puts
.nd:    mov     si, MDB(s_rm4)
        call    rm_puts
.key:   xor     ah, ah
        int     16h
        cmp     al, 13
        je      .one
        cmp     al, '1'
        je      .one
        cmp     al, '2'
        je      .two
        cmp     al, '4'
        je      .flop
        cmp     al, '3'
        jne     .key
        cmp     byte [MDB(rm_dos)], 0FFh
        je      .key
        jmp     rm_bootdos
.flop:  call    rm_floppy               ; (back only if it can't)
        mov     si, MDB(s_rmnof)
        call    rm_puts
        jmp     .show
.two:   mov     byte [MDB(r_noov)], 1
.one:   mov     si, MDB(s_rmcr)
        call    rm_puts
        pop     es
        pop     ds
        popa
.go:    jmp     ems_init

rm_puts:
        lodsb
        or      al, al
        jz      .x
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     rm_puts
.x:     ret

; -> AL = the ordinal of a bootable image (system type 1) that isn't ours,
; else FFh.  The BIOS's ROM data at RM_SEG.
RM_SEG  equ     4000h                   ; (free: past the load image and its stack)
rm_dosimg:
        push    ds
        mov     ax, RM_SEG
        mov     ds, ax
        mov     ax, 0E401h
        int     15h
        jc      .none
        mov     cl, al
        xor     dl, dl
.l:     cmp     dl, cl
        jae     .none
        push    cx
        push    dx
        mov     ax, 0E402h
        int     15h
        mov     ax, dx                  ; (AH: its system type)
        pop     dx
        pop     cx
        jc      .none
        cmp     ah, 1
        jne     .n
        cmp     bx, R_ID
        je      .n
        push    es                      ; bootable, as the BIOS checks it: its
        push    cx                      ;  trailer's BB66h and 80h (GRiD's
        push    dx                      ;  application ROMs are system type 1
        cli                             ;  too, without a boot sector); E403
        mov     ax, 0E403h              ;  leaves CL 0 (and BX, DH changed)
        int     15h
        mov     ax, R_WIN + 1FF0h
        mov     es, ax
        cmp     word [es:0], 0BB66h
        jne     .nb
        cmp     byte [es:3], 80h
.nb:    pushf
        mov     ax, 0E404h
        int     15h
        popf
        sti
        pop     dx
        pop     cx
        pop     es
        je      .y
.n:     inc     dl
        jmp     .l
.y:     mov     al, dl
        pop     ds
        ret
.none:  mov     al, 0FFh
        pop     ds
        ret

; GRiD MS-DOS (image [rm_dos]): what the BIOS does, from here: the image
; copied to 8000:0000, then its boot sector with DL = 'r'
rm_bootdos:
        mov     dl, [MDB(rm_dos)]
        mov     ax, RM_SEG
        mov     ds, ax
        cli
        mov     ax, 0E403h
        int     15h
        mov     ax, R_WIN
        mov     ds, ax
        mov     ax, 8000h
        mov     es, ax
        xor     si, si
        xor     di, di
        mov     cx, 8000h
        rep     movsw
        mov     ax, R_WIN + 1000h
        mov     ds, ax
        mov     ax, 9000h
        mov     es, ax
        xor     si, si
        xor     di, di
        mov     cx, 8000h
        rep     movsw
        mov     ax, 9FF0h               ; its trailer, in the copy: bootSeg
        mov     es, ax
        mov     bx, [es:4]
        cmp     bx, 8000h
        jae     .s
        add     bx, 8000h
.s:     mov     ax, RM_SEG
        mov     ds, ax
        mov     ax, 0E404h
        int     15h
        push    bx
        push    0
        mov     dl, 'r'
        sti
        retf

; the floppy in A:: its boot sector to 0:7C00 and on to it, as INT 19h
; would.  Back (CF) if there is no disk or no boot sector.
rm_floppy:
        mov     di, 3
.t:     xor     ax, ax
        xor     dx, dx
        int     13h
        mov     ax, 0201h
        mov     cx, 1
        xor     dx, dx
        push    0
        pop     es
        mov     bx, 7C00h
        int     13h
        jnc     .rd
        dec     di
        jnz     .t
        stc
        ret
.rd:    cmp     word [es:7DFEh], 0AA55h
        jne     .no
        xor     dx, dx
        push    0
        push    7C00h
        retf
.no:    stc
        ret

rm_dos  db      0FFh
s_rm1   db      13, 10, 'Lodestone, from the ROM', 13, 10, 10
        db      '  1  Lodestone', 13, 10
        db      "  2  Lodestone with the ROM's own settings", 13, 10, 0
s_rm3   db      '  3  GRiD MS-DOS', 13, 10, 0
s_rm4   db      '  4  The floppy in A:', 13, 10, 10, 'Choose: ', 0
s_rmnof db      13, 10, 'No disk to start from in A:', 13, 10, 0
s_rmcr  db      13, 10, 0

; ---------------------------------------------------------------------
;  rs_boot: KSPLASH.INC's sp_boot calls it first, once INT 21h works
;  (DS = CS = 1000h, ES = KSEG).  Booted from the ROM: the current drive,
;  the settings' drive and the master environment's PATH.
; ---------------------------------------------------------------------
rs_boot:
        mov     al, [es:bootdrv]        ; from a floppy: captures on it (A:, or
        cmp     al, 2                   ;  B: from the external drive)
        jae     .r
        add     al, 'A'
        mov     [es:capdrv], al
.r:     cmp     byte [es:bootdrv], R_DRV
        jne     .x
        mov     dl, R_DRV               ; the current drive: C:, else R:
        cmp     byte [es:drvtab + 2 * DRVSZ + D_PRES], 0
        je      .cd
        mov     dl, 2
.cd:    mov     ah, 0Eh
        int     21h
        xor     al, al                  ; the settings over the ROM's: none
        cmp     [MDB(r_noov)], al       ;  (the menu's 2), else C:'s, else
        jne     .sd                     ;  A:'s if it has a LODE.INI
        mov     al, 3
        cmp     dl, 2
        je      .sd
        call    rs_aini
.sd:    mov     [es:setdrv], al
        cmp     dl, 2                   ; with C:: PATH=C:\LODE;R:\, and
        jne     .x                      ;  screen captures there
        mov     byte [es:capdrv], 'C'
        push    es
        mov     es, [es:ex_env]
        xor     di, di
        mov     si, MDB(s_rsenv)
        mov     cx, s_rsenve - s_rsenv
        rep     movsb
        pop     es
.x:     ret

; -> AL = 1 if A:\LODE.INI is there, else 0.  No disk in A: is no error
; here: INT 24h fails anything meanwhile.
rs_aini:
        push    es
        push    dx
        mov     ax, 3524h
        int     21h
        push    es
        push    bx
        mov     dx, MDB(rs_i24)
        mov     ax, 2524h
        int     21h
        mov     dx, MDB(s_aini)
        mov     ax, 4300h
        int     21h
        mov     al, 0
        jc      .r
        inc     ax
.r:     pop     dx
        pop     ds
        push    ax
        mov     ax, 2524h
        int     21h
        pop     ax
        push    cs
        pop     ds
        pop     dx
        pop     es
        ret
rs_i24: mov     al, 3                   ; fail
        iret

s_aini  db      'A:\LODE.INI', 0
s_rsenv db      'COMSPEC=R:\LCMD.COM', 0, 'PATH=C:\LODE;R:\', 0, 'PROMPT=$P$G', 0, 0
s_rsenve:

; ---------------------------------------------------------------------
;  ini_read: the settings for the start-up's readers (KSPLASH.INC's,
;  KMDISK.INC's), which take the first match: DH's LODE.INI (the changes)
;  first, then the boot drive's (on R:, the ROM's own).  DS = CS = 1000h.
;  -> SI = INI_BUF, the text, ended by a NUL.  Read from the disks once a
;  start-up (rs_boot has chosen DH by then): the readers after the first
;  get the same text (nothing writes INI_BUF meanwhile; LODE.PIC runs at
;  PIC_SEG, past it).
; ---------------------------------------------------------------------
ini_read:
        mov     si, INI_BUF
        cmp     byte [MDB(ini_got)], 0
        jne     .r
        mov     byte [MDB(ini_got)], 1
        push    es
        push    cs
        pop     es
        mov     ax, 3305h
        int     21h
        mov     di, INI_BUF
        push    dx
        mov     al, dh
        call    .one
        mov     [MDB(ini_mid)], di      ; (where the boot drive's starts)
        pop     dx
        mov     al, dl
        call    .one
        mov     byte [di], 0
        mov     si, INI_BUF
        pop     es
        ret
.one:   or      al, al
        jz      .r
        cmp     di, INI_BUF + 4000      ; (room left for another file?)
        jae     .r
        add     al, 'A' - 1
        mov     [MDB(s_rini)], al
        mov     dx, MDB(s_rini)
        mov     ax, 3D00h
        int     21h
        jc      .r
        mov     bx, ax
        mov     dx, di
        mov     cx, INI_BUF + 4094
        sub     cx, di
        mov     ah, 3Fh
        int     21h
        jc      .c
        add     di, ax
        mov     al, 10
        stosb
.c:     mov     ah, 3Eh
        int     21h
.r:     ret
s_rini   db      '@:\LODE.INI', 0
ini_got  db      0                      ; (read this start-up)
ini_mid  dw      INI_BUF                ; (DH's text ends here: te_boot)

; SI = LODE.INI's text (ASCIIZ), DI = a key as "NAME", 1Dh, 0 (that is,
; "NAME=" AND 0DFh, any case) -> SI = its value on the first line that has
; it; CF if none.  (AX, BX, DI change; CX is kept.)  The start-up's readers
; all use it: KSPLASH.INC's SPLASH= and PRINTER=, KMDISK.INC's MDISK= and
; MULTITASK=.
ini_key:
        mov     bx, di
.line:  mov     di, bx
.c:     mov     al, [di]
        or      al, al
        jz      .x                      ; (CF clear)
        mov     ah, [si]
        and     ax, 0DFDFh
        cmp     al, ah
        jne     .next
        inc     si
        inc     di
        jmp     .c
.next:  lodsb
        or      al, al
        jz      .no
        cmp     al, 10
        jne     .next
        jmp     .line
.no:    stc
.x:     ret
