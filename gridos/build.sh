#!/bin/sh
# Build Grid-OS: boot sector, installer, kernel (with listing and symbol
# map), GRIDCMD.COM (the shell), DEFRAG.COM, HEADCLN.COM, the .RUN programs
# (apps/, with mkrun.py), the font files (fonts/), the test programs and BENCH.  Then:
# python3 tests/test_kernel.py, tests/test_apps.py, and bench/run_bench.py ROM-image
set -e
cd "$(dirname "$0")/src"
nasm -f bin -o BOOT.BIN BOOT.ASM
nasm -f bin -o GOSBOOT.COM GOSBOOT.ASM
printf '[map symbols GRIDOS.MAP]\n%%include "GRIDOS.ASM"\n' > _m.asm
nasm -f bin -o GRIDOS.SYS _m.asm -l GRIDOS.LST
rm -f _m.asm
nasm -f bin -o GRIDCMD.COM GRIDCMD.ASM
nasm -f bin -o DEFRAG.COM DEFRAG.ASM
nasm -f bin -o HEADCLN.COM HEADCLN.ASM
cd ../fonts
nasm -f bin -i ../src/ -o TERMINUS.FNT TERMINUS.ASM
cd ..
for a in SYSTEM WRITE; do python3 mkrun.py apps/$a.ASM apps/$a.RUN; done
python3 mkrun.py tests/UITEST.ASM tests/UITEST.RUN
cd tests
nasm -f bin -o TESTDOS.COM TESTDOS.ASM
nasm -f bin -o UPPER.COM UPPER.ASM
nasm -f bin -o CACHETST.COM CACHETST.ASM
nasm -f bin -o EMSTEST.COM EMSTEST.ASM
nasm -f bin -o CAPTEST.COM CAPTEST.ASM
nasm -f bin -o HDFLUSH.COM HDFLUSH.ASM
cd ../bench
nasm -f bin -o BENCH.COM BENCH.ASM
nasm -f bin -o DISKMAP.COM DISKMAP.ASM
cd ..
ls -l apps/*.RUN fonts/*.FNT src/BOOT.BIN src/GOSBOOT.COM src/GRIDOS.SYS src/GRIDCMD.COM src/DEFRAG.COM src/HEADCLN.COM tests/TESTDOS.COM tests/UPPER.COM tests/CACHETST.COM tests/EMSTEST.COM tests/CAPTEST.COM tests/HDFLUSH.COM bench/BENCH.COM bench/DISKMAP.COM
