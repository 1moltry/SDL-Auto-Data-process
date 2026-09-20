@echo off
rem ============================================================
rem  SDL nanopore analysis -- GUI launcher, DEBUG version
rem  Same as 启动界面.bat but keeps the console open so you can
rem  read startup errors / Python tracebacks.
rem
rem  Requires the package to be installed first:
rem      pip install -e .
rem ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found on PATH.
    echo         Install Python, then run:  pip install -e .
    pause
    exit /b 1
)

echo Starting GUI with:
where python
echo.
python -m nanopore gui
echo.
echo GUI exited with code %errorlevel%
pause
