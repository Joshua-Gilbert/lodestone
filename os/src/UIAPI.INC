; =====================================================================
;  UIAPI.INC - the Lodestone UI core as programs see it (API version 6)
;
;  The UI core lives in the UI segment with the Executive.  A .RUN
;  program is loaded into the same segment, above the core, and calls it
;  with ordinary 3-byte near calls into the jump table at offset 0:
;
;        call    UI_PUTS
;
;  A .RUN is built with mkrun.py, which assembles it twice (at 0 and at
;  1110h) and records every word that differs: words that grow with the
;  origin are addresses inside the program (the loader adds the load
;  offset), words that shrink are calls into the jump table (the loader
;  subtracts it).  So a .RUN loads wherever the core ends.  RUN_API equ n
;  after the include is the API version it needs, in its header (a core
;  older than that refuses it); without one, mkrun.py writes UI_API.
;
;  Entry: the first byte of the program, called near with DS = ES = SS =
;  CS = the UI segment, DF clear, SI -> the argument (ASCIIZ, "" if none:
;  for Write, the file to open).  Return with RET, AX = exit code.  The
;  stack is the core's (about 3 KB is free); keep big buffers in BSS or
;  in blocks from UI_ALLOC.
;  Until it calls UI_SETREDRAW, the caller's redraw routine stays (API 5):
;  a program that only opens a window over the Executive (the calculator)
;  never sets one, and the Executive is redrawn under it after the saver.
;  Exit code 0FFFFh says the screen is as the program found it (API 5):
;  the Executive doesn't read the directory and redraw.
;
;  Conventions for every call below:
;   * all registers and DS/ES are preserved except the outputs listed;
;   * DF stays clear; CF is an output only where it is listed;
;   * screen positions are BX = byte column (0-79) and DX = pixel row
;     (0-399).  Text rows must be multiples of 4 (the glyph blitter
;     writes the four interleaved banks with fixed offsets);
;   * AH = 00h draws text normally, FFh inverse (it is XORed in);
;   * callbacks (list rows, window contents, key handlers, redraw) may
;     change any register except segment registers.
; =====================================================================

        cpu     286
UI_API      equ 6                       ; this file's API version (2: UI_FONT, 3: UI_SAVER,
                                        ;  4: UI_SAVER's tidying, 5: the caller's redraw
                                        ;  routine stays, exit code 0FFFFh, 6: W_FLAGS,
                                        ;  windows that move and close, EV_MOVED)

