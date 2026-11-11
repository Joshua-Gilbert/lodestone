; =====================================================================
;  KEMS.INC - the EMS manager: LIM 4.0 on INT 67h for the 1520's own
;  expanded memory, driven as GRiD's EMM.SYS drives it:
;    a 64 KB page frame at E000h in 4 windows of 16 KB; window w's page
;    register is port 0258h + w*4000h, and reads back: 80h + raw page
;    (0-127) shows that page there, 0 takes it away (the window reads FFh).
;    INT 15h E442h with DL = FFh: DL bit 0 = 1 when the BIOS set EMS mode.
;
;  Only resident when there is EMS.  This section follows the kernel
;  image in LODE.SYS; `start' runs ems_init there, which copies it
;  above the BSS before init.  Without EMS that is all, and the arena
;  gets the space.  With EMS it keeps everything up to the last
;  page in ems_ltab and patches the kernel to use it: mem_init's arena
;  starts above it, vec_table's INT 67h points here, terminate gives a
;  program's EMS back before its memory (a TSR keeps its own), the device
;  EMMXXXX0 opens, and 'EMMXXXX0' is at offset 0Ah of the kernel's
;  segment, where programs look for it.  None of that costs a byte
;  without EMS.  And the disk cache moves in (with 3 pages or more): the
;  last two pages the scan finds are its memory, and no program sees
;  them; dio's call to tc_piece, mem_init (no "SC" block: DOS programs
;  get its 18 KB) and INT 21h F0h's lend and back are hooked to the code
;  under "the disk cache's memory" below.
;
;  Pages: ems_ltab holds every page the scan found, as its register
;  value.  Each handle owns one run of it, [start, start + count); the
;  runs fill [0, ems_used) and the rest is free.  So a map is a lookup
;  and an OUT, an allocation takes the free entries after the last run,
;  and only a resize or a free moves entries (in place).
;
;  INT 67h runs on the caller's stack (it comes from interrupt handlers
;  and from inside INT 21h) with interrupts off; only 57h's copying lets
;  them in.  Not here: 55h/56h (map and jump or call) and handle names
;  (53h/54h answer as if no handle had one), the hardware details of
;  59h, alternate map sets (5Bh) and 5Dh.
;
;  (Laid out for size: the error stubs sit among the functions that jump
;  to them, so those jumps stay short.)
; =====================================================================
EMS_FRAME   equ 0E000h
EMS_PORT    equ 0258h           ; window 0's page register (+4000h a window)
EMS_NH      equ 32              ; handles (0 is the system's, always open)
EMS_NS      equ 8               ; contexts 47h can hold at once
ems_used    equ ems_h + 2       ; pages in runs (handle 0's owner: unused)

; ---------------------------------------------------------------------
;  INT 67h
; ---------------------------------------------------------------------
; INT 67h 44h: logical page BX of handle DX into window AL (BX = FFFFh:
; the window off) -> AH = 0 or the error, AL kept, any DS.  The kernel's
; own maps come in as an interrupt (EMS_MAP: PUSHF, PUSH CS, CALL), so
; the one copy has no CALL and RET in the call programs make all the time;
; .po (EMS_OUT) puts register value AH into window AL, AH = 0
%macro EMS_MAP 0
        pushf
        push    cs
        call    ems_int67.p
%endmacro
%macro EMS_OUT 0
        pushf
        push    cs
        call    ems_int67.po
%endmacro
ems_int67:
        cmp     ah, 44h
        jne     ems_gen
.p:     push    bx                      ; 44h, the call programs make all
        push    dx                      ;  the time: straight to the port
        cmp     al, 4
        jae     .e8b
        cmp     dx, EMS_NH
        jae     .e83
        shl     dx, 2
        xchg    bx, dx                  ; BX = the handle's record, DX = page
        inc     dx
        jz      .off
        dec     dx
        or      dh, dh
        jnz     .e8a
        cmp     dl, [cs:ems_h+bx+1]     ; (a closed handle has none)
        jae     .e8a
        add     dl, [cs:ems_h+bx]
        mov     bl, dl                  ; (BH = 0)
        mov     ah, [cs:ems_ltab+bx]
.out:   mov     dh, al                  ; register value AH into window AL
        shl     dh, 6                   ;  -> AL kept, AH = 0
        or      dh, EMS_PORT >> 8
        mov     dl, EMS_PORT & 0FFh
        xchg    al, ah
        out     dx, al
        mov     al, ah
        xor     ah, ah
.x:     pop     dx
        pop     bx
        iret
.e8a:   mov     ah, 8Ah                 ; no such page, if the handle is open
        db      3Dh                     ; (CMP AX, imm16: over the next 2 bytes)
.off:   xor     ah, ah                  ; off (0), if the handle is open
        cmp     byte [cs:ems_h+bx], 0FFh
        je      .e83
        or      ah, ah
        jz      .out
        jmp     short .x
.e83:   mov     ah, 83h
        jmp     short .x
.e8b:   mov     ah, 8Bh                 ; no such window
        jmp     short .x
.po:    push    bx
        push    dx
        jmp     short .out
        times   -(.p - ems_int67 != 5) db 0     ; (KMT's mt_i67: CMP AH,44h and
                                                ;  JNE ems_gen become its JMP FAR)

; the other calls: the caller's registers in a frame laid out as INT 21h's
; (F_*), BP on it, DS = the kernel.  A function gets AH = 0 and BX = its
; number's offset in ems_tab (function - 40h, times 2), sees AL, CX, DX,
; SI, DI and ES as the caller passed them, and returns AH
ems_gen:
        push    es
        push    ds
        pusha
        mov     bp, sp
        push    cs
        pop     ds
        cld
        cli                             ; (a PUSHF / CALL FAR caller may not)
        sub     ah, 40h
        cmp     ah, EMS_NF
        jae     .bad
        xor     bx, bx
        xchg    bl, ah
        add     bx, bx
        call    [ems_tab+bx]
.x:     mov     [bp+F_AX+1], ah
        popa
        pop     ds
        pop     es
        iret
.bad:   mov     ah, 84h
        jmp     .x

ems_tab:
        dw ems_ret, ems41,   ems42,   ems43,   ems_e84, ems45,   ems46,   ems45     ; 40
        dw ems45,   ems_e84, ems_e84, ems_lst, ems4C,   ems_lst, ems4E,   ems4F     ; 48
        dw ems50,   ems4C,   ems52,   ems53,   ems54,   ems_e84, ems_e84, ems57     ; 50
        dw ems58,   ems59,   ems5A,   ems_ea4, ems_ret, ems_ea4                     ; 58
EMS_NF      equ ($ - ems_tab) / 2

ems_e84: mov    ah, 84h                 ; no such function
        ret

; 41h: BX = the page frame's segment (40h, 5Ch: AH = 0 only)
ems41:  mov     word [bp+F_BX], EMS_FRAME
ems_ret: ret

; 46h: AL = the version, 4.0
ems46:  mov     byte [bp+F_AX], 40h
        ret

; 59h: AL=0 hardware details (A4h), 1 as 42h
ems59:  cmp     al, 1
        jb      ems_ea4
        ja      ems_e8f
; 42h: BX = free pages, DX = all pages
ems42:  mov     al, 0                   ; (ems_init: the page count)
        mov     [bp+F_DX], ax
        sub     al, [ems_used]
        mov     [bp+F_BX], ax
        ret

ems_ea4: mov    ah, 0A4h                ; the operating system says no
        ret
ems_e8f: mov    ah, 8Fh                 ; no such subfunction
        ret

; 4Eh: the context (the 4 page registers): AL=0 to ES:DI, 1 from DS:SI,
; 2 both, 3 AL = its size
ems4E:  cmp     al, 3
        ja      ems_e8f
        je      ems_size
        push    ax
        cmp     al, 1
        je      .s
        call    ems_getmap
.s:     pop     ax
        or      al, al
        je      .r
        mov     ds, [bp+F_DS]
        jmp     ems_setmap
.r:     ret
ems_size:
        mov     byte [bp+F_AX], 4
        ret

; 4Fh: part of it: AL=0 the windows listed at DS:SI (count, segments) to
; ES:DI (7Fh for the others), 1 back from DS:SI, 2 AL = its size
ems4F:  cmp     al, 2
        ja      ems_e8f
        je      ems_size
        mov     ds, [bp+F_DS]
        cmp     al, 1
        je      .set
        mov     ax, 7F7Fh
        stosw
        stosw
        sub     di, 4
        lodsw
        xchg    ax, cx
        jcxz    .ok
.l:     lodsw
        call    ems_win
        jc      .e8b
        xchg    ax, bx                  ; BX = the window
        mov     dx, bx
        ror     dx, 2
        or      dx, EMS_PORT
        in      al, dx
        mov     [es:di+bx], al
        loop    .l
.ok:    xor     ah, ah
        ret
.set:   jmp     ems_setmap
.e8b:   mov     ah, 8Bh
        ret

; 50h: CX pages of handle DX at once, from DS:SI (logical page, then
; window: AL=0, or its segment: AL=1)
ems50:  cmp     al, 1
        ja      ems_e8f
        mov     ds, [bp+F_DS]
        jcxz    .x
.l:     lodsw
        xchg    ax, bx
        lodsw
        cmp     byte [bp+F_AX], 0
        je      .w
        call    ems_win
        jc      ems4F.e8b
.w:     cmp     ax, 4
        jae     ems4F.e8b
        EMS_MAP                         ; (BX, DX kept)
        or      ah, ah
        jnz     .x
        loop    .l
.x:     ret

; 52h: attributes: every handle is volatile (AL=0 get, 1 set, 2 capability)
ems52:  cmp     al, 2
        je      .vol
        ja      ems_e8f2
        call    ems_rec
        jc      .x
        dec     al
        jnz     .vol
        cmp     byte [bp+F_BX], 1       ; set:
        jb      .x                      ;  volatile, as it is
        mov     ah, 91h                 ;  non-volatile: not here
        je      .x
        mov     ah, 90h                 ;  no such attribute
.x:     ret
.vol:   mov     [bp+F_AX], ah           ; (AL = 0: volatile)
        ret

; 53h: names: AL=0 ES:DI = handle DX's (none: zeros), 1 set (not kept)
ems53:  cmp     al, 1
        ja      ems_e8f2
        call    ems_rec
        jc      .x
        dec     al
        jz      .x
        xor     ax, ax
        stosw
        stosw
        stosw
        stosw
.x:     ret

ems_e8f2: mov   ah, 8Fh                 ; (another, for short jumps)
        ret

; 58h: the windows: AL=0 ES:DI = (segment, number) of each, CX = 4; 1 CX = 4
ems58:  cmp     al, 1
        ja      ems_e8f2
        mov     word [bp+F_CX], 4
        je      .x
        mov     dx, EMS_FRAME
        xor     ax, ax
.l:     xchg    ax, dx
        stosw
        add     ax, 400h
        xchg    ax, dx
        stosw
        inc     ax
        cmp     al, 4
        jb      .l
.x:     ret

; 43h: a handle with BX pages (not 0) -> DX
ems43:  mov     ah, 89h
        cmp     word [bp+F_BX], 0
        jne     ems_alloc
        ret
; 5Ah: the same, 0 pages allowed (AL = 0 standard, 1 raw: the same here)
ems5A:  cmp     al, 1
        ja      ems_e8f2
ems_alloc:
        mov     si, ems_h + 4
        mov     dx, 1
.f:     cmp     byte [si], 0FFh
        je      .got
        add     si, 4
        inc     dx
        cmp     dl, EMS_NH
        jb      .f
        mov     ah, 85h                 ; no handle left
        ret
.got:   mov     al, [ems_used]          ; an empty run after the last one
        mov     [si], al
        ; its owner: the current PSP when the caller's code is in its
        ; memory, else 0 (a TSR's interrupt handler that didn't switch
        ; PSPs: kept for good, never taken back at someone else's exit)
        mov     ax, [cur_psp]
        mov     bx, [bp+F_CS]
        sub     bx, ax
        jb      .nobody
        dec     ax
        mov     es, ax                  ; (ems_gen gives the caller's back)
        inc     ax
        cmp     bx, [es:3]
        jb      .own
.nobody: xor    ax, ax
.own:   mov     [si+2], ax
        mov     cx, [bp+F_BX]
        call    ems_resize
        or      ah, ah
        jnz     .no
        mov     [bp+F_DX], dx
        ret
.no:    mov     byte [si], 0FFh         ; (it stays free)
        ret

; ---------------------------------------------------------------------
;  57h: move (AL=0) or exchange (AL=1) a region, DS:SI ->
;    +0 dd length, then source and destination, each:
;    db type (0 conventional, 1 EMS), dw handle, dw offset,
;    dw segment (conventional) or logical page (EMS).
;  In pieces of up to 16 KB, none crossing a page, each EMS side's page
;  in a window the other side doesn't use; the windows as they were at
;  the end.  Overlapping moves come out right (92h); exchanges can't.
;  Everything it keeps is on the stack: an interrupt handler may call
;  INT 67h while it copies.
; ---------------------------------------------------------------------
M_LEN   equ -6                  ; bytes still to go (dword)
M_S     equ -16                 ; the source: dword v (the linear address,
M_D     equ -26                 ;  or the offset in the handle's pages), its
                                ;  record (0: conventional), and the piece's
                                ;  offset and segment; the destination too
M_MAP   equ -30                 ; the page registers to put back
M_ST    equ -31                 ; 0, or 92h (overlapped)
M_FN    equ -33                 ; 0 move, 1 exchange
M_BACK  equ -32                 ; 1: backwards (overlap, destination above)
M_SIZE  equ 32                  ; (below the return address)

ems57:  cmp     al, 1
        ja      ems_e8f2
        sub     sp, M_SIZE
        mov     [bp+M_FN], ax           ; (and M_BACK = 0)
        mov     [bp+M_ST], ah
        push    ss
        pop     es
        lea     di, [bp+M_MAP]
        call    ems_getmap
        mov     ds, [bp+F_DS]
        lodsw
        mov     [bp+M_LEN], ax
        lodsw
        mov     [bp+M_LEN+2], ax
        cmp     word [bp+M_LEN], 1      ; at most 1 MB
        sbb     ax, 10h
        mov     ah, 96h
        jae     .e
        mov     di, M_S
        call    ems_side
        jc      .e
        mov     di, M_D
        call    ems_side
        jc      .e
        push    cs
        pop     ds
        ; the same memory on both sides (conventional, or the same handle)?
        mov     ax, [bp+M_S+4]
        cmp     ax, [bp+M_D+4]
        jne     .next
        mov     ax, [bp+M_D]
        mov     dx, [bp+M_D+2]
        sub     ax, [bp+M_S]
        sbb     dx, [bp+M_S+2]          ; DX:AX = destination - source
        jae     .up
        not     dx                      ; (how far apart)
        neg     ax
        sbb     dx, -1
        jmp     short .apart
.up:    inc     byte [bp+M_BACK]
.apart: sub     ax, [bp+M_LEN]          ; closer than its length: they
        sbb     dx, [bp+M_LEN+2]        ;  overlap
        jb      .lap
        mov     byte [bp+M_BACK], 0
        jmp     short .next
.lap:   mov     ah, 97h                 ; an exchange can't overlap
        cmp     byte [bp+M_FN], 0
        jne     .e
        mov     byte [bp+M_ST], 92h
        cmp     byte [bp+M_BACK], 0
        je      .next
        mov     ax, [bp+M_LEN]          ; backwards: from the ends
        mov     dx, [bp+M_LEN+2]
        call    .adv
        jmp     short .next
.done:  mov     ah, [bp+M_ST]
.e:     push    ss                      ; the windows as they were
        pop     ds
        lea     si, [bp+M_MAP]
        push    ax
        call    ems_setmap
        pop     ax
        add     sp, M_SIZE
        ret
        ; the next piece: CX = up to 16 KB, in one page on each EMS side
.next:  mov     cx, 4000h
        cmp     word [bp+M_LEN+2], 0
        jne     .big
        cmp     [bp+M_LEN], cx
        jae     .big
        mov     cx, [bp+M_LEN]
        jcxz    .done
.big:   xor     bx, bx                  ; BL = the window for EMS
        mov     di, M_S
        call    ems_room
        mov     di, M_D
        call    ems_room
        mov     di, M_S
        call    ems_piece
        mov     di, M_D
        call    ems_piece
        push    cx
        mov     es, [bp+M_D+8]
        mov     di, [bp+M_D+6]
        mov     si, [bp+M_S+6]
        mov     ds, [bp+M_S+8]
        sti
        cmp     byte [bp+M_FN], 0
        jne     .xch
        cmp     byte [bp+M_BACK], 0
        jne     .back
        shr     cx, 1
        rep     movsw
        adc     cx, cx
        rep     movsb
        jmp     short .moved
.back:  add     si, cx                  ; (an odd byte at the top, then
        dec     si                      ;  words down: each word read before
        add     di, cx                  ;  a write reaches it, as bytes)
        dec     di
        std
        shr     cx, 1
        jnc     .bw
        movsb
.bw:    dec     si
        dec     di
        rep     movsw
        cld
        jmp     short .moved
.xch:   shr     cx, 1                   ; (an odd byte, then words)
        jnc     .xw
        mov     al, [es:di]
        xchg    al, [si]
        stosb
        inc     si
.xw:    jcxz    .moved
.xl:    mov     ax, [es:di]
        xchg    ax, [si]
        stosw
        inc     si
        inc     si
        loop    .xl
.moved: cli
        push    cs
        pop     ds
        pop     cx
        sub     [bp+M_LEN], cx
        sbb     word [bp+M_LEN+2], 0
        mov     ax, cx                  ; on by CX (back: -CX)
        xor     dx, dx
        cmp     [bp+M_BACK], dl
        je      .fw
        neg     ax
        dec     dx
.fw:    call    .adv
        jmp     .next
.adv:   add     [bp+M_S], ax            ; both sides on by DX:AX
        adc     [bp+M_S+2], dx
        add     [bp+M_D], ax
        adc     [bp+M_D+2], dx
        ret

; one side of a 57h region from DS:SI into [bp+DI] -> CF, AH = the error.
; SI moves on.
ems_side:
        lodsb                           ; type
        mov     ah, 98h
        cmp     al, 1
        ja      .e
        push    ax
        lodsw
        xchg    ax, dx                  ; DX = handle
        lodsw
        xchg    ax, bx                  ; BX = offset
        lodsw                           ; AX = segment or logical page
        pop     cx                      ; CL = type
        push    si
        push    ds                      ; (the handles are ours)
        push    cs
        pop     ds
        test    cl, 1
        jnz     .ems
        mov     cx, 16                  ; conventional: v = segment*16 + offset,
        mul     cx                      ;  and it ends by 1 MB
        add     ax, bx
        adc     dx, 0
        xor     si, si
        mov     cx, 10h
        xor     bx, bx
        jmp     short .end
.ems:   xchg    ax, cx                  ; CX = logical page
        call    ems_rec                 ; SI = the handle's record
        jc      .e1
        mov     ah, 95h                 ; offset past the page
        cmp     bx, 4000h
        jae     .e1
        mov     ah, 8Ah                 ; no such page
        or      ch, ch
        jnz     .e1
        cmp     cl, [si+1]
        jae     .e1
        mov     ax, 4000h               ; v = page*16K + offset
        mul     cx
        or      ax, bx
        mov     cl, [si+1]              ; it ends within the handle's pages:
        xor     ch, ch                  ;  CX:BX = pages*16K
        mov     bx, cx
        shr     cx, 2
        and     bx, 3
        ror     bx, 2
.end:   mov     [bp+di], ax
        mov     [bp+di+2], dx
        mov     [bp+di+4], si
        add     ax, [bp+M_LEN]
        adc     dx, [bp+M_LEN+2]
        cmp     dx, cx
        jb      .ok
        ja      .past
        cmp     ax, bx
        jbe     .ok
.past:  mov     ah, 93h                 ; past the handle's pages ...
        or      si, si
        jnz     .e1
        mov     ah, 0A2h                ; ... or past 1 MB
.e1:    pop     ds
        pop     si
.e:     stc
        ret
.ok:    pop     ds
        pop     si
        clc
        ret

; side [bp+DI], before a piece: an EMS side cuts CX down to what is left
; of its page; a conventional one within 16 KB of window 0 (either way)
; sends the EMS side to window 3 (BL), clear of it
ems_room:
        cmp     word [bp+di+4], 0
        jne     .ems
        mov     ax, [bp+di+1]           ; v / 256: DC000h <= v < E8000h?
        sub     ax, 0DC0h
        cmp     ax, 0C0h
        jae     .x
        mov     bl, 3
.x:     ret
.ems:   mov     ax, [bp+di]             ; forwards 4000h - (v & 3FFFh),
        cmp     byte [bp+M_BACK], 0     ;  backwards ((v - 1) & 3FFFh) + 1
        jne     .b
        neg     ax
.b:     dec     ax
        and     ax, 3FFFh
        inc     ax
        cmp     cx, ax
        jbe     .x
        mov     cx, ax
        ret

; side [bp+DI]'s piece of CX bytes (from v, or up to v backwards): its
; offset and segment; an EMS side's page goes into window BL (BL on by one)
ems_piece:
        mov     ax, [bp+di]
        mov     dx, [bp+di+2]
        cmp     byte [bp+M_BACK], 0
        je      .f
        sub     ax, cx
        sbb     dx, 0
.f:     mov     si, [bp+di+4]
        or      si, si
        jnz     .ems
        mov     [bp+di+6], ax           ; conventional
        and     word [bp+di+6], 15
        shr     ax, 4
        shl     dx, 12
        or      ax, dx
        mov     [bp+di+8], ax
        ret
.ems:   push    ax
        and     ah, 3Fh
        mov     [bp+di+6], ax           ; the offset in the page
        pop     ax
        shl     ax, 1                   ; the logical page: v >> 14
        rcl     dx, 1
        shl     ax, 1
        rcl     dx, 1
        add     dl, [si]
        mov     si, dx
        mov     al, bl
        inc     bx
        mov     ah, [ems_ltab+si]
        EMS_OUT                         ; (AL = the window)
        shl     al, 2                   ; its segment: E0h + 4 * window, 00h
        add     al, EMS_FRAME >> 8
        xchg    al, ah
        mov     [bp+di+8], ax
        ret

; ---------------------------------------------------------------------
;  handles and their pages
; ---------------------------------------------------------------------
; handle DX -> SI = its record; CF and AH = 83h if there is none
ems_rec:
        cmp     dx, EMS_NH
        jae     .bad
        mov     si, dx
        shl     si, 2
        add     si, ems_h
        cmp     byte [si], 0FFh         ; (CF unless closed: turned over)
        cmc
        jnc     .x
.bad:   mov     ah, 83h
        stc
.x:     ret

; 45h: close handle DX, its pages back (handle 0 stays open, empty);
; 47h: the windows' pages saved for it; 48h: back as they were.
; (BX = 0Ah, 0Eh, 10h)
ems45:  call    ems_rec
        jc      .x
        mov     al, dl
        call    ems_slot                ; DI = its saved context, if any
        jne     .none
        mov     ah, 86h                 ; 45h: it has one
        cmp     bl, 0Eh
        jb      .x
        mov     ah, 8Dh                 ; 47h: it has one already
        je      .x
        mov     byte [di], 0FFh         ; 48h: back as they were
        lea     si, [di+1]
        mov     ah, 0
        jmp     ems_setmap
.none:  cmp     bl, 0Eh
        jb      ems_free                ; 45h
        mov     ah, 8Eh                 ; 48h: nothing saved
        ja      .x
        mov     al, 0FFh                ; 47h: into a free slot
        call    ems_slot
        mov     ah, 8Ch                 ; no room
        jne     .x
        mov     [di], dl
        inc     di
        push    ds
        pop     es
        mov     ah, 0
        jmp     ems_getmap
.x:     ret

; the handle whose record is at SI gives all its pages back and closes
; (handle 0 stays open); a context it saved goes too.  -> AH = 0.
; AX, BX, CX, DI changed.
ems_free:
        xor     cx, cx
        call    ems_resize
        mov     ax, si
        sub     ax, ems_h
        shr     ax, 2
        call    ems_slot
        jne     .s
        mov     byte [di], 0FFh
.s:     cmp     si, ems_h
        je      .x
        mov     byte [si], 0FFh
.x:     ret

; 4Ch: BX = handle DX's pages; 51h: it gets BX pages first (BX = 18h, 22h)
ems4C:  call    ems_rec
        jc      .x
        cmp     bl, 18h
        je      .n
        mov     cx, [bp+F_BX]
        call    ems_resize
.n:     mov     bl, [si+1]
        mov     bh, 0
        mov     [bp+F_BX], bx
.x:     ret

; 54h: AL=0 the directory (ems_lst), 1 search (A0h: no names), 2 BX = handles
ems54:  cmp     al, 1
        jb      ems_lst
        mov     ah, 0A0h
        je      .x
        mov     ah, 8Fh
        cmp     al, 2
        jne     .x
        mov     word [bp+F_BX], EMS_NH
        mov     ah, 0
.x:     ret
; 4Bh: BX = handles open; 4Dh: and at ES:DI (handle, pages) of each;
; 54h AL=0: AL = handles open, at ES:DI (handle, name) of each (no names)
; (BX = 16h, 1Ah, 28h)
ems_lst:
        mov     cl, bl
        mov     si, ems_h
        xor     bx, bx
        xor     dx, dx
.l:     cmp     byte [si], 0FFh
        je      .n
        inc     bx
        cmp     cl, 16h
        je      .n
        mov     ax, dx
        stosw
        mov     al, [si+1]
        cmp     cl, 1Ah
        je      .w
        xor     al, al
        stosw
        stosw
        stosw
.w:     stosw
.n:     add     si, 4
        inc     dx
        cmp     dl, EMS_NH
        jb      .l
        mov     [bp+F_AX], bl           ; (54h's answer; AX is the others' too)
        cmp     cl, 28h
        je      .r
        mov     [bp+F_BX], bx
.r:     ret

; the handle whose record is at SI gets CX pages.  If it grows, its run
; goes to the end of the runs first and takes the free pages after it;
; if it shrinks, its last pages go to the end.  Either way one turn of
; ltab[a, used) left by k, and the runs from a + k on start k earlier.
; -> AH = 0, or 87h/88h and no change.  AX, BX, CX, DI changed.
ems_resize:
        mov     ah, 87h                 ; more than there are
        cmp     cx, strict word 0       ; (ems_init: the page count)
.np1    equ     $ - 2
        ja      ems_lst.r
        mov     bl, [ems_used]          ; the runs' end after it: used - c + n,
        mov     bh, 0                   ;  within the pages
        add     bx, cx
        sub     bl, [si+1]
        sbb     bh, 0
        mov     ah, 88h                 ; more than are free
        cmp     bx, strict word 0       ; (the page count)
.np2    equ     $ - 2
        ja      .x
        push    dx
        mov     dl, [si]                ; DL = s
        mov     dh, [si+1]              ; DH = c
        mov     al, [ems_used]          ; AL = the end
        mov     [ems_used], bl
        mov     [si+1], cl
        cmp     cl, dh
        jb      .less
        mov     cl, al                  ; more: from s, by c, and the run
        sub     cl, dh                  ;  starts at end - c
        jmp     short .turn
.less:  add     dl, cl                  ; fewer: from s + n, by c - n
        sub     dh, cl
        mov     cl, [si]                ; (the start stays)
.turn:  mov     ah, dl                  ; the runs from a + k on start k
        add     ah, dh                  ;  earlier
        mov     di, ems_h
.adj:   cmp     byte [di], 0FFh
        je      .an
        cmp     [di], ah
        jb      .an
        sub     [di], dh
.an:    add     di, 4
        cmp     di, ems_h + 4 * EMS_NH
        jb      .adj
        push    si
        mov     bl, al                  ; ltab[a, end) left by k: three
        mov     bh, 0                   ;  reversals
        mov     al, dl
        mov     ah, 0
        mov     dl, dh
        mov     dh, 0
        add     ax, ems_ltab            ; AX = &ltab[a]
        add     bx, ems_ltab            ; BX = &ltab[end]
        add     dx, ax                  ; DX = &ltab[a + k]
        mov     si, ax
        mov     di, dx
        call    ems_rev
        mov     si, dx
        mov     di, bx
        call    ems_rev
        mov     si, ax
        mov     di, bx
        call    ems_rev
        pop     si
        mov     [si], cl
        pop     dx
        mov     ah, 0
.x:     ret
; the bytes [SI, DI) reversed (CH changed)
ems_rev:
.l:     dec     di
        cmp     si, di
        jae     .x
        mov     ch, [si]
        xchg    ch, [di]
        mov     [si], ch
        inc     si
        jmp     .l
.x:     ret

; the save slot of handle AL (FFh: a free slot) -> DI, ZF; NZ if none.
; CX changed.
ems_slot:
        mov     di, ems_sv
        mov     cx, EMS_NS
.l:     cmp     [di], al
        je      .x
        add     di, 5                   ; (NZ)
        loop    .l
.x:     ret

; the 4 page registers to ES:DI (AL, DX changed)
ems_getmap:
        mov     dx, EMS_PORT
.l:     in      al, dx
        stosb
        add     dh, 40h
        jnc     .l
        ret
; and back from DS:SI; a byte 7Fh leaves its window as it is
ems_setmap:
        mov     dx, EMS_PORT
.l:     lodsb
        cmp     al, 7Fh
        je      .n
        out     dx, al
.n:     add     dh, 40h
        jnc     .l
        ret

; segment AX -> window AX (0-3); CF if it isn't one
ems_win:
        sub     ax, EMS_FRAME
        test    ax, 0F3FFh
        jnz     .no
        shr     ax, 10                  ; (CF clear: bit 9 was 0)
        ret
.no:    stc
        ret

; terminate's call (patched in, with interrupts on): the EMS of the PSP
; in AX goes back, then its memory.  (Terminate needs only AX and BX.)
ems_free_owner:
        push    ax
        push    bx
        cli
        mov     si, ems_h + 4
.l:     cmp     byte [si], 0FFh
        je      .n
        cmp     [si+2], ax
        jne     .n
        push    ax
        call    ems_free
        pop     ax
.n:     add     si, 4
        cmp     si, ems_h + 4 * EMS_NH
        jb      .l
        sti
        pop     bx
        pop     ax
        jmp     mem_free_owner

%ifndef NOTC
; ---------------------------------------------------------------------
;  the disk cache's memory: two pages (ems_tcpg) in two windows side by
;  side, only while tc_piece runs, then the windows as they were.  dio
;  calls ems_tc in place of tc_piece (a piece: at most TC_PARAS paragraphs
;  at ES:BX).  Windows 2 and 3 (E800h): the ones least used (57h and most
;  programs start at 0); 0 and 1 (E000h) when the piece's memory may be in
;  2 or 3; when it may be in both halves, no cache this time (emptied: a
;  write may pass it).  Interrupts are off from the first register read
;  to the last write, so nothing sees the frame half switched.
;  While the pages are in, an interrupt handler that maps a page into
;  window 2 or 3 and back (as LIM asks) is safe from the copies, but a
;  fill's DMA in that moment would go to its page; and one that reads the
;  frame without mapping sees the cache.  (An EMS disk cache's lot.)
;  No INT 24h with the pages in: the cache's own reads run without it,
;  and when one fails dio reads the piece itself (with retries and INT 24h
;  as always), the program's windows back.
; ---------------------------------------------------------------------
ems_tc: mov     ax, bx
        shr     ax, 4
        mov     dx, es
        add     ax, dx                  ; its first paragraph P
        mov     dx, EMS_PORT + 8000h
        mov     di, EMS_FRAME + 800h
        sub     ax, EMS_FRAME + 800h - TC_PARAS
        cmp     ax, 800h + TC_PARAS     ; P below E800h - TC_PARAS, or from
        jae     .in                     ;  F000h on: windows 2 and 3
        mov     dh, EMS_PORT >> 8
        mov     di, EMS_FRAME
        cmp     ax, TC_PARAS            ; from E800h on: 0 and 1
        jae     .in
        mov     byte [tc_drv], 0FFh
        xor     al, al                  ; (CF clear)
        ret
.in:    mov     [tc_seg], di
        mov     di, [ems_tcpg]
        mov     ah, 0
        xchg    ah, [io_crit]
        cli
        in      al, dx                  ; AH = io_crit as it was, AL = what
        xchg    ax, di                  ;  the first window showed
        out     dx, al
        add     dh, 40h
        in      al, dx
        xchg    al, ah
        out     dx, al                  ; (AH = what the second one showed)
        sti
        push    di
        push    dx
        push    ax
        call    tc_piece
        jnc     .ok
        xor     al, al                  ; (a read failed: dio's turn)
.ok:    xchg    ax, di
        pop     ax
        pop     dx
        cli
        mov     al, ah
        out     dx, al
        sub     dh, 40h                 ; (CF clear)
        pop     ax
        out     dx, al
        sti
        mov     [io_crit], ah
        xchg    ax, di
        ret

; INT 21h F0h AL=2 and 3 (lend, back): the windows' save-under is a
; block of the cache's size of its own while it is lent; the cache goes on
; meanwhile.  CF (AX = 8) if it is lent already or there is no room.
ems_lend:
        cmp     word [ems_su], 0
        jne     .no
        mov     bx, TC_PARAS
        mov     dx, 8
        call    mem_alloc
        jc      .no
        mov     [ems_su], ax
        dec     ax
        mov     es, ax
        mov     word [es:8], 'SC'
        inc     ax
        jmp     f_F0.lx
.no:    jmp     f_F0.nolend
ems_back:
        xor     ax, ax
        xchg    ax, [ems_su]
        mov     es, ax
        call    mem_free                ; (none lent: no block at 0, nothing)
        jmp     ok
%endif

ems_pend:                               ; (the end of the code)

; ---------------------------------------------------------------------
;  data: right after the code in memory, not in the file (section emsbss:
;  ems_init lays it down as it starts)
; ---------------------------------------------------------------------
section emsbss
ems_bss:
%ifndef NOTC
ems_tcpg:   resw 1                      ; the cache's two pages (register values)
ems_su:     resw 1                      ; the save-under block (F0h AL=2)
%endif
ems_h:      resb 4 * EMS_NH             ; handles: start (FFh: closed), pages,
                                        ;  owner PSP; 0 is the system's (0, 0,
                                        ;  0; its owner's low byte: ems_used),
                                        ;  the others FFh, 0, 0
ems_sv:     resb EMS_NS * 5             ; 47h: handle (FFh: free), 4 registers
                                        ;  (all FFh)
ems_ltab:   resb 128                    ; the pages (only those found stay; 0)
            resb (16 - ((ems_pend - ems_start) + ($ - $$)) % 16) % 16   ; (align 16)
ems_end:                                ; (KHD.INC's module follows)
section ems

; ---------------------------------------------------------------------
;  start-up: `start' jumps here in the load image (1000h:image_end + ...,
;  DS = 1000h, ES = KSEG, the boot stack), so only relative jumps and
;  the kernel's data through DS = KSEG.  All the above goes above the
;  BSS; with EMS it stays and is hooked in, else the arena takes it.
;  Then on to KHD.INC's start-up, which does the same for the hard disk.
;  (Section boot: in the file after the modules, never kept in memory.)
; ---------------------------------------------------------------------
section boot
ems_init:
        mov     si, image_end           ; (where this section is in the file)
        mov     di, bss_end
        mov     cx, (ems_pend - ems_start + 1) / 2
        rep     movsw
        push    es
        pop     ds
        mov     di, ems_bss             ; then its data, as it starts
        xor     ax, ax
%ifndef NOTC
        stosw                           ; ems_tcpg, ems_su
        stosw
%endif
        stosw                           ; ems_h: 0, the system's
        stosw
        mov     cx, EMS_NH - 1
.fh:    mov     al, 0FFh                ;  the others closed
        stosw
        xor     al, al
        stosw
        loop    .fh
        mov     cx, EMS_NS * 5          ; ems_sv
        mov     al, 0FFh
        rep     stosb
        mov     cx, ems_end - ems_ltab  ; ems_ltab
        xor     al, al
        rep     stosb
        mov     di, ems_ltab
        mov     ax, 0E442h              ; the BIOS: EMS mode?  (its CF is
        mov     dl, 0FFh                ;  whatever it was called with)
        int     15h
        or      ah, ah
        jnz     .no
        cmp     dl, 0FFh                ; (a BIOS that doesn't know the call)
        je      .no
        test    dl, 1
        jz      .no
        mov     dx, EMS_PORT            ; (each loop over the 4 ports ends
        mov     bl, 5Ah                 ;  back at window 0's)
.pat:   mov     al, bl                  ; the page registers keep what is
.pw:    out     dx, al                  ;  written (two patterns)
        inc     al
        add     dh, 40h
        jnc     .pw
        mov     ah, bl
.pr:    in      al, dx
        cmp     al, ah
        jne     .off
        inc     ah
        add     dh, 40h
        jnc     .pr
        xor     bl, 0FFh
        js      .pat
        mov     ax, EMS_FRAME           ; each page through window 0: a tag
        mov     es, ax                  ;  (top down), then the ones that
        mov     al, 0FFh                ;  kept theirs (aliases don't)
.tw:    out     dx, al
        push    word [es:0]             ; (what it held: back afterwards)
        mov     ah, al
        not     ah
        mov     [es:0], ax
        dec     al
        js      .tw
        mov     al, 80h
.tr:    out     dx, al
        mov     ah, al
        not     ah
        cmp     [es:0], ax
        jne     .tn
        mov     [di], al
        inc     di
.tn:    inc     al
        jnz     .tr
        mov     al, 80h                 ; every page's first word as it was
.tb:    out     dx, al                  ;  (in the order opposite to the tags',
        pop     word [es:0]             ;  so an alias ends up right too): M:
        inc     al                      ;  may have kept its files through a
        jnz     .tb                     ;  warm restart
.off:   xor     al, al                  ; all four windows off
        mov     dx, EMS_PORT
.o:     out     dx, al
        add     dh, 40h
        jnc     .o
        push    ds
        pop     es
        mov     ax, di
        sub     ax, ems_ltab
        jz      .no
%ifndef NOTC
        cmp     ax, 3                   ; the disk cache: the last two pages
        jb      .ntc
        dec     di
        dec     di
        mov     ax, [di]
        mov     [ems_tcpg], ax
        mov     ax, ems_tc              ; dio's tc_piece
        sub     ax, dio.tcp + 3
        mov     [dio.tcp + 1], ax
        mov     al, 0E9h                ; F0h's lend and back: JMP NEAR
        mov     [f_F0.lend], al
        mov     [f_F0.back], al
        mov     ax, ems_lend
        sub     ax, f_F0.lend + 3
        mov     [f_F0.lend + 1], ax
        mov     ax, ems_back
        sub     ax, f_F0.back + 3
        mov     [f_F0.back + 1], ax
        mov     word [mem_init.tc], 0EBh | (mem_init.zm - mem_init.tc - 2) << 8
        mov     byte [mem_init.zm + 1], 'Z'     ; (no "SC" block)
        ; KMDISK.INC: M:'s installer and resident part into the cache's
        ; second page, past its 2 KB; INT 67h 5Bh to the stub at KSEG:0012h
        ; (where `start' was); init's last jump to md_boot, through a far
        ; jump at KSEG:0000 (md_boot puts `start's bytes back)
        mov     dx, EMS_PORT
        mov     al, [ems_tcpg + 1]
        out     dx, al
        mov     ax, EMS_FRAME
        mov     es, ax
        push    di
        push    ds
        push    cs
        pop     ds
        mov     si, section.mdt.start
        mov     di, MD_TPG + CWDLEN     ; (KMDISK.INC: md_cwd isn't in the file)
        mov     cx, MD_TLEN - CWDLEN
        rep     movsb
        mov     cl, MD_BLEN             ; (its variables: zeros)
        mov     al, 0
        rep     stosb
        pop     es                      ; (KSEG)
        mov     si, MDB(md_stub)
        mov     di, MD_STUB
        mov     cl, md_stub_end - md_stub
        rep     movsb
        push    es
        pop     ds
        xor     al, al                  ; window 0 off again
        out     dx, al
        mov     word [ems_tab + 2 * (5Bh - 40h)], MD_STUB
        mov     ax, [0]                 ; (md_boot puts these back)
        mov     [cs:MDB(md_s0)], ax
        mov     ax, [2]
        mov     [cs:MDB(md_s0) + 2], ax
        mov     al, [4]
        mov     [cs:MDB(md_s0) + 4], al
        mov     byte [0], 0EAh          ; JMP FAR md_boot
        mov     word [1], MDB(md_boot)
        mov     word [3], 1000h
        xor     ax, ax                  ; JMP NEAR 0000h
        sub     ax, init.go + 3
        mov     [init.go + 1], ax
        pop     di
        mov     ax, di
        sub     ax, ems_ltab
.ntc:
%endif
        mov     [ems42 + 1], al         ; the page count, where it is used
        mov     [ems_resize.np1], ax
        mov     [ems_resize.np2], ax
        add     di, 15                  ; keep up to the last page
        mov     [kern_top], di
        mov     word [vec_table.v67], ems_int67
        mov     ax, ems_free_owner
        sub     ax, terminate.fcall + 3
        mov     [terminate.fcall + 1], ax
        mov     byte [dev_names.emm], 8
        mov     word [0Ah], 'EM'        ; the name at INT 67h's segment:000Ah
        mov     word [0Ch], 'MX'        ;  (`start' was there: done with)
        mov     word [0Eh], 'XX'
        mov     word [10h], 'X0'
.no:    jmp     hd_init                 ; (in the load image too)
