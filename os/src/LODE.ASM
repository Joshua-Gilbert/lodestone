; =====================================================================
;  LODE.SYS  -  Lodestone 0.6 kernel for the GRiDCase 1520
;  nasm -f bin -o LODE.SYS LODE.ASM
;
;  A small DOS 3.30-compatible kernel plus the GRiD-style Executive.
;  Loaded by the Lodestone boot sector to 1000:0000 (DL = boot drive,
;  DS:SI -> boot sector), it moves itself down to 0060:0000 and stays
;  resident there:
;
;    KCORE  INT 21h through one entry frame, console, clock, misc INTs
;    KMEM   MCB memory arena
;    KDISK  floppy sector driver (whole runs, track/DMA splits), FAT12
;           cache, sector buffers, critical errors
;    KFAT   names, paths, directories, clusters
;    KFILE  handles (SFT + per-process JFT), files and devices (CON, NUL,
;           AUX, PRN, COM1/2, LPT1, GPIBnn), find first/next, dir calls
;    KPROC  PSP, environment, EXEC (.COM/.EXE), terminate, TSR, ^C
;    KGPIB  the GRIDGPIB driver on INT 60h (same API and signature)
;    KEMS   the EMS manager (LIM 4.0, INT 67h) - only resident when the
;           machine has EMS: it follows the kernel image in this file,
;           and its start-up puts it above the BSS and keeps it, or not
;    KHD    the internal hard disk as C: (AT bus, FAT16) - the same way,
;           only resident when there is one: after EMS
;    KMDISK M:, the temporary disk, in EMS: its installer in the disk
;           cache's EMS, its resident part only while M: is on, split off
;           the master environment's block
;    KSPLASH the start-up picture's bootstrap: loads, runs and drops
;           \LODE.PIC (SPLASH.ASM); load image only, never resident
;    KMT    multitasking, only with MULTITASK=1 (and EMS): its start-up
;           here (load image only), its resident part a file of its own,
;           LODEMT.SYS, read into a block at the top of memory
;
;  The UI segment (section ui, our COMMON.SHR) follows the kernel in this
;  file.  At start-up it is copied into a block of its own (owner 8, "UI")
;  just above the root PSP, and the root process runs there:
;    UICORE the UI core: jump table (UIAPI.INC), events, drawing, windows,
;           lists, forms, the screen saver, the .RUN loader
;    EXEC   the Executive: GRiD-style file list that runs programs
;  It talks to the kernel only through INT 21h, like any program.
;
;  Register convention inside the kernel: DS = ES = KSEG unless a routine
;  says otherwise; BP = the INT 21h frame while a call is in progress;
;  failures return CF set and AX = DOS error code.
; =====================================================================
cpu 286
org 0

KSEG    equ 0060h               ; where the kernel lives
VERSION equ 0006h               ; Lodestone 0.6

