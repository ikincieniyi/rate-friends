@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher bulunamadi. Python 3.13 kurun.
  exit /b 1
)

py -3.13 -c "import sys; assert sys.version_info[:2] == (3, 13)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.13 bulunamadi.
  exit /b 1
)

if not exist ".venv-py313\Scripts\python.exe" (
  echo Python 3.13 sanal ortami hazirlaniyor...
  py -3.13 -m venv .venv-py313
  if errorlevel 1 exit /b 1
)

".venv-py313\Scripts\python.exe" -m pip --version >nul 2>nul
if errorlevel 1 (
  ".venv-py313\Scripts\python.exe" -m ensurepip --upgrade
  if errorlevel 1 exit /b 1
)

".venv-py313\Scripts\python.exe" -c "import fastapi, uvicorn, jinja2, multipart, itsdangerous" >nul 2>nul
if errorlevel 1 (
  echo Eksik bagimliliklar kuruluyor...
  ".venv-py313\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)

".venv-py313\Scripts\python.exe" scripts\local_run.py
exit /b %errorlevel%
