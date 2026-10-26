; MTSRQ.COM - for test_mt.py (T5c): a program woken by the GPIB driver's
; SRQ interrupt.
;   MTSRQ N [O | K | F | G | T]
; Asks MT_WAKE (INT 21h F0h AL=23h, BL=1; its AX kept at wres), takes the
; driver's SRQ count (INT 60h AH=0Eh), then sleeps (CLI, the count looked
; at, STI / HLT) until the count moves: at `seen` (offset 10Dh, which
; test_mt watches, finding it by `sig`) it counts one (nseen) and sleeps
; again; after N it ends.
;   O  no MT_WAKE (it waits its turn)
;   K  a key read (INT 16h AH=00h) first: waiting for it, its task isn't
;      ready to run, so an SRQ wakes nothing
;   F  MT_WAKE asked, then given up (BL=1, then BL=0): as O
;   G  only BL=0 (giving up what another program asked: nothing), then
;      it ends at once
;   T  asked, then it stays resident (31h): its program's end isn't
;      seen, its task's is
; nasm -f bin -o MTSRQ.COM MTSRQ.ASM
cpu 286
org 100h
        jmp     near start
nseen   dw      0                       ; 103h: SRQs seen
wres    dw      0FFFFh                  ; 105h: MT_WAKE's AX (FFFFh: not asked)
sig     db      'MTSRQ*'                ; 107h
seen:   mov     [last], ax              ; 10Dh: the count moved
        inc     word [nseen]
        mov     ax, [nseen]
        cmp     ax, [want]
        jb      sleep
        mov     ax, 4C00h
        int     21h

start:  mov     si, 81h
        call    blanks
        lodsb
        sub     al, '0'
        xor     ah, ah
        mov     [want], ax
        call    blanks
        lodsb
        and     al, 0DFh
        mov     [opt], al
        cmp     al, 'O'
        je      .gp
        xor     bl, bl
        cmp     al, 'G'
        je      .w
        inc     bl
        cmp     al, 'F'
        jne     .w
        mov     ax, 0F023h
        int     21h
        xor     bl, bl
.w:     mov     ax, 0F023h
        int     21h
        mov     [wres], ax
        cmp     byte [opt], 'G'
        jne     .t
        mov     ax, 4C00h
        int     21h
.t:     cmp     byte [opt], 'T'
        jne     .gp
        mov     ax, 3100h
        mov     dx, (pend - $$ + 100h + 15) / 16
        int     21h
.gp:    mov     ax, 0E02h               ; the driver's SRQ count (AL=2: ask)
        int     60h
        mov     es, dx
        mov     di, cx
        cmp     byte [opt], 'K'
        jne     .c
        xor     ah, ah
        int     16h
.c:     mov     ax, [es:di]
        mov     [last], ax
sleep:  cli
        mov     ax, [es:di]
        cmp     ax, [last]
        jne     seen
        sti
        hlt
        jmp     sleep

blanks: cmp     byte [si], ' '
        jne     .x
        inc     si
        jmp     blanks
.x:     ret

last    dw      0
want    dw      0
opt     db      0
pend:
        times   -((seen - $$) != 0Dh) db 0  ; (seen at 10Dh)
