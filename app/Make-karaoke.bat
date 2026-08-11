@echo off
rem Peretaschite na etot znachok audiofail i fail s tekstom.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

if "%~1"=="" goto nofiles

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

%PY% --version >nul 2>&1
if errorlevel 1 goto nopython

%PY% "%~dp0tools\auto.py" %*
echo.
pause
exit /b

:nofiles
echo.
echo   Peretaschite myshkoy na etot znachok srazu dva faila:
echo     - pesnyu   (mp3, wav, flac, m4a...)
echo     - tekst    (txt)
echo.
echo   Mozhno tak zhe peretaschit celuyu papku s pesnyami.
echo.
pause
exit /b

:nopython
echo.
echo   Python ne nayden. Zapustite snachala "..\Install.bat".
echo.
pause
