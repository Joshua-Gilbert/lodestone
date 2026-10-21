; =====================================================================
;  LODEBOOT.COM 1.0 - make a floppy boot Lodestone              (Lodestone)
;  nasm -f bin -o LODEBOOT.COM LODEBOOT.ASM        (needs BOOT.BIN)
;  Run under DOS on the Grid:  LODEBOOT        (drive A:)
;                              LODEBOOT B      (drive B:)
;  Reads the disk's boot sector, keeps its BPB (so the FAT file system
;  and every file on the disk stay as they are), replaces the boot
;  code with the Lodestone loader, writes it back and verifies it.
;  The loader then boots \LODE.SYS from that disk.  Only sector 0
;  is written.  Needs a standard FAT12 floppy (720 KB or 1.44 MB).
; =====================================================================
cpu 286
org 100h

start:  cld
        mov     dx, s_title
        call    print
        mov     byte [drv], 0
        mov     si, 81h                 ; optional drive letter
        mov     cl, [80h]
        xor     ch, ch
.arg:   jcxz    .argd
        lodsb
        dec     cx
        or      al, 20h
        cmp     al, 'b'
        jne     .arg
        mov     byte [drv], 1
.argd:  mov     al, [drv]
        add     al, 'A'
        mov     [s_drive], al
        mov     [s_askd], al
        ; ---- read sector 0 ----
        mov     bx, old
        call    rd0
        jnc     .rok
        mov     dx, s_rderr
        jmp     quit
.rok:   ; ---- sanity-check the BPB ----
        mov     dx, s_badbpb
        cmp     word [old+510], 0AA55h
        jne     quit
        cmp     word [old+0Bh], 512
        jne     quit
        mov     al, [old+0Dh]           ; sectors per cluster 1 or 2
        cmp     al, 1
        jb      quit
        cmp     al, 2
        ja      quit
        mov     al, [old+10h]           ; FATs 1 or 2
        cmp     al, 1
        jb      quit
        cmp     al, 2
        ja      quit
        mov     ax, [old+18h]           ; sectors per track 8..36
        cmp     ax, 8
        jb      quit
        cmp     ax, 36
        ja      quit
        cmp     word [old+1Ah], 2       ; two heads
        jne     quit
        mov     ax, [old+13h]           ; 640..5760 sectors (FAT12)
        cmp     ax, 640
        jb      quit
        cmp     ax, 5760
        ja      quit
        ; ---- show what we found and ask ----
        mov     dx, s_found
        call    print
        mov     ax, [old+13h]
        shr     ax, 1
        call    pdec
        mov     dx, s_kb
        call    print
        cmp     word [old+3], 'LO'
        jne     .ask
        cmp     word [old+5], 'DE'
        jne     .ask
        cmp     byte [old+7], 'S'
        jne     .ask
        mov     dx, s_already
        call    print
.ask:   mov     dx, s_ask
        call    print
        xor     ah, ah
        int     16h
        or      al, 20h
        cmp     al, 'y'
        je      .go
        mov     dx, s_cancel
        jmp     quit
.go:    mov     dx, s_yes
        call    print
        ; ---- build: our code + the disk's BPB (bytes 0Bh..3Dh) ----
        mov     si, bootbin
        mov     di, new
        mov     cx, 512
        rep     movsb
        mov     si, old + 0Bh
        mov     di, new + 0Bh
        mov     cx, 3Eh - 0Bh
        rep     movsb
        mov     al, [drv]
        mov     [new+24h], al           ; BPB drive number
        ; ---- write, then read back and compare ----
        mov     cx, 4
.wr:    push    cx
        mov     ax, 0301h
        mov     bx, new
        mov     cx, 0001h
        xor     dh, dh
        mov     dl, [drv]
        int     13h
        pop     cx
        jnc     .wok
        xor     ah, ah
        mov     dl, [drv]
        int     13h
        loop    .wr
        mov     dx, s_wrerr
        jmp     quit
.wok:   mov     bx, chk
        call    rd0
        mov     dx, s_vferr
        jc      quit
        mov     si, new
        mov     di, chk
        mov     cx, 512
        repe    cmpsb
        jne     quit
        mov     dx, s_ok
quit:   call    print
        mov     ax, 4C00h
        int     21h

rd0:    mov     cx, 4                   ; read sector 0 to BX, CF on error
.r:     push    cx
        push    bx
        mov     ax, 0201h
        mov     cx, 0001h
        xor     dh, dh
        mov     dl, [drv]
        int     13h
        pop     bx
        pop     cx
        jnc     .x
        push    bx
        xor     ah, ah
        mov     dl, [drv]
        int     13h
        pop     bx
        loop    .r
        stc
.x:     ret

print:  mov     ah, 9
        int     21h
        ret

pdec:   xor     cx, cx
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     dx
        add     dl, '0'
        mov     ah, 2
        int     21h
        loop    .p
        ret

s_title db 'LODEBOOT 1.0 - make a Lodestone boot floppy',13,10,'$'
s_found db 'Drive '
s_drive db 'A: FAT12 floppy, $'
s_kb    db ' KB.',13,10,'$'
s_already db 'It already has the Lodestone loader (this rewrites it).',13,10,'$'
s_ask   db 'Write the Lodestone boot sector to drive '
s_askd  db 'A:?  Files are kept. (Y/N) $'
s_yes   db 'Y',13,10,'$'
s_cancel db 'N',13,10,'Nothing written.',13,10,'$'
s_rderr db 'Cannot read the boot sector - is a formatted disk in the drive?',13,10,'$'
s_badbpb db 'Not a standard FAT12 floppy (720K/1.44M) - nothing written.',13,10,'$'
s_wrerr db 'Write failed - is the disk write-protected?',13,10,'$'
s_vferr db 'Verify FAILED - the boot sector did not read back correctly!',13,10,'$'
s_ok    db 'Done. Put LODE.SYS on this disk and boot it (tap F during start-up',13,10
        db 'so the BIOS boots the floppy instead of the EPROM).',13,10,'$'
drv     db 0
bootbin incbin 'BOOT.BIN'
old     times 512 db 0
new     times 512 db 0
chk     times 512 db 0
