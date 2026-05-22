"""ProtoForge one-click installer for Windows.

Called by install.bat - handles all installation logic in Python
to avoid CMD batch file fragility.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent


def run(cmd, **kwargs):
    """Run a command and return the result."""
    return subprocess.run(cmd, shell=True, cwd=str(PROJECT_DIR), **kwargs)


def main():
    os.chdir(str(PROJECT_DIR))
    print()
    print("  ProtoForge 一键安装并启动 (Windows)")
    print("  物联网协议仿真与测试平台")
    print()

    # Step 1: Check Python version
    print("[1/5] 检查 Python ...")
    if sys.version_info < (3, 10):
        print(f"  [错误] Python 版本太低: {sys.version}，需要 3.10+")
        input("按回车退出 ...")
        sys.exit(1)
    print(f"       已找到 Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    # Step 2: Create virtual environment
    print()
    print("[2/5] 创建 Python 虚拟环境 ...")
    venv_dir = PROJECT_DIR / "venv"
    if venv_dir.exists():
        print("       虚拟环境已存在，跳过创建")
    else:
        result = run(f'"{sys.executable}" -m venv venv')
        if result.returncode != 0:
            print("  [错误] 创建虚拟环境失败")
            input("按回车退出 ...")
            sys.exit(1)
        print("       虚拟环境创建成功")

    # Determine venv python path
    venv_python = venv_dir / "Scripts" / "python.exe"

    # Step 3: Install Python dependencies
    print()
    print("[3/5] 安装 Python 依赖（可能需要几分钟）...")

    # Ensure pip is available in venv
    ensure_pip = run(f'"{venv_python}" -m ensurepip --default-pip')
    if ensure_pip.returncode != 0:
        # Try upgrading pip with the system python
        run(f'"{sys.executable}" -m pip install --target "{venv_dir}/Lib/site-packages" pip')

    run(f'"{venv_python}" -m pip install --quiet --upgrade pip')

    result = run(f'"{venv_python}" -m pip install -e ".[all]"')
    if result.returncode != 0:
        print("  [警告] 全部协议安装失败，尝试安装核心依赖...")
        result = run(f'"{venv_python}" -m pip install -e .')
        if result.returncode != 0:
            print("  [错误] Python 依赖安装失败")
            print("  请检查网络连接，或尝试设置国内镜像：")
            print("  pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple")
            input("按回车退出 ...")
            sys.exit(1)

    # Step 4: Build frontend
    print()
    print("[4/5] 构建前端页面 ...")
    node_path = shutil.which("node")
    if not node_path:
        print("  [警告] 没有找到 Node.js，将使用仓库中预构建的前端")
        print("  如需修改前端代码，请安装 Node.js 18+: https://nodejs.org/")
    else:
        node_version = subprocess.run(
            [node_path, "--version"], capture_output=True, text=True
        ).stdout.strip()
        print(f"       已找到 Node.js {node_version}")

        web_dir = PROJECT_DIR / "web"
        if web_dir.exists():
            print("       安装前端依赖...")
            subprocess.run(
                "npm install --quiet", shell=True, cwd=str(web_dir),
                capture_output=True,
            )
            print("       构建前端页面...")
            build_result = subprocess.run(
                "npm run build", shell=True, cwd=str(web_dir),
                capture_output=True, text=True,
            )
            if build_result.returncode != 0:
                print("  [警告] 前端构建失败，将使用仓库中已有的前端文件")
            else:
                print("       前端构建成功")

    # Step 5: Initialize config
    print()
    print("[5/5] 初始化配置 ...")
    env_file = PROJECT_DIR / ".env"
    env_example = PROJECT_DIR / ".env.example"
    if not env_file.exists():
        if env_example.exists():
            shutil.copy2(env_example, env_file)
            print("       配置文件已从 .env.example 复制到 .env")
        else:
            print("       未找到 .env.example，将使用默认配置")
    else:
        print("       配置文件 .env 已存在，跳过")

    # Read port and password from .env
    port = "8000"
    password = "admin"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("PROTOFORGE_PORT=") and not line.startswith("#"):
                        port = line.split("=", 1)[1].strip()
                    elif line.startswith("PROTOFORGE_ADMIN_PASSWORD=") and not line.startswith("#"):
                        password = line.split("=", 1)[1].strip()
        except Exception:
            pass

    print()
    print("  +--------------------------------------------------+")
    print("  |                                                  |")
    print("  |   安装成功！正在启动 ProtoForge ...               |")
    print("  |                                                  |")
    print(f"  |   浏览器打开 http://localhost:{port}              |")
    print(f"  |   登录：admin / {password}                       |")
    print("  |                                                  |")
    print("  |   按 Ctrl+C 可停止服务                           |")
    print("  |                                                  |")
    print("  +--------------------------------------------------+")
    print()
    print("  正在启动服务（演示模式）...")
    print("  启动后浏览器打开上面的地址即可访问 Web 界面")
    print()

    # Start server
    result = subprocess.run([str(venv_python), "-m", "protoforge.cli", "demo"])
    if result.returncode != 0:
        print()
        print("  [错误] 服务启动失败，请检查上方错误信息")
        input("按回车退出 ...")


if __name__ == "__main__":
    main()
