; TESTKEY.COM - a child program for CLAUDE's RUN tests: reads keys through
; INT 16h (so CLAUDE's key-script hook feeds it), echoes them, quits on Esc
; with the number of keys as its exit code.
cpu 286
org 100h
start:  mov     ax, 0003h
        int     10h
        mov     si, msg
        call    puts
        xor     bx, bx
.l:     xor     ah, ah
        int     16h
        cmp     al, 1Bh
        je      .done
        inc     bx
        mov     ah, 0Eh
        int     10h
        jmp     .l
.done:  mov     si, bye
        call    puts
        mov     al, bl
        mov     ah, 4Ch
        int     21h
puts:   lodsb
        or      al, al
        jz      .x
        mov     ah, 0Eh
        int     10h
        jmp     puts
.x:     ret
msg     db 'TESTKEY ready: ', 0
bye     db 13, 10, 'bye', 0
