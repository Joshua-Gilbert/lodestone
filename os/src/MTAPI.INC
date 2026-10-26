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
                                        ;  run ends it at once (its exit code
                                        ;  FFxxh, xx EXEC's error: MT_EXIT)
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
                                        ;  enough EMS, or the copy failed)
MT_UNPARK   equ 16h                     ; BL = a parked task: its memory back at
                                        ;  the same place (tasks in the way
                                        ;  parked first), and it goes on as it
                                        ;  was (behind).  CF: AX = 1 (no such
                                        ;  task, or not parked), 8 (the place
                                        ;  taken by memory not a task's, or by a
                                        ;  task that can't be parked; or its
                                        ;  EMS gone, or the copy failed)
MT_EXIT     equ 17h                     ; BL = a task's number -> AL = its state
                                        ;  (TS_*: TS_FREE once ended), AH = how
                                        ;  many tasks have been started with
                                        ;  that number (1-255, then 1 again; 0:
                                        ;  none yet); DX = the exit code of the
                                        ;  last one ended (its high byte 4Dh's
                                        ;  AH: 0 ended, 1 ^C or MT_KILL, 2 a
                                        ;  critical error's Abort, 3 stayed
                                        ;  resident; FFxxh: its program not
                                        ;  started, xx EXEC's error), CL = the
                                        ;  count it was started with (so CL =
                                        ;  AH: the one started last has ended)
                                        ;  CF: AX = 1 (no such number)
MT_FLAGS    equ 18h                     ; BL = a task (not 0): its SPF_BG and
                                        ;  SPF_FREEZE, CL's cleared, then CH's
                                        ;  set (CX = 0: only read) -> AL = them,
                                        ;  and MTF_DIRECT if it was found
                                        ;  writing the screen itself.  From its
                                        ;  next turn (SPF_BG: its next INT 10h
                                        ;  call).  CF: AX = 1 (no such task),
                                        ;  5 (task 0)
MT_UI       equ 19h                     ; (the Executive's, at its start: DX:AX
                                        ;  = LODEMT.SYS's far entry for it.
                                        ;  AL = 0: start the program DS:SI
                                        ;  (Return); AL = 1: has a task ended?
                                        ;  ES:DI = room for a message)
MT_TSR      equ 1Ah                     ; (Resident Claude's, at CLAUDE /R and
                                        ;  /U: M7c) ES:BX = the instruction
                                        ;  after its key wait's HLT, where the
                                        ;  tick may switch from it in the task
                                        ;  whose call it is (0:0: none any
                                        ;  more) -> DX:AX = MT's three bytes:
                                        ;  the front task's number, the running
                                        ;  one's, and 1 while its pop-up waits
                                        ;  for the front task (the stub's to
                                        ;  set and clear)
MT_WIN      equ 1Dh                     ; (a window .RUN's, at its start: M8b)
                                        ;  CF clear if the UI code running is a
                                        ;  window .RUN's session, beside others:
                                        ;  it is a window then.  CF: AX = 1
                                        ;  (not one: it has the whole screen)
MT_SCREEN   equ 1Ch                    ; the caller's screen, which it wrote
                                        ;  itself, is as it should be (put back
                                        ;  after a screen saver): not counted
                                        ;  against it as writing the screen
                                        ;  itself (M4a; only the front task's)
MT_TOPEN    equ 1Eh                     ; (T2: TERM.RUN, at its start) BL = a
                                        ;  task, CL = its count (TE_GEN: MT_EXIT's
                                        ;  AH): shown by the window .RUN that
                                        ;  calls, whose UI_EVENT gives EV_TICK
                                        ;  from now on when the task's screen or
                                        ;  state changed, it ended, or 9 ticks
                                        ;  went by.  CF: AX = 1 (no such task,
                                        ;  another count, not a window .RUN's
                                        ;  call), 5 (task 0; parked)
MT_TROWS    equ 1Fh                     ; (T1: a terminal window's look) BL = a
                                        ;  task, ES:DI = room, DX = a row, CX =
                                        ;  rows (to row 24): those rows of its
                                        ;  screen as MT keeps it (its pages; the
                                        ;  page shown), cols x 2 bytes a row,
                                        ;  copied there -> AX = its changes'
                                        ;  count (it went up: look again; any
                                        ;  INT 10h call of it behind, and its
                                        ;  leaving the front; with a screen
                                        ;  published, MT_PUB's and its PB_CHG
                                        ;  too), BX = its cursor there (row,
                                        ;  column), CL = columns, CH = its
                                        ;  mode.  T5b: with DH bit 7 set (the
                                        ;  row in DL), a screen published
                                        ;  (MT_PUB) and shown (PBF_SHOWN), the
                                        ;  task behind in a text mode: the rows
                                        ;  of its cells instead (glyph, PBA_*;
                                        ;  rows past PB_ROWS blank, 0020h), DL
                                        ;  32 (1 and 16 too, as below), CH =
                                        ;  its rows, BX = PB_CUR (FFFFh with
                                        ;  PBF_NOCUR).  DL = MTF_DIRECT, 2 if
                                        ;  nothing was copied (not a text mode
                                        ;  of 80 columns or fewer, or rows past
                                        ;  its 32 KB), 4 its pages gone (2 too),
                                        ;  8 in front (its screen the real one,
                                        ;  not its pages), 16 its program took
                                        ;  the mouse (INT 33h AX=0 or 21h: T4,
                                        ;  MT_TMOUSE), DH = its state (TS_*;
                                        ;  TS_FROZEN as MT_LIST).  CF: AX = 1
                                        ;  (no such task, rows past 24 or none,
                                        ;  room in the EMS frame's windows 0-1
                                        ;  or past its segment's end), 5 (task
                                        ;  0, the Executive; parked)
MT_TKEY     equ 20h                     ; (T1) BL = a task, CX = a key (as INT
                                        ;  16h gives them): typed to it, for its
                                        ;  INT 16h and DOS's key reads (before
                                        ;  the keyboard's; for AH=00h and 01h,
                                        ;  and DOS's, those they don't give
                                        ;  dropped), 32 waiting at most; ready
                                        ;  to run if it waited for one.  Not
                                        ;  while a critical error's prompt, a
                                        ;  call MT passed on to the BIOS or an
                                        ;  INT 13h call is under way: the
                                        ;  keyboard's then.  CF: AX = 1 (no such
                                        ;  task), 5 (task 0; parked), 8 (32
                                        ;  waiting already)
MT_TMOUSE   equ 21h                     ; (T4: TERM.RUN's, a click in its
                                        ;  window) BL = a task, BH = buttons
                                        ;  (bit 0 left, 1 right), CX = x, DX = y
                                        ;  (INT 33h's units): its own mouse
                                        ;  state, for its INT 33h calls behind,
                                        ;  as the mouse would leave it (in its
                                        ;  ranges, presses and releases counted);
                                        ;  a release before its program has
                                        ;  read the press (AX=3, 5, 6) held till it
                                        ;  has.  CF: AX = 1 (no such task, not
                                        ;  the Executive's call), 5 (task 0;
                                        ;  parked)
MT_PUB      equ 22h                     ; (T5b) a screen published for a
                                        ;  terminal window: drawn there from
                                        ;  its cells with its own font, not
                                        ;  from MT's pages.  CL = 0, a task's
                                        ;  program: ES:DI = its descriptor
                                        ;  (PB_* below: read, never written;
                                        ;  it, its cells, font and table all in
                                        ;  the task's memory), 0:0 to withdraw
                                        ;  it -> AL = 1 if a terminal window
                                        ;  shows the task, else 0; AH = the
                                        ;  task.  Withdrawn when that program
                                        ;  ends.  While one is published, the
                                        ;  task in a text mode and a window
                                        ;  showing it, CODE-Tab passes over the
                                        ;  task and MT_FRONT refuses it (AX =
                                        ;  5): its window is its screen (a
                                        ;  graphics mode's goes full screen,
                                        ;  T3).  A program told AL = 0 should
                                        ;  withdraw it and draw its screen
                                        ;  itself.  CL = 1, the
                                        ;  Executive's (TERM.RUN): BL = a task
                                        ;  -> ES:DI = its descriptor, 0:0 none.
                                        ;  CF: AX = 1 (no such task; CL not 0
                                        ;  or 1; CL = 1 from a task), 5 (CL =
                                        ;  0 from task 0; CL = 1 for task 0, or
                                        ;  a parked one), 0Dh (a descriptor not
                                        ;  all in the task's memory, nor its
                                        ;  cells, font or table; a field out of
                                        ;  range)
MT_TASKS    equ 8                     ; most tasks at once (0 is the Executive)
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
MTF_DIRECT  equ 1                       ; (MT_FLAGS: found writing the screen
                                        ;  itself, so frozen behind without
                                        ;  SPF_BG)

; ---- a published screen's descriptor (MT_PUB, T5b) -------------------
PB_VER      equ 0                       ; byte: 1 (or more)
PB_FLAGS    equ 1                       ; byte: PBF_*
PB_COLS     equ 2                       ; byte: columns, 1-80
PB_ROWS     equ 3                       ; byte: rows, 1-25
PB_CELLS    equ 4                       ; far: rows of PB_COLS words: a glyph
                                        ;  (low byte), PBA_* (high)
PB_FONT     equ 8                       ; far: 16 bytes a glyph (8x16, its
                                        ;  top row first, bit 7 leftmost),
                                        ;  codes PB_FIRST to PB_GEND - 1
PB_FIRST    equ 12                      ; byte: the first code with a glyph,
                                        ;  20h at most (one below it: 20h's)
PB_GEND     equ 13                      ; byte: the code past the last, 40h
                                        ;  at least (one from it on: '?')
PB_CUR      equ 14                      ; word: the cursor (row, column)
PB_CHG      equ 16                      ; word: a count the program adds 1 to
                                        ;  when its cells or these fields
                                        ;  change: the window looks again
PB_XLAT     equ 18                      ; far: 128 bytes, code page 437's
                                        ;  text for codes 80h-FFh (a window's
                                        ;  Copy); 0:0: none (they are '?')
PB_SIZE     equ 22
PBF_SHOWN   equ 1                       ; its cells shown (else MT's pages, as
                                        ;  any task's: a program it runs)
PBF_NOCUR   equ 2                       ; no cursor shown
PBA_INV     equ 1                       ; (a cell's attribute) inverse
PBA_UND     equ 2                       ;  underlined

; ---- a task's record (MT_LIST)----------------------------------------
TR_ID       equ 0                       ; byte: its number
TR_STATE    equ 1                       ; byte: TS_*
TR_PSP      equ 2                       ; word: its stub's PSP (task 0: the root's;
                                        ;  parked: where it will be once back)
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
