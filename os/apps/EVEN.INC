; EVEN.INC - a .RUN's hot labels on even offsets: on the 286 a taken jump to
; an odd address costs more prefetch.  The pads, `times ($ - $$) & 1 db
; 90h` (the label after even) or `times ($ + 1 - $$) & 1 db 90h` (odd), each
; after a JMP or RET, never run nor in front of data, hold wherever the
; code before them moves; mkrun.py's two builds (1110h apart) give them the
; same bytes.  A .RUN loads on a paragraph (run_app's run_base, a window
; .RUN's slot), so an offset's parity is the address's.  bench/hot.py counts
; the taken entries ("ap_taken"), bench/plan.py SECTION=app SC=1 places the
; pads; `EVEN label, ...` after the labels it names stops the build if one
; is odd
%macro EVEN 1-*
%rep %0
        times -((%1 - $$) & 1) db 0
%rotate 1
%endrep
%endmacro
