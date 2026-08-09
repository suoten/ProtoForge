"""S7 协议服务器实现.

本模块实现了 Siemens S7 通信协议的仿真服务器，
支持以下功能:
    - S7 CPU 连接与机架/槽位握手
    - DB (Data Block) 读写
    - I/Q/M/T/C 区域数据访问
    - 多变量读取 (Read Var)
    - 周期性数据交换

支持与以下真实网关对接:
    - Siemens S7-300/400/1200/1500 PLC
    - DeltaTec S7 网关
    - Anybus S7 网关
    - 任何标准 S7 客户端

协议规范:
    - ISO-on-TCP (RFC 1006) 传输层
    - S7 通信层 (COTP + S7 协议)
    - TSAP 寻址 (本地/远程)

典型用法::

    server = S7Server()
    await server.start({"host": "0.0.0.0", "port": 102})
    device_id = await server.create_device(device_config)
"""

import asyncio
import logging
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from protoforge.core.messages import desc, msg
from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)


@dataclass
class S7ConnectionState:
    """S7 连接状态 — 记录 PDU 协商结果."""

    pdu_size: int = 480
    max_amq_caller: int = 8
    max_amq_callee: int = 8
    setup_completed: bool = False


class S7DeviceBehavior(StandardDeviceBehavior):  # FIXED: 继承StandardDeviceBehavior，复用_points/_values/_generators初始化
    S7_AREA_DB = 0x84
    S7_AREA_INPUTS = 0x81
    S7_AREA_OUTPUTS = 0x82
    S7_AREA_MARKERS = 0x83
    S7_AREA_TIMERS = 0x1D
    S7_AREA_COUNTERS = 0x1C

    def __init__(self, points: list | None = None, db_header_size: int = 0):
        super().__init__(points)  # FIXED: 调用super().__init__()初始化_points/_values/_generators
        self._db_data: dict[int, bytearray] = {1: bytearray(1024)}
        self._marker_data: bytearray = bytearray(256)
        self._input_data: bytearray = bytearray(256)
        self._output_data: bytearray = bytearray(256)
        self._timer_data: bytearray = bytearray(512)  # FIXED-P1: Timer区域内存
        self._counter_data: bytearray = bytearray(512)  # FIXED-P1: Counter区域内存
        self._area_lock = threading.Lock()  # FIXED-C03: 保护Timer/Counter区域的并发读写
        # 存储点位的 (area, db_number, offset) 三元组，支持 I/Q/M/DB/T/C 全区域
        self._point_addresses: dict[str, tuple[int, int, int]] = {}
        # FIX: S7-1200/1500 优化块访问时，DB 数据区开头有 2 字节系统头
        # 真实设备上用户变量从 byte 2 开始，ProtoForge 模板地址从 byte 0 开始
        # 解决方案：解析模板地址时加 db_header_size，使内部偏移与真实设备一致
        self._db_header_size = db_header_size
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                address = getattr(p, 'address', '0') or '0'
                area, db_number, offset = self._parse_s7_address(str(address), self._db_header_size)
                self._point_addresses[name] = (area, db_number, offset)
                if name in self._values:
                    self._sync_value_to_area(name, self._values[name])

    @staticmethod
    def _parse_s7_address(address: str, db_header_size: int = 0) -> tuple[int, int, int]:
        """解析 S7 地址字符串，返回 (area_code, db_number, byte_offset)。

        支持的地址格式:
          DB 区域:
            DB1.DBD0   - DB1 的双字(byte 0-3)
            DB1.DBW2   - DB1 的字(byte 2-3)
            DB1.DBB4   - DB1 的字节(byte 4)
            DB1.DBX0.0 - DB1 的位(byte 0, bit 0)
            DB2.DBD10  - DB2 的双字(byte 10-13)
          M 区域(标记位/中间存储器):
            M0.0       - 位(byte 0, bit 0)
            MB0        - 字节(byte 0)
            MW2        - 字(byte 2-3)
            MD4        - 双字(byte 4-7)
          I 区域(输入):
            I0.0       - 位
            IB0        - 字节
            IW0        - 字
            ID4        - 双字
          Q 区域(输出):
            Q0.0       - 位
            QB0        - 字节
            QW0        - 字
            QD4        - 双字
          T 区域(定时器):
            T1         - 定时器 1
          C 区域(计数器):
            C1         - 计数器 1

        Args:
            address: S7 地址字符串
            db_header_size: 优化块访问时的 DB 头偏移(仅影响 DB 区域)

        Returns:
            (area_code, db_number, byte_offset) 三元组
            area_code: 0x84=DB, 0x83=M, 0x81=I, 0x82=Q, 0x1D=T, 0x1C=C
            db_number: DB 号(非 DB 区域为 0)
            byte_offset: 字节偏移量
        """
        try:
            addr_upper = address.upper().replace(' ', '')

            # --- DB 区域 ---
            if addr_upper.startswith('DB'):
                parts = addr_upper.split('.')
                db_number = int(parts[0].replace('DB', '') or '1')
                if len(parts) >= 2:
                    offset_part = parts[1]
                    if offset_part.startswith('DBD') or offset_part.startswith('DBW'):
                        offset = int(offset_part[3:] or '0')
                    elif offset_part.startswith('DBX'):
                        byte_bit = offset_part[3:]
                        if '.' in byte_bit:
                            byte_str, _ = byte_bit.split('.')
                            offset = int(byte_str or '0')
                        else:
                            offset = int(byte_bit or '0')
                    elif offset_part.startswith('DBB'):
                        offset = int(offset_part[3:] or '0')
                    else:
                        offset = int(''.join(c for c in offset_part if c.isdigit()) or '0')
                    # FIX: 优化块访问时，用户变量在真实设备上偏移 +db_header_size
                    offset += db_header_size
                    return (S7DeviceBehavior.S7_AREA_DB, db_number, offset)
                # DB 号但无偏移
                return (S7DeviceBehavior.S7_AREA_DB, db_number, db_header_size)

            # --- M 区域(标记位/中间存储器) ---
            # 格式: M0.0, MB0, MW2, MD4
            if addr_upper.startswith('M'):
                if len(addr_upper) > 1 and addr_upper[1] == 'B':
                    # MB0 - 字节
                    offset = int(addr_upper[2:] or '0')
                elif len(addr_upper) > 1 and addr_upper[1] == 'W':
                    # MW2 - 字
                    offset = int(addr_upper[2:] or '0')
                elif len(addr_upper) > 1 and addr_upper[1] == 'D':
                    # MD4 - 双字
                    offset = int(addr_upper[2:] or '0')
                else:
                    # M0.0 - 位
                    rest = addr_upper[1:]
                    if '.' in rest:
                        byte_str, _ = rest.split('.')
                        offset = int(byte_str or '0')
                    else:
                        offset = int(rest or '0')
                return (S7DeviceBehavior.S7_AREA_MARKERS, 0, offset)

            # --- I 区域(输入) ---
            # 格式: I0.0, IB0, IW0, ID4
            if addr_upper.startswith('I') or addr_upper.startswith('E'):
                # S7 中 E(德语 Eingang) = I(英语 Input)
                prefix = addr_upper[0]
                rest = addr_upper[1:]
                if rest.startswith('B'):
                    offset = int(rest[1:] or '0')
                elif rest.startswith('W'):
                    offset = int(rest[1:] or '0')
                elif rest.startswith('D'):
                    offset = int(rest[1:] or '0')
                elif '.' in rest:
                    byte_str, _ = rest.split('.')
                    offset = int(byte_str or '0')
                else:
                    offset = int(rest or '0')
                return (S7DeviceBehavior.S7_AREA_INPUTS, 0, offset)

            # --- Q 区域(输出) ---
            # 格式: Q0.0, QB0, QW0, QD4
            # S7 中 A(德语 Ausgang) = Q(英语 Output)
            if addr_upper.startswith('Q') or addr_upper.startswith('A'):
                rest = addr_upper[1:]
                if rest.startswith('B'):
                    offset = int(rest[1:] or '0')
                elif rest.startswith('W'):
                    offset = int(rest[1:] or '0')
                elif rest.startswith('D'):
                    offset = int(rest[1:] or '0')
                elif '.' in rest:
                    byte_str, _ = rest.split('.')
                    offset = int(byte_str or '0')
                else:
                    offset = int(rest or '0')
                return (S7DeviceBehavior.S7_AREA_OUTPUTS, 0, offset)

            # --- T 区域(定时器) ---
            # 格式: T1, T2, ...
            if addr_upper.startswith('T'):
                timer_num = int(addr_upper[1:] or '0')
                return (S7DeviceBehavior.S7_AREA_TIMERS, 0, timer_num)

            # --- C 区域(计数器) ---
            # 格式: C1, C2, ...
            # 注意: S7 中 Z(德语 Zähler) = C(英语 Counter)
            if addr_upper.startswith('C') or addr_upper.startswith('Z'):
                counter_num = int(addr_upper[1:] or '0')
                return (S7DeviceBehavior.S7_AREA_COUNTERS, 0, counter_num)

            # 无法识别的格式，默认到 DB1 offset 0
            logger.warning("S7 address '%s' not recognized, defaulting to DB1 offset 0", address)
            return (S7DeviceBehavior.S7_AREA_DB, 1, db_header_size)
        except (ValueError, IndexError) as e:
            logger.warning("S7 address parse failed for '%s': %s, defaulting to DB1 offset 0", address, e)
            return (S7DeviceBehavior.S7_AREA_DB, 1, db_header_size)

    def _sync_value_to_area(self, point_name: str, value: Any) -> None:
        """将点位值同步到对应的 S7 数据区域(DB/M/I/Q/T/C)。"""
        if point_name not in self._point_addresses:
            return
        area, db_number, offset = self._point_addresses[point_name]
        try:
            point = self._points.get(point_name)
            dt = str(point.data_type) if point and hasattr(point, 'data_type') else ""
            if dt in ("float32",) or (not dt and isinstance(value, float)):
                data = struct.pack(">f", float(value))  # S7 uses big-endian (Motorola)
            elif dt in ("float64",):
                data = struct.pack(">d", float(value))
            elif dt in ("int16",):
                data = struct.pack(">h", int(value))
            elif dt in ("uint16",):
                data = struct.pack(">H", int(value) & 0xFFFF)
            elif dt in ("int32", "dint"):
                data = struct.pack(">i", int(value))
            elif dt in ("uint32",):
                data = struct.pack(">I", int(value) & 0xFFFFFFFF)
            elif dt in ("string",) or isinstance(value, str):
                encoded = str(value).encode("utf-8")
                data = bytes([254, min(len(encoded), 254)]) + encoded[:254]
            elif isinstance(value, bool):
                data = struct.pack("<?", value)
            else:
                data = struct.pack(">i", int(value))
            # 根据 area 写入对应的数据区域
            if area == self.S7_AREA_DB:
                self.write_db_area(db_number, offset, data)
            else:
                self.write_area(area, db_number, offset, data)
        except (ValueError, TypeError, struct.error) as e:
            logger.warning("S7 on_write value conversion error for %s: %s", point_name, e)

    # 向后兼容: 保留旧方法名
    _sync_value_to_db = _sync_value_to_area

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._written_values[point_name] = value
            self._sync_value_to_area(point_name, value)
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._sync_value_to_area(point_name, value)

    def get_db_area(self, db_number: int, size: int) -> bytearray:
        if db_number not in self._db_data:
            self._db_data[db_number] = bytearray(max(size, 1024))
        elif len(self._db_data[db_number]) < size:
            self._db_data[db_number].extend(bytearray(max(size, 1024) - len(self._db_data[db_number])))
        return self._db_data[db_number]

    def write_db_area(self, db_number: int, offset: int, data: bytes) -> None:
        if db_number not in self._db_data:
            self._db_data[db_number] = bytearray(1024)
        buf = self._db_data[db_number]
        end = offset + len(data)
        if end > len(buf):
            buf.extend(bytearray(end - len(buf)))
        buf[offset:offset + len(data)] = data

    def read_area(self, area: int, db_number: int, offset: int, size: int) -> bytes:
        if area == self.S7_AREA_DB:
            buf = self.get_db_area(db_number, offset + size)
            return bytes(buf[offset:offset + size])
        elif area == self.S7_AREA_MARKERS:
            end = min(offset + size, len(self._marker_data))
            return bytes(self._marker_data[offset:end])
        elif area == self.S7_AREA_INPUTS:
            end = min(offset + size, len(self._input_data))
            return bytes(self._input_data[offset:end])
        elif area == self.S7_AREA_OUTPUTS:
            end = min(offset + size, len(self._output_data))
            return bytes(self._output_data[offset:end])
        elif area == self.S7_AREA_TIMERS:  # FIXED-P1: Timer区域读取
            with self._area_lock:  # FIXED-C03: 加锁保护并发扩展
                buf = self._timer_data
                if offset + size > len(buf):
                    buf.extend(bytearray(offset + size - len(buf)))
                return bytes(buf[offset:offset + size])
        elif area == self.S7_AREA_COUNTERS:  # FIXED-P1: Counter区域读取
            with self._area_lock:  # FIXED-C03: 加锁保护并发扩展
                buf = self._counter_data
                if offset + size > len(buf):
                    buf.extend(bytearray(offset + size - len(buf)))
                return bytes(buf[offset:offset + size])
        return b"\x00" * size

    def write_area(self, area: int, db_number: int, offset: int, data: bytes) -> None:
        if area == self.S7_AREA_DB:
            self.write_db_area(db_number, offset, data)
        elif area == self.S7_AREA_MARKERS:
            end = offset + len(data)
            if end > len(self._marker_data):
                self._marker_data.extend(bytearray(end - len(self._marker_data)))
            self._marker_data[offset:offset + len(data)] = data
        elif area == self.S7_AREA_INPUTS:
            end = offset + len(data)
            if end > len(self._input_data):
                self._input_data.extend(bytearray(end - len(self._input_data)))
            self._input_data[offset:offset + len(data)] = data
        elif area == self.S7_AREA_OUTPUTS:
            end = offset + len(data)
            if end > len(self._output_data):
                self._output_data.extend(bytearray(end - len(self._output_data)))
            self._output_data[offset:offset + len(data)] = data
        elif area == self.S7_AREA_TIMERS:  # FIXED-P1: Timer区域写入
            with self._area_lock:  # FIXED-C03: 加锁保护并发扩展
                end = offset + len(data)
                if end > len(self._timer_data):
                    self._timer_data.extend(bytearray(end - len(self._timer_data)))
                self._timer_data[offset:offset + len(data)] = data
        elif area == self.S7_AREA_COUNTERS:  # FIXED-P1: Counter区域写入
            with self._area_lock:  # FIXED-C03: 加锁保护并发扩展
                end = offset + len(data)
                if end > len(self._counter_data):
                    self._counter_data.extend(bytearray(end - len(self._counter_data)))
                self._counter_data[offset:offset + len(data)] = data


