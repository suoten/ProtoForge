"""ProtoForge one-click installer for Windows.

Called by install.bat - handles all installation logic in Python
to avoid CMD batch file fragility.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent


def run(cmd, **kwargs):
    """Run a command and return the result."""
    if isinstance(cmd, str):
        import shlex
        cmd = shlex.split(cmd)
    return subprocess.run(cmd, cwd=str(PROJECT_DIR), **kwargs)


def _find_npm() -> str | None:
    """Locate the npm executable cross-platform.

    On Windows npm ships as npm.cmd plus an extensionless Unix sh shim
    with the same name. A bare "npm" in subprocess.run raises
    FileNotFoundError (WinError 2), and shutil.which("npm") may resolve
    to the sh shim (WinError 193), because CreateProcess only executes
    .exe/.cmd via full path. Prefer npm.cmd explicitly on Windows.
    """
    if os.name == "nt":
        return shutil.which("npm.cmd") or shutil.which("npm")
    return shutil.which("npm")


def _generate_jwt_secret(venv_python: Path) -> str:
    """Generate a stable JWT secret using Python's secrets module."""
    result = subprocess.run(
        [str(venv_python), "-c", "import secrets; print(secrets.token_urlsafe(32))"],
        capture_output=True, text=True, cwd=str(PROJECT_DIR),
    )
    secret = result.stdout.strip()
    return secret if secret else "protoforge_default_jwt_secret_change_me_in_production_2026"


def _read_env_text(env_file: Path) -> str:
    """Read .env as UTF-8 with GBK fallback, self-healing to UTF-8.

    .env is always read back as UTF-8 by pydantic-settings; if a cleaner
    tool or editor re-encodes it (e.g. GBK, common on Chinese Windows),
    the server crashes with UnicodeDecodeError on startup. Detect the
    encoding here and rewrite the file as UTF-8 in place.
    """
    raw = env_file.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gb18030", errors="replace")
        env_file.write_text(text, encoding="utf-8")
        print("  [警告] .env 编码异常（非 UTF-8，可能被清理工具/编辑器改动），已自动转换为 UTF-8")
        return text


def _ensure_env_key(env_file: Path, key: str, default_value: str) -> None:
    """Ensure a key in .env has a non-empty value. If empty or missing, set default_value.

    This is critical for JWT_SECRET: if left empty, each server restart generates
    a new random key, invalidating all previously issued tokens → 401 errors.
    """
    if not env_file.exists():
        return
    lines = _read_env_text(env_file).splitlines()
    found = False
    changed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") and not stripped.startswith("#"):
            found = True
            value = stripped.split("=", 1)[1].strip() if "=" in stripped else ""
            if not value:
                lines[i] = f"{key}={default_value}"
                changed = True
            break
    if not found:
        lines.append(f"{key}={default_value}")
        changed = True
    if changed:
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"       已设置 {key}")


def main():
    os.chdir(str(PROJECT_DIR))
    print()
    print("  ProtoForge 一键安装并启动 (Windows)")
    print("  物联网协议仿真与测试平台")
    print()

    # Step 1: Check Python version
    print("[1/5] 检查 Python ...")
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

        npm_path = _find_npm()
        if not npm_path:
            print("  [警告] 找到 Node.js 但未找到 npm，将使用仓库中预构建的前端")
            print("  如需构建前端，请重装 Node.js（需包含 npm）: https://nodejs.org/")

        web_dir = PROJECT_DIR / "web"
        if web_dir.exists() and npm_path:
            print("       安装前端依赖...")
            try:
                subprocess.run(
                    [npm_path, "install", "--quiet"], cwd=str(web_dir),
                    capture_output=True,
                )
                print("       构建前端页面...")
                build_result = subprocess.run(
                    [npm_path, "run", "build"], cwd=str(web_dir),
                    capture_output=True, text=True,
                )
            except OSError as e:
                # 兜底：npm 存在但启动失败（权限/环境异常），降级用预构建前端
                print(f"  [警告] npm 启动失败（{e}），将使用仓库中预构建的前端")
            else:
                if build_result.returncode != 0:
                    print("  [警告] 前端构建失败，将使用仓库中已有的前端文件")
                    stderr_tail = (build_result.stderr or "").strip().splitlines()[-3:]
                    for line in stderr_tail:
                        print(f"         {line}")
                else:
                    print("       前端构建成功")

    # Step 5: Initialize config (关键：确保 JWT_SECRET 非空，否则每次重启 token 都失效 → 401)
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

    # 关键修复：确保 .env 中 JWT_SECRET 和 ADMIN_PASSWORD 非空
    # 如果 JWT_SECRET 为空，每次重启都会生成不同的随机密钥，导致所有已登录用户的 token 失效（401 错误）
    _ensure_env_key(env_file, "PROTOFORGE_JWT_SECRET", _generate_jwt_secret(venv_python))
    _ensure_env_key(env_file, "PROTOFORGE_ADMIN_PASSWORD", "admin")
    _ensure_env_key(env_file, "PROTOFORGE_DEMO_MODE", "true")

    # Read port and password from .env
    port = "8000"
    password = "admin"
    if env_file.exists():
        try:
            env_text = _read_env_text(env_file)
            for line in env_text.splitlines():
                line = line.strip()
                if line.startswith("PROTOFORGE_PORT=") and not line.startswith("#"):
                    port = line.split("=", 1)[1].strip()
                elif line.startswith("PROTOFORGE_ADMIN_PASSWORD=") and not line.startswith("#"):
                    password = line.split("=", 1)[1].strip()
        except Exception as e:
            import logging
            logging.warning("读取 .env 配置文件失败: %s", e)

    print()
    print("  +--------------------------------------------------+")
    print("  |                                                  |")
    print("  |   安装成功！正在启动 ProtoForge ...               |")
    print("  |                                                  |")
    print(f"  |   浏览器打开 http://localhost:{port}              |")
    print(f"  |   登录：admin / {'*' * len(password)}                       |")  # FIXED-P0: 密码脱敏显示，不打印明文
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
