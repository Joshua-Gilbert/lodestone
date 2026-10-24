; WINPOS.INC - a window .RUN's window (win: W_COL, W_Y, W_W, W_H) opened a
; little lower and to the right when its slot is higher up the segment
; than the first's (UI_VERSION's CX: the core's paragraphs, where the
; windows' slots start), so a second one isn't right over the first:
; 4 KB steps, two at most.  Write's and TERM's (in a window: MT_WIN)
%macro WIN_STAGGER 0
        call    UI_VERSION
        shl     cx, 4
        mov     ax, start
        sub     ax, cx
        jb      %%x
        mov     cl, 12
        shr     ax, cl
        cmp     ax, 2
        jbe     %%c
        mov     ax, 2
%%c:    mov     bx, ax
        shl     bx, 1
        add     [win+W_COL], bx
        sub     [win+W_W], bx
        shl     ax, 4
        add     [win+W_Y], ax
        sub     [win+W_H], ax
%%x:
%endmacro
