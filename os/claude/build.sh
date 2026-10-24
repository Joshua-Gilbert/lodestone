#!/bin/sh
# CLAUDE.COM (with RCON.BIN, resident Claude's console, inside), their
# symbol maps (for the emulator tests), TESTKEY.COM and CRITKEY.COM
set -e
cd "$(dirname "$0")"
nasm -f bin -i ../src/ -o RCON.BIN RCON.ASM
printf '[map symbols RCON.MAP]\n%%include "RCON.ASM"\n' > _map.asm
nasm -f bin -i ../src/ -o _map.bin _map.asm
cmp -s _map.bin RCON.BIN
nasm -f bin -i ../src/ -o CLAUDE.COM CLAUDE.ASM -l CLAUDE.LST
printf '[map symbols CLAUDE.MAP]\n%%include "CLAUDE.ASM"\n' > _map.asm
nasm -f bin -i ../src/ -o _map.bin _map.asm
cmp -s _map.bin CLAUDE.COM
nasm -f bin -i ../src/ -dPROFILE -o CLAUDEP.COM CLAUDE.ASM     # where the time goes (PROF.INC)
printf '[map symbols CLAUDEP.MAP]\n%%include "CLAUDE.ASM"\n' > _map.asm
nasm -f bin -i ../src/ -dPROFILE -o _map.bin _map.asm
cmp -s _map.bin CLAUDEP.COM
rm -f _map.asm _map.bin
nasm -f bin -o TESTKEY.COM TESTKEY.ASM
nasm -f bin -o CRITKEY.COM CRITKEY.ASM     # (test_resident_term: an INT 24h handler that waits for a key)
ls -l CLAUDE.COM CLAUDEP.COM TESTKEY.COM CRITKEY.COM
