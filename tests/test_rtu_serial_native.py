"""Issue #36 回归：Modbus RTU 串口模式必须真正打开串口，失败必须明确报错。

旧行为（被本套用例钉死的 bug）：pymodbus 3.13 OldAPI 失效后，串口模式被
静默替换成 TCP bridge——串口从未被打开，用户在串口监视工具里看到 COM 口
"空闲"，且无任何提示。新行为：串口模式真正 serial.Serial() 占用 COM 口
（自持 RTU 帧循环 + 复用 _process_modbus_frame），打开失败置 ERROR 并抛
明确异常；TCP bridge 仅在显式 mode=tcp_bridge（或 edgelite int port）时启用。
"""

import asyncio
import struct
from unittest.mock import patch

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.modbus._common import crc16_modbus
from protoforge.protocols.modbus.rtu_server import ModbusRtuServer
from tests.wire_golden_harness import free_tcp_port


class FakeSerial:
    """内存串口：测试预置收到的请求字节，收集服务端写出的响应字节。"""

    def __init__(self, incoming: bytes = b""):
        self.is_open = True
        self._in = bytearray(incoming)
        self.written = bytearray()

    @property
    def in_waiting(self) -> int:
        return len(self._in)

    def read(self, n: int = 1) -> bytes:
        out = bytes(self._in[:n])
        del self._in[:n]
        return out

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def close(self) -> None:
        self.is_open = False


def _read_holding_request(addr: int = 1, start: int = 0, count: int = 2) -> bytes:
    pdu = bytes([addr, 3]) + struct.pack(">HH", start, count)
    return pdu + struct.pack("<H", crc16_modbus(pdu))


def _make_server() -> ModbusRtuServer:
    server = ModbusRtuServer()
    server._behaviors["dev1"] = __import__(
        "protoforge.protocols.modbus._common", fromlist=["ModbusDeviceBehavior"]
    ).ModbusDeviceBehavior([
        PointConfig(name="v", address="HR0", data_type="uint16"),
    ])
    server._device_configs["dev1"] = DeviceConfig(
        id="dev1", name="d", protocol="modbus_rtu",
        points=[PointConfig(name="v", address="HR0", data_type="uint16")],
    )
    server._slave_map["dev1"] = 1
    store = server._get_data_store(1)
    store.holding_regs[0] = 0x1234
    return server


# ---------------------------------------------------------------------------
# 自持串口帧循环
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serial_mode_reads_and_responds():
    """串口收到合法请求帧 → 服务端经同一串口写回带 CRC 的响应帧。"""
    server = _make_server()
    fake = FakeSerial(_read_holding_request(addr=1, start=0, count=2))
    with patch.object(server, "_open_serial", side_effect=lambda: setattr(server, "_serial", fake)):
        await server.start({"port": "COM1", "baudrate": 9600})
    assert server.status.value == "running"
    # 给帧循环时间处理
    for _ in range(50):
        if fake.written:
            break
        await asyncio.sleep(0.02)
    try:
        assert fake.written, "服务端必须经串口回写响应帧"
        resp = bytes(fake.written)
        assert resp[0] == 1 and resp[1] == 3 and resp[2] == 4  # addr fc bytecount
        assert struct.unpack(">H", resp[3:5])[0] == 0x1234    # HR0 值
        assert struct.unpack("<H", resp[-2:])[0] == crc16_modbus(resp[:-2])
    finally:
        await asyncio.wait_for(server.stop(), timeout=5)
        assert server._serial is None  # stop 释放串口
        assert fake.is_open is False


@pytest.mark.asyncio
async def test_serial_mode_broadcast_no_response():
    """广播（addr=0）写请求被执行但不回包。"""
    server = _make_server()
    # FC6 写单寄存器广播：addr=0, HR5=77
    pdu = bytes([0, 6]) + struct.pack(">HH", 5, 77)
    fake = FakeSerial(pdu + struct.pack("<H", crc16_modbus(pdu)))
    with patch.object(server, "_open_serial", side_effect=lambda: setattr(server, "_serial", fake)):
        await server.start({"port": "COM1"})
    for _ in range(50):
        if len(fake._in) == 0 and fake.written == b"":
            await asyncio.sleep(0.02)
            continue
        break
    await asyncio.sleep(0.15)
    try:
        assert fake.written == b"", "广播不得回包"
        assert server._get_data_store(1).holding_regs[5] == 77, "广播写必须生效"
    finally:
        await asyncio.wait_for(server.stop(), timeout=5)


@pytest.mark.asyncio
async def test_serial_mode_crc_error_dropped():
    """CRC 校验失败的帧被丢弃（不同步、不响应、不错误状态）。"""
    server = _make_server()
    bad = bytearray(_read_holding_request())
    bad[-1] ^= 0xFF  # 破坏 CRC
    fake = FakeSerial(bytes(bad))
    with patch.object(server, "_open_serial", side_effect=lambda: setattr(server, "_serial", fake)):
        await server.start({"port": "COM1"})
    await asyncio.sleep(0.3)
    try:
        assert fake.written == b""
        assert server.status.value == "running"
    finally:
        await asyncio.wait_for(server.stop(), timeout=5)


# ---------------------------------------------------------------------------
# 启动行为契约（Issue #36 核心）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_serial_open_failure_raises_clearly():
    """串口打不开 → 状态 ERROR + 抛出含串口名的明确异常（不再静默回退 bridge）。"""
    server = ModbusRtuServer()

    def _boom():
        raise OSError("PermissionError(13, '拒绝访问')")

    with patch.object(server, "_open_serial", side_effect=_boom):
        with pytest.raises(RuntimeError, match="COM99"):
            await server.start({"port": "COM99"})
    assert server.status.value == "error"


@pytest.mark.asyncio
async def test_explicit_bridge_mode_still_works():
    """显式 mode=tcp_bridge：MBAP 帧直连原生帧处理器（既有兼容行为保留）。"""
    server = _make_server()
    port = free_tcp_port()
    await server.start({"mode": "tcp_bridge", "port": "COM1", "tcp_bridge_port": port})
    try:
        assert server.status.value == "running"
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=5)
        # MBAP 里 unit_id 在 header；PDU 以功能码开头（不含 addr）
        pdu = bytes([3]) + struct.pack(">HH", 0, 2)
        mbap = struct.pack(">HHHB", 1, 0, len(pdu) + 1, 1) + pdu
        writer.write(mbap)
        await writer.drain()
        header = await asyncio.wait_for(reader.readexactly(7), timeout=5)
        resp_len = struct.unpack(">H", header[4:6])[0] - 1
        resp = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5)
        # resp = fc(1) + bytecount(1) + data(count*2)
        assert resp[0] == 3 and struct.unpack(">H", resp[2:4])[0] == 0x1234
        writer.close()
    finally:
        await asyncio.wait_for(server.stop(), timeout=5)


@pytest.mark.asyncio
async def test_edgelite_int_port_routes_to_bridge():
    """edgelite 推送发 int port → 显式桥接（既有集成兼容）。"""
    server = _make_server()
    port = free_tcp_port()
    await server.start({"port": port, "tcp_bridge_port": port})
    try:
        assert server.status.value == "running"
        assert server._serial is None, "桥接模式不得占用串口"
    finally:
        await asyncio.wait_for(server.stop(), timeout=5)
