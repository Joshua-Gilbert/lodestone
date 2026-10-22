; NODISKIG.COM (test_kernel t_nodisk): an INT 24h handler that answers Ignore (0) always, as some
; programs' do; calls on an empty B: after A:'s boot sector went to bounce
org 100h
        mov     dx, i24
        mov     ax, 2524h
        int     21h
        mov     ah, 0Dh                 ; disk reset: D_CHK for A:, B:
        int     21h
        mov     ah, 36h                 ; free space A: (same_disk: A:'s boot
        mov     dl, 1                   ;  sector into bounce)
        int     21h
        mov     si, s_a
        call    p4
        mov     byte [seen], 0
        mov     ax, 3D00h
        mov     dx, p_x
        int     21h
        jc      .e1
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
        mov     si, s_ok
        call    pz
        jmp     .n1
.e1:    push    ax
        mov     si, s_err
        call    pz
        pop     ax
        call    phw
.n1:    call    pcrit
        mov     byte [seen], 0
        mov     ah, 36h                 ; free space B:
        mov     dl, 2
        int     21h
        mov     si, s_b
        call    p4
        call    pcrit
        mov     byte [seen], 0
        mov     ah, 4Eh                 ; find first B:*.*
        mov     cx, 16h
        mov     dx, p_all
        int     21h
        jc      .e2
        mov     si, s_ff
        call    pz
        mov     si, 80h + 1Eh           ; the name found
        call    pz
        jmp     .n2
.e2:    push    ax
        mov     si, s_fe
        call    pz
        pop     ax
        call    phw
.n2:    call    pcrit
        mov     ax, 4C00h
        int     21h
; AX BX CX DX after 36h
p4:     push    dx
        push    cx
        push    bx
        push    ax
        call    pz
        pop     ax
        call    phw
        pop     ax
        call    phw
        pop     ax
        call    phw
        pop     ax
        call    phw
        ret
pcrit:  mov     si, s_c
        call    pz
        mov     al, [seen]
        call    phb
        mov     al, [c_ah]
        call    phb
        mov     si, s_nl
        call    pz
        ret
i24:    push    ds
        push    cs
        pop     ds
        inc     byte [seen]
        mov     [c_ah], ah
        mov     al, 0                   ; Ignore
        cmp     byte [seen], 20
        jb      .x
        mov     al, 3
.x:     pop     ds
        iret
pz:     lodsb
        or      al, al
        jz      .x
        mov     dl, al
        mov     ah, 2
        int     21h
        jmp     pz
.x:     ret
phw:    push    ax
        mov     al, ah
        call    phb
        pop     ax
        call    phb
        mov     dl, ' '
        mov     ah, 2
        int     21h
        ret
phb:    push    ax
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
        mov     ah, 2
        int     21h
        ret
seen    db 0
c_ah    db 0
p_x     db 'B:X.TXT', 0
p_all   db 'B:*.*', 0
s_a     db 'A: free ', 0
s_b     db 'B: free ', 0
s_ok    db 'open B:X.TXT ok', 0
s_err   db 'open B:X.TXT err ', 0
s_ff    db 'find B:*.* ok ', 0
s_fe    db 'find B:*.* err ', 0
s_c     db ' crit n/AH ', 0
s_nl    db 13, 10, 0
