"""内置基准场景（v1.11.0）——官方数字与用户复现的唯一定义源。

每个场景是 ``async def scenario(**params) -> dict``，返回 metrics 字典
（延迟分位/吞吐/tick 时长/内存增量）。全部在**独立引擎/端口**上运行，
不污染运行中的主引擎；结束释放全部资源。

场景清单（``BUILTIN_SCENARIOS`` 供 CLI/API 展示）：
  - engine_tick_generation  引擎生成吞吐：N 设备 × M 点位，手动驱动 tick
  - modbus_wire_read        Modbus TCP 线级读延迟（真实 socket，P50/P95/P99）
  - modbus_concurrent_read  并发客户端线级读吞吐
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from protoforge.benchmark.runner import percentiles

logger = logging.getLogger(__name__)


def _rss_mb() -> float:
    rss = 0.0
    try:
        import psutil
        rss = psutil.Process().memory_info().rss / 1024 / 1024
    except Exception as e:
        logger.debug("rss unavailable: %s", e)  # psutil 缺失时内存指标记 0
    return rss


def BUILTIN_SCENARIOS() -> list[dict[str, Any]]:
    """场景元数据（CLI/API 展示用）。"""
    return [
        {
            "name": "engine_tick_generation",
            "description": "引擎生成吞吐：N 设备 × M 点位逐 tick 生成时长",
            "params": {"devices": 100, "points_per_device": 50, "ticks": 20},
        },
        {
            "name": "modbus_wire_read",
            "description": "Modbus TCP 线级读延迟（真实 socket 单客户端）",
            "params": {"reads": 1000, "points": 50},
        },
        {
            "name": "modbus_concurrent_read",
            "description": "Modbus TCP 并发客户端吞吐",
            "params": {"clients": 10, "reads_per_client": 100},
        },
    ]


SCENARIO_REGISTRY: dict[str, Callable[..., Any]] = {}  # type: ignore[name-defined]


def _register(name: str):
    def deco(fn):
        SCENARIO_REGISTRY[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------------------
# ① 引擎生成吞吐
# ---------------------------------------------------------------------------

def _port_serving(port: int, timeout: float = 0.5) -> bool:
    """端口可连即视为有服务在监听。"""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _free_tcp_port() -> int:
    """从 OS 取一个当前无监听的 TCP 端口（重试 20 次）。"""
    import socket

    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.3)
        try:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
        finally:
            probe.close()
    raise RuntimeError("no free TCP port available")


@_register("engine_tick_generation")
async def bench_engine_tick(devices: int = 100, points_per_device: int = 50,
                            ticks: int = 20) -> dict[str, Any]:
    """独立引擎 + N 设备 × M 点位（正弦/随机），手动驱动 tick 计时。"""
    from protoforge.engine.engine import SimulationEngine
    from protoforge.models.device import DeviceConfig, PointConfig

    eng = SimulationEngine(tick_interval=3600)  # 不跑后台 tick，手动驱动
    rss_before = _rss_mb()
    t0 = time.perf_counter()
    try:
        for i in range(devices):
            pts = []
            for j in range(points_per_device):
                gt = "sine" if j % 2 == 0 else "random"
                pts.append(PointConfig(
                    name=f"p{j}", address=f"HR{j}", data_type="float32",
                    generator_type=gt,
                    generator_config={"min": 10.0, "max": 20.0} if gt == "random" else {},
                    min_value=10.0, max_value=20.0,
                ))
            await eng.create_device(DeviceConfig(
                id=f"bench-{i:04d}", name=f"BP{i}", protocol="modbus_tcp",
                points=pts))
        setup_seconds = time.perf_counter() - t0

        tick_durations: list[float] = []
        for _ in range(max(1, ticks)):
            t = time.perf_counter()
            async with eng._devices_lock:
                snapshot = list(eng._devices.values())
            for instance in snapshot:
                await instance.tick()
            tick_durations.append((time.perf_counter() - t) * 1000)

        total_points = devices * points_per_device
        metrics = {
            "devices": devices,
            "points_total": total_points,
            "ticks": len(tick_durations),
            "tick_avg_ms": round(sum(tick_durations) / len(tick_durations), 3),
            "tick_max_ms": round(max(tick_durations), 3),
            "tick_p95_ms": percentiles(tick_durations)["latency_p95_ms"],
            "setup_seconds": round(setup_seconds, 2),
            "memory_rss_delta_mb": round(_rss_mb() - rss_before, 2),
        }
        return metrics
    finally:
        eng._running = False
        try:
            await asyncio.wait_for(eng.stop(), timeout=30)
        except Exception as e:
            logger.debug("bench engine stop: %s", e)


# ---------------------------------------------------------------------------
# ② Modbus 线级读延迟（真实 socket）
# ---------------------------------------------------------------------------

@_register("modbus_wire_read")
async def bench_modbus_wire(reads: int = 1000, points: int = 50) -> dict[str, Any]:
    """单个 pymodbus 客户端对 ProtoForge Modbus TCP 从站连续读保持寄存器。"""
    from pymodbus.client import AsyncModbusTcpClient
    from pymodbus.framer import FramerType

    from protoforge.models.device import DeviceConfig, PointConfig
    from protoforge.protocols.modbus.server import ModbusTcpServer

    server = ModbusTcpServer()
    port = _free_tcp_port()
    await server.start({"host": "127.0.0.1", "port": port})
    await server.create_device(DeviceConfig(
        id="bench-mod", name="Bench", protocol="modbus_tcp",
        points=[PointConfig(name=f"p{j}", address=f"HR{j}", data_type="uint16",
                            generator_type="fixed", fixed_value=j)
                for j in range(max(1, points))]))
    for _ in range(50):
        if _port_serving(port):
            break
        await asyncio.sleep(0.1)

    client = AsyncModbusTcpClient("127.0.0.1", port=port, framer=FramerType.SOCKET,
                                  timeout=5, retries=1)
    rss_before = _rss_mb()
    latencies: list[float] = []
    errors = 0
    try:
        if not await client.connect():
            raise ConnectionError("benchmark client connect failed")
        t0 = time.perf_counter()
        for _ in range(max(1, reads)):
            t = time.perf_counter()
            rr = await client.read_holding_registers(0, count=2, device_id=1)
            latencies.append((time.perf_counter() - t) * 1000)
            if rr is None or rr.isError():
                errors += 1
        duration = time.perf_counter() - t0
        metrics = percentiles(latencies)
        metrics.update({
            "reads": len(latencies),
            "errors": errors,
            "throughput_rps": round(len(latencies) / duration, 1),
            "memory_rss_delta_mb": round(_rss_mb() - rss_before, 2),
        })
        return metrics
    finally:
        try:
            client.close()
        except Exception as close_err:
            logger.debug("benchmark client close: %s", close_err)
        try:
            await asyncio.wait_for(server.stop(), timeout=15)
        except Exception as e:
            logger.debug("bench modbus server stop: %s", e)


# ---------------------------------------------------------------------------
# ③ 并发客户端吞吐
# ---------------------------------------------------------------------------

@_register("modbus_concurrent_read")
async def bench_modbus_concurrent(clients: int = 10,
                                  reads_per_client: int = 100) -> dict[str, Any]:
    """C 个并发 pymodbus 客户端同时读——吞吐与尾延迟。"""
    from pymodbus.client import AsyncModbusTcpClient
    from pymodbus.framer import FramerType

    from protoforge.models.device import DeviceConfig, PointConfig
    from protoforge.protocols.modbus.server import ModbusTcpServer

    server = ModbusTcpServer()
    port = _free_tcp_port()
    await server.start({"host": "127.0.0.1", "port": port,
                        "max_connections": max(clients + 10, 20)})
    await server.create_device(DeviceConfig(
        id="bench-mod", name="Bench", protocol="modbus_tcp",
        points=[PointConfig(name="v", address="HR0", data_type="uint16")]))
    for _ in range(50):
        if _port_serving(port):
            break
        await asyncio.sleep(0.1)

    async def _one(idx: int) -> list[float]:
        client = AsyncModbusTcpClient("127.0.0.1", port=port, framer=FramerType.SOCKET,
                                      timeout=5, retries=1, name=f"bench-{idx}")
        out: list[float] = []
        try:
            if not await client.connect():
                raise ConnectionError(f"client {idx} connect failed")
            for _ in range(max(1, reads_per_client)):
                t = time.perf_counter()
                rr = await client.read_holding_registers(0, count=1, device_id=1)
                out.append((time.perf_counter() - t) * 1000)
                if rr is None or rr.isError():
                    raise IOError(f"client {idx} read error: {rr}")
        finally:
            try:
                client.close()
            except Exception as close_err:
                logger.debug("benchmark client close: %s", close_err)
        return out

    all_latencies: list[float] = []
    errors = 0
    rss_before = _rss_mb()
    try:
        t0 = time.perf_counter()
        results = await asyncio.gather(*[_one(i) for i in range(max(1, clients))],
                                       return_exceptions=True)
        duration = time.perf_counter() - t0
        for r in results:
            if isinstance(r, BaseException):
                errors += 1
                logger.warning("concurrent bench client failed: %s", r)
            else:
                all_latencies.extend(r)
        total_reads = clients * reads_per_client
        metrics = percentiles(all_latencies)
        metrics.update({
            "clients": clients,
            "reads_expected": total_reads,
            "reads_completed": len(all_latencies),
            "errors": errors,
            "throughput_rps": round(len(all_latencies) / duration, 1),
            "memory_rss_delta_mb": round(_rss_mb() - rss_before, 2),
        })
        return metrics
    finally:
        try:
            await asyncio.wait_for(server.stop(), timeout=15)
        except Exception as e:
            logger.debug("bench modbus server stop: %s", e)


async def run_scenario(scenario: str, **params: Any) -> dict[str, Any]:
    """按名执行场景（API/CLI 入口；未知场景抛 ValueError）。"""
    fn = SCENARIO_REGISTRY.get(scenario)
    if fn is None:
        raise ValueError(
            f"Unknown benchmark scenario: {scenario}. "
            f"Available: {', '.join(sorted(SCENARIO_REGISTRY))}")
    return await fn(**params)
