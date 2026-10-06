; =====================================================================
;  D488TEST.COM - the GPIBTEST read-only test set, through Driver488
;  Build: nasm -f bin -o D488TEST.COM D488TEST.ASM            (Grid-OS)
;
;  Run with IOtech DRVR488 loaded (type DRVR488 first).  Uses the driver
;  exactly the way TM5000 does: text commands to \DEV\IEEEOUT ("OUTPUT
;  nn;cmd", "ENTER nn", "SPOLL nn"), replies read from \DEV\IEEEIN, both
;  handles in raw mode, IOCTL "BREAK" first.  Only change: TIME OUT 2 so
;  a silent device can't hang the test (TM5000 relies on the default).
;
;  Same instruments, same read-only commands, same repetitions as
;  GPIBTEST 1.0, so the two logs compare line by line.  Each line shows
;  the driver's own time and, after it, the time with the fixed sleeps
;  TM5000 adds around that call (write 50 ms, enter 50 ms, spoll 50 ms).
;  Output: screen + A:\D488TEST.TXT
; =====================================================================
cpu 286
org 100h

K_ID    equ 0                   ; OUTPUT nn;<q> + ENTER nn
K_READ  equ 1                   ; ENTER nn
K_SPOLL equ 2                   ; SPOLL nn
REPS    equ 10
SPREPS  equ 20
RMAX    equ 4096

start:  cld
        call    log_open
        mov     dx, s_title
        call    puts
        ; ---- open the driver's two devices --------------------------
        mov     dx, n_out
        mov     ax, 3D01h
        int     21h
        jc      nodrv
        mov     [hout], ax
        mov     dx, n_in
        mov     ax, 3D00h
        int     21h
        jc      nodrv
        mov     [hin], ax
        mov     bx, [hout]
        call    rawmode
        mov     bx, [hin]
        call    rawmode
        call    brk
        mov     si, c_tmo               ; TIME OUT 2
        call    dwrite
        mov     si, c_hello             ; driver identification
        call    dwrite
        call    dread
        jc      .nh
        mov     dx, s_drv
        call    puts
        mov     dx, rbuf
        call    puts
        call    crlf
.nh:    call    commit
        call    pit_init
        call    stamp
        mov     [tall], ax
        mov     [tall+2], dx

        mov     dx, s_thdr
        call    puts
        mov     si, bustab
.dev:   lodsb
        cmp     al, 0FFh
        je      .done
        mov     bl, al
        lodsb
        mov     [prof], al
        push    si
        call    test_dev
        call    commit
        pop     si
.skip:  lodsb                           ; skip name
        cmp     al, '$'
        jne     .skip
        jmp     .dev
.done:  call    summary
        call    pit_done
        mov     dx, s_end
        call    puts
        call    log_close
        mov     ax, 4C00h
        int     21h

nodrv:  mov     dx, s_nodrv
        call    puts
        call    log_close
        mov     ax, 4C01h
        int     21h

; ---- one device: BL = address, [prof] = profile, SI -> name ----------
test_dev:
        mov     dx, s_dhdr
        call    puts
        mov     al, bl
        xor     ah, ah
        call    pdec2
        mov     dx, s_2sp
        call    puts
        mov     dx, si
        call    puts
        call    crlf
        mov     al, [prof]
        cmp     al, 'H'
        jne     .t1
        mov     byte [kind], K_ID
        mov     si, q_idn
        mov     di, l_idn
        mov     cx, REPS
        mov     byte [t_show], 1
        call    run_test
        jmp     .tsp
.t1:    cmp     al, 'P'
        je      .tsp
        mov     byte [kind], K_ID
        mov     si, q_id
        mov     di, l_id
        mov     cx, REPS
        mov     byte [t_show], 1
        call    run_test
        mov     byte [kind], K_ID
        mov     si, q_set
        mov     di, l_set
        mov     cx, 1
        mov     byte [t_show], 1
        call    run_test
        cmp     byte [prof], 'M'
        jne     .tsp
        mov     byte [kind], K_READ
        mov     di, l_read
        mov     cx, REPS
        mov     byte [t_show], 1
        call    run_test
.tsp:   mov     byte [kind], K_SPOLL
        mov     di, l_spoll
        mov     cx, SPREPS
        mov     byte [t_show], 1
        call    run_test
        ret

; ---- run one test: [kind], SI = query text, CX reps, DI label, BL addr
run_test:
        mov     [t_q], si
        mov     [t_reps], cx
        mov     [t_lbl], di
        xor     ax, ax
        mov     [t_ok], ax
        mov     [t_sum], ax
        mov     [t_sum+2], ax
        mov     [t_max], ax
        mov     [t_max+2], ax
        dec     ax
        mov     [t_min], ax
        mov     [t_min+2], ax
        mov     cx, [t_reps]
.lp:    push    cx
        call    stamp
        mov     [t0], ax
        mov     [t0+2], dx
        call    xact
        pushf
        call    stamp
        sub     ax, [t0]
        sbb     dx, [t0+2]
        popf
        pop     cx
        jc      .fail
        inc     word [t_ok]
        inc     word [ntrans]
        add     [t_sum], ax
        adc     [t_sum+2], dx
        add     [t_bus], ax
        adc     [t_bus+2], dx
        cmp     dx, [t_min+2]
        ja      .nmin
        jb      .smin
        cmp     ax, [t_min]
        jae     .nmin
.smin:  mov     [t_min], ax
        mov     [t_min+2], dx
.nmin:  cmp     dx, [t_max+2]
        jb      .nmax
        ja      .smax
        cmp     ax, [t_max]
        jbe     .nmax
.smax:  mov     [t_max], ax
        mov     [t_max+2], dx
.nmax:  loop    .lp
        jmp     .rep
.fail:  inc     word [nfail]
        call    brk                     ; get the driver's attention back
.rep:   mov     dx, s_ind
        call    puts
        mov     dx, [t_lbl]
        call    puts
        mov     ax, [t_ok]
        mov     cl, 2
        call    pdecw
        mov     al, '/'
        call    putc
        mov     ax, [t_reps]
        call    pdec
        cmp     word [t_ok], 0
        jne     .some
        mov     dx, s_failed
        call    puts
        ret
.some:  mov     dx, s_avg
        call    puts
        mov     ax, [t_sum]
        mov     dx, [t_sum+2]
        mov     cx, [t_ok]
        push    bx
        call    ldiv
        pop     bx
        mov     [t_avg], ax
        mov     [t_avg+2], dx
        call    pms
        mov     dx, s_min
        call    puts
        mov     ax, [t_min]
        mov     dx, [t_min+2]
        call    pms
        mov     dx, s_max
        call    puts
        mov     ax, [t_max]
        mov     dx, [t_max+2]
        call    pms
        mov     dx, s_ms
        call    puts
        mov     ax, [rxcnt]
        mov     cl, 5
        call    pdecw
        mov     dx, s_bytes
        call    puts
        ; TM5000 fixed sleeps: 100 ms around a query, 50 around enter/spoll
        mov     ax, [t_avg]
        mov     dx, [t_avg+2]
        mov     cx, 50*1193
        cmp     byte [kind], K_ID
        jne     .one
        add     ax, cx
        adc     dx, 0
.one:   add     ax, cx
        adc     dx, 0
        push    dx
        push    ax
        mov     dx, s_tm
        call    puts
        pop     ax
        pop     dx
        call    pms
        mov     dx, s_ms2
        call    puts
        mov     ax, [t_ok]
        cmp     ax, [t_reps]
        je      .nl
        mov     dx, s_then
        call    puts
.nl:    call    crlf
        cmp     byte [t_show], 0
        je      .x
        mov     dx, s_show
        call    puts
        mov     dx, rbuf
        call    puts
        mov     dx, s_show2
        call    puts
.x:     ret

; ---- one Driver488 transaction ([kind], [t_q], BL); CF on error -------
xact:   push    bx
        mov     di, cbuf
        cmp     byte [kind], K_ID
        jne     .en
        mov     si, c_output            ; "OUTPUT nn;<query>"
        call    cpy
        call    putaddr
        mov     al, ';'
        stosb
        mov     si, [t_q]
        call    cpy
        call    endcmd
        mov     si, cbuf
        call    dwrite
        jc      .x
        mov     di, cbuf
.en:    mov     si, c_enter             ; "ENTER nn" or "SPOLL nn"
        cmp     byte [kind], K_SPOLL
        jne     .e2
        mov     si, c_spoll
.e2:    call    cpy
        call    putaddr
        call    endcmd
        mov     si, cbuf
        call    dwrite
        jc      .x
        call    dread
.x:     pop     bx
        ret

cpy:    lodsb                           ; copy ASCIIZ SI -> DI (no 0)
        or      al, al
        jz      .x
        stosb
        jmp     cpy
.x:     ret

putaddr:                                ; two-digit address BL at DI
        mov     al, bl
        xor     ah, ah
        mov     cl, 10
        div     cl
        add     ax, 3030h
        stosw
        ret

endcmd: mov     ax, 0A0Dh               ; CR LF, then terminate
        stosw
        xor     al, al
        stosb
        ret

; write ASCIIZ SI to IEEEOUT; CF on error or short write
dwrite: push    bx
        push    cx
        mov     dx, si
        xor     cx, cx
.l:     lodsb
        or      al, al
        jz      .n
        inc     cx
        jmp     .l
.n:     mov     bx, [hout]
        push    cx
        mov     ah, 40h
        int     21h
        pop     cx
        jc      .x
        cmp     ax, cx
        je      .x                      ; (CF=0 from cmp when equal)
        stc
.x:     pop     cx
        pop     bx
        ret

; read one reply from IEEEIN (until LF) into rdata; rbuf = printable copy
dread:  push    bx
        mov     word [rxcnt], 0
        mov     di, rdata
.l:     mov     bx, [hin]
        mov     cx, rdata+RMAX
        sub     cx, di
        jbe     .eom
        mov     dx, di                  ; one read, like TM5000 (loop only
                                        ; if the driver returns no LF yet)
        mov     ah, 3Fh
        int     21h
        jc      .err
        or      ax, ax
        jz      .eom
        add     [rxcnt], ax
        mov     cx, ax
        mov     si, di
        add     di, ax
.s:     lodsb                           ; LF in this chunk ends the reply
        cmp     al, 0Ah
        je      .eom
        loop    .s
        jmp     .l
.eom:   cmp     word [rxcnt], 0
        je      .err
        call    mkshow
        clc
        pop     bx
        ret
.err:   mov     byte [rbuf], '$'
        stc
        pop     bx
        ret

mkshow: mov     si, rdata               ; printable copy for the log
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
        cmp     di, rbuf+70
        jae     .x
        stosb
        jmp     .l
.x:     mov     byte [di], '$'
        ret

rawmode:                                ; BX = handle
        mov     ax, 4400h
        int     21h
        jc      .x
        or      dl, 20h
        xor     dh, dh
        mov     ax, 4401h
        int     21h
.x:     ret

brk:    mov     bx, [hout]              ; IOCTL write "BREAK"
        mov     dx, c_break
        mov     cx, 5
        mov     ax, 4403h
        int     21h
        ret

summary:
        call    stamp
        sub     ax, [tall]
        sbb     dx, [tall+2]
        mov     [tall], ax
        mov     [tall+2], dx
        mov     dx, s_sum2
        call    puts
        mov     ax, [ntrans]
        call    pdec
        mov     dx, s_sum3
        call    puts
        mov     ax, [nfail]
        call    pdec
        mov     dx, s_sum4
        call    puts
        mov     ax, [t_bus]
        mov     dx, [t_bus+2]
        call    pms
        mov     dx, s_sum5
        call    puts
        mov     ax, [tall]
        mov     dx, [tall+2]
        call    pms
        mov     dx, s_ms
        call    puts
        call    crlf
        ret

%include "common.inc"

; =====================================================================
bustab  db  2,'T','11403$'
        db  6,'T','FG5010$'
        db 11,'T','SI5020$'
        db 13,'T','PS5004$'
        db 16,'M','DM5120$'
        db 18,'H','HP 8753D$'
        db 19,'P','8753D second address$'
        db 28,'M','DM5010$'
        db 29,'M','DC5009$'
        db 30,'T','PS5010$'
        db 0FFh
n_out   db '\DEV\IEEEOUT',0
n_in    db '\DEV\IEEEIN',0
n_log   db 'A:\D488TEST.TXT',0
c_break db 'BREAK'
c_tmo   db 'TIME OUT 2',13,10,0
c_hello db 'HELLO',13,10,0
c_output db 'OUTPUT ',0
c_enter db 'ENTER ',0
c_spoll db 'SPOLL ',0
q_id    db 'ID?',0
q_set   db 'SET?',0
q_idn   db '*IDN?',0
l_id    db 'ID?       $'
l_idn   db '*IDN?     $'
l_set   db 'SET?      $'
l_read  db 'reading   $'
l_spoll db 'ser.poll  $'
s_title db 'D488TEST 1.0 - GPIBTEST read-only set through Driver488 (Grid-OS)',13,10
        db '=================================================================',13,10,'$'
s_nodrv db '** Cannot open \DEV\IEEEOUT / \DEV\IEEEIN - load DRVR488 first.',13,10,'$'
s_drv   db 'Driver: $'
s_thdr  db 13,10,'Times per transaction, ms  (driver alone  | with TM5000 sleeps):',13,10,'$'
s_dhdr  db 13,10,'addr $'
s_2sp   db '  $'
s_ind   db '    $'
s_failed db '  FAILED',13,10,'$'
s_avg   db '  avg$'
s_min   db '  min$'
s_max   db '  max$'
s_ms    db ' ms$'
s_bytes db ' B$'
s_tm    db '  | TM5000$'
s_ms2   db '$'
s_then  db '  then failed$'
s_show  db '        "$'
s_show2 db '"',13,10,'$'
s_sum2  db 13,10,'Summary: $'
s_sum3  db ' transactions OK, $'
s_sum4  db ' failed',13,10,'Driver time $'
s_sum5  db ' ms, total run $'
s_end   db 13,10,'Log: A:\D488TEST.TXT',13,10,'$'
s_crlf  db 13,10,'$'
prof    db 0
kind    db 0
t_show  db 0
pitset  db 0
hout    dw 0
hin     dw 0
fh      dw 0
bufn    dw 0
t_q     dw 0
t_reps  dw 0
t_lbl   dw 0
t_ok    dw 0
rxcnt   dw 0
ntrans  dw 0
nfail   dw 0
t0      dd 0
t_sum   dd 0
t_min   dd 0
t_max   dd 0
t_avg   dd 0
t_bus   dd 0
tall    dd 0
rbuf    times 72 db 0
cbuf    times 80 db 0
fbuf    times 512 db 0
rdata   times RMAX+2 db 0
