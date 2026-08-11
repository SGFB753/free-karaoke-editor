@echo off
rem Sobiraet karaoke dlya vseh pesen v papke.
rem Pary ischutsya po imeni: Veter.mp3 + Veter.txt
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")

%PY% --version >nul 2>&1
if errorlevel 1 goto nopython

set "FOLDER=%~1"
if not "%FOLDER%"=="" goto run

echo.
echo   Ukazhite papku s pesnyami.
echo   Mozhno prosto peretaschit papku na etot znachok.
echo.
set /p "FOLDER=Papka: "
if "%FOLDER%"=="" goto end

:run
%PY% "%~dp0tools\auto.py" "%FOLDER%"
echo.

:end
pause
exit /b

:nopython
echo.
echo   Python ne nayden. Zapustite snachala "..\Install.bat".
echo.
pause
