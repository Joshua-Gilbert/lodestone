; =====================================================================
;  GGTEST.COM - the GPIBTEST read-only test set through GRIDGPIB  (Grid-OS)
;  Build: nasm -f bin -o GGTEST.COM GGTEST.ASM
;
;  Needs GRIDGPIB loaded.  Same scan, same instruments, same read-only
;  commands and repetitions as GPIBTEST 1.0 (direct) and D488TEST 1.0
;  (Driver488), so the three logs compare line by line.  Every bus
;  operation goes through the driver's INT API, exactly as a program
;  such as TM5000 will use it.  Output: screen + A:\GGTEST.TXT
; =====================================================================
cpu 286
org 100h

MYADDR  equ 21
RBUFLEN equ 70
RAWMAX  equ 4096

start:  cld
        call    log_open
        mov     dx, s_title
        call    puts
        ; ---- find the driver: INT 60h-66h with 'GRIDGPIB' at entry+2 --
        mov     al, 60h
.f:     push    ax
        mov     ah, 35h
        int     21h
        lea     di, [bx+2]
        mov     si, sig
        mov     cx, 8
        repe    cmpsb
        pop     ax
        je      .got
        inc     al
        cmp     al, 67h
        jb      .f
        mov     dx, s_nodrv
        call    puts
        jmp     quit
.got:   mov     [gint+1], al            ; patch INT nn
        push    ds
        pop     es
        mov     ah, 00h
        call    gint
        cmp     ax, 4747h
        jne     .bad
        mov     dx, s_drv
        call    puts
        mov     al, [gint+1]
        call    phex8
        mov     dx, s_drv2
        call    puts
        mov     ah, 0Ch                 ; stats: DX = resident bytes
        call    gint
        mov     ax, dx
        call    pdec
        mov     dx, s_drv3
        call    puts
        mov     ah, 01h                 ; IFC + REN
        call    gint
        jnc     .init
.bad:   mov     dx, s_drvbad
        call    puts
        jmp     quit
.init:  call    commit
        call    pit_init
        call    stamp
        mov     [tall], ax
        mov     [tall+2], dx

        ; ---- serial-poll scan (twice each), like GPIBSCAN -----------------
        mov     dx, s_scan
        call    puts
        xor     bx, bx
.sc:    cmp     bl, MYADDR
        je      .scn
        call    spoll
        jc      .scn
        mov     [stat], al
        call    spoll
        jc      .scn
        mov     [stat2], al
        mov     byte [amap+bx], '#'
        inc     byte [nfound]
        mov     di, [nfound]
        and     di, 0FFh
        mov     [found+di-1], bl
        mov     dx, s_addr
        call    puts
        mov     al, bl
        xor     ah, ah
        call    pdec2
        mov     dx, s_stat
        call    puts
        mov     al, [stat]
        call    phex8
        mov     dx, s_stat2
        call    puts
        mov     al, [stat2]
        call    phex8
        mov     al, 'h'
        call    putc
        call    crlf
.scn:   inc     bl
        cmp     bl, 31
        jb      .sc
        mov     byte [amap+MYADDR], '*'
        mov     dx, s_map
        call    puts
        mov     dx, amap
        call    puts
        call    crlf
        mov     dx, s_nfound
        call    puts
        mov     al, [nfound]
        xor     ah, ah
        call    pdec
        mov     dx, s_devs
        call    puts
        call    commit

        ; ---- the test set ---------------------------------------------------
        cmp     byte [nfound], 0
        je      .end
        mov     dx, s_thdr
        call    puts
        call    commit
        xor     si, si
.dev:   mov     bl, [found+si]
        push    si
        call    test_dev
        call    commit
        pop     si
        inc     si
        mov     ax, si
        cmp     al, [nfound]
        jb      .dev
        mov     ah, 0Ch                 ; driver's own recovery counter
        call    gint
        mov     [recov], ax
        call    summary
.end:   mov     bl, 0FFh                ; everyone back to local
        mov     ah, 09h
        call    gint
        mov     dx, s_done
        call    puts
