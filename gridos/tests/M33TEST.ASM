; M33TEST.COM - INT 33h under Grid-OS, step by step (tests/test_apps.py
; drives it: between steps it waits for a key, while the test moves and
; clicks the mouse and looks at the screen).  Each step prints one line:
;   name: AX BX CX DX  (hex)
        org     100h
        cpu     286

        mov     ax, 0                   ; reset
        int     33h
        mov     si, s_reset
        call    show
        mov     ax, 24h                 ; version
        int     33h
        mov     si, s_ver
        call    show
        mov     ax, 1                   ; pointer on (text mode 3)
        int     33h
        call    getkey                    ; (the test: the cell is inverse;
                                        ;  moves and clicks the mouse)
        mov     ax, 3
        int     33h
        mov     si, s_pos
        call    show
        mov     ax, 5                   ; left presses
        xor     bx, bx
        int     33h
        mov     si, s_press
        call    show
        mov     ax, 6                   ; left releases
        xor     bx, bx
        int     33h
        mov     si, s_rel
        call    show
        mov     ax, 0Bh                 ; mickeys
        int     33h
        mov     si, s_mick
        call    show
        mov     ax, 7                   ; x 100..200 (given the wrong way)
        mov     cx, 200
        mov     dx, 100
        int     33h
        mov     ax, 8                   ; y 50..60
        mov     cx, 50
        mov     dx, 60
        int     33h
        mov     ax, 4
        xor     cx, cx
        xor     dx, dx
        int     33h
        mov     ax, 3
        int     33h
        mov     si, s_rng
        call    show
        mov     ax, 7                   ; whole screen again
        xor     cx, cx
        mov     dx, 639
        int     33h
        mov     ax, 8
        xor     cx, cx
        mov     dx, 199
        int     33h
        mov     ax, 0Ch                 ; event handler: everything
        mov     cx, 1Fh
        push    cs
        pop     es
        mov     dx, handler
        int     33h
        call    getkey                    ; (the test: move and click)
        mov     ax, 0Ch
        xor     cx, cx
        int     33h
        mov     ax, [calls]
        mov     bx, [conds]
        mov     cx, [hx]
        mov     dx, [hy]
        mov     si, s_ev
        call    show
        mov     ax, 2                   ; pointer off
        int     33h
        call    getkey                    ; (the test: the cell is back)
        mov     ax, 1
        int     33h
        call    getkey                    ; (the test writes over the cell...)
        mov     ax, 2
        int     33h
        call    getkey                    ; (... and it stays written)
        mov     ax, 0004h               ; CGA 320 x 200
        int     10h
        mov     ax, 0
        int     33h
        mov     ax, 26h                 ; the largest coordinates
        int     33h
        mov     si, s_max
        call    show
        mov     ax, 1
        int     33h
        call    getkey                    ; (the test: the arrow is drawn)
        mov     ax, 2
        int     33h
        call    getkey                    ; (the test: and gone)
        mov     ax, 1                   ; on again, and left on: the
        int     33h                     ;  Executive must cope
        mov     ax, 0Ch                 ; a handler, left set as we go
        mov     cx, 1Fh
        push    cs
        pop     es
        mov     dx, handler
        int     33h
        mov     ax, 0003h
        int     10h
        mov     ax, 4C00h
        int     21h

handler:                                ; (far; DS is the driver's)
        inc     word [cs:calls]
        or      [cs:conds], ax
        mov     [cs:hx], cx
        mov     [cs:hy], dx
        retf

getkey:   mov     ah, 0
        int     16h
        ret

; SI = name; AX BX CX DX in hex
show:   push    dx
        push    cx
        push    bx
        push    ax
        mov     dx, si
        mov     ah, 9
        int     21h
        mov     cx, 4
.r:     pop     ax
        call    hex
        loop    .r
        mov     dx, s_crlf
        mov     ah, 9
        int     21h
        ret

hex:    push    cx
        mov     cx, 4
.d:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        int     21h
        pop     ax
        loop    .d
        mov     dl, ' '
        mov     ah, 2
        int     21h
        pop     cx
        ret

calls   dw 0
conds   dw 0
hx      dw 0
hy      dw 0
s_reset db 'reset: $'
s_ver   db 'version: $'
s_pos   db 'pos: $'
s_press db 'press: $'
s_rel   db 'release: $'
s_mick  db 'mickeys: $'
s_rng   db 'range: $'
s_ev    db 'events: $'
s_max   db 'max: $'
s_crlf  db 13, 10, '$'
