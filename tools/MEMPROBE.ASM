; =====================================================================
;  MEMPROBE.COM  -  GRiDCase 1520 memory diagnostic         (Lodestone)
;  Build:  nasm -f bin -o MEMPROBE.COM MEMPROBE.ASM
;  Run  :  MEMPROBE                    (clean boot, no HIMEM/EMM)
;          Report goes to screen AND A:\PROBE.TXT (committed to disk
;          before each risky test, so a hang still leaves a partial log)
;          MEMPROBE /F                 (force ext scan even if XMS/EMS loaded)
;
;  Reports: BIOS id, INT 12h/15h sizes, CMOS dump, XMS/EMS drivers,
;  A20 gate behaviour, 640K-1M upper memory map, and a non-destructive
;  64 KB-block scan of 1-16 MB via INT 15h AH=87h (detects aliasing).
; =====================================================================
cpu 286
org 100h

NBLK    equ 240                 ; blocks 16..255 (1 MB .. 16 MB)

start:
        cld
        mov     dx, fname
        xor     cx, cx
        mov     ah, 3Ch             ; create/truncate A:\PROBE.TXT
        int     21h
        jc      .nof
        mov     [fh], ax
.nof:   mov     dx, s_title
        call    puts
        cmp     word [fh], 0
        jne     .fok
        mov     dx, s_nofile
        call    puts
.fok:

; ---- parse /F -------------------------------------------------------
        mov     si, 81h
        mov     cl, [80h]
        xor     ch, ch
.pa:    jcxz    .pdone
        lodsb
        dec     cx
        cmp     al, '/'
        jne     .pa
        jcxz    .pdone
        mov     al, [si]
        or      al, 20h
        cmp     al, 'f'
        jne     .pa
        mov     byte [force], 1
.pdone:

; ---- BIOS identification -------------------------------------------
        mov     dx, s_bdate
        call    puts
        push    es
        mov     ax, 0F000h
        mov     es, ax
        mov     di, 0FFF5h
        mov     cx, 8
.bd:    mov     al, [es:di]
        inc     di
        call    putc_pr
        loop    .bd
        mov     dx, s_model
        call    puts
        mov     al, [es:0FFFEh]
        call    phex8
        call    crlf

        ; search F000 segment for "GRiD" strings (max 4)
        xor     di, di
        mov     byte [cnt], 0
.sr:    cmp     di, 0FFF0h
        jae     .srdone
        cmp     word [es:di], 'GR'
        jne     .srnx
        cmp     word [es:di+2], 'iD'
        jne     .srnx
        ; back up over printable chars (max 30)
        mov     bx, di
        mov     cx, 30
.bk:    or      bx, bx
        jz      .bkd
        mov     al, [es:bx-1]
        cmp     al, 20h
        jb      .bkd
        cmp     al, 7Eh
        ja      .bkd
        dec     bx
        loop    .bk
.bkd:   mov     dx, s_romstr
        call    puts
        mov     cx, 70
.fw:    mov     al, [es:bx]
        cmp     al, 20h
        jb      .fwd
        cmp     al, 7Eh
        ja      .fwd
        call    putc
        inc     bx
        loop    .fw
.fwd:   call    crlf
        mov     di, bx
        inc     byte [cnt]
        cmp     byte [cnt], 4
        jae     .srdone
        jmp     .sr
.srnx:  inc     di
        jmp     .sr
.srdone:
        pop     es

        ; INT 15h AH=C0h system configuration
        mov     dx, s_c0
        call    puts
        push    es
        mov     ah, 0C0h
        stc
        int     15h
        jc      .c0no
        or      ah, ah
        jnz     .c0no
        mov     al, [es:bx+2]
        call    phex8
        mov     al, '/'
        call    putc
        mov     al, [es:bx+3]
        call    phex8
        mov     al, '/'
        call    putc
        mov     al, [es:bx+4]
        call    phex8
        mov     dx, s_feat
        call    puts
        mov     al, [es:bx+5]
        call    phex8
        jmp     .c0d
