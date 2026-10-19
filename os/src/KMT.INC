; =====================================================================
;  KMT.INC - multitasking, behind a switch: MULTITASK=1 in \LODE.INI
;  (with EMS; without it, it stays off).  Being built in steps (the plan:
;  docs/lodestone-multitasking.md); this is the first, the switch and the
;  skeleton: one task, the Executive, and nothing switches yet.
;
;  Off, none of it is in memory: its start-up (mt_boot, section boot) is
;  only in the load image, its resident part (section mtt) isn't even in
;  LODE.SYS, and INT 21h F0h with AL = 10h and up fails as before (f_F0's
;  f_bad).  The resident part is the file's last section, which the build
;  (mkmt.py) cuts off into LODEMT.SYS, writing its checksum into mt_sum.
;  On, mt_boot (from md_boot, after M:) reads \LODEMT.SYS from the drive
;  started from (R: from the ROM) into a block of its own (owner 8, "MT")
;  at the top of memory: a filler block takes the rest first, then goes,
;  so DOS programs still get one block below it, and the UI block keeps its
;  room for a .RUN right after it.  A LODEMT.SYS that isn't this LODE.SYS's
;  (shorter, or its first MT_LEN bytes' checksum differs), none, or no
;  room: it stays off.  The
;  part runs in its own segment, assembled from 0; it reaches the kernel
;  with far jumps, so it doesn't have to be within KSEG's 64 KB.
;    - INT 08h goes through mt_tick (the BIOS's handler first);
;    - INT 21h F0h through mt_f0: f_F0's first 5 bytes (MOV AL,[BP+F_AX]
;      and OR AL,AL) become a far jump to it, and it comes back past
;      them.  (KEMS.INC patches f_F0.lend and .back, further in: no
;      clash.)
;  The calls: MTAPI.INC.
; =====================================================================
%ifndef NOTC
%include "MTAPI.INC"

; ---- the resident part (in its own segment, from 0) -----------------
section mtt
mt_tstart:
mt_old08    dd      0                   ; INT 08h as it was
mt_ticks    dw      0                   ; ticks seen (mt_tick runs)
mt_front    db      0                   ; the task in front
            align   2
mt_tab:     db      0, TS_RUN           ; task 0: the Executive
            dw      0                   ;  (its PSP: mt_boot)
            db      'Executive', 0, 0, 0
            times   (MT_TASKS - 1) * MT_REC db 0

; INT 08h: the BIOS's handler first (the tick count, INT 1Ch, the end of
; the interrupt), then ours
mt_tick:
        pushf
        call    far [cs:mt_old08]
        inc     word [cs:mt_ticks]
        iret

