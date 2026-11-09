# Lodestone 0.2 — the kernel (built 2026-10-04/05; 0.2.1 disk cache, 0.2.2 screen saver + DEFRAG, 2026-10-05)

Lodestone 0.2 replaces GRiD MS-DOS with its own DOS 3.30-compatible kernel. It boots from the floppy, shows the Executive, runs DOS programs and comes back to the Executive. The GPIB driver is built in.

**Milestone met, in emulation:**
- browse the floppy;
- run TM5000G from the Executive and return;
- CLAUDE.COM runs unchanged.

**On the 1520 (2026-10-05):**
- Joshua ran TESTDOS under Lodestone and saw all "ok" lines.
- The plain EPROM boot with the floppy in now keeps GRiD MS-DOS's own shell (LCMD rename, below): both checks passed.
- CACHETST under 0.2.1: 240 ops, 0 errors.
- BENCH under both systems: **Lodestone takes 82–83 s in total against GRiD MS-DOS's 289 s.**
- **0.2.2** (screen saver + DEFRAG, see `lodestone-defrag.md`) runs on the 1520. The saver started DEFRAG after 5 minutes idle, and DEFRAG packed the cluttered root. **BENCH run 7: directory ×10 took 0.05 s** (MS-DOS 0.21), so Lodestone is now **ahead of GRiD MS-DOS on all ten tests**.

## 0.2.1: disk cache, benchmark (2026-10-05)
Joshua suspected 0.2's disk reads were a little slower than GRiD MS-DOS's. We benchmarked in pcemu against GRiD MS-DOS 3.30 from the EPROM image, on the same kind of 1.44 MB floppy with real-drive timing, then on the real 1520.

- **BENCH.COM** (`os\bench`, version 1.2):
  - 10 tests timed with INT 1Ah. It prints seconds, KB/s, the system and "Memory for programs".
  - Each run is added to `BENCH.TXT` on the disk it ran from. It's written at the end, so the logging doesn't disturb the timing. It waits for a key before exiting.
  - The same program runs under either OS.
  - `run_bench.py <EPROM image>` runs both and prints a side-by-side table from exact emulator timing points (INT 1Ah with BX=BExxh).
  - `trace.py N` shows every BIOS disk call of test N; `prof.py` and `gapprof.py` show where the kernel's CPU time goes.
