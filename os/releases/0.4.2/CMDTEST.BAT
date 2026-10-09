@echo off
rem CMDTEST.BAT - tries LCMD 0.4.2's batch language: "ok" or "FAIL" for
rem each step, then a summary.  Its own files are CT$*.TMP, gone at the end.
if "%1"=="SUB" goto sub
echo Lodestone command test (%0)
set ctf=
set ctn=
echo x > ct$1.tmp && echo ok   1 and-and runs after success || call %0 SUB FAIL 1
type ct$none.x > nul && call %0 SUB FAIL 2 || echo ok   2 or-or runs after a failure
type ct$none.x > nul
if errorlevel 1 echo ok   3 ERRORLEVEL 1 after a failed TYPE
if not errorlevel 1 call %0 SUB FAIL 3
type ct$1.tmp > nul
if not errorlevel 1 echo ok   4 ERRORLEVEL 0 after TYPE worked
if errorlevel 1 call %0 SUB FAIL 4
if exist ct$1.tmp echo ok   5 IF EXIST
if not exist ct$1.tmp call %0 SUB FAIL 5
if not exist ct$none.x echo ok   6 IF NOT EXIST
if exist ct$none.x call %0 SUB FAIL 6
echo x > ct$2.tmp
for %%f in (ct$*.tmp) do call %0 SUB COUNT
if "%ctn%"=="xx" echo ok   7 FOR over CT$*.TMP, CALL, SHIFT, %%NAME%%
if not "%ctn%"=="xx" call %0 SUB FAIL 7
for %%f in (a b c) do if %%f==b goto ctgo
call %0 SUB FAIL 8
:ctgo
echo ok   8 GOTO out of a FOR
copy ct$1.tmp ct$c.tmp > nul && echo ok   9 COPY || call %0 SUB FAIL 9
del ct$*.tmp
if not exist ct$*.tmp echo ok  10 DEL with a wildcard
if exist ct$*.tmp call %0 SUB FAIL 10
echo Now CHOICE picks N by itself after 3 seconds (press no key):
choice /c:yn /t:n,3 Continue
if errorlevel 2 echo ok  11 CHOICE /T: the default after the time
if not errorlevel 2 call %0 SUB FAIL 11
echo The next line should say "CMDTEST line 37: File not found":
type ct$none.x
if "%ctf%"=="" echo All 11 tests passed.
if not "%ctf%"=="" echo Failed:%ctf%
set ctf=
set ctn=
goto end
:sub
shift
if "%1"=="FAIL" goto fail
if "%1"=="COUNT" goto count
goto end
:fail
echo FAIL %2
set ctf=%ctf% %2
goto end
:count
set ctn=%ctn%x
:end
