"""MEWTOCOL (Panasonic FP series) wire-level regression tests — v1.4.4 standard frames.

Real-TCP end-to-end: a strict MEWTOCOL-COM master (raw ASCII frames over a real
socket, per Issue #11 scope) verifies:

1. RDD / WDD round-trips on the DT data area (uint16 / int16 / float32),
   with 5-digit DECIMAL start/end (INCLUSIVE) and LOW-BYTE-FIRST word order
   — cross-checked against hiroeorz/mewtocol-go's frame builder/parser.
2. RCS / RCC / WCS / WCC contact round-trips on R/Y areas.
3. BCC covers the WHOLE frame INCLUDING the leading '%'; a corrupted frame
   gets '%STN!21' (2-digit code, no command echo).
4. undefined commands get '%STN!40'.
5. external writes propagate to the engine DeviceInstance.
6. station-number routing (two devices) — station parsed as DECIMAL.
7. "EE" global broadcast executes but is NOT answered (like real PLCs).

Frame grammar (ASCII, CR-terminated):
  request  % <STN:2dec> # <CMD> <params> <BCC:2hex>
  success  % <STN:2dec> $ <CMD> <data> <BCC:2hex>
  error    % <STN:2dec> ! <err:2hex> <BCC:2hex>
  BCC      = XOR of ASCII codes of ALL chars from '%' up to (excluding) BCC.
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
from protoforge.protocols.mewtocol.server import (
    MewtocolServer,
    bcc,
    hex_to_word,
    word_to_hex,
)
import protoforge.main as main_module

HOST = "127.0.0.1"
PORT = 12049


# ---------------------------------------------------------------------------
# mini master helpers (standard frames, mewtocol-go compatible)
# ---------------------------------------------------------------------------

def build_frame(stn, cmd: str, params: str) -> str:
    stn_text = stn if isinstance(stn, str) else f"{stn:02d}"
    payload = f"%{stn_text}#{cmd}{params}"
    return f"{payload}{bcc(payload)}\r"


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
            PointConfig(name="recipe_no", address="LD5", data_type="uint16",
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

    async def send(self, stn, cmd: str, params: str) -> str:
        self.writer.write(build_frame(stn, cmd, params).encode("ascii"))
        await self.writer.drain()
        buf = ""
        while not buf.endswith("\r"):
            chunk = await asyncio.wait_for(self.reader.read(256), timeout=5)
            if not chunk:
                raise ConnectionError("server closed connection")
            buf += chunk.decode("ascii", errors="replace")
        return buf

    async def send_expect_silence(self, stn, cmd: str, params: str, timeout: float = 1.0):
        """Broadcast: write frame, assert NO response arrives within timeout."""
        self.writer.write(build_frame(stn, cmd, params).encode("ascii"))
        await self.writer.drain()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(self.reader.read(256), timeout=timeout)

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
    def parse(resp: str) -> tuple[int, str | None, bool, str]:
        """Return (station, cmd_or_None, is_ok, data_or_error)."""
        body = resp.strip("\r")
        assert body.startswith("%"), resp
        given = body[-2:]
        core = body[:-2]
        assert bcc(core) == given, f"BCC mismatch in response {resp!r}"
        stn, marker, rest = core[1:3], core[3], core[4:]
        if marker == "!":
            return int(stn, 10), None, False, rest[:2]  # 2-digit error, no echo
        # 真实 PLC 响应只回显命令前两个字符（RCS→$RC、WCS→$WC）
        cmd = rest[:2]
        return int(stn, 10), cmd, True, rest[2:]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rd_uint16_low_byte_first(env):
    """RDD DT0：uint16 增量生成器的新值可见；字序为低字节在前（0x04D2 -> "D204"）。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)
    await engine.get_protocol_server("mewtocol").write_point(device.id, "counter", 1234)
    resp = await master.send(1, "RD", "D0000000000")  # DT0..DT0（含首尾）
    stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (stn, cmd, ok) == (1, "RD", True)
    assert data == "D204", f"1234=0x04D2 must transmit low byte first 'D204', got {data!r}"
    assert hex_to_word(data) == 1234


