# Lodestone

A fast DOS 3.30-compatible OS for the GRiDCase 1520 (80C286, 640×400 gas-plasma display, 1.44 MB floppy). It has its own Executive, a disk cache, a built-in GPIB driver, a screen saver that defragments the floppy, and (from 0.3) a shared UI core with programs of its own: System and Write.

> **Name:** Lodestone is the working name. The code, the files on the floppy and the screen still say **Grid-OS** (`GRIDOS.SYS`, "Grid-OS 0.3"). Renaming those is a separate step.

It boots from a floppy, shows a GRiD-style Executive, runs ordinary DOS programs (TM5000G, CLAUDE.COM, …) and comes back. On the real 1520 it runs the BENCH file-system benchmark in **83 s against GRiD MS-DOS's 289 s**, and it's ahead on all ten tests.

## What's here

| Folder | What |
|---|---|
| `gridos/src` | The OS, in NASM: boot sector (`BOOT.ASM`), `GOSBOOT.COM` (installs the boot sector), the kernel (`GRIDOS.ASM` + `K*.INC`), the UI core (`UICORE.INC`, its API in `UIAPI.INC`) and the Executive (`EXEC.INC`), the shell `GRIDCMD.COM`, `DEFRAG.COM`, `HEADCLN.COM` (drive head cleaning with a wet cleaning disk) |
| `gridos/apps` | Programs on the UI core (`.RUN`, built with `gridos/mkrun.py`): `SYSTEM.RUN` (Usage: memory, disks, clock, devices, GPIB) and `WRITE.RUN` (a GRiDWrite-style editor) |
| `gridos/tests` | `pcemu`-based tests: kernel (60 checks), the UI core, programs and INT 33h (237), DEFRAG (33) and a power cut at every DEFRAG write, HEADCLN (9), the Claude-link scenarios, GGTEST; also TESTDOS / CACHETST / UPPER / MEMSZ / TSR / M33TEST and the other M33 programs (DOS programs) and UITEST.RUN |
| `gridos/bench` | BENCH.COM, DISKMAP.COM, `run_bench.py` (Lodestone against GRiD MS-DOS in the emulator), profiling tools, `RESULTS.TXT` and the 1520 logs |
| `gridos/claude` | CLAUDE.COM, Claude for GRiD (the GRiD side of claude-link) |
| `gridos/releases` | Builds that went onto the floppy: 0.1, 0.2, 0.2.1, 0.2.2 |
| `gridos/screens` | Emulator screenshots |
| `gridos/*.py` | `pcemu.py` (a BIOS-level PC in unicorn: INT 13h with real-drive timing, mode 40h, 7210 GPIB model), `ktest.py`, `mkimg.py`, `psf.py`, `sim7210.py`; `gosim.py` and `test_*.py` are the 0.1 harness |
| `claude-link` | `gridlink` on the Raspberry Pi: GRiD ↔ GPIB (AR488 Nano) ↔ Pi ↔ Claude API, the AR488 patch, and its tests |
| `tools` | 1520 tools: GRIDGPIB (GPIB driver for GRiD MS-DOS), GPIBSCAN/GPIBTEST/GGTEST, MEMPROBE, GRIDPROBE, RAMSPEED, ROMDUMP, the C GPIB library, and TM5000G.EXE (a test fixture; its source lives in the TM5000 repo) |
| `rom` | Our notes on the 1520 BIOS (a symbol map) and a hardware probe log; no ROM images (see below) |
| `docs` | Design notes: kernel, the UI core and programs (0.3), DEFRAG and the saver, the floppy development loop |

## Build

Needs NASM 2.15+, and Python 3 for the `.RUN` programs (`mkrun.py`).

```sh
gridos/build.sh        # everything in gridos/src, apps, tests and bench
gridos/kbuild.sh       # just the kernel, with GRIDOS.MAP / .LST
cd gridos/claude && ./build.sh
```

The built binaries are committed too, so a fresh clone can go straight onto a floppy.

## Tests (emulator)

Needs Python 3, `unicorn` 2.x and mtools.

```sh
cd gridos
python3 tests/test_kernel.py          # 60 checks
python3 tests/test_apps.py            # 237 checks (add "shots" for screens/0.3)
python3 tests/test_defrag.py          # 33 checks
python3 tests/defrag_cut.py 2         # power cut at every DEFRAG write (~20 min)
python3 tests/defrag_cut.py 2 worn    # the same on a simulated worn drive
python3 tests/test_claude_kernel.py   # Claude-link scenarios on the kernel
python3 bench/run_bench.py <GRiD MS-DOS EPROM image>
```

Some tests need files that aren't in this repo: the GRiD MS-DOS EPROM image (`GRID_ROM=…`, or `rom/GRID_MSDOS330_ROM_300909-00.BIN`). Without it, those checks are skipped.

## On the GRiD (the floppy loop)

1. Format a 1.44 MB floppy and copy `GRIDOS.SYS`, `GRIDCMD.COM`, `DEFRAG.COM`, `SYSTEM.RUN`, `WRITE.RUN` and whatever programs you want.
2. Under GRiD MS-DOS (EPROM boot, where the floppy is B:), run `B:GOSBOOT B` once per format.
3. Restart and tap **F** as the memory count finishes: the 1520 boots the floppy.
4. A new `GRIDOS.SYS` can simply be copied over; the boot sector follows the FAT chain.

Keep `COMMAND.COM`, `CONFIG.SYS` and `AUTOEXEC.BAT` off this floppy unless they're meant for GRiD MS-DOS: booted from the EPROM with the floppy in, GRiD MS-DOS uses them from the floppy. See `docs/gridos-floppy-dev.md`.

## Not in this repo

These aren't ours to publish, even privately: the 1520 BIOS and GRiD MS-DOS ROM dumps, the GRiD MS-DOS disks and utilities, the vendor GPIB driver package (Driver488), and the floppy backups. They stay on the development PC. `.gitignore` keeps ROM images and disk images out.

## Status

Grid-OS 0.2.2 runs on the 1520. It boots, runs TESTDOS, TM5000G and CLAUDE.COM, and the screen saver defragments the floppy.

0.3 (in emulation, not yet on the 1520) moves the Executive onto a shared UI core in its own segment and adds the first programs, System and Write; DOS programs get 572 KB (0.2.2: 570.7 KB). See `docs/gridos-0.3-apps.md`. Next: Term and Command, the rest of the Executive (Subjects, file operations), INT 33h mouse for DOS programs, and EMS. The roadmap and the hardware notes are in the claude.ai Project.
