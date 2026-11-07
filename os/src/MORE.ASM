; MORE.COM - a screen at a time (DOS 3.30's MORE) for Lodestone
;
;   MORE < name         TYPE name | MORE         MORE name
;
; Its input (or the file named) to the screen, stopping at "-- More --"
; when a screen is full, for a key.  The screen's size is the BIOS's
; (40:4Ah columns, 40:84h + 1 rows, 25 if it says 0); a line longer than
; the screen counts as the rows it takes, a tab as up to the next of every
; eighth column.  The key comes from the keyboard itself (the input is the
; pipe); Ctrl-C there ends it.  Ctrl-Z in the input is its end.
; Exit code: 0, or 1 (the file can't be opened).
cpu 286
org 100h

CHUNK   equ 4096

start:  mov     sp, stack_top
        cld
        xor     bx, bx                  ; the input: handle 0, or the file
        mov     si, 81h
        mov     cl, [80h]
        xor     ch, ch
        add     cx, si
        mov     di, cx
        mov     byte [di], 0
.sp:    lodsb
        cmp     al, ' '
        je      .sp
        cmp     al, 9
        je      .sp
        or      al, al
        jz      .in
        cmp     al, 13
        je      .in
        lea     dx, [si-1]              ; a name: to its end
.e:     lodsb
        cmp     al, ' '
        ja      .e
        mov     byte [si-1], 0
        mov     ax, 3D00h
        int     21h
        mov     dx, s_nofile
        jc      fail
        mov     bx, ax
.in:    mov     [hin], bx
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [44Ah]              ; the screen: columns, rows
        mov     dl, [484h]
        pop     ds
        or      ax, ax
        jnz     .c
        mov     ax, 80
.c:     mov     [cols], ax
        xor     dh, dh
        or      dl, dl
        jnz     .r
        mov     dl, 24
.r:     mov     [rows], dx              ; (rows - 1: the prompt's row is
        xor     di, di                  ;  the last)  DI = out's length
        xor     bp, bp                  ; BP = the column
        mov     word [row], 0
.rd:    mov     bx, [hin]
        mov     cx, CHUNK
        mov     dx, ibuf
        mov     ah, 3Fh
        int     21h
        jc      .end
        or      ax, ax
        jz      .end
        mov     cx, ax
        mov     si, ibuf
.ch:    lodsb
        cmp     al, 1Ah
        je      .end
        call    one
        loop    .ch
        jmp     .rd
.end:   call    flush
        mov     ax, 4C00h
        int     21h
fail:   mov     ah, 9
        int     21h
        mov     ax, 4C01h
        int     21h

; character AL out, the rows counted; a full screen: the prompt
one:    mov     [obuf+di], al
        inc     di
        cmp     di, OBUF
        jb      .k
        call    flush
.k:     cmp     al, 10
        je      .nl
        cmp     al, 13
        je      .cr
        cmp     al, 9
        je      .tab
        cmp     al, 8
        je      .bs
        cmp     al, 7                   ; (a bell takes no room)
        je      .x
        inc     bp
        cmp     bp, [cols]
        jb      .x
        xor     bp, bp                  ; wrapped: the next row
        jmp     short .row
.tab:   or      bp, 7
        inc     bp
        cmp     bp, [cols]
        jb      .x
        xor     bp, bp
        jmp     short .row
.bs:    or      bp, bp
        jz      .x
        dec     bp
        ret
.cr:    xor     bp, bp
        ret
.nl:    xor     bp, bp
.row:   inc     word [row]
        mov     ax, [row]
        cmp     ax, [rows]
        jb      .x
        call    flush                   ; a screen: "-- More --" and a key
        push    cx
        push    si
        mov     dx, s_more
        call    con
        mov     ah, 1                   ; (keys typed before it: not this)
.fl:    int     16h
        jz      .wk
        xor     ah, ah
        int     16h
        mov     ah, 1
        jmp     .fl
.wk:    xor     ah, ah
        int     16h
        cmp     al, 3                   ; Ctrl-C: the end
        je      .stop
        mov     dx, s_unmore
        call    con
        pop     si
        pop     cx
        mov     word [row], 0
.x:     ret
.stop:  mov     dx, s_crlf
        call    con
        mov     ax, 4C00h
        int     21h

; out to standard output
flush:  push    ax
        push    bx
        push    cx
        push    dx
        mov     cx, di
        jcxz    .x
        mov     dx, obuf
        mov     bx, 1
        mov     ah, 40h
        int     21h
.x:     xor     di, di
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

; DX ($) to the screen (standard error: not the output, if that goes on
; through a pipe or into a file)
con:    push    bx
        push    cx
        mov     bx, dx
        xor     cx, cx
.l:     cmp     byte [bx], '$'
        je      .w
        inc     bx
        inc     cx
        jmp     .l
.w:     mov     bx, 2
        mov     ah, 40h
        int     21h
        pop     cx
        pop     bx
        ret

s_more  db '-- More --$'
s_unmore db 13, '          ', 13, '$'
s_crlf  db 13, 10, '$'
s_nofile db 'MORE: the file can', 39, 't be opened', 13, 10, '$'

OBUF    equ 256
        alignb 2
section .bss
hin     resw 1
cols    resw 1
rows    resw 1
row     resw 1
obuf    resb OBUF
ibuf    resb CHUNK
        resb 512
stack_top:
