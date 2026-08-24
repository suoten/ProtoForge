"""FINS (Factory Interface Network Service) 协议仿真服务器.

本模块实现了 Omron FINS 通信协议的仿真服务器，
支持以下功能:
    - FINS/TCP (端口 9600) 传输
    - FINS/UDP (端口 9600) 传输
    - 内存区域读写 (CIO/DM/HR/AR/DM/EM)
    - 状态读取与控制
    - 节点地址寻址

支持与以下真实设备对接:
    - Omron CJ/CS/CP/NJ/NX 系列 PLC
    - Anybus FINS 网关
    - 任何标准 FINS 客户端
"""

import asyncio
import logging
import re
import struct
import time
from typing import Any

from protoforge.core.messages import desc
from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)


class FinsDeviceBehavior(StandardDeviceBehavior):
    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._memory_areas: dict[int, bytearray] = {}
        self._point_addresses: dict[str, tuple[int, int]] = {}
        self._point_bit_addresses: dict[str, tuple[int, int, int]] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                address = getattr(p, 'address', '0') or '0'
                area, offset = self._parse_fins_address(str(address))
                self._point_addresses[name] = (area, offset)
                bit_address = self._parse_fins_bit_address(str(address))
                if bit_address:
                    self._point_bit_addresses[name] = bit_address
                self._sync_value_to_area(name, self._values.get(name, 0))

    # FIXED-P0: FINS标准符号地址到区域代码映射
    _FINS_AREA_MAP = {
        'CIO': 0xB0, 'WR': 0xB1, 'W': 0xB1, 'HR': 0xB2, 'H': 0xB2,
        'AR': 0xB3, 'A': 0xB3, 'DM': 0x82, 'D': 0x82,
        'EM': 0x90, 'E': 0x90, 'TIM': 0x09, 'T': 0x09,
        'CNT': 0x08, 'C': 0x08,
    }

    _FINS_BIT_AREA_MAP = {
        0x30: 0xB0,  # CIO bit -> CIO word
        0x31: 0xB1,  # WR bit -> WR word
        0x32: 0xB2,  # HR bit -> HR word
        0x33: 0xB3,  # AR bit -> AR word
        0x02: 0x82,  # DM bit -> DM word
    }

    @staticmethod
    def _data_type_name(point: Any) -> str:
        data_type = getattr(point, "data_type", "") if point else ""
        return str(getattr(data_type, "value", data_type) or "").lower()

    @classmethod
    def _type_width(cls, point: Any) -> int:
        """返回点位在 FINS 字节内存中的宽度。"""
        dt = cls._data_type_name(point)
        if dt in ("int32", "uint32", "dint", "float32"):
            return 4
        if dt == "float64":
            return 8
        return 2

    @classmethod
    def _encode_value(cls, point: Any, value: Any) -> bytes:
        """统一把点位值编码为 FINS 内存中的大端字节。"""
        dt = cls._data_type_name(point)
        if dt == "bool":
            return struct.pack(">H", 1 if bool(value) else 0)
        if dt == "float32":
            return struct.pack(">f", float(value))
        if dt == "float64":
            return struct.pack(">d", float(value))
        if dt == "int16":
            return struct.pack(">h", int(value))
        if dt == "uint16":
            return struct.pack(">H", int(value) & 0xFFFF)
        if dt in ("int32", "dint"):
            return struct.pack(">i", int(value))
        if dt == "uint32":
            return struct.pack(">I", int(value) & 0xFFFFFFFF)
        if dt == "string" or isinstance(value, str):
            return str(value).encode("utf-8")
        return struct.pack(">h", int(value) & 0xFFFF)

    @classmethod
    def _decode_value(cls, point: Any, data: bytes) -> Any:
        """统一把 FINS 内存字节解码为点位值。数据不足时不解码。"""
        dt = cls._data_type_name(point)
        if dt == "string":
            if not data:
                return None
            return data.rstrip(b"\x00").decode("utf-8", errors="replace")
        width = cls._type_width(point)
        if len(data) < width:
            return None
        if dt == "bool":
            return int.from_bytes(data[:2], byteorder="big") != 0
        if dt == "float32":
            return struct.unpack(">f", data[:4])[0]
        if dt == "float64":
            return struct.unpack(">d", data[:8])[0]
        if dt == "int16":
            return struct.unpack(">h", data[:2])[0]
        if dt == "uint16":
            return struct.unpack(">H", data[:2])[0]
        if dt in ("int32", "dint"):
            return struct.unpack(">i", data[:4])[0]
        if dt == "uint32":
            return struct.unpack(">I", data[:4])[0]
        return struct.unpack(">h", data[:2])[0]

    @staticmethod
    def _parse_fins_address(address: str) -> tuple[int, int]:
        try:
            if ':' in address:
                parts = address.split(':')
                area = int(parts[0])
                offset = int(parts[1]) if len(parts) > 1 else 0
                return (area, offset)
            # FIXED-P0: 支持FINS标准符号地址格式(CIO0.00/DM0/D100等)
            m = re.match(r'^([A-Za-z]+)(\d+)(?:\.(\d+))?$', address)
            if m:
                prefix = m.group(1).upper()
                word_offset = int(m.group(2))
                bit_offset = int(m.group(3)) if m.group(3) else 0
                area = FinsDeviceBehavior._FINS_AREA_MAP.get(prefix, 0x82)
                byte_offset = word_offset * 2 + (bit_offset // 8 if bit_offset else 0)
                return (area, byte_offset)
            return (0x82, int(address))
        except (ValueError, IndexError):
            return (0x82, 0)

    @staticmethod
    def _parse_fins_bit_address(address: str) -> tuple[int, int, int] | None:
        match = re.match(r'^([A-Za-z]+)(\d+)\.(\d+)$', address.strip())
        if not match:
            return None
        prefix = match.group(1).upper()
        word_address = int(match.group(2))
        bit_address = int(match.group(3))
        if not 0 <= bit_address <= 15:
            return None
        word_area = FinsDeviceBehavior._FINS_AREA_MAP.get(prefix, 0x82)
        return word_area, word_address, bit_address

    def _sync_value_to_area(self, point_name: str, value: Any) -> None:
        if point_name not in self._point_addresses:
            return
        area, offset = self._point_addresses[point_name]
        try:
            point = self._points.get(point_name)
            dt = self._data_type_name(point)
            if point_name in self._point_bit_addresses:
                word_area, word_address, bit_address = self._point_bit_addresses[point_name]
                current = int.from_bytes(
                    self.read_area(word_area, word_address * 2, 2),
                    byteorder="big",
                )
                mask = 1 << bit_address
                current = (current | mask) if bool(value) else (current & ~mask)
                self.write_area(
                    word_area,
                    word_address * 2,
                    current.to_bytes(2, byteorder="big"),
                )
                return
            data = self._encode_value(point, value)
            self.write_area(area, offset, data)
        except (ValueError, TypeError, struct.error) as e:
            logger.warning("FINS on_write value conversion error for %s: %s", point_name, e)

    def on_write(self, point_name: str, value: Any) -> bool:  # FIXED: 重复代码→继承StandardDeviceBehavior
        if point_name in self._values:
            self._values[point_name] = value
            self._sync_value_to_area(point_name, value)
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._sync_value_to_area(point_name, value)

    def get_value(self, point_name: str) -> Any:  # FIXED-P0: 动态值生成后同步到内存区
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and pt.generator_type.value != "fixed":
                if point_name in self._written_values:
                    return self._written_values[point_name]
                value = gen.generate()
                self._values[point_name] = value
                self._sync_value_to_area(point_name, value)
                return value
        return self._values.get(point_name, 0)

    def read_area(self, area: int, offset: int, size: int) -> bytearray:
        if area not in self._memory_areas:
            self._memory_areas[area] = bytearray(max(offset + size, 1024))
        elif len(self._memory_areas[area]) < offset + size:
            self._memory_areas[area].extend(bytearray(max(offset + size, 1024) - len(self._memory_areas[area])))
        return self._memory_areas[area][offset:offset + size]

    def write_area(self, area: int, offset: int, data: bytes) -> None:
        if area not in self._memory_areas:
            self._memory_areas[area] = bytearray(1024)
        buf = self._memory_areas[area]
        end = offset + len(data)
        if end > len(buf):
            buf.extend(bytearray(end - len(buf)))
        buf[offset:offset + len(data)] = data

    def read_bits(self, bit_area: int, word_address: int,
                  bit_address: int, count: int) -> bytes:
        word_area = self._FINS_BIT_AREA_MAP.get(bit_area)
        if word_area is None:
            return bytes(count)

        result = bytearray(count)
        for index in range(count):
            absolute_bit = bit_address + index
            current_word = word_address + absolute_bit // 16
            current_bit = absolute_bit % 16
            raw = self.read_area(word_area, current_word * 2, 2)
            word = int.from_bytes(raw, byteorder="big")
            result[index] = 1 if word & (1 << current_bit) else 0
        return bytes(result)

    def write_bits(self, bit_area: int, word_address: int,
                   bit_address: int, values: bytes) -> None:
        word_area = self._FINS_BIT_AREA_MAP.get(bit_area)
        if word_area is None:
            return

        changed_bits: list[tuple[int, int, bool]] = []
        for index, value in enumerate(values):
            absolute_bit = bit_address + index
            current_word = word_address + absolute_bit // 16
            current_bit = absolute_bit % 16
            raw = self.read_area(word_area, current_word * 2, 2)
            word = int.from_bytes(raw, byteorder="big")
            mask = 1 << current_bit
            is_on = value != 0
            word = (word | mask) if is_on else (word & ~mask)
            self.write_area(
                word_area,
                current_word * 2,
                word.to_bytes(2, byteorder="big"),
            )
            changed_bits.append((current_word, current_bit, is_on))

        for name, (point_area, point_word, point_bit) in self._point_bit_addresses.items():
            if point_area != word_area:
                continue
            for changed_word, changed_bit, is_on in changed_bits:
                if point_word == changed_word and point_bit == changed_bit:
                    self._values[name] = is_on
                    self._written_values[name] = is_on

    def sync_word_bits_to_points(self, word_area: int, word_address: int,
                                 data: bytes) -> None:
        """字写入后，同步覆盖范围内的位测点。"""
        word_count = len(data) // 2
        for name, (point_area, point_word, point_bit) in self._point_bit_addresses.items():
            if point_area != word_area:
                continue
            relative_word = point_word - word_address
            if not 0 <= relative_word < word_count:
                continue
            start = relative_word * 2
            word = int.from_bytes(data[start:start + 2], byteorder="big")
            value = bool(word & (1 << point_bit))
            self._values[name] = value
            self._written_values[name] = value

    def sync_word_write_to_points(self, word_area: int, word_address: int,
                                  data: bytes) -> None:
        """把协议层的字写入统一同步回所有重叠的非位点位。"""
        write_start = word_address * 2
        write_end = write_start + len(data)
        for name, (point_area, point_offset) in self._point_addresses.items():
            if name in self._point_bit_addresses or point_area != word_area:
                continue
            point = self._points.get(name)
            width = self._type_width(point)
            dt = self._data_type_name(point)
            point_end = point_offset + width
            if dt == "string":
                # 字符串长度由本次写入和下一个点位的地址共同确定，避免按旧值长度截断。
                next_offsets = [
                    other_offset
                    for other_name, (other_area, other_offset) in self._point_addresses.items()
                    if other_name != name
                    and other_name not in self._point_bit_addresses
                    and other_area == word_area
                    and other_offset > point_offset
                ]
                point_end = min(min(next_offsets, default=write_end), write_end)
            if point_offset < write_start or point_end > write_end:
                continue
            start = point_offset - write_start
            chunk_end = min(point_end, write_end)
            value = self._decode_value(point, data[start:chunk_end - write_start])
            if value is not None:
                self._values[name] = value
                self._written_values[name] = value


class FinsServer(ProtocolServer):
    protocol_name = "fins"
    protocol_display_name = "Omron FINS"

    FINS_TCP_MAGIC = b"FINS"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, FinsDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_params: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 9600
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._sid_counter = 1
        self._udp_transport = None

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 9600)
        self._validate_port(self._port)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("FINS server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"FINS service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start FINS server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("FINS task cancelled")
        except Exception as e:
            logger.warning("FINS server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("FINS server stopped")
            self._log_debug("system", "server_stop", "FINS service stopped")

    async def _serve(self) -> None:
        loop = asyncio.get_running_loop()
        tcp_server = await asyncio.start_server(
            self._handle_connection, self._host, self._port, reuse_address=True  # FIXED-M10: 启用地址复用
        )
        transport, _ = await loop.create_datagram_endpoint(
            lambda: FinsUdpProtocol(self), local_addr=(self._host, self._port), reuse_address=True  # FIXED-M10: UDP也启用地址复用，避免TCP/UDP同端口绑定失败
        )
        self._udp_transport = transport
        try:
            async with tcp_server:
                await tcp_server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("FINS server task cancelled")
        except Exception as e:
            logger.exception("FINS server error: %s", e)
            self._status = ProtocolStatus.ERROR
        finally:
            if self._udp_transport:
                self._udp_transport.close()

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("FINS connection from %s", addr)
        _READ_TIMEOUT = 120  # FIXED: Increase from 30s to 120s to prevent premature connection close when multiple devices share the FINS driver
        try:
            while self._server_running:
                header = await asyncio.wait_for(reader.readexactly(8), timeout=_READ_TIMEOUT)
                magic = header[0:4]
                if magic != self.FINS_TCP_MAGIC:
                    break
                body_len = struct.unpack(">I", header[4:8])[0]
                body = await asyncio.wait_for(reader.readexactly(body_len), timeout=_READ_TIMEOUT) if body_len > 0 else b""
                response = self._process_fins(body)
                if response:
                    resp_header = self.FINS_TCP_MAGIC + struct.pack(">I", len(response))
                    writer.write(resp_header + response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.IncompleteReadError, asyncio.CancelledError, asyncio.TimeoutError, BrokenPipeError, ConnectionAbortedError) as e:
            logger.debug("Connection handler error: %s", e)  # FIXED: 添加日志记录，避免异常被静默吞掉
        except Exception as e:  # FIXED-P1: 兜底捕获所有其他异常，避免单个帧处理错误导致整个连接崩溃
            logger.exception("FINS connection handler unexpected error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_fins(self, data: bytes) -> bytes | None:
        """处理 FINS/TCP 帧。

        支持两种帧格式:
        1. 标准 FINS/TCP: body = Command(4) + ErrorCode(4) + Data
           - Command=0x00000000: Node address data send (client→server)
           - Command=0x00000002: FINS frame send (client→server)
        2. 非标准 EdgeLite 握手: body = FINS frame (无 Command/ErrorCode 前缀)
           EdgeLite 驱动在 connect() 后直接发送 FINS 帧（Controller Read）做节点握手
        """
        if len(data) < 4:
            return None

        # 尝试读取 4 字节 command 判断是否为标准 FINS/TCP 帧
        command = struct.unpack(">I", data[0:4])[0]

        if command == 0x00000000 or command == 0x00000001:
            # 标准 FINS/TCP: Node address data send
            return self._handle_fins_init(data)
        elif command == 0x00000002 or command == 0x00000003:
            # 标准 FINS/TCP: FINS frame send
            return self._handle_fins_send(data)
        else:
            # 非标准 EdgeLite 握手: body 直接就是 FINS 帧
            return self._handle_fins_frame_direct(data)

    def _handle_fins_init(self, data: bytes) -> bytes:
        """处理标准 FINS/TCP 节点地址协商。

        请求 body: Command(4) + ErrorCode(4) + ClientNodeAddr(4)
        响应 body: Command(4)=0x00000001 + ErrorCode(4)=0 + SrceNodeAddr(4) + DestNodeAddr(4)

        fins 库的 node_address_data_send() 发送 command=0, data=\x00*4
        并从 response.data[0:4] 读取 srce_node_add, [4:8] 读取 dest_node_add
        """
        client_node = 0
        if len(data) >= 12:
            client_node = struct.unpack(">I", data[8:12])[0]

        server_node = 1
        resp = bytearray()
        resp += struct.pack(">I", 0x00000001)  # Command: node address data send response
        resp += struct.pack(">I", 0x00000000)  # Error code: success
        resp += struct.pack(">I", server_node)  # Srce node address (server)
        resp += struct.pack(">I", client_node)  # Dest node address (client)
        return bytes(resp)

    def _handle_fins_send(self, data: bytes) -> bytes:
        """处理标准 FINS/TCP 帧发送。

        请求 body: Command(4) + ErrorCode(4) + FINS frame(N)
        响应 body: Command(4)=0x00000002 + ErrorCode(4)=0 + FINS response frame(N)
        """
        # FINS 帧从 data[8] 开始（跳过 Command(4) + ErrorCode(4)）
        fins_frame = data[8:]
        if len(fins_frame) < 12:
            return self._make_fins_error(0x0204)

        mrc = fins_frame[10]
        src = fins_frame[11]

        fins_response = self._build_fins_response(fins_frame, mrc, src)
        if fins_response is None:
            return self._make_fins_error(0x0204)

        # 用标准 FINS/TCP Command(4) + ErrorCode(4) 包装
        resp = bytearray()
        resp += struct.pack(">I", 0x00000002)  # Command: FINS frame send response
        resp += struct.pack(">I", 0x00000000)  # Error code: success
        resp += fins_response
        return bytes(resp)

    def _handle_fins_frame_direct(self, data: bytes) -> bytes | None:
        """处理 EdgeLite 非标准握手帧。

        EdgeLite 驱动在 TCPFinsConnection.connect() 完成节点地址协商后，
        直接发送 FINS 帧（不带 Command/ErrorCode 前缀）做 Controller Read 握手。
        响应也直接返回 FINS 响应帧（不带 Command/ErrorCode 前缀）。
        """
        fins_frame = data
        if len(fins_frame) < 12:
            return None

        mrc = fins_frame[10]
        src = fins_frame[11]

        fins_response = self._build_fins_response(fins_frame, mrc, src)
        if fins_response is None:
            # 返回 FINS 错误帧（无 Command/ErrorCode 包装）
            fins_response = self._build_fins_error_frame(fins_frame, 0x0204)
        return fins_response

    def _build_fins_response(self, fins_frame: bytes, mrc: int, src: int) -> bytes | None:
        """构建 FINS 响应帧（不含 FINS/TCP Command/ErrorCode 前缀）。

        FINS 响应帧格式: SwappedHeader(10) + MRC(1) + SRC(1) + EndCode(2) + Data(N)
        """
        if mrc == 0x01 and src == 0x01:  # 0x0101=内存区读取
            return self._build_memory_read_response(fins_frame)
        elif mrc == 0x01 and src == 0x02:  # 0x0102=内存区写入
            return self._build_memory_write_response(fins_frame)
        elif mrc == 0x05 and src == 0x01:  # 0x0501=控制器读取
            return self._build_controller_read_response(fins_frame)
        return None

    def _swap_fins_header(self, fins_header: bytes) -> bytearray:
        """交换FINS帧头中的源/目标地址，用于构造响应帧"""
        resp_header = bytearray(fins_header)
        # DNA(3) <-> SNA(6), DA1(4) <-> SA1(7), DA2(5) <-> SA2(8)
        resp_header[3], resp_header[6] = resp_header[6], resp_header[3]  # DNA <-> SNA
        resp_header[4], resp_header[7] = resp_header[7], resp_header[4]  # DA1 <-> SA1
        resp_header[5], resp_header[8] = resp_header[8], resp_header[5]  # DA2 <-> SA2
        return resp_header

    def _build_memory_read_response(self, fins_frame: bytes) -> bytes:
        """构建内存区读取 FINS 响应帧。

        FINS 响应帧: SwappedHeader(10) + MRC(1) + SRC(1) + EndCode(2) + Data(N)
        """
        if len(fins_frame) < 16:
            return self._build_fins_error_frame(fins_frame, 0x0204)

        area = fins_frame[12]
        word_addr = struct.unpack(">H", fins_frame[13:15])[0]
        bit_addr = fins_frame[15]
        word_count = struct.unpack(">H", fins_frame[16:18])[0] if len(fins_frame) >= 18 else 1
        if word_count == 0 or word_count > 1000:
            return self._build_fins_error_frame(fins_frame, 0x0204)

        is_bit_access = area in FinsDeviceBehavior._FINS_BIT_AREA_MAP
        read_size = word_count if is_bit_access else word_count * 2
        read_data = bytearray(read_size)
        behavior = self._behaviors.get(self._default_device_id or "")
        if behavior:
            if is_bit_access:
                read_data = behavior.read_bits(area, word_addr, bit_addr, word_count)
            else:
                read_data = behavior.read_area(area, word_addr * 2, read_size)

        resp = bytearray()
        resp += bytes(self._swap_fins_header(fins_frame[0:10]))  # 10 bytes swapped header
        resp += bytes([fins_frame[10], fins_frame[11]])  # MRC + SRC (echo)
        resp += struct.pack(">H", 0x0000)  # End code: success
        resp += read_data
        return bytes(resp)

    def _build_memory_write_response(self, fins_frame: bytes) -> bytes:
        """构建内存区写入 FINS 响应帧。"""
        if len(fins_frame) < 16:
            return self._build_fins_error_frame(fins_frame, 0x0204)

        area = fins_frame[12]
        word_addr = struct.unpack(">H", fins_frame[13:15])[0]
        bit_addr = fins_frame[15]
        word_count = struct.unpack(">H", fins_frame[16:18])[0] if len(fins_frame) >= 18 else 1
        if word_count == 0 or word_count > 1000:
            return self._build_fins_error_frame(fins_frame, 0x0204)

        is_bit_access = area in FinsDeviceBehavior._FINS_BIT_AREA_MAP
        data_size = word_count if is_bit_access else word_count * 2
        write_data = fins_frame[18:18 + data_size] if len(fins_frame) >= 18 + data_size else b""
        behavior = self._behaviors.get(self._default_device_id or "")
        if behavior:
            if is_bit_access:
                behavior.write_bits(area, word_addr, bit_addr, write_data)
            else:
                behavior.write_area(area, word_addr * 2, write_data)
                behavior.sync_word_bits_to_points(area, word_addr, write_data)
                behavior.sync_word_write_to_points(area, word_addr, write_data)
            self._log_debug("recv", "fins_write",
                            f"Write area {area} offset {word_addr}",
                            detail={"area": area, "offset": word_addr, "len": len(write_data)})

        resp = bytearray()
        resp += bytes(self._swap_fins_header(fins_frame[0:10]))  # 10 bytes swapped header
        resp += bytes([fins_frame[10], fins_frame[11]])  # MRC + SRC (echo)
        resp += struct.pack(">H", 0x0000)  # End code: success
        return bytes(resp)

    def _build_controller_read_response(self, fins_frame: bytes) -> bytes:
        """构建控制器读取 FINS 响应帧。"""
        device_config = self._device_configs.get(self._default_device_id or "")
        # FINS控制器读取响应数据布局(End Code之后):
        # Controller Model(1) + Controller Version(1) + System Version(2) + Controller Name(20) + Status(2) = 26 bytes
        controller_data = bytearray(26)
        controller_data[0] = 0x01  # Controller Model
        controller_data[1] = 0x01  # Controller Version
        controller_data[2:4] = struct.pack(">H", 0x0100)  # System Version V1.00
        if device_config:
            name_bytes = device_config.name.encode("ascii", errors="replace")[:20]
            controller_data[4:24] = name_bytes.ljust(20, b"\x00")
            proto_config = device_config.protocol_config or {}
            if "model" in proto_config:
                model_val = proto_config["model"]
                controller_data[0] = int(model_val) if isinstance(model_val, int) else 0x01
            if "firmware" in proto_config:
                fw = proto_config["firmware"]
                if isinstance(fw, (int, float)):
                    controller_data[2:4] = struct.pack(">H", int(fw * 100) & 0xFFFF)
        else:
            controller_data[4:24] = b"ProtoForge-FINS\x00\x00\x00\x00"[:20]
        controller_data[24:26] = struct.pack(">H", 0x0000)  # Controller Status: Normal

        resp = bytearray()
        resp += bytes(self._swap_fins_header(fins_frame[0:10]))  # 10 bytes swapped header
        resp += bytes([fins_frame[10], fins_frame[11]])  # MRC + SRC (echo)
        resp += struct.pack(">H", 0x0000)  # End code: success
        resp += controller_data
        return bytes(resp)

    def _build_fins_error_frame(self, fins_frame: bytes, error_code: int) -> bytes:
        """构建 FINS 错误响应帧（不含 FINS/TCP Command/ErrorCode 前缀）。"""
        resp = bytearray()
        resp += bytes(self._swap_fins_header(fins_frame[0:10]))  # 10 bytes swapped header
        resp += bytes([fins_frame[10], fins_frame[11]])  # MRC + SRC (echo)
        resp += struct.pack(">H", error_code)  # End code: error
        return bytes(resp)

    def _make_fins_error(self, error_code: int) -> bytes:
        """构建标准 FINS/TCP 错误响应（Command(4) + ErrorCode(4)）。"""
        resp = bytearray()
        resp += struct.pack(">I", 0x00000002)  # Command: FINS frame send response
        resp += struct.pack(">I", error_code)  # Error code
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = FinsDeviceBehavior(device_config.points)
        proto_config = device_config.protocol_config or {}
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_params[device_config.id] = {  # FIXED-P1: 移入_behaviors_lock内保护
                "source_node": proto_config.get("source_node", 0),
                "dest_node": proto_config.get("dest_node") or proto_config.get("fins_node", 1),  # FIXED-P0: 兼容fins_node参数名
                "dest_unit": proto_config.get("dest_unit") or proto_config.get("fins_unit", 0),  # FIXED-P0: 兼容fins_unit参数名
            }
        await self._update_default_device_async(device_config.id)

        logger.info("FINS device created: %s (src=%d, dest=%d)",
                     device_config.id,
                     self._device_params[device_config.id]["source_node"],
                     self._device_params[device_config.id]["dest_node"])
        self._log_debug("system", "device_create",
                        f"FINS device created: {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_params.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock内保护
        await self._clear_default_device_async(device_id)
        logger.info("FINS device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"FINS device removed: {device_id}",
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
        """内部同步：更新 FINS 内存区，绕过访问控制检查。"""
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return
        behavior._values[point_name] = value
        behavior._sync_value_to_area(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": desc("listen_address", "FINS server listen address")},
                "port": {"type": "integer", "default": 9600, "description": desc("fins_port", "FINS port (default 9600, TCP+UDP shared)")},
            },
        }


class FinsUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: FinsServer):
        self._server = server
        self._transport = None

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple):
        # FINS UDP帧: 帧头10字节(ICF+RSV+GW+DNA+DA1+DA2+SNA+SA1+SA2+SID) + MRC+SRC+数据
        if len(data) < 12:
            return
        fins_header = data[:10]
        mrc = data[10]
        src = data[11]
        fins_data = data[12:]
        response = self._process_fins_udp(mrc, src, fins_data, fins_header)
        if response and self._transport:
            self._transport.sendto(response, addr)

    def _process_fins_udp(self, mrc: int, src: int, data: bytes, header: bytes) -> bytes | None:
        server = self._server
        if server is None:  # FIXED-N05: 服务器未初始化时忽略UDP报文
            return None
        if mrc == 0x01 and src == 0x01:
            return self._handle_memory_read_udp(data, header)
        elif mrc == 0x02 and src == 0x01:
            return self._handle_memory_write_udp(data, header)
        elif mrc == 0x05 and src == 0x01:
            return self._handle_controller_read_udp(data, header)
        return None

    def _swap_fins_header(self, fins_header: bytes) -> bytearray:
        """交换FINS帧头中的源/目标地址，用于构造响应帧"""
        resp_header = bytearray(fins_header)
        # DNA(3) <-> SNA(6), DA1(4) <-> SA1(7), DA2(5) <-> SA2(8)
        resp_header[3], resp_header[6] = resp_header[6], resp_header[3]  # DNA <-> SNA
        resp_header[4], resp_header[7] = resp_header[7], resp_header[4]  # DA1 <-> SA1
        resp_header[5], resp_header[8] = resp_header[8], resp_header[5]  # DA2 <-> SA2
        return resp_header

    def _handle_memory_read_udp(self, data: bytes, header: bytes) -> bytes:
        server = self._server
        if len(data) < 6:
            return bytes(self._swap_fins_header(header)) + bytes([0x01, 0x01]) + b"\x00\x00"
        area = data[0]
        word_addr = struct.unpack(">H", data[1:3])[0]
        data[3]
        word_count = struct.unpack(">H", data[4:6])[0]
        if word_count == 0 or word_count > 1000:  # FIXED-N17: UDP读取word_count上限校验
            return bytes(self._swap_fins_header(header)) + bytes([0x01, 0x01]) + struct.pack(">H", 0x0204)
        behavior = server._behaviors.get(server._default_device_id or "")
        read_size = word_count * 2
        resp_data = bytearray(read_size)
        if behavior:
            resp_data = behavior.read_area(area, word_addr * 2, read_size)
        return bytes(self._swap_fins_header(header)) + bytes([0x01, 0x01]) + struct.pack(">H", 0) + bytes(resp_data)

    def _handle_memory_write_udp(self, data: bytes, header: bytes) -> bytes:
        if len(data) < 6:
            return bytes(self._swap_fins_header(header)) + bytes([0x02, 0x01]) + b"\x00\x00"
        server = self._server
        area = data[0]
        word_addr = struct.unpack(">H", data[1:3])[0]
        data[3]
        word_count = struct.unpack(">H", data[4:6])[0]
        if word_count == 0 or word_count > 1000:  # FIXED-N18: UDP写入word_count上限校验
            return bytes(self._swap_fins_header(header)) + bytes([0x02, 0x01]) + struct.pack(">H", 0x0204)
        write_data = data[6:6 + word_count * 2] if len(data) >= 6 + word_count * 2 else data[6:]
        behavior = server._behaviors.get(server._default_device_id or "")
        if behavior:
            behavior.write_area(area, word_addr * 2, write_data)
            behavior.sync_word_bits_to_points(area, word_addr, write_data)
            behavior.sync_word_write_to_points(area, word_addr, write_data)
        return bytes(self._swap_fins_header(header)) + bytes([0x02, 0x01]) + struct.pack(">H", 0)

    def _handle_controller_read_udp(self, data: bytes, header: bytes) -> bytes:
        server = self._server
        device_config = server._device_configs.get(server._default_device_id or "")
        # FINS控制器读取响应数据布局(End Code之后):
        # Controller Model(1) + Controller Version(1) + System Version(2) + Controller Name(20) + Status(2) = 26 bytes
        controller_data = bytearray(26)
        controller_data[0] = 0x01  # Controller Model
        controller_data[1] = 0x01  # Controller Version
        controller_data[2:4] = struct.pack(">H", 0x0100)  # System Version V1.00
        if device_config:
            name_bytes = device_config.name.encode("ascii", errors="replace")[:20]
            controller_data[4:24] = name_bytes.ljust(20, b"\x00")
        else:
            controller_data[4:24] = b"ProtoForge-FINS\x00\x00\x00\x00"[:20]
        controller_data[24:26] = struct.pack(">H", 0x0000)  # Controller Status: Normal
        return bytes(self._swap_fins_header(header)) + bytes([0x05, 0x01]) + struct.pack(">H", 0) + bytes(controller_data)

    def error_received(self, exc):
        logger.warning("FINS UDP error received: %s", exc)
