"""v1.6.0 桌面模式（protoforge.desktop）测试。

覆盖纯逻辑与可Mock的流程分支：
  - 端口挑选 / 服务探测 / 健康等待
  - 界面打开模式回退（native→browser→failed）
  - 更新检查的静默降级
  - run_desktop 的"已有实例直接开界面"路径
"""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from protoforge import desktop
from tests.wire_golden_harness import free_tcp_port


# ---------------------------------------------------------------------------
# 端口与探测
# ---------------------------------------------------------------------------

def test_is_port_serving_true_when_listener_present():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert desktop.is_port_serving(port) is True
    finally:
        srv.close()


def test_is_port_serving_false_when_free():
    assert desktop.is_port_serving(free_tcp_port()) is False


def test_pick_desktop_port_skips_occupied():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    occupied = srv.getsockname()[1]
    try:
        picked = desktop.pick_desktop_port(occupied)
        assert picked != occupied
        # picked 端口应当真实可绑定
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", picked))
    finally:
        srv.close()


def test_ui_url_format():
    assert desktop.ui_url(18080) == "http://127.0.0.1:18080/"
    assert desktop.ui_url(8080, host="0.0.0.0") == "http://0.0.0.0:8080/"


# ---------------------------------------------------------------------------
# 健康等待（真实 HTTP 服务）
# ---------------------------------------------------------------------------

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # 静默
        pass


def test_wait_until_healthy_true():
    srv = HTTPServer(("127.0.0.1", 0), _HealthHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert desktop.wait_until_healthy(port, timeout=3) is True
    finally:
        srv.shutdown()


def test_wait_until_healthy_false_on_timeout():
    assert desktop.wait_until_healthy(free_tcp_port(), timeout=1) is False


# ---------------------------------------------------------------------------
# 界面打开回退链
# ---------------------------------------------------------------------------

def test_open_ui_browser_mode(monkeypatch):
    opened = []
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: opened.append(url) or True)
    assert desktop.open_ui(18080) == "browser"
    assert opened == ["http://127.0.0.1:18080/"]


def test_open_ui_browser_failure(monkeypatch):
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: False)
    assert desktop.open_ui(18080) == "browser-failed"


def test_open_ui_native_falls_back_without_webview(monkeypatch):
    # 当前 venv 没有 webview：prefer_native 应自动回退 browser
    import builtins
    real_import = builtins.__import__

    def no_webview(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("webview not installed")
        return real_import(name, *args, **kwargs)

    opened = []
    monkeypatch.setattr(builtins, "__import__", no_webview)
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url: opened.append(url) or True)
    assert desktop.open_ui(18080, prefer_native=True) == "browser"
    assert opened == ["http://127.0.0.1:18080/"]


# ---------------------------------------------------------------------------
# 更新检查（静默降级）
# ---------------------------------------------------------------------------

def test_check_update_once_returns_data(monkeypatch):
    import protoforge.core.version_check as vc

    async def fake_fetch(current, timeout=6.0):
        return {"current": current, "latest": "v9.9.9", "update_available": True,
                "check_failed": False, "url": "https://example.com"}

    monkeypatch.setattr(vc, "fetch_release_info", fake_fetch)
    info = desktop.check_update_once()
    assert info is not None and info["update_available"] is True


def test_check_update_once_silent_on_failure(monkeypatch):
    import protoforge.core.version_check as vc

    async def boom(current, timeout=6.0):
        raise RuntimeError("offline")

    monkeypatch.setattr(vc, "fetch_release_info", boom)
    assert desktop.check_update_once() is None


# ---------------------------------------------------------------------------
# run_desktop：已有实例路径（不起第二个服务）
# ---------------------------------------------------------------------------

def test_run_desktop_opens_existing_instance(monkeypatch):
    opened = []
    monkeypatch.setattr(desktop, "is_port_serving", lambda p, host="127.0.0.1", timeout=0.5: True)
    monkeypatch.setattr(desktop, "open_ui", lambda p, h="127.0.0.1", prefer_native=False: opened.append(p) or "browser")
    started = {"server": False}
    monkeypatch.setattr(desktop, "_start_server_thread",
                        lambda *a, **k: started.__setitem__("server", True) or (None, None))
    code = desktop.run_desktop(port=18080)
    assert code == 0
    assert opened == [18080]
    assert started["server"] is False
