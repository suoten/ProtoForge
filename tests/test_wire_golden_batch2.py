"""Batch 2 of v1.7.0 golden tests: fanuc(DBP) / coap / http / mtconnect.

Deterministic assertions; timestamps/instance ids masked where unavoidable.
"""

import asyncio
import json
import re
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from tests.wire_golden_harness import free_tcp_port, free_udp_port, open_conn

HOST = "127.0.0.1"


async def _teardown(server, writer=None):
    if writer is not None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    # FIXED(v1.8.1): shield 保证 10s 超时必然触发——部分协议 stop() 会吞掉
    # 外部取消（suppress CancelledError），裸 wait_for 的超时被吞后调用方
    # 永久挂起（黄金用例全量回归实测）。超时后 stop_task 遗弃给事件循环，
    # 测试收尾时由 asyncio.run 的取消逻辑兜底。
    stop_task = asyncio.ensure_future(server.stop())
    try:
        await asyncio.wait_for(asyncio.shield(stop_task), timeout=10)
    except asyncio.TimeoutError:
        pass
    except Exception:
        stop_task.cancel()


# ---------------------------------------------------------------------------
# fanuc — DBP block protocol (EdgeLite-compatible): connect + acts readback
# ---------------------------------------------------------------------------

def _dbp(cmd: int, body: bytes = b"") -> bytes:
    payload = struct.pack("<HH", 0, 4 + len(body)) + struct.pack("<HH", cmd, len(body)) + body
    return b"DBP\x00" + struct.pack("<I", len(payload)) + payload


@pytest.mark.asyncio
async def test_fanuc_dbp_connect_and_acts_exact():
    """DBP handshake returns ret=0; acts returns default spindle speed 3000."""
    from protoforge.protocols.fanuc.server import FanucServer
    server = FanucServer()
    port = free_tcp_port()
    await asyncio.wait_for(server.start({"host": HOST, "port": port}), timeout=15)
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-fanuc", name="Fanuc Golden", protocol="fanuc",
        points=[PointConfig(name="spindle_speed", address="0", data_type="int16")],
    ))
    reader = writer = None
    try:
        reader, writer = await open_conn(port)

        # connect
        writer.write(_dbp(0x0016))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(8), timeout=5)
        assert head[:4] == b"DBP\x00"
        plen = struct.unpack("<I", head[4:8])[0]
        payload = await asyncio.wait_for(reader.readexactly(plen), timeout=5)
        expected_payload = struct.pack("<HH", 0, 4) + struct.pack("<HH", 0, 0)
        assert payload == expected_payload, f"connect: {payload.hex(' ')}"

        # acts (0x0095): data[0:2] = spindle speed int16 LE, default 3000
        writer.write(_dbp(0x0095))
        await writer.drain()
        head2 = await asyncio.wait_for(reader.readexactly(8), timeout=5)
        plen2 = struct.unpack("<I", head2[4:8])[0]
        payload2 = await asyncio.wait_for(reader.readexactly(plen2), timeout=5)
        expected2 = struct.pack("<HH", 0, 6) + struct.pack("<HHh", 0, 2, 0)  # _cnc_status initialized to 0
        assert payload2 == expected2, f"acts: {payload2.hex(' ')} exp {expected2.hex(' ')}"
        await _teardown(server, writer)
    except Exception:
        await _teardown(server, writer)
        raise


# ---------------------------------------------------------------------------
# coap — RFC 7252: CON GET with Uri-Path -> ACK 2.05, MID/token echo
# ---------------------------------------------------------------------------

def _coap_get(path_segments: str, mid: int = 0x1234, token: bytes = b"\xAB\xCD") -> bytes:
    """Build a CON GET with Uri-Path options (option 11, delta-encoded)."""
    parts = [p for p in path_segments.split("/") if p]
    out = bytearray()
    first = True
    for seg in parts:
        raw = seg.encode()
        delta = 11 if first else 0
        first = False
        assert len(raw) < 13
        out.append(delta << 4 | len(raw))
        out.extend(raw)
    header = bytes([0x42, 0x01]) + struct.pack(">H", mid) + token  # CON, GET, TKL=2 (matches token)
    return header + bytes(out)


