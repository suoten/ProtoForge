import argparse
import sys


def main():
    from protoforge.config import get_settings
    settings = get_settings()
    default_host = settings.host
    default_port = settings.port

    parser = argparse.ArgumentParser(
        prog="protoforge",
        description="ProtoForge - 物联网协议仿真与测试平台",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    run_parser = subparsers.add_parser("run", help="启动 ProtoForge 服务")
    run_parser.add_argument("--host", default=default_host, help=f"监听地址 (默认: {default_host})")
    run_parser.add_argument("--port", type=int, default=default_port, help=f"监听端口 (默认: {default_port})")
    run_parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    run_parser.add_argument("--log-level", default="info", help="日志级别")

    demo_parser = subparsers.add_parser("demo", help="一键启动演示（自动创建示例设备和场景）")
    demo_parser.add_argument("--host", default=default_host, help="监听地址")
    demo_parser.add_argument("--port", type=int, default=default_port, help="监听端口")

    subparsers.add_parser("version", help="查看版本")

    subparsers.add_parser("init", help="初始化数据目录和默认配置")

    args = parser.parse_args()

    if args.command == "version":
        print("ProtoForge v0.1.0 - 物联网协议仿真与测试平台")
        return

    if args.command == "init":
        _init_command()
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
    from pathlib import Path
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    print("✓ 数据目录已创建: data/")
    print("✓ 初始化完成！运行 'protoforge run' 启动服务")
    print("  或运行 'protoforge demo' 一键体验演示")


def _run_server(host="0.0.0.0", port=8000, reload=False, log_level="info", demo_mode=False):
    import os

    if demo_mode:
        os.environ["PROTOFORGE_DEMO_MODE"] = "1"
        print()
        print("╔══════════════════════════════════════════════════╗")
        print("║        ProtoForge 演示模式                      ║")
        print("║                                                  ║")
        print("║  ✓ 自动创建示例设备和场景                        ║")
        print("║  ✓ 自动启动所有协议服务                          ║")
        print("║  ✓ 默认账号: admin / admin                       ║")
        print("║                                                  ║")
        print(f"║  访问地址: http://localhost:{port}                ║")
        print("╚══════════════════════════════════════════════════╝")
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