- **DISKMAP.COM** (`os\bench`): saves the floppy's boot sector, FATs and root to DISKMAP.BIN and shows how many root entries are in use, deleted ones included. It works under either OS and reads the disk directly with INT 13h.
- **pcemu timing model:**
  - 300 rpm; 3 ms step + 15 ms settle (the GRiD BIOS's SPECIFY DFh); 400 ms spin-up; 2 s motor run-on.
  - 1.44 MB sector spacing (gap 108); BIOS overhead 250 µs in, 100 µs out.
  - CPU: 4 µs per basic block, with REP string ops at the RAMSPEED-measured 1520 rates.
  - The first model charged a whole block per REP iteration. That made copies about 6× too slow and showed INT 21h dispatch as 48% slower than MS-DOS — an artefact, not a kernel problem.
  - Fixed 2026-10-05: an IRQ still pending at HLT is now delivered before the emulator sleeps to the next tick, as a real PIC would deliver it after IRET. Before this, a mouse IRQ could starve behind the timer.
- **What 0.2 did, compared with MS-DOS:**
  - 16 KB reads were 3% slower, EXE loading 23% slower, small files 8% slower.
  - 128-byte reads took 105 s on both: one disk turn per sector. 512-byte reads were 12× faster on 0.2.
  - Causes:
    - every request start and every 64 KB DMA split missed the next sector, costing a full turn;
    - the EXE loader's 32 KB chunks ended mid-sector;
    - close wrote the whole FAT (18 sectors), after the directory entry;
    - writes went one sector per BIOS call.
- **Changes in 0.2.1:**
  - **Cylinder cache (KDISK):**
    - An 18 KB system block (owner 8, "SC") at the top of memory, inside one 64 KB DMA page.
    - When a file is read in order — from the start, or within 512 bytes after where the last read ended (new SFT field S_RAE) — the disk reads ahead to the end of the cylinder on both heads (two BIOS calls), as far as the file goes.
    - A search that reaches the root directory's second sector or later reads the whole root into the cache in one pass (`root_pre`), unless the sector it needs is already in a sector buffer (`buf_has`).
    - Reads that straddle a DMA boundary go through the cache in one BIOS call instead of three.
    - Writes copy their data into whatever the cache holds of those sectors. A failed or Ignored write empties the cache. So does a media change, F5, INT 21h 0Dh or a mount.
    - Read-ahead is a guess: one try and no INT 24h. If it fails, just the requested sectors are read the normal way, and that cylinder gets no more read-ahead.
  - **Sector buffers:** 5 — four for directory and system sectors (LRU, `buf_get`) and one for file data only (`buf_getd`, part-sector reads and writes). File data can't push directory sectors out, and a root of up to 63 entries (4 sectors) stays buffered.
  - **Directory searches** (find next, and `dir_find` behind open/create/delete) step through a sector's entries straight in the buffer. Root entries in the same sector as the last lookup skip the lookup entirely. This is root-only, because subdirectory sectors can move when a directory is deleted and recreated.
  - **Help window:** its 11 KB save-under now borrows the cache's memory; the cache is locked while help is open.
  - **Writes:**
    - Whole runs up to the end of the track.
    - The free clusters right after the chain's end are found with a tight FAT12 loop (`free_run`) and join the run.
    - They are linked into the FAT before the write if the run starts a track, when there is time to spare; otherwise after the write.
  - **FAT:** only the changed sectors are written (dirty mask). The FAT goes before the directory entry on close and on MKDIR.
  - **File position:** the SFT cluster cache moves to the end of each run, and `rw_where` has no shift loop.
- **Results in the emulator (seconds; `bench\RESULTS.TXT`):**

  | Test | 0.2 | 0.2.1 | GRiD MS-DOS | 0.2.1 / DOS |
  |---|---|---|---|---|
  | Write 256 KB, 16 KB writes | 9.34 | 9.29 | 13.08 | 0.71× |
  | Read 256 KB, 16 KB reads | 11.53 | 8.58 | 11.55 | 0.74× |
  | Read 256 KB, 512-byte reads | 8.59 | 8.61 | 105.19 | 0.08× |
  | Read 256 KB, 128-byte reads | 105.19 | 8.65 | 105.19 | 0.08× |
  | 64 random 512-byte reads | 9.74 | 9.26 | 9.93 | 0.93× |
  | 20 small files, create + delete | 27.87 | 21.15 | 26.41 | 0.80× |
  | Load + run 120 KB .EXE × 3 | 17.25 | 12.10 | 14.03 | 0.86× |
  | Directory ×10 / open+close ×100 / INT 21h ×1000 | 0.02 / 0.22 / 0.09 | 0.02 / 0.20 / 0.09 | 0.06 / 0.41 / 0.12 | 0.4–0.8× |

  - 0.2.2 on the standard disk gives the same: small files 21.54, random 9.33, EXE ×3 12.11, total 78.98 s.
  - Small shifts between kernel builds (e.g. reads 8.58 → 8.78) come from where BENCH.DAT lands relative to the track. A bigger kernel moves it by a cluster. They are not speed changes.
- Sequential reads of any request size now cost one pass per cylinder, about 3 turns. That is close to the floor: each step to the next cylinder misses its sector 1.
- **Memory for programs:** 570 KB in emulation for 0.2.2 (571–572 KB for earlier 0.2.1 builds), against 582 KB under 0.2 and 580 KB under GRiD MS-DOS. Started from the command prompt instead of the Executive, a program gets ~16 KB less, because LCMD stays loaded underneath (554 KB in run 7).
- **On the real 1520 (2026-10-05; `bench\BENCH_1520_2026-10-05.TXT` and `..._fresh.TXT`):**

  | Test | 1: first build | 2: dir/write fixes | 3: entry stepping | 4: fresh floppy | 5: `buf_has`, after copy | 6: data buffer | 7: 0.2.2, after DEFRAG | GRiD MS-DOS |
  |---|---|---|---|---|---|---|---|---|
  | Write 256 KB | 14.66 | 12.68 | 12.90 | 12.68 | 12.90 | 12.52 | 12.41 | 13.89 |
  | Read 256 KB, 16 KB / 512 B / 128 B | 8.95 / 8.78 / 8.78 | 9.39 / 9.55 / 9.77 | 9.00 / 9.39 / 9.55 | 8.84 / 8.78 / 8.78 | 9.17 / 9.33 / 9.55 | 8.78 / 8.78 / 8.78 | 8.67 / 8.56 / 8.62 | 11.97 / 104.86 / 104.86 |
  | 64 random reads | 9.88 | 10.27 | 10.05 | 9.88 | 10.32 | 9.28 | 9.66 | 10.49 |
  | Directory ×10 | 19.88 | 0.54 | 0.43 | 0.43 | 0.43 | 0.43 | **0.05** | 0.21 |
  | Open + close ×100 | 0.21 | 0.10 | 0.10 | 0.10 | 0.10 | 0.10 | 0.16 | 0.21 |
  | 20 small files | 62.73 | 21.58 | 21.14 | 21.58 | 21.58 | 21.53 | 22.74 | 28.45 |
  | Load EXE ×3 | 12.85 | 12.90 | 13.51 | 12.96 | 12.90 | 12.08 | 12.02 | 14.06 |
  | INT 21h ×1000 | 0.05 | 0.10 | 0.05 | 0.05 | 0.10 | 0.05 | 0.05 | 0.10 |
  | Total | 146.8 | 87.0 | 86.2 | 84.15 | 86.45 | **82.39** | 82.99 | 289.2 |

  - Reads matched the emulator within 2–4% on the first run. The short tests differ by one 55 ms clock tick.
  - **The old floppy's root was cluttered** (150+ entries). The first build re-read each sector. One-pass reading and cache updates on writes took the listing from 19.88 to 0.54 s, and entry stepping took it to 0.43 s.
  - **Run 4 (freshly formatted):** reads were back to the first run's values. Writes were still 12.68 (drive timing, not layout).
  - **Run 5:** reads 0.3–0.8 s slower. Reproduced in the emulator: Windows put the new LODE.SYS after TM5000G and freed the old one's 47 clusters at the front, so BENCH.DAT was split. The same happened in runs 2–3. In run 6 the new kernel went back into that gap, and reads were at full speed again.
  - **The data buffer (run 6):** random reads 10.32 → 9.28 s and EXE ×3 12.90 → 12.08 s, as the emulator predicted.
  - **The directory listing stayed at 0.43 s because of our copying.** DISKMAP on the 1520 showed the root at 78 entries (5 sectors), only 17 of them live.
    - The desktop bridge writes each file under a hidden long-name temp file (`.CACHETST.COM.21336.m11ot0.tmp`) and then renames it. That leaves 4 dead entries per copy, and Windows never reuses them; it appends. Lodestone and MS-DOS do reuse deleted slots when creating files.
    - An exact emulator copy of that floppy gave 0.45 s (real 0.43).
  - **Buffer sweep (emulator, exact copy):** N directory buffers hold a root of up to 16N−1 entries. Past that, each listing does one whole-root read, ~0.45 s. It is a cliff, not a curve. Each bridge copy adds 4 entries, so one buffer lasts 4 copies.
    - Joshua chose **one extra buffer** (4 directory buffers; still 571 KB at the time). It handles ordinary floppies of up to 63 root entries.
    - The real fix for our development floppy is cleaning the root, which **DEFRAG does** (0.2.2).
  - **Run 7 (0.2.2, after DEFRAG packed the root to ~21 entries and every file into one piece):**
    - **The directory listing took 0.05 s, one clock tick with no disk reads.**
    - Reads were the best yet. Small files (+1.2 s) and random reads (+0.4 s) were a little slower than run 6, but not because of the kernel: 0.2.2 gives the old values in the emulator.
    - The cause is either the layout after packing (where free space now starts) or retries on the drive's side 0, the side DEFRAG found weak (see `lodestone-defrag.md`). A DISKMAP of the floppy as it is now would let the emulator check it.
  - **Option 2 declined:** a permanent 7 KB root cache. Joshua's reasons: disk-swap risk, small gain.
- **Independent review of the cache code:** no high-severity bugs. Three edge cases were fixed:
  - a failed head-1 read-ahead could leave a bad sector marked as cached;
  - the FAT buffer stays at 12 sectors, so corrupt 12-bit chain values stay inside it;
  - close only flushes the FAT when the cached FAT belongs to this file's drive.

## 0.2.2: screen saver and DEFRAG (2026-10-05)
Full description in `lodestone-defrag.md`.
- After 5 minutes idle the Executive runs `DEFRAG.COM /S`, which shows the disk map and tidies the floppy. Then comes a dark screen with the time and date, moving every 20 s.
- DEFRAG keeps going on worn disks: it marks bad clusters, leaves unreadable files where they are, and logs to `A:\DEFRAG.TXT`. `DEFRAG /T` tests the free space.
- Kernel additions:
  - **INT 21h F0h** (AL=0: 'GO' signature; AL=1: files open on a drive; later AL=8: a floppy written by the caller through INT 13h, taken as it is).
  - **INT 21h 0Dh** only writes a dirty FAT to the same disk, always drops everything, and returns AL=FFh if it couldn't write.
  - **D_CHK:** after 0Dh the next access re-checks the boot sector.
- After DEFRAG the Executive calls INT 21h 36h, so the FAT is cached again while the disk is surely the same.
- The version shows as "Lodestone 0.2.2"; the help window has a "5 minutes idle — screen saver" line.

## The shell is LCMD.COM, not COMMAND.COM (fixed 2026-10-05)
- **What happened:** the first floppy had the Lodestone shell as `A:\COMMAND.COM`. When GRiD MS-DOS was booted from the EPROM (no F) with that floppy in the drive, its SYSINIT took `\COMMAND.COM` from A: in place of the ROM's own.
  - The shell ran under real MS-DOS 3.30, and DIR worked.
  - EXIT then ended the primary shell, so DOS stopped with "Bad or missing Command Interpreter".
- **Fix:**
  - The shell is now **LCMD.COM**, and the kernel's environment has `COMSPEC=A:\LCMD.COM`.
  - With `/P`, or when it is its own parent, it acts as a real first shell: EXIT does nothing, `\AUTOEXEC.BAT` runs, COMSPEC is set if missing, and an empty environment (segment 0) is handled.
- **Rule for this floppy:** keep COMMAND.COM, CONFIG.SYS and AUTOEXEC.BAT off A: unless they are meant for GRiD MS-DOS. With this floppy in the drive, GRiD MS-DOS uses them from A:.

## What's on the floppy (A:)
The full list is in `lodestone-floppy-dev.md`.
- Freshly formatted on 2026-10-05 and refilled; LODEBOOT was rerun, as it has to be after every format.
- **LODE.SYS:** 24,400 bytes, Lodestone 0.2.2. **DEFRAG.COM:** 9,158 bytes (also `DEFRAG B:`). **LODE.TXT** for 0.2.2.
- **BENCH.COM 1.2** and **CACHETST.COM** both log to .TXT files on the disk and wait for a key. `BENCH.TXT` holds runs 4–7. **DISKMAP.COM** and its DISKMAP.BIN (17 KB, can be deleted) are there too, as is DEFRAG's log **DEFRAG.TXT**.
- 71 clusters on side 0 of cylinders 61–78 are marked bad by DEFRAG (see `lodestone-defrag.md`).
- Each file was copied on its own and read back byte for byte. DEFRAG.COM needed a second copy, because the first left the old file, again.
- The boot sector loads any kernel size (it follows the FAT chain), so a new LODE.SYS doesn't need LODEBOOT; only a format does.

## Source (`os/` in the repo)
`src\LODE.ASM` includes the modules below. Build everything with `build.sh` (NASM; on Windows under WSL). `kbuild.sh` builds the kernel alone, with `LODE.MAP` and `.LST`. A `-dNOTC` build has no cache.

| Module | What |
|---|---|
| LODE.ASM | load at 1000:0000 → relocate to **0060:0000**, clear BSS, init, start the Executive |
| KCORE.INC | INT 21h entry/dispatch (incl. F0h), console I/O, ^C, date/time, vectors, misc. calls |
| KMEM.INC | MCB arena; the cache block at the top |
| KDISK.INC | drive table, BPB mount, disk changes (D_CHK), FAT cache (dirty sectors), `free_run`, sector buffers (`buf_get` / `buf_getd` / `buf_has`), cylinder cache, INT 13h transfers, INT 24h, `disk_reset` |
| KFAT.INC | paths, directory search/create (root prefetch, same-sector shortcut, `dir_lim`), MKDIR/RMDIR/CHDIR/RENAME/attributes |
| KFILE.INC | SFT + per-process handles, files and devices, read (read-ahead hints) / write (runs) / seek, find first/next |
| KPROC.INC | PSP, environment, EXEC (.COM/.EXE), terminate, TSR |
| KGPIB.INC | GRIDGPIB's resident code built in (INT 60h), plus the fast path |
| EXEC.INC + EXECRUN.INC | the Executive, and the screen saver |
| LCMD.ASM | LCMD.COM, the shell |
| DEFRAG.ASM | DEFRAG.COM (see `lodestone-defrag.md`) |

The old `src\COMMAND.ASM/.COM` and `releases\0.2\COMMAND.COM` on the PC are obsolete and can be deleted.

**Size (0.2.2):**
- Image 24,400 bytes.
- BSS: FAT cache 6 KB, 5 sector buffers, Executive list 7.7 KB, stacks. The help save-under lives in the cache.
- Resident: about 48 KB kernel + 18 KB cache, leaving **570 KB for programs** in emulation. TM5000G needs about 450 KB.

## Design
- **One INT 21h entry.** The caller's registers are copied into a frame on the kernel stack; nested calls (from an INT 24h handler) get a second stack. Every function exits through ok / done / fail / ok_ax / ret_al.
  - The version reported is 3.30.
  - Functions 00–0E, 19, 1A, 25, 29–31, 33–3F, 40–4F, 50–52, 54, 56–5C, 62, 66–68, and Lodestone's own F0h. FCB file calls return FFh.
- **Hot code on even offsets.** On the 286 a taken jump to an odd address costs more prefetch. Pad bytes (`times ($ - $$) & 1 db 90h`, each after a JMP or RET, never executed) keep the most-entered labels even: INT 21h's entry, dispatch and exits, console output, read/write, the FAT and buffer paths, the directory scan and GPIB's ticks. `os/bench/hot.py` counts taken entries over a few workloads and `plan.py` picks the pad sites; LODE.ASM's `EVEN` list stops the build if a listed label goes odd. The 2026-10-26 audit's kernel batch took taken entries landing odd from 51-54 % to 27-32 %. The resident UI has its own pads and `EVEN` list (section ui; `SECTION=ui` for plan.py and evalpar.py, and hot.py's UI workloads: idle, list, menu, form, drag, Write, Calc, System, a terminal window): its UI batch took them from 43.6 % to 30.3 %. The UI image is copied to a paragraph, so an offset's parity is the address's there too. The same holds for CLAUDE.COM, its /R stub and RCON (`SECTION=claude|rstub|rcon`; the link's workloads), LCMD.COM (`SECTION=lcmd`: the prompt, batch files, PATH, pipes, the task commands; 47-51 % → 29-33 %) and each .RUN (`SECTION=app APP=NAME`, with `mkrun.py -l` for the listing; Write's typing 61 % → 26 %, TERM's drawing 53 % → 16 %): each has its pads and an `EVEN` list.
- **Memory.** A standard MCB arena from just above the kernel; the last block is the cache (owner 8). First fit, with free neighbours merged (48h/49h/4Ah).
- **Disks.**
  - Drives come from INT 11h; each disk is mounted from its BPB (512-byte sectors, FAT12).
  - The whole FAT is cached for one drive at a time. Only the changed sectors are written back, on flush, close, terminate and rename.
  - There are 5 write-through sector buffers: 4 for directory and system sectors (LRU) and 1 for file data. The cylinder cache (above) sits behind them.
  - Reads and writes go straight to the program's memory where they can, in runs across touching clusters. Transfers are split at track ends and 64 KB DMA boundaries. Reads that straddle a boundary go through the cache, writes through a bounce buffer.
  - 3 retries, then INT 24h (Abort / Retry / Fail).
- **Disk changes.**
  - The change line (INT 13h 16h) is checked on every path call, and on every handle call on a floppy file. After INT 21h 0Dh the next access checks regardless (D_CHK).
  - On a "changed" report the kernel drops cached sectors, then compares the boot sector's BPB (0Bh–3Dh, which includes the serial number), the first FAT sector and the root's first sector with what it has (so a disk changed on another machine is another disk, even with its FAT's first sector as it was; MS-DOS 3.30 looks only at the label).
  - A program that writes a floppy's boot sector or root's first sector itself, through INT 13h, tells the kernel with INT 21h F008h (DL = the drive, 0 = A:; CX = the sector, 0 for the boot sector; ES:BX = 1,024 bytes: the sector as the program read it, then as it wrote it). The program's part is to have checked, between its read and its write, that the disk was the one it read. The kernel's part: what was read must be what the kernel knows its disk by (the BPB kept, the root's first sector's sum), and a boot sector may change only in its label; then the kernel knows the disk by what was written, so the disk stays the same disk with files open on it, and a disk swapped in before or after is another disk at the next look. Otherwise it refuses (CF, 5) and takes nothing. It reads nothing from the disk itself, drops its sectors of that disk, and, taken or not, has the drive looked at at its next access (the program's own INT 13h read may have cleared the change line). With nothing open on the floppy and nothing to go, the kernel just forgets the disk, and the next access mounts whatever is in the drive. A boot sector's label alone never makes another disk (the root's label, in its sectors, does), so the same disk labelled elsewhere, or a label taken from another disk with the same BPB, doesn't lock the kernel's own disk out. LABEL does this after each write (its output can go to a file on the disk it labels), and says so if it is refused. A program that doesn't, with a file open on that floppy, finds the disk taken for another after 0Dh ("Invalid disk change"), where MS-DOS, its change line not set, would read on. A root write that fails or is answered Ignore leaves the disk with the old sector or the new one, so the kernel takes either as that disk's (and the disk with neither is another), until a look, or the kernel's own read of that sector, finds which. At a file's close its entry is written only into a slot that still holds the file's name: one whose write was Ignored and never reached the disk, unused or another file's since, is left alone (no nameless entry, no other file's entry overwritten; the chain is lost clusters).
  - A floppy's changed FAT is written from another drive's call (that drive's FAT loaded in its place) or at a program's end only after its own drive is looked at, as INT 21h 0Dh does: another disk there is "Invalid disk change", Retry looks again, and Fail drops the changes (its files with changes pending are refused) while the call goes on. A look that can't read the disk asks as a write does ("Not ready writing drive B", the FAT's, as MS-DOS's dirty buffer would), Retry looks again, and the user's Fail gives the changes up, as MS-DOS does with a buffer whose write fails: the call goes on. A drive without a change line that was used less than 2 seconds before isn't looked at, by the 2-second rule.
  - A Fail nobody was asked for drops nothing. Lodestone's own handlers answer some critical errors without asking: the Executive fails every code but 0Fh (and 0Fh too while a text task is in front of it, where it can't ask), a task's error behind a graphics screen is failed at once, a screen capture fails what it meets, LCMD fails without a prompt while it works for itself (Tab looking for names, the rest of a command after one Fail, the saver's look for DEFRAG), the utilities (CHKDSK, DISKCOPY, DISKCOMP, FORMAT, SYS, DEFRAG, LABEL, XCOPY), CLAUDE.COM and its resident part fail DOS's errors in their own work, and the kernel's own default handler (a program run from the Executive with none of its own, and the EXEC of Shift-CODE-P's prompt) fails everything. They answer 83h, which the kernel takes as Fail but remembers (those that also run under MS-DOS, DEFRAG, XCOPY and CLAUDE.COM, answer 83h only when INT 21h F000h says Lodestone, 3 elsewhere); the kernel's default answers an ordinary 3 and marks it in a byte of the kernel's, so a program's handler that chains to it sees what MS-DOS's would give. Then a floppy's changed FAT is kept and the call fails (the drive is looked at again at its next access; a path call answers 3), INT 21h 0Dh keeps it changed too, and "Invalid disk change" leaves the old disk mounted with its changes, the call failing, so the question comes back when someone can answer it. A program's own handler, or LCMD's when it asks, is the user's, and so is its Fail. While a floppy's changes are kept so, the other floppy's FAT can't come in: its calls fail until the disk is back (or someone answers Fail; a handle call answers 5, a path call 3); C: goes on (its FAT has its own cache). The Executive asks about it ("Put the disk back in drive B:", as for 0Fh): RETURN tries again, ESC is the user's Fail and gives the changes up (keys typed before it asks, or typed with another key, are let go, as COMMAND's 0C01h does, so an ESC typed ahead never answers it); before it runs a program it asks for the program's attributes (43h: the program's drive's FAT wanted, whichever drive, R: and M: too), so the question comes then, with its handler in, rather than the program's load failing for nobody. A handler that calls the kernel's default first and then asks its user has that user's Fail taken for nobody's: putting the disk back, or Abort at "Invalid disk change", still settles it. The exception is "Invalid disk change" for a transfer the BIOS fails with 06h (an AT BIOS's change line under a transfer): its Fail unmounts the disk whoever answered, since the rest of the call's transfers must not reach the disk in.
  - A program that never retries a failed close (or answers Abort) can leave a file's chain longer than its directory entry says: the FAT changes go out once the disk is back, the entry never written. CHKDSK /F cuts the chain to the size and keeps the rest as FILE0000.CHK.
  - Same disk: it keeps its mount, but its current directory is unknown all the same (the disk may have changed elsewhere: MS-DOS's "don't know"), and so is every other task's on that floppy. Different disk: it remounts, and the current directory is unknown (MS-DOS's -1). An unknown current directory is found again by its name, else the root, at the next path call, absolute or relative, and at 47h, as MS-DOS's ValidateCDS does; handle calls (such as a changed file's close) never read it. If the disk can't be read then (its FAT or a directory on the way, or another floppy's changed FAT that can't go out first), the name is kept and the directory stays unknown: a relative path answers 3, an absolute one goes on, so the disk's other files can still be copied off, and CD to one settles it. RMDIR with the current directory still unknown answers 3; of the current directory itself, 16, as MS-DOS. A directory entry whose cluster is FFFFh (broken; FAT16's end mark) is never a current directory: CD to it answers 3. A directory whose first cluster the disk can't have (1, FFFFh, past its end) is never read or written: a path through it answers 3. The current directory is never taken for the root because a read failed. A search (4Fh) on a drive with a look due (after another disk was failed without anyone asked, or 0Dh) looks at the drive first, so it never reads another disk's sectors as the old one's. With no FAT sector to compare (after 0Dh with nothing open on the disk), the current directory is found again by name too. With a file open, 0Dh keeps the FAT sector to compare, so another disk with the same boot sector is not taken for it.
  - With files open or changes to go on the old disk, another disk is INT 24h 0Fh, "Invalid disk change" (Retry, Fail), as MS-DOS 3.30 asks. A changed file's last close counts as open until its entry is written, so a disk swapped before it is asked about too, and Retry with the disk back writes it.
  - After a Fail there, the old disk's changes still in the cache are dropped and its files with changes pending are refused. If the old disk is put back before another disk is mounted, and its first FAT sector compares the same (the boot sector alone can't tell two disks MS-DOS formatted, or copied, apart), it keeps its mount, and its other files read and write on, as in MS-DOS. Once another disk has been mounted, the old disk's files are refused (5). A read that fails while the disk is looked at (an empty drive) is INT 24h's for that read; Retry looks again. After the Fail, handle calls answer 5 and path calls 3: the path calls' 3 is GRiD MS-DOS 3.30's, measured; the handle calls' 5, their documented code, is assumed. 59h gives the same code (MS-DOS's probably 83).
  - A transfer the BIOS fails with 06h (the disk changed under it, read-ahead's too) is not tried again on whatever disk is in: the same disk goes on with it, another is INT 24h 0Fh there and then. That is asked even with nothing open: the rest of the call would read the old disk's chains and directories on the new one.
  - Drives without a change line (INT 13h 15h: 1) are usable: the BIOS reports "changed" every time. Path calls look at the disk each time; handle calls only when the drive has been unused for about 2 seconds, as MS-DOS's rule (the BIOS's whole tick count, so an hour later is not "2 seconds"). A drive whose 16h says "not changed" has a change line whatever 15h said, and is treated as one. The 1520's drives have a change line (DEFRAG, which needs one, runs on them).
  - Under multitasking each task's current directories go with the floppy's mount they were found on: after another mount they are found again by name.
- **Handles and devices.**
  - 24 SFT entries and 20 handles per process, inherited on EXEC; dup, force-dup and IOCTL 4400h.
  - Devices: CON, NUL, AUX/COM1, COM2, PRN/LPT1 and GPIBnn. The GPIB device is a file handle too.
- **Processes.**
  - EXEC builds the PSP and an environment copy with the program name. A .COM gets up to 64 KB; an .EXE is relocated in 64-entry chunks.
  - Terminate restores INT 22h–24h, closes files, frees memory and returns into the parent's EXEC call; the DTA goes back to the parent's PSP:80h.
  - TSR (31h) keeps its files open.
  - ^C runs INT 23h on the caller's stack: IRET restarts the call, RETF with CF ends the program.
- **Built-in GPIB (INT 60h).**
  - The GRIDGPIB 1.1 API, reporting version 1.23. It installs only if a 7210 answers at the GRiD's GPIB ports.
  - SRQ on IRQ 5 (1.21, the GPIB cartridge's E1 jumper). The 7210 interrupts on SRQ only (IMR2 SRQI). The handler ORs ISR2 into the shadow AH=0Bh reads, and adds 1 to a count.
    - AH=0Eh: AL = 0 off, 1 on, anything else just asks. It returns AX = the IRQ in use (5, or 0) and DX:CX = the count. A client reads the count with interrupts off before a HLT, so it can't sleep through an SRQ.
    - On by default. `GPIBIRQ=0` in LODE.INI turns it off at start-up (KSPLASH.INC's `gi_boot`). 32 interrupts in one tick (no jumper, a floating line) turn it off by themselves.
    - The handler checks the PIC's in-service register first: in real mode the 286 also raises INT 0Dh for a word at offset FFFFh, and that goes on to the old vector.
    - On the 1520 (tools/GPIBIRQ.COM): one IRQ 5 an SRQ, as fast as polling, and it wakes a HLT. SRQI latches on SRQ's edge and clears on read, so a held SRQ doesn't interrupt again.
  - Fast path: a tight ISR1 polling loop for the bulk of each transfer. The careful per-byte code still handles EOI, RFD holdoff and timeouts.
    - 1.22, from tools/GPIBLOOP.COM on the 1520 (1.0-1.6, 4 KB echoes through the Pico 2 bridge): reading 70 → 152 KB/s, writing 77 → 112. Both loops are CPU-bound (the bus keeps up), and a taken jump costs about 0.6 µs, so a byte that is ready costs one, LOOP's.
    - Read: the count in CX (all but the last two bytes of room), END from the chip (LF too, with REOS) instead of a compare per byte, the wait out of line. A read's first poll doesn't miss.
    - Write: the next byte fetched while the bus handshakes, so DO → OUT is three instructions; a miss costs one taken jump, back to a count just above the poll. Each miss ORs its ISR1 read into the shadow, since ERR clears as it is read; every 64 misses it looks for ERR (no listener), and 256 such waits go to the careful loop.
    - `gp_done_n` is settled from SI/DI at the end (an INC in memory per byte cost 1.6 µs of a 12.6 µs write byte). Pad bytes keep the jump targets at their measured parity. 48 bytes more than 1.21.
    - Tried and dropped: AUXRB's TRI (no change: T1 isn't the limit), LOOPZ polls (slower), END tested on the same read as DI (its first poll came too early and missed), the unbounded write poll (119 KB/s, but it would hang on a listener that stops).
  - **The frame check (1.23).** The driver keeps a Fletcher-16 (mod 256: A = 1 + the bytes, B = the sum of the A's) as it moves the bytes, two ADDs a byte in the fast loops. CLAUDEP.COM's profile on the 1520 had CLAUDE's own pass over each 2 KB frame at ~2.65 ms (1.3 µs a byte), more than half of the GRiD's 5 ms between frames.
    - **03h with AL = 2:** a binary read that returns BX = the check of every byte read (BL = A, BH = B; A = 1, B = 0 to start).
    - **02h with AL = 3:** after the data, the check of all but the first byte (GLP's 47h) as two more bytes, A then B, EOI with B. CX counts them.
    - Other AL values are as before (bit 0: EOI, or stop at LF). CLAUDE uses these with 1.23 and up, once the Pi has agreed to the Fletcher sum: a lone frame is checked from BX in a dozen instructions (`ks_check`), anything else by the scan as before; its frames go out for the driver to finish. The bytes on the wire are the same.
    - It costs the fast loops ~0.3 µs a byte (reads ~5 % slower for other programs) and 144 bytes resident.
  - Measured in emulation:
    - GGTEST ID? 6.9 → 4.2 ms;
    - Claude, 22.8 KB each way: 8.0 → 6.8 s at 115,200 baud, and 5.4 → 2.9 s with a 2 Mbaud bridge.
- **The Executive** (the root process) uses INT 21h like any program.
  - After a program it re-lists the disk, keeps the selection and shows "NAME ended[, exit code n]".
  - Keys: CODE-A Claude, CODE-C command prompt, F5 re-read after a disk swap.
  - The screen saver after 5 minutes idle (0.2.2).
- **LCMD.COM** (the shell):
  - Built-ins: DIR, TYPE, COPY, DEL, REN, MD, RD, CD, CLS, ECHO, VER, VOL, SET, PATH, PROMPT, DATE, TIME, PAUSE, REM and EXIT.
  - Programs through PATH, batch files, redirection and pipes.
  - `/C line` and `/P`.
  - Its own INT 24h handler.

## Tests (all in emulation; `os\tests`)
- **pcemu.py** — a BIOS-only PC that boots the real floppy image through the real boot sector.
  - It has INT 13h controller limits, a timer IRQ, mode 40h and the 7210 bus model.
  - It can write-protect a disk, swap disks, have no change line, and have unreadable sectors (`Floppy.bad`).
  - The real-drive timing model is optional (`disk_model='real'`), and CMOS comes from `CMOS128.BIN`.
  - ktest's `run_answering` presses Enter at "Press any key".
- **tests\test_kernel.py — 59 checks, all pass:**
  - TESTDOS (24 API tests);
  - a FAT/CHKDSK-style check after each run;
  - TM5000G with the built-in GPIB;
  - 31 shell checks;
  - write-protect, disk swaps and a no-change-line drive.
  - **cache (10 checks):**
    - CACHETST with every byte checked, and its CACHETST.TXT log;
    - the help window borrows the cache and gives it back, with the screen restored;
    - TYPE goes through the cache;
    - after a swap to a floppy laid out the same, its own file is read (with and without a change line);
    - a well-used root (120 old entries): a second DIR makes 0 disk reads, and new and deleted files show up correctly;
    - BENCH twice on a short root, restarting in between: the second run's directory test makes no disk calls (it fails on a kernel without the data buffer);
    - a bad sector part way through a file: the read-ahead gives up once and the file reads up to it, then the usual Data error.
- **tests\test_defrag.py — 33 checks**, and **tests\defrag_cut.py** (a power cut at every DEFRAG write, also on a simulated worn drive) — see `lodestone-defrag.md`.
- **CACHETST.COM** (`tests\`) does random reads, read runs, granule writes into cached areas, and reopens, across two interleaved (fragmented) files.
  - It caught a deliberately broken kernel (no invalidation on write) with 3 errors.
  - It passes on 1.44 MB, 720 KB, 1.2 MB and 360 KB disks, under GRiD MS-DOS, and on the real 1520.
- **tests\test_claude_kernel.py — 21 of 21 pass.** These are the Claude-link scenarios with CLAUDE.COM on the real kernel and shell.
- **tests\ggtest_kernel.py** — GGTEST on the kernel. Its results match GRIDGPIB's.
- Independent reviews: the kernel (10 issues, all fixed), the 0.2.1 cache (above), and DEFRAG with the saver (`lodestone-defrag.md`).

## Known gaps (later versions)
- No INT 33h mouse for DOS programs yet; TM5000G runs keyboard-only.
- No INT 67h EMS, INT 25h/26h or FCB file calls. EXEC modes 01/03 are not supported.
- Handle I/O doesn't check for a disk change: don't swap floppies with a file open. With the cache, a whole cylinder of the old disk could be served.
- Programs that write sectors with INT 13h directly bypass the cache. Formatters and disk editors are examples. DEFRAG does too, but it calls 0Dh before and after. Press F5 afterwards, or use GRiD MS-DOS for them.
- Subdirectories (Subjects) aren't prefetched like the root, and don't get the same-sector shortcut.
- A root longer than 63 entries is read in one pass (~0.3 s) when its sectors aren't in the buffers. DEFRAG removes the dead entries our copies leave.
- On real hardware, writes are ~3 s per 256 KB above the emulator. The fresh-floppy run showed this is drive timing (the request-start gap), not layout. Not yet investigated.
- A new file takes the first free clusters from the front of the disk, so a hole left by a replaced file (e.g. each LODE.SYS copy from Windows) fragments the next big file. DEFRAG fixes that afterwards.
- The Executive stays resident while programs run (not swapped to EMS). The cache could later move to EMS pages to give the 18 KB back.
- The Executive returns straight away after a program, so TESTDOS output can't be read. A "Press any key" in the Executive is an option.
- The 1520's floppy drive may be weak on side 0 at the inner cylinders (DEFRAG's findings). Clean the heads and compare with another floppy.

## On the 1520 (checklist)
1. Restart and tap **F** as the memory count finishes. The Executive should say **"Lodestone 0.2.2"**.
2. Run **TESTDOS** (24 passed, 0 failed) and **CACHETST** (0 errors; a few minutes). Done for 0.2.1 on 2026-10-05: 0 errors.
3. Run **BENCH** from the Executive; it adds its results to `BENCH.TXT`. Under GRiD MS-DOS, restart without F, type `B:` (the floppy under the EPROM boot) and then `BENCH`. Done 2026-10-05: MS-DOS once, Lodestone seven times (best 82.39 s; run 7 directory 0.05 s).
4. **0.2.2:** done 2026-10-05. The saver ran DEFRAG, DEFRAG finished on the worn floppy, and BENCH showed the directory listing at 0.05 s.
   - **Next:** the same floppy in the external **B:** drive (1.44 MB): `B:DEFRAG B: /T`, then `DEFRAG /T` back in A:, and compare the "disk errors" counts. That tells a weak drive head from a worn disk. Then clean A:'s heads.
   - Optional: run DISKMAP once more, so the emulator can reproduce run 7's small-file time exactly.
5. **CODE-C** → `DIR`, `VER`, `TYPE LODE.TXT`, `EXIT`; then **TM5000G** and **CODE-A** as before.
6. Rollback if needed: copy `os\releases\0.2.1\LODE.SYS` (or `0.2`, `0.1`) to A:, and delete DEFRAG.COM (with no DEFRAG.COM, the saver only shows the clock).
