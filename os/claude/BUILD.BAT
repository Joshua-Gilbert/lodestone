@echo off
rem CLAUDE.COM, its symbol map (for the emulator tests), and TESTKEY.COM
cd /d "%~dp0"
nasm -f bin -i ..\src\ -o CLAUDE.COM CLAUDE.ASM -l CLAUDE.LST || exit /b 1
> _map.asm echo [map symbols CLAUDE.MAP]
>> _map.asm echo %%include "CLAUDE.ASM"
nasm -f bin -i ..\src\ -o _map.bin _map.asm || exit /b 1
del _map.asm _map.bin
nasm -f bin -o TESTKEY.COM TESTKEY.ASM || exit /b 1
dir CLAUDE.COM TESTKEY.COM
