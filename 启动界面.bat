@echo off
rem ============================================================
rem  SDL nanopore analysis -- GUI launcher (double-click me)
rem  Starts the PyQt5 GUI with NO console window.
rem
rem  Requires the package to be installed first:
rem      pip install -e .
rem
rem  If nothing happens, run 启动界面-调试.bat to see the error.
rem ============================================================
setlocal

rem Always run from the folder that holds this script, so that
rem "python -m nanopore" can find the package.
cd /d "%~dp0"

rem pythonw = same interpreter as python, but no console window.
rem It must be the interpreter the package was installed into.
where pythonw >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pythonw not found on PATH.
    echo         Install Python, then run:  pip install -e .
    echo         Or edit this file and set PYW to your pythonw.exe path.
    pause
    exit /b 1
)

start "" pythonw -m nanopore gui
exit /b 0
