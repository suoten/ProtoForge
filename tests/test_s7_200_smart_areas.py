"""S7-200 Smart Q 区 / V 区读取回归（Gitee issue IKY3ME）。

用户报告（v1.16.3）：模拟西门子 S7-200 Smart 设备，Q 区和 V 区都读不出数据。

根因：
- V 区：`_parse_s7_address` 不识别 V 前缀，所有 V 点位落入"无法识别→DB1
  offset 0"分支，值全部堆在 offset 0，客户端按真实地址（V=协议层 DB1）
  读到的全是 0。修复：V 区显式映射 DB1（V10.0→DB1.DBX10.0，VW20→DBW20，
  VD100→DBD100）。
- Q 区：地址解析一直正确（0x82）；客户端读值异常来自位号丢弃（M 区/DBX
  位寻址修复，见 test_s7_bit_addressing.py）——v1.16.5 已修。
- 另外 KEPServer 等客户端的订阅缓存在设备保存重启后不自动刷新，重新订阅即可。
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.s7.server import S7DeviceBehavior, S7Server
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"
PDU_REF = 0x0001


def _tpkt(payload: bytes) -> bytes:
    return b"\x03\x00" + struct.pack(">H", len(payload) + 4) + payload


COTP_DT = b"\x02\xf0\x80"


def s7_job(func: bytes, params: bytes, data: bytes = b"") -> bytes:
    header = bytes([0x32, 0x01, 0x00, 0x00]) + struct.pack(">H", PDU_REF)
    header += struct.pack(">H", len(func) + len(params)) + struct.pack(">H", len(data))
    return _tpkt(COTP_DT + header + func + params + data)


def s7_item(transport: int, length: int, db: int, area: int,
            byte_offset: int, bit: int = 0) -> bytes:
    full_addr = (byte_offset << 3) | bit
    return bytes([0x12, 0x0A, 0x10, transport]) + struct.pack(">H", length) \
        + struct.pack(">H", db) + bytes([area]) + bytes(
            [(full_addr >> 16) & 0xFF, (full_addr >> 8) & 0xFF, full_addr & 0xFF])


def _parse_read_items(resp: bytes) -> list[tuple[int, int, bytes]]:
    """响应 = 17 头 + 2 参数(Function+Count) + N 个数据项(RC1+TS1+Len2+Data+Pad)。"""
    assert resp[19] == 0x04, f"function {resp[19]:#x}"
    count = resp[20]
    items = []
    off = 21
    for _ in range(count):
        ret, ts = resp[off], resp[off + 1]
        ln = (resp[off + 2] << 8) | resp[off + 3]
        nbytes = ln // 8 if ts == 0x04 else ln  # BIT 以位数计长
        data = resp[off + 4:off + 4 + nbytes]
        items.append((ret, ts, data))
        off += 4 + nbytes + (nbytes % 2)
    return items


# ---------- V 区地址解析（协议层 V = DB1） ----------

@pytest.mark.parametrize("addr,expected", [
    ("V10.0", (0x84, 1, 10, 0)),
    ("V0.0", (0x84, 1, 0, 0)),
    ("VW20", (0x84, 1, 20, None)),
    ("VD100", (0x84, 1, 100, None)),
    ("VB10", (0x84, 1, 10, None)),
])
def test_parse_v_area(addr, expected):
    area, db, off = S7DeviceBehavior._parse_s7_address(addr, 0)
    bit = S7DeviceBehavior._parse_s7_bit(addr)
    e_area, e_db, e_off, e_bit = expected
    assert (area, db, off, bit) == (e_area, e_db, e_off, e_bit)


# ---------- 端到端：Q 区 / V 区真 socket 读取 ----------

async def _start_qv_server():
    server = S7Server()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port, "rack": 0, "slot": 1})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-s7",
        name="S7-200 Smart",
        protocol="s7",
        points=[
            PointConfig(name="q01", address="Q0.1", data_type="bool"),
            PointConfig(name="v100", address="V10.0", data_type="bool"),
            PointConfig(name="vd100", address="VD100", data_type="float32"),
            PointConfig(name="vw20", address="VW20", data_type="int16"),
        ],
    ))
    await server.sync_point_value("dev-s7", "q01", True)     # Q0.1 = 1
    await server.sync_point_value("dev-s7", "v100", True)    # V10.0 = 1
    await server.sync_point_value("dev-s7", "vd100", 23.5)   # VD100 = 23.5
    await server.sync_point_value("dev-s7", "vw20", -2)      # VW20 = -2
    return server, port


async def _connect_and_setup(port):
    reader, writer = await asyncio.open_connection(HOST, port)
    cr = _tpkt(bytes([0x11, 0xE0, 0x00, 0x00, 0x01, 0x00, 0x00,
                      0xC1, 0x02, 0x01, 0x02, 0xC2, 0x02, 0x01, 0x00,
                      0xC0, 0x01, 0x07]))
    writer.write(cr)
    await writer.drain()
    await asyncio.wait_for(reader.readexactly(22), timeout=5)   # COTP CC
    req = s7_job(b"\xf0\x00", struct.pack(">HHH", 1, 1, 480))   # Setup Comm
    writer.write(req)
    await writer.drain()
    await asyncio.wait_for(reader.readexactly(27), timeout=5)   # Setup Ack
    return reader, writer


async def _read_items(reader, writer, items: list[bytes]) -> list[tuple[int, int, bytes]]:
    req = s7_job(b"\x04", bytes([len(items)]) + b"".join(items))
    writer.write(req)
    await writer.drain()
    n_items = len(items)
    # 每个数据项最小 6 字节，先按 21 + 6*n 读出，再按实际长度补读
    resp = bytearray(await asyncio.wait_for(reader.readexactly(21 + 6 * n_items), timeout=5))
    off = 21
    for _ in range(n_items):
        ts = resp[off + 1]
        ln = (resp[off + 2] << 8) | resp[off + 3]
        nbytes = ln // 8 if ts == 0x04 else ln
        total = off + 4 + nbytes + (nbytes % 2)
        while len(resp) < total:
            resp += await asyncio.wait_for(reader.read(1024), timeout=5)
        off = total
    return _parse_read_items(bytes(resp))


async def _teardown(server, writer=None):
    if writer is not None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    await asyncio.wait_for(server.stop(), timeout=10)


@pytest.mark.asyncio
async def test_s7_200_smart_q_and_v_areas():
    server, port = await _start_qv_server()
    try:
        reader, writer = await _connect_and_setup(port)
        # 单请求混合读：Q0.1(BIT) + V10.0(BIT) —— S7-200 Smart 典型客户端行为
        items = await _read_items(reader, writer, [
            s7_item(0x01, 1, 0, 0x82, 0, bit=1),    # Q0.1
            s7_item(0x01, 1, 1, 0x84, 10, bit=0),   # V10.0 = DB1.DBX10.0
        ])
        assert all(ret == 0xFF for ret, _ts, _d in items), f"return codes: {items}"
        assert items[0][2] == b"\x01", f"Q0.1 should be 1, got {items[0][2].hex()}"
        assert items[1][2] == b"\x01", f"V10.0 should be 1, got {items[1][2].hex()}"

        # V 区字/双字
        items = await _read_items(reader, writer, [
            s7_item(0x04, 2, 1, 0x84, 20),          # VW20 = -2
            s7_item(0x04, 4, 1, 0x84, 100),         # VD100 = 23.5 (float32)
        ])
        assert all(ret == 0xFF for ret, _ts, _d in items)
        assert items[0][2] == struct.pack(">h", -2)
        assert items[1][2] == struct.pack(">f", 23.5)
        await _teardown(server, writer)
    except Exception:
        await _teardown(server)
        raise
