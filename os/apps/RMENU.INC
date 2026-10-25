; RMENU.INC - a right click's menu (UI_MENU) of the items that apply now:
; Write's and TERM's (T4).  SI = the items, a record each (dw its text,
; the routine it runs, what it needs: RM_SEL a selection, RM_CLIP
; something to paste; a 0 word after the last); AL = RM_SEL with a
; selection; BX, CX = where (EV_RCLICK's).  Jumps to the routine of the
; item chosen; returns with none (ESC, a click outside).  At least one
; item must need nothing.  The caller's BSS: rm_buf, rm_do (a word an item)
RM_SEL      equ 1
RM_CLIP     equ 2
rmenu:  push    bx
        push    cx
        push    ax
        mov     al, 2                   ; (what the clipboard holds)
        call    UI_CLIP
        pop     dx                      ; DL = what applies
        jcxz    .n
        or      dl, RM_CLIP
.n:     not     dl                      ; (DL: what doesn't)
        xor     di, di
.i:     lodsw
        or      ax, ax
        jz      .m
        xchg    ax, bx
        lodsw
        xchg    ax, cx
        lodsw
        test    al, dl
        jnz     .i
        mov     [rm_buf + di], bx
        mov     [rm_do + di], cx
        add     di, 2
        jmp     .i
.m:     xchg    ax, di
        shr     ax, 1                   ; AL = how many (AH 0: the first lit)
        pop     cx
        pop     bx
        mov     si, rm_buf
        call    UI_MENU
        jc      .x
        mov     bx, ax
        add     bx, bx
        jmp     [rm_do + bx]
.x:     ret
