; DISKMAP.COM - saves the floppy's system area (boot sector, both FATs and
; the root directory) to DISKMAP.BIN on the current drive, and shows how
; much of the root directory is in use - deleted entries included, since a
; search has to walk past them to the end marker.
;
; Reads with INT 13h from floppy unit 0, so it works the same under Lodestone
; (where the floppy is A:) and GRiD MS-DOS (where it is B:).  Everything is
; read into memory before DISKMAP.BIN is created, so the dump shows the disk
; as it was.  Waits for a key at the end.
cpu 286
org 100h

MAXSEC  equ 80                          ; system area we can hold (40 KB)

start:  cld
        mov     sp, stack_top
        mov     di, sbuf                ; (a .COM's memory isn't cleared)
        mov     cx, stack_top - sbuf
        xor     al, al
        rep     stosb
        mov     dx, s_title
        call    print
        ; a 512-byte sector buffer that doesn't cross a 64 KB DMA boundary
        mov     ax, cs
        shl     ax, 4
        add     ax, sb1
        mov     word [sbuf], sb1
        cmp     ax, 0FE00h
        jbe     .sb
        mov     word [sbuf], sb2
.sb:    ; the boot sector: geometry and where the root is
        mov     word [spt], 18          ; (for reading sector 0 itself)
        mov     word [heads], 2
        xor     ax, ax
        call    rdsec
        jc      dskerr
        mov     si, [sbuf]
        cmp     word [si+0Bh], 512
        jne     notfat
        mov     ax, [si+18h]
        or      ax, ax
        jz      notfat
        cmp     ax, 63
        ja      notfat
        mov     [spt], ax
        mov     ax, [si+1Ah]
        or      ax, ax
        jz      notfat
        cmp     ax, 2
        ja      notfat
        mov     [heads], ax
        mov     ax, [si+11h]
        mov     [nroot], ax
        mov     al, [si+10h]
        xor     ah, ah
        mul     word [si+16h]
        add     ax, [si+0Eh]
        mov     [rootlba], ax           ; reserved + FATs
        mov     ax, [nroot]
        add     ax, 15
        shr     ax, 4
        mov     [rootsecs], ax
        add     ax, [rootlba]
        mov     [nsecs], ax
        cmp     ax, MAXSEC
        ja      notfat
        ; everything into memory, one sector at a time
        xor     ax, ax
        mov     [lba], ax
.rd:    mov     ax, [lba]
        call    rdsec
        jc      dskerr
        mov     si, [sbuf]
        mov     di, [lba]
        shl     di, 9
        add     di, area
        mov     cx, 256
        rep     movsw
        inc     word [lba]
        mov     ax, [lba]
        cmp     ax, [nsecs]
        jb      .rd
        ; the root: entries up to the end marker
        mov     si, [rootlba]
        shl     si, 9
        add     si, area
        xor     cx, cx                  ; index
.sc:    cmp     cx, [nroot]
        jae     .sx
        mov     al, [si]
        or      al, al
        jz      .sx
        inc     word [used]
        cmp     al, 0E5h
        jne     .live
        inc     word [ndel]
        jmp     short .nx
.live:  mov     al, [si+11]
        cmp     al, 0Fh
        jne     .nl
        inc     word [nlfn]
        jmp     short .nx
.nl:    test    al, 08h
        jnz     .nx                     ; (the volume label)
        inc     word [nfil]
.nx:    add     si, 32
        inc     cx
        jmp     .sc
.sx:    ; save it
        mov     dx, s_file
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      ferr
        mov     bx, ax
        mov     cx, [nsecs]
        shl     cx, 9
        mov     dx, area
        mov     ah, 40h
        int     21h
        jc      ferr
        cmp     ax, cx
        jne     ferr
        mov     ah, 3Eh
        int     21h
        jc      ferr
        ; report
        mov     dx, s_r1
        call    print
        mov     ax, [used]
        call    pnum
        mov     dx, s_r2
        call    print
        mov     ax, [nfil]
        call    pnum
        mov     dx, s_r3
        call    print
        mov     ax, [nlfn]
        call    pnum
        mov     dx, s_r4
        call    print
        mov     ax, [ndel]
        call    pnum
        mov     dx, s_r5
        call    print
        mov     ax, [used]              ; sectors up to the end marker
        shr     ax, 4
        inc     ax
        cmp     ax, [rootsecs]
        jbe     .rs
        mov     ax, [rootsecs]
.rs:    call    pnum
        mov     dx, s_r6
        call    print
        mov     ax, [rootsecs]
        call    pnum
        mov     dx, s_r7
        call    print
        mov     ax, [nsecs]
        call    pnum
        mov     dx, s_saved
        call    print
        jmp     done

dskerr: mov     dx, s_dsk
        jmp     short fail
notfat: mov     dx, s_nofat
        jmp     short fail
ferr:   mov     dx, s_ferr
fail:   call    print
done:   mov     dx, s_key
        call    print
        mov     ah, 8
        int     21h
        mov     dx, s_crlf
        call    print
        mov     ax, 4C00h
        int     21h

; read sector AX of floppy unit 0 into [sbuf], 3 tries.  CF on error
rdsec:  push    bx
        push    cx
        push    dx
        xor     dx, dx
        div     word [spt]
        inc     dl
        mov     cl, dl                  ; sector
        xor     dx, dx
        div     word [heads]
        mov     dh, dl                  ; head
        mov     ch, al                  ; cylinder
        mov     byte [tries], 3
.t:     push    cx
        push    dx
        mov     bx, [sbuf]
        push    cs
        pop     es
        mov     dl, 0
        mov     ax, 0201h
        int     13h
        pop     dx
        pop     cx
        jnc     .x
        xor     ax, ax                  ; reset, try again
        push    dx
        mov     dl, 0
        int     13h
        pop     dx
        dec     byte [tries]
        jnz     .t
        stc
.x:     pop     dx
        pop     cx
        pop     bx
        ret

print:  mov     ah, 9
        int     21h
        ret
putc:   push    ax
        mov     ah, 2
        int     21h
        pop     ax
        ret
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
.p:     pop     dx
        add     dl, '0'
        call    putc
        loop    .p
        pop     dx
        pop     cx
        pop     bx
        ret

s_title db 'DISKMAP 1.0 - the floppy', 39, 's boot sector, FATs and root directory', 13, 10, '$'
s_file  db 'DISKMAP.BIN', 0
s_r1    db 'Root directory: $'
s_r2    db ' entries before the end marker', 13, 10, '  $'
s_r3    db ' files and subjects, $'
s_r4    db ' long-name parts, $'
s_r5    db ' deleted', 13, 10, '  a search reads $'
s_r6    db ' of its $'
s_r7    db ' sectors', 13, 10, 'Saved $'
s_saved db ' sectors to DISKMAP.BIN', 13, 10, '$'
s_dsk   db 'Cannot read the floppy (drive unit 0)', 13, 10, '$'
s_nofat db 'Not a FAT floppy this program knows', 13, 10, '$'
s_ferr  db 'Cannot write DISKMAP.BIN', 13, 10, '$'
s_key   db 'Press any key$'
s_crlf  db 13, 10, '$'

        alignb  2
section .bss
sbuf    resw 1
spt     resw 1
heads   resw 1
nroot   resw 1
rootlba resw 1
rootsecs resw 1
nsecs   resw 1
lba     resw 1
used    resw 1
ndel    resw 1
nlfn    resw 1
nfil    resw 1
tries   resb 1
        alignb 16
sb1     resb 512
sb2     resb 512
area    resb 512 * MAXSEC
        resb 512
stack_top:
