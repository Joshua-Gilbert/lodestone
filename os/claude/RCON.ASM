; =====================================================================
;  RCON.ASM - resident Claude's console: the pop-up (CLAUDE /R)
;  Build:  nasm -f bin -i ../src/ -o RCON.BIN RCON.ASM   (before CLAUDE.ASM,
;          which carries it: CLAUDE /R copies it into its first EMS page)
;
;  Runs at E000:0000, called far by CLAUDE.COM's resident stub from inside
;  INT 16h, on the stub's stack, with the program's EMS windows saved and
;  ours mapped: window 0 this code and its data, windows 1-2 (E400h) the
;  program's screen while the console is up.  ES:BX -> the stub's
;  parameters.  It calls nothing but INT 10h, the BIOS's INT 16h (the
;  stub's old16) and INT 33h: DOS may be busy under the program (indos).
;  A DOS program's mouse pointer (INT 33h, drawn from the mouse's IRQ) is
;  hidden while the console is up, so a move then draws nothing on the
;  console and leaves no wrong cell on the program's screen.
;
;  M1: the console is empty, Term's 24 rows blank and its status band;
;  CODE-\ goes back.  Everything the program had comes back byte for
;  byte: its video mode, the 32 KB of video memory, the BIOS's video data
;  (40:49h-66h), and the keys it had typed ahead (kept aside meanwhile,
;  so the console can't read them).
; =====================================================================
cpu 286
org 0

VSEG    equ 0B800h
SAVESEG equ 0E400h              ; windows 1-2: the program's screen
HOTKEY  equ 2B00h               ; CODE-\ as AH=10h gives it
P_OLD16 equ 0                   ; the stub's parameters (CLAUDE.ASM r_params)
P_INDOS equ 4
TROWS   equ 24                  ; Term's rows; the status band is row 24
NKEYS   equ 16

rc_main:
        push    ds
        push    cs
        pop     ds
        cld
        mov     ax, [es:bx + P_OLD16]   ; the BIOS's INT 16h, and is DOS busy?
        mov     [old16], ax
        mov     ax, [es:bx + P_OLD16 + 2]
        mov     [old16 + 2], ax
        push    ds
        lds     si, [es:bx + P_INDOS]
        lodsb
        pop     ds
        mov     [indos], al
        xor     ax, ax                  ; INT 33h there?  The program's
        mov     es, ax                  ;  pointer off (its own cell back
        mov     [mouse], al             ;  first, before the screen is kept)
        mov     ax, [es:33h * 4]
        or      ax, [es:33h * 4 + 2]
        jz      .nm
        inc     byte [mouse]
        mov     ax, 2
        int     33h
.nm:    push    cs
        pop     es
        push    ds                      ; the BIOS's video data, and the keys
        push    40h                     ;  typed ahead: out of its buffer
        pop     ds
        mov     si, 49h
        mov     di, bios
        mov     cx, 66h - 49h + 1
        rep     movsb
        cli
        mov     si, [1Ah]
        mov     di, keys
        xor     cx, cx
.k:     cmp     si, [1Ch]
        je      .kd
        cmp     cx, NKEYS
        jae     .kd
        movsw
        inc     cx
        cmp     si, [82h]
        jb      .k
        mov     si, [80h]
        jmp     .k
.kd:    mov     ax, [1Ch]
        mov     [1Ah], ax
        sti
        pop     ds
        mov     [nkeys], cx
        push    ds                      ; the screen, to windows 1-2
        push    VSEG
        pop     ds
        push    SAVESEG
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 4000h
        rep     movsw
        pop     ds
        mov     ax, 0040h               ; the console
        int     10h
        call    draw
.key:   mov     ah, 10h                 ; (the BIOS's own: past the stub)
        pushf
        call    far [old16]
        cmp     ax, HOTKEY
        jne     .key
        mov     al, [bios]              ; the program's mode, screen and data
        xor     ah, ah
        int     10h
        push    ds
        push    SAVESEG
        pop     ds
        push    VSEG
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 4000h
        rep     movsw
        pop     ds
        push    40h
        pop     es
        mov     si, bios
        mov     di, 49h
        mov     cx, 66h - 49h + 1
        rep     movsb
        cmp     byte [bios], 3          ; text: the cursor as it was
        ja      .g
        mov     cx, [bios + 60h - 49h]
        mov     ah, 1
        int     10h
        mov     bl, [bios + 62h - 49h]
        xor     bh, bh
        shl     bx, 1
        mov     dx, [bios + 50h - 49h + bx]
        mov     bh, [bios + 62h - 49h]
        mov     ah, 2
        int     10h
        jmp     short .t
.g:     cmp     byte [bios], 6          ; CGA graphics: its colour register
        ja      .t
        mov     dx, 3D9h
        mov     al, [bios + 66h - 49h]
        out     dx, al
.t:     call    keys_back
        cmp     byte [mouse], 0         ; the program's pointer back, where
        je      .x                      ;  the mouse is now
        mov     ax, 1
        int     33h
.x:     pop     ds
        retf

; the keys typed ahead go back in front of any typed since (the head moves
; back one word for each; as many as there is room for)
keys_back:
        mov     cx, [nkeys]
        jcxz    .x
        push    ds
        push    40h
        pop     ds
        cli
        mov     ax, [1Ch]               ; room: 15 less those there now
        sub     ax, [1Ah]
        jae     .n
        add     ax, [82h]
        sub     ax, [80h]
.n:     shr     ax, 1
        neg     ax
        add     ax, 15
        cmp     cx, ax
        jbe     .r
        mov     cx, ax
.r:     jcxz    .d
        mov     si, cx                  ; the last of ours first
        shl     si, 1
        add     si, keys - 2
        mov     bx, [1Ah]
.l:     cmp     bx, [80h]
        ja      .b
        mov     bx, [82h]
.b:     dec     bx
        dec     bx
        mov     ax, [cs:si]
        mov     [bx], ax
        dec     si
        dec     si
        loop    .l
        mov     [1Ah], bx
.d:     sti
        pop     ds
.x:     ret

; Term's screen, empty, and its status band
draw:   push    VSEG
        pop     es
        xor     di, di
        xor     ax, ax
        mov     cx, 4000h
        rep     stosw
        mov     di, TROWS * 320
        mov     cx, 80
.b:     mov     ax, 0120h               ; inverse (cell takes AX)
        call    cell
        inc     di
        loop    .b
        mov     di, TROWS * 320 + 1
        mov     si, s_title
        call    puts
        cmp     byte [indos], 0
        je      .r
        mov     si, s_dos
        call    puts
.r:     mov     di, TROWS * 320 + 79 - (s_keys_end - s_keys - 1)
        mov     si, s_keys
        ; (falls through)

; DS:SI -> ASCIIZ at cell ES:DI, inverse
puts:   lodsb
        or      al, al
        jz      .x
        mov     ah, 1
        call    cell
        inc     di
        jmp     puts
.x:     ret

%include "CELL.INC"

s_title db      'Claude (resident)  ', 86h, '  no link yet', 0
s_dos   db      '  ', 86h, '  DOS busy', 0
s_keys  db      'CODE-\ back to the program', 0
s_keys_end:

%include "TERMINUS.INC"
%include "GLYPHS.INC"

old16   dd      0
indos   db      0
mouse   db      0                       ; not 0: INT 33h is there
nkeys   dw      0
bios    times 66h - 49h + 1 db 0
keys    times NKEYS dw 0
