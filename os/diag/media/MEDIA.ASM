; MEDIA.COM - does the 1520's floppy drive tell the computer which kind of
; disk is in it?  A probe for FORMAT: a 720 KB disk has no density hole, a
; 1.44 MB one has; if anything the computer can read changes with the
; hole, FORMAT can choose the size by itself.
;
;   MEDIA [A: | B:]
;
; Once: the drive's type (INT 13h 08h's BL) and CMOS 10h (the drive types
; the setup keeps).  Then for each disk put in, a key after it:
;
;   - ports 3F0h-3F7h with the drive as it is (3F5h, the controller's
;     data register, not read: that would take a byte from it);
;   - the boot sector read through the BIOS (INT 13h 02h, up to three
;     tries): its status, and the BIOS's media state for the drive
;     (40:90h or 40:91h: the data rate it settled on, bits 7-6);
;   - the ports again at once, while the read leaves the drive selected
;     and its motor running (a drive gives a density signal, if any, only
;     when selected);
;   - the controller's Sense Drive Status (command 04h): ST3, the drive's
;     own lines (fault, write protect, ready, track 0, two-sided);
;   - INT 13h 20h, the PS/2 BIOS's media type (where a drive senses it):
;     CF and AX as the BIOS gives them.  Last, as a BIOS that doesn't know
;     the call is least likely to answer it well.
;
; Nothing is written to the disk and the controller is given no command
; but 04h (which moves nothing and raises no interrupt); a time-out there
; resets the controller through the BIOS.  At the end, INT 21h 0Dh, so
; the kernel looks at the drive afresh (the BIOS's read takes the drive's
; change line).  Runs under Lodestone (as the only task) or GRiD MS-DOS.
cpu 286
org 100h

TRIES   equ 3
SPIN    equ 0FFFFh                      ; MSR polls before a time-out

start:  cld
        mov     si, 81h                 ; the drive: A: unless B: named
.sk:    lodsb
        cmp     al, ' '
        je      .sk
        cmp     al, 9
        je      .sk
        and     al, 0DFh
        cmp     al, 'B'
        jne     .a
        mov     byte [unit], 1
.a:     mov     al, [unit]
        add     al, 'A'
        mov     [s_drv+6], al
        mov     dx, s_title
        call    print
        mov     dx, s_drv
        call    print

        mov     ax, cs                  ; a sector's buffer that doesn't
        shl     ax, 4                   ;  cross a 64 KB DMA boundary
        add     ax, buf1
        mov     word [buf], buf1
        cmp     ax, 10000h - 512
        jbe     .b
        mov     word [buf], buf1 + 512
.b:
        mov     dx, s_type              ; INT 13h 08h: the drive's type
        call    print
        mov     dl, [unit]
        mov     ah, 08h
        push    es
        int     13h
        pop     es
        jnc     .t
        mov     dx, s_fail
        call    print
        mov     al, ah
        call    hex2
        jmp     short .cm
.t:     mov     al, bl
        call    hex2
        mov     dx, s_types
        call    print
.cm:    mov     dx, s_cmos              ; CMOS 10h
        call    print
        cli
        mov     al, 10h
        out     70h, al
        jmp     short $+2
        in      al, 71h
        sti
        call    hex2
        mov     dx, s_crlf
        call    print

next:   mov     dx, s_insert
        call    print
        mov     ah, 08h                 ; a key (Esc ends it)
        int     21h
        cmp     al, 27
        je      done
        cmp     al, 3
        je      done
        inc     byte [disk]
        mov     dx, s_disk
        call    print
        mov     al, [disk]
        call    dec2
        mov     dx, s_crlf
        call    print

        mov     dx, s_before
        call    print
        call    ports

        mov     dx, s_read              ; the boot sector, through the BIOS
        call    print
        mov     bp, TRIES
.r:     push    es
        push    cs
        pop     es
        mov     bx, [buf]
        mov     ax, 0201h
        mov     cx, 0001h
        xor     dh, dh
        mov     dl, [unit]
        int     13h
        pop     es
        jnc     .rok
        dec     bp
        jz      .rok
        push    ax
        mov     dl, [unit]
        xor     ah, ah
        int     13h
        pop     ax
        jmp     .r
.rok:   pushf                           ; (the ports first, while the
        push    ax                      ;  drive is selected)
        mov     dx, s_after
        call    print
        call    ports
        call    sense
        pop     ax
        popf
        mov     dx, s_rdst
        call    print
        mov     al, ah
        call    hex2
        mov     dx, s_rdok
        or      ah, ah
        jz      .rp
        mov     dx, s_rdbad
.rp:    call    print
        mov     dx, s_mstate            ; "40:90h = 97h (250 kbps ...)"
        call    print
        mov     dl, [unit]
        add     dl, '0'
        mov     ah, 2
        int     21h
        mov     dx, s_eq
        call    print
        push    ds
        xor     bx, bx
        mov     ds, bx
        mov     bl, [cs:unit]
        mov     al, [90h+bx+400h]
        pop     ds
        call    hex2
        mov     dx, s_h
        call    print
        mov     dx, s_noest             ; bit 4: the media established
        test    al, 10h
        jz      .ms
        shr     al, 6
        xor     ah, ah
        mov     bx, ax
        shl     bx, 1
        mov     dx, [rates+bx]
.ms:    call    print
        mov     dx, s_crlf
        call    print

        mov     dx, s_st3               ; ST3
        call    print
        cmp     byte [st3ok], 0
        jne     .s
        mov     dx, s_noans
        call    print
        jmp     short .s2
.s:     mov     al, [st3v]
        call    hex2
        mov     dx, s_h
        call    print
        call    st3bits
