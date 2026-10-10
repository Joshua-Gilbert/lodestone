@echo off
rem Build Lodestone with NASM on Windows (nasm.exe on the PATH; the .RUN
rem programs also need Python 3 for mkrun.py)
cd src
nasm -f bin -o BOOT.BIN BOOT.ASM
nasm -f bin -o LODEBOOT.COM LODEBOOT.ASM
echo [map symbols LODE.MAP] > _m.asm
echo %%include "LODE.ASM" >> _m.asm
nasm -f bin -o LODE.SYS _m.asm -l LODE.LST
del _m.asm
nasm -f bin -o LODE.PIC SPLASH.ASM
nasm -f bin -o LCMD.COM LCMD.ASM
nasm -f bin -o DEFRAG.COM DEFRAG.ASM
nasm -f bin -o HEADCLN.COM HEADCLN.ASM
cd ..\fonts
nasm -f bin -i ..\src\ -o TERMINUS.FNT TERMINUS.ASM
cd ..
python mkrun.py apps\SYSTEM.ASM apps\SYSTEM.RUN
python mkrun.py apps\WRITE.ASM apps\WRITE.RUN
python mkrun.py tests\UITEST.ASM tests\UITEST.RUN
cd tests
nasm -f bin -o TESTDOS.COM TESTDOS.ASM
nasm -f bin -o UPPER.COM UPPER.ASM
nasm -f bin -o CACHETST.COM CACHETST.ASM
nasm -f bin -o EMSTEST.COM EMSTEST.ASM
nasm -f bin -o CAPTEST.COM CAPTEST.ASM
nasm -f bin -o HDFLUSH.COM HDFLUSH.ASM
nasm -f bin -o HDABS.COM HDABS.ASM
cd ..\bench
nasm -f bin -o BENCH.COM BENCH.ASM
nasm -f bin -o DISKMAP.COM DISKMAP.ASM
cd ..
