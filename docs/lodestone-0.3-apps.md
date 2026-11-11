# Lodestone 0.3 — the UI core and the first programs (2026-10-05)

0.3 starts the application suite. The Executive now sits on a shared UI core (our COMMON.SHR), and programs written for it are `.RUN` files that load next to it and call it with near calls. The first two are **System** (GRiD's "Usage") and **Write** (after GRiDWrite). When 0.3 was written, everything here had been tested only in emulation. 0.3 is built on 0.2.3, so it keeps 0.2.3's one-sector-at-a-time retry on read errors.

## The UI segment
- **The finding that shaped it:** the kernel's segment (0060h) was 50 KB full. Code, BSS and the Executive's lists ended at C350h, which left too little room for programs in the same segment.
- **What changed:** `LODE.SYS` now has two parts.
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
  | **A DOS program gets (MEMSZ.COM)** | **570.7 KB** | **571.5 KB** (569.4 KB with 0.3.1's INT 33h mouse, 568.7 KB with 0.3.2's File form, 565.9 KB with 0.3.3's file commands, 565.7 KB with 0.3.4) |

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
  - With `MULTITASK=1` and window `.RUN`s open (M8c, `docs/lodestone-multitasking.md`), it stays live under them: a click on it or CODE-F6 brings it to the front, the windows staying on top, and what it draws is cut around them. Return on a text file then opens it in another Write. System still needs the whole screen: CODE-U says to close the windows first.

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
  | Transfer | CODE-T (CODE-X with `MULTITASK=1`) | Save, Write to a file, Include a file |
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

- **With `MULTITASK=1`** (M8b, `docs/lodestone-multitasking.md`), Write is a window:
  - it opens near full width (76 columns, 15 text rows), with its title, rule and status line inside, and the Executive's list around it;
  - it moves (its title strip, or CODE-F7), closes (its close box, as ESC), and is resized by its bottom-right corner or CODE-F8 and the arrows;
  - several can be open at once, each with its own file, beside the calculator and the tasks. CODE-W from any window opens another, for a new file, and Return on a text file in the Executive opens that file in another (M8c). A second one opens a little lower and to the right;
  - CODE-T is then the Tasks window's, so **Transfer is CODE-X**, and its help says so;
  - the shadow copy is in a block of its own, as the text is, so each Write takes 11,408 bytes of the UI segment.

  It is a window only when it runs as one (`MT_WIN`, F0h AL=1Dh). It still asks for UI API 4, so an older core runs it, full-screen, as does one with the switch off.

## GRiD's font (2026-10-06)
- *Since 2026-11-05 the built-in font is Lodefont (`lodestone-font.md`); GRiD's is `GRIDFONT.FNT`, on ROM 2.*
- Why Lodestone doesn't use the GRiD's built-in fonts. What the 1520 has:
  - **The text-mode fonts** (4, picked with INT 15h E422h) are in the display controller. They only show in text modes and the processor can't read them, so a graphics screen can't use them.
  - **The BIOS** has only the IBM 8×8 CGA font (F000:FA6E). In mode 40h its INT 10h draws each row twice.
  - **InteGRiD's fonts**, `InterGRiD\PROGRAMS\*.TYP`: 21 bitmap fonts from 4×8 to 24×32. **TC8X16 is byte for byte the 8×16 font built into GRID.EXE**, the system font InteGRiD used on 640×400 screens.
- **The .TYP format**, decoded: an OMF object module (GRiD linked fonts into programs). Its data segment is an 8-byte header (number of characters, width, height, line height, baseline, 0, 0, 0), then the glyphs as a strike: row 0 of every character, then row 1, and so on, MSB = leftmost pixel. TC8X16 has 255 characters: two-letter control-code glyphs, ASCII, then arrows, ©, a four-glyph GRiD logo, Latin-1 letters and box drawing.
- **Now:** `src/FONT.INC` is TC8X16, made by `typfont.py` (which also draws any .TYP as a sheet). Only codes 32–127 are kept, so it costs the same 1,536 bytes as the Terminus-derived font did. The Executive, the core, System, Write and DEFRAG use it.
  - The glyphs fill the 16-pixel cell (capitals rows 0–13, descenders to row 15), as on GRiD's own screens.
  - CLAUDE.COM keeps its glyphs from Terminus Font (`src/TERMINUS.INC`) for now, because its extra glyphs (●, ⎿, box corners) were drawn to match it.
  - The screen reader in the tests knows both fonts.
- **Rights:** GRiD Systems was bought by Tandy in 1988 and its products sold on after that. In the US, the design of a bitmap typeface generally isn't protected by copyright. The original .TYP files stay out of the repo; `FONT.INC` holds only the 96 glyphs. (Not legal advice.)

## Switching fonts (2026-10-06, API 2)
- GRiD's font stays built in, and other fonts are files.
  - A **.FNT** file is the 96 glyphs of codes 32–127, 8×16, 16 bytes each, top row first: exactly 1,536 bytes.
  - `fonts/TERMBOLD.FNT` (the font 0.3 started with) is built from `src/TERMINUS.INC` by `fonts/TERMBOLD.ASM`. `typfont.py X.TYP --fnt X.FNT` makes one from any 8×16 GRiD font.
- **The core:**
  - one font slot, as before;
  - `UI_FONT` (jump-table entry 45, so `UI_API` is now 2): AL = 0 gives the name in use, AL = 1 sets glyphs and a name;
  - at first start, `font_boot` reads `\LODE.INI`, and a line `FONT=NAME.FNT` (any case) loads that file. Without the file, or with one that isn't exactly 1,536 bytes, GRiD's stays;
  - the saver passes `F=seg:off` to DEFRAG, which copies the font, so the tidying map matches.
- **System, Display** (a seventh topic, between GPIB and About):
  - it shows the font in use, the fonts on the disk, and two sample lines;
  - Return goes to the next font (the .FNT files in directory order, then GRiD's again) and redraws everything;
  - `LODE.INI` is rewritten keeping its other lines (it's meant for more settings). An old `FONT=` line goes, and with GRiD's font and nothing else the file is deleted;
  - a write-protected disk: the font changes for now, and a message says it couldn't be saved.
  - System carries a copy of GRiD's font to switch back to (SYSTEM.RUN is 7,570 bytes; that memory is only used while System runs).
- **Cost:**
  - LODE.SYS +244 bytes (30,292);
  - a DOS program gets 571.5 KB (from 571.7);
  - DEFRAG.COM +54 bytes;
  - the font file is 1,536 bytes on the disk.
- **Tests (`t_font`, 11 checks):**
  - GRiD's at the start;
  - the Display topic; Return to TERMBOLD.FNT, with the screen redrawn in it;
  - LODE.INI written, and TERMBOLD.FNT again after a restart;
  - the saver's DEFRAG in TERMBOLD.FNT;
  - back to GRiD's, with LODE.INI deleted;
  - other INI lines kept, in any case;
  - a missing file, and a wrong-sized .FNT passed over.
- CLAUDE.COM keeps its Terminus-derived glyphs built in for now.

## The mouse for DOS programs (0.3.1, 2026-10-06)
- **TM5000G said "No mouse detected"**, though the mouse works in the Executive. The core had a working serial-mouse driver: it finds the mouse on COM2/COM1 and decodes its packets. But DOS programs had only the kernel's INT 33h stub, which returned AX = 0, and the core switched the mouse off before every DOS program.
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
- **Cost:** LODE.SYS 32,162 bytes (+1,870 with the fixes below). A DOS program gets 569.4 KB, 2.1 KB less, because the driver stays resident while programs run. The version is now 0.3.1; System's About shows it.
- **Tests (`t_mouse`, 38 checks; `tests/M33TEST.COM` steps through the calls, `M33GFX`, `M33QUIT`, `M33HSET` and `M33HVIC` cover the fixes below):**
  - the port is left alone for MEMSZ; reset, version, show, follow, position, presses and releases, mickeys, ranges, the event handler, hide;
  - a cell the program wrote over stays as written; mode 4's arrow drawn and taken away;
  - the program ends with the pointer on and a handler set, and the Executive and its mouse are fine;
  - with no mouse, reset returns 0;
  - **TM5000G:** "Mouse support enabled.", "Mouse: ON", and a click on Configure Modules opens it.
  - The TSR test also checks that INT 33h follows the UI block.
  - the graphics pointer bit for bit against the masks (mode 40h at three places with a hot spot, mode 6 clipped, mode 4 with a hot spot);
  - a program that ends inside its handler, a handler left behind under the shell, a packet while a handler is being set.
- **Fixes (2026-10-06),** each with a test that fails on the code before:
  - **DF:** `int33_ui` didn't clear the direction flag, so a program calling with DF set made the reset write 138 bytes backwards over the Executive's row table (fn 09h, 16h and 17h too). Now `cld` on entry.
  - **A program ending inside its event handler** left `m33_busy` set, which silenced every later program's handler. It's cleared when a program ends and at a reset.
  - **A handler left behind under the shell** (LCMD → a program that sets one and ends without a reset → the next program loaded at the same segment) was called inside the new program: the owner check can't tell two programs at one segment apart. Now the kernel tells the core when a program ends (`ui_progend` → `m33_gone`), and that program's handler goes. A TSR's stays.
  - **Setting a handler raced the mouse:** INT 21h AH=62h turns interrupts on, and a packet then found the new handler with the old owner (0) and dropped it. The owner is asked first, and owner 0 means none. pcemu now has the 1520's reset jump at FFFF:0, which made this visible.
  - **The hot spot in modes 4/5** was taken in physical pixels; Microsoft's masks and hot spot are in virtual pixels (one bit each).
  - **With no mouse**, calls other than the resets drew a pointer or reported a driver; now they return unchanged.
  - Not changed: modes 48h/74h (the 1520's other 640 × 400 modes) get no pointer and a 200-line range. TM5000G's own menus call hide twice when left by a key and show once, so its pointer stays hidden after the first key choice (Microsoft's driver counts the same way: TM5000G's bug, `ui.c`).
- **On the 1520, still to see:** the pointer on the plasma in TM5000G's text menus and in its CGA graph screen.

## The File form (0.3.2, 2026-10-06)
- **Aims:**
  - change devices in the Executive (a 1520 can have an external B: drive);
  - Tab between Device, Subject and Title, as in GRiDManager;
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
  - `UI_FINDAPP` looks in the subject, then in the root of the disk Lodestone started from. So SYSTEM, WRITE and CLAUDE are found while B: is shown.
  - System's Display lists the fonts, and writes LODE.INI, on the start-up disk ("Fonts on the start-up disk:").
  - The saver runs DEFRAG only from the current drive's root, so a data disk on B: isn't tidied unless it has DEFRAG. (Since 0.3.12 it runs the start-up disk's DEFRAG on A:, B: and C: in turn; see `lodestone-defrag.md`.)
- **Cost:** LODE.SYS 32,842 bytes (+680 since 0.3.1; CODE-R and CODE-D saved about 150). A DOS program gets 568.7 KB (0.7 KB less than 0.3.1): the Executive's code (now 4.2 KB) stays resident while DOS programs run.
- **Tests (`t_form`, 26 checks; `t_exec` reaches subjects through the form):**
  - titles only, Title outlined; the form's values;
  - Tab to Device (the drives, the prompt), to Subject (the tree), back to Title with the same file; Shift-Tab; ESC;
  - a subject two levels down; a subject with an extension;
  - B: through Device, Return to its subjects and titles, a text file on B: in Write;
  - CODE-U from B:; fonts and LODE.INI on A:;
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

  The keys are the commands' initials. The command prompt moved from CODE-C to **CODE-P**.
- **Copy** writes the copy under a temporary name first, and renames it only once it is complete. So a full or write-protected disk leaves what was there alone, and the date and time go with the copy.
- **Move** on the same drive only moves the directory entry. To the other drive it copies, then erases; a read-only file is refused.
- **A title that is already there** is replaced only after confirming.
  - The Subject is typed as a path from the root (`\` for Root, `\DOS.330\DEEP`).
  - A title can't contain `\ : * ?`; a subject can't contain `: * ?`.
  - Copy or Move onto the file itself is refused however it is spelled; the kernel cuts names to 8.3, so "NOTES.TXTX" is NOTES.TXT.
- **Erase** asks first, and read-only files stay.
- **Core, through the screen saver:** questions, forms and messages keep their band. The core remembers the waiting band (`held1`/`held2`, `hold_band`) and `redraw_all` puts it back. DEFRAG doesn't start while a question waits; the saver shows only the dark clock.
- **Kernel, `buf_put`:** a sector write that fails no longer leaves the change in the buffer. Before, a later write to the same sector carried it to the disk: for example, a delete refused by a write-protected disk happened after all once the tab was off.
- **Cost:** LODE.SYS 35,360 bytes. A DOS program gets 565.9 KB, 2.8 KB less than 0.3.2.
- **Tests:**
  - **`t_files`:** each command and its form, replace-or-not, read-only files, a write-protected disk, and copies between A: and B: checked byte for byte.
  - **`t_file_safety`:** the edge cases:
    - one file however spelled;
    - the saver during a question and during a form;
    - forbidden characters;
    - the deepest subject (65 characters);
    - Move from a write-protected disk;
    - a failed directory write not carried to the disk later;
    - a failed rename after replacing ("Copy kept as …TMP").
  - With all of them, apps has 237 checks; kernel 60, DEFRAG 33, Claude link 21 and HEADCLN 9 still pass.

## The screen saver's delay (0.3.4, 2026-10-06)
- **Aim:** set in System when the screen saver starts.
- **System has a "Screen saver" topic,** between Display and About. It shows "Starts after: 5 minutes". Return steps through 1, 2, 5, 10, 15 and 30 minutes, then never, and the choice takes effect at once.
- **LODE.INI** keeps the choice as `SAVER=n` (any case). There is no line for the usual 5 minutes, and `SAVER=0` means never. Its other lines, `FONT=` included, are kept; with nothing left the file goes.
  - System writes both settings through one routine (`save_ini`, with `ini_is` matching a key in any case).
  - At start-up the core reads `SAVER=` as well as `FONT=`, in either order.
- **The most is 30 minutes:** the core counts idle ticks under 8000h, which is how it copes with the clock going back at midnight. A larger value in LODE.INI is taken as 30.
- **The core:**
  - `saver_t` (ticks; FFFFh means never) replaces the constant;
  - a new call, `UI_SAVER` (entry 46, so UI API 3): AL = 0 gives the minutes, AL = 1 sets them from BL.
  - SYSTEM.RUN needs this core (API 3).
- **Cost:** LODE.SYS 35,272 bytes (−88; the setting costs 120 bytes, and trimming the Executive's help saved 208).
- **The Executive's help, trimmed:** 13 lines instead of 18. Gone: Home / End, Mouse, the F1 line and "5 minutes idle — screen saver" (no longer true). "A letter — the next name with it" became "Type its first letter — find a name"; CODE-U reads "System"; CODE-D "Delete the file". SYSTEM.RUN 8,084. A DOS program gets 565.7 KB.
- **Tests (`t_saver_delay`, 14 checks):**
  - 5 minutes to start with; the topic; each step and its LODE.INI;
  - "never" over 30 idle minutes; 1 minute: no saver at 50 s, the saver after a minute;
  - after a restart; `FONT=` and `SAVER=` together; `saver=2` before `FONT=` with another line kept; back to 5 removing the line; `SAVER=99` taken as 30.

## Wildcards in Copy, Move and Delete (0.3.5, 2026-10-06)
- **Design:** wildcards typed in the form (GRiDManager style), not marking in the list; Copy, Move and Delete take them, Rename stays one title; Replace as Ask / All / None, plus Only newer for backups.
- **The forms:**
  - **Copy:** Titles, Device, Subject, Title, Replace, Only newer.
  - **Move:** Titles, Device, Subject, Replace.
  - **Delete:** Titles (one field, so Return confirms: CODE-D, Return erases as before).
  - Titles starts as the chosen title. Type `*.TXT`, `NOTES.*` or `?.DAT` for every title in the listed subject that matches, or another title for just that one; left empty it is the chosen one. No `\` or `:` in it.
  - With `*` or `?` in Titles each title keeps its name, so Title must stay as filled in (or be emptied).
- **Replace** (a title already there): Ask puts the question for each (Return replaces, ESC leaves that one and goes on), All replaces without asking, None leaves them all.
- **Only newer:** a title already there is left unless it is older (FAT date, then time). For an A: to B: backup: `*.*`, Replace All, Only newer Yes.
- **Delete with `*` or `?`** asks first: "Erase: Confirm to erase 5 titles *.BAK". Read-only titles stay and are counted ("Erased 4 titles, 1 read-only kept").
- **The band after several:** "Copied 3 titles to B:\DATA, 2 left as they were" / "Moved 2 titles to A:\WORK". One title left by Replace None or Only newer: "NOTES.TXT is there already: left as it was".
- **Errors stop the run** at that title and say why ("Can't copy A.TXT: Disk is write-protected"); a Move that copied but couldn't erase says so and goes no further. The list is read again if anything changed.
- **How:** `pat_find` collects the matching names (find first/next, attribute 0: files and read-only ones, not hidden or system), with their date and time, into a block of their own (17 bytes a title), cut down to what it holds so Copy's 32 KB buffer still fits. The directory can then change under the run (Move renames, Copy makes its temporary file) without upsetting it. `xfer_do` uses find first on the destination (time, date, subject or not) where it used 4300h.
- **A Subject that isn't there is made** (a Move to `B:\NEWFOLDER` on the 1520 needed it): "B:\NEW\DEEP isn't there: Confirm to make it", then each level in turn. ESC leaves everything as it was.
- **Two kernel fixes found on the way** (a failed MKDIR on a write-protected disk):
  - `clu_zero` returned the cluster number instead of the error (so "error 17"), and its CF was lost to an `add sp`. It now returns CF with AX = the error.
  - A cluster taken for a new subject (MKDIR) or for a subject that grows was kept when it couldn't be written: a lost cluster, or, when a subject had to grow, its chain led into a cluster of old data that showed as stray entries. Both now give the cluster back.
- **Cost:** LODE.SYS 36,636 bytes (+1,364). A DOS program gets 564.6 KB (−1.1 KB).
- **Fixes:** three bugs, all fixed with tests: an emptied Titles checked leftover bytes after the chosen title (a stray `\` or `*` from an earlier path); a wildcard Move that couldn't erase an original was reported as a full success; and the name block could take all free memory, starving Copy's buffer. Left as designed: ESC at a Replace question leaves just that title.
- **Tests (`t_wild`, 31 checks; the last 8 for making subjects and the kernel fixes):** the form; `*.TXT` to B: with None, with All and Only newer (older replaced, newer and as-new left), with Ask (Return, then ESC each); Move `*.DAT` on the same drive and `*.*` to B:; no match; a path in Titles; Title changed with a pattern; a pattern into its own subject; another title typed in Titles; Titles emptied; one title with None; a write-protected B: and A:; Delete `*.TXT` (ESC, then Return, the read-only one kept). The existing Copy/Move/Delete tests now step over the Titles field.

## Delete on a subject (0.3.6, 2026-10-06)
- **Why:** Delete wouldn't remove a folder. Now a subject goes, empty or not, after a question.
- **How:** outline Subject, choose the subject (it is the current one), CODE-D: "Erase: Confirm to erase \OLD and all in it". Return erases every title under it (read-only, hidden and system ones too: their attributes are cleared first), every subject below it once empty, then the subject. Subject then lists the subjects again with the one above chosen. Root can't be erased (a beep). An error stops it and says what and why ("Can't erase K.TXT: Disk is write-protected").
- **The walk (`tree_del`):** after the CHDIR to `..` (checked), one DTA (the Executive's own): files are erased as find-next goes; on reaching a subject it goes down into it, and once a subject is empty and removed the level above is searched again from its start (everything before it is gone). The path is `dstpath` (no new buffer).
- **Size:** the first build counted the titles for the question, which needed a DTA a level and a second pass (+552 bytes). That was too much, so the count went: 186 bytes less.
- **Guards for damaged disks:** a subject whose first entry isn't "." (a corrupt one pointing at the root or elsewhere) is left alone; a path longer than DOS allows stops the walk.
- **Kernel fix (RMDIR, also the prompt's RD):** a subject Windows or Linux wrote long names into kept the long-name entries after its files were erased, and RMDIR took those as titles ("Access denied"). They no longer count.
- **Checked:** no way was found (in the first build) for the walk to leave the subject on a sound disk. The fixes for long names and an unchecked CHDIR, and the damaged-disk guards, are in.
- **Cost:** LODE.SYS 37,002 bytes (+366). A DOS program gets 564.2 KB (−0.4 KB).
- **Tests (`t_subdel`, 10 checks):** Root refused; the question; ESC; Return erasing a tree with a read-only title, a long-named one and empty subjects; the list after; an empty subject; a write-protected disk. Checked to fail without the RMDIR fix.

## Screen capture (0.3.9, 2026-10-07)
- **Design:** the BIOS's own print-screen key (Shift-PrtSc) saves the screen to a file instead of printing it; the file goes in the root of the boot disk; graphics become a BMP and text a TXT.
- **Asking:** on Shift-PrtSc the 1520's BIOS (INT 9, after its EOI) calls INT 5. The kernel owns INT 5 now, and its handler only sets `cap_req`, because the key can come in the middle of anything (the BIOS, a disk transfer, the kernel).
- **Taking it, at the next safe moment.** `capture` goes ahead only when `cap_req` is 1 and `indos` is 1 (one word compare), and the PIC has no interrupt in service:
  - at the INT 21h entry, for an outermost call, before the dispatch;
  - in the console's key wait (`kbd_get`, before its INT 28h), so LCMD's prompt and programs waiting on INT 21h take it at once;
  - in the UI's idle poll, which now asks for the current drive (INT 21h 19h, 4 bytes), so the Executive and `.RUN` programs take it at once too.
  - A DOS program that reads the keyboard straight from the BIOS gets the picture at its next DOS call.
  - It runs on the kernel stack. Its own create, write, close and erase calls nest on the critical-error stack (about 90 of its 512 bytes in pcemu).
- **The files:** `SCREEN01.BMP` … `SCREEN99.BMP`, or `SCREEN01.TXT` …, in the root of the boot drive. Each extension is numbered on its own, and create-new (5Bh) finds the first number free.
  - **Printing, through a driver (2026-10-19):** with `PRINTER=PS.PRN` in LODE.INI (System, Devices, Return: the next `.PRN`, then none), PrtSc alone prints, and Shift-PrtSc still saves the file (INT 5 reads the BIOS's shift flags at 40:17 into `cap_file`; on the 1520 both are Fn-PrtSc). A driver is a flat binary of 16 bytes to 1 KB that starts with a `JMP SHORT` and then `'PRN', 1`; the kernel runs nothing else, and System offers nothing else (a print job saved as `.PRN` would otherwise be run as code and hang the machine). At the same safe moment the kernel reads it into the capture's 1 KB at the kernel stack's bottom, calls it far at offset 0, and forgets it: it reads the screen itself, may use the BIOS but not DOS, and returns AL = 0 when printed. A missing driver, one under 16 bytes or over 1 KB, one without the signature, or AL ≠ 0 gives the long beep. When the ROM's own LODE.INI names a driver, choosing none in System writes an empty `PRINTER=`, so it stays none. Resident: the loader and a 24-byte path, 0.2 KB of DOS memory (561.5 / 577.6 KB with EMS). The path is set at start-up by the kernel's discarded boot code (KSPLASH.INC `pr_boot`: from the ROM `C:\LODE\NAME` if it is there, else the drive started from, as PATH finds programs), and System changes it in place through INT 21h F006h (ES:BX → the path, CX its room). `drivers/PS.PRN` (on ROM 1 too) sends PostScript to LPT1 through INT 17h, as TM5000G prints to a Brother HL-5370DW: the graphics modes as a 640 × 400 `image` (hex, bottom line first, lit pixels black), the text modes as Courier lines with `( ) \` escaped and the PC's graphics characters as `?`; each byte tried for 10 s while the printer is busy. A first version had the PostScript code in the kernel (0.6 KB resident); a driver loaded only when printing costs less. Tests: `test_kernel.py t_print` (PostScript byte for byte against video memory, another driver, one over 1 KB, a missing one; its output rendered with Ghostscript), `test_apps.py t_prtsc_setting`.
  - **Graphics:** a 640 × 400, 1-bit BMP with the Windows 3 header, 32,062 bytes, in dark red (36, 8, 2) and orange (255, 120, 40), the 1520 plasma's colours and the README's (brown and amber before 2026-10-19). Modes 40h, 48h and 74h read four banks. The 200-line modes (4 to 6) read two banks and write each line twice; modes 4 and 5 come out as their bit patterns.
  - **Text** (modes 0–3): the shown page (40:4Eh) as 25 lines of 40 or 80 columns (40:4Ah), without trailing blanks, NUL as a blank, ending CR LF.
  - The mouse pointer is in the picture if it's on the screen.
- **Written in big pieces.** The kernel writes straight to the disk, so a first build that wrote each 80-byte line on its own cost a disk turn per line: 94 s for one picture on pcemu's real-floppy timing. The capture now writes through a buffer:
  - in the Executive and `.RUN` programs, the disk cache's memory, lent the way the windows' save-under borrows it (INT 21h F0h AL=2/3, 18 KB);
  - in a DOS program, or when the cache's memory is out already (a help window), 1 KB at the bottom of the kernel stack. With EMS the lend is a block of free memory, which a DOS program might still be using past its own block.
  - On the real-floppy model: a BMP takes 2.9 s in the Executive and 8.1 s in a DOS program; a TXT takes 1.4 s.
- **Errors:**
  - Nothing reaches INT 24h meanwhile: `crit_disk` fails at once, so neither the UI's handler (which would keep the error for its next message) nor a program's runs.
  - A write-protected or full disk, or no number free, gives a long beep. A part-written file is erased, and after a write fails no more are tried.
  - Success gives one beep (BEL through INT 10h).
  - The program's INT 21h 59h error is kept.
  - A press while a picture is being saved is dropped (the screen is the same).
- **Fixes,** confirmed in pcemu, all with tests:
  - **Data loss:** a disk swapped in that a program had already read through the BIOS (change line clear, no 0Dh yet, as HEADCLN does) got the boot disk's cached FAT and root written over it: 30 files gone. The capture now starts with `disk_reset` (as INT 21h 0Dh), so the kernel checks the disk first and writes the picture to the disk that is there.
  - **Inside a hardware interrupt:** a TSR's INT 1Ch hook that calls DOS while InDOS is 0 (as clock TSRs do) made the capture run before the timer's EOI, with the floppy's IRQ blocked. The capture now waits while the PIC's in-service register is non-zero. pcemu now models that register.
  - **A disk pulled mid-picture** would have tried every remaining piece (minutes with the BIOS's time-outs). It stops after the first failure.
  - **With EMS, inside a DOS program,** the lend wrote 18 KB into free memory. It isn't used there any more.
  - Left: a DOS program's mouse event handler that calls DOS runs after the EOI, so it isn't caught; a BOUND fault (also INT 5) now loops silently instead of printing for ever; and the Executive's list shows the new file only after F5.
- **On the 1520 (2026-10-07):** Shift-PrtSc in the Executive gave `SCREEN01.BMP` (the list, the band and the mouse pointer, as on the plasma), and at LCMD's prompt `SCREEN01.TXT` (the banner and the prompt, trimmed).
- **Cost:** LODE.SYS 39,790 bytes (+500): the capture and its writer 396 bytes, the BMP header 62, the name 16, the INT 5 handler 7, the hooks 16 (vector, two calls, `crit_disk`), and 4 in the UI. A DOS program gets 563.7 KB without EMS and 579.8 KB with it (−0.5 KB).
- **pcemu:** `pc.prtsc()` raises INT 5 the way the BIOS's INT 9 does. The PIC's in-service register is modelled: delivery sets the bit, EOI clears it, and OCW3 selects what port 20h reads.
- **Tests (`t_capture` in `test_kernel.py`, 18 checks; `tests/CAPTEST.COM`):**
  - In the Executive: the BMP matches video memory bit for bit; one beep; the screen is untouched; the cache's memory is given back.
  - With the cache's memory already lent: the 1 KB buffer, a correct picture, and the cache still lent.
  - In a DOS program: mode 6 (each line twice, through the 1 KB buffer, no lend); 80-column text with trailing blanks and a NUL; 40 columns; a BIOS key wait with a timer hook calling DOS (not taken inside the interrupt; taken at the program's next call).
  - At LCMD's prompt.
  - On a write-protected disk: a long beep, the disk untouched, the UI's error not set.
  - A disk changed behind the kernel's back: its files kept, the picture on it.
  - On a full disk: a long beep, no file left, the disk consistent, and one write only.
  - The changed-disk and timer-hook checks fail without their fixes.

## The hard disk as C: (0.3.10, 2026-10-07)
- **Why:** the 1520's BIOS only types the few Conner drives on its list, so a Conner CP30104H (121 MB, freed by `HDPROBE /X`) is invisible to INT 13h. Lodestone drives it itself at 1F0h–1F7h. The aims: as small and fast as the EMS driver, nothing in memory without a drive, and fine to use with the drive's 4 bad sectors (free space; HDSCAN found the same 4 twice).
- **Start-up (`hd_init`, section `boot`, after `ems_init`):**
  - **Is there a drive?** A register echo test; if it fails, two status reads separated by filler bytes tell an empty or floating bus (FFh, or leftover code bytes without BSY) from a drive spinning up (BSY in both), which gets 5 s.
  - **Geometry:** IDENTIFY words 1, 3 and 6, set with 91h as the BIOS would. CHS throughout (drives of the 1520's age have no LBA).
  - **The partition:** the first type 04h, 06h or 0Eh entry, then its boot sector. Checked before anything is trusted: 512-byte sectors, a power-of-two cluster size up to 64, 1 or 2 FATs, the root within 32 MB, the volume under 2 GB and within the table's partition, the partition within the drive, 4,085–65,518 clusters, a FAT that holds them.
  - **Only then** is the module copied in (after EMS's, or where EMS's would be), C:'s drive-table entry made, IRQ 14 masked (unless the BIOS has a hard disk), and the kernel hooked.
- **Hooks:** 13 kernel routines start with a 3-byte `JMP NEAR` into the module: `dio`, `fat_load`, `fat_flush`, `fat_flush_drv`, `fat_get`, `fat_set`, `free_run`, `clu2lba`, `buf_get`, `buf_getd`, `buf_inval_range`, `root_pre`, INT 21h 36h. A `.hk` label in each marks the instructions copied into the hook's trampoline, which A: and B: run before jumping back; `HKROOM` fails the assembly if a place has less than 3 bytes.
- **32-bit sector numbers, C: only:** the high part travels in `lba_hi` (set by `clu2lba` and directory code, consumed by `buf_get`/`buf_getd`/`dio`), in a cache buffer's drive byte (2 + 4 × high part), and in bits 9 and up of directory-entry offsets (`d_off`, `S_DOFF`; `dent_buf` unpacks them). Two drive letters for the 121 MB were considered and dropped: repartitioning, about 100 bytes a letter, and PC-formatted CF cards need 32 bits anyway.
- **Transfers:** `rep insw`/`outsw`, polled, up to 127 sectors a command (ES:BX normalised so a run stays in 64 KB), each command tried twice, then INT 24h as for the floppies.
- **The FAT:** a 1.5 KB window of 3 sectors, least-recently-used with dirty bits, written to every FAT copy at each kernel FAT flush or when a slot is needed. A sector that can't be had (unreadable, or its slot's changes can't be written) comes back as FFFFh: no cluster is followed or taken there, and writes to it go nowhere. The free count is made on the first INT 21h 36h (kept only if every FAT sector read) and kept up to date after.
- **Kernel changes:** FAT16 end markers (FFF0h and up read as ends, FFFFh written); NDRV 3; INT 21h 0Eh reports 3 drives with C:; drives with D_UNIT bit 7 skip the change-line check; the Executive's Device list and Copy form offer C: ("Hard disk C:"); DEFRAG and the saver's tidying stay with the floppies; About shows the patch number.
- **Cost:** LODE.SYS 42,114 bytes (+2,324). Without a drive a DOS program gets 547.4 KB (−0.2 KB, the kernel's 32-bit plumbing). With C: the module (1,248 bytes) and window cost 2.8 KB with EMS (560.7 KB) and 3.2 KB without (544.2 KB).
- **Fixes, 8, all tested:** an unreadable FAT sector left a window slot labelled with the new sector over the old one's contents (later writes went to the wrong FAT sector); a failed write-back on eviction lost the slot's changes; a failed flush cleared the dirty bits; C:'s flush failing stopped a floppy's FAT from being written; the free count could drift past an unreadable sector; the boot sector wasn't checked against the table or the drive; `clu2lba` left a stale high part; `drv_init`'s unit mask.
- **Tests (`tests/test_hd.py`, 42 checks; disks from `tests/fat16img.py`, which also checks one as CHKDSK would):** no drive, floating bus, stuck drive, no / FAT12 / oversized partitions; the shell on C: (DIR, TYPE, COPY both ways, MD/CD/REN/DEL/RD) with a directory and a file past sector 65,535 and one across it; TM5000G copied and run from C:; a 121 MB disk behind a real CP30104H's sector 0 and boot sector; a bad sector; a full disk; FAT sectors that can't be read (DEL with Fail, Abort mid-read) or written (DEL through five FAT sectors, a passing fault, C:'s FAT failing while A:'s has changes, with `HDFLUSH.COM`); TESTDOS and CACHETST on C:; the Executive; memory. pcemu's `Ata` takes writes (30h) and refuses listed ones (`badw`).
- **On the 1520 (2026-10-07):** works.
- **0.3.11:** INT 25h/26h (absolute sectors, DOS 4's 32-bit form) for C:, and DEFRAG on C:; see `lodestone-defrag.md`.

## System and the hard disk; the saver's tidying (0.3.12, 2026-10-07)
- **Aims:** C: in Disks, the hard disk's own name in Devices, and a switch for whether the screen saver tidies the disks.
- **Disks:** after A: (and B:), C: when INT 21h 0Eh says 3 drives. Its label, size, free space and space in use. Sizes now print in 32 bits (UI_SBU32): the CP30104H shows "118448 KB".
- **Devices:** a "Hard disk" line with the name the drive gives itself, e.g. "Conner Peripherals 120MB - CP30104H", or "none".
  - System sends IDENTIFY (ECh) itself and reads words 27–46, with a 1 s time-out. It does this only when Lodestone has C:, so the kernel keeps no copy of the name (no resident bytes).
  - A name longer than the value column runs to the right edge.
- **Screen saver:** a second line, "Tidies the disks first: yes/no". Space switches it (band: "RETURN: the next delay    SPACE: tidy or not    ESC: back"; the help has a line for it).
  - Saved as `TIDY=0` in LODE.INI when off; FONT=, SAVER= and other lines are kept.
  - The core reads TIDY=0 at start-up (`sv_notidy`). UI_SAVER (UI API 4): AL = 0 also returns AH = 1 when not tidying; AL = 2 sets it from BL.
- **Cost:** SYSTEM.RUN 8,731 bytes (+459). The core +44 bytes (LODE.SYS 42,348). WRITE.RUN and UITEST.RUN are rebuilt for API 4, same size.
- **Tests:**
  - `test_apps.py t_saver_tidy`, 7 checks: the line and band; Space to no and LODE.INI; with a delay too; the saver straight to the dark screen; after a restart; Space back; DEFRAG again.
  - `test_hd.py t_system`, 3 checks: A:, B: and C: in Disks with 32-bit sizes; the drive's name in Devices; without a drive, no C: and "none".
  - The delay tests now expect the new band text.

## Copy on a subject (0.3.13, 2026-10-08)
- Folder copy works the way Delete on a subject (0.3.6) does: outline Subject, choose the subject (it is the current one), CODE-C.
- **The form** ("Copy WORK", "Copy Root"): Device, Subject, Replace, Only newer.
  - **Subject is where the copy goes**, the subject itself to start with, so a copy on another disk changes only Device: WORK on A: to B: is `B:\WORK`. Typed as a path from the root, as in the title Copy.
  - Replace (Ask, All, None) and Only newer work title by title, as in the title Copy. A backup of a whole subject to B: is Device B:, Replace All, Only newer Yes; run again, it copies only what changed.
  - The destination subject, if it isn't there, is made after the question the title Copy asks ("B:\WORK isn't there: Confirm to make it"; ESC makes nothing). The subjects below it are made without asking.
  - Root copies the whole disk.
- **Refused before anything is done:** a copy into the subject itself or into a subject in it, or Root into its own drive: "Can't copy WORK into itself: choose another place". The form starts out as exactly that, so confirming it unchanged says so. `\WORKS` is somewhere else, and is copied to.
  - The check compares the path as typed (in capitals, `/` as `\`). Spellings the kernel takes for the same subject (`\.\WORK\SUB`, `\WORK.\BAK`, `\LONGNAMEX` for `\LONGNAME`) get past it. Then the copy still ends (the list was made first) and nothing is lost, but titles can be copied twice, one level down. Left as it is: catching every spelling would cost more code than it saves.
- **How (`sub_copy`):**
  - **First the list** (`sc_list`): a block of its own (`sc_seg`) holds where the copy goes, then the subjects to copy as paths from the subject (`""`, `\SUB`, `\SUB\DEEP`), a level at a time (find first/next, attribute 16h, on each one listed), so each comes after the one it is in. It is made before anything is written, so the copy can't take itself in, even when the destination is spelled some way the check above misses (`\LONGNAMEX` for `\LONGNAME`): then the first title is "the file itself" and it stops there.
  - It is a block and not the Subject list's buffer (`entries`) because the core's redraw after the screen saver rebuilds the Subject list there, and a Replace question can wait through the saver.
  - The Subject list stops at 5 levels; this list doesn't, so a deeper subject (on C:) is copied too.
  - **Path lengths:** DOS takes 66 characters for a subject. `sc_lim` is that, less the longer of the subject and where it goes (Root counts 0: a path put after it brings its own `\`); a subject below it whose path from it is longer, or a destination already longer itself (66 characters typed without the first `\`), is refused before anything is made (Path not found).
  - **Then each subject** (`sc_copy`): `curdir` is where its titles are and `c_sub` where they go (one `\` where the two paths meet, `sb_join`, for Root at either end); it is made (MKDIR, or there already as a subject; the destination itself is checked the same way, so a file of that name or an empty drive says so instead of "Copied 0 titles"); then the title machinery of 0.3.5 does the rest: `pat_here` (a second entry into `pat_find` that keeps `curdir` and the counts) collects the titles into their block, and `xfer_all` copies each one (written under a made-up name, then renamed; the date and time kept; `same_file`).
  - **Afterwards** the Subject list is read again (copies on the same drive show at once) with the subject still chosen, and the band says "Copied 23 titles to B:\WORK" (", 2 left as they were").
  - **Errors stop it** and say why, as with titles: "Can't copy A.TXT: Disk is write-protected", "Can't copy KEEP: Disk is write-protected" (the subject couldn't be made). What was copied stays.
- **Hidden and system titles and subjects are copied too** (the list searches with attribute 16h, the titles with 06h, which `pat_here` takes in BP), and the copies keep those two bits (`hs_copy`: 4300h on the original, 4301h on the copy; the kernel sets them on a subject too). The first build left them behind as the title Copy does, but Delete on a subject erases them, so a copy then a delete lost them without a word. A copy of a read-only title isn't read-only, as with titles (a later Replace couldn't erase it). Move on a subject isn't offered (CODE-M still beeps there).
- **Shared with the title commands now** (no change in what they do): `form_fill` (Device, Subject, Title, Replace, the drives) out of `xfer_form`; `sum_to` ("Copied 5 titles to …") out of `xfer_sum`; `seg_free` frees the titles' block, Copy's buffer and the subjects' block.
- **A kernel fix found on the way:** after a subject couldn't be made (or grow) on a write-protected B:, A:'s directories couldn't be read ("Can't read the disk: Disk is write-protected") until F5 or the tab came off.
  - The kernel caches one FAT, A:'s or B:'s. MKDIR took a cluster on B:, couldn't write it, and gave it back (0.3.5), which left B:'s FAT marked as changed though it was as on the disk. That can never be written to a write-protected disk, and loading A:'s FAT writes the cached one out first, so every read of A: failed with error 19.
  - The title Copy into a new subject on a write-protected B: did this since 0.3.5; the subject copy's own Subject list, read again right after, showed it at once.
  - Now `fat_keep` and `fat_back` keep the FAT's changed-sectors mask around the cluster taken, and put it back when the cluster is given back because it couldn't be written (MKDIR: only when the zeroing fails, before any FAT write; a subject's growth likewise). Nothing reached the disk, so the FAT is as before in every sense.
- **Checked:** no crash, stack imbalance or lost FAT change; the kernel fix is sound (the drive's own FAT is always the one cached when it saves the mask; C:'s FAT16 is untouched by it). Fixed, each with a check that fails before:
  - hidden and system titles and subjects left behind without a word (above);
  - "Copied 0 titles to B:\X" with no disk in B:, or with a file called X there: the destination wasn't checked like the subjects below it;
  - the screen saver (any redraw) while the form was open wrote the subject's path into `runpath`, so the band said "Can't copy \WORK into itself" or, for Root, "Can't copy : …". The name is put back from the form's title;
  - a 67-character destination was made and then failed; and for Root to Root the length limit was one too strict.
  - Left: the spelling aliases above.
- **Cost:** LODE.SYS 43,256 bytes (+908: the subject copy 844, the kernel fix 64). A DOS program gets 562.5 KB without EMS and 578.6 KB with it (−0.9 KB): the Executive's code stays in memory while a program runs.
- **Tests (`t_subcopy`, 33 checks; 2 more in `t_wild`):** the form; confirmed unchanged ("into itself"); to B: (the question, every title and subject there byte for byte, a read-only one, 75 KB three levels down, an empty subject, the dates, no temporary file, both disks sound, Subject still chosen, the memory back); again with Replace Ask through the screen saver; Only newer and Replace All into a backup there already; into a subject in it, into itself with a `\` after; `\WORKS`; Root into its own drive; Root to `B:\ALL` (all of A:); a subject to B:'s root; on the same drive (the Subject list shows the copy); ESC at the question; an empty subject; a 61-character destination; a write-protected B: (making the subject, copying a title), A:'s Subject list after it; help; CODE-M on a subject; and the fixes' cases (hidden and system titles and a hidden subject, still hidden on B:; the saver while the form is open; a file where it goes; no disk in B:; 67 characters). The two write-protected list checks fail without the kernel fix, the six fix checks without their fixes.
- **`test_headcln.py`:** its first key went in while HEADCLN was still printing its prompt, and HEADCLN drops keys typed before it waits. Whether that happened depended on where the emulator's run slice ended, and it did once the Executive grew (HEADCLN loads 864 bytes higher): 7 of 9 checks failed. It now waits for the whole prompt.

## M:, the temporary disk (0.3.14, 2026-10-08)
- **What it is for:** Claude's scratchpad once Claude stays resident (0.5), and anything else that wants files fast and only for a while. It is a RAM disk in EMS, like GRiD's Temporary Disk and Microsoft's RAMDrive, built on the kernel's own FAT12.
- **What the user sees:**
  - **Drive M:**, 256 KB unless set otherwise, whenever the machine has EMS. DIR, COPY, MD/CD/RD, programs run from it, the Executive's file commands: all as on A: and C:.
  - **The Executive's Device list and Copy form** offer "Temporary disk M:". They now list B: only when the kernel has it (a second floppy drive); 0.3.10–0.3.13 listed B: with C: "if only to say it isn't there".
  - **System, Temporary disk** (a new topic, before About): Return steps through Off, 64, 128, 256, 512 KB, 1 MB and All free. The topic shows M:'s actual size, its free space and what All free would give. Without EMS it says "needs EMS".
  - **A change takes effect at once.** A new size empties M:. System asks first when there are files on it ("M: holds files: Confirm to erase them"), and refuses while a file on M: is open ("A file on M: is open: M: can't change now"). When EMS is short, M: is as big as fits and the topic says so ("less EMS was free"); with none free, "No EMS is free for M:: it is off".
  - **LODE.INI:** `MDISK=n` (KB), `MDISK=0` (off), `MDISK=ALL`; no line means 256 KB. M: is whole 16 KB pages (MDISK=100 gives 96 KB, at least one page). A line without a number counts as no line; more than any machine has counts as ALL. System writes the line (none for 256) and keeps the other lines.
  - **Other programs:** `DEFRAG M:` says "M: is the temporary disk, in memory: nothing to tidy", and the screen saver's tidying passes M: over. System's Disks shows M: with C:, and Memory shows M:'s block ("Temporary disk M:  0.3 KB").
- **The volume:** FAT12, 512-byte sectors, 1 KB clusters (2 sectors), one FAT, 64 root entries (128 from 256 KB up). 256 KB gives 251 KB for files; 1 MB, 1,017 KB; All free on the 1520 (86 pages), 1,365 KB.
  - 2 KB and 4 KB clusters were tried. Sequential transfers barely change; 64 random reads go from 0.24 s to 0.14 s and 0.10 s; small files waste more. 1 KB stays.
- **Where it lives.** Nothing is in memory without EMS, and nothing while M: is off:
  - **The installer and the resident part's image** sit in the disk cache's second EMS page, in the 14 KB the cache never uses (its 36 sectors are 18 KB in two pages). `ems_init` copies them there at start-up. The installer runs there, in window 0, called through INT 67h AH=5Bh AL='M'. 5Bh is an operating-system function in LIM 4.0; any other AL still gets A4h.
  - **A 26-byte stub at KSEG:0012h** maps the cache page in, calls the installer and puts window 0 back.
    - Those bytes were `start`'s. `start` runs only at 1000:0000 in the load image: BOOT.ASM has its own `KSEG equ 1000h`, nothing jumps to `start`, and a warm restart loads the file again.
    - After boot only 000Ah–0011h ('EMMXXXX0') are read.
  - **The resident part (`md_res`, 336 bytes: 21 paragraphs)** exists only while M: is on. It is a block of its own (owner 8, "MD") split off the master environment's block.
    - The environment's MCB shrinks from 32 paragraphs to 10 (160 bytes; its strings take 45), and the MD block follows it.
    - DOS tools that edit the master environment see a 160-byte block and stay inside it.
    - The environment's 512 bytes were never memory DOS programs got, so they get exactly as much with M: on as off. Off, the MD block goes and the environment has its 512 bytes again.
    - The suggested 256 bytes for the environment doesn't leave room: 512 − 16 (the MCB) − 336 = 160.
  - **What the resident part holds:** M:'s drive table entry and current directory, five hooks and the sector routine. The hooks are C:'s places (`use_drive`, `dio`) plus INT 21h 0Eh's drive count, `cwd_of` and `drv_present`.
    - The kernel now calls `cwd_of` and `drv_present` in every place that tested NDRV or indexed `cwdstr` itself: `f_0E`, `f_29` (it took any letter), `f_3B`, `f_47`, find next, IOCTL 4408h, `full_name`, `unmount`.
    - That saved 16 bytes, one paragraph of the kernel, which pays for the Executive's 22.
  - **Pages:** an EMS handle of its own, owner 0, from Lodestone's EMS manager (INT 67h 43h). No program's exit frees it, and programs see those pages as used.
    - Not handle 0: LIM lets any program empty handle 0, and EMSTEST does.
    - 256 KB is 16 of the 1520's 88 pages; programs keep 70.
- **The sector routine (`md_dio`):** the kernel's FAT engine does everything else. M:'s only code of its own is this routine, as `hd_dio` is C:'s.
  - It normalises ES:BX (BX < 16), splits a transfer where a 16 KB page ends, and checks each page against the handle's record: still owner 0 (M:'s), and within its pages.
  - It writes the page register itself (port 0258h + w × 4000h, value 80h | page from `ems_ltab`), never INT 67h. It reads the window's register, writes M:'s page, copies with `rep movsw`, then writes the old value back. The read and write of the register happen with interrupts off.
  - **The window:** window 3 (EC00h), or window 0 (E000h) when the caller's buffer is at E800h–EFFFh. A piece is at most 16 KB, so it never reaches the window being borrowed. A program's own pages in any window are as they were after every call, and a buffer in the frame (a program's EMS page) works.
  - **M: never reaches the cylinder cache:** the hook comes before `dio`'s call to it. M:'s directory and FAT sectors pass through the kernel's five sector buffers like any drive's, which is how the kernel edits them. They are keyed 0Ch, which no floppy key (no high part) or C: key (bit 1 set) can equal.
- **Warm restart:** M:'s first page holds a boot sector with the page list and a checksum.
  - **At start-up**, `md_boot` reads `MDISK=` and M: is made. If the handle got the same raw pages, the boot sector is exactly what M: would write, and the FAT is sane, M: keeps its files. Otherwise it starts empty.
  - **Turning M: off** clears that sector's first word, so a later restart doesn't bring back what was there.
  - **On the 1520 it doesn't (EMSKEEP, 2026-10-08, `bench/EMSKEEP_1520_2026-10-08.TXT`):** all 8 stamped pages came back with about 16,300 of their 16,384 bytes changed (what chance leaves alike), so the BIOS's warm restart rewrites EMS, most likely in its memory test. M: starts empty after every restart on this machine; the check costs nothing (it lives in the installer's EMS page, not in memory programs get) and stays for boards that do keep EMS.
  - `ems_init`'s page scan used to leave a tag in each page's first word; it now puts the words back.
- **The letter M::** no trouble found. INT 21h 0Eh returns 13 with M: (3 without, as before); D: to L: are invalid drives, as on DOS with a gap. LCMD, TM5000G, BENCH and the test programs work on M:.
- **Speed.** pcemu is calibrated to the 1520: frame copy 3,074 KB/s, and now 1 µs for each EMS port IN or OUT, which it didn't charge before. Table: BENCH 1.4 on M: (1 MB) in pcemu, BENCH 1.3 on A: on the 1520, HDSCAN on C: on the 1520.

  | Test | A: (1520, BENCH 1.3) | C: (1520) | M: (pcemu, 1 MB) |
  |---|---|---|---|
  | Write 256 KB, 16 KB at a time | 19 KB/s | | 0.175 s: 1,463 KB/s |
  | Read 256 KB, 16 KB at a time | 26 KB/s | 463 KB/s (HDSCAN, whole tracks) | 0.104 s: 2,461 KB/s |
  | Read 256 KB, 512 bytes at a time | | | 0.335 s |
  | Read 256 KB, 128 bytes at a time | | | 1.181 s |
  | 64 random 512-byte reads | 10 s | | 0.238 s |
  | Directory listing × 10 | | | 0.011 s |
  | Open + close × 100 | | | 0.196 s |
  | 20 × create a 1 KB file, then delete | 22 s | | 0.170 s |
  | Load + run a 120 KB .EXE × 3 | | | 0.158 s |
  | INT 21h calls × 1000 | | | 0.108 s |

  `BENCH /N 10` gives the same per-run rates (2,466 KB/s read, 1,382 KB/s write).

  - **Big reads** run at 2,461 KB/s. `md_dio` itself copies at about 2,950 KB/s (96 % of the frame's copy rate); the rest is the kernel's per-call work.
  - **Big writes:** the M: path runs at about 2,340 KB/s. The BENCH figure also counts BENCH's own fill of its 16 KB buffer (`stosb`, 66 ms in pcemu).
  - **Small writes, create and delete:** no waiting at all. 20 create/delete pairs take 0.17 s against 22 s on A:.
  - **64 random reads:** 0.24 s against 10 s. What is left is the kernel walking the FAT chain (`sft_cluster`, `fat_get`).
  - **BENCH 1.4:** `/N n` does each test n times over (`BENCH /N 10`), for drives too fast for one pass to time well.
- **Cost:**
  - **LODE.SYS 45,358 bytes (+2,102):**
    - M:'s installer and resident image, 1,745 bytes (load image only, copied into EMS);
    - the start-up, +336 (`ems_init`'s copying and the page scan's restore, the stub, `md_boot`);
    - the Executive, +22 (the drive list, "Temporary disk M:", the `sub_build` guard);
    - the kernel, −16.
  - **Memory for a DOS program run from the Executive**, in paragraphs (KB). Identical in every case:

    | | 0.3.13 | 0.3.14, M: off | 0.3.14, M: 256 KB |
    |---|---|---|---|
    | Floppies | 36,003 (562.5) | 36,003 | 36,003 |
    | EMS | 37,033 (578.6) | 37,033 | 37,033 |
    | C: | 35,792 (559.2) | 35,792 | 35,792 |
    | C: and EMS | 36,849 (575.7) | 36,849 | 36,849 |

  - **The arena's start, with EMS:** 0.3.13 has the environment (32 paragraphs), the root PSP (16) and the UI block (2,171). 0.3.14 with M: off has the environment (32), the root PSP (16) and the UI block (2,172), one paragraph lower. With M: on: the environment (10), MD (21), the root PSP (16), the UI block (2,172).
  - **Resident cost by case:** without EMS, nothing. With EMS and M: off, nothing (the installer is in the cache's spare EMS; the stub uses dead start-up bytes). With M: on, 352 bytes (the MD block and its MCB), all out of the environment's unused room. The EMS pages are M:'s size.
  - SYSTEM.RUN 10,003 bytes (+1,272), DEFRAG.COM 10,220 (+82), BENCH.COM 2,858 (+196).
- **Found on the way:**
  - **`sub_build` overwrote a TSR.** It wrote the Subject list's first entry into `entries` even when the UI block had no room for it, i.e. when a TSR had just been left right after the UI block. Now the list is empty until `ui_room` moves the block.
  - **System's LODE.INI save dropped unknown lines** when there was no M: (a flag test). Fixed.
- **Fixes: two real bugs and five smaller ones, each with a check that fails before its fix (`test_kernel.py t_mdreview`):**
  - **EXEC of "F:X.EXE" overran `ex_name`.** This came from this change's refactor: `full_name` lost its NDRV check, so for a drive the kernel doesn't have, `cwd_of` pointed past `cwdstr` (into `bounce`, or 16 KB further for "1:"). The copy, which has no limit, ran over `ex_name` and on into KEMS's code. Now `drv_present` first; the path is then refused (0Fh).
  - **"A file on M: is open" when none was.** `md_open` tested `S_REF` as a word, which takes in `S_MODE`, and a closed slot keeps its mode and drive. After `COPY A:X M:`, a new size was refused until some other open reused the slot.
  - **M:'s handle closed by a program by mistake and given to another.** M: wrote into the other program's pages, and turning M: off closed that program's handle. `md_dio` now checks the owner (still 0) at no cost in paragraphs, by reading the page count as a word; `md_down` frees only its own.
  - **A disk turned off by a program came back at a warm restart.** Now turning M: off clears its boot sector's first word.
  - **INT 67h 43h failing for want of a free handle** returned 85h, which System didn't expect. It now returns 82h, as for no pages.
  - **Called from inside INT 21h** (a handler, a hot key): the installer re-entered INT 21h, possibly under an M: directory operation. It now refuses with 80h when `indos` isn't 0.
  - **The current drive** was reset to the boot drive on a new size, not only when M: went off. Now only when it goes off.
  - **Left as it is:** a caller with its stack inside the page frame's first two windows (the installer maps them). The only callers are System, the start-up and MDTEST; a real fix needs about 10 bytes in a stub that has one to spare. The API comment says so.
- **Tests:**
  - **`test_kernel.py t_mdisk`, 48 checks:** nothing without EMS, with MDISK=0, or on a 2-page board; the stub and hooks; 256 KB by default (its own handle, owner 0); the MD block split off the environment; an empty FAT12 disk of the right shape; DOS programs' memory the same on and off; 64, 128, 512, 1024 KB, All free, off and 256 KB again, each consistent and split (off: no block, no hook, no EMS); COPY with A:, MD/CD/DIR/DEL/RD, a program run from M:, M: full (MDTEST /F); refused while a file is open (80h); EMS held by a resident program (M: as big as fits: 416 KB); no EMS free (82h); LODE.INI lines (ALL in either case; 128 among other lines; 100: 96 KB; 5: 16 KB; no number or junk: 256 KB; 99999: all); an 8-page board (96 KB); warm restarts (EMS kept, lost, M:'s first page lost; MDISK= changed).
  - **MDTEST /W:** the program's own pages in all four windows, a file of 72 KB in odd pieces across M:'s pages, buffers in the frame (window 1, windows 2–3 across, window 0); every window and page as it was.
  - **`t_mdreview`, 8 checks:** the fixes above (with the fixes taken out, all 8 fail).
  - **`t_cache_ems`:** CACHETST with M: on all along (one more check says so).
  - **`test_apps.py t_mdisk`, 32 checks:** System's topic with no EMS (needs EMS; nothing written), Disks and Memory, every Return step and its LODE.INI line; the Device list and Copy form with M: (copy, rename, move to A:, delete, copy a subject); a program run from M:; the erase question (ESC keeps everything); refused with a file open; M: off while the Executive is on it; MDISK=0 after a restart; the saver and DEFRAG M:.
  - **`test_hd.py t_mdisk`, 8 checks:** C: and M: together (COPY both ways, past 64K sectors), the Device list and Copy form with both, memory with M: on and off. `t_exec`'s Device list now has no B: on its one-floppy machine.
  - **`tests/MDTEST.COM`:**
    - `/Q` query, `/S n` set, `/O n` with a file open;
    - `/W` windows, `/F` fill;
    - `/H n` hold EMS pages (resident), `/K` keep `M:\KEEP.TMP` open (resident);
    - `/C h` close an EMS handle, `/X name` EXEC a name directly.
  - **pcemu:** `warm_boot(ems='keep'|'lose'|pages)`, and Ctrl-Alt-Del through INT 19h at F000:E05B.
  - **All suites pass:** apps 367, kernel 177, hard disk 56, DEFRAG 49, Claude link 21, HEADCLN 9, HDSCAN 20, HDPROBE 33.
- **On the 1520:**
  - **Copy to the floppy** (`releases/0.3.14`): LODE.SYS, SYSTEM.RUN, DEFRAG.COM, LODE.TXT, BENCH.COM and EMSKEEP.COM. LCMD.COM and WRITE.RUN are unchanged.
  - **EMSKEEP first.** Run `EMSKEEP`: it stamps 8 EMS pages and writes EMSKEEP.DAT. Press Ctrl-Alt-Del into Lodestone, then run `EMSKEEP /C`. It says "EMS kept what it held through the restart", "was cleared or rewritten", or "kept part", and adds the result to EMSKEEP.TXT. Run it once under GRiD MS-DOS with EMM.SYS too.
  - **BENCH on M::** in System, Temporary disk, press Return until 1 MB. Then at the command prompt (CODE-P) run `M:` and `A:BENCH /N 10`. BENCH.TXT goes on M:, so `COPY M:BENCH.TXT A:` before switching off.

## A stale M: after MDISK=0 (0.3.15, 2026-10-08)
- **A bug in 0.3.14:** a start-up with M: off (`MDISK=0`, typed into LODE.INI) left the old disk's boot sector in what would be M:'s first page. Programs could then use those pages, and a later start-up with M: on (the same pages again) found the boot sector, a FAT that passed the check, and mounted the old disk with whatever the programs had left in its data. Turning M: off from System was already safe (`md_down` clears the boot sector).
- **Fix (`md_wipe`, KMDISK.INC):** at start-up, when M: isn't made (off, or no room), the first free EMS page, where M: would start, loses an old M:'s boot sector (its first word, only when it starts as M:'s does). It runs in the installer, in the disk cache's EMS page: LODE.SYS +80 bytes, no memory for DOS programs (562.5 / 578.6 / 559.2 / 575.7 KB, as before).
- **Test:** `t_mdreview` gains the case (M: with a file, a warm restart with MDISK=0, then one with no line): it failed before the fix (the old A.COM came back) and passes now. All suites pass: kernel 178, apps 367, hard disk 56, DEFRAG 49, Claude link 21, HDPROBE 33, HDSCAN 20, HEADCLN 9.
- **Version:** LODE_VER 003Fh. 0.3.15 is the last patch number the BH.BL scheme has for 0.3 (minor << 4 | patch): the next release is 0.4.0, or the scheme changes.
- **Copy to the floppy** (`releases/0.3.15`): LODE.SYS and LODE.TXT.

## Term: Claude Code on the GRiD (0.4.0, 2026-10-09)
- **What it is:** `CLAUDE /T` makes the GRiD the screen and keyboard of the real Claude Code, running on a Pi 5 on the GPIB bus on the user's own Claude plan (a subscription may only be used through the unmodified program, so nothing but a terminal sits in between). Only the screen cells that change cross the link; the GRiD's files, DOS programs, screen and GPIB bus are Claude Code tools through an MCP server on the Pi. The design, the measurements and Phase 2 (Claude resident over DOS programs) are in `docs/term.md`; the frame format in `claude-link/PROTOCOL.md`, section 6.
- **On the GRiD:** CLAUDE.COM 1.1 (12,320 bytes, +1,168). Its link moved to `claude/TERMLINK.INC`, its cell drawing to `TERMCELL.INC` with the CELLS decoder, the shadow, scroll, cursor and status band; `TERMKEYS.INC` reads keys with AH=11h/10h and batches them. CODE-Q quits, CODE-R redraws. `CLAUDE` without `/T` is the chat as before.
- **What the user sees:** Claude Code's own screen on rows 0-23 (its prompt box, answers, diffs in inverse, permission dialogs), the session's title and the link on row 24. A DOS program Claude runs takes the screen while it runs; then Claude Code's screen comes back from CLAUDE's copy.
- **Cost:** LODE.SYS unchanged but for the version (45,438 bytes); memory for DOS programs unchanged (562.5 / 578.6 / 559.2 / 575.7 KB). CLAUDE.COM takes 1.4 KB more while it runs (about 68.9 KB), so a DOS program it runs gets 1.4 KB less. Nothing stays resident.
- **Fixes:** nothing unsafe was found in the GRiD's CELLS path; 8 issues and some smaller ones are fixed and tested (`docs/term.md`). The ones on the GRiD: in Term, CLAUDE ignores the chat's messages (a turn still running when the GRiD switched); an answer to HELLO that isn't a HELLO restarts the link; CODE-R held down could cost a REPLY (now one repaint request at a time, and a request runs only when its REPLY has room).
- **The GRiD's tools for Claude Code** (Pi side only): four only look and can be allowed for good; three change something (DOS programs, file changes and copies, anything sent over GPIB) and Claude Code asks before every call. Pi files only inside `~/grid`; copies at most 1 MB and reads 48 KB, bigger is an error, never a cut; every argument checked; DOS device names refused (`AUX` would hang the GRiD) (`docs/term.md`, Tool server limits).
- **Version:** LODE_VER 0040h; the Executive's band and help, LCMD's banner and VER say 0.4.
- **Tests:** all suites pass: kernel 178, apps 367, hard disk 56, DEFRAG 49, Claude link on the kernel 21, HDPROBE 33, HDSCAN 20, HEADCLN 9; claude-link: chat 10 + 20 (emulator), Term 17 + 8 (emulator), MCP 13.
- **Copy to the floppy** (`releases/0.4.0`): LODE.SYS, LCMD.COM, LODE.TXT, CLAUDE.COM.

## The rename (0.4.1, 2026-10-09)
- Grid-OS is now Lodestone: LODE.SYS, LODE.INI, LODE.TXT, LCMD.COM and LODEBOOT.COM (they were GRIDOS.SYS, GRIDOS.INI, GRIDOS.TXT, GRIDCMD.COM and GOSBOOT.COM); the repo's `gridos/` folder is `os/`. The boot sector looks for LODE.SYS, so a Grid-OS floppy needs LODEBOOT once; it runs at the prompt (`t_lodeboot`). Done on the 1520's floppy, and it boots.

## Command (0.4.2, 2026-10-09)
The aim: a command prompt resident Claude can script against, as Claude Code drives PowerShell or Git Bash.
- **The line editor** (LCMD's own; DOS's INT 21h 0Ah when standard input isn't the keyboard):
  - Left, Right, Home, End, Backspace and Del edit the line; ESC clears it; Ctrl-C drops it.
  - Up and Down step through a 512-byte history (the same line twice in a row is kept once); F3 adds the rest of the last line.
  - Tab completes the word before the cursor as a file or subject name (`*` or `*.*` added); Tab again gives the next name, then the first again. A subject gets its `\`.
  - A line wraps over rows; when the screen scrolls the line's start goes up with it.
- **The screen saver at the prompt.** LCMD waits for keys in its own loop (INT 21h 0Bh, then `hlt`). After the Executive's delay it calls the Executive's own saver: DEFRAG on each disk unless TIDY=0, then the dark screen with the time. It keeps the 80×25 text screen in 4,000 bytes taken for the purpose, and puts the screen back afterwards, cursor included. The key that ends the saver is taken. With the start-up floppy taken out, the saver's look for DEFRAG there fails without LCMD's "Abort, Retry, Fail?", as in the Executive, and the dark screen comes on (2026-10-22: it stopped at the question).
  - The kernel's INT 21h F0h AL=5 gives the delay and the far entry, `ui_saver_far` (`call saver` + `retf`).
  - The Executive's `saver` no longer redraws on its own; its event loop does that.
  - `ui_lend`/`ui_reclaim` count, so the saver's DEFRAG, run while LCMD (itself a child of the Executive) is the program, doesn't give the directory buffer back early.
  - At PAUSE and CHOICE too, but not while a FOR, DIR /P or a run of Tabs has a directory search going: DEFRAG could reorder the directory under it.
  - Ctrl-C during the saver does nothing.
- **Batch files:**
  - `IF [NOT] EXIST name | ERRORLEVEL n | a==b command`. EXIST counts subjects too, and `dir\NUL` tests for a subject.
  - `GOTO label`, which also leaves a FOR.
  - `FOR %V IN (set) DO command`. Wildcards give each matching name with its subject; the redirection on the FOR line covers all of it.
  - `CALL name args`, up to 8 deep. The calling file's place, its line and FOR's state wait in a block of their own, so `CALL X && Y`, a FOR in a CALLed file and `CALL X | Y` all work.
  - `SHIFT`, `%NAME%` from the environment, and `CHOICE [/C:keys] [/N] [/S] [/T:c,nn]` (nn at most 99; ERRORLEVEL is the key's place).
- **For scripts:**
  - `a && b` runs b if a worked, `a || b` if it didn't, left to right as in cmd.
  - A program sets ERRORLEVEL to its exit code. A built-in that can fail sets 0 or 1. ECHO, REM, CLS, VER, PAUSE, GOTO, SHIFT, IF, FOR and CALL leave it to the commands they run, so `PROG` / `ECHO` / `IF ERRORLEVEL` still sees PROG's code.
  - **Unlike DOS 3.30:** a DEL or a CD that works after a program resets ERRORLEVEL to 0.
  - An error in a batch file says where: `BUILD line 7: File not found`.
  - A shell reading commands from a file (`LCMD < S.TXT`) ends at the file's end.
- **Redirection and pipes nest:** a FOR's or a CALLed file's own redirection is a level of its own (12 at most), undone level by level, and after Ctrl-C too. Each level's pipe files have their own names (`\PIPEx1.$$$`). Since 2026-11-03 they go in %TEMP% when it is set (docs/lodestone-rom.md), else the current drive's root.
- **COPY** reads and writes up to 64 KB at a time, in a block taken from free memory while it runs; it was 4 KB, kept in LCMD all the time.
  - A 300 KB copy on the floppy, in the emulator's disk model: 35.8 s before, 22.8 s now.
  - TYPE reads 512 bytes at a time as before, so a bad sector costs no more of the text.
- **Cost:**
  - LODE.SYS 45,466 bytes (+26 over 0.4.1). Resident, 32 bytes more (kernel 16, Executive 16), which leaves memory for DOS programs unchanged at 562.5 / 578.6 KB.
  - LCMD.COM is 10,909 bytes (+3,312). It still takes the same memory while a program runs from it (a program gets 16.1 KB less than from the Executive): the copy buffer it no longer keeps pays for the new code and the history. Its BSS is 40 bytes smaller.
- **Fixes:** 12 issues, 10 of them reproduced in pcemu.
  - `CALL` overwrote the line it was on (`&&`, `||` and `|` after it ran garbage).
  - Ctrl-C in COPY or TYPE leaked the buffer and the files; unwind now frees them.
  - Ctrl-C in a CALLed file could leave ECHO off at the prompt.
  - PAUSE and CHOICE hung on a file at its end.
  - `CHOICE /T` over an hour hung the CPU on a divide.
  - Abort during the saver could end LCMD inside the Executive's code; the saver now ignores Ctrl-C and leaves INT 24h's Abort-to-Fail alone.
  - A FOR in a CALLed file was refused.
  - Nested pipes shared their files.
  - `IF EXIST dir\NUL` didn't work.
  - Errors named %1 after SHIFT.
  - CHOICE /S was ignored.
  - DEFRAG could run under a directory search.
  - All are fixed, with tests.
- **Tests:** `t_command` (34 checks: the batch language, exit codes, every fix above, and CMDTEST.BAT), `t_cmdedit` (18: the editor, history, Tab, Ctrl-C, input from a file), `t_cmdsaver` (10: the saver at the prompt and in PAUSE, the Executive's memory and INT 24h afterwards, the start-up floppy taken out).
- **Version:** LODE_VER 0042h.
- **Copy to the floppy** (`releases/0.4.2`): LODE.SYS, LCMD.COM, LODE.TXT, and CMDTEST.BAT, a self-test of the batch language for the 1520 ("All 11 tests passed"). CLEANOLD.BAT deletes the Grid-OS files 0.4.1 replaced. On the 1520 the prompt, history, Tab and the saver all work, and CMDTEST passes all 11.
- **Fixed after 0.4.2 (found by SPIKES.BAT on the 1520, 2026-10-09):** `ECHO.` (a blank line), `ECHO.text`, `CD..` and `CD\` didn't work.
  - **Cause:** splitting a command word from its arguments when no space comes between them relied on AL after `strlen`, which leaves AL at 0.
  - **Effect:** `ECHO. >> FILE` wrote its arguments ("spikes.txt") instead of a blank line.
  - **Now:** `ECHO.` writes a blank line and `ECHO.text` writes the text. LCMD.COM is 10,903 bytes. `t_command` checks all four forms, into a file too.

## Calculator (0.4.4, 2026-10-12)
The aim: a calculator on the 80287, scriptable at the prompt (`CALC 4*4`) and a small window over the Executive like MS-Windows' Calculator. It should use an 80287 or a 287XL when one is fitted. Memory should grow as little as possible, and existing code should be reused.
- **One engine, two hosts.**
  - `src/CALC.INC` holds the engine: the parser, the 80287's and the 287XL's code, whole numbers when there is no coprocessor, and the answer as text.
  - `CALC.COM` (the prompt) and `CALC.RUN` (the window) both `%include` it, so neither stays in memory.
  - `src/FPU.INC` (`fpu_detect`, 42 bytes) is shared by the engine, the Executive and System.
- **Which coprocessor.**
  - Nothing runs on it unless INT 11h says there is one. With no chip, the 286's EM bit may be set, and a coprocessor instruction would trap to INT 7. On the 1520 that bit is POST's own probe, not SETUP's CMOS bit: its `reset.asm` sets it only after the chip answered FNINIT, FNSTCW and FNSTSW, so the Executive's check at start-up never waits on an empty socket.
  - Then FNINIT, and FNSTSW AX must read 0 (with no chip the 286 reads the idle bus).
  - After FNINIT an 80287 compares +∞ and −∞ equal (projective infinity); a 287XL or any 387-class chip doesn't.
- **The grammar** is recursive descent:
  - `+ - * / ^ ( )`; `\` is the whole part of a division and `%` the remainder (C's: towards 0, the sign of the left);
  - `-2^2` = −4, `2^3^2` = 2^9, and `2^-1` works;
  - functions `sqrt sin cos tan atan ln log exp abs`, constants `pi ans`; any other name is the host's (an environment variable in CALC.COM);
  - a sum that starts with `+ * / \ % ^` goes on from the answer.
  - Brackets go 24 deep and 20 operators can wait at once ("Too deep"), so the `.RUN` stays well inside the Executive's stack.
- **With a coprocessor:**
  - the number being worked on is ST0, and the left side of each operator waits in a 10-byte slot, so the coprocessor's stack never holds more than four;
  - all exceptions stay masked (there is no IRQ 13 handler);
  - at the end, FSTSW (invalid, zero divide, overflow) and FXAM (a NaN or ∞ that slipped by without a flag) give "Not a number", "Divide by zero" or "Too big".
- **The 80287's ranges.** On an 80287, FYL2X, F2XM1, FPTAN, FPATAN and FSCALE outside their ranges give garbage with no flag. So:
  - ln and log check x > 0 first;
  - sin, cos and tan reduce with FPREM by π/4, which also gives the octant, then FPTAN (never at 0, never at π/4: an odd octant uses (X−Y)/(X+Y)); sin and cos are Y and X over their hypotenuse, swapped and signed for the octant;
  - in degrees they reduce by 45 instead (exact), and only the remainder becomes radians, on both chips: multiples of 45 land on r = 0, so `cos(90)` and `sin(180)` are 0 and `tan(90)` is "Divide by zero";
  - atan keeps 0 < Y < X (π/2 − atan(1/v) above 1; 0 and ±1 exactly);
  - `^` multiplies out a whole exponent up to 32767 (exact, and a negative base works), else 2^(y·log₂x) with F2XM1 on 0…½ and FSCALE under 2^14.
- **What the 287XL adds:** FSIN, FCOS and full-range FPTAN and FPATAN. In radians they are used directly, faster and exact for big angles, with the 80287's way kept for |x| ≥ 2^63.
- **The answer:** 15 digits, written out from 0.00001 to 10^15, else `1.5E+20`.
  - The decimal exponent comes from FXTRACT's binary one × log₁₀2, corrected by the scaled value. It was FYL2X, but QEMU computes that through host doubles, which overflowed past 1e308 in the emulator; FXTRACT is exact on both.
  - Then the value is scaled to 15 digits, FRNDINT, FBSTP.
  - 999999999999999.9 gives `1E+15`, and 0.1+0.2 gives `0.3`.
- **Without a coprocessor:**
  - whole numbers, 32 bits signed, with `+ - * \ % ^`, checked for overflow ("Too big");
  - `/` when it comes out whole (6/2 = 3; 7/2 says "Needs an 80287"), as do a decimal point, `E` and the functions (ABS works);
  - so `CALC N=N+1` gives the same in a batch file with or without a chip.
- **CALC.COM:** `CALC [/D] [name=]expression`.
  - The answer goes to standard output, so `> FILE` works. An error goes to standard error as `CALC: Divide by zero` and the like, with ERRORLEVEL 1, for `&&`, `||` and `IF ERRORLEVEL`.
  - Names are read from its copy of the environment.
  - `name=` writes the answer into LCMD's environment through PSP:16h, as LCMD's SET does it (the old one out, the new one at the end, "Out of environment space"). The kernel gives a child a copy, so its own would be lost.
  - It writes only when the parent's environment block is owned by the parent and is exactly LCMD's 40h paragraphs (`ENVPARA`, from `LCMDENV.INC`, which LCMD.ASM includes too). The Executive's is the master environment, which M:'s 0.3 KB shares, and it is never written; under any other parent `name=` prints the answer, then "CALC: name= works only at the command prompt" with ERRORLEVEL 1.
  - Names are up to 15 letters and values up to 31 characters; longer is "Name too long" or "Value too long", never cut short into another name or number. The name errors say which name.
  - An answer it couldn't write (a full disk under `> FILE`) is "Can't write the answer", ERRORLEVEL 1.
  - `CALC /?` says how to use it, and which coprocessor it found, on standard output. `CALC` alone or a wrong switch says the same on standard error with ERRORLEVEL 1.
  - It leaves the coprocessor as FNINIT leaves it, so no sticky flag waits for the next program (on the 1520, POST unmasks IRQ 13 when there is a chip).
  - **Two CALCs in the Executive's list** (a known limit, 2026-10-23): CALC.COM and CALC.RUN both show as "CALC", Kind "Program". Return on CALC.COM runs this one with no expression: its usage flashes on the text screen and the Executive says "CALC.COM ended, exit code 1". The calculator window is CALC.RUN, or CODE-K.
- **CALC.RUN** (CODE-K) is a 38-byte by 228-pixel window, with 8.5 KB of save-under in the lent cache memory:
  - the core's line editor for the sum;
  - the answer under it, right-aligned;
  - a 6×6 keypad drawn, hit-tested and acted on from one table.
  - A click ends `UI_EDIT`, so the window adds the key's text itself. After an answer it starts afresh, as typing does. It then pushes one End key with INT 16h AH=05h, so `UI_EDIT` doesn't replace the line at the next key typed. Keys typed meanwhile are taken out first (AH=11h/10h, as the core reads them) and put back after the End, in order, so End always has room and comes first.
  - F2 or the Deg key switches to degrees, and the key is lit while on. F1 is its help. ESC or CODE-K closes it.
  - With `MULTITASK=1`, it can stay open beside the Tasks window: CODE-T opens the tasks from inside it, CODE-K brings it back to the front from the tasks (in front, it still closes it), a click or CODE-F6 changes which is in front (not while its help is open), and there is no save-under (`docs/lodestone-multitasking.md`, M8a).
- **API 5:** the window never sets a redraw routine. So:
  - `run_app` no longer clears the caller's. The Executive's `relist` stays underneath, and after the saver (or a save-under that couldn't be lent) the Executive and then the window are redrawn.
  - Exit code 0FFFFh means the screen is as the program found it, and `run_run` skips the directory read and redraw.
  - System, Write and UITEST set their own routine before their first `UI_EVENT`, so nothing changes for them.
  - Each `.RUN` now says which API it needs: `RUN_API equ n` after the include, which `mkrun.py` writes into the header (else `UI_API`, and never more than it). System, Write and UITEST declare 4 and CALC.RUN 5, so 0.4.4's SYSTEM.RUN still runs on an older LODE.SYS; WRITE.RUN and UITEST.RUN are byte for byte 0.4.3's.
- **The coprocessor lamp:**
  - the Executive's info line shows ` 80287 ` or ` 80287XL ` lit (inverse) after `80286`, and nothing when there is none;
  - it is probed (`fpu_detect`, after INT 11h), not taken from the CMOS bit;
  - the Executive keeps one byte, the lamp's width (0, 7 or 9), for both the text and the inverse;
  - System's Devices names it the same way (`80287XL`, `80287`, `none`).
- **The 287 elsewhere: nothing to gain.** Every `mul`/`div` on the busy paths is a single 16-bit instruction of 13 to 25 cycles:
  - sector maths (`KDISK.INC`);
  - EMS pages (`KEMS.INC`);
  - one per edge row in the start-up picture;
  - cluster maths in DEFRAG;
  - decimal printing.

  The ESC handshake and the operand transfer alone cost more, and `rep movsw` moves memory faster than FILD/FISTP. Using the 287 inside the kernel would also need FSAVE/FRSTOR around a DOS program's own work. Its wins are floating point: this, and the plot view and instrument programs to come.
- **The emulator:** pcemu's CPU is QEMU's, 387-class, so it reads as a 287XL. The 80287's code paths are tested with a build that uses them anyway (`-DCALC_287`). QEMU's own shortcuts:
  - FSQRT of a negative without the invalid flag;
  - an overflow to ∞ without the overflow flag;
  - FPREM and the transcendentals through host doubles: the 80287 path is right to 1e−12 up to |x| = 10^4, and only to 1e−11 at 10^6, where the real FPREM is exact.

  The FXAM check covers the first two; the 1520 checks the rest.
- **Cost:**
  - LODE.SYS 45,930 bytes (+128): the lamp's detection and drawing, CODE-K, and the `relist` skip. Resident +128 bytes (8 paragraphs), so a DOS program gets 562.3 / 578.4 KB (was 562.5 / 578.6).
  - CALC.COM 3,627 bytes and CALC.RUN 4,160 bytes (3,708 + 607 BSS) cost nothing until they run.
  - LCMD.COM is unchanged, byte for byte.
  - SYSTEM.RUN is 10,376 bytes (+60).
- **Fixes:** 9 issues, 5 of them reproduced in pcemu. All are fixed except (8), with tests:
  1. **The window's line was wiped by any key that ends the line editor** (F2, F1, Tab, the arrows, a click off the keys): the next character replaced the whole sum. Now the window goes back to the editor with End first, unless the line is the answer's.
  2. **A leading `+` didn't go on from the answer:** it was taken as a plus sign. Fixed.
  3. **FPREM on an infinity could loop forever on a real 80287**, which leaves C2 undefined there (`sin(1e5000)`, `(1/0)%3`). FPREM now runs only on a number, by the same check as at the end.
  4. **`name=` could write into another program's environment** when the copy EXEC made for it happened to be 1 KB. Now nothing may follow the block's end: EXEC's copies carry 0001h and the program's name there.
  5. **`0^-0.5` gave 0.** It is now "Divide by zero".
  6. **A full environment lost the old variable:** it was taken out before the room was checked. The room is now checked first.
     - The first version of that fix summed in AX across a `strlen` that changes AL. That let a 1016-byte environment overflow into the next MCB. The new test caught it, and it is fixed.
     - LCMD's own SET still behaves as before here.
  7. **INT 16h AH=05h on the 1520:** confirmed in GRiD's BIOS source (`KbPlaceChar`, which puts the key at the buffer's tail).
  8. **API 5's two changes apply to older `.RUN`s too.** Left as is: every `.RUN` there is sets its redraw routine first and none returns 0FFFFh, and checking the header's API would cost resident bytes.
  9. **A stale strip after the Executive was redrawn under the window** (the saver, then a changed listing). The window counts its paints, and when it was repainted it exits with 0, so the Executive reads the disk and redraws.
- **More fixes (2026-10-12):** 17 findings after merging; ten were fixed, and the nine bugs among them, below, each have a test. Eight of those tests were run against the code before and failed; the ninth, the API stamp, fails by construction (the old `mkrun.py` wrote 05 into every header):
  1. **`name=` under a parent that isn't LCMD printed, set nothing and gave ERRORLEVEL 0,** so `:loop / calc i=i+1 / if not %i%==3 goto loop` would never end. Now "name= works only at the command prompt", ERRORLEVEL 1, and `ENVPARA` comes from one file (`LCMDENV.INC`) for LCMD and CALC.
  2. **`mkrun.py` stamped every `.RUN` with the current API,** so 0.4.4's SYSTEM.RUN would be "Not a program" on a floppy with an older LODE.SYS. Now `RUN_API` (above).
  3. **Misuse looked like success:** `CALC /X`, `CALC %UNSET%` and a bare `CALC` printed the usage to standard output with ERRORLEVEL 0. Now standard error and 1; `CALC /?` for the usage on purpose.
  4. **Sticky flags left on the coprocessor** after a good answer (only an error ran FNINIT). `calc_fmt` now ends with FNINIT. Mattered more than it looked: POST unmasks IRQ 13 on the 1520.
  5. **Write errors ignored:** `CALC 6*7 > FILE` on a full disk left an empty file and ERRORLEVEL 0.
  6. **The window's paint count was a byte:** the 257th repaint made it 1 again, and the window would close with 0FFFFh over a stale save-under. Now a sticky shift (1, 3, 7 … FF).
  7. **Long names and values were cut short silently:** a 33-digit value became a number 100 times smaller. Now "Name too long" / "Value too long", and the name errors say which name.
  8. **The window's End key queued behind type-ahead,** so a key typed while a click was handled wiped the clicked sum (and a full BIOS buffer dropped it). Keys typed meanwhile now come out and go back after the End.
  9. **Degrees gave chip-dependent answers:** π/180 was applied before reducing, so `/D cos(90)` printed 6.12323399573677E-17 in pcemu (a smaller but still non-zero number on a real 287XL) while the 80287's path could print 0. Now reduced by 45 in degrees on both.
  10. **Resident bytes:** `run_usage` jumps to `run_write.e`, and the lamp's width is worked out once, at start-up. 8 bytes of code, but the resident block was 6 bytes into its last paragraph, so DOS programs get 16 bytes back.

  Settled without a change: **the start-up probe can't hang on an empty socket** (POST's own probe sets INT 11h's bit, above). Left as they are, by choice: delete the 287XL's code or the whole-number engine (both are wanted; the 80287's path is tested by `-DCALC_287`), gate API 5's changes on the header (resident bytes), compare the memory check with 0.4.3's LODE.SYS rather than fixed figures, `ans` and the leading operator in the one-shot CALC.COM, and a guard in `draw_ans` that can't fire.
- **Tests:**
  - `test_kernel.py` `t_calc` (114 checks):
    - sums, formatting and errors with ERRORLEVEL;
    - redirection;
    - `name=`, counting in a batch file, and `%%`;
    - the environment fixes (a 1 KB copy, a full block);
    - the 80287's code paths against Python;
    - FPREM never on an infinity;
    - a parent that isn't LCMD (`RUNCALC.COM`, which prints CALC's exit code);
    - whole numbers with INT 11h saying none;
    - the 2026-10-12 fixes: degrees on both paths, long names and values, `/?` and misuse, the coprocessor's status word after a sum, and a full disk.
  - `test_apps.py` `t_calc` (33):
    - the lamp lit and absent, and System's Devices;
    - the window: keys, `+1` and `*10` after an answer, Up and F2 inside a sum, the keypad, Deg lit, help, errors;
    - the screen byte for byte after ESC, with the UI block back to its size;
    - the saver with the window open, then exit code 0, and again after 257 repaints;
    - keys typed while a click is handled (put in the BIOS buffer as `keep_line` starts, through pcemu's block watch);
    - the `.RUN` headers: CALC 5; System, Write and UITEST 4;
    - no CALC.RUN, and the Executive's help.
  - The re-baselines:
    - `test_splash.py`'s memory check can't run 0.4.2's LODE.SYS any more (the Executive's layout moved and ktest reads it by the new map), so it now compares with and without the picture against 562.3 / 578.4 KB;
    - `test_apps.py`'s floor is 562.3 KB;
    - System's Devices expects 80287XL.
  - All 1005 checks pass: kernel 355, apps 400, splash 62, C: 56, DEFRAG 49, Claude link 21, HDPROBE 33, HDSCAN 20, HEADCLN 9.
- **Version:** LODE_VER 0044h, UI API 5.
- **Copy to the floppy** (`releases/0.4.4`): LODE.SYS, LODE.TXT, CALC.COM, CALC.RUN and SYSTEM.RUN. WRITE.RUN is 0.4.3's.
- **On the 1520 (2026-10-13), first run: no coprocessor found** (`bench/CALCTEST_1520_2026-10-13_044.TXT`). The lamp stayed dark, and CALC said `Coprocessor: none: whole numbers only`. The whole-number engine itself was right: `6*7`, `-2^2`, `2^3^2`, `7\2`, `7%2` and the batch loop all passed, and the rest said "Needs an 80287". Fixed in 0.4.5 (below).
- **0.4.5 on the 1520 (2026-10-13): all passed** (`bench/CALCTEST_1520_2026-10-13.TXT`, run by `tests/CALCTEST.BAT`):
  - `Coprocessor: 80287`.
  - **Exact answers, 18 of 18:** `0.1+0.2` 0.3, `2^-1` 0.5, `sqrt(16)` 4, `pi`, `999999999999999.9` 1E+15, `sin(0)`, `tan(0)`, `atan(0)`, `atan(1)` π/4, `/D tan(45)` 1, `/D cos(90)` 0, `/D cos(180)` −1, the whole-number sums, and `CALC N=N+1` counting in a batch file.
  - **Against 15-digit references, 15 of 16 to the last digit:** `2^0.5`, `sqrt(2)`, `1.5^2.5`, `exp(-0.7)` (0.49658530379141: pcemu's QEMU gives …409), `exp(1)`, `ln(10)`, `log(2)`, `sin(1)`, `cos(1)`, `tan(1)`, `atan(0.5)`, `atan(3)`, `1e300*1e300` (1E+600), `/D sin(30)`, `/D tan(60)`.
  - **`sin(1e6)`:** −0.349993502171308 against −0.349993502171293, 1.5e−14 out, inside the 1e−13 expected from reducing by the 80287's 64-bit π/4. pcemu's 80287 path is 5e−11 out (QEMU's FPREM through doubles).
  - **Errors:** `ln(0)` and `log(-1)` Not a number, `1/0` and `0^-0.5` Divide by zero, `sin(1e5000)` Too big (no hang), each with ERRORLEVEL 1.
  - **The Executive:** the lamp lit `80287`; System's Devices says 80287; the window's typed sums, `+1` after an answer, keypad clicks, F2 degrees, F1 help, and ESC back to the Executive as it was.
  - Still to see: no coprocessor (the chip out, or bit 1 of 0:410 cleared with DEBUG), and a 287XL.

## The 80287 found (0.4.5, 2026-10-13)
- **The bug:** `fpu_detect` (FPU.INC) wanted the whole status word to be 0 after FNINIT. A real 80287's FNINIT leaves the condition codes C0-C3 as they were. On the 1520 the status read 4000h: C3 was still set from the last compare. So the lamp, System's Devices and CALC all said there was no coprocessor.
  - The 1520's POST masks C0-C3 in its own probe (`reset.asm`: "they are undefined after FINIT"), so INT 11h's bit was set all along.
  - TM5000G checks the control word (037Fh) instead, so it found the chip.
  - A 387-class chip clears C0-C3 at FNINIT. pcemu's CPU is QEMU's, 387-class, so no test could see it.
- **The fix:** the check is `test ax, 0B8BFh`: every bit but C0-C3 and bit 6 (reserved on the 80287), the mask POST means to use. +1 byte.
  - LODE.SYS is 45,932 bytes, CALC.COM 3,628, CALC.RUN 4,161 and SYSTEM.RUN 10,377.
  - A DOS program still gets 562.3 / 578.4 KB.
- **Test:** the `-DCALC_287` build now also sets C0-C3 after FNINIT, as the 80287 may. `t_calc` checks that it still says `Coprocessor: 80287` (115 checks). On the old check, 33 of them fail.
- **For the 1520:**
  - `tests/FPUPROBE.COM` prints what the coprocessor answers after FNINIT: INT 11h, the MSW, the control and status words, C0-C3, and which kind the infinities say. Measured: `INT 11h 4463  MSW FFF0  after FNINIT: control 037F  status 4000  C0-C3 0001  infinities equal (80287)`.
  - `tests/CALCTEST.BAT` tests the calculator step by step and logs `CALCTEST.TXT`:
    - step 1: the sums at the prompt, exact ones checked, the rest logged for comparison;
    - `CALCTEST W`: the Executive side.
- **Version:** LODE_VER 0045h. `releases/0.4.5`: LODE.SYS, LODE.TXT, CALC.COM, CALC.RUN, SYSTEM.RUN, CALCTEST.BAT, FPUPROBE.COM.
- **Fixed after 0.4.5 (2026-10-17; tested in emulation):**
  - **LODE.INI past 511 bytes:** `font_boot` read only the first 511 bytes, so once System's file grew past them its FONT=, SAVER= and TIDY= lines (written last) were lost at start-up. SPLASH= and MDISK= were already read past 1 KB (see `lodestone-splash.md`). It now reads 4095 bytes like them; the font file goes after them in the directory buffer. LODE.SYS is the same size and nothing more is resident. `t_saver_delay` checks all three after 960 bytes of other lines.
  - **SET with no room:** LCMD took the old NAME= out before looking for room for the new value, so "Out of environment space" left the variable gone. It now looks first, counting the old entry as freed, as CALC already did. `t_calc` checks both a replacement that only just fits and one that doesn't.
  - **COPY:** its 64 KB buffer is now whole sectors (65,024 bytes, not 65,520), so reads and writes after the first don't start part-way through a sector. A 300 KB COPY with the 1520's drive timing: 22.85 s → 21.26 s.
  - LCMD.COM is 10,970 bytes.

## Windows that move and close (UI API 6, after 0.6, 2026-10-19)
The aim: Lodestone's own programs as GUI-style windows, the calculator first; and the first step towards multitasking, where several will be open at once.
- **API 6:**
  - A window gets a seventh word, `W_FLAGS` (so `W_SIZE` is 14). `WF_MOVE`: the user may move it. `WF_CLOSE`: a close box at the right end of its title strip.
  - The core reads `W_FLAGS` only from a `.RUN` that needs API 6 or newer (`win_flags`). An older `.RUN`'s windows are 12 bytes, so there is no such word: they never move. SYSTEM, WRITE and UITEST still declare API 4 and are unchanged.
  - `UI_EVENT` handles the top window's title strip itself:
    - a press drags a `WF_MOVE` window: a 1-pixel XOR outline follows the pointer, snapped to byte columns and to rows in fours (the glyph blitter's rule), kept between the title rule (row 24) and the band (360);
    - CODE-F7 (6E00h) moves it with the arrow keys, a column or 4 rows a press; Return puts it there, ESC leaves it;
    - a click on the close box (a dark cell with an x, the strip's last cell but one) gives K_ESC, which every program already treats as "close" (with `MULTITASK=1`, a `.RUN` for API 9 gets `EV_CLOSE` instead: UI API 9 below).
  - After a move, `UI_EVENT` returns `EV_MOVED` (0FF02h).
  - `UI_EDIT` in a moved window carries on: the core shifts the field with the window, and the cursor stays where it was in the line. (`UI_EDIT` sets the field's place on every call, so shifting it when no editor waits does no harm.)
- **The move itself** (`win_move`):
  1. the screen under the old place comes back from the save-under (`win_restore`, split out of `ui_wclose`);
  2. what is under the new place is saved into the same slot (the size is unchanged);
  3. the window is painted there.

  With no save-under (the disk cache's memory already lent out), everything is drawn again (`redraw_all`).
- **The calculator** draws everything from where its window is now (`icol`, `ey`, `ry`, `ky`, worked out in `w_draw`). A paint at a new place (after a move) doesn't count as a repaint over an older screen, so closing after a move still ends with 0FFFFh: the save-under taken at the move is current, and the Executive doesn't redraw. Its help lists CODE-F7.
- **Not tested on the 1520 yet:** that its BIOS gives CODE-F7 as 6E00h through INT 16h AH=10h, as a PC BIOS gives Alt-F7. pcemu only confirms its own key mapping.
- **Tests:** `t_calc_move`, 18 checks:
  - the close box;
  - a drag (the window, its title and its keys at the new place; the line editor goes on);
  - CODE-F7 with Return and with ESC;
  - clamping at both corners;
  - the saver with a moved window;
  - closing after two moves (exit code 0FFFFh, the screen exactly as before);
  - a click on the title that doesn't move it;
  - a move with no save-under.
- **Cost:** the UI block's code grows by 530 bytes (`ui_image_end` 53EAh → 55FCh), so a DOS program gets 0.5 KB less: 561.7 KB without EMS, 577.8 KB with it (0.6: 562.2 / 578.3). The kernel is unchanged (`image_end`, `bss_end`). CALC.RUN is 4,378 bytes (+217). ROM 1 has 24,576 bytes left, one sector less (LODE.SYS is 48,380 bytes).
  - It was 656 bytes at first. Reusing what the core already had saved 126:
    - the outline is drawn by the form's field outline (`fm_outline`'s XOR frame, now `xor_rect`) instead of a routine of its own. That frame went pixel by pixel; it now runs along a row with a rotating bit and down a side a row lookup at a time, so a drag step costs about 10,500 instructions (52,000 pixel by pixel; the byte-wise routine before, 3,800), and the form's outline is quicker too;
    - the drag reads the mouse through `mouse_event`;
    - the mouse and the keys share one move routine (`win_mv`);
    - no flag for "an editor waits" (above);
    - and `W_DRAW` isn't told why it is drawn: the calculator compares its window's place with where it drew last.

## Window .RUNs and resizing (with MULTITASK=1, M8, 2026-10-22)
Only with the switch on; the core with it off ignores all of this. The details are in `docs/lodestone-multitasking.md` (M8a, M8b, M8c).
- **The Executive stays live under the windows** (M8c), and what it draws is cut around them. A full-screen `.RUN` (System, Paint) can't start while window `.RUN`s are open: the Executive says to close them first.
- **`RUN_FLAGS equ RF_WIN`** after the include puts bit 0 in the header's word 14 (`mkrun.py`; it was always 0, and no core reads it with the switch off). It says the `.RUN` is a window `.RUN`: with `MULTITASK=1` it runs as a session, beside other windows, and doesn't make its starter wait. Its windows then have `W_FLAGS` whatever its `RUN_API`, so Write can keep asking for API 4. CALC, TASKS and WRITE set it; SYSTEM doesn't, and a full-screen `.RUN` such as Paint shouldn't.
- **`WF_SIZE` (4) in `W_FLAGS`:** the user may resize the window:
  - by its bottom-right corner (its last column, the bottom 12 pixel rows): a press there drags the outline's corner, snapped to columns and to rows in fours;
  - by CODE-F8 (6F00h): the arrows widen or narrow it a column, lengthen or shorten it 16 rows; Return keeps the size, ESC leaves it.

  It stays at least 24 columns by 72 rows, on the screen above the band; ESC puts back the size it had. Then the screen is drawn again (the window's `W_DRAW` at its new size) and `UI_EVENT` returns `EV_SIZE` (0FF04h).

## Right clicks (UI API 7, 2026-10-21)
- **What:** `UI_EVENT` and `UI_POLL` give `AX = EV_RCLICK` (FF03h), with BX = x and CX = y as for `EV_CLICK`, for a press of the right button.
  - It is the first user of the right button. Paint (`PAINT.RUN`) declares API 6 and doesn't use it yet; a right-drag to erase is a step of its own.
- **Only to a program that asks:**
  - The program must be a `.RUN` that needs API 7 (`RUN_API equ 7`); the core checks its header's version, as `W_FLAGS` does for API 6. Older `.RUN`s (System, Write, the calculator, UITEST) never see the event. Their key handling was written before it existed. The Executive sees it in its own list since 2026-11-04 (its menu, below), and only there.
  - The left button must be up.
  - Both buttons pressed in one packet give `EV_CLICK` only.
- **A window's drag:** `win_mv` follows the mouse through `mouse_event`, which with no event leaves x and y in AX and BX.
  - When the left comes up and the right goes down in one look (a roll from one finger to the other, or two packets while the outline is drawn), `mouse_event` returns `EV_RCLICK`, with x and y in BX and CX.
  - `win_mv` now takes them from there; before, it read the event code as x, and the window jumped to the right edge. The press goes into ending the drag and doesn't reach the program.
  - A right press on a window's title strip or close box neither moves nor closes it: the program gets it.
- **The core's own waits,** inside an API 7 program:
  - `UI_EDIT`, and so `UI_FORM`'s text fields, ignore every event but `EV_CLICK`. A first character typed still replaces the text: before, a right click went down the editing-key path and lost that.
  - `UI_FORM`'s choices and `UI_ASK` ignore it.
  - `UI_MSG` and `UI_HELP` take it as any key.
  - `UI_LVKEY` returns CF: not a list key.
  - **`UI_DISPATCH` matches ASCII entries by AL alone,** so a table entry for 01h–03h (Ctrl-A to Ctrl-C) would run on `EV_CLICK`, `EV_MOVED` or `EV_RCLICK`. No table has one. UIAPI.INC says so.
- **The code:**
  - `mouse_event` finds the buttons pressed since the last look (`NOT old AND new`).
  - It builds the event in DX, so AX and BX still hold x and y when there's none.
  - The "left up" test is a `SHR CL, 1` into CF.
- **Versioning:** `UI_API` is 7, so a `.RUN` built without `RUN_API` now needs 7 and is refused by an older LODE.SYS, as at 5 and 6. Every `.RUN` here declares its own `RUN_API` (System, Write, UITEST 4, the calculator 6), so they are byte for byte as before.
- **Known limit (as for the left button since 0.3.1):** after `UI_RUN` the core doesn't take the buttons' state again. A button still held when the DOS program ends gives a click on the way back. Only the saver's wake takes it again.
- **Cost:**
  - The core's code grows by 31 bytes: 25 for the event, 5 for `win_mv`, and 1 for `UI_EDIT`. `ui_image_end` grows by 30 (4E90h → 4EAEh), because an `align 2` takes up one.
  - `ui_keep_end` grows by 32 (6144h → 6164h). MEMSZ reads 0.1 KB less: 566.2 KB without EMS, 582.3 KB with it.
  - The kernel is unchanged.
- **Tests (`t_rclick`, 14 checks; `tests/RCTEST.ASM`, an API 7 `.RUN` that records every event, and `RC6.ASM`, the same for API 6):**
  - the event with its x and y; nothing at the release;
  - the left click as before; both at once; the right while the left is held;
  - a window dragged with the right pressed half way, and one where the left goes up as the right goes down in one packet: each exactly where the drag left it;
  - right clicks on the close box and the title strip;
  - `UI_EDIT` on "ab" and `UI_ASK`: the right click seen reaching them, and ignored;
  - nothing in the Executive, before or after an API 7 `.RUN`;
  - nothing in the API 6 build.
  - The checks catch each gate taken out, the event built in AX, `win_mv` reading AX as x, and `UI_EDIT` taking it as an editing key.
  - The drag's roll case and `UI_EDIT`'s lost "typed first replaces" are fixed, with a check each.
  - The hook that watches the Executive sits at `ui_event.got`, a jump target. A label reached by falling through, as `mouse_event.ev` is on the right button's path, is not hooked in pcemu, so a hook there would have seen nothing.

## Pop-up menus and drags (UI API 8, 2026-10-23)
The first of four steps toward right-click editing in Write: this one is the core's part. Then come a clipboard shared by every `.RUN` (`UI_CLIP`), Write's drag selection and right-click menu, and its Cut, Copy and Paste (CODE-Z, CODE-C, CODE-V).
- **`UI_MENU` (entry 47):** a pop-up menu.
  - In: SI = AL items (1–20), each a word pointer to ASCIIZ; AH = the item lit first (below AL); BX = x, CX = y, as `EV_RCLICK` gives them.
  - A window at that point, without a title, kept on the screen: its column at most 80 less its width, its row between the title rule and the band, a multiple of 4. It is as wide as the longest item and 4 columns more, and 16 rows per item and 8 more high.
  - The arrows, PgUp, PgDn, Home and End move the light; a letter lights the next item starting with it (`UI_LVKEY`); Return (or CODE-Return) or a click on an item chooses: CF clear, AX = the item.
  - ESC (or CODE-ESC), or a click outside the window: CF set. The click does nothing else (it is taken). A click inside the window above the first item or below the last (its top and bottom edges) does nothing; one on its left or right edge, on an item's row, chooses that item.
  - With four windows open (`NWIN`) there is no room for it: CF at once, with a beep, as `UI_FORM` does. Otherwise it would be no window: not drawn, not modal, and (with `MULTITASK=1`) a borrow of the cache nobody gives back. AL outside 1–20 is refused the same way; AH past the last item lights the first. It is at most 80 columns wide: longer items are cut at the edge.
  - Items that don't apply are left out by the caller, not greyed: it costs the core nothing.
  - It is built from what was there: the help window's structure (`help_w`, as `UI_HELP` and `UI_FORM` use it) and a list view (`LV_*`) in the core's BSS.
- **`UI_MOUSE` (entry 48):** the mouse now, for a drag.
  - It waits for the next interrupt (a tick at most), then: AX = the buttons down (bit 0 the left, bit 1 the right), BX = x, CX = y. CF set if there is no mouse.
  - The pointer stays hidden (the program shows where the drag is, as `win_mv` does with its outline).
  - It keeps the buttons as seen (`oldmb`), so a press seen here is no event later: a program calls it after `EV_CLICK` until the left button is up, and the next press is an event again.
  - The saver doesn't start meanwhile (each call is activity).
- **With `MULTITASK=1`:**
  - **The menu saves what is under it.** A window `.RUN`'s windows have no save-under (M8a: `mw_lend` lends no cache while one runs, so closing one draws the screen again, through the Executive's directory). A menu over one would have done that at every close. So when windows are open and none is saved, the menu borrows the cache itself (F002h) and gives it back after (`mn_lent`). That is safe where M8's rule isn't needed: the menu is modal and doesn't move, and nothing else is drawn over it meanwhile.
  - **It is modal:** it is `help_w`, so `mw_modal` keeps the focus where it is. CODE-F6 and the launch keys do nothing; a click on another window is a click outside: no choice, and that window doesn't come to the front.
  - **A drag lets the tasks run.** `UI_MOUSE` and `win_mv` (a window moved by its title strip) wait in `mwait`, whose HLT is a safe point like the UI's idle one (`..@ui_midle`, beside `..@ui_idle` and `..@ui_sidle` in `mt_safe`). Before, a window's drag held every DOS task until the button came up. As at the idle HLT, a tick that finds the UI there ends its turn (`mt_tick`: just after a HLT), and between the mouse's bytes (about 8 ms each) it is there nearly all the time: so the tasks get their turns while it moves too. So that a drag still follows the mouse, MT notes where the mouse was when it switched from the UI there (`mt_mdset`: `mt_mdrag`, `mt_mx`, `mt_my`, `mt_mb`), and once it has moved, or a button has changed, the UI is the next to run, at the next tick, ahead of the tasks behind (`mt_mwant`, beside `mt_kwant`'s key for the front task). While it moves, the drag runs every other tick at least, whatever the number of tasks; held still, the UI waits its turn and the tasks get the rest. The round then goes on after the task a boost took the turn from (`mt_mrot`, in `mt_pick`), so every task behind gets its turns while the mouse moves, not only the first; and the boost is used up once the UI runs (`mt_load` clears `mt_mdrag`). Known limit: a packet that comes after the UI last read the mouse but before its wait (the button let go, say) is only seen at its next turn, up to a round of the tasks behind later. Resizing (`mw_size`, in MT's own code) still holds them.
- **Versioning:** `UI_API` is 8. Every `.RUN` here declares its `RUN_API`, so they are byte for byte as before; Write moves to 8 with its menu (an older LODE.SYS will refuse that WRITE.RUN).
- **Cost:**
  - The core's code grows by 422 bytes (`ui_image_end` 4F5Ah → 5100h): `UI_MENU` is most of it, `UI_MOUSE` and `mwait` about 40. Its BSS by 23 (`mn_tab`, `mn_lv`, `mn_lent`, outside every range a session keeps: M8's `mw_ctx` doesn't grow).
  - `ui_keep_end` grows by 438 bytes (621Ah → 63D0h). MEMSZ reads 0.5 KB less: 564.9 KB without EMS, 581.0 KB with it; with `MULTITASK=1` 561.1 KB (561.7 before; MT's block 1,276 paragraphs, 13 more, for `..@ui_midle` and the mouse boost).
  - LODE.SYS is 48,704 bytes (48,288 before), LODEMT.SYS 17,484 (17,270). ROM 1 has 1,536 bytes left (2,560 before).
- **Tests:**
  - `t_menu` in test_apps (20 checks; `tests/MENUTEST.ASM`, an API 8 window `.RUN` that opens a window with a pattern in it, a menu at each right click, M and N for menus at (639, 399) and (0, 0), and a drag at each left press):
    - placed at the click, its size from its items; Down, Down, Return; a letter; a click on an item; a click outside (taken: no event, no drag); a click on its edge (still open); ESC (the program's window still open);
    - the screen under the title bar byte for byte as before after each;
    - kept on the screen at (639, 399) and (0, 0); AH = 3 lit first, and AH past the last item (the first lit); 20 items at (100, 399), from row 32; an item of 90 characters (the menu 80 columns wide, from column 0);
    - four windows open (the most): no menu, CF at once, nothing drawn;
    - the saver while it is open: back after it, with the same item lit;
    - a drag followed to its end, and the next press an event again; the right pressed during a drag and let go after the left: no right click after it (no menu);
    - with no window open: `ui_wopen`'s own save-under, and the cache given back;
    - with no mouse: `UI_MOUSE`'s CF.
  - `t_menu` in test_mt (5 checks):
    - in a window session: the cache borrowed, the screen as it was with no `redraw_all`;
    - CODE-F6 and a click on the Executive while it is open: the focus stays;
    - a drag with two MTSPINs behind: switched to from `UI_MOUSE`'s wait (`..@ui_midle`), every switch at a safe point (the test's safe-point rules know the new spot); held still, the UI only its turn; moving, each position seen within the tick (`mt_mwant`), and both MTSPINs taking turns between.
  - Between them the checks fail with any one of these taken out or broken: the three clamps (right, below, above), the column test and the row test of a click, a click on the edge taken as outside, no ESC, the light not where AH says, AH past the last item kept, no width clamp, no `NWIN` guard, no borrow of the cache, the cache not given back, `UI_MOUSE` not keeping the buttons (a right press during a drag became a menu after it), its CF not set with no mouse, `..@ui_midle` not a safe point, no `mt_mwant`, the buttons not noted by `mt_mdset`, and the round not going on after the task a boost took the turn from.

## The clipboard (UI_CLIP, UI API 8, 2026-10-23)
The second of the four steps toward right-click editing in Write: a clipboard every `.RUN` shares. Write's Cut, Copy and Paste (step 4, below) use it, and any program after them.
- **`UI_CLIP` (entry 49):**
  - AL = 0: CX bytes from ES:DI into it, at most 16,384 (more: CF, AX = 8, and what it held is kept). CX = 0 empties it.
  - AL = 1: what it holds into ES:DI, CX bytes at most -> CX = how many.
  - AL = 2: -> CX = how many it holds (0: empty).
  - CF: AX = the error, an EMS one (80h and up) or DOS's (`UI_SBERR` words them).
  - The bytes are as given: text in the program's own form (Write's lines end in LF, as in its buffer).
- **Kept when a program ends:** the core holds it, so a `.RUN` can copy, end, and another (or the same, on another file) paste. With `MULTITASK=1` every window `.RUN` shares it, and the state (`clip_h`, `clip_len`, `clip_f`) is outside every range a session keeps (`mw_ctx`).
- **Where:**
  - **An EMS page of its own,** taken the first time something is put (INT 67h 43h, one page) and copied in and out with 57h, so the page frame isn't touched. The handle is nobody's: the UI's code isn't in the running program's memory, so `ems_alloc` gives it owner 0, and no program's end (nor a task's, parked or killed) takes it back.
  - **Without EMS, or with none free** (`MDISK=ALL` takes every page): `CLIP.$$$` in the root of the settings drive (INT 21h 3305h's DH, where LODE.INI's changes go), else of the start-up drive; started from the ROM with neither, C: if there, else A: (as System saves settings; R: takes no writes). The drive is chosen once, at start-up. Written anew at each put, read at each get. A short write (the disk full) is error 29, a short read error 30. A put that can't even make the file leaves what the clipboard held; once the file has been cut, any error empties it. A get that fails (the file gone, or another floppy in the drive) keeps the size: the clipboard still says it holds something, so Paste is offered again and fails until the next Copy, or until the disk comes back.
- **Cost:**
  - The core's code grows by 322 bytes (`ui_image_end` 5100h → 5242h), its BSS by 5.
  - `ui_keep_end` grows by 342 bytes (63D0h → 6526h). MEMSZ reads 0.3 KB less: 564.6 KB without EMS, 580.7 KB with it; with `MULTITASK=1` 560.7 KB.
  - LODE.SYS is 49,040 bytes (48,704 before); LODEMT.SYS is the same size (17,484 bytes). ROM 1 still has 1,536 bytes left. One EMS page, only once something is put.
- **Tests:**
  - `t_clip` in test_apps (9 checks; `tests/CLIPTEST.ASM`, an API 8 window `.RUN` with keys for put, get and size, and a block of its own for the bytes):
    - with EMS: empty at first, and emptied takes no page yet; 1000 bytes put (a page of its own, one page, nobody's; no file); got with room for 2000 (just them, nothing past) and for 10;
    - the program ended and started again: still them, the same handle;
    - 16,385 refused (error 8, what it held kept); 16,384 put and got back whole, the same handle; 0 bytes: empty;
    - no EMS: emptied first writes no file; `A:\CLIP.$$$` holds exactly what was put, got back whole, and after the program starts again; another put rewrites it;
    - EMS with every page M:'s (`MDISK=ALL`): the file.
  - `t_clip` in test_mt (1 check): put from a window session; the session ended; a task with an EMS page of its own (MTKILL F) started, parked, back and killed from LCMD, its page freed; the clipboard and its handle as they were.
  - The checks fail on each of: no 16 KB limit, the size not kept, a get not cut to what it holds, a new page at every put, no fall-back to the file, both copies in the same direction, the error not in AX, and emptying not done at once (it took a page, or wrote the file). Untested: the settings drive over the start-up one (a floppy start has both as A:), and a short write to the file (a full disk).

## Write with the mouse: drags and a menu (UI API 8, 2026-10-23)
The third of the four steps toward right-click editing in Write. Write asks for UI API 8 now (`RUN_API`; an older LODE.SYS refuses it) and uses `UI_MOUSE` and `UI_MENU`. Its keys are as they were.
- **A drag selects.** A press in the text puts the cursor there, as a click always did. While the left button is held, `UI_MOUSE` follows the pointer, and the cursor with it, until the button is up:
  - **editing,** the first move makes a selection of its own: from where the button went down to the cursor (`M_SEL` with no command yet, `cmd` 0). The band says what can follow: "Selected: CODE-E erases   CODE-M moves   CODE-D duplicates" / "Right click: the commands   ESC cancels" (step 4 changed that second line, below);
  - **making a selection** (CODE-E, CODE-M or CODE-D first, as GRiDWrite does it), the drag is the selection, from where it began; Return confirms as before;
  - **pointing** (Move's and Duplicate's destination), the cursor follows;
  - past the top or the bottom of the text area the cursor goes a line beyond it at each look (a tick apart at most, after each redraw: about 10 lines a second in pcemu), so the view scrolls while the button is held; past a side of a window's text area, a column beyond, so a long line scrolls sideways (the whole screen's has no room beside it); below the text's end, its end;
  - a drag back to where it began, or a click, ends a drag's selection (editing again, the cursor where it was let go or clicked).
- **Then the command.** With a drag's selection up: CODE-E, Backspace or Delete erase it at once; CODE-M and CODE-D take it and ask where to (as after Return in GRiDWrite's order); emptied (CODE-B, or the cursor keys back to where it began), these beep and it stays a drag's; CODE-B starts it again at the cursor; ESC ends it; the cursor keys extend it. Return beeps (the command first). Any other key ends it and is an ordinary key: a character is typed at the cursor, not over the selection.
- **A right click in the text: a menu** (`UI_MENU`, at the click) of Write's commands: Erase, Move, Duplicate, Find..., Substitute..., Jump..., each with its key.
  - Editing, the cursor goes where the click was first; with a drag's selection, the selection is kept and the menu's Erase, Move and Duplicate work on it. Without one they start as their keys do (then make a selection and confirm). Find, Substitute and Jump end a drag's selection first.
  - After Find has shown what it found, a right click in the text (like a left one) is editing again.
  - Outside the text area (its window's frame, the rule, the status line, the band), and while pointing or making a selection for a command, a right click does nothing.
  - Cut, Copy and Paste came in step 4, at the top of this menu (below).
- **With `MULTITASK=1`** the same in Write's window: the text area is the window's (`x0`, `y0`, `cols`, `rows`), and a drag lets the tasks behind run (`UI_MOUSE`'s wait).
- **Help:** two lines say it (the help window stays at 15 lines, so step 4's three fit in its 18): "Command, select, confirm (Return); or drag first" and "Ins: overtype.  Right click: menu.  Any key closes".
- **Cost:** WRITE.RUN is 9,526 bytes (8,679 before; the core is unchanged). ROM 1 has 512 bytes left (1,536 before).
- **Tests:**
  - `t_write_mouse` in test_apps (23 checks): WRITE.RUN's header asks for API 8; a drag over a word (a selection of its own, the band); CODE-E erases it; a drag, CODE-M, a click, Return moves it; Backspace erases one; a character after a drag is typed, nothing erased; a click ends one; a drag back to where it began makes none; CODE-E first, then a drag, Return; the cursor keys extend one, Return beeps, ESC ends it (still in Write); CODE-B empties one, then CODE-E beeps and it stays a drag's; Delete erases one; CODE-D, a drag to point, Return duplicates it; no menu while making a selection for a command; a right click: the menu with its items, the cursor there, Find's form from it; a drag kept for the menu's Erase, and its Move by its letter; no menu while pointing, on the status line; ESC; after Find, a right click is editing; Jump from the menu ends a drag's selection; a drag held below the text area scrolls the view, the cursor on its last row (a 60-line file), and one held above it scrolls back.
  - `t_write` in test_mt (1 check more): in Write's window, moved, a drag selects (0 to 6), a right click gives its menu, Erase erases; a right click with none puts the cursor where it was in the window's text area.
  - `t_calc` in test_apps: SYSTEM.RUN and UITEST.RUN still declare API 4, WRITE.RUN 8.
  - The checks fail on each of: no drag (the button's state not followed), no anchor where the button went down, no command cleared for a drag's own selection, a click not ending one, a drag back to its start leaving an empty one, no scroll below the text area, no keys of its own for a drag's selection, Backspace not erasing it, the selection not kept for a right click, a menu while pointing, a menu outside the text area, the menu's Erase not on the selection, Jump from the menu not ending it, a right click not ending Found, the cursor not moved to a right click, an emptied selection taking the command, Delete not erasing one, Return not beeping (it ended one), ESC leaving Write. Untested: a drag left of a window's text area while it is scrolled sideways (the whole screen has no room left of its text; with no sideways scroll, a column to the left is column 0 either way).

## Write's Cut, Copy and Paste (the clipboard, 2026-10-23)
The last of the four steps toward right-click editing in Write: Cut, Copy and Paste through the clipboard every `.RUN` shares (`UI_CLIP`).
- **Keys:**
  - With a drag's selection up, **CODE-Z** cuts it (into the clipboard, out of the text) and **CODE-C** copies it (still selected). Without one, both beep. A selection of more than 16 KB is refused: "The clipboard holds 16 KB at most", and the clipboard keeps what it held.
  - **CODE-V** pastes what the clipboard holds at the cursor, or over a drag's selection, which goes first. The cursor ends after it, and lines and the status line count it. An empty clipboard: a beep. No room in the text for it: "Out of memory", and nothing changes.
  - The bytes go as Write holds them, lines ending in LF. Another `.RUN`, or Write again after it has ended (the core keeps the clipboard), pastes them; with `MULTITASK=1` so does another Write's window.
- **The right click's menu** takes what applies: Cut and Copy with a drag's selection, Paste with something to paste, then Erase, Move, Duplicate, Find..., Substitute... and Jump.... Left out, not greyed.
- **The band** for a drag's selection says "CODE-Z cuts   CODE-C copies   Right click: menu   ESC cancels" on its second line. **Help** has the three, in their places: 18 lines, all the help window shows.
- **Room, with `MULTITASK=1`:** two Writes and the calculator still fit in the UI segment together. That took two changes, as Write grew 685 bytes:
  - **Write's file I/O buffer** (1 KB) is in its shadow's block now (`IOOFF`, outside the UI segment), not its BSS; the row, the status line and a message that shared it have their own 336 bytes.
  - **MT reads a window `.RUN`'s fixups into its stack's room** (`mw_load`): past its BSS, unused until it runs, not on top of the BSS. A slot was its image, the larger of its BSS and its fixups, and its stack; now it is its image, its BSS and the larger of its stack (2,560 bytes) and its fixups. Write's slot is 12,080 bytes; the old reckoning would have made it 12,768 (the 9,526-byte Write's was 12,128). LODEMT.SYS grows by 22 bytes.
- **Cost:** WRITE.RUN is 10,211 bytes (9,526 before). ROM 1 is full: no sector left (512 bytes before). LODEMT.SYS 17,506 bytes (17,484).
- **Tests:**
  - `t_write_clip` in test_apps (11 checks): with the clipboard empty and nothing selected, no Cut, Copy or Paste in the menu, and CODE-C, CODE-Z, CODE-V do nothing (the text not even marked changed); a drag from right to left (the selection past the cursor), CODE-C: in the clipboard (CLIP.$$$ here, no EMS), still selected; CODE-V after a click; CODE-Z; CODE-V over a drag's selection; the menu's Paste with nothing selected, and Cut, Copy and Paste with a selection (Cut chosen); the menu's Copy (still selected) and its Paste over a selection; a whole line copied and pasted at the end (a line more); saved, quit, and Write again pastes it; 19,500 bytes refused by Copy and by Cut (the clipboard keeps the 3 it held, nothing erased), then 194 copied; text typed at the start, then copied from right to left (after the gap); an emptied selection copied: a beep, the clipboard as it was; a paste of 5 bytes over the 2 at the start (the room counted from the gap, not from where the selection ends). The band's second line and the help's 18 lines (in `t_write`) are checked too.
  - `t_write` in test_mt: what the first Write's window copied, CODE-V in a second Write's, saved in its file; two Writes and the calculator side by side as before.
  - The checks fail on each of: Cut not erasing, a refused Cut erasing all the same, the menu's Copy cutting, the room for a paste over a selection reckoned from its end, an empty selection copied (the clipboard emptied), error 8 not said as such, Paste not over the selection, its lines not counted, Cut and Copy in the menu with nothing selected, Paste in it with nothing to paste, an empty clipboard pasted (the text marked changed), MT applying the fixups from where they no longer are (`kmwsi`: every window .RUN broken) or the slot sized by the fixups alone (`kmwslot`: TASKS.RUN then fits beside two Writes and the calculator), and the file written from the wrong segment. Reading the copy of a selection past the cursor from before the gap makes no difference: the gap only gets there by moving back over that text, which leaves an exact copy of it, and any edit ends the selection first.
  - Untested: Paste with no room in the text (a 64 KB buffer).

## Shorter help (2026-10-23)
The help windows say less, and System's About no longer calls Lodestone a working name.
- **System:** 6 lines, not 13. The six "Return on <topic>" lines and the three "Space on <topic>" lines are one each ("Return: what the band says", "Space: on or off (see the band)"): each topic's band already says what Return and Space do there. About: "for the GRiDCase 1520".
- **The Executive:** the file commands shorter: "Copy (a file or subject)", "Delete (a file or subject)", "Move (a file)", "Rename (a file)"; "CODE-W: Write (a new file)"; "F5: read the disk again"; "Command prompt" capitalised as the rest.
- **Write:** still 18 lines, the descriptions shorter ("Find text", "Replace text", "Go to a line", "Save and exit", ...).
- **Cost:** none. The UI core is the same size (`ui_keep_end` 6526h, MEMSZ as before); SYSTEM.RUN 12,393 bytes (12,821), WRITE.RUN 10,162 (10,211). ROM 1 has a sector free again (512 bytes).
- **Tests:** the Executive's and Write's help checks in test_apps read the new lines (and not the old: no "the file"), test_splash's System help its Space line; the memory figures are unchanged.

## Close boxes for programs that need ESC (UI API 9, 2026-10-27)
With `MULTITASK=1`, a `.RUN` that asks for API 9 gets `EV_CLOSE` (0FF05h) from `UI_EVENT` for a click on its window's close box, not K_ESC, so that ESC can mean something else to it. The terminal window (TERM.RUN) is the one: its ESC goes to the program in it, and its close box asks, then ends that program. KMW's `mw_got` gives it (the UI core only says API 9 now); with the switch off the close box gives ESC, even to an API 9 `.RUN`. Older `.RUN`s get ESC as before. Design and tests: `lodestone-multitasking.md`, M9c.

## The info line: free memory (2026-11-03)
The Executive's bottom line now reads, for example, `80286 80287XL  581K + 1120K EMS free  Plasma 640x400  Mouse COM2  BIOS 10/25/89`.
- **Free, not installed.** The first figure is the conventional memory a DOS program started now would get. It is the same figure as System's "Free for programs", and agrees with MEMSZ.COM.
  - `conv_free` asks the kernel for its largest free block (INT 21h 48h with BX = FFFFh, which merges free runs as it scans).
  - It also takes the run right after the UI block, plus what `ui_lend` gives a program (the directory buffer, down to `UI_KEEP_PARAS`), and uses that when it is larger. No lend is added while a `.RUN` is loaded.
  - The second figure is the EMS manager's free pages (INT 67h 42h), shown as `K EMS free`. INT 67h is called only after `ems_mgr` finds `EMMXXXX0`; `ems_mgr` is now `src/EMM.INC`, shared with System.
  - Without an EMS manager the line is `565K free`, plus `+ nnnK ext` when the BIOS reports extended memory. Nothing in Lodestone uses that memory, so all of it is free.
  - It is read each time the line is drawn, so it shows what is free after a program ends or a TSR stays.
- **The panel is read from the hardware.** The line reads port 7F8h. The 1520's BIOS answers INT 15h E420h (TechRef 3-20, "Select or Get Current Display") by reading that same port (`GridDisplay20` in gridcase-bios):
  - bit 3 set means the internal panel, and bits 0-2 give its kind: 5 is plasma 640x400 (`Plasma 640x400`), 7 is LCD 640x400 (`LCD 640x400`);
  - bit 3 clear means the external RGB port (`External`);
  - anything else shows `Panel`. A 640x200 panel can't show Lodestone (mode 40h).
  - pcemu's `vid_status` (default FDh) sets what the port reads.
- **Width.** The gaps are 2 spaces, not 3. The longest line, with 4-digit EMS and a 287XL, is 79 characters.
- **Cost.** The UI block grows by 160 bytes (10 paragraphs: `UI_KEEP_PARAS` 643h to 64Dh), so DOS programs get 0.2 / 0.1 KB less (MEMSZ 565.5 / 581.6 KB). The added code sits after `draw_all`, and both of its shifts (30 and 138 bytes) are even, so the hot labels keep their parity. `sysinfo` no longer reads INT 12h or E440h.
- **Tests (test_apps):**
  - t_system: the line's free figure is MEMSZ's, with no EMS on the line without an EMS manager;
  - t_memory: with EMS, conventional free is MEMSZ's, EMS free is System's, and the line is at most 80 characters;
  - t_calc: ports FFh, F5h and FEh show `LCD 640x400`, `External` and `Panel`, on the line and in System's Devices, and 384 KB of extended memory (pcemu's `ext_kb`) shows as `+ 384K ext`;
  - t_memory: after a 16 KB TSR (TSR.ASM with -DKEEP=400h) the line drops from 565K to 524K, as System's 524.3 KB does. The UI block moves past the TSR and leaves a hole, so the largest run loses more than 16 KB.
  - t_calc_move: a window dragged without a save-under leaves the line as it was. The Executive redraws under a loaded .RUN, so conv_free shows its last figure from a draw with no .RUN loaded. Before this fix the line dropped to 553K and stayed that way after the window closed.
  - The checks fail with the lend correction dropped (558K against MEMSZ's 565.5) or the EMS figure halved.

## The Executive's right-click menu (2026-11-04)
A right click in the Executive's list selects the row under it, then opens a menu (`UI_MENU`, at the click) of what applies to that row. Each item is one of the Executive's keys, run as if typed (`ui_dispatch` on `ex_keys`). The menu is there with multitasking on and off. The modes a program lists for itself, CLAUDE.COM's Web browser among them, are in the next section.

- **What it offers:**

  | Right click on | Items |
  |---|---|
  | A file (Title outlined) | Open (Return), Copy (CODE-C), Move (CODE-M), Rename (CODE-R), Delete (CODE-D) |
  | A DOS program, with `MULTITASK=1` | the same, with Open full screen (Shift-Return) after Open |
  | A subject (Subject outlined) | Copy, Delete |
  | No row, or a drive (Device outlined) | Write, Claude, Calculator, Command prompt, Tasks (with `MULTITASK=1`), System, Read the disk again (F5) |
  | The form, or the band | nothing |

  - Each item shows its key, as Write's menu does: "Rename", a tab to column 21, "CODE-R".
  - Open full screen runs the program in the Executive's own task (`run_wait`), as Shift-Return does. Under multitasking, Shift held as Open is chosen on a DOS program does the same, because Open is Return (KMW's `mw_prog` looks at Shift; untested).
  - A right click on an item of the menu chooses it, as a left one does.
  - A right click while a message waits in the band clears it and opens the menu at once; a left click only clears it, as before.
  - The help window says "Right click   a menu of what applies" (16 lines now, of the 18 it has room for).
- **How:**
  - `ex_menu` (EXEC.INC) works out what applies as RMENU.INC's need bits. `RX_ROW` is a row of Title or Subject, `RX_FILE` a file, `RX_PROG` a DOS program and `RX_NONE` no row. `RX_MT`, multitasking on, is bit 0, RMENU's `RM_SEL`, which the Executive has no use for, so `or dl, [ex_mtw]` sets it. RMENU's `RM_CLIP` (bit 1) is left alone.
  - RMENU.INC, Write's and TERM's menu builder, is shared as it was. It moved from `os/apps` to `os/src`, where both the apps' and the kernel's builds find it. `rm_buf` and `rm_key` hold all 13 items (`rmenu` has no bound; asserted against `ex_items`).
  - The items are `ex_items`: a text, a key and what it needs. `K_XFULL` (FE00h, no key's code) stands for Open full screen.
  - **The key chosen is put in the BIOS's keyboard buffer** (INT 16h AH=05h, as the End key above is pushed; on the 1520, GRiD's `KbPlaceChar`), and `ex_loop` reads it as if typed. So under multitasking KMW sees it first, as a typed key: CODE-K and CODE-T bring an open calculator or Tasks to the front instead of starting a second.
  - A right click on a subject that can't be opened (its CHDIR fails: its message in the band) gives no menu.
- **Who gets a right click** (`mouse_event`, UICORE.INC):
  - Before, only a `.RUN` for API 7.
  - Now also the Executive's own wait. Bit 0 of `ex_rclk` is set while `ex_loop` waits in `UI_EVENT` and while its menu is up, and clear everywhere else: the Executive's forms, its help, a `.RUN` it runs.
  - With multitasking on, KMW's `mw_poll`, the look `UI_EVENT` makes, sets bit 1 around it, and the core then makes the event for everyone, so that KMW can route it. `mw_got` passes it on only to whom it was for: the Executive's wait (bit 0), or a `.RUN` for API 7 (`mw_rcno`). An older `.RUN` (the calculator, Tasks, System) still never sees one. `UI_POLL`, which `mw_got` never sees, has no bit 1, so the core's old rule holds there.
  - `mw_got` routes a right click as a left one. On another window, or on the Executive, it brings that one to the front and is taken, with no menu. On the one in front it is that one's. So two right clicks open the Executive's menu from a window in front.
  - `ex_rclk` is kept per window session, as `ex_mtw` is (KMW's `mw_ctx`, now 2 bytes there, and its length assert counts both). A new session starts with it 0.
- **Cost** (multitasking off):
  - The UI block grows by 580 bytes (`ui_keep_end` 64D0h to 6714h), so DOS programs get 0.6 / 0.5 KB less: MEMSZ 564.9 KB without EMS, 581.0 KB with it. That is the resident cost of a menu with multitasking off.
  - With multitasking on, MEMSZ is 556.8 KB (557.5 before).
  - LODE.SYS is 50,176 bytes, exactly 98 sectors (49,648 before). ROM 1 has 1,024 bytes (2 sectors) left (1,536 before).
  - LODEMT.SYS is 21,736 bytes (21,679 before), still 43 sectors.
  - Three new parity pads keep the hot code where it was: after `mouse_event` (UICORE.INC), after RMENU.INC's include (`focus_key` odd, LODE.ASM's list), and before `mw_got` (`mt_par`). `mw_poll`'s pad stays.
- **Tests:**
  - test_apps `t_exmenu` (multitasking off):
    - A right click on NOTE.TXT selects it. The menu is its 5 items in order (Open, Copy, Move, Rename, Delete; 88 pixels high), with no Open full screen and no programs. ESC leaves the screen as it was.
    - From the menu, R, Return gives Rename's form, and Copy and Move give theirs.
    - MEMSZ.COM's menu has the same 5, and Open runs it ("MEMSZ.COM ended").
    - A right click under the last row clears the message and gives the 6 programs in order, with no Tasks. Down, Down, Return opens the calculator, and so does a right click on its item.
    - The form and the band give no menu. A drive gives the programs.
    - The subject SUB gives Copy and Delete, and Copy's form is for SUB.
    - The help window has the line. Delete from the menu asks, and Return deletes.
  - test_apps `t_rclick`: its two checks that the Executive saw no right click now see EV_RCLICK, then the left click that closes the menu.
  - test_mt `t_exmenu` (14 checks, multitasking on):
    - LCMD.COM's menu is 6 items with Open full screen. That runs LCMD in task 0, full screen, with no task for it, and EXIT comes back ("LCMD.COM ended").
    - LODE.INI's menu (not a program) has no Open full screen.
    - No row gives 7 programs with Tasks. Open on LCMD.COM is a task in a terminal window, as Return.
    - With the calculator up and the Executive in front, a right click on the calculator's title brings it to the front with no menu. A right click inside it is not given it (the events past `mw_got`, at `ui_event.got`+5).
    - A right click on the Executive's list brings it to the front with no menu, and the next one opens it.
    - The menu's Calculator with one open brings that one to the front, with no second.
    - With no windows: RC6.RUN (API 6) and RCP6.RUN (API 6, reading with `UI_POLL`; new) get no right click; RCTEST.RUN (API 7) does. The left click after it reaches each, so the check reads each one's own events (RCP6's are at other offsets than RCTEST's).
    - Then, with RCTEST's API 7 still in `run_hdr`, a right click in the Executive's Rename form is not given.
- **Untested:**
  - a right click on a window of a `.RUN` for API 7 while another is in front (only the calculator, an older one, is tested);
  - Open full screen on an `.EXE` (only `.COM`s), and Shift held as Open is chosen;
  - a subject that can't be opened (its CHDIR failing under the menu);
  - the choices of a menu longer than the screen (13 items at most, 7 at once).
  - `mw_rcno` at `.own` (the filter ahead of `mw_topses`): reaching it needs an Executive wait that isn't its list's, with a session window open on top. The Executive's forms, help and messages are windows on top, so this is defensive; the Rename-form check runs with no windows (`.win0`).
  - KMW's `mw_say` (an older path: a message from the Executive's wait, as when a window doesn't fit) leaves bit 0 of `ex_rclk` on, so `ui_msg`'s wait can see a right click. It ends on any event and the result is thrown away, so this is harmless.
- **Fixes:**
  - **`UI_POLL` gave an API 6 `.RUN` right clicks under multitasking.** The core made the event for everyone whenever multitasking was on, and only `mw_got` filtered it, but `UI_POLL` doesn't go through `mw_got`. Now only `mw_poll`'s look makes it for everyone (bit 1). Reproduced with RCP6.RUN, now a test.
  - **The menu's Calculator and Tasks started a second window** under multitasking, where CODE-K and CODE-T typed bring the open one to the front. The key went straight to `ui_dispatch`, past KMW. Now it is put in the BIOS's buffer and read as typed.
  - **A filter bypass:** with the Executive in front and a window on top, `mw_topses` returned events before the filter. The filter is now first (`mw_rcno`, at `.own` and with no windows).
  - **Smaller fixes:** `mw_ctx`'s length assert counted 1 byte for the `ex_mtw` range, which is 2 now; a subject whose CHDIR fails gave a menu for the subject before it; and `rm_buf` was sized for the 7 that apply at once now, with no check.
  - **Checks added:** the items' order; Copy and Move chosen; a file that isn't a program under multitasking; a right click in a form under multitasking.
  - **Bytes:** `RX_MT` as `ex_mtw`'s own bit and one word add for `ex_mtw` and `ex_rclk` in `ex_loop` saved 10 bytes, which the fixes used.
  - **The RCP6 check** read its events at RCTEST's offsets, so it could never fail (`mw_poll` leaving bit 1 set got through). It now reads RCP6's own, and has a left click that must arrive.

## A program's modes on the right-click menu (2026-11-04)
A program can name its own modes, which the Executive's right-click menu then offers after Open (and Open full screen). CLAUDE.COM 1.17 names five: Claude Code (`/T`), Web browser (`/W`), Chat (`/C`), Load resident (`/R`) and Unload resident (`/U`). With multitasking on, Web browser starts `CLAUDE /W` as a task in a terminal window: gridfox, sized to the window.
- **The mode block** is in the program file, so a program names its own modes and nothing needs listing in LODE.INI:
  - A `.COM` that has one starts with a jump (`EB xx` or `E9 xx xx`), then `'LMOD'`, then up to six entries, then a 0.
  - Each entry is `db flags, 'Label', 0, 'arguments', 0`. The label is shown as the Executive's own are: CLAUDE's are the text, HT, 21, the switch, so the switch shows in the key column. It is only a label there: no key types it. An HT must be followed by its column byte (one last in a label would take the label's 0 for it and show the arguments too; nothing is written out of bounds).
  - Flags: `LM_MODE` (80h) is always set, so an entry never starts with 0. `LM_TASK0` (1): run in the Executive's own task, full screen, as Shift-Return. `LM_PAUSE` (2), with `LM_TASK0`: wait for a key after the program, so the line it prints can be read ("Press any key").
  - CLAUDE's Load and Unload resident have both: `/R` is refused in a task, and `/U` fails with any task running.
  - The Executive reads only the first 127 bytes. An entry whose arguments' 0 isn't among them is left out, with the rest after it. CLAUDE asserts that its block fits.
- **How** (EXEC.INC):
  - `ex_modes` runs on a right click on a DOS program. It reads the file's first 127 bytes into `msgbuf` and fills the mode slots, six entries of `ex_items` after Open full screen. An unused slot needs `RX_OFF`, a bit nothing sets, so it never shows. Its text is `s_empty`, since a 0 text ends RMENU's list.
  - `msgbuf` is free while the menu is up: there is no menu while a message shows, and no task's message comes while the Executive isn't in its own wait.
  - A slot's key is `K_MODE` + n (FDxxh, no key's code). `ex_menu` finds the label from the slot, the flags in the byte before it and the arguments after it.
  - `run_progt` is `run_prog` with the arguments in DI, ASCIIZ; `run_wait` takes them in DI too. With multitasking on, the CMP that KMW patches is now `run_progt`'s, and `mw_prog` makes the task's tail: `mk_tail`, factored out of `exec_raw`, then `MT_SPAWN`'s `SP_TAIL` (which the multitasker already copied into the task, but mt_ui never set). Shift still runs it full screen, with its arguments.
  - Without `LM_TASK0` a mode runs as Open does: with multitasking on, a task; Shift, full screen.
  - `run_pause` asks `UI_RUN` to wait for a key after the program, before the screen goes back to the Executive's. It is cleared as it is read, whether EXEC worked or not (if it failed, "Press any key" shows on a blank screen before the "Can't run" message). A pad byte after it in the UI's BSS keeps the words after it, MOUSE33's among them, at their parity.
- **Cost:**
  - `ui_keep_end` 6714h to 6806h (+242 bytes): MEMSZ 564.7 KB without EMS, 580.7 KB with it (564.9 / 581.0 before); 556.6 KB with multitasking on (556.8).
  - LODE.SYS 50,416 bytes, 99 sectors (98 before). ROM 1 has 512 bytes left, so every file stays on ROM 1.
  - LODEMT.SYS 21,760 bytes (+24), still 43 sectors. CLAUDE.COM 26,218 bytes (+112); ROM 2 has 79,872 bytes left (80,384 before).
- **Tests:**
  - test_apps `t_modes` (10 checks, multitasking off), with MODET.COM (tests/MODET.ASM: a block of three modes; it writes its tail to TAIL.TXT):
    - The menu of MODET.COM is Open, its three modes (Plain, Pause, Full), then the file's. After it, MEMSZ.COM (no jump at 100h) and NOTE.TXT show none of them.
    - MODEL.COM, whose third entry's arguments end with their 0 at byte 127, shows two. MODEE.COM, with it at byte 126 (the last read), shows three.
    - MODEX.COM (a jump, then `LMOX`) shows none; MODE7.COM (seven) shows the first six.
    - CLAUDE.COM shows its five, each with its switch in the key column.
    - Each mode runs with its arguments (" /A B", " /P", " /F"); Pause waits with "Press any key" in text mode; Open has no tail; a Full after Pause doesn't wait, and `run_pause` is 0 again.
  - test_mt `t_modes` (9 checks, multitasking on):
    - The menu with Open full screen. Plain is a task with its tail; Open after it a task with none; Plain with Shift full screen in the Executive's task (its own `exec_raw`) with the tail.
    - Pause and Full run in the Executive's task; Pause waits for a key. Open full screen then has no tail (`msgbuf` holds the block). Return afterwards: a task with no tail.
    - CLAUDE.COM's Web browser: CLAUDE a task, the Executive in front, its PSP's tail " /W".
- **Untested:** an `.EXE` (its `MZ` isn't a jump, so no block is found); a read error on the file (no modes then); the Pi's side of the Web browser from the menu (no Pi in test_mt).

## Fixes and tests
- **Fixes:** 14 issues in the new code; all are fixed and the confirmed ones have tests:
  - **The TSR case:** the empty list and .RUNs that wouldn't load. Fixed with `ui_room` and the move.
  - **Backward Substitute** re-matching its own replacement text.
  - **Write's cursor** drawn on the wrong row after a full redraw.
  - **Ins** leaving the old cursor shape behind.
  - **Register-contract slips:** `UI_SBU16`'s AX, `UI_EVENT` / `UI_EDIT` / `UI_LVCLICK` registers.
  - **Window and saver details:** the redraw routine not cleared before a `.RUN`, a form outline left behind after the saver, System's band after the saver, a fifth window unbalancing closes, and a message's Return swallowed after the saver.
  - **Smaller ones:** keypad arrows with NumLock, `UI_RUN` with a `.RUN` path, date numbers over 255, and saving to `X.$$$`.
- **More fixes (2026-10-06):** about 40 findings, almost all confirmed as bugs in the emulator. Fixed, with tests for the serious ones:
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
  - The fixes cost 434 bytes: LODE.SYS is 30,048 bytes, and a DOS program gets 571.7 KB.
  - **Left for later (kernel, outside this change):**
    - `same_disk` compares only the BPB, so two freshly formatted disks with the same label and serial number are taken for one;
    - `f_3B` cuts the current-directory string at 66 characters;
    - a failed mount returns an error without INT 24h.
  - **Not changed:** System takes the 80287 from INT 11h (SETUP's CMOS bit) rather than probing it, and Write's "Write to a file" overwrites without asking.
- **`tests/test_apps.py` — 122 checks** (160 with 0.3.1's `t_mouse`, 186 with 0.3.2's `t_form`, 237 with 0.3.3's `t_files` and `t_file_safety`, 251 with 0.3.4's `t_saver_delay`, 282 with 0.3.5's `t_wild`, 292 with 0.3.6's `t_subdel`, below)**:**
  - **UITEST.RUN** exercises the API: lists, forms, ask, help, errors, BSS zeroing, exit code, cleanup to the paragraph, and a file that isn't a `.RUN`.
  - **System:** every topic, setting the clock, a bad date, the GPIB scan.
  - **CODE-?, CODE-Return, CODE-ESC** in the Executive, a form, System and Write, as the 1520's BIOS delivers them (below).
  - **Write:** every command; the saved bytes; Cancel; a new file; a 41 KB file round trip; a write-protected disk; Include; a mouse click; backward Substitute.
  - **Memory:** MEMSZ before and after; a TSR after the UI block; the screen saver inside Write.
  - **The fixes' cases:**
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
  - `src/LODE.ASM` (the sections, `ui_load`, `run_ui`);
  - `src/KCORE.INC` (F0h 2–4), `src/KPROC.INC` (the root restart).
- **Programs:**
  - `apps/SYSTEM.ASM`, `apps/WRITE.ASM` → `.RUN` via `mkrun.py`;
  - `build.sh` builds them.
- **Tests:** `tests/test_apps.py`, `tests/UITEST.ASM`, `tests/MEMSZ.ASM`, `tests/TSR.ASM`.
- **The shell:** LCMD's version strings say 0.3.

## For the 1520
- **Copy to the floppy:** `LODE.SYS` (30,292 bytes, with the CODE-? fix, GRiD's font, the fixes above and the font switch), `LCMD.COM`, `SYSTEM.RUN`, `WRITE.RUN`, `LODE.TXT`, `DEFRAG.COM` and `TERMBOLD.FNT`. All are in `releases/0.3`. Copy each on its own and read it back, as usual.
- **Check:**
  - CODE-U (System), each topic, and setting the clock;
  - CODE-W (Write): type, Quit, name it;
  - open LODE.TXT from the list, scroll, try Find, then ESC (Cancel);
  - run TM5000G and come back;
  - leave the machine for 5 minutes inside Write;
  - in System's GPIB topic, scan the real bus.
- **Unknown on the real machine:**
  - how fast Write's full redraws really are.

## Next
- **Programs:**
  - Term, with profiles (the Claude Code terminal: 0.4.0, in CLAUDE.COM);
  - Command, on the text view;
  - the GPIB console;
  - CLAUDE as a `.RUN`.
- **Executive work (0.3 proper):** Subjects, file operations (Copy on a subject: 0.3.13), R: (M:: 0.3.14), settings.
- **Later:** the EMS swap of the UI block while DOS programs run, which would give programs about 17 KB more.
