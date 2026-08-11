@echo off
rem Peretaschite na etot znachok gotovuyu stranicu karaoke (.html).
rem Bez peretaskivaniya - pokazhet spisok stranic ryadom i dast vybrat.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

%PY% --version >nul 2>&1
if errorlevel 1 goto nopython

%PY% "%~dp0tools\video.py" %*
echo.
pause
exit /b

:nopython
echo.
echo   Python ne nayden. Zapustite snachala "..\Install.bat".
echo.
pause
