@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONPATH=%CD%\src"
set "AG2C_APP=%CD%\packaging\windows\tray.py"

set "AG2C_PYTHON="
set "AG2C_PYTHONW="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "AG2C_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "%LocalAppData%\Programs\Python\Python312\pythonw.exe" set "AG2C_PYTHONW=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if not defined AG2C_PYTHON if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "AG2C_PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined AG2C_PYTHONW if exist "%LocalAppData%\Programs\Python\Python313\pythonw.exe" set "AG2C_PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
if not defined AG2C_PYTHON set "AG2C_PYTHON=python"
if not defined AG2C_PYTHONW if /I not "%AG2C_PYTHON%"=="python" (
  set "AG2C_PYTHONW=%AG2C_PYTHON:python.exe=pythonw.exe%"
)

if not exist "%AG2C_APP%" (
  echo Cannot find the tray entry: %AG2C_APP%
  pause
  exit /b 1
)

if not exist "%CD%\portable.ini" (
  echo home=.>"%CD%\portable.ini"
)
if not exist "%CD%\data" mkdir "%CD%\data"
set "AG2C_PORTABLE=%CD%"
set "AG2C_DATA_ROOT=%CD%\data"
if exist "%CD%\git\cmd\git.exe" set "AG2C_PORTABLE_GIT=%CD%\git"

set "AG2C_CHECK=%AG2C_PYTHON%"
if defined AG2C_PYTHONW if exist "%AG2C_PYTHONW%" set "AG2C_CHECK=%AG2C_PYTHONW%"
"%AG2C_CHECK%" -c "import webview" 1>nul 2>nul
if errorlevel 1 (
  echo pywebview is missing. Installing...
  "%AG2C_PYTHON%" -m pip install --disable-pip-version-check "pywebview>=5"
  if errorlevel 1 (
    echo Could not install pywebview. Run: python -m pip install pywebview
    pause
    exit /b 1
  )
)

if defined AG2C_PYTHONW if exist "%AG2C_PYTHONW%" (
  start "AutoGovern2Code" /B "%AG2C_PYTHONW%" "%AG2C_APP%" --portable
  exit /b 0
)

start "AutoGovern2Code" /B "%AG2C_PYTHON%" "%AG2C_APP%" --portable
exit /b 0
