"""AB protocol server implementation."""

import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.observability.messages import desc
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 30  # FIXED-P0: 模块级常量，_handle_connection中timeout=_READ_TIMEOUT引用的是模块变量而非self

_CIP_TYPE_MAP = {
    "bool": (0xC1, 1),
    "int16": (0xC3, 2),
    "uint16": (0xC7, 2),
    "int32": (0xC4, 4),
    "dint": (0xC4, 4),
    "uint32": (0xC8, 4),
    "float32": (0xCA, 4),
    "float64": (0xCB, 8),
    "string": (0xA0, 0),
}


class AbDeviceBehavior(StandardDeviceBehavior):
    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._tags: dict[str, Any] = {}
        self._data_types: dict[str, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                raw_dt = p.data_type if hasattr(p, 'data_type') else p.get("data_type", "int32")
                # FIXED: 枚举安全归一化（str(enum) 会带类名前缀，导致 _CIP_TYPE_MAP 永远 miss）
                data_type = str(getattr(raw_dt, "value", raw_dt) or "int32").strip().lower()
                self._tags[name] = self._values.get(name, 0)
                self._data_types[name] = data_type

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._written_values[point_name] = value
            self._tags[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._tags[point_name] = value

    def get_tag(self, tag_name: str) -> Any:
        if tag_name in self._tags:
            return self._tags[tag_name]
        return None

    def set_tag(self, tag_name: str, value: Any) -> None:
        self._tags[tag_name] = value
        self._values[tag_name] = value

    def get_tag_type(self, tag_name: str) -> str:
        return self._data_types.get(tag_name, "int32")

    def get_data_type(self, point_name: str) -> str:
        return self._data_types.get(point_name, "int32")


class AbServer(ProtocolServer):
    protocol_name = "ab"
    protocol_display_name = "Rockwell AB"

    EIP_HEADER_SIZE = 24

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, AbDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_slots: dict[str, int] = {}
        self._host = "0.0.0.0"
        self._port = 44818
        self._session_handle = 1
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 44818)
        self._validate_port(self._port)
        self._start_config = config
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("AB EtherNet/IP server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"AB service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start AB server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("AB task cancelled")
        except Exception as e:
            logger.warning("AB server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("AB server stopped")
            self._log_debug("system", "server_stop", "AB service stopped")

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("AB server task cancelled")
        except Exception as e:
            logger.exception("AB server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("AB connection from %s", addr)
        try:
            while self._server_running:
                # FIXED-C04: 先读EIP头24字节获取length，再读剩余数据，避免大报文截断
                header = await asyncio.wait_for(reader.readexactly(24), timeout=_READ_TIMEOUT)
                eip_length = struct.unpack("<H", header[2:4])[0]
                payload = b""
                if eip_length > 0:
                    payload = await asyncio.wait_for(reader.readexactly(eip_length), timeout=_READ_TIMEOUT)
                data = header + payload
                response = self._process_eip(data)
                if response:
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError, asyncio.TimeoutError, asyncio.IncompleteReadError, BrokenPipeError, ConnectionAbortedError) as e:
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))
            logger.debug("Connection handler error: %s", e)  # FIXED: 添加日志记录，避免异常被静默吞掉
        except Exception as e:  # FIXED-P1: 兜底捕获所有其他异常，避免单个帧处理错误导致整个连接崩溃
            self.record_protocol_error(ProtocolErrorCategory.INTERNAL, str(e))
            logger.exception("AB connection handler unexpected error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_eip(self, data: bytes) -> bytes | None:
        if len(data) < self.EIP_HEADER_SIZE:
            return None

        command = struct.unpack("<H", data[0:2])[0]
        struct.unpack("<H", data[2:4])[0]
        session = struct.unpack("<I", data[4:8])[0]
        struct.unpack("<I", data[8:12])[0]
        sender_context = data[12:20]

        if command == 0x0065:
            return self._handle_register_session(data)
        elif command == 0x0066:
            return self._make_eip_response(0x0066, session, b"", sender_context)
        elif command == 0x006F:
            return self._handle_send_rr_data(data, sender_context)
        elif command == 0x0070:
            return self._handle_send_unit_data(data, sender_context)
        elif command == 0x0001:
            return self._handle_list_identity(data, session, sender_context)

        return self._make_eip_error(command, session, 0x01, sender_context)

    def _handle_list_identity(self, data: bytes, session: int,
                              sender_context: bytes = bytes(8)) -> bytes:
        config = getattr(self, '_start_config', {})
        host = config.get("host", self._host)
        port = config.get("port", self._port)
        try:
            ip_parts = [int(x) for x in host.split(".")]
            ip_bytes = bytes(ip_parts) if len(ip_parts) == 4 else b"\x00\x00\x00\x00"
        except (ValueError, AttributeError):
            ip_bytes = b"\x00\x00\x00\x00"
        identity = bytearray()
        identity += struct.pack("<I", 0x00000001)
        identity += struct.pack("<H", 0x0001)
        identity += struct.pack("<H", 0x0001)
        identity += struct.pack("<H", 0x0000)
        identity += struct.pack("<H", 0x008E)
        identity += struct.pack("<H", 0x0001)
        identity += struct.pack("<H", port)
        identity += ip_bytes
        identity += bytes([0x01, 0x00])
        identity += struct.pack("<I", 0x00000000)
        identity += struct.pack("<H", 0x0000)
        identity += struct.pack("<H", 0x0000)
        identity += struct.pack("<H", 0x0000)
        device_name = config.get("device_name", "ProtoForge-AB").encode("utf-8")
        identity += struct.pack("<B", len(device_name))
        identity += device_name
        # Bug 3 fix: 添加Item封装层 (Item Count + Item Type + Item Length)
        item_payload = bytearray()
        item_payload += struct.pack("<H", 0x0001)              # Item Count = 1
        item_payload += struct.pack("<H", 0x000C)              # Item Type = List Identity Item
        item_payload += struct.pack("<H", len(identity))       # Item Length
        item_payload += identity
        return self._make_eip_response(0x0001, session, bytes(item_payload), sender_context)

    def _make_eip_response(self, command: int, session: int, payload: bytes,
                           sender_context: bytes = bytes(8)) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", command)
        resp += struct.pack("<H", len(payload))
        resp += struct.pack("<I", session)
        resp += struct.pack("<I", 0x00000000)
        resp += sender_context
        resp += struct.pack("<I", 0x00000000)
        resp += payload
        return bytes(resp)

    def _handle_register_session(self, data: bytes) -> bytes:
        sender_context = data[12:20] if len(data) >= 20 else bytes(8)
        resp = bytearray()
        resp += struct.pack("<H", 0x0065)
        resp += struct.pack("<H", 0x0004)
        new_session = self._session_handle
        self._session_handle = (self._session_handle + 1) & 0xFFFFFFFF  # FIXED-M06: 防止溢出为负数
        resp += struct.pack("<I", new_session)
        resp += struct.pack("<I", 0x00000000)
        resp += sender_context
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", 0x0001)
        resp += struct.pack("<H", 0x0000)
        return bytes(resp)

    def _handle_send_rr_data(self, data: bytes,
                             sender_context: bytes = bytes(8)) -> bytes:
        if len(data) < self.EIP_HEADER_SIZE + 6:
            return self._make_eip_error(0x006F, struct.unpack("<I", data[4:8])[0], 0x01,
                                        sender_context)

        session = struct.unpack("<I", data[4:8])[0]

        # FIX: 正确解析 SendRRData 的 CIP 数据偏移量
        # 结构: EIP Header(24) + Interface Handle(4) + Timeout(2) + Item Count(2) + Items
        # Item 1 (Null Address): Type(2) + Length(2) + Data(Length bytes)
        # Item 2 (Unconnected Data 0x00B2): Type(2) + Length(2) + Data(CIP message)
        offset = self.EIP_HEADER_SIZE + 4 + 2  # Skip Interface Handle + Timeout
        item_count = struct.unpack("<H", data[offset:offset + 2])[0] if offset + 2 <= len(data) else 0
        offset += 2
        cip_data = b""
        for _ in range(item_count):
            if offset + 4 > len(data):
                break
            item_type = struct.unpack("<H", data[offset:offset + 2])[0]
            item_len = struct.unpack("<H", data[offset + 2:offset + 4])[0]
            offset += 4
            if offset + item_len > len(data):
                break
            if item_type == 0x00B2:  # Unconnected Data item
                cip_data = data[offset:offset + item_len]
                break
            offset += item_len

        if not cip_data:
            return self._make_eip_error(0x006F, session, 0x01, sender_context)

        cip_service = cip_data[0]

        # FIX: 使用正确的 CIP Service Code
        # 0x54=Forward Open, 0x5B=Large Forward Open, 0x4E=Forward Close,
        # 0x4C=Read Tag, 0x4D=Write Tag
        # FIXED-P0: pylogix>=1.1 默认 ConnectionSize>511 时发送 0x5B Large Forward Open，
        # 原实现不支持导致返回错误帧，客户端 Forward Open 永远失败
        if cip_service in (0x54, 0x5B):
            return self._handle_cip_forward_open(session, cip_data, sender_context,
                                                 large=(cip_service == 0x5B))
        elif cip_service == 0x4E:
            return self._handle_cip_forward_close(session, cip_data, sender_context)
        elif cip_service == 0x4C:
            return self._handle_cip_read_tag(session, cip_data, sender_context)
        elif cip_service == 0x4D:
            return self._handle_cip_write_tag(session, cip_data, sender_context)

        return self._make_cip_error_response(session, cip_service, 0x01, sender_context)

    def _handle_send_unit_data(self, data: bytes,
                               sender_context: bytes = bytes(8)) -> bytes:
        session = struct.unpack("<I", data[4:8])[0]
        if len(data) < 46:
            return self._make_cip_error_response(session, 0x00, 0x00, sender_context)
        # FIXED-P0: 标准 SendUnitData 布局 —— EIP header(24) + InterfaceHandle(4) +
        # Timeout(2) + ItemCount(2) + Item1(Connected Address: Type(2)+Len(2)+ConnID(4))
        # + Item2(Connected Data: Type(2)+Len(2)+SeqNum(2)) + CIP data
        # 原实现把 item_count 读在 offset 16（EIP header 内部），导致 Read/Write Tag
        # 全部走错误分支，已连接读写永远失败
        item_count = struct.unpack("<H", data[30:32])[0] if len(data) >= 32 else 0
        if item_count < 2:
            return self._make_cip_error_response(session, 0x00, 0x00, sender_context)
        t_o_conn_id = struct.unpack("<I", data[36:40])[0] if len(data) >= 40 else 0
        seq_num = struct.unpack("<H", data[44:46])[0] if len(data) >= 46 else 0
        cip_data = data[46:] if len(data) > 46 else b""
        if len(cip_data) > 2:
            service = cip_data[0]
            # FIXED-P0: 已连接消息必须返回裸 CIP 数据，原实现调用 _handle_cip_read_tag/
            # _handle_cip_write_tag（返回完整 EIP SendRRData 帧）导致双重封装，
            # 客户端解析失败
            if service == 0x4C:
                cip_resp = self._build_cip_read_response(cip_data)
            elif service == 0x4D:
                cip_resp = self._build_cip_write_response(cip_data)
            else:
                return self._make_cip_error_response(session, 0x00, 0x00, sender_context)
            return self._wrap_unit_data_response(session, t_o_conn_id, seq_num, cip_resp,
                                                 sender_context)
        return self._make_cip_error_response(session, 0x00, 0x00, sender_context)

    def _wrap_unit_data_response(self, session: int, conn_id: int, seq_num: int,
                                 cip_resp: bytes,
                                 sender_context: bytes = bytes(8)) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0x0070)
        resp += struct.pack("<H", 0)
        resp += struct.pack("<I", session)
        resp += struct.pack("<I", 0x00000000)
        resp += sender_context
        resp += struct.pack("<I", 0x00000000)
        # FIXED-P0: 标准 SendUnitData 布局在 EIP header 后必须携带
        # Interface Handle(4) + Timeout(2)，原实现缺失导致 CIP 数据错位 6 字节，
        # 客户端(pylogix)解析 status/type 时越界
        resp += struct.pack("<I", 0x00000000)          # Interface Handle: 4 bytes
        resp += struct.pack("<H", 0x0000)              # Timeout: 2 bytes
        items = bytearray()
        items += struct.pack("<H", 2)
        items += struct.pack("<H", 0x00B1)
        items += struct.pack("<H", 4)
        items += struct.pack("<I", conn_id)
        items += struct.pack("<H", 0x00B1)
        items += struct.pack("<H", 2 + len(cip_resp))
        items += struct.pack("<H", seq_num)
        items += cip_resp
        resp += items
        resp[2:4] = struct.pack("<H", len(resp) - 24)
        return bytes(resp)

    def _handle_cip_forward_open(self, session: int, cip_data: bytes,
                                 sender_context: bytes = bytes(8),
                                 large: bool = False) -> bytes:
        # FIX: 正确解析 Forward Open 请求
        # 标准格式(0x54): Service(1)+PathSize(1)+Path(N*2)+Priority(1)+TimeoutTicks(1)+
        #        O->T ConnID(4)+T->O ConnID(4)+ConnSerial(2)+VendorID(2)+OrigSerial(4)+
        #        O->T RPI(4)+T->O RPI(4)+O->T Params(2)+T->O Params(2)+Transport(1)
        # 大格式(0x5B): O->T/T->O Params 为 4 字节，响应 Service=0xDB
        path_size_words = cip_data[1] if len(cip_data) > 1 else 0
        path_end = 2 + path_size_words * 2  # 跳过 Service(1) + PathSize(1) + Path
        p = path_end
        if p + 1 > len(cip_data):
            p = 2  # fallback
        # FIXED-P0: Priority(1) 与 TimeoutTicks(1) 是两个独立字节，原实现只跳 1 字节
        # 导致后续所有字段错位 1 字节（echo 的连接 ID/参数错值）
        p += 2
        o_t_conn_id = struct.unpack("<I", cip_data[p:p+4])[0] if p+4 <= len(cip_data) else 0x00000001
        p += 4
        t_o_conn_id = struct.unpack("<I", cip_data[p:p+4])[0] if p+4 <= len(cip_data) else 0x00000002
        p += 4
        conn_serial = struct.unpack("<H", cip_data[p:p+2])[0] if p+2 <= len(cip_data) else 0x0001
        p += 2
        vendor_id = struct.unpack("<H", cip_data[p:p+2])[0] if p+2 <= len(cip_data) else 0x0001
        p += 2
        orig_serial = struct.unpack("<I", cip_data[p:p+4])[0] if p+4 <= len(cip_data) else 0x00000001
        p += 4
        o_t_rpi = struct.unpack("<I", cip_data[p:p+4])[0] if p+4 <= len(cip_data) else 0x00010000
        p += 4
        t_o_rpi = struct.unpack("<I", cip_data[p:p+4])[0] if p+4 <= len(cip_data) else 0x00010000
        p += 4
        if large:
            # 大格式: Params 为 4 字节（高 16 位 flags + 低 16 位连接尺寸）
            o_t_params = struct.unpack("<I", cip_data[p:p+4])[0] if p+4 <= len(cip_data) else 0x00004302
            p += 4
            t_o_params = struct.unpack("<I", cip_data[p:p+4])[0] if p+4 <= len(cip_data) else 0x00004302
            p += 4
        else:
            o_t_params = struct.unpack("<H", cip_data[p:p+2])[0] if p+2 <= len(cip_data) else 0x4302
            p += 2
            t_o_params = struct.unpack("<H", cip_data[p:p+2])[0] if p+2 <= len(cip_data) else 0x4302
            p += 2

        # FIX: Forward Open Response service = 0xD4 (0x54|0x80) / 0xDB (0x5B|0x80)
        resp_service = 0xDB if large else 0xD4
        cip_resp = bytearray()
        cip_resp += bytes([resp_service, 0x00])  # Service Response + Reserved
        cip_resp += bytes([0x00, 0x00])       # Status=Success + Additional Status Size=0
        cip_resp += struct.pack("<I", o_t_conn_id)   # O->T Connection ID (echo from request)
        cip_resp += struct.pack("<I", t_o_conn_id)   # T->O Connection ID (echo from request)
        cip_resp += struct.pack("<H", conn_serial)
        cip_resp += struct.pack("<H", vendor_id)
        cip_resp += struct.pack("<I", orig_serial)
        cip_resp += struct.pack("<I", o_t_rpi)
        cip_resp += struct.pack("<I", t_o_rpi)
        if large:
            cip_resp += struct.pack("<I", o_t_params)
            cip_resp += struct.pack("<I", t_o_params)
        else:
            cip_resp += struct.pack("<H", o_t_params)
            cip_resp += struct.pack("<H", t_o_params)
        cip_resp += bytes([0x00])  # Connection Path Size = 0 (no path echoed)
        return self._wrap_cip_response(session, cip_resp, sender_context)

    def _handle_cip_forward_close(self, session: int, cip_data: bytes,
                                  sender_context: bytes = bytes(8)) -> bytes:
        # FIX: Forward Close Response service = 0xCE (0x4E | 0x80)
        cip_resp = bytearray()
        cip_resp += bytes([0xCE])
        cip_resp += bytes([0x00])       # Reserved
        cip_resp += bytes([0x00])       # Status = Success
        cip_resp += bytes([0x00])       # Additional Status Size = 0
        return self._wrap_cip_response(session, cip_resp, sender_context)

    @staticmethod
    def _pack_cip_value(data_type: str, value: Any) -> bytes:
        # FIXED: 标准 CIP Read Tag 响应数据段 = Symbol Type(2 字节: 类型码 + 0x00) + 值字节。
        # 原实现额外插入 2 字节 size 字段（type(1)+size(2)+value），非真实 ControlLogix 行为。
        type_info = _CIP_TYPE_MAP.get(data_type, (0xC1, 4))
        type_code, size = type_info
        try:  # FIXED-P1: int()/float()异常保护，非数字值时回退0
            if data_type == "bool":
                return struct.pack("<H", type_code) + bytes([0x01 if value else 0x00])
            elif data_type == "string":
                s = str(value).encode("utf-8")
                return struct.pack("<HH", type_code, len(s)) + s
            elif data_type in ("int16",):
                return struct.pack("<Hh", type_code, int(value))
            elif data_type in ("uint16",):
                return struct.pack("<HH", type_code, int(value))
            elif data_type in ("int32",):
                return struct.pack("<Hi", type_code, int(value))
            elif data_type in ("uint32",):
                return struct.pack("<HI", type_code, int(value))
            elif data_type in ("float32",):
                return struct.pack("<Hf", type_code, float(value))
            elif data_type in ("float64",):
                return struct.pack("<Hd", type_code, float(value))
            else:
                return struct.pack("<Hi", type_code, int(value))
        except (ValueError, TypeError):
            return struct.pack("<Hi", type_code, 0)

    def _parse_cip_tag_path(self, cip_data: bytes) -> str:
        tag_parts = []
        offset = 2
        while offset < len(cip_data):
            segment_type = cip_data[offset]
            if segment_type == 0x91:
                offset += 1
                if offset >= len(cip_data):
                    break
                tag_len = cip_data[offset]
                offset += 1
                if offset + tag_len > len(cip_data):
                    break
                tag_name = cip_data[offset:offset + tag_len].decode("ascii", errors="replace").rstrip("\x00")
                tag_parts.append(tag_name)
                offset += tag_len
                if tag_len % 2 != 0:
                    offset += 1
            elif segment_type == 0x28:
                offset += 1
                if offset >= len(cip_data):
                    break
                member_id = cip_data[offset]
                offset += 1
                if tag_parts:
                    tag_parts[-1] = f"{tag_parts[-1]}.{member_id}"
            elif segment_type == 0x00:
                offset += 1
            else:
                offset += 1
        return ".".join(tag_parts) if tag_parts else ""

    def _get_path_end_offset(self, cip_data: bytes) -> int:
        # FIXED: 按标准计算路径终点 = 2 + PathSize(字) * 2。
        # 原实现逐字节扫描寻找段类型，无法识别路径结束，
        # 会把写入的 Tag Type/Count/数据字节也当作路径段走查，
        # 导致 path_end 越界、写入被误判为路径错误（status 0x04）。
        if len(cip_data) < 2:
            return len(cip_data)
        path_size_words = cip_data[1]
        end = 2 + path_size_words * 2
        return min(end, len(cip_data))

    def _build_cip_read_response(self, cip_data: bytes) -> bytes:
        """构造裸 CIP Read Tag 响应（不含 EIP 封装）"""
        tag_value = 0
        data_type = "int32"
        behavior = self._behaviors.get(self._default_device_id or "")
        tag_name = self._parse_cip_tag_path(cip_data)
        if tag_name and behavior:
            # Bug 6 fix: 检查tag是否存在，不存在时返回CIP错误(0x04=路径段错误)
            if tag_name not in behavior._tags and tag_name not in behavior._data_types:
                return bytes([0xCC, 0x00, 0x04, 0x00])
            tag_value = behavior.get_tag(tag_name)
            if tag_value is None:
                tag_value = behavior.get_value(tag_name)
            data_type = behavior.get_data_type(tag_name)
        elif not tag_name:
            if behavior and behavior._values:
                data_type = "dint"
                tag_value = 0

        # FIX: Read Tag Response service = 0xCC (0x4C | 0x80)
        # CIP 响应格式: Service(1) + Reserved(1) + Status(1) + AddStatusSize(1) + Data
        cip_resp = bytearray()
        cip_resp += bytes([0xCC])
        cip_resp += bytes([0x00])       # Reserved
        cip_resp += bytes([0x00])       # Status = Success
        cip_resp += bytes([0x00])       # Additional Status Size = 0
        cip_resp += self._pack_cip_value(data_type, tag_value)
        return bytes(cip_resp)

    def _handle_cip_read_tag(self, session: int, cip_data: bytes,
                             sender_context: bytes = bytes(8)) -> bytes:
        return self._wrap_cip_response(session, self._build_cip_read_response(cip_data),
                                       sender_context)

    def _build_cip_write_response(self, cip_data: bytes) -> bytes:
        """构造裸 CIP Write Tag 响应（不含 EIP 封装）"""
        tag_name = self._parse_cip_tag_path(cip_data)
        behavior = self._behaviors.get(self._default_device_id or "")
        if tag_name and behavior:
            path_end = self._get_path_end_offset(cip_data)
            if path_end < 0 or path_end + 3 > len(cip_data):  # FIXED-N07: 路径偏移校验，至少需要3字节(type+size)
                return bytes([0xCD, 0x00, 0x04, 0x00])
            if path_end < len(cip_data):
                # FIXED: 标准 CIP Write Tag 请求的数据段 = Tag Type(UINT 2 字节) +
                # Number of Elements(UINT 2 字节) + 数据。原实现按自造的
                # type(1)+size(2)+value 解析（bool skip=4 / 其他 skip=3），
                # 与真实 ControlLogix 不兼容。
                if path_end + 4 > len(cip_data):
                    return bytes([0xCD, 0x00, 0x05, 0x00])
                type_code = struct.unpack("<H", cip_data[path_end:path_end + 2])[0]
                elem_count = struct.unpack("<H", cip_data[path_end + 2:path_end + 4])[0]
                value_data = cip_data[path_end + 4:]
                if len(value_data) > 0:
                    data_type = behavior.get_tag_type(tag_name)
                    write_value = self._unpack_cip_value(data_type, value_data)
                    behavior.set_tag(tag_name, write_value)
                    self._log_debug("recv", "cip_write",
                                    f"Write tag {tag_name}={write_value}",
                                    detail={"tag": tag_name, "value": write_value,
                                            "type_code": type_code, "count": elem_count})

        # FIX: Write Tag Response service = 0xCD (0x4D | 0x80)
        # CIP 响应格式: Service(1) + Reserved(1) + Status(1) + AddStatusSize(1)
        cip_resp = bytearray()
        cip_resp += bytes([0xCD])
        cip_resp += bytes([0x00])  # Reserved
        if not (tag_name and behavior):  # FIXED-L03: tag不存在或behavior为None时返回CIP错误码0x04
            cip_resp += bytes([0x04])  # Status = Path destination unknown
            cip_resp += bytes([0x00])  # Additional Status Size = 0
        else:
            cip_resp += bytes([0x00])  # Status = Success
            cip_resp += bytes([0x00])  # Additional Status Size = 0
        return bytes(cip_resp)

    def _handle_cip_write_tag(self, session: int, cip_data: bytes,
                              sender_context: bytes = bytes(8)) -> bytes:
        return self._wrap_cip_response(session, self._build_cip_write_response(cip_data),
                                       sender_context)

    @staticmethod
    def _unpack_cip_value(data_type: str, data: bytes) -> Any:
        try:
            # FIXED: 数据从 Write Tag 请求的 type+count 字段之后开始，直接就是值字节
            if data_type == "bool" and len(data) >= 1:
                return data[0] != 0
            elif data_type == "int16" and len(data) >= 2:
                return struct.unpack("<h", data[:2])[0]
            elif data_type == "uint16" and len(data) >= 2:
                return struct.unpack("<H", data[:2])[0]
            elif data_type == "int32" and len(data) >= 4:
                return struct.unpack("<i", data[:4])[0]
            elif data_type == "uint32" and len(data) >= 4:
                return struct.unpack("<I", data[:4])[0]
            elif data_type == "float32" and len(data) >= 4:
                return struct.unpack("<f", data[:4])[0]
            elif data_type == "float64" and len(data) >= 8:
                return struct.unpack("<d", data[:8])[0]
            elif len(data) >= 4:
                return struct.unpack("<i", data[:4])[0]
        except (struct.error, IndexError) as e:
            logger.warning("AB CIP value unpack error: %s", e)
        return 0

    def _wrap_cip_response(self, session: int, cip_data: bytes,
                           sender_context: bytes = bytes(8)) -> bytes:
        # FIX: Unconnected Data (0x00B2) 不应有 sequence number 前缀
        # (那属于 Connected Data 0x00B1 的格式)
        resp = bytearray()
        resp += struct.pack("<H", 0x006F)              # Command: SendRRData
        resp += struct.pack("<H", 0)                    # Length (updated below)
        resp += struct.pack("<I", session)
        resp += struct.pack("<I", 0x00000000)
        resp += sender_context
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", 0x00000000)          # Interface Handle: 4 bytes
        resp += struct.pack("<H", 0x0000)              # Timeout: 2 bytes
        resp += struct.pack("<H", 0x0002)              # Item Count: 2 bytes
        resp += struct.pack("<H", 0x0000)              # Item1 Type (Null Address): 2 bytes
        # FIXED-P0: 标准 Null Address Item 的 Length 必须为 0 且不带 data，
        # 原实现写 Length=4 并多跟 4 字节零，导致 CIP 数据整体偏移 +4，
        # 客户端(pylogix)在 offset 42 读 GeneralStatus 时读到错位字节，Forward Open 永远失败
        resp += struct.pack("<H", 0x0000)              # Item1 Length = 0 (no data)
        resp += struct.pack("<H", 0x00B2)              # Item2 Type (Unconnected Data): 2 bytes
        resp += struct.pack("<H", len(cip_data))       # Item2 Length: CIP data only
        resp += cip_data
        resp[2:4] = struct.pack("<H", len(resp) - 24)  # Update EIP length
        return bytes(resp)

    def _make_cip_error_response(self, session: int, service: int, error: int,
                                 sender_context: bytes = bytes(8)) -> bytes:
        cip_resp = bytearray()
        cip_resp += bytes([(service | 0x80) & 0xFF])
        cip_resp += bytes([0x00])
        cip_resp += struct.pack("<I", 0x00000000)
        cip_resp += bytes([error])
        return self._wrap_cip_response(session, cip_resp, sender_context)

    def _make_eip_error(self, command: int, session: int, status: int,
                        sender_context: bytes = bytes(8)) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", command)
        resp += struct.pack("<H", 0x0000)
        resp += struct.pack("<I", session)
        resp += struct.pack("<I", status)
        resp += sender_context
        resp += struct.pack("<I", 0x00000000)
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = AbDeviceBehavior(device_config.points)
        proto_config = device_config.protocol_config or {}
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_slots[device_config.id] = proto_config.get("slot", 0)  # FIXED-P1: 移入_behaviors_lock内保护
        await self._update_default_device_async(device_config.id)

        logger.info("AB device created: %s (slot=%d)",
                     device_config.id, self._device_slots[device_config.id])
        self._log_debug("system", "device_create",
                        f"AB device created: {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_slots.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock内保护
        await self._clear_default_device_async(device_id)
        logger.info("AB device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"AB device removed: {device_id}",
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return []
        now = time.time()
        return [PointValue(name=p.name, value=behavior.get_value(p.name), timestamp=now) for p in config.points]

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        return behavior.on_write(point_name, value)

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        """内部同步：更新 AB 标签数据，绕过访问控制检查。"""
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return
        behavior.set_value(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": desc("listen_address", "EtherNet/IP server listen address")},
                "port": {"type": "integer", "default": 44818, "description": desc("ab_port", "EtherNet/IP port (default 44818)")},
            },
        }
