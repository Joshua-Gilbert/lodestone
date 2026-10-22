; =====================================================================
;  MTAPI.INC - multitasking (KMT.INC) as programs see it: INT 21h AH=F0h
;  with AL = 10h and up.  With multitasking off (no MULTITASK=1 in
;  LODE.INI, or no EMS) every one of them fails: CF set, AX = 1, as any
;  call MS-DOS doesn't have.
; =====================================================================
MT_SPAWN    equ 10h                     ; a program as a new task: DS:DX = its
                                        ;  path (ASCIIZ, with its extension; up
                                        ;  to 126 characters), ES:BX = a block
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
                                        ;  as fit), AL = the front task's number,
                                        ;  AH = the caller's
MT_FRONT    equ 13h                     ; BL = a task: it comes to the front at
                                        ;  the next key wait.  CF: AX = 1 (none),
                                        ;  5 (parked).
                                        ;  (When the front task ends, task 0
                                        ;  comes to the front.)
MT_KILL     equ 14h                     ; BL = a task: it ends, whatever runs in
                                        ;  it, its programs' files closed and
                                        ;  their EMS and memory freed, its exit
                                        ;  code 0100h (as ^C ends a program).
                                        ;  Another task: when it next runs (soon:
                                        ;  the caller's turn ends on this call's
                                        ;  way out, if it is at a safe point);
                                        ;  the caller's own: at once, no return
                                        ;  (from an interrupt's handler, an INT
                                        ;  24h handler or a mouse event
                                        ;  handler: at its next safe point).
                                        ;  A parked task: brought back first
                                        ;  (MT_UNPARK).  CF: AX = 1 (no such
                                        ;  task), 5 (task 0, the Executive), 8
                                        ;  (parked, and it can't be brought back)
MT_PARK     equ 15h                     ; BL = a task: its memory (its region)
                                        ;  copied to EMS and given back; it
                                        ;  doesn't run till MT_UNPARK.  CF: AX =
                                        ;  1 (no such task), 5 (task 0, the
                                        ;  caller's own, the one in front, one
                                        ;  being ended or parked already, or one
                                        ;  a vector points into: pinned), 8 (not
                                        ;  enough EMS)
MT_UNPARK   equ 16h                     ; BL = a parked task: its memory back at
                                        ;  the same place (tasks in the way
                                        ;  parked first), and it goes on as it
                                        ;  was (behind).  CF: AX = 1 (no such
                                        ;  task, or not parked), 8 (the place
                                        ;  taken by memory not a task's, or by a
                                        ;  task that can't be parked; or its
                                        ;  EMS gone)
MT_SCREEN   equ 1Ch                    ; the caller's screen, which it wrote
                                        ;  itself, is as it should be (put back
                                        ;  after a screen saver): not counted
                                        ;  against it as writing the screen
                                        ;  itself (M4a; only the front task's)
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
SPF_BG      equ 2                       ; it runs in the background whatever it
                                        ;  does, its output on the screen in
                                        ;  front (as before M4a)
SPF_FREEZE  equ 4                       ; it never runs in the background

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
TS_WAITF    equ 3                       ; waiting to be in front (a graphics
                                        ;  mode or a pixel asked for in the
                                        ;  background)
TS_FROZEN   equ 4                       ; (MT_LIST only) ready, but frozen in the
                                        ;  background: it writes the screen
                                        ;  itself, or SPF_FREEZE
TS_PARKED   equ 5                       ; parked in EMS (MT_PARK): it doesn't run