; ---- the jump table: entry n at offset 3n ---------------------------
UI_VERSION  equ  0 * 3  ; -> AX = API version, BX = Lodestone version (BH major, BL minor
                        ;  in the high nibble, patch in the low: 0030h = 0.3),
                        ;  CX = the UI block's own size in paragraphs (without
                        ;  the .RUN), DX = the mouse's port (0 = no mouse),
                        ;  SI = the paragraphs it keeps while a DOS program
                        ;  runs (the Executive's directory goes to the program)
UI_CLS      equ  1 * 3  ; clear the whole screen
UI_FILL     equ  2 * 3  ; DX = y, CX = rows, BX = col, BP = width in bytes, AL = byte
UI_HLINE    equ  3 * 3  ; DX = y, BX = col, CX = width in bytes: a solid rule
UI_VLINE    equ  4 * 3  ; AX = pixel x, DX = y, CX = height
UI_DOTS     equ  5 * 3  ; DX = y, BX = col, CX = width: a dotted rule
UI_INVERT   equ  6 * 3  ; DX = y, CX = rows, BX = col, BP = width: XOR FFh
UI_PUTC     equ  7 * 3  ; AL = char, BX = col, DX = y, AH = mask
UI_PUTS     equ  8 * 3  ; SI = ASCIIZ, BX = col, DX = y, AH = mask -> SI past the NUL
UI_PUTSN    equ  9 * 3  ; SI = text, CX = count, BX = col, DX = y, AH = mask
                        ;  (control characters show as glyphs; clipped at col 80)
UI_CENTER   equ 10 * 3  ; SI = ASCIIZ, DX = y, AH = mask: centred on the screen
UI_BOX      equ 11 * 3  ; BX = col, DX = y, CX = width in bytes, BP = height: 1-px frame
UI_STRLEN   equ 12 * 3  ; SI = ASCIIZ -> CX = length
UI_SBSTR    equ 13 * 3  ; append ASCIIZ SI at DI -> DI advanced (no NUL written)
UI_SBU16    equ 14 * 3  ; append AX (unsigned decimal) at DI -> DI
UI_SBU32    equ 15 * 3  ; append CX:AX (unsigned decimal) at DI -> DI
UI_SBDATE   equ 16 * 3  ; append DOS date AX as "5-Oct-26" at DI -> DI
UI_SBTIME   equ 17 * 3  ; append DOS time AX as "9:41 pm" at DI -> DI
UI_SBHEX4   equ 18 * 3  ; append AX as 4 hex digits at DI -> DI
UI_SBERR    equ 19 * 3  ; append the message for DOS error AX at DI -> DI
                        ;  (error 83 says what the disk said, from INT 24h)
UI_EVENT    equ 20 * 3  ; wait for an event -> AX = BIOS key (AL = ASCII,
                        ;  AH = scan code), or AX = EV_CLICK with BX = x, CX = y.
                        ;  The pointer shows while it waits.  The clock in the
                        ;  title bar and the screen saver are handled here.
                        ;  The top window's title strip too (API 6, W_FLAGS):
                        ;  a press there drags a WF_MOVE window, CODE-F7 moves
                        ;  it with the arrow keys, then AX = EV_MOVED; a click
                        ;  on a WF_CLOSE window's close box gives K_ESC
UI_POLL     equ 21 * 3  ; the same without waiting: CF set if nothing happened
                        ;  (then AX, BX, CX are unchanged).  The pointer stays hidden.
UI_TICK     equ 22 * 3  ; -> AX = BIOS tick count (18.2 per second)
UI_SETREDRAW equ 23 * 3 ; SI = routine that redraws the whole screen (after the
                        ;  screen saver or a DOS program), 0 = none
UI_SCREEN   equ 24 * 3  ; SI = title: clear the screen, title bar with the date
                        ;  and time (kept up to date by UI_EVENT), rule under it
UI_BAND     equ 25 * 3  ; SI = line 1, DI = line 2 (0 = blank): the inverse
                        ;  prompt band at the bottom.  The strings must stay put.
UI_MSG      equ 26 * 3  ; SI = message: in the band until a key or click, then
                        ;  the band as it was -> AX = the key (EV_CLICK for a
                        ;  click, with BX, CX as UI_EVENT gives them)
UI_ASK      equ 27 * 3  ; SI = line 1 ("Quit: Confirm to save and exit"): CF clear
                        ;  for Return or a click on the band, CF set for ESC
UI_WOPEN    equ 28 * 3  ; SI = window (W_* below): save what is underneath,
                        ;  draw the frame and title, call its draw routine
UI_WCLOSE   equ 29 * 3  ; close the top window, restoring the screen under it
UI_HELP     equ 30 * 3  ; SI = key table, DI = title: a window with the table's
                        ;  help lines; any key or click closes it
UI_DISPATCH equ 31 * 3  ; SI = key table, AX = key: call its handler (AX = key)
                        ;  and return CF clear (registers as the handler left
                        ;  them); CF set if the key isn't in the table
UI_LVDRAW   equ 32 * 3  ; BX = list (LV_* below): draw the visible rows
UI_LVKEY    equ 33 * 3  ; BX = list, AX = key: Up, Down, PgUp, PgDn, Home, End,
                        ;  and a letter jumps to the next name starting with it
                        ;  -> CF set if not a list key
UI_LVCLICK  equ 34 * 3  ; BX = list, CX = y -> CF set if outside the rows; else
                        ;  AX = 1 if the selected row was clicked again, 0 if
                        ;  another row (now selected)
UI_LVSET    equ 35 * 3  ; BX = list, AX = item: select it (scrolls, redraws)
UI_EDIT     equ 36 * 3  ; line editor: SI = ASCIIZ buffer, BP = most characters,
                        ;  BX = col, DX = y, CX = field width in columns.  The
                        ;  cursor starts at the end; a character typed first
                        ;  replaces the text, an editing key keeps it
                        ;  -> AX = the key that ended it (Return, ESC, Tab,
                        ;  Shift-Tab, Up, Down, PgUp, PgDn, F1, a CODE key) or
                        ;  EV_CLICK (BX = x, CX = y).  In a window that moves
                        ;  (API 6), the field moves with it and editing goes on
UI_FORM     equ 37 * 3  ; SI = form (F_* below): a window with the fields;
                        ;  Return goes to the next field and confirms on the
                        ;  last -> CF set if cancelled with ESC
UI_ALLOC    equ 38 * 3  ; BX = paragraphs -> AX = segment (CF: AX = 8 and BX =
                        ;  largest free; or a program already has 16 blocks).
                        ;  Blocks still allocated are freed when the .RUN ends.
UI_FREE     equ 39 * 3  ; ES = a block from UI_ALLOC
UI_RUN      equ 40 * 3  ; run a DOS program (.COM or .EXE; a .RUN gives error 11):
                        ;  SI = path, DI = command tail (ASCIIZ)
                        ;  -> AX = its exit code; CF if it couldn't run (AX = error).
                        ;  Text mode while it runs, then the redraw routine.
UI_FINDAPP  equ 41 * 3  ; SI = file name ("WRITE.RUN") -> SI = path where it is
                        ;  (current subject, then the root); CF if nowhere
UI_CRITERR  equ 42 * 3  ; -> AX = the last INT 24h error (DI + 1; 0 = none), cleared
UI_BEEP     equ 43 * 3  ; a short beep
UI_KEYSHIFT equ 44 * 3  ; -> AL = BIOS shift state (bit 0/1 Shift, 2 Ctrl, 3 CODE)
UI_FONT     equ 45 * 3  ; the screen font (API 2).  AL = 0 -> SI = its file name
                        ;  ("TERMINUS.FNT"; "" = GRiD's, built in).  AL = 1: SI =
                        ;  FONT_BYTES of glyphs (8x16, codes 32-127, 16 bytes
                        ;  each, top row first), DI = its name ("" = built in):
                        ;  that is the font from now on.  Nothing is redrawn;
                        ;  the caller redraws its screen.  At start-up the core
                        ;  takes the font named by FONT= in \LODE.INI.
UI_SAVER    equ 46 * 3  ; the screen saver's delay (API 3).  AL = 0 -> AL =
                        ;  minutes (0 = never), AH = 1 if it doesn't tidy the
                        ;  disks (API 4); AL = 1: BL = minutes (at most 30;
                        ;  0 = never); AL = 2: BL = 1 not to tidy, 0 to tidy
                        ;  (API 4).  At start-up the core takes SAVER= in
                        ;  \LODE.INI (5 without it), and TIDY=0.
UI_LAST     equ 46 * 3
FONT_BYTES  equ 96 * 16                 ; a font file (.FNT): exactly this long

EV_CLICK    equ 0FF01h                  ; a left-button press (BX = x, CX = y)
EV_MOVED    equ 0FF02h                  ; the top window was moved (API 6): its
                                        ;  W_COL and W_Y are new, and it is drawn there

; ---- keys (BIOS INT 16h codes; CODE is the Alt key) -------------------
; The core reads keys with INT 16h AH=10h: the 1520's BIOS gives CODE with
; punctuation, Return, ESC and Backspace (CODE-?, CODE-Return, CODE-ESC)
; only that way.  Keypad Enter and / and the grey keys come as AH=00h
; would return them.
; In a key table an entry with AL = 0 matches by scan code (AL of the key
; 0 or E0h); any other entry matches the ASCII code in AL.
K_NONE      equ 0FFFFh                  ; a help line with no key
K_ENTER     equ 1C0Dh
K_ESC       equ 011Bh
K_TAB       equ 0F09h
K_SPACE     equ 3920h
K_BTAB      equ 0F00h                   ; Shift-Tab
K_BKSP      equ 0E08h
K_UP        equ 4800h
K_DOWN      equ 5000h
K_LEFT      equ 4B00h
K_RIGHT     equ 4D00h
K_HOME      equ 4700h
K_END       equ 4F00h
K_PGUP      equ 4900h
K_PGDN      equ 5100h
K_INS       equ 5200h
K_DEL       equ 5300h
K_CLEFT     equ 7300h                   ; Ctrl-Left
K_CRIGHT    equ 7400h
K_CHOME     equ 7700h
K_CEND      equ 7500h
K_CPGUP     equ 8400h
K_CPGDN     equ 7600h
K_F1        equ 3B00h
K_F2        equ 3C00h
K_F5        equ 3F00h
K_CODE_F7   equ 6E00h                   ; move the top window (API 6)
K_CODE_ENTER equ 1C00h
K_CODE_ESC  equ 0100h
K_CODE_A    equ 1E00h
K_CODE_B    equ 3000h
K_CODE_C    equ 2E00h
K_CODE_D    equ 2000h
K_CODE_E    equ 1200h
K_CODE_F    equ 2100h
K_CODE_G    equ 2200h
K_CODE_H    equ 2300h
K_CODE_I    equ 1700h
K_CODE_J    equ 2400h
K_CODE_K    equ 2500h
K_CODE_L    equ 2600h
K_CODE_M    equ 3200h
K_CODE_N    equ 3100h
K_CODE_O    equ 1800h
K_CODE_P    equ 1900h
K_CODE_Q    equ 1000h
K_CODE_R    equ 1300h
K_CODE_S    equ 1F00h
K_CODE_T    equ 1400h
K_CODE_U    equ 1600h
K_CODE_V    equ 2F00h
K_CODE_W    equ 1100h
K_CODE_X    equ 2D00h
K_CODE_Y    equ 1500h
K_CODE_Z    equ 2C00h
K_CODE_HELP equ 3500h                   ; CODE-? (CODE-/)

; ---- key table: entries of 3 words, ending with a 0 word -------------
;        dw key, handler, help line (ASCIIZ, 0 = none)
%define KEY(k, h, t) dw k, h, t

; ---- window: W_SIZE bytes ---------------------------------------------
W_COL       equ 0                       ; byte column
W_Y         equ 2                       ; pixel row (multiple of 4)
W_W         equ 4                       ; width in bytes
W_H         equ 6                       ; height in pixels
W_TITLE     equ 8                       ; ASCIIZ (0 = no title strip)
W_DRAW      equ 10                      ; contents (BX = the window), 0 = none;
                                        ;  AX = EV_MOVED when drawn because of a move
W_FLAGS     equ 12                      ; WF_* (API 6; a .RUN for API 5 or older
                                        ;  has 12-byte windows: no flags)
W_SIZE      equ 14
W_TOP       equ 24                      ; first text row inside a titled window
WF_MOVE     equ 1                       ; the user may move it by its title strip
WF_CLOSE    equ 2                       ; a close box at the title strip's right
                                        ;  end: a click on it is K_ESC

; ---- list view: LV_SIZE bytes -----------------------------------------
LV_Y        equ 0                       ; first row's pixel y (multiple of 4)
LV_ROWS     equ 2                       ; rows shown (16 pixels each)
LV_N        equ 4                       ; number of items
LV_SEL      equ 6                       ; selected item
LV_TOP      equ 8                       ; first item shown
LV_DRAW     equ 10                      ; row: AX = item, DX = y, CL = mask (00h or
                                        ;  FFh, the band is already filled with it)
LV_CHG      equ 12                      ; after the selection moves (0 = none)
LV_COL      equ 14                      ; the highlight band: first column
LV_W        equ 16                      ;  and width in bytes
LV_NAME     equ 18                      ; AX = item -> SI = its name, for
                                        ;  type-to-find (0 = none)
LV_SIZE     equ 20

; ---- form ---------------------------------------------------------------
F_TITLE     equ 0                       ; window title
F_PROMPT    equ 2                       ; band line ("Find: Fill in form and confirm")
F_W         equ 4                       ; window width in bytes
F_LW        equ 6                       ; label column width (characters)
F_N         equ 8                       ; number of fields
F_FIELDS    equ 10                      ; then F_N fields of FL_SIZE bytes:
FL_LABEL    equ 0                       ;  ASCIIZ
FL_TYPE     equ 2                       ;  FT_TEXT or FT_CHOICE (+ width << 8 for text)
FL_DATA     equ 4                       ;  text: the buffer; choice: a byte (option number)
FL_EXTRA    equ 6                       ;  text: most characters; choice: the options,
                                        ;  ASCIIZ one after another, then a 0 byte
FL_SIZE     equ 8
FT_TEXT     equ 1
FT_CHOICE   equ 2

; ---- screen -------------------------------------------------------------
SCR_TITLE_Y equ 0                       ; title bar
SCR_TOP     equ 24                      ; first free row under the title rule
SCR_BAND_Y  equ 360                     ; the prompt band (to 399)
