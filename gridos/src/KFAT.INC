; =====================================================================
;  KFAT.INC - names, paths and directories on FAT12, and the INT 21h
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
path2_buf   resb 130
nm11        resb 11             ; a parsed name component
r_drv       resb 1              ; resolved path: drive,
            alignb 2
r_dir       resw 1              ;   directory cluster (0 = root),
r_name      resb 11             ;   last component (0 = none)
r_wild      resb 1              ;   it has wildcards
d_lba       resw 1              ; the directory entry found: sector,
d_off       resw 1              ;   offset in it,
d_index     resw 1              ;   index in its directory
de          resb 32             ; a copy of it
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

; copy the caller's ASCIIZ path DS:DX (frame) to path_buf (uppercase,
; '/' -> '\').  CF: AX = 3 if empty or too long
get_path:
        mov     si, [bp+F_DX]
        mov     di, path_buf
gpath:  push    ds
        mov     ds, [bp+F_DS]
        mov     cx, 128
.l:     lodsb
        cmp     al, 'a'
        jb      .n
        cmp     al, 'z'
        ja      .n
        sub     al, 20h
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
        jne     .ext0
        cmp     byte [si], '.'
        jne     .bad
.ext0:  cmp     byte [si], '.'
        jne     .ok
        inc     si
        mov     di, nm11 + 8
        mov     cx, 3
        call    .field
        jc      .bad
.ok:    mov     al, ah
        clc
        jmp     .x
.bad:   stc
.x:     pop     di
        pop     cx
        ret
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
.chk:   push    di
        push    cx
        push    ax
        mov     di, badchars
        mov     cx, NBADC
        repne   scasb
        pop     ax
        pop     cx
        pop     di
        je      .err
        cmp     al, ' '
        jbe     .err
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
badchars db '"+,/:;<=>[]|'
NBADC   equ $ - badchars

; resolve path_buf (or SI) -> r_drv, r_dir, r_name, r_wild.
; Gets the drive ready and its FAT loaded.  CF: AX = error (3 or 15)
resolve:
        mov     si, path_buf
resolve_si:
        mov     word [it_dir], 0
        mov     al, [cur_drv]
        cmp     byte [si+1], ':'
        jne     .d
        mov     al, [si]
        sub     al, 'A'
        add     si, 2
.d:     push    si
        call    drv_ready
        mov     bx, si
        pop     si
        jc      .x
        mov     al, [act]
        mov     [r_drv], al
        call    fat_load
        jc      .x
        mov     bx, [actp]
        mov     ax, [bx+D_CWD]
        cmp     byte [si], '\'
        jne     .c
        xor     ax, ax
        inc     si
.c:     mov     [r_dir], ax
        mov     byte [r_name], 0
        mov     byte [r_wild], 0
.comp:  cmp     byte [si], 0
        je      .ok
        call    parse_comp
        jc      .np
        cmp     byte [si], '\'
        jne     .last
        inc     si
        or      al, al
        jnz     .np
        cmp     word [nm11], '. '
        je      .comp
        push    si
        mov     ax, [r_dir]
        mov     cl, A_DIR
        call    dir_find
        pop     si
        jc      .npe
        test    byte [de+11], A_DIR
        jz      .np
        mov     ax, [de+26]
        mov     [r_dir], ax
        jmp     .comp
.npe:   cmp     ax, 2
        je      .np
        stc                             ; a disk error
        ret
.last:  mov     [r_wild], al
        push    si
        mov     si, nm11
        mov     di, r_name
        mov     cx, 11
        rep     movsb
        pop     si
.ok:    clc
        ret
.np:    mov     ax, 3
        stc
.x:     ret

; entry BX of directory AX -> SI (in a sector buffer), d_lba, d_off.
; CF: past the end of the directory (AX = 18) or a disk error
dir_entry:
        push    bx
        push    cx
        push    dx
        push    di
        mov     [d_index], bx
        mov     di, [actp]
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
        cmp     ax, [it_dir]
        jne     .walk0
        cmp     dx, [it_ci]
        jb      .walk0
        mov     ax, [it_cl]
        mov     cx, [it_ci]
        jmp     .walk
.walk0: mov     [it_dir], ax
        xor     cx, cx
.walk:  cmp     cx, dx
        je      .there
        call    fat_get
        cmp     ax, 0FF0h
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
.rd:    mov     [d_lba], dx
        mov     al, [act]
        call    buf_get
        mov     word [io_ra], 0         ; (a buffer hit leaves it set)
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
        mov     [d_off], bx
        add     si, bx
        clc
        jmp     .x
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

; drive [act]'s whole root directory into the disk cache, one pass (if
; it isn't there already; errors are left to the reads that follow).
; DI = drive table entry
root_pre:
        push    ax
        push    bx
        push    cx
        push    dx
        push    es
        push    cs
        pop     es
        mov     bx, bounce
        mov     ax, [di+D_RSEC]
        dec     ax
        mov     [io_ra], ax
        mov     dx, [di+D_ROOT]
        mov     cx, 1
        mov     al, [act]
        mov     ah, 2
        call    disk_io_raw
        pop     es
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

; find nm11 (wildcards allowed) in directory AX.  CL = attributes the
; caller accepts beyond plain files (A_DIR, A_HID, A_SYS); volume labels
; never match.  -> BX = index, SI = entry, de = copy.  CF: AX = 2
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
        mov     [d_index], bx           ; (found further into the sector)
        mov     dx, bx
        and     dx, 15
        shl     dx, 5
        mov     [d_off], dx
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
        cmp     ax, 0FF0h
        jb      .last
        call    clu_alloc               ; linked after DX
        jc      .err
        call    clu_zero
        jc      .err
        mov     word [it_dir], 0
        pop     ax
        push    ax
        call    dir_entry               ; BX = first entry of the new cluster
        jc      .err
        pop     ax
        clc
        ret
.full:  mov     ax, 5
.err:   add     sp, 2
        stc
        ret

; write zeros over cluster AX (keeps AX)
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
        pop     ax
        call    clu2lba
        mov     dx, ax
        mov     si, [actp]
        mov     cl, [si+D_SPC]
        xor     ch, ch
        mov     al, [act]
        call    buf_inval_range
.w:     push    cx
        mov     al, [act]
        mov     ah, 3
        mov     cx, 1
        mov     bx, bounce
        call    disk_io
        pop     cx
        jc      .x
        inc     dx
        loop    .w
        clc
.x:     pop     es
        pop     di
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        pop     si
        ret

; a fresh directory entry at SI: name r_name, attribute CL, cluster AX,
; size 0, stamped now.  Then written to disk.  CF: AX = error
new_entry:
        push    di
        push    cx
        push    ax
        mov     di, si
        push    si
        mov     si, r_name
        mov     cx, 11
        rep     movsb
        pop     si
        pop     ax
        pop     cx
        mov     [si+11], cl
        push    di
        lea     di, [si+12]
        push    ax
        push    cx
        mov     cx, 5
        xor     ax, ax
        rep     stosw
        pop     cx
        pop     ax
        pop     di
        mov     [si+26], ax
        mov     word [si+28], 0
        mov     word [si+30], 0
        push    ax
        push    dx
        call    dos_stamp
        mov     [si+22], ax
        mov     [si+24], dx
        pop     dx
        pop     ax
        pop     di
        jmp     buf_put

; DS:SI entry name -> ES:DI "NAME.EXT",0
name_out:
        push    cx
        push    si
        mov     cx, 8
.n:     lodsb
        cmp     al, ' '
        je      .ne
        stosb
        loop    .n
        jmp     .e
.ne:    dec     cx
        add     si, cx
.e:     cmp     byte [si], ' '
        je      .z
        mov     al, '.'
        stosb
        mov     cx, 3
.x:     lodsb
        cmp     al, ' '
        je      .z
        stosb
        loop    .x
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
        jc      .x
        cmp     byte [r_name], 0
        je      .nf
        cmp     byte [r_wild], 0
        jne     .nf
        mov     si, r_name
        mov     di, nm11
        mov     cx, 11
        rep     movsb
        mov     ax, [r_dir]
        mov     cl, A_HID | A_SYS | A_DIR
        call    dir_find
.x:     ret
.nf:    mov     ax, 2
        stc
        ret

f_41:   call    get_path                ; DELETE
        jc      .e
        call    find_file
        jc      .e
        test    byte [de+11], A_DIR | A_RO | A_VOL
        jnz     .acc
        call    sft_busy                ; open?  then refuse
        jc      .acc
        mov     byte [si], 0E5h
        call    buf_put
        jc      .e
        mov     ax, [de+26]
        call    free_chain
        call    fat_flush
        jc      .e
        jmp     ok
.acc:   mov     ax, 5
.e:     jmp     fail

f_43:   call    get_path                ; get/set attributes
        jc      .e
        call    find_file
        jc      .e
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
        jnz     .acc
        mov     ah, [si+11]
        and     ah, A_DIR
        or      al, ah
        mov     [si+11], al
        call    buf_put
        jc      .e
        jmp     ok
.bad:   mov     ax, 1
        jmp     .e
.acc:   mov     ax, 5
.e:     jmp     fail

f_39:   call    get_path                ; MKDIR
        jc      .e
        call    resolve
        jc      .e
        cmp     byte [r_name], 0
        je      .acc
        cmp     byte [r_wild], 0
        jne     .np
        cmp     byte [r_name], '.'
        je      .acc
        mov     si, r_name
        mov     di, nm11
        mov     cx, 11
        rep     movsb
        mov     ax, [r_dir]
        mov     cl, A_HID | A_SYS | A_DIR
        call    dir_find
        jnc     .acc                    ; already there
        cmp     ax, 2
        jne     .e
        mov     ax, [r_dir]
        call    dir_slot
        jc      .e
        push    bx
        push    word [d_lba]
        push    word [d_off]
        xor     dx, dx
        call    clu_alloc
        jc      .e3
        call    clu_zero
        jc      .e3
        mov     [new_dir], ax
        call    fat_flush               ; its cluster is taken before it is named
        jc      .e3
        pop     word [d_off]
        pop     word [d_lba]
        pop     bx
        mov     al, [act]
        mov     dx, [d_lba]
        call    buf_get                 ; the parent's slot again
        jc      .e
        add     si, [d_off]
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
        call    fat_flush
        jc      .e
        jmp     ok
.e3:    add     sp, 6
        jmp     .e
.np:    mov     ax, 3
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
        mov     si, r_name
        mov     di, nm11
        mov     cx, 11
        rep     movsb
        cmp     word [nm11], '. '
        je      .ok
        mov     ax, [r_dir]
        mov     cl, A_DIR | A_HID | A_SYS
        call    dir_find
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
        call    resolve
        jc      .e
        cmp     byte [r_name], 0
        je      .acc
        cmp     byte [r_name], '.'
        je      .acc
        mov     si, r_name
        mov     di, nm11
        mov     cx, 11
        rep     movsb
        mov     ax, [r_dir]
        mov     cl, A_DIR | A_HID | A_SYS
        call    dir_find
        jc      .np
        test    byte [de+11], A_DIR
        jz      .np
        mov     ax, [de+26]
        mov     si, [actp]
        cmp     ax, [si+D_CWD]
        je      .cur
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
        jne     .full
        inc     bx
        jmp     .chk
.full:  add     sp, 4
        mov     ax, 5
        jmp     .e
.empty: pop     word [d_off]
        pop     word [d_lba]
        mov     al, [act]
        mov     dx, [d_lba]
        call    buf_get
        jc      .e
        add     si, [d_off]
        mov     byte [si], 0E5h
        call    buf_put
        jc      .e
        mov     ax, [new_dir]
        call    free_chain
        mov     word [it_dir], 0
        call    fat_flush
        jc      .e
        jmp     ok
.cur:   mov     ax, 16                  ; the current directory
        jmp     .e
.np:    mov     ax, 3
        jmp     .e
.acc:   mov     ax, 5
.e:     jmp     fail

