; DISKCOPY.COM - copies a floppy track for track (DOS 3.30's DISKCOPY), and,
; built with COMP defined (DISKCOMP.ASM), DISKCOMP.COM, which compares two
;
;   DISKCOPY [d1: [d2:]] [/1] [/V]
;   DISKCOMP [d1: [d2:]] [/1]
;
;   d1: d2:  the source and the target, A: or B:.  None: the current drive
;            for both; one: it the source, the current drive the target.
;            The same drive twice: one drive, the disks swapped as asked
;   /1       side 0 only
;   /V       (DISKCOPY) each track read back after it is written
;   /8       (DISKCOMP) the first 8 sectors of each track only
;
; The source's layout comes from its boot sector's BPB: 360 KB, 720 KB,
; 1.2 MB, 1.44 MB (9, 15 or 18 sectors a track, 40 or 80 cylinders, one
; or two sides; DISKCOMP 160 and 320 KB too, 8 sectors: DISKCOPY can't set
; that layout for a format, INT 13h 18h has none); a disk without one is
; refused.  As many tracks as memory holds are read at a time (each in a
; buffer of its own that doesn't cross a 64 KB DMA boundary): a 1.44 MB
; disk takes three passes.  The source's boot sector alone is enough if
; the sector after it won't read (that one is then zeros, as on the copy).
;
; With one drive, each prompt makes sure the right disk is in, by its
; first two sectors (the boot sector and the FAT's first): "That isn't
; the SOURCE diskette" (or TARGET, or "Drive not ready") and the prompt
; again.  DISKCOPY's target keeps a boot sector unlike the source's (its
; first OEM byte inverted) until the last pass is written, then gets the
; real one, so even disks without serial numbers are told apart; at the
; first TARGET prompt a disk with the source's first two sectors (the
; source left in, or an earlier copy without a serial number) is asked
; about ("Write on it all the same (Y/N)?").  DISKCOMP's two disks are
; told apart only if their first two sectors differ (a serial number
; does): a copy without one can't be told from the source.  A disk
; changed in the middle of a pass (INT 13h's 06h), or at the
; write-protected prompt, is checked the same way before anything more is
; read or written.  An extended key (two bytes from DOS) is one key.
;
; DISKCOPY: the target's first track is verified at the source's layout
; (INT 13h 18h sets it; INT 1Eh points at the BIOS's table for it, and is
; put back on every way out); if it doesn't read, every track is
; formatted as it is written ("Formatting while copying"), and a track
; that won't take a write is formatted and written again (track 0 that
; won't: the copy ended).  A copy ended once something is written says
; "Target diskette may be unusable".  A source with
; DOS 4's serial number (a 29h BPB) gives the copy a new one, as MS-DOS 4
; does: the kernel then knows the copy for another disk; and the target
; drive's current directory goes to its root, for a source without one.
; A sector of the source that won't read is said (side, track) and
; written as zeros; the copy goes on.  A write-protected target: put
; right, and a key.  INT 21h 0Dh before (the kernel's changes on the
; disk) and after (it reads the target again).  Files open on the target
; drive refuse it.
;
; DISKCOMP: "Compare error on side h, track t" for each track that
; differs, "Compare OK" if none; DOS 4's serial numbers are not compared
; (a DISKCOPY's copy compares OK).
;
; Esc or Ctrl-C stops either.  With multitasking it must be the only task
; (Shift-Return, no others): the BIOS's diskette table is everyone's.
; Exit codes, MS-DOS's: DISKCOPY 0 copied, 1 a read or write error, 2
; stopped, 3 it couldn't (no disk, not ready, a layout the drive can't
; take), 4 wrong at the start (switches, drives, memory, not Lodestone);
; DISKCOMP 0 the same, 1 they differ, 2 stopped, 3 a read error, 4 the
; same as DISKCOPY's.  (Read and write errors name the drive they were
; on.)
cpu 286
org 100h

TRIES   equ 3
MAXSPT  equ 18
MAXTRK  equ 160                         ; 80 cylinders, 2 sides

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     bx, prog_end + 15
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     dx, ctrlc
        mov     ax, 2523h
        int     21h
        mov     dx, crit
        mov     ax, 2524h
        int     21h
        mov     byte [src], 0FFh
        mov     byte [dst], 0FFh
        call    args
        jc      init_fail
        xor     dx, dx                  ; (DL 0, as XCOPY's: NetWare's F0h)
        mov     ax, 0F000h              ; Lodestone?
        int     21h
        cmp     ax, 4F47h
        mov     dx, s_notlode
        jne     init_fail
        mov     ax, 0F012h              ; the only task?  (CF: multitasking
        xor     cx, cx                  ;  is off)
        int     21h
        jc      .one
        cmp     cx, 1
        mov     dx, s_tasks
        ja      init_fail
.one:   mov     ah, 19h                 ; the drives: none given, the
        int     21h                     ;  current one twice; one, it to
        cmp     byte [src], 0FFh        ;  the current one
        jne     .s
        mov     [src], al
.s:     cmp     byte [dst], 0FFh
        jne     .d
        mov     [dst], al
.d:     int     11h                     ; floppies there
        xor     cl, cl
        test    al, 1
        jz      .n
        mov     cl, al
        shr     cl, 6
        inc     cl
.n:     mov     dx, s_baddrv
        mov     al, [src]
        cmp     al, cl
        jae     init_fail
        mov     al, [dst]
        cmp     al, cl
        jae     init_fail
        mov     al, [src]
        cmp     al, [dst]
        jne     .two
        mov     byte [single], 1
.two:   mov     al, [src]
        add     al, 'A'
        mov     [s_sd], al
        mov     [s_es], al
        mov     al, [dst]
        add     al, 'A'
        mov     [s_td], al
        mov     [s_ot], al
%ifndef COMP
        mov     [s_et], al
        mov     [s_cd], al
%endif
        mov     ah, 48h                 ; memory: all of it
        mov     bx, 0FFFFh
        int     21h
        mov     ah, 48h
        int     21h
        mov     dx, s_nomem
        jc      init_fail
        mov     [mseg], ax
        mov     [mparas], bx
        mov     ax, cs                  ; a track's buffer that doesn't
        shl     ax, 4                   ;  cross a 64 KB DMA boundary
        add     ax, tb1
        mov     word [tbuf], tb1
        cmp     ax, 10000h - MAXSPT * 512
        jbe     another
        mov     word [tbuf], tb2

; ---------------------------------------------------------------------
another:
        mov     byte [result], 0
        call    one_disk
.after: call    dpt_back
%ifdef COMP
        mov     dx, s_again
%else
        call    told
        mov     dx, s_again
%endif
        call    yesno
        je      another
        mov     al, [result]
        mov     ah, 4Ch
        int     21h

init_fail:
        call    print
        mov     ax, 4C04h
        int     21h

; Esc, Ctrl-C: the BIOS's table back, the kernel told, exit code 2
stopped:
        mov     dx, s_crlf
        call    print
stop1:
%ifndef COMP
        call    unus
%endif
        mov     dx, s_ended
        call    print
        call    dpt_back
%ifndef COMP
        call    told
%endif
        mov     ax, 4C02h
        int     21h
ctrlc:  push    cs
        pop     ds
        jmp     stop1
crit:   mov     al, 83h                 ; (Fail, nobody asked: the kernel
        iret                            ;  drops nothing, its rule 4)

; DX ($) said, then a key: Y (ZF), or another (NZ; Ctrl-C stops)
yesno:  call    print
        call    flush_keys
        call    getkey
        push    ax
        cmp     al, ' '
        jb      .nb
        call    putc
.nb:    mov     dx, s_crlf
        call    print
        pop     ax
        cmp     al, 3
        je      stopped
        and     al, 0DFh
        cmp     al, 'Y'
        ret

%ifndef COMP
; something written, the copy not whole: "Target diskette may be unusable"
unus:   cmp     byte [wrote], 0
        je      .x
        mov     dx, s_unus
        call    print
.x:     ret

; the copy written (or some of it): the kernel reads the target again
; (INT 21h 0Dh), and its current directory there is the root
told:   cmp     byte [wrote], 0
        je      .x
        mov     byte [wrote], 0
        mov     ah, 0Dh
        int     21h
        mov     al, [dst]
        add     al, 'A'
        mov     ah, ':'
        mov     [path], ax
        mov     word [path+2], '\'
        mov     dx, path
        mov     ah, 3Bh
        int     21h
.x:     ret
%endif

; ---------------------------------------------------------------------
; one disk copied (compared).  [result] as the exit code
one_disk:
        mov     ah, 0Dh                 ; the kernel's changes on the disk
        int     21h
        mov     byte [firstw], 1
        mov     byte [fmtmode], 0
        mov     byte [t0done], 0
        mov     byte [force], 0
        mov     word [trk], 0
        mov     dx, s_insrc             ; the disks in
        call    print
        cmp     byte [single], 0
        jne     .p
        mov     dx, s_instg
        call    print
.p:     call    press
        call    rd_boot                 ; the source's boot sector, its layout
        jc      fatal
        mov     si, [tbuf]
        mov     di, bootsrc
        mov     cx, 512
        rep     movsw
        call    layout
        jc      fatal
        mov     al, [dst]
        call    drive_takes
        jc      fatal
        mov     dx, s_crlf
%ifdef COMP
        call    print
        mov     dx, s_cmping
%else
        call    print
        mov     dx, s_copying
%endif
        call    print
        mov     ax, [cyls]
        call    pnum
        mov     dx, s_tracks
        call    print
        mov     ax, [spt]
        call    pnum
        mov     dx, s_spt
        call    print
        mov     ax, [hc]
        call    pnum
        mov     dx, s_sides
        call    print
        call    slots
        jc      init_fail               ; (not enough memory: exit code 4)
%ifndef COMP
        mov     si, bootsrc             ; what the copy's boot sector is to
        mov     di, bootdst             ;  be: a new serial number, if the
        mov     cx, 512                 ;  source has one (and its next
        rep     movsw                   ;  sector the source's)
        mov     byte [newser], 0
        cmp     byte [bootsrc+26h], 29h
        jne     .mk
        call    serial
        mov     [bootdst+27h], ax
        mov     [bootdst+29h], dx
        mov     byte [newser], 1
.mk:    mov     si, bootdst             ; and its boot sector until the last
        mov     di, bootmk              ;  pass is written: unlike the
        mov     cx, 512                 ;  source's
        rep     movsw
        not     byte [bootmk+3]
%endif
        ; ---- a pass: as many tracks as there are buffers
.pass:  mov     ax, [ntr]
        sub     ax, [trk]
        jbe     .done
        cmp     ax, [nslot]
        jbe     .n
        mov     ax, [nslot]
.n:     mov     [npass], ax
        cmp     word [trk], 0           ; one drive, a pass after the first:
        je      .rd                     ;  the source in again
        cmp     byte [single], 0
        je      .rd
        call    src_in
.rd:    mov     byte [phase], 0
        xor     bx, bx                  ; read them
.r:     cmp     bx, [npass]
        jae     .rdd
        push    bx
        call    esc_key
        jc      .esc
        mov     ax, [trk]
        add     ax, bx
        call    trk_ch
        shl     bx, 1
        mov     es, [slotseg+bx]
        mov     dl, [src]
        call    rd_track                ; (unreadable sectors said, zeros)
        push    cs
        pop     es
        pop     bx
        cmp     al, 2
        je      fatal
        inc     bx
        jmp     .r
.esc:   pop     bx
        jmp     stopped
.rdd:   mov     byte [phase], 1
        cmp     byte [single], 0        ; one drive: the target in
        je      .wr
        call    tg_in
.wr:
%ifdef COMP
        cmp     byte [firstw], 0        ; the first time: the target's
        je      .c                      ;  layout must be the source's
        call    rd_tboot
        jc      fatal
        mov     si, [tbuf]
        mov     di, boottg
        mov     cx, 512
        rep     movsw
        mov     si, bootsrc + 0Bh
        mov     di, boottg + 0Bh
        mov     cx, 13h                 ; (bytes, sectors .. heads)
        repe    cmpsb
        je      .c
        mov     dx, s_ntype
        call    print
        mov     byte [result], 1
        ret
.c:     mov     byte [firstw], 0
        xor     bx, bx                  ; compare them
.cl:    cmp     bx, [npass]
        jae     .next
        push    bx
        call    esc_key
        jc      .esc
        mov     [cslot], bx
        mov     ax, [trk]
        add     ax, bx
        mov     [ctrk], ax
        call    trk_ch
        push    ds
        pop     es
        call    comp_track
        pop     bx
        cmp     al, 2
        je      fatal
        inc     bx
        jmp     .cl
%else
        cmp     byte [firstw], 0        ; the first time: no files open on
        je      .w                      ;  it, write-protected?  formatted?
        call    tg_first
        jc      fatal
.w:     mov     byte [firstw], 0
        xor     bx, bx                  ; write them
.wl:    cmp     bx, [npass]
        jae     .next
        push    bx
        call    esc_key
        jc      .esc
        mov     ax, [trk]
        add     ax, bx
        mov     [ctrk], ax
        call    trk_ch
        shl     bx, 1
        mov     es, [slotseg+bx]
        cmp     word [ctrk], 0          ; its boot sector the copy's
        jne     .wt
        mov     si, bootdst
        xor     di, di
        mov     cx, 256
        rep     movsw
        not     byte [es:3]             ; (until the last pass: unlike the
.wt:    call    wr_track                ;  source's)
        push    cs
        pop     es
        pop     bx
        cmp     al, 2
        je      fatal
        cmp     word [ctrk], 0          ; track 0 not written: the end
        jne     .wn
        or      al, al
        jnz     fatal2
        mov     byte [t0done], 1
.wn:    inc     bx
        jmp     .wl
%endif
.next:  mov     ax, [npass]
        add     [trk], ax
        jmp     .pass
.done:
%ifndef COMP
        mov     si, bootdst             ; the copy's own boot sector, now
        mov     di, [tbuf]
        mov     cx, 256
        rep     movsw
        mov     byte [cyl], 0
        mov     byte [head], 0
        mov     ax, [tbuf]
        shr     ax, 4
        mov     bx, cs
        add     ax, bx
        mov     es, ax
        push    word [spt]
        mov     word [spt], 1
        call    wr_one
        pop     word [spt]
        push    cs
        pop     es
        cmp     al, 2
        je      fatal
        or      al, al
        jnz     fatal2
%endif
        call    dpt_back
%ifdef COMP
        cmp     byte [result], 0
        jne     .x
        mov     dx, s_cmpok
        call    print
%else
        call    told
        cmp     byte [newser], 0
        je      .x
        mov     dx, s_ser
        call    print
        mov     ax, [bootdst+29h]
        call    phex
        mov     al, '-'
        call    putc
        mov     ax, [bootdst+27h]
        call    phex
        mov     dx, s_crlf
        call    print
%endif
.x:     ret

; it couldn't go on: why (DX), "Copy process ended", exit code 3 (the
; stack as it is: one_disk's caller's frame is dropped)
fatal:  call    print
fatal2:
%ifndef COMP
        call    unus
%endif
        mov     dx, s_ended
        call    print
        call    dpt_back
        mov     byte [result], 3
        mov     sp, stack_top           ; (back to another's loop: what was
        jmp     another.after           ;  on the stack is dropped)

; "Press any key when ready . . ." through DOS: Esc, Ctrl-C, a file's end
; stop it
press:  call    flush_keys
        mov     dx, s_press
        call    print
        call    getkey
        push    ax
        mov     dx, s_crlf
        call    print
        pop     ax
        cmp     al, 27
        je      .s
        cmp     al, 3
        je      .s
        cmp     al, 1Ah
        je      .s
        ret
.s:     jmp     stopped

; ---------------------------------------------------------------------
; one drive: the source in (a pass after the first), or the target (each
; pass), made sure of: "That isn't ...", "Drive not ready", and the
; prompt again
src_in: mov     dx, s_insrc
        call    print
        call    press
        call    src_ok
        jnc     tg_in.x
.no:    call    print
        jmp     src_in
tg_in:  mov     dx, s_intg
        call    print
        call    press
        call    tg_ok
        jnc     .x
.no:
%ifndef COMP
        cmp     dx, s_issrc             ; the source's first two sectors
        je      .q                      ;  (before track 0): sure?
%endif
        call    print
        jmp     tg_in
%ifndef COMP
.q:     call    yesno
        jne     tg_in
        mov     byte [force], 1
%endif
.x:     ret

; a disk changed under a pass (06h, or at the write-protected prompt):
; still the one it should be (the source read, the target written)?  If
; not, the prompt for it until it is.  ES kept
isit:   pusha
        cmp     byte [phase], 0
        jne     .t
        call    src_ok
        jnc     .x
        call    print
        call    src_in
        jmp     short .x
.t:     call    tg_ok
        jnc     .x
        call    tg_in.no
.x:     popa
        ret

; the source in?  (its first two sectors as at the start)  CF: DX = why
src_ok: call    rd_boot
        jc      .x
        mov     di, bootsrc
        call    same1k
        mov     dx, s_notsrc
        jne     no_x
.x:     ret

%ifdef COMP
; the target in?  (as at its first read; the first time, any)  CF: DX
tg_ok:  call    rd_tboot
        jc      .x
        cmp     byte [firstw], 0
        jne     .x
        mov     di, boottg
        call    same1k
        mov     dx, s_nottg
        jne     no_x
.x:     ret
%else
; the target in?  Once track 0 is written, its first two sectors as they
; were written (unlike the source's); before, any disk but one with the
; source's (DX = s_issrc, unless that was said to be all right).  CF: DX
tg_ok:  call    rd_tboot
        jnc     .rd
        cmp     dx, s_nrdy
        je      no_x
        cmp     byte [t0done], 0        ; (a blank disk: a target, until
        jne     no_x                    ;  track 0 is written)
        clc
        ret
.rd:    cmp     byte [t0done], 0
        jne     .mk
        cmp     byte [force], 0
        jne     .x
        mov     di, bootsrc
        call    same1k
        mov     dx, s_issrc
        je      no_x
        clc
.x:     ret
.mk:    mov     di, bootmk
        call    same1k
        mov     dx, s_nottg
        jne     no_x
        ret
%endif
no_x:   stc
        ret

; tbuf's first 1024 bytes and DS:DI's: ZF if the same.  ES kept
same1k: push    es
        push    cs
        pop     es
        mov     si, [tbuf]
        mov     cx, 512
        repe    cmpsw
        pop     es
        ret

; ---------------------------------------------------------------------
; the source's boot sector and the sector after it (cylinder 0, side 0,
; sectors 1-2) -> tbuf: what tells one disk from another.  The pair won't
; read: the boot sector alone, the next sector zeros (as rd_track makes
; one that won't read).  CF: DX = why.  ES kept
rd_boot:
        mov     dl, [src]
        mov     si, s_noboot
        jmp     short rd_b
rd_tboot:
        mov     dl, [dst]
        mov     si, s_tnoboot
rd_b:   mov     [unit], dl
        mov     byte [nb], 2
.n:     mov     bp, TRIES
.t:     push    es
        push    cs
        pop     es
        mov     bx, [tbuf]
        mov     al, [nb]                ; (and the next: the FAT's first
        mov     ah, 02h                 ;  sector, so two disks of a DOS
        mov     cx, 0001h               ;  without serial numbers differ)
        xor     dh, dh
        mov     dl, [unit]
        int     13h
        pop     es
        jnc     .ok
        mov     dx, s_nrdy
        cmp     ah, 80h
        je      .no
        call    reset
        dec     bp
        jnz     .t
        mov     dx, si
        dec     byte [nb]
        jnz     .n
.no:    stc
        ret
.ok:    cmp     byte [nb], 2
        je      .x
        push    es
        push    cs
        pop     es
        mov     di, [tbuf]
        add     di, 512
        mov     cx, 256
        xor     ax, ax
        rep     stosw
        pop     es
.x:     clc
        ret

; the source's BPB -> [spt], [heads], [cyls], [hc] (the sides copied),
; [ntr], [kbit] (its bit in takes).  CF: DX
layout: mov     dx, s_nolay
        cmp     word [bootsrc+510], 0AA55h
        jne     .no
        cmp     word [bootsrc+0Bh], 512
        jne     .no
        mov     ax, [bootsrc+18h]       ; sectors a track: 9, 15, 18 (and
%ifdef COMP                             ;  DISKCOMP 8)
        cmp     ax, 8
        je      .s
%endif
        cmp     ax, 9
        je      .s
        cmp     ax, 15
        je      .s
        cmp     ax, 18
        jne     .no
.s:     mov     [spt], ax
        mov     cx, [bootsrc+1Ah]       ; sides: 1 or 2
        or      cx, cx
        jz      .no
        cmp     cx, 2
        ja      .no
        mov     [heads], cx
        mul     cx
        mov     bx, ax                  ; sectors a cylinder
        mov     ax, [bootsrc+13h]
        xor     dx, dx
        div     bx
        or      dx, dx
        mov     dx, s_nolay
        jnz     .no
        cmp     ax, 40
        je      .c
        cmp     ax, 80
        jne     .no
.c:     mov     [cyls], ax
        mov     cx, [heads]             ; /1: side 0
        cmp     byte [side1], 0
        je      .h
        mov     cx, 1
.h:     mov     [hc], cx
        mul     cx
        mov     [ntr], ax
        mov     al, 1                   ; its bit: 40 cylinders 1, 720 KB 2,
        cmp     word [cyls], 40         ;  1.2 MB 4, 1.44 MB 8
        je      .k
        mov     al, 2
        cmp     word [spt], 9
        jbe     .k
        mov     al, 4
        cmp     word [spt], 15
        je      .k
        mov     al, 8
.k:     mov     [kbit], al
%ifdef COMP
        cmp     byte [eight], 0         ; /8: 8 sectors a track compared
        je      .ok
        mov     word [spt], 8
.ok:
%endif
        clc
        ret
.no:    stc
        ret

; can drive AL take the layout?  (INT 13h 08h's kind; unknown: yes)
; CF: DX
drive_takes:
        mov     dl, al
        mov     ah, 08h
        push    es
        int     13h
        pop     es
        jc      .y
        mov     [dkind], bl
        cmp     bl, 1
        jb      .y
        cmp     bl, 4
        ja      .y
        xor     bh, bh
        mov     al, [takes+bx-1]
        test    al, [kbit]
        jnz     .y
        mov     dx, s_nosup
        stc
        ret
.y:     clc
        ret

; the buffers: one a track, none across 64 KB, as many as there are
; (MAXTRK at most).  CF: DX (not even one)
slots:  mov     ax, [spt]
        shl     ax, 5
        mov     [tparas], ax            ; a track's paragraphs
        mov     ax, [mseg]
        mov     dx, ax
        add     dx, [mparas]            ; DX = the end
        xor     bx, bx
.l:     cmp     bx, MAXTRK * 2
        jae     .x
        mov     cx, ax                  ; across a 64 KB boundary?  the next
        and     cx, 0FFFh               ;  one, then
        add     cx, [tparas]
        cmp     cx, 1000h
        jbe     .in
        or      ax, 0FFFh
        inc     ax
        jz      .x
.in:    mov     cx, ax
        add     cx, [tparas]
        jc      .x
        cmp     cx, dx
        ja      .x
        mov     [slotseg+bx], ax
        add     bx, 2
        mov     ax, cx
        jmp     .l
.x:     shr     bx, 1
        mov     [nslot], bx
        or      bx, bx
        jnz     .ok
        mov     dx, s_nomem
        stc
        ret
.ok:    clc
        ret

; track AX (cylinder * sides copied + side) -> [cyl], [head]
trk_ch: xor     dx, dx
        div     word [hc]
        mov     [cyl], al
        mov     [head], dl
        ret

; read track [cyl]/[head] of drive DL into ES:0: whole, or sector by
; sector (each that won't read is said and left zeros).  -> AL = 0 all
; read, 1 some didn't, 2 not ready (DX = why).  ES kept
rd_track:
        mov     [unit], dl
.go:    mov     bp, TRIES
.t:     mov     ax, [spt]
        mov     ah, 02h
        mov     cl, 1
        xor     bx, bx
        call    bios_at
        jnc     .ok
        cmp     ah, 80h
        je      .nr
        cmp     ah, 06h
        je      .chg
        call    reset
        dec     bp
        jnz     .t
        mov     byte [sct], 1           ; sector by sector
        mov     byte [bad], 0
.s:     mov     bp, TRIES
.st:    mov     al, [sct]
        dec     al
        xor     ah, ah
        shl     ax, 9
        mov     bx, ax
        mov     ax, 0201h
        mov     cl, [sct]
        call    bios_at
        jnc     .sn
        cmp     ah, 06h
        je      .chg
        call    reset
        dec     bp
        jnz     .st
        push    es                      ; zeros where it couldn't be read
        mov     al, [sct]
        dec     al
        xor     ah, ah
        shl     ax, 9
        mov     di, ax
        mov     cx, 256
        xor     ax, ax
        rep     stosw
        pop     es
        mov     byte [bad], 1
.sn:    inc     byte [sct]
        mov     al, [sct]
        cmp     al, [spt]
        jbe     .s
        cmp     byte [bad], 0
        je      .ok
        mov     al, [unit]
        add     al, 'A'
        mov     [s_es], al
        mov     dx, s_rderr             ; "Unrecoverable read error on drive
        call    print                   ;  A:, side 0, track 5"
        call    p_where
%ifdef COMP
        mov     byte [result], 3
%else
        mov     byte [result], 1
%endif
        mov     al, 1
        ret
.ok:    xor     al, al
        ret
.nr:    mov     dx, s_nrdy
        mov     al, 2
        ret
.chg:   call    isit                    ; (the disk changed: the right one?
        jmp     .go                     ;  the track again)

; AH = call, AL = sectors, CL = the first, at [cyl]/[head] of [unit],
; ES:BX.  CF: AH = the BIOS's error.  ES, BP kept
bios_at:
        mov     ch, [cyl]
        mov     dh, [head]
        mov     dl, [unit]
        int     13h
        ret

reset:  push    ax
        mov     dl, [unit]
        xor     ah, ah
        int     13h
        pop     ax
        ret

; "side h, track t" (the cylinder)
p_where:
        mov     al, [head]
        xor     ah, ah
        call    pnum
        mov     dx, s_trk
        call    print
        mov     al, [cyl]
        xor     ah, ah
        call    pnum
        mov     dx, s_crlf
        jmp     print

%ifdef COMP
; ---------------------------------------------------------------------
; read track [cyl]/[head] of the target into tbuf and compare it with its
; buffer ([cslot]; [ctrk] the track).  -> AL = 0, 2 not ready (DX).  [result] 1 if they
; differ, 3 if it won't read
comp_track:
        mov     dl, [dst]
        push    es
        push    cs
        pop     es
        mov     ax, [tbuf]              ; (rd_track reads to ES:0: tbuf is on
        shr     ax, 4                   ;  a paragraph, as alignb 16 puts it)
        mov     bx, cs
        add     ax, bx
        mov     es, ax
        call    rd_track
        pop     es
        cmp     al, 2
        je      .x
        mov     bx, [cslot]             ; its buffer (this pass's)
        shl     bx, 1
        mov     es, [slotseg+bx]
        cmp     word [ctrk], 0          ; DOS 4's serial numbers: not
        jne     .cmp                    ;  compared (a DISKCOPY's copy has
        cmp     byte [bootsrc+26h], 29h ;  a new one)
        jne     .cmp
        cmp     byte [boottg+26h], 29h
        jne     .cmp
        mov     si, [tbuf]
        mov     ax, [es:27h]
        mov     [si+27h], ax
        mov     ax, [es:29h]
        mov     [si+29h], ax
.cmp:   mov     si, [tbuf]
        xor     di, di
        mov     cx, [spt]
        shl     cx, 8
        repe    cmpsw
        push    cs
        pop     es
        je      .same
        mov     dx, s_cmperr            ; "Compare error on side 0, track 5"
        call    print
        call    p_where
        cmp     byte [result], 1
        jae     .same
        mov     byte [result], 1
.same:  xor     al, al
.x:     ret
%else
; ---------------------------------------------------------------------
; the target, before its first write: no files open on it; formatted as
; it is written unless its own boot sector says it has the source's
; layout and its first track verifies at it (a disk of another density
; can read at the wrong rate after a BIOS's retries: only its BPB tells);
; the layout set (INT 13h 18h, INT 1Eh -> the BIOS's table).  CF: DX
tg_first:
        mov     ax, 0F001h
        mov     dl, [dst]
        int     21h
        mov     dx, s_open
        jcxz    .bt
        stc
        ret
.bt:    mov     byte [fmtmode], 1
        call    rd_tboot                ; its BPB: the source's layout?
        jnc     .bp
        cmp     dx, s_nrdy
        je      .no
        jmp     short .mt
.bp:    mov     si, [tbuf]
        cmp     word [si+510], 0AA55h
        jne     .mt
        mov     ax, [si+13h]            ; (sectors, sectors a track, sides)
        cmp     ax, [bootsrc+13h]
        jne     .mt
        mov     ax, [si+18h]
        cmp     ax, [bootsrc+18h]
        jne     .mt
        mov     ax, [si+1Ah]
        cmp     ax, [bootsrc+1Ah]
        jne     .mt
        mov     byte [fmtmode], 0
.mt:    mov     al, [dst]
        mov     [unit], al
        call    media
        jc      .x
        cmp     byte [fmtmode], 0
        jne     .f
        mov     byte [cyl], 0           ; and its first track at it
        mov     byte [head], 0
        mov     bp, TRIES
.v:     push    es
        push    cs
        pop     es
        mov     bx, [tbuf]
        mov     ax, [spt]
        mov     ah, 04h
        mov     cl, 1
        call    bios_at
        pop     es
        jnc     .ok
        mov     dx, s_nrdy
        cmp     ah, 80h
        je      .no
        call    reset
        dec     bp
        jnz     .v
        mov     byte [fmtmode], 1
.f:     mov     dx, s_fmting
        call    print
.ok:    clc
.x:     ret
.no:    stc
        ret

; the target's layout: INT 13h 18h (17h for a BIOS without it), INT 1Eh at
; the table it gives (dpt_back puts the old one back).  CF: DX
media:  mov     bp, TRIES
.t:     mov     ch, [cyls]
        dec     ch
        mov     cl, [spt]
        mov     dl, [dst]
        mov     ah, 18h
        push    es
        int     13h
        jnc     .ok
        pop     es
        cmp     ah, 0Ch
        je      .nos
        cmp     ah, 1
        je      .t17
        call    reset
        dec     bp
        jnz     .t
        cmp     ah, 80h
        jne     .go
        mov     dx, s_nrdy
        stc
        ret
.nos:   mov     dx, s_nosup
        stc
        ret
.ok:    mov     [dpt1], di
        mov     [dpt1+2], es
        pop     es
        cmp     byte [dptset], 0
        jne     .set
        push    es
        mov     ax, 351Eh
        int     21h
        mov     [dpt0], bx
        mov     [dpt0+2], es
        pop     es
.set:   push    ds
        lds     dx, [dpt1]
        mov     ax, 251Eh
        int     21h
        pop     ds
        mov     byte [dptset], 1
.go:    clc
        ret
.t17:   mov     al, 1                   ; 17h's types: 360 KB 1 (2 in a 1.2
        cmp     word [cyls], 40         ;  MB drive), 1.2 MB 3, 720 KB 4
        jne     .t2
        cmp     byte [dkind], 2
        jne     .ts
        inc     ax
        jmp     short .ts
.t2:    mov     al, 3
        cmp     word [spt], 15
        je      .ts
        mov     al, 4
        cmp     word [spt], 9
        jne     .go
.ts:    mov     dl, [dst]
        mov     ah, 17h
        int     13h
        clc
        ret

; write track [cyl]/[head] of the target from ES:0 (formatted first when
; it must be; with /V read back).  -> AL = 0 written, 1 it wouldn't be
; (said), 2 not ready (DX).  ES kept
wr_track:
        mov     al, [dst]
        mov     [unit], al
        mov     byte [wrote], 1         ; (something will have changed)
        mov     byte [fmted], 0
        cmp     byte [fmtmode], 0
        je      .w
.f:     call    fmt_track
        cmp     al, 2
        je      .x
        mov     byte [fmted], 1
.w:     mov     bp, TRIES
.wt:    mov     ax, [spt]
        mov     ah, 03h
        mov     cl, 1
        xor     bx, bx
        call    bios_at
        jnc     .v
        call    wp_or_nr                ; write-protected: put right, again
        jc      .x
        jz      .w
        call    reset
        dec     bp
        jnz     .wt
        cmp     byte [fmted], 0         ; it won't take a write: formatted,
        je      .f                      ;  then once more
        jmp     short .bad
.v:     cmp     byte [verify], 0
        je      .ok
        mov     bp, TRIES
.vt:    mov     ax, [spt]
        mov     ah, 04h
        mov     cl, 1
        xor     bx, bx
        call    bios_at
        jnc     .ok
        cmp     ah, 06h                 ; (the disk changed: the right one?
        jne     .vr                     ;  written again)
        call    isit
        jmp     .w
.vr:    call    reset
        dec     bp
        jnz     .vt
.bad:   mov     dx, s_wrerr             ; "Unrecoverable write error on drive
        call    print                   ;  B:, side 0, track 5"
        call    p_where
        mov     byte [result], 1
        mov     al, 1
        ret
.ok:    xor     al, al
.x:     ret
; one sector (track 0's first, [spt] 1) from ES:0, not formatted if it
; won't take it
wr_one: mov     al, [dst]
        mov     [unit], al
        mov     byte [fmted], 1
        jmp     wr_track.w

; the BIOS's error AH at a target write: write-protected (said; a key)
; or the disk changed (06h): the target made sure of, ZF: try again; not
; ready (CF, AL = 2, DX); another (NZ)
wp_or_nr:
        cmp     ah, 80h
        jne     .p
        mov     dx, s_nrdy
        mov     al, 2
        stc
        ret
.p:     cmp     ah, 06h
        je      .c
        cmp     ah, 03h
        jne     .o
        push    es
        mov     dx, s_wprot
        call    print
        call    press
        pop     es
.c:     call    isit
        mov     al, [dst]
        mov     [unit], al
        xor     ah, ah                  ; (ZF)
        clc
        ret
.o:     or      ah, ah                  ; (NZ)
        clc
        ret

; format track [cyl]/[head] of the target: its sectors' IDs in tbuf.
; -> AL = 0, 2 not ready (DX); a failure that isn't is left to the write
fmt_track:
        push    es
        push    cs
        pop     es
        mov     di, [tbuf]
        mov     cx, [spt]
        mov     bl, 1
.id:    mov     al, [cyl]
        mov     ah, [head]
        stosw
        mov     al, bl
        mov     ah, 2
        stosw
        inc     bl
        loop    .id
        pop     es
.f:     mov     bp, TRIES
.ft:    push    es
        push    cs
        pop     es
        mov     bx, [tbuf]
        mov     ax, [spt]
        mov     ah, 05h
        mov     cl, 1
        call    bios_at
        pop     es
        jnc     .ok
        call    wp_or_nr
        jc      .x
        jz      fmt_track               ; (the IDs again: isit used tbuf)
        call    reset
        dec     bp
        jnz     .ft
.ok:    xor     al, al
.x:     ret

; a new serial number from the date and the time, as MS-DOS 4 -> DX:AX
serial: mov     ah, 2Ah
        int     21h
        push    cx
        push    dx
        mov     ah, 2Ch
        int     21h
        pop     ax
        add     ax, dx
        pop     bx
        add     bx, cx
        inc     word [nser]             ; (never twice the same in a run)
        add     ax, [nser]
        mov     dx, bx
        ret
%endif

; INT 1Eh back as it was
dpt_back:
        cmp     byte [dptset], 0
        je      .x
        mov     byte [dptset], 0
        push    ds
        mov     dx, [dpt0]
        mov     ds, [dpt0+2]
        mov     ax, 251Eh
        int     21h
        pop     ds
.x:     ret

; ---------------------------------------------------------------------
; command tail: d1: d2: /1 /V.  CF: DX
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
.l:     lodsb
        cmp     al, 13
        je      .ok
        cmp     al, ' '
        je      .l
        cmp     al, 9
        je      .l
        cmp     al, '/'
        je      .sw
        cmp     byte [si], ':'
        jne     .bad
        and     al, 0DFh
        sub     al, 'A'
        cmp     al, 25
        ja      .bad
        inc     si
        cmp     byte [src], 0FFh
        jne     .d2
        mov     [src], al
        jmp     .l
.d2:    cmp     byte [dst], 0FFh
        jne     .bad
        mov     [dst], al
        jmp     .l
.sw:    lodsb
        cmp     al, '1'
        je      .one
%ifndef COMP
        and     al, 0DFh
        cmp     al, 'V'
        jne     .bad
        mov     byte [verify], 1
        jmp     .l
%else
        cmp     al, '8'
        jne     .bad
        mov     byte [eight], 1
        jmp     .l
%endif
.one:   mov     byte [side1], 1
        jmp     .l
.ok:    clc
        ret
.bad:   mov     dx, s_badsw
        stc
        ret

; ---------------------------------------------------------------------
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

; Esc or Ctrl-C typed meanwhile?  CF if so.  Other keys are taken out
; too, so one typed by mistake can't hide an Esc behind it
esc_key:
        mov     ah, 1
        int     16h
        jz      .n
        xor     ah, ah
        int     16h
        cmp     al, 27
        je      .y
        cmp     al, 3
        jne     esc_key
.y:     stc
        ret
.n:     clc
        ret

; a key through DOS (an extended one's second byte taken too: AL = 0)
getkey: mov     ah, 08h
        int     21h
        or      al, al
        jnz     .x
        mov     ah, 08h
        int     21h
        xor     al, al
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
; AX in decimal
pnum:   pusha
        mov     bx, 10
        xor     cx, cx
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     ax
        add     al, '0'
        call    putc
        loop    .p
        popa
        ret
; AX in 4 hex digits
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
; the layouts each kind of drive (INT 13h 08h's BL, 1-4) takes: a bit
; each, 40 cylinders 1, 720 KB 2, 1.2 MB 4, 1.44 MB 8
takes   db      1, 1 | 4, 2, 2 | 8

s_insrc db 13, 10, 'Insert SOURCE diskette in drive '
s_sd    db 'A:', 13, 10, '$'
s_instg db 'Insert TARGET diskette in drive '
s_td    db 'A:', 13, 10, '$'
s_intg  db 13, 10, 'Insert TARGET diskette in drive '
s_ot    db 'A:', 13, 10, '$'
s_press db 'Press any key when ready . . . (Esc: stop) $'
s_notsrc db "That isn't the SOURCE diskette (its boot sector differs)", 13, 10, '$'
s_nottg db "That isn't the TARGET diskette (its boot sector differs)", 13, 10, '$'
%ifdef COMP
s_cmping db 'Comparing $'
s_again db 13, 10, 'Compare another diskette (Y/N)? $'
s_ended db 'Compare process ended', 13, 10, '$'
s_cmperr db 'Compare error on side $'
s_cmpok db 13, 10, 'Compare OK', 13, 10, '$'
s_ntype db 13, 10, 'The diskettes are not of the same type: they differ', 13, 10, '$'
%else
s_copying db 'Copying $'
s_again db 13, 10, 'Copy another diskette (Y/N)? $'
s_ended db 'Copy process ended', 13, 10, '$'
s_fmting db 'Formatting while copying', 13, 10, '$'
s_wrerr db 'Unrecoverable write error on drive '
s_et    db 'A:, side $'
s_wprot db 13, 10, 'The TARGET diskette is write-protected: correct it, then', 13, 10, '$'
s_open  db 'Files are open on drive '
s_cd    db 'A: (a batch file or a program running from it)', 13, 10, '$'
s_ser   db 13, 10, 'Volume Serial Number is $'
s_unus  db 'Target diskette may be unusable', 13, 10, '$'
s_issrc db "That disk's first two sectors are the SOURCE diskette's: is it the", 13, 10
        db 'SOURCE?  Write on it all the same (Y/N)? $'
%endif
s_tracks db ' tracks', 13, 10, '$'
s_spt   db ' sectors/track, $'
s_sides db ' side(s)', 13, 10, '$'
s_rderr db 'Unrecoverable read error on drive '
s_es    db 'A:, side $'
s_trk   db ', track $'
s_nrdy  db 'Drive not ready: no disk in it?', 13, 10, '$'
s_noboot db 'The SOURCE diskette',39,'s boot sector can',39,'t be read', 13, 10, '$'
s_tnoboot db 'The TARGET diskette',39,'s boot sector can',39,'t be read', 13, 10, '$'
s_nolay db 'The SOURCE diskette has no layout this can copy (360 KB, 720 KB,', 13, 10
        db '1.2 MB or 1.44 MB, in its boot sector)', 13, 10, '$'
s_nosup db 'Drive types or diskette types not compatible', 13, 10, '$'
s_nomem db 'Insufficient memory', 13, 10, '$'
s_baddrv db 'Invalid drive specification: A: or B:, a floppy drive there', 13, 10, '$'
s_badsw db 'Invalid parameter', 13, 10, '$'
s_notlode db 'Needs Lodestone (other DOSes have their own)', 13, 10, '$'
s_tasks db 'Other tasks are running, or this runs as one (Shift-Return with no', 13, 10
        db 'other tasks: alone)', 13, 10, '$'
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
src     resb 1
dst     resb 1
single  resb 1
side1   resb 1
verify  resb 1
result  resb 1
firstw  resb 1
fmtmode resb 1
fmted   resb 1
dptset  resb 1
wrote   resb 1
newser  resb 1
unit    resb 1
cyl     resb 1
head    resb 1
sct     resb 1
bad     resb 1
kbit    resb 1
dkind   resb 1
t0done  resb 1
force   resb 1
phase   resb 1
nb      resb 1
eight   resb 1
        alignb 2
spt     resw 1
heads   resw 1
cyls    resw 1
hc      resw 1
ntr     resw 1
trk     resw 1
ctrk    resw 1
cslot   resw 1
npass   resw 1
nslot   resw 1
tparas  resw 1
mseg    resw 1
mparas  resw 1
tbuf    resw 1
nser    resw 1
dpt0    resw 2
dpt1    resw 2
path    resb 4
slotseg resw MAXTRK
bootsrc resb 1024                       ; (with the sector after each)
bootdst resb 1024
boottg  resb 1024
bootmk  resb 1024
        alignb 16
tb1     resb MAXSPT * 512
tb2     resb MAXSPT * 512
        resb 1024
stack_top:
bss_end:
prog_end:
