@echo off
rem Build the self-contained Windows release even on the default PowerShell
rem policy, which blocks local .ps1 files launched by double click.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1" %*
exit /b %errorlevel%