@pytest.mark.asyncio
async def test_rd_int16_negative(env):
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)
    resp = await master.send(1, "RD", "D0001000010")  # DT10..DT10
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("RD", True)
    assert data == "E7FF", f"-25=0xFFE7 low-byte-first 'E7FF', got {data!r}"


@pytest.mark.asyncio
async def test_rd_float32_two_words_low_word_first(env):
    """float32 占 DT20-DT21 两个连续字，低字在低地址；字内仍低字节在前。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)
    resp = await master.send(1, "RD", "D0002000021")  # DT20..DT21（含首尾）
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("RD", True)
    w0 = hex_to_word(data[0:4])
    w1 = hex_to_word(data[4:8])
    raw = (w1 << 16) | w0
    value = struct.unpack(">f", struct.pack(">I", raw))[0]
    assert abs(value - 42.5) < 0.01, f"expected 42.5, got {value} (data={data!r})"


@pytest.mark.asyncio
async def test_wd_roundtrip_and_engine_propagation(env):
    """WDD 写入后 RDD 回读一致（低字节在前解析），且写值传播到引擎。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)
    resp = await master.send(1, "WD", "D0001000010" + "0C00")  # 12 = 0x000C -> "0C00"
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("WD", True)
    assert data == ""  # $WD 无数据

    resp = await master.send(1, "RD", "D0001000010")
    _stn, _cmd, ok, data = MiniMaster.parse(resp)
    assert ok and hex_to_word(data) == 12

    vals = {pv.name: pv.value for pv in engine.get_device_instance(device.id).read_all_points()}
    assert vals["setpoint"] == 12


@pytest.mark.asyncio
async def test_rcs_wcs_contacts(env):
    """RCS/WCS 单点触点读写：R/Y 区，bool 点位与引擎双向同步。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)

    resp = await master.send(1, "RCS", "R0000")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("RC", True)
    assert data == "1"  # run_flag fixed True

    resp = await master.send(1, "WCS", "Y00001")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("WC", True) and data == ""

    resp = await master.send(1, "RCS", "Y0000")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert data == "1"

    vals = {pv.name: pv.value for pv in engine.get_device_instance(device.id).read_all_points()}
    assert vals["output_y0"] in (True, 1)

    await master.send(1, "WCS", "Y00000")
    resp = await master.send(1, "RCS", "Y0000")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert data == "0"


@pytest.mark.asyncio
async def test_rcc_wcc_word_units(env):
    """RCC/WCC 字单位触点读写：word w 的 bit i = 接点 w*16+i。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)

    await master.send(1, "WCS", "Y00001")
    await master.send(1, "WCS", "Y00111")  # 写 Y11（编号 0011 + 状态 1，word0 bit11）
    resp = await master.send(1, "RCC", "Y00000000")  # word0..word0
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (cmd, ok) == ("RC", True)
    assert hex_to_word(data) == (1 << 0) | (1 << 11), f"got {data!r}"

    # WCC 写 word0 = bit0|bit11 清零再读
    resp = await master.send(1, "WCC", "Y00000000" + "0000")
    _stn, cmd, ok, _d = MiniMaster.parse(resp)
    assert (cmd, ok) == ("WC", True)
    resp = await master.send(1, "RCC", "Y00000000")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert hex_to_word(data) == 0


@pytest.mark.asyncio
async def test_bcc_error_response_2digit_no_echo(env):
    """BCC 校验失败返回 '%01!21'（2 位错误码、无命令回显），BCC 含 '%'。"""
    _engine, _device, reader, writer = env
    master = MiniMaster(reader, writer)
    bad = "%01#RDD0000000000XX\r"  # XX 不是正确 BCC
    resp = await master.send_raw(bad)
    stn, cmd, ok, err = MiniMaster.parse(resp)
    assert (stn, cmd, ok) == (1, None, False)
    assert err == "21", f"expected BCC error code 21, got {err!r}"


