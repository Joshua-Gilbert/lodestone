; ROMT.COM - asks the BIOS about the application ROMs (INT 15h E400-E404)
; and writes what it answered to A:\ROMT.BIN: tests/test_rom.py runs it
; under the real BIOS (tools/simgrid.py) and under pcemu, and compares.
org 100h
        mov ax, cs
        add ax, (tbl - $$ + 100h + 15) / 16
        mov [seg_], ax
        mov ax, 0E400h
        int 15h
        mov [r0], ax
        mov [r0+2], bx
        mov [r0+4], cx
        push ds
        mov ds, [cs:seg_]
        mov ax, 0E401h
        int 15h
        pop ds
        mov [r1], ax
        pushf
        pop word [r1+2]
        xor si, si
.img:   mov ax, si
        cmp al, [r1]
        jae .done
        push ds
        mov ds, [cs:seg_]
        mov ax, 0E402h
        mov dx, si
        int 15h
        pop ds
        mov di, si
        shl di, 4
        mov [imgs+di], ax
        mov [imgs+di+2], bx
        mov [imgs+di+4], cx
        mov [imgs+di+6], dx
        mov [imgs+di+8], es
        cli
        push ds
        mov ds, [cs:seg_]
        mov ax, 0E403h
        mov dx, si
        int 15h
        pop ds
        pushf
        pop word [imgs+di+10]
        mov [imgs+di+12], ax
        push ds
        mov ax, 0A000h
        mov ds, ax
        mov ax, [0]
        pop ds
        mov [imgs+di+14], ax
        push ds
        mov ds, [cs:seg_]
        mov ax, 0E404h
        int 15h
        pop ds
        sti
        inc si
        jmp .img
.done:  mov ah, 3Ch
        xor cx, cx
        mov dx, fn
        int 21h
        mov bx, ax
        mov ah, 40h
        mov cx, end_ - r0
        mov dx, r0
        int 21h
        mov ah, 3Eh
        int 21h
        mov ax, 4C00h
        int 21h
fn db 'A:\ROMT.BIN',0
seg_ dw 0
r0 dw 0,0,0
r1 dw 0,0
imgs times 8*16 db 0
end_:
align 16
tbl times 256 db 0
