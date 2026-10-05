"""CJ/T 188-2004 wire-level golden tests.

Golden frames per CJ/T 188-2004:
  frame: 68 ADDR(7B hex) C L DATA CS 16
  read data: C=0x81, DATA = DI(1B) +0x33
  response: C=0x81 (DIR bit already set), DATA = DI(1) + BCD value, all +0x33
  error: C=0xC1 (0x81|0x40), DATA = 0x01
  read address: C=0x83 -> response C=0x83, DATA = 7-byte address (not +0x33)
"""

import asyncio

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.cjt188.server import CJT188Server
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"
METER_ADDR = "00000000001234"
METER_ADDR_BYTES = bytes.fromhex(METER_ADDR)


def cs(payload: bytes) -> int:
    return sum(payload) & 0xFF


def build_frame(addr: bytes, ctrl: int, data: bytes) -> bytes:
    body = addr + bytes([ctrl, len(data)]) + data
    return b"\x68" + body + bytes([cs(body)]) + b"\x16"


async def start_server():
    server = CJT188Server()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-188",
        name="CJT188 Golden",
        protocol="cjt188",
        points=[
            PointConfig(name="total_volume", address="0x90", data_type="float32"),
            PointConfig(name="temperature", address="0x93", data_type="float32"),
        ],
        protocol_config={"meter_address": METER_ADDR, "meter_type": 0},
    ))
    await server.sync_point_value("dev-188", "total_volume", 1234.567)
    await server.sync_point_value("dev-188", "temperature", -7.5)
    return server, port


async def teardown(server, writer=None):
    if writer is not None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    await asyncio.wait_for(server.stop(), timeout=10)


async def exchange(port, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection(HOST, port)
    writer.write(request)
    await writer.drain()
    head = await asyncio.wait_for(reader.readexactly(10), timeout=5)  # 68 addr(7) C L
    assert head[0] == 0x68, f"bad frame head: {head.hex(' ')}"
    data_len = head[9]
    rest = await asyncio.wait_for(reader.readexactly(data_len + 2), timeout=5)
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=3)
    except (asyncio.TimeoutError, ConnectionError):
        pass
    return head + rest


def read_data_request(di: int) -> bytes:
    return build_frame(METER_ADDR_BYTES, 0x81, bytes([(di + 0x33) & 0xFF]))


@pytest.mark.asyncio
async def test_read_cumulative_volume_exact():
    """DI 0x90 (累积流量), 1234.567 m3 -> BCD LE 67 45 23 01, C=0x81, data +0x33."""
    server, port = await start_server()
    try:
        resp = await exchange(port, read_data_request(0x90))
        data = bytes([0x90, 0x67, 0x45, 0x23, 0x01])
        enc = bytes((b + 0x33) & 0xFF for b in data)
        expected = build_frame(METER_ADDR_BYTES, 0x81, enc)
        assert resp == expected, f"volume resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_read_temperature_exact():
    """DI 0x93 (温度), -7.5 C -> decimals=1, BCD LE of 75 = 75 00, sign kept in BCD magnitude."""
    server, port = await start_server()
    try:
        resp = await exchange(port, read_data_request(0x93))
        data = bytes([0x93]) + bytes([0x75, 0x00])  # 2 bytes, magnitude of scaled -7.5*10
        enc = bytes((b + 0x33) & 0xFF for b in data)
        expected = build_frame(METER_ADDR_BYTES, 0x81, enc)
        assert resp == expected, f"temp resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_unknown_di_error_response():
    """Unknown DI -> C=0xC1, L=1, DATA=0x01."""
    server, port = await start_server()
    try:
        resp = await exchange(port, read_data_request(0x99))
        expected = build_frame(METER_ADDR_BYTES, 0xC1, bytes([0x01]))
        assert resp == expected, f"error resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_read_address():
    """C=0x83 read address -> C=0x83, DATA = 7-byte address (plain, not +0x33)."""
    server, port = await start_server()
    try:
        resp = await exchange(port, build_frame(METER_ADDR_BYTES, 0x83, b""))
        expected = build_frame(METER_ADDR_BYTES, 0x83, METER_ADDR_BYTES)
        assert resp == expected, f"addr resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)
