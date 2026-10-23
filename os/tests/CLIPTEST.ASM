; CLIPTEST.RUN - UI_CLIP (UI API 8) as a .RUN sees it (tests/test_apps.py
; t_clip, tests/test_mt.py).  A window .RUN with a block of its own (bseg:
; 0 is what P puts, 16400 where G gets).  P: UI_CLIP AL=0 with plen bytes;
; G: AL=1 with gmax room (CX after it in gcx); S: AL=2 (CX in scx).  Each
; leaves its CF in rcf (FFFFh: set) and AX in rret.  ESC: the end.
;   python3 mkrun.py tests/CLIPTEST.ASM tests/CLIPTEST.RUN
%include "UIAPI.INC"
RUN_API equ 8
RUN_FLAGS equ RF_WIN
        org     RUN_ORG

GOFF    equ 16400

start:  mov     bx, 2 * GOFF / 16 + 1
        call    UI_ALLOC
        jc      .x
        mov     [bseg], ax
        mov     si, win
        call    UI_WOPEN
.l:     call    UI_EVENT
        cmp     ax, K_ESC
        je      .end
        mov     es, [bseg]
        xor     di, di
        mov     cx, [plen]
        mov     dl, al
        xor     ax, ax                  ; P: put
        cmp     dl, 'P'
        je      .call
        mov     di, GOFF
        mov     cx, [gmax]
        inc     ax                      ; G: get
        cmp     dl, 'G'
        je      .call
        inc     ax                      ; S: its size
        cmp     dl, 'S'
        jne     .l
.call:  call    UI_CLIP
        sbb     dx, dx
        mov     [rcf], dx
        mov     [rret], ax
        mov     [gcx], cx               ; (G's and S's CX; P's is plen)
        mov     [scx], cx
        push    ds
        pop     es
        jmp     .l
.end:   call    UI_WCLOSE
.x:     xor     ax, ax
        ret

win     dw 30, 100, 20, 60, s_win, 0, 0
s_win   db 'Clip test',0

section .bss
bseg    resw 1
plen    resw 1
gmax    resw 1
gcx     resw 1
scx     resw 1
rcf     resw 1
rret    resw 1
run_bss_end:
