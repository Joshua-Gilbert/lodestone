; RSPIKE.COM - resident Claude, the spikes (plan: lodestone-resident-claude.md)
;
;   RSPIKE          stays resident; CODE-\ over any program waiting for a
;                   key shows a pop-up, CODE-\ again goes back
;   RSPIKE /G:nn    the pop-up also asks the GPIB instrument at address nn
;                   "ID?" through INT 60h (spike 2: TM5000G undisturbed)
; Exit code 0 loaded, 1 no EMS (or not enough), 2 resident already.
;
; Spike 1: the pop-up's code runs from an EMS page of its own, mapped into
; the frame over whatever the program had there (its 4 window registers
; read and put back, as M: does), on a stack of its own.
; Spike 3: the program's screen (32 KB at B800h) and the BIOS's video data
; (40:49h-66h) go to two more EMS pages and come back after the pop-up.
;
; The conventional part is an INT 16h hook: every call first looks for
; CODE-\ with AH=11h (the 1520's BIOS keeps Alt with \ as an "enhanced"
; key that AH=01h drops and AH=00h skips), and a waiting read loops here
; with HLT so the key is seen while the program waits.
cpu 286
org 100h

NPAGES  equ 3                   ; the pop-up's code, then the screen (2)
HOTKEY  equ 2B00h               ; CODE-\ as AH=10h/11h give it
FRAME   equ 0E000h
EPORT   equ 0258h               ; window 0's page register (+4000h a window)

        jmp     init

; ---- resident --------------------------------------------------------
old16   dd      0
entry   dd      FRAME << 16     ; the pop-up's code: E000:0000
hwval   db      0, 0, 0         ; our pages' register values
saved   db      0, 0, 0, 0      ; the program's windows meanwhile
inpop   db      0
params:                         ; for the code in EMS (ES:BX)
p_old16 dd      0
p_gpib  db      0
p_count dw      0
stk_ss  dw      0
stk_sp  dw      0

        db      'RSPK'                  ; (loaded already? the bytes before
int16:  cmp     ah, 0                   ;  INT 16h's handler say)
        je      .rd
        cmp     ah, 10h
        je      .rd
        cmp     ah, 1
        je      .pk
        cmp     ah, 11h
        je      .pk
.ch:    jmp     far [cs:old16]
.pk:    call    hot
        jmp     .ch
.rd:    sti                             ; a read: wait here (the hot key
.w:     call    hot                     ;  seen meanwhile), then the BIOS's
        push    ax
        mov     ah, 11h
        pushf
        call    far [cs:old16]
        pop     ax
        jnz     .ch
        hlt
        jmp     .w

; CODE-\ waiting?  Then it is taken and the pop-up runs.  Registers kept.
hot:    cmp     byte [cs:inpop], 0
        jne     .x
        push    ax
        mov     ah, 11h
        pushf
        call    far [cs:old16]
        jz      .no
        cmp     ax, HOTKEY
        jne     .no
        mov     ah, 10h
        pushf
        call    far [cs:old16]
        call    popup
.no:    pop     ax
.x:     ret

popup:  mov     byte [cs:inpop], 1
        pusha
        push    ds
        push    es
        mov     [cs:stk_ss], ss         ; a stack of our own
        mov     [cs:stk_sp], sp
        cli
        push    cs
        pop     ss
        mov     sp, stack_top
        sti
        cld
        mov     dx, EPORT               ; the program's windows, then ours
        mov     si, saved
        mov     cx, 4
.s:     in      al, dx
        mov     [cs:si], al
        inc     si
        add     dx, 4000h
        loop    .s
        mov     dx, EPORT
        mov     si, hwval
        mov     cx, NPAGES
.m:     mov     al, [cs:si]
        out     dx, al
        inc     si
        add     dx, 4000h
        loop    .m
        push    cs
        pop     es
        mov     bx, params
        call    far [cs:entry]
        mov     dx, EPORT               ; the program's windows back
        mov     si, saved
        mov     cx, 4
.r:     mov     al, [cs:si]
        out     dx, al
        inc     si
        add     dx, 4000h
        loop    .r
        inc     word [cs:p_count]
        cli
        mov     ss, [cs:stk_ss]
        mov     sp, [cs:stk_sp]
        sti
        pop     es
        pop     ds
        popa
        mov     byte [cs:inpop], 0
        ret

        align   2
stack:  times 384 db 0
stack_top:
res_end:

; ---- the pop-up, copied into our first EMS page (runs at E000:0000) -----
section blob follows=.text vstart=0
e_main: push    ds
        push    cs
        pop     ds
        mov     ax, [es:bx]             ; the parameters
        mov     [e_old16], ax
        mov     ax, [es:bx + 2]
        mov     [e_old16 + 2], ax
        mov     al, [es:bx + 4]
        mov     [e_gpib], al
        mov     ax, [es:bx + 5]
        mov     [e_count], ax
        push    ds                      ; the BIOS's video data
        push    40h
        pop     ds
        mov     si, 49h
        push    cs
        pop     es
        mov     di, e_bios
        mov     cx, 66h - 49h + 1
        rep     movsb
        pop     ds
        push    ds                      ; the screen: windows 1 and 2
        push    0B800h
        pop     ds
        push    FRAME + 400h
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 4000h
        rep     movsw
        pop     ds
        mov     ax, 0040h               ; Claude's screen (here: a few lines)
        int     10h
        mov     si, e_msg1
        call    e_puts
        mov     ax, [e_count]
        inc     ax
        call    e_pnum
        mov     si, e_msg2
        call    e_puts
        mov     al, [e_bios]
        xor     ah, ah
        call    e_phex
        mov     si, e_crlf
        call    e_puts
        cmp     byte [e_gpib], 0
        je      .wait
        mov     si, e_msg3              ; spike 2: ask the instrument
        call    e_puts
        mov     al, [e_gpib]
        xor     ah, ah
        call    e_pnum
        mov     si, e_msg4
        call    e_puts
        push    cs
        pop     es
        mov     si, e_idq
        mov     di, e_buf
        mov     cx, e_idq_n
        mov     dx, 79
        mov     bl, [e_gpib]
        xor     bh, bh
        mov     ax, 0401h               ; query, the reply up to LF
        int     60h
        jc      .gerr
        mov     bx, cx
        mov     byte [e_buf + bx], 0
        mov     si, e_buf
        call    e_puts
        jmp     .gd
.gerr:  push    ax
        mov     si, e_gerr
        call    e_puts
        pop     ax
        call    e_pnum
.gd:    mov     si, e_crlf
        call    e_puts
.wait:  mov     si, e_msg5
        call    e_puts
.k:     mov     ah, 10h                 ; CODE-\ again (the BIOS itself)
        pushf
        call    far [e_old16]
        cmp     ax, HOTKEY
        jne     .k
        mov     al, [e_bios]            ; the program's mode, its screen,
        xor     ah, ah                  ;  the BIOS's data
        int     10h
        push    ds
        push    FRAME + 400h
        pop     ds
        push    0B800h
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 4000h
        rep     movsw
        pop     ds
        push    40h
        pop     es
        mov     si, e_bios
        mov     di, 49h
        mov     cx, 66h - 49h + 1
        rep     movsb
        cmp     byte [e_bios], 3        ; text: the cursor as it was
        ja      .g
        mov     cx, [e_bios + 60h - 49h]
        mov     ah, 1
        int     10h
        mov     bl, [e_bios + 62h - 49h]
        xor     bh, bh
        shl     bx, 1
        mov     dx, [e_bios + 50h - 49h + bx]
        mov     bh, [e_bios + 62h - 49h]
        mov     ah, 2
        int     10h
        jmp     .x
.g:     cmp     byte [e_bios], 6        ; CGA graphics: its colour register
        ja      .x
        mov     dx, 3D9h
        mov     al, [e_bios + 66h - 49h]
        out     dx, al
.x:     pop     ds
        retf

e_puts: lodsb
        or      al, al
        jz      .x
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        jmp     e_puts
.x:     ret
e_pnum: xor     cx, cx                  ; AX in decimal
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     ax
        add     al, '0'
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        loop    .p
        ret
e_phex: mov     cx, 2                   ; AL in hex
        mov     ah, al
.h:     rol     ah, 4
        mov     al, ah
        and     al, 15
        add     al, '0'
        cmp     al, '9'
        jbe     .o
        add     al, 7
.o:     push    ax
        mov     ah, 0Eh
        mov     bx, 7
        int     10h
        pop     ax
        loop    .h
        ret

e_msg1  db      'Resident spike: pop-up ', 0
e_msg2  db      ' over a program in video mode ', 0
e_msg3  db      'GPIB ', 0
e_msg4  db      ' says: ', 0
e_gerr  db      'error ', 0
e_msg5  db      'CODE-\ takes you back.', 0
e_crlf  db      13, 10, 0
e_idq   db      'ID?', 13, 10
e_idq_n equ     $ - e_idq
e_old16 dd      0
e_gpib  db      0
e_count dw      0
e_bios  times 30 db 0
e_buf   times 80 db 0
blob_end:

; ---- loading (not kept) ------------------------------------------------
section .text
init:   mov     si, 81h                 ; /G:nn
.a:     lodsb
        cmp     al, 13
        je      .ad
        cmp     al, '/'
        jne     .a
        lodsb
        and     al, 0DFh
        cmp     al, 'G'
        jne     .a
        cmp     byte [si], ':'
        jne     .n
        inc     si
.n:     xor     bx, bx
.nd:    lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .ne
        mov     ah, bl
        shl     bl, 2
        add     bl, ah
        shl     bl, 1
        add     bl, al
        jmp     .nd
.ne:    mov     [p_gpib], bl
        dec     si
        jmp     .a
.ad:    mov     ax, 3516h               ; here already?
        int     21h
        cmp     word [es:bx - 4], 'RS'
        jne     .new
        cmp     word [es:bx - 2], 'PK'
        jne     .new
        mov     dx, s_again
        mov     ah, 9
        int     21h
        mov     ax, 4C02h
        int     21h
.new:   mov     ax, 3567h               ; EMS: a manager on INT 67h?
        int     21h
        mov     di, 0Ah
        mov     si, s_emm
        mov     cx, 8
        repe    cmpsb
        push    cs
        pop     es
        jne     .noems
        mov     ah, 41h                 ; its frame must be E000h
        int     67h
        or      ah, ah
        jnz     .noems
        cmp     bx, FRAME
        jne     .noems
        mov     ah, 43h
        mov     bx, NPAGES
        int     67h
        or      ah, ah
        jnz     .nopages
        mov     [handle], dx
        mov     dx, EPORT               ; each page's register value: map it
        in      al, dx                  ;  in window 0, read the register
        mov     [w0], al
        xor     bx, bx
.l:     mov     ax, 4400h
        mov     dx, [handle]
        push    bx
        int     67h
        pop     bx
        mov     dx, EPORT
        in      al, dx
        mov     [hwval + bx], al
        inc     bx
        cmp     bx, NPAGES
        jb      .l
        mov     al, [hwval]             ; the pop-up's code into page 0
        out     dx, al
        push    FRAME
        pop     es
        mov     si, section.blob.start  ; (where the .COM holds it)
        xor     di, di
        mov     cx, blob_end
        rep     movsb
        push    cs
        pop     es
        mov     al, [w0]                ; window 0 as it was
        out     dx, al
        mov     ax, 3516h
        int     21h
        mov     [old16], bx
        mov     [old16 + 2], es
        mov     [p_old16], bx
        mov     [p_old16 + 2], es
        mov     dx, int16
        mov     ax, 2516h
        int     21h
        mov     es, [2Ch]               ; no environment kept
        mov     ah, 49h
        int     21h
        mov     dx, s_ok
        mov     ah, 9
        int     21h
        mov     dx, (res_end - $$ + 100h + 15) / 16
        mov     ax, 3100h
        int     21h
.noems: mov     dx, s_noems
        jmp     .q
.nopages:
        mov     dx, s_nopages
.q:     mov     ah, 9
        int     21h
        mov     ax, 4C01h
        int     21h

s_emm     db 'EMMXXXX0'
s_again   db 'RSPIKE is resident already', 13, 10, '$'
s_ok      db 'RSPIKE resident: CODE-\ pops it up over a program waiting for a key', 13, 10, '$'
s_noems   db 'RSPIKE needs EMS with its frame at E000h', 13, 10, '$'
s_nopages db 'RSPIKE: not enough free EMS (3 pages)', 13, 10, '$'
handle    dw 0
w0        db 0
