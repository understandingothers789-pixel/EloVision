@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m elovision.windows_runtime diagnose
pause
