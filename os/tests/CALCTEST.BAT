@echo off
rem CALCTEST.BAT - the 0.4.4 calculator on the 1520, in two steps.
rem   CALCTEST     step 1: sums at the prompt (the coprocessor's own code)
rem   CALCTEST W   step 2, after a visit to the Executive: the lamp and
rem                the window (CODE-K)
rem The answers go to CALCTEST.TXT.
if "%1"=="X" goto x
if "%1"=="V" goto v
if "%1"=="W" goto win
if "%1"=="w" goto win
echo Calculator test (0.4.5) > calctest.txt
ver >> calctest.txt
calc /? >> calctest.txt
fpuprobe >> calctest.txt
set bad=0
cls
echo Step 1 of 2: sums at the prompt.  Nothing to press until the end.
echo.
fpuprobe
echo.
echo Exact answers (ok or BAD):
echo Exact answers: >> calctest.txt
call %0 X 42 6*7
call %0 X 0.3 0.1+0.2
call %0 X -4 -2^2
call %0 X 512 2^3^2
call %0 X 0.5 2^-1
call %0 X 3 7\2
call %0 X 4 sqrt(16)
call %0 X 3.14159265358979 pi
call %0 X 1E+15 999999999999999.9
call %0 X 0 sin(0)
call %0 X 0 tan(0)
call %0 X 0 atan(0)
call %0 X 0.785398163397448 atan(1)
call %0 X 1 tan(45) /d
call %0 X 0 cos(90) /d
call %0 X -1 cos(180) /d
set r=
calc r=7%%2 > nul
if "%r%"=="1" echo ok   7%%2 = %r% >> calctest.txt
if not "%r%"=="1" echo BAD  7%%2 = %r%  (want 1) >> calctest.txt
if not "%r%"=="1" calc bad=bad+1 > nul
echo           7%%2 = %r%
set n=0
:loop
calc n=n+1 > nul
if errorlevel 1 goto loopbad
if not "%n%"=="5" goto loop
echo ok   a batch loop counted to %n% with CALC N=N+1 >> calctest.txt
echo           a batch loop counted to %n%
goto loopok
:loopbad
echo BAD  CALC N=N+1 failed at %n% >> calctest.txt
calc bad=bad+1 > nul
:loopok
echo.
echo Answers to compare later (written to CALCTEST.TXT):
echo Answers to compare: >> calctest.txt
call %0 V 2^0.5
call %0 V sqrt(2)
call %0 V 1.5^2.5
call %0 V exp(-0.7)
call %0 V exp(1)
call %0 V ln(10)
call %0 V log(2)
call %0 V sin(1)
call %0 V cos(1)
call %0 V tan(1)
call %0 V atan(0.5)
call %0 V atan(3)
call %0 V sin(1e6)
call %0 V 1e300*1e300
call %0 V sin(30) /d
call %0 V tan(60) /d
pause
cls
echo Sums that must fail.  Under each "want" line CALC should say the same:
echo Errors: >> calctest.txt
echo   want: CALC: Not a number
calc ln(0)
if not errorlevel 1 calc bad=bad+1 > nul
if not errorlevel 1 echo BAD  ln(0) did not fail >> calctest.txt
echo   want: CALC: Not a number
calc log(-1)
if not errorlevel 1 calc bad=bad+1 > nul
if not errorlevel 1 echo BAD  log(-1) did not fail >> calctest.txt
echo   want: CALC: Divide by zero
calc 1/0
if not errorlevel 1 calc bad=bad+1 > nul
if not errorlevel 1 echo BAD  1/0 did not fail >> calctest.txt
echo   want: CALC: Divide by zero
calc 0^-0.5
if not errorlevel 1 calc bad=bad+1 > nul
if not errorlevel 1 echo BAD  0^-0.5 did not fail >> calctest.txt
echo   (if this one hangs, restart: CALCTEST.TXT says so)
echo running sin(1e5000) >> calctest.txt
echo   want: CALC: Too big
calc sin(1e5000)
if not errorlevel 1 calc bad=bad+1 > nul
if not errorlevel 1 echo BAD  sin(1e5000) did not fail >> calctest.txt
echo sin(1e5000) came back >> calctest.txt
echo.
choice /c:yn Did each CALC line match the want line above it
if not errorlevel 2 echo ok   the five error messages >> calctest.txt
if errorlevel 2 echo BAD  the error messages did not all match >> calctest.txt
if errorlevel 2 calc bad=bad+1 > nul
echo Step 1: %bad% wrong >> calctest.txt
cls
echo Step 1 done: %bad% wrong.
echo.
echo Step 2: type EXIT, and in the Executive:
echo   1. Look at the info line: after 80286, a lit 80287 (or 80287XL)?
echo   2. System, Devices: the coprocessor named the same way?
echo   3. CODE-K: type 6*7 and Return; then +1 and Return (43).
echo   4. Click 2, *, 3 and = on its keypad (6).
echo   5. F2 (Deg lit), then sin(30) and Return (0.5).  Then F1: its help.
echo   6. ESC: the Executive as it was.
echo Then CODE-P and type CALCTEST W to record what you saw.
goto end
:x
set r=
calc %4 r=%3 > nul
if "%r%"=="%2" echo ok   %4 %3 = %r% >> calctest.txt
if not "%r%"=="%2" echo BAD  %4 %3 = %r%  (want %2) >> calctest.txt
if not "%r%"=="%2" calc bad=bad+1 > nul
if "%r%"=="%2" echo   ok    %4 %3 = %r%
if not "%r%"=="%2" echo   BAD   %4 %3 = %r%  (want %2)
goto end
:v
set r=
calc %3 r=%2 > nul
echo      %3 %2 = %r% >> calctest.txt
echo         %3 %2 = %r%
goto end
:win
echo. >> calctest.txt
echo Step 2: the Executive >> calctest.txt
cls
echo Step 2 of 2: what you saw in the Executive.
echo.
choice /c:12n The lamp after 80286 (1: 80287  2: 80287XL  N: none)
if errorlevel 3 echo    lamp: none >> calctest.txt
if errorlevel 2 if not errorlevel 3 echo    lamp: 80287XL >> calctest.txt
if not errorlevel 2 echo    lamp: 80287 >> calctest.txt
choice /c:yn System, Devices named the coprocessor the same way
if errorlevel 2 echo BAD  System, Devices: a different name >> calctest.txt
if not errorlevel 2 echo ok   System, Devices: the same name >> calctest.txt
choice /c:yn The window: 6*7 gave 42 and +1 then gave 43
if errorlevel 2 echo BAD  window: typed sums >> calctest.txt
if not errorlevel 2 echo ok   window: typed sums, +1 from the answer >> calctest.txt
choice /c:yn The window: clicking 2 * 3 = on the keypad gave 6
if errorlevel 2 echo BAD  window: keypad clicks >> calctest.txt
if not errorlevel 2 echo ok   window: keypad clicks >> calctest.txt
choice /c:yn The window: F2 lit Deg and sin(30) gave 0.5
if errorlevel 2 echo BAD  window: degrees >> calctest.txt
if not errorlevel 2 echo ok   window: degrees >> calctest.txt
choice /c:yn The window: F1 showed its help
if errorlevel 2 echo BAD  window: help >> calctest.txt
if not errorlevel 2 echo ok   window: help >> calctest.txt
choice /c:yn ESC put the Executive back as it was
if errorlevel 2 echo BAD  window: ESC left the screen wrong >> calctest.txt
if not errorlevel 2 echo ok   window: ESC, the Executive as it was >> calctest.txt
cls
echo Done.  CALCTEST.TXT:
echo.
type calctest.txt
:end
