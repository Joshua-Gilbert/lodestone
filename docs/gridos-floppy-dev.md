# Grid-OS floppy development loop (Grid-OS 0.2.2 on the floppy, 2026-10-05)

Decision: develop from a boot floppy until the OS is stable, then build the ROM version (see `gridos-kernel-hardware-spec.md` for the EPROM format). The plan is in `gridos-roadmap.md`; the kernel is described in `gridos-0.2-kernel.md`, DEFRAG and the screen saver in `gridos-defrag.md`.

## Pieces (source in `grid-OS\gridos\src`, build with `gridos\build.sh` or `BUILD.BAT`)
- **BOOT.ASM** — the 512-byte floppy boot sector, with 37 bytes spare.
  - Works with any standard FAT12 BPB.
  - Finds `\GRIDOS.SYS` in the root directory and follows its FAT chain, so the file can be fragmented or replaced at will.
  - No size limit; it loads 0.2.2's 24 KB unchanged.
  - Reads whole runs of sectors per INT 13h call, split only at track ends and 64 KB DMA boundaries.
  - Loads the kernel to **1000:0000** and jumps there with DL = boot drive and DS:SI = 0:7C00 (BPB).
  - On error it prints a message, waits for a key and issues INT 19h.
- **GOSBOOT.COM** — runs under GRiD MS-DOS on the Grid.
  - Reads sector 0 and checks it is a 720 KB / 1.44 MB FAT12 floppy.
  - Keeps the disk's own BPB (bytes 0Bh–3Dh), drops in the Grid-OS boot code, writes it back and verifies it.
  - Asks Y/N first, writes sector 0 only, and leaves files untouched. `GOSBOOT B` targets drive B:.
- **GRIDOS.SYS 0.2.2** — the kernel plus the Executive, with the disk cache and the screen saver: **24,400 bytes**. See `gridos-0.2-kernel.md`.
  - 0.2.1 (last build, 23,744 bytes) is kept in `gridos\releases\0.2.1`, 0.2 in `releases\0.2`, and 0.1 (the 6,496-byte "hello" kernel) in `releases\0.1` with its source. 0.2.2 is in `releases\0.2.2` (GRIDOS.SYS, DEFRAG.COM, GRIDOS.TXT).
  - The Executive look and the serial mouse carry over from 0.1:
    - mode 40h, Terminus Bold 16;
    - the date/title/time bar, list, form, system line and prompt band;
    - Microsoft mouse on COM2/COM1, XOR arrow.
- **DEFRAG.COM** — the disk tidier, and the screen saver's first act. It keeps going on worn disks (marks bad clusters, logs to DEFRAG.TXT), and `DEFRAG /T` tests the free space. See `gridos-defrag.md`.
- **GRIDCMD.COM** — the command prompt (CODE-C) and CLAUDE's `COMSPEC /C`.
  - Deliberately **not** named COMMAND.COM; see the rule below.
