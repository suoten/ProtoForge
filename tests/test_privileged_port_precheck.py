"""v1.4.1 特权端口预检回归测试。

背景（用户反馈）：Docker 容器以非 root 用户运行时，S7 默认端口 102 是 Linux 特权端口，
绑定报 PermissionError。旧逻辑中 PermissionError 被 _is_port_in_use 误判为"端口被占用"，
自动换端口又连续撞上 103..1023 的权限墙，最终报 "No free port found in range"（API 503），
用户无法理解。修复：start_protocol 在占用检测前用测试 socket 预检，PermissionError
时抛出带可操作建议的 RuntimeError（API 503 + 友好文案）。

测试通过 monkeypatch 模拟内核的 bind 权限行为（Windows 上无法真实复现 Linux 权限拒绝），
不依赖平台特性。
"""

import socket

import pytest

from protoforge.engine import engine as engine_module
from protoforge.engine.engine import SimulationEngine
from protoforge.engine.defaults import get_friendly_error
from protoforge.protocols.base import ProtocolStatus
from protoforge.protocols.custom_tcp.server import CustomTcpServer


class _BindDeniedSocket:
    """模拟 Linux 非 root 环境：绑定 <1024 端口抛 PermissionError，其余端口抛占用。"""

    denied_below = 1024

    def __init__(self, family=socket.AF_INET, type=socket.SOCK_STREAM, *args, **kwargs):
        self.family = family
        self.type = type

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def bind(self, address):
        port = address[1] if isinstance(address, tuple) else 0
        if port and port < self.denied_below:
            raise PermissionError(1, "Operation not permitted")
        raise OSError(98, "Address already in use")

    def connect_ex(self, address):
        return 101  # 非零：无监听

    def settimeout(self, value):
        pass

    def close(self):
        pass


class _AlwaysInUseSocket(_BindDeniedSocket):
    """模拟所有端口都占用（用于验证占用路径不受预检影响）。"""

    denied_below = 0  # 任何端口 bind 都抛 OSError(EADDRINUSE)


def _make_engine() -> SimulationEngine:
    engine = SimulationEngine()
    engine.register_protocol(CustomTcpServer())
    return engine


@pytest.mark.asyncio
async def test_privileged_port_permission_denied_gives_actionable_error(monkeypatch):
    """特权端口绑定被拒（Linux/Docker 非 root）→ RuntimeError 且提示可操作解法，而非 503 无从排查。"""
    monkeypatch.setattr(engine_module.socket, "socket", _BindDeniedSocket)
    eng = _make_engine()
    with pytest.raises(RuntimeError) as exc_info:
        await eng.start_protocol("custom_tcp", {"host": "0.0.0.0", "port": 102})
    msg = str(exc_info.value)
    assert "privileged port" in msg
    assert "NET_BIND_SERVICE" in msg  # Docker 解法
    assert "1024" in msg              # 改端口解法
    assert eng._protocol_servers["custom_tcp"].status != ProtocolStatus.RUNNING


@pytest.mark.asyncio
async def test_non_privileged_port_in_use_falls_to_occupancy_path(monkeypatch):
    """≥1024 端口 bind 被拒（真实占用）→ 不受预检影响，仍走占用检测 → 自动换端口路径。"""
    monkeypatch.setattr(engine_module.socket, "socket", _BindDeniedSocket)
    eng = _make_engine()
    with pytest.raises(RuntimeError) as exc_info:
        await eng.start_protocol("custom_tcp", {"host": "0.0.0.0", "port": 1030})
    assert "No free port found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_all_ports_in_use_still_reports_no_free_port(monkeypatch):
    """所有端口都占用 → 仍走占用检测路径报 "No free port found"（回归：预检不改变占用语义）。"""
    monkeypatch.setattr(engine_module.socket, "socket", _AlwaysInUseSocket)
    eng = _make_engine()
    with pytest.raises(RuntimeError) as exc_info:
        await eng.start_protocol("custom_tcp", {"host": "0.0.0.0", "port": 38000})
    assert "No free port found" in str(exc_info.value)


def test_friendly_error_no_free_port_mentions_s7_and_cap():
    """友好报错映射：'No free port found' 中英文均提示特权端口根因与解法。"""
    zh = get_friendly_error("No free port found in range 103-202", lang="zh")
    assert "特权端口" in zh and "NET_BIND_SERVICE" in zh
    en = get_friendly_error("No free port found in range 103-202", lang="en")
    assert "privileged port" in en and "NET_BIND_SERVICE" in en
