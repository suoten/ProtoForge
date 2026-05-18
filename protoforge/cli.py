import argparse
import sys


def main():
    from protoforge.config import get_settings
    settings = get_settings()
    default_host = settings.host
    default_port = settings.port

    parser = argparse.ArgumentParser(
        prog="protoforge",
        description="ProtoForge - IoT Protocol Simulation & Testing Platform",  # FIXED: 中文→英文
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")  # FIXED: Chinese→English

    run_parser = subparsers.add_parser("run", help="Start ProtoForge server")  # FIXED: Chinese→English
    run_parser.add_argument("--host", default=default_host, help=f"Listen address (default: {default_host})")  # FIXED: Chinese→English
    run_parser.add_argument("--port", type=int, default=default_port, help=f"Listen port (default: {default_port})")  # FIXED: Chinese→English
    run_parser.add_argument("--reload", action="store_true", help="Enable hot reload for development")  # FIXED: Chinese→English
    run_parser.add_argument("--log-level", default="info", help="Log level (debug/info/warning/error)")  # FIXED: Chinese→English

    demo_parser = subparsers.add_parser("demo", help="Start demo mode with sample devices")  # FIXED: Chinese→English
    demo_parser.add_argument("--host", default=default_host, help="Listen address")  # FIXED: Chinese→English
    demo_parser.add_argument("--port", type=int, default=default_port, help="Listen port")  # FIXED: Chinese→English

    subparsers.add_parser("version", help="Show version")  # FIXED: Chinese→English

    subparsers.add_parser("init", help="Initialize data directory and default config")  # FIXED: Chinese→English

    migrate_parser = subparsers.add_parser("migrate", help="Run database migrations")  # FIXED: Chinese→English
    migrate_parser.add_argument("--revision", default="head", help="Target revision (default: head)")  # FIXED: Chinese→English

    args = parser.parse_args()

    if args.command == "version":
        print("ProtoForge v0.1.0 - IoT Protocol Simulation & Testing Platform")  # FIXED: 中文→英文
        return

    if args.command == "init":
        _init_command()
        return

    if args.command == "migrate":
        _migrate_command(getattr(args, "revision", "head"))
        return

    if args.command == "demo":
        _run_server(host=args.host, port=args.port, demo_mode=True)
        return

    if args.command == "run" or args.command is None:
        host = getattr(args, "host", "0.0.0.0")
        port = getattr(args, "port", 8000)
        reload = getattr(args, "reload", False)
        log_level = getattr(args, "log_level", "info")
        _run_server(host=host, port=port, reload=reload, log_level=log_level)
        return

    parser.print_help()


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
            print("+ Created .env from .env.example")  # FIXED: Chinese->English, avoid Unicode on Windows
        except (OSError, PermissionError) as e:
            print(f"! Failed to create .env: {e}")  # FIXED: Chinese->English
    print("+ Data directory created: data/")  # FIXED: Chinese->English
    print("+ Done! Run 'protoforge run' to start the server")  # FIXED: Chinese->English
    print("  or run 'protoforge demo' for a quick demo")  # FIXED: Chinese→English


def _migrate_command(revision: str = "head"):
    import subprocess
    print(f"Running database migration to revision: {revision}")  # FIXED: Chinese→English
    try:
        result = subprocess.run(
            ["alembic", "upgrade", revision],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("+ Database migration completed")  # FIXED: Chinese->English, avoid Unicode on Windows
        else:
            print(f"! Migration failed:\n{result.stderr}")  # FIXED: Chinese->English
            sys.exit(1)
    except FileNotFoundError:
        print("! alembic not found. Install it: pip install alembic")  # FIXED: Chinese->English
        sys.exit(1)


def _run_server(host="0.0.0.0", port=8000, reload=False, log_level="info", demo_mode=False):
    import os
    import secrets

    if not demo_mode:
        port_str = str(port)
        admin_pw = os.environ.get("PROTOFORGE_ADMIN_PASSWORD", "")
        if not admin_pw:
            admin_pw = secrets.token_urlsafe(12)
            os.environ["PROTOFORGE_ADMIN_PASSWORD"] = admin_pw
            logger_banner_msg = f"admin / {admin_pw} (auto-generated, save this now!)"
        else:
            logger_banner_msg = f"admin / ********"
        w = 50
        print()
        print("╔" + "═" * w + "╗")
        print("║  ProtoForge is starting" + " " * (w - 25) + "║")
        print("║  Access:  http://localhost:" + port_str + " " * max(0, w - 28 - len(port_str)) + "║")
        print("║  API Docs: http://localhost:" + port_str + "/docs" + " " * max(0, w - 34 - len(port_str)) + "║")
        print("║  Admin:   " + logger_banner_msg + " " * max(0, w - 12 - len(logger_banner_msg)) + "║")
        print("╚" + "═" * w + "╝")
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
        print("╔" + "═" * w + "╗")
        print("║  ProtoForge Demo Mode" + " " * (w - 22) + "║")
        print("║" + " " * w + "║")
        print("║  + Auto-create sample devices and scenarios" + " " * max(0, w - 46) + "║")
        print("║  + Auto-start all protocol services" + " " * max(0, w - 39) + "║")
        print("║  + Login: admin / " + demo_pw + " " * max(0, w - 21 - len(demo_pw)) + "║")
        print("║" + " " * w + "║")
        port_str = str(port)
        access_content = f"Access URL: http://localhost:{port_str}"
        print("║  " + access_content + " " * max(0, w - 2 - len(access_content)) + "║")
        print("╚" + "═" * w + "╝")
        print()

    import uvicorn
    uvicorn.run(
        "protoforge.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
