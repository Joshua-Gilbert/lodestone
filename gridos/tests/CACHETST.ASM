; CACHETST.COM - stress test for the disk cache (and any DOS's file I/O).
; Builds two files written in turns (so their clusters interleave), then
; does random reads, read runs, and writes of 128-byte granules across
; both, checking every byte read against what was written: the content of
; each byte is a function of its file, position and the "version" of its
; 128-byte granule, which every write bumps.  Closes and reopens now and
; then, checks both files whole at the end and deletes them.
; Reads go to a buffer across a 64 KB boundary (DMA can't cross one: the
; disk cache reads such a piece itself), so that way is tested too.
; With EMS it holds 4 pages of its own in the 4 windows of the frame,
; filled with a pattern, all along: every other random read and write
; goes through the frame (at a random place), and every 16 ops the frame
; must still show our pages and the pattern - the cache may use the frame
; too (Grid-OS keeps it in EMS), but must give it back as it was.  Its
; INT 24h handler retries a disk error 3 times, and checks the frame too.
; Output: "CACHETST: n ops, e errors"; exit code = errors (max 255).
; What it prints is also added to CACHETST.TXT, then it waits for a key.
cpu 286
org 100h

NOPS    equ 240
GRAN    equ 128
MAXG    equ 2048                ; granules per file (256 KB)
RBUF    equ 16384
WBUF    equ 8192
LOGMAX  equ 2048
FRAME   equ 0E000h

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, stack_top - bss_start
        xor     al, al
        rep     stosb
        mov     bx, 1000h
        mov     ah, 4Ah
        int     21h
        mov     [rseg], ds
        mov     word [roff], rbuf
        mov     bx, 1400h               ; 80 KB: the read buffer 8 KB before
        mov     ah, 48h                 ;  the 64 KB boundary in it
        int     21h
        jc      .nob
        add     ax, 200h + 0FFFh
        and     ax, 0F000h
        sub     ax, 200h
        mov     [rseg], ax
        mov     word [roff], 0
.nob:   mov     dx, crit24
        mov     ax, 2524h
        int     21h
        mov     word [seed], 4321
        mov     si, s_hello
        call    pr
        call    is_gridos
        mov     si, s_msdos
        jne     .os
        mov     si, s_gridos
.os:    call    pr
        call    pdate
        call    ems_open
        ; --- build: A 4 KB and B 2 KB at a time, 40 times
        mov     bl, 0
        call    fcreate
        mov     bl, 1
        call    fcreate
        mov     byte [nver], 1
        mov     cx, 40
.b:     push    cx
        mov     bl, 0
        call    fend
        mov     cx, 4096 / GRAN
        call    wgran
        mov     bl, 1
        call    fend
        mov     cx, 2048 / GRAN
        call    wgran
        pop     cx
        loop    .b
        ; --- random operations
        mov     si, s_built
        call    pr
        mov     word [opno], 0
.op:    inc     word [opno]
        mov     byte [r24], 0
        test    byte [opno], 15
        jnz     .nd
        mov     al, '.'
        call    pch
        call    fcheck
.nd:
        mov     cx, 2
        call    rand
        mov     bl, al                  ; the file
        mov     cx, 10
        call    rand
        cmp     al, 4
        jb      .rd
        cmp     al, 6
        jb      .run
        cmp     al, 8
        jb      .wr
        cmp     al, 9
        jb      .rw
        call    reopen
        jmp     .nx
.rw:    call    op_rw
        jmp     .nx
.rd:    call    op_read
        jmp     .nx
.run:   call    op_run
        jmp     .nx
.wr:    call    op_write
.nx:    cmp     word [nerr], 20
        jae     .end
        cmp     word [opno], NOPS
        jb      .op
        ; --- both files whole, three ways, after a reopen
        call    reopen
        mov     word [rsz], 512
        call    whole
        mov     word [rsz], 3000
        call    whole
        mov     word [rsz], RBUF
        call    whole
.end:   mov     bl, 0
        call    fclose
        mov     bl, 1
        call    fclose
        mov     dx, f_a
        mov     ah, 41h
        int     21h
        mov     dx, f_b
        mov     ah, 41h
        int     21h
        call    ems_close
        mov     si, s_res
        call    pr
        mov     ax, [opno]
        call    pdec
        mov     si, s_ops
        call    pr
        mov     ax, [nerr]
        call    pdec
        mov     si, s_errs
        call    pr
        mov     si, s_crlf
        call    pr
        call    savelog
        mov     si, s_key
        call    pr
        mov     ah, 8                   ; wait for a key
        int     21h
        mov     al, [nerr]
        mov     ah, 4Ch
        int     21h

; Grid-OS?  (its COMSPEC is GRIDCMD.COM) -> ZF
is_gridos:
        push    ds
        push    si
        mov     ds, [2Ch]
        xor     si, si
.var:   cmp     byte [si], 0
        je      .no
        cmp     word [si], 'CO'
        jne     .skip
        cmp     word [si+2], 'MS'
        jne     .skip
        cmp     word [si+4], 'PE'
        jne     .skip
.find:  lodsb
        or      al, al
        jz      .no
        cmp     al, 'G'
        jne     .find
        cmp     word [si], 'RI'
        jne     .find
        cmp     word [si+2], 'DC'
        jne     .find
        cmp     word [si+4], 'MD'
        jne     .find
        pop     si
        pop     ds
        cmp     al, al
        ret
.skip:  lodsb
        or      al, al
        jnz     .skip
        cmp     si, 7F00h
        jb      .var
.no:    pop     si
        pop     ds
        or      sp, sp
        ret

; "run 2026-10-05 11:20", CR LF
pdate:  mov     si, s_date
        call    pr
        mov     ah, 2Ah
        int     21h
        push    dx
        mov     ax, cx
        call    pdec
        mov     al, '-'
        call    pch
        pop     dx
        push    dx
        mov     al, dh
        call    p2
        mov     al, '-'
        call    pch
        pop     dx
        mov     al, dl
        call    p2
        mov     al, ' '
        call    pch
        mov     ah, 2Ch
        int     21h
        push    cx
        mov     al, ch
        call    p2
        mov     al, ':'
        call    pch
        pop     cx
        mov     al, cl
        call    p2
        mov     si, s_crlf
        jmp     pr
p2:     xor     ah, ah                  ; AL as 2 digits
        cmp     al, 10
        jae     .n
        push    ax
        mov     al, '0'
        call    pch
        pop     ax
.n:     jmp     pdec

; add what was printed to CACHETST.TXT
savelog:
        mov     dx, s_log
        mov     ax, 3D01h
        int     21h
        jc      .new
        mov     bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        jmp     .w
.new:   mov     dx, s_log
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .fail
        mov     bx, ax
.w:     mov     dx, logbuf
        mov     cx, [logpos]
        mov     ah, 40h
        int     21h
        jc      .fc
        cmp     ax, cx
        jne     .fc
        mov     ah, 3Eh
        int     21h
        jc      .fail
        mov     si, s_saved
        jmp     pr
.fc:    mov     ah, 3Eh
        int     21h
.fail:  mov     si, s_nosave
        jmp     pr

; ---------------------------------------------------------------------
;  EMS: 4 pages of ours in the frame's 4 windows all along.  Frame byte f
;  (0-FFFFh) holds f + 7 * (f >> 8) + 3Ch, so each window's page is told
;  apart from the others (and from anything else) by what it holds.
; ---------------------------------------------------------------------
ems_open:
        push    es
        mov     ax, 3567h               ; an EMS manager?  ('EMMXXXX0' at
        int     21h                     ;  its segment:000Ah)
        mov     di, 0Ah
        mov     si, s_emm
        mov     cx, 8
        repe    cmpsb
        pop     es
        jne     .x
        mov     ah, 43h
        mov     bx, 4
        int     67h
        or      ah, ah
        jnz     .x
        mov     [ems_h], dx
        xor     bx, bx
.m:     mov     ax, bx                  ; page n into window n
        mov     ah, 44h
        int     67h
        inc     bx
        cmp     bx, 4
        jb      .m
        call    fall                    ; the pattern in all of it
        mov     si, s_ems
        call    pr
.x:     ret

; the frame as it was, the pages given back; what went through it
ems_close:
        mov     dx, [ems_h]
        or      dx, dx
        jz      .x
        call    fcheck
        mov     ah, 45h
        int     67h
        mov     si, s_emsr
        call    pr
        mov     ax, [fr_r]
        call    pdec
        mov     si, s_emsw
        call    pr
        mov     ax, [fr_w]
        call    pdec
        mov     si, s_emsx
        call    pr
.x:     cmp     word [n24], 0           ; disk errors (INT 24h)
        je      .y
        mov     si, s_24
        call    pr
        mov     ax, [n24]
        call    pdec
        mov     si, s_crlf
        call    pr
.y:     cmp     byte [bad24], 0
        je      .z
        mov     bl, 'F' - 'A'
        mov     ax, 0FB00h              ; INT 24h found the frame changed
        jmp     error
.z:     ret

; every byte of the frame as we left it?  Else an error (and the pattern
; put back, so it is reported once)
fcheck: cmp     word [ems_h], 0
        je      .x
        push    es
        mov     ax, FRAME
        mov     es, ax
        xor     di, di
        mov     cx, 8000h
        call    pchk
        jne     .bad
        mov     cx, 8000h
        call    pchk
        jne     .bad
        pop     es
.x:     ret
.bad:   dec     di
        mov     ah, [es:di]
        mov     [pos], di
        mov     word [pos+2], FRAME
        pop     es
        mov     bl, 'F' - 'A'           ; ("file F at E000xxxx": the frame)
        call    error
fall:   push    es
        mov     ax, FRAME
        mov     es, ax
        xor     di, di
        mov     cx, 8000h
        call    pfill
        mov     cx, 8000h
        call    pfill
        pop     es
        ret

; AL = the pattern's byte at frame offset DI (AH changed)
pbyte:  mov     ax, di
        mov     al, ah
        mov     ah, 7
        mul     ah
        add     ax, di
        add     al, 3Ch
        ret
; ES:DI on, CX bytes (not 0): the pattern there / is it there (ZF)?
pfill:  call    pbyte
.l:     stosb
        inc     al
        test    di, 0FFh
        jnz     .n
        add     al, 7
.n:     loop    .l
        ret
pchk:   call    pbyte
.l:     scasb
        jne     .x
        inc     al
        test    di, 0FFh
        jnz     .n
        add     al, 7
.n:     loop    .l
        cmp     al, al
.x:     ret

; INT 24h: retry a disk error up to 3 times in a row, then fail.  With
; EMS the frame must show our pages while it runs (first and last byte
; of each window).
crit24: push    ds
        push    es
        push    cx
        push    di
        push    cs
        pop     ds
        inc     word [n24]
        cmp     word [ems_h], 0
        je      .r
        mov     ax, FRAME
        mov     es, ax
        xor     di, di
        mov     cx, 4
.w:     call    pbyte
        cmp     [es:di], al
        jne     .bad
        add     di, 3FFFh
        call    pbyte
        cmp     [es:di], al
        jne     .bad
        inc     di
        loop    .w
        jmp     short .r
.bad:   mov     byte [bad24], 1
.r:     inc     byte [r24]
        mov     al, 1                   ; retry
        cmp     byte [r24], 3
        jbe     .x
        mov     al, 3                   ; fail
.x:     pop     di
        pop     cx
        pop     es
        pop     ds
        iret

; ---------------------------------------------------------------------
; read a random piece (with EMS, every other one into the frame)
op_read:
        call    rpos
        jc      .x
        mov     cx, RBUF
        call    rand
        inc     ax
        call    clamp                   ; CX = length
        call    fseek
        jcxz    .c
        test    byte [opno], 1
        jz      .c
        cmp     word [ems_h], 0
        je      .c
        push    cx                      ; somewhere in the frame
        neg     cx
        call    rand
        pop     cx
        push    word [rseg]
        push    word [roff]
        mov     word [rseg], FRAME
        mov     [roff], ax
        push    ax
        push    cx
        call    rdchk
        pop     cx
        pop     di
        push    es                      ; our pattern back there
        mov     ax, FRAME
        mov     es, ax
        call    pfill
        pop     es
        pop     word [roff]
        pop     word [rseg]
        inc     word [fr_r]
        ret
.c:     call    rdchk
.x:     ret

; a run of reads in order from a random place
op_run: call    rpos
        jc      .x
        call    fseek
        mov     cx, 8
        call    rand
        add     al, 2
        mov     [runs], al
.l:     mov     cx, 4000
        call    rand
        inc     ax
        call    clamp
        jcxz    .x
        call    rdchk
        dec     byte [runs]
        jnz     .l
.x:     ret

; read 8 KB in order from a granule (the cache keeps it), rewrite a few
; granules in the middle, read it all again
op_rw:  call    rpos
        jc      .x
        and     word [pos], -GRAN
        mov     ax, [pos]
        mov     [rwp], ax
        mov     ax, [pos+2]
        mov     [rwp+2], ax
        call    fseek
        mov     ax, 8192
        call    clamp
        cmp     cx, 4 * GRAN
        jb      .x
        mov     [rwl], cx
        push    cx                      ; (a small read first: the next one
        mov     cx, GRAN                ;  then reads on from it, so the
        call    rdchk                   ;  disk reads ahead into its cache)
        pop     cx
        sub     cx, GRAN
        call    rdchk
        mov     ax, [rwp]               ; granules 1..3 of it
        add     ax, GRAN
        mov     [pos], ax
        mov     ax, [rwp+2]
        adc     ax, 0
        mov     [pos+2], ax
        call    fseek
        inc     byte [nver]
        jnz     .v
        inc     byte [nver]
.v:     mov     cx, 3
        call    wgran
        mov     ax, [rwp]
        mov     [pos], ax
        mov     ax, [rwp+2]
        mov     [pos+2], ax
        call    fseek
        mov     cx, [rwl]
        call    rdchk
.x:     ret

; write 1..64 granules from a random granule (up to the end: may grow)
op_write:
        call    fsize_g                 ; AX = granules now
        inc     ax
        mov     cx, ax
        call    rand
        mov     [g0], ax
        mov     cx, WBUF / GRAN
        call    rand
        inc     ax
        mov     cx, ax
        mov     ax, MAXG
        sub     ax, [g0]
        cmp     cx, ax
        jbe     .n
        mov     cx, ax
.n:     jcxz    .x
        mov     ax, [g0]
        call    gpos                    ; DX:AX = its position
        mov     [pos], ax
        mov     [pos+2], dx
        call    fseek
        inc     byte [nver]
        jnz     .v
        inc     byte [nver]             ; (0 is never a version)
.v:     test    byte [opno], 1          ; with EMS, every other one from
        jz      .w                      ;  somewhere in the frame
        cmp     word [ems_h], 0
        je      .w
        push    cx
        shl     cx, 7
        neg     cx
        call    rand
        mov     [wfo], ax
        mov     byte [wfr], 1
        pop     cx
.w:     call    wgran
.x:     ret

; whole file in reads of [rsz] bytes
whole:  mov     bl, 0
        call    .one
        mov     bl, 1
.one:   xor     ax, ax
        mov     [pos], ax
        mov     [pos+2], ax
        call    fseek
.l:     mov     ax, [rsz]
        call    clamp
        jcxz    .x
        push    bx
        call    rdchk
        pop     bx
        cmp     word [nerr], 20
        jb      .l
.x:     ret

; ---------------------------------------------------------------------
; read CX bytes of file BL at [pos] (the file is there) to [rseg]:[roff]
; and check them
rdchk:  mov     [rlen], cx
        push    bx
        call    hnd
        push    ds
        mov     dx, [roff]
        mov     ds, [rseg]
        mov     ah, 3Fh
        int     21h
        pop     ds
        pop     bx
        jc      .derr
        cmp     ax, [rlen]
        jne     .short
        push    es
        mov     es, [rseg]
        mov     si, [roff]
        mov     cx, [rlen]
        call    .g
        pop     es
        ret
.g:     jcxz    .x
        mov     ax, [pos]
        mov     dx, [pos+2]
        call    expect                  ; AL = first byte, DI = bytes in granule
        cmp     di, cx
        jbe     .c
        mov     di, cx
.c:     sub     cx, di
        add     [pos], di
        adc     word [pos+2], 0
.b:     cmp     [es:si], al
        jne     .bad
        inc     si
        inc     al
        dec     di
        jnz     .b
        jmp     .g
.x:     ret
.bad:   mov     ah, [es:si]
        sub     [pos], di               ; (the failing byte's position)
        sbb     word [pos+2], 0
        jmp     error
.derr:  mov     ah, 0FFh
        jmp     error
.short: mov     ah, 0FEh
        mov     al, 0
        jmp     error

; AH = got, AL = wanted, BL = file, [pos]: count and report (first 5)
error:  inc     word [nerr]
        cmp     word [nerr], 5
        ja      .x
        push    ax
        mov     si, s_err
        call    pr
        mov     ax, [opno]
        call    pdec
        mov     si, s_file
        call    pr
        mov     al, bl
        add     al, 'A'
        call    pch
        mov     si, s_at
        call    pr
        mov     ax, [pos+2]
        call    phex
        mov     ax, [pos]
        call    phex
        mov     si, s_want
        call    pr
        pop     ax
        push    ax
        xor     ah, ah
        call    phex
        mov     si, s_got
        call    pr
        pop     ax
        mov     al, ah
        xor     ah, ah
        call    phex
        mov     si, s_crlf
        call    pr
.x:     ret

; DX:AX = position in file BL -> AL = the byte that belongs there,
; DI = bytes from there to the end of its granule.  Keeps the rest.
; byte = pos + 3*(pos>>8) + 59*(pos>>16) + 37*version + 101*file (low 8)
expect: push    bx
        push    cx
        push    dx
        push    si
        mov     di, ax
        and     di, GRAN - 1
        neg     di
        add     di, GRAN
        mov     si, ax                  ; vtab[file * MAXG + pos / GRAN]
        shr     si, 7
        mov     cx, dx
        shl     cx, 9
        or      si, cx
        mov     cl, bl
        xor     ch, ch
        shl     cx, 11
        add     si, cx
        mov     cl, [vtab+si]
        mov     ch, al
        mov     al, ah
        mov     ah, 3
        mul     ah
        add     ch, al
        mov     al, dl
        mov     ah, 59
        mul     ah
        add     ch, al
        mov     al, cl
        mov     ah, 37
        mul     ah
        add     ch, al
        mov     al, bl
        mov     ah, 101
        mul     ah
        add     al, ch
        pop     si
        pop     dx
        pop     cx
        pop     bx
        ret

; write CX granules at [pos] of file BL as version [nver]: mark them,
; fill the buffer, write; [pos] moves past them
wgran:  push    cx
        mov     ax, [pos]
        mov     dx, [pos+2]
        call    granof
        mov     si, ax
        mov     al, bl
        xor     ah, ah
        shl     ax, 11
        add     si, ax
        mov     al, [nver]
.m:     mov     [vtab+si], al
        inc     si
        loop    .m
        pop     cx
        shl     cx, 7                   ; bytes
        mov     [wlen], cx
        mov     di, wbuf
        mov     ax, [pos]
        mov     dx, [pos+2]
.f:     push    ax
        push    dx
        push    cx
        push    di
        call    expect
        pop     di
        mov     cx, GRAN
.fb:    stosb
        inc     al
        loop    .fb
        pop     cx
        pop     dx
        pop     ax
        add     ax, GRAN
        adc     dx, 0
        sub     cx, GRAN
        jnz     .f
        push    bx
        call    hnd
        mov     dx, wbuf
        mov     cx, [wlen]
        push    ds
        cmp     byte [wfr], 0
        je      .wr
        push    es                      ; from the frame: there first
        push    di
        mov     ax, FRAME
        mov     es, ax
        mov     di, [wfo]
        mov     si, dx
        rep     movsb
        pop     di
        pop     es
        mov     cx, [wlen]
        mov     dx, [wfo]
        mov     ds, ax
.wr:    mov     ah, 40h
        int     21h
        pop     ds
        pop     bx
        pushf
        push    ax
        cmp     byte [wfr], 0           ; our pattern back there
        je      .np
        mov     byte [wfr], 0
        inc     word [fr_w]
        push    es
        mov     ax, FRAME
        mov     es, ax
        mov     di, [wfo]
        mov     cx, [wlen]
        call    pfill
        pop     es
.np:    pop     ax
        popf
        jc      .e
        cmp     ax, [wlen]
        jne     .e
        mov     ax, [wlen]              ; the file may have grown
        add     ax, [pos]
        mov     dx, [pos+2]
        adc     dx, 0
        mov     [pos], ax
        mov     [pos+2], dx
        call    szp
        cmp     dx, [si+2]
        jb      .x
        ja      .gr
        cmp     ax, [si]
        jbe     .x
.gr:    mov     [si], ax
        mov     [si+2], dx
.x:     ret
.e:     mov     ah, 0FDh
        mov     al, 0
        jmp     error

; ---------------------------------------------------------------------
; random position in file BL -> [pos] (CF if the file is empty)
rpos:   call    fsize_g
        or      ax, ax
        jz      .no
        mov     cx, ax
        call    rand
        push    ax
        mov     cx, GRAN
        call    rand
        mov     cx, ax
        pop     ax
        call    gpos
        add     ax, cx
        adc     dx, 0
        mov     [pos], ax
        mov     [pos+2], dx
        clc
        ret
.no:    stc
        ret
; AX wanted -> CX = AX, or less so as not to pass the end of file BL
clamp:  push    ax
        call    szp
        mov     ax, [si]
        mov     dx, [si+2]
        sub     ax, [pos]
        sbb     dx, [pos+2]
        pop     cx
        or      dx, dx
        jnz     .x
        cmp     cx, ax
        jbe     .x
        mov     cx, ax
.x:     ret
; file BL's granules -> AX
fsize_g:
        call    szp
        mov     ax, [si]
        mov     dx, [si+2]
granof: shr     ax, 7
        shl     dx, 9
        or      ax, dx
        ret
; granule AX -> DX:AX position
gpos:   mov     dx, ax
        shr     dx, 9
        shl     ax, 7
        ret
; SI -> file BL's size (dword)
szp:    mov     si, fsz
        cmp     bl, 0
        je      .x
        add     si, 4
.x:     ret
; [pos] of file BL at its end
fend:   call    szp
        mov     ax, [si]
        mov     [pos], ax
        mov     ax, [si+2]
        mov     [pos+2], ax
        jmp     fseek
; BX = handle of file BL (BL kept in BH... returns BX = handle)
hnd:    cmp     bl, 0
        mov     bx, [ha]
        je      .x
        mov     bx, [hb]
.x:     ret
fseek:  push    bx
        push    cx
        push    dx
        call    hnd
        mov     dx, [pos]
        mov     cx, [pos+2]
        mov     ax, 4200h
        int     21h
        pop     dx
        pop     cx
        pop     bx
        ret
fcreate:
        push    bx
        call    fnm
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        pop     bx
        jmp     sethnd
fopen:  push    bx
        call    fnm
        mov     ax, 3D02h
        int     21h
        pop     bx
sethnd: jc      .e
        cmp     bl, 0
        jne     .b
        mov     [ha], ax
        ret
.b:     mov     [hb], ax
        ret
.e:     mov     ah, 0FCh
        mov     al, 0
        jmp     error
fclose: push    bx
        call    hnd
        mov     ah, 3Eh
        int     21h
        pop     bx
        ret
fnm:    mov     dx, f_a
        cmp     bl, 0
        je      .x
        mov     dx, f_b
.x:     ret
reopen: push    bx
        mov     bl, 0
        call    fclose
        mov     bl, 1
        call    fclose
        mov     bl, 0
        call    fopen
        mov     bl, 1
        call    fopen
        pop     bx
        ret

; random 0 .. CX-1 -> AX
rand:   push    dx
        mov     ax, [seed]
        mov     dx, 25173
        mul     dx
        add     ax, 13849
        mov     [seed], ax
        mul     cx
        mov     ax, dx
        pop     dx
        ret

pr:     push    ax
.l:     lodsb
        or      al, al
        jz      .x
        call    pch
        jmp     .l
.x:     pop     ax
        ret
; AL to the screen, and a copy for CACHETST.TXT
pch:    push    ax
        push    dx
        push    di
        mov     di, [logpos]
        cmp     di, LOGMAX
        jae     .s
        mov     [logbuf+di], al
        inc     word [logpos]
.s:     mov     dl, al
        mov     ah, 2
        int     21h
        pop     di
        pop     dx
        pop     ax
        ret
pdec:   push    si
        push    bx
        mov     si, numbuf + 6
        mov     byte [si], 0
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        add     dl, '0'
        dec     si
        mov     [si], dl
        or      ax, ax
        jnz     .d
        call    pr
        pop     bx
        pop     si
        ret
phex:   push    si
        push    cx
        mov     si, numbuf
        mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 15
        add     al, '0'
        cmp     al, '9'
        jbe     .s
        add     al, 7
.s:     mov     [si], al
        inc     si
        pop     ax
        loop    .h
        mov     byte [si], 0
        mov     si, numbuf
        call    pr
        pop     cx
        pop     si
        ret

s_hello db 'CACHETST - disk cache stress test', 13, 10, 0
s_built db 'files built', 13, 10, 0
s_res   db 13, 10, 'CACHETST: ', 0
s_ops   db ' ops, ', 0
s_errs  db ' errors', 13, 10, 0
s_err   db 'error in op ', 0
s_file  db ', file ', 0
s_at    db ' at ', 0
s_want  db ': want ', 0
s_got   db ', got ', 0
s_crlf  db 13, 10, 0
s_gridos db 'on Grid-OS, ', 0
s_msdos db 'on MS-DOS, ', 0
s_date  db 'run ', 0
s_log   db 'CACHETST.TXT', 0
s_saved db 'Results added to CACHETST.TXT', 13, 10, 0
s_nosave db 'Could not write CACHETST.TXT', 13, 10, 0
s_key   db 'Press any key', 0
f_a     db 'CACHE_A.TST', 0
f_b     db 'CACHE_B.TST', 0
s_emm   db 'EMMXXXX0'
s_ems   db 'EMS: 4 pages of ours in the frame all along', 13, 10, 0
s_emsr  db 'EMS: the frame as we left it; ', 0
s_emsw  db ' reads and ', 0
s_emsx  db ' writes through it', 13, 10, 0
s_24    db 'Disk errors retried (INT 24h): ', 0

section .bss
bss_start:
rseg    resw 1                  ; where reads go: the buffer across 64 KB,
roff    resw 1                  ;  or the frame
ems_h   resw 1                  ; our EMS handle (0: no EMS)
fr_r    resw 1                  ; reads and writes through the frame
fr_w    resw 1
wfo     resw 1                  ; this write from the frame at wfo
wfr     resb 1
r24     resb 1                  ; INT 24h retries in a row
n24     resw 1                  ; INT 24h calls
bad24   resb 1                  ; one found the frame changed
seed    resw 1
opno    resw 1
nerr    resw 1
ha      resw 1
hb      resw 1
fsz     resd 2
pos     resd 1
rlen    resw 1
wlen    resw 1
rsz     resw 1
g0      resw 1
rwp     resd 1
rwl     resw 1
nver    resb 1
runs    resb 1
numbuf  resb 8
logpos  resw 1
logbuf  resb LOGMAX
vtab    resb MAXG * 2
rbuf    resb RBUF
wbuf    resb WBUF
        resb 512
stack_top:
