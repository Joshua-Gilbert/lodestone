#!/bin/sh
# Build Grid-OS: boot sector, installer, kernel (with listing and symbol
# map), GRIDCMD.COM (the shell), DEFRAG.COM, the test programs and BENCH.  Then:
# python3 tests/test_kernel.py, and python3 bench/run_bench.py ROM-image
set -e
cd "$(dirname "$0")/src"
nasm -f bin -o BOOT.BIN BOOT.ASM
nasm -f bin -o GOSBOOT.COM GOSBOOT.ASM
printf '[map symbols GRIDOS.MAP]\n%%include "GRIDOS.ASM"\n' > _m.asm
nasm -f bin -o GRIDOS.SYS _m.asm -l GRIDOS.LST
rm -f _m.asm
nasm -f bin -o GRIDCMD.COM GRIDCMD.ASM
nasm -f bin -o DEFRAG.COM DEFRAG.ASM
cd ../tests
nasm -f bin -o TESTDOS.COM TESTDOS.ASM
nasm -f bin -o UPPER.COM UPPER.ASM
nasm -f bin -o CACHETST.COM CACHETST.ASM
cd ../bench
nasm -f bin -o BENCH.COM BENCH.ASM
nasm -f bin -o DISKMAP.COM DISKMAP.ASM
cd ..
ls -l src/BOOT.BIN src/GOSBOOT.COM src/GRIDOS.SYS src/GRIDCMD.COM src/DEFRAG.COM tests/TESTDOS.COM tests/UPPER.COM tests/CACHETST.COM bench/BENCH.COM bench/DISKMAP.COM
