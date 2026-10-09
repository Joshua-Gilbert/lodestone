; =====================================================================
;  RAMSPEED.COM - GRiDCase 1520 memory speed test               (Lodestone)
;  Build:  nasm -f bin -o RAMSPEED.COM RAMSPEED.ASM
;  Run  :  RAMSPEED [label]      e.g.  RAMSPEED NEW-SIPPS   RAMSPEED FACTORY
;
;  Each test runs for 36 BIOS ticks (~2 s) and reports KB/s.
;  Results go to the screen and are APPENDED to A:\RAMSPEED.TXT, so runs
;  with different SIPPs / speed settings can be compared side by side.
;
;  Tests
;    CPU     LOOP-instruction rate (normalises runs at different CPU speed)
;    CONV    rep stosw / rep lodsw / rep movsw, 32 KB blocks, in a low
;            (~64-128K) and a high (~544-608K) conventional-memory area
;    ROM     rep lodsw from BIOS ROM F000:8000
;    EMS     via a LIM driver (GRiD EMM.SYS): frame write/read/copy with 4
;            pages mapped, and map-page + read 16 KB (page switch included)
;    EXT     INT 15h/87h 16 KB block moves at 1.0 / 1.5 / 2.0 MB
;            (BIOS protected-mode copy incl. mode-switch overhead - this is
;            what RAMDRIVE /E and XMS drivers on a 286 actually get)
;            The write test saves and restores the 16 KB it overwrites.
; =====================================================================
cpu 286
org 100h

DUR     equ 36                  ; ticks per test (~1.98 s)

start:  cld
        ; ---- label from command line -------------------------------
        mov     si, 81h
        mov     cl, [80h]
        xor     ch, ch
.sk:    jcxz    .lend
        cmp     byte [si], ' '
        jne     .lcp
        inc     si
        dec     cx
        jmp     .sk
.lcp:   mov     di, label
        cmp     cx, 30
        jbe     .lc2
        mov     cx, 30
.lc2:   rep     movsb
        mov     byte [di], '$'
.lend:
        ; ---- buffer segments ----------------------------------------
        mov     ax, cs
        add     ax, 1000h
        mov     [seglow], ax
        mov     ax, [2]                 ; PSP: top of our memory block
        cmp     ax, 9800h
        jae     .hiok
        mov     word [seghigh], 0       ; not enough memory for high test
.hiok:
        ; ---- open log (append) --------------------------------------
        mov     dx, fname
        mov     ax, 3D01h               ; open, write-only
        int     21h
        jnc     .opened
        mov     dx, fname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .nolog
.opened:
        mov     [fh], ax
        mov     bx, ax
        mov     ax, 4202h               ; seek to end
        xor     cx, cx
        xor     dx, dx
        int     21h
        jmp     .hdr
.nolog: mov     word [fh], 0
        mov     dx, s_nolog
        call    scr_only

        ; ---- header -------------------------------------------------
.hdr:   mov     dx, s_title
        call    puts
        mov     dx, s_run
        call    puts
        mov     dx, label
        call    puts
        mov     dx, s_date
        call    puts
        mov     ah, 2Ah                 ; DOS date: CX=year DH=month DL=day
        int     21h
        push    dx
        mov     ax, cx
        call    pdec
        mov     al, '-'
        call    putc
        pop     dx
        push    dx
        mov     al, dh
        call    pdec2
        mov     al, '-'
        call    putc
        pop     dx
        mov     al, dl
        call    pdec2
        mov     al, ' '
        call    putc
        mov     ah, 2Ch                 ; DOS time: CH=h CL=m
        int     21h
        push    cx
        mov     al, ch
        call    pdec2
        mov     al, ':'
        call    putc
        pop     cx
        mov     al, cl
        call    pdec2
        call    crlf

        mov     ah, 88h                 ; extended memory size
        clc
        int     15h
        jnc     .e88
        xor     ax, ax
.e88:   mov     [extkb], ax
        mov     dx, s_ext
        call    puts
        call    pdec
        mov     dx, s_kbnl
        call    puts
        call    commit

; ---- CPU ------------------------------------------------------------
        mov     dx, t_cpu
        mov     word [opfn], op_cpu
        mov     word [opkb], 0          ; special: rate = kloops/s
        call    runtest

; ---- conventional low -----------------------------------------------
        mov     ax, [seglow]
        mov     [tseg], ax
        mov     word [opkb], 32
        mov     dx, t_lw
        mov     word [opfn], op_write
        call    runtest
        mov     dx, t_lr
        mov     word [opfn], op_read
        call    runtest
        mov     dx, t_lc
        mov     word [opfn], op_copy
        call    runtest

; ---- conventional high ----------------------------------------------
        cmp     word [seghigh], 0
        je      .nohigh
        mov     ax, [seghigh]
        mov     [tseg], ax
        mov     dx, t_hw
        mov     word [opfn], op_write
        call    runtest
        mov     dx, t_hr
        mov     word [opfn], op_read
        call    runtest
        mov     dx, t_hc
        mov     word [opfn], op_copy
        call    runtest
        jmp     .rom
.nohigh:
        mov     dx, s_nohigh
        call    puts

; ---- ROM ------------------------------------------------------------
.rom:   mov     word [tseg], 0F800h     ; F800:0000 = F000:8000
        mov     dx, t_rom
        mov     word [opfn], op_read
        call    runtest
        call    commit

; ---- EMS (LIM driver, e.g. GRiD EMM.SYS) -----------------------------
        call    ems_tests
        call    commit

; ---- extended via INT 15h/87h ----------------------------------------
        cmp     word [extkb], 32
        jae     .ext
        mov     dx, s_noext
        call    puts
        jmp     .done
.ext:   mov     word [opkb], 16
        mov     word [opfn], op_ext_rd
        mov     byte [ehi], 10h         ; 1.0 MB
        mov     dx, t_e10
        call    runtest
        cmp     word [extkb], 512+16
        jb      .extw
        mov     byte [ehi], 18h         ; 1.5 MB
        mov     dx, t_e15
        call    runtest
        cmp     word [extkb], 1024+16
        jb      .extw
        mov     byte [ehi], 20h         ; 2.0 MB
        mov     dx, t_e20
        call    runtest

        ; write test at 1.0 MB with save/restore
.extw:  mov     byte [ehi], 10h
        mov     ax, [seglow]            ; save original 16 KB into seglow:8000
        mov     [xseg], ax
        mov     word [xoff], 8000h
        call    ext_to_local
        jc      .ewfail
        mov     word [xoff], 0
        mov     word [opfn], op_ext_wr
        mov     dx, t_ew
        call    runtest
        mov     word [xoff], 8000h      ; restore
        call    local_to_ext
        jnc     .done
.ewfail:
        mov     dx, s_ewfail
        call    puts

.done:  call    crlf
        call    flush
        mov     bx, [fh]
        or      bx, bx
        jz      .x
        mov     ah, 3Eh
        int     21h
        mov     dx, s_saved
        call    scr_only
.x:     mov     ax, 4C00h
        int     21h

; =====================================================================
;  EMS tests: frame write/read/copy with 4 pages mapped, then
;  map-a-page + read 16 KB (includes the INT 67h page switch).
; =====================================================================
ems_tests:
        push    es
        mov     ax, 3567h
        int     21h
        mov     di, 0Ah
        mov     si, s_emmname
        mov     cx, 8
        repe    cmpsb
        pop     es
        je      .have
        mov     dx, s_noems
        call    puts
        ret
.have:  mov     ah, 40h                 ; status
        int     67h
        or      ah, ah
        jnz     .bad
        mov     ah, 41h                 ; page frame
        int     67h
        or      ah, ah
        jnz     .bad
        mov     [emsframe], bx
        mov     ah, 42h                 ; pages free/total
        int     67h
        mov     [emsfree], bx
        mov     dx, s_emspg
        call    puts
        mov     ax, bx
        call    pdec
        mov     dx, s_emsfr
        call    puts
        mov     ax, [emsframe]
        call    phex16
        call    crlf
        cmp     word [emsfree], 4
        jae     .alloc
        mov     dx, s_emsfew
        call    puts
        ret
.alloc: mov     ah, 43h                 ; allocate 4 pages
        mov     bx, 4
        int     67h
        or      ah, ah
        jnz     .bad
        mov     [emshandle], dx
        xor     bx, bx                  ; map logical 0..3 -> physical 0..3
.mp:    mov     al, bl
        mov     ah, 44h
        mov     dx, [emshandle]
        push    bx
        int     67h
        pop     bx
        or      ah, ah
        jnz     .badfree
        inc     bx
        cmp     bx, 4
        jb      .mp
        mov     ax, [emsframe]
        mov     [tseg], ax
        mov     word [opkb], 32
        mov     dx, t_mw
        mov     word [opfn], op_write
        call    runtest
        mov     dx, t_mr
        mov     word [opfn], op_read
        call    runtest
        mov     dx, t_mc
        mov     word [opfn], op_copy
        call    runtest
        mov     word [opkb], 16
        mov     word [emslog], 0
        mov     dx, t_mm
        mov     word [opfn], op_ems_mapread
        call    runtest
        mov     ah, 45h                 ; release
        mov     dx, [emshandle]
        int     67h
        ret
.badfree:
        push    ax
        mov     ah, 45h
        mov     dx, [emshandle]
        int     67h
        pop     ax
.bad:   mov     dx, s_emsbad
        call    puts
        mov     al, ah
        call    phex8
        call    crlf
        ret

; map next logical page (0..3) into physical page 0, read 16 KB
op_ems_mapread:
        mov     bx, [emslog]
        inc     word [emslog]
        and     bx, 3
        mov     ax, 4400h               ; AL = physical page 0
        mov     dx, [emshandle]
        int     67h
        or      ah, ah
        jnz     .f
        push    ds
        mov     ax, [emsframe]
        mov     ds, ax
        xor     si, si
        mov     cx, 2000h               ; 8K words = 16 KB
        rep     lodsw
        pop     ds
        clc
        ret
.f:     mov     [r87], ah
        stc
        ret

; =====================================================================
;  Test runner.  DX = name string, [opfn] = op, [opkb] = KB per op.
; =====================================================================
runtest:
        call    puts
        call    sync
        mov     [t0], ax
        mov     word [cntlo], 0
        mov     word [cnthi], 0
.l:     call    word [opfn]
        jc      .err
        add     word [cntlo], 1
        adc     word [cnthi], 0
        call    gettick
        sub     ax, [t0]
        cmp     ax, DUR
        jb      .l
        mov     [elapsed], ax

        ; units total (DX:AX) = count * (opkb or 1)
        mov     ax, [cntlo]
        mov     dx, [cnthi]
        mov     bx, [opkb]
        or      bx, bx
        jz      .cpu
        mul     bx                      ; count < 65536 here
        ; KB/s = KB * 18207 / (elapsed * 1000)
        mov     bx, 18207
        call    mul32x16                ; DX:AX *= BX (low 32 bits)
        mov     bx, [elapsed]
        call    div32x16
        mov     bx, 1000
        call    div32x16
        call    pdec
        mov     dx, s_kbs
        call    puts
        ret
.cpu:   ; kloops/s = count(ops of 1000 loops) * 18207 / (elapsed*1000)
        mov     bx, 18207
        call    mul32x16
        mov     bx, [elapsed]
        call    div32x16
        mov     bx, 1000
        call    div32x16
        call    pdec
        mov     dx, s_kls
        call    puts
        ret
.err:   mov     dx, s_err
        call    puts
        mov     al, [r87]
        call    phex8
        call    crlf
        ret

