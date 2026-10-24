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
;  Everything the program had comes back byte for byte: its video mode and
;  CGA colour register (as 40:66h has it; set before its screen comes back,
;  so that never shows in the mode set's colours), the 32 KB of video
;  memory, the BIOS's video data (40:49h-66h), and the
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
;  latch.
;
;  M3: Claude sees the program and types into it.  HELLO names it (its
;  PSP's path, when DOS isn't busy), and so does the band.  SCREEN answers
;  with the program's screen as kept in windows 1-2 (the reply's first
;  bytes just in front of it, the bytes there kept aside meanwhile).  TYPE
;  is a key script (RUN's: keys, FF FF n waits n ticks): the console goes
;  back to the program, the stub feeds it the keys from here (rc_feed,
;  this page in window 0 meanwhile), and when they are done the console
;  comes back with the program's screen as TYPE's answer, the link as it
;  was (a HELLO would cancel the Pi's call).  CODE-\ meanwhile stops them.
;
;  Files and GPIB (OPS.INC, CLAUDE.COM's own): DIR, READ, WRITE, DELETE,
;  RENAME, MKDIR, RMDIR, STAT, FREE and GPIB.  The file requests call DOS
;  under the paused program, so only where that is safe (dos_ok, at each
;  pop-up): DOS not busy, or busy one call deep in the kernel's own key
;  wait (COPY CON, DOS's AH=01h...: the kernel runs our call on a stack of
;  its own, and nothing of the file system's is in use).  Not two deep,
;  not from a program's INT 24h handler waiting for a key (one deep, but
;  the call is its own: the kernel's disk state is the failed call's), and
;  not from Lodestone's tasks' (MT's) key wait, whose INT 16h calls come
;  from MT's segment, as do those of its INT 24h prompt: those answer F7h,
;  DOS busy, and the band says so.  Each request runs with INT 23h and 24h ours (a critical
;  error fails the call; ^C does nothing) and our DTA, the program's back
;  after; its file handle is the program's PSP's, closed before the reply.
;  The request and its reply share a buffer in window 3 after the shadow
;  (each request's arguments are used before its reply is written), and so
;  does the frame being sent.  RUN, INFO and SETTIME are answered F6h, a
;  DOS program is paused.
; =====================================================================
cpu 286
org 0

%define RCON                            ; TERMLINK: no INT 60h AH=0Bh (the
                                        ;  driver's SRQ count instead)
%define KSUM                            ; TERMLINK: the driver's frame check (1.23)
%define LINK_CHAIN                      ; TERMLINK: the next frame straight after
                                        ;  an answer
%define GP_OTMO gp_otmo                  ; OPS.INC: the driver's timeout under
                                        ;  a GPIB request (ours, 2 s: old_tmo is
                                        ;  the program's)
%define K_QUIT 2B00h                    ; TERMKEYS: CODE-\ back to the program,
%define K_QUIT2 1000h                   ;  CODE-Q too
%define KBD_OWN                         ;  and the BIOS's INT 16h, past the stub
%macro kbd 0
        pushf
        call    far [old16]
%endmacro

VSEG    equ 0B800h
SAVESEG equ 0E400h              ; windows 1-2: the program's screen
SHADSEG equ 0EC00h              ; window 3: Term's shadow (the stub's fourth page),
SHADLEN equ 0F00h               ;  24 x 80 cells
IOSEG   equ SHADSEG + SHADLEN / 16  ; then a REQUEST, and its REPLY over it
REQMAX  equ 8700                ; a REQUEST: id, op, then a write of 8 KB and its path
                                ;  (HELLO's req=: gridlink's 8 KB writes), a TYPE script
IOSIZE  equ 8192 + 16           ; a REPLY: id, status, an 8 KB read (gridlink's chunk)
reqbuf  equ (IOSEG - 0E000h) * 16       ; (DS = E000h: windows 0-3 are DS:0-FFFFh)
TXMAX   equ 3300                ; GRiD -> Pi payload per frame (CLAUDE.COM's: a read's
                                ;  reply in three frames)
txframe equ reqbuf + REQMAX     ; the frame being sent, after them
P_OLD16 equ 0                   ; the stub's parameters (CLAUDE.ASM r_params)
P_INDOS equ 4
P_SS    equ 8                   ;  the stack the stub came on: the INT 16h call's
P_KS    equ 12                  ;  r_ks, then r_pend
NKEYS   equ 16
KSMAX   equ 2 + 2048            ; TYPE: id, op, a key script of 2 KB (gridlink's MAX_TYPE)
TAIL    equ 12                  ; the page's last bytes: a reply's first ones
NAMEMAX equ 12                  ; the program's name (8.3)
%ifndef RXPAY
%assign RXPAY 2048                 ; Pi -> GRiD payload (HELLO's rx=); the EMS page has room for ~2.4 KB
%endif
RXMAX   equ RXPAY + 9                 ; a frame and one byte more (see CLAUDE.ASM)
%defstr RXPAY_S RXPAY
%if REQMAX != 8700
%error kv_hello's req= is REQMAX's
%endif
TXQN    equ 6
TITLEN  equ 36                  ; the Pi's title, then DOS busy (48 cells)
%include "GLP.INC"

        jmp     short rc_main
nano    db      7               ; offset 2: CLAUDE /R /A:nn (CLAUDE.ASM RC_NANO)
term    db      1               ; (TERMLINK: Term's polling)
busy    db      0               ;  (and no chat turn)
feed_e: jmp     near rc_feed    ; offset 5: the stub's feeder (CLAUDE.ASM RC_FEED)
        times   -((feed_e - $$) != 5) db 0

rc_main:
        push    ds
        push    cs
        pop     ds
        cld
        mov     [parms], bx             ; (the stub's, for the feeder)
        mov     [parms + 2], es
        mov     ax, [es:bx + P_OLD16]   ; the BIOS's INT 16h, and is DOS busy?
        mov     [old16], ax
        mov     ax, [es:bx + P_OLD16 + 2]
        mov     [old16 + 2], ax
        push    ds
        lds     si, [es:bx + P_INDOS]
        lodsb
        pop     ds
        mov     [indos], al
        call    dos_check
        mov     al, [indos]
        mov     byte [prog], 0          ; the program's name (AH=62h, its PSP:
        cmp     al, 1                   ;  the kernel runs a call made inside
        ja      .pn                     ;  another on a stack of its own, its
        mov     ah, 62h                 ;  frame there; not two deep, where
        int     21h                     ;  that stack is an INT 24h handler's)
        call    prog_name
.pn:    xor     ax, ax                  ; INT 33h there?  The program's
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
        call    unborrow                ; (a reply cut short: its bytes back)
        mov     al, [bios]              ; the program's mode, screen and data
        xor     ah, ah
        int     10h
        cmp     byte [bios], 6          ; CGA: its colour register before its
        ja      .sc                     ;  screen, which would show first in
        mov     dx, 3D9h                ;  the mode set's (3Fh: white in mode 6)
        mov     al, [bios + 66h - 49h]
        out     dx, al
.sc:    push    ds
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
        ja      .t
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

; dos_ok: 1 if the file requests may call DOS (the header).  AL = indos.
; The INT 16h call's frame on the stack the stub came on: the stub's pushes
; (ES, DS, PUSHA), r_hot's return, then IP, CS
dos_check:
        mov     byte [dos_ok], 0
        cmp     al, 1
        jb      .ok
        ja      .x
        push    es
        les     bx, [parms]
        mov     dx, [es:bx + P_INDOS + 2]       ; the kernel's segment
        mov     ax, [es:bx + P_SS]      ; (SS, then SP)
        mov     bx, [es:bx + P_SS + 2]
        mov     es, ax
        cmp     dx, [es:bx + 2 + 2 + 16 + 2 + 2]
        jne     .p
        pop     es
.ok:    mov     byte [dos_ok], 1
.x:     ret
.p:     pop     es
        ret

; prog: the name the program was started by, from its PSP (BX): after its
; environment's strings come a count and the path (the kernel's EXEC, as
; DOS's); the name after its last \ or :, at most NAMEMAX characters, up
; to a control character.  Only from an environment the program owns
; still (EXEC gives it the block): one it freed may hold anything now.
prog_name:
        mov     es, bx
        mov     ax, [es:2Ch]
        or      ax, ax
        jz      .x
        dec     ax                      ; (its MCB)
        mov     es, ax
        cmp     [es:1], bx
        jne     .x
        inc     ax
        mov     es, ax
        xor     di, di
        xor     al, al
        mov     cx, 8000h
.s:     cmp     [es:di], al             ; an empty string: the end
        je      .e
        repne   scasb                   ; past this one
        je      .s
        jmp     short .x                ; (no end in 32 KB)
.e:     inc     di
        cmp     word [es:di], 0         ; (no path after)
        je      .x
        add     di, 2
        mov     si, di
        mov     cx, 128
.n:     mov     al, [es:di]
        inc     di
        or      al, al
        jz      .c
        cmp     al, '\'
        je      .b
        cmp     al, ':'
        jne     .l
.b:     mov     si, di
.l:     loop    .n
        jmp     short .x
.c:     push    ds
        push    es
        pop     ds
        push    cs
        pop     es
        mov     di, prog
        mov     cx, NAMEMAX
.k:     lodsb
        cmp     al, 21h                 ; (the NUL; and no space or control
        jb      .z                      ;  character in HELLO's line)
        stosb
        loop    .k
.z:     mov     byte [es:di], 0
        pop     ds
.x:     push    cs
        pop     es
        ret

; Claude's keys (TYPE), for the stub's r_feed: called far with this page in
; window 0, on the program's stack, AH = its INT 16h call.  CF if no key
; now (AX kept); else AX = the next key, taken if AH is a read (00h, 10h).
; A wait (FF FF n) holds them n ticks; at the end (or a {SNAP}: TYPE's
; screen comes at the end anyway) the stub's r_ks goes 0 and r_pend 1:
; the console comes back, and answers TYPE.
rc_feed:
        push    ds
        push    si
        push    bx
        push    cs
        pop     ds
        mov     bx, ax
.l:     mov     si, [ks_pos]
        cmp     si, [ks_len]
        jae     .end
        mov     ax, [ksbuf + si]
        cmp     ax, 0FFFFh
        je      .wt
        cmp     ax, 0FEFFh
        je      .end
        test    bh, 1                   ; (a peek leaves it)
        jnz     .k
        add     word [ks_pos], 2
.k:     clc
        jmp     short .x
.wt:    push    ds
        push    40h
        pop     ds
        mov     ax, [6Ch]
        pop     ds
        cmp     byte [ks_wait], 0
        jne     .w2
        mov     byte [ks_wait], 1
        push    ax
        mov     al, [ksbuf + si + 2]
        xor     ah, ah
        mov     [ks_until], ax
        pop     ax
        add     [ks_until], ax
.w2:    sub     ax, [ks_until]
        js      .no
        mov     byte [ks_wait], 0
        add     word [ks_pos], 3
        jmp     .l
.end:   mov     byte [played], 1
        push    es
        push    di
        les     di, [parms]
        mov     word [es:di + P_KS], 0100h      ; r_ks 0, r_pend 1
        pop     di
        pop     es
.no:    mov     ax, bx
        stc
.x:     pop     bx
        pop     si
        pop     ds
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
        mov     byte [req_ready], 0
        mov     word [ioseg], IOSEG
        mov     byte [n_failrun], 0
        mov     byte [sdc_due], 0
        mov     al, 0                   ; back from Claude's keys (all played,
        xchg    al, [type_due]          ;  or CODE-\ stopped them: the rest
        mov     [type_back], al         ;  dropped)
        les     di, [parms]
        mov     byte [es:di + P_KS], 0
        push    cs
        pop     es
        call    find_gpib
        sbb     al, al                  ; (none: 0FFh)
        inc     al
        mov     [gp_ok], al
        mov     si, st_nogpib
        jz      .nl
        mov     ax, 0EFFh               ; the driver's SRQ interrupt (IRQ 5,
        call    gg_call                 ;  Lodestone's 1.21 on): DX:CX = its
        jc      .ni                     ;  count, which we only read (never
        or      ax, ax                  ;  AH=0Bh: the program's latch)
        jnz     .ii
.ni:    xor     dx, dx
.ii:    mov     [irq_ptr], cx
        mov     [irq_ptr + 2], dx
        mov     bx, 2000                ; our own timeout, 2 s: the driver's
        mov     ah, 0Ah                 ;  is the program's too (TM5000G's
        call    gg_call                 ;  TIME OUT n: up to 60 s a byte, with
        mov     [old_tmo], ax           ;  a stuck bridge); its own back after
        mov     si, st_connecting
        cmp     byte [type_back], 0     ; TYPE's answer, the link as it was (a
        je      .h                      ;  HELLO would cancel the Pi's call),
        cmp     byte [connected], 0     ;  if it was up when we went
        je      .h
        cmp     byte [lstate], LS_IDLE
        jne     .h
        call    type_reply
        mov     si, st_connecting       ; (type_reply leaves SI on the reply)
        jmp     short .st
.h:     mov     byte [lstate], LS_RESET ; HELLO at once
        mov     ax, [now]
        sub     ax, 18
        mov     [t_reset], ax
.nl:    mov     byte [connected], 0
.st:    call    set_status
        call    term_redraw             ; Term's screen from the shadow, the band
.loop:  call    get_ticks
        mov     [now], ax
        cmp     byte [gp_ok], 0
        je      .k
        call    link_service
        call    req_service
.k:     call    term_kbd
        cmp     byte [quit], 0
        jne     .out
        call    idle
        jmp     .loop
.out:   cmp     byte [gp_ok], 0         ; before going back: the keys typed so
        je      .x                      ;  far and what is queued go, and the
        cmp     byte [type_due], 0      ;  last frame gets its answer (else
        jne     .dt                     ;  the bridge would hold it, and SRQ,
        mov     al, G_EVENT             ;  while the program has the bus); 3 s
        mov     si, evaway              ;  at most.  The user's CODE-\ (not
        mov     cx, 1                   ;  TYPE's keys): an EVENT says so, and the
        call    txq_put_cs              ;  Pi answers Claude Code's calls at once
                                        ;  until the next HELLO
.dt:    mov     ax, [now]
        mov     [t_quit], ax
.d:     call    get_ticks
        mov     [now], ax
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
        je      .t                      ;  bridge's line (and SRQ) cleared
        mov     bl, [nano]
        mov     ah, 06h
        call    gg_call
        mov     byte [connected], 0     ; (so the next pop-up says HELLO)
.t:     mov     bx, [old_tmo]           ; the program's timeout back
        mov     ah, 0Ah
        call    gg_call
.x:     ret

shadow_seg:                             ; Term's shadow, in window 3
        mov     word [shadseg], SHADSEG
        ret

; HLT when nothing is due: no frame on its way or to send, no keys, and
; quiet for 2 s (TERMLINK polls back to back until then).  Waiting for an
; answer, with the driver's SRQ interrupt: HLT till it (or a tick, or a
; key), unless it came already or a key is waiting
idle:   cmp     byte [lstate], LS_WAIT
        jne     .i
        cmp     word [irq_ptr + 2], 0
        je      .x
        cmp     byte [srq_held], 0      ; (the line held by another device:
        jne     .x                      ;  no edge would wake us)
        mov     ah, 11h
        kbd
        jnz     .x
        push    es
        les     bx, [irq_ptr]
        cli
        mov     ax, [es:bx]
        pop     es
        cmp     ax, [srq_seen]
        jne     .s
        sti                             ; (STI's shadow covers the HLT)
        hlt
.z:     ret                             ; (the tests count wakes here)
.s:     sti
        ret
.i:     mov     al, [txq_n]
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
.ok:    mov     byte [ksum], 0          ; Lodestone's driver 1.23 and up keeps
        cmp     cx, 0123h               ;  the frame check as it moves the bytes
        jb      .k
        cmp     cx, 0200h
        jae     .k
        inc     byte [ksum]
.k:     clc
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
        mov     ax, 0501h               ; GLP 1; flags: Term, the Fletcher sum,
        cmp     word [irq_ptr + 2], 0   ;  and with the driver's SRQ interrupt
        je      .w                      ;  GF_WAKE: the Pi rings while we are
        mov     byte [wake_ok], 1       ;  idle (its count: no AH=0Bh)
        or      ah, GF_WAKE
.w:     stosw
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
        cmp     byte [prog], 0          ; the program paused, if we know it
        je      .s
        mov     si, kv_prog
        call    put_str
        mov     si, prog
        call    put_str
        mov     al, 10
        stosb
.s:     cmp     byte [have_screen], 0   ; the screen we kept, so the Pi can go
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
        push    es                      ; (TERMLINK's crc16 reads ES:SI in RCON)
        push    SHADSEG
        pop     es
        xor     si, si
        mov     cx, TROWS * 160
        mov     ax, 0FFFFh
        call    crc16
        pop     es
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
        mov     byte [rep_q], 0         ; (repaint's; away's is the last)
        ret
.r:     cmp     al, G_REPLY
        jne     .x
        mov     byte [reply_busy], 0
        jmp     unborrow                ; (a screen's: the bytes before it back)
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
        cmp     cx, 2                   ; the Pi takes the Fletcher sum: every
        jb      .c                      ;  frame from now on
        test    byte [si+1], HF_FCS
        jz      .c
        mov     byte [use_fl], 1
.c:     mov     byte [connected], 1
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

; a REQUEST, its frames gathered in reqbuf (id, op, arguments).  SCREEN:
; the program's screen; TYPE: Claude's keys for it (the answer when they
; are done); files and GPIB: req_service, from the session's loop (F7h,
; DOS busy, for a file's when DOS can't be called); anything else F6h, a
; DOS program is paused (RUN, INFO, SETTIME, snapshots)
rf_request:
        cmp     byte [rq_more], 0
        jne     .c
        mov     word [rq_len], 0
        mov     byte [rq_over], 0
.c:     mov     di, [rq_len]
        mov     ax, di
        add     ax, cx
        cmp     ax, REQMAX
        jbe     .p
        mov     byte [rq_over], 1
        jmp     short .m
.p:     add     di, reqbuf
        rep     movsb
        mov     [rq_len], ax
.m:     mov     al, [pf_kind]
        and     al, 80h
        mov     [rq_more], al
        jnz     .x
        cmp     word [rq_len], 2        ; (an id and an op)
        jb      .x
        cmp     byte [quit], 0          ; (going back: the Pi has the EVENT)
        jne     .x
        cmp     byte [reply_busy], 0    ; (one at a time, as CLAUDE.COM)
        jne     .x
        cmp     byte [txq_n], TXQN
        jae     .x
        mov     al, [reqbuf]
        mov     ah, 0F0h                ; too big for us
        cmp     byte [rq_over], 0
        jne     reply2
        mov     ah, [reqbuf + 1]
        cmp     ah, OP_TYPE
        je      type_start
        cmp     ah, OP_SCREEN
        je      .sc
        mov     si, rc_optab
.o:     cmp     ah, [si]
        je      .op
        add     si, 3
        cmp     byte [si], 0
        jne     .o
        mov     ah, 0F6h
        jmp     reply2
.op:    cmp     ah, 20h                 ; (GPIB: no DOS)
        je      .go
        cmp     byte [dos_ok], 0
        mov     ah, 0F7h
        je      reply2
.go:    mov     [rq_id], al
        mov     [rq_op], si
        mov     byte [req_ready], 1
        ret
.sc:    xor     cl, cl                  ; (no flags)
        jmp     screen_msg
.x:     ret

rc_optab:
        db 02h
        dw op_dir
        db 03h
        dw op_read
        db 04h
        dw op_write
        db 05h
        dw op_delete
        db 06h
        dw op_rename
        db 07h
        dw op_mkdir
        db 08h
        dw op_rmdir
        db 09h
        dw op_stat
        db 0Ah
        dw op_free
        db 20h
        dw op_gpib
        db 0

; the request rf_request took, once its REPLY can be queued (txq_put would
; drop it).  A file's with DOS ours meanwhile: the program's DTA, INT 23h
; and INT 24h aside, ours in
req_service:
        cmp     byte [req_ready], 0
        je      .x
        cmp     byte [txq_n], TXQN
        jae     .x
        mov     byte [req_ready], 0
        mov     si, [rq_op]
        cmp     byte [si], 20h
        jne     .d
        jmp     [si + 1]
.d:     push    si
        mov     ah, 2Fh
        int     21h
        mov     [sv_dta], bx
        mov     [sv_dta + 2], es
        push    ds
        xor     ax, ax
        mov     ds, ax
        mov     si, 23h * 4
        mov     di, sv_vec
        push    cs
        pop     es
        mov     cx, 4
        cli
        rep     movsw
        mov     word [23h * 4], rc_i23
        mov     [23h * 4 + 2], cs
        mov     word [24h * 4], rc_i24
        mov     [24h * 4 + 2], cs
        sti
        pop     ds
        pop     si
        call    [si + 1]
        push    es
        xor     ax, ax
        mov     es, ax
        mov     si, sv_vec
        mov     di, 23h * 4
        mov     cx, 4
        cli
        rep     movsw
        sti
        pop     es
        push    ds
        lds     dx, [sv_dta]
        mov     ah, 1Ah
        int     21h
        pop     ds
.x:     ret

rc_i24: mov     al, 3                   ; a critical error: fail the call
rc_i23: iret                            ; ^C: nothing (the call goes on)

%include "OPS.INC"

; a REPLY of its own: AL = id, AH = status, no data (reply_n: CX = 3,
; with TYPE's flags already at replybuf + 2)
reply2: mov     cx, 2
reply_n:
        mov     [replybuf], ax
        mov     byte [reply_busy], 1
        mov     al, G_REPLY
        mov     si, replybuf
        jmp     txq_put_cs

; TYPE (AL = its id): the keys go to the program, the console goes back
; to it; the answer comes when they are done (the next pop-up: session)
type_start:
        mov     cx, [rq_len]
        cmp     cx, KSMAX
        mov     ah, 0F0h                ; (too big for ksbuf)
        ja      reply2
        mov     [type_id], al
        mov     word [ks_pos], 2
        mov     [ks_len], cx
        mov     si, reqbuf              ; (for the feeder, which has this page
        mov     di, ksbuf               ;  alone)
        rep     movsb
        mov     byte [ks_wait], 0
        mov     byte [played], 0
        mov     byte [type_due], 1
        les     di, [parms]
        mov     byte [es:di + P_KS], 1
        push    cs
        pop     es
        mov     byte [quit], 1
        ret

type_reply:                             ; TYPE's answer: flags, the screen
        mov     al, [type_id]
        mov     ah, [played]            ; (bit 0: all the keys were played)
        mov     cl, 1
        ; (falls through)

; Queue the REPLY with the program's screen as kept (its mode's part of
; windows 1-2), as CLAUDE.COM's SCREEN: mode, banks, bpp (0: text cells),
; width, height, bytes a line, then the screen.  AL = id; CL = 1 with
; TYPE's flags (AH) after the status, 0 without.  The reply's first bytes
; go just in front of the screen (the page's tail, or the saved screen
; there for a text page further on), the bytes there kept aside until it
; has gone (unborrow).
screen_msg:
        push    ax
        push    cx
        call    unborrow
        mov     bl, [bios]              ; the mode: text, from 40:4Eh, 40:4Ah
        cmp     bl, 3                   ;  columns, 25 rows
        ja      .g
        mov     dl, [bios + 4Ah - 49h]
        xor     dh, dh
        mov     al, 50                  ; (cells of 2 bytes)
        mul     dl
        mov     cx, ax
        mov     di, [bios + 4Eh - 49h]
        mov     ax, 25
        mov     bh, 1                   ; one bank
        mov     si, dx                  ; bpl = columns * 2
        shl     si, 1
        xor     bp, bp                  ; bpp 0
        jmp     short .h
.g:     cmp     bl, 7                   ; (mono: not in our copy, B000h)
        je      .no
        xor     di, di
        mov     si, 80
        mov     dx, 640
        mov     ax, 200
        mov     bh, 2
        mov     cx, 4000h
        mov     bp, 1
        cmp     bl, 6
        je      .h
        jb      .c4
        mov     ax, 400                 ; mode 40h (and any other): 640x400,
        mov     bh, 4                   ;  four banks
        mov     cx, 8000h
        jmp     short .h
.c4:    mov     dx, 320                 ; modes 4, 5: 320x200, 2 bits
        inc     bp
.h:     mov     [sm_len], cx            ; DI = offset in windows 1-2
        push    es
        push    SAVESEG - 1             ; (the page's tail: E3FF:0004..000F)
        pop     es
        add     di, 10h - TAIL
        mov     [borrow_at], di
        push    si                      ; (bpl)
        push    ds                      ; the bytes there, aside
        push    di
        push    es
        pop     ds
        mov     si, di
        push    cs
        pop     es
        mov     di, borrowed
        mov     cx, TAIL
        rep     movsb
        pop     di
        pop     ds
        pop     si
        mov     byte [borrow_on], 1
        push    SAVESEG - 1
        pop     es
        mov     [es:di + 3], bl         ; mode, banks, bpp, width, height, bpl
        mov     [es:di + 4], bh
        mov     [es:di + 5], bp         ; (bpp; the width writes over its 2nd
        mov     [es:di + 6], dx         ;  byte)
        mov     [es:di + 8], ax
        mov     [es:di + 10], si
        pop     es
        pop     cx
        pop     ax
        mov     si, [borrow_at]
        mov     dx, [sm_len]
        add     dx, TAIL
        push    es
        push    SAVESEG - 1
        pop     es
        mov     [es:si + 2], ah         ; TYPE's flags, after id and status
        or      cl, cl
        jnz     .t
        inc     si                      ; SCREEN: id, status, then the screen
        dec     dx                      ;  (the status over the flags)
.t:     mov     [es:si], al
        mov     byte [es:si + 1], 0
        pop     es
        mov     cx, dx
        mov     byte [reply_busy], 1
        mov     al, G_REPLY
        mov     dx, SAVESEG - 1
        jmp     txq_put
.no:    pop     cx                      ; no screen we can send: F5h (TYPE: and
        pop     ax                      ;  its flags)
        mov     [replybuf + 2], ah
        mov     ah, 0F5h
        xor     ch, ch                  ; 2 bytes, 3 with the flags
        add     cl, 2
        jmp     reply_n

; a reply's first bytes gone: the bytes they stood on back
unborrow:
        cmp     byte [borrow_on], 0
        je      .x
        mov     byte [borrow_on], 0
        push    es
        push    SAVESEG - 1
        pop     es
        mov     di, [borrow_at]
        mov     si, borrowed
        mov     cx, TAIL
        rep     movsb
        pop     es
.x:     ret

; ---- the band ----------------------------------------------------
; title_text: the Pi's title (or ours), the program's name, then DOS busy
; if the file requests can't call it (a long status on the right covers the
; end: the name is in HELLO for Claude anyway)
make_title:
        mov     di, title_text
        mov     si, ptitle
        call    put_str
        cmp     byte [prog], 0
        je      .t
        mov     si, s_sep
        call    put_str
        mov     si, prog
        call    put_str
.t:     cmp     byte [dos_ok], 0
        jne     .z
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

skipz:  lodsb                           ; SI past the next NUL (OPS.INC)
        or      al, al
        jnz     skipz
        ret

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
kv_hello    db 'app=resident', 10, 'grid=CLAUDE 1.9', 10, 'rx=', RXPAY_S, 10, 'req=8700', 10
            db 'ops=files,gpib', 10, 'addr=', 0
kv_screen   db 'screen=', 0
kv_prog     db 'prog=', 0
s_sep       db '  ', 86h, '  ', 0
s_title0    db 'Claude (resident)', 0
s_dos       db '  ', 86h, '  DOS busy', 0
s_tkeys     db 'CODE-\ back  CODE-R repaints', 0
s_back      db '  ', 86h, '  CODE-\ back', 0
st_connecting db 'Connecting to the Pi', 82h, 0
st_lost     db 'Link to the Pi lost, reconnecting', 82h, 0
st_noans    db 'No answer from the bridge at GPIB address ', 0
st_nogpib   db 'No GPIB driver (GRIDGPIB)', 0
evrepaint   db 03h
evaway      db 04h                      ; (the user went back to the program)

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
old_tmo     resw 1                      ;  the program's timeout (ms) meanwhile
sdc_due     resb 1                      ; the link failed: SDC to the bridge
irq_ptr     resw 2                      ; the driver's SRQ count (AH=0Eh), seg 0: none
srq_seen    resw 1                      ;  as it was at the last look
ksum        resb 1                      ; 1: INT 60h 02h AL=3, 03h AL=2 (KSUM)
tx_app      resb 1                      ; 1: txframe's check is the driver's to add
lw_eoi      resb 1                      ; lw_go's AL for INT 60h 02h: 1, or 3
n_kok       resw 1                      ; frames ks_check passed (the tests)
now         resw 1
; the link (TERMLINK.INC)
connected   resb 1
pi_active   resb 1
lstate      resb 1
TERMLINK_RESET_VARS
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
txq         resb TXQN * 10
txlen       resw 1
nakframe    resb 8
rxn         resw 1
rxbuf       resb RXMAX + 1
pf_kind     resb 1
rq_more     resb 1                      ; a REQUEST's frames still coming
rq_over     resb 1                      ;  more than REQMAX of them
replybuf    resb 4                      ; a reply of our own: id, status (flags)
hellobuf    resb 128
; M3: the program, its screen, Claude's keys
parms       resd 1                      ; the stub's parameters (r_ks, r_pend)
prog        resb NAMEMAX + 1            ; the program's name, or nothing
sm_len      resw 1                      ; a screen's bytes
borrow_on   resb 1                      ; a reply's first bytes stand at
borrow_at   resw 1                      ;  E3FF:this, over these
borrowed    resb TAIL
type_due    resb 1                      ; TYPE's keys out: answer at the pop-up
type_back   resb 1
type_id     resb 1
played      resb 1                      ;  (all of them were)
ks_pos      resw 1                      ; the next key in ksbuf
ks_len      resw 1
ks_wait     resb 1                      ; a wait under way, until
ks_until    resw 1
; files and GPIB (OPS.INC)
dos_ok      resb 1                      ; 1: the file requests may call DOS
rq_id       resb 1                      ; the request req_service runs: its id,
rq_op       resw 1                      ;  its rc_optab entry
ioseg       resw 1                      ; IOSEG
gp_otmo     resw 1                      ; the driver's timeout, ours, meanwhile
gp_dlen     resw 1
gp_max      resw 1
wr_data     resw 1
wr_len      resw 1
wr_done     resw 1
sv_dta      resd 1                      ; the program's DTA, INT 23h and 24h,
sv_vec      resd 2                      ;  while a file's request runs
dta         resb 44
ksbuf       resb KSMAX                  ; TYPE's request, for the feeder
crctab      resw 256
; Term (TERMCELL.INC, TERMKEYS.INC)
t_active    resw 1
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
title_text  resb NAMEMAX + 5 + TITLEN + 16
status_text resb 72
rc_top:                                 ; (Term's shadow: SHADSEG, window 3)

section .text
        times   -((rc_top - $$) > 4000h - TAIL) db 0    ; (one EMS page, 16 KB,
                                                        ;  its last bytes a reply's)
        times   -(TROWS * 160 > SHADLEN) db 0           ; window 3: the shadow,
        times   -(IOSIZE > REQMAX) db 0                 ;  the request and reply,
        times   -(txframe + TXMAX + 8 > 10000h) db 0    ;  the frame
