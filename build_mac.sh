#!/bin/bash

echo "=============================="
echo "  Building FormBot macOS"
echo "=============================="

python3 -m pip install --upgrade pip
python3 -m pip install requests playwright pyinstaller

export PLAYWRIGHT_BROWSERS_PATH=0

python3 -m playwright install chromium

rm -rf build
rm -rf dist
rm -f FormBot.spec

python3 -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --name "FormBot" \
    --icon "icon.icns" \
    --collect-all playwright \
    main.py

echo ""
echo "=============================="
echo "BUILD COMPLETE"
echo "dist/FormBot.app"
echo "=============================="