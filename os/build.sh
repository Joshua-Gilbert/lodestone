#!/bin/sh
# Build Lodestone: boot sector, installer, kernel (with listing and symbol
# map), the start-up picture LODE.PIC, LCMD.COM (the shell), DEFRAG.COM, HEADCLN.COM, CALC.COM, the .RUN programs
# (apps/, with mkrun.py), the font files (fonts/), the test programs and BENCH.  Then:
# python3 tests/test_kernel.py, tests/test_apps.py, and bench/run_bench.py ROM-image
set -e
cd "$(dirname "$0")/src"
nasm -f bin -o BOOT.BIN BOOT.ASM
nasm -f bin -o ROMBOOT.BIN ROMBOOT.ASM
nasm -f bin -o LODEBOOT.COM LODEBOOT.ASM
printf '[map symbols LODE.MAP]\n%%include "LODE.ASM"\n' > _m.asm
nasm -f bin -o LODE.SYS _m.asm -l LODE.LST
rm -f _m.asm
nasm -f bin -o LODE.PIC SPLASH.ASM
nasm -f bin -o LCMD.COM LCMD.ASM
nasm -f bin -o DEFRAG.COM DEFRAG.ASM
nasm -f bin -o HEADCLN.COM HEADCLN.ASM
nasm -f bin -o CALC.COM CALC.ASM
cd ../fonts
nasm -f bin -i ../src/ -o TERMINUS.FNT TERMINUS.ASM
cd ..
for a in SYSTEM WRITE CALC; do python3 mkrun.py apps/$a.ASM apps/$a.RUN; done
python3 mkrun.py tests/UITEST.ASM tests/UITEST.RUN
# ROM 1, the boot ROM (tools/mkrom.py): the kernel first, then the core set
python3 ../tools/mkrom.py LODE1.BIN --boot src/ROMBOOT.BIN src/LODE.SYS src/LODE.PIC src/LCMD.COM \
    apps/SYSTEM.RUN apps/WRITE.RUN apps/CALC.RUN src/CALC.COM src/DEFRAG.COM fonts/TERMINUS.FNT rom/LODE.INI
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
ls -l LODE1.BIN LODE1_EPROM.BIN apps/*.RUN fonts/*.FNT src/BOOT.BIN src/LODEBOOT.COM src/LODE.SYS src/LODE.PIC src/LCMD.COM src/DEFRAG.COM src/HEADCLN.COM src/CALC.COM tests/TESTDOS.COM tests/UPPER.COM tests/CACHETST.COM tests/EMSTEST.COM tests/CAPTEST.COM tests/HDFLUSH.COM tests/HDABS.COM bench/BENCH.COM bench/DISKMAP.COM
