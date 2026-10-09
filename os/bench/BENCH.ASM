; BENCH.COM - DOS file system benchmark (Lodestone or MS-DOS, same program)
;
; Times each test with the BIOS clock (INT 1Ah, 55 ms ticks) and prints
; seconds and KB/s.  Works on the current drive and directory; makes and
; deletes BENCH.DAT (256 KB), BENCHX.EXE (120 KB) and BENCHnn.TMP.
; Everything it prints is also added to BENCH.TXT there (written at the
; end, so the log doesn't disturb the timing), then it waits for a key.
; Every timing point also passes BX = BE00h + 2n (start) / 2n+1 (end), which
; the emulator records to the microsecond; real BIOSes ignore BX.
; 1.3: with an EMS manager (INT 67h), three EMS tests after the total
; (not in it): page mapping, and 57h moves to and from EMS.
; 1.4: BENCH /N n runs each test n times between its two timing points
; (1-99), for a disk so fast that one run is a tick or two (M:, the
; temporary disk in EMS); the times are for all n, the KB/s for one.
cpu 286
org 100h

CHUNK   equ 16384
LOGMAX  equ 3600
BIGKB   equ 256
EXEKB   equ 120

start:  mov     sp, stack_top
        cld
        mov     di, bss_start
        mov     cx, stack_top - bss_start
        xor     al, al
        rep     stosb
        mov     ax, [2]                 ; memory a program gets (paragraphs)
        mov     bx, cs
        sub     ax, bx
        mov     [memp], ax
        mov     bx, prog_end + 15
        shr     bx, 4
        mov     ah, 4Ah
        int     21h
        mov     word [reps], 1          ; /N n: each test n times
        mov     si, 81h
.arg:   lodsb
        cmp     al, 13
        je      .args
        cmp     al, '/'
        jne     .arg
        lodsb
        and     al, 0DFh
        cmp     al, 'N'
        jne     .arg
.sp:    lodsb
        cmp     al, ' '
        je      .sp
        dec     si
        xor     bx, bx
.dg:    lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .dn
        cbw
        imul    bx, bx, 10
        add     bx, ax
        cmp     bx, 99
        jbe     .dg
        mov     bx, 99
.dn:    or      bx, bx
        jz      .args
        mov     [reps], bx
.args:  mov     ax, BIGKB
        mul     word [reps]
        mov     [kbn], ax
        mov     dx, s_title
        call    print
        call    is_lodestone
        mov     dx, s_lodestone
        je      .os
        mov     ax, 3000h               ; FreeDOS: OEM FDh
        int     21h
        mov     dx, s_freedos
        cmp     bh, 0FDh
        je      .os
        mov     dx, s_msdos
.os:    call    print
        mov     ah, 30h
        int     21h
        push    ax
        xor     ah, ah
        call    pnum
        mov     dl, '.'
        call    putc
        pop     ax
        mov     al, ah
        xor     ah, ah
        cmp     al, 10
        jae     .v
        push    ax
        mov     dl, '0'
        call    putc
        pop     ax
.v:     call    pnum
        mov     dx, s_close
        call    print
        call    pdate
        mov     dx, s_mem
        call    print
        mov     ax, [memp]
        shr     ax, 6
        call    pnum
        mov     dx, s_memkb
        call    print
        cmp     word [reps], 1          ; ("; each test 20 times")
        je      .one
        mov     dx, s_reps
        call    print
        mov     ax, [reps]
        call    pnum
        mov     dx, s_times
        call    print
.one:   mov     dx, s_head
        call    print

        mov     byte [tno], 1
        mov     dx, n_write
        call    begin
        mov     bx, t_write
        call    reps_of
        call    finish_kb

        mov     dx, n_read16
        call    begin
        mov     word [rsize], CHUNK
        mov     bx, t_read
        call    reps_of
        call    finish_kb

        mov     dx, n_read512
        call    begin
        mov     word [rsize], 512
        mov     bx, t_read
        call    reps_of
        call    finish_kb

        mov     dx, n_read128
        call    begin
        mov     word [rsize], 128
        mov     bx, t_read
        call    reps_of
        call    finish_kb

        mov     dx, n_random
        call    begin
        mov     bx, t_random
        call    reps_of
        call    finish

        mov     dx, n_dir
        call    begin
        mov     bx, t_dir
        call    reps_of
        call    finish

        mov     dx, n_open
        call    begin
        mov     bx, t_open
        call    reps_of
        call    finish

        mov     dx, n_small
        call    begin
        mov     bx, t_small
        call    reps_of
        call    finish

        call    make_exe                ; (not timed)
        mov     dx, n_exec
        call    begin
        mov     bx, t_exec
        call    reps_of
        call    finish

        mov     dx, n_calls
        call    begin
        mov     bx, t_calls
        call    reps_of
        call    finish

        mov     dx, s_dat               ; clean up
        mov     ah, 41h
        int     21h
        mov     dx, s_exe
        mov     ah, 41h
        int     21h
        mov     dx, s_total
        call    print
        mov     ax, [total]
        call    psecs
        mov     dx, s_crlf
        call    print
        call    ems_bench
        mov     dx, s_crlf              ; (a blank line between runs)
        call    print
        call    savelog
        mov     dx, s_key
        call    print
        mov     ah, 8                   ; wait for a key
        int     21h
        mov     al, [errors]
        mov     ah, 4Ch
        int     21h

; Lodestone?  (its COMSPEC is LCMD.COM) -> ZF
is_lodestone:
        push    ds
        mov     ds, [2Ch]
        xor     si, si
.var:   cmp     byte [si], 0
        je      .no
        cmp     word [si], 'CO'
        jne     .skip
        cmp     word [si+2], 'MS'
        jne     .skip
        cmp     word [si+4], 'PE'
        jne     .skip
.find:  lodsb                           ; LCMD in its value?
        or      al, al
        jz      .no
        cmp     al, 'L'
        jne     .find
        cmp     word [si], 'CM'
        jne     .find
        cmp     byte [si+2], 'D'
        jne     .find
        pop     ds
        cmp     al, al                  ; ZF
        ret
.skip:  lodsb
        or      al, al
        jnz     .skip
        cmp     si, 7F00h
        jb      .var
.no:    pop     ds
        or      sp, sp                  ; NZ
        ret

; "  date 2026-10-05 11:20", CR LF
pdate:  mov     dx, s_date
        call    print
        mov     ah, 2Ah
        int     21h
        push    dx
        mov     ax, cx
        call    pnum
        pop     dx
        push    dx
        mov     dl, '-'
        call    putc
        pop     dx
        push    dx
        mov     al, dh
        call    p2
        mov     dl, '-'
        call    putc
        pop     dx
        mov     al, dl
        call    p2
        mov     dl, ' '
        call    putc
        mov     ah, 2Ch
        int     21h
        push    cx
        mov     al, ch
        call    p2
        mov     dl, ':'
        call    putc
        pop     cx
        mov     al, cl
        call    p2
        mov     dx, s_crlf
        jmp     print
p2:     xor     ah, ah                  ; AL as 2 digits
        cmp     al, 10
        jae     .n
        push    ax
        mov     dl, '0'
        call    putc
        pop     ax
.n:     jmp     pnum

; add what was printed to BENCH.TXT
savelog:
        mov     dx, s_log
        mov     ax, 3D01h               ; there already: on the end of it
        int     21h
        jc      .new
        mov     bx, ax
        mov     ax, 4202h
        xor     cx, cx
        xor     dx, dx
        int     21h
        jmp     .w
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
        mov     dx, s_saved
        jmp     print
.fc:    mov     ah, 3Eh
        int     21h
.fail:  mov     dx, s_nosave
        jmp     print

; ---------------------------------------------------------------------
; timing: begin (DX = name), finish / finish_kb (KB in [kb])
; the test at BX, [reps] times
reps_of:
        mov     cx, [reps]
.l:     push    cx
        push    bx
        call    bx
        pop     bx
        pop     cx
        loop    .l
        ret

begin:  push    dx
        call    print
        pop     dx
        mov     bl, [tno]
        shl     bl, 1
        mov     bh, 0BEh
        xor     ah, ah
        int     1Ah
        mov     [t0], dx
        mov     [t0+2], cx
        ret
stamp:  mov     bl, [tno]
        shl     bl, 1
        inc     bl
        mov     bh, 0BEh
        xor     ah, ah
        int     1Ah
        sub     dx, [t0]
        sbb     cx, [t0+2]
        mov     [ticks], dx
        add     [total], dx
        inc     byte [tno]
        ret
finish: call    stamp
        mov     ax, [ticks]
        call    psecs
        mov     dx, s_crlf
        jmp     print
; DX:AX = DX:AX / BX
div32:  mov     cx, ax
        mov     ax, dx
        xor     dx, dx
        div     bx
        xchg    ax, cx
        div     bx
        mov     dx, cx
        ret
finish_kb:
        call    stamp
        mov     ax, [ticks]
        call    psecs
        mov     dx, s_sp4
        call    print
        ; KB/s = KB * 18207 / ticks / 1000 (32-bit long division)
        mov     ax, [kbn]
        mov     cx, 18207
        mul     cx
        mov     bx, [ticks]
        or      bx, bx
        jnz     .d
        inc     bx
.d:     call    div32
        mov     bx, 1000
        call    div32
        call    pnum
        mov     dx, s_kbs
        jmp     print

; ---------------------------------------------------------------------
t_write:
        mov     dx, s_dat
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      err
        mov     [fh], ax
        mov     di, buf                 ; something other than zeros
        mov     cx, CHUNK
        mov     al, 0A5h
.f:     stosb
        inc     al
        loop    .f
        mov     si, BIGKB / 16
.w:     mov     bx, [fh]
        mov     dx, buf
        mov     cx, CHUNK
        mov     ah, 40h
        int     21h
        jc      err
        dec     si
        jnz     .w
        mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        ret

t_read: mov     dx, s_dat
        mov     ax, 3D00h
        int     21h
        jc      err
        mov     [fh], ax
.r:     mov     bx, [fh]
        mov     dx, buf
        mov     cx, [rsize]
        mov     ah, 3Fh
        int     21h
        jc      err
        or      ax, ax
        jnz     .r
        mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        ret

t_random:
        mov     dx, s_dat
        mov     ax, 3D00h
        int     21h
        jc      err
        mov     [fh], ax
        mov     word [seed], 1234
        mov     si, 64
.r:     mov     ax, [seed]              ; LCG
        mov     cx, 25173
        mul     cx
        add     ax, 13849
        mov     [seed], ax
        mov     dx, ax                  ; offset = (seed & 1FFh) * 512, < 256 KB
        and     dx, 1FFh
        mov     cl, 9
        mov     ax, dx
        shl     ax, cl
        mov     cx, dx
        shr     cx, 7
        mov     dx, ax
        mov     bx, [fh]
        mov     ax, 4200h
        int     21h
        jc      err
        mov     bx, [fh]
        mov     dx, buf
        mov     cx, 512
        mov     ah, 3Fh
        int     21h
        jc      err
        dec     si
        jnz     .r
        mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        ret

t_dir:  mov     si, 10
.l:     mov     dx, s_all
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        jc      .n
.f:     mov     ah, 4Fh
        int     21h
        jnc     .f
.n:     dec     si
        jnz     .l
        ret

t_open: mov     si, 100
.l:     mov     dx, s_dat
        mov     ax, 3D00h
        int     21h
        jc      err
        mov     bx, ax
        mov     ah, 3Eh
        int     21h
        dec     si
        jnz     .l
        ret

t_small:
        mov     byte [fnum], 0
.c:     call    tmpname
        mov     dx, s_tmp
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      err
        mov     bx, ax
        push    bx
        mov     dx, buf
        mov     cx, 1024
        mov     ah, 40h
        int     21h
        pop     bx
        mov     ah, 3Eh
        int     21h
        inc     byte [fnum]
        cmp     byte [fnum], 20
        jb      .c
        mov     byte [fnum], 0
.d:     call    tmpname
        mov     dx, s_tmp
        mov     ah, 41h
        int     21h
        inc     byte [fnum]
        cmp     byte [fnum], 20
        jb      .d
        ret
tmpname:
        mov     al, [fnum]
        xor     ah, ah
        mov     bl, 10
        div     bl
        add     ax, '00'
        mov     [s_tmp + 5], al
        mov     [s_tmp + 6], ah
        ret

; a 120 KB .EXE that exits at once (like loading a big program)
EXESZ   equ 32 + EXEKB * 1024
make_exe:
        mov     di, buf
        mov     cx, CHUNK / 2
        xor     ax, ax
        rep     stosw
        mov     word [buf], 'MZ'
        mov     word [buf + 2], EXESZ % 512
        mov     word [buf + 4], (EXESZ + 511) / 512
        mov     word [buf + 8], 2               ; header paragraphs
        mov     word [buf + 0Ch], 0FFFFh        ; max alloc
        mov     word [buf + 10h], 0FFFEh        ; SP (SS = 0)
        mov     word [buf + 18h], 1Ch
        mov     word [buf + 32], 00B8h          ; mov ax, 4C00h
        mov     word [buf + 34], 0CD4Ch         ; int 21h
        mov     byte [buf + 36], 21h
        mov     dx, s_exe
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      err
        mov     [fh], ax
        mov     si, EXESZ / CHUNK       ; whole chunks, then the rest
.w:     mov     cx, CHUNK
        call    .put
        mov     di, buf                 ; after the first: all zeros
        mov     cx, 40
        xor     ax, ax
        rep     stosb
        dec     si
        jnz     .w
        mov     cx, EXESZ % CHUNK
        call    .put
        mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        ret

.put:   mov     bx, [fh]
        mov     dx, buf
        mov     ah, 40h
        int     21h
        jc      err
        ret

t_exec: mov     byte [fnum], 3
.l:     mov     word [epb], 0
        mov     word [epb + 2], tail
        mov     [epb + 4], cs
        mov     word [epb + 6], fcb
        mov     [epb + 8], cs
        mov     word [epb + 10], fcb
        mov     [epb + 12], cs
        mov     [save_ss], ss
        mov     [save_sp], sp
        push    cs
        pop     es
        mov     dx, s_exe
        mov     bx, epb
        mov     ax, 4B00h
        int     21h
        cli
        mov     ss, [cs:save_ss]
        mov     sp, [cs:save_sp]
        sti
        push    cs
        pop     ds
        push    cs
        pop     es
        cld
        jc      err
        dec     byte [fnum]
        jnz     .l
        ret

t_calls:
        mov     si, 1000
.l:     mov     ah, 30h
        int     21h
        dec     si
        jnz     .l
        ret

; ---------------------------------------------------------------------
; EMS (INT 67h), if a manager is there: 16 pages of a handle of our own
ems_bench:
        mov     ax, 3567h               ; 'EMMXXXX0' at the vector's segment:0Ah?
        int     21h
        mov     di, 0Ah
        mov     si, s_emm
        mov     cx, 8
        repe    cmpsb
        push    cs
        pop     es
        je      .yes
        mov     dx, s_noems
        jmp     print
.yes:   mov     ah, 41h                 ; the page frame
        int     67h
        or      ah, ah
        jnz     .bad
        mov     [frame], bx
        mov     ah, 43h                 ; 16 pages
        mov     bx, 16
        int     67h
        or      ah, ah
        jnz     .bad
        mov     [eh], dx
        mov     dx, s_emshead
        call    print
        mov     dx, n_map
        call    begin
        mov     si, 5000                ; map pages 0 and 1 in turn: 10000 maps
.m:     mov     ax, 4400h
        xor     bx, bx
        mov     dx, [eh]
        int     67h
        mov     ax, 4400h
        mov     bx, 1
        int     67h
        dec     si
        jnz     .m
        call    finish
        mov     word [kbn], 1024
        mov     byte [mv_dst], 1        ; to EMS: conventional -> handle
        mov     dx, n_mvto
        call    begin
        call    .moves
        call    finish_kb
        mov     byte [mv_dst], 0        ; from EMS
        mov     dx, n_mvfrom
        call    begin
        call    .moves
        call    finish_kb
        mov     dx, [eh]
        mov     ah, 45h
        int     67h
        ret
.bad:   mov     al, ah                  ; "EMS error nn"
        xor     ah, ah
        push    ax
        mov     dx, s_emserr
        call    print
        pop     ax
        call    pnum
        mov     dx, s_crlf
        jmp     print
; 64 moves of 16 KB (1 MB) between buf and the handle's pages 0..15
.moves: xor     si, si
.mv:    mov     di, mvs
        mov     ax, CHUNK               ; length
        stosw
        xor     ax, ax
        stosw
        mov     bx, si
        and     bx, 15
        cmp     byte [mv_dst], 0
        jne     .to
        call    .ems                    ; from EMS ...
        call    .conv                   ; ... to buf
        jmp     short .go
.to:    call    .conv
        call    .ems
.go:    push    si
        mov     si, mvs
        mov     ax, 5700h
        int     67h
        pop     si
        or      ah, ah
        jnz     .e
        inc     si
        cmp     si, 64
        jb      .mv
        ret
.e:     mov     al, ah
        xor     ah, ah
        jmp     err
.conv:  xor     al, al                  ; conventional: buf
        stosb
        xor     ax, ax
        stosw
        mov     ax, buf
        stosw
        mov     ax, cs
        stosw
        ret
.ems:   mov     al, 1                   ; EMS: the handle, offset 0, page BX
        stosb
        mov     ax, [eh]
        stosw
        xor     ax, ax
        stosw
        mov     ax, bx
        stosw
        ret

err:    inc     byte [errors]
        push    ax
        mov     dx, s_err
        call    print
        pop     ax
        call    pnum
        mov     dx, s_crlf
        jmp     print

; ---------------------------------------------------------------------
; print the $-string at DX, and keep a copy for BENCH.TXT
print:  push    si
        push    di
        cld
        mov     si, dx
        mov     di, [logpos]
.c:     lodsb
        cmp     al, '$'
        je      .e
        cmp     di, LOGMAX
        jae     .c
        mov     [logbuf+di], al
        inc     di
        jmp     .c
.e:     mov     [logpos], di
        pop     di
        pop     si
        mov     ah, 9
        int     21h
        ret
putc:   push    di                      ; DL
        mov     di, [logpos]
        cmp     di, LOGMAX
        jae     .s
        mov     [logbuf+di], dl
        inc     word [logpos]
.s:     pop     di
        mov     ah, 2
        int     21h
        ret
; AX unsigned
pnum:   push    bx
        push    cx
        push    dx
        mov     bx, 10
        xor     cx, cx
.d:     xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .d
.p:     pop     dx
        add     dl, '0'
        call    putc
        loop    .p
        pop     dx
        pop     cx
        pop     bx
        ret
; ticks AX -> "  12.34 s" (right-aligned)
psecs:  mov     cx, 5493                ; hundredths = ticks * 5.4925
        mul     cx
        mov     cx, 1000
        div     cx                      ; AX = hundredths
        xor     dx, dx
        mov     cx, 100
        div     cx                      ; AX = seconds, DX = hundredths
        push    dx
        cmp     ax, 100
        jae     .a
        push    ax
        mov     dl, ' '
        call    putc
        pop     ax
        cmp     ax, 10
        jae     .a
        push    ax
        mov     dl, ' '
        call    putc
        pop     ax
.a:     call    pnum
        mov     dl, '.'
        call    putc
        pop     ax
        cmp     ax, 10
        jae     .b
        push    ax
        mov     dl, '0'
        call    putc
        pop     ax
.b:     call    pnum
        mov     dx, s_secs
        jmp     print

s_title     db 'BENCH 1.4 - DOS file system benchmark on $'
s_freedos   db 'FreeDOS (DOS $'
s_emm       db 'EMMXXXX0'
s_noems     db 'No EMS (INT 67h)', 13, 10, '$'
s_emshead   db 13, 10, 'EMS (INT 67h), not in the total:', 13, 10, '$'
s_emserr    db 'EMS error $'
n_map       db 'Map a page x 10000                  $'
n_mvto      db 'Move 1 MB to EMS (57h), 16 KB each  $'
n_mvfrom    db 'Move 1 MB from EMS (57h)            $'
s_lodestone    db 'Lodestone (DOS $'
s_msdos     db 'MS-DOS (DOS $'
s_close     db ')', 13, 10, '$'
s_date      db 'Run $'
s_mem       db 'Memory for programs: $'
s_memkb     db ' KB$'
s_reps      db '; each test $'
s_times     db ' times (the times for all of them, KB/s for one)$'
s_head      db 13, 10, 13, 10, '$'
n_write     db 'Write 256 KB, 16 KB at a time       $'
n_read16    db 'Read 256 KB, 16 KB at a time        $'
n_read512   db 'Read 256 KB, 512 bytes at a time    $'
n_read128   db 'Read 256 KB, 128 bytes at a time    $'
n_random    db '64 random 512-byte reads            $'
n_dir       db 'Directory listing x 10              $'
n_open      db 'Open + close x 100                  $'
n_small     db '20 x create 1 KB file, then delete  $'
n_exec      db 'Load + run a 120 KB .EXE x 3        $'
n_calls     db 'INT 21h calls x 1000                $'
s_total     db 13, 10, 'Total                               $'
s_secs      db ' s$'
s_sp4       db '   $'
s_kbs       db ' KB/s', 13, 10, '$'
s_crlf      db 13, 10, '$'
s_log       db 'BENCH.TXT', 0
s_saved     db 'Results added to BENCH.TXT', 13, 10, '$'
s_nosave    db 'Could not write BENCH.TXT', 13, 10, '$'
s_key       db 'Press any key$'
s_err       db '  error $'
s_dat       db 'BENCH.DAT', 0
s_exe       db 'BENCHX.EXE', 0
s_tmp       db 'BENCH00.TMP', 0
s_all       db '*.*', 0
tail        db 0, 13
fcb         db 0, '           ', 0, 0, 0, 0

section .bss
bss_start:
tno         resb 1
errors      resb 1
fnum        resb 1
fh          resw 1
memp        resw 1
rsize       resw 1
seed        resw 1
t0          resw 2
ticks       resw 1
total       resw 1
save_ss     resw 1
save_sp     resw 1
epb         resw 7
logpos      resw 1
kbn         resw 1
reps        resw 1
frame       resw 1
eh          resw 1
mv_dst      resb 1
mvs         resb 18
logbuf      resb LOGMAX
buf         resb CHUNK
            resb 512
stack_top:
prog_end:
