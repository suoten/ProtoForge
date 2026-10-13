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
REM FIXED: 子进程异常退出（含解析崩溃导致的"一闪而过"）时，父窗口必须
REM 停下来显示日志，绝不允许闪退。Ctrl+C 正常停止服务时错误码为负数，
REM 仅提示不当作错误。
set "PFQS_EC=%errorlevel%"
echo 1 2>%TEMP%\pfqs_flag.txt
if %PFQS_EC% LSS 0 goto parent_done
if "%PFQS_EC%"=="0" goto parent_done
echo.
echo   [错误] 启动脚本异常退出（错误码 %PFQS_EC%）。
echo   详细日志: %TEMP%\protoforge_quickstart.log
echo   （如果刚才是你手动 Ctrl+C 停止服务，可直接关闭本窗口）
echo.
if exist "%TEMP%\protoforge_quickstart.log" type "%TEMP%\protoforge_quickstart.log"
pause
:parent_done
exit /b %PFQS_EC%

:main
title ProtoForge Quick Start
cd /d "%~dp0"
set "PFQS_LOG=%TEMP%\protoforge_quickstart.log"
type nul > "%PFQS_LOG%"

echo.
echo   ======================================================
echo         ProtoForge 一键启动 (Windows)
echo         物联网协议仿真与测试平台
echo   ======================================================
echo.

REM Step 1: 检查 Python（含 Microsoft Store 假别名检测）
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
python --version >"%TEMP%\pf_pyver.txt" 2>&1
findstr /B /C:"Python 3" "%TEMP%\pf_pyver.txt" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [错误] 检测到的 python 不是真实的 Python 安装（可能是 Microsoft Store 占位程序）。
    echo   当前输出:
    type "%TEMP%\pf_pyver.txt"
    echo.
    echo   请从 https://www.python.org/downloads/ 安装 Python 3.10+，
    echo   安装时勾选 "Add Python to PATH"，并可在
    echo   "设置 - 应用 - 高级应用设置 - 应用执行别名" 中关闭 python 别名。
    echo.
    pause
    exit /b 1
)
type "%TEMP%\pf_pyver.txt"
echo.

REM Step 2: 创建/检查虚拟环境
echo [2/5] 检查 Python 虚拟环境 ...
if exist "venv\Scripts\python.exe" (
    echo       虚拟环境已存在，跳过创建
) else (
    echo       创建虚拟环境 ...
    python -m venv venv >> "%PFQS_LOG%" 2>&1
    if errorlevel 1 (
        echo   [错误] 创建虚拟环境失败，详细原因:
        type "%PFQS_LOG%"
        echo.
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

    venv\Scripts\python.exe -m ensurepip --default-pip >> "%PFQS_LOG%" 2>&1
    venv\Scripts\python.exe -m pip install --quiet --upgrade pip >> "%PFQS_LOG%" 2>&1

    echo       安装核心依赖...
    venv\Scripts\pip.exe install -e .
    if errorlevel 1 (
        echo.
        echo   [错误] 核心依赖安装失败，详细日志: %PFQS_LOG%
        echo   可尝试设置国内镜像后重新运行:
        echo   pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
        echo.
        pause
        exit /b 1
    )
    echo       核心依赖安装成功

    echo       安装扩展协议依赖（可选，失败不影响核心功能）...
    venv\Scripts\pip.exe install -e ".[all]" >> "%PFQS_LOG%" 2>&1
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

REM Step 3.5: 导入预检 —— 服务"一闪而过"的最大嫌疑是导入即崩，
REM 此处直接展示真实堆栈，窗口停住
venv\Scripts\python.exe -c "import protoforge.cli" > "%TEMP%\pf_import_check.txt" 2>&1
if errorlevel 1 (
    echo   [错误] 核心模块导入失败，真实错误如下（截图发群里即可定位）:
    echo.
    type "%TEMP%\pf_import_check.txt"
    echo.
    echo   详细日志: %PFQS_LOG%
    pause
    exit /b 1
)
echo       核心模块导入检查通过
echo.

REM Step 4: 确保 .env 配置正确
echo [4/5] 检查配置文件 ...

set "JWT_SECRET_GEN="
venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))" > "%TEMP%\pf_jwt_tmp" 2>nul
set /p JWT_SECRET_GEN=<"%TEMP%\pf_jwt_tmp" 2>nul
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

if not exist "data" mkdir data

venv\Scripts\python.exe -m alembic upgrade head >> "%PFQS_LOG%" 2>&1
if errorlevel 1 (
    echo       [提示] 数据库迁移未执行或失败，系统将自动创建数据库
) else (
    echo       数据库迁移完成
)
echo.

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

venv\Scripts\python.exe -m protoforge.cli demo

if errorlevel 1 (
    echo.
    echo   [错误] 服务启动失败，请检查上方错误信息（截图发群里可快速定位）
    echo.
    echo   常见原因:
    echo   1. 端口 8000 被占用 - 修改 .env 中的 PROTOFORGE_PORT
    echo   2. 依赖未装全 - 运行: venv\Scripts\pip install -e ".[all]"
    echo   3. 数据库损坏 - 删除 data\protoforge.db 后重试
    echo   4. 详细日志: %PFQS_LOG%
    echo.
)
echo.
echo   ProtoForge 已停止
echo.
pause
exit /b 0
