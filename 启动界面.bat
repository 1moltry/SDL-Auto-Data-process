@echo off
rem ============================================================
rem  SDL nanopore analysis -- GUI launcher (double-click me)
rem  Starts the PyQt5 GUI with NO console window.
rem  If nothing happens, run 启动界面-调试.bat to see the error.
rem ============================================================
setlocal

rem Always run from the folder that holds this script, so that
rem "python -m nanopore" can find the package.
cd /d "%~dp0"

rem Anaconda's Python is the one with PyQt5/pyqtgraph installed.
rem Hardcoded on purpose: several other Python installs on this
rem machine lack PyQt5, so a bare "python" may resolve to the
rem wrong one. pythonw = same interpreter, no console window.
set "PYW=D:\anaconda3\pythonw.exe"

if not exist "%PYW%" (
    set "PYW=pythonw"
    where pythonw >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] No Python with PyQt5 found.
        echo         Edit this file and set PYW to your pythonw.exe path.
        pause
        exit /b 1
    )
)

start "" "%PYW%" -m nanopore gui
exit /b 0
