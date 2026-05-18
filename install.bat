@echo off
chcp 65001 >nul
title ProtoForge 一键安装

echo.
echo   ╔══════════════════════════════════════════════════╗
echo   ║        ProtoForge 一键安装脚本 (Windows)         ║
echo   ║         物联网协议仿真与测试平台                    ║
echo   ╚══════════════════════════════════════════════════╝
echo.
echo   [提示] 如果下载很慢，按 Ctrl+C 退出，然后：
echo   pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
echo   再重新运行此脚本。
echo.

:: Step 1: 检查 Python
echo [1/5] 检查 Python ...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [错误] 没有找到 Python，请先安装 Python 3.10+
    echo   下载地址：https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo        已找到 Python %PYVER%

python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if %errorlevel% neq 0 (
    echo.
    echo   [错误] Python 版本太低，需要 3.10 或更高
    echo   当前版本：%PYVER%
    echo   请从 https://www.python.org/downloads/ 下载最新版
    echo.
    pause
    exit /b 1
)

:: Step 2: 创建虚拟环境
echo.
echo [2/5] 创建 Python 虚拟环境 ...
if exist venv\ (
    echo        虚拟环境已存在，跳过创建
) else (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo.
        echo   [错误] 创建虚拟环境失败
        echo   请检查 Python 安装是否正确
        echo.
        pause
        exit /b 1
    )
    echo        虚拟环境创建成功
)

:: Step 3: 激活并安装 Python 依赖
echo.
echo [3/5] 安装 Python 依赖（可能需要几分钟）...
call .\venv\Scripts\activate.bat 2>nul
if %errorlevel% neq 0 (
    echo.
    echo   [提示] 虚拟环境激活方式可能不同，尝试直接安装...
)

.\venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.\venv\Scripts\python.exe -m pip install -e ".[all]"
if %errorlevel% neq 0 (
    echo.
    echo   [警告] 全部协议安装失败，尝试安装核心依赖...
    .\venv\Scripts\python.exe -m pip install -e .
    if %errorlevel% neq 0 (
        echo.
        echo   [错误] Python 依赖安装失败
        echo   请检查网络连接，或尝试设置国内镜像：
        echo   pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
        echo.
        pause
        exit /b 1
    )
)

:: Step 4: 检查 Node.js 并构建前端
echo.
echo [4/5] 构建前端页面 ...

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [警告] 没有找到 Node.js，将使用仓库中预构建的前端
    echo   如需修改前端代码，请安装 Node.js 18+：
    echo   https://nodejs.org/
    echo.
) else (
    for /f "tokens=2" %%v in ('node --version 2^>^&1') do set NODEVER=%%v
    echo        已找到 Node.js %NODEVER%

    cd web
    echo        安装前端依赖...
    call npm install --quiet 2>nul
    if %errorlevel% neq 0 (
        echo.
        echo   [警告] npm install 失败，将使用仓库中已有的前端文件
        echo   网络慢可设置国内镜像：
        echo   npm config set registry https://registry.npmmirror.com
        echo.
    ) else (
        echo        构建前端页面...
        call npm run build 2>nul
        if %errorlevel% neq 0 (
            echo.
            echo   [警告] 前端构建失败，将使用仓库中已有的前端文件
            echo.
        ) else (
            echo        前端构建成功
        )
    )
    cd ..
)

:: Step 5: 完成
echo.
echo [5/5] 初始化配置 ...
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo        配置文件已从 .env.example 复制到 .env
    ) else (
        echo        未找到 .env.example，将使用默认配置
    )
) else (
    echo        配置文件 .env 已存在，跳过
)

echo.
echo   ╔══════════════════════════════════════════════════╗
echo   ║                                                  ║
echo   ║   安装成功！现在可以启动 ProtoForge 了：           ║
echo   ║                                                  ║
echo   ║   方式一：演示模式（推荐新手）                      ║
echo   ║     .\venv\Scripts\python.exe -m protoforge.cli demo ║
echo   ║     浏览器打开 http://localhost:8000               ║
echo   ║     登录：admin / admin                           ║
echo   ║                                                  ║
echo   ║   方式二：普通模式                                 ║
echo   ║     .\venv\Scripts\python.exe -m protoforge.cli run  ║
echo   ║     浏览器打开 http://localhost:8000               ║
echo   ║     登录：admin / admin                           ║
echo   ║                                                  ║
echo   ╚══════════════════════════════════════════════════╝
echo.
echo   提示：窗口关闭后，如需重新查看上面的命令，打开 README.md 找"方式二"。
echo.
echo   按任意键退出 ...
pause >nul