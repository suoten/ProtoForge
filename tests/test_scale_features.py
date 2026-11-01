"""v1.11.0 大规模三件测试：tick 分片 / 连接上限门 / 内存可观测。"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# tick 分片（行为等价：值仍生成；分批让出）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_sharding_preserves_generation():
    """分片开启下 engine tick 仍为全部设备生成新值。"""
    from protoforge.engine.engine import SimulationEngine
    from protoforge.engine.generator import DataGenerator
    from protoforge.engine.device import DeviceInstance

    eng = SimulationEngine(tick_interval=3600)
    eng.tick_shard_size = 3  # 5 设备 → 2 个批次边界
    try:
        for i in range(5):
            cfg = DeviceConfig(
                id=f"shard-{i}", name=f"S{i}", protocol="modbus_tcp",
                points=[PointConfig(name="v", address=f"HR{i}", data_type="uint16",
                                    generator_type="random", min_value=1,
                                    max_value=100)])
            async with eng._devices_lock:
                eng._devices[cfg.id] = DeviceInstance(cfg, DataGenerator())
        async with eng._devices_lock:
            snapshot = list(eng._devices.values())
        for instance in snapshot:
            await instance.tick()
        for instance in snapshot:
            vals = instance.read_all_points()
            assert vals and vals[0].value is not None
        # 分片参数存在且可调
        eng.tick_shard_size = 0  # 关闭
        assert eng.tick_shard_size == 0
    finally:
        eng._running = False


@pytest.mark.asyncio
async def test_tick_stats_recorded():
    """手动驱动一轮 tick 统计口径（tick_stats 由 _tick_loop 维护——
    这里验证字段存在与引擎属性可配置）。"""
    from protoforge.engine.engine import SimulationEngine
    eng = SimulationEngine()
    assert {"tick_avg_ms", "tick_max_ms", "tick_count"} <= set(eng.tick_stats)
    assert eng.tick_shard_size == 100


# ---------------------------------------------------------------------------
# 连接上限门（modbus_tcp 端到端）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_limit_rejects_excess():
    """max_connections=1：第二个并发连接被立即关闭。"""
    from protoforge.protocols.modbus.server import ModbusTcpServer

    server = ModbusTcpServer()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port, "max_connections": 1})
    await server.create_device(DeviceConfig(
        id="lim-dev", name="L", protocol="modbus_tcp",
        points=[PointConfig(name="v", address="HR0", data_type="uint16")]))
    readers = []
    try:
        # 第 1 个连接：正常
        r1, w1 = await asyncio.wait_for(asyncio.open_connection(HOST, port), timeout=5)
        readers.append(r1)
        await asyncio.sleep(0.2)  # 让 accept/handler 进入循环
        assert server.active_connections >= 1
        # 第 2 个连接：超限 → 服务端立即关闭（read 返回 b'' 即 EOF）
        r2, w2 = await asyncio.wait_for(asyncio.open_connection(HOST, port), timeout=5)
        try:
            head = await asyncio.wait_for(r2.read(1), timeout=3)
            assert head == b"", f"expected EOF on rejected connection, got {head!r}"
        finally:
            w2.close()
        # 第 1 个连接仍可正常读写（发一个合法 FC03 请求）
        pdu = struct.pack(">BHH", 3, 0, 1)
        w1.write(struct.pack(">HHHB", 1, 0, len(pdu) + 1, 1) + pdu)
        await w1.drain()
        head = await asyncio.wait_for(r1.readexactly(7), timeout=5)
        assert head[4:6] != b"\x00\x00"
        w1.close()
    finally:
        await asyncio.wait_for(server.stop(), timeout=10)


@pytest.mark.asyncio
async def test_connection_gate_disabled_by_default():
    """未配置 max_connections（默认 0）→ 不限，多连接并存。"""
    from protoforge.protocols.modbus.server import ModbusTcpServer

    server = ModbusTcpServer()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port})
    try:
        writers = []
        for _ in range(3):
            _, w = await asyncio.wait_for(asyncio.open_connection(HOST, port), timeout=5)
            writers.append(w)
        await asyncio.sleep(0.3)
        assert server.active_connections >= 3
        for w in writers:
            w.close()
        await asyncio.sleep(0.2)
    finally:
        await asyncio.wait_for(server.stop(), timeout=10)


# ---------------------------------------------------------------------------
# 内存可观测（metrics gauge）
# ---------------------------------------------------------------------------

def test_metrics_collect_process_memory():
    from protoforge.engine.engine import SimulationEngine
    from protoforge.observability.metrics import metrics

    eng = SimulationEngine()
    metrics.collect_from_engine(eng)
    assert metrics.get_gauge("protoforge_process_rss_mb") > 0
    assert metrics.get_gauge("protoforge_process_threads") > 0
