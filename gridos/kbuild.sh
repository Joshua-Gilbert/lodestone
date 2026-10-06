#!/bin/sh
# Build the Grid-OS 0.2 kernel (with listing and symbol map)
set -e
cd "$(dirname "$0")/src"
printf '[map symbols GRIDOS.MAP]\n%%include "GRIDOS.ASM"\n' > _m.asm
nasm -f bin -o GRIDOS.SYS _m.asm -l GRIDOS.LST
rm -f _m.asm
ls -l GRIDOS.SYS
