; =====================================================================
;  GRIDOS.SYS  -  Grid-OS 0.2 kernel for the GRiDCase 1520
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
;    EXEC   the Executive: GRiD-style file list that runs programs
;
;  Register convention inside the kernel: DS = ES = KSEG unless a routine
;  says otherwise; BP = the INT 21h frame while a call is in progress;
;  failures return CF set and AX = DOS error code.
; =====================================================================
cpu 286
org 0

KSEG    equ 0060h               ; where the kernel lives
VERSION equ 0002h               ; Grid-OS 0.2

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
        jmp     KSEG:init

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
        cli
        mov     sp, xstack_top          ; the Executive has its own stack
        sti
        jmp     exec_main

section .bss align=16
bss_start:
section .text

%include "KCORE.INC"
%include "KMEM.INC"
%include "KDISK.INC"
%include "KFAT.INC"
%include "KFILE.INC"
%include "KPROC.INC"
%include "KGPIB.INC"
%include "EXEC.INC"
%include "FONT.INC"

bootbpb     times 64 db 0
bootdrv     db 0
            align 2
image_end:                              ; everything above is copied low

section .bss align=16
            alignb 16
bss_end:
