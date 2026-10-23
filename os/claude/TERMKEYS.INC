; =====================================================================
;  TERMKEYS.INC - Term's keyboard: every key goes to the Pi as the word
;  INT 16h AH=10h returns (the Pi turns it into an xterm's bytes), except
;  CODE-Q (quit) and CODE-R (repaint).  AH=10h/11h, not 00h/01h: the 1520
;  BIOS gives CODE with punctuation, Return, Esc and Backspace only to
;  those.  Keys typed while a KEYS message is on its way wait in keybuf
;  and go together in the next one.
;  Resident Claude's console (RCON.ASM) defines its own K_QUIT and K_QUIT2
;  (the keys back to the program) and `kbd` (the BIOS's INT 16h, past the
;  stub's hook).
; =====================================================================
KEYMAX  equ 64                          ; keys in one KEYS message
%ifndef K_QUIT
K_QUIT  equ 1000h                       ; CODE-Q
%endif
K_PAINT equ 1300h                       ; CODE-R
K_CTRLL equ 260Ch                       ; Ctrl-L: repaint here, and the Pi's too
%ifndef KBD_OWN
%macro kbd 0
        int     16h
%endmacro
%endif

term_kbd:
%ifdef KBD_EVERY
        cmp     byte [lstate], LS_IDLE  ; while a frame is on its way, the keys
        je      .l                      ;  (and the mouse) every KBD_EVERY PIT
        mov     ax, [now]               ;  counts, not every round of the main
        cmp     ax, [kbd_tick]          ;  loop: INT 16h and INT 33h took
        jne     .due                    ;  ~0.25 ms a round on the 1520
        call    pit_read
        mov     dx, [kbd_pit]
        sub     dx, ax
        cmp     dx, KBD_EVERY
        jae     .due
        ret
.due:   call    pit_read
        mov     [kbd_pit], ax
        mov     ax, [now]
        mov     [kbd_tick], ax
%endif
.l:     mov     ah, 11h
        kbd
        jz      term_send
        cmp     byte [keyn], KEYMAX
        jae     term_send               ; full: they wait in the BIOS
        mov     ah, 10h
        kbd
        cmp     ax, K_QUIT
%ifdef K_QUIT2
        je      .qt
        cmp     ax, K_QUIT2
%endif
        jne     .p
.qt:    mov     byte [quit], 1
        ret
.p:     cmp     ax, K_PAINT
        jne     .c
        call    term_repaint
        jmp     .l
.c:     cmp     byte [connected], 0
        je      .l                      ; no Pi: nothing to type into
        cmp     ax, K_CTRLL
        jne     .k
        call    term_redraw
        mov     ax, K_CTRLL
.k:     mov     bl, [keyn]
        xor     bh, bh
        shl     bx, 1
        mov     [keybuf + bx], ax
        inc     byte [keyn]
        mov     ax, [now]
        mov     [t_active], ax
        jmp     .l
term_send:                              ; the keys typed so far: one KEYS at a time
%ifdef TERM_MOUSE
        call    term_mouse
%endif
        cmp     byte [keyn], 0
        je      .x
        cmp     byte [keys_q], 0
        jne     .x
        cmp     byte [txq_n], TXQN      ; (txq_put drops what doesn't fit)
        jae     .x
        mov     cl, [keyn]
        xor     ch, ch
        shl     cx, 1
        push    cx
        mov     si, keybuf
        mov     di, keysend
        rep     movsb
        pop     cx
        mov     byte [keyn], 0
        mov     byte [keys_q], 1
        mov     al, G_KEYS
        mov     si, keysend
        call    txq_put_cs
.x:     ret

%ifdef TERM_MOUSE
; A left click to the Pi: EVENT 05h and where, in pixels.  INT 33h AX=5 counts
; presses since it was last asked, so a quick click between two polls isn't
; missed.  One EVENT at a time (rep_q), and a queue slot left for a REPLY,
; as for CODE-R.  (A link restart empties the queue.)
term_mouse:
        cmp     byte [tmouse], 0
        je      .x
        cmp     byte [rep_q], 0
        jne     .x
        cmp     byte [txq_n], TXQN - 1
        jae     .x
        mov     ax, 5
        xor     bx, bx                  ; the left button
        int     33h                     ; BX = presses, CX, DX = where the last was
        or      bx, bx
        jz      .x
        mov     [evmouse + 1], cx       ; x 0-639, y 0-399
        mov     [evmouse + 3], dx
        mov     byte [rep_q], 1
        mov     al, G_EVENT
        mov     si, evmouse
        mov     cx, 5
        jmp     txq_put_cs
.x:     ret
%endif

; CODE-R: redraw from the shadow now, and ask the Pi for a fresh screen
term_repaint:
        call    term_redraw
        cmp     byte [connected], 0
        je      .x
        cmp     byte [rep_q], 0         ; one at a time, and a slot left over
        jne     .x
        cmp     byte [txq_n], TXQN - 1
        jae     .x
        mov     byte [rep_q], 1
        mov     al, G_EVENT
        mov     si, evrepaint
        mov     cx, 1
        call    txq_put_cs
.x:     ret