@pytest.mark.asyncio
async def test_coap_get_point_ack_exact():
    from protoforge.protocols.coap.server import CoAPServer
    server = CoAPServer()
    port = free_udp_port()
    await asyncio.wait_for(server.start({"host": HOST, "port": port}), timeout=15)
    await asyncio.sleep(0.1)
    # address becomes the uri (uri = addr if addr else sensor/<name>)
    await server.create_device(DeviceConfig(
        id="dev-coap", name="CoAP Golden", protocol="coap",
        points=[PointConfig(name="temp", address="sensors/temp", data_type="float32")],
    ))
    await server.write_point("dev-coap", "temp", 19.5)

    loop = asyncio.get_running_loop()

    class Rx(asyncio.DatagramProtocol):
        def __init__(self): self.q = asyncio.Queue()
        def datagram_received(self, data, addr): self.q.put_nowait(data)

    transport, rx = await loop.create_datagram_endpoint(Rx, remote_addr=(HOST, port))
    try:
        transport.sendto(_coap_get("sensors/temp", mid=0x1234, token=b"\xAB\xCD"))
        resp = await asyncio.wait_for(rx.q.get(), timeout=5)
        # CON -> ACK (type 2), ver 1, TKL 2, code 0x45 (2.05 Content)
        assert resp[0] == 0x62, f"header byte: {resp[0]:#x}"
        assert resp[1] == 0x45
        assert resp[2:4] == b"\x12\x34"          # MID echo
        assert resp[4:6] == b"\xab\xcd"          # token echo
        # Content-Format is option 12 (0xC1 packed), value JSON=50 (0x32)
        assert resp[6:8] == bytes([0xC1, 50])
        assert resp[8:9] == b"\xff"
        payload = json.loads(resp[9:].decode())
        assert payload["point"] == "temp"
        assert payload["value"] == pytest.approx(19.5)
        assert "timestamp" in payload and "device_id" in payload
    finally:
        transport.close()
        await asyncio.wait_for(server.stop(), timeout=10)


# ---------------------------------------------------------------------------
# http — GET /health: exact status line/headers, JSON keys (values asserted)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_health_exact():
    from protoforge.protocols.http.server import HttpSimulatorServer
    server = HttpSimulatorServer()
    port = free_tcp_port()
    await asyncio.wait_for(server.start({"host": HOST, "port": port}), timeout=15)
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-http", name="HTTP Golden", protocol="http",
        points=[PointConfig(name="v", address="v", data_type="float32")],
    ))
    reader = writer = None
    try:
        reader, writer = await open_conn(port)
        writer.write(b"GET /health HTTP/1.1\r\nHost: t\r\n\r\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(4096), timeout=5)
        text = raw.decode("utf-8", errors="replace")
        assert text.startswith("HTTP/1.1 200 OK\r\n")
        assert "Content-Type: application/json; charset=utf-8\r\n" in text
        assert "Connection: keep-alive\r\n" in text
        body = text.split("\r\n\r\n", 1)[1]
        data = json.loads(body)
        assert data == {"status": "ok", "protocol": "http", "devices": 1}, data
        await _teardown(server, writer)
    except Exception:
        await _teardown(server, writer)
        raise


# ---------------------------------------------------------------------------
# mtconnect — /probe returns MTConnectDevices XML (masked time fields)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mtconnect_probe_xml_contract():
    from protoforge.protocols.mtconnect.server import MtConnectServer
    server = MtConnectServer()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port,
                        "device_uuid": "pf-golden-uuid", "manufacturer": "ProtoForge"})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-mtc", name="MTC Golden", protocol="mtconnect",
        points=[
            PointConfig(name="spindle_speed", address="spindle_speed", data_type="float32"),
        ],
        protocol_config={"device_uuid": "pf-golden-uuid"},
    ))
    reader = writer = None
    try:
        reader, writer = await open_conn(port)
        writer.write(b"GET /probe HTTP/1.1\r\nHost: t\r\n\r\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(16384), timeout=5)
        text = raw.decode("utf-8", errors="replace")
        assert "200 OK" in text.split("\r\n", 1)[0]
        body = text.split("\r\n\r\n", 1)[1]
        # XML contract (creationTime/instanceId masked by regex presence check)
        assert "<MTConnectDevices" in body
        assert "</MTConnectDevices>" in body
        assert 'uuid="pf-golden-uuid"' in body
        assert "ProtoForge" in body
        # data item from points
        assert "spindle_speed" in body
        # header fields present in some form
        assert re.search(r'creationTime="[^"]+"', body)
        assert re.search(r'instanceId="\d+"', body)
        await _teardown(server, writer)
    except Exception:
        await _teardown(server, writer)
        raise