gettick:
        push    ds
        mov     ax, 40h
        mov     ds, ax
        mov     ax, [6Ch]
        pop     ds
        ret

sync:   call    gettick
        mov     bx, ax
.w:     call    gettick
        cmp     ax, bx
        je      .w
        ret

; DX:AX = DX:AX * BX  (low 32 bits)
mul32x16:
        push    cx
        push    si
        mov     si, dx
        mul     bx                      ; DX:AX = lo*BX
        mov     cx, dx
        push    ax
        mov     ax, si
        mul     bx                      ; hi*BX
        add     cx, ax
        pop     ax
        mov     dx, cx
        pop     si
        pop     cx
        ret

; DX:AX = DX:AX / BX
div32x16:
        push    cx
        mov     cx, ax
        mov     ax, dx
        xor     dx, dx
        div     bx                      ; high part
        push    ax
        mov     ax, cx
        div     bx                      ; remainder:low
        pop     dx
        pop     cx
        ret

; =====================================================================
;  Operations (CF=1 on failure)
; =====================================================================
op_cpu: mov     cx, 1000
.l:     loop    .l
        clc
        ret

op_write:
        push    es
        mov     es, [tseg]
        xor     di, di
        mov     cx, 4000h               ; 16K words = 32 KB
        xor     ax, ax
        rep     stosw
        pop     es
        clc
        ret

op_read:
        push    ds
        mov     ax, [tseg]
        mov     ds, ax
        xor     si, si
        mov     cx, 4000h
        rep     lodsw
        pop     ds
        clc
        ret

op_copy:
        push    ds
        push    es
        mov     ax, [tseg]
        mov     ds, ax
        mov     es, ax
        xor     si, si
        mov     di, 8000h
        mov     cx, 4000h
        rep     movsw
        pop     es
        pop     ds
        clc
        ret

op_ext_rd:
        mov     ax, [seglow]
        mov     [xseg], ax
        mov     word [xoff], 0
        jmp     ext_to_local

op_ext_wr:
        mov     ax, [seglow]
        mov     [xseg], ax
        mov     word [xoff], 0
        jmp     local_to_ext

; 16 KB: phys [ehi]0000h -> [xseg]:[xoff]
ext_to_local:
        pusha
        call    loclin
        mov     si, 24                  ; dest = local
        call    setdesc
        xor     ax, ax
        mov     dl, [ehi]
        mov     si, 16                  ; source = extended
        call    setdesc
        jmp     short do87

; 16 KB: [xseg]:[xoff] -> phys [ehi]0000h
local_to_ext:
        pusha
        call    loclin
        mov     si, 16
        call    setdesc
        xor     ax, ax
        mov     dl, [ehi]
        mov     si, 24
        call    setdesc
do87:   push    es
        push    ds
        pop     es
        mov     si, gdt
        mov     cx, 2000h               ; 8K words = 16 KB
        mov     ah, 87h
        int     15h
        pop     es
        mov     [r87], ah
        popa
        jc      .f
        cmp     byte [r87], 0
        jne     .f
        clc
        ret
.f:     stc
        ret

; DL:AX = linear address of [xseg]:[xoff]
loclin: mov     ax, [xseg]
        mov     dx, ax
        shl     ax, 4
        shr     dx, 12
        add     ax, [xoff]
        adc     dx, 0
        ret

setdesc:
        mov     word [gdt+si], 0FFFFh
        mov     [gdt+si+2], ax
        mov     [gdt+si+4], dl
        mov     byte [gdt+si+5], 93h
        mov     word [gdt+si+6], 0
        ret

; =====================================================================
;  Output: screen + buffered log file
; =====================================================================
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

scr_only:
        push    ax
        mov     ah, 09h
        int     21h
        pop     ax
        ret

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

commit: call    flush
        pusha
        mov     bx, [fh]
        or      bx, bx
        jz      .r
        mov     ah, 68h
        int     21h
