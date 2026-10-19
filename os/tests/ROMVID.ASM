; ROMVID.COM - reads a file on R: into video memory (B800h), under the
; ROM's window, and into ordinary memory, and says whether the two agree:
; R:'s reads must bounce through the kernel when the destination is
; under A000-BFFF.  (tests/test_rom.py)
org 100h
        mov     ax, cs
        add     ax, 1000h
        mov     es, ax                  ; ordinary memory: 64 KB on
        mov     dx, fname
        mov     ax, 3D00h
        int     21h
        jc      .bad
        mov     bx, ax
        push    ds
        push    es
        pop     ds
        xor     dx, dx
        mov     cx, 9000
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .bad
        mov     [n1], ax
        mov     ax, 4200h
        xor     cx, cx
        xor     dx, dx
        int     21h
        push    ds
        mov     ax, 0B800h
        mov     ds, ax
        mov     dx, 1                   ; (an odd address, too)
        mov     cx, 9000
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .bad
        cmp     ax, [n1]
        jne     .diff
        mov     ah, 3Eh
        int     21h
        push    ds
        mov     cx, ax
        mov     cx, [n1]
        mov     ax, 0B800h
        mov     ds, ax
        mov     si, 1
        xor     di, di
        repe    cmpsb
        pop     ds
        jne     .diff
        mov     dx, m_same
        jmp     short .say
.diff:  mov     dx, m_diff
        jmp     short .say
.bad:   mov     dx, m_bad
.say:   mov     ah, 9
        int     21h
        mov     ax, 4C00h
        int     21h
fname   db      'R:\LCMD.COM', 0
n1      dw      0
m_same  db      'ROMVID: the same$'
m_diff  db      'ROMVID: different$'
m_bad   db      'ROMVID: error$'
