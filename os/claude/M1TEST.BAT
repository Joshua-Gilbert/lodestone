@echo off
rem M1TEST.BAT - resident Claude M1 (CLAUDE /R and /U), step by step, on the
rem 1520.  Needs CLAUDE.COM, MEMSZ.COM, EMSUSE.COM and GFXUSE.COM here (and
rem TM5000G.EXE for step 6).  Every answer goes to M1TEST.TXT.
if "%1"=="GFX" goto gfx
echo Resident Claude M1 > m1test.txt
cls
echo Step 1 of 7: memory, then CLAUDE /R.
memsz >> m1test.txt
claude /r
if errorlevel 2 goto already
if errorlevel 1 goto noload
echo 1 CLAUDE /R: resident >> m1test.txt
goto loaded
:already
echo 1 CLAUDE /R: resident already, from before (restart for step 1's memory) >> m1test.txt
:loaded
memsz >> m1test.txt
claude /r
if errorlevel 2 echo 1 CLAUDE /R again: resident already, as it should >> m1test.txt
if not errorlevel 2 echo 1 CLAUDE /R again: NOT REFUSED >> m1test.txt
pause
cls
echo Step 2 of 7: EMS under the console.
echo When it asks for keys: press any key, then CODE-\ (Claude's console
echo comes: an empty screen, a band at the bottom), CODE-\ again (back
echo here), then another key, then Esc.
pause
emsuse
if errorlevel 1 echo 2 EMSUSE: EMS NOT KEPT >> m1test.txt
if not errorlevel 1 echo 2 EMSUSE: 0 bad >> m1test.txt
choice /c:yn Did the console show (band: Claude, resident) and go away again
if errorlevel 2 echo 2 console: NO >> m1test.txt
if not errorlevel 2 echo 2 console: yes >> m1test.txt
cls
echo Step 3 of 7: screens under the console, in three video modes.
for %%m in (4 6 40) do call %0 GFX %%m
cls
echo Step 4 of 7: DOS busy.  Type a line into COPY CON: hi, then CODE-\
echo (the console's band should say DOS busy), CODE-\ again, then Enter,
echo then Ctrl-Z and Enter.
copy con m1test.tmp
type m1test.tmp
choice /c:yn Did the band say DOS busy, and the file hold your line
if errorlevel 2 echo 4 DOS busy: NO >> m1test.txt
if not errorlevel 2 echo 4 DOS busy: yes >> m1test.txt
del m1test.tmp
cls
echo Step 5 of 7: keys you type straight after CODE-\ comes back.
echo In EMSUSE: CODE-\, CODE-\ again, then at once type a, b and Esc.
pause
emsuse
choice /c:yn Did EMSUSE end with 2 keys, 0 bad
if errorlevel 2 echo 5 keys after: NO >> m1test.txt
if not errorlevel 2 echo 5 keys after: yes >> m1test.txt
cls
if not exist tm5000g.exe goto notm
echo Step 6 of 7: TM5000G.  In any of its menus press CODE-\, move the
echo mouse a little while the console is up, then CODE-\: its screen back,
echo its mouse pointer where the mouse is.  Then use it as usual, its mouse
echo and a module scan too, and leave it.
pause
tm5000g
cls
choice /c:yn Did the console show, and TM5000G come back right and work
if errorlevel 2 echo 6 TM5000G: NOT RIGHT >> m1test.txt
if not errorlevel 2 echo 6 TM5000G: ok >> m1test.txt
goto unload
:notm
echo 6 TM5000G: not on this disk >> m1test.txt
:unload
cls
echo Step 7 of 7: CLAUDE /U, then memory again (as in step 1).
claude /u
if errorlevel 1 echo 7 CLAUDE /U: NOT TAKEN OUT >> m1test.txt
if not errorlevel 1 echo 7 CLAUDE /U: taken out >> m1test.txt
memsz >> m1test.txt
goto done
:noload
echo 1 CLAUDE /R DID NOT LOAD >> m1test.txt
:done
cls
echo Done.  One more by hand: CLAUDE /R, EXIT, then CODE-\ twice in the
echo Executive; it should come back as it was.  The answers, in M1TEST.TXT:
echo.
type m1test.txt
goto end
:gfx
echo.
echo Mode %2: when the pattern shows, CODE-\ twice, then a key, then Esc.
echo Watch the pattern and its grey levels before and after the console.
pause
gfxuse %2
if errorlevel 1 echo 3 mode %2: SCREEN NOT KEPT >> m1test.txt
if not errorlevel 1 echo 3 mode %2: 0 bad >> m1test.txt
choice /c:yn Mode %2: the same picture and grey levels after the console
if errorlevel 2 echo 3 mode %2 looked: DIFFERENT >> m1test.txt
if not errorlevel 2 echo 3 mode %2 looked: same >> m1test.txt
:end
