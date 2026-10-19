; =====================================================================
;  MTAPI.INC - multitasking (KMT.INC) as programs see it: INT 21h AH=F0h
;  with AL = 10h and up.  With multitasking off (no MULTITASK=1 in
;  LODE.INI, or no EMS) every one of them fails: CF set, AX = 1, as any
;  call MS-DOS doesn't have.
; =====================================================================
MT_LIST     equ 12h                     ; the tasks: ES:DI = room for CX records
                                        ;  (MT_REC bytes each) -> CX = how many
                                        ;  tasks there are (records for as many
                                        ;  as fit), AL = the front task's number
MT_TASKS    equ 8                       ; most tasks at once (0 is the Executive)

; ---- a task's record (MT_LIST; the task table is the same) -----------
TR_ID       equ 0                       ; byte: its number
TR_STATE    equ 1                       ; byte: TS_*
TR_PSP      equ 2                       ; word: its program's PSP
TR_NAME     equ 4                       ; 12 bytes: its program's name, ASCIIZ
MT_REC      equ 16

TS_FREE     equ 0                       ; (no task: not listed)
TS_RUN      equ 1                       ; running
