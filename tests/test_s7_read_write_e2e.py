"""S7 Read Var end-to-end: request frame -> response data == behavior values.

Covers int16 / int32 / float32 / bool (issue #30): values are set through
the device behavior API and the raw response bytes must equal the packed
values. Frame helpers mirror tests/test_wire_golden_s7.py.
"""

from __future__ import annotations

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.s7.server import S7Server
from tests.test_wire_golden_s7 import (
    connect_and_cc,
    s7_ack,
    s7_item,
    s7_job,
    server_holder,
    teardown,
)

HOST = "127.0.0.1"
PDU_REF = 0x0001

VALUES = {
    "counter": -2,  # int16 @ MW0
    "pressure": 0x12345678,  # int32 @ DB1.DBD8
    "temperature": 23.5,  # float32 @ DB1.DBD0
    "motor": True,  # bool @ DB1.DBX4.0
}


async def start_server():
    server = S7Server()
    from tests.wire_golden_harness import free_tcp_port

    port = free_tcp_port()
    await server.start({"host": HOST, "port": port, "rack": 0, "slot": 1})
    await asyncio.sleep(0.1)
    await server.create_device(
        DeviceConfig(
            id="dev-s7-rw",
            name="S7 ReadWrite",
            protocol="s7",
            points=[
                PointConfig(name="temperature", address="DB1.DBD0", data_type="float32"),
                PointConfig(name="motor", address="DB1.DBX4.0", data_type="bool"),
                PointConfig(name="counter", address="MW0", data_type="int16"),
                PointConfig(name="pressure", address="DB1.DBD8", data_type="int32"),
            ],
        )
    )
    await server.sync_point_value("dev-s7-rw", "temperature", VALUES["temperature"])
    await server.sync_point_value("dev-s7-rw", "counter", VALUES["counter"])
    await server.sync_point_value("dev-s7-rw", "pressure", VALUES["pressure"])
    await server.sync_point_value("dev-s7-rw", "motor", VALUES["motor"])
    return server, port


async def read_var(reader, writer, item: bytes, expect_len: int) -> bytes:
    req = s7_job(b"\x04", bytes([0x01]) + item)
    writer.write(req)
    await writer.drain()
    return await asyncio.wait_for(reader.readexactly(expect_len), timeout=5)


@pytest.mark.asyncio
async def test_read_int16_matches_behavior():
    """MW0 int16: response bytes == packed behavior value (-2 -> FF FE)."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        resp = await read_var(reader, writer, s7_item(0x04, 2, 0, 0x83, 0), 27)
        item_data = bytes([0xFF, 0x04]) + struct.pack(">H", 16) + struct.pack(">h", VALUES["counter"])
        assert resp == s7_ack(PDU_REF, 2, item_data, b"\x04\x01")
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_read_int32_matches_behavior():
    """DB1.DBD8 int32: response bytes == packed behavior value."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        resp = await read_var(reader, writer, s7_item(0x04, 4, 1, 0x84, 8), 29)
        item_data = bytes([0xFF, 0x04]) + struct.pack(">H", 32) + struct.pack(">i", VALUES["pressure"])
        assert resp == s7_ack(PDU_REF, 2, item_data, b"\x04\x01")
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_read_float32_matches_behavior():
    """DB1.DBD0 float32: response bytes == packed behavior value."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        resp = await read_var(reader, writer, s7_item(0x04, 4, 1, 0x84, 0), 29)
        item_data = bytes([0xFF, 0x04]) + struct.pack(">H", 32) + struct.pack(">f", VALUES["temperature"])
        assert resp == s7_ack(PDU_REF, 2, item_data, b"\x04\x01")
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_read_bool_matches_behavior():
    """DB1.DBX4.0 bool set True: BIT read returns byte with bit 0 set."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        resp = await read_var(reader, writer, s7_item(0x01, 1, 1, 0x84, 4, bit=0), 27)
        item_data = bytes([0xFF, 0x03]) + struct.pack(">H", 1) + b"\x01\x00"
        assert resp == s7_ack(PDU_REF, 2, item_data, b"\x04\x01")
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise
