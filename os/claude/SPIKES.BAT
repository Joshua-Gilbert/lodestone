@echo off
rem SPIKES.BAT - resident Claude's spikes, step by step, on the 1520.
rem   SPIKES nn   nn: the GPIB address of a TM5000 module that is on
rem               (the pop-up asks it for its ID); SPIKES alone: no GPIB.
rem Every answer goes to SPIKES.TXT.  RSPIKE stays loaded until a restart.
if "%1"=="GFX" goto gfx
echo Resident Claude spikes (GPIB address %1) > spikes.txt
cls
echo Step 1 of 5: the hot key.
echo Press CODE-\ once, then Esc twice.  Nothing shows: the keys go to a file.
keycode > spkey.txt
type spkey.txt >> spikes.txt
echo. >> spikes.txt
type spkey.txt
echo.
choice /c:yn Did it show 2B00 (then 011B for the Esc)
if errorlevel 2 echo 1 hot key: NOT 2B00 >> spikes.txt
if not errorlevel 2 echo 1 hot key: 2B00 >> spikes.txt
cls
echo Step 2 of 5: RSPIKE.
if "%1"=="" rspike
if not "%1"=="" rspike /g:%1
if errorlevel 2 goto loaded
if errorlevel 1 goto noload
:loaded
echo 2 RSPIKE resident >> spikes.txt
cls
echo Step 3 of 5: EMS under the pop-up.
echo When it asks for keys: press any key, then CODE-\ (the pop-up comes),
echo CODE-\ again (back here), then another key, then Esc.
pause
emsuse
if errorlevel 1 echo 3 EMSUSE: EMS NOT KEPT >> spikes.txt
if not errorlevel 1 echo 3 EMSUSE: 0 bad >> spikes.txt
choice /c:yn Did the pop-up show and go away again
if errorlevel 2 echo 3 pop-up: NO >> spikes.txt
if not errorlevel 2 echo 3 pop-up: yes >> spikes.txt
cls
echo Step 4 of 5: screens under the pop-up, in three video modes.
for %%m in (4 6 40) do call %0 GFX %%m
cls
if not exist tm5000g.exe goto notm
echo Step 5 of 5: TM5000G.  In any of its menus press CODE-\: the pop-up
echo (with the module's ID if you gave its address); CODE-\ goes back.  Then
echo use TM5000G as usual, a graphics screen too if you can, and leave it.
pause
tm5000g
cls
choice /c:yn Did the pop-up show (and the ID) and TM5000G work after it
if errorlevel 2 echo 5 TM5000G: NOT RIGHT >> spikes.txt
if not errorlevel 2 echo 5 TM5000G: ok >> spikes.txt
choice /c:ynx A graphics screen: same grey levels after the pop-up (X: not tried)
if errorlevel 3 echo 5 TM5000G graphics: not tried >> spikes.txt
if errorlevel 2 if not errorlevel 3 echo 5 TM5000G graphics: DIFFERENT >> spikes.txt
if not errorlevel 2 echo 5 TM5000G graphics: same >> spikes.txt
goto done
:notm
echo 5 TM5000G: not on this disk >> spikes.txt
goto done
:noload
echo 2 RSPIKE DID NOT LOAD >> spikes.txt
:done
del spkey.txt
cls
echo Done.  One more by hand: EXIT, then CODE-\ twice in the Executive; it
echo should come back as it was.  The answers, in SPIKES.TXT:
echo.
type spikes.txt
goto end
:gfx
echo.
echo Mode %2: when the pattern shows, CODE-\ twice, then a key, then Esc.
echo Watch the pattern and its grey levels before and after the pop-up.
pause
gfxuse %2
if errorlevel 1 echo 4 mode %2: SCREEN NOT KEPT >> spikes.txt
if not errorlevel 1 echo 4 mode %2: 0 bad >> spikes.txt
choice /c:yn Mode %2: the same picture and grey levels after the pop-up
if errorlevel 2 echo 4 mode %2 looked: DIFFERENT >> spikes.txt
if not errorlevel 2 echo 4 mode %2 looked: same >> spikes.txt
:end
