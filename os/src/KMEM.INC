; =====================================================================
;  KMEM.INC - the memory arena: DOS-style MCBs from the end of the
;  kernel to the top of conventional memory.  The last block (owner 8,
;  "SC") is the floppy track cache (KDISK), unless it is in EMS (KEMS).
;  MCB (one paragraph before each block): [0] 'M' or 'Z' (last),
;  [1] owner PSP (0 = free), [3] size in paragraphs, [8] name.
; =====================================================================
section .bss
first_mcb   resw 1
mem_top     resw 1
section .text

kern_top    equ mem_init + 1            ; this immediate: KEMS.INC moves it up
mem_init:
        mov     ax, bss_end + 15        ; (the arena starts above the kernel)
        shr     ax, 4
        add     ax, KSEG
        mov     [first_mcb], ax
        mov     [lol-2], ax
        int     12h
        shl     ax, 6
        mov     [mem_top], ax
%ifndef NOTC
        ; The track cache: the last block (owner 8, "SC") at the top of
        ; memory, inside one 64 KB page so floppy DMA reaches all of it
        ; (below the page boundary if it would cross one).  (KEMS.INC:
        ; when the cache is in EMS, a jump to .zm, which makes a 'Z')
.tc:    mov     cx, ax
        sub     cx, TC_PARAS            ; its data
        dec     ax                      ; its last paragraph
        mov     dx, ax
        xor     dx, cx
        test    dh, 0F0h
        jz      .tcat
        and     ax, 0F000h
        mov     cx, ax
        sub     cx, TC_PARAS
.tcat:  mov     [tc_seg], cx
        mov     bx, cx
        dec     bx                      ; its MCB
        push    es
        mov     es, bx
        mov     byte [es:0], 'Z'
        mov     word [es:1], 8
        mov     word [es:3], TC_PARAS
        mov     word [es:8], 'SC'
        pop     es
        mov     ax, bx                  ; free memory ends below it
.zm:    mov     dl, 'M'
%else
        mov     dl, 'Z'
%endif
        mov     bx, [first_mcb]
        sub     ax, bx
        dec     ax
        push    es
        mov     es, bx
        mov     [es:0], dl
        mov     word [es:1], 0
        mov     [es:3], ax
        pop     es
        ret

; merge the free blocks that follow the free block at ES (an MCB)
mem_merge:
        push    ax
        push    bx
.l:     cmp     byte [es:0], 'Z'
        je      .x
        mov     ax, es
        add     ax, [es:3]
        inc     ax                      ; next MCB
        push    ds
        mov     ds, ax
        cmp     word [ds:1], 0
        jne     .nf
        mov     bl, [ds:0]
        mov     ax, [ds:3]
        pop     ds
        inc     ax
        add     [es:3], ax
        mov     [es:0], bl
        jmp     .l
.nf:    pop     ds
.x:     pop     bx
        pop     ax
        ret

; allocate BX paragraphs for owner DX -> AX = segment
; CF: AX = 8 (BX = largest free) or 7 (arena damaged)
mem_alloc:
        push    cx
        push    si
        push    es
        xor     si, si                  ; largest free so far
        mov     ax, [first_mcb]
.scan:  mov     es, ax
        mov     cl, [es:0]
        cmp     cl, 'M'
        je      .ok
        cmp     cl, 'Z'
        jne     .bad
.ok:    cmp     word [es:1], 0
        jne     .next
        call    mem_merge
        mov     cx, [es:3]
        cmp     cx, bx
        jae     .take
        cmp     cx, si
        jbe     .next
        mov     si, cx
.next:  cmp     byte [es:0], 'Z'
        je      .full
        add     ax, [es:3]
        inc     ax
        jmp     .scan
.take:  call    mem_split               ; ES = MCB, BX = size wanted
        mov     [es:1], dx
        mov     ax, es
        inc     ax
        clc
        jmp     .x
.full:  mov     bx, si
        mov     ax, 8
        stc
        jmp     .x
.bad:   mov     ax, 7
        stc
.x:     pop     es
        pop     si
        pop     cx
        ret

; block at MCB ES is >= BX paragraphs: cut it to BX, the rest becomes free
mem_split:
        push    ax
        push    cx
        mov     cx, [es:3]
        sub     cx, bx
        jz      .x                      ; exact
        dec     cx                      ; the new MCB takes a paragraph
        jz      .x                      ; (one spare paragraph: keep it)
        mov     ax, es
        add     ax, bx
        inc     ax
        push    ds
        mov     ds, ax
        mov     al, [es:0]
        mov     [ds:0], al
        mov     word [ds:1], 0
        mov     [ds:3], cx
        pop     ds
        mov     byte [es:0], 'M'
        mov     [es:3], bx
.x:     pop     cx
        pop     ax
        ret

; free the block at segment ES.  CF: AX = 9 (not a block)
mem_free:
        push    es
        call    mem_mcb
        jc      .x
        mov     word [es:1], 0
        clc
.x:     pop     es
        ret

; ES = block -> ES = its MCB, CF + AX = 9 if it isn't one
mem_mcb:
        push    ax
        mov     ax, es
        dec     ax
        mov     es, ax
        cmp     byte [es:0], 'M'
        je      .ok
        cmp     byte [es:0], 'Z'
        je      .ok
        pop     ax
        mov     ax, 9
        stc
        ret
.ok:    pop     ax
        clc
        ret

; resize the block at ES to BX paragraphs.  CF: AX = 8, BX = most possible
mem_resize:
        push    es
        call    mem_mcb
        jc      .x
        cmp     bx, [es:3]
        jbe     .cut
        push    word [es:3]             ; grow: take in following free blocks
        call    mem_merge
        cmp     bx, [es:3]
        jbe     .grow
        mov     ax, [es:3]              ; most possible
        pop     bx                      ; can't: back to the old size
        call    mem_split
        mov     bx, ax
        mov     ax, 8
        stc
        jmp     .x
.grow:  add     sp, 2
.cut:   call    mem_split
        clc
.x:     pop     es
        ret

; free every block owned by PSP AX
mem_free_owner:
        push    bx
        push    es
        mov     bx, [first_mcb]
.l:     mov     es, bx
        cmp     byte [es:0], 'M'
        je      .ok
        cmp     byte [es:0], 'Z'
        jne     .x
.ok:    cmp     [es:1], ax
        jne     .n
        mov     word [es:1], 0
.n:     cmp     byte [es:0], 'Z'
        je      .x
        add     bx, [es:3]
        inc     bx
        jmp     .l
.x:     pop     es
        pop     bx
        ret

; largest free block -> BX
mem_largest:
        push    ax
        push    dx
        mov     bx, 0FFFFh
        xor     dx, dx
        call    mem_alloc               ; fails with BX = largest
        pop     dx
        pop     ax
        ret

; INT 21h 48h, 49h, 4Ah
f_48:   mov     bx, [bp+F_BX]
        mov     dx, [cur_psp]
        call    mem_alloc
        mov     [bp+F_BX], bx           ; (the largest on failure; unchanged
        jmp     ret_cfax                ;  when it worked)
f_49:   mov     es, [bp+F_ES]
        call    mem_free
        jmp     ret_cf
f_4A:   mov     es, [bp+F_ES]
        mov     bx, [bp+F_BX]
        call    mem_resize
        mov     [bp+F_BX], bx           ; (as for 48h)
        jmp     ret_cf
