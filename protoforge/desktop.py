"""ProtoForge 桌面模式（v1.6.0）。

目标：工控现场的 Windows 机器（无 Python/Node/Docker、可能离线）双击即用。

行为：
  1. 冻结模式下先 chdir 到 exe 目录 —— data/、logs/、.env 全部落 exe 旁
     （"配置随目录走"，便携包解压即用）；
  2. 后台线程启动 uvicorn 服务（与 `protoforge run` 同一 app、同一配置链路）；
  3. 轮询 /health 就绪后自动打开界面：
     - 已有实例在运行（健康检查直接通过）→ 不再起第二个服务，直接打开
       已运行实例的界面（自然实现"重复双击=打开界面"）；
     - pywebview 可用时优先原生窗口，否则系统默认浏览器；
  4. 启动后检查 GitHub 新版本（复用 v1.4.0 更新检查逻辑），有更新时
     托盘气泡 / 控制台提示 + Release 页链接；
  5. 可选系统托盘（pystray + Pillow，随 [desktop] extra 安装），菜单：
     打开界面 / 检查更新 / 退出；无托盘库时 Ctrl+C 优雅退出。

设计取舍（相对规划原案）：v1.6.0 用"浏览器界面 + 可选托盘"而非 pywebview
原生窗口——浏览器在工控现场零依赖、无 WebView2 运行时兼容问题，且打包
体积与杀软误报都更可控；pywebview 壳留作后续增强。
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DESKTOP_PORT = 18080
HEALTH_TIMEOUT_SECONDS = 90.0


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def is_port_serving(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """端口上是否已有 ProtoForge 实例（TCP 可连即视为有服务）。"""
    af = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(af, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False


def pick_desktop_port(preferred: int = DEFAULT_DESKTOP_PORT) -> int:
    """从 preferred 起找第一个空闲端口（新实例用；已有实例场景不走这里）。"""
    port = preferred
    for _ in range(50):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            port += 1
    return preferred


def ui_url(port: int, host: str = "127.0.0.1") -> str:
    return f"http://{host}:{port}/"


def wait_until_healthy(port: int, timeout: float = HEALTH_TIMEOUT_SECONDS,
                       host: str = "127.0.0.1") -> bool:
    """轮询 /health 直到 200 或超时（桌面模式自己的就绪判定，不经鉴权）。"""
    import urllib.request

    deadline = time.monotonic() + timeout
    url = ui_url(port, host).rstrip("/") + "/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 本机回环
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


# ---------------------------------------------------------------------------
# 服务器线程
# ---------------------------------------------------------------------------

def _start_server_thread(host: str, port: int, log_level: str = "info") -> tuple[Any, threading.Thread]:
    """在守护线程里跑 uvicorn.Server（与 protoforge run 同一 app/配置链路）。

    返回 (uvicorn.Server, thread)。uvicorn 在非主线程不装信号处理器，
    退出由调用方置 server.should_exit = True 触发优雅停机。
    """
    import uvicorn

    config = uvicorn.Config(
        "protoforge.main:app",
        host=host,
        port=port,
        log_level=log_level,
        # 桌面模式不启用 access 日志（与 run 一致的 file 日志已足够）
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "()": "uvicorn.logging.DefaultFormatter",
                    "fmt": "%(levelprefix)s %(message)s",
                    "use_colors": False,
                },
            },
            "handlers": {
                "default": {"formatter": "default", "class": "logging.StreamHandler",
                            "stream": "ext://sys.stderr"},
            },
            "root": {"level": log_level.upper(), "handlers": ["default"]},
            "loggers": {
                "uvicorn": {"level": log_level.upper(), "propagate": True},
                "uvicorn.error": {"level": log_level.upper(), "propagate": True},
                "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": False},
            },
        },
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="protoforge-desktop-server", daemon=True)
    thread.start()
    return server, thread


# ---------------------------------------------------------------------------
# 更新检查（复用 v1.4.0 逻辑）
# ---------------------------------------------------------------------------

def check_update_once(timeout: float = 6.0) -> dict[str, Any] | None:
    """同步检查更新；失败返回 None（静默）。供托盘/控制台提示用。"""
    try:
        import asyncio

        from protoforge import __version__
        from protoforge.core.version_check import fetch_release_info

        return asyncio.run(fetch_release_info(__version__, timeout=timeout))
    except Exception as e:  # noqa: BLE001 — 更新检查绝不影响主流程
        logger.debug("Desktop update check failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# 界面打开与托盘
# ---------------------------------------------------------------------------

def open_ui(port: int, host: str = "127.0.0.1", prefer_native: bool = False) -> str:
    """打开管理界面。返回实际使用的模式："native" / "browser" / "browser-failed"。

    native 需要 pywebview（可选依赖，未安装时自动回退浏览器）。
    """
    url = ui_url(port, host)
    if prefer_native:
        try:
            import webview  # type: ignore[import-not-found] # 可选依赖

            threading.Thread(
                target=lambda: webview.create_window("ProtoForge", url, width=1400, height=900),
                daemon=True,
            ).start()
            return "native"
        except ImportError:
            pass
    if webbrowser.open(url):
        return "browser"
    return "browser-failed"


class _Tray:
    """可选系统托盘（pystray + Pillow）。库缺失时为 None 占位，主流程自动降级。"""

    def __init__(self, port: int, on_open_ui, on_quit):
        self.port = port
        self._on_open_ui = on_open_ui
        self._on_quit = on_quit
        self.icon: Any = None

    def start(self) -> bool:
        try:
            import pystray  # type: ignore[import-not-found]
            from PIL import Image, ImageDraw  # type: ignore[import-not-found]
        except ImportError:
            return False

        # 生成 64x64 占位图标（蓝底 "PF"），避免依赖仓库外资源
        img = Image.new("RGB", (64, 64), (24, 100, 180))
        draw = ImageDraw.Draw(img)
        draw.text((14, 20), "PF", fill=(255, 255, 255))

        def _open(icon=None, item=None):
            self._on_open_ui()

        def _quit(icon=None, item=None):
            self._on_quit()

        self.icon = pystray.Icon(
            "ProtoForge", img, title=f"ProtoForge — {ui_url(self.port)}",
            menu=pystray.Menu(
                pystray.MenuItem("打开界面", _open, default=True),
                pystray.MenuItem("退出", _quit),
            ),
        )
        threading.Thread(target=self.icon.run, name="protoforge-tray", daemon=True).start()
        return True

    def notify(self, title: str, message: str) -> None:
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
            except Exception as e:  # noqa: BLE001 — 通知失败不影响主流程
                logger.debug("Tray notify failed: %s", e)

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_desktop(host: str = "127.0.0.1", port: int | None = None,
                prefer_native: bool = False, use_tray: bool = True,
                check_updates: bool = True, log_level: str = "info") -> int:
    """桌面模式主流程。返回进程退出码。

    语义约定：
      - 目标端口上已有健康实例 → 直接打开它的界面并退出（退出码 0）；
      - 新启动实例 → 阻塞运行直到托盘退出 / Ctrl+C / 服务线程结束；
      - 服务未能就绪 → 退出码 1。
    """
    from protoforge import __version__

    # 冻结模式：数据落 exe 旁（配置随目录走）。开发模式不动 CWD。
    if getattr(sys, "frozen", False):
        exe_dir = str(Path(sys.executable).resolve().parent)
        os.chdir(exe_dir)
        os.environ.setdefault("PROTOFORGE_IN_DESKTOP", "1")

    target_port = port or DEFAULT_DESKTOP_PORT

    # 已有实例在跑 → 只开界面（重复双击语义）
    if is_port_serving(target_port, host):
        print(f"+ 检测到 ProtoForge 已在 {ui_url(target_port, host)} 运行，直接打开界面")
        open_ui(target_port, host, prefer_native=False)
        return 0

    port = pick_desktop_port(target_port)

    w = 52
    print()
    print("+" + "-" * w + "+")
    print("|  ProtoForge Desktop" + " " * (w - 22) + "|")
    print(f"|  v{__version__}" + " " * max(0, w - 7 - len(__version__)) + "|")
    print("|  界面就绪后自动打开浏览器" + " " * max(0, w - 26) + "|")
    print("|  退出：托盘菜单 / Ctrl+C" + " " * max(0, w - 24) + "|")
    print("+" + "-" * w + "+")
    print()

    server, thread = _start_server_thread(host, port, log_level=log_level)
    healthy = wait_until_healthy(port)

    tray = _Tray(port, on_open_ui=lambda: open_ui(port, host, prefer_native),
                 on_quit=lambda: setattr(server, "should_exit", True))
    if healthy and use_tray:
        tray.start()

    if not healthy:
        print("! 服务未能就绪（健康检查超时），请查看 logs/protoforge.log")
        server.should_exit = True
        thread.join(timeout=10)
        return 1

    mode = open_ui(port, host, prefer_native)
    print(f"+ 界面地址: {ui_url(port, host)}  （打开方式: {mode}）")
    print(f"+ 数据目录: {Path.cwd() / 'data'}")

    if check_updates:
        info = check_update_once()
        if info and info.get("update_available"):
            msg = f"发现新版本 {info.get('latest')}（当前 v{__version__}），详情: {info.get('url')}"
            print(f"! {msg}")
            tray.notify("ProtoForge 有新版本", msg)

    try:
        while thread.is_alive() and not server.should_exit:
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n+ 收到退出信号，正在停止服务…")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        tray.stop()
        print("+ ProtoForge Desktop 已退出")
    return 0
