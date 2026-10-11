@echo off
REM ============================================
REM ProtoForge Installer (Windows)
REM Runs installer.py which handles all logic in Python
REM ============================================

REM FIXED: same chcp 65001 UTF-8 restart workaround as quickstart.bat
if "%~1"=="__utf8" goto main
chcp 65001 >nul
cmd /s /c ""%~f0" __utf8"
exit /b %errorlevel%

:main
title ProtoForge Installer

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