.c0no:  mov     dx, s_unsup
        call    puts
.c0d:   pop     es
        call    crlf

; ---- CPU mode -------------------------------------------------------
        mov     dx, s_msw
        call    puts
        smsw    ax
        call    phex16
        test    al, 1
        jz      .real
        mov     dx, s_pmode
        call    puts
.real:  call    crlf

; ---- conventional / INT 15h 88h -------------------------------------
        mov     dx, s_conv
        call    puts
        int     12h
        call    pdec
        mov     dx, s_kb
        call    puts

        mov     dx, s_i1588
        call    puts
        mov     ah, 88h
        clc
        int     15h
        jc      .e88
        call    pdec
        mov     dx, s_kb
        call    puts
        jmp     .d88
.e88:   mov     dx, s_cf
        call    puts
        mov     al, ah
        call    phex8
        call    crlf
.d88:

; ---- CMOS -----------------------------------------------------------
        mov     dx, s_cmos
        call    puts
        xor     bx, bx
.cm:    test    bl, 0Fh
        jnz     .cmsp
        call    crlf
        mov     al, ' '
        call    putc
        call    putc
        mov     al, bl
        call    phex8
        mov     al, ':'
        call    putc
.cmsp:  mov     al, ' '
        call    putc
        mov     al, bl
        call    rdcmos
        mov     [cmos+bx], al       ; bh is 0
        call    phex8
        inc     bl
        cmp     bl, 40h
        jb      .cm
        call    crlf
        mov     dx, s_cbase
        call    puts
        mov     ax, [cmos+15h]
        call    pdec
        mov     dx, s_cext
        call    puts
        mov     ax, [cmos+17h]
        call    pdec
        mov     dx, s_cpost
        call    puts
        mov     ax, [cmos+30h]
        call    pdec
        mov     dx, s_kb
        call    puts

; ---- XMS ------------------------------------------------------------
        mov     dx, s_xms
        call    puts
        mov     ax, 4300h
        int     2Fh
        cmp     al, 80h
        jne     .noxms
        mov     byte [drvload], 1
        push    es
        mov     ax, 4310h
        int     2Fh
        mov     [xmsent], bx
        mov     [xmsent+2], es
        pop     es
        mov     dx, s_present
        call    puts
        xor     ah, ah
        call    far [xmsent]
        call    phex16
        mov     dx, s_xfree
        call    puts
        mov     ah, 08h
        call    far [xmsent]
        push    dx
        call    pdec
        mov     dx, s_xtot
        call    puts
        pop     ax
        call    pdec
        mov     dx, s_kb
        call    puts
        jmp     .xd
.noxms: mov     dx, s_none
        call    puts
.xd:

; ---- EMS ------------------------------------------------------------
        mov     dx, s_ems
        call    puts
        push    es
        mov     ax, 3567h
        int     21h
        mov     di, 0Ah
        mov     si, s_emmname
        mov     cx, 8
        repe    cmpsb
        pop     es
        jne     .noems
        mov     byte [drvload], 1
        mov     dx, s_ever
        call    puts
        mov     ah, 46h
        int     67h
        call    phex8
        mov     dx, s_eframe
        call    puts
        mov     ah, 41h
        int     67h
        mov     ax, bx
        call    phex16
        mov     dx, s_epages
        call    puts
        mov     ah, 42h
        int     67h
        push    bx
        mov     ax, dx
        call    pdec
        mov     dx, s_efree
        call    puts
        pop     ax
        call    pdec
        call    crlf
        jmp     .ed
.noems: mov     dx, s_none
        call    puts
.ed:

        call    commit
; ---- A20 gate -------------------------------------------------------
        mov     dx, s_a20
        call    puts
        call    a20test
        mov     [a20orig], al
        call    onoff
        mov     dx, s_kbcout
        call    puts
        call    kbc_readout
        call    phex8
        mov     dx, s_p92
        call    puts
        in      al, 92h
        call    phex8
        call    crlf
        cmp     byte [a20orig], 0
        jne     .a20d
        ; A20 is off: try the standard 8042 method, then restore
        mov     dx, s_a20kbc
        call    puts
        mov     ah, 0DFh
        call    kbc_setout
        call    a20test
        push    ax
        call    onoff
        pop     ax
        or      al, al
        jz      .a20d
        mov     ah, 0DDh            ; put it back the way we found it
        call    kbc_setout
