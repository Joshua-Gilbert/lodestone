; TESTDOS.COM - DOS API checks for the Lodestone kernel.
; Run it from the Executive (or any DOS) on a scratch floppy: it creates,
; reads, seeks, truncates, renames and deletes files, makes and removes
; directories (one big enough to grow past a cluster), duplicates handles,
; allocates memory, runs a child it writes itself, and so on.  One line per
; test on stdout, then a total; the exit code is the number of failures.
cpu 286
org 100h

start:  mov     sp, stack_top
        cld
        mov     di, bss_start           ; DOS doesn't clear memory for us
        mov     cx, stack_top - bss_start
        xor     al, al
        rep     stosb
        mov     bx, 1000h               ; keep 64 KB, give the rest back
        mov     ah, 4Ah
        int     21h
        mov     si, s_hello
        call    pr
        mov     si, tests
.next:  lodsw
        or      ax, ax
        jz      .done
        mov     bx, ax
        lodsw
        push    si
        mov     [tname], ax
        mov     byte [step], 0
        mov     [tsp], sp
        call    bx
        jc      .bad
        inc     word [npass]
        mov     si, s_ok
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
        call    cleanup
.n:     pop     si
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
        mov     al, [nfail]
        mov     ah, 4Ch
        int     21h

; a failed check: back to the runner with CF and AX
fail:   mov     sp, [tsp]
        sub     sp, 2
        stc
        ret
; a call that should have failed didn't
failnc: mov     ax, 0FFFFh
        jmp     fail

; close stray handles 5..19 after a failure
cleanup:
        mov     bx, 5
.c:     mov     ah, 3Eh
        int     21h
        inc     bx
        cmp     bx, 20
        jb      .c
        ret

%macro STEP 1
        mov     byte [step], %1
%endmacro
%macro DOS 1
        mov     ah, %1
        int     21h
        jc      fail
%endmacro
; the call must fail with error %1
%macro DOSERR 2
        mov     ah, %1
        int     21h
        jnc     failnc
        cmp     ax, %2
        jne     fail
%endmacro
%macro EQ 2
        cmp     %1, %2
        je      %%ok
        mov     ax, %1
        jmp     fail
%%ok:
%endmacro

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
pdec:   push    si                      ; AX unsigned
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
        pop     si
        ret
phex:   push    si
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
        pop     si
        ret

; ---------------------------------------------------------------------
; the test pattern: byte at file offset O = lo(O) xor (hi(O)*3 + 1)
; fill ES:DI with CX bytes from offset AX
pat_fill:
        push    ax
        push    cx
        push    dx
.l:     mov     dl, ah
        mov     dh, ah
        shl     dl, 1
        add     dl, dh
        inc     dl
        xor     dl, al
        mov     [es:di], dl
        inc     di
        inc     ax
        loop    .l
        pop     dx
        pop     cx
        pop     ax
        ret
; compare DS:SI (CX bytes) with the pattern from offset AX: CF on mismatch
pat_check:
        push    ax
        push    cx
        push    dx
        push    si
        jcxz    .ok
.l:     mov     dl, ah
        mov     dh, ah
        shl     dl, 1
        add     dl, dh
        inc     dl
        xor     dl, al
        cmp     [si], dl
        jne     .bad
        inc     si
        inc     ax
        loop    .l
.ok:    clc
        jmp     .x
.bad:   stc
.x:     pop     si
        pop     dx
        pop     cx
        pop     ax
        ret

; size of the file named at DX (find first) -> DX:AX
fsize:  push    cx
        mov     cx, 0
        mov     ah, 4Eh
        int     21h
        pop     cx
        jc      .x
        mov     ax, [80h + 1Ah]
        mov     dx, [80h + 1Ch]
.x:     ret

; ---------------------------------------------------------------------
t_ver:  STEP 1
        mov     ax, 3000h
        int     21h
        EQ      ax, 1E03h
        STEP 2
        mov     ah, 19h
        int     21h
        xor     ah, ah
        EQ      ax, 0
        STEP 3
        mov     ah, 2Ah
        int     21h
        cmp     cx, 1980
        jb      fail
        STEP 4
        mov     ax, 3300h
        int     21h
        clc
        ret

t_create:
        STEP 1
        mov     dx, f_t1
        xor     cx, cx
        DOS     3Ch
        mov     [h1], ax
        STEP 2
        push    ds
        pop     es
        mov     di, buf
        mov     cx, 1000
        xor     ax, ax
        call    pat_fill
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 1000
        DOS     40h
        EQ      ax, 1000
        STEP 3
        mov     bx, [h1]
        DOS     3Eh
        STEP 4
        mov     dx, f_t1
        call    fsize
        jc      fail
        EQ      ax, 1000
        clc
        ret

t_read: STEP 1
        mov     dx, f_t1
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     [h1], ax
        STEP 2
        call    clrbuf
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 2000
        DOS     3Fh
        EQ      ax, 1000
        STEP 3
        mov     si, buf
        mov     cx, 1000
        xor     ax, ax
        call    pat_check
        jc      fail
        STEP 4
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 100
        DOS     3Fh
        EQ      ax, 0
        mov     bx, [h1]
        DOS     3Eh
        clc
        ret

clrbuf: push    es
        push    ds
        pop     es
        mov     di, buf
        mov     cx, BUFSZ / 2
        xor     ax, ax
        rep     stosw
        pop     es
        ret

t_seek: STEP 1
        mov     dx, f_t1
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     [h1], ax
        STEP 2
        mov     bx, ax
        xor     cx, cx
        mov     dx, 500
        mov     ax, 4200h
        int     21h
        jc      fail
        EQ      ax, 500
        STEP 3
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 10
        DOS     3Fh
        EQ      ax, 10
        mov     si, buf
        mov     ax, 500
        mov     cx, 10
        call    pat_check
        jc      fail
        STEP 4
        mov     bx, [h1]
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        jc      fail
        EQ      ax, 1000
        EQ      dx, 0
        STEP 5
        mov     bx, [h1]
        mov     cx, 0FFFFh
        mov     dx, -10
        mov     ax, 4201h
        int     21h
        jc      fail
        EQ      ax, 990
        STEP 6
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 100
        DOS     3Fh
        EQ      ax, 10
        mov     bx, [h1]
        DOS     3Eh
        clc
        ret

; 40 KB in 4 KB writes, read back in 1531-byte pieces
BIGSZ   equ 40960
t_big:  STEP 1
        mov     dx, f_big
        xor     cx, cx
        DOS     3Ch
        mov     [h1], ax
        mov     word [off], 0
.w:     STEP 2
        push    ds
        pop     es
        mov     di, buf
        mov     cx, 4096
        mov     ax, [off]
        call    pat_fill
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 4096
        DOS     40h
        EQ      ax, 4096
        add     word [off], 4096
        cmp     word [off], BIGSZ
        jb      .w
        STEP 3
        mov     bx, [h1]
        DOS     3Eh
        STEP 4
        mov     dx, f_big
        call    fsize
        jc      fail
        EQ      ax, BIGSZ
        STEP 5
        mov     dx, f_big
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     [h1], ax
        mov     word [off], 0
.r:     STEP 6
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 1531
        DOS     3Fh
        or      ax, ax
        jz      .eof
        mov     cx, ax
        mov     si, buf
        mov     ax, [off]
        STEP 7
        call    pat_check
        jc      fail
        add     [off], cx
        jmp     .r
.eof:   STEP 8
        EQ      word [off], BIGSZ
        mov     bx, [h1]
        DOS     3Eh
        clc
        ret

; 32 KB in one read into a block of its own (DMA boundaries, bounce)
t_bigread:
        STEP 1
        mov     bx, 800h
        DOS     48h
        mov     [mseg], ax
        STEP 2
        mov     dx, f_big
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     [h1], ax
        STEP 3
        push    ds
        mov     bx, [h1]
        mov     ds, [mseg]
        xor     dx, dx
        mov     cx, 8000h
        mov     ah, 3Fh
        int     21h
        pop     ds
        jc      fail
        EQ      ax, 8000h
        STEP 4
        push    ds
        mov     ds, [mseg]
        xor     si, si
        mov     cx, 8000h
        xor     ax, ax
        call    pat_check
        pop     ds
        jc      fail
        mov     bx, [h1]
        DOS     3Eh
        STEP 5
        mov     es, [mseg]
        DOS     49h
        push    ds
        pop     es
        clc
        ret

t_append:
        STEP 1
        mov     dx, f_t1
        mov     ax, 3D02h
        int     21h
        jc      fail
        mov     [h1], ax
        STEP 2
        mov     bx, ax
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h
        int     21h
        jc      fail
        STEP 3
        push    ds
        pop     es
        mov     di, buf
        mov     cx, 100
        mov     ax, 1000
        call    pat_fill
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 100
        DOS     40h
        EQ      ax, 100
        mov     bx, [h1]
        DOS     3Eh
        STEP 4
        mov     dx, f_t1
        call    fsize
        EQ      ax, 1100
        STEP 5
        mov     dx, f_t1
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     [h1], ax
        mov     bx, ax
        mov     dx, buf
        mov     cx, 2000
        DOS     3Fh
        EQ      ax, 1100
        mov     si, buf
        mov     cx, 1100
        xor     ax, ax
        call    pat_check
        jc      fail
        mov     bx, [h1]
        DOS     3Eh
        clc
        ret

t_trunc:
        STEP 1
        mov     dx, f_t1
        mov     ax, 3D02h
        int     21h
        jc      fail
        mov     [h1], ax
        mov     bx, ax
        xor     cx, cx
        mov     dx, 600
        mov     ax, 4200h
        int     21h
        jc      fail
        STEP 2
        mov     bx, [h1]
        xor     cx, cx
        mov     dx, buf
        DOS     40h
        EQ      ax, 0
        mov     bx, [h1]
        DOS     3Eh
        STEP 3
        mov     dx, f_t1
        call    fsize
        EQ      ax, 600
        clc
        ret

t_rename:
        STEP 1
        push    ds
        pop     es
        mov     dx, f_t1
        mov     di, f_t2
        DOS     56h
        STEP 2
        mov     dx, f_t1
        mov     ax, 3D00h
        int     21h
        jnc     failnc
        EQ      ax, 2
        STEP 3
        mov     dx, f_t2
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     bx, ax
        DOS     3Eh
        STEP 4                          ; onto an existing name: refused
        mov     dx, f_t2
        mov     di, f_big
        mov     ah, 56h
        int     21h
        jnc     failnc
        EQ      ax, 5
        STEP 5                          ; onto "." or ".." in the root:
        mov     dx, f_t2                ;  refused (it made an entry "."
        mov     di, d_dot               ;  nothing could name)
        DOSERR  56h, 5
        mov     dx, f_t2
        mov     di, d_up
        DOSERR  56h, 5
        mov     dx, f_t2                ; still there
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     bx, ax
        DOS     3Eh
        clc
        ret

t_attr: STEP 1
        mov     dx, f_t2
        mov     cx, 1
        mov     ax, 4301h
        int     21h
        jc      fail
        STEP 2
        mov     dx, f_t2
        mov     ax, 4300h
        int     21h
        jc      fail
        test    cl, 1
        jz      fail
        STEP 3
        mov     dx, f_t2
        mov     ax, 3D01h
        int     21h
        jnc     failnc
        EQ      ax, 5
        STEP 4
        mov     dx, f_t2
        mov     ah, 41h
        int     21h
        jnc     failnc
        EQ      ax, 5
        STEP 5
        mov     dx, f_t2
        xor     cx, cx
        mov     ax, 4301h
        int     21h
        jc      fail
        mov     dx, f_t2
        mov     ax, 3D01h
        int     21h
        jc      fail
        mov     bx, ax
        DOS     3Eh
        clc
        ret

