# Grid-OS floppy development loop (Grid-OS 0.3 on the floppy, 2026-10-06)

Decision: develop from a boot floppy until the OS is stable, then build the ROM version (see `gridos-kernel-hardware-spec.md` for the EPROM format). The plan is in `gridos-roadmap.md`; the kernel is described in `gridos-0.2-kernel.md`, DEFRAG and the screen saver in `gridos-defrag.md`, the UI core and the programs in `gridos-0.3-apps.md`.

## Pieces (source in `grid-OS\gridos\src` and `gridos\apps`, build with `gridos\build.sh` or `BUILD.BAT`)
- **BOOT.ASM** — the 512-byte floppy boot sector, with 37 bytes spare.
  - Works with any standard FAT12 BPB.
  - Finds `\GRIDOS.SYS` in the root directory and follows its FAT chain, so the file can be fragmented or replaced at will.
  - No size limit; it loads 0.3's 30 KB unchanged.
  - Reads whole runs of sectors per INT 13h call, split only at track ends and 64 KB DMA boundaries.
  - Loads the kernel to **1000:0000** and jumps there with DL = boot drive and DS:SI = 0:7C00 (BPB).
  - On error it prints a message, waits for a key and issues INT 19h.
- **GOSBOOT.COM** — runs under GRiD MS-DOS on the Grid.
  - Reads sector 0 and checks it is a 720 KB / 1.44 MB FAT12 floppy.
  - Keeps the disk's own BPB (bytes 0Bh–3Dh), drops in the Grid-OS boot code, writes it back and verifies it.
  - Asks Y/N first, writes sector 0 only, and leaves files untouched. `GOSBOOT B` targets drive B:.
