@echo off
rem Razovaya nastroyka: proveryaet ffmpeg i stavit nuzhnye biblioteki.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

%PY% --version >nul 2>&1
if errorlevel 1 goto nopython

%PY% "app\tools\setup_check.py"
echo.
pause
exit /b

:nopython
echo.
echo   Python ne nayden.
echo.
echo   Skachayte ego s https://python.org
echo   Pri ustanovke obyazatelno otmette galochku
echo   "Add Python to PATH", inache nichego ne zarabotaet.
echo.
pause
