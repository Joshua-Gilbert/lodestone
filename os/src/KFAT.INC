; =====================================================================
;  KFAT.INC - names, paths and directories on FAT12/16, and the INT 21h
;  calls that work on paths: 39h MKDIR, 3Ah RMDIR, 3Bh CHDIR, 41h
;  DELETE, 43h attributes, 47h current directory, 56h RENAME.
; =====================================================================
A_RO    equ 01h
A_HID   equ 02h
A_SYS   equ 04h
A_VOL   equ 08h
A_DIR   equ 10h
A_ARC   equ 20h

section .bss
path_buf    resb 130            ; the caller's path, copied here
path2_buf   equ KL_P2           ; (130 bytes, in the INT 21h stack's low area: K2)
nm11        resb 11             ; a parsed name component; resolve's last is
r_name      equ nm11            ;  r_name (0 = none), so no parse_comp may
                                ;  come between a resolve and a use of it
r_drv       resb 1              ; resolved path: drive,
r_wild      resb 1              ;   its last component has wildcards,
            alignb 2
r_dir       resw 1              ;   directory cluster (0 = root)
d_lba       resw 1              ; the directory entry found: sector,
d_off       resw 1              ;   offset in it (bits 9+: the sector
                                ;   number's high part: dent_buf),
de          resb 32             ; a copy of it (RENAME copies the three)
de_idx      resw 1              ; dir_entry's last root sector: an entry
de_lba      resw 1              ;   in it, its LBA,
de_bix      resw 1              ;   its buffer,
de_drv      resb 1              ;   the drive (FFh: none)
de_root     resb 1
            alignb 2
dl_lim      resw 1              ; dir_lim: entries in the directory searched
it_dir      resw 1              ; dir_entry's cluster cache
it_cl       resw 1
it_ci       resw 1
section .text

; AL: a small letter (a-z) made a capital.  Flags changed
up_al:  cmp     al, 'a'
        jb      .x
        cmp     al, 'z'
        ja      .x
        sub     al, 20h
.x:     ret

; copy the caller's ASCIIZ path DS:DX (frame) to path_buf (uppercase,
; '/' -> '\').  CF: AX = 3 if empty or too long
get_path:
        mov     si, [bp+F_DX]
        mov     di, path_buf
gpath:  push    ds
        mov     ds, [bp+F_DS]
        mov     cx, 128
.l:     lodsb
        call    up_al
.n:     cmp     al, '/'
        jne     .s
        mov     al, '\'
.s:     mov     [es:di], al
        inc     di
        or      al, al
        jz      .end
        loop    .l
        pop     ds
        jmp     .bad
        times ($ - $$) & 1 db 90h       ; (hot: even)
.end:   pop     ds
        cmp     byte [path_buf], 0
        je      .bad
        clc
        ret
.bad:   mov     ax, 3
        stc
        ret

; parse one component at SI into nm11 (wildcards become '?').
; -> SI at the '\' or NUL after it, AL = 1 if wildcards.  CF: invalid
parse_comp:
        push    cx
        push    di
        mov     di, nm11
        push    di
        mov     cx, 11
        mov     al, ' '
        rep     stosb
        pop     di
        xor     ah, ah                  ; wildcard flag
        cmp     byte [si], '.'
        jne     .name
        mov     byte [di], '.'          ; "." or ".."
        inc     si
        cmp     byte [si], '.'
        jne     .dots
        mov     byte [di+1], '.'
        inc     si
.dots:  mov     al, [si]
        or      al, al
        jz      .ok
        cmp     al, '\'
        je      .ok
        jmp     .bad
.name:  mov     cx, 8
        call    .field
        jc      .bad
        cmp     di, nm11                ; nothing at all?
        jne     .sp
        cmp     byte [si], '.'
        jne     .bad
        jmp     short .ext0
.sp:    cmp     byte [nm11], ' '        ; (a space inside a name, as MS-DOS:
        je      .bad                    ;  not first)
.ext0:  cmp     byte [si], '.'
        jne     .ok
        inc     si
        mov     di, nm11 + 8
        mov     cx, 3
        call    .field
        jc      .bad
        jmp     short .dots             ; (then \ or 0: a second dot is no
.ok:    cmp     byte [nm11], 0E5h       ;  name, as MS-DOS)
        jne     .ok5                    ; (a first E5h is 05h on the disk:
        mov     byte [nm11], 05h        ;  E5h there is a free entry)
.ok5:   mov     al, ah
        clc
        jmp     .x
.bad:   stc
.x:     pop     di
        pop     cx
        ret
        times ($ - $$) & 1 db 90h       ; (hot: even)
; up to CX characters into DI; stops at '.', '\' or NUL
.field: mov     dx, cx
.fl:    mov     al, [si]
        or      al, al
        jz      .fe
        cmp     al, '\'
        je      .fe
        cmp     al, '.'
        je      .fe
        inc     si
        cmp     al, '*'
        je      .star
        cmp     al, '?'
        jne     .chk
        mov     ah, 1
        jmp     .put
        times ($ - $$) & 1 db 90h       ; (hot: even)
.chk:   push    di
        push    cx
        mov     di, badchars
        mov     cx, NBADC
        repne   scasb
        pop     cx
        pop     di
        je      .err
        cmp     al, ' '
        jb      .err
.put:   jcxz    .fl                     ; too long: the rest is ignored
        mov     [di], al
        inc     di
        dec     cx
        jmp     .fl
.star:  mov     ah, 1
.st:    jcxz    .fl
        mov     byte [di], '?'
        inc     di
        loop    .st
        jmp     .fl
.fe:    clc
        ret
.err:   stc
        ret
badchars equ sepchars + 2                ; '"+,/:;<=>[]|' (KCORE.INC: f_29's
NBADC   equ NSEP - 2                    ;  separators past '.' and '\')

; resolve path_buf for a name to make, as MS-DOS: CF: AX = 5 if there is
; none, or it is "." or ".." (in the root no such entry would be found), 3
; with wildcards, or resolve's error
resolve_new:
        call    resolve
        jc      new_name.x
new_name:                               ; (the same after a resolve; one that
        mov     ax, 3                   ;  worked sets r_wild only with r_name)
        cmp     byte [r_wild], 0
        jne     .f
        mov     al, [r_name]
        cmp     al, '.'
        je      .f5
        or      al, al
        jz      .f5
        clc
.x:     ret
.f5:    mov     al, 5
.f:     stc
        ret

; the drive of the path at SI (get_path's: capitals) -> AL, SI past its
; "X:" (none: the current drive)
path_drv:
        mov     al, [cur_drv]
        cmp     byte [si+1], ':'
        jne     .x
        mov     al, [si]
        sub     al, 'A'
        add     si, 2
.x:     ret

; resolve path_buf (or SI) -> r_drv, r_dir, r_name, r_wild.
; Gets the drive ready and its FAT loaded.  CF: AX = error (3 or 15)
resolve:
        mov     si, path_buf
resolve_si:
        xor     ax, ax
        mov     [it_dir], ax
        mov     [r_wild], al            ; (before the drive: nf_last and
        mov     [r_name], al            ;  RMDIR read them)
        call    path_drv
        push    si
        call    drv_ready
        mov     bx, si
        pop     si
        jc      .dr                     ; (invalid, or not ready: 3, MS-DOS's)
        mov     al, [act]
        mov     [r_drv], al
        call    fat_load                ; (keeps BX: the drive's entry)
        jc      .dr                     ; (another floppy's FAT stuck: 3 too,
.cw:    mov     ax, [bx+D_CWD]          ;  KDISK.INC rule 4)
        cmp     byte [si], '\'
        je      .abs
        inc     ax                      ; (FFFFh: the current directory
        jz      .find                   ;  unknown, its disk unreadable when
        dec     ax                      ;  it was looked for: found now, a
        jmp     short .c                ;  relative path wanting it; still
.find:  call    cwd_find                ;  unreadable: 3, MS-DOS's)
        jnc     .cw
        jmp     .np
.abs:   xor     ax, ax
        inc     si
.c:     mov     [r_dir], ax
.comp:  cmp     byte [si], 0
        je      .ok
        call    parse_comp
        jc      .bad
        cmp     byte [si], '\'
        jne     .last
.bs:    inc     si
        cmp     byte [si], '\'         ; (two \s: one, as MS-DOS)
        je      .bs
        cmp     byte [si], 0            ; (a \ last: 3, as MS-DOS)
        je      .np
        or      al, al
        jnz     .np
        cmp     word [nm11], '. '
        je      .comp
        push    si
        mov     ax, [r_dir]
        call    dir_find
        pop     si
        jc      .npe
        test    byte [de+11], A_DIR
        jz      .np
        mov     ax, [de+26]
        mov     [r_dir], ax
        jmp     .comp
.npe:   cmp     ax, 2
        je      .rest
        stc                             ; a disk error
        ret
.rest:  call    parse_comp              ; a directory not there: the rest
        jc      .bad                    ;  read on, as MS-DOS (X17): a bad
        cmp     byte [si], '\'         ;  middle part 3, a bad or wild last
        jne     .rl                     ;  one marked (open, create: 2)
        inc     si
        cmp     byte [si], 0            ; (a \ last: that part is the
        je      .rl                     ;  last, as MS-DOS: wild 2, else 3)
        jmp     .rest
.rl:    mov     [r_wild], al
        jmp     short .np
.last:  cmp     word [nm11], '..'       ; (".." last in the root: 3, as
        jne     .l1                     ;  MS-DOS)
        cmp     word [r_dir], 0
        je      .np
.l1:    mov     [r_wild], al            ; (r_name: nm11 as parsed)
.ok:    clc
        ret
.bad:   lodsb                           ; no name: if it is the last part,
        cmp     al, '\'                 ;  r_wild = FFh (open and create say
        je      .np                     ;  2 then, as MS-DOS: nf_last)
        or      al, al
        jnz     .bad
        dec     byte [r_wild]           ; (from 0)
.np:    mov     ax, 3
        mov     [r_name], ah            ; (none: f_3A.nd reads it so)
        stc
.x:     ret
.dr:    cmp     al, 26                  ; (not a DOS disk: said as such)
        jne     .np
        stc
        ret
        times ($ - $$) & 1 db 90h       ; (hot: even)

; entry BX of directory AX -> SI (in a sector buffer), d_lba, d_off.
; CF: past the end of the directory (AX = 18), a disk error, or AX = 5 (a
; chain longer than the disk: a loop)
dir_entry:
        push    bx
        push    cx
        push    dx
        push    di
        mov     di, [actp]
        xor     ch, ch                  ; (the sector number's high part)
        or      ax, ax
        jnz     .sub
        cmp     bx, [di+D_NROOT]
        jae     .end
        ; The root: in the same sector as last time, still in its buffer?
        ; Then no lookup (a search steps through 16 entries a sector).
        ; (Only the root: its sectors never move.)
        mov     dx, bx
        xor     dx, [de_idx]
        cmp     dx, 16
        jae     .r
        mov     cl, [act]
        cmp     cl, [de_drv]
        jne     .r
        push    bx
        mov     bx, [de_bix]
        cmp     [buf_drv+bx], cl
        jne     .rx
        shl     bx, 1
        mov     dx, [de_lba]
        cmp     [buf_lba+bx], dx
        jne     .rx
        mov     si, [de_bix]
        pop     bx
        shl     si, 9
        add     si, bufs
        mov     [d_lba], dx
        jmp     .got
.rx:    pop     bx
.r:     mov     byte [de_drv], 0FFh     ; (none until this lookup works)
        mov     byte [de_root], 1
        mov     dx, bx
        shr     dx, 4
        jz      .r0                     ; Past the first sector and not in a
        push    dx                      ; buffer: a search that far usually
        add     dx, [di+D_ROOT]         ; reads on to the end marker, so the
        mov     al, [act]               ; whole root goes into the disk cache
        call    buf_has                 ; in one pass (if it isn't there).
        pop     dx                      ; A short root stays in the buffers
        je      .r0                     ; and needs none of that.
        call    root_pre
.r0:    add     dx, [di+D_ROOT]
        jmp     .rd
.sub:   mov     byte [de_root], 0
        mov     cl, [di+D_SHIFT]
        add     cl, 4
        mov     dx, bx
        shr     dx, cl                  ; cluster number in the chain
        cmp     dx, [di+D_NCL]          ; (more than the disk has: a loop,
        jae     .brk                    ;  rule 7)
        cmp     ax, [it_dir]
        jne     .walk0
        cmp     dx, [it_ci]
        jb      .walk0
        mov     ax, [it_cl]
        mov     cx, [it_ci]
        jmp     .walk
        times ($ + 5 - $$) & 1 db 90h   ; (hot: .walk and what follows even)
.walk0: mov     [it_dir], ax
        xor     cx, cx
.walk:  cmp     cx, dx
        je      .there
        call    fat_get
        cmp     ax, 0FFF0h
        jae     .end0
        cmp     ax, 2
        jb      .end0
        inc     cx
        jmp     .walk
.there: mov     [it_cl], ax
        mov     [it_ci], cx
        call    clu2lba
        mov     dx, bx
        shr     dx, 4
        mov     cl, [di+D_SPC]
        dec     cl
        and     dl, cl
        xor     dh, dh
        add     dx, ax
        adc     byte [lba_hi], 0
        mov     ch, [lba_hi]
.rd:    mov     [d_lba], dx
        mov     [lba_hi], ch
        mov     al, [act]
        call    buf_get
        jc      .x
        cmp     byte [de_root], 0
        je      .got
        mov     [de_idx], bx            ; remember where this root sector is
        mov     [de_lba], dx
        mov     ax, si
        sub     ax, bufs
        shr     ax, 9
        mov     [de_bix], ax
        mov     al, [act]
        mov     [de_drv], al
.got:   and     bx, 15
        shl     bx, 5
        add     si, bx
        shl     ch, 1
        or      bh, ch
        mov     [d_off], bx
        clc
        jmp     .x
.brk:   mov     ax, 5
        stc
        jmp     short .x
.end0:  mov     word [it_dir], 0
.end:   mov     ax, 18
        stc
.x:     pop     di
        pop     dx
        pop     cx
        pop     bx
        ret

; the end of directory AX for in-sector stepping: the root's size, or
; none (dir_entry finds the end of a subdirectory)
dir_lim:
        mov     word [dl_lim], 0FFFFh
        or      ax, ax
        jnz     .x
        push    di
        mov     di, [actp]
        mov     ax, [di+D_NROOT]
        mov     [dl_lim], ax
        xor     ax, ax
        pop     di
.x:     ret

; the directory entry at sector DX, place AX (as d_off: the offset, and
; from bit 9 the sector number's high part) on drive [act] -> SI.  CF: AX
dent_buf:
        push    bx
        mov     bx, ax
        and     bx, 511
        shr     ah, 1
        mov     [lba_hi], ah
        mov     al, [act]
        call    buf_get
        jc      .x
        add     si, bx
.x:     pop     bx
        ret

; drive [act]'s whole root directory into the disk cache, one pass (if
; it isn't there already; errors are left to the reads that follow).
; DI = drive table entry
root_pre:
        push    ax
        push    bx
        push    cx
.hk:                                    ; (KHD.INC: not for C:)
        push    dx
        mov     ax, [di+D_RSEC]
        dec     ax
        mov     [io_ra], ax
        mov     dx, [di+D_ROOT]
        call    raw_bounce
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

; find nm11 (wildcards allowed) in directory AX: files, directories,
; hidden and system entries alike (CL isn't read); volume labels and long
; names never match.  -> BX = index, SI = entry, de = copy.  CF: AX = 2
dir_find:
        push    ax
        call    dir_lim
        xor     bx, bx
.l:     pop     ax
        push    ax
        call    dir_entry
        jc      .end
.e:     mov     dl, [si]
        or      dl, dl
        jz      .no
        cmp     dl, 0E5h
        je      .n
        mov     dl, [si+11]
        cmp     dl, 0Fh
        je      .n
        test    dl, A_VOL
        jnz     .n
        call    name_match
        jne     .n
        mov     dx, bx                  ; (found further into the sector)
        and     dx, 15
        shl     dx, 5
        and     word [d_off], 0FE00h
        or      [d_off], dx
        push    si
        push    di
        push    cx
        mov     di, de
        mov     cx, 16
        rep     movsw
        pop     cx
        pop     di
        pop     si
        pop     ax
        clc
        ret
.n:     inc     bx                      ; the next entry: in this sector,
        test    bl, 15                  ; straight on in the buffer
        jz      .l
        cmp     bx, [dl_lim]
        jae     .l
        add     si, 32
        jmp     .e
.end:   cmp     ax, 18
        je      .no
        add     sp, 2                   ; a disk error: AX says which
        stc
        ret
.no:    pop     ax
        mov     ax, 2
        stc
        ret

; entry name at SI vs pattern nm11 -> ZF = 1 if it matches
name_match:
        push    cx
        push    si
        push    di
        mov     di, nm11
        mov     cx, 11
.l:     mov     al, [di]
        cmp     al, '?'
        je      .n
        cmp     al, [si]
        jne     .x
.n:     inc     si
        inc     di
        loop    .l
        cmp     al, al
.x:     pop     di
        pop     si
        pop     cx
        ret

; a free entry in directory AX (extends a subdirectory when full)
; -> BX = index, SI = entry.  CF: AX = 5 (root full) or an error
dir_slot:
        push    ax
        xor     bx, bx
.l:     pop     ax
        push    ax
        call    dir_entry
        jc      .end
        cmp     byte [si], 0
        je      .got
        cmp     byte [si], 0E5h
        je      .got
        inc     bx
        jmp     .l
.got:   pop     ax
        clc
        ret
.end:   cmp     ax, 18
        jne     .err
        pop     ax
        push    ax
        or      ax, ax
        jz      .full                   ; the root can't grow
        ; append a cluster to the subdirectory: find its last cluster
.last:  mov     dx, ax
        call    fat_get
        cmp     ax, 2                   ; (free or reserved: a broken chain,
        jb      .brk                    ;  KDISK.INC rule 7)
        cmp     ax, 0FFF0h
        jb      .last
        call    fat_keep
        push    dx                      ; unlinked: zeroed first, then linked
        xor     dx, dx                  ;  (an Abort between: one cluster
        call    clu_alloc               ;  lost, nothing stale named)
        pop     dx
        jc      .err
        push    ax
        call    clu_zero
        pop     cx                      ; (CX = the new cluster)
        jc      .unl
        mov     ax, dx                  ; the last one -> the new one
        mov     dx, cx
        call    fat_set
        mov     word [it_dir], 0
        pop     ax
        push    ax
        call    dir_entry               ; BX = first entry of the new cluster
        jc      .err
        pop     ax
        clc
        ret
.unl:   push    ax                      ; it can't be written: given back
        mov     ax, cx
        xor     dx, dx
        call    fat_set
        call    fat_back                ; (the FAT as it was: unchanged)
        pop     ax
        jmp     short .err
.brk:
.full:  mov     ax, 5
.err:   add     sp, 2
        stc
        ret

; write zeros over cluster AX (keeps AX).  CF: AX = error
clu_zero:
        push    si
        push    ax
        push    bx
        push    cx
        push    dx
        push    di
        push    es
        push    ax
        mov     di, bounce
        mov     cx, 256
        xor     ax, ax
        push    cs
        pop     es
        rep     stosw
        mov     si, [actp]
        mov     cl, [si+D_SPC]
        xor     ch, ch
        pop     ax
        call    clu2lba
        mov     dx, ax
        mov     si, [lba_hi]            ; (for each sector: disk_io uses it up)
        mov     al, [act]
        call    buf_inval_range
.w:     push    cx
        mov     [lba_hi], si
        mov     al, [act]
        mov     ah, 3
        mov     cx, 1
        mov     bx, bounce
        call    disk_io
        pop     cx
        jc      .x
        inc     dx
        jnz     .nw
        inc     si
.nw:    loop    .w
        clc
.x:     pop     es
        pop     di
        pop     dx
        pop     cx
        pop     bx
        jnc     .ok                     ; (an error: AX = it, not the cluster;
        pop     si                      ;  pops keep CF)
        pop     si
        ret
.ok:    pop     ax
        pop     si
        ret

; a fresh directory entry at SI: name r_name, attribute CL, cluster AX,
; size 0, stamped now.  Then written to disk.  CF: AX = error.  AX and
; CX changed (the fields go in their order, ES = DS).  An entry in use
; (CREATE's truncate) keeps bytes 12-21, which other systems use: a free
; slot (0, E5h) gets them zeroed
new_entry:
        push    di
        push    si
        push    dx
        push    ax
        mov     di, si
        mov     dl, [si]                ; (in use?)
        mov     si, r_name
        mov     al, cl
        mov     cx, 11
        rep     movsb                   ; [0] the name
        stosb                           ; [11] the attribute
        dec     dl                      ; 0, E5h (and E6h-FFh) -> FFh, E4h+
        cmp     dl, 0E4h
        jae     .z
        add     di, 10                  ; [12] kept
        jmp     short .t
.z:     xor     ax, ax
        mov     cl, 5
        rep     stosw                   ; [12] zeroed
.t:     call    dos_stamp
        stosw                           ; [22] the time
        xchg    ax, dx
        stosw                           ; [24] the date
        pop     ax
        stosw                           ; [26] the cluster
        xor     ax, ax
        stosw                           ; [28] the size
        stosw
        pop     dx
        pop     si
        pop     di
        jmp     buf_put

; DS:SI entry name -> ES:DI "NAME.EXT",0
name_out:
        push    cx                      ; (as MS-DOS's: only the trailing
        push    si                      ;  spaces of each part go, so a
        mov     cx, 8                   ;  label's inside ones are kept)
        rep     movsb
        cmp     byte [es:di-8], 05h     ; (a first 05h is E5h's place on the
        jne     .nt                     ;  disk: E5h, as MS-DOS gives it)
        mov     byte [es:di-8], 0E5h
.nt:    cmp     byte [es:di-1], ' '
        jne     .e
        dec     di
        inc     cx
        cmp     cx, 8
        jb      .nt
.e:     cmp     word [si], '  '         ; an extension: any of its 3 not a
        jne     .x                      ;  space
        cmp     byte [si+2], ' '
        je      .z
.x:     mov     al, '.'
        stosb
        mov     cx, 3
        rep     movsb
.xt:    cmp     byte [es:di-1], ' '
        jne     .z
        dec     di
        jmp     .xt
.z:     xor     al, al
        stosb
        pop     si
        pop     cx
        ret

; ---------------------------------------------------------------------
;  INT 21h path calls
; ---------------------------------------------------------------------
; the path names an existing file: -> de, d_lba/d_off, SI.  CF: AX
find_file:
        call    resolve
        jc      find_named.x
        cmp     byte [r_name], 0
        je      find_named.nf
        cmp     byte [r_wild], 0
        jne     resolve_si.np           ; (3, as MS-DOS; open's 2: nf_last)
; r_name (nm11) in r_dir: dir_find's answer
find_named:
        mov     ax, [r_dir]
        jmp     dir_find
.nf:    mov     ax, 2
        stc
.x:     ret

f_43:   call    get_path                ; get/set attributes
        jc      f_41.e
        call    find_file
        jc      f_41.e
        cmp     byte [bp+F_AX], 0
        jne     .set
        mov     al, [de+11]
        xor     ah, ah
        mov     [bp+F_CX], ax
        jmp     ok
.set:   cmp     byte [bp+F_AX], 1
        jne     .bad
        mov     al, [bp+F_CX]
        test    al, A_DIR | A_VOL
        jnz     f_41.acc
        mov     ah, [si+11]
        and     ah, A_DIR
        or      al, ah
        mov     [si+11], al
        call    buf_put
        jmp     ret_cf
.bad:   mov     ax, 1
        jmp     short f_41.e

f_41:   call    get_path                ; DELETE
        jc      .e
        call    find_file
        jc      .nf
        test    byte [de+11], A_DIR | A_RO | A_VOL
        jnz     .acc
        call    sft_busy                ; open?  then refuse
        jc      .acc
        mov     byte [si], 0E5h
        call    buf_put
        jc      .e
        mov     ax, [de+26]
        call    free_chain
        call    fat_flush_act
        jmp     ret_cf
.nf:    cmp     ax, 2                   ; not there (its directory is): a
        jne     .e                      ;  device's name is 5, as MS-DOS
        call    dev_lookup
        mov     ax, 2                   ; (CF kept)
        jc      .e
.acc:   mov     ax, 5
.e:     jmp     fail

f_39:   call    get_path                ; MKDIR
        jc      .e
        call    resolve_new
        jc      .e
        call    find_named
        jnc     .acc                    ; already there
        cmp     ax, 2
        jne     .e
        call    dev_lookup              ; a device's name (its directory
        jnc     .acc                    ;  there): 5, as MS-DOS
        mov     ax, [r_dir]
        call    dir_slot                ; (d_lba/d_off: the slot, until the
        jc      .e                      ;  next dir_entry or dir_find)
        xor     dx, dx
        mov     [new_dir], dx
        call    fat_keep
        call    clu_alloc
        jc      .e3
        mov     [new_dir], ax
        call    clu_zero
        jnc     .z
        push    ax                      ; it can't be written: given back, the
        mov     ax, [new_dir]           ;  FAT as it was (nothing went out)
        xor     dx, dx
        call    fat_set
        call    fat_back
        pop     ax
        jmp     .e
.z:     call    fat_flush_act           ; its cluster is taken before it is named
        jc      .e3
        mov     dx, [d_lba]
        mov     ax, [d_off]
        call    dent_buf                ; the parent's slot again
        jc      .e
        mov     ax, [new_dir]
        mov     cl, A_DIR
        call    new_entry
        jc      .e
        ; "." and ".." in the new directory
        mov     ax, [new_dir]
        call    clu2lba
        mov     dx, ax
        mov     al, [act]
        call    buf_get
        jc      .e
        mov     di, r_name
        mov     ax, '. '
        stosw
        mov     ax, '  '
        mov     cx, 4
        rep     stosw
        stosb
        mov     ax, [new_dir]
        mov     cl, A_DIR
        call    new_entry
        jc      .e
        add     si, 32
        mov     word [r_name], '..'
        mov     ax, [r_dir]
        mov     cl, A_DIR
        call    new_entry
        jc      .e
        call    fat_flush_act
        jmp     ret_cf
.e3:    push    ax                      ; the cluster given back (a failed
        mov     ax, [new_dir]           ;  write: else a lost cluster once
        or      ax, ax                  ;  the FAT goes out)
        jz      .e4
        xor     dx, dx
        call    fat_set
.e4:    pop     ax
        jmp     .e
.acc:   mov     ax, 5
.e:     jmp     fail

section .bss
new_dir     resw 1
section .text

; the path names an existing directory -> AX = its cluster.  CF: AX
find_dir:
        call    resolve
        jc      .x
        mov     ax, [r_dir]
        cmp     byte [r_name], 0
        je      .ok
        cmp     byte [r_wild], 0
        jne     .np
        cmp     word [r_name], '. '
        je      .ok
        call    dir_find                ; (AX = r_dir; nm11 = r_name)
        jc      .np
        test    byte [de+11], A_DIR
        jz      .np
        mov     ax, [de+26]
.ok:    clc
.x:     ret
.np:    mov     ax, 3
        stc
        ret

f_3A:   call    get_path                ; RMDIR
        jc      .e
        call    find_dir
        jc      .nd
        mov     si, [actp]              ; the current directory (".", or the
        cmp     ax, [si+D_CWD]          ;  root from it): 16, as MS-DOS
        je      .cur
        cmp     byte [r_name], 0        ; after it: for "" and "." find_dir
        je      .acc                    ;  doesn't look the name up, so
        cmp     byte [r_name], '.'      ;  d_lba/d_off aren't the entry's
        je      .acc                    ;  (".." it finds, but is refused too)
        mov     [new_dir], ax
        push    word [d_lba]
        push    word [d_off]
        mov     bx, 2                   ; empty apart from "." and ".."?
.chk:   mov     ax, [new_dir]
        call    dir_entry
        jnc     .ck
        cmp     ax, 18
        je      .empty
        add     sp, 4                   ; a disk error
        jmp     .e
.ck:
        cmp     byte [si], 0
        je      .empty
        cmp     byte [si], 0E5h
        je      .nx
        cmp     byte [si+11], 0Fh       ; (a long name left by another
        jne     .full                   ;  system: not a title)
.nx:    inc     bx
        jmp     .chk
.full:  add     sp, 4
        mov     ax, 5
        jmp     .e
.empty: pop     word [d_off]
        pop     word [d_lba]
        mov     dx, [d_lba]
        mov     ax, [d_off]
        call    dent_buf
        jc      .e
        mov     byte [si], 0E5h
        call    buf_put
        jc      .e
        mov     ax, [new_dir]
        call    free_chain
        mov     word [it_dir], 0
        call    fat_flush_act
        jmp     ret_cf
.cur:   mov     ax, 16                  ; the current directory
        jmp     .e
.nd:    cmp     ax, 3                   ; a wildcard: 16 (MS-DOS's); the path
        jne     .e                      ;  there but its last name a file's or
        cmp     byte [r_wild], 1        ;  a device's: 5, not there: 3, as
        je      .cur                    ;  MS-DOS
        cmp     byte [r_name], 0
        je      .e
        call    find_named              ; (nm11: the last name still)
        jnc     .acc
        call    dev_lookup
        mov     ax, 3                   ; (CF kept)
        jc      .e
.acc:   mov     ax, 5
.e:     jmp     fail

f_3B:   call    get_path                ; CHDIR
        jc      .e
        call    find_dir
        jc      .e
        mov     [cwd_cl], ax
        ; the new path string, worked out whole in cwd_new, then the
        ; drive's own and its cluster changed if it fits: "\" and 63, as
        ; MS-DOS's (DIRSTRLEN: 47h's answer and its NUL fill the caller's
        ; 64 bytes).  Longer is 3, nothing changed; a path that goes down
        ; past that and back up ("X\..") is only the end that counts
        mov     al, [act]
        call    cwd_of
        mov     si, di
        mov     di, cwd_new
        mov     cx, CWDLEN / 2
        rep     movsw
        mov     di, cwd_new
        mov     si, path_buf
        cmp     byte [si+1], ':'
        jne     .nd
        add     si, 2
.nd:    cmp     byte [si], '\'
        jne     .rel
        mov     word [di], '\'          ; absolute: start at the root
        inc     si
.rel:   mov     [cwd_p], di
.comp:  lodsb                           ; (a doubled '\': nothing)
        cmp     al, '\'
        je      .comp
        or      al, al
        jz      .end
        dec     si
        call    parse_comp              ; -> nm11 (find_dir took the path, so
        mov     ax, [nm11]              ;  each part is a name, up to \ or 0)
        cmp     ax, '. '
        je      .comp
        cmp     ax, '..'
        jne     .add
        ; up one level: cut at the last '\'
        mov     di, [cwd_p]
        mov     cx, CWNEW
        xor     al, al
        push    di
        repne   scasb
        pop     cx                      ; CX = start
        dec     di
.bk:    cmp     di, cx
        jbe     .root
        dec     di
        cmp     byte [di], '\'
        jne     .bk
        cmp     di, cx
        je      .root
        mov     byte [di], 0
        jmp     .comp
.root:  mov     di, cx
        mov     word [di], '\'
        jmp     .comp
.add:   mov     di, [cwd_p]             ; append "\NAME.EXT", as MS-DOS keeps
        mov     cx, CWNEW               ;  it: 8.3, whatever was typed
        xor     al, al
        repne   scasb
        dec     di
        cmp     byte [di-1], '\'
        je      .cp
        mov     al, '\'
        stosb
.cp:    push    si
        push    di
        mov     si, nm11
        mov     di, cwd_nm
        call    name_out
        pop     di
        mov     si, cwd_nm
.cpl:   lodsb                           ; (it fits: each part comes out no
        stosb                           ;  longer than typed, path_buf 128)
        or      al, al
        jnz     .cpl
        pop     si
        jmp     .comp
.end:   mov     di, cwd_new             ; the whole: "\" and 63 at most
        mov     cx, CWDMAX + 1
        xor     al, al
        repne   scasb
        mov     ax, 3
        jne     .e                      ; (no NUL by then: too long)
        mov     al, [act]               ; it fits: the drive's
        call    cwd_of
        mov     si, cwd_new
        mov     cx, CWDLEN / 2
        rep     movsw
        mov     si, [actp]
        mov     ax, [cwd_cl]
        mov     [si+D_CWD], ax
        jmp     ok
.e:     jmp     fail

section .bss
cwd_p       resw 1
section .text
CWDMAX  equ 64                          ; "\" and 63, as MS-DOS's
CWNEW   equ 196                         ; (CWDMAX, then path_buf's 128 at
cwd_new equ path2_buf                   ;  most: CHDIR's, in K2, with rename's
cwd_nm  equ path2_buf + CWNEW           ;  and EXEC's places, which it never
cwd_cl  equ path2_buf + CWNEW + 14      ;  meets: the new string, a name for
        times -(CWNEW + 16 > KL_REL - KL_P2) db 0  ; it, the cluster)
        times -(CWDMAX + 1 > CWDLEN) db 0

f_47:   mov     al, [bp+F_DX]           ; current directory (no drive, no '\')
        call    drv_dflt
        call    drv_present
        jc      .bad
        call    cwd_of
        lea     si, [di+1]              ; (without the leading '\')
        mov     es, [bp+F_DS]
        mov     di, [bp+F_SI]
.c:     lodsb
        stosb
        or      al, al
        jnz     .c
        mov     ax, 0100h               ; (DOS returns this)
        jmp     ok_ax
.bad:   mov     ax, 15
        jmp     fail

f_56:   call    get_path                ; RENAME (files; same drive)
        jc      .e
        mov     si, [bp+F_DI]
        mov     di, path2_buf
        push    word [bp+F_DS]
        mov     ax, [bp+F_ES]
        mov     [bp+F_DS], ax
        call    gpath
        pop     word [bp+F_DS]
        jc      .e
        call    find_file               ; the old name (a device's: 5, as
        jc      f_41.nf                 ;  MS-DOS, DELETE's answer)
        test    byte [de+11], A_DIR | A_VOL
        jnz     .acc
        call    sft_busy
        jc      .acc
        mov     al, [r_drv]
        mov     [ren_drv], al
        mov     si, d_lba               ; d_lba, d_off, de
        mov     di, ren_lba
        mov     cx, 18
        rep     movsw
        mov     si, path2_buf
        call    resolve_si              ; the new name
        jc      .e
        mov     ax, path2_buf           ; a device's name (its directory
        call    dev_look_ax             ;  there): 5, as MS-DOS
        jnc     .acc
        mov     al, [r_drv]
        cmp     al, [ren_drv]
        jne     .dev
        call    new_name
        jc      .e
        call    find_named
        jnc     .acc                    ; the new name exists
        cmp     ax, 2
        jne     .e
        mov     ax, [r_dir]
        call    dir_slot
        jc      .e
        call    fat_flush_act           ; a grown target linked before it is named
        jc      .e
        mov     di, si                  ; the old entry, renamed, in the slot
        push    si
        mov     si, ren_de
        mov     cx, 16
        rep     movsw
        pop     si
        mov     di, si
        push    si
        mov     si, r_name
        mov     cx, 11
        rep     movsb
        pop     si
        mov     ax, [d_off]             ; the old one in the same sector:
        xor     ax, [ren_off]           ;  deleted in the same write (else
        and     ax, 0FE00h              ;  the two entries name one chain
        jnz     .two                    ;  between the writes, as MS-DOS's)
        mov     ax, [d_lba]
        cmp     ax, [ren_lba]
        jne     .two
        mov     bx, si
        mov     ax, [d_off]
        and     ax, 511
        sub     bx, ax
        mov     ax, [ren_off]
        and     ax, 511
        add     bx, ax
        mov     byte [bx], 0E5h
        call    buf_put
        jmp     ret_cf
.two:   call    buf_put
        jc      .e
        mov     dx, [ren_lba]           ; and the old one deleted
        mov     ax, [ren_off]
        call    dent_buf
        jc      .un
        mov     byte [si], 0E5h
        call    buf_put
        jnc     .ok
.un:    push    ax                      ; (not: the new one taken out again,
        mov     dx, [d_lba]             ;  if it can be, so no two entries
        mov     ax, [d_off]             ;  name the chain)
        call    dent_buf
        jc      .unx
        mov     byte [si], 0E5h
        call    buf_put
.unx:   pop     ax
        stc
.ok:    jmp     ret_cf
.dev:   mov     ax, 17                  ; not the same device
        jmp     .e
.acc:   mov     ax, 5
.e:     jmp     fail
        times   -(de != d_off + 2 || ren_off != ren_lba + 2 || ren_de != ren_off + 2) db 0

; (rename's block, in the INT 21h stack's low area: KCORE.INC, K2)
ren_lba     equ KL_REN          ; d_lba, d_off and de, copied in one go
ren_off     equ KL_REN + 2
ren_de      equ KL_REN + 4
ren_de_end  equ ren_de + 32     ; (EXEC's ex_hdr: KPROC.INC)
ren_drv     equ ren_de_end
