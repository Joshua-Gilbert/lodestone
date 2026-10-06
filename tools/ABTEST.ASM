; =====================================================================
;  ABTEST.COM - A/B bulk-read test: direct chip access vs GRIDGPIB
;  Build: nasm -f bin -o ABTEST.COM ABTEST.ASM                   (Grid-OS)
;
;  Needs GRIDGPIB loaded.  Alternates the same read-only transaction
;  through the two paths, 5 rounds, so the instrument is in the same state
;  for both:  11403 (addr 2) SET? - 3.5 KB, the long reply that came out
;  7-16% slower through the driver than direct.  Output: A:\ABTEST.TXT
; =====================================================================
cpu 286
org 100h

%include "direct_equ.inc"
ROUNDS  equ 5
DEV     equ 2
RAWMAX  equ 4096
RBUFLEN equ 70

start:  cld
        call    log_open
        mov     dx, s_title
        call    puts
        mov     al, 60h                 ; find GRIDGPIB
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
.got:   mov     [gint+1], al
        push    ds
        pop     es
        call    pit_init
        mov     byte [round], 0
.rnd:   ; ---- A: direct ----
        call    d_recover               ; chip init + IFC + REN
        mov     bl, DEV
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     si, q_set
        call    d_query
        pushf
        call    stamp
        sub     ax, [t0]
        sbb     dx, [t0+2]
        popf
        mov     di, s_a
        call    report
        add     [suma], ax
        adc     [suma+2], dx
        ; ---- B: through the driver ----
        mov     ah, 01h                 ; driver: IFC + REN, fresh state
        call    gint
        mov     bl, DEV
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        mov     si, q_set2
        mov     cx, 5
        push    ds
        pop     es
        mov     di, raw
        mov     dx, RAWMAX
        mov     al, 1
        mov     ah, 04h
        call    gint
        mov     [rxcnt], cx
        pushf
        call    stamp
        sub     ax, [t0]
        sbb     dx, [t0+2]
        popf
        mov     di, s_b
        call    report
        add     [sumb], ax
        adc     [sumb+2], dx
        call    commit
        inc     byte [round]
        cmp     byte [round], ROUNDS
        jb      .rnd
        ; ---- averages ----
        mov     dx, s_avga
        call    puts
        mov     ax, [suma]
        mov     dx, [suma+2]
        mov     cx, ROUNDS
        call    ldiv
        call    pms
        mov     dx, s_avgb
        call    puts
        mov     ax, [sumb]
        mov     dx, [sumb+2]
        mov     cx, ROUNDS
        call    ldiv
        call    pms
        mov     dx, s_ms
        call    puts
        call    crlf
        mov     ah, 01h                 ; leave the driver in charge
        call    gint
quit:   call    pit_done
        call    log_close
        mov     ax, 4C00h
        int     21h

gint:   int     60h
        ret

; DI = label, DX:AX = elapsed, CF = failed, [rxcnt] = bytes
report: pushf
        push    ax
        push    dx
        mov     dx, s_r
        call    puts
        mov     al, [round]
        inc     al
        xor     ah, ah
        call    pdec
        mov     dx, di
        call    puts
        pop     dx
        pop     ax
        push    ax
        push    dx
        call    pms
        mov     dx, s_ms
        call    puts
        mov     ax, [rxcnt]
        mov     cl, 6
        call    pdecw
        mov     dx, s_bytes
        call    puts
        pop     dx
        pop     ax
        popf
        jnc     .ok
        push    dx
        mov     dx, s_fail
        call    puts
        pop     dx
.ok:    push    dx
        call    crlf
        pop     dx
        ret

%include "direct.inc"
%include "timing.inc"
%include "io.inc"

sig     db 'GRIDGPIB'
q_set   db 'SET?',10,0                  ; direct: ASCIIZ with LF
q_set2  db 'SET?',13,10                 ; driver: 5 bytes (CR LF like gg_puts)
n_log   db 'A:\ABTEST.TXT',0
s_title db 'ABTEST 1.0 - 11403 SET? (3.5 KB): direct vs GRIDGPIB, alternating',13,10,'$'
s_nodrv db '** GRIDGPIB not loaded.',13,10,'$'
s_r     db '  round $'
s_a     db '  direct  $'
s_b     db '  driver  $'
s_ms    db ' ms$'
s_bytes db ' B$'
s_fail  db '  FAILED$'
s_avga  db 13,10,'average: direct $'
s_avgb  db ' ms   driver $'
s_crlf  db 13,10,'$'
round   db 0
pitset  db 0
shadow1 db 0
shadow2 db 0
rawisr1 db 0
rawadsr db 0
rawdir  db 0
lat     dw 0
recov   dw 0
t_start dw 0
t_len   dw 0
rxcnt   dw 0
fh      dw 0
bufn    dw 0
t0      dd 0
suma    dd 0
sumb    dd 0
rbuf    times RBUFLEN+2 db 0
fbuf    times 512 db 0
raw     times RAWMAX+2 db 0
