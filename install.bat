@echo off
chcp 65001 >nul
title ProtoForge 一键启动

echo.
echo   ProtoForge 一键安装并启动 (Windows)
echo   物联网协议仿真与测试平台
echo.

:: Check Python first (the only thing we need before running the Python installer)
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [错误] 没有找到 Python，请先安装 Python 3.10+
    echo   下载地址：https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

:: Run the Python installer script
python protoforge\installer.py
if %errorlevel% neq 0 (
    echo.
    echo   [错误] 安装或启动失败，请检查上方错误信息
    echo.
    pause
)