t_delete:
        STEP 1
        mov     dx, f_t2
        DOS     41h
        STEP 2
        mov     dx, f_t2
        mov     ax, 3D00h
        int     21h
        jnc     failnc
        EQ      ax, 2
        STEP 3
        mov     dx, f_t2
        DOSERR  41h, 2
        clc
        ret

t_dir:  STEP 1
        mov     dx, d_sub
        DOS     39h
        STEP 2
        mov     dx, d_sub
        DOSERR  39h, 5
        STEP 3
        mov     dx, d_sub
        DOS     3Bh
        mov     dx, d_dot               ; RD . in it: 5 (not 16, "the
        DOSERR  3Ah, 5                  ;  current directory")
        STEP 4
        mov     si, buf
        xor     dl, dl
        DOS     47h
        mov     si, buf
        mov     di, d_sub
        call    streq
        jc      fail
        STEP 5
        mov     dx, f_in
        xor     cx, cx
        DOS     3Ch
        mov     bx, ax
        push    bx
        mov     dx, s_hi
        mov     cx, 5
        DOS     40h
        pop     bx
        DOS     3Eh
        STEP 6
        mov     dx, d_up
        DOS     3Bh
        mov     si, buf
        xor     dl, dl
        DOS     47h
        cmp     byte [buf], 0
        jne     fail
        STEP 7
        mov     dx, f_subin
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     bx, ax
        push    bx
        mov     dx, buf
        mov     cx, 100
        DOS     3Fh
        pop     bx
        EQ      ax, 5
        DOS     3Eh
        mov     si, buf
        mov     di, s_hi
        mov     cx, 5
        repe    cmpsb
        jne     fail
        STEP 8
        mov     dx, f_suball
        mov     cx, 10h
        call    count
        EQ      ax, 3
        STEP 9
        mov     dx, d_sub
        DOSERR  3Ah, 5
        STEP 10
        mov     dx, f_subin
        DOS     41h
        mov     dx, d_subw              ; "S?B": wildcards, refused (it
        DOSERR  3Ah, 3                  ;  removed the first match)
        mov     dx, d_subdot            ; SUB\., empty now: 5 (not SUB
        DOSERR  3Ah, 5                  ;  through its own "." entry)
        mov     dx, d_root              ; \: 5
        DOSERR  3Ah, 5
        mov     dx, d_up                ; .. in the root: 3, as for CD
        DOSERR  3Ah, 3
        mov     dx, d_sub               ; so SUB is still there to remove
        DOS     3Ah
        STEP 11
        mov     dx, d_sub
        DOSERR  3Bh, 3
        clc
        ret

; strings DS:SI and DS:DI equal (ASCIIZ)?  CF if not
streq:  lodsb
        cmp     al, [di]
        jne     .no
        inc     di
        or      al, al
        jnz     streq
        clc
        ret
.no:    stc
        ret

; number of matches for pattern DX with attributes CX -> AX
count:  push    bx
        xor     bx, bx
        mov     ah, 4Eh
        int     21h
        jc      .x
.l:     inc     bx
        mov     ah, 4Fh
        int     21h
        jnc     .l
.x:     mov     ax, bx
        pop     bx
        ret

; a directory with 40 files grows past its first cluster
NFILES  equ 40
t_bigdir:
        STEP 1
        mov     dx, d_d2
        DOS     39h
        mov     byte [fnum], 0
.c:     STEP 2
        call    mkname
        mov     dx, fname
        xor     cx, cx
        DOS     3Ch
        mov     bx, ax
        push    bx
        mov     dx, fname + 3
        mov     cx, 3
        DOS     40h
        pop     bx
        DOS     3Eh
        inc     byte [fnum]
        cmp     byte [fnum], NFILES
        jb      .c
        STEP 3
        mov     dx, f_d2all
        mov     cx, 10h
        call    count
        EQ      ax, NFILES + 2
        STEP 4                          ; the last one reads back
        dec     byte [fnum]
        call    mkname
        mov     dx, fname
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     bx, ax
        push    bx
        mov     dx, buf
        mov     cx, 10
        DOS     3Fh
        pop     bx
        EQ      ax, 3
        DOS     3Eh
        mov     si, buf
        mov     di, fname + 3
        mov     cx, 3
        repe    cmpsb
        jne     fail
        STEP 5
        mov     byte [fnum], 0
.d:     call    mkname
        mov     dx, fname
        DOS     41h
        inc     byte [fnum]
        cmp     byte [fnum], NFILES
        jb      .d
        STEP 6
        mov     dx, f_d2all
        mov     cx, 10h
        call    count
        EQ      ax, 2
        STEP 7
        mov     dx, d_d2
        DOS     3Ah
        clc
        ret

; fname = "D2\Fnn" for [fnum]
mkname: mov     al, [fnum]
        xor     ah, ah
        mov     bl, 10
        div     bl
        add     ax, '00'
        mov     [fname + 4], al
        mov     [fname + 5], ah
        ret

t_dup:  STEP 1
        mov     dx, f_big
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     [h1], ax
        STEP 2
        mov     bx, ax
        DOS     45h
        mov     [h2], ax
        STEP 3                          ; they share the file position
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 10
        DOS     3Fh
        mov     bx, [h2]
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4201h
        int     21h
        jc      fail
        EQ      ax, 10
        STEP 4
        mov     bx, [h1]
        DOS     3Eh
        mov     bx, [h2]
        mov     dx, buf
        mov     cx, 10
        DOS     3Fh
        EQ      ax, 10
        mov     si, buf
        mov     ax, 10
        mov     cx, 10
        call    pat_check
        jc      fail
        STEP 5
        mov     bx, [h2]
        mov     cx, [h1]
        DOS     46h
        mov     bx, [h1]
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4201h
        int     21h
        jc      fail
        EQ      ax, 20
        mov     bx, [h1]
        DOS     3Eh
        mov     bx, [h2]
        DOS     3Eh
        STEP 6
        mov     bx, [h2]
        DOSERR  3Eh, 6
        clc
        ret

t_mem:  STEP 1
        mov     bx, 100h
        DOS     48h
        mov     [mseg], ax
        mov     es, ax
        xor     di, di
        mov     cx, 800h
        mov     ax, 0AA55h
        rep     stosw
        STEP 2
        mov     es, [mseg]
        mov     bx, 200h
        DOS     4Ah
        STEP 3
        mov     es, [mseg]
        mov     bx, 0FFFFh
        mov     ah, 4Ah
        int     21h
        jnc     failnc
        EQ      ax, 8
        cmp     bx, 200h
        jb      fail
        STEP 4
        mov     es, [mseg]
        DOS     49h
        STEP 5
        mov     bx, 0FFFFh
        mov     ah, 48h
        int     21h
        jnc     failnc
        EQ      ax, 8
        cmp     bx, 1000h               ; at least 64 KB free
        jb      fail
        STEP 6
        DOS     48h                     ; the largest block itself
        mov     es, ax
        DOS     49h
        push    ds
        pop     es
        clc
        ret

; a child it writes itself: prints, exits with code 7
t_exec: STEP 1
        mov     dx, f_child
        xor     cx, cx
        DOS     3Ch
        mov     bx, ax
        push    bx
        mov     dx, child
        mov     cx, child_end - child
        DOS     40h
        pop     bx
        DOS     3Eh
        STEP 2
        mov     word [epb], 0
        mov     word [epb + 2], tail
        mov     [epb + 4], ds
        mov     word [epb + 6], fcb
        mov     [epb + 8], ds
        mov     word [epb + 10], fcb
        mov     [epb + 12], ds
        push    ds
        pop     es
        mov     dx, f_child
        mov     bx, epb
        mov     ax, 4B00h
        int     21h
        push    cs
        pop     ds
        push    cs
        pop     es
        jc      fail
        STEP 3
        mov     ah, 4Dh
        int     21h
        EQ      ax, 7
        STEP 4                          ; no such program
        mov     dx, f_none
        mov     bx, epb
        mov     ax, 4B00h
        int     21h
        jnc     failnc
        EQ      ax, 2
        STEP 5
        mov     dx, f_child
        DOS     41h
        clc
        ret

child:  ; org 100h code, position independent enough
        db      0B4h, 09h               ; mov ah, 9
        db      0BAh, 0Ch, 01h          ; mov dx, 010Ch
        db      0CDh, 21h               ; int 21h
        db      0B8h, 07h, 4Ch          ; mov ax, 4C07h
        db      0CDh, 21h               ; int 21h
        db      '  (child ran)', 13, 10, '$'
child_end:

; a child that stays resident (INT 31h) with a handler on INT 61h
t_tsr:  STEP 1
        mov     ax, 3561h
        int     21h
        mov     [old61], bx
        mov     [old61 + 2], es
        push    ds
        pop     es
        mov     dx, f_tsr
        xor     cx, cx
        DOS     3Ch
        mov     bx, ax
        push    bx
        mov     dx, tsr
        mov     cx, tsr_end - tsr
        DOS     40h
        pop     bx
        DOS     3Eh
        STEP 2
        mov     word [epb], 0
        mov     word [epb + 2], tail
        mov     [epb + 4], ds
        mov     word [epb + 6], fcb
        mov     [epb + 8], ds
        mov     word [epb + 10], fcb
        mov     [epb + 12], ds
        mov     dx, f_tsr
        mov     bx, epb
        mov     ax, 4B00h
        int     21h
        push    cs
        pop     ds
        push    cs
        pop     es
        jc      fail
        STEP 3
        mov     ah, 4Dh
        int     21h
        EQ      ax, 0300h
        STEP 4
        xor     ax, ax
        int     61h
        EQ      ax, 1234h
        STEP 5
        push    ds
        lds     dx, [old61]
        mov     ax, 2561h
        int     21h
        pop     ds
        mov     dx, f_tsr
        DOS     41h
        clc
        ret

tsr:    db      0B8h, 61h, 25h          ; mov ax, 2561h
        db      0BAh, 10h, 01h          ; mov dx, 0110h
        db      0CDh, 21h               ; int 21h
        db      0BAh, 12h, 00h          ; mov dx, 12h (paragraphs)
        db      0B8h, 00h, 31h          ; mov ax, 3100h
        db      0CDh, 21h               ; int 21h
        db      0B8h, 34h, 12h          ; mov ax, 1234h
        db      0CFh                    ; iret
tsr_end:

t_time: STEP 1
        mov     dx, f_big
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     [h1], ax
        mov     bx, ax
        mov     ax, 5700h
        int     21h
        jc      fail
        cmp     dx, (46 << 9)           ; dated 2026
        jb      fail
        STEP 2
        mov     bx, [h1]
        mov     dx, (10 << 9) | (1 << 5) | 1
        mov     cx, (12 << 11)
        mov     ax, 5701h
        int     21h
        jc      fail
        mov     bx, [h1]
        DOS     3Eh
        STEP 3
        mov     dx, f_big
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     [h1], ax
        mov     bx, ax
        mov     ax, 5700h
        int     21h
        jc      fail
        EQ      dx, (10 << 9) | (1 << 5) | 1
        EQ      cx, (12 << 11)
        mov     bx, [h1]
        DOS     3Eh
        clc
        ret

t_free: STEP 1
        xor     dl, dl
        DOS     36h
        cmp     ax, 0FFFFh
        je      fail
        EQ      cx, 512
        mov     [free0], bx
        mov     [spc], ax
        STEP 2                          ; 10 KB more
        mov     dx, f_t1
        xor     cx, cx
        DOS     3Ch
        mov     bx, ax
        push    bx
        mov     dx, buf
        mov     cx, 10240
        DOS     40h
        pop     bx
        DOS     3Eh
        STEP 3
        xor     dl, dl
        DOS     36h
        mov     ax, [free0]
        sub     ax, bx                  ; clusters used
        mov     bx, ax
        mov     ax, 20
        xor     dx, dx
        div     word [spc]
        EQ      bx, ax
        STEP 4
        mov     dx, f_t1
        DOS     41h
        xor     dl, dl
        DOS     36h
        EQ      bx, [free0]
        clc
        ret

t_new:  STEP 1
        mov     dx, f_big
        xor     cx, cx
        DOSERR  5Bh, 80
        STEP 2
        mov     dx, f_new
        xor     cx, cx
        DOS     5Bh
        mov     bx, ax
        DOS     3Eh
        mov     dx, f_new
        DOS     41h
        STEP 3                          ; a temporary file in the root
        mov     word [tmpn], '\'
        mov     dx, tmpn
        xor     cx, cx
        DOS     5Ah
        mov     bx, ax
        DOS     3Eh
        STEP 4
        mov     dx, tmpn
        DOS     41h
        clc
        ret

t_ioctl:
        STEP 1
        mov     bx, 1
        mov     ax, 4400h
        int     21h
        jc      fail
        test    dl, 80h
        jz      fail
        STEP 2
        mov     dx, f_big
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     bx, ax
        push    bx
        mov     ax, 4400h
        int     21h
        pop     bx
        jc      fail
        test    dl, 80h
        jnz     fail
        DOS     3Eh
        STEP 3
        mov     dx, f_con
        mov     ax, 3D01h
        int     21h
        jc      fail
        mov     bx, ax
        push    bx
        mov     dx, s_viacon
        mov     cx, s_viacon_end - s_viacon
        DOS     40h
        pop     bx
        DOS     3Eh
        STEP 4
        mov     dx, f_nul
        mov     ax, 3D02h
        int     21h
        jc      fail
        mov     bx, ax
        push    bx
        mov     dx, buf
        mov     cx, 10
        DOS     3Fh
        pop     bx
        EQ      ax, 0
        DOS     3Eh
        clc
        ret

t_parse:
        STEP 1
        push    ds
        pop     es
        mov     si, s_fcbname
        mov     di, fcb2
        mov     ax, 2900h
        int     21h
        xor     ah, ah
        EQ      ax, 0
        STEP 2
        cmp     byte [fcb2], 1
        jne     fail
        mov     si, fcb2 + 1
        mov     di, s_fcbwant
        mov     cx, 11
        repe    cmpsb
        jne     fail
        STEP 3
        mov     si, s_fcbwild
        mov     di, fcb2
        mov     ax, 2900h
        int     21h
        xor     ah, ah
        EQ      ax, 1
        clc
        ret

t_find: STEP 1
        mov     dx, f_all
        xor     cx, cx
        call    count
        cmp     ax, 2
        jb      fail
        STEP 2
        mov     dx, f_nomatch
        xor     cx, cx
        mov     ah, 4Eh
        int     21h
        jnc     failnc
        cmp     ax, 18
        je      .ok
        EQ      ax, 2
.ok:    clc
        ret

; a gap: writing past the end makes the file longer
t_gap:  STEP 1
        mov     dx, f_big
        mov     ax, 3D02h
        int     21h
        jc      fail
        mov     [h1], ax
        mov     bx, ax
        xor     cx, cx
        mov     dx, 50000
        mov     ax, 4200h
        int     21h
        jc      fail
        STEP 2
        mov     bx, [h1]
        mov     dx, buf
        mov     cx, 10
        DOS     40h
        EQ      ax, 10
        mov     bx, [h1]
        DOS     3Eh
        STEP 3
        mov     dx, f_big
        call    fsize
        EQ      ax, 50010
        STEP 4                          ; the start is untouched
        mov     dx, f_big
        mov     ax, 3D00h
        int     21h
        jc      fail
        mov     bx, ax
        push    bx
        mov     dx, buf
        mov     cx, 4096
        DOS     3Fh
        pop     bx
        EQ      ax, 4096
        DOS     3Eh
        mov     si, buf
        mov     cx, 4096
        xor     ax, ax
        call    pat_check
        jc      fail
        STEP 5
        mov     dx, f_big
        DOS     41h
        clc
        ret

; ---------------------------------------------------------------------
tests:  dw t_ver, n_ver
        dw t_create, n_create
        dw t_read, n_read
        dw t_seek, n_seek
        dw t_big, n_big
        dw t_bigread, n_bigread
        dw t_append, n_append
        dw t_trunc, n_trunc
        dw t_rename, n_rename
        dw t_attr, n_attr
        dw t_delete, n_delete
        dw t_dir, n_dir
        dw t_bigdir, n_bigdir
        dw t_dup, n_dup
        dw t_mem, n_mem
        dw t_exec, n_exec
        dw t_tsr, n_tsr
        dw t_time, n_time
        dw t_free, n_free
        dw t_new, n_new
        dw t_ioctl, n_ioctl
        dw t_parse, n_parse
        dw t_find, n_find
        dw t_gap, n_gap
        dw 0

n_ver       db 'version, drive, date', 0
n_create    db 'create and write', 0
n_read      db 'open and read', 0
n_seek      db 'seek', 0
n_big       db '40 KB file, odd-sized reads', 0
n_bigread   db '32 KB in one read', 0
n_append    db 'append', 0
n_trunc     db 'truncate', 0
n_rename    db 'rename', 0
n_attr      db 'attributes, read-only', 0
n_delete    db 'delete', 0
n_dir       db 'directories', 0
n_bigdir    db 'directory of 40 files', 0
n_dup       db 'duplicate handles', 0
n_mem       db 'memory blocks', 0
n_exec      db 'run a child, exit code', 0
n_tsr       db 'terminate and stay resident', 0
n_time      db 'file date and time', 0
n_free      db 'free space', 0
n_new       db 'create new, temporary file', 0
n_ioctl     db 'devices: IOCTL, CON, NUL', 0
n_parse     db 'parse file name', 0
n_find      db 'find', 0
n_gap       db 'write past the end', 0

s_hello     db 'TESTDOS - DOS API checks', 13, 10, 0
s_ok        db 'ok    ', 0
s_fail      db 'FAIL  ', 0
s_step      db ' (step ', 0
s_code      db ', AX=', 0
s_total     db 13, 10, 'TESTDOS: ', 0
s_passed    db ' passed, ', 0
s_failed    db ' failed', 13, 10, 0
s_crlf      db 13, 10, 0
s_hi        db 'hello'
s_viacon    db '  (written to CON)', 13, 10
s_viacon_end:
s_fcbname   db 'A:FOO.BAR', 0
s_fcbwant   db 'FOO     BAR'
s_fcbwild   db 'X*.?', 0
f_t1        db 'T1.DAT', 0
f_t2        db 'T2.DAT', 0
f_big       db 'BIG.DAT', 0
f_new       db 'NEW.DAT', 0
f_child     db 'CHILD.COM', 0
f_tsr       db 'TSR.COM', 0
f_none      db 'NOPE.COM', 0
f_con       db 'CON', 0
f_nul       db 'NUL', 0
f_all       db '*.*', 0
f_nomatch   db 'ZZZZZZ.QQQ', 0
d_sub       db 'SUB', 0
d_up        db '..', 0
d_dot       db '.', 0
d_subw      db 'S?B', 0
d_subdot    db 'SUB\.', 0
d_root      db '\', 0
f_in        db 'IN.TXT', 0
f_subin     db 'SUB\IN.TXT', 0
f_suball    db 'SUB\*.*', 0
d_d2        db 'D2', 0
f_d2all     db 'D2\*.*', 0
fname       db 'D2\F00', 0
tail        db 0, 13
fcb         db 0, '           ', 0, 0, 0, 0

section .bss
bss_start:
npass   resw 1
nfail   resw 1
tname   resw 1
tsp     resw 1
step    resb 1
fnum    resb 1
ecode   resw 1
h1      resw 1
h2      resw 1
off     resw 1
mseg    resw 1
free0   resw 1
spc     resw 1
epb     resw 7
old61   resw 2
fcb2    resb 37
tmpn    resb 80
numbuf  resb 8
BUFSZ   equ 10240
buf     resb BUFSZ
        resb 1024
stack_top:
