"""Omron FINS (TCP) wire-level golden tests.

Golden frames per the Omron FINS/TCP and FINS command references:
  TCP: "FINS" magic + length(4 BE) + body
  node address send:  body = 00000000 + 00000000 + client_node(4 BE)
                      resp = 00000001 + 00000000 + server_node(4) + client_node(4)
  frame send:         body = 00000002 + 00000000 + FINS frame
  FINS frame: ICF RSV GCT DNA DA1 DA2 SNA SA1 SA2 SID(10B header) + MRC SRC + ...
  response header swaps (DNA<->SNA, DA1<->SA1, DA2<->SA2), SID echoed,
  end code 0000 on success, word data big-endian.
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.fins.server import FinsServer
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"
CLIENT_NODE = 0x0B
SID = 0x07


def fins_tcp(body: bytes) -> bytes:
    return b"FINS" + struct.pack(">I", len(body)) + body


def fins_frame(mrc: int, src: int, rest: bytes) -> bytes:
    header = bytes([0x80, 0x00, 0x02, 0x00, 0x0A, 0x00, 0x00, CLIENT_NODE, 0x00, SID])
    return header + bytes([mrc, src]) + rest


async def start_server():
    server = FinsServer()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-fins",
        name="FinsTest",
        protocol="fins",
        points=[
            PointConfig(name="dm100", address="DM100", data_type="int16"),
            PointConfig(name="dm101", address="DM101", data_type="int16"),
        ],
    ))
    await server.sync_point_value("dev-fins", "dm100", -2)   # FF FE
    await server.sync_point_value("dev-fins", "dm101", 10)   # 00 0A
    return server, port


async def teardown(server, writer=None):
    if writer is not None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    await asyncio.wait_for(server.stop(), timeout=10)


async def handshake(port):
    """TCP connect + node address negotiation; returns (reader, writer)."""
    reader, writer = await asyncio.open_connection(HOST, port)
    body = struct.pack(">I", 0) + struct.pack(">I", 0) + struct.pack(">I", CLIENT_NODE)
    writer.write(fins_tcp(body))
    await writer.drain()
    resp = await asyncio.wait_for(reader.readexactly(4 + 4 + 16), timeout=5)
    expected = b"FINS" + struct.pack(">I", 16) \
        + struct.pack(">I", 0x00000001) + struct.pack(">I", 0) \
        + struct.pack(">I", 1) + struct.pack(">I", CLIENT_NODE)
    assert resp == expected, f"node init mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    return reader, writer


async def exchange(reader, writer, body: bytes) -> bytes:
    writer.write(fins_tcp(body))
    await writer.drain()
    head = await asyncio.wait_for(reader.readexactly(8), timeout=5)
    assert head[:4] == b"FINS", f"bad tcp header: {head.hex(' ')}"
    body_len = struct.unpack(">I", head[4:8])[0]
    return await asyncio.wait_for(reader.readexactly(body_len), timeout=5)


@pytest.mark.asyncio
async def test_node_address_handshake_exact():
    server, port = await start_server()
    try:
        reader, writer = await handshake(port)
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_dm_word_read_exact():
    """MRC 0101 memory area read: DM100..101 -> swapped header + endcode 0 + BE data."""
    server, port = await start_server()
    try:
        reader, writer = await handshake(port)
        frame = fins_frame(0x01, 0x01, bytes([0x82]) + struct.pack(">H", 100)
                           + bytes([0x00]) + struct.pack(">H", 2))
        resp = await exchange(reader, writer, struct.pack(">I", 2) + struct.pack(">I", 0) + frame)
        resp_frame = resp[8:]
        # swapped header: DNA<->SNA(00), DA1(0A)<->SA1(0B), DA2(00)
        expected = bytes([0x80, 0x00, 0x02, 0x00, CLIENT_NODE, 0x00, 0x00, 0x0A, 0x00, SID,
                          0x01, 0x01, 0x00, 0x00, 0xFF, 0xFE, 0x00, 0x0A])
        assert resp_frame == expected, f"dm read mismatch:\n got {resp_frame.hex(' ')}\n exp {expected.hex(' ')}"
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_dm_word_write_and_readback():
    """MRC 0102 memory area write DM100=0x1234 -> endcode 0; point value updated."""
    server, port = await start_server()
    try:
        reader, writer = await handshake(port)
        frame = fins_frame(0x01, 0x02, bytes([0x82]) + struct.pack(">H", 100)
                           + bytes([0x00]) + struct.pack(">H", 1) + b"\x12\x34")
        resp = await exchange(reader, writer, struct.pack(">I", 2) + struct.pack(">I", 0) + frame)
        resp_frame = resp[8:]
        expected = bytes([0x80, 0x00, 0x02, 0x00, CLIENT_NODE, 0x00, 0x00, 0x0A, 0x00, SID,
                          0x01, 0x02, 0x00, 0x00])
        assert resp_frame == expected, f"dm write mismatch:\n got {resp_frame.hex(' ')}\n exp {expected.hex(' ')}"

        vals = {pv.name: pv.value for pv in await server.read_points("dev-fins")}
        assert vals["dm100"] == 0x1234, f"point not updated: {vals}"
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise


@pytest.mark.asyncio
async def test_controller_read():
    """MRC 0501 controller read -> endcode 0 + 26 bytes (model/version/name/status)."""
    server, port = await start_server()
    try:
        reader, writer = await handshake(port)
        frame = fins_frame(0x05, 0x01, b"")
        resp = await exchange(reader, writer, struct.pack(">I", 2) + struct.pack(">I", 0) + frame)
        resp_frame = resp[8:]
        assert resp_frame[:12] == bytes([0x80, 0x00, 0x02, 0x00, CLIENT_NODE, 0x00, 0x00, 0x0A, 0x00, SID,
                                         0x05, 0x01])
        assert resp_frame[12:14] == b"\x00\x00", f"endcode not success: {resp_frame.hex(' ')}"
        assert len(resp_frame[14:]) == 26, f"controller data length: {len(resp_frame[14:])}"
        assert resp_frame[14:18] == bytes([0x01, 0x01, 0x01, 0x00])  # model/version/sysver
        assert resp_frame[18:26] == b"FinsTest"                    # device name
        await teardown(server, writer)
    except Exception:
        await teardown(server)
        raise
