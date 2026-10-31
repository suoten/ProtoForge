"""S7 主站（v1.9.0）— 原生 TPKT/COTP/S7 客户端，拨出轮询真实 PLC。

连接建立序列（与 snap7 一致，与 ProtoForge 自身 S7 从站回环互通）：

  1. TCP 连接
  2. COTP CR（TSAP: 本地 0x0100 / 远端 0x01{rack<<5|slot}，默认 rack0 slot0）
  3. S7 Setup Communication（F0，协商 AMQ 与 PDU 尺寸）
  4. Read Var（0x04）/ Write Var（0x05）轮询

地址格式复用从站实现的 ``S7DeviceBehavior._parse_s7_address``：
DB1.DBD0 / DB1.DBX0.0 / M0.0 / MW2 / IW4 / Q0.0 …
数据编码为大端序（S7 网络字节序）。
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from protoforge.models.device import PointConfig
from protoforge.protocols.master.base import MasterBase
from protoforge.protocols.s7.server import S7DeviceBehavior

# 传输尺寸常量（请求 item 的 transport size 字段）
_TS_BIT = 0x01
_TS_WORD = 0x04

_DATA_TYPE_SIZE = {
    "bool": 1, "int16": 2, "uint16": 2, "int32": 4, "uint32": 4,
    "float32": 4, "float64": 8, "string": 32,
}


logger = logging.getLogger(__name__)

class _S7Conn:
    """S7 主站连接：流读写 + PDU 引用计数 + 协商结果。"""

    __slots__ = ("reader", "writer", "pdu_ref", "pdu_size", "timeout")

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, timeout: float):
        self.reader = reader
        self.writer = writer
        self.pdu_ref = 0
        self.pdu_size = 0x03C0
        self.timeout = timeout

    async def recv_tpkt(self) -> bytes:
        head = await asyncio.wait_for(self.reader.readexactly(4), timeout=self.timeout)
        if head[0] != 0x03:
            raise IOError(f"S7 TPKT 头错误: {head.hex(' ')}")
        total = struct.unpack(">H", head[2:4])[0]
        rest = await asyncio.wait_for(
            self.reader.readexactly(total - 4), timeout=self.timeout)
        return head + rest


class S7MasterServer(MasterBase):
    """S7 主站：原生帧客户端，按扫描周期 Read Var 轮询。"""

    protocol_name = "s7_master"
    protocol_display_name = "S7 Master (Client)"
    protocol_description = "主动连接真实 S7-300/400/1200/1500 PLC，轮询 DB/M/I/Q 区域并支持写入"
    protocol_version = "1.0.0"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "192.168.1.100",
                         "description": "PLC IP 地址"},
                "port": {"type": "integer", "default": 102,
                         "description": "ISO-on-TCP 端口"},
                "rack": {"type": "integer", "default": 0,
                         "description": "机架号（0-7）"},
                "slot": {"type": "integer", "default": 0,
                         "description": "槽号（S7-1200/1500 通常 0 或 1）"},
            },
        }

    # -- 连接 ------------------------------------------------------------

    async def _connect(self, cfg: dict[str, Any]) -> Any:
        host = cfg.get("host")
        if not host:
            raise ValueError("s7_master 需要 protocol_config.host")
        port = int(cfg.get("port", 102))
        timeout = self._timeout_of(cfg)
        rack = int(cfg.get("rack", 0))
        slot = int(cfg.get("slot", 0))
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(str(host), port), timeout=timeout)
        conn = _S7Conn(reader, writer, timeout)
        try:
            await self._cotp_cr(conn, rack, slot)
            await self._setup_comm(conn)
        except Exception:
            writer.close()
            raise
        return conn

    async def _close_conn(self, conn: Any) -> None:
        try:
            conn.writer.close()
            await asyncio.wait_for(conn.writer.wait_closed(), timeout=2)
        except Exception as e:
            logger.debug("%s close conn error: %s", tag, e)

    async def _cotp_cr(self, conn: _S7Conn, rack: int, slot: int) -> None:
        # snap7 风格 CR（与 wire golden 用例一致）：
        #   C1 called TSAP   = 01 {rack<<5|slot}   （服务端侧）
        #   C2 calling TSAP  = 01 00               （客户端侧）
        #   C0 TPDU size     = 07（2048 字节）
        called_tsap = bytes([0x01, (rack & 0x07) << 5 | (slot & 0x1F)])
        body = bytes([0x11, 0xE0,                       # LI=17, CR
                      0x00, 0x00,                       # DST-REF
                      0x00, 0x01,                       # SRC-REF
                      0x00,                             # Class
                      0xC1, 0x02]) + called_tsap \
            + bytes([0xC2, 0x02, 0x01, 0x00,            # calling TSAP 0x0100
                     0xC0, 0x01, 0x07])                 # TPDU size 2048
        cr = bytes([0x03, 0x00]) + struct.pack(">H", 4 + len(body)) + body
        conn.writer.write(cr)
        await conn.writer.drain()
        cc = await conn.recv_tpkt()
        if len(cc) < 6 or cc[5] != 0xD0:
            raise IOError(f"S7 COTP CC 异常: {cc[:8].hex(' ')}")

    async def _setup_comm(self, conn: _S7Conn) -> None:
        conn.pdu_ref = (conn.pdu_ref + 1) & 0xFFFF
        pdu_ref = conn.pdu_ref
        pdu_size = 0x03C0
        # S7 Job 头 10 字节: 32 01 resv2 ref2 paramlen2 datalen2
        head = struct.pack(">BBHHHH", 0x32, 0x01, 0x0000, pdu_ref, 0x0008, 0x0000)
        param = bytes([0xF0, 0x00, 0x00, 0x01, 0x00, 0x01,
                       (pdu_size >> 8) & 0xFF, pdu_size & 0xFF])
        frame = bytes([0x03, 0x00]) + struct.pack(">H", 7 + len(head) + len(param)) \
            + bytes([0x02, 0xF0, 0x80]) + head + param
        conn.writer.write(frame)
        await conn.writer.drain()
        resp = await conn.recv_tpkt()
        if len(resp) < 21 or resp[7] != 0x32:
            raise IOError(f"S7 Setup 响应异常: {resp[:12].hex(' ')}")
        # Ack 头 12 字节: 32 03 resv2 ref2 paramlen2 datalen2 errclass errcode
        if resp[17] != 0x00 or resp[18] != 0x00:
            raise IOError(f"S7 Setup 拒绝: err={resp[17]:#x}/{resp[18]:#x}")
        if resp[19] != 0xF0:
            raise IOError(f"S7 Setup 响应功能码异常: {resp[19]:#x}")
        conn.pdu_size = struct.unpack(">H", resp[25:27])[0] or pdu_size

    # -- 轮询 ------------------------------------------------------------

    async def _poll_once(self, conn: Any, device_id: str,
                         cfg: dict[str, Any], points: list) -> dict[str, Any]:
        values: dict[str, Any] = {}
        # 单 item 请求逐点读（协议转换场景点位数有限，PDU 内多 item
        # 组包留给后续版本；单 item 对真实 PLC 兼容性最好）
        for pt in points:
            try:
                values[pt.name] = await self._read_one(conn, pt)
            except (ValueError, KeyError):
                continue  # 地址不合法的点位跳过
        return values

    async def _read_one(self, conn: _S7Conn, pt: PointConfig) -> Any:
        area, db_number, offset = S7DeviceBehavior._parse_s7_address(str(pt.address), 0)
        dt = pt.data_type.value
        size = _DATA_TYPE_SIZE.get(dt, 2)
        is_bit = dt == "bool" and "." in str(pt.address)
        ts = _TS_BIT if is_bit else _TS_WORD
        length = 1 if is_bit else size
        addr3 = (offset * 8 + int(str(pt.address).rsplit(".", 1)[1])) if is_bit else offset * 8
        item = bytes([0x12, 0x0A, 0x10, ts]) + struct.pack(">H", length) \
            + struct.pack(">H", db_number) + bytes([area]) \
            + bytes([(addr3 >> 16) & 0xFF, (addr3 >> 8) & 0xFF, addr3 & 0xFF])

        conn.pdu_ref = (conn.pdu_ref + 1) & 0xFFFF
        head = struct.pack(">BBHHHH", 0x32, 0x01, 0x0000, conn.pdu_ref, 0x0002, 0x0000)
        param = bytes([0x04, 0x01]) + item
        frame = bytes([0x03, 0x00]) + struct.pack(">H", 7 + len(head) + len(param)) \
            + bytes([0x02, 0xF0, 0x80]) + head + param
        conn.writer.write(frame)
        await conn.writer.drain()

        resp = await conn.recv_tpkt()
        return self._parse_read_response(resp, dt, size)

    def _parse_read_response(self, resp: bytes, dt: str, size: int) -> Any:
        # Ack_Data: TPKT(4) + COTP(3) + S7 header(12: 含 errclass/errcode)
        #           + param(2: func+itemcount) + data
        if len(resp) < 25 or resp[7] != 0x32 or resp[8] != 0x03:
            raise IOError(f"S7 读响应异常: {resp[:12].hex(' ') if resp else 'empty'}")
        err_class = resp[17]
        if err_class != 0:
            raise IOError(f"S7 读错误 class={err_class}")
        data_start = 4 + 3 + 12 + 2  # TPKT + COTP + S7 header + param(func+itemcount)
        if data_start >= len(resp):
            raise IOError("S7 读响应缺数据段")
        return_code = resp[data_start]
        if return_code != 0xFF:
            raise IOError(f"S7 item 读失败 return_code={return_code:#x}")
        raw = resp[data_start + 4:]
        if dt == "bool":
            return bool(raw[0] & 1)
        data = raw[:size]
        data = data + b"\x00" * (size - len(data))
        if dt == "int16":
            return struct.unpack(">h", data)[0]
        if dt == "uint16":
            return struct.unpack(">H", data)[0]
        if dt == "int32":
            return struct.unpack(">i", data)[0]
        if dt == "uint32":
            return struct.unpack(">I", data)[0]
        if dt == "float32":
            return struct.unpack(">f", data)[0]
        if dt == "float64":
            return struct.unpack(">d", data)[0]
        if dt == "string":
            return data.split(b"\x00")[0].decode("utf-8", errors="replace")
        return data[0]

    # -- 写远端 ----------------------------------------------------------

    async def _write_remote(self, conn: Any, device_id: str, cfg: dict[str, Any],
                            point_name: str, value: Any) -> bool:
        device_cfg = self._device_configs.get(device_id)
        if device_cfg is None:
            return False
        pt = next((p for p in device_cfg.points if p.name == point_name), None)
        if pt is None:
            return False
        await self._write_one(conn, pt, value)
        return True

    async def _write_one(self, conn: _S7Conn, pt: PointConfig, value: Any) -> None:
        area, db_number, offset = S7DeviceBehavior._parse_s7_address(str(pt.address), 0)
        dt = pt.data_type.value
        is_bit = dt == "bool" and "." in str(pt.address)
        addr3 = (offset * 8 + int(str(pt.address).rsplit(".", 1)[1])) if is_bit else offset * 8
        ts = _TS_BIT if is_bit else _TS_WORD

        if is_bit:
            raw = bytes([1 if value else 0])
            length = 1
        else:
            raw = _encode(dt, value)
            length = len(raw) * 8  # 写数据段 Length 字段是位数（服务端 ts==0x04 时 //8）
        item = bytes([0x12, 0x0A, 0x10, ts]) + struct.pack(">H", 1 if is_bit else len(raw)) \
            + struct.pack(">H", db_number) + bytes([area]) \
            + bytes([(addr3 >> 16) & 0xFF, (addr3 >> 8) & 0xFF, addr3 & 0xFF])

        data_item = bytes([0x00, ts]) + struct.pack(">H", length) + raw
        if len(raw) % 2:
            data_item += b"\x00"

        param = bytes([0x05, 0x01]) + item
        conn.pdu_ref = (conn.pdu_ref + 1) & 0xFFFF
        head = struct.pack(">BBHHHH", 0x32, 0x01, 0x0000, conn.pdu_ref,
                           len(param), len(data_item))
        frame = bytes([0x03, 0x00]) \
            + struct.pack(">H", 7 + len(head) + len(param) + len(data_item)) \
            + bytes([0x02, 0xF0, 0x80]) + head + param + data_item
        conn.writer.write(frame)
        await conn.writer.drain()

        resp = await conn.recv_tpkt()
        data_start = 4 + 3 + 12 + 2
        if len(resp) <= data_start:
            raise IOError("S7 写响应缺数据段")
        if resp[data_start] != 0xFF:
            raise IOError(f"S7 写失败 return_code={resp[data_start]:#x}")


def _encode(dt: str, value: Any) -> bytes:
    if dt == "int16":
        return struct.pack(">h", int(value))
    if dt == "uint16":
        return struct.pack(">H", int(value) & 0xFFFF)
    if dt == "int32":
        return struct.pack(">i", int(value))
    if dt == "uint32":
        return struct.pack(">I", int(value) & 0xFFFFFFFF)
    if dt == "float32":
        return struct.pack(">f", float(value))
    if dt == "float64":
        return struct.pack(">d", float(value))
    if dt == "string":
        raw = str(value).encode("utf-8")[:32]
        return raw + b"\x00" * (32 - len(raw))
    return bytes([int(bool(value))])