.a20d:

        call    commit
; ---- Upper memory C000-EFFF (4 KB chunks) ---------------------------
        mov     dx, s_umb
        call    puts
        push    es
        mov     bx, 0C000h
.um:    test    bx, 0FFFh
        jnz     .umc
        call    crlf
        mov     dx, s_ind
        call    puts
        mov     ax, bx
        call    phex16
        mov     al, ' '
        call    putc
.umc:   mov     es, bx
        call    classify
        call    putc
        add     bx, 100h
        cmp     bx, 0F000h
        jb      .um
        pop     es
        call    crlf
        mov     dx, s_umleg
        call    puts

        call    commit
; ---- Extended memory scan ------------------------------------------
        mov     dx, s_ext
        call    puts
        cmp     byte [drvload], 0
        je      .doscan
        cmp     byte [force], 0
        jne     .doscan
        mov     dx, s_skip
        call    puts
        jmp     done
.doscan:
        mov     dx, s_scan
        call    puts
        ; phase A: save originals
        mov     bx, 16
.pA:    call    blkaddr_save        ; DI -> save slot
        mov     [lin_off], di
        call    rd_blk
        jnc     .pAok
        mov     byte [stat+bx-16], 'E'
        cmp     byte [firsterr], 0
        jne     .pAn
        mov     [firsterr], ah
        jmp     .pAn
.pAok:  mov     byte [stat+bx-16], 0
.pAn:   inc     bx
        cmp     bx, 256
        jb      .pA

        ; phase B: write tags, descending (lowest address wins aliases)
        mov     bx, 255
.pB:    cmp     byte [stat+bx-16], 'E'
        je      .pBn
        mov     [tag+6], bx
        mov     ax, bx
        not     ax
        mov     [tag+8], ax
        mov     word [lin_off], tag
        call    wr_blk
        jnc     .pBn
        mov     byte [stat+bx-16], 'E'
.pBn:   dec     bx
        cmp     bx, 16
        jae     .pB

        ; phase C: read back & classify
        mov     bx, 16
.pC:    cmp     byte [stat+bx-16], 'E'
        je      .pCn
        mov     word [lin_off], rdbuf
        call    rd_blk
        jc      .pCe
        mov     si, rdbuf
        mov     di, tag
        push    es
        push    ds
        pop     es
        mov     cx, 6
        repe    cmpsb
        pop     es
        jne     .pCnone
        mov     ax, [rdbuf+6]
        mov     dx, ax
        not     dx
        cmp     dx, [rdbuf+8]
        jne     .pCnone
        cmp     ax, bx
        jne     .pCal
        mov     byte [stat+bx-16], '#'
        inc     word [good]
        jmp     .pCn
.pCal:  mov     byte [stat+bx-16], 'a'
        cmp     word [al_from], 0
        jne     .pCn
        mov     [al_from], bx
        mov     [al_to], ax
        jmp     .pCn
.pCnone:
        mov     byte [stat+bx-16], '.'
        jmp     .pCn
.pCe:   mov     byte [stat+bx-16], 'E'
.pCn:   inc     bx
        cmp     bx, 256
        jb      .pC

        ; phase D: restore originals
        mov     bx, 255
.pD:    cmp     byte [stat+bx-16], 'E'
        je      .pDn
        call    blkaddr_save
        mov     [lin_off], di
        call    wr_blk
.pDn:   dec     bx
        cmp     bx, 16
        jae     .pD

        ; print map: one line per MB
        mov     dx, s_map
        call    puts
        mov     bx, 16
.mp:    test    bx, 0Fh
        jnz     .mpc
        call    crlf
        mov     al, ' '
        call    putc
        call    putc
        mov     ax, bx
        shr     ax, 4
        cmp     ax, 10
        jae     .mp2
        push    ax
        mov     al, ' '
        call    putc
        pop     ax
.mp2:   call    pdec
        mov     dx, s_mbc
        call    puts
.mpc:   mov     al, [stat+bx-16]
        call    putc
        inc     bx
        cmp     bx, 256
        jb      .mp
        call    crlf
        mov     dx, s_mapleg
        call    puts

        ; summary
        mov     dx, s_good
        call    puts
        mov     ax, [good]
        shl     ax, 6
        call    pdec
        mov     dx, s_contig
        call    puts
        xor     cx, cx
        mov     bx, 16
.ct:    cmp     byte [stat+bx-16], '#'
        jne     .ctd
        inc     cx
        inc     bx
        cmp     bx, 256
        jb      .ct
.ctd:   mov     ax, cx
        shl     ax, 6
        call    pdec
        mov     dx, s_kb
        call    puts
        cmp     word [al_from], 0
        je      .noal
        mov     dx, s_alias
        call    puts
        mov     ax, [al_from]
        call    phex8blk
        mov     dx, s_alias2
        call    puts
        mov     ax, [al_to]
        call    phex8blk
        call    crlf
.noal:  cmp     byte [firsterr], 0
        je      done
        mov     dx, s_err87
        call    puts
        mov     al, [firsterr]
        call    phex8
        call    crlf

done:   cmp     word [fh], 0
        je      .x
        mov     dx, s_end
        call    puts
        call    flush
        mov     bx, [fh]
        mov     ah, 3Eh             ; close
        int     21h
.x:     mov     ax, 4C00h
        int     21h

; =====================================================================
;  Subroutines
; =====================================================================

; DI = save + (BX-16)*16
blkaddr_save:
        mov     di, bx
        sub     di, 16
        shl     di, 4
        add     di, save
        ret

; linear address of DS:[lin_off] -> DX:AX (DX = high byte)
dslin:  mov     ax, ds
        mov     dx, ax
        shl     ax, 4
        shr     dx, 12
        add     ax, [lin_off]
        adc     dx, 0
        ret

; set descriptor at [gdt+SI] base = DL:AX
setdesc:
        mov     word [gdt+si], 0FFFFh
        mov     [gdt+si+2], ax
        mov     [gdt+si+4], dl
        mov     byte [gdt+si+5], 93h
        mov     word [gdt+si+6], 0
        ret

; copy 16 bytes: phys block BX (offset 0)  ->  DS:[lin_off]
rd_blk: pusha
        call    dslin
        mov     si, 24              ; dest = local
        call    setdesc
        xor     ax, ax
        mov     dl, bl
        mov     si, 16              ; source = block
        call    setdesc
        jmp     short do87

; copy 16 bytes: DS:[lin_off]  ->  phys block BX
wr_blk: pusha
        call    dslin
        mov     si, 16
        call    setdesc
        xor     ax, ax
        mov     dl, bl
        mov     si, 24
        call    setdesc
do87:   push    es
        push    ds
        pop     es
        mov     si, gdt
        mov     cx, 8
        mov     ah, 87h
        int     15h
        pop     es
        mov     [r87], ah
        popa
        mov     ah, [r87]
        jc      .c
        or      ah, ah
        jnz     .c
        clc
        ret
.c:     stc
        ret

; classify 4 KB chunk at ES:0 -> AL = 'M' RAM, 'R' option ROM,
;                                      'r' read-only data, '-' empty
classify:
        cmp     word [es:0], 0AA55h
        jne     .nr
        mov     al, 'R'
        ret
.nr:    xor     di, di
        call    wtest
        jc      .ram
        mov     di, 800h
        call    wtest
        jc      .ram
        xor     di, di
        mov     cx, 16
.ff:    cmp     byte [es:di], 0FFh
        jne     .ro
        add     di, 100h
        loop    .ff
        mov     al, '-'
        ret
.ro:    mov     al, 'r'
        ret
.ram:   mov     al, 'M'
        ret

