; HDABS.COM - for test_hd.py: INT 25h/26h (absolute sectors) on C:.
;   HDABS             read C:'s sector 0 (prints its OEM name and whether
;                     interrupts are on after it: "IF=1"), then try A: and
;                     C: in the old form (both refused: error 0207h)
;   HDABS R ssssssss  read sector ssssssss (hex) of C:, print its first 8 bytes
;   HDABS W ssssssss  write 512 'Z's there
; Errors print as "error hhhh" (AX).
cpu 286
org 100h
        mov     [pkt+8], cs             ; (the buffer's segment)
        mov     si, 81h
.sp:    lodsb
        cmp     al, ' '
        je      .sp
        cmp     al, 13
        je      basic
        and     al, 0DFh
        mov     [op], al
        xor     bx, bx                  ; BX:DX = the sector, from hex
        xor     dx, dx
.h:     lodsb
        cmp     al, ' '
        je      .h
        sub     al, '0'
        jb      .go
        cmp     al, 9
        jbe     .d
        and     al, 0DFh
        sub     al, 7
.d:     mov     cx, 4
.sh:    shl     dx, 1
        rcl     bx, 1
        loop    .sh
        or      dl, al
        jmp     .h
.go:    mov     [pkt], dx
        mov     [pkt+2], bx
        cmp     byte [op], 'W'
        je      .w
        call    rd
        jc      fail
        mov     si, buf                 ; its first 8 bytes
        mov     di, line
        mov     cx, 8
        rep     movsb
        mov     dx, line
        jmp     say_q
.w:     mov     di, buf
        mov     cx, 512
        mov     al, 'Z'
        rep     stosb
        mov     al, 2
        mov     cx, 0FFFFh
        mov     bx, pkt
        int     26h
        pop     bx                      ; (the flags left behind)
        jc      fail
        mov     dx, s_wrote
        jmp     say_q

basic:  cli                             ; (the call turns them on, as DOS)
        call    rd                      ; sector 0: its OEM name
        pushf
        pop     ax
        test    ah, 2
        jz      .if0
        mov     byte [s_if + 3], '1'
.if0:   jc      fail
        mov     si, buf + 3
        mov     di, oem
        mov     cx, 8
        rep     movsb
        mov     dx, s_oem
        call    say
        mov     al, 0                   ; A:: not supported
        mov     cx, 0FFFFh
        mov     bx, pkt
        int     25h
        pop     bx
        call    res
        mov     al, 2                   ; C: in the old form: not supported
        mov     cx, 1
        xor     dx, dx
        mov     bx, buf
        int     25h
        pop     bx
        call    res
        jmp     quit

rd:     mov     al, 2
        mov     cx, 0FFFFh
        mov     bx, pkt
        int     25h
        pop     bx
        ret

res:    jnc     .ok                     ; "error hhhh" or "ok"
        jmp     short err
.ok:    mov     dx, s_ok
        jmp     say
fail:   call    err
quit:   mov     ax, 4C00h
        int     21h
say_q:  call    say
        jmp     quit
err:    mov     di, s_err + 6
        mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 15
        add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     stosb
        pop     ax
        loop    .h
        mov     dx, s_err
say:    mov     ah, 9
        int     21h
        ret

op      db 0
pkt     dd 0
        dw 1
        dw buf, 0
s_oem   db 'OEM='
oem     db '........', ' '
s_if    db 'IF=0', 13, 10, '$'
s_ok    db 'ok', 13, 10, '$'
s_err   db 'error hhhh', 13, 10, '$'
s_wrote db 'written', 13, 10, '$'
line    db '........', 13, 10, '$'
buf     times 512 db 0
