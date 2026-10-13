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
REM FIXED: 防御 cmd AutoRun 干扰（部分国产软件会改码页），子进程再强制一次 UTF-8
chcp 65001 >nul
REM FIXED: 必须先切到脚本所在目录 —— 双击"以管理员身份运行"或从其他目录
REM 调用时 cwd 不在这里，相对路径 protoforge\installer.py 会找错位置，
REM 报 "can't open file ... installer.py"
title ProtoForge Installer
cd /d "%~dp0"

echo.
echo   ProtoForge Installer (Windows)
echo.

if not exist "protoforge\installer.py" (
    echo   [ERROR] protoforge\installer.py not found in this folder.
    echo   Current folder: %CD%
    echo.
    echo   This script must stay inside the extracted ProtoForge SOURCE package
    echo   ^(the folder that contains protoforge\, web\, quickstart.bat ...^).
    echo.
    echo   - If you downloaded the PORTABLE package ^(contains ProtoForge.exe^):
    echo     just double-click ProtoForge.exe directly. No installer needed.
    echo   - If you downloaded the SOURCE package: re-extract it completely
    echo     and run quickstart.bat instead ^(recommended^).
    echo.
    pause
    exit /b 1
)

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
    echo   Tip: if this keeps failing, use quickstart.bat instead
    echo   ^(or the portable ProtoForge.exe if you have the portable package^).
    echo.
    pause
)
