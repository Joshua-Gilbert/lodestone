; =====================================================================
;  MTAPI.INC - multitasking (KMT.INC) as programs see it: INT 21h AH=F0h
;  with AL = 10h and up.  With multitasking off (no MULTITASK=1 in
;  LODE.INI, or no EMS) every one of them fails: CF set, AX = 1, as any
;  call MS-DOS doesn't have.
; =====================================================================
MT_SPAWN    equ 10h                     ; a program as a new task: DS:DX = its
                                        ;  path (ASCIIZ, with its extension; up
                                        ;  to 127 characters), ES:BX = a block
                                        ;  (SP_* below) -> AL = the task.  CF:
                                        ;  AX = 4 (8 tasks already), 8 (no room
                                        ;  for its region).  Success means the
                                        ;  task is made: a program that can't be
                                        ;  run ends it at once (no call returns
                                        ;  its exit code yet)
MT_END      equ 11h                     ; (the task's stub, when its program is
                                        ;  done: the task ends)
MT_LIST     equ 12h                     ; the tasks: ES:DI = room for CX records
                                        ;  (MT_REC bytes each) -> CX = how many
                                        ;  tasks there are (records for as many
                                        ;  as fit), AL = the front task's number
MT_FRONT    equ 13h                     ; BL = a task: it comes to the front at
                                        ;  the next key wait.  CF: AX = 1 (none).
                                        ;  (When the front task ends, task 0
                                        ;  comes to the front.)
MT_TASKS    equ 8                       ; most tasks at once (0 is the Executive)
MT_DEFARENA equ 1000h                   ; a task's memory if SP_PARAS is 0: 64 KB

; ---- MT_SPAWN's block (EXEC's, then two more fields) -----------------
SP_ENV      equ 0                       ; word: environment (0: the caller's;
                                        ;  a copy of up to 1 KB is kept)
SP_TAIL     equ 2                       ; far: the command tail (count, text,
                                        ;  CR; 126 characters kept; 0:0: none)
SP_FCB1     equ 6                       ; far (not used: the stub's are blank)
SP_FCB2     equ 10                      ; far (not used)
SP_PARAS    equ 14                      ; word: the task's memory, paragraphs
SP_FLAGS    equ 16                      ; byte: SPF_*
SP_SIZE     equ 17
SPF_FRONT   equ 1                       ; it comes to the front

; ---- a task's record (MT_LIST) ----------------------------------------
TR_ID       equ 0                       ; byte: its number
TR_STATE    equ 1                       ; byte: TS_*
TR_PSP      equ 2                       ; word: its stub's PSP (task 0: the root's)
TR_NAME     equ 4                       ; its program's name, NUL-padded: a
TR_NAMELEN  equ 12                      ;  whole 8.3 name fills it (no NUL)
MT_REC      equ 16

TS_FREE     equ 0                       ; (no task: not listed)
TS_RUN      equ 1                       ; running, or ready to
TS_WAITK    equ 2                       ; waiting for a key (in the background,
                                        ;  or in front with another running)
