; =====================================================================
;  KPROC.INC - processes: the master environment and the root PSP (the
;  Executive), EXEC of .COM and .EXE programs, terminate / TSR, exit
;  codes, and the built-in GPIB driver's start-up.
; =====================================================================
section .bss
cur_psp     resw 1
root_psp    resw 1
last_exit   resw 1              ; AL = code, AH = how it ended
term_keep   resw 1              ; TSR: paragraphs to keep
gp_ok       resb 1              ; INT 60h installed
            alignb 2
ex_psp      resw 1
ex_size     resw 1              ; paragraphs given
ex_load     resw 1
ex_ip       resw 1
ex_cs       resw 1
ex_sp       resw 1
ex_ss       resw 1
ex_sft      resw 1
ex_left     resw 2              ; bytes still to load
ex_min      resw 1
ex_max      resw 1
ex_isexe    resb 1
            alignb 2
ex_env      resw 1              ; the EXEC parameter block's copy (f_4B
ex_tail     resw 2              ;  moves it in one go: keep the order)
ex_fcb1     resw 2
ex_fcb2     resw 2
ex_name     resb 132            ; full program name for the environment
section .text
; scratch that is dead while a program loads (from the header read on
; EXEC runs no path call and no RENAME; MULTITASK=1 switches tasks only
; outside INT 21h, or at a key wait, which EXEC's own code never makes):
ex_hdr      equ ren_de          ; .EXE header (28 of its 32 bytes)
ex_rel      equ path_buf        ; relocation entries, 64 at a time (256 of
                                ;  path_buf's and path2_buf's 260)
        times -(path2_buf - path_buf != 130) db 0       ; (they must stay together,
        times -(nm11 - path_buf < 256) db 0             ;  nothing between, 256 B;
        times -(ren_de_end - ren_de < 28) db 0          ;  ren_de holds the header)

section ovl
proc_init:
        mov     bx, 32                  ; master environment, 512 bytes
        mov     dx, 8
        call    mem_alloc
        mov     [ex_env], ax
        mov     es, ax
        xor     di, di
        mov     si, env0
.c:     lodsb
        cmp     al, '@'
        jne     .s
        mov     al, [bootdrv]           ; (the drive started from: R: too)
        add     al, 'A'
.s:     stosb
        cmp     si, env0_end
        jb      .c
        push    cs
        pop     es
        mov     bx, 16                  ; the root PSP (the Executive)
        mov     dx, 8
        call    mem_alloc
        mov     [root_psp], ax
        mov     [cur_psp], ax
        push    ax
        dec     ax
        mov     es, ax
        pop     ax
        mov     [es:1], ax              ; owns itself
        push    ax
        mov     ax, [ex_env]
        dec     ax
        mov     es, ax
        pop     ax
        mov     [es:1], ax              ; and the environment
        mov     es, ax
        mov     bx, ax                  ; parent = itself
        mov     dx, ax
        add     dx, 16
        mov     ax, [ex_env]
        call    make_psp
        mov     word [es:0Ah], root_term
        mov     word [es:0Ch], KSEG
        mov     word [es:0Eh], int23
        mov     word [es:10h], KSEG
        mov     word [es:12h], int24
        mov     word [es:14h], KSEG
        mov     word [es:18h], 0        ; handles 0-2: CON
        mov     byte [es:1Ah], 0
        mov     byte [es:1Bh], 1        ; 3: AUX
        mov     byte [es:1Ch], 2        ; 4: PRN
        mov     ax, es
        mov     [dta+2], ax
        mov     word [dta], 80h
        push    cs
        pop     es
        ret
env0    db 'COMSPEC=@:\LCMD.COM', 0, 'PATH=@:\', 0, 'PROMPT=$P$G', 0, 0
env0_end:
section .text

; build a PSP at ES: AX = environment, BX = parent, DX = top of memory.
; Handles are inherited from the parent (unless opened with bit 7).
make_psp:
        push    ax
        push    cx
        push    si
        push    di
        push    ax
        xor     di, di
        mov     cx, 128
        xor     ax, ax
        rep     stosw
        mov     word [es:0], 20CDh
        mov     [es:2], dx
        mov     byte [es:5], 9Ah        ; CP/M-style call (unused)
        mov     word [es:6], 0FEF0h
        mov     word [es:8], 0F01Dh
        push    ds                      ; INT 22h-24h as they are now
        xor     si, si
        mov     ds, si
        mov     si, 22h * 4
        mov     di, 0Ah
        mov     cx, 6
        rep     movsw
        pop     ds
        mov     [es:16h], bx
        pop     word [es:2Ch]           ; environment
        mov     word [es:32h], 20
        mov     word [es:34h], 18h
        mov     [es:36h], es
        mov     word [es:38h], 0FFFFh
        mov     word [es:3Ah], 0FFFFh
        mov     word [es:50h], 21CDh
        mov     byte [es:52h], 0CBh
        mov     di, 5Ch                 ; two blank FCBs
        call    .fcb
        mov     di, 6Ch
        call    .fcb
        mov     byte [es:81h], 0Dh
        ; handles
        mov     di, 18h
        mov     cx, 20
        mov     al, 0FFh
        rep     stosb
        mov     ax, es
        cmp     ax, bx
        je      .x                      ; the root: set by the caller
        push    ds
        mov     ds, bx                  ; the parent's handles
        xor     si, si
.h:     mov     al, [18h+si]
        cmp     al, NSFT
        jae     .n
        push    si                      ; (SI: the handle)
        call    sft_of
        mov     di, si
        pop     si
        test    byte [cs:di+S_MODE], 80h
        jnz     .n                      ; opened "not inherited"
        inc     byte [cs:di+S_REF]
        mov     [es:18h+si], al
.n:     inc     si
        cmp     si, 20
        jb      .h
        pop     ds
.x:     pop     di
        pop     si
        pop     cx
        pop     ax
        ret
.fcb:   mov     byte [es:di], 0
        inc     di
        mov     cx, 11
        mov     al, ' '
        rep     stosb
        ret

; ---------------------------------------------------------------------
;  4Bh EXEC (AL = 0: load and run).  DS:DX = program, ES:BX = block:
;  environment, command tail (far), FCB 1 (far), FCB 2 (far)
; ---------------------------------------------------------------------
f_4B:   cmp     byte [bp+F_AX], 0
        je      .go
        mov     ax, 1
        jmp     fail
.go:    call    get_path
        jc      .e0
        push    cs                      ; the parameter block, as it is laid
        pop     es                      ;  out: ex_env, ex_tail, ex_fcb1,
        push    ds                      ;  ex_fcb2
        mov     ds, [bp+F_ES]
        mov     si, [bp+F_BX]
        mov     di, ex_env
        mov     cx, 7
        rep     movsw
        pop     ds
        call    full_name
        jc      .e0
        call    find_file
        jc      .nf
        test    byte [de+11], A_DIR | A_VOL
        jnz     .acc
        call    sft_alloc
        jc      .e0
        mov     [ex_sft], si
        xor     al, al
        call    sft_fill
        ; header
        mov     cx, 28
        mov     di, ex_hdr
        call    file_read
        push    cs
        pop     es
        jc      .e1
        mov     byte [ex_isexe], 0
        cmp     ax, 28
        jb      .com
        cmp     word [ex_hdr], 'MZ'
        je      .exe
        cmp     word [ex_hdr], 'ZM'
        je      .exe
.com:   mov     si, [ex_sft]
        cmp     word [si+S_SIZE+2], 0
        jne     .big
        mov     ax, [si+S_SIZE]
        cmp     ax, 0FE00h
        ja      .big
        mov     [ex_left], ax
        mov     word [ex_left+2], 0
        add     ax, 100h + 15
        shr     ax, 4
        inc     ax                      ; and some stack
        mov     [ex_min], ax
        mov     word [ex_max], 0FFFFh
        jmp     .env
.exe:   mov     byte [ex_isexe], 1
        mov     ax, [ex_hdr+4]          ; pages
        mov     dx, [ex_hdr+2]          ; bytes in the last page
        or      dx, dx
        jz      .p
        dec     ax
.p:     mov     cx, 512
        mul     cx
        add     ax, [ex_hdr+2]
        adc     dx, 0                   ; DX:AX = file image size
        mov     cx, [ex_hdr+8]          ; header paragraphs
        shl     cx, 4
        sub     ax, cx
        sbb     dx, 0
        jb      .bad
        mov     [ex_left], ax
        mov     [ex_left+2], dx
        add     ax, 15
        adc     dx, 0
        mov     cx, 16
        div     cx                      ; AX = image paragraphs
        add     ax, 10h                 ; + the PSP
        mov     bx, ax
        add     ax, [ex_hdr+0Ah]        ; + minimum extra
        jc      .big
        mov     [ex_min], ax
        mov     ax, bx
        add     ax, [ex_hdr+0Ch]        ; + maximum extra
        jnc     .mx
        mov     ax, 0FFFFh
.mx:    cmp     ax, [ex_min]            ; (a header asking less than its minimum)
        jae     .mx2
        mov     ax, [ex_min]
.mx2:   mov     [ex_max], ax
        ; the environment: the parent's (or the one given) + the name
.env:   mov     ax, [ex_env]
        or      ax, ax
        jnz     .ge
        mov     es, [cur_psp]
        mov     ax, [es:2Ch]
        push    cs
        pop     es
.ge:    mov     [ex_srcenv], ax
        push    ds
        mov     ds, ax
        xor     si, si
.el:    lodsb                           ; to the double NUL
        or      al, al
        jnz     .el
        cmp     byte [si], 0
        je      .ee
        cmp     si, 32000
        jb      .el
.ee:    inc     si
        pop     ds
        mov     [ex_envlen], si
        mov     di, ex_name
        xor     al, al
        mov     cx, 132
        repne   scasb
        sub     di, ex_name             ; name length + NUL
        mov     bx, si
        add     bx, di
        add     bx, 2 + 15
        shr     bx, 4
.xe:    mov     dx, [cur_psp]           ; (KMT.INC: MULTITASK=1 makes these 5
        call    mem_alloc               ;  bytes a far jump to mt_xenv, which
.xr:    jc      .e1                     ;  comes back to .xr)
        mov     [ex_env], ax
        mov     es, ax
        xor     di, di
        mov     cx, [ex_envlen]
        push    ds
        mov     ds, [ex_srcenv]
        xor     si, si
        rep     movsb
        pop     ds
        mov     ax, 1
        stosw
        mov     si, ex_name
.nm:    lodsb
        stosb
        or      al, al
        jnz     .nm
        push    cs
        pop     es
        ; the program's memory
        call    mem_largest
        cmp     bx, [ex_min]
        jb      .nomem
        cmp     bx, [ex_max]
        jbe     .sz
        mov     bx, [ex_max]
.sz:    mov     [ex_size], bx
        mov     dx, [cur_psp]
        call    mem_alloc
        jc      .nomem
        mov     [ex_psp], ax
        dec     ax                      ; both blocks belong to the child
        mov     es, ax
        mov     ax, [ex_psp]
        mov     [es:1], ax
        mov     bx, [ex_env]
        dec     bx
        mov     es, bx
        mov     [es:1], ax
        ; its PSP
        mov     es, ax
        mov     dx, ax
        add     dx, [ex_size]
        mov     bx, [cur_psp]
        mov     ax, [ex_env]
        call    make_psp
        push    ds
        lds     si, [cs:ex_tail]        ; command tail (128 bytes)
        mov     di, 80h
        mov     cx, 128
        rep     movsb
        pop     ds
        push    ds
        lds     si, [cs:ex_fcb1]
        mov     di, 5Ch
        mov     cx, 16
        rep     movsb
        pop     ds
        push    ds
        lds     si, [cs:ex_fcb2]
        mov     di, 6Ch
        mov     cx, 16
        rep     movsb
        pop     ds
        push    cs
        pop     es
        ; load it
        mov     si, [ex_sft]
        cmp     byte [ex_isexe], 0
        jne     .lexe
        mov     word [si+S_POS], 0
        mov     word [si+S_POS+2], 0
        mov     word [si+S_CCL], 0
        mov     cx, [ex_left]
        mov     es, [ex_psp]
        mov     di, 100h
        call    file_read
        push    cs
        pop     es
        jc      .e2
        cmp     ax, [ex_left]           ; all of it?  (C:'s FAT read failed,
        jne     .e2s                    ;  Fail or Abort, or a chain shorter
                                        ;  than the size: a short count, no CF)
        mov     ax, [ex_psp]
        mov     [ex_cs], ax
        mov     [ex_ss], ax
        mov     word [ex_ip], 100h
        mov     ax, 0FFFEh
        cmp     word [ex_size], 1000h
        jae     .csp
        mov     ax, [ex_size]
        shl     ax, 4
        sub     ax, 2
.csp:   mov     [ex_sp], ax
        mov     es, [ex_psp]
        mov     di, ax
        mov     word [es:di], 0         ; RET goes to PSP:0 (INT 20h)
        push    cs
        pop     es
        jmp     .close
.lexe:  mov     ax, [ex_hdr+8]          ; the image starts after the header
        mov     dx, 16
        mul     dx
        mov     [si+S_POS], ax
        mov     [si+S_POS+2], dx
        mov     word [si+S_CCL], 0
        mov     ax, [ex_psp]
        add     ax, 10h
        mov     [ex_load], ax
        mov     [ex_seg], ax
.ld:    mov     ax, [ex_left]
        or      ax, [ex_left+2]
        jz      .rel
        mov     cx, 8000h
        cmp     word [ex_left+2], 0
        jne     .c1
        cmp     [ex_left], cx
        jae     .c1
        mov     cx, [ex_left]
.c1:    mov     es, [ex_seg]
        xor     di, di
        push    cx
        call    file_read
        pop     cx
        push    cs
        pop     es
        jc      .e2
        cmp     ax, cx
        jne     .e2s                    ; file shorter than its header says
        sub     [ex_left], ax
        sbb     word [ex_left+2], 0
        add     word [ex_seg], 800h
        jmp     .ld
.rel:   mov     ax, [ex_hdr+18h]        ; relocation table
        mov     [si+S_POS], ax
        mov     word [si+S_POS+2], 0
        mov     word [si+S_CCL], 0
        mov     bx, [ex_hdr+6]          ; entries
.rl:    or      bx, bx
        jz      .regs
        mov     cx, bx
        cmp     cx, 64
        jbe     .r1
        mov     cx, 64
.r1:    push    bx
        push    cx
        shl     cx, 2
        mov     di, ex_rel
        call    file_read
        pop     cx
        pop     bx
        push    cs
        pop     es
        jc      .e2
        shr     ax, 2                   ; all of them there?  (else entries
        cmp     ax, cx                  ;  nobody read: what ex_rel held)
        jne     .e2s
        sub     bx, cx
        mov     di, ex_rel
        mov     dx, [ex_load]
.rp:    mov     ax, [di+2]
        add     ax, dx
        mov     es, ax
        push    di
        mov     di, [di]
        add     [es:di], dx
        pop     di
        add     di, 4
        loop    .rp
        push    cs
        pop     es
        jmp     .rl
.regs:  mov     ax, [ex_load]
        add     ax, [ex_hdr+16h]
        mov     [ex_cs], ax
        mov     ax, [ex_hdr+14h]
        mov     [ex_ip], ax
        mov     ax, [ex_load]
        add     ax, [ex_hdr+0Eh]
        mov     [ex_ss], ax
        mov     ax, [ex_hdr+10h]
        mov     [ex_sp], ax
.close: mov     si, [ex_sft]
        mov     byte [si+S_REF], 0
        ; the parent waits: its stack (with this call's frame) in its PSP
        mov     es, [cur_psp]
        mov     ax, [bp+F_USP]
        mov     [es:2Eh], ax
        mov     ax, [bp+F_USS]
        mov     [es:30h], ax
        mov     es, [ex_psp]            ; the child ends back at the caller
        mov     ax, [bp+F_IP]
        mov     [es:0Ah], ax
        mov     ax, [bp+F_CS]
        mov     [es:0Ch], ax
        mov     ax, [ex_psp]
        mov     [cur_psp], ax
        mov     [dta+2], ax
        mov     word [dta], 80h
        ; and go
        cli
        mov     byte [indos], 0
        mov     ss, [ex_ss]
        mov     sp, [ex_sp]
        push    0202h
        push    word [ex_cs]
        push    word [ex_ip]
        mov     ax, [ex_psp]
        mov     ds, ax
        mov     es, ax
        xor     ax, ax
        xor     bx, bx
        mov     cx, 00FFh
        mov     dx, ds
        xor     si, si
        xor     di, di
        xor     bp, bp
        iret

.nomem: mov     es, [ex_env]            ; not enough memory
        call    mem_free
        push    cs
        pop     es
        mov     ax, 8
        jmp     .e1
.e2s:   mov     ax, 11                  ; bad format
.e2:    push    ax                      ; load failed: give everything back
        push    es
        mov     es, [ex_psp]            ; the handles it inherited (the
        call    close_all               ;  parent holds each: none commits)
        pop     es
        mov     ax, [ex_psp]
        call    mem_free_owner
        pop     ax
        jmp     .e1
.bad:   mov     ax, 11
        jmp     .e1
.big:   mov     ax, 8
.e1:    mov     si, [ex_sft]
        mov     byte [si+S_REF], 0
        jmp     .e0
.acc:   mov     ax, 5                   ; (nf_last leaves 5 alone)
.nf:    call    nf_last                 ; (a last part that is no name: 2,
.e0:    jmp     fail                    ;  as OPEN, as MS-DOS)

section .bss
ex_srcenv   resw 1
ex_envlen   resw 1
ex_seg      resw 1
section .text

; path_buf -> ex_name, fully qualified ("A:\DIR\NAME.EXE")
full_name:
        mov     si, path_buf
        mov     di, ex_name
        mov     al, [cur_drv]
        cmp     byte [si+1], ':'
        jne     .d
        mov     al, [si]
        sub     al, 'A'
        add     si, 2
.d:     push    ax
        add     al, 'A'
        mov     ah, ':'
        stosw
        pop     ax
        cmp     byte [si], '\'
        je      .rest
        push    si                      ; (a drive the kernel has?  get_path
        call    drv_present             ;  doesn't check: else no directory,
        jc      .cwe                    ;  and resolve refuses it)
        push    di
        call    cwd_of
        mov     si, di
        pop     di
.cw:    lodsb
        or      al, al
        jz      .cwe
        stosb
        jmp     .cw
.cwe:   pop     si
        cmp     byte [di-1], '\'
        je      .rest
        mov     al, '\'
        stosb
.rest:  cmp     di, ex_name + 127       ; (the environment has room for 128)
        jae     .long
        lodsb
        stosb
        or      al, al
        jnz     .rest
        clc
        ret
.long:  mov     byte [ex_name + 127], 0
        mov     ax, 3
        stc
        ret

; ---------------------------------------------------------------------
;  ending a program
; ---------------------------------------------------------------------
f_00:   xor     al, al
        jmp     terminate
f_4C:   mov     al, [bp+F_AX]
        jmp     terminate
f_31:   mov     ax, [bp+F_DX]           ; stay resident: DX paragraphs
        cmp     ax, 6
        jae     .k
        mov     ax, 6
.k:     mov     [term_keep], ax
        mov     byte [term_type], 3
        mov     al, [bp+F_AX]
        jmp     terminate
f_4D:   mov     ax, [last_exit]
        jmp     ok_ax

; end the current program with exit code AL (how: [term_type]).  Can be
; called from anywhere in the kernel; returns to the parent's EXEC call.
; .ah: AH = how, DS = KSEG (ES needn't be)
terminate:
        push    cs
        pop     ds
        push    cs
        pop     es
        mov     ah, [term_type]
.ah:    mov     [last_exit], ax
        mov     byte [term_type], 0
        mov     bx, [cur_psp]
        cmp     bx, [root_psp]
        je      root_restart            ; the Executive itself: start over
        mov     es, bx
        cmp     byte [last_exit+1], 3   ; a TSR keeps its files open
        je      .kf
        call    close_all
.kf:    push    ds                      ; INT 22h-24h back from its PSP
        push    es
        pop     ds
        xor     di, di
        mov     es, di
        mov     di, 22h * 4
        mov     si, 0Ah
        mov     cx, 6
        cli
        rep     movsw
        sti
        pop     ds
        mov     es, bx
        cmp     byte [last_exit+1], 3
        jne     .free
        push    bx
        mov     bx, [term_keep]
        call    mem_resize
        pop     bx
        jmp     .mem
.free:  call    ui_progend              ; (INT 33h forgets its handler)
        mov     ax, bx
.fcall: call    mem_free_owner          ; (KEMS.INC: ems_free_owner, if EMS)
.mem:   call    fat_flush
        mov     es, bx
        mov     dx, [es:16h]            ; parent
        mov     si, [es:0Ah]            ; where to go back to
        mov     cx, [es:0Ch]
        mov     [cur_psp], dx
        mov     [dta+2], dx
        mov     word [dta], 80h
        mov     es, dx
        mov     di, [es:2Eh]            ; the parent's stack and frame
        mov     ax, [es:30h]
        mov     es, ax
        mov     [es:di+F_IP], si
        mov     [es:di+F_CS], cx
        and     byte [es:di+F_FL], 0FEh
        cli
        mov     byte [indos], 0
        mov     ax, es
        mov     ss, ax
        mov     sp, di
        popa
        pop     ds
        pop     es
        iret

; tell the UI core that the program at BX ends (MOUSE33.INC's m33_gone)
ui_progend:
        mov     ax, [ui_seg]
        or      ax, ax
        jz      .x
        push    bx
        push    ds
        push    cs                      ; a far call: back to .r, to
        push    .r                      ;  [ui_seg]:m33_gone
        push    ax
        push    m33_gone
        retf
.r:     pop     ds
        pop     bx
.x:     ret

; INT 22h of the root, or the Executive asked to end: run it again
root_term:
root_restart:
        cli
        mov     ax, cs
        mov     ds, ax
        mov     es, ax
        mov     byte [indos], 0
        jmp     run_ui

; ---------------------------------------------------------------------
;  the built-in GPIB driver: install on INT 60h if there is a uPD7210
; ---------------------------------------------------------------------
section ovl
gpib_init:
        call    gp_chip_init
        mov     dx, gp_R_ADR0
        in      al, dx
        and     al, 1Fh
        cmp     al, gp_MYADDR
        jne     .no
        call    gp_bus_init
        push    es
        push    0
        pop     es
        cli
        mov     word [es:60h*4], gp_entry
        mov     [es:60h*4+2], cs
        mov     ax, [es:gp_IRQVEC*4]    ; INT 0Dh: ours from here on (the one
        mov     [gp_oldirq], ax         ;  found is kept for INT 0Dh's exception)
        mov     ax, [es:gp_IRQVEC*4+2]
        mov     [gp_oldirq+2], ax
        mov     word [es:gp_IRQVEC*4], gp_isr
        mov     [es:gp_IRQVEC*4+2], cs
        sti
        pop     es
        mov     byte [gp_ok], 1
        call    gp_irq_on               ; SRQ on IRQ 5 (GPIBIRQ=0 in LODE.INI:
.no:    ret                             ;  off again, KMDISK.INC's md_boot)
section .text
