@echo off
setlocal
cd /d "%~dp0"
echo ELO Vision - install Python dependencies and official Maia 3 79M weights
if exist ".venv\Scripts\python.exe" goto dependencies
where py >nul 2>&1
if errorlevel 1 goto missing_python
py -3.12 -m venv .venv
if errorlevel 1 goto failed
:dependencies
.venv\Scripts\python.exe -m elovision.windows_runtime install
if errorlevel 1 goto failed
echo.
echo Setup finished. See the CPU/AMD result above. Run start.bat to launch ELO Vision.
pause
exit /b 0
:missing_python
echo Install Python 3.12 from python.org, including the Python launcher, then retry.
goto failed
:failed
echo.
echo Installation stopped. Read the error above and the troubleshooting in README.md.
pause
exit /b 1
