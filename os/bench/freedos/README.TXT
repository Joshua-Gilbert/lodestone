FreeDOS files for the emulator benchmark (bench/compare3.py, bench/fdimg.py).
Built 2026-10-07 from source with Open Watcom v2 and NASM:
  KERNEL.SYS   FreeDOS kernel, build 2046 (git d6791ad, github.com/FDOS/kernel),
               8086 build, FAT12/16, not UPX-compressed:
               make all COMPILER=owlinux XCPU=86 XFAT=16 XUPX=
  BOOT12.BIN   its FAT12 floppy boot sector (boot/fat12com.bin, same build)
  COMMAND.COM  FreeCOM 0.87 (git 04fc21a, github.com/FDOS/freecom), English,
               no XMS swap, its config.std as shipped: ./build.sh no-xms-swap
All are GPL (version 2 or later); COMMAND.COM links FreeCOM's SUPPL
library, which is LGPL (version 2 or later, suppl/src/copying.lb in the
FreeCOM archive). Their complete sources, unmodified, as of the commits
they were built from, are in src/:
  kernel-d6791ad.tar.gz          github.com/FDOS/kernel   d6791add2043
  kernel-share-47f3d42.tar.gz    github.com/FDOS/share    47f3d4252725
  kernel-country-7f83e04.tar.gz  github.com/FDOS/country  7f83e041d00f
  freecom-04fc21a.tar.gz         github.com/FDOS/freecom  04fc21a9f679
share and country are the kernel's submodules: unpack each into the
kernel tree's share/ or country/ before building it. From src/, after
tar xzf kernel-d6791ad.tar.gz && cd FDOS-kernel-d6791ad:
  tar xzf ../kernel-share-47f3d42.tar.gz --strip-components=1 -C share
  tar xzf ../kernel-country-7f83e04.tar.gz --strip-components=1 -C country
The license texts are LICENSES/GPL-2.0.txt and LICENSES/LGPL-2.1.txt at
the top of this repo.
