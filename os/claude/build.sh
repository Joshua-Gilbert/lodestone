#!/bin/sh
# CLAUDE.COM, its symbol map (for the emulator tests), and TESTKEY.COM
set -e
cd "$(dirname "$0")"
nasm -f bin -i ../src/ -o CLAUDE.COM CLAUDE.ASM -l CLAUDE.LST
printf '[map symbols CLAUDE.MAP]\n%%include "CLAUDE.ASM"\n' > _map.asm
nasm -f bin -i ../src/ -o _map.bin _map.asm
cmp -s _map.bin CLAUDE.COM
rm -f _map.asm _map.bin
nasm -f bin -o TESTKEY.COM TESTKEY.ASM
ls -l CLAUDE.COM TESTKEY.COM
