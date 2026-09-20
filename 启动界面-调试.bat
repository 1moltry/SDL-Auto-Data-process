@echo off
rem ============================================================
rem  SDL nanopore analysis -- GUI launcher, DEBUG version
rem  Same as 启动界面.bat but keeps the console open so you can
rem  read startup errors / Python tracebacks.
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY=D:\anaconda3\python.exe"
if not exist "%PY%" set "PY=python"

echo Starting GUI with: %PY%
"%PY%" -m nanopore gui
echo.
echo GUI exited with code %errorlevel%
pause
