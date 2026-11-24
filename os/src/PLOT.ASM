; PLOT.COM - draws an HP-GL file on the pen plotter, the Tek 4662 behind
; its Nano (plotter-nano/), over GPIB, from the GRiD itself: no Pi needed.
;
;   PLOT file [/A:n]
;
; /A:n is the Nano's GPIB address (default 1).  The same rules as
; gridlink's grid_plotter (claude-link/gridlink/mcp.py, hpgl_check and
; PlotJob), so a file that one plots the other does too:
;
; - The whole file is checked before anything is sent: printable ASCII,
;   line ends, tabs, ETX (a label's end), BS, SO and SI (in labels),
;   ESC and SUB (the 4662's own commands), nothing else; and no label (LB,
;   BL or WD outside a label, its letters as the Nano reads them: the
;   control characters between them but ESC dropped, ETX too) left without
;   an ETX after it, which would keep the Nano busy for ever.  A ';' goes on the end if there isn't one:
;   the Nano ends a command only at the next one or a ';'.
; - A command with a label (LB, BL or WD anywhere before its first ';')
;   ends at the label's ETX (and a ';' after it): a ';' in its text is text.
; - The Nano answers a serial poll with the room in its buffer (bits 0-5,
;   in 4-byte units; bit 7 when it and the plotter's queue are empty).
;   Each poll, PLOT sends the whole commands that fit (at least 64 bytes,
;   or the drawing's end), or, for one command longer than 200 bytes of
;   room, that room's worth of it (a label's rest is then read as a
;   label's, to its ETX, whatever ';' its text holds; never a cut between
;   the mnemonic's two letters).  So no write waits
;   on the bus while the pen draws: the driver's own time-out (2 s a byte,
;   shared with every GPIB client, so left alone) is plenty.
; - A status of 0 is the Nano full and drawing (after an Esc, say), not
;   no Nano: that is a time-out.  One that asks for service (bit 6) isn't
;   the Nano (the Claude bridge, with a frame for the GRiD): refused.
; - While the Nano is full it waits (HLT: idle under multitasking), and
;   gives up after 200 s with no progress.  At the end it polls until the
;   Nano is idle, the pen's last strokes.
; - At the start, a Nano that polls idle (bit 7) is plotted on: an idle
;   Nano is never in a label.  A busy one is waited for while its status
;   changes (an earlier drawing left to finish draining: this one queues
;   behind it).  With its ring empty and unchanged for 60 s it isn't
;   drawing (a label never ended, a command cut part-way, only the
;   plotter's own queue left): it is sent a Selected Device Clear (the
;   driver's function 06h; firmware that takes it drops what it holds and
;   starts afresh, out of any label; older firmware takes the next bytes
;   as the rest of what it holds) and plotted on.  With bytes in its ring
;   and unchanged for 200 s it gives up, no clear (the ring holds an
;   earlier drawing's bytes; at 0, "no room": another instrument?).  Esc
;   there clears and plots at once, ^C stops, nothing sent.
; - Esc (or ^C) stops it: a Selected Device Clear first (what the Nano
;   holds dropped, by firmware that takes it), then "PU;" after the last
;   whole command, once a poll gives room for it; inside a label split
;   part-way, ETX and "PU;" (inside any other command split part-way,
;   nothing: an ETX would end a half number).  A read error part-way (a
;   disk error is failed, no question: INT 24h) sends the same, no clear.
;   Esc while the pen finishes (all sent) leaves it to finish: no clear.
;   A pen-up that can't be sent (no room for ~2 s) is said, and, inside a
;   label, that firmware ignoring the clear is still in it.
; - Given up part-way with the Nano answering (no room for 200 s, a write
;   failed): a clear, best-effort, so firmware that takes it isn't left
;   in a label.  (No answer at all: nothing to send it to.)
;
; The GPIB driver is the first of INT 60h-66h with 'GRIDGPIB' at entry+2:
; Lodestone's built-in one, or GRIDGPIB.COM under GRiD MS-DOS.
;
; Exit codes: 0 plotted, 1 stopped (Esc), 2 nothing sent (the file, the
; switches, no GPIB, no Nano), 3 failed part-way.
cpu 286
org 100h

BUFSZ   equ 4096                        ; the file's window (room for one more: the ';')
LOW     equ 512                         ; filled again when less is left (> the most room, 252)
MINW    equ 64                          ; bytes worth a write (less only as the drawing's end)
BIG     equ 200                         ; room enough to send part of a longer command
T_WAIT  equ 9                           ; ticks between polls while the Nano is full (~0.5 s)
T_POLL  equ 18                          ; after a poll that failed, and while the pen finishes
T_STALL equ 3641                        ; 200 s with no progress: given up
T_STILL equ 1092                        ; 60 s of a busy start's status unchanged, ring empty: not drawing
                                        ;  (a label that came whole draws from the Nano's own buffer, ~38 s)
RING_EMPTY equ 3Ch                      ; the Nano's status with its ring empty, not idle ((RING_HOLD 240 - 0) / 4)
E_BUSY  equ 6                           ; the driver: in a call from another task
%if LOW <= 252
%error LOW must be more than the most room (252): fit takes the window's end for a command's
%endif

start:  cld
        mov     di, bss_start           ; (a .COM's memory isn't cleared)
        mov     cx, bss_end - bss_start
        xor     al, al
        rep     stosb
        call    now                     ; ([tprev] from the BIOS: [el] counts from here)
        xor     ax, ax
        mov     [el], ax
        mov     [el+2], ax
        mov     byte [addr], 1
        mov     byte [whole], 1
        call    args
        mov     dx, s_usage
        jc      fail2
        call    find_gpib
        mov     dx, s_nogpib
        jc      fail2
        mov     al, [addr]
        cmp     al, [myaddr]
        mov     dx, s_mine
        je      fail2
        mov     ax, 0F000h              ; Lodestone?  (its own call)
        int     21h
        cmp     ax, 4F47h
        jne     .c24
        mov     byte [crit_a], 83h      ; (its kernel's nobody-asked)
.c24:   mov     dx, on_crit             ; a disk error: the call fails (the pen up)
        mov     ax, 2524h
        int     21h
        mov     dx, [fname]
        mov     ax, 3D00h
        int     21h
        mov     dx, s_noopen
        jc      fail2
        mov     [handle], ax
        call    check                   ; DX = why, CF
        jc      fail2
        mov     ax, 4200h               ; back to the start
        mov     bx, [handle]
        xor     cx, cx
        xor     dx, dx
        int     21h
        mov     dx, on_brk              ; ^C: stop as Esc does
        mov     ax, 2523h
        int     21h
        call    now
        mov     [mark], ax
.p0:    call    spoll                   ; is the Nano there?
        jnc     .p1
        cmp     ax, E_BUSY
        jne     .nn
        call    stalled                 ; (never for 200 s, but bounded)
        jc      .nn
        mov     cx, 1
        call    pause
        jmp     .p0
.p1:    test    al, 40h                 ; RQS: something else (the Claude bridge
        jz      .go                     ;  with a frame waiting); the Nano never
.rq:    mov     dx, s_rqs               ;  asks.  (Any other byte is the Nano: 0
        call    print                   ;  is it full and drawing, as after Esc)
        call    paddr
        mov     dx, s_rqs2
        jmp     fail2
.nn:    mov     dx, s_nonano
        call    print
        call    paddr
        mov     dx, s_nonano2
        jmp     fail2
.go:    test    al, 80h                 ; idle: nothing to clear (an idle Nano is
        jnz     .pl                     ;  never in a label)
; busy: waited for while its status changes (draining an earlier drawing
; left to finish: nothing of it lost).  The status is the Nano's ring only
; (its room, RING_EMPTY when empty), and the ring may stand still for
; minutes with bytes in it while the Nano waits on the plotter (its
; STATUS_TIMEOUT, 180 s).  So: the ring empty and the status the same for
; T_STILL (60 s: a label that came whole may still be drawn from the
; Nano's own buffer for ~38 s, and a clear would stop it): not drawing (a
; label never ended, a command cut part-way, or only the plotter's own
; queue left, which a clear keeps): a clear, best-effort, and the plot.  Bytes in the ring and the same for 200 s:
; given up, no clear (it holds an earlier drawing's bytes); at 0, "no
; room".  Esc: the clear and the plot now (the user's choice); ^C stops.
; No answer for 200 s: given up.  RQS: refused, as at the first poll.
        mov     [lastst], al
        mov     dx, s_busy
        call    print
.kf:    mov     ah, 1                   ; (keys typed before the question:
        int     16h                     ;  not its answer)
        jz      .k0
        xor     ah, ah
        int     16h
        jmp     .kf
.k0:    call    now
        mov     [mark], ax              ; [mark]: the status's last change,
        mov     [ansat], ax             ;  [ansat]: the last answer
.bw:    cmp     byte [brk], 0
        jne     .bc
.bk:    mov     ah, 1
        int     16h
        jz      .bp
        xor     ah, ah
        int     16h
        cmp     al, 27
        je      .be
        cmp     al, 3
        jne     .bk
.bc:    clc                             ; (nothing sent: no pen-up)
        jmp     stopped
.bp:    call    spoll
        jc      .bn
        mov     cx, ax
        call    now
        mov     [ansat], ax
        test    cl, 80h
        jnz     .pl
        test    cl, 40h
        jnz     .rq
        cmp     cl, [lastst]            ; progress: the status changing (the
        je      .bs                     ;  pen drawing what it holds)
        mov     [lastst], cl
        mov     [mark], ax
        jmp     short .bz
.bs:    sub     ax, [mark]
        cmp     cl, RING_EMPTY
        jne     .bh
        cmp     ax, T_STILL
        jb      .bz
        mov     dx, s_still             ; not draining, nothing in its ring:
        call    print                   ;  cleared, plotted to
.be:    call    gclear                  ; (if it fails, the writes say so)
        jmp     short .pl
.bh:    cmp     ax, T_STALL             ; bytes in its ring, the same for 200 s:
        jb      .bz                     ;  given up, nothing sent, no clear
        mov     dx, s_full
        test    cl, 3Fh
        jz      .bf
        mov     dx, s_held
        jmp     short .bf
.bn:    call    now                     ; no answer: asked again, for 200 s
        sub     ax, [ansat]
        cmp     ax, T_STALL
        mov     dx, s_noans
        jb      .bz
.bf:    jmp     fail3
.bz:    mov     cx, T_POLL
        call    pause
        jmp     .bw
.pl:    mov     dx, s_plot1
        call    print
        mov     ax, [tot]
        mov     dx, [tot+2]
        call    pnum32
        mov     dx, s_plot2
        call    print
        call    paddr
        mov     dx, s_plot3
        call    print
        call    now
        mov     [mark], ax
        call    progress

; ---- the plot: poll, send what fits, wait while it's full ---------------
send:   call    refill
        jnc     .f
        jmp     rfail
.f:
        mov     ax, [blen]
        cmp     ax, [pos]
        je      finish                  ; (only at the end of the file)
        call    keys
        jc      cancel
        call    spoll
        jnc     .got
        call    stalled
        mov     dx, s_noans
        jc      fail3
        mov     cx, T_POLL
        call    pause
        jmp     send
.got:   and     ax, 3Fh                 ; the room, in bytes
        shl     ax, 2
        mov     [room], ax
        call    fit                     ; BX = whole commands' end, DX = the next one's
        mov     cx, bx
        sub     cx, [pos]
        mov     ax, MINW                ; at least min(64, what's left)
        cmp     byte [eof], 0
        je      .m
        mov     si, [blen]
        sub     si, [pos]
        cmp     si, ax
        jae     .m
        mov     ax, si
.m:     cmp     cx, ax
        jae     .whole
        cmp     word [room], BIG        ; one command longer than a lot of room:
        jb      .wait                   ;  that room's worth of it
        sub     dx, [pos]
        cmp     dx, [room]
        jbe     .wait
        mov     cx, [room]
        mov     byte [whole], 0
        mov     byte [inlab], 0         ; a label split in its text, before its
        cmp     byte [lastlab], 0       ;  ETX: its rest parsed as a label's, up
        je      .wr                     ;  to that ETX
        mov     ax, [pos]
        add     ax, cx                  ; (AX: the cut)
        cmp     ax, [labst]             ; at or before its mnemonic: the rest
        jbe     .wr                     ;  finds it
        cmp     ax, [labat]
        jae     .t
        mov     ax, [labst]             ; between the mnemonic's letters: cut
        sub     ax, [pos]               ;  before them (none before: all of
        jz      .in                     ;  the room, its rest a label's)
        mov     cx, ax
        jmp     short .wr
.t:     mov     bx, [pos]               ; (DX: its end, from [pos]; its ETX is
        add     bx, dx                  ;  the last byte, or the one before a
        dec     bx                      ;  ';'; neither: not in the window, so
        cmp     byte [buf+bx], 3        ;  past the cut)
        je      .e
        cmp     byte [buf+bx], ';'
        jne     .in
        dec     bx
        cmp     byte [buf+bx], 3
        jne     .in
.e:     sub     bx, [pos]
        cmp     bx, cx                  ; the ETX in this part: only the ';'
        jb      .wr                     ;  (or nothing) left, a command's end
.in:    mov     byte [inlab], 1
        jmp     short .wr
.wait:  call    stalled
        mov     dx, s_full
        jc      fail3c
        mov     cx, T_WAIT
        call    pause
        jmp     send
.whole: mov     byte [whole], 1
        mov     byte [inlab], 0
.wr:    mov     si, buf
        add     si, [pos]
        call    gwrite
        mov     dx, s_wfail
        jc      fail3c
        add     [pos], cx
        add     [sent], cx
        adc     word [sent+2], 0
        inc     word [writes]
        call    now
        mov     [mark], ax
        call    progress
        jmp     send

; all sent: poll until the Nano is idle (the pen's last strokes)
finish: mov     dx, s_fin
        call    print
        call    now
        mov     [mark], ax
.l:     call    keys
        jc      .left
        call    spoll
        jc      .e
        test    al, 80h
        jnz     .done
.e:     call    stalled
        jc      .ni
        mov     cx, T_POLL
        call    pause
        jmp     .l
.ni:    mov     dx, s_noidle            ; (all sent, but no idle for 200 s)
        jmp     short .lf
.left:  mov     dx, s_left
.lf:    call    print
        mov     ax, 4C00h
        int     21h
.done:  mov     dx, s_done
        call    print
        mov     ax, [sent]
        mov     dx, [sent+2]
        call    pnum32
        mov     dx, s_done2
        call    print
        mov     ax, [writes]
        xor     dx, dx
        call    pnum32
        mov     dx, s_done3
        call    print
        mov     cx, 10                  ; seconds = ticks * 10 / 182
        mov     ax, [el+2]
        mul     cx
        mov     bx, ax
        mov     ax, [el]
        mul     cx
        add     dx, bx
        mov     bx, 182
        call    ddiv
        call    pnum32
        mov     dx, s_done4
        call    print
        mov     ax, 4C00h
        int     21h

; Esc or ^C: a clear (what the Nano holds dropped), then the pen up after it
cancel: call    gclear
        call    penup
; CF: the pen-up wasn't sent
stopped: pushf
        mov     dx, s_stop
        call    print
        call    pdone
        mov     dx, s_stop2
        call    print
        popf
        jnc     .x
        mov     dx, s_nopu
        call    print
        cmp     byte [inlab], 0         ; (ETX not sent: firmware that ignored
        je      .x                      ;  the clear is still in the label)
        mov     dx, s_nolab
        call    print
.x:     mov     ax, 4C01h
        int     21h

; "PU;" after the last whole command, ETX and "PU;" inside a label split
; part-way (none if nothing was sent, or the last write ended inside any
; other command: an ETX there would end a half number), once a poll gives
; room for it: a write past the room would hold the bus (NRFD) until the
; pen frees some.  ~2 s at most.  CF if it was due and not sent (no room
; for it, or the write failed)
penup:  mov     al, [whole]
        or      al, [inlab]
        jz      .x
        mov     ax, [sent]
        or      ax, [sent+2]
        jz      .x
        call    now
        mov     [mark], ax
.p:     call    spoll
        jc      .w
        test    al, 3Fh                 ; (4 bytes or more)
        jz      .w
        mov     si, s_pu
        mov     cx, 3
        cmp     byte [inlab], 0
        je      .g
        dec     si                      ; (s_epu: the label's ETX first)
        inc     cx
.g:     jmp     gwrite
.w:     call    now
        sub     ax, [mark]
        cmp     ax, 36
        jae     .n
        mov     cx, 1
        call    pause
        jmp     .p
.n:     stc
.x:     ret

; the file failed part-way: the pen up, then fail3
rfail:  call    penup
        mov     dx, s_rderr
        jmp     short fail3
; the Nano answered but took nothing for 200 s, or a write to it failed: a
; clear (if it takes one, out of any label it is in), then fail3
fail3c: push    dx
        call    gclear                  ; (if it fails, it fails)
        pop     dx
; DX = what went wrong, part-way: how far it got
fail3:  push    dx
        mov     dx, s_crlf
        call    print
        pop     dx
        call    print
        mov     dx, s_none
        mov     ax, [sent]
        or      ax, [sent+2]
        jz      .p
        mov     dx, s_far
        call    print
        call    pdone
        mov     dx, s_far2
.p:     call    print
        mov     ax, 4C03h
        int     21h
; DX = why nothing was sent
fail2:  call    print
        mov     ax, 4C02h
        int     21h

; ---- pass 1: the file as the Nano will take it -------------------------
; [tot] = the bytes to send (a ';' on the end if there isn't one).  CF with
; DX = the message if it can't be plotted.
check:  mov     byte [prev], 0
.rd:    mov     ah, 3Fh
        mov     bx, [handle]
        mov     cx, BUFSZ
        mov     dx, buf
        int     21h
        jc      .rerr
        or      ax, ax
        jz      .eof
        mov     cx, ax
        mov     si, buf
.b:     lodsb
        cmp     al, ' '
        jb      .ct
        je      .sp
        cmp     al, 7Eh
        ja      .bad
        cmp     al, ';'
        je      .semi
        mov     byte [any], 1
        cmp     al, 'a'                 ; LB, BL, WD outside a label: one
        jb      .u                      ;  begins, to its ETX ([lopen]: in it;
        cmp     al, 'z'                 ;  any case)
        ja      .u
        sub     al, 20h
.u:     mov     [lastc], al
        cmp     byte [lopen], 0         ; (in a label: its text)
        jne     .nx
        mov     ah, al
        mov     al, [prev]
        mov     [prev], ah
        cmp     ax, 'LB'
        je      .lo
        cmp     ax, 'BL'
        je      .lo
        cmp     ax, 'WD'
        jne     .nx
.lo:    mov     byte [lopen], 1
        jmp     short .nx
.semi:  mov     [lastc], al
.sp:    mov     [prev], al
        jmp     short .nx
.ct:    cmp     al, 1Bh                 ; ESC: no letter before the next; the
        jne     .ck                     ;  other controls [prev] as it was (the
        mov     [prev], al              ;  Nano drops them between a mnemonic's
.ck:    cmp     al, 13                  ;  letters, ETX too); line ends and tabs
        je      .nx
        cmp     al, 10
        je      .nx
        cmp     al, 9
        je      .nx
        cmp     al, 3                   ; ETX: a label's end (outside one,
        jne     .c2                     ;  dropped)
        cmp     byte [lopen], 0
        je      .ok
        mov     byte [lopen], 0
        mov     byte [prev], 0
        jmp     short .ok
.c2:    cmp     al, 8                   ; BS, SO, SI (labels), ESC, SUB (the 4662's own)
        je      .ok
        cmp     al, 0Eh
        je      .ok
        cmp     al, 0Fh
        je      .ok
        cmp     al, 1Bh
        je      .ok
        cmp     al, 1Ah
        jne     .bad
.ok:    mov     byte [any], 1
        mov     [lastc], al
.nx:    dec     cx                      ; (LOOP: out of reach)
        jz      .nw
        jmp     .b
.nw:    mov     ax, si                  ; the next window
        sub     ax, buf
        add     [tot], ax
        adc     word [tot+2], 0
        jmp     .rd
.eof:   mov     dx, s_nothing
        cmp     byte [any], 0
        je      .no
        mov     dx, s_label
        cmp     byte [lopen], 0
        jne     .no
        cmp     byte [lastc], ';'
        je      .y
        mov     byte [semi], 1          ; (refill puts it on)
        add     word [tot], 1
        adc     word [tot+2], 0
.y:     clc
        ret
.rerr:  mov     dx, s_rderr
.no:    stc
        ret
.bad:   push    ax                      ; "byte 07h at 1234"
        mov     dx, s_bad
        call    print
        pop     ax
        call    phex
        mov     dx, s_bad2
        call    print
        dec     si
        sub     si, buf
        mov     ax, [tot]
        mov     dx, [tot+2]
        add     ax, si
        adc     dx, 0
        call    pnum32
        mov     dx, s_bad3
        stc
        ret

; ---- the file's window: buf[pos..blen) still to send --------------------
; Filled again when less than LOW is left.  CF: a read error.
refill: mov     cx, [blen]
        sub     cx, [pos]
        cmp     cx, LOW
        jae     .x
        cmp     byte [eof], 0
        jne     .x
        mov     si, buf                 ; what's left to the front
        add     si, [pos]
        mov     di, buf
        push    cx
        rep     movsb
        pop     cx
        mov     [blen], cx
        mov     word [pos], 0
        mov     dx, buf
        add     dx, cx
        neg     cx
        add     cx, BUFSZ
        mov     ah, 3Fh
        mov     bx, [handle]
        int     21h
        jc      .r
        add     [blen], ax
        cmp     ax, cx                  ; less than asked: the end
        jae     .x
        mov     byte [eof], 1
        cmp     byte [semi], 0
        je      .x
        mov     bx, [blen]
        mov     byte [buf+bx], ';'
        inc     word [blen]
.x:     clc
.r:     ret

; BX = the end of the whole commands from [pos] that fit in [room] ([pos]
; if none does), DX = the end of the one after them
fit:    mov     bx, [pos]
.n:     call    cmd_end
        mov     ax, di
        sub     ax, [pos]
        cmp     ax, [room]
        ja      .x
        mov     bx, di
        cmp     di, [blen]
        jb      .n
.x:     mov     dx, di
        ret

; DI = where the command at BX ends: after its ';', or, with a label (LB,
; BL or WD before that ';', its letters as the Nano reads them: dropped),
; after the label's ETX and the ';' after that; [blen] if not in the
; window.  [lastlab] = 1 for a label, [labst] = its mnemonic's first
; letter, [labat] = its text's start.  At [pos] with [inlab] (a label split
; part-way) it is that label's rest: up to its ETX, whatever ';' its text
; holds.  (DX lost)
; Limits (files built to reach them): this scan and send's split take a
; label mnemonic's two letters to be less than a room (~200 bytes) apart;
; with that many dropped bytes between them, an ETX among them, PLOT's cuts
; can differ from gridlink's hpgl_ends (L, 240 ETX, B, text).  And only
; LB, BL and WD are kept whole: in a file with no ';' at all, a cut can
; fall between the two letters of any other mnemonic, as it always could.
cmd_end: mov    byte [lastlab], 0
        mov     di, bx
        cmp     bx, [pos]
        jne     .s
        cmp     byte [inlab], 0
        je      .s
        mov     [labst], di
        jmp     short .lt
.s:     cmp     di, [blen]
        jae     .x
        mov     al, [buf+di]
        cmp     al, ' '
        je      .i
        cmp     al, ';'
        je      .i
        cmp     al, 13
        je      .i
        cmp     al, 10
        je      .i
        cmp     al, 9
        jne     .c
.i:     inc     di
        jmp     .s
.c:     xor     ah, ah                  ; AH: the last byte the Nano keeps
.m:     cmp     di, [blen]              ;  (0: none), DX: its place
        jae     .x
        mov     al, [buf+di]
        cmp     al, ';'
        je      .e
        call    dropped
        je      .n
        cmp     al, 'a'                 ; (any case)
        jb      .k
        cmp     al, 'z'
        ja      .k
        sub     al, 20h
.k:     xchg    al, ah                  ; AL the one before, AH this one
        cmp     ax, 'LB'
        je      .lab
        cmp     ax, 'BL'
        je      .lab
        cmp     ax, 'WD'
        je      .lab
        mov     dx, di
.n:     inc     di
        jmp     .m
.lab:   mov     [labst], dx
        inc     di
.lt:    mov     [labat], di
        mov     byte [lastlab], 1
        mov     al, 3
        call    find
        jc      .x
        inc     di
        cmp     di, [blen]
        jae     .x
        cmp     byte [buf+di], ';'
        jne     .x
.e:     inc     di
.x:     ret

; ZF if AL is one the Nano drops between a mnemonic's letters (outside a
; label): every byte below 20h but ESC (which ends a mnemonic), ETX too,
; and every byte from 7Fh up
dropped: cmp    al, 1Bh
        je      .n
        cmp     al, 20h
        jb      .y
        cmp     al, 7Fh
        jb      .n
.y:     cmp     al, al
        ret
.n:     test    al, al                  ; (AL not 0 here: NZ)
        ret

; DI = the first AL at or after DI in the window, or CF and [blen]
find:   mov     cx, [blen]
        sub     cx, di
        jcxz    .nf
        add     di, buf
        repne   scasb
        jne     .nf
        dec     di
        sub     di, buf
        clc
        ret
.nf:    mov     di, [blen]
        stc
        ret

; ---- GPIB ---------------------------------------------------------------
; the first of INT 60h-66h with 'GRIDGPIB' at entry+2; CF if none
find_gpib:
        mov     al, 60h
.v:     push    ax
        mov     ah, 35h
        int     21h
        pop     ax
        mov     cx, es
        or      cx, bx
        jz      .nx
        lea     di, [bx+2]
        mov     si, s_sig
        mov     cx, 8
        repe    cmpsb
        je      .f
.nx:    inc     al
        cmp     al, 67h
        jb      .v
        push    cs
        pop     es
        stc
        ret
.f:     push    cs
        pop     es
        mov     [gg+1], al              ; patch the INT
        xor     ah, ah
        call    gg
        cmp     ax, 4747h
        jne     .no
        mov     [myaddr], dl
        clc
        ret
.no:    stc
        ret

gg:     int     60h
        ret

; serial poll: AL = the Nano's status byte, or CF (AX = the error)
spoll:  mov     ah, 05h
        mov     bl, [addr]
        jmp     gg

; a Selected Device Clear to the Nano (firmware that takes it drops what it
; holds and starts afresh; bytes after it are kept)
gclear: mov     ax, 0600h
        jmp     short gcall
; CX bytes at DS:SI to the Nano, EOI with the last
gwrite: mov     ax, 0201h
; the driver's function AX for the Nano; again while the driver is in
; another task's call.  CF: failed (AX = the error)
gcall:  push    ax
        push    cx
        push    si
        mov     bl, [addr]
        call    gg
        pop     si
        pop     cx
        pop     bx
        jnc     .x
        cmp     ax, E_BUSY
        stc
        jne     .x
        call    stalled
        jc      .x
        push    cx
        mov     cx, 1
        call    pause
        pop     cx
        mov     ax, bx
        jmp     gcall
.x:     ret

; ---- time ---------------------------------------------------------------
; AX = ticks since the start ([el], counted from the BIOS's tick count;
; past midnight's wrap as one tick)
now:    push    ds
        xor     ax, ax
        mov     ds, ax
        mov     ax, [46Ch]
        pop     ds
        push    ax
        sub     ax, [tprev]
        cmp     ax, 8000h
        jb      .a
        mov     ax, 1
.a:     add     [el], ax
        adc     word [el+2], 0
        pop     ax
        mov     [tprev], ax
        mov     ax, [el]
        ret

; CF if 200 s have gone since [mark] (the last progress)
stalled: call   now
        sub     ax, [mark]
        cmp     ax, T_STALL
        cmc
        ret

; CX ticks, idle (HLT)
pause:  push    dx
        push    cx
        call    now
        mov     dx, ax
        pop     cx
.l:     sti
        hlt
        call    now
        sub     ax, dx
        cmp     ax, cx
        jb      .l
        pop     dx
        ret

; CF if Esc was pressed or ^C typed
keys:   cmp     byte [brk], 0
        jne     .c
.k:     mov     ah, 1
        int     16h
        jz      .n
        xor     ah, ah
        int     16h
        cmp     al, 27
        je      .c
        cmp     al, 3                   ; (^C as a key)
        jne     .k
.c:     stc
        ret
.n:     clc
        ret

on_brk: mov     byte [cs:brk], 1
        iret

on_crit: mov    al, [cs:crit_a]         ; Fail: the read fails, rfail lifts the pen.
        iret                            ;  83h, nobody asked, on Lodestone (its
crit_a  db      3                       ;  kernel drops nothing, KDISK.INC rule
                                        ;  4: no unmount at a disk change); else 3

; ---- the command line: a file name and /A:n ----------------------------
args:   mov     si, 81h
        mov     bl, [80h]
        xor     bh, bh
        mov     byte [si+bx], 0
.sk:    lodsb
        cmp     al, ' '
        je      .sk
        cmp     al, 9
        je      .sk
        or      al, al
        jz      .end
        cmp     al, '/'
        je      .sw
        cmp     word [fname], 0
        jne     .bad                    ; (a second name)
        lea     dx, [si-1]
        mov     [fname], dx
.nm:    lodsb
        cmp     al, ' '
        je      .ne
        cmp     al, 9
        je      .ne
        cmp     al, '/'
        je      .ne
        or      al, al
        jnz     .nm
.ne:    mov     byte [si-1], 0
        cmp     al, '/'
        je      .sw
        or      al, al
        jnz     .sk
        jmp     short .end
.sw:    lodsb
        and     al, 0DFh
        cmp     al, 'A'
        jne     .bad
        cmp     byte [si], ':'
        jne     .d0
        inc     si
.d0:    xor     dx, dx
        xor     cx, cx
.dg:    mov     al, [si]
        sub     al, '0'
        cmp     al, 9
        ja      .de
        inc     si
        inc     cx
        xor     ah, ah
        imul    dx, dx, 10
        add     dx, ax
        cmp     dx, 30
        ja      .bad
        jmp     .dg
.de:    jcxz    .bad
        mov     [addr], dl
        jmp     .sk
.end:   cmp     word [fname], 1         ; CF if there's no name
        ret
.bad:   stc
        ret

; ---- output -------------------------------------------------------------
; "\r  1234 of 5678 bytes sent (21%)   Esc stops"
progress:
        mov     dx, s_cr
        call    print
        call    pdone
        mov     dx, s_pct
        call    print
        mov     ax, [sent]              ; sent * 100 / tot, both cut to 16 bits
        mov     dx, [sent+2]
        mov     bx, [tot]
        mov     cx, [tot+2]
.s:     jcxz    .d
        shr     cx, 1
        rcr     bx, 1
        shr     dx, 1
        rcr     ax, 1
        jmp     .s
.d:     mov     cx, 100
        mul     cx
        div     bx
        xor     dx, dx
        call    pnum32
        mov     dx, s_pct2
        jmp     print

; "1234 of 5678 bytes sent"
pdone:  mov     ax, [sent]
        mov     dx, [sent+2]
        call    pnum32
        mov     dx, s_of
        call    print
        mov     ax, [tot]
        mov     dx, [tot+2]
        call    pnum32
        mov     dx, s_sent
        jmp     print

paddr:  mov     al, [addr]
        xor     ah, ah
        xor     dx, dx
        ; fall through
; DX:AX in decimal
pnum32: push    si
        mov     bx, 10
        xor     si, si
.d:     call    ddiv
        push    cx
        inc     si
        mov     cx, ax
        or      cx, dx
        jnz     .d
.p:     pop     ax
        add     al, '0'
        call    putc
        dec     si
        jnz     .p
        pop     si
        ret

; DX:AX / BX -> DX:AX, CX = the remainder
ddiv:   push    ax
        mov     ax, dx
        xor     dx, dx
        div     bx
        mov     cx, ax
        pop     ax
        div     bx
        xchg    dx, cx
        ret

; AL as two hex digits
phex:   push    ax
        shr     al, 4
        call    .h
        pop     ax
        and     al, 0Fh
.h:     add     al, '0'
        cmp     al, '9'
        jbe     putc
        add     al, 7
putc:   push    ax
        push    dx
        mov     dl, al
        mov     ah, 2
        int     21h
        pop     dx
        pop     ax
        ret

print:  mov     ah, 9
        int     21h
        ret

s_sig   db 'GRIDGPIB'
s_epu   db 3                            ; (ETX, then)
s_pu    db 'PU;'
s_usage db 'PLOT - draws an HP-GL file on the pen plotter (the 4662 behind its Nano) over GPIB', 13, 10, 13, 10
        db '  PLOT file [/A:n]', 13, 10, 13, 10
        db '  /A:n  the Nano', 39, 's GPIB address (default 1)', 13, 10, '$'
s_nogpib db 'PLOT: there is no GPIB driver', 13, 10, '$'
s_mine  db 'PLOT: that is the GRiD', 39, 's own GPIB address', 13, 10, '$'
s_noopen db 'PLOT: the file can', 39, 't be opened', 13, 10, '$'
s_rderr db 'PLOT: the file can', 39, 't be read', 13, 10, '$'
s_nothing db 'PLOT: there is no HP-GL in the file', 13, 10, '$'
s_label db 'PLOT: a label (LB, BL or WD) has no ETX at its end.  Nothing was sent.', 13, 10, '$'
s_bad   db 'PLOT: byte $'
s_bad2  db 'h at $'
s_bad3  db ' is not HP-GL (printable ASCII, line ends, ETX, BS, SO, SI, ESC, SUB).', 13, 10
        db 'Nothing was sent.', 13, 10, '$'
s_nonano db 'PLOT: the Nano at GPIB $'
s_nonano2 db ' does not answer a serial poll: is it powered, and running', 13, 10
        db 'firmware v4 or later?  Nothing was sent.', 13, 10, '$'
s_plot1 db 'Plotting $'
s_plot2 db ' bytes of HP-GL on the 4662 at GPIB $'
s_plot3 db '  (Esc stops)', 13, 10, '$'
s_cr    db 13, '  $'
s_of    db ' of $'
s_sent  db ' bytes sent$'
s_pct   db ' ($'
s_pct2  db '%)  $'
s_fin   db 13, 10, 'All sent; the pen is finishing (Esc leaves it to finish).$'
s_left  db 13, 10, 'Left to finish.', 13, 10, '$'
s_noidle db 13, 10, 'All sent, but the Nano has not been idle for 200 s.', 13, 10, '$'
s_rqs   db 'PLOT: GPIB $'
s_rqs2  db ' asks for service: it is not the Nano.  Nothing was sent.', 13, 10, '$'
s_done  db 13, 10, 'Done: $'
s_done2 db ' bytes in $'
s_done3 db ' writes, $'
s_done4 db ' s.', 13, 10, '$'
s_stop  db 13, 10, 'Stopped: $'
s_stop2 db '.  What the Nano still holds may draw.', 13, 10, '$'
s_nopu  db 'The pen-up could not be sent: the Nano had no room for it, or the write failed.', 13, 10, '$'
s_nolab db 'If its firmware ignores a clear, it is still in a label and would take the next', 13, 10
        db 'drawing as text: switch the Nano off and on before plotting again.', 13, 10, '$'
s_busy  db 'The plotter is still busy.  Waiting for it (Esc: plot now).', 13, 10, '$'
s_still db 'The plotter has not changed for 60 s: plotting now.', 13, 10, '$'
s_held  db 'PLOT: the plotter still holds an earlier drawing and has not moved for 200 s', 13, 10
        db '(Esc while it waits plots now).$'
s_noans db 'PLOT: the Nano stopped answering serial polls.$'
s_full  db 'PLOT: the Nano had no room for 200 s.$'
s_wfail db 'PLOT: a write to the Nano failed.$'
s_none  db '  Nothing was sent.', 13, 10, '$'
s_far   db '  $'
s_far2  db '; part of the drawing may be on the paper.', 13, 10, '$'
s_crlf  db 13, 10, '$'

        alignb 2
section .bss
bss_start:
fname   resw 1
handle  resw 1
tot     resd 1                          ; the bytes to send
sent    resd 1
el      resd 1                          ; ticks since the start
tprev   resw 1
mark    resw 1                          ; [el] at the last progress
blen    resw 1                          ; the window: buf[pos..blen)
pos     resw 1
room    resw 1
writes  resw 1
labst   resw 1                          ; cmd_end's label: its mnemonic's first letter
labat   resw 1                          ;  and its text's start
ansat   resw 1                          ; the start's wait: [el] at the last answer
addr    resb 1
myaddr  resb 1
eof     resb 1
semi    resb 1                          ; 1: a ';' to go on the end
whole   resb 1                          ; 1: the last write ended a command
brk     resb 1
any     resb 1
lopen   resb 1
inlab   resb 1                          ; 1: [pos] is inside a label split part-way
lastlab resb 1                          ; 1: cmd_end's last command was a label
lastc   resb 1
prev    resb 1
lastst  resb 1                          ; the start's wait: the last status
        alignb 2
buf     resb BUFSZ + 2
bss_end:
