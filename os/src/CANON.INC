; CANON.INC - a path made whole, for ATTRIB, XCOPY and TREE (Lodestone
; has no INT 21h 60h): the path at SI (ASCIIZ: a drive or not, a "\" first
; or not, "." and ".." anywhere, "/" as "\") -> cpath, "D:\DIR\SUB" from
; the drive's root (the root itself "D:\"), upper case, no "\" last.
; A relative path goes on from the drive's current directory (INT 21h
; 47h).  CF: DX = message (an invalid drive, a path over DOS's 64).
; Needs upcase; the caller puts CANON_BSS in its BSS.
%macro CANON_BSS 0
cdrv    resb 1
cpath   resb 84
tmp     resb 68
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
        je      .comps                  ; (the root's parent: the root)
.bk:    dec     di
        cmp     byte [di-1], '\'
        jne     .bk
        cmp     di, [croot]
        je      .comps
        dec     di
        jmp     .comps
.dot:   inc     si
        jmp     .comps
.name:  cmp     di, [croot]             ; "\" between parts
        je      .c
        mov     byte [di], '\'
        inc     di
.c:     lodsb
        or      al, al
        jz      .last
        cmp     al, '\'
        je      .end
        cmp     al, '/'
        je      .end
        call    upcase
        mov     [di], al
        inc     di
        cmp     di, cpath + 3 + 64      ; DOS's 64 after the root
        jb      .c
        mov     dx, s_long
        stc
        ret
.last:  dec     si
.end:   jmp     .comps
.done:  clc
        ret

s_baddrv db 'Invalid drive specification', 13, 10, '$'
s_long  db 'Path too long', 13, 10, '$'
