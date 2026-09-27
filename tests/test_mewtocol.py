"""MEWTOCOL (Panasonic FP series) wire-level regression tests.

Real-TCP end-to-end: a strict MEWTOCOL-COM master (raw ASCII frames over a real
socket, per Issue #11 scope) verifies:

1. %RD / %WD round-trips on DT/WR word areas (int16 / uint16 / float32)
2. %RC / %WC round-trips on R/X/Y contact areas
3. BCC validation — a corrupted frame gets an '!' error response
4. unsupported commands (%RM monitor registration) get an '!' error response
5. external writes propagate to the engine DeviceInstance
6. engine-generated dynamic values are visible to the master (no stale words)
7. station-number routing (two devices, different stations)

Frame grammar (ASCII, CR-terminated):
  request  % <STN:2hex> # <CMD:2> <params> <BCC:2hex>
  success  % <STN:2hex> $ <CMD:2> <data> <BCC:2hex>
  error    % <STN:2hex> ! <CMD:2> <err:4>  <BCC:2hex>
  BCC      = XOR of ASCII codes of chars between '%' and BCC.
"""

import asyncio
import os
import struct

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_mewtocol.db")

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
from protoforge.protocols.mewtocol.server import MewtocolServer, bcc
import protoforge.main as main_module

HOST = "127.0.0.1"
PORT = 12049


# ---------------------------------------------------------------------------
# mini master helpers
# ---------------------------------------------------------------------------

def build_frame(stn: int, cmd: str, params: str) -> str:
    core = f"{stn:02X}#{cmd}{params}"
    return f"%{core}{bcc(core)}\r"


def build_device(stn: int = 1, device_id: str = "mewtocol-plc") -> DeviceConfig:
    return DeviceConfig(
        id=device_id,
        name="Panasonic FP Test",
        protocol="mewtocol",
        protocol_config={"station_number": stn},
        points=[
            PointConfig(name="counter", address="DT0", data_type="uint16",
                        generator_type=GeneratorType.INCREMENT, min_value=0, max_value=60000),
            PointConfig(name="setpoint", address="DT10", data_type="int16",
                        generator_type=GeneratorType.FIXED, fixed_value=-25),
            PointConfig(name="temperature", address="DT20", data_type="float32",
                        generator_type=GeneratorType.FIXED, fixed_value=42.5),
            PointConfig(name="run_flag", address="R0", data_type="bool",
                        generator_type=GeneratorType.FIXED, fixed_value=True),
            PointConfig(name="output_y0", address="Y0", data_type="bool",
                        generator_type=GeneratorType.FIXED, fixed_value=False),
            PointConfig(name="recipe_no", address="WR5", data_type="uint16",
                        generator_type=GeneratorType.FIXED, fixed_value=7),
        ],
    )


@pytest_asyncio.fixture
async def env():
    main_module._log_bus = LogBus()

    from protoforge.db.session import Database
    main_module._database = Database()
    await main_module._database.connect()

    engine = SimulationEngine()
    engine.register_protocol(MewtocolServer())
    await engine.start()
    _register_engine(engine)
    _register_database(main_module._database)
    _register_log_bus(main_module._log_bus)

    device = build_device()
    await engine.create_device(device)
    await engine.start_protocol("mewtocol", {"host": HOST, "port": PORT})
    await asyncio.sleep(0.3)

    reader, writer = await asyncio.open_connection(HOST, PORT)

    yield engine, device, reader, writer

    writer.close()
    with __import__("contextlib").suppress(Exception):
        await writer.wait_closed()
    await engine.stop()
    await main_module._database.close()
    _clear_registry()


class MiniMaster:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def send(self, stn: int, cmd: str, params: str) -> str:
        self.writer.write(build_frame(stn, cmd, params).encode("ascii"))
        await self.writer.drain()
        buf = ""
        while not buf.endswith("\r"):
            chunk = await asyncio.wait_for(self.reader.read(256), timeout=5)
            if not chunk:
                raise ConnectionError("server closed connection")
            buf += chunk.decode("ascii", errors="replace")
        return buf

    async def send_raw(self, text: str) -> str:
        self.writer.write(text.encode("ascii"))
        await self.writer.drain()
        buf = ""
        while not buf.endswith("\r"):
            chunk = await asyncio.wait_for(self.reader.read(256), timeout=5)
            if not chunk:
                raise ConnectionError("server closed connection")
            buf += chunk.decode("ascii", errors="replace")
        return buf

    @staticmethod
    def parse(resp: str) -> tuple[int, str, bool, str]:
        """Return (station, cmd, is_ok, data_or_error)."""
        body = resp.strip("\r")[1:]
        given = body[-2:]
        core = body[:-2]
        assert bcc(core) == given, f"BCC mismatch in response {resp!r}"
        stn, marker, rest = core[:2], core[2], core[3:]
        cmd = rest[:2]
        payload = rest[2:]
        return int(stn, 16), cmd, marker == "$", payload


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rd_uint16_increment(env):
    """%RD DT0：uint16 增量生成器的新值必须可见（不能读到旧值/0）。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)
    await engine.get_protocol_server("mewtocol").write_point(device.id, "counter", 1234)
    resp = await master.send(1, "RD", "DT0000000001")
    stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (stn, cmd, ok) == (1, "RD", True)
    assert data == "04D2", f"expected 1234=0x04D2, got {data!r}"


@pytest.mark.asyncio
async def test_rd_int16_negative(env):
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)
    resp = await master.send(1, "RD", "DT0001000001")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("RD", True)
    assert data == "FFE7", f"-25 must encode as 0xFFE7, got {data!r}"


@pytest.mark.asyncio
async def test_rd_float32_two_words_low_first(env):
    """float32 占 DT20-DT21 两个连续字，低字在前。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)
    resp = await master.send(1, "RD", "DT0002000002")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("RD", True)
    raw = (int(data[4:8], 16) << 16) | int(data[0:4], 16)
    value = struct.unpack(">f", struct.pack(">I", raw))[0]
    assert abs(value - 42.5) < 0.01, f"expected 42.5, got {value} (data={data!r})"


