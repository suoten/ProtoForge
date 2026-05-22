@echo off
chcp 65001 >nul
title ProtoForge

echo.
echo   ProtoForge Installer (Windows)
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [ERROR] Python not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo   Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

python protoforge\installer.py
if %errorlevel% neq 0 (
    echo.
    echo   [ERROR] Installation or startup failed. Check the error messages above.
    echo.
    pause
)
