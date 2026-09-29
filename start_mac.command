#!/bin/bash
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[X] python3 not found. Install Python 3.10+ from https://www.python.org/downloads/macos/"
  read -p "Press Enter to close..."
  exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  echo "[X] This Python has no Tk (tkinter). Please install Python from python.org (not the Homebrew one)"
  echo "    or run: brew install python-tk"
  read -p "Press Enter to close..."
  exit 1
fi

if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

source venv/bin/activate
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
python -m playwright install chromium

python formbot_v5.py
read -p "Press Enter to close..."
