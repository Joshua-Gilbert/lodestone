; MDTEST.COM - checks of M:, Grid-OS's temporary disk in EMS, for the
; emulator tests (tests/test_kernel.py, t_mdisk) and for the 1520.
;   MDTEST /Q        M:'s setting, size, the most it can have, its handle
;   MDTEST /S n      M: at n KB (0 off, ALL all free)
;   MDTEST /O n      the same with a file on M: open (refused: 80h)
;   MDTEST /W        file I/O on M: with this program's own EMS pages in
;                    all four windows: pieces across M:'s 16 KB pages, a
;                    buffer in the frame (each half), then every window and
;                    page of ours as it was
;   MDTEST /F        M: filled to the last cluster, read back, emptied
;   MDTEST /H n      n EMS pages held by a resident program (stays: TSR)
;   MDTEST /K        M:\KEEP.TMP kept open by a resident program (TSR)
;   MDTEST /C h      close EMS handle h (as a program might, by mistake,
;                    M:'s) -> "closed XX", 45h's answer
;   MDTEST /X name   EXEC name (INT 21h 4B00h straight, as the shell
;                    doesn't: it looks first) -> "exec XX", the error code
; Prints one line per check ("ok" or "FAIL"); the exit code is the number
; of failures (255: no M:).
cpu 286
org 100h

FRAME   equ 0E000h
PORT    equ 0258h
BIG     equ 72 * 1024           ; /W: the file's size

start:  mov     sp, stack_top
        cld
        mov     bx, 1000h               ; (64 KB: ours)
        mov     ah, 4Ah
        int     21h
        mov     si, 81h
.a:     lodsb
        cmp     al, 13
        je      usage
        cmp     al, '/'
        jne     .a
        lodsb
        and     al, 0DFh
        mov     [op], al
        cmp     al, 'X'
        je      do_x
        call    number                  ; (n, if any)
        mov     [arg], ax
        mov     al, [op]
        cmp     al, 'Q'
        je      do_q
        cmp     al, 'S'
        je      do_s
        cmp     al, 'O'
        je      do_o
        cmp     al, 'W'
        je      do_w
        cmp     al, 'F'
        je      do_f
        cmp     al, 'H'
        je      do_h
        cmp     al, 'K'
        je      do_k
        cmp     al, 'C'
        je      do_c
usage:  mov     si, s_usage
        call    pr
        mov     ax, 4CFFh
        int     21h

; the number after the switch -> AX ("ALL": FFFFh; none: 0)
number: lodsb
        cmp     al, ' '
        je      number
        dec     si
        mov     ax, [si]
        and     ax, 0DFDFh
        cmp     ax, 'AL'
        jne     .n
        mov     ax, 0FFFFh
        ret
.n:     xor     bx, bx
.d:     lodsb
        sub     al, '0'
        cmp     al, 9
        ja      .x
        cbw
        imul    bx, bx, 10
        add     bx, ax
        jmp     .d
.x:     xchg    ax, bx
        ret

; /C h: INT 67h 45h on handle h -> "closed XX"
do_c:   mov     dx, [arg]
        mov     ah, 45h
        int     67h
        mov     al, ah
        xor     ah, ah
        push    ax
        mov     si, s_closed
        call    pr
        pop     ax
        call    phex
        call    crlf
        jmp     done

; /X name: INT 21h 4B00h on it -> "exec XX" (00: it ran)
do_x:   lodsb
        cmp     al, ' '
        je      do_x
        dec     si
        mov     dx, si
.e:     lodsb
        cmp     al, ' '
        ja      .e
        mov     byte [si-1], 0
        mov     word [epb+2], s_tail
        mov     word [epb+6], 5Ch
        mov     word [epb+10], 6Ch
        mov     [epb+4], cs
        mov     [epb+8], cs
        mov     [epb+12], cs
        mov     bx, epb
        mov     ax, 4B00h
        int     21h
        cli                             ; (as DOS 2 left them: the stack is
        push    cs                      ;  ours again, nothing on it needed)
        pop     ss
        mov     sp, stack_top
        sti
        push    cs
        pop     ds
        jc      .r
        xor     ax, ax
.r:     push    ax
        mov     si, s_exec
        call    pr
        pop     ax
        call    phex
        call    crlf
        jmp     done

; INT 67h 5Bh 'M', BL = op -> AH, BX, CX, DX, SI
mdcall: mov     ax, 5B4Dh
        int     67h
        ret

do_q:   xor     bl, bl
        call    mdcall
        or      ah, ah
        jnz     nomd
        push    si
        push    dx
        push    cx
        mov     si, s_set
        call    pr
        mov     ax, bx
        call    pdec
        mov     si, s_size
        call    pr
        pop     ax
        call    pdec
        mov     si, s_max
        call    pr
        pop     ax
        call    pdec
        mov     si, s_hnd
        call    pr
        pop     ax
        call    pdec
        call    crlf
        jmp     done
nomd:   mov     al, ah
        xor     ah, ah
        push    ax
        mov     si, s_nomd
        call    pr
        pop     ax
        call    phex
        call    crlf
        mov     ax, 4CFFh
        int     21h

do_s:   mov     cx, [arg]
        mov     bl, 1
        call    mdcall
        cmp     ah, 0A4h
        je      nomd
report: push    cx
        push    ax
        mov     si, s_res
        call    pr
        pop     ax
        mov     al, ah
        xor     ah, ah
        call    phex
        mov     si, s_size
        call    pr
        pop     ax
        call    pdec
        call    crlf
        jmp     done

do_o:   mov     dx, s_open              ; a file on M: open
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .e
        mov     [fh], ax
        mov     cx, [arg]
        mov     bl, 1
        call    mdcall
        push    cx
        push    ax
        mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        mov     dx, s_open
        mov     ah, 41h
        int     21h
        pop     ax
        pop     cx
        jmp     report
.e:     mov     si, s_nocreate
        call    pr
        mov     ax, 4C01h
        int     21h

; ---------------------------------------------------------------------
;  /W
do_w:   mov     bx, 4                   ; four pages of our own, one in each
        mov     ah, 43h                 ;  window, each filled with its own
        int     67h                     ;  pattern
        or      ah, ah
        jnz     .noems
        mov     [hnd], dx
        xor     bx, bx
.m:     mov     al, bl
        mov     dx, [hnd]
        mov     ah, 44h
        int     67h
        or      ah, ah
        jnz     .noems
        mov     al, bl
        call    winfill
        inc     bx
        cmp     bx, 4
        jb      .m
        call    getregs
        mov     si, regs0
        call    savregs
        ; a file of BIG bytes in pieces of odd sizes from conventional memory
        mov     dx, s_big
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .ferr
        mov     [fh], ax
        mov     word [pos], 0
        mov     word [pos+2], 0
        mov     si, sizes
.wl:    lodsw
        or      ax, ax
        jz      .wd
        push    si
        mov     cx, ax
        call    bpat                    ; buf: the file's bytes from pos
        mov     dx, buf
        mov     bx, [fh]
        mov     ah, 40h
        int     21h
        pop     si
        jc      .ferr
        cmp     ax, cx
        jne     .ferr
        add     [pos], cx
        adc     word [pos+2], 0
        jmp     .wl
.wd:    mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        mov     byte [wmask], 1111b
        mov     si, n_wwin
        call    chkwins
        ; read back, other pieces
        mov     dx, s_big
        mov     ax, 3D00h
        int     21h
        jc      .ferr
        mov     [fh], ax
        mov     word [pos], 0
        mov     word [pos+2], 0
        mov     byte [bad], 0
        mov     si, rsizes
.rl:    lodsw
        or      ax, ax
        jz      .rd
        push    si
        mov     cx, ax
        mov     dx, buf2
        mov     bx, [fh]
        mov     ah, 3Fh
        int     21h
        pop     si
        jc      .ferr
        cmp     ax, cx
        jne     .ferr
        push    si
        mov     si, buf2
        call    bcmp
        pop     si
        add     [pos], cx
        adc     word [pos+2], 0
        jmp     .rl
.rd:    mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        mov     si, n_wdata
        call    result
        mov     si, n_rwin
        call    chkwins
        ; a buffer in the frame: written from window 1 (ours), read into
        ; windows 2 and 3 across their boundary (M: then uses window 0),
        ; then into window 0 (M: uses window 3)
        mov     ax, FRAME + 400h
        mov     es, ax
        xor     di, di
        mov     cx, 4000h
        mov     al, 5Ah
.ff:    stosb
        inc     al
        loop    .ff
        push    ds
        pop     es
        mov     dx, s_frm
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .ferr
        mov     bx, ax
        push    ds
        mov     ax, FRAME + 400h
        mov     ds, ax
        mov     dx, 100h                ; (5Ah, 5Bh, ... from there too)
        mov     cx, 12000
        mov     ah, 40h
        int     21h
        pop     ds
        jc      .ferr
        mov     ah, 3Eh
        int     21h
        mov     byte [wmask], 1101b
        mov     si, n_fwwin
        call    chkwins
        mov     dx, s_frm
        mov     ax, 3D00h
        int     21h
        jc      .ferr
        mov     bx, ax
        push    ds
        mov     ax, FRAME + 800h
        mov     ds, ax
        mov     dx, 2000h               ; E800:2000 + 12000: into window 3
        mov     cx, 12000
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .ferr
        mov     ah, 3Eh
        int     21h
        mov     byte [bad], 0
        push    ds
        mov     ax, FRAME + 800h
        mov     ds, ax
        mov     si, 2000h
        mov     cx, 12000
        call    fcheck
        pop     ds
        mov     si, n_fdata
        call    result
        mov     byte [wmask], 0001b     ; (window 0: M:'s for the time)
        mov     si, n_f2win
        call    chkwins
        mov     dx, s_frm
        mov     ax, 3D00h
        int     21h
        jc      .ferr
        mov     bx, ax
        push    ds
        mov     ax, FRAME
        mov     ds, ax
        xor     dx, dx
        mov     cx, 12000
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      .ferr
        mov     ah, 3Eh
        int     21h
        mov     byte [bad], 0
        push    ds
        mov     ax, FRAME
        mov     ds, ax
        xor     si, si
        mov     cx, 12000
        call    fcheck
        pop     ds
        mov     si, n_f0data
        call    result
        mov     byte [bad], 0           ; window 1 untouched
        push    ds
        mov     ax, FRAME + 400h
        mov     ds, ax
        xor     si, si
        mov     cx, 4000h
        call    fcheck
        pop     ds
        mov     si, n_f0win
        call    chkwins.x0
        mov     dx, s_big
        mov     ah, 41h
        int     21h
        mov     dx, s_frm
        mov     ah, 41h
        int     21h
        mov     dx, [hnd]
        mov     ah, 45h
        int     67h
        jmp     done
.noems: mov     si, s_noems
        call    pr
        mov     ax, 4CFFh
        int     21h
.ferr:  mov     si, n_file
        mov     byte [bad], 1
        call    result
        jmp     done

; window AL filled with its own pattern (our page AL): word i is
; (A0h + AL) * 256 + AL + i * 0101h
winfill:
        push    ax
        push    cx
        push    di
        push    es
        mov     cl, al
        mov     ah, al                  ; ES = E000h + 400h * window
        shl     ah, 2
        add     ah, FRAME >> 8
        xor     al, al
        mov     es, ax
        xor     di, di
        mov     al, cl
        mov     ah, cl
        add     ah, 0A0h
        mov     cx, 2000h
.l:     stosw
        add     ax, 0101h
        loop    .l
        pop     es
        pop     di
        pop     cx
        pop     ax
        ret

; the four page registers -> regs
getregs:
        push    ax
        push    dx
        push    di
        mov     di, regs
        mov     dx, PORT
.l:     in      al, dx
        mov     [di], al
        inc     di
        add     dh, 40h
        jnc     .l
        pop     di
        pop     dx
        pop     ax
        ret
savregs:
        push    si
        mov     ax, [regs]
        mov     [si], ax
        mov     ax, [regs+2]
        mov     [si+2], ax
        pop     si
        ret

; check SI: the registers as at the start, and the pattern of each window
; whose bit is set in [wmask]
chkwins:
        push    si
        call    getregs
        mov     byte [bad], 0
        mov     ax, [regs]
        cmp     ax, [regs0]
        jne     .b
        mov     ax, [regs+2]
        cmp     ax, [regs0+2]
        jne     .b
        xor     bx, bx                  ; each window's pattern
.w:     mov     al, [wmask]
        mov     cl, bl
        shr     al, cl
        test    al, 1
        jz      .nw
        push    ds
        mov     ah, bl
        shl     ah, 2
        add     ah, FRAME >> 8
        xor     al, al
        mov     ds, ax
        xor     si, si
        mov     al, bl
        mov     ah, bl
        add     ah, 0A0h
        mov     cx, 2000h
.c:     cmp     [si], ax
        jne     .bw
        add     si, 2
        add     ax, 0101h
        loop    .c
        pop     ds
.nw:    inc     bx
        cmp     bx, 4
        jb      .w
        jmp     .x
.bw:    pop     ds
.b:     mov     byte [bad], 1
.x:     pop     si
        jmp     result
.x0:    push    si                      ; (the registers only, on [bad])
        call    getregs
        mov     ax, [regs]
        cmp     ax, [regs0]
        jne     .b
        mov     ax, [regs+2]
        cmp     ax, [regs0+2]
        jne     .b
        jmp     .x

; [bad] = 1 if the CX bytes at DS:SI aren't 5Ah, 5Bh, ... (the frame file)
fcheck: mov     ah, 5Ah
.l:     lodsb
        cmp     al, ah
        je      .n
        mov     byte [cs:bad], 1
.n:     inc     ah
        loop    .l
        ret

; buf: CX bytes of the file from pos (byte = low byte of pos * 7 + high)
bpat:   push    ax
        push    bx
        push    cx
        push    di
        mov     di, buf
        mov     ax, [pos]
        mov     bx, [pos+2]
.l:     push    ax
        imul    ax, ax, 7
        add     al, ah
        add     al, bl
        stosb
        pop     ax
        add     ax, 1
        adc     bx, 0
        loop    .l
        pop     di
        pop     cx
        pop     bx
        pop     ax
        ret
; SI: CX bytes of the file from pos?  [bad] = 1 if not
bcmp:   push    ax
        push    bx
        push    cx
        mov     ax, [pos]
        mov     bx, [pos+2]
.l:     push    ax
        imul    ax, ax, 7
        add     al, ah
        add     al, bl
        cmp     al, [si]
        pop     ax
        je      .n
        mov     byte [bad], 1
.n:     inc     si
        add     ax, 1
        adc     bx, 0
        loop    .l
        pop     cx
        pop     bx
        pop     ax
        ret

; ---------------------------------------------------------------------
;  /H n: n pages of EMS held, and resident (a program that keeps EMS)
do_h:   mov     bx, [arg]
        mov     ah, 43h
        int     67h
        or      ah, ah
        jnz     nomd
        mov     si, s_held
        call    pr
        mov     dx, 20h                 ; (512 bytes: the PSP and a little)
        mov     ax, 3100h
        int     21h

; /K: M:\KEEP.TMP open, and resident
do_k:   mov     dx, s_keep
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      nomd
        mov     si, s_held
        call    pr
        mov     dx, 20h
        mov     ax, 3100h
        int     21h

; ---------------------------------------------------------------------
;  /F: M: filled to the last cluster, read back, emptied
do_f:   mov     ah, 36h
        mov     dl, 13
        int     21h
        cmp     ax, 0FFFFh
        je      nomd
        mul     cx                      ; bytes a cluster
        mul     bx                      ; DX:AX free bytes
        mov     [free], ax
        mov     [free+2], dx
        mov     dx, s_fill
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jc      .e
        mov     [fh], ax
        mov     word [pos], 0
        mov     word [pos+2], 0
.wl:    mov     cx, 15000
        call    bpat
        mov     dx, buf
        mov     bx, [fh]
        mov     ah, 40h
        int     21h
        jc      .e
        add     [pos], ax
        adc     word [pos+2], 0
        cmp     ax, cx
        je      .wl
        mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        mov     byte [bad], 0           ; all of the free space taken
        mov     ax, [pos]
        cmp     ax, [free]
        jne     .b1
        mov     ax, [pos+2]
        cmp     ax, [free+2]
        je      .g1
.b1:    mov     byte [bad], 1
.g1:    mov     si, n_full
        call    result
        mov     ah, 36h
        mov     dl, 13
        int     21h
        mov     byte [bad], 0
        or      bx, bx
        jz      .g2
        mov     byte [bad], 1
.g2:    mov     si, n_none
        call    result
        mov     dx, s_fill              ; read back
        mov     ax, 3D00h
        int     21h
        jc      .e
        mov     [fh], ax
        mov     ax, [pos]
        mov     [total], ax
        mov     ax, [pos+2]
        mov     [total+2], ax
        mov     word [pos], 0
        mov     word [pos+2], 0
        mov     byte [bad], 0
.rl:    mov     cx, 15000
        mov     dx, buf2
        mov     bx, [fh]
        mov     ah, 3Fh
        int     21h
        jc      .e
        or      ax, ax
        jz      .rd
        mov     cx, ax
        mov     si, buf2
        call    bcmp
        add     [pos], cx
        adc     word [pos+2], 0
        jmp     .rl
.rd:    mov     bx, [fh]
        mov     ah, 3Eh
        int     21h
        mov     ax, [pos]
        cmp     ax, [total]
        jne     .b3
        mov     ax, [pos+2]
        cmp     ax, [total+2]
        je      .g3
.b3:    mov     byte [bad], 1
.g3:    mov     si, n_fullrd
        call    result
        mov     dx, s_fill
        mov     ah, 41h
        int     21h
        mov     ah, 36h
        mov     dl, 13
        int     21h
        mul     cx
        mul     bx
        mov     byte [bad], 0
        cmp     ax, [free]
        jne     .b4
        cmp     dx, [free+2]
        je      .g4
.b4:    mov     byte [bad], 1
.g4:    mov     si, n_freed
        call    result
        jmp     done
.e:     mov     si, n_file
        mov     byte [bad], 1
        call    result
        jmp     done

; ---------------------------------------------------------------------
; [bad] -> "ok"/"FAIL" and the name at SI
result: push    si
        mov     si, s_ok
        cmp     byte [bad], 0
        je      .p
        inc     byte [nfail]
        mov     si, s_fail
.p:     call    pr
        pop     si
        call    pr
        jmp     crlf

done:   mov     si, s_end
        call    pr
        mov     al, [nfail]
        mov     ah, 4Ch
        int     21h

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
        mov     bx, 1
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
pdec:   push    si
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
        mov     cx, 2
        xchg    al, ah
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

sizes   dw 5000, 16384, 20000, 511, 513, 9999, 3000, 8325, 10000, 0     ; = 73728
rsizes  dw 16384, 1, 2, 30000, 7000, 341, 20000, 0                      ; = 73728
s_usage db 'MDTEST /Q | /S n | /O n | /W | /F | /H n | /K | /C h | /X name', 13, 10, 0
s_exec  db 'exec ', 0
s_closed db 'closed ', 0
s_tail  db 0, 13
epb     dw 0, 0, 0, 0, 0, 0, 0
s_keep  db 'M:\KEEP.TMP', 0
s_held  db 'held, resident', 13, 10, 0
s_set   db 'M: setting ', 0
s_size  db ' size ', 0
s_max   db ' max ', 0
s_hnd   db ' handle ', 0
s_res   db 'result ', 0
s_nomd  db 'no M: here, INT 67h 5Bh says ', 0
s_noems db 'no EMS', 13, 10, 0
s_nocreate db "can't make M:\OPEN.TMP", 13, 10, 0
s_open  db 'M:\OPEN.TMP', 0
s_big   db 'M:\BIG.DAT', 0
s_frm   db 'M:\FRAME.DAT', 0
s_fill  db 'M:\FILL.DAT', 0
s_ok    db 'ok    ', 0
s_fail  db 'FAIL  ', 0
s_end   db 'MDTEST done', 13, 10, 0
s_crlf  db 13, 10, 0
n_wwin  db 'write: our four windows and pages as they were', 0
n_wdata db 'read back: 72 KB in pieces across M:', 27h, 's pages', 0
n_rwin  db 'read: our four windows and pages as they were', 0
n_fwwin db 'written from a buffer in window 1: the windows as they were', 0
n_fdata db 'read into windows 2-3 (across them): the data', 0
n_f2win db 'and the windows as they were', 0
n_f0data db 'read into window 0: the data', 0
n_f0win db 'and window 1 untouched, the registers as they were', 0
n_file  db 'file calls on M:', 0
n_full  db 'M: filled: every free byte taken', 0
n_none  db 'then 0 clusters free', 0
n_fullrd db 'read back whole', 0
n_freed db 'deleted: all of it free again', 0

section .bss
op      resb 1
bad     resb 1
nfail   resb 1
        resb 1
arg     resw 1
fh      resw 1
hnd     resw 1
pos     resw 2
free    resw 2
total   resw 2
regs    resb 4
regs0   resb 4
wmask   resb 1
numbuf  resb 8
buf     resb 20480
buf2    resb 30720
        resb 512
stack_top:
