; ATTRIB.COM - shows or changes files' attributes (DOS 3.30's ATTRIB, and
; DOS 5's hidden and system bits)
;
;   ATTRIB [+R|-R] [+A|-A] [+H|-H] [+S|-S] [d:][path][name] [/S]
;
;   +R -R   read-only        +A -A   archive
;   +H -H   hidden           +S -S   system (DOS 5's: Lodestone has no
;                            other way to show or clear them)
;   name    wildcards as DIR's; *.* if none.  Directories and the volume
;           label are never touched
;   /S      the files matching in every directory below too
;
; With no + or -, each file is listed as DOS 5 lists it, the bits it has
; in the first columns:
;   A  SHR  A:\SUB\NAME.EXT
; With them, each file matching gets them (INT 21h 4301h), and nothing is
; printed but errors.  Hidden and system files are found too, but, as DOS
; 5's, changed only by a command that changes H or S: otherwise "Not
; resetting hidden file - A:\X".  Paths are shown whole, from the drive's
; root, each part 8.3 as the kernel reads it.  A directory whose path
; would pass 65 characters after "D:\" is said ("Path too long - ") and
; left out.
;
; Exit code: 0 done, 1 something failed (no file found, a bad switch, a
; file that refused or wasn't changed, a path too long: each said).
cpu 286
org 100h

MAXDEPTH equ 34                         ; (PMAX's 65: "X\" 32 times at most)
DTASZ   equ 44

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        call    args
        jc      fail
        mov     si, spec                ; the directory, absolute, and the
        call    split                   ;  name: dir (with "\" last), pat
        jc      fail
        mov     word [depth], 0
        call    walk
        cmp     word [nfound], 0
        jne     .done
        mov     dx, s_nf                ; "File not found - X"
        call    print
        mov     si, spec
        call    puts
        call    crlf
        mov     byte [err], 1
.done:  mov     al, [err]
        mov     ah, 4Ch
        int     21h
fail:   call    print
        mov     ax, 4C01h
        int     21h

; ---------------------------------------------------------------------
; command tail: + and - bits, /S, the name.  CF: DX = message
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
.l:     lodsb
        cmp     al, 13
        je      .end
        cmp     al, ' '
        je      .l
        cmp     al, 9
        je      .l
        cmp     al, '+'
        je      .bit
        cmp     al, '-'
        je      .bit
        cmp     al, '/'
        je      .sw
        cmp     byte [spec], 0          ; the name (one)
        jne     .bad
        dec     si
        mov     di, spec
        mov     cx, 80
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        cmp     al, '/'
        je      .ne
        call    upcase
        stosb
        loop    .n
        jmp     short .bad
.ne:    dec     si
        mov     byte [di], 0
        jmp     .l
.bit:   mov     ah, al                  ; AH = + or -
        lodsb
        call    upcase
        mov     bl, 1
        cmp     al, 'R'
        je      .b
        mov     bl, 2
        cmp     al, 'H'
        je      .b
        mov     bl, 4
        cmp     al, 'S'
        je      .b
        mov     bl, 20h
        cmp     al, 'A'
        jne     .bad
.b:     cmp     ah, '+'
        jne     .clr
        or      [aset], bl
        jmp     .l
.clr:   or      [aclr], bl
        jmp     .l
.sw:    lodsb
        call    upcase
        cmp     al, 'S'
        jne     .bad
        mov     byte [subs], 1
        jmp     .l
.end:   mov     al, [aset]              ; (+R -R together: no)
        test    al, [aclr]
        jnz     .bad
        cmp     byte [spec], 0
        jne     .ok
        mov     word [spec], '*.'
        mov     word [spec+2], '*'
.ok:    clc
        ret
.bad:   mov     dx, s_badsw
        stc
        ret

; ---------------------------------------------------------------------
; the directory at [dir] (absolute, "\" last) and those below it with /S:
; each file in it matching [pat]
walk:   mov     ax, [depth]             ; this level's DTA
        mov     bx, DTASZ
        mul     bx
        add     ax, dtas
        mov     [dta], ax
        mov     dx, ax
        mov     ah, 1Ah
        int     21h
        mov     si, pat                 ; dir + pat
        call    dir_add
        mov     dx, dir
        mov     cx, 06h                 ; (hidden and system too)
        mov     ah, 4Eh
        int     21h
.f:     jc      .sub
        mov     bx, [dta]
        test    byte [bx+21], 18h       ; (no directories, no label)
        jnz     .fn
        inc     word [nfound]
        lea     si, [bx+30]             ; the file's path: dir + its name
        call    dir_add
        call    one
.fn:    mov     ah, 4Fh
        int     21h
        jmp     .f
.sub:   cmp     byte [subs], 0          ; /S: each directory in it (no
        je      .x                      ;  deeper than PMAX lets it:
        mov     si, s_all               ;  MAXDEPTH's DTAs)
        call    dir_add
        mov     dx, dir
        mov     cx, 16h
        mov     ah, 4Eh
        int     21h
.d:     jc      .x
        mov     bx, [dta]
        test    byte [bx+21], 10h
        jz      .dn
        cmp     byte [bx+30], '.'
        je      .dn
        push    word [dirlen]
        lea     si, [bx+30]             ; into it: dir + NAME + "\"
        call    dir_add
        mov     si, [dirend]
        cmp     si, 3 + PMAX
        ja      .long
        mov     byte [dir+si], '\'
        inc     si
        mov     byte [dir+si], 0
        mov     [dirlen], si
        inc     word [depth]
        call    walk
        dec     word [depth]
.dl:    pop     word [dirlen]
        mov     ax, [depth]             ; (ours again: the DTA for 4Fh)
        mov     bx, DTASZ
        mul     bx
        add     ax, dtas
        mov     [dta], ax
        mov     dx, ax
        mov     ah, 1Ah
        int     21h
.dn:    mov     ah, 4Fh
        int     21h
        jmp     .d
.x:     ret
.long:  mov     byte [err], 1           ; "Path too long - A:\SUB\NAME"
        mov     dx, s_long2
        call    print
        mov     si, dir
        call    puts
        call    crlf
        jmp     .dl

; ASCIIZ at SI after dir's first [dirlen] characters -> [dirend], CF if
; too long (it isn't then added: dir's directory and an 8.3 name always
; fit, PMAX's 65 after "D:\" and 13)
dir_add:
        mov     di, [dirlen]
        mov     bx, di
.l:     lodsb
        cmp     di, 82
        jae     .long
        mov     [dir+di], al
        inc     di
        or      al, al
        jnz     .l
        dec     di
        mov     [dirend], di
        clc
        ret
.long:  mov     byte [dir+bx], 0
        mov     [dirend], bx
        stc
        ret

; the file at dir (its DTA at [dta]): listed, or its bits changed
one:    mov     bx, [dta]
        mov     al, [bx+21]
        mov     ah, [aset]
        or      ah, [aclr]
        jnz     .set
        mov     ah, ' '                 ; "A  SHR  A:\SUB\NAME.EXT"
        test    al, 20h
        jz      .a
        mov     ah, 'A'
.a:     mov     [line], ah
        mov     word [line+1], '  '
        mov     ah, ' '
        test    al, 4
        jz      .s
        mov     ah, 'S'
.s:     mov     [line+3], ah
        mov     ah, ' '
        test    al, 2
        jz      .h
        mov     ah, 'H'
.h:     mov     [line+4], ah
        mov     ah, ' '
        test    al, 1
        jz      .r
        mov     ah, 'R'
.r:     mov     [line+5], ah
        mov     word [line+6], '  '
        mov     byte [line+8], '$'
        mov     dx, line
        call    print
        mov     si, dir
        call    puts
        jmp     crlf
.set:   test    al, 6                   ; hidden or system: only if H or
        jz      .ch                     ;  S is changed (DOS 5's)
        mov     ah, [aset]
        or      ah, [aclr]
        test    ah, 6
        jnz     .ch
        mov     dx, s_nrsys
        test    al, 4
        jnz     .e1
        mov     dx, s_nrhid
.e1:    mov     byte [err], 1
        jmp     short .e
.ch:    and     al, 27h                 ; the bits a file may have
        mov     cl, [aclr]
        not     cl
        and     al, cl
        or      al, [aset]
        xor     ah, ah
        mov     cx, ax
        mov     dx, dir
        mov     ax, 4301h
        int     21h
        jnc     .x
        mov     byte [err], 1           ; "Access denied - A:\X.TXT"
        mov     dx, s_deny
        cmp     ax, 5
        je      .e
        mov     dx, s_fail
.e:     call    print
        mov     si, dir
        call    puts
        call    crlf
.x:     ret

; ---------------------------------------------------------------------
; the name at SI: its directory, absolute ([dir], "\" last, [dirlen]) and
; its last part ([pat]).  CF: DX = message
split:  mov     di, si                  ; the last "\" or ":"
        xor     bx, bx
.l:     lodsb
        or      al, al
        jz      .e
        cmp     al, '\'
        je      .m
        cmp     al, ':'
        jne     .l
.m:     mov     bx, si
        jmp     .l
.e:     or      bx, bx
        jz      .nod
        mov     si, bx                  ; the name: from there (8.3)
        mov     di, pat
        call    part83
        mov     al, [bx]                ; (the directory part alone)
        push    ax
        mov     byte [bx], 0
        mov     si, spec
        call    canon
        pop     ax
        mov     [bx], al
        jmp     short .d
.nod:   mov     si, spec                ; no directory: the current one
        mov     di, pat
        call    part83
        mov     si, s_empty
        call    canon
.d:     jc      .x
        cmp     byte [pat], 0
        jne     .p
        mov     word [pat], '*.'
        mov     word [pat+2], '*'
.p:     call    cdir
        jc      .x
        mov     si, cpath               ; dir = canon + "\" (the root has one)
        mov     di, dir
.cp:    lodsb
        stosb
        or      al, al
        jnz     .cp
        dec     di
        cmp     byte [di-1], '\'
        je      .r
        mov     byte [di], '\'
        inc     di
        mov     byte [di], 0
.r:     sub     di, dir
        mov     [dirlen], di
        clc
.x:     ret

; the path at SI (ASCIIZ, a drive and directories, as typed) -> cpath:
; "D:\DIR\SUB", from the root, . and .. gone, upper case.  CF: DX
%include "CANON.INC"

; ---------------------------------------------------------------------
upcase: cmp     al, 'a'
        jb      .x
        cmp     al, 'z'
        ja      .x
        sub     al, 20h
.x:     ret
print:  mov     ah, 9
        int     21h
        ret
crlf:   mov     dx, s_crlf
        jmp     print
; ASCIIZ at SI (it may hold a $)
puts:   lodsb
        or      al, al
        jz      .x
        mov     dl, al
        mov     ah, 2
        int     21h
        jmp     puts
.x:     ret

s_all   db '*.*', 0
s_empty db 0
s_nf    db 'File not found - $'
s_deny  db 'Access denied - $'
s_fail  db 'Cannot change - $'
s_nrhid db 'Not resetting hidden file - $'
s_nrsys db 'Not resetting system file - $'
s_long2 db 'Path too long - $'
s_badsw db 'Invalid parameter', 13, 10, '$'
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
aset    resb 1
aclr    resb 1
subs    resb 1
err     resb 1
        alignb 2
depth   resw 1
nfound  resw 1
dta     resw 1
dirlen  resw 1
dirend  resw 1
spec    resb 82
pat     resb 82
dir     resb 82
line    resb 10
dtas    resb MAXDEPTH * DTASZ
CANON_BSS
        resb 1024
stack_top:
bss_end:
