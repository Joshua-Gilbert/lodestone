; COMP.COM - compares files byte for byte (DOS 3.30's COMP) for Lodestone
;
;   COMP [d:][path][name] [d:][path][name]
;
; The first may have wildcards (each file it matches is compared), or be
; a directory or a drive (all its files).  The second names each one's
; partner: a file; a directory or drive (the same name there); or a name
; with wildcards, filled from the first's (COMP *.TXT *.BAK: X.TXT with
; X.BAK).  Either left out is asked for.  Files of different sizes aren't
; compared; otherwise each difference is "Compare error at OFFSET n",
; with the two bytes (hex), and after 10 it stops: "10 Mismatches -
; ending compare".  None: "Files compare OK".  Then "Compare more files
; (Y/N)?", read through DOS (so COMP X Y < N.TXT ends there).
;
; Exit code (DOS 3.30's has none: as Lodestone's built-ins, so scripts can
; test it): 0 every file compared the same, 1 a difference (or different
; sizes), 2 a file not found, or couldn't be read.
cpu 286
org 100h

CHUNK   equ 8192

start:  mov     sp, stack_top
        cld
        mov     di, bss_start           ; (a .COM's memory isn't cleared)
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     dx, dta
        mov     ah, 1Ah
        int     21h
        mov     si, 81h                 ; the two names from the command line
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
        mov     di, name1
        call    word_to
        mov     di, name2
        call    word_to
.again: cmp     byte [name1], 0
        jne     .n1
        mov     dx, s_ask1              ; "Enter primary file name"
        mov     di, name1
        call    ask
.n1:    cmp     byte [name2], 0
        jne     .n2
        mov     dx, s_ask2              ; "Enter 2nd file name or drive id"
        mov     di, name2
        call    ask
.n2:    call    run
        mov     dx, s_more              ; "Compare more files (Y/N)?"
        call    print
        call    getkey
        push    ax
        cmp     al, ' '
        jb      .ne
        call    putc
.ne:    mov     dx, s_crlf
        call    print
        pop     ax
        and     al, 0DFh
        cmp     al, 'Y'
        jne     .end
        mov     byte [name1], 0
        mov     byte [name2], 0
        jmp     .again
.end:   mov     al, [result]
        mov     ah, 4Ch
        int     21h

; the next word at SI -> DI (ASCIIZ, upper case; "" if none)
word_to:
.s:     mov     al, [si]
        cmp     al, ' '
        je      .n
        cmp     al, 9
        jne     .w
.n:     inc     si
        jmp     .s
.w:     mov     cx, 79
.l:     lodsb
        cmp     al, ' '
        jbe     .e
        call    up
        stosb
        loop    .l
.e:     dec     si
        mov     byte [di], 0
        ret
up:     cmp     al, 'a'
        jb      .x
        cmp     al, 'z'
        ja      .x
        sub     al, 20h
.x:     ret

; the question at DX, an answer -> DI (ASCIIZ)
ask:    push    di
        call    print
        mov     byte [kbuf], 80
        mov     dx, kbuf
        mov     ah, 0Ah
        int     21h
        mov     dx, s_crlf
        call    print
        pop     di
        mov     si, kbuf + 2
        mov     cl, [kbuf+1]
        xor     ch, ch
        add     si, cx
        mov     byte [si], 13
        mov     si, kbuf + 2
        jmp     word_to

; ---------------------------------------------------------------------
; name1 against name2: each file name1 matches
run:    mov     si, name1               ; a directory or a drive: its files
        call    is_dir
        jnc     .pat
        call    add_all
.pat:   mov     si, name1               ; where its names start: dir1end
        call    name_at
        mov     [dir1end], bx
        mov     si, name2               ; name2: a directory (or drive)?
        call    is_dir
        mov     byte [twodir], 0
        jc      .d2
        mov     si, name2
        call    name_at
        mov     [dir2end], bx
        jmp     short .ff
.d2:    mov     byte [twodir], 1
        mov     si, name2               ; (its end: a \ after it, if none)
        call    str_end
        cmp     byte [si-1], '\'
        je      .de
        cmp     byte [si-1], ':'
        je      .de
        mov     word [si], '\'
        inc     si
.de:    mov     [dir2end], si
.ff:    mov     dx, name1
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        jc      .none
.f:     mov     si, dta + 1Eh           ; this one's path
        mov     di, [dir1end]
        mov     cx, 13
        rep     movsb
        call    partner                 ; -> path2
        call    pair
        mov     ah, 4Fh
        int     21h
        jnc     .f
        ret
.none:  mov     si, name1
        mov     dx, s_nofile
        jmp     notfound

; is SI a directory (or a bare drive, or the root)?  CF if so
is_dir: push    si
        call    str_end
        mov     cx, si
        pop     si
        sub     cx, si                  ; its length
        jcxz    .n
        cmp     cx, 2                   ; "A:"
        jne     .t
        cmp     byte [si+1], ':'
        je      .y
