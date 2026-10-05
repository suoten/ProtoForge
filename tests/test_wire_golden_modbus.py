"""Modbus TCP / Modbus RTU(TCP bridge) wire-level golden tests.

Golden frames per Modbus Messaging Implementation Guide (MBAP) and
MODBUS Application Protocol V1.1b3 (PDUs, exception codes). The RTU
server without a serial port falls back to its TCP bridge, which speaks
MBAP framing and shares the PDU processor with the TCP server — so the
PDU-level goldens gate both implementations.
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.modbus.rtu_server import ModbusRtuServer
from protoforge.protocols.modbus.server import ModbusTcpServer
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"


def build_device(device_id: str, protocol: str) -> DeviceConfig:
    return DeviceConfig(
        id=device_id,
        name="Modbus Golden",
        protocol=protocol,
        points=[
            PointConfig(name="power", address="40001", data_type="uint16"),
            PointConfig(name="temp", address="HR10", data_type="float32"),
            PointConfig(name="run", address="C0", data_type="bool"),
        ],
        protocol_config={"slave_id": 1},
    )


def mbap(tx_id: int, unit: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", tx_id, 0, len(pdu) + 1, unit) + pdu


async def start_tcp_server():
    server = ModbusTcpServer()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port})
    await asyncio.sleep(0.1)
    await server.create_device(build_device("dev-tcp", "modbus_tcp"))
    await server.sync_point_value("dev-tcp", "power", 0x1234)
    await server.sync_point_value("dev-tcp", "temp", 23.5)  # HR10..11 = 41 BC 00 00
    await server.sync_point_value("dev-tcp", "run", True)
    return server, port


async def start_rtu_bridge_server():
    server = ModbusRtuServer()
    port = free_tcp_port()
    # serial port does not exist -> TCP bridge mode on `tcp_bridge_port`
    await server.start({
        "port": "/dev/ttyPF_GOLDEN0",
        "baudrate": 9600,
        "tcp_bridge_port": port,
    })
    await asyncio.sleep(0.1)
    await server.create_device(build_device("dev-rtu", "modbus_rtu"))
    await server.sync_point_value("dev-rtu", "power", 0x1234)
    return server, port


# ---------------------------------------------------------------------------
# Modbus TCP golden frames
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tcp_read_holding_registers_exact():
    """FC03: MBAP echo + PDU 03 <byte_count> <regs BE>. Golden: HR0=0x1234."""
    server, port = await start_tcp_server()
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(mbap(0x0100, 1, struct.pack(">BHH", 3, 0, 1)))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(7), timeout=5)
        assert head == b"\x01\x00\x00\x00\x00\x05\x01"
        pdu = await asyncio.wait_for(reader.readexactly(4), timeout=5)
        assert pdu == b"\x03\x02\x12\x34"
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_tcp_read_float32_register_pair():
    """FC03 across a float32 point: big-endian IEEE-754 split into 2 regs."""
    server, port = await start_tcp_server()
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(mbap(0x0200, 1, struct.pack(">BHH", 3, 10, 2)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(6), timeout=5)
        assert pdu == b"\x03\x04\x41\xbc\x00\x00"  # 23.5
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_tcp_write_single_register_echo_and_readback():
    """FC06 must echo the exact request PDU; value readable via FC03."""
    server, port = await start_tcp_server()
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(mbap(0x0300, 1, struct.pack(">BHH", 6, 5, 0xBEEF)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(5), timeout=5)
        assert pdu == b"\x06\x00\x05\xbe\xef"

        writer.write(mbap(0x0301, 1, struct.pack(">BHH", 3, 5, 1)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(4), timeout=5)
        assert pdu == b"\x03\x02\xbe\xef"
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_tcp_coil_write_and_read():
    """FC05 write coil ON (FF 00), FC01 read back packed bit."""
    server, port = await start_tcp_server()
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(mbap(0x0400, 1, struct.pack(">BHH", 5, 0, 0xFF00)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(5), timeout=5)
        assert pdu == b"\x05\x00\x00\xff\x00"

        writer.write(mbap(0x0401, 1, struct.pack(">BHH", 1, 0, 1)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(3), timeout=5)
        assert pdu == b"\x01\x01\x01"
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_tcp_exception_codes():
    """count=0 -> ILLEGAL DATA VALUE (0x03); unsupported FC -> ILLEGAL FUNCTION (0x01)."""
    server, port = await start_tcp_server()
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(mbap(0x0500, 1, struct.pack(">BHH", 3, 0, 0)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        assert pdu == b"\x83\x03"

        writer.write(mbap(0x0501, 1, struct.pack(">BH", 7, 0)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        assert pdu == b"\x87\x01"
        writer.close()
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# Modbus RTU TCP-bridge golden frames
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rtu_bridge_read_holding_registers_exact():
    """RTU bridge (no serial port) speaks MBAP; same golden PDU as TCP."""
    server, port = await start_rtu_bridge_server()
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(mbap(0x0A00, 1, struct.pack(">BHH", 3, 0, 1)))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(7), timeout=5)
        assert head == b"\x0a\x00\x00\x00\x00\x05\x01"
        pdu = await asyncio.wait_for(reader.readexactly(4), timeout=5)
        assert pdu == b"\x03\x02\x12\x34"
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_rtu_bridge_write_and_exception():
    server, port = await start_rtu_bridge_server()
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(mbap(0x0B00, 1, struct.pack(">BHH", 6, 2, 0x0064)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(5), timeout=5)
        assert pdu == b"\x06\x00\x02\x00\x64"

        writer.write(mbap(0x0B01, 1, struct.pack(">BHH", 3, 2, 0)))
        await writer.drain()
        await asyncio.wait_for(reader.readexactly(7), timeout=5)
        pdu = await asyncio.wait_for(reader.readexactly(2), timeout=5)
        assert pdu == b"\x83\x03"
        writer.close()
    finally:
        await server.stop()
