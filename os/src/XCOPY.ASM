; XCOPY.COM - copies files and directories (DOS 3.30's XCOPY)
;
;   XCOPY source [destination] [/A] [/M] [/D:date] [/P] [/S] [/E] [/V] [/W]
;
;   source       files (wildcards as DIR's), or a directory (all of it)
;   destination  a directory (made as needed), a file name, or a name with
;                wildcards (*.BAK); the current directory if none.  A name
;                that isn't there: "Does B:\X specify a file name or
;                directory name on the target (F = file, D = directory)?"
;   /A           only files with the archive bit, which stays
;   /M           only files with the archive bit, cleared on each copied
;   /D:date      only files dated on or after it (mm-dd-yy or mm-dd-yyyy)
;   /P           asks before each file (Y/N)
;   /S           the directories below too (those with files in them)
;   /E           with /S, empty ones too
;   /V           each copy read back and compared with its source
;   /W           waits for a key before it starts
;
; As DOS's: it reads as many files as fit in memory, then writes them, so
; a floppy's heads move less than COPY's (a file bigger than memory goes
; through it a piece at a time); hidden and system files are skipped; each
; copy keeps its source's date and time and is a plain file (archive);
; a file is never copied onto itself, nor a tree into itself.  As the
; Executive's Copy: each copy is made as a new file in its directory (DOS's
; CREATE TEMPORARY) and takes its name only when all of it is there, so a
; full disk or a bad sector leaves the old destination as it was, and a
; file that fails is said and the rest go on.  The answers come through
; DOS, so XCOPY ... < ANS.TXT answers from a file (its line ends aren't
; answers).
;
; Paths are compared as the kernel reads them (CANON.INC: each part 8.3,
; "SUB." SUB), so no other spelling gets a file onto itself or a tree into
; itself.  Into the directory it reads (XCOPY *.* *.BAK), it lists the
; names first and copies from the list, so its own copies aren't read
; again.  A directory whose path would pass 63 characters after "D:\" is
; said ("Path too long - ") and left out.  Ctrl-C says how many were
; copied: files held in memory then aren't.  As the Executive's Copy: a
; hidden or system destination is replaced by a plain copy, and a copy
; needs room for the old and new files at once (the new one takes the
; name only when it is all there).
;
; Exit code (DOS's): 0 copied, 1 no files found, 2 Ctrl-C, 4 couldn't start
; (a bad switch or path, no memory, a cyclic copy, a file onto itself), 5
; a file failed (a full disk, a write error, a path too long: each said).
cpu 286
org 100h

MAXDEPTH equ 34                         ; (PMAX's 63: "X\" 31 times at most)
DTASZ   equ 44
QMAX    equ 40                          ; files held in memory at once
QSZ     equ 176                         ; a held file's record:
LMAX    equ 4096                        ; samedir: names at most
Q_SRC   equ 0                           ;  its source (82)
Q_DST   equ 82                          ;  where it goes (82)
Q_SIZE  equ 164                         ;  dword
Q_TIME  equ 168
Q_DATE  equ 170
Q_SEG   equ 172                         ;  its data in memory (FFFFh: not
CHUNK   equ 8000h                       ;  held: copied a piece at a time)
VCH     equ 2048                        ; /V: compared a piece at a time
MINBUF  equ VCH / 16 * 2 + CHUNK / 16   ; the least memory it runs in

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     bx, prog_end + 15       ; the rest of memory: the buffer
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     bx, 0FFFFh
        mov     ah, 48h
        int     21h
        cmp     bx, MINBUF              ; (BX: as much as there is; less
        jae     .big                    ;  than it needs: that, which a
        mov     bx, MINBUF              ;  terminal window's task grows to
.big:   mov     ah, 48h                 ;  make room for)
        int     21h
        mov     dx, s_nomem
        jc      fail
        mov     [bufseg], ax
        mov     [bufparas], bx
        mov     dx, ctrlc
        mov     ax, 2523h
        int     21h
        mov     dx, crit
        mov     ax, 2524h
        int     21h
        mov     word [ohandle], 0FFFFh
        call    args
        jc      fail
        call    source
        jc      fail
        call    target
        jc      fail
        cmp     byte [subs], 0          ; /S into itself: no
        je      .w
        call    cyclic
        jc      fail
.w:     cmp     byte [waitk], 0
        je      .go
        mov     dx, s_wait
        call    print
        call    getkey
        call    crlf
.go:    mov     dx, s_reading
        call    print
        mov     word [depth], 0
        call    walk
        call    flush
        cmp     word [nfound], 0
        jne     .sum
        mov     dx, s_nf                ; "File not found - X"
        call    print
        mov     si, srcarg
        call    puts
        call    crlf
        mov     ax, 4C01h
        int     21h
.sum:   mov     ax, [ncopied]           ; "   n File(s) copied"
        mov     cx, 9
        call    pdecw
        mov     dx, s_copied
        call    print
        mov     al, 0
        cmp     byte [self], 0
        je      .s
        mov     al, 4
.s:     cmp     byte [werr], 0
        je      .x
        mov     al, 5
.x:     mov     ah, 4Ch
        int     21h

fail:   call    print
        mov     ax, 4C04h
        int     21h

; Ctrl-C: the copy being made goes (the old destination is still there)
ctrlc:  push    cs
        pop     ds
        mov     bx, [ohandle]
        cmp     bx, 0FFFFh
        je      .x
        mov     ah, 3Eh
        int     21h
        mov     dx, opath
        mov     ah, 41h
        int     21h
.x:     mov     ax, [ncopied]           ; "n File(s) copied": those held in
        mov     cx, 9                   ;  memory, not yet written, aren't
        call    pdecw
        mov     dx, s_copied
        call    print
        mov     ax, 4C02h
        int     21h
crit:   mov     al, 3                   ; (a critical error: Fail, said as
        iret                            ;  the call's own)

; ---------------------------------------------------------------------
; command tail: source, destination, switches.  CF: DX
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
        mov     di, srcarg              ; the first name the source, the
        cmp     byte [di], 0            ;  second where it goes
        je      .nm
        mov     di, dstarg
        cmp     byte [di], 0
        jne     .bad
.nm:    dec     si
        mov     cx, 80
.n:     lodsb
        cmp     al, ' '
        jbe     .ne
        cmp     al, '/'
        je      .ne
        call    upcase
        stosb
        loop    .n
        jmp     .bad
.ne:    dec     si
        mov     byte [di], 0
        jmp     .l
.sw:    lodsb
        call    upcase
        mov     bx, sw_a
        cmp     al, 'A'
        je      .set
        mov     bx, sw_m
        cmp     al, 'M'
        je      .set
        mov     bx, prompt
        cmp     al, 'P'
        je      .set
        mov     bx, subs
        cmp     al, 'S'
        je      .set
        mov     bx, empty
        cmp     al, 'E'
        je      .set
        mov     bx, verify
        cmp     al, 'V'
        je      .set
        mov     bx, waitk
        cmp     al, 'W'
        je      .set
        cmp     al, 'D'
        jne     .bad
        cmp     byte [si], ':'
        jne     .bad
        inc     si
        call    date
        jc      .bad
        mov     [ddate], ax
        mov     byte [dset], 1
        jmp     .l
.set:   mov     byte [bx], 1
        jmp     .l
.end:   cmp     byte [srcarg], 0
        mov     dx, s_noparm
        je      .x
        clc
        ret
.bad:   mov     dx, s_badsw
.x:     stc
        ret

; "mm-dd-yy" or "mm-dd-yyyy" ("/" or "." between too) at SI -> AX as a
; FAT date.  CF if not one
date:   call    num
        jc      .x
        cmp     ax, 12
        ja      .bad
        or      ax, ax
        jz      .bad
        mov     [dmon], ax
        call    sep
        jc      .x
        call    num
        jc      .x
        cmp     ax, 31
        ja      .bad
        or      ax, ax
        jz      .bad
        mov     [dday], ax
        call    sep
        jc      .x
        call    num
        jc      .x
        cmp     ax, 100                 ; two digits: 80-99 the 1900s,
        jae     .y4                     ;  00-79 the 2000s
        add     ax, 1900
        cmp     ax, 1980
        jae     .y4
        add     ax, 100
.y4:    sub     ax, 1980
        jb      .bad
        cmp     ax, 127
        ja      .bad
        shl     ax, 9
        mov     bx, [dmon]
        shl     bx, 5
        or      ax, bx
        or      ax, [dday]
        clc
        ret
.bad:   stc
.x:     ret
sep:    lodsb
        cmp     al, '-'
        je      .y
        cmp     al, '/'
        je      .y
        cmp     al, '.'
        je      .y
        stc
        ret
.y:     clc
        ret
num:    xor     ax, ax
        xor     cx, cx
.l:     mov     bl, [si]
        sub     bl, '0'
        cmp     bl, 9
        ja      .e
        imul    ax, ax, 10
        xor     bh, bh
        add     ax, bx
        inc     si
        inc     cx
        cmp     cx, 4
        jbe     .l
.e:     cmp     cx, 1                   ; (CF: no digits)
        ret

; ---------------------------------------------------------------------
; the source: its directory (sdir, absolute, "\" last) and the names in it
; (pat).  A directory named alone: all of it.  CF: DX
source: mov     si, srcarg
        call    lastpart                ; BX -> the last part (in srcarg)
        cmp     byte [bx], 0            ; "A:", "\SUB\": all of it
        je      .dir
        mov     si, bx
        call    haswild
        jc      .files
        mov     si, srcarg              ; a name alone: a directory?
        call    canon
        jc      .x
        call    isdir
        jnc     .whole
.files: push    bx                      ; its directory, and the names
        mov     si, bx                  ;  (8.3, as the kernel takes them)
        mov     di, pat
        call    part83
        pop     bx
        mov     al, [bx]
        push    ax
        mov     byte [bx], 0
        mov     si, srcarg
        call    canon
        pop     ax
        mov     [bx], al
        jc      .x
        jmp     short .set
.dir:   mov     si, srcarg
        call    canon
        jc      .x
.whole: mov     si, s_all
        mov     di, pat
        call    strcpy
.set:   call    cdir
        jc      .x
        mov     si, cpath
        mov     di, sdir
        call    dirset
        mov     [sdl], ax
        clc
.x:     ret

; where it goes: ddir ("\" last), and dkind: 0 a directory, 1 one file
; (dname), 2 names made from dname's wildcards.  CF: DX
target: cmp     byte [dstarg], 0        ; none: the current directory
        jne     .g
        mov     si, s_empty
        call    canon
        jc      .x
        jmp     .isd
.g:     mov     si, dstarg
        call    canon
        jc      .x
        mov     si, dstarg              ; "B:\", "B:", "SUB\": a directory
        call    strend
        mov     al, [di-1]
        cmp     al, '\'
        je      .isd
        cmp     al, ':'
        je      .isd
        cmp     byte [cpath+3], 0       ; (the root)
        je      .isd
        call    isdir
        jnc     .isd
        mov     si, dstarg              ; a name: wildcards?
        call    lastpart
        mov     si, bx
        call    haswild
        jnc     .name
        mov     byte [dkind], 2
        jmp     short .file
.name:  mov     dx, cpath               ; a file there already?
        mov     ax, 4300h
        int     21h
        jnc     .one
        call    ask_fd                  ; not there: a file, or a directory?
        jnc     .isd
.one:   mov     byte [dkind], 1
.file:  mov     si, bx                  ; dname (8.3), and its directory
        mov     di, dname
        call    part83
        mov     al, [bx]
        push    ax
        mov     byte [bx], 0
        mov     si, dstarg
        call    canon
        pop     ax
        mov     [bx], al
        jc      .x
.isd:   call    cdir
        jc      .x
        mov     si, cpath
        mov     di, ddir
        call    dirset
        mov     [ddl], ax
        clc
.x:     ret

; "Does B:\X specify a file name / or directory name on the target /
; (F = file, D = directory)?" -> CF: a file; NC: a directory
ask_fd: mov     dx, s_does
        call    print
        mov     si, cpath
        call    puts
        mov     dx, s_fd
        call    print
.k:     call    getkey
        cmp     al, 1Ah                 ; (the end of a file it reads)
        je      .eof
        call    upcase
        cmp     al, 'F'
        je      .f
        cmp     al, 'D'
        jne     .k
        call    putc
        call    crlf
        clc
        ret
.f:     call    putc
        call    crlf
        stc
        ret
.eof:   call    crlf
        mov     dx, s_noans
        jmp     fail

; /S: the destination inside the source's tree?  CF: DX
cyclic: mov     si, sdir
        mov     di, ddir
        mov     cx, [sdl]
        repe    cmpsb
        jne     .ok
        mov     dx, s_cyclic
        stc
        ret
.ok:    clc
        ret

; ---------------------------------------------------------------------
; sdir (sdl) to ddir (ddl): its files matching pat, then with /S each
; directory in it
walk:   call    set_dta
        mov     si, sdir                ; into the directory it reads?
        mov     di, ddir
        call    streq
        jne     .rd
        call    samedir
        jmp     short .sub
.rd:    mov     si, pat
        mov     di, sdir
        add     di, [sdl]
        call    strcpy
        mov     dx, sdir
        xor     cx, cx                  ; (no hidden or system files)
        mov     ah, 4Eh
        int     21h
.f:     jc      .sub
        mov     bx, [dta]
        test    byte [bx+21], 18h
        jnz     .fn
        call    one
.fn:    call    set_dta
        mov     ah, 4Fh
        int     21h
        jmp     .f
.sub:   cmp     byte [subs], 0          ; (no deeper than PMAX lets it:
        je      .x                      ;  MAXDEPTH's DTAs)
        mov     si, s_all
        mov     di, sdir
        add     di, [sdl]
        call    strcpy
        mov     dx, sdir
        mov     cx, 16h
        mov     ah, 4Eh
        int     21h
.d:     jc      .x
        mov     bx, [dta]
        test    byte [bx+21], 10h
        jz      .dn
        cmp     byte [bx+30], '.'
        je      .dn
        push    word [sdl]
        push    word [ddl]
        lea     si, [bx+30]             ; sdir + NAME + "\", ddir the same
        mov     di, sdir
        add     di, [sdl]
        mov     bp, sdir
        mov     cx, [sdl]
        call    subadd
        jc      .long
        sub     di, sdir
        mov     [sdl], di
        lea     si, [bx+30]
        mov     di, ddir
        add     di, [ddl]
        mov     bp, ddir
        mov     cx, [ddl]
        call    subadd
        jc      .long
        sub     di, ddir
        mov     [ddl], di
        cmp     byte [empty], 0         ; /E: made now, files or not
        je      .in
        call    mkdirs
        jnc     .in
        mov     byte [werr], 1
        mov     dx, s_mkdir
        mov     si, ddir
        call    say
.in:    inc     word [depth]
        call    walk
        dec     word [depth]
.dl:    pop     word [ddl]
        pop     word [sdl]
        call    set_dta
        mov     si, s_all               ; (sdir as the search had it)
        mov     di, sdir
        add     di, [sdl]
        call    strcpy
.dn:    mov     ah, 4Fh
        int     21h
        jmp     .d
.x:     ret
.long:  mov     di, bp                  ; "Path too long - B:\SUB\NAME": not
        add     di, cx                  ;  copied, said (CX: the length the
        mov     byte [di], 0            ;  buffer at BP had)
        mov     byte [werr], 1
        mov     dx, s_plong
        call    print
        mov     si, bp
        call    puts
        lea     si, [bx+30]
        call    say1
        jmp     .dl

; NAME at SI onto DI, then "\" (DI past it), none of it past PMAX after
; "D:\" (BP = the buffer's start).  CF: too long (nothing past it written)
subadd: lodsb
        or      al, al
        jz      .e
        mov     dx, di
        sub     dx, bp
        cmp     dx, 3 + PMAX
        jae     .long
        stosb
        jmp     subadd
.e:     mov     al, '\'
        stosb
        mov     byte [di], 0
        clc
        ret
.long:  stc
        ret

; sdir is ddir (XCOPY *.* *.BAK): the names matching pat listed first, at
; the top of the buffer, then each found again by its name and copied, so
; the copies made in the directory are never taken for its files (a .BAK
; there before is: "onto itself")
samedir:
        call    .find
        xor     bp, bp                  ; how many
.c:     jc      .room
        call    .is
        jnz     .cn
        inc     bp
        cmp     bp, LMAX
        jae     .nomem
.cn:    mov     ah, 4Fh
        int     21h
        jmp     .c
.room:  mov     ax, bp                  ; their room: 13 bytes each
        mov     cx, 13
        mul     cx
        add     ax, 15
        shr     ax, 4
        mov     [lparas], ax
        mov     cx, [bufparas]
        sub     cx, ax
        cmp     cx, MINBUF
        jb      .nomem
        mov     [bufparas], cx
        add     cx, [bufseg]
        mov     [lseg], cx
        mov     [lnum], bp
        call    .find                   ; the names
        xor     di, di
        mov     cx, [lnum]
.l:     jc      .go
        jcxz    .go
        call    .is
        jnz     .ln
        push    cx
        push    es
        mov     es, [lseg]
        lea     si, [bx+30]
        mov     cx, 13
        rep     movsb
        pop     es
        pop     cx
        dec     cx
.ln:    mov     ah, 4Fh
        int     21h
        jmp     .l
.go:    mov     ax, di                  ; (as many as were found again)
        xor     dx, dx
        mov     cx, 13
        div     cx
        mov     [lnum], ax
        xor     ax, ax
        mov     [lidx], ax
.e:     mov     ax, [lidx]              ; each: sdir + its name, found
        cmp     ax, [lnum]
        jae     .x
        inc     word [lidx]
        mov     cx, 13
        mul     cx
        mov     si, ax
        mov     di, sdir
        add     di, [sdl]
        push    ds
        mov     ds, [lseg]
        rep     movsb
        pop     ds
        mov     dx, sdir
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        jc      .e
        call    .is
        jnz     .e
        call    one
        jmp     .e
.x:     mov     ax, [lparas]            ; (the held files' memory is below)
        add     [bufparas], ax
        ret
.nomem: mov     dx, s_nomem
        jmp     fail
.find:  mov     si, pat                 ; 4Eh: sdir + pat
        mov     di, sdir
        add     di, [sdl]
        call    strcpy
        mov     dx, sdir
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        ret
.is:    mov     bx, [dta]               ; ZF: a file (not a directory or
        test    byte [bx+21], 18h       ;  the label)
        ret

set_dta:
        push    ax
        push    bx
        push    dx
        mov     ax, [depth]
        mov     bx, DTASZ
        mul     bx
        add     ax, dtas
        mov     [dta], ax
        mov     dx, ax
        mov     ah, 1Ah
        int     21h
        pop     dx
        pop     bx
        pop     ax
        ret

; the file in the DTA at [dta]: chosen?  Then read into memory, to be
; written when memory is full or at the end
one:    mov     bx, [dta]
        mov     al, [bx+21]
        mov     ah, [sw_a]              ; /A, /M: its archive bit
        or      ah, [sw_m]
        jz      .dt
        test    al, 20h
        jz      .x
.dt:    cmp     byte [dset], 0          ; /D: its date
        je      .ok
        mov     ax, [bx+24]
        cmp     ax, [ddate]
        jb      .x
.ok:    inc     word [nfound]
        lea     si, [bx+30]             ; its source: sdir + NAME
        mov     di, sdir
        add     di, [sdl]
        call    strcpy
        mov     di, ddir                ; where it goes: ddir + a name
        add     di, [ddl]
        lea     si, [bx+30]
        cmp     byte [dkind], 0
        je      .dn
        mov     si, dname
        cmp     byte [dkind], 1
        je      .dn
        lea     si, [bx+30]             ; (dname's wildcards)
        call    tname
        jmp     short .same
.dn:    call    strcpy
.same:  mov     si, sdir                ; onto itself?
        mov     di, ddir
        call    streq
        jne     .new
        mov     byte [self], 1
        mov     dx, s_self
        mov     si, sdir
        jmp     say
.new:   cmp     byte [prompt], 0        ; /P: "A:\X.TXT (Y/N)?"
        je      .take
        mov     si, sdir
        call    puts
        mov     dx, s_yn
        call    print
.k:     call    getkey                  ; (a file's line ends: not answers)
        cmp     al, 13
        je      .k
        cmp     al, 10
        je      .k
        push    ax
        cmp     al, ' '
        jb      .pe
        call    putc
.pe:    call    crlf
        pop     ax
        call    upcase
        cmp     al, 'Y'
        jne     .x
.take:  jmp     hold
.x:     ret

; DOS's name made from dname's wildcards for the name at SI -> DI
; (ASCIIZ), as COPY makes one: both as 11-character fields (a * fills the
; rest of its part with ?), then each ? the name's own character there
tname:  push    bx
        push    di
        mov     di, sfcb
        call    to_fcb
        mov     si, dname
        mov     di, tfcb
        call    to_fcb
        xor     bx, bx
.c:     mov     al, [tfcb+bx]
        cmp     al, '?'
        jne     .k
        mov     al, [sfcb+bx]
.k:     mov     [rfcb+bx], al
        inc     bx
        cmp     bx, 11
        jb      .c
        pop     di
        mov     si, rfcb                ; "NAME.EXT" from it
        mov     cx, 8
.b:     lodsb
        cmp     al, ' '
        je      .bs
        stosb
.bs:    loop    .b
        cmp     byte [rfcb+8], ' '
        je      .ne
        mov     al, '.'
        stosb
        mov     cx, 3
.e:     lodsb
        cmp     al, ' '
        je      .es
        stosb
.es:    loop    .e
.ne:    mov     byte [di], 0
        pop     bx
        ret

; the name at SI ("NAME.EXT", wildcards or not) -> the 11 bytes at DI
to_fcb: push    di
        mov     cx, 11
        mov     al, ' '
        rep     stosb
        pop     di
        push    di
        mov     cx, 8
        call    .fld
        pop     di
        add     di, 8
        mov     cx, 3
        cmp     byte [si], '.'
        jne     .x
        inc     si
        call    .fld
.x:     ret
.fld:   lodsb                           ; one part, CX characters at most
        or      al, al
        jz      .end
        cmp     al, '.'
        je      .end
        cmp     al, '*'
        je      .st
        jcxz    .fld                    ; (more than fits: left out)
        stosb
        dec     cx
        jmp     .fld
.st:    jcxz    .fld
        mov     al, '?'
        rep     stosb
        jmp     .fld
.end:   dec     si                      ; (the "." or the end left there)
        ret

; ---------------------------------------------------------------------
; the chosen file (sdir, ddir, the DTA): held in memory, or, bigger than
; memory, copied a piece at a time.  Memory full: the held ones written
hold:   mov     bx, [dta]
        mov     ax, [bx+26]             ; its paragraphs
        mov     dx, [bx+28]
        add     ax, 15
        adc     dx, 0
        mov     cx, 16
        cmp     dx, cx
        jae     .big
        div     cx
        cmp     ax, [bufparas]
        ja      .big
        mov     cx, ax
        mov     ax, [qcur]
        add     ax, cx
        jc      .fl
        cmp     ax, [bufparas]
        ja      .fl
        cmp     word [qn], QMAX
        jb      .room
.fl:    push    cx
        call    flush
        pop     cx
.room:  call    qrec                    ; DI = its record
        mov     ax, [qcur]
        mov     [di+Q_SEG], ax
        add     [qcur], cx
        push    cx
        call    readin
        pop     cx
        jc      .rf
        inc     word [qn]
        ret
.rf:    sub     [qcur], cx              ; (it couldn't be read: said)
        ret
.big:   call    flush                   ; bigger than memory
        call    qrec
        mov     word [di+Q_SEG], 0FFFFh
        mov     si, sdir
        call    puts
        call    crlf
        jmp     wfile

; DI = the next record, its source, destination, size, date, time
qrec:   mov     ax, [qn]
        mov     bx, QSZ
        mul     bx
        add     ax, queue
        mov     di, ax
        push    di
        mov     si, sdir
        call    strcpy
        pop     di
        push    di
        add     di, Q_DST
        mov     si, ddir
        call    strcpy
        pop     di
        mov     bx, [dta]
        mov     ax, [bx+26]
        mov     [di+Q_SIZE], ax
        mov     ax, [bx+28]
        mov     [di+Q_SIZE+2], ax
        mov     ax, [bx+22]
        mov     [di+Q_TIME], ax
        mov     ax, [bx+24]
        mov     [di+Q_DATE], ax
        ret

; the record at DI's source into its memory ("A:\X.TXT" said as it is
; read).  CF: it couldn't be (said)
readin: push    di
        mov     si, di
        call    puts
        call    crlf
        pop     di
        mov     dx, di
        mov     ax, 3D00h
        int     21h
        jc      .err
        mov     bx, ax
        mov     ax, [di+Q_SEG]
        add     ax, [bufseg]
        mov     cx, [di+Q_SIZE]
        mov     dx, [di+Q_SIZE+2]
        call    xread
        pushf
        mov     ah, 3Eh
        int     21h
        popf
        jnc     .x
.err:   mov     byte [werr], 1
        mov     dx, s_cantrd
        mov     si, di
        call    say
        stc
.x:     ret

; DX:CX bytes from handle BX into memory from segment AX, 32 KB at a
; time (AH = 3Fh; xwrite: 40h, to the handle).  CF if it fails ([xerr]
; 1: DOS said so) or comes up short ([xerr] 0: a write's, the disk full)
xread:  mov     byte [xop], 3Fh
        jmp     short xio
xwrite: mov     byte [xop], 40h
xio:    pusha
        push    ds
        mov     byte [xerr], 1
        mov     bp, ax
        mov     si, cx                  ; DI:SI = bytes left
        mov     di, dx
.l:     mov     cx, CHUNK
        or      di, di
        jnz     .n
        cmp     si, cx
        jae     .n
        mov     cx, si
        jcxz    .ok
.n:     mov     ah, [cs:xop]
        mov     ds, bp
        xor     dx, dx
        int     21h
        push    cs
        pop     ds
        jc      .x
        cmp     ax, cx
        je      .on
        mov     byte [xerr], 0
        stc
        jmp     short .x
.on:
        sub     si, cx
        sbb     di, 0
        add     bp, CHUNK / 16
        jmp     .l
.ok:    clc
.x:     pop     ds
        popa
        ret

; the held files written
flush:  xor     bx, bx
.l:     cmp     bx, [qn]
        jae     .x
        push    bx
        mov     ax, bx
        mov     cx, QSZ
        mul     cx
        add     ax, queue
        mov     di, ax
        call    wfile
        pop     bx
        inc     bx
        jmp     .l
.x:     mov     word [qn], 0
        mov     word [qcur], 0
        ret

; ---------------------------------------------------------------------
; the record at DI written to its destination: its directory made if need
; be, a new file in it (CREATE TEMPORARY) written, dated and closed, then
; the old destination erased and the new file given its name.  Whatever
; fails: said, the new file gone, the old destination as it was
wfile:  mov     [rec], di
        lea     si, [di+Q_DST]          ; its directory: opath = it, "\" last
        mov     di, opath
        call    strcpy
        mov     di, opath
        call    lastpart_di             ; BX -> past the last "\"
        mov     byte [bx], 0
        call    mkdirs_o
        jc      .mkf
        mov     dx, opath
        xor     cx, cx
        mov     ah, 5Ah
        int     21h
        jc      .cant
        mov     [ohandle], ax
        mov     di, [rec]
        cmp     word [di+Q_SEG], 0FFFFh
        je      .stream
        mov     bx, ax                  ; from memory
        mov     ax, [di+Q_SEG]
        add     ax, [bufseg]
        mov     cx, [di+Q_SIZE]
        mov     dx, [di+Q_SIZE+2]
        call    xwrite
        jnc     .done
        cmp     byte [xerr], 0          ; (short: the disk is full; an
        je      .full                   ;  error: said as one)
        mov     dx, s_wrerr
        jmp     .undo
.stream:
        call    stream
        jc      .sfail
.done:  mov     bx, [ohandle]
        mov     di, [rec]
        mov     cx, [di+Q_TIME]
        mov     dx, [di+Q_DATE]
        mov     ax, 5701h
        int     21h
        mov     ah, 3Eh                 ; (closing writes the rest out)
        int     21h
        mov     word [ohandle], 0FFFFh
        jc      .full2
        mov     di, [rec]               ; the old destination: a file, not
        lea     dx, [di+Q_DST]          ;  read-only, or none
        mov     ax, 4300h
        int     21h
        jc      .name
        test    cl, 11h
        jnz     .deny
        mov     ah, 41h
        int     21h
        jc      .deny
.name:  mov     di, [rec]
        mov     dx, opath
        lea     di, [di+Q_DST]
        mov     ah, 56h
        int     21h
        jc      .kept
        cmp     byte [verify], 0
        je      .m
        call    vfy
        jc      .vbad
.m:     cmp     byte [sw_m], 0          ; /M: the source's archive bit off
        je      .c
        mov     di, [rec]
        mov     dx, di
        mov     ax, 4300h
        int     21h
        jc      .c
        and     cx, 27h & ~20h
        mov     ax, 4301h
        int     21h
.c:     inc     word [ncopied]
        ret
.sfail: cmp     al, 1                   ; (stream: AL = 1 a read failed,
        mov     dx, s_cantrd            ;  2 a write did, 0 short)
        je      .undo
        mov     dx, s_wrerr
        cmp     al, 2
        je      .undo
        jmp     short .full
.full:  mov     dx, s_full
.undo:  mov     bx, [ohandle]
        mov     ah, 3Eh
        int     21h
        mov     word [ohandle], 0FFFFh
        jmp     short .gone
.full2: mov     dx, s_full
.gone:  push    dx
        mov     dx, opath               ; the new file goes
        mov     ah, 41h
        int     21h
        pop     dx
        jmp     short .bad
.deny:  push    dx
        mov     dx, opath
        mov     ah, 41h
        int     21h
        pop     dx
        mov     dx, s_deny
        jmp     short .bad
.kept:  mov     dx, s_kept              ; "Copy kept as B:\SUB\ABCDTMP - B:\X"
        call    print
        mov     si, opath
        call    puts
        mov     dx, s_dash
        jmp     short .bad
.vbad:  mov     dx, s_vfy
        jmp     short .bad
.mkf:   mov     dx, s_mkdir
        mov     si, opath
        mov     byte [werr], 1
        jmp     say
.cant:  mov     dx, s_cantwr
.bad:   mov     byte [werr], 1
        mov     si, [rec]
        add     si, Q_DST
        jmp     say

; a file bigger than memory: its source to [ohandle] through the buffer.
; CF: AL = 0 a write failed (or came up short), 1 a read
stream: mov     di, [rec]
        mov     dx, di
        mov     ax, 3D00h
        int     21h
        jc      .of
        mov     [ihandle], ax
.l:     mov     bx, [ihandle]
        mov     cx, CHUNK
        push    ds
        mov     ds, [bufseg]
        xor     dx, dx
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .rf
        or      ax, ax
        jz      .end
        mov     cx, ax
        mov     bx, [ohandle]
        push    ds
        mov     ds, [bufseg]
        xor     dx, dx
        mov     ah, 40h
        int     21h
        pop     ds
        jc      .we
        cmp     ax, cx
        jne     .wf
        jmp     .l
.we:    call    .close
        mov     al, 2
        stc
        ret
.end:   call    .close
        clc
        ret
.rf:    call    .close
        mov     al, 1
        stc
        ret
.wf:    call    .close
        xor     al, al
        stc
        ret
.of:    mov     al, 1                   ; (the source won't open)
        ret
.close: mov     bx, [ihandle]
        mov     ah, 3Eh
        int     21h
        ret

; /V: the copy (the record's destination) read back and compared with
; its source (memory, or the source file).  CF if they differ
vfy:    mov     di, [rec]
        lea     dx, [di+Q_DST]
        mov     ax, 3D00h
        int     21h
        jc      .bad
        mov     [vh1], ax
        mov     word [vh2], 0FFFFh
        cmp     word [di+Q_SEG], 0FFFFh
        jne     .mem
        mov     dx, di                  ; (streamed: the source again)
        mov     ax, 3D00h
        int     21h
        jc      .bc
        mov     [vh2], ax
.mem:   mov     ax, [di+Q_SEG]
        add     ax, [bufseg]
        mov     [vseg], ax
        mov     word [voff], 0
.l:     mov     bx, [vh1]
        mov     cx, VCH
        mov     dx, vbuf
        mov     ah, 3Fh
        int     21h
        jc      .bc
        mov     [vn], ax
        or      ax, ax
        jz      .eof
        cmp     word [vh2], 0FFFFh
        je      .cm
        mov     bx, [vh2]               ; the source's piece
        mov     cx, ax
        mov     dx, vbuf2
        mov     ah, 3Fh
        int     21h
        jc      .bc
        cmp     ax, [vn]
        jne     .bc
        mov     si, vbuf
        mov     di, vbuf2
        mov     cx, ax
        repe    cmpsb
        jne     .bc
        jmp     .l
.cm:    push    ds                      ; memory's piece
        mov     si, vbuf
        les     di, [voff]
        mov     cx, [vn]
        repe    cmpsb
        push    ds
        pop     es
        pop     ds
        jne     .bc
        mov     ax, [vn]                ; (on: 2 KB, 128 paragraphs)
        add     [voff], ax
        cmp     word [voff], 8000h
        jb      .l
        sub     word [voff], 8000h
        add     word [vseg], 800h
        jmp     .l
.eof:   mov     di, [rec]               ; as long as the source?
        mov     ax, 4202h
        mov     bx, [vh1]
        xor     cx, cx
        xor     dx, dx
        int     21h
        cmp     ax, [di+Q_SIZE]
        jne     .bc
        cmp     dx, [di+Q_SIZE+2]
        jne     .bc
        call    .close
        clc
        ret
.bc:    call    .close
.bad:   stc
        ret
.close: mov     bx, [vh1]
        mov     ah, 3Eh
        int     21h
        mov     bx, [vh2]
        cmp     bx, 0FFFFh
        je      .cx
        mov     ah, 3Eh
        int     21h
.cx:    ret

; ---------------------------------------------------------------------
; ddir made, each level that isn't there (/E's empty ones).  mkdirs_o: opath
mkdirs: mov     si, ddir
        mov     di, opath
        call    strcpy
mkdirs_o:
        mov     si, opath + 3           ; past "D:\"
.l:     lodsb
        or      al, al
        jz      .ok
        cmp     al, '\'
        jne     .l
        mov     byte [si-1], 0          ; this level
        push    si
        mov     dx, opath
        mov     ah, 39h
        int     21h
        jnc     .n
        mov     ax, 4300h               ; (there already: a directory?)
        int     21h
        jc      .no
        test    cl, 10h
        jz      .no
.n:     pop     si
        mov     byte [si-1], '\'
        jmp     .l
.no:    pop     si
        mov     byte [si-1], '\'
        stc
        ret
.ok:    clc
        ret

; ---------------------------------------------------------------------
; the message at DX, then the path at SI: "Insufficient disk space - B:\X"
say:    call    print
say1:   call    puts
        jmp     crlf

; the path at cpath: a directory?  CF if not (the root is)
isdir:  cmp     byte [cpath+3], 0
        je      .y
        mov     dx, cpath
        mov     ax, 4300h
        int     21h
        jc      .n
        test    cl, 10h
        jz      .n
.y:     clc
        ret
.n:     stc
        ret

; cpath (ASCIIZ) -> DI = "dir" with "\" last at DI: AX = its length
dirset: push    di
        call    strcpy
        cmp     byte [di-1], '\'
        je      .r
        mov     byte [di], '\'
        inc     di
        mov     byte [di], 0
.r:     mov     ax, di
        pop     di
        sub     ax, di
        ret

; SI (ASCIIZ) -> BX past its last "\" or ":" (its last part)
lastpart:
        mov     bx, si
.l:     lodsb
        or      al, al
        jz      .x
        cmp     al, '\'
        je      .m
        cmp     al, ':'
        jne     .l
.m:     mov     bx, si
        jmp     .l
.x:     ret
lastpart_di:
        mov     si, di
        jmp     lastpart

; SI: has a * or ?  CF if so
haswild:
        push    si
.l:     lodsb
        or      al, al
        jz      .n
        cmp     al, '*'
        je      .y
        cmp     al, '?'
        jne     .l
.y:     pop     si
        stc
        ret
.n:     pop     si
        clc
        ret

strcpy: lodsb
        stosb
        or      al, al
        jnz     strcpy
        dec     di
        ret
strend: mov     di, si                  ; SI's end -> DI
.l:     cmp     byte [di], 0
        je      .x
        inc     di
        jmp     .l
.x:     ret
streq:  lodsb                           ; SI, DI: the same?  ZF
        scasb
        jne     .x
        or      al, al
        jnz     streq
.x:     ret

%include "CANON.INC"

upcase: cmp     al, 'a'
        jb      .x
        cmp     al, 'z'
        ja      .x
        sub     al, 20h
.x:     ret
getkey: mov     ah, 08h
        int     21h
        ret
print:  mov     ah, 9
        int     21h
        ret
crlf:   mov     dx, s_crlf
        jmp     print
putc:   push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        ret
puts:   push    si
.l:     lodsb
        or      al, al
        jz      .x
        cmp     al, ' '
        jae     .p
        mov     al, '?'
.p:     call    putc
        jmp     .l
.x:     pop     si
        ret
; AX in decimal, right-aligned in CX places
pdecw:  pusha
        mov     di, numbuf + 8
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        add     dl, '0'
        dec     di
        mov     [di], dl
        or      ax, ax
        jnz     .d
        mov     ax, numbuf + 8
        sub     ax, di
.p:     cmp     ax, cx
        jae     .o
        dec     di
        mov     byte [di], ' '
        inc     ax
        jmp     .p
.o:     mov     byte [numbuf + 8], '$'
        mov     dx, di
        call    print
        popa
        ret

s_all   db '*.*', 0
s_empty db 0
s_reading db 'Reading source file(s)...', 13, 10, '$'
s_wait  db 'Press any key to begin copying file(s)$'
s_copied db ' File(s) copied', 13, 10, '$'
s_nf    db 'File not found - $'
s_yn    db ' (Y/N)? $'
s_does  db 'Does $'
s_fd    db ' specify a file name', 13, 10
        db 'or directory name on the target', 13, 10
        db '(F = file, D = directory)? $'
s_noans db 'No answer: nothing copied', 13, 10, '$'
s_self  db 'File cannot be copied onto itself - $'
s_cyclic db 'Cannot perform a cyclic copy', 13, 10, '$'
s_full  db 'Insufficient disk space - $'
s_cantrd db 'Cannot read - $'
s_cantwr db 'Cannot write - $'
s_wrerr db 'Disk error writing - $'
s_deny  db 'Access denied - $'
s_mkdir db 'Unable to create directory - $'
s_vfy   db 'Verify error - $'
s_kept  db 'Copy kept as $'
s_dash  db ' - $'
s_nomem db 'Insufficient memory', 13, 10, '$'
s_plong db 'Path too long - $'
s_badsw db 'Invalid parameter', 13, 10, '$'
s_noparm db 'Required parameter missing', 13, 10, '$'
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
sw_a    resb 1
sw_m    resb 1
prompt  resb 1
subs    resb 1
empty   resb 1
verify  resb 1
waitk   resb 1
dset    resb 1
dkind   resb 1
self    resb 1
werr    resb 1
xop     resb 1
xerr    resb 1
        alignb 2
dmon    resw 1
dday    resw 1
ddate   resw 1
bufseg  resw 1
bufparas resw 1
qn      resw 1
qcur    resw 1
rec     resw 1
depth   resw 1
nfound  resw 1
ncopied resw 1
dta     resw 1
sdl     resw 1
ddl     resw 1
ohandle resw 1
ihandle resw 1
vh1     resw 1
vh2     resw 1
vn      resw 1
voff    resw 1                          ; (les: offset, then segment)
vseg    resw 1
lseg    resw 1
lparas  resw 1
lnum    resw 1
lidx    resw 1
srcarg  resb 82
dstarg  resb 82
pat     resb 82
dname   resb 82
sdir    resb 82
ddir    resb 82
opath   resb 96
numbuf  resb 10
sfcb    resb 11
tfcb    resb 11
rfcb    resb 11
dtas    resb MAXDEPTH * DTASZ
queue   resb QMAX * QSZ
vbuf    resb VCH
vbuf2   resb VCH
CANON_BSS
        resb 1024
stack_top:
bss_end:
prog_end:
