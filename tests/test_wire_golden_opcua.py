"""OPC-UA transport-level golden tests (HELF/ACKF handshake).

The OPC-UA stack is asyncua; ProtoForge owns the address space. These
goldens gate the transport layer a real client touches first:
  HEL (reverse hello word 'HELF') -> ACK ('ACKF', 28-byte message)
  non-OPC-UA garbage -> connection closed without a response.
"""

import asyncio
import struct

import pytest

from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"

pytest.importorskip("asyncua", reason="asyncua not installed")


def hello(endpoint_url: str) -> bytes:
    body = (struct.pack("<I", 0)                 # protocol version
            + struct.pack("<I", 65536)           # receive buffer
            + struct.pack("<I", 65536)           # send buffer
            + struct.pack("<I", 16777216)        # max message size
            + struct.pack("<I", 1000)            # max chunk count
            + struct.pack("<I", len(endpoint_url)) + endpoint_url.encode())
    return b"HELF" + struct.pack("<I", 8 + len(body)) + body


async def start_server():
    from protoforge.protocols.opcua.server import OpcUaServer
    server = OpcUaServer()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port})
    await asyncio.sleep(0.3)
    return server, port


async def teardown(server):
    await asyncio.wait_for(server.stop(), timeout=15)


@pytest.mark.asyncio
async def test_hello_ack():
    """HEL must be answered by a well-formed ACK: 'ACKF' + 28-byte message."""
    server, port = await start_server()
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(hello(f"opc.tcp://{HOST}:{port}"))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(8), timeout=5)
        assert head[:4] == b"ACKF", f"expected ACKF, got {head[:4]!r}"
        size = struct.unpack("<I", head[4:8])[0]
        assert size == 28, f"ACK total size must be 28 (8 header + 20 body), got {size}"
        rest = await asyncio.wait_for(reader.readexactly(20), timeout=5)
        version, recv_buf, send_buf, max_msg, max_chunks = struct.unpack("<IIIII", rest)
        assert version == 0, f"protocol version: {version}"
        assert recv_buf > 0 and send_buf > 0 and max_msg > 0
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_garbage_rejected():
    """Non-UA bytes must never produce a protocol response, and the server
    must keep serving valid clients afterwards (asyncua may close the
    connection or stay silent — both are acceptable)."""
    server, port = await start_server()
    writer = None
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        try:
            data = await asyncio.wait_for(reader.read(64), timeout=2)
        except asyncio.TimeoutError:
            data = None  # silence is acceptable
        if data:
            assert not data.startswith((b"ACKF", b"OPNF")), \
                f"server answered garbage with a UA response: {data[:32]!r}"
        writer.close()
        # the service must still answer a well-formed client on a new connection
        reader2, writer2 = await asyncio.open_connection(HOST, port)
        writer2.write(hello(f"opc.tcp://{HOST}:{port}"))
        await writer2.drain()
        head = await asyncio.wait_for(reader2.readexactly(8), timeout=5)
        assert head[:4] == b"ACKF", "valid HEL after garbage must still be answered"
        writer2.close()
        try:
            await asyncio.wait_for(writer2.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    finally:
        await teardown(server)
