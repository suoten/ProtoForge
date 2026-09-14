@echo off
chcp 65001 >nul
title ProtoForge Quick Start
REM ============================================
REM ProtoForge 一键启动 (Windows)
REM 双击即可运行，自动检查环境、安装依赖、启动服务
REM ============================================

cd /d "%~dp0"

echo.
echo   ╔══════════════════════════════════════════════════╗
echo   ║        ProtoForge 一键启动 (Windows)              ║
echo   ║        物联网协议仿真与测试平台                     ║
echo   ╚══════════════════════════════════════════════════╝
echo.

REM Step 1: 检查 Python
echo [1/4] 检查 Python ...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [错误] 没有找到 Python，请先安装 Python 3.10+
    echo   下载地址: https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
python --version
echo.

REM Step 2: 创建/检查虚拟环境
echo [2/4] 检查 Python 虚拟环境 ...
if exist "venv\Scripts\python.exe" (
    echo       虚拟环境已存在，跳过创建
) else (
    echo       创建虚拟环境 ...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo   [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo       虚拟环境创建成功
)
echo.

REM Step 3: 检查依赖是否已安装（通过检测 protoforge 包是否可导入）
echo [3/4] 检查 Python 依赖 ...
venv\Scripts\python.exe -c "import protoforge" >nul 2>&1
if %errorlevel% neq 0 (
    echo       首次运行，正在安装依赖（可能需要几分钟）...
    venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    venv\Scripts\pip.exe install -e ".[all]" >nul 2>&1
    if %errorlevel% neq 0 (
        echo       全部协议安装失败，尝试安装核心依赖...
        venv\Scripts\pip.exe install -e .
        if %errorlevel% neq 0 (
            echo   [错误] 依赖安装失败，请检查网络连接
            echo   可尝试设置国内镜像: pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
            pause
            exit /b 1
        )
    )
    echo       依赖安装成功
) else (
    echo       依赖已安装，跳过
)
echo.

REM Step 4: 确保 .env 配置正确（关键：生成稳定的 JWT_SECRET）
echo [4/4] 检查配置文件 ...
venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))" > "%TEMP%\pf_jwt_tmp" 2>nul
set /pf JWT_SECRET_GEN=<"%TEMP%\pf_jwt_tmp"
del "%TEMP%\pf_jwt_tmp" >nul 2>&1

if not exist ".env" (
    echo       首次运行，生成配置文件 ...
    REM 生成 .env，确保 JWT_SECRET 非空且持久
    (
        echo # ProtoForge 配置文件（由 quickstart.bat 自动生成）
        echo PROTOFORGE_HOST=0.0.0.0
        echo PROTOFORGE_PORT=8000
        echo PROTOFORGE_DB_PATH=data/protoforge.db
        echo PROTOFORGE_JWT_SECRET=%JWT_SECRET_GEN%
        echo PROTOFORGE_ADMIN_PASSWORD=admin
        echo PROTOFORGE_DEMO_MODE=true
        echo PROTOFORGE_LOG_LEVEL=info
        echo PROTOFORGE_CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
    ) > ".env"
    echo       配置文件已生成
) else (
    REM 检查 .env 中 JWT_SECRET 是否为空，为空则补填
    findstr /R "^PROTOFORGE_JWT_SECRET=$" .env >nul 2>&1
    if %errorlevel% equ 0 (
        echo       检测到 JWT_SECRET 为空，正在修复 ...
        powershell -Command "(Get-Content '.env') -replace '^PROTOFORGE_JWT_SECRET=$', 'PROTOFORGE_JWT_SECRET=%JWT_SECRET_GEN%' | Set-Content '.env'"
        echo       JWT_SECRET 已修复
    ) else (
        echo       配置文件正常
    )
)
echo.

REM 确保 data 目录存在
if not exist "data" mkdir data

REM 显示启动信息
echo ════════════════════════════════════════════════════
echo.
echo   ProtoForge 正在启动...
echo.
echo   浏览器打开: http://localhost:8000
echo   登录账号:   admin
echo   登录密码:   admin
echo.
echo   按 Ctrl+C 可停止服务
echo.
echo ════════════════════════════════════════════════════
echo.

REM 启动服务（演示模式）
venv\Scripts\python.exe -m protoforge.cli demo

if %errorlevel% neq 0 (
    echo.
    echo   [错误] 服务启动失败，请检查上方错误信息
    echo   或尝试重新运行本脚本
    echo.
    pause
)
