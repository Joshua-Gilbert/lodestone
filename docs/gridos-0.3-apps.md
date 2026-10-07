# Grid-OS 0.3 — the UI core and the first programs (2026-10-05)

0.3 starts the application suite. The Executive now sits on a shared UI core (our COMMON.SHR), and programs written for it are `.RUN` files that load next to it and call it with near calls. The first two are **System** (GRiD's "Usage") and **Write** (after GRiDWrite). Everything here is tested in emulation; nothing has been on the 1520 yet. 0.3 is built on 0.2.3, so it keeps 0.2.3's one-sector-at-a-time retry on read errors.

## The UI segment
- **The finding that shaped it:** the kernel's segment (0060h) was 50 KB full. Code, BSS and the Executive's lists ended at C350h, which left too little room for programs in the same segment.
- **What changed:** `GRIDOS.SYS` now has two parts.
  - The kernel stays at 0060:0000.
  - The UI section (`section ui`, `vstart=0`) is copied at boot into a DOS block of its own (owner 8, name `UI`), just above the root PSP. The root process (the Executive) runs there on its own 2.5 KB stack.
  - The UI talks to the kernel only through INT 21h:
    - **F0h AL=2/3** lends the disk cache's memory for windows' save-under, and gives it back;
    - **F0h AL=4** tells the kernel where the UI block moved (below).
- **NASM detail:** `alignb` in a `vfollows` nobits section makes NASM's bin output fail ("cannot mix real and virtual attributes"). `uibss` therefore uses a `ualignb(n)` macro instead.
- **Memory:**

  | | 0.2.2 | 0.3 |
  |---|---|---|
  | Kernel (resident) | — | 30.6 KB |
  | UI block: core + Executive + font + stack | (in the kernel's 50 KB) | 18.0 KB |
  | UI block: the Executive's directory | (in the kernel) | 7.5 KB |
  | Free while the Executive waits | — | 564.4 KB |
  | **A DOS program gets (MEMSZ.COM)** | **570.7 KB** | **571.5 KB** (569.4 KB with 0.3.1's INT 33h mouse, 568.7 KB with 0.3.2's File form, 565.9 KB with 0.3.3's file commands) |

  - While a DOS program runs, the UI block shrinks to `ui_keep_end`, so the Executive's 7.5 KB directory buffer goes to the program. The Executive reads the directory again afterwards anyway.
  - The core added about 4.5 KB of code, but the lent directory more than pays for it.

## The core (`src/UICORE.INC`, API in `src/UIAPI.INC`)
- **Jump table at offset 0:** 45 entries of 3-byte `jmp`, numbered in UIAPI.INC and checked at assembly time (an entry out of order is an error).
- **One register convention:**
  - every call keeps all registers except its listed outputs;
  - DS = ES = CS = the UI segment;
  - DF is clear;
  - callbacks may change anything except segment registers.
- **What it provides:**
  - **Events:** `UI_EVENT` / `UI_POLL` cover keys, the serial mouse (the pointer shows only while waiting), the title-bar clock and the 5-minute screen saver.
  - **Redrawing:** after the saver or a DOS program, the program's redraw routine (`UI_SETREDRAW`) runs, then the core redraws the band and any open windows over it.
  - **Drawing:** fill, rules, box, invert, glyphs. `UI_PUTSN` is a row blitter that sets up the screen segment and cell address once per row.
  - **Text builders:** strings, decimal, hex, dates, times.
  - **Error text:** `UI_SBERR` turns a DOS error into words, using what INT 24h said for disk errors.
  - **Screen chrome:** title bar with date and time, and the two-line inverse prompt band. `UI_MSG` shows "… / Press any key". `UI_ASK` asks GRiD's way: "Quit: Confirm to save and exit" / "Press RETURN to confirm or ESC to cancel".
  - **Windows:** up to 4 deep, with save-under in the lent cache memory.
  - **Help:** `UI_HELP` builds the window from a key table, so the help and the keys can't drift apart.
  - **Key tables:** `dw key, handler, help line`; `UI_DISPATCH` runs the handler.
  - **List view:** `UI_LV*` handles arrows, PgUp/PgDn, Home/End, type-to-find, and clicks. A second click on the selected row confirms. The keypad works with NumLock, as in 0.2.
  - **Line editor:** `UI_EDIT`. A character typed first replaces the old value; an editing key keeps it.
  - **Forms:** `UI_FORM` puts text and choice fields in a window. Return goes to the next field and confirms on the last; CODE-Return or a click on the band confirms; ESC cancels. Choices are shown GRiD-style, all options with the chosen one inverse.
  - **Memory:** `UI_ALLOC` / `UI_FREE`. Blocks a program leaves allocated are freed when it ends.
  - **Programs:**
    - `UI_RUN` runs a DOS program: text mode, mouse off, the kernel's INT 24h, DTA kept, then a redraw. It refuses `.RUN` files, which EXEC would take for a .COM.
    - `UI_FINDAPP` looks in the current subject, then the root.
    - `UI_CRITERR` returns the last INT 24h error.
- **INT 24h:** while the UI runs, its own handler fails the call and remembers why. A missing or write-protected floppy gives a message in the band, not a text prompt on the graphics screen.
- **The screen saver moved into the core:**
  - In the Executive with no window open, it runs DEFRAG first, as before.
  - Inside a `.RUN` or with a window open, it shows only the dark clock.
  - Waking redraws whatever was on screen.

## `.RUN` programs
- **Building:** `mkrun.py` assembles the source twice, at `org 0` and at `org 1110h`, and compares the two word by word.
  - +1110h is an address inside the program: the loader adds the load offset.
  - −1110h is a near call into the jump table: the loader subtracts it.
  - Anything else is an error. A `.RUN` can therefore load wherever the core ends, and survive core rebuilds.
- **File layout:** `GRUN`, API version, image size, BSS size, the two fixup counts, then the image and the fixups.
- **Loading:**
  - the UI block grows (INT 21h 4Ah) to hold the image and BSS;
  - one read brings in image and fixups;
  - the fixups are applied, the BSS is zeroed, and the program is called near with SI = its argument;
  - the DTA is put back afterwards, the program's blocks are freed, windows closed, the cache given back, and the block shrunk.
  - The redraw routine is cleared before the program starts.
- **When something resident is in the way (a TSR):**
  - The kernel's EXEC allocates first-fit, so a TSR started from the Executive ends up right after the UI block. The block could then neither take its directory back nor grow for a `.RUN`.
  - So after every program the Executive's main loop checks that the block can grow by 16 KB (`ui_room`). If it can't, the block **moves**: a new block is allocated past the TSR and everything is copied, its own stack included. Then the kernel (F0h AL=4), INT 24h, the mouse vector and the DTA are pointed at the copy, and the old block is freed.
  - The move is done only in the main loop, where the stack holds no segment values.
- **The Executive:**
  - shows `.RUN` files as Kind "Program";
  - opens Text, Source, Batch, Settings and Profile files with `WRITE.RUN`, passing the whole path;
  - CODE-U runs System, CODE-W starts Write with a new file.

## SYSTEM.RUN — Usage (7.4 KB)
- **Layout:** topics on the left (Memory, Disks, Clock, Devices, GPIB, Display, About), details on the right. (It was 4.9 KB before Display, which brought a copy of GRiD's font: below.)
- **Memory:** read from the MCB chain the way the kernel keeps it. It shows the kernel, Executive and UI core, this program, the disk cache, any resident programs, and what a DOS program would get. That figure counts the program going and the directory being lent; it agrees with MEMSZ.COM within 1 KB. It also shows EMS and extended memory from the GRiD BIOS.
- **Disks:** label, size, free and in use for A:, and B: if there is one.
- **Clock:**
  - The date shows in full ("Sunday, 4 October 2026"); Return opens a form.
  - The date can be "5-Oct-2026", "5/10/26" or "5 october 2026"; the time "9:41 pm" or "21:41".
  - The kernel sets the RTC too.
  - A date that doesn't exist is refused, and the form comes back.
- **Devices:** CPU, 80287, BIOS date, panel type (port 7F8h), mouse port, COM and LPT ports, floppy types from CMOS.
- **GPIB:**
  - shows the built-in driver (version 1.20, INT 60h) and our address;
  - Return asks, then serial-polls addresses 0–30 and lists who answered;
  - it sends no device messages and ends with GTL to all.
  - In emulation it finds 6, 14 and 29 in 4.8 s.
- **Display:** the font in use and the fonts on the disk; Return switches (see "Switching fonts" below).
- **About:** version, DOS 3.30, UI API, and the font credit.

## WRITE.RUN — Write (8.0 KB)
- **GRiDWrite's command summary**, taken from the strings in GWRITE.RUN. Verb first: press the command, select with the cursor keys or the mouse, then confirm. CODE-B starts the selection again.

  | Command | Key | Does |
  |---|---|---|
  | Begin | CODE-B | restart the selection |
  | Duplicate | CODE-D | duplicate selected text (then point and confirm) |
  | Erase | CODE-E | erase selected text |
  | Find | CODE-F | form: text, Match (Independent of case / Exactly), Direction |
  | Jump | CODE-J | to a line |
  | Move | CODE-M | move selected text (then point and confirm) |
  | Options | CODE-O | automatic indent; tab stops 8 / 4 / 2 |
  | Quit | CODE-Q | save and exit (asks for a name for a new file; .TXT added) |
  | Substitute | CODE-S | form: search, replace, match, direction, Verification (Y / N / S single / A all / ESC) |
  | Transfer | CODE-T | Save, Write to a file, Include a file |
  | Usage | CODE-U | characters, lines, room left |
  | Cancel | CODE-ESC or ESC | exit without saving |

- **GRiD's own wording in the band:** "Erase: Make a selection and confirm", "Move: Point to destination and confirm", "Find: Confirm for next occurrence", "No further matches to text specified", "Number of substitutions: n".
- **The text:**
  - a gap buffer in a block of its own (up to 64 KB);
  - LF inside; CR LF on disk, with a CR held over between 1 KB chunks; reading stops at ^Z;
  - tabs are kept and shown to the next stop;
  - long lines scroll sideways in steps of 20 columns.
- **Saving:** writes `NAME.$$$` beside the file, then deletes the old one and renames. A failed save (say, a write-protected disk) leaves the old file and says why. Saving to a name that is itself `.$$$` uses `.$$1` for the temporary file.
- **The screen:**
  - drawn from a shadow copy, so only rows that differ are redrawn;
  - a typed character rebuilds only its own row;
  - Return, scrolling and selections rebuild all rows;
  - the cursor is the lower half of the cell (insert) or the whole cell (overtype; Ins switches). It was a bar under the character, but with GRiD's font (below) that bar joined the letter on the next line: l looked like T;
  - the status line shows line, column, mode and Changed.
- **Speed in emulation** (4 µs per basic block, probably slower than the real 286 for these tight loops), on a 41 KB file:

  | Key | Time |
  |---|---|
  | type a character | 7.5 ms |
  | cursor keys | about 1.5 ms |
  | Return | about 100 ms |
  | Ctrl-Home / Ctrl-End | about 0.2 s |

## GRiD's font (2026-10-06)
- Joshua asked why Grid-OS didn't use the GRiD's built-in fonts. What the 1520 has:
  - **The text-mode fonts** (4, picked with INT 15h E422h) are in the display controller. They only show in text modes and the processor can't read them, so a graphics screen can't use them.
  - **The BIOS** has only the IBM 8×8 CGA font (F000:FA6E). In mode 40h its INT 10h draws each row twice.
  - **InteGRiD's fonts**, `InterGRiD\PROGRAMS\*.TYP` on Joshua's PC: 21 bitmap fonts from 4×8 to 24×32. **TC8X16 is byte for byte the 8×16 font built into GRID.EXE**, the system font InteGRiD used on 640×400 screens.
- **The .TYP format**, decoded: an OMF object module (GRiD linked fonts into programs). Its data segment is an 8-byte header (number of characters, width, height, line height, baseline, 0, 0, 0), then the glyphs as a strike: row 0 of every character, then row 1, and so on, MSB = leftmost pixel. TC8X16 has 255 characters: two-letter control-code glyphs, ASCII, then arrows, ©, a four-glyph GRiD logo, Latin-1 letters and box drawing.
- **Now:** `src/FONT.INC` is TC8X16, made by `typfont.py` (which also draws any .TYP as a sheet). Only codes 32–127 are kept, so it costs the same 1,536 bytes as Terminus did. The Executive, the core, System, Write and DEFRAG use it.
  - The glyphs fill the 16-pixel cell (capitals rows 0–13, descenders to row 15), as on GRiD's own screens.
  - CLAUDE.COM keeps Terminus (`src/TERMINUS.INC`) for now, because its extra glyphs (●, ⎿, box corners) were drawn to match it.
  - The screen reader in the tests knows both fonts.
- **Rights:** GRiD Systems was bought by Tandy in 1988 and its products sold on after that. In the US, the design of a bitmap typeface generally isn't protected by copyright. The original .TYP files stay out of the repo; `FONT.INC` holds only the 96 glyphs. (Not legal advice.)

## Switching fonts (2026-10-06, API 2)
- **Joshua's choice:** GRiD's font stays built in, and other fonts are files.
  - A **.FNT** file is the 96 glyphs of codes 32–127, 8×16, 16 bytes each, top row first: exactly 1,536 bytes.
  - `fonts/TERMINUS.FNT` (the font 0.3 started with) is built from `src/TERMINUS.INC` by `fonts/TERMINUS.ASM`. `typfont.py X.TYP --fnt X.FNT` makes one from any 8×16 GRiD font.
- **The core:**
  - one font slot, as before;
  - `UI_FONT` (jump-table entry 45, so `UI_API` is now 2): AL = 0 gives the name in use, AL = 1 sets glyphs and a name;
  - at first start, `font_boot` reads `\GRIDOS.INI`, and a line `FONT=NAME.FNT` (any case) loads that file. Without the file, or with one that isn't exactly 1,536 bytes, GRiD's stays;
  - the saver passes `F=seg:off` to DEFRAG, which copies the font, so the tidying map matches.
- **System, Display** (a seventh topic, between GPIB and About):
  - it shows the font in use, the fonts on the disk, and two sample lines;
  - Return goes to the next font (the .FNT files in directory order, then GRiD's again) and redraws everything;
  - `GRIDOS.INI` is rewritten keeping its other lines (it's meant for more settings). An old `FONT=` line goes, and with GRiD's font and nothing else the file is deleted;
  - a write-protected disk: the font changes for now, and a message says it couldn't be saved.
  - System carries a copy of GRiD's font to switch back to (SYSTEM.RUN is 7,570 bytes; that memory is only used while System runs).
- **Cost:**
  - GRIDOS.SYS +244 bytes (30,292);
  - a DOS program gets 571.5 KB (from 571.7);
  - DEFRAG.COM +54 bytes;
  - the font file is 1,536 bytes on the disk.
- **Tests (`t_font`, 11 checks):**
  - GRiD's at the start;
  - the Display topic; Return to Terminus, with the screen redrawn in it;
  - GRIDOS.INI written, and Terminus again after a restart;
  - the saver's DEFRAG in Terminus;
  - back to GRiD's, with GRIDOS.INI deleted;
  - other INI lines kept, in any case;
  - a missing file, and a wrong-sized .FNT passed over.
- CLAUDE.COM keeps Terminus built in for now.

## The mouse for DOS programs (0.3.1, 2026-10-06)
- **Joshua found that TM5000G said "No mouse detected"**, though the mouse works in the Executive. The core had a working serial-mouse driver: it finds the mouse on COM2/COM1 and decodes its packets. But DOS programs had only the kernel's INT 33h stub, which returned AX = 0, and the core switched the mouse off before every DOS program.
- **Now the core answers INT 33h itself** (`src/MOUSE33.INC`), on the same driver. Its vector is set at start-up and again when the UI block moves past a TSR.
  - **The mouse stays off while a DOS program runs until the program asks for it** (function 0 or 21h). A program that drives COM1/COM2 itself is left alone. After the program ends, the core takes the mouse back, hides the pointer and forgets any event handler.
  - **Functions:** 00–0Ch, 0Fh, 10h, 13h–17h, 1Ah, 1Bh, 1Dh–21h, 24h, 26h. The others return with the registers unchanged.
    - Coordinates are virtual, as in Microsoft's driver: x 0–639 in every mode; y 0–199, 0–399 in mode 40h, and rows × 8 in text modes.
    - The defaults are Microsoft's too: 8 mickeys per 8 pixels across and 16 down.
    - Version 6.26, a serial mouse on IRQ 3 or 4.
  - **The pointer** is drawn the Microsoft way, (screen AND screen mask) XOR cursor mask:
    - text modes 0–3 and 7 show one inverse cell (77FFh / 7700h);
    - modes 4/5, 6 and 40h show the arrow, with function 09h shapes and hot spots;
    - when the pointer goes, any byte the program has written over since is left as it is.
  - **The event handler** (0Ch / 14h) runs after the interrupt is acknowledged, with interrupts on, and never re-entered. It is dropped if its program is no longer in memory: the owner word of that program's memory block no longer names it.
- **Cost:** GRIDOS.SYS 32,162 bytes (+1,870 with the review's fixes). A DOS program gets 569.4 KB, 2.1 KB less, because the driver stays resident while programs run. The version is now 0.3.1; System's About shows it.
- **Tests (`t_mouse`, 38 checks; `tests/M33TEST.COM` steps through the calls, `M33GFX`, `M33QUIT`, `M33HSET` and `M33HVIC` cover the review's cases):**
  - the port is left alone for MEMSZ; reset, version, show, follow, position, presses and releases, mickeys, ranges, the event handler, hide;
  - a cell the program wrote over stays as written; mode 4's arrow drawn and taken away;
  - the program ends with the pointer on and a handler set, and the Executive and its mouse are fine;
  - with no mouse, reset returns 0;
  - **TM5000G:** "Mouse support enabled.", "Mouse: ON", and a click on Configure Modules opens it.
  - The TSR test also checks that INT 33h follows the UI block.
  - the graphics pointer bit for bit against the masks (mode 40h at three places with a hot spot, mode 6 clipped, mode 4 with a hot spot);
  - a program that ends inside its handler, a handler left behind under the shell, a packet while a handler is being set.
- **Review (a Fable agent, 2026-10-06):** 6 findings, all confirmed and fixed, each with a test that fails on the code before:
  - **DF:** `int33_ui` didn't clear the direction flag, so a program calling with DF set made the reset write 138 bytes backwards over the Executive's row table (fn 09h, 16h and 17h too). Now `cld` on entry.
  - **A program ending inside its event handler** left `m33_busy` set, which silenced every later program's handler. It's cleared when a program ends and at a reset.
  - **A handler left behind under the shell** (GRIDCMD → a program that sets one and ends without a reset → the next program loaded at the same segment) was called inside the new program: the owner check can't tell two programs at one segment apart. Now the kernel tells the core when a program ends (`ui_progend` → `m33_gone`), and that program's handler goes. A TSR's stays.
  - **Setting a handler raced the mouse:** INT 21h AH=62h turns interrupts on, and a packet then found the new handler with the old owner (0) and dropped it. The owner is asked first, and owner 0 means none. pcemu now has the 1520's reset jump at FFFF:0, which made this visible.
  - **The hot spot in modes 4/5** was taken in physical pixels; Microsoft's masks and hot spot are in virtual pixels (one bit each).
  - **With no mouse**, calls other than the resets drew a pointer or reported a driver; now they return unchanged.
  - Not changed: modes 48h/74h (the 1520's other 640 × 400 modes) get no pointer and a 200-line range. TM5000G's own menus call hide twice when left by a key and show once, so its pointer stays hidden after the first key choice (Microsoft's driver counts the same way: TM5000G's bug, `ui.c`).
- **On the 1520, still to see:** the pointer on the plasma in TM5000G's text menus and in its CGA graph screen.

## The File form (0.3.2, 2026-10-06)
- **Joshua's requests:**
  - change devices in the Executive (his 1520 has an external B: drive);
  - Tab between Device, Subject and Title, "kind of GMANAGER style … but for sure allow tab";
  - drop CODE-R (restart) and CODE-D (restart into the EPROM): CTRL-ALT-DEL restarts, and the code costs memory.
- **GRiD's File form, from GEXEC's own help:** "Press the Arrow keys to select an item. Press RETURN to move the outline to the next item in the form." The items are Device, Subject, Title and Kind. GRiDManager lists titles or subjects in columns.
- **Now:**
  - The form under the list has Device, Subject, Title and Kind (with size and date). A box outlines the current item.
  - The list holds the outlined item's choices:
    - Device: the floppy drives the BIOS reports (A:, B:);
    - Subject: Root and every directory of the drive, depth first, by name, indented by level, with dates;
    - Title: the files of the subject. Subjects no longer appear in the file list, and ".." is gone.
  - Arrow keys (Left and Right too, in Device and Subject) choose. The choice takes effect at once: INT 21h 0Eh, or CHDIR, and the form follows.
  - Tab and Shift-Tab move the outline: Title, Device, Subject, round. In Device and Subject, Return moves to the next item and ESC goes back to Title. On Title, Return opens, as before.
  - A click on an item outlines it. A second click on a choice moves on.
  - If nothing changed, Title comes back with the same file chosen.
  - The band says "Device: Select item and confirm" or "Subject: Select item and confirm", in GRiD's wording.
- **Subjects are read when Subject is outlined,** into the directory buffer (`entries`, 14 bytes each). It is lent to DOS programs, so the list costs no resident memory. At most 2 per list entry (480), 5 levels deep. A disk that can't be read leaves Root alone, with "Can't read the disk: …" in the band.
- **Things that stay on the start-up disk** (INT 21h 3305h):
  - `UI_FINDAPP` looks in the subject, then in the root of the disk Grid-OS started from. So SYSTEM, WRITE and CLAUDE are found while B: is shown.
  - System's Display lists the fonts, and writes GRIDOS.INI, on the start-up disk ("Fonts on the start-up disk:").
  - The saver runs DEFRAG only from the current drive's root, so a data disk on B: isn't tidied unless it has DEFRAG.
- **Cost:** GRIDOS.SYS 32,842 bytes (+680 since 0.3.1; CODE-R and CODE-D saved about 150). A DOS program gets 568.7 KB (0.7 KB less than 0.3.1): the Executive's code (now 4.2 KB) stays resident while DOS programs run.
- **Tests (`t_form`, 26 checks; `t_exec` reaches subjects through the form):**
  - titles only, Title outlined; the form's values;
  - Tab to Device (the drives, the prompt), to Subject (the tree), back to Title with the same file; Shift-Tab; ESC;
  - a subject two levels down; a subject with an extension;
  - B: through Device, Return to its subjects and titles, a text file on B: in Write;
  - CODE-U from B:; fonts and GRIDOS.INI on A:;
  - clicks on items and choices; Left and Right in Device;
  - help (Tab, no CODE-R or CODE-D); CODE-R and CODE-D do nothing;
  - B: with no disk (pcemu's `Floppy.empty`); one drive.

## File commands (0.3.3, 2026-10-06)
- **Verb first, as in GRiDManager:** choose a title, press the command, fill in the form, and confirm.

  | Key | Command | Form |
  |---|---|---|
  | CODE-C | Copy | Device, Subject and Title of the copy (this drive, subject and title to start with) |
  | CODE-M | Move | Device and Subject |
  | CODE-R | Rename | the new title, in the same subject |
  | CODE-D | Delete (erase) | a question first |

  Joshua's keys: C for Copy, D for Delete, M for Move, R for Rename. The command prompt moved from CODE-C to **CODE-P**.
- **Copy** writes the copy under a temporary name first, and renames it only once it is complete. So a full or write-protected disk leaves what was there alone, and the date and time go with the copy.
- **Move** on the same drive only moves the directory entry. To the other drive it copies, then erases; a read-only file is refused.
- **A title that is already there** is replaced only after confirming.
  - The Subject is typed as a path from the root (`\` for Root, `\DOS.330\DEEP`).
  - A title can't contain `\ : * ?`; a subject can't contain `: * ?`.
  - Copy or Move onto the file itself is refused however it is spelled; the kernel cuts names to 8.3, so "NOTES.TXTX" is NOTES.TXT.
- **Erase** asks first, and read-only files stay.
- **Core, through the screen saver:** questions, forms and messages keep their band. The core remembers the waiting band (`held1`/`held2`, `hold_band`) and `redraw_all` puts it back. DEFRAG doesn't start while a question waits; the saver shows only the dark clock.
- **Kernel, `buf_put`:** a sector write that fails no longer leaves the change in the buffer. Before, a later write to the same sector carried it to the disk: for example, a delete refused by a write-protected disk happened after all once the tab was off.
- **Cost:** GRIDOS.SYS 35,360 bytes. A DOS program gets 565.9 KB, 2.8 KB less than 0.3.2.
- **Tests:**
  - **`t_files`:** each command and its form, replace-or-not, read-only files, a write-protected disk, and copies between A: and B: checked byte for byte.
  - **`t_file_safety`:** the review's cases:
    - one file however spelled;
    - the saver during a question and during a form;
    - forbidden characters;
    - the deepest subject (65 characters);
    - Move from a write-protected disk;
    - a failed directory write not carried to the disk later;
    - a failed rename after replacing ("Copy kept as …TMP").
  - With all of them, apps has 237 checks; kernel 60, DEFRAG 33, Claude link 21 and HEADCLN 9 still pass.

## Review and tests
- **An independent review** of the new code found 14 issues; all are fixed and the confirmed ones have tests:
  - **The TSR case:** the empty list and .RUNs that wouldn't load. Fixed with `ui_room` and the move.
  - **Backward Substitute** re-matching its own replacement text.
  - **Write's cursor** drawn on the wrong row after a full redraw.
  - **Ins** leaving the old cursor shape behind.
  - **Register-contract slips:** `UI_SBU16`'s AX, `UI_EVENT` / `UI_EDIT` / `UI_LVCLICK` registers.
  - **Window and saver details:** the redraw routine not cleared before a `.RUN`, a form outline left behind after the saver, System's band after the saver, a fifth window unbalancing closes, and a message's Return swallowed after the saver.
  - **Smaller ones:** keypad arrows with NumLock, `UI_RUN` with a `.RUN` path, date numbers over 255, and saving to `X.$$$`.
- **A second review (2026-10-06):** a panel of six reviewers (Fable), one per area, hunting classic bugs. About 40 findings, almost all confirmed in the emulator. Fixed, with tests for the serious ones:
  - **A click above an open form hung the machine:** a borrow went unchecked before a `DIV`, which faulted. Every form was affected (Write's Find/Substitute/Jump/Save, System's clock).
  - **Write's PgDn, PgUp and Jump didn't redraw the text:** `update` compared the view with itself. It now compares with the view last drawn.
  - **A damaged `.RUN` could wreck the core:** the fixup counts and offsets weren't checked, so a bad header rewrote the jump table or crashed. Now it's "Not a program".
  - **`UI_RUN` with a `.RUN` still ran it:** the `'R.'` constant had its bytes the wrong way round for the memory word ".R".
  - **Re-entering a form field reset it:** after a key the form ignores (PgDn, Ins, F2 …) or a click in the field, the next letter wiped the field. The editor now goes on where it was.
  - **Subjects with an extension (`DOS.330`) couldn't be opened:** CHDIR got only the first 8 characters. It now gets NAME.EXT, and a failure is said in the band.
  - **Setting the clock forward started the saver at once.** The core now takes a tick jump of over 2 s between polls as activity.
  - **System's band** was blank at the start and after the clock form. **A bad time** no longer leaves a new date set. **Numbers** are at most 4 digits. Trailing text, "13 pm" and wrong month names are refused.
  - **The Executive:** "X.COM ended" and the selection are kept when the UI block moves past a TSR. Directory read errors and more than 240 entries are said in the band. The path buffer for Write held 80 bytes, but a deep subject needs 82. An unknown short kind showed stray spaces.
  - **Write:**
    - a Substitute that doesn't fit is refused before the match is erased;
    - a click ends Found mode;
    - a read-only target is left alone, and the temporary file goes;
    - a CR that doesn't fit at the end of a file fails the load;
    - a new file's name is forgotten if its save fails.
  - **Core details:**
    - drawing with a count of 0 (or off the screen) is clipped (`LOOP` with CX = 0 ran 65,536 times);
    - the pointer and clicks read x and y from the same mouse packet;
    - `UI_SBERR` ignores codes ≥ 256, and error 39 is "Disk is full";
    - a 19-line help window no longer covers the title bar;
    - `UI_LVCLICK` returns AX, not just AL;
    - a form with no window slot left is refused;
    - a field is shown from its start when left;
    - `UI_ALLOC` refuses a 17th block (it couldn't be freed for the program), with NALLOC raised from 8;
    - the mouse's line (1200 baud, 7N1) is set again after a DOS program.
  - The fixes cost 434 bytes: GRIDOS.SYS is 30,048 bytes, and a DOS program gets 571.7 KB.
  - **Left for later (kernel, outside this change):**
    - `same_disk` compares only the BPB, so two freshly formatted disks with the same label and serial number are taken for one;
    - `f_3B` cuts the current-directory string at 66 characters;
    - a failed mount returns an error without INT 24h.
  - **Not changed:** System takes the 80287 from INT 11h (SETUP's CMOS bit) rather than probing it, and Write's "Write to a file" overwrites without asking.
- **`tests/test_apps.py` — 122 checks** (160 with 0.3.1's `t_mouse`, 186 with 0.3.2's `t_form`, 237 with 0.3.3's `t_files` and `t_file_safety`, below)**:**
  - **UITEST.RUN** exercises the API: lists, forms, ask, help, errors, BSS zeroing, exit code, cleanup to the paragraph, and a file that isn't a `.RUN`.
  - **System:** every topic, setting the clock, a bad date, the GPIB scan.
  - **CODE-?, CODE-Return, CODE-ESC** in the Executive, a form, System and Write, as the 1520's BIOS delivers them (below).
  - **Write:** every command; the saved bytes; Cancel; a new file; a 41 KB file round trip; a write-protected disk; Include; a mouse click; backward Substitute.
  - **Memory:** MEMSZ before and after; a TSR after the UI block; the screen saver inside Write.
  - **The review's cases:**
    - a click above a form;
    - a field kept after PgDn;
    - `UI_RUN` on a `.RUN`;
    - two damaged `.RUN` headers;
    - System's band;
    - the clock set forward;
    - a bad time with a new date;
    - five bad dates and times;
    - PgUp, PgDn and Jump redraws;
    - a click after Find;
    - a subject with an extension;
    - 245 files in a subject;
    - the message and selection after a TSR.
    With the old core, these fail.
  - With `shots`, screenshots go to `screens/0.3`.
- **The other suites still pass:** kernel 60, DEFRAG 33, HEADCLN 9, Claude link 21. The Claude-link check now expects INT 24h to be the UI's handler.
- **pcemu changes:**
  - Pending IRQs are delivered like a PIC: all of them, highest priority first. Before, only IRQ 0 was delivered per step, and the mouse starved during long INT 13h calls.
  - INT 1Ah AH=03h/05h now set the emulated RTC.
  - INT 16h behaves like the 1520's BIOS for the "enhanced-only" keys (below).
- **Found on the 1520 (2026-10-06): CODE-? did nothing.**
  - The 1520's BIOS (GRiD's Phoenix 286 BIOS of 10/25/89; source in github.com/philip-searle/gridcase-bios) stores CODE (Alt) with most punctuation, Return, ESC and Backspace as *enhanced-keyboard* keys: scan code plus F0h, e.g. CODE-? = 35F0h.
  - INT 16h AH=00h/01h skip such keys, and AH=01h even removes them from the buffer. Only AH=10h/11h return them, as 3500h. 0.2's Executive had the same gap; its CODE-? never worked on the machine either.
  - **Fix:** the core reads keys with AH=11h/10h (`read_key`) and maps keypad Enter and / and the grey keys' E0h back to what AH=00h gives. So CODE-?, CODE-Return and CODE-ESC all work now.
  - pcemu now models the BIOS here, and the tests press these keys; with the old core, 7 checks fail.
- **New test programs:**
  - **MEMSZ.COM** prints the memory a program got.
  - **TSR.COM** stays resident with 512 bytes.

## Files
- **The OS:**
  - `src/UIAPI.INC`, `src/UICORE.INC`, `src/EXEC.INC` (rewritten; `EXECRUN.INC` merged into it and the core);
  - `src/GRIDOS.ASM` (the sections, `ui_load`, `run_ui`);
  - `src/KCORE.INC` (F0h 2–4), `src/KPROC.INC` (the root restart).
- **Programs:**
  - `apps/SYSTEM.ASM`, `apps/WRITE.ASM` → `.RUN` via `mkrun.py`;
  - `build.sh` / `BUILD.BAT` build them (BUILD.BAT needs Python for mkrun).
- **Tests:** `tests/test_apps.py`, `tests/UITEST.ASM`, `tests/MEMSZ.ASM`, `tests/TSR.ASM`.
- **The shell:** GRIDCMD's version strings say 0.3.

## For the 1520
- **Copy to the floppy:** `GRIDOS.SYS` (30,292 bytes, with the CODE-? fix, GRiD's font, the review's fixes and the font switch), `GRIDCMD.COM`, `SYSTEM.RUN`, `WRITE.RUN`, `GRIDOS.TXT`, `DEFRAG.COM` and `TERMINUS.FNT`. All are in `releases/0.3`. Copy each on its own and read it back, as usual.
- **Check:**
  - CODE-U (System), each topic, and setting the clock;
  - CODE-W (Write): type, Quit, name it;
  - open GRIDOS.TXT from the list, scroll, try Find, then ESC (Cancel);
  - run TM5000G and come back;
  - leave the machine for 5 minutes inside Write;
  - in System's GPIB topic, scan the real bus.
- **Unknown on the real machine:**
  - how fast Write's full redraws really are.

## Next
- **Programs:**
  - Term, with profiles (including the Claude Code terminal);
  - Command, on the text view;
  - the GPIB console;
  - CLAUDE as a `.RUN`.
- **Executive work (0.3 proper):** Subjects, file operations, R: and M:, settings.
- **Later:** the EMS swap of the UI block while DOS programs run, which would give programs about 17 KB more.
