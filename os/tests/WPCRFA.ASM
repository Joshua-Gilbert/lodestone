; WPCRFA.COM (test_hd): a create over C:\FAR\NOTE.TXT; its own INT 24h answers Abort
org 100h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     dx, name
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .x
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
.x:     mov     ax, 4C00h
        int     21h
h24:    mov     al, 2
        iret
name    db 'C:\FAR\NOTE.TXT', 0
