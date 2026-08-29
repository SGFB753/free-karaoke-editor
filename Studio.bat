@echo off
rem Karaoke Studio - okno programmy. Zakroyte eto okno, chtoby zakonchit.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

rem The installer puts every optional library into this private Python.  Use
rem it first: the system `py` may exist too, but without Whisper or Demucs.
if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
  goto havepython
)

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

:havepython
"%PY%" --version >nul 2>&1
if errorlevel 1 goto nopython

"%PY%" "app\studio.py"
echo.
echo   Studiya zakryta.
pause
exit /b

:nopython
echo.
echo   Python ne nayden. Zapustite snachala "Install.bat".
echo.
pause
