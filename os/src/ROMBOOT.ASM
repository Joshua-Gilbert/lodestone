; =====================================================================
;  Lodestone ROM boot sector  (ROMBOOT.ASM)            nasm -f bin
;
;  The first sector of Lodestone's ROM image (tools/mkrom.py puts it there
;  and writes the volume's BPB over 0Bh-3Dh).  The 1520's BIOS copies the
;  whole 128 KB image to 8000:0000 and jumps here (8000:0000, DL = 'r',
;  interrupts on).  This finds LODE.SYS in the volume's root, copies it
;  from that RAM copy to 1000:0000 (mkrom.py keeps files contiguous) and
;  starts it as the floppy boot sector does: DL = the boot drive, here
;  R: (17), DS:SI -> this boot sector.
; =====================================================================
cpu 286
org 0
R_DRV   equ 17
ROOT    equ 2 * 512                 ; mkrom.py's layout: the root,
NROOT   equ 32                      ;  32 entries;
DATA    equ 4                       ;  cluster 2 at sector 4
KSEG    equ 1000h                   ; where the kernel is started (BOOT.ASM's)

        jmp     short start
        nop
        db      'LODE ROM'
        times   3Eh - ($ - $$) db 0 ; (the BPB, mkrom.py's)

start:  cli
        xor     ax, ax
        mov     ss, ax
        mov     sp, 7C00h
        sti
        cld
        push    cs
        pop     ds
        push    cs
        pop     es
        mov     si, ROOT
        mov     dx, NROOT
.find:  push    si
        mov     di, kname
        mov     cx, 11
        repe    cmpsb
        pop     si
        je      .found
        add     si, 32
        dec     dx
        jnz     .find
.fail:  mov     si, m_fail
.p:     lodsb
        or      al, al
        jz      .h
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     .p
.h:     hlt
        jmp     .h
.found: cmp     word [si+30], 0     ; (under 64 KB)
        jne     .fail
        mov     cx, [si+28]
        jcxz    .fail
        mov     ax, [si+26]         ; its first cluster -> its paragraph
        add     ax, DATA - 2        ;  in the RAM copy
        shl     ax, 5
        mov     bx, cs
        add     ax, bx
        mov     ds, ax
        mov     ax, KSEG
        mov     es, ax
        xor     si, si
        xor     di, di
        inc     cx
        shr     cx, 1
        rep     movsw
        push    cs                  ; DS:SI -> this boot sector's BPB
        pop     ds
        xor     si, si
        mov     dl, R_DRV
        jmp     KSEG:0000h

kname   db      'LODE    SYS'
m_fail  db      'Lodestone ROM: no LODE.SYS', 13, 10, 0
        times   510 - ($ - $$) db 0
        dw      0AA55h
