; MTNEST.COM - for test_mt.py: mt_v10 entered with interrupts on (PUSHF / CALL FAR,
; as a TSR's INT 10h hook that STIs and chains does), an INT 1Ch handler calling
; INT 10h meanwhile.  Its own EMS page in window 0 with a signature; after each
; call the signature is checked.  FILE: "OK n" or "BAD i r n" (r: window 0's reg)
; nasm -f bin -o MTNEST.COM MTNEST.ASM
cpu 286
%ifndef COUNT
%define COUNT 3000
%endif
org 100h
        mov     sp, stk_top
        mov     ah, 4Ah
        mov     bx, (stk_top - $$ + 100h + 15) / 16
        int     21h
        mov     si, 81h
.b:     lodsb
        cmp     al, ' '
        je      .b
        dec     si
        mov     [fnm], si
.w:     lodsb
        cmp     al, ' '
        ja      .w
        mov     byte [si-1], 0
        mov     ah, 43h                 ; one EMS page of its own, in window 0
        mov     bx, 1
        int     67h
        or      ah, ah
        jnz     fail
        mov     [hnd], dx
        mov     ax, 4400h
        xor     bx, bx
        int     67h
        or      ah, ah
        jnz     fail
        mov     dx, 258h
        in      al, dx
        mov     [own], al
        push    0E000h
        pop     es
        mov     word [es:0], 'SI'
        mov     word [es:2], 'G!'
        xor     ax, ax                  ; INT 10h's vector (mt_v10), INT 1Ch hooked
        mov     es, ax
        mov     ax, [es:10h*4]
        mov     [v10], ax
        mov     ax, [es:10h*4+2]
        mov     [v10+2], ax
        cli
        mov     ax, [es:1Ch*4]
        mov     [o1c], ax
        mov     ax, [es:1Ch*4+2]
        mov     [o1c+2], ax
        mov     word [es:1Ch*4], h1c
        mov     [es:1Ch*4+2], cs
        sti
        mov     cx, COUNT
.l:     push    cx
        mov     ax, 0601h               ; a window not the whole width: row by
        mov     bh, 07h                 ;  row in the emulator
        mov     cx, 0001h
        mov     dx, 184Dh
%ifdef VIA_INT
        sti
        int     10h
%else
        sti
        pushf
        call    far [v10]
        sti                             ; (pcemu's BIOS returns with RETF 2, the
                                        ;  flags as it had them: the 1520's IRETs)
%endif
        push    0E000h
        pop     es
        cmp     word [es:0], 'SI'
        jne     .bad
        cmp     word [es:2], 'G!'
        jne     .bad
        pop     cx
        loop    .l
        mov     si, s_ok
        mov     ax, [n1c]
        call    hexw
        jmp     done
.bad:   pop     cx
        mov     [iter], cx
        mov     dx, 258h
        in      al, dx
        mov     ah, [own]
        mov     [reg], ax
        mov     si, s_bad
        mov     ax, [iter]
        call    hexw
        mov     al, ' '
        stosb
        mov     ax, [reg]
        call    hexa
        mov     al, ' '
        stosb
        mov     ax, [n1c]
        call    hexa
done:   cli                             ; INT 1Ch back
        xor     ax, ax
        mov     es, ax
        mov     ax, [o1c]
        mov     [es:1Ch*4], ax
        mov     ax, [o1c+2]
        mov     [es:1Ch*4+2], ax
        sti
        push    cs
        pop     es
        mov     ah, 3Ch
        xor     cx, cx
        mov     dx, [fnm]
        int     21h
        jc      .x
        mov     bx, ax
        mov     ah, 40h
        mov     cx, di
        sub     cx, outb
        mov     dx, outb
        int     21h
        mov     ah, 3Eh
        int     21h
.x:     mov     ah, 45h
        mov     dx, [hnd]
        int     67h
        mov     ah, 8                   ; wait for a key
        int     21h
        mov     ax, 4C00h
        int     21h
fail:   mov     ax, 4C01h
        int     21h

; SI = a prefix (ASCIIZ) to outb, then AX in hex; DI past it
hexw:   push    cs
        pop     es
        mov     di, outb
        push    ax
.p:     lodsb
        or      al, al
        jz      .e
        stosb
        jmp     .p
.e:     pop     ax
hexa:   mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .d
        add     al, 7
.d:     stosb
        pop     ax
        loop    .h
        ret

h1c:    pusha
        push    ds
        push    es
        push    cs
        pop     ds
        inc     word [n1c]
        mov     ax, 0A20h               ; a write of nothing (CX = 0): shadowed
        xor     cx, cx                  ;  all the same (mt_vshad maps the pages)
        xor     bx, bx
        int     10h
        pop     es
        pop     ds
        popa
        jmp     far [cs:o1c]

s_ok    db      'OK ', 0
s_bad   db      'BAD ', 0
fnm     dw      0
hnd     dw      0
own     db      0
v10     dd      0
o1c     dd      0
n1c     dw      0
iter    dw      0
reg     dw      0
outb    times 32 db 0
        times 256 db 0
stk_top:
