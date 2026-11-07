; FIND.COM - the lines with a string in them (DOS 3.30's FIND) for Lodestone
;
;   FIND [/V] [/C] [/N] "string" [d:][path]name ...
;
;   /V   the lines without the string
;   /C   only how many lines there are (with or, /V, without it)
;   /N   each line's number before it: [12]
;
; The string is matched as given, capitals and all (as DOS 3.30's), and
; "" in it stands for one ".  With no file named it reads its input (a
; pipe: DIR | FIND "COM"); each file named is read in turn, under
; "---------- NAME" (wildcards: each file they match).  A file ends at
; its end or at Ctrl-Z; a line at LF (a CR before it is the line's).
; Lines longer than 1,023 characters are taken as several.
;
; Exit code: 0 a line found (or, /V, one without it), 1 none, 2 an error
; (a file not found, a bad switch, no string).
cpu 286
org 100h

LMAX    equ 1024                        ; a line's room
CHUNK   equ 16384                       ; read at a time

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     byte [result], 1
        call    args
        jc      err
        cmp     word [nfiles], 0
        jne     .files
        xor     bx, bx                  ; no file: the input
        call    one
        jmp     short .end
.files: mov     si, [fptr]              ; each name (and what it matches)
.f:     cmp     word [nfiles], 0
        je      .end
        dec     word [nfiles]
        call    arg_next                ; -> argbuf, SI past it
        push    si
        call    each
        pop     si
        jmp     .f
.end:   mov     al, [result]
        mov     ah, 4Ch
        int     21h
err:    call    eprint
        mov     ax, 4C02h
        int     21h

; ---------------------------------------------------------------------
; command tail: switches, the string (quoted), the names.  CF: DX
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
.sw:    call    skipsp
        cmp     al, '/'
        jne     .str
        inc     si
        lodsb
        and     al, 0DFh
        cmp     al, 'V'
        je      .v
        cmp     al, 'C'
        je      .c
        cmp     al, 'N'
        je      .n
        mov     dx, s_badsw
        stc
        ret
.v:     mov     byte [opt_v], 1
        jmp     .sw
.c:     mov     byte [opt_c], 1
        jmp     .sw
.n:     mov     byte [opt_n], 1
        jmp     .sw
.str:   mov     dx, s_nostr
        cmp     al, '"'
        jne     .bad
        inc     si
        mov     di, pat                 ; the string: "" is one "
        xor     cx, cx
.s:     lodsb
        cmp     al, 13
        je      .bad
        cmp     al, '"'
        jne     .sc
        cmp     byte [si], '"'
        jne     .se
        inc     si
.sc:    cmp     cx, 127
        jae     .s
        stosb
        inc     cx
        jmp     .s
.se:    mov     [patlen], cx
        mov     [fptr], si              ; the names: count them (and say
        call    skipsp                  ;  if there are any)
        cmp     al, 13
        je      .cn
        mov     byte [nfiles+2], 1
.cn:    call    skipsp
        cmp     al, 13
        je      .ok
        inc     word [nfiles]
.cw:    lodsb
        cmp     al, ' '
        ja      .cw
        dec     si
        jmp     .cn
.ok:    clc
        ret
.bad:   stc
        ret

skipsp: mov     al, [si]
        cmp     al, ' '
        je      .n
        cmp     al, 9
        jne     .x
.n:     inc     si
        jmp     skipsp
.x:     ret

; the next name at SI -> argbuf (ASCIIZ), SI past it
arg_next:
        call    skipsp
        mov     di, argbuf
        mov     cx, 79
.l:     lodsb
        cmp     al, ' '
        jbe     .e
        stosb
        loop    .l
.e:     dec     si
        mov     byte [di], 0
        ret

; the name in argbuf: each file it matches.  (Its directory part kept,
; for the path of each.)
each:   mov     dx, dta
        mov     ah, 1Ah
        int     21h
        mov     si, argbuf              ; where the name starts: after the
        mov     di, argbuf              ;  last \ or :
        mov     bx, di
.p:     lodsb
        or      al, al
        jz      .pe
        cmp     al, '\'
        je      .ps
        cmp     al, ':'
        jne     .p
.ps:    mov     bx, si
        jmp     .p
.pe:    mov     [dirend], bx
        mov     dx, argbuf
        xor     cx, cx                  ; (files only)
        mov     ah, 4Eh
        int     21h
        jc      .none
.f:     mov     si, dta + 1Eh           ; its path: the directory, its name
        mov     di, [dirend]
        mov     cx, 13
        rep     movsb
        mov     dx, argbuf
        mov     ax, 3D00h
        int     21h
        jc      .none
        mov     bx, ax
        push    bx
        mov     dx, s_head              ; "---------- NAME"
        call    print
        mov     si, argbuf
        call    pz
        cmp     byte [opt_c], 0         ; (/C: the count after it)
        jne     .c
        mov     dx, s_crlf
        call    print
.c:     pop     bx
        call    one
        mov     ah, 3Eh
        int     21h
        mov     ah, 4Fh
        int     21h
        jnc     .f
        ret
.none:  mov     dx, s_nofile            ; "File not found - NAME"
        call    eprint
        mov     si, argbuf
        call    epz
        mov     dx, s_crlf
        call    eprint
        mov     byte [result], 2
        ret

; ---------------------------------------------------------------------
; handle BX, read through: each line matched and written (or counted)
one:    mov     [hin], bx
        mov     word [count], 0
        mov     word [count+2], 0
        mov     word [lno], 0
        mov     word [lno+2], 0
        mov     word [bend], 0
        mov     word [bpos], 0
        mov     byte [eof], 0
.line:  xor     di, di                  ; DI = the line's length
.c:     call    getc
        jc      .last
        cmp     al, 10
        je      .lf
        cmp     di, LMAX - 1
        jae     .full
        mov     [lbuf+di], al
        inc     di
        jmp     .c
.full:  dec     word [bpos]             ; (that character the next line's)
.lf:    call    do_line
        jmp     .line
.last:  or      di, di                  ; a last line with no LF
        jz      .done
        call    do_line
.done:  cmp     byte [opt_c], 0
        je      .x
        mov     dx, s_colon             ; /C: ": n" (after a file's name),
        cmp     byte [nfiles+2], 0      ;  or just n for the input
        je      .cn
        call    print
.cn:    mov     ax, [count]
        mov     dx, [count+2]
        call    pdec
        mov     dx, s_crlf
        call    print
.x:     mov     bx, [hin]
        ret

; the line in lbuf (DI long, its LF not in it): has it the string?
do_line:
        add     word [lno], 1
        adc     word [lno+2], 0
        call    has
        mov     al, 0
        adc     al, 0                   ; AL = 1: it has it
        xor     al, [opt_v]
        jz      .x
        cmp     byte [result], 2        ; (an error stays the exit code)
        je      .r
        mov     byte [result], 0
.r:     add     word [count], 1
        adc     word [count+2], 0
        cmp     byte [opt_c], 0
        jne     .x
        cmp     byte [opt_n], 0         ; "[12]"
        je      .t
        mov     al, '['
        call    putc
        mov     ax, [lno]
        mov     dx, [lno+2]
        call    pdec
        mov     al, ']'
        call    putc
.t:     mov     cx, di                  ; the line, and its LF
        mov     dx, lbuf
        mov     bx, 1
        mov     ah, 40h
        int     21h
        mov     al, 10
        call    putc
.x:     ret

; is pat in lbuf[0, DI)?  CF if so
has:    mov     cx, [patlen]
        jcxz    .y                      ; ("": every line)
        mov     dx, di
        sub     dx, cx
        jb      .n
        xor     bx, bx
.l:     push    cx
        mov     si, pat
        lea     ax, [lbuf+bx]
        push    di
        mov     di, ax
        push    ds
        pop     es
        repe    cmpsb
        pop     di
        pop     cx
        je      .y
        inc     bx
        cmp     bx, dx
        jbe     .l
.n:     clc
        ret
.y:     stc
        ret

; the next character from [hin] -> AL.  CF at the end (or Ctrl-Z)
getc:   cmp     byte [eof], 0
        jne     .end
        mov     si, [bpos]
        cmp     si, [bend]
        jb      .h
        push    bx
        push    cx
        push    dx
        mov     bx, [hin]
        mov     cx, CHUNK
        mov     dx, ibuf
        mov     ah, 3Fh
        int     21h
        pop     dx
        pop     cx
        pop     bx
        jc      .eof
        or      ax, ax
        jz      .eof
        mov     [bend], ax
        xor     si, si
.h:     mov     al, [ibuf+si]
        inc     si
        mov     [bpos], si
        cmp     al, 1Ah
        je      .eof
        clc
        ret
.eof:   mov     byte [eof], 1
.end:   stc
        ret

; ---------------------------------------------------------------------
print:  mov     ah, 9
        int     21h
        ret
eprint: push    bx                      ; DX ($) to standard error
        push    cx
        mov     si, dx
        xor     cx, cx
.l:     cmp     byte [si], '$'
        je      .w
        inc     si
        inc     cx
        jmp     .l
.w:     mov     bx, 2
        mov     ah, 40h
        int     21h
        pop     cx
        pop     bx
        ret
epz:    mov     bx, 2                   ; SI (ASCIIZ) to standard error
        jmp     short pz.go
pz:     mov     bx, 1                   ; SI (ASCIIZ) to standard output
.go:    push    si
        xor     cx, cx
.l:     cmp     byte [si], 0
        je      .w
        inc     si
        inc     cx
        jmp     .l
.w:     pop     dx
        mov     ah, 40h
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
; DX:AX in decimal
pdec:   pusha
        mov     di, numbuf + 12
        mov     bx, 10
.d:     push    ax
        mov     ax, dx
        xor     dx, dx
        div     bx
        mov     si, ax
        pop     ax
        div     bx
        add     dl, '0'
        dec     di
        mov     [di], dl
        mov     dx, si
        mov     si, ax
        or      si, dx
        jnz     .d
        mov     byte [numbuf + 12], '$'
        mov     dx, di
        call    print
        popa
        ret

s_head  db '---------- $'
s_colon db ': $'
s_crlf  db 13, 10, '$'
s_badsw db 'FIND: Invalid switch', 13, 10, '$'
s_nostr db 'FIND: no string ("in quotes"): FIND [/V] [/C] [/N] "string" [name ...]', 13, 10, '$'
s_nofile db 'File not found - $'

        alignb 2
section .bss
bss_start:
opt_v   resb 1
opt_c   resb 1
opt_n   resb 1
eof     resb 1
result  resb 1
        alignb 2
nfiles  resw 2                          ; (the second word: files named)
fptr    resw 1
patlen  resw 1
hin     resw 1
bpos    resw 1
bend    resw 1
dirend  resw 1
count   resw 2
lno     resw 2
pat     resb 128
argbuf  resb 96
numbuf  resb 14
dta     resb 44
lbuf    resb LMAX
ibuf    resb CHUNK
        resb 512
stack_top:
bss_end:
