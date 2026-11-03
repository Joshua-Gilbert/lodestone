; =====================================================================
;  KSPLASH.INC - the bootstrap for the start-up picture
;
;  The picture is a program of its own, \LODE.PIC (SPLASH.ASM).  At the
;  end of start-up, once INT 21h works, this reads SPLASH= in \LODE.INI
;  (0, No or Off: no picture), reads LODE.PIC into free memory past the
;  load image (PIC_SEG:0000), checks its signature and length, and calls
;  it: it draws, waits 2 seconds or for a key, and returns.  Then on to M:'s
;  start-up or the Executive, which take that memory over.  No LODE.PIC on
;  the disk, or not a real one: no picture, nothing else changes.
;
;  It lives in section boot: it runs from the load image and is never
;  kept, so DOS programs get as much as before.
; =====================================================================
section boot

PIC_SEG equ 2000h                       ; LODE.PIC here: inside the arena's
                                        ;  free block at this point, past
                                        ;  the load image.  (The UI block,
                                        ;  the only one below, ends near
                                        ;  1200h: one reaching this far
                                        ;  would have wiped this code first.)
PIC_MAX equ 0C000h                      ; the most of it read (the rest of
                                        ;  the segment is its scratch)
SP_BUF  equ 0F000h                      ; (the load image's segment)
                                        ;  \LODE.INI, up to 4 KB, as md_boot's
                                        ;  MD_IBUF: it reads it after us

; hd_init's last jump (DS = ES = KSEG).  init ends through a far jump at
; KSEG:0000, as for KMDISK.INC's md_boot: to sp_boot here, which goes on
; to md_boot if ems_init put that jump there, or else to run_ui.
sp_hook:
        cld
        cmp     byte [0], 0EAh          ; JMP FAR md_boot there already?
        jne     .own
        mov     ax, [1]                 ; (then md_boot puts `start's
        mov     [cs:MDB(sp_next)], ax   ;  bytes back)
        mov     ax, [3]
        mov     [cs:MDB(sp_next) + 2], ax
        jmp     short .j
.own:   push    cs                      ; `start's first 5 bytes, to put
        pop     es                      ;  back
        xor     si, si
        mov     di, MDB(sp_s0)
        movsw
        movsw
        movsb
        push    ds
        pop     es
        mov     byte [cs:MDB(sp_back)], 1
        mov     byte [0], 0EAh
        xor     ax, ax                  ; JMP NEAR 0000h
        sub     ax, init.go + 3
        mov     [init.go + 1], ax
.j:     mov     word [1], MDB(sp_boot)
        mov     word [3], 1000h
        jmp     KSEG:init

; init's last jump, through KSEG:0000 (CS = 1000h)
sp_boot:
        cli
        mov     ax, KSEG
        mov     ds, ax
        mov     ss, [ui_seg]            ; (run_ui's stack, as md_boot's:
        mov     sp, ui_stack_top        ;  nothing on it yet)
        sti
        cld
        mov     es, ax
        push    cs
        pop     ds
        cmp     byte [MDB(sp_back)], 0
        je      .on
        mov     si, MDB(sp_s0)          ; KSEG:0000 as `start' left it
        xor     di, di
        movsw
        movsw
        movsb
.on:    call    rs_boot                 ; (KROM.INC: booted from the ROM)
        call    pr_boot                 ; PrtSc's printer driver
        cmp     word [MDB(sp_next)], run_ui ; TEMP=: in the environment (with
        jne     .tm                     ;  EMS, md_boot's, once M: is made)
        call    te_boot
.tm:
        call    gi_boot                 ; GPIBIRQ=0: GPIB's SRQ interrupt off
        call    fp_boot                 ; a coprocessor that can't store: none
        call    sp_wanted
        jc      .go
        call    sp_load
        jc      .go
        call    PIC_SEG:0000h           ; the picture: drawn, 2 s, back
.go:    jmp     far [cs:MDB(sp_next)]

; GPIBIRQ=0 in the settings (the first such line, the changes' before the
; ROM's): the built-in GPIB driver's SRQ interrupt off (KGPIB.INC turns it
; on at init, when the driver is in).  Another value leaves it on.  DS = CS.
gi_boot:
        call    ini_read                ; (KROM.INC: LODE.INI's, both)
        mov     di, MDB(s_gieq)         ; "GPIBIRQ=" (any case)?
        call    ini_key
        jc      .x
        cmp     byte [si], '0'
        jne     .x
        push    es
        push    0
        pop     es
        les     bx, [es:60h*4]
        cmp     word [es:bx+2], 'GR'    ; ('GRIDGPIB' at the driver's entry
        pop     es                      ;  + 2: no 7210, no driver)
        jne     .x
        mov     ax, 0E00h
        int     60h
.x:     ret

; The coprocessor INT 11h reports, tried once before anything uses it:
; one FNSTENV, 7 words to memory, as every program storing a result moves
; several.  A 287XL in the 1520 was seen to take one-word stores (POST's,
; the Executive's FNSTSW AX) but hang on every longer one, BUSY held with
; interrupts off: a frozen machine at MT's first FNSAVE, or CALC's first
; result.  The 286 waits on BUSY with interrupts on, so a tick hooked here
; ends it: at the third (110-165 ms) it clears BUSY's latch (F0h, as the
; BIOS's INT 75h) and resets the chip (F1h, as POST); the store returns,
; and from then on INT 11h says no coprocessor (40:10h bit 1), so CALC,
; MT and the Executive leave it alone.  A working chip takes microseconds.
; DS = CS.  (-dFPTEST: the store made one that never ends, for test_kernel)
fp_boot:
        int     11h
        test    al, 2
        jz      .x
        push    es
        xor     ax, ax
        mov     es, ax
        mov     byte [MDB(fp_n)], 0
        mov     byte [MDB(fp_dead)], 0
        cli
        mov     ax, [es:8 * 4]
        mov     [MDB(fp_old)], ax
        mov     ax, [es:8 * 4 + 2]
        mov     [MDB(fp_old) + 2], ax
        mov     word [es:8 * 4], MDB(fp_t8)
        mov     [es:8 * 4 + 2], cs
        sti
        fninit
%ifdef FPTEST
.w:     cmp     byte [MDB(fp_dead)], 0
        je      .w
%else
        fnstenv [MDB(fp_buf)]
        fwait
%endif
        cli
        mov     ax, [MDB(fp_old)]
        mov     [es:8 * 4], ax
        mov     ax, [MDB(fp_old) + 2]
        mov     [es:8 * 4 + 2], ax
        sti
        cmp     byte [MDB(fp_dead)], 0
        je      .ok
        and     byte [es:410h], ~2      ; no coprocessor, from here on
        jmp     short .y
.ok:    fninit
.y:     pop     es
.x:     ret

; fp_boot's tick: the BIOS's first, then the third one ends the store
fp_t8:  pushf
        call    far [cs:MDB(fp_old)]
        inc     byte [cs:MDB(fp_n)]
        cmp     byte [cs:MDB(fp_n)], 3
        jb      .x
        mov     byte [cs:MDB(fp_dead)], 1
        push    ax
        xor     al, al
        out     0F0h, al                ; BUSY's latch cleared
        out     0F1h, al                ; the coprocessor reset
        pop     ax
.x:     iret

; CF if the settings say SPLASH=0 (or No, or Off).  DS = CS.
sp_wanted:
        call    ini_read                ; (KROM.INC: LODE.INI's, both)
        mov     di, MDB(s_speq)         ; "SPLASH=" (any case)?
        call    ini_key
        jc      .yes                    ; (no such line)
        mov     al, [si]
        cmp     al, '0'
        je      .no
        and     al, 0DFh
        cmp     al, 'N'                 ; No
        je      .no
        cmp     al, 'O'                 ; Off (and not On)
        jne     .yes
        mov     al, [si+1]
        and     al, 0DFh
        cmp     al, 'F'
        je      .no
.yes:   clc
        ret
.no:    stc
        ret

; PRINTER=NAME in the settings (the first such line, the changes' before
; the ROM's; "PRINTER=": none) -> the kernel's prn_path, where PATH finds
; it: from the ROM C:\LODE\NAME if it is there, else the root of the
; drive started from.  Only the path is kept; KCORE.INC's capture reads
; the driver at PrtSc.  DS = CS, ES = KSEG.
pr_boot:
        push    KSEG
        pop     es
        mov     ax, 3305h               ; SCREEN.PRN (Shift-PrtSc's file
        int     21h                     ;  writer, KC-2): in the root of the
        add     dl, 'A' - 1             ;  drive started from (R:\ from the
        mov     [es:scr_path], dl       ;  ROM)
        call    ini_read                ; (KROM.INC: LODE.INI's, both)
        mov     di, MDB(s_preq)         ; "PRINTER=" (any case)?
        call    ini_key
        jc      .x                      ; (no such line)
        cmp     byte [si], ' '          ; ("PRINTER=": none)
        jbe     .x
        mov     ax, 3305h
        int     21h
        add     dl, 'A' - 1
        mov     [MDB(s_prroot)], dl
        cmp     dl, 'R'
        jne     .root
        push    si
        mov     bx, MDB(s_prlode)       ; from the ROM: C:\LODE's first
        call    .cp
        pop     si
        push    ds
        push    es
        pop     ds
        mov     dx, prn_path
        mov     ax, 4300h
        int     21h
        pop     ds
        jnc     .x
.root:  mov     bx, MDB(s_prroot)
; ES:prn_path = the string at BX, then the name at SI (to a blank or the
; line's end, 12 characters at most)
.cp:    mov     di, prn_path
.p:     mov     al, [bx]
        inc     bx
        or      al, al
        jz      .n
        stosb
        jmp     .p
.n:     mov     cx, 12
.nm:    lodsb
        cmp     al, ' '
        jbe     .z
        stosb
        loop    .nm
.z:     xor     al, al
        stosb
.x:     ret

; TEMP=DIR in the settings (the first such line, the changes' before the
; ROM's; "TEMP=": none) -> TEMP=DIR at the end of the master environment
; (after rs_boot's), so every program's %TEMP%: CLAUDE.COM's CLAUDE.OUT
; (the ROM's LODE.INI says M:\, not the current drive R:, X51).  The value
; to a blank or the line's end, 64 characters at most.  A drive that isn't
; there (M: off, or no EMS) sets none: CLAUDE.OUT on the current drive, C:
; with the hard disk.  So with EMS md_boot calls it, M: made (or not), and
; past md_split: the environment's 160 bytes hold COMSPEC, PATH, PROMPT
; (50) and this (71).  DS = CS, ES = KSEG.
te_boot:
        call    ini_read                ; (KROM.INC: LODE.INI's, both)
        mov     di, MDB(s_teeq)         ; "TEMP=" (any case)?
        call    ini_key
        jc      .x                      ; (no such line)
        cmp     byte [si], ' '          ; ("TEMP=": none)
        jbe     .x
        cmp     byte [si+1], ':'        ; a drive: there?
        jne     .ok
        mov     dl, [si]
        and     dl, 0DFh
        sub     dl, 'A' - 1             ; (1 = A:)
        push    si
        push    ds
        push    ss                      ; (its current directory into
        pop     ds                      ;  bytes of the stack, f_47's most:
        sub     sp, CWDLEN              ;  INT 21h 47h, 15 if the drive
        mov     si, sp                  ;  isn't there)
        mov     ah, 47h
        int     21h
        lea     sp, [si+CWDLEN]
        pop     ds
        pop     si
        jc      .x
.ok:    push    es
        mov     es, [es:ex_env]
        xor     di, di
        xor     al, al
        mov     cx, 160
.e:     scasb                           ; (the empty string that ends it?)
        je      .at
        dec     di
        repne   scasb                   ; past this string
        jmp     .e
.at:    dec     di
        mov     bx, MDB(s_teeq)
        mov     cx, 4                   ; "TEMP"
.k:     mov     al, [bx]
        inc     bx
        stosb
        loop    .k
        mov     al, '='
        stosb
        mov     cx, 64
.v:     lodsb
        cmp     al, ' '
        jbe     .z
        stosb
        loop    .v
.z:     xor     ax, ax                  ; its NUL, and the environment's
        stosw
        pop     es
.x:     ret

; \LODE.PIC into PIC_SEG:0000.  CF if there is none, or it isn't one: its
; signature, after a JMP SHORT, is "LODEPIC", 1, and the word after it is
; its length, exactly what was read (a cut-short copy isn't run).  DS = CS.
sp_load:
        mov     ax, 3305h               ; on the drive started from
        int     21h
        add     dl, 'A' - 1
        mov     [MDB(s_sppic)], dl
        mov     dx, MDB(s_sppic)
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     bx, ax
        push    ds
        push    PIC_SEG
        pop     ds
        xor     dx, dx
        mov     cx, PIC_MAX
        mov     ah, 3Fh
        int     21h
        pop     ds
        jnc     .rd
        xor     ax, ax                  ; (a read error: as if empty)
.rd:    push    ax
        mov     ah, 3Eh
        int     21h
        pop     cx
        cmp     cx, 16
        jb      .no
        push    es
        push    PIC_SEG
        pop     es
        mov     si, MDB(s_picsig)
        mov     di, 2
        push    cx
        mov     cx, 8
        repe    cmpsb
        pop     cx
        jne     .ne
        cmp     cx, [es:10]             ; (the length it says it has)
.ne:    pop     es
        jne     .no
        clc
        ret
.no:    stc
.x:     ret

s_speq  db      'SPLASH', 1Dh, 0        ; (as "SPLASH=" AND 0DFh)
s_preq  db      'PRINTER', 1Dh, 0       ; (as "PRINTER=" AND 0DFh)
s_gieq  db      'GPIBIRQ', 1Dh, 0       ; (as "GPIBIRQ=" AND 0DFh)
s_teeq  db      'TEMP', 1Dh, 0          ; (as "TEMP=" AND 0DFh)
s_prlode db     'C:\LODE\', 0
s_prroot db     '@:\', 0
s_sppic db      '@:\LODE.PIC', 0
s_picsig db     'LODEPIC', 1
sp_next dw      run_ui, KSEG            ; where to after (or md_boot)
sp_s0   db      0, 0, 0, 0, 0           ; KSEG:0000's 5 bytes, if ours
sp_back db      0                       ;  (1: put them back)
fp_old  dd      0                       ; fp_boot's: the BIOS's INT 08h,
fp_n    db      0                       ;  ticks while it waits, 1 if they
fp_dead db      0                       ;  ended the store, and the store's
fp_buf  times 14 db 0                   ;  14 bytes
