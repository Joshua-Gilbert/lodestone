; GGVER.COM - what a GRIDGPIB driver answers to AH=00h (presence: AX, CX
; the version, DH the vector, DL its address) and AH=0Ch's DX (resident
; bytes), on the first INT 60h-66h with 'GRIDGPIB' at entry+2:
; "GGVER v=nn ax=xxxx cx=xxxx dx=xxxx st=xxxx".  (tests/test_apps.py)
cpu 286
org 100h
        cld
        mov     al, 60h
.f:     push    ax
        mov     ah, 35h
        int     21h
        lea     di, [bx+2]
        mov     si, sig
        mov     cx, 8
        repe    cmpsb
        pop     ax
        je      .got
        inc     al
        cmp     al, 67h
        jb      .f
        mov     dx, m_none
        jmp     .say
.got:   mov     [gint+1], al
        mov     [v], al
        mov     ah, 00h
        call    gint
        mov     [ax0], ax
        mov     [cx0], cx
        mov     [dx0], dx
        mov     ah, 0Ch
        call    gint
        mov     [st], dx
        mov     dx, m_v
        mov     ah, 9
        int     21h
        mov     al, [v]
        call    hex2
        mov     si, vals
.n:     lodsw
        or      ax, ax
        jz      .x
        mov     dx, ax
        lodsw
        push    ax
        mov     ah, 9
        int     21h
        pop     ax
        push    ax
        mov     al, ah
        call    hex2
        pop     ax
        call    hex2
        jmp     .n
.x:     mov     dx, m_end
.say:   mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h
gint:   int     60h
        ret
hex2:   push    ax                      ; AL in hex
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
sig     db      'GRIDGPIB'
v       db      0
m_v     db      'GGVER v=$'
m_ax    db      ' ax=$'
m_cx    db      ' cx=$'
m_dx    db      ' dx=$'
m_st    db      ' st=$'
m_end   db      13, 10, '$'
m_none  db      'GGVER: no driver', 13, 10, '$'
vals    dw      m_ax
ax0     dw      0
        dw      m_cx
cx0     dw      0
        dw      m_dx
dx0     dw      0
        dw      m_st
st      dw      0
        dw      0
