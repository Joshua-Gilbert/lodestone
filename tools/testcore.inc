; =====================================================================
;  Automated test set
; =====================================================================
P_POLL  equ 0
P_488   equ 1
P_TEK   equ 2
P_METER equ 3
REPS    equ 10
SPREPS  equ 20

; test one device, address BL
test_dev:
        mov     dx, s_dhdr
        call    puts
        mov     al, bl
        xor     ah, ah
        call    pdec2
        mov     dx, s_2sp
        call    puts
        ; --- identify: ID? (Tek) then *IDN? (488.2) ---
        mov     byte [prof], P_POLL
        mov     si, q_id
        call    query
        jc      .i2
        cmp     word [rbuf], 'ID'
        jne     .i2
        mov     byte [prof], P_TEK
        mov     si, meters              ; DM5120 / DM5010 / DC5009 ?
.mt:    cmp     byte [si], 0
        je      .idok
        push    si
        mov     di, rbuf+7
        mov     cx, 6
        repe    cmpsb
        pop     si
        je      .ism
        add     si, 6
        jmp     .mt
.ism:   mov     byte [prof], P_METER
        jmp     .idok
.i2:    mov     si, q_idn
        call    query
        jc      .noid
        mov     byte [prof], P_488
.idok:  mov     dx, rbuf
        call    puts
        call    crlf
        jmp     .pre
.noid:  mov     dx, s_noid2
        call    puts
.pre:   call    spoll                   ; status before the tests
        mov     [st_pre], al
        jnc     .t
        mov     byte [st_pre], 0FFh
.t:     cmp     byte [prof], P_488
        jne     .t1
        mov     si, q_idn               ; 488.2: *IDN? x10
        mov     di, l_idn
        mov     cx, REPS
        mov     byte [t_show], 0
        call    run_test
        jmp     .tsp
.t1:    cmp     byte [prof], P_TEK
        jb      .tsp
        mov     si, q_id                ; Tek: ID? x10
        mov     di, l_id
        mov     cx, REPS
        mov     byte [t_show], 0
        call    run_test
        mov     si, q_set               ; Tek: SET? once (all settings)
        mov     di, l_set
        mov     cx, 1
        mov     byte [t_show], 1
        call    run_test
        cmp     byte [prof], P_METER
        jne     .tsp
        xor     si, si                  ; meter: talk-only reading x10
        mov     di, l_read
        mov     cx, REPS
        mov     byte [t_show], 1
        call    run_test
.tsp:   mov     si, 1                   ; everyone: serial poll x20
        mov     di, l_spoll
        mov     cx, SPREPS
        mov     byte [t_show], 0
        call    run_test
        ; --- status afterwards ---
        call    spoll
        jc      .x
        test    al, 20h
        jz      .x
        push    ax
        mov     dx, s_warn
        call    puts
        pop     ax
        call    phex8
        mov     dx, s_warn2
        call    puts
        mov     al, [st_pre]
        call    phex8
        mov     dx, s_warn3
        call    puts
        inc     word [nwarn]
.x:     ret

; run one test.  SI = query (ASCIIZ), 0 = read only, 1 = serial poll;
; CX = repetitions; DI = label; BL = address.  Stops at the first failure.
run_test:
        mov     [t_si], si
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
        mov     si, [t_si]
        cmp     si, 1
        je      .sp
        or      si, si
        jz      .rd
        call    query
        jmp     .done
.rd:    call    query_read
        jmp     .done
.sp:    call    spoll
        mov     [t_st], al
.done:  pushf
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
        cmp     dx, [t_min+2]           ; min
        ja      .nmin
        jb      .smin
        cmp     ax, [t_min]
        jae     .nmin
.smin:  mov     [t_min], ax
        mov     [t_min+2], dx
.nmin:  cmp     dx, [t_max+2]           ; max
        jb      .nmax
        ja      .smax
        cmp     ax, [t_max]
        jbe     .nmax
.smax:  mov     [t_max], ax
        mov     [t_max+2], dx
.nmax:  loop    .lp
        jmp     .rep
.fail:  inc     word [nfail]
        mov     [t_fail], ax            ; how long the failing call took
        mov     [t_fail+2], dx
        ; ---- report ----
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
        call    failinfo
        call    crlf
        ret
.some:  mov     dx, s_avg
        call    puts
        mov     ax, [t_sum]
        mov     dx, [t_sum+2]
        mov     cx, [t_ok]
        push    bx
        call    ldiv                    ; (remainder in BX - keep address)
        pop     bx
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
        cmp     word [t_si], 1
        je      .st
        mov     ax, [rxcnt]
        mov     cl, 5
        call    pdecw
        mov     dx, s_bytes
        call    puts
        jmp     .fl
.st:    mov     dx, s_st
        call    puts
        mov     al, [t_st]
        call    phex8
        mov     al, 'h'
        call    putc
.fl:    mov     ax, [t_ok]
        cmp     ax, [t_reps]
        je      .nl
        mov     dx, s_then
        call    puts
        call    failinfo
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

summary:
        call    stamp
        sub     ax, [tall]
        sbb     dx, [tall+2]
        mov     [tall], ax
        mov     [tall+2], dx
        mov     dx, s_sum1
        call    puts
        mov     al, [nfound]
        xor     ah, ah
        call    pdec
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
        mov     dx, s_sum6
        call    puts
        mov     ax, [recov]
        call    pdec
        mov     dx, s_sum7
        call    puts
        mov     ax, [nwarn]
        call    pdec
        call    crlf
        ret


; " (err n after x ms)" for the failing transaction
failinfo:
        mov     dx, s_ferr
        call    puts
        mov     ax, [lasterr]
        call    pdec
        mov     dx, s_fafter
        call    puts
        mov     ax, [t_fail]
        mov     dx, [t_fail+2]
        call    pms
        mov     dx, s_fms
        call    puts
        ret
