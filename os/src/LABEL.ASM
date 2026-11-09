; LABEL.COM - a disk's volume label (DOS 3.30's LABEL) for Lodestone
;
;   LABEL [d:][label]
;
;   d:      A: or B: (a floppy) or C: (the hard disk); the current drive
;           if none is given.  M: (the temporary disk) is refused: the
;           kernel keeps its directory sectors where only its own writes
;           reach them.  R: is the ROM.
;   label   the new label, 11 characters at most (spaces too), none of
;           " * + , . / : ; < = > ? [ \ ] | ( ) & ^ (FORMAT's rule).
;           Without one: the label now and the serial number, then
;           "Volume label (11 characters, ENTER for none)?"; Enter alone
;           with a label there asks "Delete current volume label (Y/N)?".
;
; The kernel makes no labels (CREATE with the label bit is refused), so
; LABEL writes the root's label entry itself, as FORMAT and CHKDSK reach
; a disk: INT 13h for a floppy, the kernel's INT 25h/26h (DOS 4's packet
; form) for C:.  The boot sector's label (2Bh) changes with it when the
; boot sector has DOS 4's extended BPB (29h at 26h).  A floppy is
; checked before each write to be the disk that was read (its change
; line; or, when it says changed or the drive has none, its boot sector
; and the root sector as read), and INT 21h 0Dh comes before and after,
; so the kernel reads the disk again; its current directory there is
; kept.  After the writes INT 21h F008h has the kernel take the disk as
; it now is, so a file open on it (LABEL's output sent there) goes on.
; INT 26h tells the kernel for C:.  With multitasking, nothing is written
; while other tasks are there (Shift-Return with no others: alone).
;
; Exit code: 0 done (or nothing asked), 1 couldn't (no such drive, not a
; FAT disk, a disk error, write-protected, the disk changed, the root
; full ...), 3 Esc or Ctrl-C at a question.  Needs Lodestone.
cpu 286
org 100h

TRIES   equ 3
K_FL    equ 0
K_HD    equ 1

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     dx, ctrlc
        mov     ax, 2523h
        int     21h
        mov     dx, crit
        mov     ax, 2524h
        int     21h
        mov     ah, 19h                 ; the current drive, unless one is
        int     21h                     ;  given
        mov     [drv], al
        call    args
        jc      fail
        mov     al, [drv]
        add     al, 'A'
        mov     [s_d1], al
        mov     [s_d2], al
        mov     [s_d3], al
        mov     [curdir], al
        mov     word [curdir+1], '\' << 8 | ':'
        mov     ax, 0F000h              ; Lodestone?
        int     21h
        cmp     ax, 4F47h
        mov     dx, s_notlode
        jne     fail
        call    which
        jc      fail
        cmp     byte [given], 0         ; a label given: is it a good one?
        je      .rd
        mov     si, label
        call    chk_label
        mov     dx, s_badlab
        jc      fail
.rd:    mov     ax, 0D00h               ; the kernel's changes on the disk
        int     21h
        mov     dl, [drv]               ; its current directory ("A:\SUB"),
        inc     dx                      ;  to be kept: once the kernel has
        push    dx                      ;  looked at the disk again (36h),
        mov     ah, 36h                 ;  so a disk swapped in before isn't
        int     21h                     ;  given the old one's
        pop     dx
        mov     si, curdir + 3
        mov     ah, 47h
        int     21h
        call    buf_set
        call    rd_boot
        jc      fail
        call    find                    ; the label's entry, or room for one
        jc      fail
        cmp     byte [given], 0
        jne     .set
        call    show                    ; "Volume in drive A is ..."
        call    alone                   ; (said before the questions, not
        jc      fail                    ;  after them)
        call    ask                     ; -> [label], or CF: nothing to do
        jc      done
        cmp     byte [label], 0
        jne     .set
        cmp     byte [hadlab], 0        ; Enter, a label there: delete it?
        je      done
        mov     dx, s_del
        call    yesno
        jne     done
.set:   call    alone                   ; (nothing written beside other
        jc      fail                    ;  tasks)
        call    fresh                   ; the root as it is now
        jc      fail
        cmp     byte [label], 0         ; (nothing to delete now: done)
        jne     .w
        cmp     byte [hadlab], 0
        je      done
.w:     call    write
        jc      fail
        call    told
done:   mov     ax, 4C00h
        int     21h

fail:   push    dx                      ; (told first: the message may go to
        call    told                    ;  a file on the disk written)
        pop     dx
        call    print
        mov     ax, 4C01h
        int     21h
stop:   mov     dx, s_crlf
        call    print
        mov     ax, 4C03h
        int     21h
ctrlc:  push    cs
        pop     ds
        call    told
        mov     ax, 4C03h
        int     21h
crit:   mov     al, 3                   ; (DOS's own I/O: fail it)
        iret

; ---------------------------------------------------------------------
; command tail: [d:][label].  CF: DX = message
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
        call    skipsp
        cmp     byte [si], 13           ; (nothing: past the tail's end is
        je      .lab                    ;  an earlier tail's leftovers)
        cmp     byte [si+1], ':'
        jne     .lab
        mov     al, [si]
        and     al, 0DFh
        sub     al, 'A'
        cmp     al, 25
        ja      .bad
        mov     [drv], al
        add     si, 2
        call    skipsp
.lab:   mov     di, kbuf                ; the rest of the line, its spaces
        mov     cx, 80                  ;  at the end cut, then 11 at most
.c:     lodsb
        cmp     al, 13
        je      .e
        stosb
        loop    .c
.e:     mov     byte [di], 0
.t:     cmp     di, kbuf
        je      .x
        cmp     byte [di-1], ' '
        jne     .g
        dec     di
        mov     byte [di], 0
        jmp     .t
.g:     mov     cx, di
        sub     cx, kbuf
        mov     dx, s_badlab            ; (more than 11)
        cmp     cx, 11
        ja      .bl
        mov     si, kbuf
        mov     di, label
        inc     cx
        rep     movsb
        mov     byte [given], 1
.x:     clc
        ret
.bad:   mov     dx, s_baddrv
.bl:    stc
        ret
skipsp: cmp     byte [si], ' '
        je      .n
        cmp     byte [si], 9
        jne     .x
.n:     inc     si
        jmp     skipsp
.x:     ret

; the drive [drv] -> [kind], [unit].  CF: DX = message
which:  mov     al, [drv]
        cmp     al, 1
        ja      .c
        mov     [unit], al              ; A: or B:: a BIOS unit there?
        mov     byte [kind], K_FL
        int     11h
        xor     cl, cl
        test    al, 1
        jz      .n
        mov     cl, al
        shr     cl, 6
        inc     cl
.n:     cmp     [unit], cl
        jae     .inv
        clc
        ret
.c:     cmp     al, 2
        jne     .m
        mov     byte [kind], K_HD
        mov     ax, 4408h               ; C: there?  (CF: no such drive)
        mov     bl, 3
        int     21h
        jc      .inv
        clc
        ret
.m:     mov     dx, s_mdisk
        cmp     al, 12
        je      .x
        mov     dx, s_rom
        cmp     al, 17
        je      .x
.inv:   mov     dx, s_baddrv
.x:     stc
        ret

; with multitasking, alone?  CF: DX = message
alone:  mov     ax, 0F012h              ; (CF: multitasking is off)
        xor     cx, cx
        int     21h
        jc      .y
        cmp     cx, 1
        jbe     .y
        mov     dx, s_tasks
        stc
        ret
.y:     clc
        ret

; a sector buffer that doesn't cross a 64 KB DMA boundary
buf_set:
        mov     ax, cs
        shl     ax, 4
        add     ax, sb1
        mov     word [sec], sb1
        cmp     ax, 10000h - 512
        jbe     .x
        mov     word [sec], sb2
.x:     ret

; ---------------------------------------------------------------------
; the boot sector -> boot (a copy), the layout.  CF: DX
rd_boot:
        mov     word [spt], 9           ; (sector 1 of any floppy)
        mov     word [heads], 2
        xor     ax, ax
        xor     dx, dx
        call    rdsec
        mov     dx, s_rderr
        jc      .x
        mov     si, [sec]
        mov     di, boot
        mov     cx, 256
        rep     movsw
        mov     dx, s_nondos
        cmp     word [boot+0Bh], 512
        jne     .bad
        cmp     byte [boot+0Dh], 0
        je      .bad
        mov     ax, [boot+0Eh]          ; reserved, FATs, sectors a FAT
        or      ax, ax
        jz      .bad
        mov     cl, [boot+10h]
        or      cl, cl
        jz      .bad
        cmp     cl, 2
        ja      .bad
        mov     bx, [boot+16h]
        or      bx, bx
        jz      .bad
        cmp     cl, 1
        je      .one
        shl     bx, 1
.one:   add     ax, bx
        mov     [rootlba], ax
        mov     ax, [boot+11h]          ; root entries: its sectors
        or      ax, ax
        jz      .bad
        cmp     ax, 4096
        ja      .bad
        add     ax, 15
        shr     ax, 4
        mov     [rsecs], ax
        cmp     byte [kind], K_FL
        jne     .ok
        mov     ax, [boot+18h]          ; a floppy's own geometry
        or      ax, ax
        jz      .bad
        cmp     ax, 63
        ja      .bad
        mov     [spt], ax
        mov     ax, [boot+1Ah]
        or      ax, ax
        jz      .bad
        cmp     ax, 2
        ja      .bad
        mov     [heads], ax
.ok:    clc
.x:     ret
.bad:   stc
        ret

; the root: its label entry ([hadlab], [esec]/[eoff]: where), or the
; first free one ([esec]/[eoff]: where a new one goes; [nofree] if none)
; -> label to show in curlab.  CF: DX
find:   mov     byte [nofree], 1
        xor     bp, bp                  ; BP = the root's sector
.s:     cmp     bp, [rsecs]
        jae     .x
        mov     ax, [rootlba]
        add     ax, bp
        xor     dx, dx
        call    rdsec
        mov     dx, s_rderr
        jc      .err
        mov     si, [sec]
        xor     bx, bx                  ; BX = the entry's offset
.e:     mov     al, [si+bx]
        or      al, al                  ; the end: a free place
        jz      .end
        cmp     al, 0E5h
        je      .free
        mov     ah, [si+bx+11]
        cmp     ah, 0Fh                 ; (a long name's piece)
        je      .n
        test    ah, 8
        jz      .n
        mov     byte [hadlab], 1        ; the label
        mov     [esec], bp
        mov     [eoff], bx
        call    .copy
        push    si
        add     si, bx
        mov     di, curlab
        mov     cx, 11
        rep     movsb
.tr:    mov     byte [di], 0            ; (its spaces at the end not shown)
        cmp     di, curlab
        je      .td
        cmp     byte [di-1], ' '
        jne     .td
        dec     di
        jmp     .tr
.td:    pop     si
        jmp     short .x
.free:  call    .keep
.n:     add     bx, 32
        cmp     bx, 512
        jb      .e
        inc     bp
        jmp     .s
.end:   call    .keep
.x:     clc
.err:   ret
.keep:  cmp     byte [nofree], 0        ; (the first free place)
        je      .k
        mov     byte [nofree], 0
        mov     [esec], bp
        mov     [eoff], bx
.copy:  push    si                      ; (its sector as read now, before
        push    di                      ;  any question: the one written
        push    cx                      ;  is made from it, and the disk
        mov     di, rootcp              ;  must still have it then)
        mov     cx, 256
        rep     movsw
        pop     cx
        pop     di
        pop     si
.k:     ret

; " Volume in drive A is LODESTONE" / "has no label", the serial number
show:   mov     dx, s_vol
        call    print
        cmp     byte [hadlab], 0
        jne     .l
        mov     dx, s_nolab
        call    print
        jmp     short .s
.l:     mov     dx, s_is
        call    print
        mov     si, curlab
        call    pstrz
        mov     dx, s_crlf
        call    print
.s:     cmp     byte [boot+26h], 29h
        jne     .x
        mov     dx, s_ser
        call    print
        mov     ax, [boot+29h]
        call    phex
        mov     al, '-'
        call    putc
        mov     ax, [boot+27h]
        call    phex
        mov     dx, s_crlf
        call    print
.x:     ret

; "Volume label (11 characters, ENTER for none)? " -> [label] (0: none);
; again while it isn't one.  CF: nothing to do (Enter alone, no label
; there: nothing changes)
ask:    mov     dx, s_ask
        call    print
        mov     byte [kbuf], 12
        mov     dx, kbuf
        mov     ah, 0Ah
        int     21h
        mov     dx, s_crlf
        call    print
        mov     cl, [kbuf+1]
        xor     ch, ch
        mov     si, kbuf+2
        mov     di, label
        rep     movsb
        mov     byte [di], 0
        mov     si, label
        call    chk_label
        jnc     .ok
        mov     dx, s_badlab
        call    print
        jmp     ask
.ok:    cmp     byte [label], 0
        jne     .y
        cmp     byte [hadlab], 0
        jne     .y
        stc
        ret
.y:     clc
        ret

; DX's question, Y or N and Enter (Backspace takes it back) -> ZF: Y.
; Esc, Ctrl-C, the end of a file: stop (3)
yesno:  push    dx
        call    flush_keys              ; (DX: its IOCTL's)
        pop     dx
        call    print
        xor     bl, bl
.k:     mov     ah, 08h
        int     21h
        or      al, al                  ; (an extended key: its scan code
        jnz     .c                      ;  next, no key of its own)
        mov     ah, 08h
        int     21h
        jmp     .k
.c:     cmp     al, 27
        je      .esc
        cmp     al, 3
        je      .esc
        cmp     al, 1Ah
        je      .esc
        cmp     al, 13
        je      .cr
        cmp     al, 8
        je      .bs
        or      bl, bl
        jnz     .k
        mov     ah, al
        and     ah, 0DFh
        cmp     ah, 'Y'
        je      .a
        cmp     ah, 'N'
        jne     .k
.a:     mov     bl, ah
        call    putc
        jmp     .k
.bs:    or      bl, bl
        jz      .k
        xor     bl, bl
        mov     dx, s_bs
        call    print
        jmp     .k
.cr:    or      bl, bl
        jz      .k
        mov     dx, s_crlf
        call    print
        cmp     bl, 'Y'
        ret
.esc:   jmp     stop

; ---------------------------------------------------------------------
; the label ([label], 0: none, delete) into the root and the boot sector.
; CF: DX
write:  cmp     byte [hadlab], 0        ; a new entry: room for it?
        jne     .r
        cmp     byte [nofree], 0
        mov     dx, s_full
        jne     .no
.r:     mov     si, rootcp              ; its sector as read (not again: the
        mov     di, [sec]               ;  disk may have been changed since)
        mov     cx, 256
        rep     movsw
        mov     di, [sec]
        add     di, [eoff]
        cmp     byte [label], 0
        jne     .put
        mov     byte [di], 0E5h         ; none: the entry deleted
        jmp     short .w
.put:   push    di
        mov     cx, 16                  ; the label's entry
        xor     ax, ax
        rep     stosw
        pop     di
        mov     si, label
        call    pad11
        sub     di, 11
        mov     byte [di+11], 08h
        call    stamp
.w:     mov     ax, [rootlba]
        add     ax, [esec]
        xor     dx, dx
        mov     byte [chkroot], 1
        call    wrsec
        mov     byte [chkroot], 0
        jc      .werr
        cmp     byte [boot+26h], 29h    ; DOS 4's BPB: its label too
        jne     .ok
        mov     si, boot
        mov     di, [sec]
        mov     cx, 256
        rep     movsw
        mov     di, [sec]
        add     di, 2Bh
        mov     si, s_noname
        cmp     byte [label], 0
        je      .bl
        mov     si, label
.bl:    call    pad11
        xor     ax, ax
        xor     dx, dx
        call    wrsec
        jc      .werr
.ok:    clc
        ret
.werr:  mov     dx, s_dchg
        cmp     byte [dchg], 0
        jne     .no
        mov     dx, s_wprot
        cmp     byte [bstat], 3
        je      .no
        mov     dx, s_wrerr
.no:    stc
        ret

; after a question: the root read again, so what was written to it while
; LABEL waited (a capture's file, a task's) isn't written over with the
; sector as it was.  A floppy whose change line says it may have been
; changed (or that has none) keeps the sector read before, and the write
; checks the disk still has it (same).  CF: DX
fresh:  mov     ax, 0D00h               ; (the kernel's changes meanwhile)
        int     21h
        cmp     byte [kind], K_FL
        jne     .re
        mov     ah, 16h
        mov     dl, [unit]
        int     13h
        jnc     .re
        mov     byte [seen], 1          ; (the line read is the line cleared:
        clc                             ;  same must not trust it now)
        ret
.re:    mov     byte [hadlab], 0
        call    find
        ret

; the entry at DI: its time and date now
stamp:  push    di
        mov     ah, 2Ch
        int     21h
        pop     di
        mov     al, cl                  ; hh:mm:ss -> hhhhhmmmmmmsssss
        xor     ah, ah
        shl     ax, 5
        mov     bl, dh
        shr     bl, 1
        xor     bh, bh
        or      ax, bx
        mov     bl, ch
        shl     bx, 11
        or      ax, bx
        mov     [di+16h], ax
        push    di
        mov     ah, 2Ah
        int     21h
        pop     di
        sub     cx, 1980                ; yyyyyyymmmmddddd
        shl     cx, 9
        mov     al, dh
        xor     ah, ah
        shl     ax, 5
        or      ax, cx
        or      al, dl
        mov     [di+18h], ax
        ret

; after writes: a floppy taken by the kernel as it is now (INT 21h F008h:
; its BPB's label and its root's first sector are what it knows the disk
; by, and a file of the kernel's may be open on it, LABEL's output sent
; there), then read again (INT 21h 0Dh), and its current directory there
; as it was
told:   cmp     byte [wrote], 0
        je      .x
        mov     byte [wrote], 0
        cmp     byte [kind], K_FL
        jne     .x
        mov     ax, 0F008h              ; (before 0Dh: its flush looks at
        mov     dl, [drv]               ;  the disk)
        int     21h
        mov     ah, 0Dh
        int     21h
        mov     dx, curdir
        mov     ah, 3Bh
        int     21h
.x:     ret

; ---------------------------------------------------------------------
;  a sector: DX:AX, at [sec].  CF: an error
; ---------------------------------------------------------------------
rdsec:  mov     byte [xop], 2
        jmp     short xsec
wrsec:  call    same                    ; (a floppy still the disk read?)
        jc      .x
        mov     byte [wrote], 1
        mov     byte [xop], 3
        jmp     short xsec
.x:     ret
xsec:   pusha
        push    es
        cmp     byte [kind], K_HD
        je      .hd
        call    fl_io
        jmp     short .x
.hd:    call    hd_io
.x:     pop     es
        popa
        ret

; a floppy's sector AX through INT 13h, TRIES times (a reset between); a
; write that finds the disk changed or write-protected isn't tried again.
; CF: [bstat]
fl_io:  xor     dx, dx
        div     word [spt]
        mov     cl, dl
        inc     cl                      ; CL = the sector
        xor     dx, dx
        div     word [heads]
        mov     ch, al                  ; CH = the cylinder, DH = the head
        mov     dh, dl
        mov     dl, [unit]
        mov     bp, TRIES
.t:     push    cs
        pop     es
        mov     bx, [sec]
        mov     al, 1
        mov     ah, [xop]
        push    dx
        push    cx
        int     13h
        pop     cx
        pop     dx
        jnc     .ok
        mov     [bstat], ah
        cmp     byte [xop], 3
        jne     .rs
        cmp     ah, 03h
        je      .err
        cmp     ah, 06h
        je      .err
.rs:    push    dx
        xor     ah, ah
        int     13h
        pop     dx
        dec     bp
        jnz     .t
.err:   stc
        ret
.ok:    clc
        ret

; C:: the kernel's INT 25h/26h (DX:AX the partition's sector)
hd_io:  mov     [pk_lba], ax
        mov     [pk_lba+2], dx
        mov     word [pk_n], 1
        mov     ax, [sec]
        mov     [pk_buf], ax
        mov     [pk_buf+2], cs
        mov     al, 2
        mov     cx, 0FFFFh
        mov     bx, pk_lba
        cmp     byte [xop], 3
        je      .w
        int     25h
        jmp     short .d
.w:     int     26h
.d:     inc     sp                      ; (the flags left; INC keeps CF)
        inc     sp
        ret

; before a write to a floppy: the disk that was read?  Its change line;
; when that says changed (or the drive has none) the boot sector as read
; (or as last written), and the root sector about to be written as read
; ([chkroot]).  CF if not: [dchg].  All kept
same:   cmp     byte [kind], K_FL
        jne     .ok
        pusha
        push    es
        cmp     byte [seen], 0          ; (a change fresh saw: compare)
        jne     .cmp
        mov     ah, 16h
        mov     dl, [unit]
        int     13h
        jnc     .y
.cmp:
        mov     si, [sec]               ; (sec holds what is to be written:
        mov     di, wsave               ;  kept meanwhile)
        mov     cx, 256
        push    cs
        pop     es
        rep     movsw
        mov     byte [xop], 2
        xor     ax, ax
        call    fl_io
        jc      .chg
        mov     si, [sec]
        mov     di, boot
        mov     cx, 256
        push    cs
        pop     es
        repe    cmpsw
        jne     .chg
        cmp     byte [chkroot], 0
        je      .y0
        mov     ax, [rootlba]
        add     ax, [esec]
        call    fl_io
        jc      .chg
        mov     si, [sec]
        mov     di, rootcp
        mov     cx, 256
        push    cs
        pop     es
        repe    cmpsw
        jne     .chg
.y0:    call    .back
.y:     pop     es
        popa
.ok:    clc
        ret
.chg:   call    .back
        mov     byte [dchg], 1
        pop     es
        popa
        stc
        ret
.back:  mov     si, wsave               ; what is to be written, back
        mov     di, [sec]
        mov     cx, 256
        push    cs
        pop     es
        rep     movsw
        ret

; ---------------------------------------------------------------------
; the label at SI (ASCIIZ): upper case, characters a label may have, 11
; at most.  CF if not.  All spaces is none ([si] = 0)
chk_label:
        push    si
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .e
        inc     cx
        cmp     cx, 11
        ja      .bad
        cmp     al, 'a'
        jb      .u
        cmp     al, 'z'
        ja      .u
        sub     al, 20h
        mov     [si-1], al
.u:     cmp     al, ' '
        jb      .bad
        cmp     al, 80h
        jae     .l
        mov     di, badch
        push    cx
        mov     cx, badch_n
        push    es
        push    cs
        pop     es
        repne   scasb
        pop     es
        pop     cx
        je      .bad
        jmp     .l
.e:     pop     si
        push    si
.sp:    lodsb
        or      al, al
        jz      .none
        cmp     al, ' '
        je      .sp
        pop     si
        clc
        ret
.none:  pop     si
        mov     byte [si], 0
        clc
        ret
.bad:   pop     si
        stc
        ret

; ASCIIZ at SI -> 11 characters at DI, spaces after
pad11:  mov     cx, 11
.l:     lodsb
        or      al, al
        jz      .s
        stosb
        loop    .l
        ret
.s:     mov     al, ' '
        rep     stosb
        ret

; stdin the keyboard: drop keys typed before a question
flush_keys:
        mov     ax, 4400h
        xor     bx, bx
        int     21h
        jc      .x
        and     dl, 81h
        cmp     dl, 81h
        jne     .x
.l:     mov     ah, 1
        int     16h
        jz      .x
        xor     ah, ah
        int     16h
        jmp     .l
.x:     ret

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
pstrz:  lodsb                           ; (a label may hold a $)
        or      al, al
        jz      .x
        call    putc
        jmp     pstrz
.x:     ret
phex:   mov     cx, 4
.l:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     call    putc
        pop     ax
        loop    .l
        ret

; ---------------------------------------------------------------------
badch   db '"*+,./:;<=>?[\]|()&^'
badch_n equ $ - badch
s_noname db 'NO NAME', 0
s_vol   db ' Volume in drive '
s_d1    db 'A $'
s_is    db 'is $'
s_nolab db 'has no label', 13, 10, '$'
s_ser   db ' Volume Serial Number is $'
s_ask   db 13, 10, 'Volume label (11 characters, ENTER for none)? $'
s_del   db 13, 10, 'Delete current volume label (Y/N)? $'
s_badlab db 'Invalid characters in volume label', 13, 10, '$'
s_baddrv db 'Invalid drive specification', 13, 10, '$'
s_mdisk db 'LABEL: M: is the temporary disk; its label stays as it was made', 13, 10, '$'
s_rom   db 'LABEL: R: is the ROM, made whole', 13, 10, '$'
s_notlode db 'LABEL: needs Lodestone (other DOSes have their own LABEL)', 13, 10, '$'
s_tasks db 'LABEL: other tasks are running, or LABEL runs as one (Shift-Return', 13, 10
        db 'with no other tasks: alone)', 13, 10, '$'
s_rderr db 'Cannot read drive '
s_d2    db 'A:', 13, 10, '$'
s_nondos db 'Probable non-DOS disk in drive '
s_d3    db 'A:', 13, 10, '$'
s_full  db 'The root directory is full: no room for a label', 13, 10, '$'
s_wprot db 'Write protect error: the label as it was', 13, 10, '$'
s_wrerr db 'Disk error writing the label', 13, 10, '$'
s_dchg  db 'The disk was changed: the label not written', 13, 10, '$'
s_bs    db 8, ' ', 8, '$'
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
drv     resb 1
unit    resb 1
kind    resb 1
given   resb 1
hadlab  resb 1
nofree  resb 1
xop     resb 1
bstat   resb 1
dchg    resb 1
wrote   resb 1
chkroot resb 1
        alignb 2
sec     resw 1                          ; -> the sector buffer
spt     resw 1
heads   resw 1
rootlba resw 1
rsecs   resw 1
esec    resw 1
eoff    resw 1
pk_lba  resw 2
pk_n    resw 1
pk_buf  resw 2
label   resb 14
curlab  resb 12
curdir     resb 68
kbuf    resb 84
seen    resb 1
        alignb 2
boot    resb 512
rootcp  resb 512
wsave   resb 512
        alignb 16
sb1     resb 512
sb2     resb 512
        resb 512
stack_top:
bss_end:
