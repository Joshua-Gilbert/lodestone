#!/bin/sh
# Build the Lodestone kernel (with listing and symbol map) and LODEMT.SYS; build.sh runs it too.
# KFLAGS: NASM's -d options, e.g. KFLAGS=-dNOSYSREQ (no SysReq task switching, M11: for a
# machine without the key) or -dNOTC (no disk cache, so no multitasking)
set -e
cd "$(dirname "$0")/src"
printf '[map symbols LODE.MAP]\n%%include "LODE.ASM"\n' > _m.asm
nasm -f bin $KFLAGS -o LODE.SYS _m.asm -l LODE.LST
rm -f _m.asm
python3 ../mkmt.py LODE.SYS LODE.MAP LODEMT.SYS
ls -l LODE.SYS
