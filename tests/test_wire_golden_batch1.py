"""Batch 1 of v1.7.0 golden tests: custom_tcp / custom_udp / toledo / opcda / s7plus.

All frames fully deterministic (no timestamps in asserted regions).
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from tests.wire_golden_harness import free_tcp_port, free_udp_port, open_conn

HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# custom_tcp — raw mode (all point values big-endian concat) and template mode
# ---------------------------------------------------------------------------

async def _start_custom_tcp(config_extra: dict | None = None):
    from protoforge.protocols.custom_tcp.server import CustomTcpServer
    server = CustomTcpServer()
    port = free_tcp_port()
    config = {"host": HOST, "port": port}
    if config_extra:
        config.update(config_extra)
    await asyncio.wait_for(server.start(config), timeout=15)
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-ctcp", name="CustomTCP Golden", protocol="custom_tcp",
        points=[
            PointConfig(name="level", address="0", data_type="uint16"),
            PointConfig(name="temp", address="1", data_type="float32"),
        ],
    ))
    await server.write_point("dev-ctcp", "level", 0x1234)
    await server.write_point("dev-ctcp", "temp", 1.5)
    return server, port


async def _teardown_tcp(server, writer=None):
    if writer is not None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    await asyncio.wait_for(server.stop(), timeout=10)


@pytest.mark.asyncio
async def test_custom_tcp_raw_mode_all_points_exact():
    """Raw mode: response = uint16 BE(0x1234) + float32 BE(1.5), nothing else."""
    server, port = await _start_custom_tcp()
    try:
        reader, writer = await open_conn(port)
        writer.write(b"\x01")  # any request byte
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(6), timeout=5)
        expected = struct.pack(">H", 0x1234) + struct.pack(">f", 1.5)
        assert resp == expected, f"got {resp.hex(' ')} exp {expected.hex(' ')}"
        await _teardown_tcp(server, writer)
    except Exception:
        await _teardown_tcp(server)
        raise


@pytest.mark.asyncio
async def test_custom_tcp_template_echo_and_point_exact():
    """Template "AA 55 {echo} {level}": magic + request echo + uint16 BE point."""
    server, port = await _start_custom_tcp({"response_template": "AA 55 {echo} {level}"})
    try:
        reader, writer = await open_conn(port)
        writer.write(b"\xDE\xAD")
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(6), timeout=5)
        expected = b"\xaa\x55" + b"\xde\xad" + struct.pack(">H", 0x1234)
        assert resp == expected, f"got {resp.hex(' ')} exp {expected.hex(' ')}"
        await _teardown_tcp(server, writer)
    except Exception:
        await _teardown_tcp(server)
        raise


# ---------------------------------------------------------------------------
# custom_udp — datagram template with {echo}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_udp_echo_exact():
    from protoforge.protocols.custom_udp.server import CustomUdpServer
    server = CustomUdpServer()
    port = free_udp_port()
    await server.start({"host": HOST, "port": port,
                        "response_template": "{echo}"})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-cudp", name="CustomUDP Golden", protocol="custom_udp",
        points=[PointConfig(name="v", address="0", data_type="uint16")],
    ))
    await server.write_point("dev-cudp", "v", 7)

    loop = asyncio.get_running_loop()
    class Rx(asyncio.DatagramProtocol):
        def __init__(self): self.q = asyncio.Queue()
        def datagram_received(self, data, addr): self.q.put_nowait(data)
    transport, rx = await loop.create_datagram_endpoint(Rx, remote_addr=(HOST, port))
    try:
        transport.sendto(b"\xCA\xFE")
        resp = await asyncio.wait_for(rx.q.get(), timeout=5)
        assert resp == b"\xca\xfe", f"echo mismatch: {resp.hex(' ')}"
    finally:
        transport.close()
        await asyncio.wait_for(server.stop(), timeout=10)


# ---------------------------------------------------------------------------
# toledo — ASCII S command with deterministic weight formatting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_toledo_stable_weight_exact():
    from protoforge.protocols.toledo.server import ToledoServer
    server = ToledoServer()
    port = free_tcp_port()
    await asyncio.wait_for(server.start({"host": HOST, "port": port, "unit": "kg"}), timeout=15)
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-toledo", name="Toledo Golden", protocol="toledo",
        points=[PointConfig(name="weight", address="0", data_type="float32")],
    ))
    await server.write_point("dev-toledo", "weight", 1234.5)

    reader, writer = await open_conn(port)
    try:
        writer.write(b"S")
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(15), timeout=5)
        # format: sign + %08.3f + unit + stable_flag + zero_flag + CRLF
        # pinned: zero_flag = 'Z' after write (weight at zero reference)
        expected = b" 1234.500kg Z\r\n"
        assert resp == expected, f"got {resp!r} exp {expected!r}"
    finally:
        await _teardown_tcp(server, writer)


@pytest.mark.asyncio
async def test_toledo_negative_weight_and_su():
    from protoforge.protocols.toledo.server import ToledoServer
    server = ToledoServer()
    port = free_tcp_port()
    await asyncio.wait_for(server.start({"host": HOST, "port": port, "unit": "kg"}), timeout=15)
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-toledo2", name="Toledo Golden 2", protocol="toledo",
        points=[PointConfig(name="weight", address="0", data_type="float32")],
    ))
    await server.write_point("dev-toledo2", "weight", -2.5)

    reader, writer = await open_conn(port)
    try:
        writer.write(b"SU")
        await writer.drain()
        resp = await asyncio.wait_for(reader.readexactly(15), timeout=5)
        # negative sign '-'; zero_flag 'Z' pinned above
        expected = b"-0002.500kg Z\r\n"
        assert resp == expected, f"got {resp!r} exp {expected!r}"
    finally:
        await _teardown_tcp(server, writer)


# ---------------------------------------------------------------------------
# opcda — PFDA bridge frames: browse / read (value bytes exact, ts masked)
# ---------------------------------------------------------------------------

def _pfda(body: bytes) -> bytes:
    return b"PFDA" + struct.pack("<I", len(body)) + body


async def _start_opcda():
    from protoforge.protocols.opcda.server import OpcDaServer
    server = OpcDaServer()
    port = free_tcp_port()
    await asyncio.wait_for(server.start({"host": HOST, "port": port}), timeout=15)
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-da", name="OpcDa Golden", protocol="opcda",
        points=[
            PointConfig(name="tank_level", address="level", data_type="float32"),
            PointConfig(name="motor", address="run", data_type="bool"),
        ],
    ))
    await server.write_point("dev-da", "tank_level", 23.5)
    return server, port


@pytest.mark.asyncio
async def test_opcda_browse_exact():
    server, port = await _start_opcda()
    try:
        reader, writer = await open_conn(port)
        writer.write(_pfda(struct.pack("<I", 0x01)))  # browse
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(8), timeout=5)
        assert head[:4] == b"PFDA"
        body = await asyncio.wait_for(reader.readexactly(struct.unpack("<I", head[4:8])[0]), timeout=5)
        # status u32 = 0 + count u32 = 2 + [len u16 + tag] * 2 (sorted insertion order)
        expected = (struct.pack("<I", 0) + struct.pack("<I", 2)
                    + struct.pack("<H", 10) + b"tank_level"
                    + struct.pack("<H", 5) + b"motor")
        assert body == expected, f"got {body.hex(' ')} exp {expected.hex(' ')}"
        await _teardown_tcp(server, writer)
    except Exception:
        await _teardown_tcp(server)
        raise


@pytest.mark.asyncio
async def test_opcda_read_float_value_exact_prefix():
    """Read response: status(4) + [type u8 + value] + quality(4) + timestamp(8).
    Pinned to current behavior: get_data_type dispatches to float64 (type 0x06)
    and OPC-DA good quality = 0xC0 (192). Everything except timestamp asserted."""
    server, port = await _start_opcda()
    try:
        reader, writer = await open_conn(port)
        tag = b"tank_level"
        body = struct.pack("<I", 0x02) + struct.pack("<H", len(tag)) + tag
        writer.write(_pfda(body))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(8), timeout=5)
        blen = struct.unpack("<I", head[4:8])[0]
        resp = await asyncio.wait_for(reader.readexactly(blen), timeout=5)
        expected_prefix = (struct.pack("<I", 0)
                           + struct.pack("<Bd", 6, 23.5)   # type 6 = float64
                           + struct.pack("<I", 0xC0))      # OPC-DA quality good
        assert resp[:17] == expected_prefix, f"got {resp.hex(' ')} exp {expected_prefix.hex(' ')}"
        assert len(resp) == 17 + 8  # + timestamp
        await _teardown_tcp(server, writer)
    except Exception:
        await _teardown_tcp(server)
        raise


@pytest.mark.asyncio
async def test_opcda_write_then_readback():
    server, port = await _start_opcda()
    try:
        reader, writer = await open_conn(port)
        # float64 value: _handle_write requires body >= 16 bytes
        # (cmd4+taglen2+tag5+bool2=13 is rejected 0x8002 - pinned limit)
        await server.create_device(DeviceConfig(
            id="dev-da2", name="OpcDa Golden 2", protocol="opcda",
            points=[PointConfig(name="dbl", address="dbl", data_type="float64")],
        ))
        tag = b"dbl"
        body = (struct.pack("<I", 0x03) + struct.pack("<H", len(tag)) + tag
                + struct.pack("<Bd", 6, 21.0))
        writer.write(_pfda(body))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(8), timeout=5)
        blen = struct.unpack("<I", head[4:8])[0]
        resp = await asyncio.wait_for(reader.readexactly(blen), timeout=5)
        assert resp == struct.pack("<I", 0), f"write ack mismatch: {resp.hex(' ')}"

        # read back
        body2 = struct.pack("<I", 0x02) + struct.pack("<H", len(tag)) + tag
        writer.write(_pfda(body2))
        await writer.drain()
        head2 = await asyncio.wait_for(reader.readexactly(8), timeout=5)
        blen2 = struct.unpack("<I", head2[4:8])[0]
        resp2 = await asyncio.wait_for(reader.readexactly(blen2), timeout=5)
        assert resp2[4:13] == struct.pack("<B", 6) + struct.pack("<d", 21.0), f"readback mismatch: {resp2.hex(' ')}"
        await _teardown_tcp(server, writer)
    except Exception:
        await _teardown_tcp(server)
        raise


# ---------------------------------------------------------------------------
# s7plus — TPKT/COTP CR->CC + setup echo + read (all-points concat, exact)
# ---------------------------------------------------------------------------

def _s7p_tpkt(payload: bytes) -> bytes:
    return struct.pack(">BBH", 0x03, 0x00, len(payload) + 4) + payload


async def _start_s7plus():
    from protoforge.protocols.s7plus.server import S7PlusServer
    server = S7PlusServer()
    port = free_tcp_port()
    await asyncio.wait_for(server.start({"host": HOST, "port": port}), timeout=15)
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-s7p", name="S7Plus Golden", protocol="s7plus",
        points=[
            PointConfig(name="speed", address="DB1.DBD0", data_type="uint16"),
            PointConfig(name="temp", address="DB1.DBD2", data_type="float32"),
        ],
    ))
    await server.write_point("dev-s7p", "speed", 0x0102)
    await server.write_point("dev-s7p", "temp", 1.0)
    return server, port


async def _s7p_handshake(port):
    reader, writer = await open_conn(port)
    cr = _s7p_tpkt(bytes([0x0A, 0xE0, 0x00, 0x01, 0x00, 0x01, 0x00, 0xC0, 0x01, 0x07]))
    writer.write(cr)
    await writer.drain()
    head = await asyncio.wait_for(reader.readexactly(4), timeout=5)
    assert head[:2] == b"\x03\x00"
    total = struct.unpack(">H", head[2:4])[0]
    cc = await asyncio.wait_for(reader.readexactly(total - 4), timeout=5)
    assert cc[1] == 0xD0, f"COTP CC type: {cc[1]:#x}"  # connect confirm
    return reader, writer


@pytest.mark.asyncio
async def test_s7plus_cotp_connect_confirm():
    server, port = await _start_s7plus()
    try:
        reader, writer = await _s7p_handshake(port)
        await _teardown_tcp(server, writer)
    except Exception:
        await _teardown_tcp(server)
        raise


@pytest.mark.asyncio
async def test_s7plus_setup_and_read_exact():
    server, port = await _start_s7plus()
    try:
        reader, writer = await _s7p_handshake(port)

        # setup comm: COTP DT + S7Plus [opcode, 0, func=0x07, 0]
        s7_setup = bytes([0x31, 0x00, 0x07, 0x00])
        cotp = bytes([0x02, 0xF0, 0x80]) + s7_setup
        writer.write(_s7p_tpkt(cotp))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(4), timeout=5)
        total = struct.unpack(">H", head[2:4])[0]
        payload = await asyncio.wait_for(reader.readexactly(total - 4), timeout=5)
        # COTP DT(3) + rsp: [rsp_id, 0, 0x07, 0, seq2, param2, data2, err2]
        assert payload[:3] == b"\x02\xf0\x80"
        s7 = payload[3:]
        expected = bytes([0x07, 0x00, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        assert s7 == expected, f"setup rsp mismatch:\n got {s7.hex(' ')}\n exp {expected.hex(' ')}"

        # read: func=0x04 -> response = all points concat: uint16 BE(0x0102) + float32 BE(1.0)
        s7_read = bytes([0x31, 0x00, 0x04, 0x00])
        writer.write(_s7p_tpkt(bytes([0x02, 0xF0, 0x80]) + s7_read))
        await writer.drain()
        head2 = await asyncio.wait_for(reader.readexactly(4), timeout=5)
        total2 = struct.unpack(">H", head2[2:4])[0]
        payload2 = await asyncio.wait_for(reader.readexactly(total2 - 4), timeout=5)
        s72 = payload2[3:]
        # [0x32?, 0, 0x04, 0, seq2, param2=0, data2=6, err2=0] + data
        expected_data = struct.pack(">H", 0x0102) + struct.pack(">f", 1.0)
        expected2 = bytes([0x04, 0x00, 0x04, 0x00, 0x00, 0x00]) \
            + struct.pack(">H", 0) + struct.pack(">H", len(expected_data)) + b"\x00\x00" \
            + expected_data
        assert s72 == expected2, f"read rsp mismatch:\n got {s72.hex(' ')}\n exp {expected2.hex(' ')}"
        await _teardown_tcp(server, writer)
    except Exception:
        await _teardown_tcp(server)
        raise