quit:   call    pit_done
        call    log_close
        mov     ax, 4C00h
        int     21h

gint:   int     60h                     ; patched to the driver's vector
        ret

; ---- driver wrappers with the GPIBTEST calling convention ------------
; spoll: BL = addr -> AL = status, CF on error
spoll:  push    bx
        mov     ah, 05h
        call    gint
        pop     bx
        jnc     .x
        push    ax
        mov     al, ah
        xor     ah, ah
        mov     [lasterr], ax
        pop     ax
        stc
.x:     ret

; query: SI = ASCIIZ command, BL = addr -> rbuf ('$'), rxcnt; CF if none
query:  push    bx
        push    si
        push    di
        mov     di, si
        xor     cx, cx
.l:     cmp     byte [di], 0
        je      .n
        inc     di
        inc     cx
        jmp     .l
.n:     push    ds
        pop     es
        mov     di, raw
        mov     dx, RAWMAX
        mov     al, 1                   ; stop at LF
        mov     ah, 04h
        call    gint
        jmp     qdone

; query_read: BL = addr, read one message (no command sent)
query_read:
        push    bx
        push    si
        push    di
        push    ds
        pop     es
        mov     di, raw
        mov     cx, RAWMAX
        mov     al, 1
        mov     ah, 03h
        call    gint
qdone:  mov     [rxcnt], cx
        mov     word [lasterr], 0
        jnc     .ok
        mov     [lasterr], ax           ; driver error code
.ok:    pushf
        call    mkshow
        popf
        jc      .x
        cmp     word [rxcnt], 0         ; nothing came -> treat as failure
        jne     .x
        stc
.x:     pop     di
        pop     si
        pop     bx
        ret

mkshow: push    ax
        push    cx
        push    si
        push    di
        mov     si, raw
        mov     di, rbuf
        mov     cx, [rxcnt]
.l:     jcxz    .x
        dec     cx
        lodsb
        cmp     al, 20h
        jb      .l
        cmp     al, 7Eh
        ja      .l
        cmp     al, '$'
        je      .l
        cmp     di, rbuf+RBUFLEN
        jae     .x
        stosb
        jmp     .l
.x:     mov     byte [di], '$'
        pop     di
        pop     si
        pop     cx
        pop     ax
        ret

%include "testcore.inc"
%include "timing.inc"
%include "io.inc"

; =====================================================================
sig     db 'GRIDGPIB'
q_id    db 'ID?',10,0
q_idn   db '*IDN?',10,0
n_log   db 'A:\GGTEST.TXT',0
s_title db 'GGTEST 1.1 - GPIBTEST read-only set through GRIDGPIB (Grid-OS)',13,10
        db '===============================================================',13,10,'$'
s_nodrv db '** GRIDGPIB is not loaded (no INT 60h-66h with its signature).',13,10,'$'
s_drvbad db '** GRIDGPIB did not answer / could not initialise the bus.',13,10,'$'
s_drv   db 'Driver: GRIDGPIB on INT $'
s_drv2  db 'h, $'
s_drv3  db ' bytes resident',13,10,'$'
s_scan  db 13,10,'Serial-polling addresses 0-30 (each twice)...',13,10,'$'
s_addr  db '  addr $'
s_stat  db ': present, status $'
s_stat2 db 'h/$'
s_map   db 13,10,'Map   0123456789012345678901234567890',13,10,'      $'
s_nfound db 'Found $'
s_devs  db ' device(s).',13,10,'$'
s_noid  db '(no reply)$'
s_done  db 13,10,'Bus released (all devices local). Log: A:\GGTEST.TXT',13,10,'$'
s_crlf  db 13,10,'$'
amap    db '...............................$'
nfound  db 0
stat    db 0
stat2   db 0
recov   dw 0
fh      dw 0
bufn    dw 0
found   times 32 db 0
rbuf    times RBUFLEN+2 db 0
%include "testdata.inc"
fbuf    times 512 db 0
raw     times RAWMAX+2 db 0
