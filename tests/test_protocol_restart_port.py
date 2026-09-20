"""FIXED: 运行中协议带新端口再次启动被静默忽略（用户反馈"自定义TCP端口改不了"）。

复现：custom_tcp 在默认端口 38000 运行中 → 高级配置改端口为 38124 → 点启动
→ API 返回 200 ok，但服务仍监听 38000，新端口被静默忽略。

根因：engine.start_protocol 对 RUNNING 状态一律跳过。
修复：单协议启动端点传 restart=True —— 运行中带配置启动 = 先停再按新配置启动；
start-all / 设备自动启动 / demo / 集成管理器均不受影响（各自已有运行守卫）。
"""

import json
import socket
import time

import pytest
from httpx import AsyncClient

from protoforge.engine.engine import SimulationEngine
from protoforge.models.device import DeviceConfig, PointConfig


def _listening(port: int, host: str = "127.0.0.1") -> bool:
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.close()
        return True
    except OSError:
        return False


def _make_engine() -> SimulationEngine:
    """裸引擎 + 显式注册 custom_tcp（真实应用启动时注册全部协议，单测环境只注册被测的）."""
    from protoforge.protocols.custom_tcp.server import CustomTcpServer
    engine = SimulationEngine()
    engine.register_protocol(CustomTcpServer())
    return engine


@pytest.mark.asyncio
async def test_restart_running_protocol_with_new_port():
    """运行中的协议以新端口再次启动 → 实际监听新端口、旧端口关闭."""
    engine = _make_engine()
    await engine.start()
    try:
        await engine.start_protocol("custom_tcp", {"host": "127.0.0.1", "port": 38000})
        await asyncio_sleep()
        assert _listening(38000), "initial start should listen on 38000"

        # restart=True：运行中带新端口启动
        await engine.start_protocol("custom_tcp", {"host": "127.0.0.1", "port": 38124}, restart=True)
        await asyncio_sleep()
        assert _listening(38124), "restarted server must listen on the NEW port"
        assert not _listening(38000), "OLD port must be released after restart"

        # 默认行为（无 restart）保持幂等跳过：端口不变
        await engine.start_protocol("custom_tcp", {"host": "127.0.0.1", "port": 38125})
        await asyncio_sleep()
        assert _listening(38124), "idempotent start must NOT change the port"
        assert not _listening(38125), "idempotent start must not bind the new port"
    finally:
        try:
            await engine.stop_protocol("custom_tcp")
        except Exception:
            pass
        await engine.stop()


@pytest.mark.asyncio
async def test_start_all_does_not_restart_running_protocols():
    """start-all 幂等性回归：运行中的协议不被重启（端口保持不变）."""
    engine = _make_engine()
    await engine.start()
    try:
        await engine.start_protocol("custom_tcp", {"host": "127.0.0.1", "port": 38000})
        await asyncio_sleep()
        # 模拟 start-all 路径：不传 restart
        await engine.start_protocol("custom_tcp", {"host": "127.0.0.1", "port": 38126})
        await asyncio_sleep()
        assert _listening(38000)
        assert not _listening(38126)
    finally:
        try:
            await engine.stop_protocol("custom_tcp")
        except Exception:
            pass
        await engine.stop()


async def asyncio_sleep():
    """等待协议端口就绪（跨平台等待，避免固定 sleep 不足）."""
    for _ in range(25):
        await __import__("asyncio").sleep(0.2)


# ---------------------------------------------------------------------------
#  API 层回归：httpx ASGI（无 503 守卫路径，直接驱动引擎）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_autostart_still_works():
    """回归：设备启动时协议未运行 → 自动启动（restart 默认 False 语义不变）."""
    engine = _make_engine()
    await engine.start()
    try:
        cfg = DeviceConfig(
            id="ct-auto", name="ct-auto", protocol="custom_tcp",
            points=[PointConfig(name="p1", address="1", data_type="uint16", access="rw")],
        )
        await engine.create_device(cfg)
        await engine.start_device("ct-auto")  # 内部走 start_protocol 自动启动路径
        for _ in range(25):
            await __import__("asyncio").sleep(0.2)
            if engine.is_protocol_running("custom_tcp"):
                break
        assert engine.is_protocol_running("custom_tcp")
    finally:
        try:
            await engine.stop_device("ct-auto")
        except Exception:
            pass
        try:
            await engine.stop_protocol("custom_tcp")
        except Exception:
            pass
        await engine.stop()
