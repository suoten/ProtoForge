"""DNP3 主站（master）实现（v1.16.1）：主动拨出连接 DNP3 从站/RTU。

复用从站实现的链路层纯函数（build_link_frame/parse_link_frame）与对象编码。
轮询策略：Class 0 完整性读（全量）+ Class 1/2 事件轮询（增量）；
远端数据进入本地点位存储（address = IOA），断线指数退避重连、
点位质量标记（good/bad）与轮询统计由 MasterBase 统一提供。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
import time
from typing import Any

from protoforge.protocols.dnp3.server import (
    G_ANALOG_INPUT,
    G_ANALOG_INPUT_EVENT,
    G_BINARY_INPUT,
    G_BINARY_INPUT_EVENT,
    G_CLASS,
    FC_ACK,
    build_link_frame,
    parse_link_frame,
    _reassemble,
)
from protoforge.protocols.master.base import MasterBase

logger = logging.getLogger(__name__)

_MASTER_SRC_DEFAULT = 1


def parse_objects_data(group: int, variation: int, data: bytes) -> list[tuple[int, Any, str]]:
    """解析单个对象的索引前缀数据点序列为 [(ioa, value, dt)] 纯函数。

    :param group: 对象组（来自 _parse_objects 的解析结果——数据从 IOA 开始，
                  不含对象头，接口与 _parse_objects 的 payload 对齐）
    :param variation: 对象变体
    :param data: 数据点序列（每点 = IOA16 + 值字段）

    支持从站编码产生的对象：G1V2/G2V1（二输入，flag 字节 bit7=值）、
    G20V6（flag + int32 定标 ×1000）、G32V1（32 位模拟量事件，flag + int32
    定标 ×1000）。模拟量统一 ÷1000 回真实工程值（与从站 encode 定标互证）。
    """
    specs = {
        (G_BINARY_INPUT, 2): (3, "bool", 1),
        (G_BINARY_INPUT_EVENT, 1): (3, "bool", 1),
        (G_ANALOG_INPUT, 6): (7, "float32", 1000),
        (32, 1): (7, "float32", 1000),
    }
    spec = specs.get((group, variation))
    if spec is None:
        return []
    per, dt, scale = spec
    out: list[tuple[int, Any, str]] = []
    i = 0
    while i + per <= len(data):
        ioa = struct.unpack("<H", data[i:i + 2])[0]
        flag = data[i + 2]
        if dt == "bool":
            out.append((ioa, bool(flag & 0x80), dt))
            i += 3
        else:
            val = struct.unpack("<i", data[i + 3:i + 7])[0] / scale
            i += 7
            out.append((ioa, float(val), dt))
    return out


class _Dnp3Conn:
    __slots__ = ("reader", "writer", "timeout", "outstation_addr", "master_addr")

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 timeout: float, outstation_addr: int, master_addr: int):
        self.reader = reader
        self.writer = writer
        self.timeout = timeout
        self.outstation_addr = outstation_addr
        self.master_addr = master_addr

    async def send_request(self, apdu: bytes) -> bytes:
        """发送一条应用层请求并收集完整响应（跳过纯 ACK 链路帧，处理 FIR/FIN 分段）。"""
        self.writer.write(build_link_frame(self.outstation_addr, self.master_addr, 0xC4, apdu))
        await self.writer.drain()
        buf = b""
        fragments: list[bytes] = []
        deadline = asyncio.get_event_loop().time() + self.timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError("DNP3 response timeout")
            chunk = await asyncio.wait_for(self.reader.read(4096), timeout=remaining)
            if not chunk:
                raise ConnectionError("outstation closed connection")
            buf += chunk
            while True:
                parsed = parse_link_frame(buf)
                if parsed is None:
                    break
                frame, consumed = parsed
                buf = buf[consumed:]
                if not frame["user_data"]:
                    continue  # 链路层 ACK / 确认帧
                fragments.append(frame["user_data"])
                th = frame["user_data"][0]
                if th & 0x40:  # FIN
                    return _reassemble(fragments) if len(fragments) > 1 else fragments[0]


class Dnp3MasterServer(MasterBase):
    """DNP3 主站：主动拨出连接 DNP3 从站，Class 0 全量 + Class 1/2 事件轮询，
    支持 G10 二输出 / G41 模拟输出遥控。"""

    protocol_name = "dnp3_master"
    protocol_display_name = "DNP3 Master"
    protocol_description = "主动连接真实 DNP3 从站/RTU（IEEE 1815），Class 0 完整性读 + Class 1/2 事件轮询，支持二输出/模拟输出控制"
    protocol_version = "1.0.0"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "192.168.1.100",
                         "description": "从站（outstation）IP 地址"},
                "port": {"type": "integer", "default": 20000,
                         "description": "DNP3 TCP 端口"},
                "outstation_addr": {"type": "integer", "default": 1,
                                    "description": "目标从站链路地址"},
                "master_addr": {"type": "integer", "default": 1,
                                "description": "本主站链路地址"},
            },
        }

    # -- 连接 ------------------------------------------------------------

    async def _connect(self, cfg: dict[str, Any]) -> Any:
        host = cfg.get("host")
        if not host:
            raise ValueError("dnp3_master 需要 protocol_config.host")
        port = int(cfg.get("port", 20000))
        timeout = self._timeout_of(cfg)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(str(host), port), timeout=timeout)
        return _Dnp3Conn(reader, writer, timeout,
                         outstation_addr=int(cfg.get("outstation_addr", 1)),
                         master_addr=int(cfg.get("master_addr", _MASTER_SRC_DEFAULT)))

    async def _close_conn(self, conn: Any) -> None:
        try:
            conn.writer.close()
        except Exception as e:
            logger.debug("DNP3 master close conn error: %s", e)

    # -- 轮询 ------------------------------------------------------------

    async def _poll_once(self, conn: Any, device_id: str,
                         cfg: dict[str, Any], points: list) -> dict[str, Any]:
        values: dict[str, Any] = {}
        ioa_map = {}
        for p in points:
            try:
                ioa_map[int(p.address)] = p
            except (TypeError, ValueError):
                continue

        # ① Class 0 完整性读
        apdu = bytes([0xC0, 0x01, 60, 1, 0x06])
        resp = await conn.send_request(apdu)
        if resp[1] == 0x81:  # Read Response
            from protoforge.protocols.dnp3.server import _parse_objects
            for obj in _parse_objects(resp[2:]):
                if obj.get("payload"):
                    for ioa, value, _dt in parse_objects_data(
                            obj["group"], obj["variation"], obj["payload"]):
                        p = ioa_map.get(ioa)
                        if p is not None:
                            values[p.name] = value

        # ② Class 1 / Class 2 事件轮询（增量）
        for var in (2, 3):
            apdu = bytes([0xC0, 0x01, 60, var, 0x06])
            resp = await conn.send_request(apdu)
            if resp[1] == 0x81 and len(resp) > 5 and resp[2] != 60:
                from protoforge.protocols.dnp3.server import _parse_objects
                for obj in _parse_objects(resp[2:]):
                    if obj.get("payload"):
                        for ioa, value, _dt in parse_objects_data(
                                obj["group"], obj["variation"], obj["payload"]):
                            p = ioa_map.get(ioa)
                            if p is not None:
                                values[p.name] = value
        return values

    # -- 遥控 ------------------------------------------------------------

    async def _write_remote(self, conn: Any, device_id: str, cfg: dict[str, Any],
                            point_name: str, value: Any) -> bool:
        cfg_dev = self._device_configs.get(device_id)
        if not cfg_dev:
            return False
        point = next((p for p in cfg_dev.points if p.name == point_name), None)
        if point is None or point.access not in ("w", "rw"):
            return False
        try:
            ioa = int(point.address)
        except (TypeError, ValueError):
            return False
        dt = point.data_type.value if hasattr(point.data_type, "value") else str(point.data_type)
        if dt == "bool":
            # G10V2：IOA16 + flag(quality online | value)
            objects = bytes([10, 2, 0x01]) + struct.pack("<H", 1)
            objects += struct.pack("<H", ioa) + bytes([0x01 | (0x80 if bool(value) else 0)])
        else:
            # G41V2：IOA16 + flag + int16
            objects = bytes([40, 2, 0x01]) + struct.pack("<H", 1)
            objects += struct.pack("<H", ioa) + bytes([0x01]) + struct.pack(
                "<h", max(-32768, min(32767, int(value))))
        # FIXED(v1.16.1): 应用层消息必须带 AC+FC 头——此前发裸对象帧，
        # 从站按 AC=0x0A/FC=0x02 错位解析为 G1V2，写被静默忽略
        apdu = bytes([0xC0, 0x02]) + objects  # AC: FIR|FIN|SEQ=0, FC=Write
        conn.writer.write(build_link_frame(conn.outstation_addr, conn.master_addr, 0xC4, apdu))
        await conn.writer.drain()
        # 应用层确认由下一轮轮询消费（从站 ACK 帧无 user_data，轮询循环自动跳过）
        return True