.t:     mov     bx, si
        add     bx, cx
        cmp     byte [bx-1], '\'        ; "...\": a directory
        je      .y
        mov     dx, si                  ; wildcards: not one
        push    si
.w:     lodsb
        or      al, al
        jz      .wn
        cmp     al, '*'
        je      .wy
        cmp     al, '?'
        je      .wy
        jmp     .w
.wy:    pop     si
        jmp     short .n
.wn:    pop     si
        mov     ax, 4300h               ; its attributes: 10h?
        int     21h
        jc      .n
        test    cl, 10h
        jz      .n
.y:     stc
        ret
.n:     clc
        ret

; a directory or drive name at SI: "\*.*" (or "*.*") after it
add_all:
        call    str_end
        cmp     byte [si-1], '\'
        je      .s
        cmp     byte [si-1], ':'
        je      .s
        mov     byte [si], '\'
        inc     si
.s:     mov     di, si
        mov     si, s_all
        mov     cx, 4
        rep     movsb
        ret

; the end of the ASCIIZ at SI -> SI (at its 0)
str_end:
.l:     cmp     byte [si], 0
        je      .x
        inc     si
        jmp     .l
.x:     ret

; where the name at SI starts (after its last \ or :) -> BX
name_at:
        mov     bx, si
.l:     lodsb
        or      al, al
        jz      .x
        cmp     al, '\'
        je      .s
        cmp     al, ':'
        jne     .l
.s:     mov     bx, si
        jmp     .l
.x:     ret

; the found name (dta+1Eh) -> path2: name2 itself, or its directory and
; the name, or name2's wildcards filled from it
partner:
        mov     si, name2               ; path2: name2's directory part
        mov     di, path2
        mov     cx, [dir2end]
        sub     cx, si
        rep     movsb
        cmp     byte [twodir], 0
        jne     .same
        mov     si, [dir2end]           ; wildcards in name2's name?
        push    si
.w:     lodsb
        or      al, al
        jz      .lit
        cmp     al, '*'
        je      .wild
        cmp     al, '?'
        je      .wild
        jmp     .w
.lit:   pop     si                      ; none: name2 as it is
        jmp     short .cp
.same:  mov     si, dta + 1Eh
.cp:    lodsb
        stosb
        or      al, al
        jnz     .cp
        ret