f_3B:   call    get_path                ; CHDIR
        jc      .e
        call    find_dir
        jc      .e
        mov     si, [actp]
        mov     [si+D_CWD], ax
        ; the new path string
        mov     al, [act]
        xor     ah, ah
        imul    di, ax, CWDLEN
        add     di, cwdstr
        mov     si, path_buf
        cmp     byte [si+1], ':'
        jne     .nd
        add     si, 2
.nd:    cmp     byte [si], '\'
        jne     .rel
        mov     word [di], '\'          ; absolute: start at the root
        inc     si
.rel:   mov     [cwd_p], di
.comp:  cmp     byte [si], 0
        je      .end
        mov     bx, si                  ; component start
.f:     lodsb
        or      al, al
        jz      .ce
        cmp     al, '\'
        jne     .f
.ce:    dec     si
        mov     cx, si
        sub     cx, bx                  ; length
        cmp     byte [si], '\'
        jne     .ap
        inc     si
.ap:    jcxz    .comp
        cmp     cx, 1
        jne     .dd
        cmp     byte [bx], '.'
        je      .comp
.dd:    cmp     cx, 2
        jne     .add
        cmp     word [bx], '..'
        jne     .add
        ; up one level: cut at the last '\'
        mov     di, [cwd_p]
        push    cx
        mov     cx, CWDLEN
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
        pop     cx
        jmp     .comp
.root:  mov     di, cx
        mov     word [di], '\'
        pop     cx
        jmp     .comp
.add:   mov     di, [cwd_p]             ; append "\NAME"
        push    cx
        mov     cx, CWDLEN
        xor     al, al
        repne   scasb
        pop     cx
        dec     di
        cmp     byte [di-1], '\'
        je      .cp
        mov     al, '\'
        stosb
.cp:    push    si
        mov     si, bx
        mov     ax, [cwd_p]
        add     ax, CWDLEN - 2
.cpl:   cmp     di, ax
        jae     .cpx
        movsb
        loop    .cpl
.cpx:   mov     byte [di], 0
        pop     si
        jmp     .comp
.end:   jmp     ok
.e:     jmp     fail

section .bss
cwd_p       resw 1
section .text

f_47:   mov     al, [bp+F_DX]           ; current directory (no drive, no '\')
        or      al, al
        jnz     .d
        mov     al, [cur_drv]
        inc     al
.d:     dec     al
        call    drv_present
        jc      .bad
        xor     ah, ah
        imul    si, ax, CWDLEN
        add     si, cwdstr
        inc     si                      ; skip the leading '\'
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
        call    find_file               ; the old name
        jc      .e
        test    byte [de+11], A_DIR | A_VOL
        jnz     .acc
        call    sft_busy
        jc      .acc
        mov     al, [r_drv]
        mov     [ren_drv], al
        mov     ax, [d_lba]
        mov     [ren_lba], ax
        mov     ax, [d_off]
        mov     [ren_off], ax
        mov     si, de
        mov     di, ren_de
        mov     cx, 16
        rep     movsw
        mov     si, path2_buf
        call    resolve_si              ; the new name
        jc      .e
        mov     al, [r_drv]
        cmp     al, [ren_drv]
        jne     .dev
        cmp     byte [r_name], 0
        je      .acc
        cmp     byte [r_wild], 0
        jne     .acc
        mov     si, r_name
        mov     di, nm11
        mov     cx, 11
        rep     movsb
        mov     ax, [r_dir]
        mov     cl, A_HID | A_SYS | A_DIR
        call    dir_find
        jnc     .acc                    ; the new name exists
        cmp     ax, 2
        jne     .e
        mov     ax, [r_dir]
        call    dir_slot
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
        call    buf_put
        jc      .e
        mov     al, [act]               ; and the old one deleted
        mov     dx, [ren_lba]
        call    buf_get
        jc      .e
        add     si, [ren_off]
        mov     byte [si], 0E5h
        call    buf_put
        jc      .e
        call    fat_flush               ; (the target may have grown)
        jc      .e
        jmp     ok
.dev:   mov     ax, 17                  ; not the same device
        jmp     .e
.acc:   mov     ax, 5
.e:     jmp     fail

section .bss
ren_drv     resb 1
            alignb 2
ren_lba     resw 1
ren_off     resw 1
ren_de      resb 32
section .text