section .bss nobits align=16 follows=.text
bss_start:                      ; = image_end (KCORE.INC's CAP_SEG counts on it)
; KEMS.INC: in the file right after the kernel image (at image_end), in
; memory right after the BSS (where ems_init copies it), its data after it
; in memory only (emsbss); KHD.INC's module after it; then both start-ups
; (in the load image only).  ems is image_end - bss_end from where it runs
; in the load image, hd and boot that less emsbss: they find themselves by
; section.hd.start and section.boot.start (MDB).
section ems progbits align=16 follows=.text vfollows=.bss valign=16
section emsbss nobits vfollows=ems valign=1     ; (KEMS.INC's data: valign=1
section hd progbits align=16 follows=ems vfollows=emsbss valign=16  ;  keeps it
                                                ;  where it was, after the code)
section boot progbits align=16 follows=hd vfollows=hd valign=16
; KMDISK.INC: M:'s installer, its resident part's image and that image's
; relocations, after the start-ups in the file; ems_init copies them into
; the disk cache's EMS (the installer runs there, at E000:MD_TPG)
%define MDB(x) (section.boot.start + ((x) - section.boot.vstart))   ; (in the load image)
MD_TPG  equ 1000h                       ; (its place in the cache's second page)
section mdt progbits align=16 follows=boot vstart=MD_TPG
; KROM.INC: R:'s resident part, assembled from 0 and relocated where it goes
section rmt progbits align=16 follows=mdt vstart=0
; the start-up code, run in the place of the disk buffers (in KSEG): see
; init.  (A constant: the assertions at the end of this file keep it
; inside them.)
OVL_AT  equ 5800h
section ovl progbits align=16 follows=rmt vstart=OVL_AT
section .text

start:  cli                     ; at 1000:0000 from the boot sector
        mov     ax, 2000h       ; temporary stack clear of the image
        mov     ss, ax
        mov     sp, 0FFFEh
        sti
        cld
        push    cs
        pop     es
        mov     di, section.ovl.start + (bootbpb - init)  ; (in this image)
        mov     cx, 64
        rep     movsb           ; BPB from DS:SI (the boot sector)
        mov     [cs:bootdrv], dl
        push    cs
        pop     ds
        mov     ax, KSEG
        mov     es, ax
        xor     si, si
        xor     di, di
        mov     cx, (image_end - start + 1) / 2
        rep     movsw
        mov     si, section.ovl.start   ; and the start-up code (section ovl)
        mov     di, OVL_AT              ;  where the disk buffers will be
        mov     cx, (ovl_end - init) / 2
        rep     movsw
        jmp     section.boot.start + (rom_menu - section.boot.vstart)   ; KROM.INC's, in this
                                        ; image (then KEMS.INC's ems_init,
                                        ; KHD.INC's hd_init, KROM.INC's
                                        ; rom_init, then KSEG:init)

; ---------------------------------------------------------------------
;  Start-up only (section ovl): copied by `start' into the place of the
;  disk buffers, which nothing uses until init has gone (no disk is read
;  before INT 21h is hooked), patched there by the start-ups, run once.
;  Nothing returns into it after init's last jump.
; ---------------------------------------------------------------------
section ovl
init:   cli
        mov     ax, cs
        mov     ds, ax
        mov     es, ax
        mov     ss, ax
        mov     sp, kstack_top
        sti
        xor     al, al                  ; clear the BSS (nothing on the stack
        mov     di, bss_start           ;  yet), all but this code
        mov     cx, OVL_AT
        sub     cx, di
        rep     stosb
        mov     di, ovl_end
        mov     cx, bss_end - ovl_end
        rep     stosb
        call    ivt_init
        call    sft_init
        call    mem_init
.cdrv:  call    drv_init                ; (KHD.INC: hd_drv_init, with C:)
        call    clock_init
        call    gpib_init
        call    proc_init               ; master environment + root PSP
        call    ui_load
.go:    jmp     near run_ui             ; (KSPLASH.INC: to LODE.PIC's bootstrap,
                                        ;  then KMDISK.INC: to M:'s start-up)

; The UI section from the loaded file (still at 1000:section.ui.start)
; into a block of its own; then its BSS cleared.  Allocated at its image
; size first, so the block's new MCB can't land on the image being copied.
; Section uiboot, the UI's start-up (next in the file), goes into the top
; of its directory buffer, which the block grows over at once (all far
; below the file's copy: nothing it still needs is in the way), and isn't
; cleared: it runs once, from exec_main, before the directory is read.
ui_load:
        mov     bx, UI_IMG_PARAS
        mov     dx, 8
        call    mem_alloc
        jc      .fail
        mov     [ui_seg], ax
        mov     es, ax
        push    ds
        mov     ax, 1000h
        mov     ds, ax
        mov     si, section.ui.start
        xor     di, di
        mov     cx, (ui_image_end - ui_base) / 2
        rep     movsw
        mov     di, UIBOOT_ORG          ; (SI = section.uiboot.start)
        mov     cx, UIBOOT_WORDS
        rep     movsw
        pop     ds
        mov     bx, UI_PARAS            ; + BSS and stack
        call    mem_resize
        jc      .fail
        mov     di, ui_bss_start
        mov     cx, UIBOOT_ORG
        sub     cx, di
        xor     al, al
        rep     stosb
        mov     ax, es
        dec     ax
        mov     es, ax
        mov     word [es:8], 'UI'
        push    cs
        pop     es
        ret
.fail:  mov     si, s_nouimem
.p:     lodsb
        or      al, al
        jz      .h
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     .p
.h:     hlt
        jmp     .h
s_nouimem   db 'Lodestone: not enough memory for the Executive', 13, 10, 0
section .text

; enter (or re-enter) the root process: the Executive, on its own stack
run_ui: cli
        mov     ax, [cs:ui_seg]
        mov     ss, ax
        mov     sp, ui_stack_top
        sti
        push    ax
        push    word exec_main
k_retf: retf                            ; (KMT.INC's KCALL returns through it)


%include "KCORE.INC"
%include "KMEM.INC"
%include "KDISK.INC"
%include "KFAT.INC"
%include "KFILE.INC"
%include "KPROC.INC"
%include "KGPIB.INC"

; The routines and loop targets most often reached by a taken jump, call or
; return (measured in pcemu: BENCH, LCMD's DIR/TYPE/COPY, the Executive, a
; CLAUDE link turn) start on even offsets: the 286 fetches words, so a jump
; to an odd one costs a fetch.  The pads that put them there ("hot" in the
; comment) are never executed.  A TIMES value of -1 here: that label went
; odd, so re-pad (KSEG is a paragraph, so the offset's parity is the address's)
; To measure and place them again: bench/hot.py (the counts), bench/plan.py
; (where the pads go), bench/evalpar.py (one build against another)
%macro EVEN 1-*
%rep %0
        times -((%1 - $$) & 1) db 0
%rotate 1
%endrep
%endmacro
section .text
        EVEN    capture, int21, int21.stk, ret_cf, ok, done, done.sw, fail, ret_cfax, ok_ax
        EVEN    f_02, tty_out, con_out, con_out.x
        EVEN    h2sft, sft_of, jft_alloc.l, sft_busy.l, sft_busy.n, f_3F, f_40, sft_read
        EVEN    rw_start, rw_step, use_drive_si, sft_cluster, sft_cluster.w, sft_cluster.got
        EVEN    rw_where.one, file_read.loop, file_read.ext, file_read.go, file_read.part
        EVEN    sec_of, pos_sec, rw_setra, file_write.loop
        EVEN    use_drive, fat_load, fat_get, fat_get.e, fat_flush.k, fat_flush.run, fat_flush.dirty
        EVEN    fat_set.one, clu2lba
        EVEN    buf_getd, buf_get, buf_get.s, buf_get.f, buf_get.n, buf_get.hit
        EVEN    disk_io, dio.more, dio.ok, tc_piece, tc_mine
        EVEN    gpath.n, gpath.s, parse_comp.fl, parse_comp.chk, f_36.l
        EVEN    dir_entry, dir_entry.sub, dir_entry.walk, dir_entry.there, dir_entry.x
        EVEN    dir_find.e, dir_find.n, name_match.l, name_match.n, name_match.x
        EVEN    dev_look_ax.f, dev_look_ax.t, dev_look_ax.skip
        EVEN    gp_cmd_begin, gp_send_cmd, gp_wait_co, gp_wait_co.ok, gp_tick, gp_tmo_start, gp_wait_tick.w
        EVEN    gp_handler.go, gp_isr

section ovl
bootbpb     times 64 db 0
            align 2
ovl_end:
section .text
bootdrv     db 0
capdrv      db 'A'                      ; screen captures go here (from the ROM:
                                        ;  C:, else A:; KROM.INC's rs_boot)
setdrv      db 0                        ; INT 21h 3305h's DH: the drive (1 = A:)
                                        ;  whose LODE.INI goes over the boot
                                        ;  drive's (KROM.INC; 0: none)
lastdrv     db 2                        ; INT 21h 0Eh's count: A: and B:, 3 with
                                        ;  C: (KHD.INC), 13 with M: (KMDISK.INC),
                                        ;  18 with R: (KROM.INC)
            align 16                    ; (free: the BSS starts on a paragraph;
                                        ;  none at lastdrv 40EFh.  The EVEN pads
                                        ;  make a change before gp_isr's move
                                        ;  this by its size +-1, so in steps of 2)
image_end:                              ; everything above is copied low;
                                        ; the EMS section starts right here
section .bss
            alignb 16
bss_end:

section ems
ems_start:
%include "KEMS.INC"
section hd
hd_start:
%include "KHD.INC"
%include "KMDISK.INC"
%include "KSPLASH.INC"                 ; (section boot: LODE.PIC's bootstrap)
%include "KROM.INC"                    ; (R:, the ROM; section rmt, and boot)

; =====================================================================
;  The UI segment: offsets from 0 in a segment of its own
; =====================================================================
section ui progbits align=16 follows=ovl vstart=0
section uibss nobits valign=16 vfollows=ui
; alignb would clash with vfollows in NASM's bin output (it sets a "real"
; section alignment); uibss starts on a paragraph, so this is the same thing
%define ualignb(n) resb ((n) - (($ - $$) % (n))) % (n)
ui_bss_start:
section uiboot                          ; (its attributes at the end: it runs
uiboot_start:                           ;  at UIBOOT_ORG, known only there)
section ui
%include "UICORE.INC"                   ; (the jump table is at offset 0)
%include "EXEC.INC"
%include "FONT.INC"
            align 2
ui_image_end:

section uibss
            ualignb(2)
            resb 2560
ui_stack_top:                           ; the Executive's (and .RUNs') stack
ui_keep_end:                            ; while a DOS program runs, the UI
entries     resb 32 * MAXENT            ;  block lets go of the Executive's
ui_bss_end:                             ;  directory (it reads it again after)                             ; (no alignb 16 here: in a vfollows
                                        ;  section it would clash in NASM)

; The UI block's sizes in paragraphs, folded by NASM: uibss starts on the
; paragraph after ui_image_end (vfollows, valign=16), so each is the image's
; paragraphs plus the BSS's to that label (the assertion at the end of the
; file: nothing goes into section ui after ui_image_end)
UI_IMG_PARAS    equ (ui_image_end - ui_base + 15) >> 4
UI_PARAS        equ UI_IMG_PARAS + ((ui_bss_end - ui_bss_start + 15) >> 4)
UI_KEEP_PARAS   equ UI_IMG_PARAS + ((ui_keep_end - ui_bss_start + 15) >> 4)

; The UI's start-up code (section uiboot: exec_main's first time, LODE.INI,
; the mouse's probe, sysinfo) runs from the top of the directory buffer,
; past what font_boot reads into it (LODE.INI, then the font file), and is
; gone once the directory is read: it isn't part of the block DOS programs
; leave the UI
UIBOOT_ORG      equ (UI_IMG_PARAS << 4) + (FONT_BUF - ui_bss_start) + FONT_BYTES + 2   ; (even)
UIBOOT_WORDS    equ (uiboot_end - uiboot_start + 1) >> 1
section uiboot
uiboot_end:
        times   -(UIBOOT_ORG + (uiboot_end - uiboot_start) > (UI_IMG_PARAS << 4) + (ui_bss_end - ui_bss_start)) db 0
        times   -((INI_READ + 1 + FONT_BYTES) & 1) db 0   ; (entries is even: ualignb(2))
        times   -(UIBOOT_ORG - (UI_IMG_PARAS << 4) - (entries - ui_bss_start) < INI_READ + 1 + FONT_BYTES + 1) db 0
                                        ; (past font_file's read, FONT_BYTES + 1;
                                        ;  ui_bss_start = UI_IMG_PARAS << 4, which
                                        ;  NASM can't check here: test_apps does)
section uiboot progbits align=2 follows=ui vstart=UIBOOT_ORG

; =====================================================================
;  KMT.INC: multitasking.  Its resident part (section mtt, assembled from
;  0, run in a segment of its own) is the file's last section: the build
;  (mkmt.py) cuts it off into LODEMT.SYS, and mt_boot reads that file.
; =====================================================================
section mtt progbits align=16 follows=uiboot vstart=0
section mttbss nobits valign=16 vfollows=mtt
%include "KMT.INC"                      ; (section mtt, and boot: mt_boot)

section ui                              ; (UI_PARAS: ui_image_end ends it)
            times -($ - ui_image_end) db 0

; section ovl inside the disk buffers (bss_start is image_end; init comes
; first in it)
[absolute 0]
        times   -(OVL_AT < (image_end - start) + (bufs - bss_start)) resb 1
        times   -(OVL_AT + (ovl_end - init) > (image_end - start) + (fatbuf - bss_start) + 512 * MAXSPF) resb 1