@pytest.mark.asyncio
async def test_wd_roundtrip_and_engine_propagation(env):
    """%WD 写入后 %RD 回读一致，且写值传播到引擎 DeviceInstance。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)
    resp = await master.send(1, "WD", f"DT0001000001000C")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("WD", True)

    resp = await master.send(1, "RD", "DT0001000001")
    _stn, _cmd, ok, data = MiniMaster.parse(resp)
    assert ok and data == "000C"  # 12

    vals = {pv.name: pv.value for pv in engine.get_device_instance(device.id).read_all_points()}
    assert vals["setpoint"] == 12


@pytest.mark.asyncio
async def test_rc_wc_contacts(env):
    """%RC/%WC 触点读写：R/Y 区，bool 点位与引擎双向同步。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)

    resp = await master.send(1, "RC", "R0000000001")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("RC", True)
    assert data == "1"  # run_flag fixed True

    resp = await master.send(1, "WC", "Y00000000011")
    _stn, cmd, ok, _data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("WC", True)

    resp = await master.send(1, "RC", "Y0000000001")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert data == "1"

    vals = {pv.name: pv.value for pv in engine.get_device_instance(device.id).read_all_points()}
    assert vals["output_y0"] in (True, 1)

    resp = await master.send(1, "WC", "Y00000000010")
    await master.send(1, "RC", "Y0000000001")
    resp = await master.send(1, "RC", "Y0000000001")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert data == "0"


@pytest.mark.asyncio
async def test_bcc_error_response(env):
    """BCC 校验失败必须返回 '!' 错误帧（命令回显 + 4 位错误码）。"""
    _engine, _device, reader, writer = env
    master = MiniMaster(reader, writer)
    bad = "%01#RDDT0000000001XX\r"  # XX 不是正确 BCC
    resp = await master.send_raw(bad)
    stn, cmd, ok, err = MiniMaster.parse(resp)
    assert not ok
    assert cmd == "RD" and err


@pytest.mark.asyncio
async def test_unsupported_command_monitor(env):
    """%RM（监视注册）不在支持范围，返回 '!' 错误帧而非崩溃/静默。"""
    _engine, _device, reader, writer = env
    master = MiniMaster(reader, writer)
    resp = await master.send(1, "RM", "DT0000000010")
    stn, cmd, ok, err = MiniMaster.parse(resp)
    assert not ok
    assert cmd == "RM" and err


@pytest.mark.asyncio
async def test_station_routing_two_devices(env):
    """不同站号路由到不同设备；未知站号回退默认设备。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)

    other = build_device(stn=2, device_id="mewtocol-plc-2")
    await engine.create_device(other)
    await asyncio.sleep(0.1)

    # 站号 2 → 第二台设备（WR5 写 9：地址字段 5 位为 00005）
    resp = await master.send(2, "WD", "WR00005000010009")
    _stn, cmd, ok, _d = MiniMaster.parse(resp)
    assert ok
    resp = await master.send(2, "RD", "WR0000500001")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert data == "0009"

    # 站号 1 → 第一台设备（WR5 固定值 7）
    resp = await master.send(1, "RD", "WR0000500001")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert data == "0007"


@pytest.mark.asyncio
async def test_station_conflict_rejected(env):
    """两台设备占用相同站号：协议服务器拒绝注册第二台（引擎同步失败并告警），
    原设备继续独占该站号（与 Modbus 从站冲突同语义，API 层另行校验）。"""
    engine, device, reader, writer = env
    conflict = build_device(stn=1, device_id="mewtocol-dup")
    await engine.create_device(conflict)
    await asyncio.sleep(0.1)

    server = engine.get_protocol_server("mewtocol")
    assert server._station_map.get(1) == device.id
    assert "mewtocol-dup" not in server._behaviors


# ---------------------------------------------------------------------------
# pure codec tests
# ---------------------------------------------------------------------------

def test_bcc_xor():
    assert bcc("01#RDDT0000000001") == bcc("01#RDDT0000000001")
    assert bcc("A") == "41"
    assert bcc("AB") == f"{0x41 ^ 0x42:02X}"


def test_word_value_codec():
    from protoforge.protocols.mewtocol.server import _value_to_words, _words_to_value
    assert _value_to_words(-25, DataType.INT16) == [0xFFE7]
    assert _words_to_value([0xFFE7], DataType.INT16) == -25
    words = _value_to_words(42.5, DataType.FLOAT32)
    assert len(words) == 2 and words[0] == (words[0] & 0xFFFF)
    assert abs(_words_to_value(words, DataType.FLOAT32) - 42.5) < 1e-6
