@echo off
REM ============================================
REM ProtoForge Quick Start (Windows)
REM Double-click to run: checks env, installs deps, starts server.
REM ============================================

REM FIXED: known cmd.exe bug -- after `chcp 65001`, the rest of the SAME
REM batch file is re-parsed with wrong byte offsets (UTF-8 multi-byte chars
REM get split), producing garbage errors. Workaround: restart the script.
REM NOTE: keep every line ABOVE `chcp 65001` pure ASCII.
if "%~1"=="__utf8" goto main
chcp 65001 >nul
cmd /s /c ""%~f0" __utf8"
exit /b %errorlevel%

:main
title ProtoForge Quick Start
cd /d "%~dp0"

echo.
echo   ======================================================
echo         ProtoForge 一键启动 (Windows)
echo         物联网协议仿真与测试平台
echo   ======================================================
echo.

REM Step 1: 检查 Python
echo [1/5] 检查 Python ...
where python >nul 2>&1
if errorlevel 1 (
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
echo [2/5] 检查 Python 虚拟环境 ...
if exist "venv\Scripts\python.exe" (
    echo       虚拟环境已存在，跳过创建
) else (
    echo       创建虚拟环境 ...
    python -m venv venv
    if errorlevel 1 (
        echo   [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo       虚拟环境创建成功
)
echo.

REM Step 3: 检查依赖是否已安装
echo [3/5] 检查 Python 依赖 ...
venv\Scripts\python.exe -c "import protoforge" >nul 2>&1
if errorlevel 1 (
    echo       首次运行，正在安装依赖（可能需要几分钟）...

    REM FIXED: ensure pip is available and up-to-date in fresh venv
    venv\Scripts\python.exe -m ensurepip --default-pip >nul 2>&1
    venv\Scripts\python.exe -m pip install --quiet --upgrade pip

    REM FIXED: install core deps first (guarantees server can start),
    REM then try [all] extras (grpcio, asyncua, etc.) as best-effort.
    REM This way if [all] fails on a slow network or missing C build tools,
    REM the server still starts with core protocols (Modbus, HTTP, GB28181, etc.)
    echo       安装核心依赖...
    venv\Scripts\pip.exe install -e .
    if errorlevel 1 (
        echo.
        echo   [错误] 核心依赖安装失败，请检查网络连接
        echo   可尝试设置国内镜像后重新运行:
        echo   pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
        echo.
        pause
        exit /b 1
    )
    echo       核心依赖安装成功

    echo       安装扩展协议依赖（可选，失败不影响核心功能）...
    venv\Scripts\pip.exe install -e ".[all]" >nul 2>&1
    if errorlevel 1 (
        echo       [提示] 扩展协议依赖安装失败，核心协议仍可正常使用
        echo       缺失的协议（OPC-UA/MQTT/BACnet/S7等）可通过以下命令单独安装:
        echo       pip install -e ".[opcua]"  或  pip install -e ".[all]"
    ) else (
        echo       扩展协议依赖安装成功
    )
    echo       依赖安装完成
) else (
    echo       依赖已安装，跳过
)
echo.

REM Step 4: 确保 .env 配置正确
echo [4/5] 检查配置文件 ...

set "JWT_SECRET_GEN="
venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))" > "%TEMP%\pf_jwt_tmp" 2>nul
set /p JWT_SECRET_GEN=<"%TEMP%\pf_jwt_tmp"
del "%TEMP%\pf_jwt_tmp" >nul 2>&1

if exist ".env" goto check_env
    echo       首次运行，生成配置文件 ...
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
    goto env_done

:check_env
findstr /B /C:"PROTOFORGE_JWT_SECRET=" .env 2>nul | findstr /R /C:"PROTOFORGE_JWT_SECRET=$" >nul 2>&1
if not errorlevel 1 (
    echo       检测到 JWT_SECRET 为空，正在修复 ...
    powershell -NoProfile -Command "(Get-Content '.env') -replace '^PROTOFORGE_JWT_SECRET=$', 'PROTOFORGE_JWT_SECRET=%JWT_SECRET_GEN%' | Set-Content '.env'"
    echo       JWT_SECRET 已修复
) else (
    echo       配置文件正常
)

:env_done
echo.

REM Step 5: 数据库迁移 + 启动
echo [5/5] 初始化数据库 ...

REM 确保 data 目录存在
if not exist "data" mkdir data

REM 运行数据库迁移（失败不阻止启动，首次运行 SQLite 会自动建表）
venv\Scripts\python.exe -m alembic upgrade head 2>nul
if errorlevel 1 (
    echo       [提示] 数据库迁移未执行或失败，系统将自动创建数据库
) else (
    echo       数据库迁移完成
)
echo.

REM 显示启动信息
echo ======================================================
echo.
echo   ProtoForge 正在启动...
echo.
echo   浏览器打开: http://localhost:8000
echo   登录账号:   admin
echo   登录密码:   admin
echo.
echo   按 Ctrl+C 可停止服务
echo.
echo ======================================================
echo.

REM 启动服务（演示模式）
venv\Scripts\python.exe -m protoforge.cli demo

if errorlevel 1 (
    echo.
    echo   [错误] 服务启动失败，请检查上方错误信息
    echo.
    echo   常见原因:
    echo   1. 端口 8000 被占用 - 修改 .env 中的 PROTOFORGE_PORT
    echo   2. 依赖未装全 - 运行: venv\Scripts\pip install -e ".[all]"
    echo   3. 数据库损坏 - 删除 data\protoforge.db 后重试
    echo.
)
echo.
echo   ProtoForge 已停止
echo.
pause