; write-test byte ES:DI, restore; CF=1 if writable
wtest:  cli
        mov     al, [es:di]
        mov     ah, al
        not     al
        mov     [es:di], al
        jmp     short $+2
        mov     al, [es:di]
        mov     [es:di], ah
        sti
        not     al
        cmp     al, ah
        jne     .no
        stc
        ret
.no:    clc
        ret

; A20 test -> AL=1 enabled, 0 wrapped
a20test:
        push    ds
        push    es
        cli
        xor     ax, ax
        mov     ds, ax
        dec     ax
        mov     es, ax              ; FFFF
        mov     al, [0500h]
        mov     ah, al
        not     al
        mov     [0500h], al
        jmp     short $+2
        cmp     al, [es:0510h]
        mov     [0500h], ah
        sti
        pop     es
        pop     ds
        mov     al, 0
        je      .w
        mov     al, 1
.w:     ret

kbc_wait_in:
        mov     cx, 0FFFFh
.l:     in      al, 64h
        test    al, 2
        jz      .ok
        loop    .l
.ok:    ret

kbc_wait_out:
        mov     cx, 0FFFFh
.l:     in      al, 64h
        test    al, 1
        jnz     .ok
        loop    .l
.ok:    ret

kbc_readout:
        cli
        call    kbc_wait_in
        mov     al, 0D0h
        out     64h, al
        call    kbc_wait_out
        in      al, 60h
        sti
        ret

; AH = output port value (DF enable / DD disable)
kbc_setout:
        cli
        call    kbc_wait_in
        mov     al, 0D1h
        out     64h, al
        call    kbc_wait_in
        mov     al, ah
        out     60h, al
        call    kbc_wait_in
        mov     al, 0FFh
        out     64h, al
        call    kbc_wait_in
        sti
        ret

; AL = CMOS index -> AL = value
rdcmos: cli
        out     70h, al
        jmp     short $+2
        in      al, 71h
        sti
        ret

onoff:  mov     dx, s_off
        or      al, al
        jz      .p
        mov     dx, s_on
.p:     jmp     puts

; print "xx0000h" address for block number in AX
phex8blk:
        call    phex8
        mov     dx, s_0000
        jmp     puts

; print '$'-string DS:DX to screen and log file
puts:   pusha
        mov     ah, 09h
        int     21h
        cmp     word [fh], 0
        je      .r
        mov     si, dx
.l:     lodsb
        cmp     al, '$'
        je      .r
        call    fput
        jmp     .l
.r:     popa
        ret

; print char AL to screen and log file
putc:   pusha
        mov     dl, al
        mov     ah, 02h
        int     21h
        cmp     word [fh], 0
        je      .r
        mov     al, dl
        call    fput
.r:     popa
        ret

; buffer AL for the log file
fput:   mov     bx, [bufn]
        mov     [fbuf+bx], al
        inc     bx
        mov     [bufn], bx
        cmp     bx, 512
        jb      .r
        call    flush
.r:     ret

flush:  pusha
        mov     cx, [bufn]
        jcxz    .r
        mov     bx, [fh]
        or      bx, bx
        jz      .r
        mov     dx, fbuf
        mov     ah, 40h
        int     21h
        mov     word [bufn], 0
.r:     popa
        ret

; flush and force DOS to write the log to the floppy (DOS 3.3+ AH=68h)
commit: call    flush
        pusha
        mov     bx, [fh]
        or      bx, bx
        jz      .r
        mov     ah, 68h
        int     21h
.r:     popa
        ret

putc_pr:
        cmp     al, 20h
        jb      .d
        cmp     al, 7Eh
        jbe     putc
.d:     push    ax
        mov     al, '.'
        call    putc
        pop     ax
        ret

crlf:   push    dx
        mov     dx, s_crlf
        call    puts
        pop     dx
        ret

phex16: push    ax
        mov     al, ah
        call    phex8
        pop     ax
phex8:  push    ax
        shr     al, 4
        call    .n
        pop     ax
        push    ax
        and     al, 0Fh
        call    .n
        pop     ax
        ret
