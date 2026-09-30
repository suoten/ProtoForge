"""UX batch: connection diagnostics, bind-host validation, point Force, version compare.

Real-engine tests (real Modbus TCP server on a free port), no mocks for the
network paths.
"""

import asyncio
import os

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_ux_diagnostics.db")

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
from protoforge.core.netutils import detect_lan_ip, is_local_bind_host, list_local_ips
import protoforge.main as main_module


def _pick_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _pick_free_port()


def _make_device() -> DeviceConfig:
    return DeviceConfig(
        id="ux-plc",
        name="UX Test PLC",
        protocol="modbus_tcp",
        protocol_config={"host": "127.0.0.1", "port": PORT, "slave_id": 1},
        points=[
            PointConfig(name="temperature", address="10", data_type=DataType.FLOAT32,
                        generator_type=GeneratorType.FIXED, fixed_value=42.5, access="rw"),
            PointConfig(name="pressure", address="20", data_type=DataType.FLOAT32,
                        generator_type=GeneratorType.SINE, min_value=1.0, max_value=9.0, access="rw"),
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
    await asyncio.sleep(0.3)

    yield engine, device

    await engine.stop()
    await main_module._database.close()
    _clear_registry()


# ---------------------------------------------------------------------------
# netutils
# ---------------------------------------------------------------------------

def test_list_local_ips_contains_loopback():
    ips = list_local_ips()
    assert "127.0.0.1" in ips


def test_is_local_bind_host():
    assert is_local_bind_host("0.0.0.0")
    assert is_local_bind_host("127.0.0.1")
    assert is_local_bind_host("localhost")
    assert is_local_bind_host(detect_lan_ip() or "0.0.0.0")
    # 外部服务器地址（EMQX 误填场景）与非法输入必须拒绝
    assert not is_local_bind_host("203.0.113.5")
    assert not is_local_bind_host("emqx.example.com")
    assert not is_local_bind_host("192.168.0.999")


# ---------------------------------------------------------------------------
# bind-host pre-validation on start_protocol
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_protocol_rejects_remote_bind_host(env):
    """host 填外部服务器 IP（EMQX 误填场景）必须启动失败并给出本机地址建议。"""
    engine, _device = env
    with pytest.raises(ValueError, match="not a local NIC address"):
        await engine.start_protocol("modbus_tcp", {"host": "203.0.113.5", "port": _pick_free_port()},
                                    restart=True)


# ---------------------------------------------------------------------------
# point Force
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_force_pins_value_across_ticks(env):
    """Force：固定值跨 tick 保持，压过正弦生成器；释放后恢复动态。"""
    engine, device = env

    engine.set_point_override(device.id, "pressure", 6.6)
    await asyncio.sleep(0.6)  # 跑几个 tick

    vals = {pv.name: pv.value for pv in engine.get_device_instance(device.id).read_all_points()}
    assert abs(vals["pressure"] - 6.6) < 1e-6, f"force not applied: {vals}"

    # 强制状态可查询
    assert engine.get_point_overrides(device.id) == {"pressure": 6.6}

    # 释放 → 生成器恢复（正弦值在 1.0-9.0 区间且会随 tick 变化）
    engine.set_point_override(device.id, "pressure", None)
    assert engine.get_point_overrides(device.id) == {}
    await asyncio.sleep(0.3)
    vals = {pv.name: pv.value for pv in engine.get_device_instance(device.id).read_all_points()}
    assert 0.5 <= float(vals["pressure"]) <= 9.5


@pytest.mark.asyncio
async def test_force_nonexistent_point_raises(env):
    engine, device = env
    with pytest.raises(ValueError, match="Point not found"):
        engine.set_point_override(device.id, "no_such_point", 1.0)


# ---------------------------------------------------------------------------
# diagnostics route functions (direct call against registry engine)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_diagnose_protocol_all_green(env):
    from protoforge.api.v1 import diagnostics_routes as diag

    engine, device = env
    result = await diag.diagnose_protocol("modbus_tcp")
    assert result["ok"] is True
    keys = {c["key"]: c for c in result["checks"]}
    assert keys["registered"]["ok"] and keys["running"]["ok"]
    assert keys["bind_address"]["ok"]
    assert keys["port_listening"]["ok"]
    assert keys["devices_registered"]["ok"]


@pytest.mark.asyncio
async def test_diagnose_unknown_protocol(env):
    from protoforge.api.v1 import diagnostics_routes as diag

    result = await diag.diagnose_protocol("no_such_proto")
    assert result["ok"] is False
    assert result["checks"][0]["key"] == "registered"
    assert result["checks"][0]["ok"] is False


@pytest.mark.asyncio
async def test_diagnose_outbound_probe(env):
    """outbound 探测：本机运行中的 Modbus 端口应可达。"""
    from protoforge.api.v1 import diagnostics_routes as diag

    _engine, _device, = env
    port = _engine.get_protocol_running_port("modbus_tcp")
    result = await diag.diagnose_outbound({"host": "127.0.0.1", "port": int(port)})
    assert result["ok"] is True and result["latency_ms"] is not None

    bad = await diag.diagnose_outbound({"host": "127.0.0.1", "port": 1})
    assert bad["ok"] is False


# ---------------------------------------------------------------------------
# version compare
# ---------------------------------------------------------------------------

def test_is_newer():
    from protoforge.api.v1.system_routes import _is_newer
    assert _is_newer("v1.4.0", "1.3.4")
    assert _is_newer("1.10.0", "1.9.9")
    assert not _is_newer("1.3.4", "1.3.4")
    assert not _is_newer("1.3.3", "1.3.4")
    assert not _is_newer("", "1.3.4")
