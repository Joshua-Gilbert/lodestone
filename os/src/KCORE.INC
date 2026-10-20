; =====================================================================
;  KCORE.INC - INT 21h entry frame and dispatch, console, clock, the
;  small DOS services, and the other kernel interrupts.
; =====================================================================

; ---- the INT 21h frame: the caller's registers, copied to our stack ---
F_DI    equ 0
F_SI    equ 2
F_BP    equ 4
F_SP    equ 6
F_BX    equ 8
F_DX    equ 10
F_CX    equ 12
F_AX    equ 14
F_DS    equ 16
F_ES    equ 18
F_IP    equ 20
F_CS    equ 22
F_FL    equ 24
F_USP   equ 26                  ; where the frame lives on the caller's stack
F_USS   equ 28
F_SIZE  equ 30

PRN_PATH equ 24                         ; ("C:\LODE\" and an 8.3 name, and its end)
section .bss
indos       resb 1              ; INT 21h nesting depth
cap_req     resb 1              ; screen capture: 1 asked for (INT 5), 2 under
                                ;  way, 4 a write failed (word with indos)
cap_lim     resw 1              ; its buffer's size
prn_path    resb PRN_PATH       ; PrtSc's printer driver ("A:\PS.PRN"; "": files)
prn_call    resd 1              ; (where it is called)
cap_file    resb 1              ; Shift was held: a file all the same
brkflag     resb 1              ; INT 21h 33h
verify      resb 1              ; INT 21h 2Eh/54h
kbd_scan    resb 1              ; second half of an extended key
con_col     resb 1              ; console column, for tabs
last_err    resw 1              ; INT 21h 59h
cc_sp       resw 1
cc_cf       resb 1
term_type   resb 1              ; 0 normal, 1 ^C, 2 critical error, 3 TSR
onebyte     resb 1
cur_year    resw 1
cur_mon     resb 1
cur_day     resb 1
            alignb 2
kstack_end  resb 1536           ; INT 21h stack (a screen capture may use
kstack_top:                     ;  its bottom 1 KB as a buffer)
            resb 512
astack_top:                     ; nested INT 21h (from INT 24h handlers)
ui_seg      resw 1              ; the UI segment (core + Executive), see LODE.ASM
section .text

; ---------------------------------------------------------------------
;  interrupt vectors
; ---------------------------------------------------------------------
ivt_init:
        push    es
        xor     ax, ax
        mov     es, ax
        mov     si, vec_table
        cli
.l:     lodsb
        cmp     al, 0FFh
        je      .x
        xor     ah, ah
        shl     ax, 2
        mov     di, ax
        lodsw
        stosw
        mov     ax, cs
        stosw
        jmp     .l
.x:     sti
        pop     es
        ret

vec_table:
        db 05h
        dw int05
        db 20h
        dw int20
        db 21h
        dw int21
        db 22h
        dw root_term
        db 23h
        dw int23
        db 24h
        dw int24
        db 25h
.v25:   dw int25                        ; (KHD.INC: C:'s, if there is a drive)
        db 26h
.v26:   dw int25
        db 27h
        dw int27
        db 28h
        dw iret_op
        db 29h
        dw int29
        db 2Ah
        dw iret_op
        db 2Eh
        dw iret_op
        db 2Fh
        dw iret_op
        db 33h
        dw int33
        db 67h
.v67:   dw int67                        ; (KEMS.INC: its handler, if EMS)
        db 0FFh

iret_op:
        iret

int29:  push    ax                      ; fast console output
        call    tty_out
        pop     ax
        iret

int23:  stc                             ; default ^C handler: end the program
        retf

int24:  mov     al, 3                   ; default critical error: fail the call
        iret

int25:  mov     ax, 0207h               ; absolute disk I/O: not supported
        stc
        retf                            ; (INT 25h/26h leave the flags pushed)

int33:  or      ax, ax                  ; no mouse for DOS programs yet
        jnz     .x
        xor     bx, bx
.x:     iret

int67:  mov     ah, 84h                 ; no EMS here (with EMS, KEMS.INC's)
        iret

int20:  mov     ax, 4C00h               ; terminate (CS = the PSP)
        jmp     int21

int27:  add     dx, 15                  ; TSR: DX = bytes from the PSP
        shr     dx, 4
        mov     ax, 3100h
        jmp     int21

; ---------------------------------------------------------------------
;  Screen capture.  Shift-PrtSc makes the BIOS call INT 5; instead of
;  printing, that asks for a picture, taken at the next safe moment: an
;  INT 21h call from outside the kernel, or a wait for a key (the UI asks
;  for the current drive while it idles).  It goes to the root of the
;  boot disk as SCREEN01 to SCREEN99: the graphics modes as a 640 x 400
;  1-bit .BMP (the 200-line modes each line twice), the text modes as
;  .TXT.  One beep when it's there, a long one when it couldn't be.
;  Written in big pieces (writes go straight to the disk, a turn each):
;  through the disk cache's memory if the Executive or a .RUN is running
;  and it can be lent, else 1 KB at the bottom of the kernel stack (the
;  stack never gets near it).
;  With a printer driver set (PRINTER= in LODE.INI, System's Devices),
;  PrtSc alone prints it instead (Shift-PrtSc still saves the file): the
;  driver, a .PRN file of 16 bytes to 1 KB starting with a JMP SHORT and
;  "PRN", 1, is read into that same 1 KB at the next safe moment, called
;  far at its offset 0 (it
;  reads the screen itself and returns AL = 0 when it has printed it), and
;  forgotten.  Nothing of it stays resident.  (drivers/PS.ASM.)
; ---------------------------------------------------------------------
int05:  push    ax                      ; (Shift held: a file, even with a
        push    ds                      ;  printer driver set)
        push    0
        pop     ds
        mov     al, [417h]
        pop     ds
        and     al, 3
        mov     [cs:cap_file], al
        or      byte [cs:cap_req], 1
        pop     ax
        iret

capture:
        cmp     word [cs:indos], 0101h  ; asked for, not under way, and in
        jne     .ret                    ;  no other INT 21h call
        pusha
        cli                             ; nor inside a hardware interrupt
        mov     al, 0Bh                 ;  (a TSR's timer hook calling DOS:
        out     20h, al                 ;  the floppy's IRQ couldn't come):
        in      al, 20h                 ;  the PIC's in-service register,
        mov     ah, al                  ;  then back to the request one
        mov     al, 0Ah
        out     20h, al
        sti
        or      ah, ah
        jz      .go
        popa
.ret:   ret
.go:    push    ds
        push    es
        push    cs
        pop     ds
        mov     byte [cap_req], 2       ; (no INT 24h meanwhile: crit_disk)
        call    disk_reset              ; a program may have changed the
                                        ;  disk behind our back, reading it
                                        ;  through the BIOS: check it first
        push    word [last_err]
        cmp     byte [cap_file], 0      ; PrtSc with a printer driver: print
        jne     .file
        cmp     byte [prn_path], 0
        jne     .prn
.file:
        mov     al, [capdrv]            ; A:, or from the ROM C: (KROM.INC)
        mov     [cap_name], al
        push    0
        pop     es
        mov     al, [es:449h]           ; the video mode
        cbw
        xchg    bp, ax
        mov     ax, 'TX'
        mov     dl, 'T'
        cmp     bp, 3
        jbe     .ext
        mov     ax, 'BM'
        mov     dl, 'P'
.ext:   mov     [cap_ext], ax
        mov     [cap_ext+2], dl
        xor     di, di
.next:  inc     di                      ; the first number not taken
        cmp     di, 99
        ja      .fail
        mov     ax, di
        aam
        add     ax, '00'
        xchg    al, ah
        mov     [cap_num], ax
        mov     ah, 5Bh
        xor     cx, cx
        mov     dx, cap_name
        int     21h
        jnc     .made
        cmp     al, 50h
        je      .next
.fail:  jmp     .f4
.made:  xchg    bx, ax                  ; BX = the file
        mov     ax, [cur_psp]           ; the buffer, at ES:0: not lent in
        cmp     ax, [root_psp]          ;  a DOS program (with EMS it would
        stc                             ;  be free memory the program may
        jne     .nol                    ;  still use)
        mov     ax, 0F002h
        int     21h
.nol:   sbb     ax, ax
        push    ax                      ; (FFFFh: not lent)
        jnc     .buf
        mov     ax, kstack_end + 15
        shr     ax, 4
        add     ax, KSEG
        mov     es, ax
        mov     cx, 1024
.buf:   mov     [cap_lim], cx
        xor     di, di
        cmp     bp, 3
        ja      .bmp
        push    0                       ; text: the page's characters, line
        pop     ds                      ;  by line, without trailing blanks
        mov     si, [44Eh]
        mov     bp, [44Ah]              ; (columns)
        push    0B800h
        pop     ds
        mov     dx, 25
.line:  mov     cx, bp
        push    si
        add     si, bp
        add     si, bp
.len:   dec     si
        dec     si
        test    byte [si], 0DFh         ; (ZF: a blank or a NUL)
        jnz     .go2
        loop    .len
.go2:   pop     si
        push    si
        jcxz    .eol
.ch:    lodsw
        test    al, 0DFh
        jnz     .c
        mov     al, ' '
.c:     call    cap_b
        loop    .ch
.eol:   mov     al, 13
        call    cap_b
        mov     al, 10
        call    cap_b
        pop     si
        add     si, bp
        add     si, bp
        dec     dx
        jnz     .line
        jmp     .end
.bmp:   mov     si, bmp_hdr
        mov     cx, 62
        rep     movsb                   ; (the buffer is empty)
        mov     dx, 399
        push    0B800h
        pop     ds
.row:   mov     si, dx                  ; bottom up: line DX's bank
        and     si, 3
        cmp     bp, 6
        ja      .r4
        shr     si, 1                   ; (200 lines: 2 banks, each line twice)
.r4:    ror     si, 3
        mov     ax, dx
        shr     ax, 2
        imul    ax, ax, 80
        add     si, ax
        mov     cx, 80
.px:    lodsb
        call    cap_b
        loop    .px
        dec     dx
        jns     .row
.end:   call    cap_fl                  ; the rest
        push    cs
        pop     ds
        mov     ah, 3Eh
        int     21h
        sbb     cx, cx                  ; (FFFFh: it didn't close)
        pop     ax
        inc     ax
        jz      .nl
        mov     ax, 0F003h              ; the cache's memory back
        int     21h
.nl:    test    byte [cap_req], 4       ; a write failed?
        jnz     .del
        inc     cx
        jnz     .beep                   ; (CX = 1)
.del:   mov     ah, 41h                 ; not all of it: none of it
        mov     dx, cap_name
        int     21h
.pcl:   mov     ah, 3Eh
        int     21h
.f4:    mov     cx, 4                   ; a long beep
.beep:  mov     al, 7
.b:     call    tty_out
        loop    .b
        pop     word [last_err]
        mov     byte [cap_req], 0       ; (pressed again meanwhile: dropped)
        pop     es
        pop     ds
        popa
        ret

; the printer driver: up to 1 KB, into the 1 KB at the kernel stack's
; bottom, then called there (AL = 0: printed)
.prn:   mov     dx, prn_path
        mov     ax, 3D00h
        int     21h
        jc      .f4
        xchg    bx, ax
        mov     ax, 4202h               ; its size (1 KB at most)
        xor     cx, cx
        cwd
        int     21h
        or      dx, dx
        jnz     .pcl
        cmp     ax, 1024
        ja      .pcl
        cmp     ax, 16                  ; (and 16 bytes at least)
        jb      .pcl
        push    ax
        mov     ax, 4200h
        cwd
        int     21h
        pop     cx
        mov     ax, kstack_end + 15
        shr     ax, 4
        add     ax, KSEG
        mov     es, ax
        mov     [prn_call+2], ax
        mov     word [prn_call], 0
        push    es
        pop     ds
        xor     dx, dx
        mov     ah, 3Fh
        int     21h
        push    cs
        pop     ds
        jc      .pcl
        cmp     ax, cx
        jne     .pcl
        cmp     word [es:2], 'PR'       ; a driver's signature: JMP SHORT,
        jne     .pcl                    ;  then "PRN", 1 (a print job saved
        cmp     word [es:4], 'N' + 100h ;  as .PRN is no driver: not run)
        jne     .pcl
        mov     ah, 3Eh
        int     21h
        call    far [prn_call]
        push    cs
        pop     ds
        mov     cx, 1
        or      al, al
        jz      .beep
        jmp     .f4

; AL to the file (BX) through the buffer at ES:DI; full, it is written
; (cap_fl).  A write that fails sets cap_req bit 2.
cap_b:  stosb
        cmp     di, [cs:cap_lim]
        jb      cap_fl.x
cap_fl: test    byte [cs:cap_req], 4    ; one failed: no more tries
        jnz     .z
        push    ds
        pusha
        push    es
        pop     ds
        xor     dx, dx
        mov     cx, di
        mov     ah, 40h
        int     21h
        jc      .bad
        cmp     ax, cx
        je      .ok
.bad:   or      byte [cs:cap_req], 4
.ok:    popa
        pop     ds
.z:     xor     di, di
.x:     ret

bmp_hdr db 'BM'
        dd 62 + 32000, 0, 62            ; size, -, where the pixels start
        dd 40, 640, 400                 ; BITMAPINFOHEADER
        dw 1, 1                         ; 1 plane, 1 bit
        dd 0, 32000, 0, 0, 2, 0
        db 2, 8, 36, 0, 40, 120, 255, 0 ; dark red, the plasma's orange (B, G, R)
cap_name db 'A:\SCREEN'
cap_num db '00.'
cap_ext db 'BMP', 0

; ---------------------------------------------------------------------
;  INT 21h: entry, dispatch, exits
; ---------------------------------------------------------------------
int21:  sti
        cld
        push    es
        push    ds
        pusha
        mov     ax, cs
        mov     ds, ax
        mov     es, ax
        mov     si, sp                  ; caller's frame at DX:SI
        mov     dx, ss
        inc     byte [indos]
        mov     bx, kstack_top
        cmp     byte [indos], 1
        je      .stk
        mov     bx, astack_top          ; nested (critical error handler)
.stk:   cli
        mov     ss, ax
        mov     sp, bx
        sti
        sub     sp, F_SIZE
        mov     bp, sp
        mov     [bp+F_USS], dx
        mov     [bp+F_USP], si
        push    ds
        mov     ds, dx
        mov     di, bp
        mov     cx, 13
        rep     movsw
        pop     ds
        call    capture                 ; (Shift-PrtSc pressed: now)
        mov     bl, [bp+F_AX+1]
        cmp     bl, 0F0h
        je      f_F0
        cmp     bl, NFUNC
        jae     f_bad
        xor     bh, bh
        shl     bx, 1
        jmp     [ftab+bx]

; return to the caller with CF clear
ok:     and     byte [bp+F_FL], 0FEh
; return to the caller (frame as it is)
done:   push    cs
        pop     ds
        mov     es, [bp+F_USS]
        mov     di, [bp+F_USP]
        mov     si, bp
        mov     cx, 13
        rep     movsw
        mov     ax, [bp+F_USS]
        mov     bx, [bp+F_USP]
        cli
        dec     byte [indos]
.sw:    mov     ss, ax                  ; (KMT.INC: MULTITASK=1 makes these 5
        mov     sp, bx                  ;  bytes a far jump to mt_exit)
        popa
        pop     ds
        pop     es
        iret
; return AX = error code, CF set
fail:   push    cs
        pop     ds
        mov     [bp+F_AX], ax
        mov     [last_err], ax
        or      byte [bp+F_FL], 1
        jmp     done
; return AX, CF clear
ok_ax:  mov     [bp+F_AX], ax
        jmp     ok
; return AL (AH kept)
ret_al: mov     [bp+F_AX], al
        jmp     done

f_bad:  mov     ax, 1
        jmp     fail
f_fcb:  mov     al, 0FFh                ; FCB calls: not supported
        jmp     ret_al
f_nul0: xor     al, al
        jmp     ret_al

NFUNC   equ 6Dh
ftab:   dw f_00, f_01, f_02, f_03, f_04, f_05, f_06, f_07              ; 00
        dw f_08, f_09, f_0A, f_0B, f_0C, f_0D, f_0E, f_fcb             ; 08
        dw f_fcb, f_fcb, f_fcb, f_fcb, f_fcb, f_fcb, f_fcb, f_fcb      ; 10
        dw f_nul0, f_19, f_1A, f_fcb, f_fcb, f_nul0, f_nul0, f_fcb     ; 18
        dw f_nul0, f_fcb, f_fcb, f_fcb, f_fcb, f_25, f_nul0, f_fcb     ; 20
        dw f_fcb, f_29, f_2A, f_2B, f_2C, f_2D, f_2E, f_2F             ; 28
        dw f_30, f_31, f_fcb, f_33, f_34, f_35, f_36, f_37             ; 30
        dw f_38, f_39, f_3A, f_3B, f_3C, f_3D, f_3E, f_3F              ; 38
        dw f_40, f_41, f_42, f_43, f_44, f_45, f_46, f_47              ; 40
        dw f_48, f_49, f_4A, f_4B, f_4C, f_4D, f_4E, f_4F              ; 48
        dw f_50, f_51, f_52, f_bad, f_54, f_bad, f_56, f_57            ; 50
        dw f_58, f_59, f_5A, f_5B, f_5C, f_bad, f_bad, f_bad           ; 58
        dw f_bad, f_bad, f_51, f_bad, f_bad, f_bad, f_66, f_67         ; 60
        dw f_68, f_bad, f_68, f_bad, f_bad                             ; 68

; ---------------------------------------------------------------------
;  ^C: back to the caller's context, call INT 23h there; IRET restarts
;  the call, RETF with CF set ends the program (like MS-DOS)
; ---------------------------------------------------------------------
ctrlc:  push    cs
        pop     ds
        mov     si, s_ctrlc
        call    con_puts
        push    cs
        pop     ds
        mov     es, [bp+F_USS]
        mov     di, [bp+F_USP]
        mov     si, bp
        mov     cx, 13
        rep     movsw                   ; the caller's registers as they came
        mov     ax, [bp+F_USS]
        mov     bx, [bp+F_USP]
        cli
        dec     byte [indos]
.sw:    mov     ss, ax                  ; (done.sw's bytes again, left alone)
        mov     sp, bx
        popa
        pop     ds
        pop     es
        sti
        mov     [cs:cc_sp], sp
        int     23h
        mov     byte [cs:cc_cf], 0      ; (MOV keeps the handler's CF)
        jnc     .nc
        mov     byte [cs:cc_cf], 1
.nc:    cmp     sp, [cs:cc_sp]
        je      .again                  ; IRET: restart the function
        inc     sp                      ; RETF: drop the flags it left
        inc     sp
        cmp     byte [cs:cc_cf], 0      ; and CF says go on or stop
        je      .again
        mov     byte [cs:term_type], 1
        mov     ax, 4C00h
.again: jmp     int21                   ; the INT 21h frame is still there
s_ctrlc db '^C', 13, 10, 0

; =====================================================================
;  console
; =====================================================================
; AL -> the screen through the BIOS (tabs expanded).  Keeps registers.
tty_out:
        push    ax
        push    bx
        cmp     al, 9
        jne     .one
.tab:   mov     al, ' '
        call    .put
        test    byte [cs:con_col], 7
        jnz     .tab
        jmp     .x
.one:   call    .put
.x:     pop     bx
        pop     ax
        ret
.put:   push    ax
        mov     ah, 0Eh
        mov     bx, 0007h
        int     10h
        pop     ax
        cmp     al, 13
        je      .cr
        cmp     al, 8
        je      .bs
        cmp     al, 7
        je      .r
        cmp     al, 10
        je      .r
        inc     byte [cs:con_col]
.r:     ret
.cr:    mov     byte [cs:con_col], 0
        ret
.bs:    cmp     byte [cs:con_col], 0
        je      .r
        dec     byte [cs:con_col]
        ret

; AL -> standard output (handle 1, possibly redirected).  Keeps registers.
con_out:
        pusha
        push    ds
        push    es
        push    cs
        pop     ds
        mov     bx, 1
        push    ax
        call    h2sft
        pop     ax
        jc      .x
        test    byte [si+S_FLAGS], SF_DEV
        jz      .file
        cmp     byte [si+S_DEV], DEV_CON
        jne     .file
        call    tty_out
        jmp     .x
.file:  mov     [onebyte], al
        push    cs
        pop     es
        mov     di, onebyte
        mov     cx, 1
        call    sft_write
.x:     pop     es
        pop     ds
        popa
        ret

; DS:SI ASCIIZ -> standard output
con_puts:
        lodsb
        or      al, al
        jz      .x
        call    con_out
        jmp     con_puts
.x:     ret

; is standard input the keyboard?  ZF = 1 if so.  Keeps registers.
stdin_con:
        push    ax
        push    bx
        push    si
        mov     bx, 0
        call    h2sft
        jc      .no
        test    byte [si+S_FLAGS], SF_DEV
        jz      .no
        cmp     byte [si+S_DEV], DEV_CON
        jmp     .x
.no:    or      sp, sp                  ; ZF = 0
.x:     pop     si
        pop     bx
        pop     ax
        ret

; next character from standard input -> AL (0 then scan code for
; extended keys; 1Ah at the end of a redirected file)
con_in:
        call    stdin_con
        jz      kbd_get
        push    bx
        push    cx
        push    si
        push    di
        push    es
        mov     bx, 0
        call    h2sft
        jc      .eof
        push    cs
        pop     es
        mov     di, onebyte
        mov     cx, 1
        call    sft_read
        jc      .eof
        or      ax, ax
        jz      .eof
        mov     al, [cs:onebyte]
        jmp     .x
.eof:   mov     al, 1Ah
.x:     pop     es
        pop     di
        pop     si
        pop     cx
        pop     bx
        ret

; keyboard (BIOS), sleeping while nothing is typed
kbd_get:
        mov     al, [cs:kbd_scan]
        or      al, al
        jz      .k
        mov     byte [cs:kbd_scan], 0
        ret
.k:     mov     ah, 1
        int     16h
        jnz     .have
        call    capture
        int     28h
        sti
        hlt
        jmp     .k
.have:  xor     ah, ah
        int     16h
        cmp     al, 0E0h
        jne     .n
        xor     al, al
.n:     or      al, al
        jnz     .x
        mov     [cs:kbd_scan], ah
.x:     ret

; anything waiting on standard input?  ZF = 0 if so
con_ready:
        call    stdin_con
        jnz     .file
        cmp     byte [cs:kbd_scan], 0
        jne     .x
        mov     ah, 1
        int     16h
        ret
.file:  push    ax
        push    bx
        push    si
        mov     bx, 0
        call    h2sft
        jc      .no
        test    byte [si+S_FLAGS], SF_DEV
        jnz     .yes
        mov     ax, [si+S_POS]
        mov     bx, [si+S_POS+2]
        cmp     bx, [si+S_SIZE+2]
        jb      .yes
        ja      .no
        cmp     ax, [si+S_SIZE]
        jb      .yes
.no:    cmp     al, al                  ; ZF = 1
        jmp     .r
.yes:   or      sp, sp                  ; ZF = 0
.r:     pop     si
        pop     bx
        pop     ax
.x:     ret

f_01:   call    con_in                  ; read with echo
        cmp     al, 3
        je      ctrlc
        call    con_out
        jmp     ret_al
f_02:   mov     al, [bp+F_DX]
        call    con_out
        jmp     done
f_03:   mov     ah, 2                   ; AUX input
        xor     dx, dx
        int     14h
        jmp     ret_al
f_04:   mov     al, [bp+F_DX]           ; AUX output
        mov     ah, 1
        xor     dx, dx
        int     14h
        jmp     done
f_05:   mov     al, [bp+F_DX]           ; printer output
        xor     ah, ah
        xor     dx, dx
        int     17h
        jmp     done
f_06:   mov     al, [bp+F_DX]           ; direct console I/O
        cmp     al, 0FFh
        je      .in
        call    con_out
        jmp     done
.in:    call    con_ready
        jz      .none
        call    con_in
        and     byte [bp+F_FL], 0BFh    ; ZF = 0: a character
        jmp     ret_al
.none:  or      byte [bp+F_FL], 40h
        xor     al, al
        jmp     ret_al
f_07:   call    con_in                  ; raw input, no echo
        jmp     ret_al
f_08:   call    con_in                  ; input, no echo
        cmp     al, 3
        je      ctrlc
        jmp     ret_al
f_09:   mov     es, [bp+F_DS]           ; '$'-terminated string
        mov     di, [bp+F_DX]
.l:     mov     al, [es:di]
        cmp     al, '$'
        je      .x
        call    con_out
        inc     di
        jmp     .l
.x:     jmp     done
f_0B:   call    con_ready
        mov     al, 0
        jz      .x
        mov     al, 0FFh
.x:     jmp     ret_al
f_0C:   call    stdin_con               ; flush, then 01/06/07/08/0A
        jnz     .go
        mov     byte [kbd_scan], 0
.fl:    mov     ah, 1
        int     16h
        jz      .go
        xor     ah, ah
        int     16h
        jmp     .fl
.go:    mov     al, [bp+F_AX]
        mov     [bp+F_AX+1], al
        cmp     al, 1
        je      f_01
        cmp     al, 6
        je      f_06
        cmp     al, 7
        je      f_07
        cmp     al, 8
        je      f_08
        cmp     al, 0Ah
        je      f_0A
        xor     al, al
        jmp     ret_al

; buffered line input: DS:DX -> max, count, text
f_0A:   mov     es, [bp+F_DS]
        mov     di, [bp+F_DX]
        mov     cl, [es:di]
        or      cl, cl
        jz      .x
        xor     ch, ch                  ; CH = count
.l:     call    con_in
        cmp     al, 3
        jne     .n3
        call    stdin_con
        je      ctrlc
.n3:    or      al, al
        jnz     .n0
        call    con_in                  ; extended key: ignored
        jmp     .l
.n0:    cmp     al, 0Dh
        je      .end
        cmp     al, 0Ah
        je      .l
        cmp     al, 1Ah
        jne     .nz
        call    stdin_con
        jne     .end                    ; end of a redirected file
.nz:    cmp     al, 8
        je      .bs
        cmp     al, 1Bh
        je      .esc
        mov     dl, ch
        inc     dl
        cmp     dl, cl
        jae     .beep
        mov     bl, ch
        xor     bh, bh
        mov     [es:di+bx+2], al
        inc     ch
        call    con_out
        jmp     .l
.beep:  mov     al, 7
        call    tty_out
        jmp     .l
.bs:    or      ch, ch
        jz      .l
        dec     ch
        call    .rub
        jmp     .l
.esc:   or      ch, ch
        jz      .l
        dec     ch
        call    .rub
        jmp     .esc
.rub:   mov     al, 8
        call    con_out
        mov     al, ' '
        call    con_out
        mov     al, 8
        jmp     con_out
.end:   mov     bl, ch
        xor     bh, bh
        mov     byte [es:di+bx+2], 0Dh
        mov     [es:di+1], ch
        mov     al, 0Dh
        call    con_out
.x:     jmp     done

; =====================================================================
;  clock: time from the BIOS tick count, date kept here (RTC at boot)
; =====================================================================
clock_init:
        mov     word [cur_year], 1980
        mov     byte [cur_mon], 1
        mov     byte [cur_day], 1
        mov     ah, 4
        int     1Ah
        jc      .x
        push    dx
        mov     al, ch
        call    bcd2bin
        mov     bl, 100
        mul     bl
        push    ax
        mov     al, cl
        call    bcd2bin
        xor     ah, ah
        pop     bx
        add     ax, bx
        pop     dx
        cmp     ax, 1980
        jb      .x
        mov     [cur_year], ax
        mov     al, dh
        call    bcd2bin
        mov     [cur_mon], al
        mov     al, dl
        call    bcd2bin
        mov     [cur_day], al
.x:     ret

bcd2bin:                                ; AL BCD -> AL binary
        push    cx
        mov     ah, al
        shr     ah, 4
        and     al, 0Fh
        mov     cl, al
        mov     al, ah
        mov     ah, 10
        mul     ah
        add     al, cl
        pop     cx
        ret

bin2bcd:                                ; AL (0-99) -> AL BCD
        aam
        shl     ah, 4
        or      al, ah
        ret

; ticks since midnight -> CX:DX; rolls the date over at midnight
clock_ticks:
        xor     ah, ah
        int     1Ah
        or      al, al
        jz      .x
        push    cx
        push    dx
        xor     ah, ah
        mov     cx, ax
.d:     call    next_day
        loop    .d
        pop     dx
        pop     cx
.x:     ret

next_day:
        push    ax
        push    bx
        push    cx
        inc     byte [cur_day]
        call    month_days
        cmp     [cur_day], al
        jbe     .x
        mov     byte [cur_day], 1
        inc     byte [cur_mon]
        cmp     byte [cur_mon], 12
        jbe     .x
        mov     byte [cur_mon], 1
        inc     word [cur_year]
.x:     pop     cx
        pop     bx
        pop     ax
        ret

; days in [cur_mon] of [cur_year] -> AL
month_days:
        mov     bl, [cur_mon]
        mov     cx, [cur_year]
; BL = month, CX = year -> AL
mdays:  xor     bh, bh
        mov     al, [mdays_tab+bx-1]
        cmp     bl, 2
        jne     .x
        test    cl, 3
        jnz     .x
        inc     al
.x:     ret
mdays_tab db 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31

f_2A:   call    clock_ticks
        mov     ax, [cur_year]
        mov     [bp+F_CX], ax
        mov     al, [cur_mon]
        mov     [bp+F_DX+1], al
        mov     al, [cur_day]
        mov     [bp+F_DX], al
        ; weekday: 1-Jan-1980 was a Tuesday
        mov     ax, 2
        mov     cx, 1980
.y:     cmp     cx, [cur_year]
        jae     .m
        add     ax, 365
        test    cl, 3
        jnz     .ny
        inc     ax
.ny:    inc     cx
        jmp     .y
.m:     mov     bl, 1
.ml:    cmp     bl, [cur_mon]
        jae     .dd
        push    ax
        push    bx
        mov     cx, [cur_year]
        call    mdays
        xor     ah, ah
        mov     dx, ax
        pop     bx
        pop     ax
        add     ax, dx
        inc     bl
        jmp     .ml
.dd:    mov     dl, [cur_day]
        xor     dh, dh
        add     ax, dx
        dec     ax
        xor     dx, dx
        mov     cx, 7
        div     cx
        mov     al, dl
        jmp     ret_al

f_2B:   mov     cx, [bp+F_CX]           ; set date
        mov     dx, [bp+F_DX]
        cmp     cx, 1980
        jb      .bad
        cmp     cx, 2099
        ja      .bad
        cmp     dh, 1
        jb      .bad
        cmp     dh, 12
        ja      .bad
        cmp     dl, 1
        jb      .bad
        mov     bl, dh
        push    dx
        call    mdays
        pop     dx
        cmp     dl, al
        ja      .bad
        call    clock_ticks             ; consume a pending midnight first
        mov     cx, [bp+F_CX]
        mov     dx, [bp+F_DX]
        mov     [cur_year], cx
        mov     [cur_mon], dh
        mov     [cur_day], dl
        mov     ax, cx                  ; the RTC too
        mov     bl, 100
        div     bl
        push    ax
        call    bin2bcd
        mov     ch, al
        pop     ax
        mov     al, ah
        call    bin2bcd
        mov     cl, al
        mov     al, [cur_mon]
        call    bin2bcd
        mov     dh, al
        mov     al, [cur_day]
        call    bin2bcd
        mov     dl, al
        mov     ah, 5
        int     1Ah
        xor     al, al
        jmp     ret_al
.bad:   mov     al, 0FFh
        jmp     ret_al

; time: hundredths = ticks * 5.492549 (= 5 + 32280/65536)
f_2C:   call    clock_ticks             ; CX:DX
        mov     si, cx
        mov     di, dx
        mov     ax, dx
        mov     bx, 32280
        mul     bx
        mov     cx, dx                  ; (lo * 32280) >> 16
        mov     ax, si
        mul     bx                      ; hi * 32280
        add     ax, cx
        adc     dx, 0                   ; DX:AX = frac part
        push    ax
        push    dx
        mov     ax, di                  ; + 5 * ticks
        mov     bx, 5
        mul     bx
        mov     cx, ax
        mov     bx, dx
        mov     ax, si
        mov     dx, 5
        mul     dx
        add     bx, ax
        pop     dx
        pop     ax
        add     ax, cx
        adc     dx, bx                  ; DX:AX = hundredths since midnight
        mov     cx, 6000
        div     cx                      ; AX = minutes, DX = hundredths in it
        push    ax
        mov     ax, dx
        mov     bl, 100
        div     bl                      ; AL = seconds, AH = hundredths
        mov     [bp+F_DX+1], al
        mov     [bp+F_DX], ah
        pop     ax
        mov     bl, 60
        div     bl
        mov     [bp+F_CX+1], al         ; hours
        mov     [bp+F_CX], ah           ; minutes
        jmp     done

; set time: ticks = hundredths * 0.182065 (= 11932/65536)
f_2D:   mov     cx, [bp+F_CX]
        mov     dx, [bp+F_DX]
        cmp     ch, 23
        ja      .bad
        cmp     cl, 59
        ja      .bad
        cmp     dh, 59
        ja      .bad
        cmp     dl, 99
        ja      .bad
        mov     al, ch
        mov     bl, 60
        mul     bl
        xor     ch, ch
        add     ax, cx                  ; minutes
        mov     bx, 6000
        mul     bx                      ; DX:AX
        mov     cl, [bp+F_DX+1]
        xor     ch, ch
        push    dx
        push    ax
        mov     ax, 100
        mul     cx
        mov     cl, [bp+F_DX]
        add     ax, cx
        pop     cx
        pop     bx
        add     ax, cx
        adc     bx, 0                   ; BX:AX hundredths
        mov     si, ax
        mov     ax, bx
        mov     cx, 11932
        mul     cx                      ; hi * k
        mov     di, ax
        mov     bx, dx
        mov     ax, si
        mul     cx                      ; lo * k
        add     dx, di
        adc     bx, 0                   ; ticks = BX:DX (>> 16)
        mov     cx, bx
        mov     ah, 1
        int     1Ah
        mov     al, [bp+F_CX+1]         ; the RTC too
        call    bin2bcd
        mov     ch, al
        mov     al, [bp+F_CX]
        call    bin2bcd
        mov     cl, al
        mov     al, [bp+F_DX+1]
        call    bin2bcd
        mov     dh, al
        xor     dl, dl
        mov     ah, 3
        int     1Ah
        xor     al, al
        jmp     ret_al
.bad:   mov     al, 0FFh
        jmp     ret_al

; DOS date/time words for now -> AX = time, DX = date
dos_stamp:
        push    bx
        push    cx
        push    si
        push    di
        call    clock_ticks
        ; reuse f_2C's arithmetic without the frame
        mov     si, cx
        mov     di, dx
        mov     ax, dx
        mov     bx, 32280
        mul     bx
        mov     cx, dx
        mov     ax, si
        mul     bx
        add     ax, cx
        adc     dx, 0
        push    ax
        push    dx
        mov     ax, di
        mov     bx, 5
        mul     bx
        mov     cx, ax
        mov     bx, dx
        mov     ax, si
        mov     dx, 5
        mul     dx
        add     bx, ax
        pop     dx
        pop     ax
        add     ax, cx
        adc     dx, bx
        mov     cx, 6000
        div     cx                      ; AX minutes, DX hundredths
        push    ax
        mov     ax, dx
        mov     bl, 100
        div     bl                      ; AL seconds
        shr     al, 1
        xor     ah, ah
        mov     si, ax                  ; 2-second units
        pop     ax
        mov     bl, 60
        div     bl                      ; AL hours, AH minutes
        mov     bl, ah
        xor     bh, bh
        xor     ah, ah
        shl     ax, 11
        shl     bx, 5
        or      ax, bx
        or      ax, si
        push    ax
        mov     ax, [cur_year]
        sub     ax, 1980
        shl     ax, 9
        mov     bl, [cur_mon]
        xor     bh, bh
        shl     bx, 5
        or      ax, bx
        mov     bl, [cur_day]
        or      ax, bx
        mov     dx, ax
        pop     ax
        pop     di
        pop     si
        pop     cx
        pop     bx
        ret

; =====================================================================
;  small services
; =====================================================================
f_0D:   call    disk_reset              ; flush and forget the disks
        mov     byte [bp+F_AX], 0       ; (AL = FFh: the FAT couldn't be
        jnc     .x                      ;  written)
        mov     byte [bp+F_AX], 0FFh
.x:     jmp     done

; INT 21h F0h: Lodestone's own calls (MS-DOS doesn't have it).
;   AL = 0: AX = 4F47h ('GO'), BX = version (0201h)
;   AL = 1: DL = drive (0 = A:) -> CX = files open on it
;   AL = 5: the Executive's screen saver, for a program at its prompt:
;           AX = idle ticks before it (FFFFh: never), ES:BX = its far entry
;   AL = 6: PrtSc's printer driver -> ES:BX = its path ("": files), CX =
;           its room (the caller changes it there)
f_F0:   mov     al, [bp+F_AX]
        or      al, al
        jnz     .1
        mov     word [bp+F_BX], 0201h
        mov     ax, 4F47h
        jmp     ok_ax
.1:     cmp     al, 2
        je      .lend
        cmp     al, 6
        je      .prn
        cmp     al, 3
        je      .back
        cmp     al, 4
        je      .useg
        cmp     al, 5
        je      .saver
        cmp     al, 1
        jne     f_bad
        jmp     .open
; AL=2: lend the disk cache's memory to the caller (windows' save-under):
; ES = its segment, CX = bytes.  CF if there is no cache or it is lent.
; (KEMS.INC: with the cache in EMS, ems_lend and ems_back instead)
.lend:  mov     ax, [tc_seg]
        or      ax, ax
        jz      .nolend
        cmp     byte [tc_lock], 0
        jne     .nolend
        mov     byte [tc_drv], 0FFh     ; nothing cached any more
        mov     byte [tc_lock], 1       ; and nothing goes in meanwhile
        mov     [bp+F_ES], ax
        mov     word [bp+F_CX], TC_SECS * 512
        jmp     ok
.nolend:
        mov     ax, 8
        jmp     fail
; AL=3: the cache has its memory back
.back:  mov     byte [tc_lock], 0
        jmp     ok
; AL=5: the saver's delay and ui_saver_far (UICORE.INC), which runs it
.saver: mov     es, [ui_seg]
        mov     [bp+F_ES], es
        mov     word [bp+F_BX], ui_saver_far
        mov     ax, [es:saver_t]
        jmp     ok_ax
; AL=6: PrtSc's printer driver -> ES:BX = its path ("A:\PS.PRN"; "": none,
; PrtSc saves files), CX = the room there: the caller changes it in place
.prn:   mov     [bp+F_ES], cs
        mov     word [bp+F_BX], prn_path
        mov     word [bp+F_CX], PRN_PATH
        jmp     ok
; AL=4: the UI segment has moved to BX (where the root process restarts)
.useg:  mov     ax, [bp+F_BX]
        mov     [ui_seg], ax
        jmp     ok
.open:  mov     dl, [bp+F_DX]
        xor     cx, cx
        mov     si, sft
        mov     bx, NSFT
.l:     cmp     byte [si+S_REF], 0
        je      .n
        test    byte [si+S_FLAGS], SF_DEV
        jnz     .n
        cmp     [si+S_DRV], dl
        jne     .n
        inc     cx
.n:     add     si, SFT_SZ
        dec     bx
        jnz     .l
        mov     [bp+F_CX], cx
        jmp     ok
f_0E:   mov     al, [bp+F_DX]           ; select drive
        call    drv_present
        jc      .x
        mov     [cur_drv], al
.x:     mov     al, [lastdrv]           ; drives A: to the last there is
.xe:    jmp     ret_al
f_19:   mov     al, [cur_drv]
        jmp     ret_al
f_1A:   mov     ax, [bp+F_DS]
        mov     [dta+2], ax
        mov     ax, [bp+F_DX]
        mov     [dta], ax
        jmp     done
f_2F:   mov     ax, [dta+2]
        mov     [bp+F_ES], ax
        mov     ax, [dta]
        mov     [bp+F_BX], ax
        jmp     done
f_25:   xor     bx, bx                  ; set vector
        mov     es, bx
        mov     bl, [bp+F_AX]
        shl     bx, 2
        mov     ax, [bp+F_DX]
        mov     dx, [bp+F_DS]
        cli
        mov     [es:bx], ax
        mov     [es:bx+2], dx
        sti
        jmp     done
f_35:   xor     bx, bx                  ; get vector
        mov     es, bx
        mov     bl, [bp+F_AX]
        shl     bx, 2
        mov     ax, [es:bx]
        mov     [bp+F_BX], ax
        mov     ax, [es:bx+2]
        mov     [bp+F_ES], ax
        jmp     done
f_2E:   mov     al, [bp+F_AX]
        and     al, 1
        mov     [verify], al
        jmp     done
f_54:   mov     al, [verify]
        jmp     ret_al
f_30:   mov     word [bp+F_AX], 1E03h   ; MS-DOS 3.30
        mov     word [bp+F_BX], 0
        mov     word [bp+F_CX], 0
        jmp     done
f_33:   mov     al, [bp+F_AX]
        cmp     al, 0
        je      .get
        cmp     al, 1
        je      .set
        cmp     al, 5
        je      .boot
        mov     al, 0FFh
        jmp     ret_al
.get:   mov     al, [brkflag]
        mov     [bp+F_DX], al
        jmp     done
.set:   mov     al, [bp+F_DX]
        and     al, 1
        mov     [brkflag], al
        jmp     done
.boot:  mov     al, [bootdrv]
        and     al, 7Fh
        inc     al
        mov     ah, [setdrv]            ; (Lodestone: DH = the drive whose
        mov     [bp+F_DX], ax           ;  LODE.INI goes over this one's)
        jmp     done
f_34:   mov     word [bp+F_ES], KSEG    ; the InDOS flag
        mov     word [bp+F_BX], indos
        jmp     done
f_37:   cmp     byte [bp+F_AX], 0       ; switch character
        jne     .x
        mov     byte [bp+F_DX], '/'
        mov     byte [bp+F_AX], 0
.x:     jmp     done
f_38:   cmp     byte [bp+F_AX], 0       ; country information (USA)
        je      .get
        cmp     byte [bp+F_AX], 1
        jne     .bad
.get:   mov     es, [bp+F_DS]
        mov     di, [bp+F_DX]
        mov     si, country
        mov     cx, 34
        rep     movsb
        mov     word [es:di-34+12h], casemap
        mov     word [es:di-34+14h], KSEG
        mov     ax, 1
        mov     [bp+F_BX], ax
        jmp     ok
.bad:   mov     ax, 2
        jmp     fail
country dw 0                            ; date format: m-d-y
        db '$', 0, 0, 0, 0
        db ',', 0, '.', 0, '-', 0, ':', 0
        db 0, 2, 0                      ; currency format, digits, 12-hour
        dw 0, 0                         ; case map (filled in)
        db ',', 0
        times 10 db 0
casemap:
        retf
f_50:   mov     ax, [bp+F_BX]
        mov     [cur_psp], ax
        jmp     done
f_51:   mov     ax, [cur_psp]
        mov     [bp+F_BX], ax
        jmp     done
f_52:   mov     word [bp+F_ES], KSEG    ; "list of lists": first MCB at -2
        mov     word [bp+F_BX], lol
        jmp     done
f_58:   cmp     byte [bp+F_AX], 0       ; allocation strategy: first fit
        jne     .set
        xor     ax, ax
        jmp     ok_ax
.set:   jmp     ok
f_59:   mov     ax, [last_err]
        mov     [bp+F_AX], ax
        mov     word [bp+F_BX], 0D01h   ; class 13 (unknown), action 1 (retry)
        mov     byte [bp+F_CX+1], 1     ; locus unknown
        jmp     done
f_5C:   jmp     ok                      ; record locks: always granted
f_66:   cmp     byte [bp+F_AX], 1       ; code page 437
        jne     .set
        mov     ax, 437
        mov     [bp+F_BX], ax
        mov     [bp+F_DX], ax
        jmp     ok
.set:   jmp     ok
f_67:   cmp     word [bp+F_BX], 20      ; handle count: 20 is all we have
        ja      .no
        jmp     ok
.no:    mov     ax, 8
        jmp     fail

; ---------------------------------------------------------------------
;  29h: parse a file name into an FCB.  DS:SI -> text, ES:DI -> FCB,
;  AL bit 0 = skip leading separators, bits 1-3 = keep drive/name/ext
; ---------------------------------------------------------------------
f_29:   mov     ds, [bp+F_DS]
        mov     si, [bp+F_SI]
        mov     es, [bp+F_ES]
        mov     di, [bp+F_DI]
        mov     bl, [bp+F_AX]
        xor     dl, dl                  ; DL = result
        test    bl, 1
        jz      .ns
.sk:    lodsb
        cmp     al, ' '
        je      .sk
        cmp     al, 9
        je      .sk
        cmp     al, ':'
        je      .sk2
        cmp     al, ';'
        je      .sk2
        cmp     al, '.'
        je      .sk2
        cmp     al, ','
        je      .sk2
        cmp     al, '='
        je      .sk2
        cmp     al, '+'
        je      .sk2
        dec     si
        jmp     .ns
.sk2:   jmp     .sk
.ns:    cmp     byte [si+1], ':'        ; drive
        jne     .nod
        mov     al, [si]
        and     al, 0DFh
        sub     al, 'A'
        jb      .bdrv
        push    si                      ; (a drive that is there)
        push    ds
        push    cs
        pop     ds
        call    drv_present
        pop     ds
        pop     si
        jc      .bdrv
        inc     ax
        mov     [es:di], al
        add     si, 2
        jmp     .nm
.bdrv:  mov     dl, 0FFh
        add     si, 2
        jmp     .nm
.nod:   test    bl, 2
        jnz     .nm
        mov     byte [es:di], 0
.nm:    lea     bx, [di+1]
        mov     cx, 8
        test    byte [bp+F_AX], 4
        call    .field
        cmp     byte [si], '.'
        jne     .noext
        inc     si
        lea     bx, [di+9]
        mov     cx, 3
        test    byte [bp+F_AX], 8
        call    .field
        jmp     .done
.noext: test    byte [bp+F_AX], 8
        jnz     .done
        mov     word [es:di+9], '  '
        mov     byte [es:di+11], ' '
.done:  push    cs
        pop     ds
        mov     [bp+F_SI], si
        mov     al, dl
        jmp     ret_al
; copy one field (CX chars) to ES:BX; ZF from "keep" test: ZF=0 keep old
.field: pushf
        mov     ah, 0                   ; AH = chars taken
.fl:    mov     al, [si]
        call    .term
        je      .fe
        inc     si
        cmp     al, '*'
        je      .star
        cmp     al, 'a'
        jb      .up
        cmp     al, 'z'
        ja      .up
        sub     al, 20h
.up:    cmp     al, '?'
        jne     .put
        or      dl, 1
.put:   jcxz    .fl
        mov     [es:bx], al
        inc     bx
        dec     cx
        inc     ah
        jmp     .fl
.star:  or      dl, 1
        jcxz    .fl
.st:    mov     byte [es:bx], '?'
        inc     bx
        inc     ah
        loop    .st
        jmp     .fl
.fe:    popf
        jnz     .keep
        or      ah, ah
        jnz     .pad
        jmp     .pad
.keep:  or      ah, ah
        jz      .fx
.pad:   jcxz    .fx
.p:     mov     byte [es:bx], ' '
        inc     bx
        loop    .p
.fx:    ret
.term:  cmp     al, ' '                 ; ZF = 1 if AL ends a name
        ja      .t1
        cmp     al, al
        ret
.t1:    push    di
        push    cx
        push    es
        push    cs
        pop     es
        mov     di, sepchars
        mov     cx, NSEP
        repne   scasb
        pop     es
        pop     cx
        pop     di
        ret
sepchars db '.\/:;,=+"[]|<>'
NSEP    equ $ - sepchars

; "list of lists" (INT 21h 52h): the first MCB segment is at lol-2
            dw 0
lol:        dd 0FFFFFFFFh               ; no DPBs
            dd 0FFFFFFFFh               ; no SFT chain
            dd 0FFFFFFFFh               ; no clock device
            dd 0FFFFFFFFh               ; no CON device
            dw 512                      ; largest sector
            dd 0FFFFFFFFh
            dd 0FFFFFFFFh
            dd 0FFFFFFFFh
            dd 0FFFFFFFFh
            db 2                        ; block devices
            db 2                        ; LASTDRIVE
