"""DL/T 645-2007 wire-level golden tests.

Golden frames per DL/T 645-2007:
  frame: 68 A0..A5(6B BCD LE) 68 C L DATA CS 16
  request read data: C=0x11, DATA = DI0..DI3 (transmission order), each +0x33
  response: C=0x91, DATA = DI(4) + value BCD, each +0x33
  error: C=0xD1 (0x91|0x40), DATA = error code +0x33
  checksum CS = sum(addr + 68 + C + L + DATA) & 0xFF
"""

import asyncio

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.dlt645.server import DLT645Server
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"
METER_ADDR = "000000000001"
METER_ADDR_BYTES = bytes([0x01, 0x00, 0x00, 0x00, 0x00, 0x00])  # BCD little-endian


def cs(payload: bytes) -> int:
    return sum(payload) & 0xFF


def read_data_frame(di_tx: bytes) -> bytes:
    """Master read-data request for a DI in transmission order (DI0 first)."""
    data = bytes((b + 0x33) & 0xFF for b in di_tx)
    body = METER_ADDR_BYTES + bytes([0x68, 0x11, len(data)]) + data
    return b"\x68" + body + bytes([cs(body)]) + b"\x16"


async def start_server():
    server = DLT645Server()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-645",
        name="DLT645 Golden",
        protocol="dlt645",
        points=[
            PointConfig(name="voltage_a", address="02010100", data_type="float32"),
            PointConfig(name="total_active_energy", address="00010000", data_type="float32"),
        ],
        protocol_config={"meter_address": METER_ADDR},
    ))
    await server.sync_point_value("dev-645", "voltage_a", 220.5)
    await server.sync_point_value("dev-645", "total_active_energy", 1234.56)
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
    # read whatever one response frame is available: header is fixed until L
    head = await asyncio.wait_for(reader.readexactly(10), timeout=5)  # 68 addr(6) 68 C L
    assert head[0] == 0x68 and head[7] == 0x68, f"bad frame head: {head.hex(' ')}"
    data_len = head[9]
    rest = await asyncio.wait_for(reader.readexactly(data_len + 2), timeout=5)
    writer.close()
    return head + rest


@pytest.mark.asyncio
async def test_read_voltage_exact():
    """DI 02010100 (A相电压) 220.5V -> sign(00)+BCD(05 22), C=0x91, all data +0x33."""
    server, port = await start_server()
    try:
        # DI stored big-endian (DI3DI2DI1DI0)=02010100; wire transmission order reversed
        resp = await exchange(port, read_data_frame(bytes([0x00, 0x01, 0x01, 0x02])))
        data = bytes([0x00, 0x01, 0x01, 0x02, 0x00, 0x05, 0x22])  # DI + sign + 2205 BCD LE
        enc = bytes((b + 0x33) & 0xFF for b in data)
        body = METER_ADDR_BYTES + bytes([0x68, 0x91, len(enc)]) + enc
        expected = b"\x68" + body + bytes([cs(body)]) + b"\x16"
        assert resp == expected, f"voltage resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_read_energy_exact():
    """DI 00010000 (组合有功总电能) 1234.56 kWh -> sign(00)+BCD(56 34 12 00)."""
    server, port = await start_server()
    try:
        resp = await exchange(port, read_data_frame(bytes([0x00, 0x00, 0x01, 0x00])))
        data = bytes([0x00, 0x00, 0x01, 0x00, 0x00, 0x56, 0x34, 0x12, 0x00])
        enc = bytes((b + 0x33) & 0xFF for b in data)
        body = METER_ADDR_BYTES + bytes([0x68, 0x91, len(enc)]) + enc
        expected = b"\x68" + body + bytes([cs(body)]) + b"\x16"
        assert resp == expected, f"energy resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_unknown_di_error_response():
    """Unknown DI -> abnormal flag C=0xD1, data = ERR_NO_DATA(0x02)+0x33, L=1."""
    server, port = await start_server()
    try:
        resp = await exchange(port, read_data_frame(bytes([0x00, 0x00, 0x99, 0x00])))
        enc = bytes([0x02 + 0x33])
        body = METER_ADDR_BYTES + bytes([0x68, 0xD1, 1]) + enc
        expected = b"\x68" + body + bytes([cs(body)]) + b"\x16"
        assert resp == expected, f"error resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_read_meter_address_broadcast():
    """C=0x15 broadcast read address: addr field = 99..99, data = the meter's own
    address BCD +0x33 (that is the whole point of the broadcast query)."""
    server, port = await start_server()
    try:
        broadcast = bytes([0x99] * 6)
        body = broadcast + bytes([0x68, 0x15, 0x00])
        request = b"\x68" + body + bytes([cs(body)]) + b"\x16"

        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(request)
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(10), timeout=5)
        data_len = head[9]
        rest = await asyncio.wait_for(reader.readexactly(data_len + 2), timeout=5)
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
        resp = head + rest

        enc = bytes((b + 0x33) & 0xFF for b in METER_ADDR_BYTES)
        resp_body = broadcast + bytes([0x68, 0x95, len(enc)]) + enc
        expected = b"\x68" + resp_body + bytes([cs(resp_body)]) + b"\x16"
        assert resp == expected, f"read addr resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_bad_checksum_gets_silence():
    """Corrupted CS must be silently dropped (no response)."""
    server, port = await start_server()
    reader = writer = None
    try:
        frame = bytearray(read_data_frame(bytes([0x00, 0x01, 0x01, 0x02])))
        frame[-2] ^= 0xFF  # corrupt checksum
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(bytes(frame))
        await writer.drain()
        try:
            await asyncio.wait_for(reader.read(1), timeout=0.6)
            raise AssertionError("server answered a corrupted frame")
        except asyncio.TimeoutError:
            pass
    finally:
        await teardown(server, writer)
