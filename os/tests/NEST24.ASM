; NEST24.COM - for test_kernel's t_execnest: an INT 24h handler's own DOS
; call while EXEC loads.  X.DAT open, then EXEC BIG.COM (the test makes a
; sector of each unreadable).  The handler, at its first call (BIG.COM's
; read), reads X.DAT (INT 21h 3Fh, nested): that read's error calls it
; again, which answers Abort; then it answers Abort for BIG.COM's.  Both
; are Fails while EXEC loads (the outer call's AH, 4Bh), so NEST24 goes on
; and prints "exec eeee read rrrr" (AX after each, CF set: an error).
cpu 286
org 100h
        mov     bx, 1000h               ; 64 KB: the rest for EXEC
        mov     ah, 4Ah
        int     21h
        mov     ax, 2524h
        mov     dx, h24
        int     21h
        mov     ax, 3D00h
        mov     dx, xname
        int     21h
        mov     [hx], ax
        mov     [pb + 4], cs
        mov     [pb + 8], cs
        mov     [pb + 12], cs
        mov     ax, 4B00h
        mov     dx, bname
        mov     bx, pb
        int     21h
        jc      .e
        mov     ax, 0FFFFh              ; (it ran: not what the test wants)
.e:     mov     di, s_exec
        call    hex
        mov     ax, [nres]
        mov     di, s_read
        call    hex
        mov     ah, 9
        mov     dx, s_out
        int     21h
        mov     ax, 4C00h
        int     21h

h24:    cmp     byte [cs:inh], 0
        jne     .ab
        mov     byte [cs:inh], 1
        pusha
        push    ds
        push    cs
        pop     ds
        mov     ah, 3Fh
        mov     bx, [hx]
        mov     cx, 512
        mov     dx, buf
        int     21h
        jc      .r
        xor     ax, ax                  ; (read: 0000, not an error)
.r:     mov     [nres], ax
        pop     ds
        popa
.ab:    mov     al, 2                   ; Abort
        iret

hex:    mov     cx, 4                   ; AX -> 4 hex digits at DI
.h:     rol     ax, 4
        push    ax
        and     al, 15
        add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     [di], al
        inc     di
        pop     ax
        loop    .h
        ret

inh     db 0
hx      dw 0
nres    dw 0FFFFh
pb      dw 0, tail, 0, fcb, 0, fcb, 0
tail    db 0, 13
fcb     times 16 db 0
xname   db 'X.DAT', 0
bname   db 'BIG.COM', 0
s_out   db 'exec '
s_exec  db '....'
        db ' read '
s_read  db '....', 13, 10, '$'
buf     times 512 db 0
