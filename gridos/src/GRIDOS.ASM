; =====================================================================
;  GRIDOS.SYS  -  Grid-OS 0.3 kernel for the GRiDCase 1520
;  nasm -f bin -o GRIDOS.SYS GRIDOS.ASM
;
;  A small DOS 3.30-compatible kernel plus the GRiD-style Executive.
;  Loaded by the Grid-OS boot sector to 1000:0000 (DL = boot drive,
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
VERSION equ 0003h               ; Grid-OS 0.3

start:  cli                     ; at 1000:0000 from the boot sector
        mov     ax, 2000h       ; temporary stack clear of the image
        mov     ss, ax
        mov     sp, 0FFFEh
        sti
        cld
        push    cs
        pop     es
        mov     di, bootbpb
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
        jmp     image_end + (ems_init - ems_start)   ; KEMS.INC's, in this
                                        ; image (then KSEG:init, EMS or not)

init:   cli
        mov     ax, cs
        mov     ds, ax
        mov     es, ax
        mov     ss, ax
        mov     sp, kstack_top
        sti
        mov     di, bss_start           ; clear BSS (nothing on the stack yet)
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        call    ivt_init
        call    sft_init
        call    mem_init
        call    drv_init
        call    clock_init
        call    gpib_init
        call    proc_init               ; master environment + root PSP
        call    ui_load
        jmp     run_ui

; The UI section from the loaded file (still at 1000:section.ui.start)
; into a block of its own; then its BSS cleared.  Allocated at its image
; size first, so the block's new MCB can't land on the image being copied.
ui_load:
        mov     bx, ui_image_end + 15
        shr     bx, 4
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
        mov     cx, ui_image_end + 1
        shr     cx, 1
        rep     movsw
        pop     ds
        mov     bx, ui_bss_end + 15     ; + BSS and stack
        shr     bx, 4
        call    mem_resize
        jc      .fail
        mov     di, ui_bss_start
        mov     cx, ui_bss_end
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

; enter (or re-enter) the root process: the Executive, on its own stack
run_ui: cli
        mov     ax, [cs:ui_seg]
        mov     ss, ax
        mov     sp, ui_stack_top
        sti
        push    ax
        push    word exec_main
        retf

s_nouimem   db 'Grid-OS: not enough memory for the Executive', 13, 10, 0

section .bss nobits align=16 follows=.text
bss_start:
; KEMS.INC: in the file right after the kernel image (at image_end), in
; memory right after the BSS (where ems_init copies it)
section ems progbits align=16 follows=.text vfollows=.bss valign=16
section .text

%include "KCORE.INC"
%include "KMEM.INC"
%include "KDISK.INC"
%include "KFAT.INC"
%include "KFILE.INC"
%include "KPROC.INC"
%include "KGPIB.INC"

bootbpb     times 64 db 0
bootdrv     db 0
            align 16                    ; (free: the BSS starts on a paragraph)
image_end:                              ; everything above is copied low;
                                        ; the EMS section starts right here
section .bss
            alignb 16
bss_end:

section ems
ems_start:
%include "KEMS.INC"

; =====================================================================
;  The UI segment: offsets from 0 in a segment of its own
; =====================================================================
section ui progbits align=16 follows=ems vstart=0
section uibss nobits valign=16 vfollows=ui
; alignb would clash with vfollows in NASM's bin output (it sets a "real"
; section alignment); uibss starts on a paragraph, so this is the same thing
%define ualignb(n) resb ((n) - (($ - $$) % (n))) % (n)
ui_bss_start:
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