.n:     add     al, '0'
        cmp     al, '9'
        jbe     .o
        add     al, 7
.o:     jmp     putc

pdec:   pusha
        xor     cx, cx
        mov     bx, 10
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

; =====================================================================
;  Data
; =====================================================================
s_title db 'MEMPROBE 1.1 - GRiDCase memory diagnostic (Lodestone)',13,10
        db '==================================================',13,10,'$'
s_bdate db 'BIOS date      : $'
s_model db '   model byte: $'
s_romstr db 'ROM string     : $'
s_c0    db 'INT15 C0 mdl/sub/rev: $'
s_feat  db '  feature1: $'
s_unsup db 'unsupported$'
s_msw   db 'MSW            : $'
s_pmode db '  (PROTECTED MODE / V86 - memory manager active!)$'
s_conv  db 'INT 12h conv.  : $'
s_i1588 db 'INT 15h/88 ext : $'
s_kb    db ' KB',13,10,'$'
s_cf    db 'CF set, AH=$'
s_cmos  db 'CMOS 00-3F:$'
s_cbase db 'CMOS base(15h) : $'
s_cext  db ' KB   ext cfg(17h): $'
s_cpost db ' KB   ext POST(30h): $'
s_xms   db 'XMS driver     : $'
s_present db 'present, ver $'
s_xfree db '  largest free $'
s_xtot  db ' KB, total free $'
s_none  db 'none',13,10,'$'
s_ems   db 'EMS driver     : $'
s_emmname db 'EMMXXXX0'
s_ever  db 'present, ver $'
s_eframe db '  frame seg $'
s_epages db '  pages total $'
s_efree db ' free $'
s_a20   db 'A20 at start   : $'
s_on    db 'ENABLED$'
s_off   db 'disabled (wraps)$'
s_kbcout db '   8042 outport: $'
s_p92   db '   port 92h reads: $'
s_a20kbc db 'A20 via 8042 D1/DF: $'
s_umb   db 13,10,'Upper memory C000-EFFF (one char per 4 KB):$'
s_ind   db '  $'
s_umleg db '  M=RAM  R=option ROM  r=read-only  -=empty(FF)',13,10,'$'
s_ext   db 13,10,'Extended memory scan (INT 15h/87h, 64 KB blocks)',13,10,'$'
s_skip  db '  SKIPPED: XMS/EMS driver loaded. Clean-boot, or use /F.',13,10,'$'
s_scan  db '  scanning 1-16 MB (contents are saved and restored)...',13,10,'$'
s_map   db '  MB  0123456789ABCDEF  (64 KB per column)$'
s_mbc   db ': $'
s_mapleg db '  #=RAM  a=alias of lower block  .=nothing  E=BIOS 87h error',13,10,'$'
s_good  db '  Working extended RAM: $'
s_contig db ' KB   contiguous from 1 MB: $'
s_alias db '  First alias: block $'
s_alias2 db ' mirrors $'
s_0000  db '0000h$'
s_err87 db '  INT 15h/87h first error code AH=$'
s_end   db 13,10,'Done. Report saved to A:\PROBE.TXT',13,10,'$'
s_nofile db '** Could not create A:\PROBE.TXT (disk in drive A:? write-protect?)',13,10
        db '** Continuing - screen output only.',13,10,'$'
fname   db 'A:\PROBE.TXT',0
fh      dw 0
bufn    dw 0
s_crlf  db 13,10,'$'

tag     db 'GRDPRB'
        dw 0, 0
        db 55h,0AAh,5Ah,0A5h,0Fh,0F0h

force   db 0
drvload db 0
cnt     db 0
a20orig db 0
firsterr db 0
r87     db 0
good    dw 0
al_from dw 0
al_to   dw 0
lin_off dw 0
xmsent  dd 0

cmos    times 64 db 0
gdt     times 48 db 0
rdbuf   times 16 db 0
stat    times NBLK db 0
save    times NBLK*16 db 0
fbuf    times 512 db 0
