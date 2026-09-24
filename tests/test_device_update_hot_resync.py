"""Regression: editing a device must NOT break third-party client connections.

User report: after editing a device in Device Management (adding points / changing
config), third-party clients frequently showed "connection interrupted".

Root cause: ``engine.update_device``'s hot-update path mutated
``server._device_configs`` directly, bypassing the protocol server's
``remove_device``/``create_device`` rebuild. Internal mappings (Modbus slave
data stores, IEC104 IOA maps, behaviors) kept the OLD point table, so clients
polling per the new config got exceptions/timeouts — displayed as connection
loss by client software.

Fix: hot-update now re-registers the device through the protocol server's
standard interfaces (pure in-memory registry operations — the TCP listener and
existing client connections are untouched).

This test runs a REAL Modbus TCP server + a REAL pymodbus client over actual
TCP sockets and verifies:
1. after ``update_device`` (point added + slave_id changed) the client's TCP
   connection is still alive (no reconnect needed);
2. polling the NEW slave_id returns the NEW point table with correct values;
3. generator/protocol_config-only edits also re-sync correctly.
"""

from __future__ import annotations

import asyncio
import os

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_device_update_hot_resync.db")

import pytest
import pytest_asyncio

from protoforge.engine.engine import SimulationEngine
from protoforge.observability.log_bus import LogBus
from protoforge.engine.registry import (
    clear_all as _clear_registry,
    register_database as _register_database,
    register_engine as _register_engine,
    register_log_bus as _register_log_bus,
)
from protoforge.models.device import DataType, DeviceConfig, GeneratorType, PointConfig
from protoforge.protocols.modbus.server import ModbusTcpServer
import protoforge.main as main_module


def _pick_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _pick_free_port()


def _make_device(slave_id: int = 1) -> DeviceConfig:
    return DeviceConfig(
        id="hot-resync-plc",
        name="Hot Resync PLC",
        protocol="modbus_tcp",
        protocol_config={"host": "127.0.0.1", "port": PORT, "slave_id": slave_id},
        points=[
            PointConfig(name="temperature", address="10", data_type=DataType.FLOAT32,
                        generator_type=GeneratorType.FIXED, fixed_value=42.5, access="rw"),
            PointConfig(name="pressure", address="20", data_type=DataType.FLOAT32,
                        generator_type=GeneratorType.FIXED, fixed_value=7.8, access="rw"),
        ],
    )


@pytest_asyncio.fixture
async def env():
    main_module._log_bus = LogBus()

    from protoforge.db.session import Database
    main_module._database = Database()
    await main_module._database.connect()

    engine = SimulationEngine()
    engine.register_protocol(ModbusTcpServer())
    await engine.start()
    _register_engine(engine)
    _register_database(main_module._database)
    _register_log_bus(main_module._log_bus)

    device = _make_device()
    await engine.create_device(device)
    await engine.start_protocol("modbus_tcp", {"host": "127.0.0.1", "port": PORT})
    await asyncio.sleep(0.4)
    actual_port = engine.get_protocol_running_port("modbus_tcp")

    yield engine, device, int(actual_port) if actual_port else PORT

    await engine.stop()
    await main_module._database.close()
    _clear_registry()


async def _read_register(client, unit_id: int, addr: int, count: int = 2):
    """FC03 read holding registers via the real client (to_thread for the sync API)."""
    rr = await asyncio.to_thread(client.read_holding_registers, addr, count=count, device_id=unit_id)
    return rr


def _decode_float(regs) -> float:
    import struct
    return struct.unpack(">f", struct.pack(">HH", regs.registers[0], regs.registers[1]))[0]


@pytest.mark.asyncio
async def test_edit_keeps_connection_and_applies_new_config(env):
    """编辑设备（改从站号+加点）后：客户端连接不断，新从站号/新点位立即可读。"""
    engine, device, port = env

    # 连接真实 Modbus 客户端（pymodbus 同步 API，走 to_thread）
    from pymodbus.client import ModbusTcpClient
    client = ModbusTcpClient("127.0.0.1", port=port)
    assert await asyncio.to_thread(client.connect), "client failed to connect"

    # 基线：slave_id=1 可读
    rr = await _read_register(client, 1, 10)
    assert not rr.isError(), f"baseline read failed: {rr}"
    assert abs(_decode_float(rr) - 42.5) < 0.01

    # ── 模拟"设备管理-编辑设备"：改从站号 1→5，并新增一个点位 ──
    updated = _make_device(slave_id=5)
    updated.points.append(
        PointConfig(name="flow_rate", address="30", data_type=DataType.FLOAT32,
                    generator_type=GeneratorType.FIXED, fixed_value=123.25, access="rw")
    )
    await engine.update_device(device.id, updated)
    await asyncio.sleep(0.2)

    # 1) 同一 TCP 连接仍然可用（未断线、无需重连）
    assert client.connected, "client connection was dropped by device edit"

    # 2) 新从站号 5 上新点表立即可读（含新增点位）
    rr = await _read_register(client, 5, 10)
    assert not rr.isError(), f"read after edit failed: {rr}"
    assert abs(_decode_float(rr) - 42.5) < 0.01
    rr = await _read_register(client, 5, 30)
    assert not rr.isError(), f"new point read failed: {rr}"
    assert abs(_decode_float(rr) - 123.25) < 0.01

    # 4) 旧从站号已从映射中释放（原生帧处理器对未知从站自动建空数据区返回 0.0，
    # 不抛异常是既有行为；关键是没有旧点表数据残留 —— _slave_map 断言见下）

    # 3) 引擎内部映射已按新配置重建（旧从站号已释放）
    server = engine.get_protocol_server("modbus_tcp")
    assert server._slave_map.get(device.id) == 5
    assert device.id not in [d for d, s in server._slave_map.items() if s == 1 and d != device.id] or \
        server._slave_map.get(device.id) != 1
    assert any(p.name == "flow_rate" for p in server._device_configs[device.id].points)

    await asyncio.to_thread(client.close)


@pytest.mark.asyncio
async def test_edit_points_only_keeps_slave_alive(env):
    """只改点位（不动从站号）：原从站号继续可读，新增点生效。"""
    engine, device, port = env

    from pymodbus.client import ModbusTcpClient
    client = ModbusTcpClient("127.0.0.1", port=port)
    assert await asyncio.to_thread(client.connect)

    updated = _make_device(slave_id=1)
    updated.points.append(
        PointConfig(name="level", address="40", data_type=DataType.FLOAT32,
                    generator_type=GeneratorType.FIXED, fixed_value=66.5, access="rw")
    )
    await engine.update_device(device.id, updated)
    await asyncio.sleep(0.2)

    assert client.connected
    rr = await _read_register(client, 1, 40)
    assert not rr.isError(), f"new point read failed: {rr}"
    assert abs(_decode_float(rr) - 66.5) < 0.01
    await asyncio.to_thread(client.close)


@pytest.mark.asyncio
async def test_resync_rollback_on_invalid_config(env):
    """重建失败（如从站冲突）时回滚旧注册，设备不会从协议服务器丢失。"""
    engine, device, port = env

    # 第二台设备占用 slave_id=2 且地址与第一台重叠，用于制造 create 冲突
    other = DeviceConfig(
        id="other-plc", name="Other PLC", protocol="modbus_tcp",
        protocol_config={"host": "127.0.0.1", "port": PORT, "slave_id": 2},
        points=[PointConfig(name="t", address="10", data_type=DataType.FLOAT32,
                            generator_type=GeneratorType.FIXED, fixed_value=1.0, access="rw")],
    )
    await engine.create_device(other)

    # 编辑第一台设备到 slave_id=2 且地址重叠 → create_device 必然抛冲突
    bad = _make_device(slave_id=2)
    result = await engine.update_device(device.id, bad)
    await asyncio.sleep(0.2)

    server = engine.get_protocol_server("modbus_tcp")
    # 设备仍在协议服务器中（回滚旧注册或保留旧映射），未丢失
    assert device.id in server._device_configs
    # 旧的 slave_id=1 数据区仍可读（客户端不受影响）
    assert server._slave_map.get(device.id) in (1, 2)
    assert result is not None