- **GRIDOS.SYS 0.3** — the kernel (with 0.2.2's disk cache and 0.2.3's one-sector-at-a-time retry) plus the UI segment (UI core, Executive, GRiD's TC8X16 font, screen saver): **30,292 bytes** with the font switch. See `gridos-0.3-apps.md`.
  - Earlier builds are kept in `gridos\releases\`:
    - `0.3` — GRIDOS.SYS, GRIDCMD.COM, GRIDOS.TXT, SYSTEM.RUN, WRITE.RUN, DEFRAG.COM (GRiD's font), TERMINUS.FNT;
    - `0.2.3` — GRIDOS.SYS 24,518, DEFRAG.COM, GRIDOS.TXT, HEADCLN.COM (**the rollback for 0.3**);
    - `0.2.2`, `0.2.1`, `0.2`, and `0.1` (the 6,496-byte "hello" kernel, with its source).
  - The Executive look and the serial mouse carry over from 0.1:
    - mode 40h; the font is GRiD's own TC8X16 (InteGRiD's system font) since 2026-10-06, Terminus Bold 16 before. Since the font switch, other 8×16 fonts are `.FNT` files (System → Display, saved as `FONT=` in `A:\GRIDOS.INI`);
    - the date/title/time bar, list, form, system line and prompt band;
    - Microsoft mouse on COM2/COM1, XOR arrow.
- **SYSTEM.RUN** (CODE-U) and **WRITE.RUN** (CODE-W, and opening text files from the list) — the first programs on the UI core. `mkrun.py` (needs Python) builds them from `apps\*.ASM`.
- **TERMINUS.FNT** (1,536 bytes) — the font 0.3 started with, as a file for System's Display topic. Built from `fonts\TERMINUS.ASM`; `typfont.py X.TYP --fnt X.FNT` makes one from any 8×16 GRiD .TYP font.
- **DEFRAG.COM** — the disk tidier, and the screen saver's first act. It keeps going on worn disks (marks bad clusters, logs to DEFRAG.TXT), and `DEFRAG /T` tests the free space. See `gridos-defrag.md`.
- **HEADCLN.COM** — floppy head cleaning with a wet cleaning disk (0.2.3).
- **GRIDCMD.COM** — the command prompt (CODE-P) and CLAUDE's `COMSPEC /C`.
  - Deliberately **not** named COMMAND.COM; see the rule below.
- **Emulator and tests:**
  - **pcemu.py** — a BIOS-only PC that boots the real floppy image (built by `mkimg.py` with mtools + BOOT.BIN). It has an optional real-drive timing model and can simulate unreadable sectors. Its INT 16h behaves like the 1520's BIOS for CODE + punctuation/Return/ESC.
  - **ktest.py** — drives the Executive and reads its screen back (it knows both fonts); symbols are looked up in the kernel or the UI segment. `run_answering` presses Enter when a program says "Press any key".
  - **tests\\:**
    - `test_kernel.py` (60 checks);
    - `test_apps.py` (111 checks: the UI core through UITEST.RUN, System, Write, the Executive, memory with MEMSZ.COM and TSR.COM, the saver inside a program, and the review panel's cases);
    - `test_defrag.py` (33 checks), with `defrag_util.py` and `defrag_cut.py` (a power cut at every DEFRAG write; `worn` mode on a simulated worn drive);
    - `test_headcln.py` (9 checks);
    - `test_claude_kernel.py` (21 Claude scenarios on the kernel);
    - `ggtest_kernel.py`, `fatcheck.py`, TESTDOS, CACHETST, UPPER.
  - **bench\\:**
    - BENCH.COM and `run_bench.py`, which compares Grid-OS with GRiD MS-DOS 3.30 booted from the EPROM image in pcemu;
    - DISKMAP.COM (dumps the floppy's system area);
    - `trace.py`, `prof.py`, `gapprof.py`;
    - the results in `RESULTS.TXT`, the 1520 logs `BENCH_1520_2026-10-05*.TXT` and `DEFRAG_1520_2026-10-05_reformatted.TXT`, and `DISKMAP_1520_2026-10-05*.BIN`.
  - Screenshots in `gridos\screens\0.2`, `screens\0.2.2` and `screens\0.3`.
  - `gosim.py` and the `test_*.py` in the `gridos` folder are the 0.1 harness; `test_toggles.py` is retired and can be deleted.

## Rule: what must not be on this floppy
- GRiD MS-DOS booted from the EPROM (no F) with this floppy in the drive takes `\COMMAND.COM` and `\CONFIG.SYS` from A: in place of its own. The strings `\CONFIG.SYS` and `\COMMAND.COM` sit in its IO.SYS, opened on the default drive, and AUTOEXEC.BAT follows from the shell.
- **Keep COMMAND.COM, CONFIG.SYS and AUTOEXEC.BAT off A:** unless they are meant for GRiD MS-DOS.
- Learned 2026-10-05: with Grid-OS's shell as A:\COMMAND.COM, GRiD MS-DOS ran it as its primary shell, and EXIT then stopped DOS with "Bad or missing Command Interpreter". The shell was renamed GRIDCMD.COM, and it now also honours `/P`.

## Loop
1. Once per floppy: format it (FAT, 1.44 MB) and copy the files.
   - Boot the Grid normally (EPROM → GRiD MS-DOS), where the floppy is **B:**.
   - Run `B:GOSBOOT B` and answer Y.
   - Formatting replaces the boot sector, so GOSBOOT has to run again after every format.
2. Boot Grid-OS: restart and **tap F as the memory count finishes**. The BIOS (GridWaitKey) takes a buffered keypress and boots the floppy instead of the EPROM.
3. Iterate: Claude rebuilds GRIDOS.SYS (and the shell, the `.RUN`s, DEFRAG.COM) and copies it straight onto A:. The floppy drive is a connected folder, reachable only while the disk is in the PC. No need to rerun GOSBOOT.
   - **Copy each file to A: on its own** (not in a batch with other files), **from a staging path not used before**, **then read it back and compare**. On 2026-10-06 a copy from a reused staging path (`outputs/floppy/GRIDOS.SYS`) wrote the file staged there at noon (30,048 bytes) instead of the new one; the read-back caught it. A copy has reported success while the floppy kept the old file three times now (most recently DEFRAG.COM on 2026-10-05). A second, solo copy fixed it each time.
   - Claude's bridge to the PC can write and read files but currently can't delete or rename them, because the device shell is blocked by a Windows update (still the case 2026-10-06). Deletions have to be done by Joshua.
   - **Results come back on the floppy:** BENCH and CACHETST add each run to `BENCH.TXT` / `CACHETST.TXT` on the disk they ran from, and DEFRAG to `DEFRAG.TXT`. Each run is headed with the date (and, for BENCH, the system). Claude reads these files once the disk is back in the PC.
   - **Each copy through the bridge leaves 4 dead root entries.** The bridge writes a hidden long-name temp file (`.NAME.EXT.pid.random.tmp`), then renames it. Windows never reuses the dead slots; it appends.
     - Once the root passes 63 entries, directory searches cost a whole-root read.
     - **DEFRAG removes them** (on its own after 5 minutes idle in the Executive). No more format-and-refill needed for that.
   - **Each kernel copy can also leave a hole** where the old GRIDOS.SYS was. The next big file (BENCH.DAT) fills it and is split, so BENCH reads look 0.3–0.8 s slower. DEFRAG puts files back in one piece. Compare BENCH read times only between runs on the same layout.
4. Back to DOS: a plain restart (CTRL-ALT-DEL) without F. Under GRiD MS-DOS booted from the EPROM, A: is the EPROM and the floppy is B:.

## What's on the floppy (A:) — reformatted 2026-10-05 evening; 0.3 copied 2026-10-06, updated at noon, in the afternoon (fonts), at 14:48 (0.3.1, TM5000G) at 15:19 (0.3.2) and at 16:07 (0.3.2 with the File form), 18:04 (0.3.3), 18:48 (0.3.4) 21:36 and 22:10 (0.3.5)
| File | Size | What |
|---|---|---|
| GRIDOS.SYS | 36,636 | **Grid-OS 0.3.5** kernel + UI core + Executive + disk cache + screen saver, in GRiD's font, with the CODE-? fix, the review panel's fixes, switchable fonts, the INT 33h mouse for DOS programs the File form (Device, Subject, Title; Tab) the file commands (Copy, Move, Rename, Delete) the screen saver's delay and wildcards (COMSPEC = A:\GRIDCMD.COM) |
| GRIDCMD.COM | 7,596 | Grid-OS command prompt (CODE-P; CLAUDE's DOS commands); says 0.3 |
| SYSTEM.RUN | 8,084 | System (CODE-U): memory, disks, clock, devices, GPIB scan, display (fonts), screen saver (delay), about |
| WRITE.RUN | 8,215 | Write (CODE-W, or open a text file from the list) |
| GRIDOS.TXT | 10,000 | readme for 0.3 (with the 0.2.x notes; GRiD's font, CODE-?, fonts and GRIDOS.INI) |
| TERMINUS.FNT | 1,536 | the Terminus font as a file for System → Display |
| DEFRAG.COM | 9,212 | disk tidier / screen saver, in the chosen font (`DEFRAG [B:]`, `DEFRAG [B:] /T` to test the free space, `DEFRAG /S` as the saver runs it) |
| DEFRAG.TXT | 1,511 | DEFRAG's log: the /T runs after the reformat (also in `gridos\bench\DEFRAG_1520_2026-10-05_reformatted.TXT`) |
| HEADCLN.COM | 1,488 | floppy head cleaning with a wet cleaning disk |
| TESTDOS.COM | 5,253 | kernel self-test (expect "24 passed, 0 failed") |
| CACHETST.COM | 1,901 | disk-cache stress test (expect "0 errors"); logs to CACHETST.TXT, waits for a key |
| BENCH.COM | 2,179 | BENCH 1.2 file system benchmark; runs under Grid-OS and GRiD MS-DOS; logs to BENCH.TXT, waits for a key |
| BENCH.TXT | 664 | BENCH log: run 8 (also in `gridos\bench\BENCH_1520_2026-10-05_reformatted.TXT`) |
| DISKMAP.COM | 952 | saves the floppy's boot sector, FATs and root to DISKMAP.BIN; shows root entries in use |
| GOSBOOT.COM | 3,047 | installs the Grid-OS boot sector (once per disk, and after every format) |
| GRIDGPIB.COM | 2,688 | GPIB driver 1.1 for GRiD MS-DOS (built into Grid-OS) |
| CLAUDE.COM | 11,152 | Claude for GRiD (Pi bridge at address 7); CODE-A in the Executive; still in Terminus |
| TM5000G.EXE | 296,634 | TM5000 3.7 (TM5000 repo `src/tm5000g.exe`, with PR #3's fix: the mouse pointer comes back after a menu is left by a key) |
| GGTEST.COM | 7,554 | GPIB driver test on the bus |
| TESTKEY.COM | 74 | echoes keys until Esc; for checking Claude's key scripts |

- Windows has recreated its `System Volume Information` folder. Grid-OS shows it as the Subject SYSTEM~1.
- **Drive A:'s head 0 is marginal on the innermost ~14 tracks** (side 0, cylinders ~62–79): the same floppy in the external B: drive shows 0 errors, and head cleaning moved the trouble only from cylinder 61 to ~66. Each error is a whole-track read that fails while every sector reads alone, so 0.2.3 (and 0.3) read such tracks one sector at a time before giving up. Files sit at the front of the disk, away from the weak tracks.

## Status
- 2026-10-04: A: backed up to `grid-OS\floppy_backup_2026-10-04` (23 files), then quick-formatted by Joshua. GRIDOS.SYS 0.1, GOSBOOT.COM and GRIDOS.TXT copied and verified byte for byte.
- **2026-10-04: first boot on the 1520 succeeded** — screen, list, form, clock and keyboard all correct. Phone photos of the plasma show partial frames; that is the camera shutter, not the display.
- 2026-10-04: test keys removed; GRIDOS.SYS 6,496 bytes on A:, verified.
- 2026-10-04 (night): added GRIDGPIB, CLAUDE, TM5000G 3.7, GGTEST and TESTKEY, and extended GRIDOS.TXT; each copied on its own and read back byte for byte.
- **2026-10-05: Grid-OS 0.2 on A:** GRIDOS.SYS 0.2, the shell, TESTDOS.COM and the new GRIDOS.TXT, each copied on its own and read back byte for byte.
- **2026-10-05, on the 1520:**
  - Grid-OS 0.2 booted, and **TESTDOS showed all ok**.
  - A plain boot (no F) brought up GRiD MS-DOS with the Grid-OS shell from A:\COMMAND.COM. DIR worked, then EXIT hung ("Bad or missing Command Interpreter").
  - Fixed the same day: the shell is now GRIDCMD.COM with `/P`. Joshua confirmed both checks passed.
- **2026-10-05: Grid-OS 0.2.1** (disk cache) on A:, with BENCH 1.2 and CACHETST.
  - CACHETST on the 1520: 0 errors.
  - BENCH on the 1520 under both systems, six Grid-OS runs as the kernel improved. Grid-OS leads MS-DOS: 82.4 s against 289 s.
- **2026-10-05: floppy tidied.** All 14 files were backed up to `grid-OS\floppy_backup_2026-10-05` and verified by checksum. Joshua quick-formatted the disk, the files were copied back (each on its own, verified), and Joshua reran `B:GOSBOOT B`.
- 2026-10-05: DISKMAP on the 1520 found the root at 78 entries, 17 live: the bridge's 4 dead entries per copy.
- **2026-10-05: Grid-OS 0.2.2 on A:** GRIDOS.SYS 24,400, DEFRAG.COM, GRIDOS.TXT; each verified identical.
- **2026-10-05 afternoon, 0.2.2 on the 1520:**
  - The saver started DEFRAG after 5 minutes idle, and it began tidying. Then it stopped at a disk error and fell back to the dark clock. Joshua: "I don't want it to just stop!"
  - DEFRAG was reworked to keep going on worn disks (8,944 bytes then).
  - The 16-cluster-limit build stopped at 15:46. The final build ran `/T` at 16:10 (4 marked), then a full run at 16:20, which **finished**: "Disk in order: 18 files, 988 KB free in 26 pieces, 67 bad clusters marked".
  - All errors were on side 0, cylinders 61–78. Every file was verified intact afterwards.
  - **BENCH run 7: directory ×10 0.05 s, total 82.99 s.** Grid-OS is ahead of MS-DOS on every test.
- **2026-10-05 evening:**
  - The power-cut rerun found a root-packing bug (old entries left after the end marker); fixed. DEFRAG also got a drive option (`DEFRAG B:`) and a disk-error count in /T. DEFRAG.COM 9,158 and GRIDOS.TXT 4,430 copied to A: and verified identical.
  - HEADCLN.COM and Grid-OS 0.2.3 (one-sector retry) followed.
  - The same floppy in B: and repeated head cleaning pinned the errors on drive A:'s head 0 (above).
  - The floppy was backed up (`floppy_backup_2026-10-05b`) and fully reformatted on the PC. **BENCH run 8 on the fresh disk: total 82.66 s.**
- **2026-10-06: Grid-OS 0.3 on A:** GRIDOS.SYS 29,588, GRIDCMD.COM, SYSTEM.RUN, WRITE.RUN and GRIDOS.TXT, each copied on its own and read back identical. The PC's `grid-OS\gridos` folder has the matching sources, tests and `releases\0.3`; `src\EXECRUN.INC` there is obsolete and can be deleted.
- **2026-10-06 morning, 0.3 on the 1520:** everything Joshua tried worked except CODE-? (help). The 1520's BIOS gives CODE with punctuation, Return and ESC only through INT 16h AH=10h; fixed the same morning. Joshua also asked for GRiD's own font (now TC8X16 from InteGRiD), and a review panel of six reviewers found ~40 issues: all fixed except three kernel ones noted for later (see `gridos-0.3-apps.md`).
- **2026-10-06 noon: 0.3 updated on A:** GRIDOS.SYS 30,048, SYSTEM.RUN 5,029, WRITE.RUN 8,215, DEFRAG.COM 9,158 and GRIDOS.TXT 6,615. Each was copied on its own and read back identical.
- **2026-10-06 afternoon: switchable fonts (UI API 2) on A:** GRIDOS.SYS 30,292, SYSTEM.RUN 7,570, WRITE.RUN 8,215 (rebuilt for API 2), DEFRAG.COM 9,212, GRIDOS.TXT 6,927 and the new TERMINUS.FNT 1,536, each copied on its own and read back identical. The PC's `grid-OS\gridos` folder matches. Committed as PR #1 (`app-suite-0.3`).
- **2026-10-06 13:20, on the 1520:** the font switch (System → Display → Return, Terminus kept after a restart, back to GRiD's), CODE-? help everywhere and CODE-ESC in Write all work. PR #1 merged into main.
- **2026-10-06 afternoon: 0.3.1, the mouse for DOS programs (INT 33h)** built and tested in emulation (160 app checks; TM5000G finds the mouse and takes clicks; a Fable review's 6 findings fixed). The PC's folder has it, in `releases\0.3.1`. A DOS program now gets 569.4 KB.
- **2026-10-06 14:48: 0.3.1 on A:** GRIDOS.SYS 32,162, GRIDOS.TXT 7,283 and TM5000G.EXE 296,634 (TM5000 PR #3: the pointer comes back after a menu left by a key), each copied on its own and read back identical (GRIDOS.SYS needed a second copy, see the rule above).
- **2026-10-06 afternoon: 0.3.2 (first build), devices in the Executive:** copied to A: at 15:19 and read back; replaced by the File form build below.
- **2026-10-06 later: 0.3.2, the File form** (GRiDManager-style: Tab / Shift-Tab, or Return, move the outline over Device, Subject, Title; the list shows that item's choices; CODE-R and CODE-D removed). Tested in emulation (186 app checks). **On A: at 16:07:** GRIDOS.SYS 32,842 and GRIDOS.TXT 7,880, each copied on its own from a fresh staging path and read back identical (SYSTEM.RUN 7,608 already there). **Next on the 1520 (0.3.2):** Tab / Shift-Tab over Device, Subject, Title; B: by Device; a subject from the tree; Return on a title; clicks on the items.
- **2026-10-06 evening: 0.3.3, file commands** (CODE-C Copy, CODE-M Move, CODE-R Rename, CODE-D Delete; CODE-P the command prompt; questions survive the screen saver; the kernel's `buf_put` fix for failed writes). Built in another session in the PC folder, then verified here: the same GRIDOS.SYS, 237 app checks. In `releases\0.3.3`: GRIDOS.SYS 35,360, GRIDOS.TXT 8,913. **On A: at 18:04**, each copied on its own from a fresh staging path and read back identical. PR #4. **Next on the 1520:** CODE-C Copy to B:, CODE-M Move, CODE-R Rename, CODE-D Delete, CODE-P prompt; a write-protected disk; the saver during a question.
- **2026-10-06 night: 0.3.4, the screen saver's delay** (System → Screen saver; Return cycles 1, 2, 5, 10, 15, 30 minutes, never; `SAVER=n` in GRIDOS.INI; UI API 3, so SYSTEM.RUN 8,084 needs this GRIDOS.SYS). Tested in emulation (251 app checks). In `releases\0.3.4`: GRIDOS.SYS 35,272 (with the Executive's help trimmed), GRIDOS.TXT 9,245, SYSTEM.RUN 8,084; the PC folder has the sources. **On A: at 18:48**, each copied on its own from a fresh staging path and read back identical. **Next on the 1520:** System → Screen saver at 1 minute, then never; a restart keeps it. WRITE.RUN changed only its API byte (2→3); the old one still runs.
- **2026-10-06 night: 0.3.5, wildcards** in Copy, Move and Delete (Titles field), Replace Ask/All/None, Only newer. Tested in emulation (274 app checks; an independent review's 3 bugs fixed). In `releases\0.3.5`: GRIDOS.SYS 36,636, GRIDOS.TXT 10,000 (first build on A: at 21:36; this one, with missing subjects made after a question and two kernel fixes for a failed MKDIR or subject growth, at 22:10).
  - **On the 1520 (2026-10-06 21:44):** Move A:\TEST.TXT to B:\NEWFOLDER (not there) said "Sector not found": B: (a 1.44 MB disk) couldn't be read for a little while; from the prompt B: then read fine and a Copy to B:\ worked. The kernel tries 3 times with a reset between; if it recurs, note whether it is right after a disk goes into B:. **Next on the 1520:** Copy `*.*` to B: with Replace All and Only newer Yes, twice (the second run copies nothing); Delete `*.BAK`.
- **Next, on the 1520 (the checklist in `gridos-0.3-apps.md`):**
  - CODE-? everywhere;
  - CODE-ESC to cancel in Write;
  - the new font, and System → Display → Return to switch to Terminus and back (a restart should keep the choice);
  - System's band;
  - a click above a form;
  - PgDn in a long file;
  - plus the earlier items: TM5000G and back, and 5 minutes idle inside Write.
- Rollback if needed: restart without F to get GRiD MS-DOS, and copy `gridos\releases\0.2.3\GRIDOS.SYS` back. GRIDCMD.COM can stay; only its version text changed in 0.3.

### Cursor flicker — accepted as a panel limitation (decision 2026-10-04)
- **Symptom:**
  - the arrow flickers only in large fully dark areas;
  - worse moving up, gone moving down;
  - fine next to any lit line.
- Software ruled out:
  - RAM composition, a solid XOR arrow and retrace sync made no difference;
  - screen memory read back exactly on hardware (0 stray bytes, 0 unstable reads).
- **Cause: gas-plasma priming in 640×400 mode.** A dot fires reliably only near recently lit dots. Moving up, the arrow's leading rows enter unprimed dark cells. GRiD's own 640×200 modes double every scan line, which may be why it never showed there.
- A faint background glow via the V6366 grey palette stopped the flicker but looked awful — rejected by Joshua.
- **Decision:** leave it as a limitation of the 640×400 mode and the gas-plasma display. The background stays off.
- Optional mitigation for later UI work: avoid large fully dark areas where the pointer travels (rules, frames, ledger lines). DEFRAG's free-cell dots are 3×3 for the same reason.
