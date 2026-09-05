@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONPATH=%CD%\src"
set "AG2C_APP=%CD%\packaging\windows\tray.py"

set "AG2C_PYTHON="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "AG2C_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined AG2C_PYTHON if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "AG2C_PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined AG2C_PYTHON set "AG2C_PYTHON=python"

if not exist "%AG2C_APP%" (
  echo Cannot find the tray entry: %AG2C_APP%
  pause
  exit /b 1
)

"%AG2C_PYTHON%" -c "from imgui_bundle import hello_imgui" 1>nul 2>nul
if errorlevel 1 (
  echo imgui-bundle is missing. Installing...
  "%AG2C_PYTHON%" -m pip install --disable-pip-version-check "imgui-bundle>=1.5"
  if errorlevel 1 (
    echo Could not install imgui-bundle. Run: python -m pip install imgui-bundle
    pause
    exit /b 1
  )
)

set "AG2C_PYTHONW="
if exist "%LocalAppData%\Programs\Python\Python312\pythonw.exe" set "AG2C_PYTHONW=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if not defined AG2C_PYTHONW if exist "%LocalAppData%\Programs\Python\Python313\pythonw.exe" set "AG2C_PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
if not defined AG2C_PYTHONW if /I not "%AG2C_PYTHON%"=="python" (
  set "AG2C_PYTHONW=%AG2C_PYTHON:python.exe=pythonw.exe%"
)

if defined AG2C_PYTHONW if exist "%AG2C_PYTHONW%" (
  start "AutoGovern2Code" "%AG2C_PYTHONW%" "%AG2C_APP%"
  exit /b 0
)

start "AutoGovern2Code" "%AG2C_PYTHON%" "%AG2C_APP%"
exit /b 0
