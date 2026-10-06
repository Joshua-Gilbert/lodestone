# Lodestone

A fast DOS 3.30-compatible OS for the GRiDCase 1520 (80C286, 640×400 gas-plasma display, 1.44 MB floppy). It has its own Executive, a disk cache, a built-in GPIB driver, and a screen saver that defragments the floppy.

> **Name:** Lodestone is the working name. The code, the files on the floppy and the screen still say **Grid-OS** (`GRIDOS.SYS`, "Grid-OS 0.2.2"). Renaming those is a separate step.

It boots from a floppy, shows a GRiD-style Executive, runs ordinary DOS programs (TM5000G, CLAUDE.COM, …) and comes back. On the real 1520 it runs the BENCH file-system benchmark in **83 s against GRiD MS-DOS's 289 s**, and it's ahead on all ten tests.

## What's here

| Folder | What |
|---|---|
| `gridos/src` | The OS, in NASM: boot sector (`BOOT.ASM`), `GOSBOOT.COM` (installs the boot sector), the kernel and Executive (`GRIDOS.ASM` + `K*.INC`, `EXEC*.INC`), the shell `GRIDCMD.COM`, `DEFRAG.COM` |
| `gridos/tests` | `pcemu`-based tests: kernel (59 checks), DEFRAG (33) and a power cut at every DEFRAG write, the Claude-link scenarios, GGTEST; also TESTDOS / CACHETST / UPPER (DOS programs) |
| `gridos/bench` | BENCH.COM, DISKMAP.COM, `run_bench.py` (Lodestone against GRiD MS-DOS in the emulator), profiling tools, `RESULTS.TXT` and the 1520 logs |
| `gridos/claude` | CLAUDE.COM, Claude for GRiD (the GRiD side of claude-link) |
| `gridos/releases` | Builds that went onto the floppy: 0.1, 0.2, 0.2.1, 0.2.2 |
| `gridos/screens` | Emulator screenshots |
| `gridos/*.py` | `pcemu.py` (a BIOS-level PC in unicorn: INT 13h with real-drive timing, mode 40h, 7210 GPIB model), `ktest.py`, `mkimg.py`, `psf.py`, `sim7210.py`; `gosim.py` and `test_*.py` are the 0.1 harness |
| `claude-link` | `gridlink` on the Raspberry Pi: GRiD ↔ GPIB (AR488 Nano) ↔ Pi ↔ Claude API, the AR488 patch, and its tests |
| `tools` | 1520 tools: GRIDGPIB (GPIB driver for GRiD MS-DOS), GPIBSCAN/GPIBTEST/GGTEST, MEMPROBE, GRIDPROBE, RAMSPEED, ROMDUMP, the C GPIB library, and TM5000G.EXE (a test fixture; its source lives in the TM5000 repo) |
| `rom` | Our notes on the 1520 BIOS (a symbol map) and a hardware probe log; no ROM images (see below) |
| `docs` | Design notes: kernel, DEFRAG and the saver, the floppy development loop |

## Build

Needs NASM 2.15+.

```sh
gridos/build.sh        # everything in gridos/src, tests and bench
gridos/kbuild.sh       # just the kernel, with GRIDOS.MAP / .LST
cd gridos/claude && ./build.sh
```

The built binaries are committed too, so a fresh clone can go straight onto a floppy.

## Tests (emulator)

Needs Python 3, `unicorn` 2.x and mtools.

```sh
cd gridos
python3 tests/test_kernel.py          # 59 checks
python3 tests/test_defrag.py          # 33 checks
python3 tests/defrag_cut.py 2         # power cut at every DEFRAG write (~20 min)
python3 tests/defrag_cut.py 2 worn    # the same on a simulated worn drive
python3 tests/test_claude_kernel.py   # Claude-link scenarios on the kernel
python3 bench/run_bench.py <GRiD MS-DOS EPROM image>
```

Some tests need files that aren't in this repo: the GRiD MS-DOS EPROM image (`GRID_ROM=…`, or `rom/GRID_MSDOS330_ROM_300909-00.BIN`). Without it, those checks are skipped.

## On the GRiD (the floppy loop)

1. Format a 1.44 MB floppy and copy `GRIDOS.SYS`, `GRIDCMD.COM`, `DEFRAG.COM` and whatever programs you want.
2. Under GRiD MS-DOS (EPROM boot, where the floppy is B:), run `B:GOSBOOT B` once per format.
3. Restart and tap **F** as the memory count finishes: the 1520 boots the floppy.
4. A new `GRIDOS.SYS` can simply be copied over; the boot sector follows the FAT chain.

Keep `COMMAND.COM`, `CONFIG.SYS` and `AUTOEXEC.BAT` off this floppy unless they're meant for GRiD MS-DOS: booted from the EPROM with the floppy in, GRiD MS-DOS uses them from the floppy. See `docs/gridos-floppy-dev.md`.

## Not in this repo

These aren't ours to publish, even privately: the 1520 BIOS and GRiD MS-DOS ROM dumps, the GRiD MS-DOS disks and utilities, the vendor GPIB driver package (Driver488), and the floppy backups. They stay on the development PC. `.gitignore` keeps ROM images and disk images out.

## Status

Grid-OS 0.2.2 runs on the 1520. It boots, runs TESTDOS, TM5000G and CLAUDE.COM, and the screen saver defragments the floppy. Next: tell a weak drive head from a worn disk with `DEFRAG B: /T`, INT 33h mouse for DOS programs, and EMS. The roadmap and the hardware notes are in the claude.ai Project.
