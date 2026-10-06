@echo off
rem Build Grid-OS with NASM on Windows (nasm.exe on the PATH)
cd src
nasm -f bin -o BOOT.BIN BOOT.ASM
nasm -f bin -o GOSBOOT.COM GOSBOOT.ASM
echo [map symbols GRIDOS.MAP] > _m.asm
echo %%include "GRIDOS.ASM" >> _m.asm
nasm -f bin -o GRIDOS.SYS _m.asm -l GRIDOS.LST
del _m.asm
nasm -f bin -o GRIDCMD.COM GRIDCMD.ASM
nasm -f bin -o DEFRAG.COM DEFRAG.ASM
nasm -f bin -o HEADCLN.COM HEADCLN.ASM
cd ..\tests
nasm -f bin -o TESTDOS.COM TESTDOS.ASM
nasm -f bin -o UPPER.COM UPPER.ASM
nasm -f bin -o CACHETST.COM CACHETST.ASM
cd ..\bench
nasm -f bin -o BENCH.COM BENCH.ASM
nasm -f bin -o DISKMAP.COM DISKMAP.ASM
cd ..
