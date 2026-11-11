; RMENU.INC - a right click's menu (UI_MENU) of the items that apply now:
; Write's and TERM's.  SI = the items, a record each (dw its text,
; its key, what it needs: RM_SEL a selection, RM_CLIP something to
; paste; a 0 word after the last); AL = RM_SEL with a selection; BX, CX =
; where (EV_RCLICK's).  -> AX = the key of the item chosen, for the
; caller to take as typed; CF with none (ESC, a click outside; no menu at
; all, and no beep, with no item that applies).  The caller's BSS:
; rm_buf, rm_key (a word an item)
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
        mov     [rm_key + di], cx
        add     di, 2
        jmp     .i
.m:     xchg    ax, di
        shr     ax, 1                   ; AL = how many (AH 0: the first lit)
        pop     cx
        pop     bx
        cmp     al, 1                   ; (none: CF)
        jb      .x
        mov     si, rm_buf
        call    UI_MENU
        jc      .x
        mov     bx, ax
        add     bx, bx                  ; (CF clear)
        mov     ax, [rm_key + bx]
.x:     ret
