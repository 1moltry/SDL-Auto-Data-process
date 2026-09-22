@echo off
setlocal
set "APP_DIR=%~dp0app"

where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher was not found. Please install Python 3.13 first.
  pause
  exit /b 1
)

py -3.13 -c "import numpy,pandas,scipy,matplotlib,openpyxl,pyabf,PyQt5,pyqtgraph" >nul 2>&1
if errorlevel 1 (
  echo Installing required components for the first launch...
  py -3.13 -m pip install -r "%APP_DIR%\requirements.txt" --timeout 120 --retries 8
  if errorlevel 1 (
    echo.
    echo Installation failed. Check the network connection and try this same launcher again.
    pause
    exit /b 1
  )
)

where pyw >nul 2>&1
if not errorlevel 1 (
  start "Nanopore analysis" /D "%APP_DIR%" pyw -3.13 "%APP_DIR%\nanopore_launcher.pyw"
  exit /b 0
)

start "Nanopore analysis" /D "%APP_DIR%" py -3.13 "%APP_DIR%\nanopore_launcher.pyw"
