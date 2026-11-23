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
; Lines longer than 1,024 characters are taken as several.  Each line goes
; out with CR LF (one that had only LF too).
;
; A read that fails ends that file (its lines so far written), "FIND: Read
; error in NAME" on standard error, and FIND goes on to the next.  Its
; output not all written (a full disk) ends it: "FIND: Insufficient disk
; space"; a write that fails (a write-protected disk, a device error)
; too: "FIND: Write error".
; Exit code: 0 a line found (or, /V, one without it), 1 none, 2 an error
; (a file not found or unreadable, a bad switch, no string, a full disk,
; a write that failed).
cpu 286
org 100h

LMAX    equ 1025                        ; a line's room (1,024 and its CR)
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
        jc      .nf                     ; (this one: said, on to the next)
        mov     bx, ax
        push    bx
        mov     dx, s_head              ; CR LF, "---------- NAME"
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
.n:     mov     ah, 4Fh
        int     21h
        jnc     .f
        ret
.nf:    call    .none
        jmp     .n
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
        mov     byte [rerr], 0
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
.x:     cmp     byte [rerr], 0          ; a read failed: "FIND: Read error in
        je      .ok                     ;  NAME" (or "... in standard input")
        mov     dx, s_rerr
        call    eprint
        mov     si, argbuf
        cmp     byte [nfiles+2], 0
        jne     .rn
        mov     si, s_stdin
.rn:    call    epz
        mov     dx, s_crlf
        call    eprint
        mov     byte [result], 2
.ok:    mov     bx, [hin]
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
        push    di
        mov     ax, [lno]
        mov     dx, [lno+2]
        call    pnum
        dec     di
        mov     byte [di], '['
        mov     byte [numbuf + 12], ']'
        mov     dx, di
        mov     cx, numbuf + 13
        sub     cx, di
        mov     bx, 1
        call    write
        pop     di
.t:     mov     bx, di                  ; the line and CR LF (in place of its
        or      bx, bx                  ;  own CR if it had one): one write
        jz      .w
        cmp     byte [lbuf+bx-1], 13
        jne     .w
        dec     bx
.w:     mov     word [lbuf+bx], 0A0Dh
        lea     cx, [bx+2]
        mov     dx, lbuf
        mov     bx, 1
        call    write
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
        jc      .rerr
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
.rerr:  mov     byte [rerr], 1          ; a read failed: its end too (said
.eof:   mov     byte [eof], 1           ;  after the lines before it)
.end:   stc
        ret

; ---------------------------------------------------------------------
print:  push    bx                      ; DX ($) to standard output
        mov     bx, 1
        jmp     short eprint.go
eprint: push    bx                      ; DX ($) to standard error
        mov     bx, 2
.go:    push    cx
        mov     si, dx
        xor     cx, cx
.l:     cmp     byte [si], '$'
        je      .w
        inc     si
        inc     cx
        jmp     .l
.w:     call    write
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
        jmp     write

; CX bytes at DX to handle BX.  Standard output's write coming up short
; (a full disk: a device takes all) ends FIND, "FIND: Insufficient disk
; space", and one failing (a write-protected disk, a device's error, a
; critical error answered Fail) "FIND: Write error", exit code 2
write:  mov     ah, 40h
        int     21h
        jc      .e
        cmp     ax, cx
        je      .x
        cmp     bx, 1
        jne     .x
        mov     dx, s_full
        jmp     short .end
.e:     cmp     bx, 1
        jne     .x
        mov     dx, s_wrerr
.end:   call    eprint
        mov     ax, 4C02h
        int     21h
.x:     ret

; DX:AX in decimal at DI, to numbuf + 12 (BX, SI changed)
pnum:   mov     di, numbuf + 12
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
        ret
; DX:AX in decimal to standard output
pdec:   pusha
        call    pnum
        mov     byte [numbuf + 12], '$'
        mov     dx, di
        call    print
        popa
        ret

s_head  db 13, 10, '---------- $'
s_colon db ': $'
s_crlf  db 13, 10, '$'
s_badsw db 'FIND: Invalid switch', 13, 10, '$'
s_nostr db 'FIND: no string ("in quotes"): FIND [/V] [/C] [/N] "string" [name ...]', 13, 10, '$'
s_nofile db 'File not found - $'
s_rerr  db 'FIND: Read error in $'
s_stdin db 'standard input', 0
s_full  db 'FIND: Insufficient disk space', 13, 10, '$'
s_wrerr db 'FIND: Write error', 13, 10, '$'

        alignb 2
section .bss
bss_start:
opt_v   resb 1
opt_c   resb 1
opt_n   resb 1
eof     resb 1
result  resb 1
rerr    resb 1
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
lbuf    resb LMAX + 1                   ; (and its CR LF)
ibuf    resb CHUNK
        resb 512
stack_top:
bss_end:
