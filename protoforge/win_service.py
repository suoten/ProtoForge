"""ProtoForge Windows 服务管理（v1.6.0，基于 NSSM）。

`protoforge install-service` / `uninstall-service` 的实现层。与
scripts/install_service.bat 同一套 NSSM 语义（开机自启/崩溃拉起/日志轮转），
但 CLI 版从 pip 安装位置也能用（不要求仓库 checkout）。

设计：参数构建是纯函数（跨平台可测）；实际执行仅在 Windows 上进行。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SERVICE_NAME = "ProtoForge"
LOG_ROTATE_BYTES = 10485760  # 10MB
NSSM_DOWNLOAD_HINT = (
    "NSSM 未找到。请从 https://nssm.cc/download 下载，"
    "把 win64\\nssm.exe 复制到 tools\\nssm.exe（或加入 PATH）后重试。"
)


@dataclass
class ServicePlan:
    """一次服务安装的完整参数（纯数据，可测试）。"""

    service_name: str
    nssm_exe: str
    python_exe: str
    app_dir: str
    port: int
    log_dir: str
    display_name: str = "ProtoForge"
    description: str = "ProtoForge - IoT protocol simulation and testing platform"

    def commands(self) -> list[list[str]]:
        """按顺序执行的 NSSM 命令行（不含 shell）。"""
        n = self.nssm_exe
        py = self.python_exe
        stdout = str(Path(self.log_dir) / "service-out.log")
        stderr = str(Path(self.log_dir) / "service-err.log")
        return [
            [n, "install", self.service_name, py, "-m", "protoforge", "run",
             "--host", "0.0.0.0", "--port", str(self.port)],
            [n, "set", self.service_name, "AppDirectory", self.app_dir],
            [n, "set", self.service_name, "AppStdout", stdout],
            [n, "set", self.service_name, "AppStderr", stderr],
            [n, "set", self.service_name, "AppRotateFiles", "1"],
            [n, "set", self.service_name, "AppRotateOnline", "1"],
            [n, "set", self.service_name, "AppRotateBytes", str(LOG_ROTATE_BYTES)],
            [n, "set", self.service_name, "AppExit", "Default", "Restart"],
            [n, "set", self.service_name, "AppRestartDelay", "5000"],
            [n, "set", self.service_name, "DisplayName", self.display_name],
            [n, "set", self.service_name, "Description", self.description],
            [n, "set", self.service_name, "Start", "SERVICE_AUTO_START"],
            [n, "start", self.service_name],
        ]

    def uninstall_commands(self) -> list[list[str]]:
        n = self.nssm_exe
        return [
            [n, "stop", self.service_name],
            [n, "remove", self.service_name, "confirm"],
        ]


def find_nssm(project_root: Path | None = None) -> str | None:
    """定位 NSSM：PATH > <root>/tools/nssm.exe > CWD/tools/nssm.exe。"""
    which = shutil.which("nssm")
    if which:
        return which
    roots = []
    if project_root:
        roots.append(project_root / "tools" / "nssm.exe")
    roots.append(Path.cwd() / "tools" / "nssm.exe")
    for p in roots:
        if p.is_file():
            return str(p)
    return None


def build_plan(nssm_exe: str, python_exe: str | None = None, app_dir: str | None = None,
               port: int = 18080, service_name: str = SERVICE_NAME,
               log_dir: str | None = None) -> ServicePlan:
    """从运行环境推导安装计划（冻结模式数据随 exe 走；开发模式随仓库/CWD）。"""
    from protoforge.core.paths import is_frozen

    if app_dir:
        root = Path(app_dir)
    elif is_frozen():
        root = Path(sys.executable).resolve().parent
    else:
        root = Path.cwd()
    py = python_exe or sys.executable
    logs = log_dir or str(Path(root) / "logs")
    return ServicePlan(
        service_name=service_name,
        nssm_exe=nssm_exe,
        python_exe=str(Path(py).resolve()),
        app_dir=str(root),
        port=port,
        log_dir=logs,
    )


def is_admin() -> bool:
    """当前进程是否有管理员权限（仅 Windows 有意义）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def execute(plan: ServicePlan, runner: Callable[[list[str]], int] | None = None) -> int:
    """按计划顺序执行命令；任何一步非 0 退出即中止。"""
    run = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True).returncode)
    for cmd in plan.commands():
        code = run(cmd)
        if code != 0:
            print(f"! 命令失败（exit {code}）: {' '.join(cmd)}")
            return code
    return 0


def execute_uninstall(plan: ServicePlan, runner: Callable[[list[str]], int] | None = None) -> int:
    run = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True).returncode)
    for cmd in plan.uninstall_commands():
        run(cmd)  # stop/remove 失败不致命（服务可能本就不存在）
    return 0


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def cmd_install_service(port: int, service_name: str = SERVICE_NAME,
                        python_exe: str | None = None) -> int:
    if sys.platform != "win32":
        print("! Windows 服务仅支持 Windows；Linux 请使用 systemd：")
        print("  https://github.com/suoten/ProtoForge/blob/master/DEPLOYMENT.md")
        return 1
    if not is_admin():
        print("! 需要管理员权限：请以管理员身份运行终端后重试")
        return 1
    nssm = find_nssm()
    if not nssm:
        print(f"! {NSSM_DOWNLOAD_HINT}")
        return 1
    plan = build_plan(nssm, python_exe=python_exe, port=port, service_name=service_name)
    print(f"+ 安装服务 {plan.service_name}（端口 {plan.port}）")
    print(f"  python : {plan.python_exe}")
    print(f"  workdir: {plan.app_dir}")
    code = execute(plan)
    if code == 0:
        print(f"+ 服务已安装并启动: http://localhost:{plan.port}")
        print(f"  管理员密码在 logs\\service-out.log 的启动横幅（Admin: ...）")
        print(f"  卸载: protoforge uninstall-service")
    return code


def cmd_uninstall_service(service_name: str = SERVICE_NAME) -> int:
    if sys.platform != "win32":
        print("! Windows 服务仅支持 Windows")
        return 1
    if not is_admin():
        print("! 需要管理员权限：请以管理员身份运行终端后重试")
        return 1
    nssm = find_nssm()
    if not nssm:
        print(f"! {NSSM_DOWNLOAD_HINT}")
        return 1
    plan = build_plan(nssm, service_name=service_name)
    code = execute_uninstall(plan)
    if code == 0:
        print(f"+ 服务 {plan.service_name} 已停止并移除")
    return code
