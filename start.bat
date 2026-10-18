@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first. Python 3.12 is required for the recommended setup.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m elovision serve --open
if errorlevel 1 pause
