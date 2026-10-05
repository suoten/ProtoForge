"""Siemens S7 (ISO-on-TCP / COTP / S7comm) wire-level golden tests.

Golden frames per the S7 Communication reference (snap7-compatible):
  TPKT: 03 00 <len:2 BE>
  COTP CR -> CC with TSAP parameter echo (0xC1 called / 0xC2 calling)
  S7 Setup Communication (0xF0): AMQ echo + PDU size negotiation
  S7 Read Var (0x04): item results with return code 0xFF, transport
    size and BIT length echo, big-endian (Motorola) byte order.

Header layout used by request framing:
  TPKT(4) + COTP DT(3) + S7 header(10: 32, msg, resv2, pduref2,
  paramlen2, datalen2) -> parameters at offset 17.
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.s7.server import S7Server
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"

PDU_REF = 0x0001


def _tpkt(payload: bytes) -> bytes:
    return b"\x03\x00" + struct.pack(">H", len(payload) + 4) + payload


COTP_DT = b"\x02\xf0\x80"


def s7_job(func: bytes, params: bytes, data: bytes = b"") -> bytes:
    """Build an S7 Job request: TPKT + COTP DT + S7 header + params [+ data].

    ``func`` is the leading function-code byte(s); the header ParamLen field
    counts func + params (the full parameter section).
    """
    header = bytes([0x32, 0x01, 0x00, 0x00]) + struct.pack(">H", PDU_REF)
    header += struct.pack(">H", len(func) + len(params)) + struct.pack(">H", len(data))
    return _tpkt(COTP_DT + header + func + params + data)


def s7_item(transport: int, length: int, db: int, area: int, byte_offset: int, bit: int = 0) -> bytes:
    """12-byte S7 any-pointer item: spec 12 0A 10 <ts> <len:2> <db:2> <area> <addr:3>."""
    full_addr = (byte_offset << 3) | bit
    return bytes([0x12, 0x0A, 0x10, transport]) + struct.pack(">H", length) \
        + struct.pack(">H", db) + bytes([area]) + bytes(
            [(full_addr >> 16) & 0xFF, (full_addr >> 8) & 0xFF, full_addr & 0xFF])


def s7_ack(pdu_ref: int, param_len: int, data: bytes, params: bytes = b"") -> bytes:
    """Build expected S7 Ack_Data frame bytes."""
    header = bytes([0x32, 0x03, 0x00, 0x00]) + struct.pack(">H", pdu_ref)
    header += struct.pack(">H", param_len) + struct.pack(">H", len(data))
    header += b"\x00\x00"  # error class / error code
    return _tpkt(COTP_DT + header + params + data)


async def start_server():
    server = S7Server()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port, "rack": 0, "slot": 1})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-s7",
        name="S7 Golden",
        protocol="s7",
        points=[
            PointConfig(name="temperature", address="DB1.DBD0", data_type="float32"),
            PointConfig(name="motor", address="DB1.DBX4.0", data_type="bool"),
            PointConfig(name="counter", address="MW0", data_type="int16"),
        ],
    ))
    await server.sync_point_value("dev-s7", "temperature", 23.5)
    await server.sync_point_value("dev-s7", "counter", -2)
    return server, port


async def connect_and_cc():
    """Open a connection and complete COTP CR -> CC; returns (reader, writer)."""
    server, port = server_holder["server"], server_holder["port"]
    reader, writer = await asyncio.open_connection(HOST, port)
    # snap7-style CR: called TSAP 01 02 (rack 0 slot 1), calling TSAP 01 00
    cr = _tpkt(bytes([0x11, 0xE0, 0x00, 0x00, 0x01, 0x00, 0x00,
                      0xC1, 0x02, 0x01, 0x02, 0xC2, 0x02, 0x01, 0x00,
                      0xC0, 0x01, 0x07]))
    writer.write(cr)
    await writer.drain()
    cc = await asyncio.wait_for(reader.readexactly(22), timeout=5)
    assert cc == bytes([
        0x03, 0x00, 0x00, 0x16,  # TPKT: 22 bytes
        0x11,                    # COTP LI
        0xD0,                    # CC
        0x00, 0x01,              # dst ref
        0x00, 0x01,              # src ref
        0x00,                    # class 0
        0xC1, 0x02, 0x01, 0x02,  # called TSAP echoed
        0xC2, 0x02, 0x01, 0x00,  # calling TSAP echoed
        0xC0, 0x01, 0x07,        # TPDU size 2048
    ]), f"COTP CC mismatch: {cc.hex(' ')}"
    return reader, writer


async def teardown(server, writer=None):
    """Close the client connection FIRST (server.wait_closed waits for it on
    py3.12), then stop the server under a guard so a stuck handler fails the
    test instead of hanging the suite."""
    if writer is not None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    await asyncio.wait_for(server.stop(), timeout=10)


server_holder: dict = {}


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cotp_cr_cc_exact():
    """CR must be confirmed with TSAP echo; a 2-byte-shift anywhere breaks this golden."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_setup_communication_negotiation():
    """0xF0 Setup Comm: echo PDU ref, AMQ caller/callee, clamp PDU into [128, 960]."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        req = s7_job(b"\xf0\x00", struct.pack(">HHH", 1, 1, 1200))
        writer.write(req)
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(27), timeout=5)
        expected = s7_ack(PDU_REF, 8, b"", bytes([
            0xF0, 0x00,
            0x00, 0x01,  # AMQ caller (echo)
            0x00, 0x01,  # AMQ callee (echo)
            0x04, 0xB0,  # PDU 1200 (within [128, 960]? no: 1200 > 960)
        ]))
        # PDU 1200 is clamped to 960 (0x03C0)
        expected = expected[:-2] + b"\x03\xc0"
        assert resp == expected, f"setup resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_read_var_db_float32_exact():
    """Read Var DB1.DBD0 (4 bytes, transport WORD): return 0xFF, data = BE float bytes."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        req = s7_job(b"\x04", bytes([0x01]) + s7_item(0x04, 4, 1, 0x84, 0))
        writer.write(req)
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(29), timeout=5)
        item_data = bytes([0xFF, 0x04]) + struct.pack(">H", 32) + struct.pack(">f", 23.5)
        expected = s7_ack(PDU_REF, 2, item_data, b"\x04\x01")
        assert resp == expected, f"read resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_read_var_markers_int16():
    """M-area (0x83) read of MW0: big-endian int16 (-2 -> FF FE)."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        req = s7_job(b"\x04", bytes([0x01]) + s7_item(0x04, 2, 0, 0x83, 0))
        writer.write(req)
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(27), timeout=5)
        item_data = bytes([0xFF, 0x04]) + struct.pack(">H", 16) + b"\xff\xfe"
        expected = s7_ack(PDU_REF, 2, item_data, b"\x04\x01")
        assert resp == expected, f"read resp mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_write_var_bit_readback():
    """Write Var BIT transport (0x01->resp 0x03): set DB1.DBX4.0, read back via Read Var."""
    server, port = await start_server()
    server_holder.update(server=server, port=port)
    try:
        reader, writer = await connect_and_cc()
        params = bytes([0x01]) + s7_item(0x01, 1, 1, 0x84, 4, bit=0)
        write_data = bytes([0x00, 0x03]) + struct.pack(">H", 1) + b"\x01" + b"\x00"  # rc resv, ts BIT, 1 bit, data, pad
        req = s7_job(b"\x05", params, write_data)
        writer.write(req)
        await writer.drain()
        # ack: TPKT(4) + COTP(3) + header(12) + params(05 01) + data(1 return code) = 22
        resp = await asyncio.wait_for(reader.readexactly(22), timeout=5)
        expected = s7_ack(PDU_REF, 2, b"\xff", b"\x05\x01")
        assert resp == expected, f"write ack mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"

        # read back the byte at DB1 offset 4 -> bit 0 set
        req2 = s7_job(b"\x04", bytes([0x01]) + s7_item(0x04, 1, 1, 0x84, 4))
        writer.write(req2)
        await writer.drain()
        resp2 = await asyncio.wait_for(reader.readexactly(27), timeout=5)
        item_data2 = bytes([0xFF, 0x04]) + struct.pack(">H", 8) + b"\x01\x00"  # odd byte + pad
        expected2 = s7_ack(PDU_REF, 2, item_data2, b"\x04\x01")
        assert resp2 == expected2, f"readback mismatch:\n got {resp2.hex(' ')}\n exp {expected2.hex(' ')}"
        await teardown(server, writer)
    except Exception:
        await teardown(server, writer)
        raise