.r:     popa
        ret

crlf:   push    dx
        mov     dx, s_crlf
        call    puts
        pop     dx
        ret

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

phex16: push    ax
        mov     al, ah
        call    phex8
        pop     ax
        jmp     phex8

; AL -> two digits
pdec2:  xor     ah, ah
        push    bx
        mov     bl, 10
        div     bl
        add     ax, '00'
        push    ax
        call    putc
        pop     ax
        mov     al, ah
        call    putc
        pop     bx
        ret

; AX -> decimal, right-aligned in 6 columns
pdec:   pusha
        xor     cx, cx
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
        mov     [ndig], cx
.p:     pop     ax
        add     al, '0'
        call    putc
        loop    .p
        popa
        ret

; =====================================================================
;  Data
; =====================================================================
s_title db 13,10,'RAMSPEED 1.1 - GRiDCase memory speed test (Lodestone)',13,10,'$'
s_run   db 'Run      : $'
s_date  db '   $'
s_ext   db 'Ext mem  : $'
s_kbnl  db ' KB',13,10,'$'
s_kbs   db ' KB/s',13,10,'$'
s_kls   db ' k loops/s',13,10,'$'
s_err   db '  ** BIOS 87h error AH=$'
s_nolog db '** Could not open A:\RAMSPEED.TXT - screen only.',13,10,'$'
s_saved db 'Appended to A:\RAMSPEED.TXT',13,10,'$'
s_nohigh db 'CONV high : skipped (not enough free memory)',13,10,'$'
s_noext db 'EXT      : skipped (no extended memory)',13,10,'$'
s_ewfail db '** EXT write test: could not save/restore - skipped',13,10,'$'
s_crlf  db 13,10,'$'
t_cpu   db 'CPU   LOOP rate            : $'
t_lw    db 'CONV  low   write (stosw)  : $'
t_lr    db 'CONV  low   read  (lodsw)  : $'
t_lc    db 'CONV  low   copy  (movsw)  : $'
t_hw    db 'CONV  high  write (stosw)  : $'
t_hr    db 'CONV  high  read  (lodsw)  : $'
t_hc    db 'CONV  high  copy  (movsw)  : $'
t_rom   db 'ROM   F000  read  (lodsw)  : $'
t_mw    db 'EMS   frame write (stosw)  : $'
t_mr    db 'EMS   frame read  (lodsw)  : $'
t_mc    db 'EMS   frame copy  (movsw)  : $'
t_mm    db 'EMS   map+read 16K (INT67) : $'
s_noems db 'EMS      : skipped (no EMS driver - GRIDMEM EMS + DEVICE=EMM.SYS)',13,10,'$'
s_emsfew db 'EMS      : skipped (fewer than 4 free pages - machine in EXT mode?)',13,10,'$'
s_emsbad db '** EMS driver error AH=$'
s_emspg db 'EMS      : $'
s_emsfr db ' pages free, frame segment $'
s_emmname db 'EMMXXXX0'
t_e10   db 'EXT   1.0MB read  (15h/87h): $'
t_e15   db 'EXT   1.5MB read  (15h/87h): $'
t_e20   db 'EXT   2.0MB read  (15h/87h): $'
t_ew    db 'EXT   1.0MB write (15h/87h): $'
fname   db 'A:\RAMSPEED.TXT',0
label   db '(no label)$'
        times 24 db 0
fh      dw 0
bufn    dw 0
seglow  dw 0
seghigh dw 8800h
tseg    dw 0
extkb   dw 0
opfn    dw 0
opkb    dw 0
t0      dw 0
elapsed dw 0
cntlo   dw 0
cnthi   dw 0
ndig    dw 0
xseg    dw 0
xoff    dw 0
ehi     db 0
emsframe dw 0
emshandle dw 0
emslog  dw 0
emsfree dw 0
r87     db 0
gdt     times 48 db 0
fbuf    times 512 db 0
