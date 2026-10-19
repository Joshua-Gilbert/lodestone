; =====================================================================
;  PS.PRN - Lodestone's PostScript printer driver     nasm -f bin
;
;  A printer driver is a file of up to 1 KB.  When Shift-PrtSc is set to
;  print (PRINTER=PS.PRN in LODE.INI; System, Devices), the kernel reads it
;  at the next safe moment into a 1 KB buffer and calls it far at offset
;  0; it prints the screen and returns AL = 0, or AL = 1 if it couldn't.
;  Nothing of it stays in memory.  Interrupts are on; it may use the BIOS
;  (INT 17h for LPT1) but not DOS, and it has the kernel's stack (keep it
;  small).  Other printers are other .PRN files written the same way.
;
;  This one sends PostScript to LPT1, as TM5000G prints to a Brother
;  HL-5370DW: the graphics modes as a 640 x 400 image across the top of
;  the page, a lit pixel black; the text modes as lines of Courier, with
;  ( ) \ escaped and the PC's graphics characters as ?.  Each byte is
;  tried for 10 s while the printer is busy (PostScript printers hold BUSY
;  while they work); a fault, no paper or no LPT1 stops it (AL = 1).
; =====================================================================
cpu 286
org 0

start:  push    ds
        push    es
        push    cs
        pop     ds
        mov     byte [bad], 0
        push    0
        pop     es
        cmp     word [es:408h], 0       ; no LPT1
        je      .no
        mov     al, [es:449h]           ; the video mode
        cbw
        xchg    bp, ax
        mov     si, ps_head
        call    prn_s
        cmp     bp, 3
        ja      .g
        mov     si, ps_text             ; text: each line as "(...)l"
        call    prn_s
        mov     si, [es:44Eh]
        mov     bp, [es:44Ah]           ; (columns)
        push    0B800h
        pop     ds
        mov     dx, 25
.line:  mov     al, '('
        call    prn_b
        mov     cx, bp
.ch:    lodsw
        test    al, al                  ; (the PC's own graphics: ?)
        jns     .a
        mov     al, '?'
.a:     cmp     al, ' '
        jae     .b
        mov     al, ' '
.b:     cmp     al, '('
        je      .esc
        cmp     al, ')'
        je      .esc
        cmp     al, '\'
        jne     .put
.esc:   push    ax
        mov     al, '\'
        call    prn_b
        pop     ax
.put:   call    prn_b
        loop    .ch
        push    si
        mov     si, ps_l
        call    prn_s
        pop     si
        dec     dx
        jnz     .line
        jmp     short .end
.g:     mov     si, ps_img              ; graphics: the lines bottom up, in
        call    prn_s                   ;  hex, a lit pixel black (0)
        push    0B800h
        pop     ds
        mov     dx, 399
.row:   mov     si, dx                  ; line DX's bank
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
        not     al
        call    prn_hex
        loop    .px
        mov     al, 10
        call    prn_b
        dec     dx
        jns     .row
.end:   mov     si, ps_tail             ; the page, and the job's end (^D)
        call    prn_s
        mov     al, [cs:bad]
        jmp     short .x
.no:    mov     al, 1
.x:     pop     es
        pop     ds
        retf

; the string at CS:SI to LPT1
prn_s:  cs lodsb
        or      al, al
        jz      prn_b.x
        call    prn_b
        jmp     prn_s
; AL as two hex digits
prn_hex:
        push    ax
        shr     al, 4
        call    prn_dig
        pop     ax
        and     al, 0Fh
prn_dig:
        add     al, 90h
        daa
        adc     al, 40h
        daa
; AL to LPT1 through INT 17h, for 10 s while it's busy; a fault or no
; paper (or 10 s busy) sets `bad', and nothing more is sent
prn_b:  cmp     byte [cs:bad], 0
        jne     .x
        pusha
        push    ds
        push    0
        pop     ds
        mov     cl, al
        mov     si, [46Ch]
.t:     mov     al, cl
        mov     ah, 0
        xor     dx, dx
        int     17h
        test    ah, 28h                 ; I/O error, out of paper
        jnz     .bad
        test    ah, 1                   ; timed out: busy, again
        jz      .ok
        mov     ax, [46Ch]
        sub     ax, si
        cmp     ax, 182
        jb      .t
.bad:   mov     byte [cs:bad], 1
.ok:    pop     ds
        popa
.x:     ret

bad     db      0
ps_head db      '%!PS-Adobe-3.0', 10, 0
ps_text db      '/Courier findfont 10 scalefont setfont/y 750 def'
        db      '/l{36 y moveto show/y y 12 sub def}def', 10, 0
ps_l    db      ')l', 10, 0
ps_img  db      '/r 80 string def 36 400 translate 540 337.5 scale 640 400 1'
        db      '[640 0 0 400 0 0]{currentfile r readhexstring pop}image', 10, 0
ps_tail db      'showpage', 10, 4, 0

%if $ - $$ > 1024
%error "a printer driver is 1 KB at most"
%endif
