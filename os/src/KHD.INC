; =====================================================================
;  KHD.INC - the internal hard disk as drive C:.  An AT-bus (IDE) drive
;  at 1F0h-1F7h, driven through its own registers: the 1520's BIOS only
;  turns on the few Conner models it knows (HDPROBE), and leaves INT 13h
;  without anything else.  C: is the first FAT16 partition (type 04h,
;  06h or 0Eh) in its partition table.
;
;  Only resident when there is one: hd_init (section boot, in the load
;  image, after ems_init) looks for the drive, the partition and its
;  boot sector, and only then keeps this module (after EMS's, or where
;  EMS would be) and hooks the kernel.  The places marked "KHD.INC" in
;  KDISK.INC and KFAT.INC then start with a jump here; for the floppies
;  each goes on with its own first instructions (copied into the .t
;  after each hook) and back.  Without the drive none of it costs a byte.
;
;  Sector numbers: 32 bits (the 1520's spare CP30104H has 237,393 in
;  its partition).  The kernel's are 16; the high part rides in [lba_hi]
;  and in a sector buffer's "drive" byte (drive + 4 * the high part), and
;  it comes together here.  Transfers: CHS by IDENTIFY's geometry (drives
;  of the 1520's age have no LBA), up to 127 sectors a command, polled
;  (REP INSW/OUTSW), each command tried twice, then INT 24h as for the
;  floppies.  The FAT: HD_NWIN sectors of it at a time (the window), written
;  to every copy when the kernel flushes its FAT (close, delete, ...) or
;  when a slot is needed.  The free clusters are counted once (INT 21h
;  36h) and kept up to date after that.
; =====================================================================
HD_PORT equ 1F0h
HD_NWIN    equ 3                           ; FAT sectors held at a time
HD_SPT  equ 255                         ; the kernel's "track" for C: (write runs)
C_DT    equ drvtab + 2 * DRVSZ          ; C:'s drive table entry

; ---------------------------------------------------------------------
;  transfers
; ---------------------------------------------------------------------
; dio for C:: AL = 2, or a buffer's key (2 + 4 * the high part); AH = 2
; read / 3 write, DX (+ [lba_hi]) = sector, CX = sectors, ES:BX.  CF: AX
hd_dio: test    al, 2
        jnz     .hd
.t:     times dio.hk - dio db 90h
        jmp     dio.hk
.hd:    push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    es
        push    ax
        shr     al, 2
        or      al, [lba_hi]
        xor     ah, ah
        mov     di, ax                  ; DI:DX = the sector
        mov     word [lba_hi], 0
        pop     ax
        call    hd_io
        mov     word [io_ra], 0         ; (read-ahead: the floppies')
        pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        ret

; AH = 2 read / 3 write, DI:DX = sector of the partition, CX = sectors,
; ES:BX = memory; INT 24h if [io_crit] when it fails.  CF: AX = DOS error
hd_io:  mov     [io_op], ah
        mov     byte [io_drv], 2
        mov     byte [io_ign], 0
.again: push    dx
        mov     ax, dx
        mov     dx, di
        call    hd_rw
        pop     dx
        jnc     .ok
        mov     [io_bios], al
        cmp     byte [io_crit], 0
        je      .f
        call    crit_disk               ; AL: 0 ignore, 1 retry, 3 fail
        cmp     al, 1
        je      .again
        or      al, al
        jnz     .f
        mov     byte [io_ign], 1
.ok:    clc
        ret
.f:     mov     al, [io_bios]
        call    bios2dos
        stc
        ret

; DX:AX = sector of the partition, CX = sectors, ES:BX = memory, [io_op].
; CF: AL = the error as a BIOS status (10h data, 04h not found, 40h seek,
; 80h no answer, 0Ch other).  Keeps all but AX
hd_rw:  pusha
        push    es
        add     ax, [hd_plba]
        adc     dx, [hd_plba+2]
        mov     si, ax                  ; DX:SI = the drive's sector
        mov     ax, bx                  ; ES:BX with BX < 16
        shr     ax, 4
        mov     di, es
        add     ax, di
        mov     es, ax
        and     bx, 15
.cmd:   jcxz    .ok
        mov     di, 127                 ; (127 sectors from BX < 16: in 64 KB)
        cmp     cx, di
        jae     .n
        mov     di, cx
.n:     mov     byte [hd_try], 2
.try:   call    hd_cmd
        jnc     .done
        dec     byte [hd_try]
        jnz     .try
        mov     [hd_err], al
        pop     es
        popa
        mov     al, [hd_err]
        stc
        ret
.done:  add     si, di
        adc     dx, 0
        sub     cx, di
        mov     ax, di
        shl     ax, 5
        mov     bp, es
        add     bp, ax
        mov     es, bp
        jmp     .cmd
.ok:    pop     es
        popa
        clc
        ret

; one READ SECTORS (20h) or WRITE SECTORS (30h): DI sectors (1-127) from
; the drive's sector DX:SI, ES:BX (BX < 16).  CF: AL as hd_rw.  Keeps
; all but AX
hd_cmd: pusha
        cld
        mov     ax, si
        div     word [hd_hs]            ; AX = cylinder, DX = the rest
        xchg    ax, dx
        div     byte [hd_spt]           ; AL = head, AH = sector - 1
        inc     ah
        mov     cx, ax
        mov     ah, 0                   ; (not busy is enough)
        call    hd_wait
        jc      .x
        push    dx                      ; (the cylinder)
        mov     dx, HD_PORT + 2
        mov     ax, di
        out     dx, al                  ; sectors
        inc     dx
        mov     al, ch
        out     dx, al                  ; the first one's number
        inc     dx
        pop     ax
        out     dx, al                  ; cylinder
        inc     dx
        mov     al, ah
        out     dx, al
        inc     dx
        mov     al, cl
        or      al, 0A0h
        out     dx, al                  ; drive 0, head
        inc     dx
        mov     al, 20h
        cmp     byte [io_op], 3
        jne     .c
        mov     al, 30h
.c:     out     dx, al
        mov     cx, di
.s:     mov     ah, 09h                 ; DRQ, or ERR
        call    hd_wait
        jc      .x
        test    al, 01h
        jnz     .e
        push    cx
        mov     cx, 256
        mov     dx, HD_PORT
        cmp     byte [io_op], 3
        je      .w
        mov     di, bx
        rep     insw
        jmp     short .nx
.w:     push    ds
        mov     si, bx
        push    es
        pop     ds
        rep     outsw
        pop     ds
.nx:    pop     cx
        add     bx, 512
        loop    .s
        cmp     byte [io_op], 3
        jne     .ok
        mov     ah, 0                   ; a write: until the drive has it
        call    hd_wait
        jc      .x
        test    al, 21h                 ; ERR, write fault
        jnz     .e
.ok:    popa
        clc
        ret
.e:     test    al, 01h                 ; the error register says what
        mov     ah, 0Ch
        jz      .m
        mov     dx, HD_PORT + 1
        in      al, dx
        mov     ah, 10h                 ; UNC, BBK: data
        test    al, 0C0h
        jnz     .m
        mov     ah, 04h                 ; IDNF, AMNF: sector not found
        test    al, 11h
        jnz     .m
        mov     ah, 40h                 ; TK0: seek
        test    al, 02h
        jnz     .m
        mov     ah, 0Ch
.m:     mov     al, ah
.x:     mov     [hd_err], al
        popa
        mov     al, [hd_err]
        stc
        ret

; until the drive isn't busy and shows one of the status bits AH (0: just
; not busy), 5 s at most.  -> AL = status.  CF: no (AL = 80h)
hd_wait:
        push    cx
        push    dx
        push    ds
        mov     dx, HD_PORT + 7
        xor     cx, cx
        mov     ds, cx
        mov     cx, [46Ch]              ; (the BIOS's tick count)
.l:     in      al, dx
        test    al, 80h
        jnz     .w
        or      ah, ah
        jz      .x                      ; (CF clear)
        test    al, ah
        jnz     .x
.w:     push    ax
        mov     ax, [46Ch]
        sub     ax, cx
        cmp     ax, 5 * 18
        pop     ax
        jb      .l
        mov     al, 80h
        stc
.x:     pop     ds
        pop     dx
        pop     cx
        ret

; ---------------------------------------------------------------------
;  the FAT window
; ---------------------------------------------------------------------
; AX = sector of the FAT -> SI = it in the window, CL = its slot's bit.
; CL = 0: not to be had (it can't be read, or the slot it needs holds
; changes that can't be written): SI is a sector of FFFFh ("ends": no
; cluster is taken or followed there), and what is written into it goes
; nowhere.  Keeps all else
hd_wget:
        push    bx
        push    dx
        xor     bx, bx
.f:     cmp     [hd_wsec+bx], ax
        je      .hit
        inc     bx
        inc     bx
        cmp     bx, HD_NWIN * 2
        jb      .f
        xor     bx, bx                  ; not there: the slot used longest ago
        mov     si, 2
.o:     mov     dx, [hd_wage+si]
        cmp     dx, [hd_wage+bx]
        jae     .on
        mov     bx, si
.on:    inc     si
        inc     si
        cmp     si, HD_NWIN * 2
        jb      .o
        call    hd_wout                 ; written back first if it changed
        jc      .none                   ;  (it can't be: it stays as it is)
        mov     word [hd_wsec+bx], 0FFFFh   ; (nothing in it until it is read)
        push    ax
        mov     cl, 2
        call    hd_wio
        pop     ax
        jc      .none
        cmp     byte [io_ign], 0        ; (INT 24h said Ignore: not good)
        jne     .none
        mov     [hd_wsec+bx], ax
.hit:   inc     word [hd_clock]
        mov     dx, [hd_clock]
        mov     [hd_wage+bx], dx
        call    hd_slot
        pop     dx
        pop     bx
        ret
.none:  push    ax
        push    di
        push    es
        push    ds
        pop     es
        mov     di, bounce              ; (scratch: the floppies' bounce sector)
        mov     si, di
        mov     cx, 256
        mov     ax, 0FFFFh
        rep     stosw
        pop     es
        pop     di
        pop     ax
        xor     cl, cl
        mov     byte [hd_bad], 1
        pop     dx
        pop     bx
        ret

; slot BX (times 2) -> SI = its memory, CL = its bit
hd_slot:
        mov     si, bx
        shl     si, 8
        add     si, [hd_win]
        push    ax
        mov     cl, bl
        shr     cl, 1
        mov     al, 1
        shl     al, cl
        mov     cl, al
        pop     ax
        ret

; FAT sector AX into slot BX (times 2) from the first FAT (CL = 2), or
; from the slot to every FAT (CL = 3).  CF: AX = error.  Keeps all else
hd_wio: push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    es
        push    ds
        pop     es
        mov     dx, ax
        add     dx, [hd_fat]
        mov     ah, cl
        call    hd_slot
        mov     bx, si
        mov     cx, 1                   ; FAT copies
        cmp     ah, 3
        jne     .c
        mov     cl, [hd_nfat]
.c:     push    cx
        push    ax                      ; (AH: the operation)
        mov     cx, 1
        xor     di, di
        mov     byte [io_crit], 1
        call    hd_io
        jc      .e
        pop     ax
        pop     cx
        add     dx, [hd_spf]
        loop    .c
        clc
        jmp     short .x
.e:     pop     cx
        pop     cx
        stc
.x:     pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        ret

; slot BX (times 2) to disk if it changed (and changed it stays if it
; can't be).  CF: AX = error.  Keeps all else
hd_wout:
        push    cx
        push    si
        call    hd_slot
        test    [hd_wdirty], cl
        jz      .x                      ; (CF clear)
        push    ax
        push    cx
        mov     ax, [hd_wsec+bx]
        mov     cl, 3
        call    hd_wio
        pop     cx
        jc      .e
        not     cl
        and     [hd_wdirty], cl         ; (CF clear)
        pop     ax
        jmp     short .x
.e:     pop     si                      ; (not the caller's AX: the error)
        stc
.x:     pop     si
        pop     cx
        ret

; every changed slot to disk.  CF: AX = error
hd_flush:
        push    bx
        xor     bx, bx
.l:     call    hd_wout
        jc      .x
        inc     bx
        inc     bx
        cmp     bx, HD_NWIN * 2
        jb      .l
.x:     pop     bx
        ret

; ---------------------------------------------------------------------
;  the hooks
; ---------------------------------------------------------------------
hd_fload:                               ; fat_load: C:'s is always there
        cmp     byte [act], 2
        jne     .t
        clc
        ret
.t:     times fat_load.hk - fat_load db 90h
        jmp     fat_load.hk

hd_fflush:                              ; fat_flush: C:'s first, then the
        call    hd_flush                ;  floppy's (whichever drive asks)
        jnc     .t
        cmp     byte [act], 2           ; C:'s failed: another drive's call
        jne     .t                      ;  goes on (C:'s waits, still changed)
        push    ax
        call    .t
        pop     ax                      ; (C:'s error)
        stc
        ret
.t:     times fat_flush.hk - fat_flush db 90h
        jmp     fat_flush.hk

hd_fdrv:                                ; fat_flush_drv
        cmp     al, 2
        je      hd_flush
.t:     times fat_flush_drv.hk - fat_flush_drv db 90h
        jmp     fat_flush_drv.hk

hd_fget:                                ; fat_get: C:'s FAT16
        cmp     byte [act], 2
        jne     .t
        cmp     ax, [C_DT + D_NCL]
        jae     .end
        push    bx
        push    cx
        push    si
        mov     bx, ax
        mov     al, ah
        xor     ah, ah
        call    hd_wget
        xor     bh, bh
        shl     bx, 1
        mov     ax, [si+bx]
        pop     si
        pop     cx
        pop     bx
        ret
.end:   mov     ax, 0FFFFh
        ret
.t:     times fat_get.hk - fat_get db 90h
        jmp     fat_get.hk

hd_fset:                                ; fat_set: C:'s, the free count kept
        cmp     byte [act], 2
        jne     .t
        cmp     ax, [C_DT + D_NCL]
        jae     .x
        push    ax
        push    bx
        push    cx
        push    si
        mov     bx, ax
        mov     al, ah
        xor     ah, ah
        call    hd_wget
        or      [hd_wdirty], cl
        xor     bh, bh
        shl     bx, 1
        mov     ax, dx                  ; (the new value)
        xchg    dx, [si+bx]             ; DX = the old one
        or      cl, cl                  ; (a sector not to be had: no change)
        jz      .nc
        cmp     word [hd_free], 0FFFFh
        je      .nc
        or      dx, dx
        jnz     .a
        dec     word [hd_free]          ; was free
.a:     or      ax, ax
        jnz     .nc
        inc     word [hd_free]          ; is free
.nc:    mov     dx, ax
        pop     si
        pop     cx
        pop     bx
        pop     ax
.x:     ret
.t:     times fat_set.hk - fat_set db 90h
        jmp     fat_set.hk

hd_frun:                                ; free_run: C:'s
        cmp     byte [act], 2
        jne     .t
        push    ax
        push    dx
        mov     dx, cx
        xor     cx, cx
.l:     cmp     cx, dx
        jae     .x
        push    ax
        call    hd_fget
        or      ax, ax
        pop     ax
        jnz     .x
        inc     cx
        inc     ax
        jmp     .l
.x:     pop     dx
        pop     ax
        ret
.t:     times free_run.hk - free_run db 90h
        jmp     free_run.hk

hd_c2l:                                 ; clu2lba: C:'s in 32 bits
        cmp     byte [act], 2
        jne     .t
        push    cx
        push    dx
        sub     ax, 2
        mov     cl, [C_DT + D_SPC]
        xor     ch, ch
        mul     cx
        add     ax, [C_DT + D_DATA]
        adc     dl, 0
        mov     [lba_hi], dl
        pop     dx
        pop     cx
        ret
.t:     times clu2lba.hk - clu2lba db 90h
        jmp     clu2lba.hk

hd_bget:                                ; buf_get: C:'s sector's key
        cmp     al, 2
        jne     .t
        call    hd_key
.t:     times buf_get.hk - buf_get db 90h
        jmp     buf_get.hk

hd_bgetd:                               ; buf_getd: the same
        cmp     al, 2
        jne     .t
        call    hd_key
.t:     times buf_getd.hk - buf_getd db 90h
        jmp     buf_getd.hk

hd_key: mov     al, [lba_hi]            ; -> AL = 2 + 4 * the high part
        shl     al, 2
        or      al, 2
        mov     byte [lba_hi], 0
        ret

hd_binv:                                ; buf_inval_range: C:'s, 32 bits
        cmp     al, 2
        jne     .t
        pusha
        mov     ah, [lba_hi]
        xor     bx, bx
.l:     push    cx
        mov     cl, [buf_drv+bx]
        mov     ch, cl
        and     ch, 3                   ; (FFh, empty: 3)
        cmp     ch, 2
        jne     .n
        shr     cl, 2
        mov     si, bx
        shl     si, 1
        mov     di, [buf_lba+si]
        sub     di, dx                  ; its distance past the first: the
        sbb     cl, ah                  ;  high part in CL, 0 if in range
        jnz     .n
        pop     cx
        push    cx
        cmp     di, cx
        jae     .n
        mov     byte [buf_drv+bx], 0FFh
.n:     pop     cx
        inc     bx
        cmp     bx, NBUF
        jb      .l
        popa
        ret
.t:     times buf_inval_range.hk - buf_inval_range db 90h
        jmp     buf_inval_range.hk

hd_rpre:                                ; root_pre: the floppies' cache only
        cmp     byte [act], 2
        jne     .t
        ret
.t:     times root_pre.hk - root_pre db 90h
        jmp     root_pre.hk

hd_f36: mov     al, [bp+F_DX]           ; INT 21h 36h: C:'s free clusters,
        or      al, al                  ;  counted once, then kept
        jnz     .d
        mov     al, [cur_drv]
        inc     al
.d:     cmp     al, 3
        je      .c
.t:     times f_36.hk - f_36 db 90h
        jmp     f_36.hk
.c:     mov     al, 2
        call    use_drive
        mov     ax, [hd_free]
        cmp     ax, 0FFFFh
        jne     .k
        xor     dx, dx                  ; free ones
        xor     ax, ax                  ; FAT sector
        mov     byte [hd_bad], 0
        mov     bx, [C_DT + D_NCL]      ; entries still to look at
.s:     call    hd_wget
        mov     cx, 256
        cmp     bx, cx
        jae     .z
        mov     cx, bx
.z:     sub     bx, cx
.zl:    cmp     word [si], 0            ; (entries 0 and 1 never are)
        jne     .zn
        inc     dx
.zn:    inc     si
        inc     si
        loop    .zl
        inc     ax
        or      bx, bx
        jnz     .s
        cmp     byte [hd_bad], 0        ; (kept only if every sector was read)
        jne     .k0
        mov     [hd_free], dx
.k0:    mov     ax, dx
.k:     mov     [bp+F_BX], ax
        mov     al, [C_DT + D_SPC]
        xor     ah, ah
        mov     [bp+F_AX], ax
        mov     word [bp+F_CX], 512
        mov     ax, [C_DT + D_NCL]
        sub     ax, 2
        mov     [bp+F_DX], ax
        jmp     done

; INT 25h/26h (absolute disk read / write) for C: (AL = 2), in DOS 4's
; form: CX = FFFFh, DS:BX = a packet (dd first sector of the partition, dw
; sectors, dd buffer).  No INT 24h for the transfer (the FAT window, which
; goes to the disk first, may ask as usual).  After a write, even one that
; failed part way, the kernel forgets what it held of those sectors, the
; window and the free count (DEFRAG writes the FAT itself).  Interrupts on,
; as INT 21h.  CF: AH = BIOS status, AL = critical-error code.  RETF, the
; flags left on the stack.
; Other drives, or the old form: not supported, as before.
hd_i25: mov     ah, 2                   ; (INT 25h leaves AH to us)
        db      0A9h                    ; (TEST AX, imm16: skips the next)
hd_i26: mov     ah, 3
        cmp     al, 2
        jne     .no
        cmp     cx, 0FFFFh
        je      .c
.no:    jmp     int25
.c:     sti
        pusha
        push    ds
        push    es
        mov     bp, sp                  ; [bp+19]: AH, the operation
        les     si, [bx+6]              ; the buffer
        mov     dx, [bx]                ; DI:DX = the first sector
        mov     di, [bx+2]
        mov     cx, [bx+4]
        mov     bx, si
        push    cs
        pop     ds
        call    hd_flush                ; (the kernel's FAT changes first)
        jc      .x
        mov     ah, [bp+19]
        mov     byte [io_crit], 0
        call    hd_io
        pushf
        test    byte [bp+19], 1
        jz      .r
        push    ax                      ; a write: forget those sectors
        mov     [lba_hi], di
        mov     al, 2
        call    buf_inval_range
        xor     ax, ax
        mov     [lba_hi], ax
        dec     ax
        mov     [hd_free], ax
%assign i 0
%rep HD_NWIN
        mov     [hd_wsec+i], ax
%assign i i+2
%endrep
        pop     ax
.r:     popf
.x:     jnc     .ok
        sub     al, 19                  ; AH = the BIOS's status, AL = the
        mov     ah, [io_bios]           ;  critical-error code
        mov     [bp+18], ax
        stc
.ok:    pop     es
        pop     ds
        popa
        retf

; init's drv_init: and then C: (its entry was made at start-up, and waits
; in the window)
hd_drv_init:
        call    drv_init
        mov     si, [hd_win]
        add     si, 512
        mov     di, C_DT
        mov     cx, DRVSZ / 2
        rep     movsw
        ret

; ---------------------------------------------------------------------
;  data
; ---------------------------------------------------------------------
hd_plba     dd 0                        ; the partition's first sector
hd_spt      dw 0                        ; geometry: sectors a track,
hd_hs       dw 0                        ;   heads * sectors a track
hd_fat      dw 0                        ; the first FAT (in the partition)
hd_spf      dw 0                        ; sectors a FAT
hd_win      dw 0                        ; the window: HD_NWIN sectors there
hd_wsec     times HD_NWIN dw 0FFFFh        ; the FAT sector in each slot
hd_wage     times HD_NWIN dw 0
hd_clock    dw 0
hd_free     dw 0FFFFh                   ; free clusters (FFFFh: not counted)
hd_nfat     db 0
hd_wdirty   db 0                        ; slots changed (bit n: slot n)
hd_try      db 0
hd_err      db 0
hd_bad      db 0                        ; a FAT sector wasn't to be had
            align 16
hd_end:                                 ; (the window, with EMS: from here)

; =====================================================================
;  start-up: from ems_init, in the load image (CS = 1000h, DS = ES =
;  KSEG, the boot stack).  As there: only relative jumps and calls (the
;  module's own code above runs here too, from the image), the kernel's
;  data through DS.  The module goes into place first, so its data is
;  there to use.
; =====================================================================
section boot
hd_init:
        push    cs
        pop     ds
        mov     si, section.hd.start    ; (where it is in the file)
        mov     di, hd_start
        mov     cx, (hd_end - hd_start) / 2
        cld
        rep     movsw
        push    es
        pop     ds
        mov     ax, hd_end              ; the window: after the module, or
        cmp     word [kern_top], bss_end + 15   ;  where EMS's would be
        jne     .w                      ;  (there is room for it there)
        mov     ax, bss_end
.w:     mov     [hd_win], ax
        call    hd_find
        jc      .no
        mov     si, hd_hooks - section.boot.vstart + section.boot.start  ; (in the image)
                                        ; hooked: each place's first bytes
.h:     mov     di, [cs:si]             ;  to its .t, and a jump to it there
        or      di, di
        jz      .hd
        mov     bx, [cs:si+4]
        mov     cx, [cs:si+2]
        sub     cx, di
.cp:    mov     al, [di]
        mov     [bx], al
        inc     di
        inc     bx
        loop    .cp
        mov     di, [cs:si]
        mov     byte [di], 0E9h         ; JMP NEAR
        mov     ax, [cs:si+6]
        sub     ax, di
        sub     ax, 3
        mov     [di+1], ax
        add     si, 8
        jmp     .h
.hd:    push    ds                      ; IRQ 14 off, unless the BIOS has the
        xor     ax, ax                  ;  disk too (then its INT 76h answers
        mov     ds, ax                  ;  it): every command raises it, and
        cmp     [475h], al              ;  the 1520 can't stop the drive
        pop     ds                      ;  asking (nIEN is at 3F6h)
        jne     .ir
        in      al, 0A1h
        or      al, 40h
        out     0A1h, al
.ir:    mov     word [vec_table.v25], hd_i25    ; INT 25h/26h for C:
        mov     word [vec_table.v26], hd_i26
        mov     ax, hd_drv_init         ; and init's call to drv_init
        sub     ax, init.cdrv + 3
        mov     [init.cdrv + 1], ax
        mov     byte [lastdrv], 3       ; INT 21h 0Eh: to C:
        mov     ax, [hd_win]            ; the arena from above it all
        add     ax, HD_NWIN * 512
        cmp     ax, hd_end
        ja      .k
        mov     ax, hd_end
.k:     add     ax, 15
        mov     [kern_top], ax
.no:    jmp     rom_init                ; (KROM.INC: then KSPLASH.INC, KSEG:init)

; is there a drive, with a FAT16 partition we can use?  CF if not.  Else
; the module's data set, and C:'s drive table entry made at [hd_win] + 512
; ([hd_win]: what is read on the way: IDENTIFY and the partition table
; there, the boot sector at + 1024; hd_wage, reset after, holds the
; drive's size meanwhile)
hd_find:
        mov     dx, HD_PORT + 6
        mov     al, 0A0h                ; drive 0
        out     dx, al
        call    hd_echo
        jnc     .here
        ; No echo: a busy drive (BSY in every register), or nobody?  A bus
        ; nobody drives reads FFh, or back the code just fetched (HDPROBE on
        ; the 1520, 2026-10-07): bytes with no BSY bit after these INs.
        mov     dx, HD_PORT + 7
        in      al, dx
        times 4 db 45h, 4Dh             ; (INC BP, DEC BP)
        mov     ah, al
        in      al, dx
        times 4 db 45h, 4Dh
        cmp     ax, 0FFFFh              ; (FFh: nothing on the bus at all)
        je      .no
        and     al, ah
        jns     .no
        mov     ah, 40h                 ; busy: spinning up?  5 s for it
        call    hd_wait
        jc      .no
        call    hd_echo
        jc      .no
.here:  mov     ah, 40h                 ; ready (DRDY)
        call    hd_wait
        jc      .no
        mov     dx, HD_PORT + 7         ; IDENTIFY: its geometry
        mov     al, 0ECh
        out     dx, al
        mov     ah, 09h
        call    hd_wait
        jc      .no
        test    al, 01h
        jnz     .no
        mov     di, [hd_win]
        mov     cx, 256
        mov     dx, HD_PORT
        rep     insw
        mov     si, [hd_win]
        mov     ax, [si + 3 * 2]        ; heads: 1-16
        dec     ax
        cmp     ax, 15
        ja      .no
        mov     cx, [si + 6 * 2]        ; sectors a track: 1-63
        dec     cx
        cmp     cx, 62
        ja      .no
        inc     cx
        mov     [hd_spt], cx
        push    ax
        inc     ax
        mul     cx
        mov     [hd_hs], ax
        mul     word [si + 1 * 2]       ; its size: * cylinders
        mov     [hd_wage], ax
        mov     [hd_wage+2], dx
        pop     ax
        or      al, 0A0h                ; INITIALIZE DEVICE PARAMETERS (91h),
        mov     dx, HD_PORT + 6         ;  as the BIOS would
        out     dx, al
        mov     dx, HD_PORT + 2
        mov     al, cl
        out     dx, al
        mov     dx, HD_PORT + 7
        mov     al, 91h
        out     dx, al
        mov     ah, 0
        call    hd_wait
        jc      .no
        xor     ax, ax                  ; the partition table
        mov     [hd_plba], ax
        mov     [hd_plba+2], ax
        mov     bx, [hd_win]
        call    .rd0
        jc      .no
        mov     bp, [hd_win]
        cmp     word [ds:bp+510], 0AA55h
        jne     .no
        add     bp, 446
        mov     cx, 4
.p:     mov     al, [ds:bp+4]
        cmp     al, 04h                 ; FAT16, under 32 MB
        je      .fp
        cmp     al, 06h                 ; FAT16 (DOS 4)
        je      .fp
        cmp     al, 0Eh                 ; FAT16 (by LBA: we go by CHS)
        je      .fp
        add     bp, 16
        loop    .p
        jmp     .no
.fp:    mov     ax, [ds:bp+8]           ; (BP: its entry, from here on)
        mov     [hd_plba], ax
        mov     ax, [ds:bp+10]
        mov     [hd_plba+2], ax
        mov     bx, [hd_win]
        add     bx, 1024
        call    .rd0                    ; its boot sector
        jc      .no
        mov     si, bx
        mov     di, [hd_win]
        add     di, 512                 ; C:'s drive table entry, made here
        push    di
        mov     cx, DRVSZ / 2
        xor     ax, ax
        rep     stosw
        pop     di
        cmp     word [si+0Bh], 512
        jne     .no
        mov     al, [si+0Dh]            ; sectors a cluster: 1, 2, 4 .. 64
        mov     [di+D_SPC], al
        or      al, al
        jz      .no
        xor     cl, cl
.sh:    shr     al, 1
        jc      .she
        inc     cl
        jmp     .sh
.she:   or      al, al
        jnz     .no
        cmp     cl, 6
        ja      .no
        mov     [di+D_SHIFT], cl
        mov     ax, [si+0Eh]            ; reserved sectors: the first FAT
        or      ax, ax
        jz      .no
        mov     [di+D_RSV], ax
        mov     [hd_fat], ax
        mov     al, [si+10h]            ; FATs: 1 or 2
        mov     [di+D_NFAT], al
        mov     [hd_nfat], al
        dec     al
        cmp     al, 1
        ja      .no
        mov     ax, [si+11h]            ; root entries
        or      ax, ax
        jz      .no
        cmp     ax, 4096
        ja      .no
        mov     [di+D_NROOT], ax
        mov     ax, [si+16h]            ; sectors a FAT
        or      ax, ax
        jz      .no
        mov     [di+D_SPF], ax
        mov     [hd_spf], ax
        xor     ch, ch
        mov     cl, [di+D_NFAT]
        mul     cx
        add     ax, [di+D_RSV]
        adc     dx, 0
        jnz     .no                     ; (the root past 32 MB: no)
        mov     [di+D_ROOT], ax
        mov     bx, [di+D_NROOT]
        add     bx, 15
        shr     bx, 4
        mov     [di+D_RSEC], bx
        add     ax, bx
        jc      .no
        mov     [di+D_DATA], ax
        mov     bx, ax                  ; sectors before the data
        mov     ax, [si+13h]            ; the size: 16 bits, or 32 (DOS 4)
        xor     dx, dx
        or      ax, ax
        jnz     .t16
        mov     ax, [si+20h]
        mov     dx, [si+22h]
.t16:   cmp     dx, 64                  ; under 2 GB (the sector numbers' high
        jae     .no                     ;  part goes in 6 bits)
        cmp     dx, [ds:bp+14]          ; within the partition, as the table
        jb      .in                     ;  says
        ja      .no
        cmp     ax, [ds:bp+12]
        ja      .no
.in:    push    ax                      ; and the partition within the drive
        push    dx
        add     ax, [hd_plba]
        adc     dx, [hd_plba+2]
        sub     ax, [hd_wage]
        sbb     dx, [hd_wage+2]         ; (its end - the drive's size: <= 0)
        cmc
        jnc     .ok                     ; (borrow: below)
        or      ax, dx
        jz      .ok                     ; (just to the end)
        stc
.ok:    pop     dx
        pop     ax
        jc      .no
        sub     ax, bx
        sbb     dx, 0
        jc      .no
        mov     cl, [di+D_SHIFT]
.cs:    or      cl, cl                  ; -> clusters
        jz      .cn
        shr     dx, 1
        rcr     ax, 1
        dec     cl
        jmp     .cs
.cn:    or      dx, dx
        jnz     .no
        cmp     ax, 4085                ; FAT16: 4085 .. 65518 clusters (the
        jb      .no                     ;  kernel takes FFF0h on as ends)
        cmp     ax, 65519
        jae     .no
        add     ax, 2
        mov     [di+D_NCL], ax
        mov     bx, [di+D_SPF]          ; and the FAT holds them all
        cmp     bx, 256
        jae     .fok
        xchg    bl, bh
        cmp     bx, ax
        jb      .no
.fok:   mov     byte [di+D_UNIT], 80h   ; (a fixed disk: drv_ready knows)
        mov     byte [di+D_MNT], 1
        mov     byte [di+D_PRES], 1
        mov     word [di+D_SPT], HD_SPT
        mov     word [di+D_HEADS], 1
        mov     word [di+D_HINT], 2
        mov     al, [si+15h]
        mov     [di+D_MEDIA], al
        xor     ax, ax
        mov     [hd_wage], ax           ; (as they were)
        mov     [hd_wage+2], ax
        clc
        ret
.no:    stc
        ret
; sector 0 of the partition (hd_plba) to BX.  CF if it can't be
.rd0:   xor     ax, ax
        xor     dx, dx
        mov     cx, 1
        mov     byte [io_op], 2
        jmp     hd_rw

; do the sector count and number registers keep what is written?  CF: no
hd_echo:
        mov     bx, 0AA55h
        call    .one
        jc      .x
        mov     bx, 055AAh
.one:   mov     dx, HD_PORT + 2
        mov     al, bl
        out     dx, al
        inc     dx
        mov     al, bh
        out     dx, al
        in      al, dx
        mov     ah, al
        dec     dx
        in      al, dx
        cmp     ax, bx
        je      .x
        stc
.x:     ret

; the places hooked: the kernel's place, its .hk, the hook's .t, the hook
hd_hooks:
        dw      dio, dio.hk, hd_dio.t, hd_dio
        dw      fat_load, fat_load.hk, hd_fload.t, hd_fload
        dw      fat_flush, fat_flush.hk, hd_fflush.t, hd_fflush
        dw      fat_flush_drv, fat_flush_drv.hk, hd_fdrv.t, hd_fdrv
        dw      fat_get, fat_get.hk, hd_fget.t, hd_fget
        dw      fat_set, fat_set.hk, hd_fset.t, hd_fset
        dw      free_run, free_run.hk, hd_frun.t, hd_frun
        dw      clu2lba, clu2lba.hk, hd_c2l.t, hd_c2l
        dw      buf_get, buf_get.hk, hd_bget.t, hd_bget
        dw      buf_getd, buf_getd.hk, hd_bgetd.t, hd_bgetd
        dw      buf_inval_range, buf_inval_range.hk, hd_binv.t, hd_binv
        dw      root_pre, root_pre.hk, hd_rpre.t, hd_rpre
        dw      f_36, f_36.hk, hd_f36.t, hd_f36
        dw      0
; each place must have room for the jump: 3 bytes or more (all of them
; whole instructions that don't jump).  A negative TIMES here says which
%macro HKROOM 1-*
%rep %0
        times (%1.hk - %1) - 3 resb 1
%rotate 1
%endrep
%endmacro
[absolute 0]
        HKROOM  dio, fat_load, fat_flush, fat_flush_drv, fat_get, fat_set, free_run, clu2lba
        HKROOM  buf_get, buf_getd, buf_inval_range, root_pre, f_36
section boot
