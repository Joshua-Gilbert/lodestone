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
        call    sp_wanted
        jc      .go
        call    sp_load
        jc      .go
        call    PIC_SEG:0000h           ; the picture: drawn, 2 s, back
.go:    jmp     far [cs:MDB(sp_next)]

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
s_prlode db     'C:\LODE\', 0
s_prroot db     '@:\', 0
s_sppic db      '@:\LODE.PIC', 0
s_picsig db     'LODEPIC', 1
sp_next dw      run_ui, KSEG            ; where to after (or md_boot)
sp_s0   db      0, 0, 0, 0, 0           ; KSEG:0000's 5 bytes, if ours
sp_back db      0                       ;  (1: put them back)
