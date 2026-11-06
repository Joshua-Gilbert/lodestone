FreeDOS files for the emulator benchmark (bench/compare3.py, bench/fdimg.py).
Built 2026-10-07 from source with Open Watcom v2 and NASM:
  KERNEL.SYS   FreeDOS kernel, build 2046 (git d6791ad, github.com/FDOS/kernel),
               8086 build, FAT12/16: make all COMPILER=owlinux XCPU=86 XFAT=16
  BOOT12.BIN   its FAT12 floppy boot sector (boot/fat12com.bin, same build)
  COMMAND.COM  FreeCOM 0.87 (git 04fc21a, github.com/FDOS/freecom), English,
               no XMS swap: ./build.sh no-xms-swap
All are GPL (version 2 or later); the sources are at those repositories.
The license text is LICENSES/GPL-2.0.txt at the top of this repo.