.wild:  pop     si                      ; SI: the template, BX: the name
        mov     bx, dta + 1Eh
        call    .part                   ; its name part (8)
        cmp     byte [si], '.'
        jne     .z
        inc     si
        cmp     byte [bx], '.'          ; (the found name's ext, if any)
        jne     .ne
        inc     bx
.ne:    mov     al, '.'
        stosb
        call    .part                   ; its ext (3)
        cmp     byte [di-1], '.'        ; (no ext: no dot)
        jne     .z
        dec     di
.z:     xor     al, al
        stosb
        ret
; template SI, name BX, up to a . or the end of each: ? the name's
; character, * the rest of the name's part
.part:  mov     al, [si]
        or      al, al
        jz      .px
        cmp     al, '.'
        je      .pb
        inc     si
        cmp     al, '*'
        je      .star
        cmp     al, '?'
        jne     .lit1
        mov     al, [bx]                ; ?: the name's, if it has one there
        or      al, al
        jz      .q
        cmp     al, '.'
        je      .q
        stosb
        inc     bx
        jmp     .part
.q:     jmp     .part
.lit1:  stosb
        mov     ah, [bx]
        or      ah, ah
        jz      .part
        cmp     ah, '.'
        je      .part
        inc     bx
        jmp     .part
.star:  mov     al, [bx]                ; *: the rest of the name's part
        or      al, al
        jz      .ss
        cmp     al, '.'
        je      .ss
        stosb
        inc     bx
        jmp     .star
.ss:    mov     al, [si]                ; (the template to its . or end)
        or      al, al
        jz      .px
        cmp     al, '.'
        je      .pb
        inc     si
        jmp     .ss
.pb:    mov     al, [bx]                ; the name to its . or end too
        or      al, al
        jz      .px
        cmp     al, '.'
        je      .px
        inc     bx
        jmp     .pb
.px:    ret

; name1 (the path in name1's buffer: its directory and the found name)
; against path2
pair:   mov     si, name1               ; "A:\X.TXT and B:\X.TXT"
        call    pz
        mov     dx, s_and
        call    print
        mov     si, path2
        call    pz
        mov     dx, s_crlf
        call    print
        mov     dx, name1
        mov     ax, 3D00h
        int     21h
        jc      .n1
        mov     [h1], ax
        mov     dx, path2
        mov     ax, 3D00h
        int     21h
        jc      .n2
        mov     [h2], ax
        mov     bx, [h1]                ; the sizes
        call    size_of
        mov     [sz1], ax
        mov     [sz1+2], dx
        mov     bx, [h2]
        call    size_of
        cmp     ax, [sz1]
        jne     .diff
        cmp     dx, [sz1+2]
        jne     .diff
        call    bytes
        jmp     short .cl
.diff:  mov     dx, s_size              ; "Files are different sizes"
        call    print
        mov     byte [result], 1
.cl:    mov     bx, [h2]
        mov     ah, 3Eh
        int     21h
.c1:    mov     bx, [h1]
        mov     ah, 3Eh
        int     21h
        ret
.n2:    mov     si, path2
        mov     dx, s_nofile
        call    notfound
        jmp     .c1
.n1:    mov     si, name1
        mov     dx, s_nofile
        ; (on into notfound)

; "File not found - NAME", exit code 2 from now on
notfound:
        call    print
        call    pz
        mov     dx, s_crlf
        call    print
        mov     byte [result], 2
        ret

; handle BX: its size -> DX:AX (and back to its start)
size_of:
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        push    ax
        push    dx
        mov     ax, 4200h
        xor     cx, cx
        xor     dx, dx
        int     21h
        pop     dx
        pop     ax
        ret

; the two, a chunk at a time: the first 10 differences said
bytes:  mov     word [errs], 0
        mov     word [off], 0
        mov     word [off+2], 0
.ch:    mov     bx, [h1]
        mov     cx, CHUNK
        mov     dx, buf1
        mov     ah, 3Fh
        int     21h
        jc      .rerr
        mov     [n1], ax
        mov     bx, [h2]
        mov     cx, CHUNK
        mov     dx, buf2
        mov     ah, 3Fh
        int     21h
        jc      .rerr
        cmp     ax, [n1]
        jne     .rerr                   ; (the same size: the same counts)
        or      ax, ax
        jz      .end
        mov     cx, ax
        xor     si, si
.b:     mov     al, [buf1+si]
        cmp     al, [buf2+si]
        jne     .err
.bn:    inc     si
        loop    .b
        add     [off], si
        adc     word [off+2], 0
        jmp     .ch
.err:   push    cx                      ; "Compare error at OFFSET 1A"
        mov     byte [result], 1
        mov     dx, s_at
        call    print
        mov     ax, [off]
        mov     dx, [off+2]
        add     ax, si
        adc     dx, 0
        push    ax
        mov     ax, dx
        or      ax, ax
        jz      .lo
        call    phex
.lo:    pop     ax
        call    phex
        mov     dx, s_f1
        call    print
        mov     al, [buf1+si]
        call    phex8
        mov     dx, s_f2
        call    print
        mov     al, [buf2+si]
        call    phex8
        mov     dx, s_crlf2
        call    print
        pop     cx
        inc     word [errs]
        cmp     word [errs], 10
        jb      .bn
        mov     dx, s_ten               ; "10 Mismatches - ending compare"
        jmp     print
.end:   cmp     word [errs], 0
        jne     .x
        mov     dx, s_ok                ; "Files compare OK"
        jmp     print
.rerr:  mov     dx, s_rerr
        mov     byte [result], 2
        jmp     print
.x:     ret

; ---------------------------------------------------------------------
getkey: mov     ah, 08h
        int     21h
        ret
print:  mov     ah, 9
        int     21h
        ret
putc:   push    ax
        push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        pop     ax
        ret
pz:     push    si                      ; SI (ASCIIZ)
.l:     lodsb
        or      al, al
        jz      .x
        call    putc
        jmp     .l
.x:     pop     si
        ret
phex:   push    ax                      ; AX in 4 hex digits
        mov     al, ah
        call    phex8
        pop     ax
phex8:  push    ax                      ; AL in 2
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     jmp     putc

s_all   db '*.*', 0
s_ask1  db 'Enter primary file name', 13, 10, '$'
s_ask2  db 'Enter 2nd file name or drive id', 13, 10, '$'
s_and   db ' and $'
s_size  db 13, 10, 'Files are different sizes', 13, 10, 13, 10, '$'
s_at    db 13, 10, 'Compare error at OFFSET $'
s_f1    db 13, 10, 'file1 = $'
s_f2    db 13, 10, 'file2 = $'
s_crlf2 db 13, 10, '$'
s_ten   db 13, 10, '10 Mismatches - ending compare', 13, 10, 13, 10, '$'
s_ok    db 13, 10, 'Files compare OK', 13, 10, 13, 10, '$'
s_rerr  db 13, 10, 'Disk error reading the files', 13, 10, 13, 10, '$'
s_nofile db 13, 10, 'File not found - $'
s_more  db 'Compare more files (Y/N)? $'
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
twodir  resb 1
result  resb 1
        alignb 2
h1      resw 1
h2      resw 1
n1      resw 1
errs    resw 1
dir1end resw 1
dir2end resw 1
off     resw 2
sz1     resw 2
name1   resb 96
name2   resb 96
path2   resb 112
kbuf    resb 84
dta     resb 44
buf1    resb CHUNK
buf2    resb CHUNK
        resb 512
stack_top:
bss_end:
