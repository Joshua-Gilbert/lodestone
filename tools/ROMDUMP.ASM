; =====================================================================
;  ROMDUMP.COM - dump GRiDCase 1520 BIOS ROM, low memory and CMOS to A:
;  Build: nasm -f bin -o ROMDUMP.COM ROMDUMP.ASM
;  Writes: A:\ROM_F000.BIN  (64 KB, F000:0000-FFFF system BIOS)
;          A:\ROM_E000.BIN  (64 KB, E000:0000-FFFF, in case ROM is 128 KB)
;          A:\LOWMEM.BIN    (1.5 KB, interrupt vectors + BIOS data area)
;          A:\CMOS128.BIN   (128 bytes, CMOS indexes 00-7F)
;  Read-only: touches nothing but the files it writes.
; =====================================================================
cpu 286
org 100h

start:  mov     dx, s_title
        call    puts

        mov     dx, f_f000
        mov     ax, 0F000h
        call    dump64k
        mov     dx, f_e000
        mov     ax, 0E000h
        call    dump64k

        ; low memory 0000:0000-05FF
        mov     dx, f_low
        call    create
        jc      fail
        mov     bx, [fh]
        push    ds
        xor     ax, ax
        mov     ds, ax
        xor     dx, dx
        mov     cx, 600h
        mov     ah, 40h
        int     21h
        pop     ds
        jc      fail
        call    close

        ; CMOS 00-7F
        xor     bx, bx
.cm:    mov     al, bl
        cli
        out     70h, al
        jmp     short $+2
        in      al, 71h
        sti
        mov     [cmos+bx], al
        inc     bx
        cmp     bx, 128
        jb      .cm
        mov     dx, f_cmos
        call    create
        jc      fail
        mov     bx, [fh]
        mov     dx, cmos
        mov     cx, 128
        mov     ah, 40h
        int     21h
        jc      fail
        call    close

        mov     dx, s_ok
        call    puts
        mov     ax, 4C00h
        int     21h

fail:   mov     dx, s_fail
        call    puts
        mov     ax, 4C01h
        int     21h

; DX = filename, AX = segment.  The 1520's DMA controller cannot read
; ROM (floppy writes DMA straight from the buffer and get FFh), so each
; 4 KB chunk is first copied into RAM by the CPU, then written from there.
dump64k:
        push    ax
        call    create
        pop     ax
        jc      fail
        mov     [srcseg], ax
        xor     si, si              ; source offset
.chunk: push    si
        push    ds
        mov     ds, [cs:srcseg]
        mov     di, buf             ; ES = CS (COM program)
        mov     cx, 800h            ; 2048 words = 4 KB
        rep     movsw
        pop     ds
        mov     bx, [fh]
        mov     dx, buf
        mov     cx, 1000h
        mov     ah, 40h
        int     21h
        pop     si
        jc      fail
        cmp     ax, 1000h
        jne     fail
        add     si, 1000h
        jnz     .chunk              ; wraps to 0 after 16 chunks
        call    close
        ret

create: push    dx
        call    puts0
        pop     dx
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .r
        mov     [fh], ax
.r:     ret

close:  mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        ret

; print ASCIIZ filename at DX followed by CRLF
puts0:  mov     si, dx
.l:     lodsb
        or      al, al
        jz      .e
        mov     dl, al
        mov     ah, 02h
        int     21h
        jmp     .l
.e:     mov     dx, s_crlf
puts:   mov     ah, 09h
        int     21h
        ret

s_title db 'ROMDUMP 1.2 - GRiDCase ROM/CMOS dump (Grid-OS)',13,10,'$'
s_ok    db 'Done. 4 files written to A:\',13,10,'$'
s_fail  db '** Write failed - disk full or write-protected?',13,10,'$'
s_crlf  db 13,10,'$'
f_f000  db 'A:\ROM_F000.BIN',0
f_e000  db 'A:\ROM_E000.BIN',0
f_low   db 'A:\LOWMEM.BIN',0
f_cmos  db 'A:\CMOS128.BIN',0
fh      dw 0
srcseg  dw 0
cmos    times 128 db 0
buf     times 1000h db 0
