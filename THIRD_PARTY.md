# Third-party material

Lodestone bundles or derives from the works below. Each keeps its own
license; the full texts are in [`LICENSES/`](LICENSES/).

| What | Where in this repo | Upstream | License |
|---|---|---|---|
| Glyphs from Terminus Font (Bold 16), converted to 8x16 bitmap tables and modified (127 drawn as a solid block; 19 of TERM437's codes drawn by `tools/mkfnt437.py`), so a Modified Version under the OFL and not "Terminus Font" itself. The Reserved Font Name stays with the original: the font file System offers is `TERMBOLD.FNT`, and none of these is presented to users as Terminus. The copyright notice and license go with them as `OFL.TXT` (`os/fonts/OFL.TXT`): on ROM 2 (since 2026-11-11), and beside the files in each release folder that has them (the ROM images released before then don't hold it) | `os/src/TERMINUS.INC`, `os/fonts/TERM437.INC`, `os/fonts/*.FNT`, and the binaries built with them: `os/LODE*.BIN`, `os/claude/*.COM`, `os/claude/RCON.BIN`, and those in `os/releases/` | Terminus Font, Dimitar Toshkov Zhekov, terminus-font.sourceforge.net | SIL Open Font License 1.1, [`LICENSES/OFL-1.1.txt`](LICENSES/OFL-1.1.txt) |
| FreeDOS kernel 2046 (`KERNEL.SYS`), its FAT12 boot sector (`BOOT12.BIN`), FreeCOM 0.87 (`COMMAND.COM`), built from unmodified sources, used only by the emulator benchmark | `os/bench/freedos/`, with their complete sources in `os/bench/freedos/src/` | github.com/FDOS/kernel (git d6791ad, with its submodules share and country), github.com/FDOS/freecom (git 04fc21a); build steps in `os/bench/freedos/README.TXT` | GPL v2 or later, [`LICENSES/GPL-2.0.txt`](LICENSES/GPL-2.0.txt); FreeCOM's SUPPL library, linked into `COMMAND.COM`, is LGPL v2 or later (its text `suppl/src/copying.lb` in the FreeCOM archive) |
| A patch to AR488 0.53.46 for the Arduino Nano bridge | `claude-link/AR488-gridlink.patch` | github.com/Twilight-Logic/AR488 | GPL v3, as AR488 is, [`LICENSES/GPL-3.0.txt`](LICENSES/GPL-3.0.txt) |
| The arduino-pico core 6.3.0, the Raspberry Pi Pico SDK, TinyUSB and newlib, linked into the ready-built bridge firmware | `pico-bridge/firmware/bridge/bridge_pico2.uf2` (its own sources are beside it; `FIRMWARE.md` has the build line, so it can be rebuilt and relinked) | github.com/earlephilhower/arduino-pico, github.com/raspberrypi/pico-sdk, github.com/hathach/tinyusb, sourceware.org/newlib | arduino-pico: LGPL v2.1, [`LICENSES/LGPL-2.1.txt`](LICENSES/LGPL-2.1.txt); Pico SDK: BSD 3-Clause, [`LICENSES/BSD-3-Clause.txt`](LICENSES/BSD-3-Clause.txt); TinyUSB: MIT, [`LICENSES/MIT-TinyUSB.txt`](LICENSES/MIT-TinyUSB.txt); newlib: the notices in [`LICENSES/COPYING.NEWLIB`](LICENSES/COPYING.NEWLIB) |
| TM5000G, the TM5000 instrument program (banner v3.6, TM5000 git 8e2d0f1), used by the kernel tests | `tools/TM5000G.EXE` | github.com/Joshua-Gilbert/TM5000 (`src/tm5000g.exe`) | Apache 2.0, [`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt) |

From GRiD Systems: `os/src/FONT.INC`, the system font of the Executive
and the apps, is the 96 printable glyphs (codes 32-127) of TC8X16, the
8x16 bitmap font of GRiD's InteGRiD, extracted by `os/typfont.py`. The
same glyphs are in `claude-link/gridlink/gridfont.py` and in the binaries
built from FONT.INC (`os/src/LODE.SYS`, `os/apps/SYSTEM.RUN`,
`os/src/DEFRAG.COM`, the `os/LODE*.BIN` ROM images, and those in
`os/releases/`). GRiD's font files themselves are not in the
repo.

Not included: the GRiD BIOS and GRiD MS-DOS ROM images. The tests read
them from outside the repo (see `rom/README.md`).
`rom/GRID1520_BIOS_891025.map` is a symbol map written for this project,
not BIOS code.

"GRiD", "GRiDCase", "Terminus", "FreeDOS", "Raspberry Pi" and the other
names here belong to their owners, who are not connected with this
project.