- **Emulator and tests:**
  - **pcemu.py** — a BIOS-only PC that boots the real floppy image (built by `mkimg.py` with mtools + BOOT.BIN). It has an optional real-drive timing model and can simulate unreadable sectors.
  - **ktest.py** — drives the Executive and reads its screen back. `run_answering` presses Enter when a program says "Press any key".
  - **tests\\:**
    - `test_kernel.py` (59 checks);
    - `test_defrag.py` (33 checks), with `defrag_util.py` and `defrag_cut.py` (a power cut at every DEFRAG write; `worn` mode on a simulated worn drive);
    - `test_claude_kernel.py` (21 Claude scenarios on the kernel);
    - `ggtest_kernel.py`, `fatcheck.py`, TESTDOS, CACHETST, UPPER.
  - **bench\\:**
    - BENCH.COM and `run_bench.py`, which compares Grid-OS with GRiD MS-DOS 3.30 booted from the EPROM image in pcemu;
    - DISKMAP.COM (dumps the floppy's system area);
    - `trace.py`, `prof.py`, `gapprof.py`;
    - the results in `RESULTS.TXT`, the 1520 logs `BENCH_1520_2026-10-05*.TXT`, and `DISKMAP_1520_2026-10-05*.BIN`.
  - Screenshots in `gridos\screens\0.2` and `screens\0.2.2`.
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
3. Iterate: Claude rebuilds GRIDOS.SYS (and GRIDCMD.COM, DEFRAG.COM) and copies it straight onto A:. The floppy drive is a connected folder, reachable only while the disk is in the PC. No need to rerun GOSBOOT.
   - **Copy each file to A: on its own** (not in a batch with other files), **then read it back and compare**. A copy has reported success while the floppy kept the old file three times now (most recently DEFRAG.COM on 2026-10-05). A second, solo copy fixed it each time.
   - Claude's bridge to the PC can write and read files but currently can't delete or rename them, because the device shell is blocked by a Windows update (still the case 2026-10-05 evening). Deletions have to be done by Joshua.
   - **Results come back on the floppy:** BENCH and CACHETST add each run to `BENCH.TXT` / `CACHETST.TXT` on the disk they ran from, and DEFRAG to `DEFRAG.TXT`. Each run is headed with the date (and, for BENCH, the system). Claude reads these files once the disk is back in the PC.
   - **Each copy through the bridge leaves 4 dead root entries.** The bridge writes a hidden long-name temp file (`.NAME.EXT.pid.random.tmp`), then renames it. Windows never reuses the dead slots; it appends.
     - Once the root passes 63 entries, directory searches cost a whole-root read.
     - **DEFRAG removes them** (on its own after 5 minutes idle under 0.2.2). No more format-and-refill needed for that.
   - **Each kernel copy can also leave a hole** where the old GRIDOS.SYS was. The next big file (BENCH.DAT) fills it and is split, so BENCH reads look 0.3–0.8 s slower. DEFRAG puts files back in one piece. Compare BENCH read times only between runs on the same layout.
4. Back to DOS: CODE-D, or a plain restart without F. Under GRiD MS-DOS booted from the EPROM, A: is the EPROM and the floppy is B:.

## What's on the floppy (A:) — reformatted 2026-10-05
| File | Size | What |
|---|---|---|
| GRIDOS.SYS | 24,400 | **Grid-OS 0.2.2** kernel + Executive + disk cache + screen saver (COMSPEC = A:\GRIDCMD.COM) |
| DEFRAG.COM | 9,158 | disk tidier / screen saver (`DEFRAG [B:]`, `DEFRAG [B:] /T` to test the free space, `DEFRAG /S` as the saver runs it) |
| DEFRAG.TXT | 1,459 | DEFRAG's log: the 15:46 stop, the /T run and the full run of 2026-10-05 |
| GRIDCMD.COM | 7,596 | Grid-OS command prompt (CODE-C; CLAUDE's DOS commands) |
| TESTDOS.COM | 5,253 | kernel self-test (expect "24 passed, 0 failed") |
| CACHETST.COM | 1,901 | disk-cache stress test (expect "0 errors"); logs to CACHETST.TXT, waits for a key |
| BENCH.COM | 2,179 | BENCH 1.2 file system benchmark; runs under Grid-OS and GRiD MS-DOS; logs to BENCH.TXT, waits for a key |
| BENCH.TXT | 2,656 | BENCH log: runs 4–7 (also in `gridos\bench\BENCH_1520_2026-10-05_fresh.TXT`) |
| DISKMAP.COM | 952 | saves the floppy's boot sector, FATs and root to DISKMAP.BIN; shows root entries in use |
| DISKMAP.BIN | 16,896 | DISKMAP's dump from 15:29, after the first DEFRAG run (saved on the PC; can be deleted) |
| GRIDOS.TXT | 4,430 | readme for 0.2.2 (saver, DEFRAG, /T, B:, DEFRAG.TXT) |
| GOSBOOT.COM | 3,047 | installs the Grid-OS boot sector (once per disk, and after every format) |
| GRIDGPIB.COM | 2,688 | GPIB driver 1.1 for GRiD MS-DOS (built into Grid-OS) |
| CLAUDE.COM | 11,152 | Claude for GRiD (Pi bridge at address 7); CODE-A in the Executive |
| TM5000G.EXE | 296,650 | TM5000 3.7 (release build, TM5000 repo `src/tm5000g.exe`) |
| GGTEST.COM | 7,554 | GPIB driver test on the bus |
| TESTKEY.COM | 74 | echoes keys until Esc; for checking Claude's key scripts |

- Windows has recreated its `System Volume Information` folder. Grid-OS shows it as the Subject SYSTEM~1, and DEFRAG counts it as the 18th file.
- **71 clusters (~35 KB) on side 0, cylinders 61–78, are marked bad** by DEFRAG. 988 KB is free. A full format gets the marked clusters back if the drive head turns out to be the cause.

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
  - DEFRAG was reworked to keep going on worn disks (now 8,944 bytes).
  - The 16-cluster-limit build stopped at 15:46. The final build ran `/T` at 16:10 (4 marked), then a full run at 16:20, which **finished**: "Disk in order: 18 files, 988 KB free in 26 pieces, 67 bad clusters marked".
  - All errors were on side 0, cylinders 61–78 — probably the drive's lower head. Every file was verified intact afterwards.
  - **BENCH run 7: directory ×10 0.05 s, total 82.99 s.** Grid-OS is ahead of MS-DOS on every test.
- **2026-10-05 evening:** the power-cut rerun found a root-packing bug (old entries left after the end marker); fixed. DEFRAG also got a drive option (`DEFRAG B:`) and a disk-error count in /T. DEFRAG.COM 9,158 and GRIDOS.TXT 4,430 copied to A: and verified identical.
- **Next:** Joshua has an external 1.44 MB **B:** drive. The same floppy in B: with `B:DEFRAG B: /T`, then in A: with `DEFRAG /T`, and compare the disk-error counts to tell drive from disk.
- Rollback if needed: restart without F to get GRiD MS-DOS, and copy `gridos\releases\0.2.1\GRIDOS.SYS` (or 0.2, 0.1) back.

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
