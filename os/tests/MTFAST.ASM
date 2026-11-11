; MTFAST.COM - for test_mt.py: a program that runs the timer fast.
;   MTFAST T FILE [K][C]
; Runs counter 0 four times as fast (mode 3, 4000h) and hooks INT 08h
; (AH=35h/25h) with a handler that counts its calls and goes on to the
; one it found every 4th time (JMP FAR), else only ends the interrupt,
; as a game's music does.  With C it hooks INT 1Ch instead, counting its
; calls (IRET), as a simpler program does that lets the clock race.
; Waits (HLT, then a DOS call) for T ticks of the BIOS's clock (40:6Ch),
; then puts the vector back and, unless K, the counter's rate; FILE gets
; its handler's calls (8 hex digits).
; nasm -f bin -o MTFAST.COM MTFAST.ASM
cpu 286
org 100h
%include "MTLIB.INC"
        mov     si, 81h
        call    num
        mov     [ticks], ax
        mov     di, fname
        call    word_
.o:     call    blanks
        and     al, 0DFh
        cmp     al, 'K'
        jne     .o1
        mov     [keep], al
        jmp     .o
.o1:    cmp     al, 'C'
        jne     .o2
        mov     byte [vec], 1Ch
        mov     word [hnd], t1c
        jmp     .o
.o2:    mov     ah, 35h
        mov     al, [vec]
        int     21h
        mov     [old], bx
        mov     [old+2], es
        push    cs
        pop     es
        mov     ah, 25h
        mov     al, [vec]
        mov     dx, [hnd]
        int     21h
        cli
        mov     al, 36h                 ; counter 0: mode 3, LSB then MSB
        out     43h, al
        xor     al, al
        out     40h, al
        mov     al, 40h                 ; 4000h: four times the BIOS's rate
        out     40h, al
        sti
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     bx, [46Ch]
.w:     sti
        hlt
        mov     ah, 2Ch                 ; (a DOS call now and then, as a game's:
        int     21h                     ;  with its hook ahead of MT's, the only
        mov     ax, [46Ch]              ;  place it is switched from)
        sub     ax, bx
        cmp     ax, [cs:ticks]
        jb      .w
        pop     ds
        cli
        cmp     byte [keep], 'K'
        je      .k
        mov     al, 36h                 ; back to 65536
        out     43h, al
        xor     al, al
        out     40h, al
        out     40h, al
.k:     mov     ah, 25h
        mov     al, [vec]
        push    ds
        lds     dx, [old]
        int     21h
        pop     ds
        sti
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .x
        xchg    bx, ax
        mov     ax, [calls+2]
        mov     di, hex
        call    hex4
        mov     ax, [calls]
        call    hex4
        mov     ah, 40h
        mov     cx, 8
        mov     dx, hex
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h

t1c:    add     word [cs:calls], 1
        adc     word [cs:calls+2], 0
        iret

tick:   add     word [cs:calls], 1
        adc     word [cs:calls+2], 0
        inc     byte [cs:div4]
        test    byte [cs:div4], 3
        jnz     .e
        jmp     far [cs:old]            ; (every 4th: the one it found)
.e:     push    ax
        mov     al, 20h
        out     20h, al
        pop     ax
        iret

blanks: lodsb
        cmp     al, ' '
        je      blanks
        ret
num:    call    blanks
        xor     bx, bx
.d:     sub     al, '0'
        jb      .e
        cmp     al, 9
        ja      .e
        cbw
        imul    bx, bx, 10
        add     bx, ax
        lodsb
        jmp     .d
.e:     dec     si
        mov     ax, bx
        ret
word_:  call    blanks
        dec     si
.c:     lodsb
        cmp     al, ' '
        jbe     .x
        stosb
        jmp     .c
.x:     dec     si
        mov     byte [di], 0
        ret
        HEX4

old     dd      0
calls   dd      0
ticks   dw      0
div4    db      0
keep    db      0
vec     db      08h
hnd     dw      tick
hex     times   8 db 0
fname   times   70 db 0
