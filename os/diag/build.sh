#!/bin/sh
# The CRASHLOG diagnostic build (README.md here): LODE.SYS, LODEMT.SYS and
# LODE.MAP built with -dCRASHLOG into this directory (os/src's own build is
# left as it is), and CRASHRPT.COM.
set -e
cd "$(dirname "$0")"
printf '[map symbols LODE.MAP]\n%%include "LODE.ASM"\n' > _m.asm
nasm -f bin -dCRASHLOG -i ../src/ -o LODE.SYS _m.asm
rm -f _m.asm
python3 ../mkmt.py LODE.SYS LODE.MAP LODEMT.SYS
nasm -f bin -o CRASHRPT.COM CRASHRPT.ASM
ls -l LODE.SYS LODEMT.SYS CRASHRPT.COM