@pytest.mark.asyncio
async def test_unsupported_command_monitor(env):
    """RM（监视注册）不在支持范围，返回 2 位错误码 40 而非崩溃/静默。"""
    _engine, _device, reader, writer = env
    master = MiniMaster(reader, writer)
    resp = await master.send(1, "RM", "0000000010")
    stn, cmd, ok, err = MiniMaster.parse(resp)
    assert not ok
    assert cmd is None and err == "40"


@pytest.mark.asyncio
async def test_station_routing_two_devices(env):
    """站号按十进制解析路由到不同设备；LD 区（L 码）读写正常。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)

    other = build_device(stn=2, device_id="mewtocol-plc-2")
    await engine.create_device(other)
    await asyncio.sleep(0.1)

    # 站号 2 → 第二台设备（LD5 写 9：0x0009 -> "0900"）
    resp = await master.send(2, "WD", "L0000500005" + "0900")
    _stn, cmd, ok, _d = MiniMaster.parse(resp)
    assert ok
    resp = await master.send(2, "RD", "L0000500005")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert hex_to_word(data) == 9

    # 站号 1 → 第一台设备（LD5 固定值 7）
    resp = await master.send(1, "RD", "L0000500005")
    _stn, cmd, ok, data = MiniMaster.parse(resp)
    assert hex_to_word(data) == 7


@pytest.mark.asyncio
async def test_station_10_decimal_not_hex(env):
    """站号 10 必须按十进制路由到站号 10 的设备（旧实现按 16 进制解析为 16）。"""
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)

    tenth = build_device(stn=10, device_id="mewtocol-plc-10")
    await engine.create_device(tenth)
    await asyncio.sleep(0.1)

    # 站号 "10"（十进制）→ 第 10 站设备（LD5 固定值 7）
    resp = await master.send(10, "RD", "L0000500005")
    stn, cmd, ok, data = MiniMaster.parse(resp)
    assert (stn, ok) == (10, True)
    assert hex_to_word(data) == 7


@pytest.mark.asyncio
async def test_global_broadcast_ee_no_response(env):
    '"EE" 全局广播执行（写入生效）但不回应，与真实 PLC 一致。'
    engine, device, reader, writer = env
    master = MiniMaster(reader, writer)

    await master.send_expect_silence("EE", "WCS", "Y00001")

    # 广播写入已生效（经默认设备）
    vals = {pv.name: pv.value for pv in engine.get_device_instance(device.id).read_all_points()}
    assert vals["output_y0"] in (True, 1)


@pytest.mark.asyncio
async def test_station_conflict_rejected(env):
    """两台设备占用相同站号：协议服务器拒绝注册第二台，原设备继续独占。"""
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

def test_bcc_xor_includes_percent():
    """BCC 必须覆盖含 '%' 的整帧（与 mewtocol-go getBcc 一致）。"""
    # 手工独立计算："%A" -> 0x25 ^ 0x41 = 0x64
    assert bcc("%A") == "64"
    assert bcc("AB") == f"{0x41 ^ 0x42:02X}"
    # 完整请求帧的 BCC 可被 Go 端 isValidBCC 逻辑（XOR 含 '%'）接受
    frame_body = "%01#RDD0000000000"
    acc = 0
    for ch in frame_body:
        acc ^= ord(ch)
    assert bcc(frame_body) == f"{acc:02X}"


def test_word_hex_low_byte_first():
    assert word_to_hex(0x04D2) == "D204"
    assert hex_to_word("D204") == 0x04D2
    assert word_to_hex(0xFFE7) == "E7FF"
    assert word_to_hex(0) == "0000"
    for w in (0x0001, 0x8000, 0xFFFF, 0x1234):
        assert hex_to_word(word_to_hex(w)) == w


def test_word_value_codec():
    from protoforge.protocols.mewtocol.server import _value_to_words, _words_to_value
    assert _value_to_words(-25, DataType.INT16) == [0xFFE7]
    assert _words_to_value([0xFFE7], DataType.INT16) == -25
    words = _value_to_words(42.5, DataType.FLOAT32)
    assert len(words) == 2 and words[0] == (words[0] & 0xFFFF)
    assert abs(_words_to_value(words, DataType.FLOAT32) - 42.5) < 1e-6
