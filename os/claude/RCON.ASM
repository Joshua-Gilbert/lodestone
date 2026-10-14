; =====================================================================
;  RCON.ASM - resident Claude's console: the pop-up (CLAUDE /R)
;  Build:  nasm -f bin -i ../src/ -o RCON.BIN RCON.ASM   (before CLAUDE.ASM,
;          which carries it: CLAUDE /R copies it into its first EMS page
;          and clears the rest of the page)
;
;  Runs at E000:0000, called far by CLAUDE.COM's resident stub from inside
;  INT 16h, on the stub's stack, with the program's EMS windows saved and
;  ours mapped: window 0 this code and its data, kept from one pop-up to
;  the next (Term's screen, the link's state); windows 1-2 (E400h) the
;  program's screen while the console is up.  ES:BX -> the stub's
;  parameters.  It calls nothing but INT 10h, the BIOS's INT 16h (the
;  stub's old16), INT 33h and the GPIB driver (found from vectors 60h-66h,
;  'GRIDGPIB' at entry+2): DOS may be busy under the program (indos).
;  A DOS program's mouse pointer (INT 33h, drawn from the mouse's IRQ) is
;  hidden while the console is up, so a move then draws nothing on the
;  console and leaves no wrong cell on the program's screen.  Its event
;  handler (INT 33h AX=0Ch/14h) is swapped out meanwhile, so clicks meant
;  for the console don't reach the program (on our stack), unless DOS is
;  busy: AX=14h makes a DOS call (AH=62h).
;
;  Everything the program had comes back byte for byte: its video mode,
;  the 32 KB of video memory, the BIOS's video data (40:49h-66h), and the
;  keys it had typed ahead (kept aside meanwhile, so the console can't
;  read them).
;
;  M2: the console is Term, Claude Code on the Pi in the same session as
;  CLAUDE /T, through CLAUDE.COM's own TERMLINK, TERMCELL and TERMKEYS.
;  Each pop-up draws Term's screen from its shadow at once and says HELLO
;  (app=resident) with the shadow's CRC: the Pi goes on from that screen
;  when it is one it sent (only what changed meanwhile comes), else draws
;  it again from a clear screen (CLAUDE /T had the link meanwhile).
;  CODE-\ or CODE-Q goes back, once the keys typed before it have gone and
;  the last frame has its answer (else the bridge would hold SRQ up while
;  the program runs).  The GPIB
;  driver's SRQ check (AH=0Bh) is never called: it clears the program's
;  latch.  Requests (files, RUN, GPIB) are M3's: each is answered F6h, a
;  DOS program is paused.
; =====================================================================
cpu 286
org 0

%define NO_SRQ                          ; TERMLINK: no INT 60h AH=0Bh
%define K_QUIT 2B00h                    ; TERMKEYS: CODE-\ back to the program,
%define K_QUIT2 1000h                   ;  CODE-Q too
%define KBD_OWN                         ;  and the BIOS's INT 16h, past the stub
%macro kbd 0
        pushf
        call    far [old16]
%endmacro

VSEG    equ 0B800h
SAVESEG equ 0E400h              ; windows 1-2: the program's screen
P_OLD16 equ 0                   ; the stub's parameters (CLAUDE.ASM r_params)
P_INDOS equ 4
NKEYS   equ 16
TXMAX   equ 256                 ; GRiD -> Pi payload: HELLO, POLL, KEYS, REPLY
RXMAX   equ 255
TXQN    equ 6
TITLEN  equ 36                  ; the Pi's title, then DOS busy (48 cells)
%include "GLP.INC"

        jmp     short rc_main
