@echo off
rem CLEANOLD.BAT - deletes the Grid-OS files Lodestone replaced (0.4.1)
for %%f in (GRIDOS.SYS GRIDOS.INI GRIDOS.TXT GRIDCMD.COM GOSBOOT.COM) do if exist %%f del %%f
for %%f in (GRIDOS.SYS GRIDOS.INI GRIDOS.TXT GRIDCMD.COM GOSBOOT.COM) do if exist %%f echo Still there: %%f
echo Done.  GRIDGPIB.COM stays: it is the GPIB driver for GRiD MS-DOS.
echo CLEANOLD.BAT can go too now: DEL CLEANOLD.BAT
