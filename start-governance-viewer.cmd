@echo off
setlocal
cd /d "%~dp0"

set "AG2C_PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
if not exist "%AG2C_PYTHON%" set "AG2C_PYTHON=python"
set "PYTHONPATH=%CD%\src"

echo Starting AutoGovern2Code governance viewer...
"%AG2C_PYTHON%" -m ag2c viewer --port 18995 --open
if errorlevel 1 (
  echo.
  echo The governance viewer could not start.
  pause
)