nano    db      7               ; offset 2: CLAUDE /R /A:nn (CLAUDE.ASM RC_NANO)
term    db      1               ; (TERMLINK: Term's polling)
busy    db      0               ;  (and no chat turn)

rc_main:
        push    ds
        push    cs
        pop     ds
        cld
        mov     ax, [es:bx + P_OLD16]   ; the BIOS's INT 16h, and is DOS busy?
        mov     [old16], ax
        mov     ax, [es:bx + P_OLD16 + 2]
        mov     [old16 + 2], ax
        push    ds
        lds     si, [es:bx + P_INDOS]
        lodsb
        pop     ds
        mov     [indos], al
        xor     ax, ax                  ; INT 33h there?  The program's
        mov     es, ax                  ;  pointer off (its own cell back
        mov     [mouse], al             ;  first, before the screen is kept)
        mov     [mswap], al
        mov     ax, [es:33h * 4]
        or      ax, [es:33h * 4 + 2]
        jz      .nm
        inc     byte [mouse]
        mov     ax, 2
        int     33h
        cmp     byte [indos], 0         ; and its event handler off (AX=14h,
        jne     .nm                     ;  no events), else clicks meant for
        mov     ax, 14h                 ;  the console reach the program, on
        xor     cx, cx                  ;  our stack.  (14h makes a DOS call,
        xor     dx, dx                  ;  AH=62h: not while DOS is busy)
        mov     es, dx
        int     33h
        mov     [mh_mask], cx
        mov     [mh_off], dx
        mov     [mh_seg], es
        inc     byte [mswap]
.nm:    push    cs
        pop     es
        push    ds                      ; the BIOS's video data, and the keys
        push    40h                     ;  typed ahead: out of its buffer
        pop     ds
        mov     si, 49h
        mov     di, bios
        mov     cx, 66h - 49h + 1
        rep     movsb
        cli
        mov     si, [1Ah]
        mov     di, keys
        xor     cx, cx
.k:     cmp     si, [1Ch]
        je      .kd
        cmp     cx, NKEYS
        jae     .kd
        movsw
        inc     cx
        cmp     si, [82h]
        jb      .k
        mov     si, [80h]
        jmp     .k
.kd:    mov     ax, [1Ch]
        mov     [1Ah], ax
        sti
        pop     ds
        mov     [nkeys], cx
        push    ds                      ; the screen, to windows 1-2
        push    VSEG
        pop     ds
        push    SAVESEG
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 4000h
        rep     movsw
        pop     ds
        mov     ax, 0040h               ; the console
        int     10h
        push    cs
        pop     es
        call    session
        mov     al, [bios]              ; the program's mode, screen and data
        xor     ah, ah
        int     10h
        push    ds
        push    SAVESEG
        pop     ds
        push    VSEG
        pop     es
        xor     si, si
        xor     di, di
        mov     cx, 4000h
        rep     movsw
        pop     ds
        push    40h
        pop     es
        mov     si, bios
        mov     di, 49h
        mov     cx, 66h - 49h + 1
        rep     movsb
        cmp     byte [bios], 3          ; text: the cursor as it was
        ja      .g
        mov     cx, [bios + 60h - 49h]
        mov     ah, 1
        int     10h
        mov     bl, [bios + 62h - 49h]
        xor     bh, bh
        shl     bx, 1
        mov     dx, [bios + 50h - 49h + bx]
        mov     bh, [bios + 62h - 49h]
        mov     ah, 2
        int     10h
        jmp     short .t
.g:     cmp     byte [bios], 6          ; CGA graphics: its colour register
        ja      .t
        mov     dx, 3D9h
        mov     al, [bios + 66h - 49h]
        out     dx, al
.t:     call    keys_back
        cmp     byte [mswap], 0         ; the program's event handler back
        je      .ms
        mov     ax, 14h
        mov     cx, [mh_mask]
        mov     dx, [mh_off]
        mov     es, [mh_seg]
        int     33h
.ms:    cmp     byte [mouse], 0         ; and its pointer, where the mouse
        je      .x                      ;  is now
        mov     ax, 1
        int     33h
.x:     pop     ds
        retf

; the keys typed ahead go back in front of any typed since (the head moves
; back one word for each; as many as there is room for)
keys_back:
        mov     cx, [nkeys]
        jcxz    .x
        push    ds
        push    40h
        pop     ds
        cli
        mov     ax, [1Ch]               ; room: the buffer's keys (a word
        sub     ax, [1Ah]               ;  less than its size: head = tail
        jae     .n                      ;  is empty) less those there now
        add     ax, [82h]
        sub     ax, [80h]
.n:     shr     ax, 1
        mov     dx, [82h]
        sub     dx, [80h]
        shr     dx, 1
        dec     dx
        sub     dx, ax
        jae     .c
        xor     dx, dx
.c:     cmp     cx, dx
        jbe     .r
        mov     cx, dx
.r:     jcxz    .d
        mov     si, cx                  ; the last of ours first
        shl     si, 1
        add     si, keys - 2
        mov     bx, [1Ah]
.l:     cmp     bx, [80h]
        ja      .b
        mov     bx, [82h]
.b:     dec     bx
        dec     bx
        mov     ax, [cs:si]
        mov     [bx], ax
        dec     si
        dec     si
        loop    .l
        mov     [1Ah], bx
.d:     sti
        pop     ds
.x:     ret

; =====================================================================
;  Term over the link until CODE-\ or CODE-Q.  DS = ES = CS.
; =====================================================================
session:
        cmp     byte [inited], 0        ; the first time: the CRC table, Term's
        jne     .i                      ;  screen blank, our title
        call    crc_init
        call    shadow_seg
        call    shadow_clear
        mov     si, s_title0
        mov     di, ptitle
        call    copyz
        mov     byte [inited], 1
.i:     call    shadow_seg
        call    make_title
        call    get_ticks
        mov     [now], ax
        mov     [t_active], ax
        mov     byte [quit], 0
        mov     byte [connected], 0
        mov     byte [n_failrun], 0
        mov     byte [sdc_due], 0
        call    find_gpib
        sbb     al, al                  ; (none: 0FFh)
        inc     al
        mov     [gp_ok], al
        mov     si, st_nogpib
        jz      .st
        mov     byte [lstate], LS_RESET ; HELLO at once
        mov     ax, [now]
        sub     ax, 18
        mov     [t_reset], ax
        mov     si, st_connecting
.st:    call    set_status
        call    term_redraw             ; Term's screen from the shadow, the band
.loop:  call    get_ticks
        mov     [now], ax
        cmp     byte [gp_ok], 0
        je      .k
        call    link_service
.k:     call    term_kbd
        cmp     byte [quit], 0
        jne     .out
        call    idle
        jmp     .loop
.out:   cmp     byte [gp_ok], 0         ; before going back: the keys typed so
        je      .x                      ;  far and what is queued go, and the
        mov     ax, [now]               ;  last frame gets its answer (else
        mov     [t_quit], ax            ;  the bridge would hold it, and SRQ,
.d:     call    get_ticks               ;  while the program has the bus); 3 s
        mov     [now], ax               ;  at most
        sub     ax, [t_quit]
        cmp     ax, 54
        jbe     .w
        mov     byte [sdc_due], 1
        jmp     short .f
.w:     cmp     byte [lstate], LS_WAIT
        jne     .s
        call    link_wait
        jmp     .d
.s:     cmp     byte [lstate], LS_IDLE  ; (the link failed: nothing to send)
        jne     .f
        cmp     byte [connected], 0
        je      .f
        call    term_send
        cmp     byte [txq_n], 0
        je      .f
        call    link_service            ; (the next frame)
        jmp     .d
.f:     cmp     byte [sdc_due], 0       ; the link failed meanwhile: the
        je      .x                      ;  bridge's line (and SRQ) cleared
        mov     bl, [nano]
        mov     ah, 06h
        call    gg_call
.x:     ret

shadow_seg:                             ; Term's shadow, in this page
        mov     ax, cs
        add     ax, (shadow - $$) >> 4
        mov     [shadseg], ax
        ret

; HLT when nothing is due: no frame on its way or to send, no keys, and
; quiet for 2 s (TERMLINK polls back to back until then)
idle:   cmp     byte [lstate], LS_WAIT
        je      .x
        mov     al, [txq_n]
        or      al, [nak_pending]
        or      al, [resend]
        or      al, [pi_active]
        or      al, [keyn]
        jnz     .x
        mov     ax, [now]
        sub     ax, [t_active]
        cmp     ax, 36
        jb      .x
        mov     ah, 11h
        kbd
        jnz     .x
        sti                             ; (STI's shadow covers the HLT)
        hlt
.x:     ret

; the GPIB driver: the first of vectors 60h-66h with 'GRIDGPIB' at
; entry+2 that answers AH=0 with 4747h.  CF if none.
find_gpib:
        mov     bx, 60h * 4
.v:     push    es
        xor     ax, ax
        mov     es, ax
        les     di, [es:bx]
        mov     ax, es
        or      ax, di
        jz      .n
        add     di, 2
        mov     si, sig_gg
        mov     cx, 8
        repe    cmpsb
        je      .f
.n:     pop     es
        add     bx, 4
        cmp     bx, 67h * 4
        jb      .v
        stc
        ret
.f:     xor     ax, ax
        mov     es, ax
        mov     ax, [es:bx]
        mov     [gpib], ax
        mov     ax, [es:bx + 2]
        mov     [gpib + 2], ax
        pop     es
        mov     ah, 0
        call    gg_call
        cmp     ax, 4747h
        je      .ok
        stc
        ret
.ok:    clc
        ret

gg_call:                                ; INT 60h-66h, the driver's
        pushf
        call    far [gpib]
        ret

; =====================================================================
;  the link: TERMLINK.INC, and what the console does with it
; =====================================================================
%include "TERMLINK.INC"

build_hello:                            ; -> CX = length of hellobuf
        mov     di, hellobuf
        mov     ax, 0101h               ; GLP 1; flags: Term
        stosw
        mov     ax, TXMAX
        stosw
        mov     ax, 24 * 256 + 80       ; 80 columns, 24 rows
        stosw
        mov     si, kv_hello
        call    put_str
        mov     al, [nano]
        call    put_num
        mov     al, 10
        stosb
        cmp     byte [have_screen], 0   ; the screen we kept, so the Pi can go
        je      .n                      ;  on from it if it is one it sent
        mov     si, kv_screen
        call    put_str
        call    screen_crc
        call    put_hex16
        mov     al, 10
        stosb
.n:     mov     byte [sdc_due], 0       ; (link_reset has just cleared it)
        mov     cx, di
        sub     cx, hellobuf
        ret

; AX = CRC-16 (TERMLINK's crc16) of the shadow (glyph, attribute, row by
; row), then the cursor's row, column and hidden (0 or 1): the Pi's
; termscreen.screen_crc
screen_crc:
        mov     si, shadow
        mov     cx, TROWS * 160
        mov     ax, 0FFFFh
        call    crc16
        mov     si, t_cur
        mov     cx, 2
        call    crc16
        mov     dl, [t_flags]
        shr     dl, 1
        and     dl, 1
        mov     [crc_hid], dl
        mov     si, crc_hid
        mov     cx, 1
        jmp     crc16

put_hex16:                              ; AX -> ES:DI, 4 hex digits
        mov     cx, 4
.d:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .s
        add     al, 7
.s:     stosb
        pop     ax
        loop    .d
        ret

msg_sent:
        mov     al, [done_type]
        cmp     al, G_KEYS
        jne     .e
        mov     byte [keys_q], 0        ; the next keys can go
        ret
.e:     cmp     al, G_EVENT
        jne     .r
        mov     byte [rep_q], 0         ; (the only EVENT: repaint)
        ret
.r:     cmp     al, G_REPLY
        jne     .x
        mov     byte [reply_busy], 0
.x:     ret

; the link went down (TERMLINK.INC link_fail): say so in the band
link_lost:
        mov     byte [connected], 0
        mov     byte [sdc_due], 1       ; (the bridge may hold a line, and SRQ)
        mov     si, st_lost
        cmp     byte [n_failrun], 3
        jae     .na
        call    set_status
        jmp     term_status
.na:    mov     di, status_text         ; "No answer from the bridge at GPIB
        mov     si, st_noans            ;  address 7"
        call    put_str
        mov     al, [nano]
        call    put_num
        mov     si, s_back
        call    copyz
        jmp     term_status

; ---- frames from the Pi ------------------------------------------
pi_frame:                               ; BX = frame offset in rxbuf
        mov     al, [rxbuf + bx + 1]
        mov     [pf_kind], al
        mov     cx, [rxbuf + bx + 4]
        lea     si, [rxbuf + bx + 6]
        and     al, 7Fh
        cmp     byte [connected], 0     ; the answer to our HELLO must be a HELLO:
        jne     .c                      ;  anything else, start the link again
        cmp     al, P_HELLO
        je      .c
        jmp     link_fail
.c:     mov     byte [pi_active], 1
        cmp     al, P_NOP
        jne     .h
        mov     byte [pi_active], 0
        ret
.h:     cmp     al, P_HELLO
        je      rf_hello
        cmp     al, P_CELLS
        je      rf_cells
        cmp     al, P_TITLE
        je      rf_title
        cmp     al, P_REQUEST
        je      rf_request
        ret                             ; (the chat's TEXT, STATUS, ASK... no)

rf_hello:
        mov     byte [connected], 1
        mov     byte [n_failrun], 0
        mov     byte [rq_more], 0
        mov     ax, [now]
        mov     [t_active], ax
        jmp     term_status

rf_cells:
        mov     ax, [now]
        mov     [t_active], ax
        mov     byte [have_screen], 1
        jmp     term_cells

rf_title:
        cmp     cx, TITLEN
        jbe     .c
        mov     cx, TITLEN
.c:     mov     di, ptitle
        rep     movsb
        mov     byte [di], 0
        call    make_title
        jmp     term_status

; a REQUEST: its id from the first frame, and when the last has come, the
; REPLY: F6h, a DOS program is paused (files, RUN and GPIB are M3's)
rf_request:
        cmp     byte [rq_more], 0
        jne     .c
        jcxz    .c
        mov     al, [si]
        mov     [rq_id], al
.c:     mov     al, [pf_kind]
        and     al, 80h
        mov     [rq_more], al
        jnz     .x
        cmp     byte [reply_busy], 0    ; (one at a time, as CLAUDE.COM)
        jne     .x
        cmp     byte [txq_n], TXQN
        jae     .x
        mov     al, [rq_id]
        mov     ah, 0F6h
        mov     [replybuf], ax
        mov     byte [reply_busy], 1
        mov     al, G_REPLY
        mov     dx, cs
        mov     si, replybuf
        mov     cx, 2
        call    txq_put
.x:     ret

; ---- the band ----------------------------------------------------
; title_text: the Pi's title (or ours), then DOS busy if DOS was
make_title:
        mov     si, ptitle
        mov     di, title_text
        call    put_str
        cmp     byte [indos], 0
        je      .z
        mov     si, s_dos
        call    put_str
.z:     mov     byte [di], 0
        ret

; status_text: SI, then how to go back
set_status:
        mov     di, status_text
        call    put_str
        mov     si, s_back
        ; (falls through)
copyz:  call    put_str                 ; DS:SI ASCIIZ -> ES:DI (with NUL)
        mov     byte [di], 0
        ret

put_str:                                ; DS:SI ASCIIZ -> ES:DI (no NUL)
.l:     lodsb
        or      al, al
        jz      .x
        stosb
        jmp     .l
.x:     ret

put_num:                                ; AL (0-99) -> ES:DI, decimal
        aam
        or      ah, ah
        jz      .u
        xchg    al, ah
        add     al, '0'
        stosb
        mov     al, ah
.u:     add     al, '0'
        stosb
        ret

; =====================================================================
;  Term's screen and keys: CLAUDE.COM's
; =====================================================================
%include "TERMCELL.INC"
%include "CELLTEXT.INC"
%include "TERMKEYS.INC"

sig_gg      db 'GRIDGPIB'
kv_hello    db 'app=resident', 10, 'grid=CLAUDE 1.1', 10, 'addr=', 0
kv_screen   db 'screen=', 0
s_title0    db 'Claude (resident)', 0
s_dos       db '  ', 86h, '  DOS busy', 0
s_tkeys     db 'CODE-\ back  CODE-R repaints', 0
s_back      db '  ', 86h, '  CODE-\ back', 0
st_connecting db 'Connecting to the Pi', 82h, 0
st_lost     db 'Link to the Pi lost, reconnecting', 82h, 0
st_noans    db 'No answer from the bridge at GPIB address ', 0
st_nogpib   db 'No GPIB driver (GRIDGPIB)', 0
evrepaint   db 03h

%include "TERMINUS.INC"
%include "GLYPHS.INC"

        align   2
rc_image_end:                           ; (CLAUDE /R clears the rest of the page)

absolute rc_image_end
inited      resb 1
old16       resd 1
indos       resb 1
mouse       resb 1                      ; not 0: INT 33h is there
mswap       resb 1                      ; not 0: its event handler swapped out
mh_mask     resw 1                      ;  (which was this)
mh_off      resw 1
mh_seg      resw 1
nkeys       resw 1
bios        resb 66h - 49h + 1
keys        resw NKEYS
quit        resb 1
t_quit      resw 1                      ; when CODE-\ came
gp_ok       resb 1                      ; the GPIB driver found
gpib        resd 1                      ;  at
sdc_due     resb 1                      ; the link failed: SDC to the bridge
now         resw 1
; the link (TERMLINK.INC)
connected   resb 1
pi_active   resb 1
lstate      resb 1
g_seq       resb 1
p_ack       resb 1
have_pi     resb 1
nak_pending resb 1
resend      resb 1
pend_msg    resb 1
pend_chunk  resw 1
done_type   resb 1
t_sent      resw 1
t_last      resw 1
t_reset     resw 1
n_fail      resw 1
n_failrun   resb 1
n_bad       resw 1
spoll_errs  resb 1
pit_last    resw 1
pit_tick    resw 1
txq_head    resb 1
txq_n       resb 1
txq         resb TXQN * 10
txlen       resw 1
txframe     resb TXMAX + 8
nakframe    resb 8
rxn         resw 1
rxbuf       resb RXMAX + 1
pf_kind     resb 1
rq_type     resb 1                      ; (link_reset clears these: CLAUDE.COM's)
rq_len      resw 1
req_ready   resb 1
snap_reply  resb 1
rq_more     resb 1                      ; a REQUEST's frames still coming
rq_id       resb 1
reply_busy  resb 1
replybuf    resw 1
hellobuf    resb 80
crctab      resw 256
; Term (TERMCELL.INC, TERMKEYS.INC)
t_active    resw 1
keyn        resb 1
keys_q      resb 1
rep_q       resb 1
keybuf      resw KEYMAX
keysend     resw KEYMAX
shadseg     resw 1
cur_on      resb 1
cur_di      resw 1
t_flags     resb 1
t_cur       resw 1
have_screen resb 1                      ; the shadow holds what the Pi drew
crc_hid     resb 1
ptitle      resb TITLEN + 1
title_text  resb TITLEN + 16
status_text resb 72
            alignb 16
shadow      resb TROWS * 160            ; Term's rows: glyph, attribute
rc_top:

section .text
        times   -((rc_top - $$) > 4000h) db 0   ; (one EMS page, 16 KB)
