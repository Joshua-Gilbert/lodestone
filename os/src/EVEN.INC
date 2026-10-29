; EVEN.INC - hot labels on even offsets: on the 286 a taken jump to an odd
; address costs more prefetch.  The pads, `times ($ - $$) & 1 db 90h` (the
; label after even) or `times ($ + 1 - $$) & 1 db 90h` (odd), each after a
; JMP or RET, never run nor in front of data, hold wherever the code before
; them moves.  `EVEN label, ...` after the labels it names stops the build if
; one is odd (relative to the section's start, $$: the code must load on a
; paragraph for that to be the address's parity).  bench/hot.py counts the
; taken entries, bench/plan.py places the pads.  Used by the kernel
; (LODE.ASM), LCMD.COM, CLAUDE.COM and RCON (TERMLINK.INC), and the .RUN
; apps: a .RUN loads on a paragraph (run_app's run_base, a window .RUN's
; slot), and mkrun.py's two builds (1110h apart) give its pads the same
; bytes ("ap_taken", plan.py SECTION=app SC=1)
%ifndef EVEN_INC
%define EVEN_INC
%macro EVEN 1-*
%rep %0
        times -((%1 - $$) & 1) db 0
%rotate 1
%endrep
%endmacro
%endif
