; =====================================================================
;  SCREEN.PRN - Lodestone's screen capture to a file     nasm -f bin
;
;  Shift-PrtSc (and PrtSc with no printer driver set) runs this, as PrtSc
;  runs a printer driver (PS.ASM says how one is read and called), from
;  the root of the drive Lodestone started from (R: from the ROM).  It
;  was the kernel's own code until 2026-11-03, when it moved here,
;  so no DOS program pays for it in memory.  Unlike a printer
;  driver it uses DOS, for its file: the kernel calls it at the start of
;  an INT 21h call that no other is inside, so its own are nested ones
;  (on the kernel's second stack), and a disk error in them fails at once
;  (no INT 24h while a capture runs).
;
;  In: DL = the drive to save on (A:, or C: from the ROM: KROM.INC's
;  capdrv), DH = 1 if it may borrow the disk cache's memory for its
;  buffer (INT 21h F002h, given back with F003h: only in the Executive;
;  under a DOS program that memory may be the program's, with EMS).  Else
;  its buffer is the rest of its 1 KB after its code.
;
;  The screen goes to SCREENnn.TXT (a text mode: the page's characters,
;  line by line, trailing blanks off) or SCREENnn.BMP (a graphics mode:
;  640 x 400, 1 bit, the plasma's colours; 200-line modes each line
;  twice), nn the first number from 01 to 99 not taken.  A write that
;  fails leaves no file.  Out: AL = 0 saved, 1 not (the kernel beeps once
;  or long).
; =====================================================================
cpu 286
org 0

        jmp     short start
        db      'PRN', 1                ; (the signature the kernel checks)

start:  push    cs
        pop     ds
        mov     [cap_name], dl
        mov     [lend], dh
        mov     byte [bad], 0
        push    0
        pop     es
        mov     al, [es:449h]           ; the video mode
        cbw
        xchg    bp, ax
        mov     ax, 'TX'
        mov     dl, 'T'
        cmp     bp, 3
        jbe     .ext
        mov     ax, 'BM'
        mov     dl, 'P'
.ext:   mov     [cap_ext], ax
        mov     [cap_ext+2], dl
        xor     di, di
.next:  inc     di                      ; the first number not taken
        cmp     di, 99
        ja      .fail
        mov     ax, di
        aam
        add     ax, '00'
        xchg    al, ah
        mov     [cap_num], ax
        mov     ah, 5Bh
        xor     cx, cx
        mov     dx, cap_name
        int     21h
        jnc     .made
        cmp     al, 50h
        je      .next
.fail:  mov     al, 1
        retf
.made:  xchg    bx, ax                  ; BX = the file
        push    cs                      ; the buffer: our own 1 KB's rest,
        pop     es                      ;  or the cache's memory, at ES:0
        mov     di, buf
        mov     cx, 1024
        cmp     byte [lend], 0
        je      .buf
        mov     ax, 0F002h
        int     21h
        jc      .own
        xor     di, di
        mov     byte [lent], 1
        jmp     short .buf
.own:   push    cs
        pop     es
        mov     cx, 1024
.buf:   mov     [cap_lim], cx
        mov     [cap_base], di
        cmp     bp, 3
        ja      .bmp
        push    0                       ; text: the page's characters, line
        pop     ds                      ;  by line, without trailing blanks
        mov     si, [44Eh]
        mov     bp, [44Ah]              ; (columns)
        push    0B800h
        pop     ds
        mov     dx, 25
.line:  mov     cx, bp
        push    si
        add     si, bp
        add     si, bp
.len:   dec     si
        dec     si
        test    byte [si], 0DFh         ; (ZF: a blank or a NUL)
        jnz     .go2
        loop    .len
.go2:   pop     si
        push    si
        jcxz    .eol
.ch:    lodsw
        test    al, 0DFh
        jnz     .c
        mov     al, ' '
.c:     call    cap_b
        loop    .ch
.eol:   mov     al, 13
        call    cap_b
        mov     al, 10
        call    cap_b
        pop     si
        add     si, bp
        add     si, bp
        dec     dx
        jnz     .line
        jmp     .end
.bmp:   mov     si, bmp_hdr
        mov     cx, 62
        rep     movsb                   ; (the buffer is empty)
        mov     dx, 399
        push    0B800h
        pop     ds
.row:   mov     si, dx                  ; bottom up: line DX's bank
        and     si, 3
        cmp     bp, 6
        ja      .r4
        shr     si, 1                   ; (200 lines: 2 banks, each line twice)
.r4:    ror     si, 3
        mov     ax, dx
        shr     ax, 2
        imul    ax, ax, 80
        add     si, ax
        mov     cx, 80
.px:    lodsb
        call    cap_b
        loop    .px
        dec     dx
        jns     .row
.end:   call    cap_fl                  ; the rest
        push    cs
        pop     ds
        mov     ah, 3Eh
        int     21h
        jnc     .cl
        mov     byte [bad], 1           ; (it didn't close: the file goes)
.cl:    cmp     byte [lent], 0
        je      .nl
        mov     ax, 0F003h              ; the cache's memory back
        int     21h
.nl:    xor     ax, ax
        cmp     byte [bad], 0
        je      .x
        mov     ah, 41h                 ; not all of it: none of it
        mov     dx, cap_name
        int     21h
        mov     al, 1
.x:     retf

; AL to the file (BX) through the buffer at ES:DI; full, it is written
; (cap_fl).  A write that fails sets bad, and none is tried after it
cap_b:  stosb
        cmp     di, [cs:cap_lim]
        jb      cap_fl.x
cap_fl: cmp     byte [cs:bad], 0
        jne     .z
        push    ds
        pusha
        push    es
        pop     ds
        mov     dx, [cs:cap_base]
        mov     cx, di
        sub     cx, dx
        mov     ah, 40h
        int     21h
        jc      .bad
        cmp     ax, cx
        je      .ok
.bad:   mov     byte [cs:bad], 1
.ok:    popa
        pop     ds
.z:     mov     di, [cs:cap_base]
.x:     ret

bmp_hdr db 'BM'
        dd 62 + 32000, 0, 62            ; size, -, where the pixels start
        dd 40, 640, 400                 ; BITMAPINFOHEADER
        dw 1, 1                         ; 1 plane, 1 bit
        dd 0, 32000, 0, 0, 2, 0
        db 2, 8, 36, 0, 40, 120, 255, 0 ; dark red, the plasma's orange (B, G, R)
cap_name db 'A:\SCREEN'
cap_num db '00.'
cap_ext db 'BMP', 0
lend    db 0                            ; (these are read afresh with the
lent    db 0                            ;  file at every capture)
bad     db 0
        align 2
cap_lim  dw 0
cap_base dw 0
buf:                                    ; the buffer when there's no cache
        times -(buf - $$ > 1024 - 256) db 0     ; (room for one of 256 bytes at least)
