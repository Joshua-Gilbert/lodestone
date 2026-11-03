; EMSTEST.COM - checks of the EMS manager (LIM 4.0, INT 67h).
; Run it under Lodestone (the kernel's own EMS), or under GRiD MS-DOS with
; GRiD's EMM.SYS to compare: the checks only Lodestone can pass (it gives a
; program's EMS back when the program ends, names aren't kept, ...) are
; skipped there.  One line per test, "info" lines for what differs
; between managers, then a total; the exit code is the number of failures.
; What it prints is also added to EMSTEST.TXT, then it waits for a key.
;   EMSTEST /L and /T are its own children (a program that leaves EMS
;   behind, a TSR that keeps it).
cpu 286
org 100h

FRAME   equ 0E000h

start:  mov     sp, stack_top
        cld
        mov     di, bss_start           ; DOS doesn't clear memory for us
        mov     cx, stack_top - bss_start
        xor     al, al
        rep     stosb
        mov     si, 81h                 ; a child?  /L or /T
.arg:   lodsb
        cmp     al, 13
        je      .main
        cmp     al, '/'
        jne     .arg
        lodsb
        and     al, 0DFh
        cmp     al, 'L'
        je      child_leak
        cmp     al, 'T'
        je      child_tsr
.main:  mov     bx, 1000h               ; keep 64 KB, give the rest back
        mov     ah, 4Ah
        int     21h
        inc     byte [logging]          ; (the children don't log)
        mov     si, s_hello
        call    pr
        mov     ax, 0F000h              ; Lodestone?
        int     21h
        cmp     ax, 4F47h
        jne     .dos
        mov     byte [lodestone], 1
.dos:   call    has_ems
        mov     si, tests
        jnc     .run
        mov     si, s_noems
        call    pr
        mov     si, tests_noems
.run:   call    runall
        call    savelog
        mov     byte [logging], 0
        mov     si, s_key
        call    pr
        mov     ah, 8                   ; wait for a key: the result stays
        int     21h                     ;  on the screen until then
        call    crlf
        mov     al, [nfail]
        mov     ah, 4Ch
        int     21h

; what was printed, added to EMSTEST.TXT (made if it isn't there)
savelog:
        mov     dx, s_log
        mov     ax, 3D01h
        int     21h
        jc      .new
        mov     bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        jmp     short .w
.new:   mov     dx, s_log
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .fail
        mov     bx, ax
.w:     mov     dx, logbuf
        mov     cx, [logpos]
        mov     ah, 40h
        int     21h
        jc      .fc
        cmp     ax, cx
        jne     .fc
        mov     ah, 3Eh
        int     21h
        jc      .fail
        mov     si, s_saved
        jmp     pr
.fc:    mov     ah, 3Eh
        int     21h
.fail:  mov     si, s_nosave
        jmp     pr

; the INT 67h vector's segment has 'EMMXXXX0' at 0Ah?  CF if not
has_ems:
        push    es
        mov     ax, 3567h
        int     21h
        mov     di, 0Ah
        mov     si, s_emm
        mov     cx, 8
        repe    cmpsb
        pop     es
        je      .y
        stc
        ret
.y:     clc
        ret

; run the tests at SI, then the total
runall:
.next:  lodsw
        or      ax, ax
        jz      .done
        mov     bx, ax
        lodsw
        push    si
        mov     [tname], ax
        mov     byte [step], 0
        mov     byte [skipped], 0
        mov     [tsp], sp
        call    bx
        jc      .bad
        cmp     byte [skipped], 0
        jne     .skip
        inc     word [npass]
        mov     si, s_ok
        call    pr
        mov     si, [tname]
        call    pr
        call    crlf
        jmp     .n
.skip:  mov     si, s_skip
        call    pr
        mov     si, [tname]
        call    pr
        call    crlf
        jmp     .n
.bad:   mov     [ecode], ax
        inc     word [nfail]
        mov     si, s_fail
        call    pr
        mov     si, [tname]
        call    pr
        mov     si, s_step
        call    pr
        mov     al, [step]
        xor     ah, ah
        call    pdec
        mov     si, s_code
        call    pr
        mov     ax, [ecode]
        call    phex
        call    crlf
.n:     call    cleanup
        pop     si
        jmp     .next
.done:  mov     si, s_total
        call    pr
        mov     ax, [npass]
        call    pdec
        mov     si, s_passed
        call    pr
        mov     ax, [nfail]
        call    pdec
        mov     si, s_failed
        call    pr
        ret

; a failed check: back to the runner with CF and AX
fail:   mov     sp, [tsp]
        sub     sp, 2
        stc
        ret
failnc: mov     ax, 0FFFFh
        jmp     fail
; an INT 67h status that is wrong: AX = it (in AH)
efail:  jmp     fail
; a test only Lodestone can pass, elsewhere: skip it
gridonly:
        cmp     byte [lodestone], 0
        jne     .x
        mov     byte [skipped], 1
        mov     sp, [tsp]
        sub     sp, 2
        clc
.x:     ret
; the rest of a test only Lodestone can pass, elsewhere: passed so far
gridrest:
        cmp     byte [lodestone], 0
        jne     .x
        mov     sp, [tsp]
        sub     sp, 2
        clc
.x:     ret

; after each test: what it saved goes back, the handles it made go
cleanup:
        mov     si, hs
        mov     cx, [nh]
        jcxz    .x
.l:     lodsw
        mov     dx, ax
        mov     ah, 48h
        int     67h
        mov     ah, 45h
        int     67h
        loop    .l
.x:     mov     word [nh], 0
        ret

%macro STEP 1
        mov     byte [step], %1
%endmacro
%macro EQ 2
        cmp     %1, %2
        je      %%ok
        mov     ax, %1
        jmp     fail
%%ok:
%endmacro
%macro EQB 2                            ; (bytes)
        cmp     %1, %2
        je      %%ok
        mov     al, %1
        mov     ah, 0
        jmp     fail
%%ok:
%endmacro
; INT 67h AH=%1 must work (AH = 0)
%macro EMS 1
        mov     ah, %1
        int     67h
        or      ah, ah
        jnz     efail
%endmacro
; INT 67h AX=%1 must work
%macro EMSAX 1
        mov     ax, %1
        int     67h
        or      ah, ah
        jnz     efail
%endmacro
; INT 67h AX=%1 must answer AH=%2
%macro EMSERR 2
        mov     ax, %1
        int     67h
        cmp     ah, %2
        jne     efail
%endmacro

; ---------------------------------------------------------------------
; helpers
; BX pages -> DX = a new handle (43h), cleaned up after the test
alloc:  EMS     43h
newh:   mov     di, [nh]                ; (DX: one more for cleanup)
        add     di, di
        mov     [hs+di], dx
        inc     word [nh]
        ret
; handle DX closed (45h) and off the cleanup list
freeh:  EMS     45h
        mov     si, hs
        mov     cx, [nh]
.l:     jcxz    .x
        cmp     [si], dx
        je      .cut
        add     si, 2
        dec     cx
        jmp     .l
.cut:   mov     di, si                  ; the rest moves up one
        add     si, 2
        dec     cx
        push    es
        push    ds
        pop     es
        rep     movsw
        pop     es
        dec     word [nh]
.x:     ret
; page BX of handle DX into window AL (44h)
map:    push    ax
        mov     ah, 44h
        int     67h
        or      ah, ah
        jnz     efail
        pop     ax
        ret
; pages 0 to CX-1 of handle DX: tag AL's signatures written (sigs) or
; checked (chks)
sigs:   xor     bx, bx
.l:     call    setsig
        inc     bx
        loop    .l
        ret
chks:   xor     bx, bx
.l:     call    chksig
        inc     bx
        loop    .l
        ret
; the signature of tag AL, page BL -> AX
sigof:  mov     ah, al
        mov     al, bl
        xor     ax, 5AA5h
        ret
; page BX of handle DX gets tag AL's signature (through window 0)
setsig: push    ax
        push    es
        push    ax
        xor     al, al
        call    map
        pop     ax
        call    sigof
        push    FRAME
        pop     es
        mov     [es:0], ax
        mov     [es:3FFEh], ax
        pop     es
        pop     ax
        ret
; it has it?  (fail if not)
chksig: push    ax
        push    es
        push    ax
        xor     al, al
        call    map
        pop     ax
        call    sigof
        push    FRAME
        pop     es
        cmp     [es:0], ax
        jne     .bad
        cmp     [es:3FFEh], ax
        jne     .bad
        pop     es
        pop     ax
        ret
.bad:   mov     ax, [es:0]
        pop     es
        jmp     fail
; the word at window AL's start -> AX
peek:   push    es
        xor     ah, ah
        shl     ax, 10
        add     ax, FRAME
        mov     es, ax
        mov     ax, [es:0]
        pop     es
        ret
; the test pattern: byte I -> AL (I in BX)
patb:   mov     al, bl
        mov     ah, bl
        shl     al, 3
        sub     al, ah                  ; 7*I
        add     al, bh
        ret
; ES:DI gets CX bytes of the pattern from BX
patfill:
.l:     call    patb
        stosb
        inc     bx
        loop    .l
        ret
; ES:DI has CX bytes of the pattern from BX?  (fail if not)
patchk:
.l:     call    patb
        scasb
        jne     .bad
        inc     bx
        loop    .l
        ret
.bad:   mov     ax, di
        jmp     fail
; 57h with the descriptor `desc' (AL = 0 move, 1 exchange) -> AH
mv:     mov     si, desc
        mov     ah, 57h
        int     67h
        ret
%macro D57 9                            ; length, then source and destination:
        mov     word [desc], %1         ;  type, handle, offset, segment/page
        mov     word [desc+2], 0
        mov     byte [desc+4], %2
        mov     word [desc+5], %3
        mov     word [desc+7], %4
        mov     word [desc+9], %5
        mov     byte [desc+11], %6
        mov     word [desc+12], %7
        mov     word [desc+14], %8
        mov     word [desc+16], %9
%endmacro
; an info line: SI = text, AX = a number (FFFFh: none)
info:   push    si
        mov     si, s_info
        call    pr
        pop     si
        call    pr
        cmp     ax, 0FFFFh
        je      .x
        call    pdec
.x:     jmp     crlf

; ---------------------------------------------------------------------
; output
pr:     push    ax
        push    bx
        push    cx
        push    dx
        mov     dx, si
.l:     lodsb
        or      al, al
        jnz     .l
        mov     cx, si
        sub     cx, dx
        dec     cx
        cmp     byte [logging], 0       ; a copy for EMSTEST.TXT
        je      .o
        push    si
        push    di
        push    cx
        mov     si, dx
        mov     di, [logpos]
        mov     ax, LOGMAX
        sub     ax, di
        cmp     cx, ax
        jbe     .c
        mov     cx, ax
.c:     add     [logpos], cx
        add     di, logbuf
        rep     movsb
        pop     cx
        pop     di
        pop     si
.o:     mov     bx, 1
        mov     ah, 40h
        int     21h
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret
crlf:   push    si
        mov     si, s_crlf
        call    pr
        pop     si
        ret
pdec:   push    si                      ; AX unsigned
        push    bx
        push    dx
        mov     si, numbuf + 6
        mov     byte [si], 0
        mov     bx, 10
.d:     xor     dx, dx
        div     bx
        add     dl, '0'
        dec     si
        mov     [si], dl
        or      ax, ax
        jnz     .d
        call    pr
        pop     dx
        pop     bx
        pop     si
        ret
phex:   push    si
        push    cx
        mov     si, numbuf
        mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 15
        add     al, '0'
        cmp     al, '9'
        jbe     .s
        add     al, 7
.s:     mov     [si], al
        inc     si
        pop     ax
        loop    .h
        mov     byte [si], 0
        mov     si, numbuf
        call    pr
        pop     cx
        pop     si
        ret

; ---------------------------------------------------------------------
; the tests
t_detect:
        STEP 1                          ; the device EMMXXXX0
        mov     dx, s_emmdev
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     bx, ax
        mov     ax, 4400h
        int     21h
        jc      fail
        test    dl, 80h                 ; a device
        jz      failnc
        STEP 2
        mov     ax, 4407h               ; ready
        int     21h
        jc      fail
        EQB      al, 0FFh
        mov     ah, 3Eh
        int     21h
        STEP 3
        EMS     40h
        STEP 4
        EMS     46h
        cmp     al, 40h
        jb      fail
        STEP 5
        EMS     41h
        EQ      bx, FRAME
        STEP 6
        EMS     42h
        mov     [total], dx
        mov     [free0], bx
        or      dx, dx
        jz      failnc
        cmp     bx, dx
        ja      fail
        mov     si, s_ipages
        mov     ax, dx
        call    info
        mov     si, s_ifree
        mov     ax, [free0]
        call    info
        mov     ax, 4E03h               ; what differs between managers
        int     67h
        xor     ah, ah
        mov     si, s_ictx2
        call    info
        mov     ax, 5402h
        int     67h
        mov     ax, bx
        mov     si, s_ihandles
        call    info
        clc
        ret

t_map:  STEP 1
        mov     bx, 4
        call    alloc
        mov     [h1], dx
        STEP 2
        EMS     4Ch
        EQ      bx, 4
        EMS     42h
        mov     ax, [free0]
        sub     ax, 4
        EQ      bx, ax
        STEP 3                          ; each page its signature
        mov     dx, [h1]
        xor     bx, bx
.s:     mov     al, 1
        call    setsig
        inc     bx
        cmp     bx, 4
        jb      .s
        STEP 4                          ; all four at once, backwards
        mov     dx, [h1]
        xor     al, al
.m:     mov     bx, 3
        sub     bl, al
        call    map
        inc     al
        cmp     al, 4
        jb      .m
        xor     al, al
.c:     push    ax
        call    peek
        mov     cx, ax
        pop     ax
        push    ax
        mov     bl, 3
        sub     bl, al
        mov     al, 1
        call    sigof
        EQ      cx, ax
        pop     ax
        inc     al
        cmp     al, 4
        jb      .c
        STEP 5                          ; each again, one at a time
        xor     bx, bx
.k:     mov     al, 1
        call    chksig
        inc     bx
        cmp     bx, 4
        jb      .k
        STEP 6
        mov     dx, [h1]
        call    freeh
        EMS     42h
        EQ      bx, [free0]
        clc
        ret

t_alias:
        STEP 1
        mov     bx, 2
        call    alloc
        mov     al, 0                   ; page 1 in windows 0 and 2
        mov     bx, 1
        call    map
        mov     al, 2
        call    map
        push    es
        push    FRAME
        pop     es
        mov     word [es:10h], 1357h
        mov     ax, [es:8010h]
        pop     es
        EQ      ax, 1357h
        STEP 2                          ; window 3 off: FFh
        mov     al, 3
        call    map
        mov     ax, 4403h
        mov     bx, 0FFFFh
        int     67h
        or      ah, ah
        jnz     efail
        mov     al, 3
        call    peek
        EQ      ax, 0FFFFh
        STEP 3                          ; off needs an open handle
        mov     ax, 4403h
        mov     bx, 0FFFFh
        mov     dx, 31
        int     67h
        EQB      ah, 83h
        clc
        ret

t_errors:
        STEP 1
        mov     bx, 1
        call    alloc
        mov     ax, 4404h               ; no window 4
        xor     bx, bx
        int     67h
        EQB      ah, 8Bh
        STEP 2
        mov     ax, 4400h               ; no page 1
        mov     bx, 1
        int     67h
        EQB      ah, 8Ah
        STEP 3
        mov     ax, 4400h               ; no such handle
        xor     bx, bx
        mov     dx, 999
        int     67h
        EQB      ah, 83h
        mov     dx, 30                  ; (closed)
        mov     ax, 4400h
        int     67h
        EQB      ah, 83h
        STEP 4
        xor     bx, bx                  ; 0 pages
        EMSERR  4300h, 89h
        mov     bx, 1000                ; more than there are
        EMSERR  4300h, 87h
        mov     bx, [free0]             ; more than are free
        EMSERR  4300h, 88h
        STEP 5
        EMSERR  3F00h, 84h              ; no such functions
        EMSERR  5E00h, 84h
        EMSERR  0DE00h, 84h
        STEP 6
        EMSERR  4E09h, 8Fh              ; no such subfunction
        mov     dx, 999
        EMSERR  4C00h, 83h
        clc
        ret

t_save: STEP 1
        mov     bx, 2
        call    alloc
        mov     [h1], dx
        mov     al, 1
        xor     bx, bx
        call    setsig
        inc     bx
        call    setsig
        STEP 2                          ; page 0 in window 0, saved, page 1 in
        xor     al, al
        xor     bx, bx
        call    map
        mov     dx, [h1]
        EMS     47h
        mov     al, 0
        mov     bx, 1
        call    map
        mov     dx, [h1]
        EMSERR  4700h, 8Dh              ; (saved already)
        EMSERR  4500h, 86h              ; (can't close it now)
        STEP 3
        EMS     48h
        xor     al, al
        call    peek
        mov     cx, ax
        mov     al, 1
        xor     bl, bl
        call    sigof
        EQ      cx, ax
        STEP 4
        mov     dx, [h1]
        EMSERR  4800h, 8Eh              ; (nothing saved)
        clc
        ret

t_context:
        STEP 1
        mov     bx, 3
        call    alloc
        mov     [h1], dx
        xor     bx, bx
.s:     mov     al, 2
        call    setsig
        inc     bx
        cmp     bx, 3
        jb      .s
        mov     al, 0                   ; 0 1 2 in windows 0 1 2, 3 off
        xor     bx, bx
        call    map
        inc     al
        inc     bx
        call    map
        inc     al
        inc     bx
        call    map
        mov     ax, 4403h
        mov     bx, 0FFFFh
        int     67h
        STEP 2
        mov     ax, 4E03h
        int     67h
        or      ah, ah
        jnz     efail
        cmp     al, 16
        ja      fail
        mov     di, ctx1
        push    ds
        pop     es
        EMSAX   4E00h
        STEP 3                          ; all moved
        mov     dx, [h1]
        mov     al, 0
        mov     bx, 2
        call    map
        mov     al, 1
        call    map
        mov     al, 2
        call    map
        mov     al, 3
        call    map
        STEP 4                          ; and back (4E02: get, then set)
        mov     di, ctx2
        mov     si, ctx1
        EMSAX   4E02h
        xor     cx, cx
.c:     mov     al, cl
        call    peek
        push    ax
        mov     al, 2
        mov     bl, cl
        call    sigof
        pop     bx
        EQ      bx, ax
        inc     cx
        cmp     cx, 3
        jb      .c
        mov     al, 3
        call    peek
        EQ      ax, 0FFFFh
        STEP 5                          ; the saved one: all on page 2
        mov     si, ctx2
        EMSAX   4E01h
        mov     al, 3
        call    peek
        push    ax
        mov     al, 2
        mov     bl, 2
        call    sigof
        pop     bx
        EQ      bx, ax
        STEP 6                          ; part of it: windows 0 and 2
        mov     si, ctx1
        EMSAX   4E01h
        mov     bx, 2
        EMSERR  4F02h, 0
        cmp     al, 16
        ja      fail
        mov     si, plist
        mov     di, ctx2
        EMSAX   4F00h
        mov     dx, [h1]                ; everything to page 1
        mov     bx, 1
        mov     al, 0
        call    map
        mov     al, 1
        call    map
        mov     al, 2
        call    map
        mov     si, ctx2
        EMSAX   4F01h
        STEP 7                          ; 0 and 2 back, 1 left on page 1
        mov     al, 0
        call    peek
        mov     cx, ax
        mov     al, 2
        xor     bl, bl
        call    sigof
        EQ      cx, ax
        mov     al, 1
        call    peek
        mov     cx, ax
        mov     al, 2
        mov     bl, 1
        call    sigof
        EQ      cx, ax
        mov     al, 2
        call    peek
        mov     cx, ax
        mov     al, 2
        mov     bl, 2
        call    sigof
        EQ      cx, ax
        STEP 8
        mov     si, plistbad
        mov     di, ctx2
        EMSERR  4F00h, 8Bh
        clc
        ret

t_multi:
        STEP 1
        mov     bx, 4
        call    alloc
        mov     [h1], dx
        xor     bx, bx
.s:     mov     al, 3
        call    setsig
        inc     bx
        cmp     bx, 4
        jb      .s
        STEP 2                          ; by window number
        mov     si, mmap0
        mov     cx, 4
        EMSAX   5000h
        call    .chk
        STEP 3                          ; by segment
        mov     si, mmap1
        mov     cx, 4
        EMSAX   5001h
        call    .chk
        STEP 4
        mov     si, mmapbad
        mov     cx, 1
        EMSERR  5001h, 8Bh
        clc
        ret
.chk:   xor     cx, cx                  ; window W has page 3 - W
.c:     mov     al, cl
        call    peek
        push    ax
        mov     al, 3
        mov     bl, 3
        sub     bl, cl
        call    sigof
        pop     bx
        EQ      bx, ax
        inc     cx
        cmp     cx, 4
        jb      .c
        ret

t_realloc:
        STEP 1
        mov     bx, 4
        call    alloc
        mov     [h1], dx
        xor     bx, bx
.s:     mov     al, 4
        call    setsig
        inc     bx
        cmp     bx, 4
        jb      .s
        STEP 2                          ; 6 pages: the first 4 kept
        mov     bx, 6
        EMS     51h
        EQ      bx, 6
        mov     bx, 4
        mov     al, 4
        call    setsig
        inc     bx
        call    setsig
        xor     bx, bx
.k:     mov     al, 4
        call    chksig
        inc     bx
        cmp     bx, 6
        jb      .k
        EMS     42h
        mov     ax, [free0]
        sub     ax, 6
        EQ      bx, ax
        STEP 3                          ; 2 pages: the first 2 kept
        mov     dx, [h1]
        mov     bx, 2
        EMS     51h
        EQ      bx, 2
        xor     bx, bx
        mov     al, 4
        call    chksig
        inc     bx
        call    chksig
        mov     ax, 4400h
        mov     bx, 2
        int     67h
        EQB      ah, 8Ah
        STEP 4                          ; 0, then 3 again
        mov     bx, 0
        EMS     51h
        EQ      bx, 0
        mov     bx, 3
        EMS     51h
        EQ      bx, 3
        EMS     42h
        mov     ax, [free0]
        sub     ax, 3
        EQ      bx, ax
        STEP 5                          ; more than are free: nothing changes
        mov     dx, [h1]
        mov     bx, [free0]
        add     bx, 1
        mov     ah, 51h
        int     67h
        cmp     ah, 87h
        je      .e5
        EQB      ah, 88h
.e5:    mov     dx, [h1]
        EMS     4Ch
        EQ      bx, 3
        clc
        ret

; three handles; the first and the middle one change size, the others
; must keep their pages
t_neighbours:
        STEP 1
        mov     bx, 3
        call    alloc
        mov     [h1], dx
        xor     bx, bx                  ; a 0-page handle in the middle
        EMSAX   5A00h
        call    newh
        mov     [h2], dx
        mov     bx, 2
        call    alloc
        mov     [h3], dx
        mov     dx, [h1]
        xor     bx, bx
        mov     al, 5
        call    setsig
        inc     bx
        call    setsig
        inc     bx
        call    setsig
        mov     dx, [h3]
        xor     bx, bx
        mov     al, 7
        call    setsig
        inc     bx
        call    setsig
        STEP 2                          ; the first grows by 2
        mov     dx, [h1]
        mov     bx, 5
        EMS     51h
        mov     dx, [h1]
        mov     bx, 1
        mov     al, 5
        call    chksig
        inc     bx
        call    chksig
        call    .all
        STEP 3                          ; the empty one gets 2
        mov     dx, [h2]
        mov     bx, 2
        EMS     51h
        mov     dx, [h2]
        xor     bx, bx
        mov     al, 6
        call    setsig
        inc     bx
        call    setsig
        call    .all
        call    .mid
        STEP 4                          ; the first shrinks to 1
        mov     dx, [h1]
        mov     bx, 1
        EMS     51h
        call    .all
        call    .mid
        STEP 5                          ; the first goes
        mov     dx, [h1]
        call    freeh
        mov     dx, [h3]
        call    .last
        call    .mid
        clc
        ret
.all:   mov     dx, [h1]                ; the first's first 1 page ...
        xor     bx, bx
        mov     al, 5
        call    chksig
.last:  mov     dx, [h3]                ; ... and the last's
        xor     bx, bx
        mov     al, 7
        call    chksig
        inc     bx
        call    chksig
        ret
.mid:   mov     dx, [h2]
        xor     bx, bx
        mov     al, 6
        call    chksig
        inc     bx
        call    chksig
        ret

; a handle with no pages starts where one in the middle starts; the
; middle one grows and shrinks, the empty one gets pages
t_middle:
        STEP 1
        mov     bx, 2
        call    alloc
        mov     [h1], dx                ; A
        xor     bx, bx
        EMSAX   5A00h
        call    newh
        mov     [h2], dx                ; Z: none
        mov     bx, 2
        call    alloc
        mov     [h3], dx                ; M
        mov     bx, 2
        call    alloc
        mov     [h4], dx                ; B
        mov     al, 11h
        mov     dx, [h1]
        mov     cx, 2
        call    sigs
        mov     al, 12h
        mov     dx, [h3]
        mov     cx, 2
        call    sigs
        mov     al, 13h
        mov     dx, [h4]
        mov     cx, 2
        call    sigs
        STEP 2                          ; M grows to 3
        mov     dx, [h3]
        mov     bx, 3
        EMS     51h
        mov     al, 12h
        mov     bx, 2
        call    setsig
        mov     cx, 3
        call    .all
        STEP 3                          ; Z gets 1
        mov     dx, [h2]
        mov     bx, 1
        EMS     51h
        mov     al, 14h
        mov     cx, 1
        call    sigs
        mov     cx, 3
        call    .all
        call    .z
        STEP 4                          ; M shrinks to 1
        mov     dx, [h3]
        mov     bx, 1
        EMS     51h
        mov     cx, 1
        call    .all
        call    .z
        STEP 5                          ; A goes
        mov     dx, [h1]
        call    freeh
        mov     al, 12h
        mov     dx, [h3]
        mov     cx, 1
        call    chks
        mov     al, 13h
        mov     dx, [h4]
        mov     cx, 2
        call    chks
        call    .z
        clc
        ret
.all:   push    cx                      ; A's 2, M's CX, B's 2 pages
        mov     al, 11h
        mov     dx, [h1]
        mov     cx, 2
        call    chks
        pop     cx
        mov     al, 12h
        mov     dx, [h3]
        call    chks
        mov     al, 13h
        mov     dx, [h4]
        mov     cx, 2
        jmp     chks
.z:     mov     al, 14h
        mov     dx, [h2]
        mov     cx, 1
        jmp     chks

; every free page in one handle (on a 2 MB board: all 128 at once)
t_all:  STEP 1
        EMS     42h
        mov     [h3], bx
        call    alloc
        mov     [h1], dx
        EMS     42h
        EQ      bx, 0
        STEP 2                          ; its first and last pages
        mov     dx, [h1]
        mov     al, 21h
        xor     bx, bx
        call    setsig
        mov     bx, [h3]
        dec     bx
        call    setsig
        xor     bx, bx
        call    chksig
        STEP 3
        mov     dx, [h1]
        call    freeh
        EMS     42h
        EQ      bx, [h3]
        clc
        ret

t_handles:
        STEP 1
        EMS     4Bh
        mov     [h3], bx                ; open now
        mov     bx, 2
        call    alloc
        mov     [h1], dx
        mov     bx, 1
        call    alloc
        mov     [h2], dx
        EMS     4Bh
        mov     ax, [h3]
        add     ax, 2
        EQ      bx, ax
        STEP 2                          ; 4Dh: the same count, our two in it
        push    ds
        pop     es
        mov     di, buf
        EMS     4Dh
        mov     ax, [h3]
        add     ax, 2
        EQ      bx, ax
        mov     si, buf
        mov     cx, bx
        xor     dx, dx
.l:     lodsw
        mov     bx, ax
        lodsw
        cmp     bx, [h1]
        jne     .n1
        EQ      ax, 2
        inc     dx
.n1:    cmp     bx, [h2]
        jne     .n2
        EQ      ax, 1
        inc     dx
.n2:    loop    .l
        EQ      dx, 2
        STEP 3                          ; 52h: volatile only
        mov     dx, [h1]
        EMSAX   5200h
        EQB      al, 0
        mov     bl, 1
        EMSERR  5201h, 91h
        EMSAX   5202h
        EQB      al, 0
        STEP 4                          ; 53h, 54h
        mov     dx, [h1]
        mov     si, s_hname
        EMSAX   5301h
        mov     di, buf
        EMSAX   5300h
        EMSAX   5402h
        cmp     bx, [h3]
        jb      fail
        call    gridrest                ; (Lodestone keeps no names)
        mov     si, s_hname
        EMSERR  5401h, 0A0h
        mov     di, buf
        EMSAX   5400h
        mov     ah, 0
        mov     cx, [h3]
        add     cx, 2
        EQ      ax, cx
        clc
        ret

t_handle0:
        call    gridonly
        STEP 1
        EMS     4Bh
        mov     cx, bx
        xor     dx, dx                  ; handle 0: emptied, still open
        EMS     45h
        EMS     4Ch
        EQ      bx, 0
        EMS     4Bh
        EQ      bx, cx
        STEP 2
        xor     dx, dx
        mov     ax, 4400h
        xor     bx, bx
        int     67h
        EQB      ah, 8Ah
        clc
        ret

t_frame:
        STEP 1
        EMSAX   5801h
        EQ      cx, 4
        push    ds
        pop     es
        mov     di, buf
        EMSAX   5800h
        EQ      cx, 4
        mov     si, buf
        mov     bx, FRAME
        xor     dx, dx
.l:     lodsw
        EQ      ax, bx
        lodsw
        EQ      ax, dx
        add     bx, 400h
        inc     dx
        loop    .l
        STEP 2
        EMS     42h
        mov     cx, bx
        mov     si, dx
        EMSAX   5901h
        EQ      bx, cx
        EQ      dx, si
        clc
        ret

; 57h between conventional memory and EMS, across a page boundary
t_move: STEP 1
        mov     bx, 3
        call    alloc
        mov     [h1], dx
        push    ds
        pop     es
        mov     di, buf
        mov     cx, BUFSZ
        xor     bx, bx
        call    patfill
        mov     di, ctx1
        EMSAX   4E00h
        STEP 2                          ; buf -> page 0 offset 10000 (into page 1)
        mov     dx, [h1]
        D57     BUFSZ, 0, 0, buf, ds, 1, dx, 10000, 0
        mov     al, 0
        call    mv
        or      ah, ah
        jnz     efail
        STEP 3                          ; the windows as they were
        mov     di, ctx2
        EMSAX   4E00h
        EMSAX   4E03h
        mov     cl, al
        xor     ch, ch
        mov     si, ctx1
        mov     di, ctx2
        repe    cmpsb
        jne     fail
        STEP 4                          ; and back, to buf2
        mov     di, buf2
        mov     cx, BUFSZ
        xor     al, al
        rep     stosb
        mov     dx, [h1]
        D57     BUFSZ, 1, dx, 10000, 0, 0, 0, buf2, ds
        mov     al, 0
        call    mv
        or      ah, ah
        jnz     efail
        mov     di, buf2
        mov     cx, BUFSZ
        xor     bx, bx
        call    patchk
        STEP 5                          ; the last byte is on page 1
        mov     al, 1
        mov     bx, 1
        mov     dx, [h1]
        call    map
        push    es
        push    FRAME + 400h
        pop     es
        mov     al, [es:10000 + BUFSZ - 1 - 4000h]
        pop     es
        push    ax
        mov     bx, BUFSZ - 1
        call    patb
        pop     cx
        EQB      cl, al
        STEP 6                          ; length 0
        D57     0, 0, 0, buf, ds, 1, dx, 0, 0
        mov     al, 0
        call    mv
        EQB      ah, 0
        clc
        ret

; 57h inside one handle: overlapping, both ways (92h), and exchange
t_overlap:
        STEP 1
        mov     bx, 3
        call    alloc
        mov     [h1], dx
        push    ds
        pop     es
        mov     di, buf
        mov     cx, BUFSZ
        xor     bx, bx
        call    patfill
        mov     dx, [h1]
        D57     BUFSZ, 0, 0, buf, ds, 1, dx, 0, 0
        mov     al, 0
        call    mv
        or      ah, ah
        jnz     efail
        STEP 2                          ; up by 100: 92h, comes out right
        mov     dx, [h1]
        D57     BUFSZ, 1, dx, 0, 0, 1, dx, 100, 0
        mov     al, 0
        call    mv
        EQB      ah, 92h
        call    .back100
        mov     di, buf2
        mov     cx, BUFSZ
        xor     bx, bx
        call    patchk
        STEP 3                          ; down by 60 (from 100 to 40)
        mov     dx, [h1]
        D57     BUFSZ, 1, dx, 100, 0, 1, dx, 40, 0
        mov     al, 0
        call    mv
        EQB      ah, 92h
        mov     dx, [h1]
        D57     BUFSZ, 1, dx, 40, 0, 0, 0, buf2, ds
        mov     al, 0
        call    mv
        or      ah, ah
        jnz     efail
        mov     di, buf2
        mov     cx, BUFSZ
        xor     bx, bx
        call    patchk
        STEP 4                          ; an exchange can't overlap
        mov     dx, [h1]
        D57     1000, 1, dx, 0, 0, 1, dx, 500, 0
        mov     al, 1
        call    mv
        EQB      ah, 97h
        STEP 5                          ; exchange: buf (pattern) <-> page 2
        mov     bx, 1                   ; (another handle, all 33h)
        call    alloc
        mov     [h2], dx
        xor     al, al
        xor     bx, bx
        call    map
        push    es
        push    FRAME
        pop     es
        xor     di, di
        mov     cx, 2000h
        mov     ax, 3333h
        rep     stosw
        pop     es
        mov     dx, [h2]
        D57     5000, 0, 0, buf, ds, 1, dx, 0, 0
        mov     al, 1
        call    mv
        or      ah, ah
        jnz     efail
        mov     di, buf
        mov     cx, 5000
        mov     al, 33h
        repe    scasb
        jne     fail
        mov     dx, [h2]
        D57     5000, 1, dx, 0, 0, 0, 0, buf2, ds
        mov     al, 0
        call    mv
        mov     di, buf2
        mov     cx, 5000
        xor     bx, bx
        call    patchk
        STEP 6                          ; S14: up by 101, an odd length
        push    ds                      ;  (backwards: a byte, then words)
        pop     es
        mov     di, buf
        mov     cx, BUFSZ
        xor     bx, bx
        call    patfill
        mov     dx, [h1]
        D57     BUFSZ, 0, 0, buf, ds, 1, dx, 0, 0
        mov     al, 0
        call    mv
        or      ah, ah
        jnz     efail
        mov     dx, [h1]
        D57     BUFSZ - 1, 1, dx, 0, 0, 1, dx, 101, 0
        mov     al, 0
        call    mv
        EQB      ah, 92h
        mov     dx, [h1]
        D57     BUFSZ - 1, 1, dx, 101, 0, 0, 0, buf2, ds
        mov     al, 0
        call    mv
        or      ah, ah
        jnz     efail
        mov     di, buf2
        mov     cx, BUFSZ - 1
        xor     bx, bx
        call    patchk
        STEP 7                          ; S14: an odd exchange at odd offsets
        mov     dx, [h2]                ;  (a byte, then words)
        xor     al, al
        xor     bx, bx
        call    map
        push    FRAME
        pop     es
        xor     di, di
        mov     cx, 2000h
        mov     ax, 3333h
        rep     stosw
        mov     dx, [h2]
        D57     4999, 0, 0, buf + 1, ds, 1, dx, 1, 0
        mov     al, 1
        call    mv
        or      ah, ah
        jnz     efail
        push    ds
        pop     es
        mov     di, buf + 1             ; buf: 33h between its own ends
        mov     cx, 4999
        mov     al, 33h
        repe    scasb
        jne     fail
        mov     di, buf
        mov     cx, 1
        xor     bx, bx
        call    patchk
        mov     di, buf + 5000
        mov     cx, 1
        mov     bx, 5000
        call    patchk
        mov     dx, [h2]                ; the page: the pattern between 33h's
        xor     al, al
        xor     bx, bx
        call    map
        push    FRAME
        pop     es
        cmp     byte [es:0], 33h
        jne     fail
        cmp     byte [es:5000], 33h
        jne     fail
        mov     di, 1
        mov     cx, 4999
        mov     bx, 1
        call    patchk
        push    ds
        pop     es
        clc
        ret
.back100:
        mov     dx, [h1]
        D57     BUFSZ, 1, dx, 100, 0, 0, 0, buf2, ds
        mov     al, 0
        call    mv
        or      ah, ah
        jnz     efail
        ret

t_moveerr:
        STEP 1
        mov     bx, 1
        call    alloc
        mov     [h1], dx
        D57     10, 2, 0, buf, ds, 1, dx, 0, 0
        mov     al, 0
        call    mv
        EQB      ah, 98h
        STEP 2
        D57     10, 0, 0, buf, ds, 1, dx, 4000h, 0
        mov     al, 0
        call    mv
        EQB      ah, 95h
        STEP 3
        D57     10, 0, 0, buf, ds, 1, dx, 0, 1
        mov     al, 0
        call    mv
        EQB      ah, 8Ah
        STEP 4
        D57     4000h, 0, 0, buf, ds, 1, dx, 1, 0
        mov     al, 0
        call    mv
        EQB      ah, 93h
        STEP 5
        D57     10, 0, 0, buf, ds, 1, 999, 0, 0
        mov     al, 0
        call    mv
        EQB      ah, 83h
        STEP 6
        D57     100h, 0, 0, 0FFF0h, 0FFFFh, 1, dx, 0, 0
        mov     al, 0
        call    mv
        EQB      ah, 0A2h
        STEP 7
        D57     0, 0, 0, buf, ds, 1, dx, 0, 0
        mov     word [desc+2], 11h      ; 1 MB + 64 KB
        mov     al, 0
        call    mv
        EQB      ah, 96h
        STEP 8
        D57     10, 0, 0, buf, ds, 1, dx, 0, 0
        mov     al, 2
        call    mv
        EQB      ah, 8Fh
        clc
        ret

; 57h from conventional memory that is a page in the frame (window 2)
t_inframe:
        STEP 1
        mov     bx, 1
        call    alloc
        mov     [h1], dx
        mov     bx, 1
        call    alloc
        mov     [h2], dx
        mov     al, 2                   ; h1's page in window 2: all 77h
        xor     bx, bx
        mov     dx, [h1]
        call    map
        push    es
        push    FRAME + 800h
        pop     es
        xor     di, di
        mov     cx, 2000h
        mov     ax, 7777h
        rep     stosw
        pop     es
        STEP 2
        mov     dx, [h2]
        D57     1000, 0, 0, 0, FRAME + 800h, 1, dx, 0, 0
        mov     al, 0
        call    mv
        or      ah, ah
        jnz     efail
        STEP 3                          ; window 2 still shows h1's page
        mov     al, 2
        call    peek
        EQ      ax, 7777h
        STEP 4                          ; h2's page got it
        mov     al, 0
        xor     bx, bx
        mov     dx, [h2]
        call    map
        mov     al, 0
        call    peek
        EQ      ax, 7777h
        clc
        ret

; random allocations, resizes and frees; every page of every handle is
; checked after each one
NSLOT   equ 5
t_stress:
        STEP 1
        mov     word [seed], 1234h
        mov     di, slot_h
        mov     cx, NSLOT
        mov     ax, 0FFFFh
        push    ds
        pop     es
        rep     stosw
        mov     word [nops], 300
.op:    call    rnd
        xor     dx, dx
        mov     bx, NSLOT
        div     bx
        mov     si, dx                  ; the slot
        mov     [cur], si
        add     si, si
        cmp     word [slot_h+si], 0FFFFh
        jne     .have
        STEP 2                          ; a new handle, 0-4 pages
        call    rnd
        xor     dx, dx
        mov     bx, 5
        div     bx
        mov     bx, dx
        EMSAX   5A00h
        call    newh
        mov     si, [cur]
        mov     [slot_n+si], bl
        inc     byte [tagc]
        mov     al, [tagc]
        mov     [slot_t+si], al
        add     si, si
        mov     [slot_h+si], dx
        xor     cx, cx                  ; its pages from 0
        call    .sign
        jmp     .check
.have:  call    rnd
        test    al, 3
        jnz     .resize
        STEP 3                          ; close it
        mov     dx, [slot_h+si]
        call    freeh
        mov     si, [cur]
        add     si, si
        mov     word [slot_h+si], 0FFFFh
        jmp     .check
.resize:
        STEP 4                          ; 0-5 pages
        call    rnd
        xor     dx, dx
        mov     bx, 6
        div     bx
        mov     bx, dx
        mov     dx, [slot_h+si]
        EMS     51h
        mov     si, [cur]
        xor     ch, ch
        mov     cl, [slot_n+si]         ; the new ones get signed
        mov     [slot_n+si], bl
        add     si, si
        mov     dx, [slot_h+si]
        call    .sign
.check: STEP 5
        xor     si, si
.cs:    mov     dx, [slot_h+si]
        cmp     dx, 0FFFFh
        je      .cn
        push    si
        shr     si, 1
        mov     al, [slot_t+si]
        xor     bh, bh
        mov     bl, [slot_n+si]
        mov     cx, bx
        xor     bx, bx
        jcxz    .ce
.cp:    call    chksig
        inc     bx
        loop    .cp
.ce:    pop     si
.cn:    add     si, 2
        cmp     si, NSLOT * 2
        jb      .cs
        dec     word [nops]
        jnz     .op
        clc
        ret
; pages CX up to [slot_n] of slot [cur] (handle DX) get their signatures
.sign:  mov     si, [cur]
        mov     al, [slot_t+si]
        xor     bh, bh
        mov     bl, [slot_n+si]
        xchg    bx, cx                  ; BX = from, CX = to
.sl:    cmp     bx, cx
        jae     .sx
        call    setsig
        inc     bx
        jmp     .sl
.sx:    ret

rnd:    mov     ax, [seed]              ; -> AX
        push    dx
        mov     dx, 25173
        mul     dx
        add     ax, 13849
        mov     [seed], ax
        pop     dx
        ret

; a program that ends without giving its EMS back: Lodestone takes it back
t_leak: call    gridonly
        STEP 1
        EMS     42h
        mov     [h1], bx
        mov     si, s_childl
        call    runchild
        STEP 2
        EMS     42h
        EQ      bx, [h1]
        clc
        ret

; a TSR keeps its EMS (then this takes it, and its memory, away)
t_tsr:  call    gridonly
        STEP 1
        EMS     42h
        mov     [h1], bx
        mov     word [tsr_psp], 0
        mov     si, s_childt
        call    runchild
        STEP 2
        cmp     word [tsr_psp], 0
        je      failnc
        EMS     42h
        mov     ax, [h1]
        sub     ax, 2
        EQ      bx, ax
        STEP 3
        mov     dx, [tsr_h]
        EMS     45h
        mov     es, [tsr_psp]
        mov     es, [es:2Ch]
        mov     ah, 49h
        int     21h
        mov     es, [tsr_psp]
        mov     ah, 49h
        int     21h
        jc      fail
        push    ds
        pop     es
        clc
        ret

; this program again with the tail at SI ("/L", "/T")
runchild:
        mov     di, ctail + 1
        xor     cx, cx
.t:     lodsb
        or      al, al
        jz      .te
        mov     [di], al
        inc     di
        inc     cx
        jmp     .t
.te:    mov     byte [di], 13
        mov     [ctail], cl
        push    ds                      ; our own name: after the environment
        mov     ds, [2Ch]
        xor     si, si
.e:     lodsb
        or      al, al
        jnz     .e
        cmp     byte [si], 0
        jne     .e
        add     si, 3
        push    cs
        pop     es
        mov     di, pathbuf
.p:     lodsb
        stosb
        or      al, al
        jnz     .p
        pop     ds
        mov     word [epb], 0
        mov     word [epb + 2], ctail
        mov     [epb + 4], ds
        mov     word [epb + 6], fcb
        mov     [epb + 8], ds
        mov     word [epb + 10], fcb
        mov     [epb + 12], ds
        mov     dx, pathbuf
        mov     bx, epb
        mov     ax, 4B00h
        int     21h
        push    cs
        pop     ds
        push    cs
        pop     es
        jc      fail
        ret

child_leak:                             ; EMSTEST /L
        mov     bx, 3
        mov     ah, 43h
        int     67h
        mov     ax, 4C00h
        int     21h

child_tsr:                              ; EMSTEST /T: 2 pages, then resident
        mov     bx, 2
        mov     ah, 43h
        int     67h
        mov     es, [16h]               ; tell the parent (the same program)
        mov     [es:tsr_h], dx
        mov     [es:tsr_psp], cs
        mov     dx, 6
        mov     ax, 3100h
        int     21h

; information for the next change: can the floppy DMA into the frame?
t_dma:  STEP 1
        mov     bx, 1
        call    alloc
        xor     al, al
        xor     bx, bx
        call    map
        push    FRAME                   ; the boot sector of A:, into the
        pop     es                      ;  frame (filled with 55h first) ...
        xor     di, di
        mov     cx, 256
        mov     ax, 5555h
        rep     stosw
        xor     bx, bx
        call    rdsec
        push    ds
        pop     es
        mov     si, s_dmafail
        jc      .info
        mov     bx, buf                 ; ... and into memory
        call    rdsec
        jc      .skip
        push    ds
        push    FRAME
        pop     ds
        xor     si, si
        mov     di, buf
        mov     cx, 512
        repe    cmpsb
        pop     ds
        mov     si, s_dmaok
        je      .info
        mov     si, s_dmabad
        mov     ah, 0
.info:  mov     al, ah
        xor     ah, ah
        cmp     si, s_dmafail
        je      .n
        mov     ax, 0FFFFh
.n:     call    info
.skip:  clc
        ret
; A: sector 1 to ES:BX, 3 tries (a drive just started, a disk change)
rdsec:  mov     si, 3
.t:     mov     ax, 0201h
        mov     cx, 1
        xor     dx, dx
        int     13h
        jnc     .x
        push    ax
        xor     ax, ax
        int     13h
        pop     ax
        dec     si
        jnz     .t
        stc
.x:     ret

; without EMS: no EMMXXXX0 either (Lodestone)
t_none: call    gridonly
        STEP 1
        mov     dx, s_emmdev
        mov     ax, 3D00h
        int     21h
        jnc     failnc
        EQ      ax, 2
        STEP 2
        mov     ah, 40h
        int     67h
        EQB      ah, 84h
        clc
        ret

; ---------------------------------------------------------------------
tests:  dw t_detect, n_detect
        dw t_map, n_map
        dw t_alias, n_alias
        dw t_errors, n_errors
        dw t_save, n_save
        dw t_context, n_context
        dw t_multi, n_multi
        dw t_realloc, n_realloc
        dw t_neighbours, n_neighbours
        dw t_middle, n_middle
        dw t_all, n_all
        dw t_handles, n_handles
        dw t_handle0, n_handle0
        dw t_frame, n_frame
        dw t_move, n_move
        dw t_overlap, n_overlap
        dw t_moveerr, n_moveerr
        dw t_inframe, n_inframe
        dw t_stress, n_stress
        dw t_leak, n_leak
        dw t_tsr, n_tsr
        dw t_dma, n_dma
        dw 0
tests_noems:
        dw t_none, n_none
        dw 0

n_detect    db 'detection: EMMXXXX0, status, version, frame, pages', 0
n_map       db 'allocate, map, free (43h 44h 45h 4Ch)', 0
n_alias     db 'one page in two windows; a window off', 0
n_errors    db 'error codes', 0
n_save      db 'save and restore (47h 48h)', 0
n_context   db 'contexts (4Eh 4Fh)', 0
n_multi     db 'map multiple (50h)', 0
n_realloc   db 'reallocate (51h)', 0
n_neighbours db 'resizing keeps the other handles', 0
n_middle    db 'an empty handle where a middle one starts', 0
n_all       db 'every free page in one handle', 0
n_handles   db 'handles: 4Bh 4Dh 52h 53h 54h', 0
n_handle0   db 'handle 0', 0
n_frame     db 'mappable windows (58h 59h)', 0
n_move      db 'move: conventional <-> EMS (57h)', 0
n_overlap   db 'move inside a handle, overlapping; exchange', 0
n_moveerr   db 'move: error codes', 0
n_inframe   db 'move from a page in the frame', 0
n_stress    db '300 random allocations, resizes, frees', 0
n_leak      db 'EMS a program leaves comes back', 0
n_tsr       db 'a TSR keeps its EMS', 0
n_dma       db 'floppy DMA into the frame (information)', 0
n_none      db 'no EMS: no EMMXXXX0, INT 67h says 84h', 0

s_hello     db 'EMSTEST - EMS (INT 67h) checks', 13, 10, 0
s_key       db 'Press any key', 0
s_log       db 'EMSTEST.TXT', 0
s_saved     db 'Added to EMSTEST.TXT', 13, 10, 0
s_nosave    db "Can't write EMSTEST.TXT", 13, 10, 0
s_noems     db 'no EMS manager (INT 67h)', 13, 10, 0
s_emm       db 'EMMXXXX0'
s_emmdev    db 'EMMXXXX0', 0
s_ok        db 'ok    ', 0
s_fail      db 'FAIL  ', 0
s_skip      db 'skip  ', 0
s_info      db 'info    ', 0
s_step      db ' (step ', 0
s_code      db ', AX=', 0
s_total     db 13, 10, 'EMSTEST: ', 0
s_passed    db ' passed, ', 0
s_failed    db ' failed', 13, 10, 0
s_crlf      db 13, 10, 0
s_ipages    db 'pages: ', 0
s_ifree     db 'free: ', 0
s_ictx2     db 'context bytes (4E03h): ', 0
s_ihandles  db 'handles (5402h): ', 0
s_dmaok     db 'floppy DMA into the frame: works', 0
s_dmabad    db 'floppy DMA into the frame: the data differs', 0
s_dmafail   db 'floppy DMA into the frame: BIOS error ', 0
s_hname     db 'EMSTEST1'
s_childl    db ' /L', 0
s_childt    db ' /T', 0
plist       dw 2, FRAME, FRAME + 800h
plistbad    dw 1, FRAME + 100h
mmap0       dw 3, 0, 2, 1, 1, 2, 0, 3
mmap1       dw 3, FRAME, 2, FRAME + 400h, 1, FRAME + 800h, 0, FRAME + 0C00h
mmapbad     dw 0, 0D000h
fcb         db 0, '           ', 0, 0, 0, 0
tsr_h       dw 0
tsr_psp     dw 0

section .bss
bss_start:
npass   resw 1
nfail   resw 1
tname   resw 1
tsp     resw 1
step    resb 1
skipped resb 1
lodestone  resb 1
tagc    resb 1
ecode   resw 1
total   resw 1
free0   resw 1
h1      resw 1
h2      resw 1
h3      resw 1
h4      resw 1
nh      resw 1
hs      resw 16
seed    resw 1
nops    resw 1
cur     resw 1
slot_h  resw NSLOT
slot_n  resb NSLOT
slot_t  resb NSLOT
epb     resw 7
ctail   resb 128
pathbuf resb 80
desc    resb 18
ctx1    resb 16
ctx2    resb 16
numbuf  resb 8
BUFSZ   equ 16000
buf     resb BUFSZ
buf2    resb BUFSZ
LOGMAX  equ 4000
logging resb 1
logpos  resw 1
logbuf  resb LOGMAX
        resb 1024
stack_top:
