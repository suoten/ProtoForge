import argparse
import os
import sys


def _load_dotenv_to_environ():
    """Load .env file values into os.environ if not already set.

    pydantic-settings reads .env internally but doesn't set os.environ.
    This ensures cli.py can read PROTOFORGE_ADMIN_PASSWORD via os.environ.get().
    """
    from pathlib import Path
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


def main():
    _load_dotenv_to_environ()

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

    subparsers.add_parser("init", help="Initialize data directory and default config")

    migrate_parser = subparsers.add_parser("migrate", help="Run database migrations")
    migrate_parser.add_argument("--revision", default="head", help="Target revision (default: head)")

    stop_parser = subparsers.add_parser("stop", help="Stop background daemon")

    args = parser.parse_args()

    if args.command == "version":
        from protoforge import __version__  # FIXED: 引用__version__单一来源，避免硬编码版本号
        print(f"ProtoForge v{__version__} - IoT Protocol Simulation & Testing Platform")
        return

    if args.command == "init":
        _init_command()
        return

    if args.command == "migrate":
        _migrate_command(getattr(args, "revision", "head"))
        return

    if args.command == "stop":
        _stop_command()
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


def _get_pid_file():
    from pathlib import Path
    return Path("data") / "protoforge.pid"


def _get_log_file():
    from pathlib import Path
    return Path("logs") / "protoforge.log"


def _stop_command():
    pid_file = _get_pid_file()
    if not pid_file.exists():
        print("! No background daemon found (PID file not found)")
        return
    try:  # FIXED: 添加异常保护，PID文件内容可能损坏
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError) as e:
        print(f"! Invalid PID file: {e}")
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, 15)  # SIGTERM
        print(f"+ Sent SIGTERM to daemon (PID {pid})")
    except ProcessLookupError:
        print(f"! Process {pid} not found (may have already stopped)")
    except PermissionError:
        print(f"! Permission denied to stop process {pid}")
    finally:
        pid_file.unlink(missing_ok=True)


def _daemonize():
    """Double-fork to fully detach from terminal (Linux/Unix only)."""
    import signal

    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent exits immediately
        os._exit(0)

    # Child becomes session leader
    os.setsid()

    # Second fork
    pid = os.fork()
    if pid > 0:
        os._exit(0)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    log_file = _get_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # FIXED: P4 - W29 使用 with 语句包裹 open()，确保文件描述符关闭
    with open(os.devnull, 'r') as si, \
         open(str(log_file), 'a') as so, \
         open(str(log_file), 'a') as se:
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

    # Ignore SIGHUP
    signal.signal(signal.SIGHUP, signal.SIG_IGN)


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
            ["alembic", "upgrade", revision],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("+ Database migration completed")
        else:
            print(f"! Migration failed:\n{result.stderr}")
            sys.exit(1)
    except FileNotFoundError:
        print("! alembic not found. Install it: pip install alembic")
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
            logger_banner_msg = f"admin / {admin_pw}"
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
            demo_pw = secrets.token_urlsafe(12)
            os.environ["PROTOFORGE_ADMIN_PASSWORD"] = demo_pw
        os.environ.setdefault("PROTOFORGE_NO_AUTH", "0")
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
            print("! Daemon mode is not supported on Windows. Use 'start /B' or run as a service.")
            print("  On Linux/macOS, use: protoforge demo --daemon")
            return
        pid_file = _get_pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        _daemonize()
        # Write PID after daemonizing (we are now the grandchild)
        pid_file.write_text(str(os.getpid()))
        # Register cleanup on exit
        import atexit
        atexit.register(lambda: _get_pid_file().unlink(missing_ok=True))

    import uvicorn

    from pathlib import Path as _Path
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
