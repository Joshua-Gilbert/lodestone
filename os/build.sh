#!/bin/sh
# Build Lodestone: boot sector, installer, kernel (with listing and symbol
# map), the start-up picture LODE.PIC, LCMD.COM (the shell), FORMAT.COM, CHKDSK.COM, FDISK.COM, SYS.COM, LABEL.COM, DISKCOPY.COM, DISKCOMP.COM, ATTRIB.COM, XCOPY.COM, TREE.COM, FIND.COM, MORE.COM, SORT.COM, COMP.COM, DEFRAG.COM, HEADCLN.COM, PLOT.COM, CALC.COM, the .RUN programs
# (apps/, with mkrun.py), the font files (fonts/), the printer drivers (drivers/), the test programs and BENCH.  Then:
# python3 tests/test_kernel.py, tests/test_apps.py, and bench/run_bench.py ROM-image.  (On Windows: under
# WSL.  The BUILD.BAT files were retired on 2026-10-30: they had fallen behind and made
# no ROM images)
set -e
cd "$(dirname "$0")/src"
nasm -f bin -o BOOT.BIN BOOT.ASM
nasm -f bin -o ROMBOOT.BIN ROMBOOT.ASM
nasm -f bin -o LODEBOOT.COM LODEBOOT.ASM
sh ../kbuild.sh                 # the kernel: LODE.SYS, LODE.MAP, LODE.LST, LODEMT.SYS (multitasking's part)
nasm -f bin -o LODE.PIC SPLASH.ASM
nasm -f bin -o LCMD.COM LCMD.ASM
nasm -f bin -o FORMAT.COM FORMAT.ASM    # (BOOT.BIN in it)
nasm -f bin -o CHKDSK.COM CHKDSK.ASM
nasm -f bin -o FDISK.COM FDISK.ASM      # (ATAIO.INC, FORMAT's too)
nasm -f bin -o SYS.COM SYS.ASM          # (BOOT.BIN in it)
nasm -f bin -o LABEL.COM LABEL.ASM
nasm -f bin -o DISKCOPY.COM DISKCOPY.ASM
nasm -f bin -o DISKCOMP.COM DISKCOMP.ASM  # (DISKCOPY.ASM with COMP)
for f in ATTRIB XCOPY TREE; do nasm -f bin -o $f.COM $f.ASM; done   # (CANON.INC in them)
for f in FIND MORE SORT COMP; do nasm -f bin -o $f.COM $f.ASM; done
nasm -f bin -o DEFRAG.COM DEFRAG.ASM
nasm -f bin -o HEADCLN.COM HEADCLN.ASM
nasm -f bin -o PLOT.COM PLOT.ASM
nasm -f bin -o CALC.COM CALC.ASM
cd ../fonts
nasm -f bin -i ../src/ -o TERMBOLD.FNT TERMBOLD.ASM
nasm -f bin -o GRIDFONT.FNT GRIDFONT.ASM  # GRiD's TC8X16 (the built-in font, src/FONT.INC, is Lodefont: lodefont.py)
nasm -f bin -o TERM.FNT TERM.ASM          # the terminal window's (TERM437.INC: ../tools/mkfnt437.py)
cd ../drivers
nasm -f bin -o PS.PRN PS.ASM            # printer drivers, read at PrtSc
nasm -f bin -o SCREEN.PRN SCREEN.ASM    # Shift-PrtSc's file writer
cd ..
for a in SYSTEM WRITE CALC TASKS TERM PAINT; do python3 mkrun.py apps/$a.ASM apps/$a.RUN; done
python3 mkrun.py tests/UITEST.ASM tests/UITEST.RUN
# ROM 1, the boot ROM (tools/mkrom.py): the kernel first, then the core set
python3 ../tools/mkrom.py LODE1.BIN --boot src/ROMBOOT.BIN src/LODE.SYS src/LODEMT.SYS src/LODE.PIC src/LCMD.COM \
    apps/SYSTEM.RUN apps/WRITE.RUN apps/CALC.RUN apps/TASKS.RUN src/CALC.COM drivers/PS.PRN \
    drivers/SCREEN.PRN rom/LODE.INI
# ROM 2, a data ROM joined to R: (KROM.INC): what ROM 1 has no room for, and the disk utilities.
# (tests/test_rom.py reads this line for ROM 2's files)
# CLAUDE.COM as committed: run claude/build.sh first after a change to it
python3 ../tools/mkrom.py LODE2.BIN --data src/DEFRAG.COM apps/TERM.RUN fonts/TERM.FNT apps/PAINT.RUN claude/CLAUDE.COM fonts/GRIDFONT.FNT fonts/TERMBOLD.FNT fonts/OFL.TXT \
    src/FORMAT.COM src/CHKDSK.COM src/FDISK.COM src/SYS.COM src/LABEL.COM src/DISKCOPY.COM src/DISKCOMP.COM \
    src/ATTRIB.COM src/XCOPY.COM src/TREE.COM \
    src/FIND.COM src/MORE.COM src/SORT.COM src/COMP.COM \
    src/HEADCLN.COM src/PLOT.COM
cd tests
nasm -f bin -o TESTDOS.COM TESTDOS.ASM
nasm -f bin -o UPPER.COM UPPER.ASM
nasm -f bin -o CACHETST.COM CACHETST.ASM
nasm -f bin -o EMSTEST.COM EMSTEST.ASM
nasm -f bin -o CAPTEST.COM CAPTEST.ASM
nasm -f bin -o HDFLUSH.COM HDFLUSH.ASM
nasm -f bin -o HDABS.COM HDABS.ASM
nasm -f bin -o RUNCALC.COM RUNCALC.ASM
cd ../bench
nasm -f bin -o BENCH.COM BENCH.ASM
nasm -f bin -o DISKMAP.COM DISKMAP.ASM
cd ..
ls -l LODE1.BIN LODE1_EPROM.BIN LODE2.BIN LODE2_EPROM.BIN apps/*.RUN fonts/*.FNT src/BOOT.BIN src/LODEBOOT.COM src/LODE.SYS src/LODE.PIC src/LCMD.COM src/FORMAT.COM src/CHKDSK.COM src/FDISK.COM src/SYS.COM src/LABEL.COM src/DISKCOPY.COM src/DISKCOMP.COM src/ATTRIB.COM src/XCOPY.COM src/TREE.COM src/FIND.COM src/MORE.COM src/SORT.COM src/COMP.COM src/DEFRAG.COM src/HEADCLN.COM src/PLOT.COM src/CALC.COM tests/TESTDOS.COM tests/UPPER.COM tests/CACHETST.COM tests/EMSTEST.COM tests/CAPTEST.COM tests/HDFLUSH.COM tests/HDABS.COM bench/BENCH.COM bench/DISKMAP.COM
