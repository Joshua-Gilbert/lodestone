# Lodestone floppy development loop

Lodestone was developed from a boot floppy before it moved to EPROM (`lodestone-rom.md`), and a floppy is still the quickest way to try a new build on a 1520. The kernel is described in `lodestone-0.2-kernel.md`, DEFRAG and the screen saver in `lodestone-defrag.md`, the UI core and the programs in `lodestone-0.3-apps.md`.

## Pieces (source in `os/src` and `os/apps`, built with `os/build.sh`, under WSL on Windows)
- **BOOT.ASM** — the 512-byte floppy boot sector, with 37 bytes spare.
  - Works with any standard FAT12 BPB.
  - Finds `\LODE.SYS` in the root directory and follows its FAT chain, so the file can be fragmented or replaced at will.
  - No size limit.
  - Reads whole runs of sectors per INT 13h call, split only at track ends and 64 KB DMA boundaries.
  - Loads the kernel to **1000:0000** and jumps there with DL = boot drive and DS:SI = 0:7C00 (BPB).
  - On error it prints a message, waits for a key and issues INT 19h.
- **LODEBOOT.COM** — runs under GRiD MS-DOS on the Grid.
  - Reads sector 0 and checks it is a 720 KB / 1.44 MB FAT12 floppy.
  - Keeps the disk's own BPB (bytes 0Bh–3Dh), drops in the Lodestone boot code, writes it back and verifies it.
  - Asks Y/N first, writes sector 0 only, and leaves files untouched. `LODEBOOT B` targets drive B:.
- **LODE.SYS** — the kernel (disk cache, one-sector-at-a-time retry, EMS manager) plus the UI segment (UI core, Executive, built-in font, screen saver). **LODEMT.SYS** is multitasking's part, from the same build. See `lodestone-0.3-apps.md`.
  - Releases are kept in `os\releases\`, each with its files; an earlier release's LODE.SYS is the rollback.
  - The Executive runs in mode 40h (640×400); other 8×16 fonts are `.FNT` files (System → Display, saved as `FONT=` in `A:\LODE.INI`). Microsoft mouse on COM2/COM1, XOR arrow.
- **The .RUN programs** — SYSTEM.RUN (CODE-U), WRITE.RUN (CODE-W, and opening text files from the list), CALC, TASKS, TERM, PAINT: programs on the UI core. `mkrun.py` (needs Python) builds them from `apps\*.ASM`.
- **TERMINUS.FNT** (1,536 bytes) — the Terminus font as a file for System's Display topic. Built from `fonts\TERMINUS.ASM`; `typfont.py X.TYP --fnt X.FNT` makes one from any 8×16 GRiD .TYP font.
- **DEFRAG.COM** — the disk tidier, and the screen saver's first act. It keeps going on worn disks (marks bad clusters, logs to DEFRAG.TXT), and `DEFRAG /T` tests the free space. See `lodestone-defrag.md`.
- **HEADCLN.COM** — floppy head cleaning with a wet cleaning disk (0.2.3).
- **LCMD.COM** — the command prompt (CODE-P) and CLAUDE's `COMSPEC /C`.
  - Deliberately **not** named COMMAND.COM; see the rule below.
- **Emulator and tests:**
  - **pcemu.py** — a BIOS-only PC that boots the real floppy image (built by `mkimg.py` with mtools + BOOT.BIN). It has an optional real-drive timing model and can simulate unreadable sectors. Its INT 16h behaves like the 1520's BIOS for CODE + punctuation/Return/ESC.
  - **ktest.py** — drives the Executive and reads its screen back (it knows both fonts); symbols are looked up in the kernel or the UI segment. `run_answering` presses Enter when a program says "Press any key".
  - **tests\\:**
    - `test_kernel.py`;
    - `test_apps.py` (the UI core through UITEST.RUN, System, Write, the Executive, memory with MEMSZ.COM and TSR.COM, the saver inside a program);
    - `test_defrag.py`, with `defrag_util.py` and `defrag_cut.py` (a power cut at every DEFRAG write; `worn` mode on a simulated worn drive);
    - `test_headcln.py`;
    - `test_claude_kernel.py` (Claude scenarios on the kernel);
    - `ggtest_kernel.py`, `fatcheck.py`, TESTDOS, CACHETST, UPPER.
  - **bench\\:**
    - BENCH.COM and `run_bench.py`, which compares Lodestone with GRiD MS-DOS 3.30 booted from the EPROM image in pcemu;
    - DISKMAP.COM (dumps the floppy's system area);
    - `trace.py`, `prof.py`, `gapprof.py`;
    - the results in `RESULTS.TXT`, the 1520 logs `BENCH_1520_2026-10-05*.TXT` and `DEFRAG_1520_2026-10-05_reformatted.TXT`, and `DISKMAP_1520_2026-10-05*.BIN`.
  - Screenshots in `os\screens\0.2`, `screens\0.2.2` and `screens\0.3`.
  - `gosim.py` and the `test_*.py` in the `os` folder are the 0.1 harness.

## Rule: what must not be on this floppy
- GRiD MS-DOS booted from the EPROM (no F) with this floppy in the drive takes `\COMMAND.COM` and `\CONFIG.SYS` from A: in place of its own. The strings `\CONFIG.SYS` and `\COMMAND.COM` sit in its IO.SYS, opened on the default drive, and AUTOEXEC.BAT follows from the shell.
- **Keep COMMAND.COM, CONFIG.SYS and AUTOEXEC.BAT off A:** unless they are meant for GRiD MS-DOS.
- Learned 2026-10-05: with Lodestone's shell as A:\COMMAND.COM, GRiD MS-DOS ran it as its primary shell, and EXIT then stopped DOS with "Bad or missing Command Interpreter". The shell was renamed GRIDCMD.COM (LCMD.COM since 0.4.1), and it now also honours `/P`.

## Loop
1. Once per floppy: format it (FAT, 1.44 MB) and copy the files.
   - Boot the Grid normally (EPROM → GRiD MS-DOS), where the floppy is **B:**.
   - Run `B:LODEBOOT B` and answer Y.
   - Formatting replaces the boot sector, so LODEBOOT has to run again after every format.
2. Boot Lodestone: restart and **tap F as the memory count finishes**. The BIOS (GridWaitKey) takes a buffered keypress and boots the floppy instead of the EPROM.
3. Iterate: rebuild (`os/build.sh`) and copy the changed files (LODE.SYS with LODEMT.SYS, the shell, the `.RUN`s, DEFRAG.COM) onto the floppy in the PC. No need to rerun LODEBOOT.
   - **Copy each file on its own, then read it back and compare.** A copy to the floppy has been seen to report success while the disk kept the old file; a second copy on its own fixed it each time.
   - **Results come back on the floppy:** BENCH and CACHETST add each run to `BENCH.TXT` / `CACHETST.TXT` on the disk they ran from, and DEFRAG to `DEFRAG.TXT`. Each run is headed with the date (and, for BENCH, the system).
   - **A copy that writes a hidden long-name temporary file and then renames it leaves 4 dead root entries per file.** Windows never reuses the dead slots; it appends.
     - Once the root passes 63 entries, directory searches cost a whole-root read.
     - **DEFRAG removes them** (on its own after 5 minutes idle in the Executive). No more format-and-refill needed for that.
   - **Each kernel copy can also leave a hole** where the old LODE.SYS was. The next big file (BENCH.DAT) fills it and is split, so BENCH reads look 0.3–0.8 s slower. DEFRAG puts files back in one piece. Compare BENCH read times only between runs on the same layout.
4. Back to DOS: a plain restart (CTRL-ALT-DEL) without F. Under GRiD MS-DOS booted from the EPROM, A: is the EPROM and the floppy is B:.

## What's on the floppy (A:)
The files to boot from are listed in the top-level README ("From a floppy"); the current release's are in `os/releases/`. A development floppy holds these, with the test programs:

| File | What |
|---|---|
| LODE.SYS, LODEMT.SYS | the kernel, UI core, Executive, disk cache, screen saver and EMS manager (COMSPEC = A:\LCMD.COM); multitasking's part, from the same build |
| LODE.PIC | the start-up picture (`lodestone-splash.md`) |
| LCMD.COM | Lodestone command prompt (CODE-P; CLAUDE's DOS commands) |
| SYSTEM.RUN, WRITE.RUN, CALC.RUN, TASKS.RUN, TERM.RUN, PAINT.RUN | the programs on the UI core |
| TERM.FNT, TERMINUS.FNT | the terminal window's font; the Terminus font for System → Display |
| DEFRAG.COM | disk tidier / screen saver (`DEFRAG [B:]`, `DEFRAG [B:] /T` to test the free space, `DEFRAG /S` as the saver runs it) |
| DEFRAG.TXT | DEFRAG's log |
| HEADCLN.COM | floppy head cleaning with a wet cleaning disk |
| TESTDOS.COM | kernel self-test (expect "0 failed") |
| CACHETST.COM | disk-cache stress test (expect "0 errors"); logs to CACHETST.TXT, waits for a key |
| BENCH.COM | file system benchmark, plus EMS tests (map, 57h moves) when there is EMS; runs under Lodestone, GRiD MS-DOS and FreeDOS; logs to BENCH.TXT, waits for a key |
| DISKMAP.COM | saves the floppy's boot sector, FATs and root to DISKMAP.BIN; shows root entries in use |
| LODEBOOT.COM | installs the Lodestone boot sector (once per disk, and after every format) |
| GRIDGPIB.COM | GPIB driver for GRiD MS-DOS (`tools/GRIDGPIB.ASM`: the kernel's KGPIB.INC, built into Lodestone, with its installer) |
| CLAUDE.COM | Claude for GRiD (Pi bridge at address 7); CODE-A in the Executive; `/T` Term (Claude Code on the Pi) |
| TM5000G.EXE | TM5000 3.7 (TM5000 repo `src/tm5000g.exe`) |
| GGTEST.COM | GPIB driver test on the bus |
| EMSTEST.COM | EMS (INT 67h) test: "0 failed" is right; waits for a key, adds to EMSTEST.TXT; also under GRiD MS-DOS + EMM.SYS |
| TESTKEY.COM | echoes keys until Esc; for checking Claude's key scripts |

- A floppy written by Windows gets a `System Volume Information` folder. Lodestone shows it as the Subject SYSTEM~1.
- **On the development 1520, drive A:'s head 0 is marginal on the innermost ~14 tracks** (side 0, cylinders ~62–79): the same floppy in the external B: drive shows 0 errors, and head cleaning moved the trouble only from cylinder 61 to ~66. Each error is a whole-track read that fails while every sector reads alone, so since 0.2.3 the kernel reads such tracks one sector at a time before giving up. Files sit at the front of the disk, away from the weak tracks.

## Notes
- Rollback if needed: restart without F to get GRiD MS-DOS, and copy an earlier release's LODE.SYS and LODEMT.SYS back from `os\releases\`.
- Floppy DMA into the EMS frame works on the 1520 (2026-10-07, `bench\EMSTEST_1520_2026-10-07.TXT`); pcemu reports BIOS error 9 for it.
- Phone photos of the plasma show partial frames; that is the camera shutter, not the display.

### Cursor flicker — a limitation of the plasma display (2026-10-04)
- **Symptom:**
  - the arrow flickers only in large fully dark areas;
  - worse moving up, gone moving down;
  - fine next to any lit line.
- Software ruled out:
  - RAM composition, a solid XOR arrow and retrace sync made no difference;
  - screen memory read back exactly on hardware (0 stray bytes, 0 unstable reads).
- **Cause: gas-plasma priming in 640×400 mode.** A dot fires reliably only near recently lit dots. Moving up, the arrow's leading rows enter unprimed dark cells. GRiD's own 640×200 modes double every scan line, which may be why it never showed there.
- A faint background glow via the V6366 grey palette stopped the flicker but looked awful, so it was rejected.
- **Decision:** leave it as a limitation of the 640×400 mode and the gas-plasma display. The background stays off.
- Optional mitigation for later UI work: avoid large fully dark areas where the pointer travels (rules, frames, ledger lines). DEFRAG's free-cell dots are 3×3 for the same reason.