; INT 21h AH=F0h, from f_F0's first bytes: DS = SS = KSEG, BP = the frame
mt_f0:  mov     al, [bp+F_AX]
        cmp     al, MT_LIST
        je      .list
        or      al, al                  ; (f_F0's own two, then on there)
        jmp     KSEG:f_F0 + 5
; MT_LIST: the records of the tasks there are, as many as fit in CX
.list:  mov     es, [bp+F_ES]
        mov     di, [bp+F_DI]
        mov     dx, [bp+F_CX]           ; (room)
        push    cs
        pop     ds
        mov     si, mt_tab
        xor     cx, cx
        mov     bx, MT_TASKS
.l:     cmp     byte [si+TR_STATE], TS_FREE
        je      .n
        inc     cx
        cmp     cx, dx
        ja      .n                      ; (no room: only counted)
        push    cx
        push    si
        mov     cx, MT_REC / 2
        rep     movsw
        pop     si
        pop     cx
.n:     add     si, MT_REC
        dec     bx
        jnz     .l
        mov     al, [mt_front]
        mov     [bp+F_CX], cx
        mov     [bp+F_AX], al
        jmp     KSEG:ok                 ; (DS = KSEG again there)
mt_tend:
MT_LEN      equ     mt_tend - mt_tstart
MT_PARAS    equ     (MT_LEN + 15) / 16

; ---- start-up (section boot, in the load image: CS = 1000h) ----------
section boot
mt_on   db      0                       ; md_boot: MULTITASK=1 is in LODE.INI
mt_sum  dw      0                       ; LODEMT.SYS's checksum (mkmt.py)
s_mteq  db      'MULTITASK', 1Dh, 0     ; (as "MULTITASK=" AND 0DFh)
s_mtsys db      '@:\LODEMT.SYS', 0

; \LODEMT.SYS into a block at the top of memory, INT 08h and INT 21h F0h
; through it.  No such file, not this LODE.SYS's, or no room: it stays off.
mt_boot:
        push    cs
        pop     ds
        mov     ax, 3305h               ; on the drive started from
        int     21h
        add     dl, 'A' - 1
        mov     [MDB(s_mtsys)], dl
        mov     dx, MDB(s_mtsys)
        mov     ax, 3D00h
        int     21h
        jc      .x
        mov     bp, ax                  ; BP = the file
        mov     ah, 48h
        mov     bx, 0FFFFh
        int     21h                     ; -> BX = the largest block
        sub     bx, MT_PARAS + 1
        jbe     .cl
        mov     ah, 48h                 ; a filler: all of it but MT's block
        int     21h                     ;  (and its MCB)
        jc      .cl
        mov     es, ax
        mov     ah, 48h
        mov     bx, MT_PARAS
        int     21h                     ; (the rest: the very end)
        pushf
        push    ax
        mov     ah, 49h                 ; the filler goes
        int     21h
        pop     dx                      ; DX = MT's block
        popf
        jc      .cl
        mov     es, dx
        dec     dx                      ; the last block?  (Not if a hole
        mov     ds, dx                  ;  below the largest one took it.)
        cmp     byte [0], 'Z'
        jne     .fr
        push    es
        pop     ds
        xor     dx, dx
        mov     cx, MT_LEN
        mov     bx, bp
        mov     ah, 3Fh                 ; the file into it
        int     21h
        push    cs
        pop     ds
        jc      .fr
        cmp     ax, MT_LEN
        jne     .fr
        xor     si, si                  ; this LODE.SYS's?  (mkmt.py's sum:
        xor     dx, dx                  ;  rotate left, add the byte)
        xor     ax, ax
        mov     cx, MT_LEN
.s:     mov     al, [es:si]
        rol     dx, 1
        add     dx, ax
        inc     si
        loop    .s
        cmp     dx, [MDB(mt_sum)]
        jne     .fr
        mov     ah, 3Eh
        mov     bx, bp
        int     21h
        mov     dx, es
        mov     ah, 62h                 ; task 0: the Executive, the root
        int     21h                     ;  process
        mov     [es:mt_tab+TR_PSP], bx
        dec     dx
        mov     ds, dx
        mov     word [1], 8             ; the system's, called MT
        mov     word [8], 'MT'
        xor     ax, ax
        mov     ds, ax
        cli
        mov     ax, [8 * 4]             ; INT 08h
        mov     [es:mt_old08], ax
        mov     ax, [8 * 4 + 2]
        mov     [es:mt_old08 + 2], ax
        mov     word [8 * 4], mt_tick
        mov     [8 * 4 + 2], es
        sti
        mov     ax, KSEG                ; INT 21h F0h: JMP FAR mt_f0
        mov     ds, ax
        mov     byte [f_F0], 0EAh
        mov     word [f_F0 + 1], mt_f0
        mov     [f_F0 + 3], es
        push    cs
        pop     ds
        ret
.fr:    push    cs                      ; (no: MT's block goes, and the file
        pop     ds                      ;  is closed)
        mov     ah, 49h
        int     21h
.cl:    mov     bx, bp
        mov     ah, 3Eh
        int     21h
.x:     ret
%endif
