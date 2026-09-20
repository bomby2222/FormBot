@echo off
title Build FormBot Windows

echo ==============================
echo   Building FormBot Windows
echo ==============================

REM ติดตั้ง package
python -m pip install --upgrade pip
python -m pip install requests playwright pyinstaller

REM ให้ Chromium อยู่ใน package ของ Playwright
set PLAYWRIGHT_BROWSERS_PATH=0

REM ติดตั้ง Chromium
python -m playwright install chromium

REM ลบ build เก่า
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist FormBot.spec del /q FormBot.spec

REM Build
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onedir ^
    --name "FormBot" ^
    --icon "icon.ico" ^
    --collect-all playwright ^
    main.py

echo.
echo ==============================
echo BUILD COMPLETE
echo dist\FormBot\FormBot.exe
echo ==============================

pause