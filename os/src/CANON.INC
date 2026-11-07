; CANON.INC - a path made whole, for ATTRIB, XCOPY and TREE (Lodestone
; has no INT 21h 60h): the path at SI (ASCIIZ: a drive or not, a "\" first
; or not, "." and ".." anywhere, "/" as "\") -> cpath, "D:\DIR\SUB" from
; the drive's root (the root itself "D:\"), upper case, no "\" last.
; A relative path goes on from the drive's current directory (INT 21h
; 47h).  Each part is cut as the kernel's parse cuts it (part83), so two
; spellings of one directory come out the same.  CF: DX = message (an
; invalid drive, ".." from the root, which the kernel refuses too, a
; path past CMAX: the longest directory, and a name in it).  cdir: CF
; if cpath is too long for a directory.
; Needs upcase; the caller puts CANON_BSS in its BSS.
PMAX    equ 65                          ; after "D:\": a directory's (the
CMAX    equ PMAX + 13                   ;  kernel's CWDLEN 68), and a file's
%macro CANON_BSS 0
cdrv    resb 1
cpath   resb 3 + CMAX + 1
tmp     resb 68
cpart   resb 14
        alignb 2
croot   resw 1
%endmacro

canon:  push    ax
        push    bx
        push    cx
        push    si
        push    di
        mov     ah, 19h                 ; the drive: the current, or given
        int     21h
        mov     [cdrv], al
        cmp     byte [si+1], ':'
        jne     .nd
        mov     al, [si]
        call    upcase
        sub     al, 'A'
        cmp     al, 25
        ja      .inv
        mov     [cdrv], al
        add     si, 2
.nd:    mov     di, cpath
        mov     al, [cdrv]
        add     al, 'A'
        mov     ah, ':'
        stosw
        mov     al, '\'
        stosb
        mov     [croot], di
        push    si                      ; (the drive there?  and its current
        mov     si, tmp                 ;  directory, for a relative path)
        mov     dl, [cdrv]
        inc     dx
        mov     ah, 47h
        int     21h
        pop     si
        jc      .inv
        mov     al, [si]
        cmp     al, '\'
        je      .abs
        cmp     al, '/'
        je      .abs
        push    si
        mov     si, tmp
        call    .comps
        pop     si
        jc      .x
        jmp     short .rest
.abs:   inc     si
.rest:  call    .comps
        jc      .x
        mov     byte [di], 0
        clc
.x:     pop     di
        pop     si
        pop     cx
        pop     bx
        pop     ax
        ret
.inv:   mov     dx, s_baddrv
        stc
        jmp     .x

; the parts at SI onto DI (cpath's end), "." and ".." taken as they mean.
; CF: DX (too long)
.comps: mov     al, [si]
        cmp     al, '\'
        je      .sep
        cmp     al, '/'
        jne     .part
.sep:   inc     si
        jmp     .comps
.part:  or      al, al
        jz      .done
        cmp     al, '.'                 ; "." or ".."?
        jne     .name
        mov     ah, [si+1]
        or      ah, ah
        jz      .dot
        cmp     ah, '\'
        je      .dot
        cmp     ah, '/'
        je      .dot
        cmp     ah, '.'
        jne     .name
        mov     ah, [si+2]
        or      ah, ah
        jz      .up
        cmp     ah, '\'
        je      .up
        cmp     ah, '/'
        jne     .name
.up:    add     si, 2                   ; "..": the last part off
        cmp     di, [croot]
        je      .nop                    ; (the root has no parent)
.bk:    dec     di
        cmp     byte [di-1], '\'
        jne     .bk
        cmp     di, [croot]
        je      .comps
        dec     di
        jmp     .comps
.dot:   inc     si
        jmp     .comps
.name:  push    di                      ; the part, 8.3
        mov     di, cpart
        call    part83
        mov     cx, di
        sub     cx, cpart
        pop     di
        jcxz    .comps                  ; (nothing of it left: "...")
        mov     ax, di                  ; room for it (and a "\" first)?
        cmp     di, [croot]
        je      .nb
        inc     ax
.nb:    add     ax, cx
        cmp     ax, cpath + 3 + CMAX
        ja      .long
        cmp     di, [croot]
        je      .cp
        mov     al, '\'
        stosb
.cp:    push    si
        mov     si, cpart
        rep     movsb
        pop     si
        jmp     .comps
.done:  clc
        ret
.long:  mov     dx, s_long
        stc
        ret
.nop:   mov     dx, s_nopath
        stc
        ret

; cpath a directory: CF (DX) if past PMAX after "D:\"
cdir:   push    ax
        push    cx
        push    di
        mov     di, cpath
        mov     cx, 3 + CMAX + 1
        xor     al, al
        repne   scasb                   ; (DI past its 0)
        mov     ax, cpath + 3 + PMAX + 1
        cmp     ax, di
        pop     di
        pop     cx
        pop     ax
        mov     dx, s_long
        ret

; the path part at SI (to a "\", "/" or 0) -> DI as the kernel's parse
; takes it: the name's first 8 characters and the extension's first 3
; (the rest left out, a "." with nothing after it dropped), upper case,
; ASCIIZ (DI at its 0); "." and ".." as they are.  SI: past the part
part83: push    cx
        cmp     byte [si], '.'
        jne     .n
        mov     al, [si+1]
        call    .term
        je      .d1
        cmp     al, '.'
        jne     .n
        mov     al, [si+2]
        call    .term
        jne     .n
        movsb                           ; ".."
.d1:    movsb                           ; "."
        jmp     short .z
.n:     mov     cx, 8
        call    .fld
        cmp     byte [si], '.'
        jne     .sk
        inc     si
        mov     al, [si]
        call    .term
        je      .z
        cmp     al, '.'
        je      .sk
        mov     al, '.'
        stosb
        mov     cx, 3
        call    .fld
.sk:    mov     al, [si]                ; (past 8.3: left out)
        call    .term
        je      .z
        inc     si
        jmp     .sk
.z:     mov     byte [di], 0
        pop     cx
        ret
.fld:   mov     al, [si]                ; CX characters at most, to a "."
        call    .term
        je      .fx
        cmp     al, '.'
        je      .fx
        inc     si
        jcxz    .fld
        call    upcase
        stosb
        dec     cx
        jmp     .fld
.fx:    ret
.term:  or      al, al                  ; ZF: AL ends a part
        jz      .t
        cmp     al, '\'
        je      .t
        cmp     al, '/'
.t:     ret

s_baddrv db 'Invalid drive specification', 13, 10, '$'
s_long  db 'Path too long', 13, 10, '$'
s_nopath db 'Path not found', 13, 10, '$'
