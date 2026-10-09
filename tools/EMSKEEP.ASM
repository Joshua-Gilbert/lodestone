; =====================================================================
;  EMSKEEP.COM - does the 1520's EMS keep what it holds through a warm
;  restart (Ctrl-Alt-Del)?                                    (Lodestone)
;  Build:  nasm -f bin -o EMSKEEP.COM EMSKEEP.ASM
;
;    EMSKEEP        stamp: 8 pages of EMS (from the EMS manager, INT 67h:
;                   Lodestone's or GRiD's EMM.SYS) filled with a pattern
;                   that depends on the page and on the time; which raw
;                   pages they are (their page registers) and the time go
;                   in EMSKEEP.DAT.  Then press Ctrl-Alt-Del.
;    EMSKEEP /C     check, after the restart: each of those raw pages put
;                   into window 3 directly (its register read first and
;                   put back after; only read, never written), compared.
;                   One line a page, then the answer; added to EMSKEEP.TXT.
;
;  The first 16 bytes of each page aren't compared: an EMS manager's
;  start-up may tag them (Lodestone 0.3.13's did; 0.3.14's puts them back).
;  The pages may belong to someone else by the time of the check (M:, the
;  disk cache, ...): EMSKEEP only reads them.  Run /C right after the
;  restart, before anything has had time to use much EMS.
;  For Lodestone's M: (0.3.14): if the pages keep their contents, M: keeps
;  its files through a warm restart; if not, it is made new each time.
; =====================================================================
cpu 286
org 100h

NPAGES  equ 8
PORT0   equ 0258h                       ; window 0's page register
PORT3   equ 0C258h                      ; window 3's
WIN0    equ 0E000h
WIN3    equ 0EC00h
SKIP    equ 16                          ; (bytes not compared at a page's start)

start:  cld
        mov     sp, stack_top
        mov     di, bss_start           ; (DOS doesn't clear memory for us)
        mov     cx, stack_top - bss_start
        xor     al, al
        rep     stosb
        mov     si, 81h
.a:     lodsb
        cmp     al, 13
        je      stamp
        cmp     al, '/'
        jne     .a
        lodsb
        and     al, 0DFh
        cmp     al, 'C'
        je      check
        mov     si, s_usage
        call    pr
        jmp     quit

; ---------------------------------------------------------------------
;  stamp
stamp:  call    has_ems
        jc      .none
        mov     ah, 43h                 ; 8 pages (fewer if that's all)
        mov     bx, NPAGES
        int     67h
        or      ah, ah
        jz      .got
        mov     ah, 42h
        int     67h
        or      bx, bx
        jz      .none
        cmp     bx, NPAGES
        jbe     .few
        mov     bx, NPAGES
.few:   mov     ah, 43h
        int     67h
        or      ah, ah
        jnz     .none
.got:   mov     [hnd], dx
        mov     [count], bx
        xor     ax, ax                  ; the seed: the BIOS's tick count
        int     1Ah
        mov     [seed], dx
        xor     bx, bx                  ; each page in window 0: its raw
.p:     push    bx                      ;  register value, then the pattern
        mov     ax, 4400h
        mov     dx, [hnd]
        int     67h
        pop     bx
        or      ah, ah
        jnz     .none
        mov     dx, PORT0
        in      al, dx
        mov     [pages + bx], al
        push    bx
        push    es
        mov     dx, WIN0
        mov     es, dx
        xor     di, di
        call    pattern                 ; (AL = the register value)
        pop     es
        pop     bx
        inc     bx
        cmp     bx, [count]
        jb      .p
        mov     dx, s_dat               ; EMSKEEP.DAT
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .nodat
        mov     bx, ax
        mov     dx, rec
        mov     cx, rec_end - rec
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
        mov     dx, [hnd]               ; the pages back (what they hold stays)
        mov     ah, 45h
        int     67h
        mov     si, s_stamped
        call    pr
        mov     si, pages
        mov     cx, [count]
.l:     lodsb
        and     ax, 7Fh
        call    pdec
        push    si
        mov     si, s_sp
        call    pr
        pop     si
        loop    .l
        mov     si, s_now
        call    pr
        jmp     quit
.none:  mov     si, s_noems
        call    pr
        jmp     quit
.nodat: mov     si, s_nodat
        call    pr
        jmp     quit

; a page's pattern: the byte at offset BX of the page whose register value
; is AL: BL * 7 + BH * 3 + AL * 13 + the seed.  K -> DL
pkey:   mov     ah, 13
        mul     ah
        add     al, [seed]
        mov     dl, al
        ret
pbyte:  mov     al, bl                  ; -> AL (DL kept)
        mov     ah, 7
        mul     ah
        add     al, dl
        add     al, bh
        add     al, bh
        add     al, bh
        ret
; ES:DI: the pattern of the page whose register value is AL
pattern:
        call    pkey
        xor     bx, bx
.l:     call    pbyte
        stosb
        inc     bx
        cmp     bx, 4000h
        jb      .l
        ret

; is there an EMS manager on INT 67h?  CF if not
has_ems:
        push    es
        mov     ax, 3567h
        int     21h
        mov     di, 0Ah
        mov     si, s_emm
        mov     cx, 8
        repe    cmpsb
        pop     es
        je      .y
        stc
        ret
.y:     clc
        ret

; ---------------------------------------------------------------------
;  check
check:  mov     dx, s_dat
        mov     ax, 3D00h
        int     21h
        jc      .nodat
        mov     bx, ax
        mov     dx, rec
        mov     cx, rec_end - rec
        mov     ah, 3Fh
        int     21h
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
        jc      .nodat
        cmp     ax, rec_end - rec
        jne     .nodat
        cmp     word [rec], 'KE'
        jne     .nodat
        mov     byte [logging], 1
        mov     si, s_check
        call    pr
        xor     bx, bx                  ; each page
.pg:    push    bx
        mov     al, [pages + bx]
        mov     [cur], al
        call    cmp_page                ; -> AX = bytes that differ
        pop     bx
        push    ax
        or      ax, ax
        jz      .k
        inc     word [nbad]
        cmp     ax, (4000h - SKIP) / 2  ; (more than half: rewritten)
        jb      .k
        inc     word [ngone]
.k:     mov     si, s_page
        call    pr
        mov     al, [cur]
        and     ax, 7Fh
        call    pdec
        mov     si, s_colon
        call    pr
        pop     ax
        or      ax, ax
        jnz     .d
        mov     si, s_kept
        call    pr
        jmp     short .n
.d:     call    pdec
        mov     si, s_differ
        call    pr
.n:     inc     bx
        cmp     bx, [count]
        jb      .pg
        mov     si, s_all
        cmp     word [nbad], 0
        je      .v
        mov     si, s_cleared
        mov     ax, [ngone]
        cmp     ax, [count]
        je      .v
        mov     si, s_partly
.v:     call    pr
        call    savelog
        jmp     quit
.nodat: mov     si, s_nodat2
        call    pr
        jmp     quit

; raw page [cur] (a register value) in window 3, compared with its pattern
; from byte SKIP on, the window as it was -> AX = bytes that differ
cmp_page:
        push    es
        mov     dx, PORT3
        cli
        in      al, dx
        mov     [old3], al
        mov     al, [cur]
        out     dx, al
        sti
        mov     ax, WIN3
        mov     es, ax
        mov     al, [cur]
        call    pkey
        mov     bx, SKIP
        xor     cx, cx                  ; CX = differences
.l:     call    pbyte
        cmp     al, [es:bx]
        je      .s
        inc     cx
.s:     inc     bx
        cmp     bx, 4000h
        jb      .l
        mov     al, [old3]
        mov     dx, PORT3
        out     dx, al                  ; window 3 as it was
        pop     es
        mov     ax, cx
        ret

; ---------------------------------------------------------------------
;  output: the screen, and (when logging) a copy for EMSKEEP.TXT
pr:     push    ax
        push    bx
        push    cx
        push    dx
        mov     dx, si
.l:     lodsb
        or      al, al
        jnz     .l
        mov     cx, si
        sub     cx, dx
        dec     cx
        cmp     byte [logging], 0
        je      .o
        push    si
        push    di
        push    cx
        mov     si, dx
        mov     di, [logpos]
        mov     ax, LOGMAX
        sub     ax, di
        cmp     cx, ax
        jbe     .c
        mov     cx, ax
.c:     add     [logpos], cx
        add     di, logbuf
        push    es
        push    ds
        pop     es
        rep     movsb
        pop     es
        pop     cx
        pop     di
        pop     si
.o:     mov     bx, 1
        mov     ah, 40h
        int     21h
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret
pdec:   push    si
        push    bx
        push    dx
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
        pop     dx
        pop     bx
        pop     si
        ret
; the log to the end of EMSKEEP.TXT (made if it isn't there)
savelog:
        mov     dx, s_log
        mov     ax, 3D01h
        int     21h
        jnc     .op
        mov     dx, s_log
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
.op:    mov     bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        mov     dx, logbuf
        mov     cx, [logpos]
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     ret

quit:   mov     ax, 4C00h
        int     21h

s_usage db 'EMSKEEP: stamp 8 EMS pages; EMSKEEP /C: check them after Ctrl-Alt-Del', 13, 10, 0
s_emm   db 'EMMXXXX0'
s_noems db 'EMSKEEP: no EMS pages to be had (no EMS manager, or none free)', 13, 10, 0
s_nodat db "EMSKEEP: can't write EMSKEEP.DAT here", 13, 10, 0
s_nodat2 db 'EMSKEEP /C: no EMSKEEP.DAT here (run EMSKEEP first, then Ctrl-Alt-Del)', 13, 10, 0
s_stamped db 'EMSKEEP: these raw EMS pages hold a pattern now: ', 0
s_sp    db ' ', 0
s_now   db 13, 10, 'Press Ctrl-Alt-Del now; when Lodestone is back, run EMSKEEP /C', 13, 10, 0
s_check db 'EMSKEEP /C: the pages stamped before the restart', 13, 10, 0
s_page  db '  raw page ', 0
s_colon db ': ', 0
s_kept  db 'every byte kept', 13, 10, 0
s_differ db ' bytes differ', 13, 10, 0
s_all   db 'EMS kept what it held through the restart', 13, 10, 0
s_cleared db 'EMS was cleared or rewritten by the restart', 13, 10, 0
s_partly db 'EMS kept part of what it held (some pages, or some bytes, changed)', 13, 10, 0
s_dat   db 'EMSKEEP.DAT', 0
s_log   db 'EMSKEEP.TXT', 0
seven   db 7
rec:    db 'KE'                         ; (the file's signature)
seed    dw 0
count   dw 0
pages   times NPAGES db 0
rec_end:

section .bss
bss_start:
hnd     resw 1
cur     resb 1
old3    resb 1
nbad    resw 1
ngone   resw 1
logging resb 1
        resb 1
logpos  resw 1
numbuf  resb 8
LOGMAX  equ 1024
logbuf  resb LOGMAX
        resb 512
stack_top:
