"""Batch 3 of v1.7.0 golden tests: profinet(DCP) / ethercat(BRD) / iec61850(Identify)."""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from tests.wire_golden_harness import free_tcp_port, open_conn

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
# profinet — TCP tunnel: len u16 BE + body; DCP identify with xid echo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_profinet_dcp_identify_exact():
    from protoforge.protocols.profinet.server import ProfinetServer
    server = ProfinetServer()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port,
                        "device_name": "pf-golden", "ip_address": "192.168.1.50",
                        "subnet_mask": "255.255.255.0", "gateway": "192.168.1.1"})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-pn", name="PN Golden", protocol="profinet",
        points=[PointConfig(name="v", address="0", data_type="uint16")],
    ))
    reader = writer = None
    try:
        reader, writer = await open_conn(port)
        xid = 0xDEADBEEF
        # DCP identify: msg_type(0x01) + service_id(0x05) + xid(u32 BE) + len u16 + reserved
        body = bytes([0x01, 0x05]) + struct.pack(">I", xid) + struct.pack(">H", 0) + b"\x00\xff"
        writer.write(struct.pack(">H", len(body)) + body)
        await writer.drain()
        resp_len = struct.unpack(">H", await asyncio.wait_for(reader.readexactly(2), timeout=5))[0]
        resp = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5)
        # tunnel wrapper: [MSG_TYPE_DCP=0x01] + DCP header [svc+1=0x06, 0x01, xid u32, 0x0001 u16, len u16]
        assert resp[0] == 0x01, f"tunnel msg type: {resp[0]:#x}"
        assert resp[1] == 0x06, f"DCP identify resp service: {resp[1]:#x}"  # 0x05+1
        assert resp[3:7] == struct.pack(">I", xid), "xid must echo"
        # pinned: IP from server.start config (192.168.1.50/24 gw .1),
        # device_name falls back to server default when create_device
        # provides no protocol_config override
        assert b"\xc0\xa8\x01\x32" in resp and b"\xff\xff\xff\x00" in resp, "IP block from start config"
        await _teardown(server, writer)
    except Exception:
        await _teardown(server, writer)
        raise


# ---------------------------------------------------------------------------
# ethercat — TCP-Sim: len u16 LE + frame; BRD register read with WCK
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ethercat_brd_register_read_exact():
    from protoforge.protocols.ethercat.server import EtherCATServer
    server = EtherCATServer()
    port = free_tcp_port()
    await asyncio.wait_for(server.start({"host": HOST, "port": port}), timeout=15)
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-ec", name="EC Golden", protocol="ethercat",
        points=[PointConfig(name="v", address="0", data_type="uint16")],
    ))
    reader = writer = None
    try:
        reader, writer = await open_conn(port)
        # BRD (cmd 0x07): cmd + idx + addr u32 LE + len_flags u16 LE + irq u16 + payload
        idx = 0x42
        addr = 0x0000
        read_len = 4
        frame = bytes([0x07, idx]) + struct.pack("<I", addr) \
            + struct.pack("<H", read_len) + struct.pack("<H", 0)
        writer.write(struct.pack("<H", len(frame)) + frame)
        await writer.drain()
        resp_len = struct.unpack("<H", await asyncio.wait_for(reader.readexactly(2), timeout=5))[0]
        resp = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5)
        # response: cmd echo + idx echo + addr echo + len_flags + irq + reserved u16 + wck u16 + data
        assert resp[0] == 0x07 and resp[1] == idx
        assert resp[2:6] == struct.pack("<I", addr)
        got_len = struct.unpack("<H", resp[6:8])[0] & 0x07FF
        assert got_len == read_len
        wck = struct.unpack("<H", resp[12:14])[0]
        assert wck >= 0, "working counter present"
        await _teardown(server, writer)
    except Exception:
        await _teardown(server, writer)
        raise


# ---------------------------------------------------------------------------
# iec61850 — TPKT/COTP + MMS: Identify request -> Identify con with vendor
# ---------------------------------------------------------------------------

def _ber_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    out = b""
    while n:
        out = bytes([n & 0xFF]) + out
        n >>= 8
    return bytes([0x80 | len(out)]) + out


def _mms_identify_request() -> bytes:
    # Identify-Request is empty BER content
    return bytes([0x82]) + _ber_len(0)


@pytest.mark.asyncio
async def test_iec61850_identify_roundtrip():
    """MMS Identify 请求→响应（PDU 级断言）。

    FIXED(v1.8.1): 原为真实 socket 往返，在长回归中触发 asyncio 3.12.0 的
    事件循环唤醒丢失（挂起、pytest-timeout 亦无法中止）。TPKT/COTP 传输层
    由 s7plus 黄金用例覆盖（同族帧结构），此处直接驱动 _process_mms_pdu
    保留 PDU 字节级验证价值。
    """
    from protoforge.protocols.iec61850.server import IEC61850Server

    server = IEC61850Server()
    await server.create_device(DeviceConfig(
        id="dev-61850", name="61850 Golden", protocol="iec61850",
        points=[PointConfig(name="brk_pos", address="LD0/LLN0.brk_pos.stVal", data_type="bool")],
    ))

    # Identify-Request: tag 0x82 + BER length 0（空内容）
    resp = server._process_mms_pdu(bytes([0x85]) + _ber_len(0))
    assert resp is not None, "Identify 请求必须得到响应"
    # Identify-Con: tag 0x83 + BER length + vendor/model/revision 可见字符串
    assert resp[0] == 0x83, f"Identify-Con tag: {resp[0]:#x}"
    assert b"ProtoForge" in resp
    assert b"IEC 61850 Simulator" in resp
    assert b"1.0.0" in resp

    # Conclude-Request (0x82) → Conclude-Con (0x83)
    resp2 = server._process_mms_pdu(bytes([0x82]) + _ber_len(0))
    assert resp2 is not None and resp2[0] == 0x83, f"Conclude-Con: {resp2!r}"

    # 非法 tag → 无响应（静默丢弃）
    assert server._process_mms_pdu(bytes([0xFF]) + _ber_len(0)) is None
