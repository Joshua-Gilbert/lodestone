# Lodestone

A fast DOS 3.30-compatible OS for the GRiDCase 1520 (80C286, 640×400 gas-plasma display, 1.44 MB floppy; Joshua's also has an 80287 and 1408 KB of EMS). It has a GRiD-style Executive, a disk cache, a built-in GPIB driver, its own EMS manager, the internal hard disk as drive C:, a RAM disk in EMS as M:, and a screen saver that defragments every disk. Programs of its own (System, Write and the calculator) run on a shared UI core.

> **Name:** Lodestone was called Grid-OS up to 0.4.0. Since 0.4.1 the kernel is `LODE.SYS` (settings in `LODE.INI`), the shell `LCMD.COM` and the boot installer `LODEBOOT.COM`; they were `GRIDOS.SYS`, `GRIDOS.INI`, `GRIDCMD.COM` and `GOSBOOT.COM`. The release notes in `os/releases/` up to 0.4.0 keep the old names.

It boots from a floppy, shows the Executive, runs ordinary DOS programs (TM5000G, CLAUDE.COM, …) and comes back. On the real 1520 it runs the BENCH file-system benchmark in **87 s against GRiD MS-DOS's 289 s**, more than 3× faster (83 s with 0.2.3).

| | |
|---|---|
| ![The start-up picture](os/screens/readme/splash.png) | ![System, Display](os/screens/readme/system_display.png) |
| The start-up picture: Fig. 1 of Annett's *Electrical Machinery* (1921), the stone and 235 nails drawn from vectors (`LODE.PIC`) | System, Display: the font, and the start-up picture (Space turns it off) |
| ![The Executive](os/screens/readme/executive.png) | ![Copy with a wildcard](os/screens/readme/copy_wildcards.png) |
| The Executive: GRiD's File form (Device, Subject, Title), the 1520's EMS and serial mouse in the status line | Copy, Move and Delete take wildcards, with Replace and Only newer |
| ![System, Memory](os/screens/readme/system_memory.png) | ![System, Disks](os/screens/readme/system_disks.png) |
| System: where the 640 KB goes, and the EMS | System: the floppy, the internal hard disk as C: (the 1520's own 121 MB Conner layout) and M:, the RAM disk |
| ![Write](os/screens/readme/write.png) | ![BENCH](os/screens/readme/bench.png) |
| Write, a GRiDWrite-style editor | BENCH 1.4 on Lodestone with EMS |
| ![The calculator](os/screens/readme/calculator.png) | ![CALC at the prompt](os/screens/readme/calc_prompt.png) |
| The calculator over the Executive (CODE-K); the coprocessor lit in the info line (the emulator's is 387-class, so it reads as a 287XL) | `CALC` at the command prompt: sums, errors with ERRORLEVEL, `name=` for batch files |

*Emulator screenshots (`os/screens/readme_shots.py`), drawn as the 1520's amber plasma shows them.*

## What it does (0.4.4)

- **A DOS 3.30 kernel** (`LODE.SYS`, 45,930 bytes): INT 21h for the programs of its day, COM and EXE loading, TSRs, INT 24h, INT 25h/26h, FAT12 and FAT16.
- **Disks:**
  - **A:** and **B:** (the external floppy drive), with a cylinder read-ahead cache;
  - **C:**, any IDE drive with a FAT16 partition up to 2 GB, driven through its own registers. The 1520's BIOS only knows a few Conner models, so Lodestone doesn't use it for this. With a drive, C: costs about 3 KB of memory; without one, nothing is loaded.
  - **M:**, the temporary disk: a RAM disk in EMS, 256 KB unless System's Temporary disk topic or `MDISK=` in `LODE.INI` says otherwise (Off up to all the free EMS). It costs DOS programs no memory: its 0.3 KB comes out of the environment's block, which programs never got. Its files are lost at power-off.
- **EMS:** Lodestone is its own LIM 4.0 EMS manager when the 1520's memory is set to EMS. The disk cache moves into two EMS pages, so DOS programs get 16 KB more.
- **GPIB:** the GRIDGPIB API on INT 60h is built in, with a faster block transfer. TM5000G and CLAUDE.COM run unchanged.
- **The Executive:** GRiD's File form, with CODE-C Copy, CODE-M Move, CODE-R Rename and CODE-D Delete. They take wildcards, Replace and Only newer, and work on whole subjects (directories) too. CODE-P opens the command prompt, CODE-U opens System, CODE-K the calculator, CODE-A starts Claude. The info line lights up the coprocessor, 80287 or 80287XL, when one is fitted.
- **The command prompt** (`LCMD.COM`): DOS 3.30's commands, redirection and pipes, plus `&&` and `||` between commands. The line can be edited, with a history (Up, Down, F3) and Tab completion of file names, and the screen saver runs there too. Batch files have IF (EXIST, ERRORLEVEL, ==, NOT), GOTO, FOR, CALL, SHIFT, CHOICE and `%NAME%` variables; an error in one names the file and line. Built-in commands that can fail set ERRORLEVEL, so scripts (Claude's too) can check every step.
- **System:** memory, disks, clock, devices (the hard disk's own name), GPIB, display (fonts), screen saver, temporary disk. Settings are kept in `LODE.INI`.
- **Write:** a GRiDWrite-style text editor.
- **The calculator,** on the 80287:
  - **In the Executive** (CODE-K, `CALC.RUN`): a window over the file list. Type a sum and press Return, or click its keys; F2 switches to degrees.
  - **At the prompt** (`CALC.COM`): `CALC 4*4`, `CALC /D sin(30)`. `CALC N=N+1` also sets `%N%` for a batch file. Errors set ERRORLEVEL; `CALC /?` says how to use it.
  - **Functions:** `+ - * / ^ \ %`, sqrt, sin, cos, tan, atan, ln, log, exp, abs, pi, the last answer; 15 digits.
  - **Coprocessors:** an 80287 does it in its 80-bit numbers. A 287XL also does sin, cos and tan itself, faster and exact for big angles. Without one, whole numbers.
  - **Cost:** the two programs cost nothing until they run; CODE-K and the lamp cost DOS programs 0.2 KB.
- **The screen saver** runs `DEFRAG` on A:, B: and C: in turn, then darkens the screen. A key stops it. Its delay and the tidying are settings.
- **DEFRAG.COM:** defragments a floppy or C:, with a map of the disk. `/T` tests the free space instead: it writes a pattern into every free sector, reads it back, and marks the clusters that fail. A power cut during any of its writes leaves the old file or the new one, never a damaged one (tested at every write, on a floppy and on C:).
- **A start-up picture:** `LODE.PIC` (2.5 KB) draws Fig. 1 of F. A. Annett's *Electrical Machinery* (1921), "Lodestone attracting some iron nails" (public domain), from vectors (in 0.25 s in the emulator): the stone as an outline filled row by row, 235 nails at 4 bytes each, LODESTONE beside it. It stays 2 seconds or until a key. A bootstrap in the kernel's start-up code (never resident) reads it into free memory, calls it and lets the memory go, so DOS programs get the same as without it. `SPLASH=0` in `LODE.INI` (System, Display, Space) or no `LODE.PIC` on the disk: no picture.
- **Screen capture:** Shift-PrtSc saves the screen to `SCREENnn.BMP` (graphics) or `SCREENnn.TXT` (text) on the boot disk.
- **An INT 33h mouse** for DOS programs: a serial mouse on COM1 or COM2.
- **Claude for GRiD** (`os/claude`, `claude-link`): Claude on the GRiD through a Raspberry Pi on the GPIB bus. It can read and edit files, run DOS programs and talk to instruments, each step confirmed on the GRiD. Two ways:
  - **Term** (`CLAUDE /T`, 0.4.0): the GRiD is the screen and keyboard of the real Claude Code, running on a Pi 5 on your own Claude plan. Only the screen cells that change cross the link. The GRiD's files, programs, screen and GPIB bus are Claude Code tools through an MCP server on the Pi.
  - **Chat** (`CLAUDE`): gridlink's own agent on an API key, in Claude Code's style.

  Both are tested in emulation and wait for the bridge hardware.

## Benchmarks: Lodestone, GRiD MS-DOS 3.30 and FreeDOS

BENCH 1.4 on all three in the emulator (rerun 2026-10-08 with 0.3.14), from the same kind of 1.44 MB floppy, with the 1520's real-drive timing (300 rpm, seeks, rotation, motor) and its 1408 KB of EMS. Lodestone runs its own EMS manager; GRiD MS-DOS and FreeDOS load GRiD's `EMM.SYS`. FreeDOS is kernel build 2046 (8086) with FreeCOM 0.87, built from [FDOS](https://github.com/FDOS) sources. Seconds, lower is better.

| Test | Lodestone 0.3.14 | GRiD MS-DOS 3.30 | FreeDOS |
|---|---:|---:|---:|
| Write 256 KB, 16 KB writes | **9.41** | 12.66 | 12.58 |
| Read 256 KB, 16 KB reads | **8.85** | 11.41 | 11.23 |
| Read 256 KB, 512-byte reads | **8.80** | 104.99 | 105.17 |
| Read 256 KB, 128-byte reads | **8.80** | 104.99 | 107.97 |
| 64 random 512-byte reads | **9.32** | 9.93 | 12.91 |
| Directory listing ×10 | **0.03** | 0.07 | 0.14 |
| Open + close ×100 | **0.22** | 0.42 | 0.91 |
| 20 small files, create + delete | 21.44 | 26.12 | **16.71** |
| Load + run a 120 KB .EXE ×3 | **11.98** | 14.68 | 15.29 |
| INT 21h calls ×1000 | **0.11** | 0.12 | 0.26 |
| **File-system total** | **79.0** | 285.4 | 283.2 |
| EMS: map a page ×10,000 | **0.43** | 2.87 | 2.87 |
| EMS: move 1 MB to EMS (57h) | **0.36** | 0.51 | 0.51 |
| EMS: move 1 MB from EMS (57h) | **0.36** | 0.51 | 0.51 |
| Memory for programs, no EMS | 562.5 KB | **580.4 KB** | 501.5 KB |
| Memory for programs, with EMS | **578.6 KB** | 573.1 KB | 494.2 KB |

- **Reads:** Lodestone reads ahead a cylinder at a time, so small reads cost almost nothing; GRiD MS-DOS and FreeDOS wait a turn of the disk for each.
- **Small files:** FreeDOS wins this one, with as many writes as Lodestone. Part of it is where its files happen to land: its system files are bigger, which moves BENCH's files to where the FAT sector follows the directory sector. The rest is write order. Lodestone writes the FAT before the directory entry at close, so a power cut can only lose clusters, never cross-link files. That costs a turn of the disk per file here.
- **EMS:** Lodestone's EMS manager maps a page about 7× faster than `EMM.SYS` and moves data about 1.4× faster, in 1.9 KB of memory against 7.3 KB.
- **Memory:** with EMS, Lodestone keeps its 18 KB disk cache in two EMS pages, so a DOS program gets more than under GRiD MS-DOS with `EMM.SYS`, with the same read speeds. Without EMS the cache stays in conventional memory and GRiD MS-DOS leaves 18 KB more. FreeDOS can't load high on a 286, and its shell is large.
- **Since 0.3.8:** the file-system total is unchanged (79.0 s against 79.1 s). Screen capture, the kernel's part of drive C:, the saver's round of the disks and copying subjects cost DOS programs 1.7 KB in all; M: costs them nothing. (The emulator now also charges the EMS page registers' I/O, which moves the EMS rows by 0.01 s for all three.)

### Memory, by configuration

What a DOS program gets when started from the Executive (MEMSZ; System's "Free for programs" shows 0.1 KB more), 0.4.4 in the emulator (the kernel's row as measured in 0.3.14), with M: at its default 256 KB wherever there is EMS:

| | Floppies only | With EMS | With C: | With C: and EMS |
|---|---:|---:|---:|---:|
| Kernel (DOS, GPIB, and EMS / C: when there) | 30.6 KB | 32.5 KB | 33.9 KB | 35.4 KB |
| Executive and UI core | 34.8 KB | 34.5 KB | 34.8 KB | 34.5 KB |
| Temporary disk M: | | 0.3 KB + 256 KB of EMS | | 0.3 KB + 256 KB of EMS |
| Disk cache | 18.0 KB | 32 KB of EMS | 18.0 KB | 32 KB of EMS |
| **Free for programs** | **562.3 KB** | **578.4 KB** | **559.1 KB** | **575.6 KB** |

M:'s 0.3 KB comes out of the environment's block (counted with the Executive otherwise), which programs never got. The rows add up to more than 640 KB because 7.5 KB of the Executive's share is its directory buffer, lent to a DOS program while it runs, so it counts in both rows. From the command prompt (`LCMD.COM` resident) a program gets 16.1 KB less. The Executive otherwise stays resident: Lodestone is meant to become multitasking.

### On the hard disk (C:) and the RAM disk (M:)

**On the real 1520** (2026-10-08, Lodestone 0.3.14): BENCH 1.4 from the 1.44 MB floppy, from the 121 MB Conner CP30104H as C:, and from M: at 1 MB. Seconds. BENCH times with the BIOS clock, so anything under about 0.2 s is only good to a tick (55 ms).

| Test | Floppy A: | Hard disk C: | RAM disk M: |
|---|---:|---:|---:|
| Write 256 KB, 16 KB writes | 12.52 | 0.87 | **0.16** |
| Read 256 KB, 16 KB reads | 9.44 | 0.43 | **0.10** |
| Read 256 KB, 512-byte reads | 9.61 | 0.71 | **0.27** |
| Read 256 KB, 128-byte reads | 9.83 | 1.42 | **0.93** |
| 64 random 512-byte reads | 10.27 | 1.09 | **0.16** |
| Directory listing ×10 | 0.38 | 0.10 | **0.00** |
| Open + close ×100 | 0.10 | 0.16 | **0.10** |
| 20 small files, create + delete | 22.63 | 3.57 | **0.10** |
| Load + run a 120 KB .EXE ×3 | 12.74 | 0.65 | **0.16** |
| INT 21h calls ×1000 | 0.05 | 0.05 | 0.05 |
| **Total** | **87.6** | **9.1** | **2.1** |

- **C: is about 10× faster than the floppy, and M: about 42×.** Writing 256 KB takes 12.5 s on the floppy, 0.87 s on C: and 0.16 s on M:. Twenty small files take 22.6 s, 3.6 s and 0.1 s.
- **The CP30104H reads ahead on its own.** 512-byte reads on C: take 0.71 s, not the 9.4 s a drive without look-ahead would take, so Lodestone's read-ahead doesn't need to cover C:.
- Logs: `os/bench/BENCH_1520_2026-10-08_A.TXT`, `_C.TXT` and `_M.TXT`.

**In the emulator** (`python3 os/bench/run_bench_hd.py`): C: is modelled on the same drive (3,360 rpm, 39 sectors a track, seeks), with and without the drive's own look-ahead. Seconds.

| Test | Floppy A: | C:, drive without look-ahead | C:, drive with look-ahead | M: |
|---|---:|---:|---:|---:|
| Write 256 KB, 16 KB writes | 9.41 | 0.76 | 0.74 | **0.18** |
| Read 256 KB, 16 KB reads | 8.85 | 0.56 | 0.35 | **0.11** |
| Read 256 KB, 512-byte reads | 8.80 | 9.39 | 0.96 | **0.35** |
| Read 256 KB, 128-byte reads | 8.80 | 9.37 | 1.89 | **1.26** |
| 64 random 512-byte reads | 9.32 | 1.02 | 1.03 | **0.31** |
| Directory listing ×10 | 0.03 | 0.02 | 0.02 | **0.01** |
| Open + close ×100 | 0.22 | 0.22 | 0.22 | **0.20** |
| 20 small files, create + delete | 21.44 | 2.71 | 2.71 | **0.18** |
| Load + run a 120 KB .EXE ×3 | 11.98 | 0.85 | 0.53 | **0.16** |
| INT 21h calls ×1000 | 0.11 | 0.11 | 0.11 | 0.11 |
| **Total** | **79.0** | **25.0** | **8.6** | **2.9** |

- **The look-ahead column matches the real drive:** 8.6 s modelled against 9.1 s measured.
- **The emulator overstates the kernel's own work about twice.** The 1,000 INT 21h calls take 0.11 s there and 0.05 s on the 1520, which is why M: is 2.9 s in the emulator and 2.1 s for real. Disk-bound tests are close.
- The model and notes are in `os/bench/RESULTS_HD.TXT`.

### On the real 1520

BENCH on Joshua's GRiDCase 1520, from its own 1.44 MB floppy (seconds). These are the latest runs on the machine. In the emulator, 0.3.14's floppy times are the same as 0.3.8's, so these still stand. The real machine runs a few seconds slower than the emulator; totals also move with where BENCH's files land on a well-used floppy (below).

| Test | GRiD MS-DOS 3.30 | Lodestone 0.2.3, 2026-10-05 | Lodestone 0.3.8, 2026-10-07 | the same, after DEFRAG |
|---|---:|---:|---:|---:|
| Write 256 KB, 16 KB writes | 13.89 | 12.35 | 12.90 | 12.63 |
| Read 256 KB, 16 KB reads | 11.97 | 8.73 | 9.55 | 9.17 |
| Read 256 KB, 512-byte reads | 104.86 | 8.56 | 9.55 | 8.95 |
| Read 256 KB, 128-byte reads | 104.86 | 8.78 | 9.77 | 8.95 |
| 64 random 512-byte reads | 10.49 | 9.61 | 10.05 | 9.72 |
| Directory listing ×10 | 0.21 | 0.05 | 0.54 | 0.05 |
| Open + close ×100 | 0.21 | 0.16 | 0.10 | 0.16 |
| 20 small files, create + delete | 28.45 | 22.30 | 22.13 | 24.88 |
| Load + run a 120 KB .EXE ×3 | 14.06 | 12.02 | 12.08 | 16.47 |
| INT 21h calls ×1000 | 0.10 | 0.05 | 0.05 | 0.05 |
| **Total** | **289.15** | **82.66** | **86.78** | **91.07** |
| Memory for programs (BENCH) | 571 KB | 554 KB | **580 KB** (with EMS) | 580 KB |
| EMS: map a page ×10,000 | | | 0.27 | 0.21 |
| EMS: move 1 MB to / from EMS | | | 0.38 / 0.32 | 0.38 / 0.32 |

- **Memory:** with the disk cache in EMS, a DOS program gets 580 KB on the real machine, 9 KB more than under GRiD MS-DOS (571 KB with its usual drivers), while Lodestone also runs its own EMS manager, the cache and the Executive.
- **EMS on the real 1520:** a page map takes about 21–27 µs, and 57h moves run at 2.7–3.1 MB/s. RAMSPEED measured EMS pages at the full speed of conventional memory (copy 3,074 KB/s).
- **The internal hard disk (a 121 MB Conner CP30104H):**
  - a read of every sector ran at 463 KB/s (HDSCAN);
  - `DEFRAG C:` took about 15 s;
  - `DEFRAG C: /T` tested all 117,577 KB free in about 15 minutes and fenced off the drive's one weak spot (14 clusters).
- **Run to run:** totals move by a few seconds with where BENCH's files land on a well-used floppy. After DEFRAG the free space starts further in, which is slower here: drive A:'s head 0 is marginal on the innermost tracks, so some tracks are read a sector at a time.

Logs: `os/bench/BENCH_1520_*.TXT`, `DEFRAG_1520_2026-10-07_C.TXT`, `EMSTEST_1520_2026-10-07.TXT`, and `rom/HDSCAN_*.TXT`.

Run the comparison with `python3 os/bench/compare3.py <GRiD MS-DOS EPROM image> <EMM.SYS>` (about 4 minutes); results and notes are in `os/bench/RESULTS3.TXT`, newest first. The earlier two-way runs, and the runs on the real 1520, are in `os/bench/RESULTS.TXT`.

## What's here

| Folder | What |
|---|---|
| `os/src` | The OS, in NASM: the boot sector (`BOOT.ASM`), the ROM's boot sector (`ROMBOOT.ASM`), `KROM.INC` (R:, the ROM drive, and booting from the ROM), `LODEBOOT.COM` (installs it), the kernel (`LODE.ASM` + `K*.INC`: `KEMS.INC` the EMS manager, `KHD.INC` the hard disk, `KMDISK.INC` the RAM disk M:, `KGPIB.INC` GPIB, `KSPLASH.INC` the start-up picture's bootstrap), `SPLASH.ASM` (`LODE.PIC`, the picture), the UI core (`UICORE.INC`, its API in `UIAPI.INC`) and the Executive (`EXEC.INC`), the shell `LCMD.COM`, `DEFRAG.COM`, `HEADCLN.COM` (drive head cleaning with a wet cleaning disk), `CALC.COM` (the calculator at the prompt; its engine `CALC.INC`, and `FPU.INC`, which coprocessor) |
| `os/splash` | The start-up picture's source: the 1921 plate, `trace.txt` (the stone's outline and the nails, editable), `trace.py` (how they were traced), `mksplash.py` (packs them into `src/SPLASH.INC` and draws the picture the tests compare the GRiD's screen with, bit for bit) |
| `os/rom` | `LODE.INI`, the settings burned into the ROM; the ROM image itself is `os/LODE1.BIN` (the file to burn is `os/LODE1_EPROM.BIN`), built by `os/build.sh` with `tools/mkrom.py` |
| `os/apps` | Programs on the UI core (`.RUN`, built with `os/mkrun.py`): `SYSTEM.RUN`, `WRITE.RUN` and `CALC.RUN` (the calculator's window) |
| `os/fonts` | `TERMINUS.FNT`, an 8×16 font System can switch to (GRiD's own is built in) |
| `os/tests` | `pcemu`-based tests (the counts are under Tests below), and the DOS programs they run: TESTDOS, CACHETST, CAPTEST, EMSTEST, HDABS, HDFLUSH, MDTEST, MEMSZ, TSR, UPPER, the M33 programs, UITEST.RUN; and for the 1520: CMDTEST.BAT (the batch language), CALCTEST.BAT (the calculator, step by step) and FPUPROBE.COM (what the coprocessor answers after FNINIT) |
| `os/bench` | BENCH.COM, DISKMAP.COM, `run_bench.py` (against GRiD MS-DOS), `compare3.py` (against GRiD MS-DOS and FreeDOS, with EMS; FreeDOS's files in `bench/freedos`), `run_bench_hd.py` (on C: and M:), profiling tools, `RESULTS.TXT`, `RESULTS3.TXT`, `RESULTS_HD.TXT` and the 1520 logs |
| `os/claude` | CLAUDE.COM, Claude for GRiD (the GRiD side of claude-link): chat, and Term (`TERMLINK.INC` the link, `TERMCELL.INC` the screen, `TERMKEYS.INC` the keys); resident Claude: `CLAUDE /R` (an INT 16h stub at the top of memory, its console `RCON.ASM` in EMS: Term's own code, Claude Code in the pop-up) and `CLAUDE /U`, with `M1TEST.BAT` for the 1520; its spikes: `RSPIKE.COM` (a pop-up TSR on CODE-\\, its code in EMS), `EMSUSE`, `GFXUSE`, `KEYCODE` and `SPIKES.BAT`, which runs them on the 1520; and the test programs `T1C`, `BUSY`, `MHAND`, `HOLE`, `HOOK16` and `PAGE1` |
| `os/releases` | Builds for the floppy, 0.1 to 0.4.3 |
| `os/screens` | Emulator screenshots (`readme/` for this page, made by `readme_shots.py`) |
| `os/*.py` | `pcemu.py` (a BIOS-level PC in unicorn: INT 13h with real-drive timing, mode 40h, the 7210 GPIB chip, EMS, an IDE drive with optional seek and rotation timing), `ktest.py`, `mkimg.py`, `mkrun.py`, `psf.py`, `sim7210.py`, `typfont.py` (builds the fonts); `gosim.py` and `test_*.py` are the 0.1 harness |
| `claude-link` | `gridlink` on the Raspberry Pi: GRiD ↔ GPIB (AR488 Nano) ↔ Pi ↔ Claude (Term: the real Claude Code in a pty, with an MCP server for the GRiD's tools; chat: the Claude API), the AR488 patch, and its tests |
| `tools` | 1520 tools: GRIDGPIB (GPIB driver for GRiD MS-DOS), GPIBSCAN, GPIBTEST, GGTEST, GRIDMEM (EMS or extended memory), EMSKEEP (does EMS keep its contents through Ctrl-Alt-Del? On the 1520: no), MEMPROBE, GRIDPROBE, RAMSPEED, ROMDUMP, HDPROBE and HDSCAN (the internal hard disk, read-only: diagnosis, and a read of every sector), the C GPIB library, and TM5000G.EXE (a test fixture; its source lives in the TM5000 repo) |
| `rom` | Our notes on the 1520 BIOS (a symbol map), probe and scan logs, and the hard disk's partition and boot sectors; no ROM images (see below) |
| `docs` | Design notes: the 0.2 kernel, the UI core and programs (0.3, with EMS, screen capture, the hard disk and M:), DEFRAG and the saver, the floppy development loop |

## Build

Needs NASM 2.15+, and Python 3 for the `.RUN` programs (`mkrun.py`).

```sh
os/build.sh        # everything in os/src, apps, tests and bench, and LODE1.BIN (ROM 1)
os/kbuild.sh       # just the kernel, with LODE.MAP / .LST
cd os/claude && ./build.sh
```

The built binaries are committed too, so a fresh clone can go straight onto a floppy.

## Tests (emulator)

Needs Python 3, `unicorn` 2.x and mtools. All 1260 checks pass on 0.6 (2026-10-18); claude-link's own are in `claude-link/tests`.

```sh
cd os
python3 tests/test_rom.py             # 80 checks: 0.6, booting from the ROM: the image, the real BIOS (which socket boots; E400-E404), R:, settings, the menu, PATH, memory
python3 tests/test_kernel.py          # 360 checks: DOS calls, files, EXEC, the cache, EMS, capture, M:, the move from Grid-OS, the command prompt, CALC
python3 tests/test_apps.py            # 401 checks: UI core, Executive, System, Write, mouse, files, the calculator and the coprocessor lamp (add "shots" for screens/0.3)
python3 tests/test_splash.py          # 62 checks: the start-up picture, bit for bit on every start-up path; SPLASH=, LODE.PIC, System's switch, memory
python3 tests/test_hd.py              # 56 checks: drive C:, and C: with M:
python3 tests/test_defrag.py          # 49 checks: DEFRAG on floppies and C:, the saver's round
python3 tests/test_claude_kernel.py   # 21 Claude-link scenarios on the kernel
python3 tests/test_resident.py        # 70 checks: resident Claude, CLAUDE /R and /U (M1), and its spikes (over EMS users, graphics modes, COPY CON, the Executive, TM5000G, a TSR peeking from INT 1Ch, a mouse event handler, a later INT 16h hook)
python3 tests/test_resident_term.py   # 77 checks: resident Claude's console is Claude Code (M2), with gridlink and a stand-in Claude Code, over EMSUSE and TM5000G, a stuck bridge; Claude sees the program and types into it, and drives TM5000G (M3)
python3 tests/test_hdprobe.py         # 33 checks: HDPROBE
python3 tests/test_hdscan.py          # 20 checks: HDSCAN
python3 tests/test_headcln.py         # 9 checks: HEADCLN
python3 tests/defrag_cut.py 2         # a power cut at every DEFRAG write (~20 min; "2 hd" for C:, "2 worn" for a worn drive)
python3 bench/run_bench.py <GRiD MS-DOS EPROM image>
python3 bench/run_bench_hd.py         # BENCH on C: and M:
```

Some tests need files that aren't in this repo: the GRiD MS-DOS EPROM image (`GRID_ROM=…`, or `rom/GRID_MSDOS330_ROM_300909-00.BIN`), and for `test_rom.py`'s real-BIOS checks the 1520's BIOS (`rom/ROM_F000.BIN`, with `rom/CMOS128.BIN`). Without them, those checks are skipped.

## On the GRiD: from the ROM (0.6)

Burn `os/LODE1_EPROM.BIN` (exactly 128 KB; `os/LODE1.BIN` with its halves swapped, as the 1520 inverts A16 to its sockets) to a 27C010 (the 1520's: a TMS27C010A-12) and put it in the **second** socket: the BIOS boots the last bootable ROM it finds. Hold Shift while the 1520 starts for the menu (the ROM's own settings, GRiD MS-DOS from the other socket, the floppy). Settings changed in System go in `C:\LODE.INI` (A: without the hard disk); copies of programs in `C:\LODE` are used before the ROM's. See `docs/lodestone-rom.md`.

## On the GRiD (the floppy loop)

1. Format a 1.44 MB floppy and copy `LODE.SYS`, `LODE.PIC` (the start-up picture; leave it off for none), `LCMD.COM`, `DEFRAG.COM`, `SYSTEM.RUN`, `WRITE.RUN`, `CALC.RUN`, `CALC.COM` and whatever programs you want.
2. Under GRiD MS-DOS (EPROM boot, where the floppy is B:), run `B:LODEBOOT B` once per format.
3. Restart and tap **F** as the memory count finishes: the 1520 boots the floppy.
4. A new `LODE.SYS` can simply be copied over; the boot sector follows the FAT chain.

Keep `COMMAND.COM`, `CONFIG.SYS` and `AUTOEXEC.BAT` off this floppy unless they're meant for GRiD MS-DOS: booted from the EPROM with the floppy in, GRiD MS-DOS uses them from the floppy. See `docs/lodestone-floppy-dev.md`.

## Not in this repo

These aren't ours to publish, even privately: the 1520 BIOS and GRiD MS-DOS ROM dumps, the GRiD MS-DOS disks and utilities, the vendor GPIB driver package (Driver488), and the floppy backups. They stay on the development PC. `.gitignore` keeps ROM images and disk images out.

## Status

Lodestone 0.6 is the current release: it boots from an EPROM, with R: the ROM drive, the ROM's settings with your changes over them, and a boot menu (`docs/lodestone-rom.md`; in the emulator and against the 1520's real BIOS, not yet burned). Before it, 0.4.5: 0.4.1 was the rename, 0.4.2 brings the command prompt's batch language, line editing and screen saver, 0.4.3 the start-up picture, 0.4.4 the calculator and the coprocessor lamp, and 0.4.5 finds a real 80287 (0.4.4 took the condition codes its FNINIT leaves behind for an empty socket). The calculator passes on the 1520 with its 80287 (`bench/CALCTEST_1520_2026-10-13.TXT`): every exact answer, the rest to the last of 15 digits but for `sin(1e6)` (1.5e−14 out, as designed), the lamp and the window. 0.4.1 boots on the 1520; 0.3.15 is the last release fully tested there, where it boots, runs TESTDOS, TM5000G and CLAUDE.COM, uses the internal hard disk as C:, and the screen saver tidies every disk. 0.3.14 added M:, the RAM disk: Claude's future scratchpad, and fast scratch space now; on the 1520 it runs BENCH in 2.1 s against the floppy's 87.6 s. M:'s files don't survive a restart on the 1520: EMSKEEP showed that its BIOS rewrites EMS at Ctrl-Alt-Del, so copy anything worth keeping to A: or C:. 0.3.15 makes sure an old M: never comes back. 0.4.0 adds Term: the real Claude Code on the GRiD's screen, on your Claude plan, tested in the emulator and waiting for the Pi 5. See `docs/lodestone-0.3-apps.md` for 0.3 release by release, and `docs/term.md` for Term.

**Next:**
1. Claude (Term and chat) on the real GPIB bridge, with the Pi 5.
2. Claude staying resident, working alongside DOS programs, with M: as its scratchpad: a hot key over a running program, Term's screen and link code in EMS (`docs/lodestone-resident-claude.md`). The spikes are done: on the 1520, CODE-\\ flips at once between a program and a pop-up whose code runs from EMS, with the program's EMS pages, its screen in modes 4, 6 and 40h, and TM5000G's GPIB work all left as they were. M1 and M2 are done in the emulator: `CLAUDE /R` makes Claude resident for 0.8 KB of conventional memory (a stub at the top of memory, so the Executive's block is never in its way) and 3 EMS pages, CODE-\\ brings up Claude Code over a program (the same session as `CLAUDE /T`) and back, and `CLAUDE /U` takes it out. M1's checks passed on the 1520 (2026-10-14); the one odd answer, mode 6, was the test program's colour (black on the 1520's panel) and a flash of white as the console went back, both now fixed, and mode 6 checked again on the 1520. M3 is done in the emulator: Claude sees the program it is popped up over and types into it (it drives TM5000G), the console coming back with the program's screen after the keys. Next: files and instruments while a program is paused, then Claude working between keys (M4).
3. Command.

Later come a plot view and instrument programs for the GPIB bench (scopes, the VNA), which can use the coprocessor detection and the calculator's 80287 code. The roadmap and the hardware notes are in the claude.ai Project.
