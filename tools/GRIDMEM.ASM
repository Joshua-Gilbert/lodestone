; =====================================================================
;  GRIDMEM.COM - GRiDCase 1520 memory mode utility            (Lodestone)
;  Build: nasm -f bin -o GRIDMEM.COM GRIDMEM.ASM
;
;  GRIDMEM        show current mode and sizes
;  GRIDMEM EXT    memory above 640K = EXTENDED (for HIMEM/XMS)  -> reboot
;  GRIDMEM EMS    memory above 640K = EMS (bank-switched)        -> reboot
;
;  Uses the GRiD BIOS extension INT 15h AH=E4h (found in BIOS 10/25/89):
;    AX=E440h  -> CX = EMS KB   (CMOS 17/18 if EMS mode, else 0)
;    AX=E441h  -> CX = ext KB   (CMOS 17/18 if extended mode, else 0)
;    AX=E442h  DL=FFh query -> DL = mode (1 = EMS, 0 = extended)
;              DL=0/1 set   -> CMOS 3Fh bit 0 (bit 1 kept, rest cleared)
;  Success = AH 00h.  The mode is applied by POST on the next boot.
;  NOTE: the E4h dispatcher groups AL by (AL>>4)&0FEh - E420-E43F are
;  display/port-07F8h functions, E440-E45F the memory/system group.
;  Refuses to run unless the BIOS date is 10/25/89 (the ROM this was
;  reverse-engineered from); GRIDMEM /F overrides.
; =====================================================================
cpu 286
org 100h

start:  mov     dx, s_title
        call    puts
        ; ---- BIOS guard: F000:FFF5 must read 10/25/89 ---------------
        push    ds
        mov     ax, 0F000h
        mov     ds, ax
        mov     si, 0FFF5h
        mov     di, biosdate
        mov     cx, 8
        repe    cmpsb
        pop     ds
        je      .bok
        mov     si, 81h                 ; allow /F override
.fs:    lodsb
        cmp     al, 13
        je      .bad
        cmp     al, '/'
        jne     .fs
        mov     al, [si]
        or      al, 20h
        cmp     al, 'f'
        je      .bok
.bad:   mov     dx, s_badbios
        call    puts
        mov     ax, 4C04h
        int     21h
.bok:

        ; ---- parse argument: first non-blank word -------------------
        mov     si, 81h
.sk:    lodsb
        cmp     al, ' '
        je      .sk
        cmp     al, 9
        je      .sk
        cmp     al, 13
        je      .show                   ; no argument
        or      al, 20h
        mov     ah, [si]
        or      ah, 20h
        mov     bl, [si+1]
        or      bl, 20h
        cmp     al, 'e'
        jne     .usage
        cmp     ah, 'x'
        jne     .notx
        cmp     bl, 't'
        jne     .usage
        mov     byte [want], 0
        jmp     .show
.notx:  cmp     ah, 'm'
        jne     .usage
        cmp     bl, 's'
        jne     .usage
        mov     byte [want], 1
        jmp     .show
.usage: mov     dx, s_usage
        call    puts
        mov     ax, 4C01h
        int     21h

        ; ---- report current state -----------------------------------
.show:  call    getmode                 ; AL = mode or CF
        jc      nogrid
        mov     [cur], al
        call    report

        cmp     byte [want], 0FFh
        je      .exit
        mov     al, [want]
        cmp     al, [cur]
        jne     .set
        mov     dx, s_already
        call    puts
        jmp     .exit

.set:   mov     dl, [want]
        mov     ax, 0E442h
        clc
        int     15h
        or      ah, ah
        jnz     setfail
        call    getmode
        jc      setfail
        cmp     al, [want]
        jne     setfail
        mov     dx, s_setext
        cmp     byte [want], 0
        je      .p
        mov     dx, s_setems
.p:     call    puts
        mov     dx, s_reboot
        call    puts
.exit:  mov     ax, 4C00h
        int     21h

nogrid: mov     dx, s_nogrid
        call    puts
        mov     ax, 4C02h
        int     21h

setfail:
        mov     dx, s_fail
        call    puts
        mov     ax, 4C03h
        int     21h

; AL = 1 EMS / 0 extended, CF on failure
getmode:
        mov     dl, 0FFh
        mov     ax, 0E442h
        clc
        int     15h
        or      ah, ah
        jnz     .f
        cmp     dl, 1
        ja      .f
        mov     al, dl
        clc
        ret
.f:     stc
        ret

report: mov     dx, s_mode
        call    puts
        mov     dx, s_ext
        cmp     byte [cur], 0
        je      .m
        mov     dx, s_ems
.m:     call    puts
        mov     dx, s_cmos
        call    puts
        mov     al, 3Fh
        call    rdcmos
        call    phex8
        mov     dx, s_close
        call    puts

        mov     dx, s_emssz
        call    puts
        xor     cx, cx
        mov     dl, 0FFh
        mov     ax, 0E440h
        int     15h
        mov     ax, cx
        call    pdec
        mov     dx, s_kb
        call    puts

        mov     dx, s_extsz
        call    puts
        xor     cx, cx
        mov     dl, 0FFh
        mov     ax, 0E441h
        int     15h
        mov     ax, cx
        call    pdec
        mov     dx, s_kb
        call    puts

        mov     dx, s_i88
        call    puts
        mov     ah, 88h
        clc
        int     15h
        jnc     .ok
        xor     ax, ax
.ok:    call    pdec
        mov     dx, s_kb
        call    puts
        ret

rdcmos: cli
        out     70h, al
        jmp     short $+2
        in      al, 71h
        sti
        ret

puts:   push    ax
        mov     ah, 09h
        int     21h
        pop     ax
        ret

putc:   push    ax
        push    dx
        mov     dl, al
        mov     ah, 02h
        int     21h
        pop     dx
        pop     ax
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

s_title db 'GRIDMEM 1.1 - GRiDCase memory mode (Lodestone)',13,10,'$'
s_usage db 'Usage: GRIDMEM [EXT | EMS]',13,10
        db '  EXT  memory above 640K becomes extended (HIMEM/XMS)',13,10
        db '  EMS  memory above 640K becomes bank-switched EMS',13,10,'$'
s_mode  db 'Memory mode     : $'
s_ext   db 'EXTENDED$'
s_ems   db 'EMS$'
s_cmos  db '  (CMOS 3Fh = $'
s_close db 'h)',13,10,'$'
s_emssz db 'EMS memory      : $'
s_extsz db 'Extended memory : $'
s_i88   db 'INT 15h/88h     : $'
s_kb    db ' KB',13,10,'$'
s_already db 'Already in that mode - nothing changed.',13,10,'$'
s_setext db 13,10,'Mode set to EXTENDED.',13,10,'$'
s_setems db 13,10,'Mode set to EMS.',13,10,'$'
s_reboot db 'Press Ctrl-Alt-Del (or power-cycle) so POST re-sizes memory.',13,10,'$'
s_nogrid db '** GRiD BIOS memory function (INT 15h E4h) not found.',13,10,'$'
s_fail  db '** BIOS did not accept the change.',13,10,'$'
s_badbios db '** This is not the 10/25/89 GRiDCase 1520 BIOS - refusing to call',13,10
        db '** undocumented BIOS functions. (GRIDMEM /F to override.)',13,10,'$'
biosdate db '10/25/89'
want    db 0FFh
cur     db 0
