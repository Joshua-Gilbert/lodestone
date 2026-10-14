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
        mov     dx, cs
        mov     si, keysend
        call    txq_put
.x:     ret

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
        mov     dx, cs
        mov     si, evrepaint
        mov     cx, 1
        call    txq_put
.x:     ret
