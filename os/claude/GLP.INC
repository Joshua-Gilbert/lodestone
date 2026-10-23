; =====================================================================
;  GLP.INC - GLP 1's message types and the link's states (gridlink/
;  PROTOCOL.md).  CLAUDE.COM and resident Claude's console (RCON.ASM)
;  both speak it, through TERMLINK.INC.
; =====================================================================
LS_RESET equ 0
LS_IDLE  equ 1
LS_WAIT  equ 2

G_HELLO   equ 01h
G_POLL    equ 02h
G_PROMPT  equ 03h
G_EVENT   equ 04h
G_REPLY   equ 05h
G_NAK     equ 06h
G_KEYS    equ 07h
P_HELLO   equ 41h
P_NOP     equ 42h
P_TEXT    equ 43h
P_STATUS  equ 44h
P_REQUEST equ 45h
P_ASK     equ 46h
P_READY   equ 47h
P_NAK     equ 48h
P_TITLE   equ 49h
P_CLEAR   equ 4Ah
P_CELLS   equ 4Bh
HF_TERM   equ 01h                ; the Pi's HELLO: Term
HF_FCS    equ 04h                ; the Pi's HELLO: frames carry the Fletcher sum from now on
GF_FCS    equ 04h                ; our HELLO: we can check frames with the Fletcher sum
GF_WAKE   equ 08h                ; our HELLO: an SRQ while we are idle makes us POLL at once
OP_SCREEN equ 11h                ; REQUEST ops the console answers (CLAUDE.COM's
OP_TYPE   equ 12h                ;  optab has its own); TYPE is the console's only

; PROF n: in a profiling build (nasm -dPROFILE: CLAUDEP.COM, PROF.INC), the
; time from here on goes to bucket n; nothing otherwise.  Keeps every
; register and the flags.
%macro PROF 1
%ifdef PROFILE
        pushf
        push    ax
        mov     al, %1
        call    prof_sw
        pop     ax
        popf
%endif
%endmacro
