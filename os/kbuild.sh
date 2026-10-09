#!/bin/sh
# Build the Lodestone 0.2 kernel (with listing and symbol map)
set -e
cd "$(dirname "$0")/src"
printf '[map symbols LODE.MAP]\n%%include "LODE.ASM"\n' > _m.asm
nasm -f bin -o LODE.SYS _m.asm -l LODE.LST
rm -f _m.asm
ls -l LODE.SYS
