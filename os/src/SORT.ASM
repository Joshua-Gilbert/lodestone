; SORT.COM - its input's lines in order (DOS 3.30's SORT) for Lodestone
;
;   SORT [/R] [/+n] < name          DIR | SORT /+14
;
;   /R    the other way round (Z to A, 9 to 0)
;   /+n   from the nth column of each line on (a line shorter than that
;         comes first)
;
; Capitals and small letters are the same to it (as DOS's); otherwise
; the character codes' order (no country's collating table: the kernel
; has none), and equal lines keep their order.  Lines end at LF (the CR
; before it is dropped; a NUL is a character); each goes out with CR LF.
; Ctrl-Z in the input, or typed at the keyboard, is its end.  Its
; messages go to standard error.
; At most 63 KB of input, as DOS's: more is "SORT: Insufficient memory".
; Exit code: 0, 1 (too much, a bad switch).
cpu 286
org 100h

MAXIN   equ 0FC00h                      ; 63 KB
MAXL    equ 16384                       ; lines

start:  mov     sp, stack_top
        cld
        mov     di, bss_start           ; (a .COM's memory isn't cleared)
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        call    args
        jc      fail
        mov     bx, prog_end + 15       ; ours, then two blocks: the text,
        shr     bx, 4                   ;  and the lines' offsets
        mov     ah, 4Ah
        int     21h
        mov     bx, MAXIN / 16 + 1      ; (+ the last line's 0)
        mov     ah, 48h
        int     21h
        mov     dx, s_mem
        jc      fail
        mov     [tseg], ax
        mov     bx, MAXL * 2 / 16
        mov     ah, 48h
        int     21h
        jc      fail
        mov     [lseg], ax
        call    rd_all                  ; the input -> tseg:0, tlen
        jc      fail
        call    split                   ; -> lseg's offsets, nlines
        jc      fail
        call    shell
        call    wr_all
        mov     ax, 4C00h
        int     21h
fail:   mov     si, dx                  ; DX ($) to standard error
        xor     cx, cx
.l:     cmp     byte [si], '$'
        je      .w
        inc     si
        inc     cx
        jmp     .l
.w:     mov     bx, 2
        mov     ah, 40h
        int     21h
        mov     ax, 4C01h
        int     21h

; command tail: /R, /+n.  CF: DX
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
        mov     word [col], 0
.l:     lodsb
        cmp     al, 13
        je      .ok
        cmp     al, ' '
        je      .l
        cmp     al, 9
        je      .l
        cmp     al, '/'
        jne     .bad
        lodsb
        cmp     al, '+'
        je      .n
        and     al, 0DFh
        cmp     al, 'R'
        jne     .bad
        mov     byte [rev], 1
        jmp     .l
.n:     xor     ax, ax
        xor     cx, cx
.d:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .de
        xor     bh, bh
        imul    ax, ax, 10
        add     ax, bx
        inc     si
        inc     cx
        cmp     ax, 255
        jbe     .d
        jmp     short .bad
.de:    jcxz    .bad
        or      ax, ax
        jz      .bad
        dec     ax
        mov     [col], ax
        jmp     .l
.ok:    clc
        ret
.bad:   mov     dx, s_badsw
        stc
        ret

; standard input -> tseg:0 .. tlen, up to a Ctrl-Z (a file's, or typed at
; the keyboard: the console's reads never come back empty).  CF: too much
rd_all: xor     di, di
.l:     mov     cx, MAXIN
        sub     cx, di
        jz      .full
        cmp     cx, 4096
        jbe     .r
        mov     cx, 4096
.r:     push    ds
        mov     ds, [cs:tseg]
        mov     dx, di
        xor     bx, bx
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .x
        or      ax, ax
        jz      .x
        push    es                      ; a Ctrl-Z in what came: the end
        mov     es, [tseg]
        mov     cx, ax
        mov     bx, di
        mov     al, 1Ah
        repne   scasb
        pop     es
        jne     .on
        dec     di                      ; (at it)
        jmp     short .x
.on:    jmp     .l                      ; (DI past what came)
.full:  push    ds                      ; full: is there more?
        mov     dx, onec
        xor     bx, bx
        mov     cx, 1
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .x
        or      ax, ax
        jz      .x
        cmp     byte [onec], 1Ah
        je      .x
        mov     dx, s_mem
        stc
        ret
.x:     mov     [tlen], di
        clc
        ret

; the text's lines: their starts in lseg (nlines).  A line ends at its LF
; (and the CR before it); the text gets an LF at its end if it hasn't one,
; so every line has one.  (Nothing else in it is changed: a NUL is a
; character like any other.)  CF: too many
split:  push    es
        push    ds
        mov     cx, [tlen]
        mov     es, [lseg]
        mov     ds, [tseg]
        xor     di, di
        jcxz    .done
        mov     si, cx                  ; the last LF
        cmp     byte [si-1], 10
        je      .s
        mov     byte [si], 10
        inc     cx
.s:     xor     si, si                  ; SI: a line's start
.ln:    cmp     di, MAXL * 2
        jae     .many
        mov     ax, si
        stosw
.c:     lodsb                           ; to its LF
        cmp     al, 10
        jne     .c
        cmp     si, cx
        jb      .ln
.done:  pop     ds
        pop     es
        shr     di, 1
        mov     [nlines], di
        clc
        ret
.many:  pop     ds
        pop     es
        mov     dx, s_mem
        stc
        ret

; Shell's sort of the starts
shell:  mov     ax, [nlines]
        cmp     ax, 2
        jb      .x
        mov     bx, 1                   ; gaps 1, 4, 13, 40 ...
.g:     mov     ax, bx
        imul    ax, ax, 3
        inc     ax
        cmp     ax, [nlines]
        jae     .go
        mov     bx, ax
        jmp     .g
.go:    mov     [gap], bx
.pass:  mov     si, [gap]               ; i = gap .. n-1
.i:     cmp     si, [nlines]
        jae     .np
        push    es
        mov     es, [lseg]
        mov     bx, si
        shl     bx, 1
        mov     ax, [es:bx]             ; the line at i
        pop     es
        mov     [hold], ax
        mov     di, si                  ; j = i
.j:     cmp     di, [gap]
        jb      .put
        mov     bx, di
        sub     bx, [gap]
        push    es
        mov     es, [lseg]
        shl     bx, 1
        mov     dx, [es:bx]             ; the line at j - gap
        pop     es
        mov     ax, [hold]
        call    before                  ; hold before it?  then it moves on
        jnc     .put
        push    es
        mov     es, [lseg]
        mov     bx, di
        shl     bx, 1
        mov     [es:bx], dx
        pop     es
        sub     di, [gap]
        jmp     .j
.put:   push    es
        mov     es, [lseg]
        mov     bx, di
        shl     bx, 1
        mov     ax, [hold]
        mov     [es:bx], ax
        pop     es
        inc     si
        jmp     .i
.np:    mov     ax, [gap]               ; the next gap
        cmp     ax, 1
        je      .x
        xor     dx, dx
        mov     bx, 3
        div     bx
        mov     [gap], ax
        jmp     .pass
.x:     ret

; does the line at AX come before the line at DX: from the column on, the
; letters' case aside, a shorter one first (/R: the other way); the same,
; the one that came first in the input (so equal lines keep their order).
; CF if so.  BX, CX, DX, SI, DI kept
before:
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    ds
        mov     [tie1], ax              ; (the two starts: their order, if
        mov     [tie2], dx              ;  they are the same)
        mov     cx, [col]
        mov     bl, [rev]
        mov     si, ax
        mov     di, dx
        mov     ds, [cs:tseg]
        call    .skip                   ; both to the column (or their end)
        xchg    si, di
        call    .skip
        xchg    si, di
.l:     call    .get                    ; AX, DX: a character + 1 each, 0 at
        mov     dx, ax                  ;  the end
        xchg    si, di
        call    .get
        xchg    si, di
        xchg    ax, dx                  ; AX: the first's, DX: the second's
        cmp     ax, dx
        jne     .d
        or      ax, ax
        jnz     .l
        mov     ax, [cs:tie1]           ; the same: the order they came in
        cmp     ax, [cs:tie2]
        jmp     short .x
.d:     or      bl, bl                  ; CF: the first's < the second's
        jnz     .rv                     ;  (before), the other way with /R
        cmp     ax, dx
        jmp     short .x
.rv:    cmp     dx, ax
.x:     pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        ret
; DS:SI's next character, upper case, + 1 -> AX (SI past it); its line's
; end (LF, or CR LF): 0 (SI kept)
.get:   mov     al, [si]
        cmp     al, 10
        je      .end
        cmp     al, 13
        jne     .ch
        cmp     byte [si+1], 10
        je      .end
.ch:    inc     si
        cmp     al, 'a'
        jb      .u
        cmp     al, 'z'
        ja      .u
        sub     al, 20h
.u:     xor     ah, ah
        inc     ax
        ret
.end:   xor     ax, ax
        ret
.skip:  jcxz    .sx                     ; past CX characters, not its end
        push    cx
.sl:    call    .get
        or      ax, ax
        jz      .se
        loop    .sl
.se:    pop     cx
.sx:    ret

; the lines, in order, to standard output (each with CR LF)
wr_all: xor     si, si
.l:     cmp     si, [nlines]
        jae     .x
        push    es
        mov     es, [lseg]
        mov     bx, si
        shl     bx, 1
        mov     dx, [es:bx]
        mov     es, [tseg]
        mov     di, dx                  ; its length: to its LF, less a CR
        mov     al, 10                  ;  before it
        mov     cx, 0FFFFh
        repne   scasb
        dec     di                      ; (at the LF)
        mov     cx, di
        sub     cx, dx
        jcxz    .w
        cmp     byte [es:di-1], 13
        jne     .w
        dec     cx
.w:     pop     es
        push    ds
        mov     ds, [tseg]
        mov     bx, 1
        mov     ah, 40h
        int     21h
        pop     ds
        mov     dx, s_crlf
        mov     cx, 2
        mov     bx, 1
        mov     ah, 40h
        int     21h
        inc     si
        jmp     .l
.x:     ret

s_crlf  db 13, 10
s_badsw db 'SORT: Invalid parameter (SORT [/R] [/+n])', 13, 10, '$'
s_mem   db 'SORT: Insufficient memory (63 KB of input at most)', 13, 10, '$'

        alignb 2
section .bss
bss_start:
rev     resb 1
onec    resb 1
col     resw 1
tseg    resw 1
lseg    resw 1
tlen    resw 1
nlines  resw 1
gap     resw 1
hold    resw 1
tie1    resw 1
tie2    resw 1
        resb 512
stack_top:
bss_end:
prog_end:
