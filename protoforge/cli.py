"""ProtoForge command-line interface entry point."""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _load_dotenv_to_environ():
    """Load .env file values into os.environ if not already set.

    pydantic-settings reads .env internally but doesn't set os.environ.
    This ensures cli.py can read PROTOFORGE_ADMIN_PASSWORD via os.environ.get().
    """
    from pathlib import Path
    # FIXED(v1.6.0): 走 app_root（冻结模式 = exe 旁 .env），与 config 层同源
    try:
        from protoforge.core.paths import app_root as _app_root
        env_file = _app_root() / ".env"
    except Exception as e:
        logger.debug("_load_dotenv_to_environ: ignored exception: %s", e)
        env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    try:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("加载 .env 文件失败: %s", e)


def main():
    _load_dotenv_to_environ()

    # Note: get_settings() is NOT called here because demo_mode env var is set
    # AFTER this point (in _run_server). Calling get_settings() here would
    # cache the old demo_mode value from .env, breaking 'protoforge demo' command.

    # Import settings lazily inside _run_server so demo_mode env var is already set
    from protoforge.config import get_settings
    settings = get_settings()
    default_host = settings.host
    default_port = settings.port

    parser = argparse.ArgumentParser(
        prog="protoforge",
        description="ProtoForge - IoT Protocol Simulation & Testing Platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    run_parser = subparsers.add_parser("run", help="Start ProtoForge server")
    run_parser.add_argument("--host", default=default_host, help=f"Listen address (default: {default_host})")
    run_parser.add_argument("--port", type=int, default=default_port, help=f"Listen port (default: {default_port})")
    run_parser.add_argument("--reload", action="store_true", help="Enable hot reload for development")
    run_parser.add_argument("--log-level", default="info", help="Log level (debug/info/warning/error)")
    run_parser.add_argument("--daemon", "-d", action="store_true", help="Run as background daemon (survives terminal close)")

    demo_parser = subparsers.add_parser("demo", help="Start demo mode with sample devices")
    demo_parser.add_argument("--host", default=default_host, help="Listen address")
    demo_parser.add_argument("--port", type=int, default=default_port, help="Listen port")
    demo_parser.add_argument("--daemon", "-d", action="store_true", help="Run as background daemon (survives terminal close)")

    subparsers.add_parser("version", help="Show version")

    doctor_parser = subparsers.add_parser(
        "doctor", help="Environment self-check (ports, DB, deps, container hints)")
    doctor_parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    desktop_parser = subparsers.add_parser(
        "desktop", help="Desktop mode: start server and auto-open the web UI (v1.6.0)")
    desktop_parser.add_argument("--host", default=None, help="Bind address (default: PROTOFORGE_HOST env or 127.0.0.1; set 0.0.0.0 for LAN access)")
    desktop_parser.add_argument("--port", type=int, default=18080, help="HTTP port (default: 18080)")
    desktop_parser.add_argument("--native", action="store_true",
                                help="Prefer native window (requires pywebview; falls back to browser)")
    desktop_parser.add_argument("--no-tray", action="store_true", help="Disable system tray (if available)")
    desktop_parser.add_argument("--no-update-check", action="store_true", help="Skip update check on start")
    desktop_parser.add_argument("--log-level", default="info", help="Log level (debug/info/warning/error)")

    svc_install = subparsers.add_parser(
        "install-service", help="Install ProtoForge as a Windows service via NSSM (admin required)")
    svc_install.add_argument("--port", type=int, default=18080, help="HTTP port for the service (default: 18080)")
    svc_install.add_argument("--name", default="ProtoForge", help="Service name (default: ProtoForge)")
    svc_install.add_argument("--python", default="", help="Python executable to run (default: current interpreter)")

    svc_uninstall = subparsers.add_parser(
        "uninstall-service", help="Stop and remove the ProtoForge Windows service (admin required)")
    svc_uninstall.add_argument("--name", default="ProtoForge", help="Service name (default: ProtoForge)")

    subparsers.add_parser("init", help="Initialize data directory and default config")

    migrate_parser = subparsers.add_parser("migrate", help="Run database migrations")
    migrate_parser.add_argument("--revision", default="head", help="Target revision (default: head)")

    subparsers.add_parser("stop", help="Stop background daemon").add_argument(
        "--port", type=int, default=8000,
        help="Server port for PID-file-less lookup on Windows (default 8000)",
    )

    audit_parser = subparsers.add_parser("audit", help="Run automated audit checks (3-layer consistency)")
    audit_parser.add_argument("--layer", choices=["1", "2", "3", "all"], default="all",
                              help="Which layer to run: 1=schema, 2=api-types, 3=exception-lint (default: all)")
    audit_parser.add_argument("--severity", choices=["error", "warning", "info"], default="warning",
                              help="Minimum severity for Layer 3 (default: warning)")
    audit_parser.add_argument("--web-dir", default="web", help="Path to web/ directory for Layer 2")
    audit_parser.add_argument("--openapi-file", default="", help="Path to openapi.json for Layer 2")

    bench_parser = subparsers.add_parser("benchmark", help="Performance benchmark commands (v1.11.0)")
    bench_sub = bench_parser.add_subparsers(dest="bench_command", help="Benchmark commands")
    bench_sub.add_parser("scenarios", help="List built-in benchmark scenarios")
    bench_list = bench_sub.add_parser("list", help="List saved benchmark results")
    bench_list.add_argument("--scenario", default="", help="Filter by scenario name")
    bench_run = bench_sub.add_parser("run", help="Run a benchmark scenario (CI-able)")
    bench_run.add_argument("--scenario", required=True, help="Scenario name (see: protoforge benchmark scenarios)")
    bench_run.add_argument("--params", default="{}", help="Scenario params as JSON, e.g. '{\"devices\": 500}'")
    bench_run.add_argument("--label", default="", help="Optional label for the result")
    bench_run.add_argument("--compare-to", default="", help="Result id to compare against (regression >10%% -> exit 1)")
    bench_run.add_argument("--wait", type=int, default=600, help="Max seconds to wait for completion")
    for sp in (bench_run, bench_list):
        sp.add_argument("--server", default="http://localhost:8000", help="ProtoForge server URL")
        sp.add_argument("--token", default="", help="Authentication token")

    env_parser = subparsers.add_parser("env", help="Environment-as-code commands (v1.10.0)")
    env_sub = env_parser.add_subparsers(dest="env_command", help="Env commands")
    for sub_name, sub_help in (("export", "Export current environment to YAML manifest"),
                               ("apply", "Apply a YAML manifest to the running server"),
                               ("diff", "Diff current environment against a manifest")):
        sp = env_sub.add_parser(sub_name, help=sub_help)
        if sub_name == "export":
            sp.add_argument("output", nargs="?", default="-", help="Output YAML path (default: stdout)")
            sp.add_argument("--name", default="exported-env", help="Manifest metadata.name")
        else:
            sp.add_argument("manifest", help="YAML manifest file path")
            sp.add_argument("--dry-run", action="store_true", help="apply: report only, change nothing")
        sp.add_argument("--server", default="http://localhost:8000", help="ProtoForge server URL")
        sp.add_argument("--token", default="", help="Authentication token")

    baseline_parser = subparsers.add_parser("baseline", help="Data baseline commands (v1.10.0)")
    baseline_sub = baseline_parser.add_subparsers(dest="baseline_command", help="Baseline commands")
    cap_p = baseline_sub.add_parser("capture", help="Capture current point values as a baseline")
    cap_p.add_argument("name", help="Baseline name")
    cap_p.add_argument("--devices", default="", help="Comma-separated device IDs (default: all)")
    cap_p.add_argument("--tolerance", type=float, default=0.0, help="Default numeric tolerance")
    cmp_p = baseline_sub.add_parser("compare", help="Compare current values against a baseline")
    cmp_p.add_argument("name", help="Baseline name")
    cmp_p.add_argument("--output", "-o", default="", help="Save JSON report to file")
    for sp in (cap_p, cmp_p):
        sp.add_argument("--server", default="http://localhost:8000", help="ProtoForge server URL")
        sp.add_argument("--token", default="", help="Authentication token")

    test_parser = subparsers.add_parser("test", help="CI/CD test execution commands")
    test_sub = test_parser.add_subparsers(dest="test_command", help="Test commands")
    test_run_parser = test_sub.add_parser("run", help="Run a test plan")
    test_run_parser.add_argument("--plan", required=True, help="Test plan ID")
    test_run_parser.add_argument("--server", default="http://localhost:8000", help="ProtoForge server URL")
    test_run_parser.add_argument("--token", default="", help="Authentication token")
    test_run_parser.add_argument("--format", choices=["junit", "json", "html"], default="junit",
                                 help="Output format (default: junit)")
    test_run_parser.add_argument("--output", "-o", default="", help="Output file path (default: stdout)")
    test_run_parser.add_argument("--timeout", type=int, default=300, help="Execution timeout in seconds (default: 300)")

    mcp_parser = subparsers.add_parser(
        "mcp", help="MCP server: let Claude/Cursor etc. drive the simulator (v1.13.0)")
    mcp_parser.add_argument("--server", default="",
                            help="ProtoForge server URL (default: PROTOFORGE_MCP_URL or http://localhost:8000)")
    mcp_parser.add_argument("--username", default="",
                            help="Login username (default: PROTOFORGE_MCP_USERNAME or admin)")
    mcp_parser.add_argument("--password", default="",
                            help="Login password (default: PROTOFORGE_MCP_PASSWORD or admin)")
    mcp_parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio",
                            help="MCP transport (default: stdio for desktop clients)")
    mcp_parser.add_argument("--host", default="127.0.0.1", help="Bind address for streamable-http (default: 127.0.0.1)")
    mcp_parser.add_argument("--port", type=int, default=8808, help="HTTP port for streamable-http (default: 8808)")

    ai_parser = subparsers.add_parser(
        "ai", help="AI 点表导入：LLM 解析说明书/寄存器表 → 设备配置（v1.13.1，默认本地 Ollama）")
    ai_sub = ai_parser.add_subparsers(dest="ai_command", help="AI commands")
    ai_sub.add_parser("check", help="检查 LLM 服务连通性并列出可用模型")
    ai_ext = ai_sub.add_parser("extract-points", help="解析文本文件为设备配置 JSON（不创建设备）")
    ai_ext.add_argument("file", help="说明书/寄存器表文本文件路径（utf-8）")
    ai_ext.add_argument("--protocol", default="", help="目标协议提示（如 modbus_tcp）")
    ai_ext.add_argument("--output", "-o", default="", help="保存 JSON 到文件（默认 stdout）")
    ai_create = ai_sub.add_parser("create-device", help="一步到位：解析文本并创建+自动启动仿真设备")
    ai_create.add_argument("file", help="说明书/寄存器表文本文件路径（utf-8）")
    ai_create.add_argument("--name", default="", help="设备名（默认用 LLM 提取的设备名）")
    ai_create.add_argument("--device-id", default="", help="设备 ID（默认按名称自动生成）")
    ai_create.add_argument("--protocol", default="", help="目标协议提示（如 modbus_tcp）")
    ai_diag = ai_sub.add_parser("diagnose", help="AI 调试排障：分析调试日志 → 结构化诊断（每条结论带日志出处，v1.13.4）")
    ai_diag.add_argument("--device", default="", help="只分析指定设备的日志")
    ai_diag.add_argument("--protocol", default="", help="只分析指定协议的日志（如 modbus_tcp）")
    ai_diag.add_argument("--direction", default="", help="方向过滤（inbound/outbound/system）")
    ai_diag.add_argument("--count", type=int, default=200, help="分析的日志条数（默认 200）")
    ai_diag.add_argument("--question", default="", help="具体问题（如：为什么 HMI 通讯中断）")
    ai_diag.add_argument("--output", "-o", default="", help="保存 JSON 到文件（默认 stdout）")
    for _sp in (ai_ext, ai_create, ai_diag):
        _sp.add_argument("--server", default="http://localhost:8000", help="ProtoForge server URL")
        _sp.add_argument("--token", default="", help="Authentication token")

    args = parser.parse_args()

    if args.command == "version":
        from protoforge import __version__  # FIXED: 引用__version__单一来源，避免硬编码版本号
        print(f"ProtoForge v{__version__} - IoT Protocol Simulation & Testing Platform")
        return

    if args.command == "doctor":
        from protoforge.doctor import main as doctor_main
        sys.exit(doctor_main(json_output=bool(getattr(args, "json", False))))

    if args.command == "desktop":
        from protoforge.desktop import run_desktop
        return run_desktop(
            host=args.host,
            port=args.port,
            prefer_native=args.native,
            use_tray=not args.no_tray,
            check_updates=not args.no_update_check,
            log_level=args.log_level,
        )

    if args.command == "install-service":
        from protoforge.win_service import cmd_install_service
        return cmd_install_service(
            port=args.port, service_name=args.name,
            python_exe=args.python or None,
        )

    if args.command == "uninstall-service":
        from protoforge.win_service import cmd_uninstall_service
        return cmd_uninstall_service(service_name=args.name)

    if args.command == "init":
        _init_command()
        return

    if args.command == "migrate":
        _migrate_command(getattr(args, "revision", "head"))
        return

    if args.command == "stop":
        _stop_command(port=getattr(args, "port", 8000))
        return

    if args.command == "audit":
        _audit_command(args)
        return

    if args.command == "test":
        _test_command(args)
        return

    if args.command == "benchmark":
        _benchmark_command(args)
        return

    if args.command == "env":
        _env_command(args)
        return

    if args.command == "baseline":
        _baseline_command(args)
        return

    if args.command == "mcp":
        from protoforge.mcp_server import run_mcp
        return run_mcp(server_url=args.server, username=args.username, password=args.password,
                       transport=args.transport, host=args.host, port=args.port)

    if args.command == "ai":
        _ai_command(args)
        return

    if args.command == "demo":
        _run_server(host=args.host, port=args.port, demo_mode=True, daemon=getattr(args, "daemon", False))
        return

    if args.command == "run" or args.command is None:
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8000)
        reload = getattr(args, "reload", False)
        log_level = getattr(args, "log_level", "info")
        daemon = getattr(args, "daemon", False)
        _run_server(host=host, port=port, reload=reload, log_level=log_level, daemon=daemon)
        return

    parser.print_help()
    return


def _get_pid_file():
    from pathlib import Path
    return Path("data") / "protoforge.pid"


def _get_log_file():
    from pathlib import Path
    return Path("logs") / "protoforge.log"


def _write_pid_file():
    """FIXED(Issue#12): 记录当前进程 PID 到 data/protoforge.pid。

    此前仅在 Unix daemon 分支写入，Windows 上 'start /B' 后台启动永远没有
    PID 文件，导致 'protoforge stop' 提示找不到后台服务。现在所有启动方式
    （前台 / 后台 / daemon）都记录 PID，stop 在全平台可用。
    """
    pid_file = _get_pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    import atexit
    atexit.register(lambda: pid_file.unlink(missing_ok=True))


def _process_alive(pid: int) -> bool:
    """跨平台安全地探测进程是否存活。

    FIXED(Issue#12): 此前用 os.kill(pid, 0) 探测，但在 Windows 上
    os.kill 对非 CTRL_* 信号一律走 TerminateProcess —— sig=0 会把目标进程
    直接杀死（退出码 0），"存活探测"变成"误杀"。
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import subprocess
        import time
        # FIXED(Issue#12): tasklist 偶发超时不轻判"已停止"，重试一次；
        # 探测误报 False 会导致 stop 跳过仍在运行的服务
        for _attempt in range(2):
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],  # noqa: S607,S603
                    capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace",
                )
                if f"\"{pid}\"" in result.stdout:
                    return True
                # 无匹配行 = 进程确实不存在（tasklist 正常完成时可靠）
                if result.returncode == 0 and result.stdout.strip():
                    return False
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(1.0)
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # 进程存在但无权限发信号（如他人进程）——视为存活
        return True


def _win_terminate(pid: int) -> bool:
    """Windows 兑底：直接 TerminateProcess 主进程（不含子进程树）。

    taskkill 超时或不可用时使用；返回是否成功发起终止。
    """
    try:
        import ctypes
        PROCESS_TERMINATE = 0x0001
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(ctypes.windll.kernel32.TerminateProcess(handle, 1))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception as e:  # noqa: BLE001 — 兑底路径，任何异常都不能阻断 stop 流程
        logger.warning("TerminateProcess fallback failed for PID %s: %s", pid, e)
        _swallowed = False
        return _swallowed


def _find_pid_by_port(port: int) -> int | None:
    """Windows 兑底：查找监听指定端口且属于 python 进程的 PID。

    用于 'start /B' 后台启动且 PID 文件丢失（如服务未优雅退出残留、
    手动删除 data 目录）的场景。校验进程镜像名为 python*，避免 PID
    复用时误杀无关应用。
    """
    if sys.platform != "win32":
        return None
    import re as _re
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],  # noqa: S607,S603
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        # 形如: TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  12345
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].rsplit(":", 1)[-1] == str(port):
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    continue
    for pid in pids:
        try:
            check = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],  # noqa: S607,S603
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            if _re.search(r'"python', check.stdout, _re.IGNORECASE):
                return pid
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _stop_command(port: int = 8000):
    pid_file = _get_pid_file()
    pid = None
    if pid_file.exists():
        try:  # FIXED: 添加异常保护，PID文件内容可能损坏
            pid = int(pid_file.read_text().strip())
        except (ValueError, OSError) as e:
            print(f"! Invalid PID file: {e}")
            pid_file.unlink(missing_ok=True)
    if pid is None:
        # FIXED(Issue#12): Windows 'start /B' 后台启动没有 PID 文件时按端口兑底
        found = _find_pid_by_port(port)
        if found is None:
            print("! No background daemon found (PID file not found)")
            hint = "" if sys.platform == "win32" else "  On Linux/macOS use: protoforge run --daemon"
            print(f"  Also tried: no python process listening on port {port}.{hint}")
            return
        pid = found
        print(f"+ Found ProtoForge process by port {port}: PID {pid}")
    if not _process_alive(pid):
        print(f"! Process {pid} not found (may have already stopped)")
        pid_file.unlink(missing_ok=True)
        return

    if sys.platform == "win32":
        # Windows 没有 SIGTERM：taskkill /T 杀进程树（含 uvicorn reload 子进程）、/F 强制。
        # SQLite 为崩溃安全设计，强杀不会损坏数据。
        import subprocess
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],  # noqa: S607,S603
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as e:
            # taskkill 超时/不可用时兜底：直接 TerminateProcess 主进程
            logger.warning("taskkill failed for PID %s (%s), falling back to TerminateProcess", pid, e)
            if not _win_terminate(pid):
                print(f"! Failed to stop process {pid}: {e}")
                return
        import time
        for _i in range(10):
            if not _process_alive(pid):
                print(f"+ Daemon (PID {pid}) stopped")
                break
            time.sleep(0.5)
        else:
            print(f"! Process {pid} still running after taskkill")
        pid_file.unlink(missing_ok=True)
        return

    # Unix: SIGTERM 优雅退出，超时后 SIGKILL
    try:
        os.kill(pid, 15)  # SIGTERM
        print(f"+ Sent SIGTERM to daemon (PID {pid})")
    except ProcessLookupError:
        print(f"! Process {pid} not found (may have already stopped)")
        pid_file.unlink(missing_ok=True)
        return
    except PermissionError:
        print(f"! Permission denied to stop process {pid}")
        pid_file.unlink(missing_ok=True)
        return

    import time
    for _i in range(30):
        if not _process_alive(pid):
            print(f"+ Daemon (PID {pid}) stopped gracefully")
            pid_file.unlink(missing_ok=True)
            return
        time.sleep(0.5)

    # 超时，强制杀死
    try:
        os.kill(pid, 9)  # SIGKILL
        print(f"! Daemon (PID {pid}) did not stop gracefully, sent SIGKILL")
    except ProcessLookupError:
        print(f"+ Daemon (PID {pid}) stopped")
    except PermissionError:
        print(f"! Permission denied to kill process {pid}")
    finally:
        pid_file.unlink(missing_ok=True)


def _daemonize():
    """Double-fork to fully detach from terminal (Linux/Unix only)."""
    import signal
    import sys as _sys

    if _sys.platform == "win32":
        return  # Daemon mode not supported on Windows

    # First fork
    pid = os.fork()  # type: ignore[attr-defined]
    if pid > 0:
        # Parent exits immediately
        os._exit(0)

    # Child becomes session leader
    os.setsid()  # type: ignore[attr-defined]

    # Second fork
    pid = os.fork()  # type: ignore[attr-defined]
    if pid > 0:
        os._exit(0)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    log_file = _get_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # FIXED: P4 - W29 使用 with 语句包裹 open()，确保文件描述符关闭
    with open(os.devnull) as si, \
         open(str(log_file), 'a') as so, \
         open(str(log_file), 'a') as se:
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

    # Ignore SIGHUP
    signal.signal(signal.SIGHUP, signal.SIG_IGN)  # type: ignore[attr-defined]


def _init_command():
    import shutil
    from pathlib import Path
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    env_example = Path(".env.example")
    env_file = Path(".env")
    if env_example.exists() and not env_file.exists():
        try:
            shutil.copy(env_example, env_file)
            print("+ Created .env from .env.example")
        except (OSError, PermissionError) as e:
            print(f"! Failed to create .env: {e}")
    print("+ Data directory created: data/")
    print("+ Done! Run 'protoforge run' to start the server")
    print("  or run 'protoforge demo' for a quick demo")


def _migrate_command(revision: str = "head"):
    import subprocess
    print(f"Running database migration to revision: {revision}")
    try:
        result = subprocess.run(
            ["alembic", "upgrade", revision],  # noqa: S607
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            print("+ Database migration completed")
        else:
            print(f"! Migration failed:\n{result.stderr}")
            sys.exit(1)
    except FileNotFoundError:
        print("! alembic not found. Install it: pip install alembic")
        sys.exit(1)


def _audit_command(args):
    """Run the 3-layer automated audit."""
    import asyncio
    from pathlib import Path

    layer = getattr(args, "layer", "all")
    severity = getattr(args, "severity", "warning")
    web_dir = getattr(args, "web_dir", "web")
    openapi_file = getattr(args, "openapi_file", "")
    project_root = Path.cwd()
    has_errors = False

    print("\n" + "=" * 60)
    print("  ProtoForge Automated Audit - 3-Layer Consistency Check")
    print("=" * 60 + "\n")

    # Layer 1: Schema audit (Pydantic model <-> DB column)
    if layer in ("1", "all"):
        print("--- Layer 1: Pydantic Model <-> DB Column Cross-Check ---\n")
        try:
            from protoforge.audit.schema_audit import audit_schema_sync, scan_all_response_models

            # Static check (no DB required)
            result = audit_schema_sync()
            print(result.summary())

            # Check for unregistered models
            unregistered = scan_all_response_models()
            if unregistered:
                print("\nUnregistered Response models (not in _MODEL_TABLE_MAP or _VIRTUAL_MODELS):")
                for name, module, fields in unregistered:
                    print(f"  {name} ({module}): {sorted(fields)}")

            # Try runtime check with DB if available
            try:
                from protoforge.config import get_settings
                settings = get_settings()
                from protoforge.db.session import Database
                db = Database(db_path=settings.db_path)
                asyncio.run(db.connect())
                try:
                    from protoforge.audit.schema_audit import audit_schema
                    runtime_result = asyncio.run(audit_schema(db))
                    if runtime_result.mismatches:
                        print("\nRuntime schema check (with DB):")
                        print(runtime_result.summary())
                        has_errors = True
                    else:
                        print("\nRuntime schema check: PASSED")
                finally:
                    asyncio.run(db.close())
            except Exception as e:
                print(f"\n(Runtime DB check skipped: {e})")

        except Exception as e:
            print(f"! Layer 1 failed: {e}")
            has_errors = True
        print()

    # Layer 2: Frontend API <-> Backend OpenAPI cross-check
    if layer in ("2", "all"):
        print("--- Layer 2: Frontend API <-> Backend OpenAPI Cross-Check ---\n")
        try:
            import subprocess
            cmd = [sys.executable, str(project_root / "scripts" / "audit_api_types.py")]
            if openapi_file:
                cmd.extend(["--openapi-file", openapi_file])
            cmd.extend(["--web-dir", web_dir])
            layer2_result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(layer2_result.stdout)
            if layer2_result.stderr:
                print(layer2_result.stderr)
            if layer2_result.returncode != 0:
                has_errors = True
        except Exception as e:
            print(f"! Layer 2 failed: {e}")
            has_errors = True
        print()

    # Layer 3: Exception handling pattern scan
    if layer in ("3", "all"):
        print("--- Layer 3: Exception Handling Pattern Scan ---\n")
        try:
            import subprocess
            cmd = [sys.executable, "-m", "protoforge.audit.exception_lint", "protoforge",
                   "--severity", severity, "--max-violations", "50"]
            layer3_result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(layer3_result.stdout)
            if layer3_result.stderr:
                print(layer3_result.stderr)
            if layer3_result.returncode != 0:
                has_errors = True
        except Exception as e:
            print(f"! Layer 3 failed: {e}")
            has_errors = True
        print()

    # Summary
    print("=" * 60)
    if has_errors:
        print("  Audit completed with ERRORS - please fix the issues above")
    else:
        print("  Audit completed - all checks passed")
    print("=" * 60 + "\n")

    if has_errors:
        sys.exit(1)


def _api_request(server: str, method: str, path: str, token: str = "",
                 payload=None, timeout: int = 60):
    import requests

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{server.rstrip('/')}{path}"
    try:
        r = requests.request(method, url, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.ConnectionError:
        print(f"! Cannot connect to ProtoForge server at {server}")
        print("  Make sure the server is running: protoforge run")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"! API error: {e}")
        if e.response is not None:
            print(f"  Response: {e.response.text[:500]}")
        sys.exit(1)


def _benchmark_command(args):
    """benchmark scenarios/list/run — 性能基准（v1.11.0，可进 CI）。"""
    import json as _json
    import time as _time

    cmd = getattr(args, "bench_command", None)
    server = args.server.rstrip("/")

    if cmd == "scenarios":
        r = _api_request(server, "GET", "/api/v1/benchmarks/scenarios", args.token)
        for sc in r.json()["scenarios"]:
            print(f"{sc['name']:24} {sc['description']}")
            print(f"{'':24} params: {_json.dumps(sc['params'])}")
        return

    if cmd == "list":
        path = "/api/v1/benchmarks" + (f"?scenario={args.scenario}" if args.scenario else "")
        r = _api_request(server, "GET", path, args.token)
        for b in r.json()["benchmarks"]:
            m = b.get("metrics", {})
            key = next((k for k in ("latency_p95_ms", "tick_avg_ms", "throughput_rps")
                        if k in m), "")
            print(f"{b['id']}  {b['scenario']:24} {key}={m.get(key, '-')}  "
                  f"ts={_time.strftime('%Y-%m-%d %H:%M', _time.localtime(b.get('timestamp') or 0))}"
                  + (f"  label={b['label']}" if b.get("label") else ""))
        return

    if cmd == "run":
        try:
            params = _json.loads(args.params)
        except _json.JSONDecodeError as e:
            print(f"! --params is not valid JSON: {e}")
            sys.exit(1)
        payload = {"scenario": args.scenario, "params": params, "label": args.label}
        r = _api_request(server, "POST", "/api/v1/benchmarks/run", args.token,
                         payload, timeout=30)
        bench_id = r.json()["id"]
        print(f"+ Benchmark queued: {bench_id}")

        deadline = _time.time() + args.wait
        while _time.time() < deadline:
            _time.sleep(2)
            r2 = _api_request(server, "GET", f"/api/v1/benchmarks/{bench_id}",
                              args.token, timeout=15)
            data = r2.json()
            if data.get("status") == "running":
                continue
            if data.get("status") == "failed":
                print(f"! Benchmark failed: {data.get('error')}")
                sys.exit(1)
            result = data["result"]
            print(f"+ Completed in {result.get('duration_seconds')}s")
            for k, v in result.get("metrics", {}).items():
                print(f"  {k:24} {v}")
            env = result.get("env", {})
            print(f"  env: python={env.get('python')} {env.get('platform')} "
                  f"cpu={env.get('cpu_count')}")
            if args.compare_to:
                rc = _api_request(server, "GET",
                                  f"/api/v1/benchmarks/compare?a={args.compare_to}&b={bench_id}",
                                  args.token)
                cmp_data = rc.json()
                for reg in cmp_data.get("regressions", []):
                    print(f"  ! REGRESSION {reg['metric']}: "
                          f"{reg['before']} -> {reg['after']} (+{reg['delta_pct']:.1%})")
                if not cmp_data.get("ok"):
                    print("! Performance regression detected (>10% on latency/duration)")
                    sys.exit(1)
                print("+ No regression above threshold.")
            sys.exit(0)
        print(f"! Timed out waiting for benchmark {bench_id}")
        sys.exit(1)

    print("Usage: protoforge benchmark {scenarios|list|run} ...")
    sys.exit(1)


def _env_command(args):
    """env export/apply/diff — 环境即代码（v1.10.0）。"""
    from pathlib import Path

    cmd = getattr(args, "env_command", None)
    server = args.server.rstrip("/")

    if cmd == "export":
        r = _api_request(server, "POST", "/api/v1/env/export", args.token,
                         {"name": args.name})
        yaml_text = r.json()["yaml"]
        if args.output == "-":
            print(yaml_text)
        else:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(yaml_text, encoding="utf-8")
            print(f"+ Manifest saved to: {args.output}")
        return

    if cmd == "apply":
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"! Manifest not found: {manifest_path}")
            sys.exit(1)
        yaml_text = manifest_path.read_text(encoding="utf-8")
        r = _api_request(server, "POST", "/api/v1/env/apply", args.token,
                         {"yaml_text": yaml_text, "dry_run": args.dry_run}, timeout=300)
        report = r.json()
        tag = "(dry run) " if report.get("dry_run") else ""
        print(f"+ {tag}Created: {len(report.get('created', []))}"
              f"  Updated: {len(report.get('updated', []))}"
              f"  Failed: {len(report.get('failed', []))}")
        for d in report.get("created", []):
            print(f"  + {d}")
        for d in report.get("updated", []):
            print(f"  ~ {d}")
        for f in report.get("failed", []):
            print(f"  ! {f.get('device_id')}: {f.get('error')}")
        sys.exit(0 if not report.get("failed") else 1)

    if cmd == "diff":
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"! Manifest not found: {manifest_path}")
            sys.exit(1)
        yaml_text = manifest_path.read_text(encoding="utf-8")
        r = _api_request(server, "POST", "/api/v1/env/diff", args.token,
                         {"yaml_text": yaml_text})
        data = r.json()
        if data.get("in_sync"):
            print("+ Environment is in sync with the manifest.")
            sys.exit(0)
        print(f"! {data['total']} difference(s):")
        for e in data.get("entries", []):
            print(f"  [{e['kind']:7}] {e['device_id']}: {e.get('detail', '')}")
        sys.exit(1)

    print("Usage: protoforge env {export|apply|diff} ...")
    sys.exit(1)


def _baseline_command(args):
    """baseline capture/compare — 数据基线与回归对比（v1.10.0）。"""
    import json as _json
    from pathlib import Path

    cmd = getattr(args, "baseline_command", None)
    server = args.server.rstrip("/")

    if cmd == "capture":
        payload = {"name": args.name, "default_tolerance": args.tolerance}
        if args.devices:
            payload["device_ids"] = [d.strip() for d in args.devices.split(",") if d.strip()]
        r = _api_request(server, "POST", "/api/v1/baselines", args.token, payload)
        data = r.json()
        print(f"+ Baseline '{data['name']}' saved: "
              f"{data['device_count']} device(s), {data['point_count']} point(s)")
        return

    if cmd == "compare":
        r = _api_request(server, "POST", f"/api/v1/baselines/{args.name}/compare",
                         args.token, {}, timeout=120)
        data = r.json()
        print(f"+ Baseline comparison '{data['baseline_name']}': "
              f"{data['passed']}/{data['total']} passed ({data['pass_rate']:.1%})")
        for v in data.get("violations", []):
            print(f"  ! {v['device_id']}/{v['point']}: "
                  f"baseline={v['baseline']} actual={v['actual']} "
                  f"delta={v['delta']} tol={v['tolerance']} ({v['reason']})")
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(
                _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"+ Report saved to: {args.output}")
        sys.exit(0 if data.get("ok") else 1)

    print("Usage: protoforge baseline {capture|compare} ...")
    sys.exit(1)


def _ai_command(args):
    """ai check / extract-points / create-device —— AI 点表导入（v1.13.1）。"""
    import json as _json
    from pathlib import Path as _Path

    cmd = getattr(args, "ai_command", None)

    if cmd == "check":
        from protoforge.ai_extract import AIClient, AIConfig
        cfg = AIConfig()
        print(f"+ LLM 服务: {cfg.base_url}  模型: {cfg.model}")
        try:
            models = AIClient(cfg).list_models()
        except Exception as e:
            print(f"! 连接失败: {type(e).__name__}: {e}")
            print("  本地 Ollama 请确认：1) `ollama serve` 已运行  2) `ollama pull "
                  + cfg.model + "` 已执行")
            print("  或设置 PROTOFORGE_AI_BASE_URL / PROTOFORGE_AI_MODEL 指向其他 OpenAI 兼容服务")
            sys.exit(1)
        if not models:
            print("! 服务可达但没有可用模型。执行：ollama pull " + cfg.model)
            sys.exit(1)
        print(f"+ 可用模型 {len(models)} 个:")
        for m in models[:20]:
            print(f"    {m}")
        hit = " (当前配置)" if cfg.model in models else "  ! 当前配置的模型不在列表中"
        print(f"+ 当前模型 {cfg.model}{hit}")
        return

    if cmd == "diagnose":
        payload = {"question": getattr(args, "question", ""), "count": args.count,
                   "protocol": args.protocol, "device_id": args.device,
                   "direction": args.direction}
        print(f"+ 请求 LLM 分析最近 {args.count} 条调试日志...")
        r = _api_request(args.server, "POST", "/ai/analyze-logs", args.token, payload,
                         timeout=600)
        data = r.json()
        if args.output:
            _Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            _Path(args.output).write_text(
                _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"+ 已保存: {args.output}")
        if data.get("ok"):
            diag = data.get("diagnosis", {})
            print("+ 摘要: " + diag.get("summary", ""))
            for f in diag.get("findings", []):
                print(f"  [{str(f.get('confidence', '?')).upper():6}] {f.get('issue', '')}")
                if f.get("likely_cause"):
                    print(f"           根因: {f['likely_cause']}")
                if f.get("suggested_fix"):
                    print(f"           建议: {f['suggested_fix']}")
                for ev in f.get("evidence", [])[:3]:
                    print(f"           出处: {ev[:120]}")
            for note in data.get("notes", [])[:5]:
                print(f"  ! note: {note}")
        else:
            print("! " + str(data.get("error", "")))
            if data.get("hint"):
                print("  hint: " + data["hint"])
        sys.exit(0 if data.get("ok") else 1)

    if cmd in ("extract-points", "create-device"):
        path = _Path(args.file)
        if not path.exists():
            print(f"! 文件不存在: {path}")
            sys.exit(1)
        text = path.read_text(encoding="utf-8", errors="replace")
        if cmd == "extract-points":
            # 本地直调 LLM，无需起 ProtoForge 服务
            from protoforge.ai_extract import extract_device_config
            print(f"+ 请求 LLM 解析（{len(text)} 字符）...")
            data = extract_device_config(text, protocol_hint=getattr(args, "protocol", ""))
            if args.output:
                _Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                _Path(args.output).write_text(
                    _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"+ 已保存: {args.output}")
            else:
                print(_json.dumps(data, ensure_ascii=False, indent=2))
            if not data.get("ok"):
                print("! " + str(data.get("error", "")))
                if data.get("hint"):
                    print("  hint: " + data["hint"])
            if not data.get("ok"):
                print("! " + str(data.get("error", "")))
                if data.get("hint"):
                    print("  hint: " + data["hint"])
            sys.exit(0 if data.get("ok") else 1)
        payload: dict = {"text": text, "protocol_hint": getattr(args, "protocol", "")}
        payload["name"] = getattr(args, "name", "")
        if getattr(args, "device_id", ""):
            payload["device_id"] = args.device_id
        print(f"+ 请求 LLM 解析（{len(text)} 字符）并创建设备...")
        r = _api_request(args.server, "POST", "/ai/create-device-from-text",
                         args.token, payload, timeout=600)
        data = r.json()
        if args.output:
            _Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            _Path(args.output).write_text(
                _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"+ 已保存: {args.output}")
        else:
            print(_json.dumps(data, ensure_ascii=False, indent=2))
        if cmd == "create-device":
            if data.get("ok"):
                print(f"+ 设备已创建并启动: {data.get('device_id')}  "
                      f"点位 {data.get('point_count')} 个  模型 {data.get('model')}")
                for note in data.get("notes", [])[:5]:
                    print(f"  ! note: {note}")
            else:
                sys.exit(1)
        elif not data.get("ok"):
            sys.exit(1)
        return

    print("Usage: protoforge ai {check|extract-points|create-device|diagnose} ...")
    sys.exit(1)


def _test_command(args):
    """Execute a test plan via API and output results in specified format."""
    import json as _json

    import requests

    test_cmd = getattr(args, "test_command", None)
    if test_cmd != "run":
        print("Usage: protoforge test run --plan <plan-id> [options]")
        sys.exit(1)

    plan_id = args.plan
    server = args.server.rstrip("/")
    token = args.token
    fmt = args.format
    output = args.output
    timeout = args.timeout

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    print(f"+ Triggering test plan '{plan_id}' on {server}...")

    # Trigger the run
    try:
        r = requests.post(
            f"{server}/api/v1/test-plans/{plan_id}/run",
            json={"trigger_source": "cli"},
            headers=headers,
            timeout=timeout,
        )
        r.raise_for_status()
        run_data = r.json()
    except requests.exceptions.ConnectionError:
        print(f"! Cannot connect to ProtoForge server at {server}")
        print("  Make sure the server is running: protoforge run")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"! API error: {e}")
        if e.response is not None:
            print(f"  Response: {e.response.text}")
        sys.exit(1)

    run_id = run_data["id"]
    status = run_data["status"]
    print(f"+ Run ID: {run_id}")
    print(f"+ Status: {status}")

    summary = run_data.get("results_summary", {})
    total = summary.get("total", 0)
    passed_count = summary.get("passed", 0)
    failed_count = summary.get("failed", 0)
    errors = summary.get("errors", 0)
    duration = summary.get("duration_seconds", 0)

    print(f"+ Results: {passed_count}/{total} passed, {failed_count} failed, {errors} errors ({duration}s)")

    # Get the report in the requested format
    try:
        r = requests.get(
            f"{server}/api/v1/test-runs/{run_id}/report",
            params={"format": fmt},
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"! Failed to get report: {e}")
        sys.exit(1)

    content = _json.dumps(r.json(), indent=2, ensure_ascii=False) if fmt == "json" else r.text

    # Output
    if output:
        from pathlib import Path
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(content, encoding="utf-8")
        print(f"+ Report saved to: {output}")
    else:
        print(content)

    # Exit code: 0 if passed, 1 if failed/error
    if status == "passed":
        sys.exit(0)
    else:
        sys.exit(1)


def _run_server(host="0.0.0.0", port=8000, reload=False, log_level="info", demo_mode=False, daemon=False):
    import secrets

    if not demo_mode:
        port_str = str(port)
        admin_pw = os.environ.get("PROTOFORGE_ADMIN_PASSWORD", "")
        if not admin_pw:
            admin_pw = secrets.token_urlsafe(12)
            os.environ["PROTOFORGE_ADMIN_PASSWORD"] = admin_pw
            logger_banner_msg = f"admin / {admin_pw} (auto-generated, save this now!)"
        else:
            # FIXED-P1: 预配置密码脱敏显示，与installer.py保持一致，避免密码泄露到终端/日志
            logger_banner_msg = f"admin / {'*' * len(admin_pw)} (configured)"
        w = 50
        print()
        print("+" + "-" * w + "+")
        print("|  ProtoForge is starting" + " " * (w - 25) + "|")
        print("|  Access:  http://localhost:" + port_str + " " * max(0, w - 28 - len(port_str)) + "|")
        print("|  API Docs: http://localhost:" + port_str + "/docs" + " " * max(0, w - 34 - len(port_str)) + "|")
        print("|  Admin:   " + logger_banner_msg + " " * max(0, w - 12 - len(logger_banner_msg)) + "|")
        print("+" + "-" * w + "+")
        print()

    if demo_mode:
        os.environ["PROTOFORGE_DEMO_MODE"] = "1"
        demo_pw = os.environ.get("PROTOFORGE_ADMIN_PASSWORD", "")
        if not demo_pw:
            # demo 模式默认 admin/admin（与 README 承诺一致，本机演示用途）；
            # 可通过环境变量 PROTOFORGE_ADMIN_PASSWORD 覆盖。非 demo 模式仍为随机密码。
            demo_pw = "admin"
            os.environ["PROTOFORGE_ADMIN_PASSWORD"] = demo_pw
        # demo 模式下同步 admin 密码到上述值（含旧数据随机密码的情况），
        # 保证"启动即用 admin/指定密码登录"；用户显式设 RESET=0 可关闭
        os.environ.setdefault("PROTOFORGE_RESET_ADMIN_PASSWORD", "1")
        os.environ.setdefault("PROTOFORGE_NO_AUTH", "0")
        # FIXED: Reset cached settings so demo_mode is picked up
        import protoforge.config as config_module
        config_module._settings = None
        config_module._settings_overrides.clear()
        w = 50
        print()
        print("+" + "-" * w + "+")
        print("|  ProtoForge Demo Mode" + " " * (w - 22) + "|")
        print("|" + " " * w + "|")
        print("|  + Auto-create sample devices and scenarios" + " " * max(0, w - 46) + "|")
        print("|  + Auto-start all protocol services" + " " * max(0, w - 39) + "|")
        print("|  + Login: admin / " + demo_pw + " " * max(0, w - 21 - len(demo_pw)) + "|")
        print("|" + " " * w + "|")
        port_str = str(port)
        access_content = f"Access URL: http://localhost:{port_str}"
        print("|  " + access_content + " " * max(0, w - 2 - len(access_content)) + "|")
        print("+" + "-" * w + "+")
        print()

    # Daemon mode: double-fork and detach from terminal
    if daemon:
        if sys.platform == "win32":
            print("! Daemon mode is not supported on Windows. Background usage:")
            print("    start /B python -m protoforge run    (or: protoforge demo)")
            print("  Then stop it from any terminal:  protoforge stop")
            return
        pid_file = _get_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        _daemonize()
        # Write PID after daemonizing (we are now the grandchild)
        pid_file.write_text(str(os.getpid()))
        # Register cleanup on exit
        import atexit
        atexit.register(lambda: _get_pid_file().unlink(missing_ok=True))
    else:
        # FIXED(Issue#12): 非 daemon 启动（含 Windows 'start /B' 后台）同样记录 PID，
        # 保证 'protoforge stop' 全平台可用；优雅退出时由 atexit 自动清理
        _write_pid_file()

    from pathlib import Path as _Path

    import uvicorn
    _log_dir = _Path("logs")
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = str(_log_dir / "protoforge.log")

    uvicorn.run(
        "protoforge.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "()": "uvicorn.logging.DefaultFormatter",
                    "fmt": "%(levelprefix)s %(message)s",
                    "use_colors": False,
                },
                "access": {
                    "()": "uvicorn.logging.AccessFormatter",
                    "fmt": "%(levelprefix)s %(client_addr)s - \"%(request_line)s\" %(status_code)s",
                    "use_colors": False,
                },
                "file_fmt": {
                    "format": "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                },
                "access": {
                    "formatter": "access",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                },
                "file": {
                    "formatter": "file_fmt",
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": _log_file,
                    "maxBytes": 10485760,
                    "backupCount": 5,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": log_level.upper(),
                "handlers": ["default", "file"],
            },
            "loggers": {
                "uvicorn": {"level": log_level.upper(), "propagate": True},
                "uvicorn.error": {"level": log_level.upper(), "propagate": True},
                "uvicorn.access": {"handlers": ["access", "file"], "level": log_level.upper(), "propagate": False},
                "protoforge": {"level": log_level.upper(), "propagate": True},
                "asyncua": {"level": "WARNING", "propagate": True},
            },
        },
    )


if __name__ == "__main__":
    main()
