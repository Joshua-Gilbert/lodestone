; SYS.COM - makes a floppy start Lodestone, its files kept (DOS 3.30's SYS)
;
;   SYS [s:] d:
;
;   d:   the floppy, A: or B:.  C:, M: and R: are refused: the 1520's BIOS
;        starts Lodestone from a floppy or the ROM only.
;   s:   where the system comes from; by default the drive Lodestone
;        started from (INT 21h 3305h: R: from the ROM)
;
; LODE.SYS, LODEMT.SYS, LODE.PIC and LCMD.COM are read from s:'s root
; (LODE.SYS must be there, the others when they are) into memory first,
; so with s: and d: one drive the disk is changed at "Insert the disk";
; then each goes onto d: through DOS: written as LODESYS.$$$, the old one
; deleted (its read-only, hidden or system bits taken off first), the new
; one renamed, so a write that fails leaves the old file.  The room is
; worked out first, file by file as they go on (an old copy's clusters
; free only once it's gone): if it isn't there, nothing is written.  The
; boot sector last: BOOT.BIN's code with the disk's own BPB (0Bh-3Dh, as
; LODEBOOT), only once every file is there, after a check that the disk
; is still the one read (its change line, or its boot sector as read),
; then read back.  The BPB stays as it was, so the kernel keeps the disk
; mounted (and its current directory there); INT 21h 0Dh before and
; after.  With multitasking it must be the only task (Shift-Return with
; no others): another could be using the disk.
;
; Exit code: 0 "System transferred", 1 couldn't (no LODE.SYS to copy, no
; room, not a floppy Lodestone can start from, write-protected, the disk
; changed, ...), 3 Esc or Ctrl-C at "Insert the disk".  Needs Lodestone.
cpu 286
org 100h

TRIES   equ 3
NSYS    equ 4
dta     equ 80h                         ; (the DTA: the PSP's, the tail read by then)

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     bx, prog_end + 15
        shr     bx, 4
        mov     ah, 4Ah                 ; room for the system files
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
        jc      fail
        mov     dx, s_nodrv
        cmp     byte [dst], 0FFh
        je      fail
        mov     ax, 0F000h              ; Lodestone?
        int     21h
        cmp     ax, 4F47h
        mov     dx, s_notlode
        jne     fail
        call    alone
        jc      fail
        mov     al, [dst]
        add     al, 'A'
        mov     [s_d1], al
        mov     [s_d2], al
        mov     [s_d3], al
        mov     [s_d4], al
        cmp     byte [dst], 1           ; A: or B: only
        mov     dx, s_notfl
        ja      fail
        int     11h                     ; is there such a drive?
        xor     cl, cl
        test    al, 1
        jz      .nd
        mov     cl, al
        shr     cl, 6
        inc     cl
.nd:    cmp     [dst], cl
        mov     dx, s_baddrv
        jae     fail
        cmp     byte [src], 0FFh        ; where the system comes from
        jne     .s
        mov     ax, 3305h
        int     21h
        dec     dl
        mov     [src], dl
.s:     call    buf_set
        call    load_sys                ; (read now: one drive)
        jc      fail
        mov     al, [src]
        cmp     al, [dst]
        jne     .go
        call    insert                  ; the same drive: the disk changed
.go:    mov     ax, 0D00h               ; the kernel's changes on the disk
        int     21h
        mov     ax, 0F001h              ; files open on it?
        mov     dl, [dst]
        int     21h
        mov     dx, s_open
        jcxz    .no
        jmp     fail
.no:    call    rd_boot                 ; a floppy Lodestone starts from?
        jc      fail
        call    room
        jc      fail
        call    copy_sys
        jc      fail
        call    wr_boot
        jc      fail
        mov     ah, 0Dh
        int     21h
        mov     dx, s_done
        call    print
        mov     ax, 4C00h
        int     21h

fail:   call    print
        mov     ah, 0Dh                 ; (whatever was written: the kernel
        int     21h                     ;  reads the disk again)
        mov     ax, 4C01h
        int     21h
stop:   mov     dx, s_crlf
        call    print
        mov     ax, 4C03h
        int     21h
ctrlc:  push    cs
        pop     ds
        mov     ax, 4C03h
        int     21h
crit:   mov     [cs:critcode], di       ; (DOS's I/O: fail it, the why kept)
        mov     byte [cs:crithit], 1
        mov     al, 3
        iret

; ---------------------------------------------------------------------
; command tail: [s:] d:.  CF: DX
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
.l:     lodsb
        cmp     al, 13
        je      .x
        cmp     al, ' '
        je      .l
        cmp     al, 9
        je      .l
        cmp     byte [si], ':'
        jne     .bad
        and     al, 0DFh
        sub     al, 'A'
        cmp     al, 25
        ja      .bad
        inc     si
        cmp     byte [dst], 0FFh        ; the first: d: (or s:, if another
        je      .d                      ;  comes)
        cmp     byte [src], 0FFh
        jne     .bad
        mov     ah, [dst]
        mov     [src], ah
.d:     mov     [dst], al
        jmp     .l
.x:     clc
        ret
.bad:   mov     dx, s_badsw
        stc
        ret

; with multitasking, alone?  CF: DX
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

; "Insert the disk ... and strike ENTER"; Esc, Ctrl-C, a file's end stop
insert: call    flush_keys
        mov     dx, s_insert
        call    print
.k:     mov     ah, 08h
        int     21h
        cmp     al, 13
        je      .go
        cmp     al, 27
        je      stop
        cmp     al, 3
        je      stop
        cmp     al, 1Ah
        je      stop
        jmp     .k
.go:    mov     dx, s_crlf
        jmp     print

; ---------------------------------------------------------------------
; d:'s boot sector -> bootcp; a FAT12 floppy BOOT.BIN starts from (as
; LODEBOOT checks it).  CF: DX
rd_boot:
        mov     byte [xop], 2
        call    sec0
        mov     dx, s_rderr
        jc      .x
        mov     si, [sec]
        mov     di, bootcp
        mov     cx, 256
        rep     movsw
        mov     dx, s_badbpb
        cmp     word [bootcp+510], 0AA55h
        jne     .bad
        cmp     word [bootcp+0Bh], 512
        jne     .bad
        mov     al, [bootcp+0Dh]        ; sectors a cluster 1 or 2
        cmp     al, 1
        jb      .bad
        cmp     al, 2
        ja      .bad
        mov     al, [bootcp+10h]        ; FATs 1 or 2
        cmp     al, 1
        jb      .bad
        cmp     al, 2
        ja      .bad
        mov     ax, [bootcp+18h]        ; sectors a track 8-36, two heads
        cmp     ax, 8
        jb      .bad
        cmp     ax, 36
        ja      .bad
        cmp     word [bootcp+1Ah], 2
        jne     .bad
        cmp     word [bootcp+0Eh], 1    ; one reserved sector, a root, a FAT
        jne     .bad
        cmp     word [bootcp+11h], 0
        je      .bad
        cmp     word [bootcp+16h], 0
        je      .bad
        cmp     word [bootcp+13h], 0    ; (16-bit sectors: a floppy)
        je      .bad
        clc
.x:     ret
.bad:   stc
        ret

; sector 0 of d: (read or write as [xop]) at [sec]: TRIES times, a reset
; between; a write that finds the disk changed or write-protected not
; again.  CF: [bstat]
sec0:   mov     bp, TRIES
.t:     push    cs
        pop     es
        mov     bx, [sec]
        mov     ax, 0001h
        mov     ah, [xop]
        mov     cx, 0001h
        xor     dh, dh
        mov     dl, [dst]
        int     13h
        jnc     .ok
        mov     [bstat], ah
        cmp     byte [xop], 3
        jne     .rs
        cmp     ah, 03h
        je      .err
        cmp     ah, 06h
        je      .err
.rs:    xor     ah, ah
        mov     dl, [dst]
        int     13h
        dec     bp
        jnz     .t
.err:   stc
        ret
.ok:    clc
        ret

; ---------------------------------------------------------------------
; the room on d:, file by file in the order they go on (each new one
; written while its old copy is still there).  CF: DX
room:   mov     ah, 36h                 ; free clusters, their size
        mov     dl, [dst]
        inc     dx
        int     21h
        cmp     ax, 0FFFFh
        mov     dx, s_rderr
        je      .no
        mul     cx                      ; (AX sectors a cluster, CX bytes)
        mov     [csize], ax
        mov     [free], bx
        mov     bx, sysrec
.f:     cmp     word [bx+R_NAME], 0
        je      .nx
        mov     ax, [bx+R_SIZE]         ; its clusters: what it needs
        mov     dx, [bx+R_SIZE+2]
        call    clus
        cmp     ax, [free]
        ja      .full
        sub     [free], ax
        call    dpath                   ; the old one's: back when it goes
        mov     dx, path
        mov     cx, 07h
        mov     ah, 4Eh
        int     21h
        jc      .nx
        mov     ax, [dta+1Ah]
        mov     dx, [dta+1Ch]
        call    clus
        add     [free], ax
.nx:    add     bx, RSZ
        cmp     bx, sysrec + NSYS * RSZ
        jb      .f
        clc
        ret
.full:  mov     dx, s_room
.no:    stc
        ret

; DX:AX bytes -> AX clusters of [csize]
clus:   add     ax, [csize]
        adc     dx, 0
        sub     ax, 1
        sbb     dx, 0
        div     word [csize]
        ret

; path = "d:\NAME" for the file record BX
dpath:  mov     si, [bx+R_NAME]
        mov     di, path
dpath2: mov     al, [dst]
        add     al, 'A'
        stosb
        mov     ax, '\' << 8 | ':'
        stosw
.c:     lodsb
        stosb
        or      al, al
        jnz     .c
        ret

; ---------------------------------------------------------------------
; s:'s system files into memory.  CF: DX
load_sys:
        mov     dl, [src]
        add     dl, 'A'
        mov     bx, sysrec
        mov     si, sysnames
.f:     mov     [bx+R_NAME], si
        mov     [bx+R_PATH], dl
        push    dx
        push    si
        lea     di, [bx+R_PATH+3]       ; "X:\NAME"
        mov     byte [bx+R_PATH+1], ':'
        mov     byte [bx+R_PATH+2], '\'
.c:     lodsb
        mov     [di], al
        inc     di
        or      al, al
        jnz     .c
        lea     dx, [bx+R_PATH]
        mov     ax, 3D00h
        int     21h
        jc      .miss
        mov     [handle], ax
        push    bx
        mov     bx, ax
        mov     ax, 5700h               ; its time and date
        int     21h
        pop     bx
        mov     [bx+R_TIME], cx
        mov     [bx+R_DATE], dx
        push    bx
        mov     bx, [handle]
        mov     ax, 4202h               ; its size
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
        pop     bx
        mov     [bx+R_SIZE], ax
        mov     [bx+R_SIZE+2], dx
        add     ax, 15                  ; its memory
        adc     dx, 0
        mov     cx, 16
        div     cx
        push    bx
        mov     bx, ax
        mov     ah, 48h
        int     21h
        pop     bx
        jc      .mem
        mov     [bx+R_SEG], ax
        mov     ah, 3Fh
        call    xfer
        pushf
        push    bx
        mov     bx, [handle]
        mov     ah, 3Eh
        int     21h
        pop     bx
        popf
        jc      .rerr
        jmp     short .nx
.miss:  cmp     bx, sysrec              ; LODE.SYS must be there; the
        je      .nosys                  ;  others when they are
        mov     word [bx+R_NAME], 0
.nx:    pop     si
        pop     dx
.sk:    lodsb                           ; the next name
        or      al, al
        jnz     .sk
        add     bx, RSZ
        cmp     bx, sysrec + NSYS * RSZ
        jb      .f
        clc
        ret
.nosys: mov     dx, s_nosys
        jmp     short .e
.mem:   push    bx
        mov     bx, [handle]
        mov     ah, 3Eh
        int     21h
        pop     bx
        mov     dx, s_sysmem
        jmp     short .e
.rerr:  mov     dx, s_sysrd
.e:     pop     si
        pop     si
        stc
        ret

; the file record BX's memory to or from [handle]: AH = 3Fh read, 40h
; write, 32 KB at a time.  CF if it fails or comes up short
xfer:   pusha
        push    ds
        mov     [fop], ah
        mov     si, [bx+R_SIZE]
        mov     di, [bx+R_SIZE+2]
        mov     bp, [bx+R_SEG]
        mov     bx, [handle]
.l:     mov     cx, 8000h
        or      di, di
        jnz     .n
        cmp     si, cx
        jae     .n
        mov     cx, si
        jcxz    .ok
.n:     mov     ah, [cs:fop]
        mov     ds, bp
        xor     dx, dx
        int     21h
        push    cs
        pop     ds
        jc      .x
        cmp     ax, cx
        stc
        jne     .x
        sub     si, cx
        sbb     di, 0
        add     bp, 800h
        jmp     .l
.ok:    clc
.x:     pop     ds
        popa
        ret

; each file onto d:: LODESYS.$$$ written, the old file deleted, the new
; one renamed.  CF: DX
copy_sys:
        mov     bx, sysrec
.f:     cmp     word [bx+R_NAME], 0
        je      .nx
        mov     si, s_tmpn              ; "d:\LODESYS.$$$"
        mov     di, tpath
        call    dpath2
        mov     dx, tpath
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .err
        mov     [handle], ax
        mov     ah, 40h
        call    xfer
        pushf
        push    bx
        mov     cx, [bx+R_TIME]
        mov     dx, [bx+R_DATE]
        mov     bx, [handle]
        mov     ax, 5701h
        int     21h
        mov     ah, 3Eh
        int     21h
        pop     bx
        popf
        jc      .gone
        call    dpath                   ; the old one away (its bits off)
        mov     dx, path
        xor     cx, cx
        mov     ax, 4301h
        int     21h
        mov     dx, path
        mov     ah, 41h
        int     21h
        jnc     .rn
        cmp     ax, 2                   ; (none there: fine)
        jne     .gone
.rn:    mov     dx, tpath               ; the new one its name
        mov     di, path
        push    ds
        pop     es
        mov     ah, 56h
        int     21h
        jc      .err
.nx:    add     bx, RSZ
        cmp     bx, sysrec + NSYS * RSZ
        jb      .f
        clc
        ret
.gone:  mov     dx, tpath               ; (the new one written in part)
        mov     ah, 41h
        int     21h
.err:   mov     dx, s_wprot
        cmp     byte [crithit], 0
        je      .e2
        cmp     byte [critcode], 0      ; (INT 24h's 0: write-protected)
        je      .e
.e2:    mov     dx, s_syswr
.e:     stc
        ret

; ---------------------------------------------------------------------
; the boot sector: BOOT.BIN's code, the disk's own BPB; only once the disk
; is still the one read (LODE.SYS on it as written; its change line, or
; its boot sector as read); then read back.  CF: DX
wr_boot:
        mov     ax, 0D00h               ; (the files' FAT and directory
        int     21h                     ;  written first)
        mov     ah, 16h                 ; the same disk?  Its change line;
        mov     dl, [dst]               ;  or its boot sector as read
        int     13h
        jnc     .same
        mov     byte [xop], 2
        call    sec0
        mov     dx, s_rderr
        jc      .x
        mov     si, [sec]
        mov     di, bootcp
        mov     cx, 256
        push    ds
        pop     es
        repe    cmpsw
        mov     dx, s_dchg
        jne     .no
.same:  mov     bx, sysrec              ; LODE.SYS there as just written (the
        call    dpath                   ;  kernel reads the disk afresh: a
        mov     dx, path                ;  disk changed meanwhile hasn't it,
        mov     cx, 07h                 ;  even with the same boot sector)
        mov     ah, 4Eh
        int     21h
        mov     dx, s_dchg
        jc      .no
        mov     ax, [dta+1Ah]
        cmp     ax, [sysrec+R_SIZE]
        jne     .no
        mov     ax, [dta+1Ch]
        cmp     ax, [sysrec+R_SIZE+2]
        jne     .no
        mov     ax, [dta+16h]
        cmp     ax, [sysrec+R_TIME]
        jne     .no
        mov     ax, [dta+18h]
        cmp     ax, [sysrec+R_DATE]
        jne     .no
        mov     si, bootcp              ; the new sector
        mov     di, [sec]
        mov     cx, 256
        push    ds
        pop     es
        rep     movsw
        mov     si, bootbin
        mov     di, [sec]
        mov     cx, 0Bh                 ; (the jump and the OEM name)
        rep     movsb
        mov     si, bootbin + 3Eh
        mov     di, [sec]
        add     di, 3Eh
        mov     cx, 512 - 3Eh
        rep     movsb
        mov     si, [sec]               ; (kept, to read back)
        mov     di, newboot
        mov     cx, 256
        rep     movsw
        mov     byte [xop], 3
        call    sec0
        jnc     .rb
        mov     dx, s_dchg
        cmp     byte [bstat], 6
        je      .no
        mov     dx, s_wprot
        cmp     byte [bstat], 3
        je      .no
        mov     dx, s_bwerr
        jmp     short .no
.rb:    mov     byte [xop], 2           ; read back
        call    sec0
        mov     dx, s_bwerr
        jc      .no
        mov     si, [sec]
        mov     di, newboot
        mov     cx, 256
        push    ds
        pop     es
        repe    cmpsw
        jne     .no
        clc
.x:     ret
.no:    stc
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

print:  mov     ah, 9
        int     21h
        ret

; ---------------------------------------------------------------------
sysnames db 'LODE.SYS', 0, 'LODEMT.SYS', 0, 'LODE.PIC', 0, 'LCMD.COM', 0
s_tmpn  db 'LODESYS.$$$', 0
R_NAME  equ 0                           ; -> its name (0: not there)
R_SEG   equ 2                           ; its memory
R_SIZE  equ 4                           ; dword
R_TIME  equ 8
R_DATE  equ 10
R_PATH  equ 12                          ; "X:\NAME", 0 (16)
RSZ     equ 28

s_insert db 'Insert the disk to start Lodestone from in drive '
s_d1    db 'A:', 13, 10, 'and strike ENTER when ready (Esc: quit)$'
s_done  db 'System transferred', 13, 10, '$'
s_nodrv db 'SYS: which drive?  SYS [s:] d: (d: a floppy, A: or B:)', 13, 10, '$'
s_notfl db 'SYS: floppies only (A: or B:): Lodestone starts from a floppy or the ROM', 13, 10, '$'
s_baddrv db 'Invalid drive specification', 13, 10, '$'
s_badsw db 'Invalid parameter', 13, 10, '$'
s_notlode db 'SYS: needs Lodestone (other DOSes have their own SYS)', 13, 10, '$'
s_tasks db 'SYS: other tasks are running, or SYS runs as one (Shift-Return with no', 13, 10
        db 'other tasks: alone)', 13, 10, '$'
s_open  db 'Files are open on drive '
s_d2    db 'A: (a batch file or a program running from it)', 13, 10, '$'
s_rderr db 'Cannot read the disk in drive '
s_d3    db 'A:', 13, 10, '$'
s_badbpb db 'Not a floppy Lodestone can start from (a FAT12 disk of 720 KB or 1.44 MB,', 13, 10
        db 'or another standard floppy): FORMAT it', 13, 10, '$'
s_room  db 'No room for the system on drive '
s_d4    db 'A:: nothing written', 13, 10, '$'
s_nosys db 'Cannot find the system: no LODE.SYS there', 13, 10, '$'
s_sysmem db 'Insufficient memory for system transfer', 13, 10, '$'
s_sysrd db 'Cannot read the system files', 13, 10, '$'
s_syswr db 'Cannot write the system files: the old ones left as they were', 13, 10, '$'
s_wprot db 'Write protect error: nothing written', 13, 10, '$'
s_dchg  db 'The disk was changed: its boot sector not written', 13, 10, '$'
s_bwerr db 'Disk error writing the boot sector', 13, 10, '$'
s_crlf  db 13, 10, '$'

        alignb 2
bootbin incbin "BOOT.BIN"

        alignb 2
section .bss
bss_start:
src     resb 1
dst     resb 1
xop     resb 1
fop     resb 1
bstat   resb 1
crithit resb 1
        alignb 2
critcode resw 1
sec     resw 1
handle  resw 1
csize   resw 1
free    resw 1
path    resb 20
tpath   resb 20
        alignb 2
sysrec  resb NSYS * RSZ
bootcp  resb 512
newboot resb 512
        alignb 16
sb1     resb 512
sb2     resb 512
        resb 1024
stack_top:
bss_end:
prog_end:
