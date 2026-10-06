; HEADCLN.COM - spins a floppy drive and sweeps its heads across the disk,
; for a wet head-cleaning disk.
;
;   HEADCLN [A:|B:] [seconds]
;
; A: is the GRiD's own drive (BIOS unit 0), B: the external one (unit 1),
; as under Grid-OS.  Default A:, 30 seconds (at most 120).
;
; It loads first, then asks for the cleaning disk, so it can be run from
; the boot floppy.  It only reads (and a read of a cleaning disk just
; fails): nothing is ever written, so a data disk left in by mistake comes
; to no harm - and if the disk turns out to be readable it stops and says
; so.  The heads move in steps of 4 cylinders from 0 to 79 and back, so the
; whole pad is used, not one ring of it.  Afterwards: take the cleaning
; disk out, a minute for the alcohol to dry, then your own disk back in
; before it returns (Grid-OS reads the disk again straight away).
; Only BIOS calls touch the drive; INT 21h 0Dh at the end so DOS (or
; Grid-OS) checks the disk again before trusting what it remembers.
cpu 286
org 100h

STEP    equ 4                           ; cylinders per move
DWELL   equ 4                           ; ticks at least at each place (~0.2 s:
                                        ;  the pad wipes the heads as it turns)
LASTCYL equ 79

start:  cld
        mov     di, bss_start           ; (a .COM's memory isn't cleared)
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        mov     byte [unit], 0
        mov     word [secs], 30
        call    args
        int     11h                     ; is there such a drive?
        xor     cl, cl
        test    al, 1
        jz      .n
        mov     cl, al
        shr     cl, 6
        inc     cl
.n:     mov     al, [unit]
        add     al, 'A'
        mov     [s_drv1], al
        mov     [s_drv2], al
        mov     [s_drv3], al
        mov     [s_drv4], al
        mov     [s_drv5], al
        mov     al, [unit]
        cmp     al, cl
        jb      .ok
        mov     dx, s_nodrv
        call    print
        mov     ax, 4C02h
        int     21h
.ok:    ; a sector buffer that doesn't cross a 64 KB DMA boundary
        mov     ax, cs
        shl     ax, 4
        add     ax, sb1
        mov     word [buf], sb1
        cmp     ax, 0FE00h
        jbe     .b
        mov     word [buf], sb2
.b:     mov     dx, s_title
        call    print
        mov     dx, s_put
        call    print
        call    getkey
        cmp     al, 27
        jne     clean
        mov     dx, s_quit
        call    print
        mov     ax, 4C01h
        int     21h

; ---------------------------------------------------------------------
clean:  mov     dx, s_crlf
        call    print
        mov     ax, [secs]              ; ticks = seconds * 18.2
        mov     bx, 182
        mul     bx
        mov     bx, 10
        div     bx
        mov     [nticks], ax
        call    ticks
        mov     [t0], ax
        mov     byte [cyl], 0
        mov     byte [dir], 1
        mov     byte [head], 0
.l:     call    ticks                   ; time up?
        sub     ax, [t0]
        cmp     ax, [nticks]
        jae     .done
        mov     bx, [nticks]
        sub     bx, ax
        mov     ax, bx                  ; seconds left
        mov     bx, 10
        mul     bx
        mov     bx, 182
        div     bx
        inc     ax
        mov     [left], ax
        call    status
        call    ticks
        mov     [tpos], ax
        call    readone
        jc      .stop                   ; (AL = why)
.dw:    mov     ah, 1                   ; Esc?
        int     16h
        jz      .dt
        xor     ah, ah
        int     16h
        cmp     al, 27
        jne     .dt
        mov     dx, s_esc
        jmp     short .msg
.dt:    call    ticks                   ; stay a moment
        sub     ax, [tpos]
        cmp     ax, DWELL
        jb      .dw
.mv:    xor     byte [head], 1          ; next place
        mov     al, [cyl]
        cmp     byte [dir], 0
        je      .dn
        add     al, STEP
        cmp     al, LASTCYL
        jb      .set
        mov     al, LASTCYL
        mov     byte [dir], 0
        inc     word [sweeps]
        jmp     short .set
.dn:    sub     al, STEP
        jnc     .set0
        xor     al, al
.set0:  or      al, al
        jnz     .set
        mov     byte [dir], 1
        inc     word [sweeps]
.set:   mov     [cyl], al
        jmp     .l
.stop:  mov     dx, s_nodisk
        cmp     al, 1
        jne     .msg
        mov     dx, s_data
        jmp     short .msg
.done:  mov     word [left], 0
        call    status
        mov     dx, s_done
.msg:   push    dx
        mov     dx, s_crlf
        call    print
        pop     dx
        call    print
        mov     ax, [sweeps]
        call    pnum
        mov     dx, s_sweeps
        call    print
        ; out with the cleaning disk; let the heads dry
        mov     dx, s_out
        call    print
        mov     word [left], 60
        call    ticks
        mov     [t0], ax
.dry:   mov     dx, s_cr
        call    print
        mov     dx, s_dry
        call    print
        mov     ax, [left]
        call    pnum
        mov     dx, s_dry2
        call    print
.w:     mov     ah, 1
        int     16h
        jz      .t
        xor     ah, ah
        int     16h
        jmp     short .back
.t:     call    ticks
        sub     ax, [t0]
        cmp     ax, 18                  ; ~a second
        jb      .w
        add     word [t0], 18
        dec     word [left]
        jnz     .dry
.back:  mov     dx, s_crlf
        call    print
        mov     dx, s_back
        call    print
        call    getkey
        mov     ah, 0Dh                 ; DOS: check the disk again
        int     21h
        mov     dx, s_crlf
        call    print
        mov     ax, 4C00h
        int     21h

; one read at [cyl]/[head], sector 1.  CF set if it has to stop: AL = 1 a
; readable disk (3 good reads running), 2 no disk / not turning (3
; time-outs running).  A failed read of the cleaning disk is the normal
; case; anything but "can't find the sector" gets a reset (which also
; recalibrates).
readone:
        mov     ax, cs
        mov     es, ax
        mov     bx, [buf]
        mov     ch, [cyl]
        mov     cl, 1
        mov     dh, [head]
        mov     dl, [unit]
        mov     ax, 0201h
        int     13h
        jc      .err
        mov     byte [nto], 0
        inc     byte [ngood]
        cmp     byte [ngood], 3
        jb      .ok
        mov     al, 1
        stc
        ret
.err:   mov     byte [ngood], 0
        cmp     ah, 80h                 ; time-out: no disk?
        jne     .e2
        inc     byte [nto]
        cmp     byte [nto], 3
        jb      .rs
        mov     al, 2
        stc
        ret
.e2:    mov     byte [nto], 0
        cmp     ah, 2                   ; address mark not found,
        je      .ok                     ; sector not found, CRC error:
        cmp     ah, 4                   ; what a cleaning disk gives
        je      .ok
        cmp     ah, 10h
        je      .ok
.rs:    xor     ax, ax                  ; anything else: reset
        mov     dl, [unit]
        int     13h
.ok:    clc
        ret

; "  Cleaning drive A:   cylinder 40, side 1    23 s left   (Esc stops)"
status: mov     dx, s_cr
        call    print
        mov     dx, s_st1
        call    print
        mov     al, [cyl]
        xor     ah, ah
        call    pnum2
        mov     dx, s_st2
        call    print
        mov     al, [head]
        add     al, '0'
        call    putc
        mov     dx, s_st3
        call    print
        mov     ax, [left]
        call    pnum3
        mov     dx, s_st4
        call    print
        ret

; the BIOS tick count (low word)
ticks:  push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        ret

; a key from the BIOS (no ^C, no echo); AL = its character
getkey: mov     ah, 1                   ; (drop anything typed before)
        int     16h
        jz      .w
        xor     ah, ah
        int     16h
        jmp     getkey
.w:     xor     ah, ah
        int     16h
        ret

; command tail: A: or B:, and a number of seconds
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 13
.l:     lodsb
        cmp     al, 13
        je      .x
        cmp     al, '0'
        jb      .ltr
        cmp     al, '9'
        ja      .ltr
        xor     dx, dx                  ; seconds
.d:     sub     al, '0'
        xor     ah, ah
        imul    dx, dx, 10
        add     dx, ax
        lodsb
        cmp     al, '0'
        jb      .de
        cmp     al, '9'
        jbe     .d
.de:    dec     si
        or      dx, dx
        jz      .l
        cmp     dx, 120
        jbe     .sv
        mov     dx, 120
.sv:    mov     [secs], dx
        jmp     .l
.ltr:   and     al, 0DFh
        cmp     byte [si], ':'
        jne     .l
        sub     al, 'A'
        cmp     al, 1
        ja      .l
        mov     [unit], al
        inc     si
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
; AX in decimal: pnum as is, pnum2 / pnum3 right-aligned in 2 / 3 places
pnum3:  cmp     ax, 100
        jae     pnum
        push    ax
        mov     al, ' '
        call    putc
        pop     ax
pnum2:  cmp     ax, 10
        jae     pnum
        push    ax
        mov     al, ' '
        call    putc
        pop     ax
pnum:   push    bx
        push    cx
        push    dx
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
        pop     dx
        pop     cx
        pop     bx
        ret

s_title db 'HEADCLN - floppy head cleaning, with a wet cleaning disk', 13, 10, 13, 10, '$'
s_put   db 'Put a few drops of isopropyl alcohol on the cleaning disk (damp, not', 13, 10
        db 'soaked), take your disk out of drive '
s_drv1  db 'A: and put the cleaning disk in.', 13, 10
        db 'Then press a key to start (Esc: quit).', 13, 10, '$'
s_quit  db 'Nothing done.', 13, 10, '$'
s_cr    db 13, '$'
s_st1   db '  Cleaning drive '
s_drv2  db 'A:   cylinder $'
s_st2   db ', side $'
s_st3   db '   $'
s_st4   db ' s left   (Esc stops)  $'
s_done  db 'Done: $'
s_esc   db 'Stopped: $'
s_data  db 'That disk can be read - it is not a cleaning disk.  Stopped: $'
s_nodisk db 'The drive does not answer - no disk in it?  Stopped: $'
s_sweeps db ' sweeps across the disk.', 13, 10, 13, 10, '$'
s_out   db 'Take the cleaning disk out of drive '
s_drv3  db 'A: now.', 13, 10, '$'
s_dry   db 'Letting the heads dry: $'
s_dry2  db ' s  (any key: skip)  $'
s_back  db 'Put your own disk back in drive '
s_drv4  db 'A: and press a key.$'
s_nodrv db 'HEADCLN: there is no floppy drive '
s_drv5  db 'A:', 13, 10, '$'
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
unit    resb 1
cyl     resb 1
head    resb 1
dir     resb 1
ngood   resb 1
nto     resb 1
secs    resw 1
nticks  resw 1
t0      resw 1
tpos    resw 1
left    resw 1
sweeps  resw 1
buf     resw 1
        alignb 16
sb1     resb 512
sb2     resb 512
bss_end:
