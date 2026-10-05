"""ProtoForge 环境自检（`protoforge doctor`）。

v1.5.0 质量护城河的一部分：把 v1.3.x—v1.4.x 修复过的每类部署问题的诊断
逻辑沉淀成一条命令（端口冲突、特权端口、数据库不可写、依赖缺失、Docker
网络拓扑、防火墙提示），让用户在发 issue 之前自己看到答案。

用法::

    protoforge doctor            # 人类可读输出
    protoforge doctor --json     # 机器可读（供 issue 模板/CI 使用）

退出码：0 = 全部通过或仅有警告；1 = 存在 error 级问题。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 各协议的可选依赖（与 pyproject extras 对应）
_PROTOCOL_DEPENDENCIES: dict[str, str] = {
    "modbus_tcp": "pymodbus",
    "modbus_rtu": "pymodbus",
    "opcua": "asyncua",
    "opcda": "pywin32",
    "mqtt": "amqtt",
}

_PRIVILEGED_PORT_NOTE = (
    "特权端口（<1024）在 Linux/Docker 需 root 或 --cap-add NET_BIND_SERVICE；"
    "Windows 可能落在系统保留段。可在高级配置中改用 1024 以上端口。"
)


@dataclass
class CheckResult:
    """单条检查结果。severity: ok / warning / error"""

    check_id: str
    severity: str
    title: str
    detail: str = ""
    fixes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "fixes": self.fixes,
        }


def _is_port_free(port: int, host: str = "0.0.0.0", udp: bool = False) -> bool:
    """探测端口是否可用。

    TCP 用 connect_ex 客户端探测（与引擎 _is_port_in_use 同款，跨平台可靠：
    Windows 的 SO_REUSEADDR 允许重复绑定，bind 探测会漏报占用）。
    UDP 无连接语义，仍用 bind 探测。
    """
    af = socket.AF_INET6 if ":" in host else socket.AF_INET
    if udp:
        try:
            with socket.socket(af, socket.SOCK_DGRAM) as s:
                s.bind((host or "0.0.0.0", port))
                return True
        except OSError:
            return False
    probe_ip = "127.0.0.1" if af == socket.AF_INET else "::1"
    try:
        with socket.socket(af, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex((probe_ip, port)) != 0
    except OSError:
        return True  # 无法探测时按空闲处理，引擎启动预检会兜底


def _in_container() -> bool:
    if os.environ.get("PROTOFORGE_IN_CONTAINER"):
        return True
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def check_environment() -> list[CheckResult]:
    from protoforge.core.paths import is_frozen

    results = [
        CheckResult("sys.platform", "ok", f"操作系统: {sys.platform} / Python {sys.version.split()[0]}"),
    ]
    frozen = is_frozen()
    venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if frozen:
        results.append(CheckResult("sys.venv", "ok", "桌面版（冻结包）：数据随 exe 目录走"))
    else:
        results.append(CheckResult(
            "sys.venv", "ok" if venv else "warning",
            "虚拟环境: " + ("已激活" if venv else "未使用虚拟环境（pip 安装位置可能与系统冲突）"),
            fixes=[] if venv else ["python -m venv venv 并激活后重装依赖"],
        ))
    return results


def check_database(settings: Any) -> list[CheckResult]:
    from protoforge.core.paths import is_frozen

    results = []
    db_path = getattr(settings, "db_path", "data/protoforge.db")
    db_file = Path(db_path.replace("sqlite:///", "").replace("sqlite://", "") or "data/protoforge.db")
    target_dir = db_file.parent if str(db_file.parent) not in ("", ".") else Path(".")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe = target_dir / ".doctor_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        results.append(CheckResult(
            "db.writable", "ok",
            f"数据目录可写: {target_dir}（SQLite 路径 {db_file}）",
        ))
    except (OSError, PermissionError) as e:
        results.append(CheckResult(
            "db.writable", "error",
            f"数据目录不可写: {target_dir}（{e}）——设备/场景配置将无法保存",
            fixes=[
                "检查目录属主与权限，或用 PROTOFORGE_DB_PATH 指向可写位置",
                "Docker 场景确认已挂载数据卷（-v protoforge-data:/app/data）",
            ],
        ))
    frozen = is_frozen()
    if not shutil.which("alembic") and not frozen:
        results.append(CheckResult(
            "db.migrations", "warning",
            "alembic 不可用——数据库迁移命令（protoforge migrate）将失败",
            fixes=["pip install alembic"],
        ))
    return results


def check_dependencies() -> list[CheckResult]:
    results = []
    missing = []
    for name in ("fastapi", "uvicorn", "sqlalchemy", "aiosqlite"):
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    if missing:
        results.append(CheckResult(
            "deps.core", "error", f"核心依赖缺失: {', '.join(missing)}",
            fixes=["pip install -e . 或参考 README 安装说明"],
        ))
    else:
        results.append(CheckResult("deps.core", "ok", "核心依赖完整（fastapi/uvicorn/sqlalchemy/aiosqlite）"))

    installed, optional_missing = [], []
    for proto, module in _PROTOCOL_DEPENDENCIES.items():
        if importlib.util.find_spec(module) is not None:
            installed.append(module)
        else:
            optional_missing.append(f"{proto} 需要 {module}")
    if optional_missing:
        results.append(CheckResult(
            "deps.optional", "warning",
            "部分协议依赖未安装（对应协议服务无法启动）: " + "; ".join(optional_missing),
            detail="已安装: " + (", ".join(sorted(set(installed))) or "无"),
            fixes=["pip install 'protoforge[all]' 安装全部协议依赖"],
        ))
    else:
        results.append(CheckResult("deps.optional", "ok", "协议可选依赖完整（pymodbus/asyncua/amqtt/pywin32）"))

    if importlib.util.find_spec("websockets") is None:
        results.append(CheckResult(
            "deps.websockets", "warning",
            "websockets 未安装——实时调试日志 WebSocket 不可用",
            fixes=["pip install websockets"],
        ))
    return results


def check_web_dist() -> list[CheckResult]:
    from protoforge.core.paths import static_dir

    dist = static_dir()
    if (dist / "index.html").exists():
        return [CheckResult("web.dist", "ok", f"前端静态资源存在: {dist}")]
    return [CheckResult(
        "web.dist", "warning",
        f"web/dist 不存在——后端将没有前端页面（API 仍可用）",
        fixes=["cd web && npm install && npm run build（pip/Docker 安装无需此步）"],
    )]


def check_http_port(settings: Any) -> list[CheckResult]:
    port = int(getattr(settings, "port", 8000))
    if _is_port_free(port):
        return [CheckResult("http.port", "ok", f"Web 端口 {port} 可用")]
    return [CheckResult(
        "http.port", "warning", f"Web 端口 {port} 已被占用——启动会失败或自动换端口",
        fixes=[f"换端口: protoforge run --port {port + 1}",
               f"占用排查: netstat -ano | findstr :{port}（Windows）/ ss -ltnp（Linux）"],
    )]


def check_protocol_ports(settings: Any) -> list[CheckResult]:
    from protoforge.engine.defaults import PROTOCOL_DEFAULTS

    results: list[CheckResult] = []
    seen: dict[int, str] = {}
    privileged: list[str] = []
    in_use: list[str] = []

    for proto, defaults in PROTOCOL_DEFAULTS.items():
        if "port" not in defaults:
            continue
        field = f"{proto}_port"
        port = int(getattr(settings, field, defaults["port"]))
        udp = proto in ("gb28181", "bacnet", "coap", "dds")
        if port < 1024:
            privileged.append(f"{proto}={port}")
        if port in seen:
            in_use.append(f"{proto} 与 {seen[port]} 共用端口 {port}")
        else:
            seen[port] = proto
            if not _is_port_free(port, udp=udp):
                in_use.append(f"{proto} 的端口 {port} 当前被占用（服务启动时将自动换端口）")

    results.append(CheckResult(
        "protocols.privileged_ports", "warning" if privileged else "ok",
        "特权端口协议: " + (", ".join(privileged) if privileged else "无"),
        detail=_PRIVILEGED_PORT_NOTE if privileged else "",
    ))
    if in_use:
        results.append(CheckResult(
            "protocols.ports_in_use", "warning",
            "端口占用/冲突: " + "; ".join(in_use),
            fixes=["在系统设置 → 协议端口 中修改，或停止占用进程"],
        ))
    else:
        results.append(CheckResult("protocols.ports_in_use", "ok", "各协议默认端口无冲突、未被占用"))
    return results


def check_container(settings: Any) -> list[CheckResult]:
    if not _in_container():
        return [CheckResult("env.container", "ok", "运行环境: 宿主机（非容器）")]
    public = getattr(settings, "protoforge_public_host", "") or ""
    return [CheckResult(
        "env.container", "warning",
        f"检测到容器环境（public_host={public or '未设置'}）——容器内网 IP 不可直达，"
        "客户端需连接宿主机 IP + 映射端口",
        fixes=[
            "docker run 时映射协议端口（-p 502:502 -p 102:102 ...）",
            "特权端口需 --cap-add NET_BIND_SERVICE",
            "在系统设置中配置 PROTOFORGE_PUBLIC_HOST 为宿主机地址",
        ],
    )]


def check_env_security(settings: Any) -> list[CheckResult]:
    no_auth = os.environ.get("PROTOFORGE_NO_AUTH", "").lower() in ("1", "true", "yes")
    if no_auth:
        return [CheckResult(
            "env.no_auth", "warning",
            "PROTOFORGE_NO_AUTH 已启用——所有 API 免认证，仅限本机测试使用",
            fixes=["生产环境移除 PROTOFORGE_NO_AUTH 环境变量"],
        )]
    return [CheckResult("env.no_auth", "ok", "API 认证已启用")]


def run_all_checks(settings: Any | None = None) -> list[CheckResult]:
    """执行全部自检（供 CLI 与测试复用）。"""
    if settings is None:
        from protoforge.config import get_settings
        settings = get_settings()
    results: list[CheckResult] = []
    results += check_environment()
    results += check_database(settings)
    results += check_dependencies()
    results += check_web_dist()
    results += check_http_port(settings)
    results += check_protocol_ports(settings)
    results += check_container(settings)
    results += check_env_security(settings)
    return results


def render_text(results: list[CheckResult]) -> str:
    icons = {"ok": "+", "warning": "!", "error": "x"}
    lines = ["", "=" * 62, "  ProtoForge Doctor - 环境自检", "=" * 62, ""]
    has_error = False
    for r in results:
        line = f"  [{icons[r.severity]}] {r.title}"
        lines.append(line)
        if r.detail:
            lines.append(f"        {r.detail}")
        for fix in r.fixes:
            lines.append(f"        -> 建议: {fix}")
        if r.severity == "error":
            has_error = True
    lines.append("")
    lines.append("=" * 62)
    if has_error:
        lines.append("  存在 error 级问题——按上方建议修复后重新运行")
    else:
        lines.append("  自检完成：未发现 error 级问题")
    lines.append("  报 issue 时请附上 `protoforge doctor --json` 的输出")
    lines.append("=" * 62 + "")
    return "\n".join(lines)


def render_json(results: list[CheckResult]) -> str:
    payload = {
        "version": _get_version(),
        "has_errors": any(r.severity == "error" for r in results),
        "checks": [r.as_dict() for r in results],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _get_version() -> str:
    try:
        from protoforge import __version__
        return __version__
    except Exception:
        return "unknown"


def main(json_output: bool = False) -> int:
    from protoforge.config import get_settings
    results = run_all_checks(get_settings())
    if json_output:
        print(render_json(results))
    else:
        print(render_text(results))
    return 1 if any(r.severity == "error" for r in results) else 0