class S7Server(ProtocolServer):
    protocol_name = "s7"
    protocol_display_name = "Siemens S7"

    _DEFAULT_PDU_SIZE = 480
    _MIN_PDU_SIZE = 128
    _MAX_PDU_SIZE = 960
    _DEFAULT_AMQ = 8
    _MAX_AMQ = 64
    _CONNECTION_TIMEOUT = 30  # 与modbus保持一致

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, S7DeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_info: dict[str, dict] = {}
        self._rack_slot_map: dict[tuple[int, int], str] = {}
        self._behaviors_sync_lock = threading.Lock()
        self._host = "0.0.0.0"
        self._port = 102
        self._requested_port = 102
        self._rack = 0
        self._slot = 1
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    @property
    def actual_port(self) -> int:
        """返回协议服务器实际监听的端口"""
        return self._port

    @property
    def requested_port(self) -> int:
        """返回用户配置的端口"""
        return self._requested_port

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._requested_port = config.get("port", 102)
        self._validate_port(self._requested_port)
        self._port = self._requested_port
        self._rack = config.get("rack", 0)
        if not isinstance(self._rack, int) or self._rack < 0 or self._rack > 7:
            raise ValueError(f"S7 rack must be between 0 and 7 (got {self._rack})")
        self._slot = config.get("slot", 1)
        if not isinstance(self._slot, int) or self._slot < 0 or self._slot > 31:
            raise ValueError(f"S7 slot must be between 0 and 31 (got {self._slot})")
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("S7 server started on %s:%d (rack=%d, slot=%d)",
                         self._host, self._port, self._rack, self._slot)
            self._log_debug("system", "server_start",
                            msg("s7", "service_started", host=self._host, port=self._port),
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start S7 server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("S7 task cancelled")
        except Exception as e:
            logger.warning("S7 server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("S7 server stopped")
            self._log_debug("system", "server_stop", msg("s7", "service_stopped"))

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("S7 server task cancelled")
        except Exception as e:
            logger.exception("S7 server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.info("S7 connection from %s", addr)
        connection_device_id: str | None = None
        try:
            while self._server_running:
                try:
                    tpkt_header = await asyncio.wait_for(reader.readexactly(4), timeout=self._CONNECTION_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                if len(tpkt_header) < 4:
                    break
                if tpkt_header[0] != 0x03:
                    break
                tpkt_len = struct.unpack(">H", tpkt_header[2:4])[0]
                remaining = tpkt_len - 4
                if remaining < 0 or remaining > 65535 - 4:  # FIXED-N02: TPKT长度域校验，防止0或超大值导致异常
                    break
                if remaining > 0:
                    payload = await reader.readexactly(remaining)
                    data = tpkt_header + payload
                else:
                    data = tpkt_header
                response, device_id = self._process_s7_message(data, connection_device_id)
                if device_id is not None:
                    connection_device_id = device_id
                if response:
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError, asyncio.IncompleteReadError, asyncio.TimeoutError, BrokenPipeError, ConnectionAbortedError):
            logger.debug("S7 connection closed: %s", addr)
        except Exception as e:  # FIXED-P1: 兜底捕获所有其他异常，避免单个帧处理错误导致整个连接崩溃
            logger.exception("S7 connection handler unexpected error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("S7 writer close error: %s", e)

    def _process_s7_message(self, data: bytes, device_id: str | None = None) -> tuple[bytes | None, str | None]:
        if len(data) < 4:
            return None, None

        tpkt_len = struct.unpack(">H", data[2:4])[0]
        if len(data) < tpkt_len:
            return None, None

        if len(data) < 10:
            return None, None

        pdu_type = data[5]  # FIXED-P0: data[4]是COTP LI字段，data[5]才是PDU Type
        if pdu_type == 0xE0:  # FIXED-P0: COTP CR(Connection Request)类型码为0xE0，非0xF0(DT)
            cotp_len = data[4]  # FIXED-P0: COTP LI(长度指示)在data[4]，非data[5]
            # FIXED-P0: LI值表示从PDU Type到COTP末尾的长度，总包长=TPKT(4)+LI字节(1)+LI值
            # 原代码 7+cotp_len 对22字节的COTP CR报文(22<24)误判为长度不足，导致所有连接被丢弃
            if len(data) < 5 + cotp_len:
                return None, None
            resolved_id = self._resolve_device_from_cotp(data)
            # Ensure device is registered before COTP CR response, so it's ready for S7 Setup
            if resolved_id and resolved_id not in self._behaviors:
                device_config = self._device_configs.get(resolved_id)
                if device_config:
                    with self._behaviors_sync_lock:
                        if resolved_id not in self._behaviors:
                            pc = device_config.protocol_config or {}
                            db_hdr = 2 if pc.get("optimized_db", False) else 0
                            self._behaviors[resolved_id] = S7DeviceBehavior(device_config.points, db_header_size=db_hdr)
                            logger.debug("S7 pre-registered device from COTP CR: %s", resolved_id)
            return self._make_cotp_cr_response(data), resolved_id

        if len(data) < 17:
            return None, None

        # S7 Job 请求分发：基于功能码(data[17])而非消息类型(data[8])
        # S7 协议中所有 Job 请求的 msg_type 都是 0x01，功能码在参数区首字节
        # TPKT(4) + COTP DT(3) + S7 Header(10) = 17，所以 data[17] 是功能码
        msg_type = data[8]
        if msg_type == 0x01:  # Job 请求
            func_code = data[17] if len(data) > 17 else 0
            if func_code == 0xF0:      # Setup Communication
                return self._make_s7_connect_response(data), None
            elif func_code == 0x04:    # Read Var
                return self._make_s7_read_response(data, device_id), None
            elif func_code == 0x05:    # Write Var
                return self._make_s7_write_response(data, device_id), None
            elif func_code == 0x28:    # Start PLC (Hot Start)
                return self._make_s7_plc_control_response(data, device_id, start=True), None
            elif func_code == 0x29:    # Stop PLC
                return self._make_s7_plc_control_response(data, device_id, start=False), None
            else:
                return self._make_s7_error_response(data), None
        elif msg_type == 0x07:  # User Data (SZL/编程/调试功能)
            # FIXED-P0: snap7 的 read_szl/get_cpu_info 使用 USER_DATA(0x07) 而非 Read Var(0x04)
            # USER_DATA 参数结构: Reserved(1) + ParamCount(1) + TypeLenHeader(2) + Method(1) + TypeGroup(1) + SubFunc(1) + DataRef(1)
            # data[17] = Reserved, data[18] = ParamCount, data[19] = 0x12, data[20] = length
            # data[21] = Method, data[22] = Type|Group, data[23] = SubFunction, data[24] = DataRef
            if len(data) > 23:
                data[21]
                type_group = data[22]
                sub_func = data[23]
                group = type_group & 0x0F
                # Group 4 = SZL, SubFunction 1 = READ_SZL
                if group == 0x04 and sub_func == 0x01 or group == 0x04:
                    return self._make_s7_szl_response(data, device_id), None
            # PLC Control via User Data
            if len(data) > 17:
                func_code = data[17]
                if func_code == 0x28:
                    return self._make_s7_plc_control_response(data, device_id, start=True), None
                elif func_code == 0x29:
                    return self._make_s7_plc_control_response(data, device_id, start=False), None
            return self._make_s7_error_response(data), None

        return None, None

    def _make_cotp_cr_response(self, data: bytes = b"") -> bytes:
        """构建 COTP Connection Confirm 响应，回显请求中的 TSAP 参数。"""
        # 尝试从请求中提取 TSAP 参数，用于正确回显
        local_tsap = b"\x01\x00"   # 默认本地 TSAP
        remote_tsap = b"\x01\x02"  # 默认远程 TSAP
        try:
            offset = 11
            while offset + 1 < len(data):
                param_code = data[offset]
                param_len = data[offset + 1]
                if offset + 2 + param_len > len(data):
                    break
                if param_code == 0xC1 and param_len >= 2:
                    remote_tsap = data[offset + 2:offset + 2 + min(param_len, 2)]
                elif param_code == 0xC2 and param_len >= 2:
                    local_tsap = data[offset + 2:offset + 2 + min(param_len, 2)]
                offset += 2 + param_len
        except (IndexError, struct.error):
            pass

        # FIX: COTP CC 响应应正确回显 TSAP，不应交换
        # CR 请求: 0xC1=Called TSAP(服务器), 0xC2=Calling TSAP(客户端)
        # CC 响应: 0xC1=Called TSAP(回显服务器TSAP=remote_tsap), 0xC2=Calling TSAP(回显客户端TSAP=local_tsap)
        tsap_payload = bytes([
            0xC1, len(remote_tsap),   # Called TSAP = 服务器 TSAP (来自 CR 的 0xC1)
        ]) + remote_tsap + bytes([
            0xC2, len(local_tsap),    # Calling TSAP = 客户端 TSAP (来自 CR 的 0xC2)
        ]) + local_tsap + bytes([
            0xC0, 0x01, 0x07,       # TPDU size = 0x07 (2048)
        ])

        cotp_len = 2 + len(tsap_payload)  # 2 bytes for header (0xD0 + dst-ref high)
        tpkt_len = 4 + 1 + cotp_len + len(tsap_payload)
        # 重新计算：TPKT(4) + COTP header(1+2+2) + payload
        # COTP CC header: LI(1) + 0xD0(1) + dst-ref(2) + src-ref(2) + class(1) = 7
        cotp_header_len = 1 + 1 + 2 + 2 + 1  # LI + PDU Type + dst-ref + src-ref + class = 7
        cotp_len = cotp_header_len - 1 + len(tsap_payload)  # LI值 = 从PDU Type到COTP末尾的长度
        cotp_header = bytes([
            cotp_len & 0xFF,  # FIXED-P0: LI动态计算，COTP CC header(6) + tsap_payload
            0xD0,   # FIXED-P0: COTP CC(Connection Confirm)类型码为0xD0，非0x0D
            0x00, 0x01,  # Destination reference (echoed from request)
            0x00, 0x01,  # Source reference
            0x00,        # Class 0
        ])
        payload = cotp_header + tsap_payload
        tpkt_len = 4 + len(payload)

        return bytes([
            0x03, 0x00,
            (tpkt_len >> 8) & 0xFF, tpkt_len & 0xFF,
        ]) + payload

    def _resolve_device_from_cotp(self, data: bytes) -> str | None:
        try:
            offset = 11
            while offset + 1 < len(data):
                param_code = data[offset]
                param_len = data[offset + 1]
                if offset + 2 + param_len > len(data):
                    break
                # 0xC2 = Called TSAP: contains the target rack/slot (server side)
                # 0xC1 = Calling TSAP: contains the client's source TSAP
                # snap7 and other S7 clients encode rack/slot in Called TSAP (0xC2)
                if param_code == 0xC2 and param_len >= 2:
                    tsap = struct.unpack(">H", data[offset + 2:offset + 4])[0]
                    tsap_low = tsap & 0xFF
                    rack = (tsap_low >> 5) & 0x07
                    slot = tsap_low & 0x1F
                    device_id = self._rack_slot_map.get((rack, slot))
                    if device_id:
                        logger.debug("S7 COTP CR resolved rack=%d slot=%d -> device %s",
                                     rack, slot, device_id)
                        return device_id
                    return self._default_device_id
                offset += 2 + param_len
        except (IndexError, struct.error) as e:
            logger.debug("S7 COTP CR parse error: %s", e)
        return self._default_device_id

    def _make_s7_connect_response(self, data: bytes, conn_state: S7ConnectionState | None = None) -> bytes:
        pdu_size_req = self._DEFAULT_PDU_SIZE
        max_amq_caller = self._DEFAULT_AMQ
        max_amq_callee = self._DEFAULT_AMQ
        try:
            s7_offset = 0
            for i in range(len(data) - 1):
                if data[i] == 0x32 and data[i + 1] in (0x01, 0x03):
                    s7_offset = i
                    break
            if s7_offset > 0 and len(data) > s7_offset + 14:
                param_start = s7_offset + 10  # S7 header = 10 bytes (Job类型无Error Class/Code)
                if data[param_start] == 0xF0 and len(data) > param_start + 5:
                    # Setup Communication参数: Function(1) + Reserved(1) + AMQ Calling(2) + AMQ Called(2) + PDU Size(2)
                    max_amq_caller = struct.unpack(">H", data[param_start + 2:param_start + 4])[0] or self._DEFAULT_AMQ
                    max_amq_callee = struct.unpack(">H", data[param_start + 4:param_start + 6])[0] or self._DEFAULT_AMQ
                    pdu_size_req = struct.unpack(">H", data[param_start + 6:param_start + 8])[0]
        except Exception as e:
            logger.debug("S7 connect param parse error: %s", e)
        pdu_size = min(max(pdu_size_req, self._MIN_PDU_SIZE), self._MAX_PDU_SIZE)
        max_amq_caller = min(max(max_amq_caller, 1), self._MAX_AMQ)
        max_amq_callee = min(max(max_amq_callee, 1), self._MAX_AMQ)
        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,  # TPKT (length updated below)
            0x02, 0xF0, 0x80,        # COTP DT
            0x32, 0x03,               # S7 Protocol ID, Msg Type = Ack Data
            0x00, 0x00,               # Reserved
        ])
        resp += data[11:13]  # PDU Reference (echo from request) - FIXED: 偏移11非10
        resp += struct.pack(">H", 0x0008)  # Parameter Length = 8
        resp += struct.pack(">H", 0x0000)  # Data Length = 0
        resp += bytes([0x00, 0x00])  # Error Class = 0, Error Code = 0
        resp += bytes([0xF0, 0x00])  # Function = Setup Communication, Reserved
        resp += struct.pack(">H", max_amq_caller)  # FIXED: AMQ Calling在PDU Size之前
        resp += struct.pack(">H", max_amq_callee)  # FIXED: AMQ Called在PDU Size之前
        resp += struct.pack(">H", pdu_size)         # FIXED: PDU Size在最后
        resp[2:4] = struct.pack(">H", len(resp))   # Dynamic TPKT length

        # 如果提供了 conn_state，存储协商结果
        if conn_state is not None:
            conn_state.pdu_size = pdu_size
            conn_state.max_amq_caller = max_amq_caller
            conn_state.max_amq_callee = max_amq_callee
            conn_state.setup_completed = True

        return bytes(resp)

    def _make_s7_read_response(self, data: bytes, device_id: str | None = None) -> bytes:
        if len(data) < 20:
            return self._make_s7_error_response(data)

        # FIXED: param_start=17 (TPKT(4)+COTP DT(3)+S7 Header(10))
        # S7 Job 请求结构: TPKT(4) + COTP DT(3) + S7 Header(10) + Parameters
        # Parameters: Function(1) + Reserved(1) + Item Count(1) + Items(N*12)
        param_start = 17
        if len(data) <= param_start + 2:
            return self._make_s7_error_response(data)

        func_code = data[param_start]  # 0x04 = Read Var
        if func_code != 0x04:
            return self._make_s7_error_response(data)

        # FIXED-P0: Read Var 参数格式 = Function(1) + ItemCount(1) + Items(N*12)
        # 没有 reserved 字节！data[param_start+1] 就是 ItemCount
        item_count = data[param_start + 1] if len(data) > param_start + 1 else 0
        if item_count == 0:  # FIXED-N04: item_count=0时返回S7错误而非默认为1
            return self._make_s7_error_response(data)

        item_offset = param_start + 2  # FIXED-P0: Items 从 param_start+2 开始
        item_results = []

        for _i in range(item_count):
            if item_offset + 12 > len(data):
                item_results.append((0x0A, b"\x00"))
                continue

            item_spec = data[item_offset:item_offset + 12]
            item_offset += 12

            # FIXED-P0: S7 Read Var Item 结构 (12 bytes):
            # [0]  Spec type (0x12)
            # [1]  Length of following (0x0A)
            # [2]  Syntax ID (0x10)
            # [3]  Transport size (0x02=byte, 0x04=byte/word, 0x09=bool)
            # [4:6] Number of elements
            # [6:8] DB Number (big-endian uint16, 0 for non-DB areas)
            # [8]  Area code (0x84=DB, 0x81=I, 0x82=Q, 0x83=M)
            # [9:12] Address (3 bytes, bit address = byte_offset * 8 + bit_number)
            spec_type = item_spec[0]
            if spec_type != 0x12:
                item_results.append((0x0A, b"\x00"))
                continue

            transport_size_code = item_spec[3]
            length = struct.unpack(">H", item_spec[4:6])[0]
            db_number = struct.unpack(">H", item_spec[6:8])[0]  # FIXED-P0: DB Number 在偏移6:8
            area = item_spec[8]  # FIXED-P0: Area 在偏移8，DB Number 之后
            full_addr = (item_spec[9] << 16) | (item_spec[10] << 8) | item_spec[11]
            offset = full_addr >> 3
            full_addr & 0x07

            read_size = (length + 7) // 8 if transport_size_code == 9 else length

            if read_size <= 0:
                read_size = 1
            if read_size > 65535:
                read_size = 65535

            value_bytes = b"\x00" * read_size
            behavior = self._behaviors.get(device_id or self._default_device_id or "")
            if behavior:
                value_bytes = behavior.read_area(area, db_number, offset, read_size)

            item_results.append((0xFF, value_bytes))

        data_len = 0
        for _result_code, val_bytes in item_results:
            data_len += 1 + 1 + 2 + len(val_bytes)
            if len(val_bytes) % 2 != 0:
                data_len += 1

        # FIXED-P0: Read Response 参数区 = Function(1) + ItemCount(1) = 2 字节
        # 返回码在 data section 中，不在 parameter section 中
        param_len = 2
        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
            0x00, 0x00,               # Reserved字段
        ])
        resp += data[11:13]            # PDU Reference偏移11
        resp += struct.pack(">H", param_len)
        resp += struct.pack(">H", data_len)
        resp += bytes([0x00, 0x00])    # Error Class=0, Error Code=0

        # Parameter section: Function(1) + ItemCount(1)
        resp += bytes([0x04])
        resp += bytes([item_count])

        # Data section: each item = ReturnCode(1) + TransportSize(1) + Length(2) + Data(N) + Padding
        for result_code, val_bytes in item_results:
            resp += bytes([result_code])
            if result_code != 0xFF:
                resp += bytes([0x00])
                resp += struct.pack(">H", 0)
            else:
                # FIXED-P0: transport_size=0x04 时 Length 是位数(bit count)，snap7 用 length//8 计算字节数
                transport_size = 0x09 if len(val_bytes) <= 1 else 0x04
                if transport_size == 0x04:
                    resp += bytes([transport_size])
                    resp += struct.pack(">H", len(val_bytes) * 8)  # 位数
                else:
                    resp += bytes([transport_size])
                    resp += struct.pack(">H", len(val_bytes))  # 字节数
                resp += val_bytes
                if len(val_bytes) % 2 != 0:
                    resp += bytes([0x00])

        resp[2:4] = struct.pack(">H", len(resp))
        return bytes(resp)

    def _make_s7_write_response(self, data: bytes, device_id: str | None = None) -> bytes:
        if len(data) < 20:
            return self._make_s7_error_response(data)

        # FIXED: param_start=17 (TPKT(4)+COTP DT(3)+S7 Header(10))
        param_start = 17
        data[param_start] if len(data) > param_start else 0x05
        # FIXED-P0: Write Var 参数格式 = Function(1) + ItemCount(1) + Items(N*12)
        item_count = data[param_start + 1] if len(data) > param_start + 1 else 0
        if item_count == 0:  # FIXED-N16: Write item_count=0时返回S7错误
            return self._make_s7_error_response(data)

        item_offset = param_start + 2  # FIXED-P0: Items 从 param_start+2 开始
        result_codes = []

        # FIXED-N15: 在循环外预先解析所有写入项数据，避免O(n²)和id()复用风险
        data_section_start = param_start + 2 + item_count * 12
        write_data_list = []
        ptr = data_section_start
        for _ in range(item_count):
            if ptr + 4 > len(data):
                write_data_list.append(b"")
                break
            ts = data[ptr + 1]
            raw_len = struct.unpack(">H", data[ptr + 2:ptr + 4])[0]
            dlen = raw_len // 8 if ts == 0x04 else raw_len
            if ptr + 4 + dlen <= len(data):
                write_data_list.append(data[ptr + 4:ptr + 4 + dlen])
            else:
                write_data_list.append(b"")
            ptr += 4 + dlen
            if dlen % 2 != 0:
                ptr += 1

        for i in range(item_count):
            if item_offset + 12 > len(data):
                result_codes.append(0x0A)
                continue

            item_spec = data[item_offset:item_offset + 12]
            item_offset += 12

            spec_type = item_spec[0]
            if spec_type != 0x12:
                result_codes.append(0x0A)
                continue

            db_number = struct.unpack(">H", item_spec[6:8])[0]  # FIXED-P0: DB Number 在偏移6:8
            area = item_spec[8]  # FIXED-P0: Area 在偏移8
            full_addr = (item_spec[9] << 16) | (item_spec[10] << 8) | item_spec[11]
            offset = full_addr >> 3
            full_addr & 0x07

            write_data = write_data_list[i] if i < len(write_data_list) else b""

            behavior = self._behaviors.get(device_id or self._default_device_id or "")
            if behavior:
                behavior.write_area(area, db_number, offset, write_data)
                for name, (p_area, p_db, p_offset) in behavior._point_addresses.items():
                    if area == p_area and (area != behavior.S7_AREA_DB or db_number == p_db) and offset == p_offset:
                        try:
                            pt = behavior._points.get(name)
                            dt = str(pt.data_type) if pt and hasattr(pt, 'data_type') else ""
                            if dt in ("float32",):
                                behavior._values[name] = struct.unpack(">f", write_data[:4])[0]  # S7 big-endian
                            elif dt in ("float64",):
                                behavior._values[name] = struct.unpack(">d", write_data[:8])[0]
                            elif dt in ("int16",):
                                behavior._values[name] = struct.unpack(">h", write_data[:2])[0]
                            elif dt in ("uint16",):
                                behavior._values[name] = struct.unpack(">H", write_data[:2])[0]
                            elif dt in ("int32", "dint"):
                                behavior._values[name] = struct.unpack(">i", write_data[:4])[0]
                            elif dt in ("uint32",):
                                behavior._values[name] = struct.unpack(">I", write_data[:4])[0]
                            elif dt in ("bool",):
                                behavior._values[name] = bool(write_data[0]) if write_data else False
                            else:
                                behavior._values[name] = struct.unpack(">i", write_data[:4])[0] if len(write_data) >= 4 else 0
                        except (struct.error, IndexError) as e:
                            logger.warning("S7 write value sync error for %s: %s", name, e)

                        # 通过 on_write 回调将协议层写入传播到 DeviceInstance
                        if self._on_write:
                            resolved_id = device_id or self._default_device_id
                            if resolved_id:
                                try:
                                    asyncio.ensure_future(
                                        self._on_write(resolved_id, name, behavior._values.get(name))
                                    )
                                except Exception as cb_err:
                                    logger.debug("S7 on_write callback schedule error: %s", cb_err)

                area_name = {0x84: "DB", 0x81: "I", 0x82: "Q", 0x83: "M"}.get(area, f"0x{area:02X}")
                self._log_debug("recv", "s7_write",
                                msg("s7", "point_written", area=area_name, db_number=db_number, offset=offset),
                                detail={"area": area_name, "db": db_number, "offset": offset, "len": len(write_data)})
            result_codes.append(0xFF)

        # FIXED-P0: Write Response 参数区 = Function(1) + ItemCount(1) = 2 字节
        # 返回码在 data section 中，不在 parameter section 中
        param_len = 2
        data_len = item_count

        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
            0x00, 0x00,               # FIXED: Reserved字段
        ])
        resp += data[11:13]            # FIXED: PDU Reference偏移11非10
        resp += struct.pack(">H", param_len)
        resp += struct.pack(">H", data_len)
        resp += bytes([0x00, 0x00])    # FIXED: Error Class=0, Error Code=0

        # Parameter section: Function(1) + ItemCount(1)
        resp += bytes([0x05])
        resp += bytes([item_count])

        # Data section: ReturnCode(1) per item
        for rc in result_codes:
            resp += bytes([rc])

        resp[2:4] = struct.pack(">H", len(resp))
        return bytes(resp)

    def _make_s7_error_response(self, data: bytes, error_code: int = 0x85) -> bytes:
        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,  # TPKT (length updated below)
            0x02, 0xF0, 0x80,
            0x32, 0x03,
            0x00, 0x00,               # FIXED: Reserved字段
        ])
        resp += data[11:13] if len(data) > 12 else b"\x00\x00"  # FIXED: PDU Reference偏移11非10
        resp += struct.pack(">H", 0x0008)  # Parameter Length = 8
        resp += struct.pack(">H", 0x0000)  # Data Length = 0
        resp += bytes([0x81, error_code])   # Error Class=0x81, Error Code
        resp += bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])  # 8 bytes padding
        resp[2:4] = struct.pack(">H", len(resp))  # Dynamic TPKT length
        return bytes(resp)

    def _make_s7_szl_response(self, data: bytes, device_id: str | None = None) -> bytes:
        # FIXED-P0: SZL 使用 USER_DATA(0x07) 协议，响应也必须是 USER_DATA 格式
        # 请求结构: TPKT(4) + COTP DT(3) + S7 Header(10) + Parameters(8) + Data(8)
        # Parameters: Reserved(1) + ParamCount(1) + 0x12(1) + Len(1) + Method(1) + TypeGroup(1) + SubFunc(1) + DataRef(1)
        # Data: ReturnCode(1) + TransportSize(1) + Length(2) + SZL_ID(2) + SZL_Index(2)

        # Extract SZL ID and Index from Data section
        # S7 Header: data[7:17], Parameters: data[17:17+param_len], Data: data[17+param_len:]
        param_len = struct.unpack(">H", data[13:15])[0] if len(data) >= 15 else 8
        data_offset = 17 + param_len
        szl_id = 0x001C  # Default: CPU Features (snap7 get_cpu_info requests this)
        szl_index = 0x0000
        if data_offset + 8 <= len(data):
            # Standard SZL request: data has ReturnCode(1)+TransportSize(1)+DataLen(2)+SZL_ID(2)+SZL_Index(2)
            extracted_id = struct.unpack(">H", data[data_offset + 4:data_offset + 6])[0]
            if extracted_id != 0x0000:
                szl_id = extracted_id
                szl_index = struct.unpack(">H", data[data_offset + 6:data_offset + 8])[0]
        # If SZL_ID couldn't be extracted (data too short or 0x0000), default to 0x001C for get_cpu_info

        # Extract request parameters for echo
        req_method = data[21] if len(data) > 21 else 0x11
        req_type_group = data[22] if len(data) > 22 else 0x44
        req_sub_func = data[23] if len(data) > 23 else 0x01
        req_data_ref = data[24] if len(data) > 24 else 0x00

        # Build SZL record data
        if szl_id == 0x0011:
            szl_records = self._build_szl_module_identification(szl_index)
        elif szl_id == 0x0012:
            szl_records = self._build_szl_component_identification(szl_index)
        elif szl_id == 0x001C:
            szl_records = self._build_szl_cpu_features()
        elif szl_id == 0x0032:
            szl_records = self._build_szl_plc_status(device_id)
        else:
            szl_records = self._build_szl_module_identification(0x0000)

        # Parse record structure: szl_records is raw bytes containing LengthDR + NDR + record data
        # Format captured from snap7 server traffic:
        #   LengthDR (2 bytes, uint16) = length of each data record
        #   NDR (2 bytes, uint16) = number of data records
        #   Record data (LengthDR * NDR bytes)
        record_data = szl_records
        record_len = len(record_data) // max(1, 1)  # Will be set properly below
        num_records = 1
        # If szl_records already has LengthDR+NDR header (from _build_szl_cpu_features), use it directly
        if szl_id == 0x001C and len(record_data) >= 4:
            # _build_szl_cpu_features returns records only; we add the header
            pass

        # USER_DATA response: S7 Header(10) + Parameters + Data
        # Response parameter: Method=0x12, TypeGroup=0x84 (0x44|0x80=response flag)
        # Captured from snap7 server: param has Length=8 with 4 extra zero bytes
        param_data = bytes([
            0x00,                          # Reserved
            0x01,                          # Parameter count
            0x12,                          # Type/length header
            0x08,                          # Length of following = 8 (match snap7 server)
            0x12,                          # Method = 0x12 (response)
            req_type_group | 0x80,        # Type|Group with 0x80 response flag (0x44 -> 0x84)
            req_sub_func,                  # SubFunction (echo)
            req_data_ref,                  # DataRef (echo)
            0x00, 0x00, 0x00, 0x00,       # Extra 4 bytes (match snap7 server)
        ])

        # Data section: ReturnCode(1) + TransportSize(1) + DataLength(2) + SZL_ID(2) + SZL_Index(2) + LengthDR(2) + NDR(2) + RecordData
        # LengthDR = length of each data record, NDR = number of records
        # For SZL 0x001C: LengthDR=34, NDR=10, records=340 bytes
        # For SZL 0x0011: LengthDR=28, NDR=4, records=112 bytes
        if szl_id == 0x001C:
            length_dr = 34  # Each CPU feature record is 34 bytes (2 index + 32 data)
            num_records = len(record_data) // length_dr
            if len(record_data) % length_dr != 0:
                # Pad to multiple of length_dr
                record_data = record_data + b'\x00' * (length_dr - (len(record_data) % length_dr))
                num_records = len(record_data) // length_dr
        else:
            length_dr = len(record_data)
            num_records = 1

        data_payload = struct.pack(">H", szl_id)  # SZL_ID
        data_payload += struct.pack(">H", szl_index)  # SZL_Index
        data_payload += struct.pack(">H", length_dr)  # LengthDR = record length
        data_payload += struct.pack(">H", num_records)  # NDR = number of records
        data_payload += record_data  # Record data

        data_section = bytes([
            0xFF,           # Return code = success
            0x09,           # Transport size = octet string
        ]) + struct.pack(">H", len(data_payload))  # DataLength
        data_section += data_payload

        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,  # TPKT (length updated below)
            0x02, 0xF0, 0x80,        # COTP DT
            0x32, 0x07,               # S7 Protocol ID, Msg Type = User Data (0x07) — snap7 expects same type as request for SZL
            0x00, 0x00,               # Reserved
        ])
        resp += data[11:13]  # PDU Reference (echo)
        resp += struct.pack(">H", len(param_data))  # Parameter Length
        resp += struct.pack(">H", len(data_section))  # Data Length
        # User Data (0x07) responses use 10-byte header (no Error Class/Code)
        resp += param_data
        resp += data_section
        resp[2:4] = struct.pack(">H", len(resp))
        return bytes(resp)

    def _build_szl_module_identification(self, index: int) -> bytes:
        # FIXED-P0: SZL 0x0011 = Order Code (snap7 parse_order_code_szl)
        # 数据记录格式: OrderCode(20) + V1(1) + V2(1) + V3(1) = 23 bytes
        # 注意: 不包含 LengthDR + NDR 头，snap7 的 parse_read_szl_response 已跳过 SZL_ID+Index
        info = self._device_info.get(self._default_device_id or "", {})
        order_num = info.get("order_number", "6ES7 000-0AA00-0AA0")
        fw_rev_str = info.get("firmware_revision", "V1.0.0")
        fw_parts = fw_rev_str.replace("V", "").split(".")
        fw_major = int(fw_parts[0]) if fw_parts and fw_parts[0].isdigit() else 1
        fw_minor = int(fw_parts[1]) if len(fw_parts) > 1 and fw_parts[1].isdigit() else 0
        fw_patch = int(fw_parts[2]) if len(fw_parts) > 2 and fw_parts[2].isdigit() else 0
        order_bytes = order_num.encode("utf-8")[:20].ljust(20, b"\x00")
        record = order_bytes + bytes([fw_major, fw_minor, fw_patch])
        return record

    def _build_szl_component_identification(self, index: int) -> bytes:
        # FIXED-P0: SZL 0x0012 = Component Identification
        # 数据记录格式与 0x0011 类似，不包含 LengthDR + NDR 头
        info = self._device_info.get(self._default_device_id or "", {})
        order_num = info.get("order_number", "6ES7 000-0AA00-0AA0")
        fw_rev_str = info.get("firmware_revision", "V1.0.0")
        fw_parts = fw_rev_str.replace("V", "").split(".")
        fw_major = int(fw_parts[0]) if fw_parts and fw_parts[0].isdigit() else 1
        fw_minor = int(fw_parts[1]) if len(fw_parts) > 1 and fw_parts[1].isdigit() else 0
        fw_patch = int(fw_parts[2]) if len(fw_parts) > 2 and fw_parts[2].isdigit() else 0
        order_bytes = order_num.encode("utf-8")[:20].ljust(20, b"\x00")
        record = order_bytes + bytes([fw_major, fw_minor, fw_patch])
        return record

    def _build_szl_cpu_features(self) -> bytes:
        # SZL 0x001C = CPU Component Identification (snap7 get_cpu_info)
        # Returns 10 records of 34 bytes each (2-byte index + 32-byte data)
        # Format captured from snap7 server traffic analysis:
        #   Record 0x0001: AS name (32 bytes)
        #   Record 0x0002: Module type name (32 bytes)
        #   Record 0x0003: zeros
        #   Record 0x0004: Copyright (32 bytes)
        #   Record 0x0005: Serial number (32 bytes)
        #   Record 0x0007: Module name (32 bytes)
        #   Record 0x0008: MMC ID (32 bytes)
        #   Record 0x0009: CPU profile (32 bytes)
        #   Record 0x000A: zeros
        #   Record 0x000B: zeros
        info = self._device_info.get(self._default_device_id or "", {})
        module_name = info.get("module_name", "ProtoForge S7")
        serial = info.get("serial_number", "PF-00000000")
        as_name = info.get("as_name", "ProtoForge")
        copyright_str = info.get("copyright", "ProtoForge Simulation")
        module_type = info.get("module_type", "ProtoForge S7-1200")

        def _record(idx: int, data_str: str = "", data_len: int = 32) -> bytes:
            """Build a 34-byte record: 2-byte index + 32-byte data."""
            d = data_str.encode("utf-8")[:data_len].ljust(data_len, b"\x00")
            return struct.pack(">H", idx) + d

        records = bytearray()
        records += _record(0x0001, as_name)        # AS name
        records += _record(0x0002, module_type)    # Module type name
        records += _record(0x0003, "")              # zeros
        records += _record(0x0004, copyright_str)  # Copyright
        records += _record(0x0005, serial)          # Serial number
        records += _record(0x0007, module_name)    # Module name
        records += _record(0x0008, "")              # MMC ID
        records += _record(0x0009, "")              # CPU profile
        records += _record(0x000A, "")              # zeros
        records += _record(0x000B, "")              # zeros

        return bytes(records)

    async def create_device(self, device_config: DeviceConfig) -> str:
        device_id = device_config.id
        proto_config = device_config.protocol_config or {}
        # FIX: S7-1200/1500 优化块访问时启用 2 字节 DB 系统头
        db_header_size = 2 if proto_config.get("optimized_db", False) else 0
        behavior = S7DeviceBehavior(device_config.points, db_header_size=db_header_size)
        async with self._behaviors_lock:  # FIXED: W3 - add _behaviors_lock protection for _behaviors and _device_configs access
            self._behaviors[device_id] = behavior
            self._device_configs[device_id] = device_config  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
        await self._update_default_device_async(device_id)

        proto_config = device_config.protocol_config or {}
        rack = proto_config.get("rack", self._rack)
        if not isinstance(rack, int) or rack < 0 or rack > 7:
            raise ValueError(f"S7 rack must be between 0 and 7 (got {rack})")
        slot = proto_config.get("slot", self._slot)
        if not isinstance(slot, int) or slot < 0 or slot > 31:
            raise ValueError(f"S7 slot must be between 0 and 31 (got {slot})")

        self._device_info[device_id] = {
            "module_name": device_config.name,
            "serial_number": f"PF-{device_id[:8].upper()}",
            "order_number": proto_config.get("order_number", "6ES7 000-0AA00-0AA0"),
            "hardware_revision": proto_config.get("hardware_revision", "1"),
            "firmware_revision": proto_config.get("firmware_revision", "V1.0.0"),
            "rack": rack,
            "slot": slot,
            "db_count": 1,
            "mb_count": 256,
            "ew_count": 256,
            "aw_count": 256,
        }
        self._rack_slot_map[(rack, slot)] = device_id

        logger.info("S7 device created: %s (rack=%d, slot=%d)",
                     device_id, rack, slot)
        self._log_debug("system", "device_create",
                        msg("s7", "device_created", name=device_config.name),
                        device_id=device_id)
        return device_id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:  # FIXED: W3 - add _behaviors_lock protection for _behaviors and _device_configs access
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
        info = self._device_info.pop(device_id, None)
        if info:
            rack = info.get("rack", 0)
            slot = info.get("slot", 1)
            self._rack_slot_map.pop((rack, slot), None)
        await self._clear_default_device_async(device_id)
        logger.info("S7 device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        msg("s7", "device_removed", id=device_id),
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return []

        values = []
        for point in config.points:
            val = behavior.get_value(point.name)
            values.append(PointValue(
                name=point.name,
                value=val,
                timestamp=time.time(),
            ))
        return values

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False

        # 检查点位是否存在且可写
        config = self._device_configs.get(device_id)
        if config:
            point = next((p for p in config.points if p.name == point_name), None)
            if point is None:
                logger.warning("S7 write_point: point '%s' not found on device %s", point_name, device_id)
                return False
            if point.access not in ("w", "rw"):
                logger.warning("S7 write_point: point '%s' is read-only on device %s", point_name, device_id)
                return False

        # 更新协议层 behavior 内部状态并同步到 DB 数据区
        success = behavior.on_write(point_name, value)
        if success and self._on_write:
            try:
                await self._on_write(device_id, point_name, value)
            except Exception as e:
                logger.warning("S7 write_point: on_write callback error for %s.%s: %s", device_id, point_name, e)
        return success

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        """内部同步：直接更新 S7 DB 数据区，绕过访问控制检查。

        引擎 tick 循环调用此方法将动态生成的值同步到 S7 数据块，
        确保非固定生成器的值能被外部 S7 客户端读到。
        """
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return
        behavior.set_value(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "default": "0.0.0.0",
                    "description": desc("listen_address"),
                },
                "port": {
                    "type": "integer",
                    "default": 102,
                    "description": desc("s7_port_desc"),
                },
                "rack": {
                    "type": "integer",
                    "default": 0,
                    "description": desc("s7_rack"),
                },
                "slot": {
                    "type": "integer",
                    "default": 1,
                    "description": desc("s7_slot"),
                },
            },
        }

    def _build_szl_plc_status(self, device_id: str | None = None) -> bytes:  # FIXED-P1: SZL 0x0032 PLC状态
        behavior = self._behaviors.get(device_id or self._default_device_id or "")
        run_status = 0x08  # 默认RUN状态
        if behavior:
            val = behavior._values.get("run_status")
            if val is not None:
                run_status = 0x08 if val else 0x04  # 0x08=RUN, 0x04=STOP
        # SZL 数据 = 纯数据记录，不包含 LengthDR + NDR 头
        record = struct.pack(">H", run_status)  # 2 bytes
        return record

    def _make_s7_plc_control_response(self, data: bytes, device_id: str | None = None, start: bool = True) -> bytes:  # FIXED-P1: Start/Stop PLC
        behavior = self._behaviors.get(device_id or self._default_device_id or "")
        if behavior and "run_status" in behavior._values:
            behavior._values["run_status"] = start
            behavior.write_area(S7DeviceBehavior.S7_AREA_DB, 1, 0, struct.pack(">B", 1 if start else 0))
        resp = bytearray([
            0x03, 0x00, 0x00, 0x00,
            0x02, 0xF0, 0x80,
            0x32, 0x03,
            0x00, 0x00,               # FIXED: Reserved字段
        ])
        resp += data[11:13] if len(data) > 12 else b"\x00\x00"  # FIXED: PDU Reference偏移11非10
        resp += struct.pack(">H", 0x0001)  # Parameter Length = 1
        resp += struct.pack(">H", 0x0000)  # Data Length = 0
        resp += bytes([0x00, 0x00])    # FIXED: Error Class=0, Error Code=0
        resp += bytes([0x28 if start else 0x29])  # Function: Start/Stop
        resp[2:4] = struct.pack(">H", len(resp))
        return bytes(resp)
