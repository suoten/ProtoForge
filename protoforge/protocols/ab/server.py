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
        self._tag_alias: dict[str, str] = {}    # point name -> tag(address)
        self._tag_reverse: dict[str, str] = {}  # tag(address) -> point name
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                addr = (p.address if hasattr(p, 'address') else p.get("address", "")) or ""
                raw_dt = p.data_type if hasattr(p, 'data_type') else p.get("data_type", "int32")
                # FIXED: 枚举安全归一化（str(enum) 会带类名前缀，导致 _CIP_TYPE_MAP 永远 miss）
                data_type = str(getattr(raw_dt, "value", raw_dt) or "int32").strip().lower()
                # FIXED-JOINT: CIP 以 tag 名寻址，tag 名即点位 address（TestTag1 等）；
                # 原实现用 point.name 注册导致 EdgeLite 按 address 读取时
                # 返回 CIP 0x04（Path destination unknown），采集恒为 null。
                # 无 address 的点位回退到 name。
                tag = addr or name
                self._tag_alias[name] = tag
                self._tag_reverse[tag] = name
                self._tags[tag] = self._values.get(tag, self._values.get(name, 0))
                self._data_types[tag] = data_type

    def _resolve_tag(self, key: str) -> str:
        """point name ↔ tag(address) 双向兼容：优先按别名映射，未知键原样返回。"""
        return self._tag_alias.get(key, key)

    def on_write(self, point_name: str, value: Any) -> bool:
        tag = self._resolve_tag(point_name)
        if point_name in self._values or tag in self._tags:
            self._values[point_name] = value
            self._written_values[point_name] = value
            self._tags[tag] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        # 引擎生成循环按 point name 调用；tag 键同步更新保证 CIP 读到最新值
        self._values[point_name] = value
        self._tags[self._resolve_tag(point_name)] = value

    def get_tag(self, tag_name: str) -> Any:
        # CIP 读取优先走 get_value 的动态生成路径（sine 等生成器实时出值），
        # 否则会一直读到 _tags 初始化时的静态 0。
        key = self._resolve_tag(tag_name)
        if key in self._tags:
            name = self._tag_reverse.get(key, key)
            return self.get_value(name)
        return None

    def set_tag(self, tag_name: str, value: Any) -> None:
        tag = self._resolve_tag(tag_name)
        name = self._tag_reverse.get(tag, tag)
        self._tags[tag] = value
        self._values[name] = value
        # 行为级写入冻结：get_value() 对动态生成器（sine/increment 等）会重新生成，
        # 不记录 _written_values 时下一次 CIP 读就把外部下发值覆盖（联调实测）。
        # 30 秒后由引擎 tick 的解冻逻辑 clear_written() 恢复动态输出。
        self._written_values[name] = value

    def get_tag_type(self, tag_name: str) -> str:
        return self._data_types.get(self._resolve_tag(tag_name), "int32")

    def get_data_type(self, point_name: str) -> str:
        return self._data_types.get(self._resolve_tag(point_name), "int32")


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
        elif command == 0x0004:
            # FIXED: Kepware 连接前先发 ListServices，缺失时对端报 framing error
            return self._handle_list_services(session, sender_context)

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

    def _handle_list_services(self, session: int, sender_context: bytes = bytes(8)) -> bytes:
        """EIP ListServices (0x0004) —— 客户端能力协商，缺失时 Kepware 报 framing error"""
        payload = bytearray()
        payload += struct.pack("<H", 1)            # Item Count = 1
        payload += struct.pack("<H", 0x0100)       # Item Type: List Services Item
        payload += struct.pack("<H", 4)            # Item Length
        payload += struct.pack("<H", 1)            # Protocol Version
        payload += struct.pack("<H", 0x021E)       # Capability Flags (同真实 ControlLogix)
        return self._make_eip_response(0x0004, session, bytes(payload), sender_context)

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
        # FIXED-P0: 补充 CIP Get_Attributes_All (0x01) —— pylogix 的
        # GetDeviceProperties()/连接 ping 验证依赖 Identity Object 查询，
        # 缺失该服务时客户端连接验证永远失败
        elif cip_service == 0x01:
            return self._handle_cip_get_attributes_all(session, cip_data, sender_context)
        elif cip_service == 0x4E:
            return self._handle_cip_forward_close(session, cip_data, sender_context)
        elif cip_service == 0x4C:
            return self._handle_cip_read_tag(session, cip_data, sender_context)
        elif cip_service == 0x4D:
            return self._handle_cip_write_tag(session, cip_data, sender_context)
        elif cip_service == 0x03:
            # FIXED: Kepware 用 Get_Attribute_List 读设备身份（Identity Object），
            # 缺失该服务时 "Unable to retrieve the identity" 并降级 Symbolic Protocol
            return self._handle_cip_get_attribute_list(session, cip_data, sender_context)
        elif cip_service == 0x0A:
            # FIXED: Kepware 批量读用 Multiple Service Packet，缺失时报 framing error
            return self._handle_cip_multiple_service(session, cip_data, sender_context)
        elif cip_service == 0x52:
            # Read Tag Fragmented —— 点位值小，按普通读处理（偏移字段被忽略）
            return self._handle_cip_read_tag(session, cip_data, sender_context)
        elif cip_service == 0x53:
            # Write Tag Fragmented —— 按普通写处理
            return self._handle_cip_write_tag(session, cip_data, sender_context)

        return self._make_cip_error_response(session, cip_service, 0x01, sender_context)

    def _handle_cip_get_attributes_all(self, session: int, cip_data: bytes,
                                       sender_context: bytes = bytes(8)) -> bytes:
        return self._wrap_cip_response(
            session, self._build_cip_get_attributes_all(cip_data), sender_context)

    def _build_cip_get_attributes_all(self, cip_data: bytes) -> bytes:
        """CIP Get_Attributes_All (0x01) —— Identity Object 标准属性集（裸 CIP 应答）

        响应: Service(0x81)+Reserved+Status+Attrs: VendorID(UINT) DeviceType(UINT)
        ProductCode(UINT) Revision(2×USINT) Status(WORD) SerialNumber(UDWORD)
        ProductName(SHORT_STRING)
        """
        config = getattr(self, '_start_config', {})
        device_name = str(config.get("device_name", "ProtoForge-AB"))
        cip_resp = bytearray()
        cip_resp += bytes([0x81, 0x00, 0x00, 0x00])       # Service|0x80 + Reserved + Status + AddStatusSize
        cip_resp += struct.pack("<H", 1)                   # Attr1: Vendor ID
        cip_resp += struct.pack("<H", 14)                  # Attr2: Device Type (Prog. Logic Controller)
        cip_resp += struct.pack("<H", 1)                   # Attr3: Product Code
        cip_resp += bytes([1, 0])                          # Attr4: Revision 1.0
        cip_resp += struct.pack("<H", 0x0000)              # Attr5: Status
        cip_resp += struct.pack("<I", 0x00000001)          # Attr6: Serial Number
        name_bytes = device_name.encode("utf-8")[:230]
        cip_resp += bytes([len(name_bytes)])               # Attr7: Product Name (SHORT_STRING)
        cip_resp += name_bytes
        return bytes(cip_resp)

    def _handle_send_unit_data(self, data: bytes,
                               sender_context: bytes = bytes(8)) -> bytes:
        session = struct.unpack("<I", data[4:8])[0]
        if len(data) < 46:
            # FIXED-P0: 已连接通道的错误必须通过 _wrap_unit_data_response 返回，
            # 原实现返回 _make_cip_error_response（SendRRData 帧），
            # Kepware 在已连接通道收到错误格式即报 framing error
            return self._make_eip_error(0x0070, session, 0x01, sender_context)
        # FIXED-P0: 标准 SendUnitData 布局 —— EIP header(24) + InterfaceHandle(4) +
        # Timeout(2) + ItemCount(2) + Item1(Connected Address: Type(2)+Len(2)+ConnID(4))
        # + Item2(Connected Data: Type(2)+Len(2)+SeqNum(2)) + CIP data
        # 原实现把 item_count 读在 offset 16（EIP header 内部），导致 Read/Write Tag
        # 全部走错误分支，已连接读写永远失败
        #
        # FIXED-P0: 动态解析 items 而非硬编码偏移，不同客户端的 item 长度可能不同
        offset = self.EIP_HEADER_SIZE + 4 + 2  # Skip Interface Handle + Timeout
        item_count = struct.unpack("<H", data[offset:offset + 2])[0] if offset + 2 <= len(data) else 0
        offset += 2
        if item_count < 2:
            return self._make_eip_error(0x0070, session, 0x01, sender_context)
        t_o_conn_id = 0
        seq_num = 0
        cip_data = b""
        for _ in range(item_count):
            if offset + 4 > len(data):
                break
            item_type = struct.unpack("<H", data[offset:offset + 2])[0]
            item_len = struct.unpack("<H", data[offset + 2:offset + 4])[0]
            offset += 4
            if offset + item_len > len(data):
                break
            # FIXED-P0: 标准 EtherNet/IP 中 Connected Address item 类型是 0x00A1，
            # Connected Data item 类型是 0x00B1。原实现两个分支都写 0x00B1，
            # 导致 Connected Address 永远不匹配，ConnID 恒为 0。
            if item_type == 0x00A1:  # Connected Address item
                if item_len >= 4:
                    t_o_conn_id = struct.unpack("<I", data[offset:offset + 4])[0]
            elif item_type == 0x00B1:  # Connected Data item
                # Connected Data: first 2 bytes = sequence number, rest = CIP data
                if item_len >= 2:
                    seq_num = struct.unpack("<H", data[offset:offset + 2])[0]
                    cip_data = data[offset + 2:offset + item_len]
            offset += item_len
        if not cip_data or len(cip_data) < 2:
            cip_resp = self._make_bare_cip_error(0x00, 0x05)
            return self._wrap_unit_data_response(session, t_o_conn_id, seq_num, cip_resp,
                                                 sender_context)
        service = cip_data[0]
        # FIXED-P0: 已连接消息必须返回裸 CIP 数据，原实现调用 _handle_cip_read_tag/
        # _handle_cip_write_tag（返回完整 EIP SendRRData 帧）导致双重封装，
        # 客户端解析失败
        if service in (0x4C, 0x52):
            cip_resp = self._build_cip_read_response(cip_data)
        elif service in (0x4D, 0x53):
            cip_resp = self._build_cip_write_response(cip_data)
        elif service == 0x01:
            # FIXED: Kepware 可能通过已连接通道查询设备身份/属性，
            # 未识别服务此前在已连接路径返回畸形错误帧
            cip_resp = self._build_cip_get_attributes_all(cip_data)
        elif service == 0x03:
            cip_resp = self._build_cip_get_attribute_list(cip_data)
        elif service == 0x0A:
            cip_resp = self._build_cip_multiple_service(cip_data)
        else:
            # FIXED-P0: 已连接通道不支持的服务也必须通过 _wrap_unit_data_response 返回
            cip_resp = self._make_bare_cip_error(service, 0x08)
        return self._wrap_unit_data_response(session, t_o_conn_id, seq_num, cip_resp,
                                             sender_context)

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
        # FIXED-P0: 标准 EtherNet/IP 中 Connected Address item 类型是 0x00A1，
        # 原实现用 0x00B1（Connected Data 类型），严格客户端解析时
        # 把 ConnID 当成 Connected Data 解析导致 framing error
        items += struct.pack("<H", 0x00A1)           # Item1: Connected Address
        items += struct.pack("<H", 4)
        items += struct.pack("<I", conn_id)
        items += struct.pack("<H", 0x00B1)           # Item2: Connected Data
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
        # FIXED-P0: 使用 _get_path_end_offset 限制扫描范围，
        # 原实现扫描整个 cip_data，会把路径后面的 Element Count / Type / Data
        # 字节误当路径段解析（如 ElementCount=1 的低字节 0x01 被跳过，
        # 但高字节 0x00 循环；若值恰好是 0x91/0x28 则误生成额外路径段，
        # 导致 tag 名拼接错误，读取返回 status 0x04）
        path_end = self._get_path_end_offset(cip_data)
        tag_parts = self._scan_tag_segments(cip_data, 2, path_end)
        if not tag_parts and path_end < len(cip_data):
            # 回退：某些客户端 PathSize 字段不准确（偏小），
            # 回退扫描整个 cip_data 以保持兼容
            tag_parts = self._scan_tag_segments(cip_data, 2, len(cip_data))
        return ".".join(tag_parts) if tag_parts else ""

    @staticmethod
    def _scan_tag_segments(cip_data: bytes, start: int, end: int) -> list[str]:
        """扫描 CIP 路径段，返回 tag 名部分列表"""
        tag_parts = []
        offset = start
        while offset < end:
            segment_type = cip_data[offset]
            if segment_type == 0x91:
                offset += 1
                if offset >= end:
                    break
                tag_len = cip_data[offset]
                offset += 1
                if offset + tag_len > end:
                    break
                tag_name = cip_data[offset:offset + tag_len].decode("ascii", errors="replace").rstrip("\x00")
                tag_parts.append(tag_name)
                offset += tag_len
                if tag_len % 2 != 0:
                    offset += 1
            elif segment_type == 0x28:
                offset += 1
                if offset >= end:
                    break
                member_id = cip_data[offset]
                offset += 1
                if tag_parts:
                    tag_parts[-1] = f"{tag_parts[-1]}.{member_id}"
            elif segment_type == 0x00:
                offset += 1
            else:
                offset += 1
        return tag_parts

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

    def _find_behavior_by_tag(self, tag_name: str):
        """FIXED: 按 tag 跨设备查找 —— 原实现只在 _default_device_id 一台设备里查，
        多设备部署时（如库里有历史 demo 设备）非默认设备的 tag 全部报 0x04
        "Path segment error"。优先默认设备，未命中再遍历其余设备。
        返回 (device_id, behavior)。"""
        default = self._default_device_id or ""
        bhv = self._behaviors.get(default)
        if bhv is not None:
            resolved = self._resolve_behavior_key(bhv, tag_name)
            if resolved in bhv._tags or resolved in bhv._data_types:
                return default, bhv
        for dev_id, b in self._behaviors.items():
            if dev_id == default:
                continue
            resolved = self._resolve_behavior_key(b, tag_name)
            if resolved in b._tags or resolved in b._data_types:
                return dev_id, b
        return default, bhv

    def _build_cip_read_response(self, cip_data: bytes) -> bytes:
        """构造裸 CIP Read Tag 响应（不含 EIP 封装）"""
        tag_value = 0
        data_type = "int32"
        tag_name = self._parse_cip_tag_path(cip_data)
        behavior = self._behaviors.get(self._default_device_id or "")
        # FIXED-P0: 支持 '@cpu' 探针标签 —— EdgeLite/上位机常用该标签做连接
        # 健康检查（约定读取控制器信息），返回设备名字符串
        if tag_name and tag_name.lower() in ("@cpu", "@identity"):
            device_name = str(getattr(self, '_start_config', {}).get("device_name", "ProtoForge-AB"))
            name_bytes = device_name.encode("utf-8")
            return bytes([0xCC, 0x00, 0x00, 0x00]) + struct.pack("<H", 0xD0) + struct.pack("<I", len(name_bytes)) + name_bytes
        if tag_name:
            device_id, behavior = self._find_behavior_by_tag(tag_name)
            if behavior is None:
                return bytes([0xCC, 0x00, 0x04, 0x00])
            tag_name = self._resolve_behavior_key(behavior, tag_name)
            # Bug 6 fix: _find_behavior_by_tag 已确认存在，直接取值
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
        device_id, behavior = (self._default_device_id or ""), self._behaviors.get(self._default_device_id or "")
        if tag_name:
            device_id, behavior = self._find_behavior_by_tag(tag_name)
        if tag_name and behavior:
            tag_name = self._resolve_behavior_key(behavior, tag_name)
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
                    # 通知引擎必须用 point 名（DeviceInstance._point_configs 的键）：
                    # tag 名（地址）传给 write_point 会被静默拒绝，设备侧 30 秒写入冻结
                    # 建不起来，引擎 tick 随即把 behavior 侧冻结当"已到期"清除，
                    # 外部下发值被生成器覆盖（联调实测）。
                    point_name = behavior._tag_reverse.get(tag_name, tag_name)
                    self._notify_engine_write(device_id, point_name, write_value)
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

    def _notify_engine_write(self, device_id: str, point_name: str, value: Any) -> None:
        """外部 CIP 写入后异步触发 _on_write 回调，传播到 DeviceInstance。"""
        if not self._on_write or not point_name or not device_id:
            return
        try:
            asyncio.create_task(self._fire_write_callback(device_id, point_name, value))
        except RuntimeError:
            pass

    async def _fire_write_callback(self, device_id: str, point_name: str, value: Any) -> None:
        try:
            await self._on_write(device_id, point_name, value)
        except Exception as e:
            logger.debug("AB external write callback error for %s.%s: %s", device_id, point_name, e)

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

    def _read_epath_class_instance(self, cip_data: bytes, start: int, end: int):
        """解析 padded EPath 中的 class/instance（逻辑段 + 符号段），失败返回 (None, None)"""
        cls = None
        inst = None
        off = start
        while off < end:
            b = cip_data[off]
            if b == 0x00:
                off += 1
                continue
            if b == 0x91:  # ANSI/Symbolic segment
                if off + 2 > end:
                    break
                ln = cip_data[off + 1]
                off += 2 + ln + (ln & 1)
                continue
            if (b & 0xE0) == 0x20:  # Logical segment
                fmt = b & 0x03
                size = (1, 2, 4)[fmt] if fmt < 3 else 1
                if off + 1 + size > end:
                    break
                val = int.from_bytes(cip_data[off + 1:off + 1 + size], "little")
                seg_type = (b >> 2) & 0x07
                if seg_type == 0:
                    cls = val
                elif seg_type == 1:
                    inst = val
                off += 1 + size
                if (1 + size) % 2 != 0:
                    off += 1  # padded EPath 补齐到偶数字节
                continue
            off += 1
        return cls, inst

    def _identity_attribute_values(self) -> dict[int, bytes]:
        """Identity Object (Class 0x01) 实例属性值（与 Get_Attributes_All 保持一致）"""
        config = getattr(self, '_start_config', {})
        device_name = str(config.get("device_name", "ProtoForge-AB"))
        name_bytes = device_name.encode("utf-8")[:230]
        return {
            1: struct.pack("<H", 1),           # Vendor ID
            2: struct.pack("<H", 14),          # Device Type: PLC
            3: struct.pack("<H", 1),           # Product Code
            4: bytes([1, 0]),                  # Revision 1.0
            5: struct.pack("<H", 0x0000),      # Status
            6: struct.pack("<I", 0x00000001),  # Serial Number
            7: bytes([len(name_bytes)]) + name_bytes,  # Product Name (SHORT_STRING)
        }

    def _handle_cip_get_attribute_list(self, session: int, cip_data: bytes,
                                       sender_context: bytes = bytes(8)) -> bytes:
        return self._wrap_cip_response(
            session, self._build_cip_get_attribute_list(cip_data), sender_context)

    def _build_cip_get_attribute_list(self, cip_data: bytes) -> bytes:
        """CIP Get_Attribute_List (0x03) —— Kepware 读设备身份用（裸 CIP 应答）

        请求: [0x03][PathSize][Path...][属性个数 UINT][属性ID UINT...]
        响应: [0x83][Status][属性个数 UINT][每项: 属性ID UINT][状态 UINT][值...]
        """
        path_end = self._get_path_end_offset(cip_data)
        cls, _inst = self._read_epath_class_instance(cip_data, 2, path_end)
        if cls != 0x01:
            # 仅支持 Identity Object，其余类按 "service not supported" 拒绝
            return self._make_bare_cip_error(0x03, 0x08)
        if path_end + 2 > len(cip_data):
            return self._make_bare_cip_error(0x03, 0x05)
        count = struct.unpack("<H", cip_data[path_end:path_end + 2])[0]
        if count == 0 or path_end + 2 + 2 * count > len(cip_data):
            return self._make_bare_cip_error(0x03, 0x05)
        attr_ids = [struct.unpack("<H", cip_data[path_end + 2 + 2 * i:path_end + 4 + 2 * i])[0]
                    for i in range(count)]
        values = self._identity_attribute_values()
        resp = bytearray()
        resp += bytes([0x83, 0x00, 0x00, 0x00])       # Reply service + Reserved + Status + AddStatusSize
        resp += struct.pack("<H", count)
        for aid in attr_ids:
            resp += struct.pack("<H", aid)
            if aid in values:
                resp += struct.pack("<H", 0x0000)  # attribute status: success
                resp += values[aid]
            else:
                resp += struct.pack("<H", 0x0014)  # attribute not gettable
        return bytes(resp)

    def _handle_cip_multiple_service(self, session: int, cip_data: bytes,
                                     sender_context: bytes = bytes(8)) -> bytes:
        return self._wrap_cip_response(
            session, self._build_cip_multiple_service(cip_data), sender_context)

    def _build_cip_multiple_service(self, cip_data: bytes) -> bytes:
        """CIP Multiple Service Packet (0x0A) —— Kepware 批量读写（裸 CIP 应答）

        请求: [0x0A][PathSize][Path...][服务数 UINT][偏移 UINT...][子请求数据区]
        响应: [0x8A][Status][服务数 UINT][偏移 UINT...][子应答数据区]

        FIXED-P0: 原实现末尾调用 _wrap_cip_response(session, ...) 但方法签名
        中没有 session/sender_context 参数，运行时直接 NameError 崩溃。
        同时 _handle_cip_multiple_service 和 _handle_send_unit_data 调用方
        都已做了 EIP 封装，_build_ 系列方法应只返回裸 CIP 数据。
        """
        path_end = self._get_path_end_offset(cip_data)
        if path_end + 2 > len(cip_data):
            return self._make_bare_cip_error(0x0A, 0x05)
        count = struct.unpack("<H", cip_data[path_end:path_end + 2])[0]
        offsets_start = path_end + 2
        data_start = offsets_start + 2 * count
        if count == 0 or data_start > len(cip_data):
            return self._make_bare_cip_error(0x0A, 0x05)
        offsets = [struct.unpack("<H", cip_data[offsets_start + 2 * i:offsets_start + 2 + 2 * i])[0]
                   for i in range(count)]
        replies: list[bytes] = []
        for i, off in enumerate(offsets):
            seg_start = data_start + off
            seg_end = data_start + offsets[i + 1] if i + 1 < count else len(cip_data)
            sub = cip_data[seg_start:seg_end] if seg_start <= seg_end <= len(cip_data) else b""
            if not sub:
                replies.append(self._make_bare_cip_error(0x0A, 0x08))
                continue
            svc = sub[0]
            if svc in (0x4C, 0x52):
                replies.append(self._build_cip_read_response(sub))
            elif svc in (0x4D, 0x53):
                replies.append(self._build_cip_write_response(sub))
            else:
                # 子服务不支持：标准 4 字节错误帧（原实现只有 2 字节，同样畸形）
                replies.append(self._make_bare_cip_error(svc, 0x08))
        data_area = b"".join(replies)
        resp = bytearray()
        resp += bytes([0x8A, 0x00, 0x00, 0x00])       # Service|0x80 + Reserved + Status + AddStatusSize
        resp += struct.pack("<H", count)
        rel = 0
        for r in replies:
            resp += struct.pack("<H", rel)
            rel += len(r)
        resp += data_area
        return bytes(resp)

    def _resolve_behavior_key(self, behavior, tag_name: str) -> str:
        """FIXED: tag 大小写不敏感匹配 —— Kepware 等客户端常将 tag 转为大写
        （如 PROGRAM:MAIN.CPULOAD），而点位 address 是 Program:Main.CpuLoad"""
        if tag_name in behavior._tags or tag_name in behavior._data_types:
            return tag_name
        lower = tag_name.lower()
        for k in behavior._tags:
            if k.lower() == lower:
                return k
        for k in behavior._data_types:
            if k.lower() == lower:
                return k
        return tag_name

    def _make_cip_error_response(self, session: int, service: int, error: int,
                                 sender_context: bytes = bytes(8)) -> bytes:
        return self._wrap_cip_response(
            session, self._make_bare_cip_error(service, error), sender_context)

    @staticmethod
    def _make_bare_cip_error(service: int, error: int) -> bytes:
        """FIXED: 标准 CIP 错误应答 = [服务|0x80][GeneralStatus 1字节][附加状态长度 UINT=0]，
        共 4 字节。原实现多出 4 字节零 + 错误码位置错误，共 7 字节畸形帧，
        Kepware 等严格客户端收到即报 "Frame received contains errors"。"""
        return bytes([(service | 0x80) & 0xFF, error & 0xFF]) + struct.pack("<H", 0)

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
