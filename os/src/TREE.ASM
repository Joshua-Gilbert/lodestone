; TREE.COM - lists a disk's directories (DOS 3.30's TREE)
;
;   TREE [d:] [/F]
;
;   d:   the drive (the current one if none is given), from its root
;   /F   each directory's files too
;
; DOS 3.30's listing, text only (the same in every font, and a script can
; search it), a directory at a time from the root, each before those in
; it, as the Executive's Subject list has them:
;
;   DIRECTORY PATH LISTING FOR VOLUME LODESTONE
;
;   Path: \SUB
;
;   Sub-directories:  DEEP
;
;   Files:            X       .TXT
;
; Hidden directories are listed (they are part of the tree); files as DIR
; shows them (no hidden or system ones).  "No sub-directories exist" when
; the root has none (without /F).  A directory whose path would pass 65
; characters after "D:\" is said ("Path too long - ") and left out.
;
; Exit code: 0 listed, 1 couldn't (a bad drive or switch), or not all (a
; path too long).
cpu 286
org 100h

MAXDEPTH equ 34                         ; (PMAX's 65: "X\" 32 times at most)
DTASZ   equ 44
COL     equ 18                          ; where names go

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        call    args
        jc      fail
        mov     si, spec                ; "D:\" of the drive asked for
        call    canon
        jc      fail
        mov     ax, [cpath]
        mov     [dir], ax
        mov     word [dir+2], '\'
        mov     word [dirlen], 3
        mov     dx, s_head              ; "DIRECTORY PATH LISTING"
        call    print
        call    label
        mov     dx, s_crlf
        call    print
        mov     word [depth], 0
        call    walk
        cmp     byte [fls], 0           ; (with /F the root's files are its
        jne     .ok                     ;  listing)
        cmp     word [ndirs], 0
        jne     .ok
        mov     dx, s_none
        call    print
.ok:    mov     al, [err]
        mov     ah, 4Ch
        int     21h
fail:   call    print
        mov     ax, 4C01h
        int     21h

; command tail: d:, /F.  CF: DX
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
        cmp     al, '/'
        je      .sw
        cmp     byte [si], ':'
        jne     .bad
        cmp     byte [spec], 0
        jne     .bad
        call    upcase
        mov     [spec], al
        mov     byte [spec+1], ':'
        inc     si
        jmp     .l
.sw:    lodsb
        call    upcase
        cmp     al, 'F'
        jne     .bad
        mov     byte [fls], 1
        jmp     .l
.end:   cmp     byte [spec], 0          ; the current drive's root
        jne     .ok
        mov     ah, 19h
        int     21h
        add     al, 'A'
        mov     [spec], al
        mov     byte [spec+1], ':'
.ok:    mov     byte [spec+2], '\'
        mov     byte [spec+3], 0
        clc
        ret
.bad:   mov     dx, s_badsw
        stc
        ret

; " FOR VOLUME NAME", if the drive has a label
label:  mov     dx, dta0
        mov     ah, 1Ah
        int     21h
        mov     si, s_all
        call    dir_add
        mov     dx, dir
        mov     cx, 08h
        mov     ah, 4Eh
        int     21h
        jc      .x
        test    byte [dta0+21], 08h
        jz      .x
        mov     dx, s_vol
        call    print
        mov     si, dta0 + 30           ; (the name as DOS gives it: no dot
        mov     cx, 12                  ;  in a label)
.c:     lodsb
        or      al, al
        jz      .x
        cmp     al, '.'
        je      .c
        call    putc
        loop    .c
.x:     mov     bx, [dirlen]
        mov     byte [dir+bx], 0
        ret

; the directory at dir ([dirlen], "\" last): its listing, then each one in it
walk:   call    set_dta
        cmp     word [depth], 0         ; "Path: \SUB" (the root's only with
        jne     .p                      ;  /F, for its files)
        cmp     byte [fls], 0
        je      .subs
.p:     mov     dx, s_path
        call    print
        mov     bx, [dirlen]            ; (the path without "D:", and the
        mov     al, [dir+bx-1]          ;  root's "\" kept)
        push    ax
        cmp     bx, 3
        je      .pr
        mov     byte [dir+bx-1], 0
.pr:    mov     si, dir + 2
        call    puts
        pop     ax
        mov     bx, [dirlen]
        mov     [dir+bx-1], al
        mov     byte [dir+bx], 0
        mov     dx, s_crlf2
        call    print
        mov     dx, s_subs              ; "Sub-directories:  DEEP" / "None"
        call    print
        mov     cx, 16h
        call    names
        mov     dx, s_crlf
        call    print
        cmp     byte [fls], 0
        je      .subs
        mov     dx, s_files             ; "Files:            X       .TXT"
        call    print
        xor     cx, cx
        call    names
        mov     dx, s_crlf
        call    print
.subs:  mov     si, s_all               ; each directory in it (no deeper
        call    dir_add                 ;  than PMAX lets it: MAXDEPTH's)
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
        inc     word [ndirs]
        push    word [dirlen]
        lea     si, [bx+30]
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
        call    set_dta
.dl:    pop     word [dirlen]
        mov     bx, [dirlen]
        mov     byte [dir+bx], 0
.dn:    mov     ah, 4Fh
        int     21h
        jmp     .d
.x:     ret
.long:  mov     dx, s_long2             ; "Path too long - A:\SUB\NAME"
        call    print
        mov     si, dir
        call    puts
        mov     dx, s_crlf
        call    print
        mov     byte [err], 1
        jmp     .dl

set_dta:
        mov     ax, [depth]
        mov     bx, DTASZ
        mul     bx
        add     ax, dtas
        mov     [dta], ax
        mov     dx, ax
        mov     ah, 1Ah
        int     21h
        ret

; the directory's entries of kind CX (16h directories, hidden ones too;
; 0 files as DIR finds them), one a line from column COL; "None" if there are none
names:  push    cx
        mov     si, s_all
        call    dir_add
        pop     cx
        push    cx
        mov     dx, dir
        mov     ah, 4Eh
        int     21h
        pop     cx
        mov     byte [any], 0
.l:     jc      .e
        mov     bx, [dta]
        mov     al, [bx+21]
        test    al, 08h
        jnz     .n
        mov     ah, cl
        and     ax, 1010h
        cmp     al, ah
        jne     .n
        cmp     byte [bx+30], '.'
        je      .n
        cmp     byte [any], 0
        je      .first
        push    cx
        mov     dx, s_crlf
        call    print
        mov     cx, COL
.sp:    mov     al, ' '
        call    putc
        loop    .sp
        pop     cx
.first: mov     byte [any], 1
        push    cx
        lea     si, [bx+30]             ; "NAME    .EXT": the dot at column 9
        call    p83
        pop     cx
.n:     push    cx
        mov     ah, 4Fh
        int     21h
        pop     cx
        jmp     .l
.e:     cmp     byte [any], 0
        jne     .x
        mov     dx, s_nonew
        call    print
.x:     mov     bx, [dirlen]
        mov     byte [dir+bx], 0
        ret

; DOS's "NAME.EXT" at SI as "NAME    .EXT" (no extension: the name alone)
p83:    xor     cx, cx
.n:     lodsb
        or      al, al
        jz      .x
        cmp     al, '.'
        je      .dot
        call    putc
        inc     cx
        jmp     .n
.dot:   cmp     cx, 8
        jae     .d
        mov     al, ' '
        call    putc
        inc     cx
        jmp     .dot
.d:     mov     al, '.'
        call    putc
        jmp     .n
.x:     ret

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

%include "CANON.INC"

upcase: cmp     al, 'a'
        jb      .x
        cmp     al, 'z'
        ja      .x
        sub     al, 20h
.x:     ret
print:  mov     ah, 9
        int     21h
        ret
putc:   push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        ret
puts:   lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     puts
.x:     ret

s_all   db '*.*', 0
s_head  db 13, 10, 'DIRECTORY PATH LISTING$'
s_vol   db ' FOR VOLUME $'
s_path  db 13, 10, 'Path: $'
s_subs  db 'Sub-directories:  $'
s_files db 13, 10, 'Files:            $'
s_nonew db 'None$'
s_none  db 13, 10, 'No sub-directories exist', 13, 10, '$'
s_long2 db 'Path too long - $'
s_badsw db 'Invalid parameter', 13, 10, '$'
s_crlf2 db 13, 10
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
fls     resb 1
err     resb 1
any     resb 1
        alignb 2
depth   resw 1
ndirs   resw 1
dta     resw 1
dirlen  resw 1
dirend  resw 1
spec    resb 8
dir     resb 82
dta0    resb DTASZ
dtas    resb MAXDEPTH * DTASZ
CANON_BSS
        resb 1024
stack_top:
bss_end:
