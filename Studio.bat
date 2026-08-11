@echo off
rem Karaoke Studio - okno programmy. Zakroyte eto okno, chtoby zakonchit.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

%PY% --version >nul 2>&1
if errorlevel 1 goto nopython

%PY% "app\studio.py"
echo.
echo   Studiya zakryta.
pause
exit /b

:nopython
echo.
echo   Python ne nayden. Zapustite snachala "Install.bat".
echo.
pause
