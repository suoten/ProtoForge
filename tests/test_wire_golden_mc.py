"""Mitsubishi MC Protocol (SLMP 3E binary) wire-level golden tests.

Golden frames per the SLMP/MELSEC 3E binary reference (pymcprotocol
compatible):
  request:  50 00 | net | pc | destIO(2 LE) | sta | len(2 LE, from offset 9)
            | timer(2) | cmd(2 LE) | subcmd(2 LE) | device | count(2 LE)
  response: D0 00 | net | pc | destIO | sta | len(2 LE) | endcode(2 LE) | data
  device field (Q subcmds): start(3B LE) + code(1B); D=0xA8 Y=0x9D
  word data little-endian; bit points packed 2/byte (even point = high nibble).
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.mc.server import McServer
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"


def slmp_read(cmd: int, subcmd: int, code: int, start: int, count: int) -> bytes:
    dev = start.to_bytes(3, "little") + bytes([code])
    body = bytes([0x00, 0x00]) + struct.pack("<H", cmd) + struct.pack("<H", subcmd) \
        + dev + struct.pack("<H", count)
    return bytes([0x50, 0x00, 0x00, 0x00, 0xFF, 0x03, 0x00]) \
        + struct.pack("<H", len(body)) + body


async def start_server():
    server = McServer()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-mc",
        name="MC Golden",
        protocol="mc",
        points=[
            PointConfig(name="d100", address="D100", data_type="uint16"),
            PointConfig(name="d101", address="D101", data_type="uint16"),
            PointConfig(name="valve", address="Y10", data_type="bool"),
        ],
    ))
    await server.sync_point_value("dev-mc", "d100", 0x1234)
    await server.sync_point_value("dev-mc", "d101", 0x5678)
    await server.sync_point_value("dev-mc", "valve", True)
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
    head = await asyncio.wait_for(reader.readexactly(9), timeout=5)  # D0 00 .. len
    assert head[0] == 0xD0, f"bad response head: {head.hex(' ')}"
    data_len = struct.unpack("<H", head[7:9])[0]
    rest = await asyncio.wait_for(reader.readexactly(data_len), timeout=5)
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=3)
    except (asyncio.TimeoutError, ConnectionError):
        pass
    return head + rest


def expect_header(net: bytes, pc: bytes, dest_io: bytes, sta: bytes, data_len: int) -> bytes:
    return b"\xd0\x00" + net + pc + dest_io + sta + struct.pack("<H", data_len)


@pytest.mark.asyncio
async def test_word_read_d100_exact():
    """D100/D101 word read: endcode 0 + LE registers 34 12 78 56."""
    server, port = await start_server()
    try:
        req = slmp_read(0x0401, 0x0000, 0xA8, 100, 2)
        resp = await exchange(port, req)
        expected = expect_header(b"\x00", b"\x00", b"\xff\x03", b"\x00", 6) \
            + struct.pack("<H", 0) + b"\x34\x12\x78\x56"
        assert resp == expected, f"word read mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_bit_read_y10_exact():
    """Y10..Y11 bit read: valve(Y10, even point) ON -> high nibble of first byte."""
    server, port = await start_server()
    try:
        req = slmp_read(0x0401, 0x0001, 0x9D, 0x10, 2)  # Y10 hex address
        resp = await exchange(port, req)
        expected = expect_header(b"\x00", b"\x00", b"\xff\x03", b"\x00", 3) \
            + struct.pack("<H", 0) + b"\x10"
        assert resp == expected, f"bit read mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_word_write_and_readback():
    """0x1401 word write D100=0xBEEF, read back via 0x0401."""
    server, port = await start_server()
    try:
        body = bytes([0x00, 0x00]) + struct.pack("<H", 0x1401) + struct.pack("<H", 0x0000) \
            + (100).to_bytes(3, "little") + bytes([0xA8]) + struct.pack("<H", 1) \
            + struct.pack("<H", 0xBEEF)
        write_req = bytes([0x50, 0x00, 0x00, 0x00, 0xFF, 0x03, 0x00]) \
            + struct.pack("<H", len(body)) + body
        resp = await exchange(port, write_req)
        expected = expect_header(b"\x00", b"\x00", b"\xff\x03", b"\x00", 2) + struct.pack("<H", 0)
        assert resp == expected, f"write ack mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"

        resp2 = await exchange(port, slmp_read(0x0401, 0x0000, 0xA8, 100, 1))
        expected2 = expect_header(b"\x00", b"\x00", b"\xff\x03", b"\x00", 4) \
            + struct.pack("<H", 0) + struct.pack("<H", 0xBEEF)
        assert resp2 == expected2, f"readback mismatch:\n got {resp2.hex(' ')}\n exp {expected2.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_bad_subheader_error_response():
    """Wrong subheader -> D0 00 error frame with endcode 0xC059."""
    server, port = await start_server()
    try:
        bad = bytes([0x51, 0x00, 0x00, 0x00, 0xFF, 0x03, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00])
        resp = await exchange(port, bad)
        expected = expect_header(b"\x00", b"\x00", b"\xff\x03", b"\x00", 2) + struct.pack("<H", 0xC059)
        # error frame echoes request net/pc/destIO/sta: request had 00 00 FF 03 00
        assert resp[:2] == b"\xd0\x00", resp.hex(" ")
        assert resp[-2:] == struct.pack("<H", 0xC059), f"error endcode mismatch: {resp.hex(' ')}"
    finally:
        await teardown(server)