.s2:    mov     dx, s_crlf
        call    print

.i20:   mov     dx, s_i20               ; INT 13h 20h
        call    print
        mov     dl, [unit]
        mov     ax, 2000h
        push    es
        int     13h
        pop     es
        mov     dx, s_cf0
        jnc     .c
        mov     dx, s_cf1
.c:     push    ax
        call    print
        pop     ax
        push    ax
        mov     al, ah
        call    hex2
        pop     ax
        call    hex2
        mov     dx, s_h
        call    print
        mov     dx, s_crlf
        call    print
        jmp     next

done:   mov     dx, s_crlf
        call    print
        mov     ah, 0Dh                 ; the kernel: the drive afresh
        int     21h
        mov     ax, 4C00h
        int     21h

; "3F0-3F7: xx xx xx xx xx -- xx xx" (3F5h not read)
ports:  mov     dx, 3F0h
.p:     cmp     dx, 3F5h
        jne     .rd
        push    dx
        mov     dx, s_dash
        call    print
        pop     dx
        jmp     short .n
.rd:    in      al, dx
        call    hex2
        push    dx
        mov     dx, s_sp
        call    print
        pop     dx
.n:     inc     dx
        cmp     dx, 3F8h
        jb      .p
        mov     dx, s_crlf
        jmp     print

; the controller's Sense Drive Status for the drive (head 0) -> [st3v],
; [st3ok] 1; a time-out: the controller reset through the BIOS
sense:  mov     byte [st3ok], 0
        mov     ah, 80h                 ; RQM, DIO 0: it takes a byte
        call    msr
        jc      .to
        mov     al, 04h
        out     dx, al
        mov     ah, 80h
        call    msr
        jc      .to
        mov     al, [unit]
        out     dx, al
        mov     ah, 0C0h                ; RQM, DIO 1: a byte for us
        call    msr
        jc      .to
        in      al, dx
        mov     [st3v], al
        mov     byte [st3ok], 1
        ret
.to:    mov     dl, [unit]
        xor     ah, ah
        int     13h
        ret

; wait for the main status register's RQM and DIO to be AH; DX = 3F5h.
; CF: a time-out
msr:    mov     cx, SPIN
        mov     dx, 3F4h
.w:     in      al, dx
        and     al, 0C0h
        cmp     al, ah
        je      .y
        loop    .w
        stc
        ret
.y:     inc     dx
        clc
        ret

; ST3's set bits by name: "fault write-protect ready track-0 two-sided"
st3bits:
        mov     bl, [st3v]
        mov     si, st3tab
.b:     lodsb
        or      al, al
        jz      .x
        mov     ah, al
        lodsw
        test    bl, ah
        jz      .b
        mov     dx, ax
        call    print
        jmp     .b
.x:     ret

; AL as two hex digits
hex2:   push    ax
        push    dx
        push    ax
        shr     al, 4
        call    .d
        pop     ax
        call    .d
        pop     dx
        pop     ax
        ret
.d:     and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        int     21h
        ret

; AL (0-99) in decimal
dec2:   xor     ah, ah
        mov     bl, 10
        div     bl
        push    ax
        or      al, al
        jz      .u
        add     al, '0'
        mov     dl, al
        mov     ah, 2
        int     21h
.u:     pop     ax
        mov     dl, ah
        add     dl, '0'
        mov     ah, 2
        int     21h
        ret

print:  push    ax
        mov     ah, 9
        int     21h
        pop     ax
        ret

unit    db 0
disk    db 0
st3ok   db 0
st3v    db 0
buf     dw 0
rates   dw r_500, r_300, r_250, r_1m
st3tab  db 80h
        dw n_fault
        db 40h
        dw n_wp
        db 20h
        dw n_rdy
        db 10h
        dw n_t0
        db 08h
        dw n_ts
        db 0
n_fault db ' fault$'
n_wp    db ' write-protect$'
n_rdy   db ' ready$'
n_t0    db ' track-0$'
n_ts    db ' two-sided$'
r_500   db '(500 kbps: 1.44M)$'
r_300   db '(300 kbps)$'
r_250   db '(250 kbps: 720K)$'
r_1m    db '(1 Mbps)$'
s_noest db '(not established)$'
s_title db 'MEDIA: what the floppy drive says of the disk in it', 13, 10, '$'
s_drv   db 'Drive A:', 13, 10, '$'
s_type  db 'INT 13h 08h type: $'
s_types db ' (1 360K, 2 1.2M, 3 720K, 4 1.44M)$'
s_fail  db 'failed, AH=$'
s_cmos  db '   CMOS 10h: $'
s_insert db 13, 10, 'Put a disk in and press a key (Esc: done) $'
s_disk  db 13, 10, 'Disk $'
s_before db '  idle      3F0-3F7: $'
s_after db '  selected  3F0-3F7: $'
s_read  db '  reading the boot sector...', 13, 10, '$'
s_rdst  db '  boot sector: AH=$'
s_rdok  db 'h read$'
s_rdbad db 'h not read$'
s_mstate db ', BIOS media state 40:9$'
s_st3   db '  ST3 (Sense Drive Status): $'
s_noans db 'no answer (controller reset)$'
s_i20   db '  INT 13h 20h: $'
s_cf0   db 'CF=0 AX=$'
s_cf1   db 'CF=1 AX=$'
s_h     db 'h $'
s_eq    db 'h = $'
s_dash  db '-- $'
s_sp    db ' $'
s_crlf  db 13, 10, '$'

        alignb 2
buf1:                                   ; (1 KB: a sector that doesn't
                                        ;  cross 64 KB, in one half)
