; FREE36.COM - INT 21h 36h for R: (DL = 18) and the current drive (DL = 0):
; "F36 ax=xxxx bx=xxxx cx=xxxx dx=xxxx" for each.  (tests/test_rom.py)
cpu 286
org 100h
        mov     dl, 18
        call    one
        mov     dl, 0
        call    one
        mov     ax, 4C00h
        int     21h
one:    mov     ah, 36h
        int     21h
        mov     [r], ax
        mov     [r + 2], bx
        mov     [r + 4], cx
        mov     [r + 6], dx
        mov     dx, m_f
        mov     ah, 9
        int     21h
        mov     si, r
        mov     di, m_r
.n:     mov     dx, di
        mov     ah, 9
        int     21h
        add     di, 5
        lodsw
        push    ax
        mov     al, ah
        call    hex2
        pop     ax
        call    hex2
        cmp     si, r + 8
        jb      .n
        mov     dx, m_end
        mov     ah, 9
        int     21h
        ret
hex2:   push    ax
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .o
        add     al, 7
.o:     mov     dl, al
        mov     ah, 2
        int     21h
        ret
r       dw      0, 0, 0, 0
m_f     db      'F36$'
m_r     db      ' ax=$', ' bx=$', ' cx=$', ' dx=$'
m_end   db      13, 10, '$'
