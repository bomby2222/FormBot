@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python not found. Install Python 3.10+ from https://www.python.org/downloads/
  echo     and tick "Add python.exe to PATH" during install.
  pause
  exit /b 1
)

if not exist venv (
  echo Creating virtual environment...
  python -m venv venv
)

call venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
python -m playwright install chromium

python formbot_v5.py
pause
