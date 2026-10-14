; =====================================================================
;  CELLTEXT.INC - text in cells, with `cell` (CELL.INC): Term's status
;  band in CLAUDE.COM and in resident Claude's console (RCON.ASM)
; =====================================================================

; DS:SI -> ASCIIZ, ES:DI = cell, AH = attribute, CX = most cells.
; Returns DI after the text.
draw_strn:
        push    ax
        push    cx
        jcxz    .x
.l:     lodsb
        or      al, al
        jz      .x
        push    ax
        call    cell
        pop     ax
        inc     di
        loop    .l
.x:     pop     cx
        pop     ax
        ret

; DX = row, AH = attribute: 80 blank cells
blank_row:
        push    ax
        push    cx
        push    di
        imul    di, dx, 320
        mov     cx, 80
        mov     al, ' '
.l:     push    ax
        call    cell
        pop     ax
        inc     di
        loop    .l
        pop     di
        pop     cx
        pop     ax
        ret

strlen: push    si                      ; DS:SI -> CX
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .x
        inc     cx
        jmp     .l
.x:     pop     si
        ret
