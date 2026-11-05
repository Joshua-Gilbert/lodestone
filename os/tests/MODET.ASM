; MODET.COM - a program that names its modes (the Executive's right-click
; menu, EXEC.INC's ex_modes; tests/test_apps.py and test_mt.py t_modes):
; its command tail into TAIL.TXT (as it came: " /A B"), and on the screen.
; -DEND=n: the third mode's arguments end with their 0 at offset n: 127
; (MODEL.COM) is past the 127 bytes the Executive reads, so it offers two;
; 126 (MODEE.COM), the last of them, three.
;   nasm -f bin -o MODET.COM MODET.ASM
org 100h
        jmp     short start
        db      'LMOD'
        db      80h, 'Plain', 0, '/A B', 0      ; (as Open: MULTITASK=1, a task)
        db      83h, 'Pause', 0, '/P', 0        ; (the Executive's task, a key after)
%ifdef END
        db      81h, 'Full', 0
        times   END - ($ - $$) db 'x'
        db      0
%else
        db      81h, 'Full', 0, '/F', 0         ; (the Executive's task)
%endif
        db      0
start:  mov     ah, 3Ch
        xor     cx, cx
        mov     dx, fname
        int     21h
        jc      .x
        xchg    bx, ax
        mov     cl, [80h]
        xor     ch, ch
        mov     dx, 81h
        mov     ah, 40h
        int     21h
        mov     ah, 3Eh
        int     21h
        mov     cl, [80h]
        mov     dx, 81h
        mov     bx, 1
        mov     ah, 40h
        int     21h
.x:     mov     ax, 4C00h
        int     21h
fname   db      'TAIL.TXT', 0
