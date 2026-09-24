"""Mitsubishi MELSEC MC 协议仿真服务器.

本模块实现了三菱 MC (Mitsubishi Communication) 协议的仿真服务器，
支持以下功能:
    - MC/Binary 协议帧解析
    - 位设备 (X/Y/M/S/T/C) 读写
    - 字设备 (D/R/ZR) 读写
    - 随机读写 (Random Read/Write)
    - 批量读取 (Batch Read)

支持与以下真实设备对接:
    - Mitsubishi Q/L/R/iQ-R 系列 PLC
    - 任何标准 MC 协议客户端
"""

import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.observability.messages import desc
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 120  # FIXED: Increase from 30s to 120s to prevent idle connection close when multiple devices share the scheduler


class McDeviceBehavior(StandardDeviceBehavior):
    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._device_memory: dict[int, bytearray] = {}
        self._point_addresses: dict[str, tuple[int, int]] = {}
        self._point_data_types: dict[str, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                address = getattr(p, 'address', '0') or '0'
                device_code, offset = self._parse_mc_address(str(address))
                self._point_addresses[name] = (device_code, offset)
                data_type = getattr(p, 'data_type', None)
                if data_type is not None:
                    self._point_data_types[name] = data_type.value if hasattr(data_type, 'value') else str(data_type)
                self._sync_value_to_memory(name, self._values.get(name, 0))

    # FIXED: 采用 SLMP/MELSEC 规范的二进制设备代码（而非 ASCII 字母码），
    # 与真实三菱 PLC 及标准 MC 客户端（如 EdgeLite）保持一致。
    DEVICE_CODE_MAP: dict[str, int] = {
        'D': 0xA8, 'R': 0xAF, 'ZR': 0xB4, 'M': 0x90,
        'X': 0x9C, 'Y': 0x9D, 'B': 0xA0, 'W': 0xB4,
        'T': 0xC2, 'C': 0xC4, 'L': 0x92, 'F': 0x93,
        'V': 0x94, 'S': 0x98, 'Z': 0xCC, 'SM': 0x93, 'SD': 0xA9,
    }

    @staticmethod
    def _parse_mc_address(address: str) -> tuple[int, int]:
        try:
            if ':' in address:
                parts = address.split(':')
                device_code = int(parts[0])
                offset = int(parts[1]) if len(parts) > 1 else 0
                return (device_code, offset)
            import re
            match = re.match(r'^([A-Za-z]+)(\d+)$', address)
            if match:
                name = match.group(1).upper()
                # FIXED-P2: X/Y设备地址使用十六进制解析
                offset = int(match.group(2), 16) if name in ('X', 'Y') else int(match.group(2))
                code = McDeviceBehavior.DEVICE_CODE_MAP.get(name, 0x44)
                return (code, offset)
            return (0x44, int(address))
        except (ValueError, IndexError):
            return (0x44, 0)

    def _sync_value_to_memory(self, point_name: str, value: Any) -> None:
        if point_name not in self._point_addresses:
            return
        device_code, offset = self._point_addresses[point_name]
        data_type = self._point_data_types.get(point_name, "")
        try:
            if data_type == "bool":
                # SLMP 位设备线上布局：点 n 存于第 n//2 字节的半字节（偶数点=bit4 高半字节，
                # 奇数点=bit0 低半字节），与 pymcprotocol/真实 Q/iQ-R PLC 一致。
                self.set_bit_in_memory(device_code, offset, bool(value))
                return
            if data_type == "int32":
                data = struct.pack("<i", int(value))
            elif data_type == "uint32":
                data = struct.pack("<I", int(value))
            elif data_type == "float64":
                data = struct.pack("<d", float(value))
            elif data_type == "float32" or isinstance(value, float):
                data = struct.pack("<f", float(value))
            elif data_type == "int16":
                data = struct.pack("<h", int(value))
            elif data_type == "uint16":
                data = struct.pack("<H", int(value))
            else:
                data = struct.pack("<H", int(value) & 0xFFFF)
            self.write_memory(device_code, offset, data)
        except (ValueError, TypeError, struct.error) as e:
            logger.warning("MC on_write value conversion error for %s: %s", point_name, e)

    def set_bit_in_memory(self, area_code: int, point_index: int, value: bool) -> None:
        """按 SLMP 线上位布局写入单个位点（点 n → 第 n//2 字节，偶数点高半字节）。"""
        if area_code not in self._device_memory:
            self._device_memory[area_code] = bytearray(1024)
        buf = self._device_memory[area_code]
        byte_index = point_index // 2
        if len(buf) <= byte_index:
            buf.extend(bytearray(byte_index + 1 - len(buf)))
        nibble = 0x10 if point_index % 2 == 0 else 0x01
        if value:
            buf[byte_index] |= nibble
        else:
            buf[byte_index] &= ~nibble & 0xFF

    def read_bits_from_memory(self, area_code: int, start: int, count: int) -> bytes:
        """按 SLMP 线上位布局读取 count 个位点，返回可直接回包的半字节打包数据。"""
        out = bytearray((count + 1) // 2)
        buf = self._device_memory.get(area_code)
        for i in range(count):
            point_index = start + i
            bit = 0
            if buf is not None:
                byte_index = point_index // 2
                if byte_index < len(buf):
                    byte = buf[byte_index]
                    bit = (byte >> 4) & 1 if point_index % 2 == 0 else byte & 1
            if i % 2 == 0:
                out[i // 2] |= bit << 4
            else:
                out[i // 2] |= bit
        return bytes(out)

    def write_bits_from_wire(self, area_code: int, start: int, data: bytes, count: int) -> None:
        """将位批量写请求的半字节打包数据按线上布局写入内存。

        请求第 i 个点位于 data[i//2] 的 bit4（i 偶）或 bit0（i 奇），
        对应绝对点位 start+i，落库到其自身的字节/半字节位置。
        """
        for i in range(count):
            byte = data[i // 2] if i // 2 < len(data) else 0
            bit = (byte >> 4) & 1 if i % 2 == 0 else byte & 1
            self.set_bit_in_memory(area_code, start + i, bool(bit))

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._written_values[point_name] = value
            self._sync_value_to_memory(point_name, value)
            return True
        return False

    def get_value(self, point_name: str) -> Any:
        """FIXED-JOINT: 覆写 get_value，在生成器产生新值时同步到 MC 内存。

        原问题：StandardDeviceBehavior.get_value() 对 sine/random 等动态生成器
        只更新 _values 字典，不同步到 _device_memory。EdgeLite 通过 SLMP 读取
        的是 _device_memory，导致读到旧值/初始值（如 float32 点位读到 0 或错位值）。
        """
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type"):
                if pt.generator_type.value != "fixed" and point_name in self._written_values:
                    return self._written_values[point_name]
                if pt.generator_type.value != "fixed":
                    value = gen.generate()
                    self._values[point_name] = value
                    self._sync_value_to_memory(point_name, value)
                    return value
        return self._values.get(point_name, 0)

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        if point_name in self._point_addresses:
            area_code, offset = self._point_addresses[point_name]
            try:
                data = struct.pack("<h", int(value))
                self.write_memory(area_code, offset, data)
            except (ValueError, TypeError, struct.error) as e:
                logger.warning("MC on_write value conversion error for %s: %s", point_name, e)

    def read_memory(self, area_code: int, size: int) -> bytearray:
        if area_code not in self._device_memory:
            self._device_memory[area_code] = bytearray(max(size, 1024))
        buf = self._device_memory[area_code]
        if len(buf) < size:
            buf.extend(bytearray(size - len(buf)))
        return buf[:size]

    def read_memory_offset(self, area_code: int, offset: int, size: int) -> bytearray:
        """FIXED-H04: 带偏移量的内存读取，含越界保护"""
        if area_code not in self._device_memory:
            self._device_memory[area_code] = bytearray(1024)
        buf = self._device_memory[area_code]
        end = offset + size
        if end > len(buf):
            buf.extend(bytearray(end - len(buf)))
        return buf[offset:offset + size]

    def write_memory(self, area_code: int, offset: int, data: bytes) -> None:
        if area_code not in self._device_memory:
            self._device_memory[area_code] = bytearray(1024)
        buf = self._device_memory[area_code]
        end = offset + len(data)
        if end > len(buf):
            buf.extend(bytearray(end - len(buf)))
        buf[offset:offset + len(data)] = data


class McServer(ProtocolServer):
    protocol_name = "mc"
    protocol_display_name = "Mitsubishi MC"

    SLMP_3E_BIN_SUBHEADER = 0x5000
    SLMP_3E_ASCII_SUBHEADER = b"5000"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, McDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_params: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 5000
        self._network = 0
        self._station = 0
        self._pc = 0xFF
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 5000)
        self._validate_port(self._port)
        self._network = config.get("network", 0)
        self._station = config.get("station", 0)
        self._pc = config.get("pc", 0xFF)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("MC server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"MC service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start MC server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("MC task cancelled")
        except Exception as e:
            logger.warning("MC server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("MC server stopped")
            self._log_debug("system", "server_stop", "MC service stopped")

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("MC server task cancelled")
        except Exception as e:
            logger.exception("MC server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("MC connection from %s", addr)
        try:
            while self._server_running:
                header = await asyncio.wait_for(reader.readexactly(9), timeout=_READ_TIMEOUT)
                if len(header) < 9:
                    break
                if header[:4] == self.SLMP_3E_ASCII_SUBHEADER:
                    # FIXED-P0: ASCII SLMP 3E帧头需22字节(子头4+网络2+PC2+目标IO4+目标站2+数据长度4+定时器4)
                    # 已读9字节，还需读13字节完成帧头
                    ascii_header_rest = await asyncio.wait_for(reader.readexactly(13), timeout=_READ_TIMEOUT)
                    ascii_header = header + ascii_header_rest
                    try:
                        data_len_field = int(ascii_header[14:18], 16)  # FIXED-P0: ASCII数据长度在偏移14-17(4字节16进制)
                    except (ValueError, IndexError):
                        break
                    remaining = await asyncio.wait_for(reader.readexactly(data_len_field), timeout=_READ_TIMEOUT)
                    data = ascii_header + remaining
                else:
                    data_len = struct.unpack("<H", header[7:9])[0]
                    total_len = 9 + data_len
                    remaining = await asyncio.wait_for(reader.readexactly(total_len - 9), timeout=_READ_TIMEOUT)
                    data = header + remaining
                response = self._process_slmp(data)
                if response:
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError, asyncio.TimeoutError,
                asyncio.IncompleteReadError, ConnectionAbortedError, BrokenPipeError) as e:
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))
            logger.debug("Connection handler error: %s", e)  # FIXED: 添加日志记录，避免异常被静默吞掉
        except Exception as e:  # FIXED-P1: 兜底捕获所有其他异常，避免单个帧处理错误导致整个连接崩溃
            self.record_protocol_error(ProtocolErrorCategory.INTERNAL, str(e))
            logger.exception("MC connection handler unexpected error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_slmp(self, data: bytes) -> bytes | None:
        if len(data) < 11:
            return None

        if data[:4] == self.SLMP_3E_ASCII_SUBHEADER:
            return self._process_slmp_ascii(data)

        subheader = struct.unpack(">H", data[0:2])[0]
        if subheader != self.SLMP_3E_BIN_SUBHEADER:
            return self._make_error_response(data, 0xC059)

        network = data[2]
        pc = data[3]
        struct.unpack("<H", data[4:6])[0]
        req_dest_station = data[6]
        struct.unpack("<H", data[7:9])[0]
        struct.unpack("<H", data[9:11])[0]

        routed_device_id = self._find_device_by_params(network, req_dest_station, pc)

        if len(data) < 15:
            return self._make_error_response(data, 0xC059)

        cmd = struct.unpack("<H", data[11:13])[0]
        subcmd = struct.unpack("<H", data[13:15])[0]
        if cmd == 0x0401:
            return self._handle_read(data, subcmd, routed_device_id)
        elif cmd == 0x0402:
            return self._handle_random_read(data, subcmd, routed_device_id)
        elif cmd == 0x1401:
            return self._handle_write(data, subcmd, routed_device_id)
        elif cmd == 0x1402:
            return self._handle_random_write(data, subcmd, routed_device_id)
        elif cmd == 0x0001:
            return self._handle_self_test(data)

        return self._make_error_response(data, 0xC059)

    # SLMP 3E 二进制帧设备字段布局（pymcprotocol 与真实 PLC 一致）：
    #   Q/经典（子命令 0x0000/0x0001）：设备号 3 字节 LE + 设备码 1 字节
    #   iQ-R（子命令 0x0002/0x0003） ：设备号 4 字节 LE + 设备码 2 字节 LE
    # FIXED-JOINT: 原实现按"设备码在前+设备号在后"解析，导致设备码恒为 0、
    # 偏移错位（D0 被解析为区域 0x00 偏移 0xA80000），线上读写与点位注册表
    # 完全脱节（联调实测：REST 写值后线上读不到；EdgeLite 采集恒为 0）。
    IQR_WORD_SUBCMD = 0x0002
    IQR_BIT_SUBCMD = 0x0003
    Q_WORD_SUBCMD = 0x0000
    Q_BIT_SUBCMD = 0x0001

    def _is_iqr_subcmd(self, subcmd: int) -> bool:
        return subcmd in (self.IQR_WORD_SUBCMD, self.IQR_BIT_SUBCMD)

    def _is_bit_subcmd(self, subcmd: int) -> bool:
        return subcmd in (self.Q_BIT_SUBCMD, self.IQR_BIT_SUBCMD)

    def _parse_device_field(self, data: bytes, offset: int, subcmd: int) -> tuple[int, int, int] | None:
        """解析 SLMP 设备字段，返回 (设备码, 起始地址, 字段结束偏移)；长度不足返回 None。"""
        if self._is_iqr_subcmd(subcmd):
            if offset + 6 > len(data):
                return None
            start_addr = int.from_bytes(data[offset : offset + 4], "little")
            device_code = int.from_bytes(data[offset + 4 : offset + 6], "little")
            return device_code, start_addr, offset + 6
        if offset + 4 > len(data):
            return None
        start_addr = int.from_bytes(data[offset : offset + 3], "little")
        device_code = data[offset + 3]
        return device_code, start_addr, offset + 4

    def _handle_read(self, data: bytes, subcmd: int, device_id: str | None = None) -> bytes:
        if len(data) < 17:
            return self._make_error_response(data, 0xC059)

        parsed = self._parse_device_field(data, 15, subcmd)
        if parsed is None:
            return self._make_error_response(data, 0xC059)
        device_code, start_addr, dev_end = parsed
        if dev_end + 2 > len(data):
            return self._make_error_response(data, 0xC059)
        point_count = struct.unpack("<H", data[dev_end : dev_end + 2])[0]

        if self._is_bit_subcmd(subcmd):
            # 位读数据每字节 2 点打包（高半字节为第 1 点）
            read_len = (point_count + 1) // 2
        elif subcmd in (self.Q_WORD_SUBCMD, self.IQR_WORD_SUBCMD):
            read_len = point_count * 2
        else:
            return self._make_error_response(data, 0xC059)

        lookup_key = device_id or self._default_device_id or ""
        behavior = self._behaviors.get(lookup_key)  # FIXED-P1: 使用路由后的device_id
        if behavior:
            if self._is_bit_subcmd(subcmd):
                read_data = behavior.read_bits_from_memory(device_code, start_addr, point_count)
            else:
                read_data = behavior.read_memory_offset(device_code, start_addr, read_len)  # FIXED-H04: 带偏移读取避免越界
        else:
            read_data = bytearray(read_len)

        resp = bytearray()
        resp += struct.pack("<H", 0x00D0)  # FIXED: 响应子头 D0 00 (SLMP 3E 标准响应子头，原误用请求子头 0x5000 回显)
        resp += bytes([data[2], data[3]])
        resp += struct.pack("<H", struct.unpack("<H", data[4:6])[0])
        resp += bytes([data[6]])
        resp += struct.pack("<H", read_len + 2)
        resp += struct.pack("<H", 0x0000)
        resp += read_data

        return bytes(resp)

    def _handle_write(self, data: bytes, subcmd: int, device_id: str | None = None) -> bytes:
        if len(data) < 17:
            return self._make_error_response(data, 0xC059)

        parsed = self._parse_device_field(data, 15, subcmd)
        if parsed is None:
            return self._make_error_response(data, 0xC059)
        device_code, start_addr, dev_end = parsed
        if dev_end + 2 > len(data):
            return self._make_error_response(data, 0xC059)
        point_count = struct.unpack("<H", data[dev_end : dev_end + 2])[0]

        if self._is_bit_subcmd(subcmd):
            write_len = (point_count + 1) // 2  # 位写数据每字节 2 点打包
        elif subcmd in (self.Q_WORD_SUBCMD, self.IQR_WORD_SUBCMD):
            write_len = point_count * 2
        else:
            return self._make_error_response(data, 0xC059)

        data_start = dev_end + 2
        write_data = data[data_start : data_start + write_len]
        behavior = self._behaviors.get(device_id or self._default_device_id or "")  # FIXED-P1: 使用路由后的device_id
        if behavior:
            if self._is_bit_subcmd(subcmd):
                behavior.write_bits_from_wire(device_code, start_addr, write_data, point_count)
            else:
                behavior.write_memory(device_code, start_addr, write_data)
            is_bit = self._is_bit_subcmd(subcmd)
            for name, (p_code, p_offset) in behavior._point_addresses.items():
                if p_code == device_code and p_offset == start_addr:
                    try:
                        dt = behavior._point_data_types.get(name, "")
                        if is_bit and dt == "bool" and len(write_data) >= 1:
                            # 点位即批写首点：值在首字节高半字节 bit4
                            behavior._values[name] = bool((write_data[0] >> 4) & 1)
                            behavior._written_values[name] = behavior._values[name]
                            continue
                        if dt == "int32" and len(write_data) >= 4:
                            behavior._values[name] = struct.unpack("<i", write_data[:4])[0]
                        elif dt == "uint32" and len(write_data) >= 4:
                            behavior._values[name] = struct.unpack("<I", write_data[:4])[0]
                        elif dt == "float64" and len(write_data) >= 8:
                            behavior._values[name] = struct.unpack("<d", write_data[:8])[0]
                        elif dt == "float32" and len(write_data) >= 4:
                            behavior._values[name] = struct.unpack("<f", write_data[:4])[0]
                        elif dt == "int16" and len(write_data) >= 2:
                            behavior._values[name] = struct.unpack("<h", write_data[:2])[0]
                        elif dt == "uint16" and len(write_data) >= 2:
                            behavior._values[name] = struct.unpack("<H", write_data[:2])[0]
                        elif len(write_data) >= 4:
                            behavior._values[name] = struct.unpack("<f", write_data[:4])[0]
                        elif len(write_data) >= 2:
                            behavior._values[name] = struct.unpack("<H", write_data[:2])[0]
                    except (struct.error, IndexError) as e:
                        logger.warning("MC write value sync error: %s", e)
                    # FIXED-H05: 移除break，遍历所有匹配点而非只更新第一个
            self._log_debug("recv", "mc_write",
                            f"Write device {device_code} offset {start_addr}",
                            detail={"device": device_code, "offset": start_addr, "len": len(write_data)})

        resp = bytearray()
        resp += struct.pack("<H", 0x00D0)  # FIXED: 响应子头 D0 00 (SLMP 3E 标准响应子头，原误用请求子头 0x5000 回显)
        resp += bytes([data[2], data[3]])
        resp += struct.pack("<H", struct.unpack("<H", data[4:6])[0])
        resp += bytes([data[6]])
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<H", 0x0000)

        return bytes(resp)

    def _handle_random_read(self, data: bytes, subcmd: int, device_id: str | None = None) -> bytes:
        if len(data) < 17:
            return self._make_error_response(data, 0xC059)
        try:
            point_count = struct.unpack("<H", data[15:17])[0]
        except (IndexError, struct.error):
            return self._make_error_response(data, 0xC059)
        read_data = bytearray()
        behavior = self._behaviors.get(device_id or self._default_device_id or "")  # FIXED-P1: 使用路由后的device_id
        offset = 17
        for _ in range(min(point_count, 64)):
            parsed = self._parse_device_field(data, offset, subcmd)
            if parsed is None:
                break
            device_code, start_addr, offset = parsed
            if behavior:
                if self._is_bit_subcmd(subcmd):
                    # 位随机读：每点 1 字节，0/1
                    bits = behavior.read_bits_from_memory(device_code, start_addr, 1)
                    read_data += bytes([1 if bits[0] & 0x10 else 0])
                else:
                    read_data += behavior.read_memory_offset(device_code, start_addr, 2)  # FIXED-N06: 带偏移读取避免越界
        resp = bytearray()
        resp += struct.pack("<H", 0x00D0)  # FIXED: 响应子头 D0 00 (SLMP 3E 标准响应子头，原误用请求子头 0x5000 回显)
        resp += bytes([data[2], data[3]])
        resp += struct.pack("<H", struct.unpack("<H", data[4:6])[0])
        resp += bytes([data[6]])
        resp += struct.pack("<H", len(read_data) + 2)
        resp += struct.pack("<H", 0x0000)
        resp += read_data
        return bytes(resp)

    def _handle_random_write(self, data: bytes, subcmd: int, device_id: str | None = None) -> bytes:
        if len(data) < 17:
            return self._make_error_response(data, 0xC059)
        behavior = self._behaviors.get(device_id or self._default_device_id or "")  # FIXED-P1: 使用路由后的device_id
        try:
            point_count = struct.unpack("<H", data[15:17])[0]
        except (IndexError, struct.error):
            return self._make_error_response(data, 0xC059)
        offset = 17
        bit_val_len = 2 if self._is_iqr_subcmd(subcmd) else 1  # iQ-R 位随机写每点 2 字节值，Q 为 1 字节
        for _ in range(min(point_count, 64)):
            parsed = self._parse_device_field(data, offset, subcmd)
            if parsed is None:
                break
            device_code, start_addr, offset = parsed
            if self._is_bit_subcmd(subcmd):
                if offset + bit_val_len > len(data):
                    break
                bit_on = any(data[offset : offset + bit_val_len])
                offset += bit_val_len
                if behavior:
                    behavior.set_bit_in_memory(device_code, start_addr, bit_on)
            else:
                if offset + 2 > len(data):
                    break
                write_val = data[offset : offset + 2]
                offset += 2
                if behavior:
                    behavior.write_memory(device_code, start_addr, write_val)
        resp = bytearray()
        resp += struct.pack("<H", 0x00D0)  # FIXED: 响应子头 D0 00 (SLMP 3E 标准响应子头，原误用请求子头 0x5000 回显)
        resp += bytes([data[2], data[3]])
        resp += struct.pack("<H", struct.unpack("<H", data[4:6])[0])
        resp += bytes([data[6]])
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<H", 0x0000)
        return bytes(resp)

    def _handle_self_test(self, data: bytes) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0x00D0)  # FIXED: 响应子头 D0 00 (SLMP 3E 标准响应子头，原误用请求子头 0x5000 回显)
        if len(data) >= 7:
            resp += data[2:7]
        else:
            resp += bytes([0, 0, 0, 0, 0])
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<H", 0x0000)
        return bytes(resp)

    def _make_error_response(self, data: bytes, error_code: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0x00D0)  # FIXED: 响应子头 D0 00 (SLMP 3E 标准响应子头，原误用请求子头 0x5000 回显)
        if len(data) >= 7:
            resp += data[2:7]
        else:
            resp += bytes([0, 0, 0, 0, 0])
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<H", error_code)
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = McDeviceBehavior(device_config.points)
        proto_config = device_config.protocol_config or {}
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_params[device_config.id] = {  # FIXED-P1: 移入_behaviors_lock内保护
                "network": proto_config.get("network", self._network),
                "station": proto_config.get("station", self._station),
                "pc": proto_config.get("pc", self._pc),
            }
        await self._update_default_device_async(device_config.id)

        logger.info("MC device created: %s (network=%d, station=%d, pc=%d)",
                     device_config.id,
                     self._device_params[device_config.id]["network"],
                     self._device_params[device_config.id]["station"],
                     self._device_params[device_config.id]["pc"])
        self._log_debug("system", "device_create",
                        f"MC device created: {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_params.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock内保护
        await self._clear_default_device_async(device_id)
        logger.info("MC device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"MC device removed: {device_id}",
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
        """内部同步：更新 MC 设备内存，绕过访问控制检查。"""
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return
        behavior._values[point_name] = value
        behavior._sync_value_to_memory(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": desc("listen_address", "MC server listen address")},
                "port": {"type": "integer", "default": 5000, "description": desc("mc_port", "MC port (default 5000)")},
                "network": {"type": "integer", "default": 0, "description": desc("mc_network", "Network number")},
                "station": {"type": "integer", "default": 0, "description": desc("mc_station", "Station number")},
                "pc": {"type": "integer", "default": 255, "description": desc("mc_pc", "PC number (0xFF=self)")},
            },
        }

    def _find_device_by_params(self, network: int, station: int, pc: int) -> str | None:  # FIXED-P1: 根据network/station/pc路由到匹配设备
        # FIXED-JOINT: 当多个设备共享相同的 network/station/pc 时，
        # 原实现返回字典遍历的第一个匹配项，但该设备可能不是请求的目标。
        # 此场景在联调中很常见（多个仿真设备使用默认参数 network=0/station=0/pc=255）。
        # 修复：收集所有匹配设备，如果只有一个则返回它；如果有多个则优先返回
        # _default_device_id（最后创建的设备通常是联调脚本刚推送的目标），
        # 否则返回第一个匹配项以保持向后兼容。
        matches = [
            dev_id for dev_id, params in self._device_params.items()
            if (params.get("network") == network and
                params.get("station") == station and
                params.get("pc") == pc)
        ]
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        # Multiple devices share the same routing params — prefer default device if it matches
        if self._default_device_id in matches:
            return self._default_device_id
        return matches[0]

    @staticmethod
    def _ascii_to_hex(ascii_str: bytes) -> int:
        return int(ascii_str.decode("ascii"), 16)

    @staticmethod
    def _hex_to_ascii(val: int, width: int = 4) -> bytes:
        return format(val, f"0{width}X").encode("ascii")

    def _process_slmp_ascii(self, data: bytes) -> bytes | None:
        if len(data) < 30:
            return None
        try:
            network = self._ascii_to_hex(data[4:6])
            pc = self._ascii_to_hex(data[6:8])
            self._ascii_to_hex(data[8:12])
            req_dest_station = self._ascii_to_hex(data[12:14])
            self._ascii_to_hex(data[14:18])
            self._ascii_to_hex(data[18:22])
            cmd = self._ascii_to_hex(data[22:26])
            subcmd = self._ascii_to_hex(data[26:30])
        except (ValueError, IndexError):
            return self._make_ascii_error_response(data, 0xC059)

        routed_device_id = self._find_device_by_params(network, req_dest_station, pc)

        if cmd == 0x0401:
            return self._handle_read_ascii(data, subcmd, routed_device_id)
        elif cmd == 0x0402:
            return self._handle_random_read_ascii(data, subcmd, routed_device_id)
        elif cmd == 0x1401:
            return self._handle_write_ascii(data, subcmd, routed_device_id)
        elif cmd == 0x1402:
            return self._handle_random_write_ascii(data, subcmd, routed_device_id)
        elif cmd == 0x0001:
            return self._make_ascii_error_response(data, 0x0000)

        return self._make_ascii_error_response(data, 0xC059)

    def _handle_read_ascii(self, data: bytes, subcmd: int, device_id: str | None = None) -> bytes:
        if len(data) < 40:
            return self._make_ascii_error_response(data, 0xC059)
        try:
            start_addr = self._ascii_to_hex(data[30:34])
            device_code = self._ascii_to_hex(data[34:36])
            word_count = self._ascii_to_hex(data[36:40])
        except (ValueError, IndexError):
            return self._make_ascii_error_response(data, 0xC059)

        if subcmd in (0x0000, 0x0002):  # 0x0000=standard word, 0x0002=iQ-R word
            read_len = word_count * 2
        elif subcmd == 0x0001:
            read_len = word_count
        else:
            return self._make_ascii_error_response(data, 0xC059)

        read_data = bytearray(read_len)
        behavior = self._behaviors.get(device_id or self._default_device_id or "")
        if behavior:
            mem = behavior.read_memory(device_code, start_addr + read_len)
            read_data = mem[start_addr:start_addr + read_len]

        resp = bytearray(b"D000")  # FIXED: ASCII 响应子头 D000
        resp += data[4:14]
        resp += self._hex_to_ascii(4 + len(read_data) * 2)
        resp += b"0000"
        for b in read_data:
            resp += self._hex_to_ascii(b, 2)
        return bytes(resp)

    def _handle_write_ascii(self, data: bytes, subcmd: int, device_id: str | None = None) -> bytes:
        if len(data) < 40:
            return self._make_ascii_error_response(data, 0xC059)
        try:
            start_addr = self._ascii_to_hex(data[30:34])
            device_code = self._ascii_to_hex(data[34:36])
            self._ascii_to_hex(data[36:40])
            write_ascii = data[40:]
        except (ValueError, IndexError):
            return self._make_ascii_error_response(data, 0xC059)

        write_data = bytearray()
        for i in range(0, len(write_ascii) - 1, 2):
            try:
                write_data.append(self._ascii_to_hex(write_ascii[i:i + 2]))
            except ValueError:
                break

        behavior = self._behaviors.get(device_id or self._default_device_id or "")
        if behavior:
            behavior.write_memory(device_code, start_addr, bytes(write_data))

        resp = bytearray(b"D000")  # FIXED: ASCII 响应子头 D000
        resp += data[4:14]
        resp += self._hex_to_ascii(4)
        resp += b"0000"
        return bytes(resp)

    def _handle_random_read_ascii(self, data: bytes, subcmd: int, device_id: str | None = None) -> bytes:
        if len(data) < 40:
            return self._make_ascii_error_response(data, 0xC059)
        try:
            point_count = self._ascii_to_hex(data[36:40])
        except (ValueError, IndexError):
            return self._make_ascii_error_response(data, 0xC059)
        read_data = bytearray()
        behavior = self._behaviors.get(device_id or self._default_device_id or "")
        offset = 40
        for _ in range(min(point_count, 64)):
            if offset + 6 > len(data):
                break
            try:
                start_addr = self._ascii_to_hex(data[offset:offset + 4])
                device_code = self._ascii_to_hex(data[offset + 4:offset + 6])
            except (ValueError, IndexError):
                break
            offset += 6
            if behavior:
                if subcmd in (0x0000, 0x0002):  # 0x0000=standard word, 0x0002=iQ-R word
                    mem = behavior.read_memory(device_code, start_addr + 2)
                    read_data += mem[start_addr:start_addr + 2]
                elif subcmd == 0x0001:
                    mem = behavior.read_memory(device_code, start_addr + 1)
                    read_data += mem[start_addr:start_addr + 1]
        resp = bytearray(b"D000")  # FIXED: ASCII 响应子头 D000
        resp += data[4:14]
        resp += self._hex_to_ascii(4 + len(read_data) * 2)
        resp += b"0000"
        for b in read_data:
            resp += self._hex_to_ascii(b, 2)
        return bytes(resp)

    def _handle_random_write_ascii(self, data: bytes, subcmd: int, device_id: str | None = None) -> bytes:
        if len(data) < 40:
            return self._make_ascii_error_response(data, 0xC059)
        behavior = self._behaviors.get(device_id or self._default_device_id or "")
        try:
            point_count = self._ascii_to_hex(data[36:40])
        except (ValueError, IndexError):
            return self._make_ascii_error_response(data, 0xC059)
        offset = 40
        for _ in range(min(point_count, 64)):
            if subcmd in (0x0000, 0x0002):  # 0x0000=standard word, 0x0002=iQ-R word
                if offset + 10 > len(data):
                    break
                try:
                    start_addr = self._ascii_to_hex(data[offset:offset + 4])
                    device_code = self._ascii_to_hex(data[offset + 4:offset + 6])
                    write_ascii = data[offset + 6:offset + 10]
                    write_data = bytearray()
                    for i in range(0, len(write_ascii) - 1, 2):
                        write_data.append(self._ascii_to_hex(write_ascii[i:i + 2]))
                    if behavior:
                        behavior.write_memory(device_code, start_addr, bytes(write_data))
                except (ValueError, IndexError):
                    break
                offset += 10
            elif subcmd == 0x0001:
                if offset + 8 > len(data):
                    break
                try:
                    start_addr = self._ascii_to_hex(data[offset:offset + 4])
                    device_code = self._ascii_to_hex(data[offset + 4:offset + 6])
                    write_ascii = data[offset + 6:offset + 8]
                    write_data = bytearray()
                    for i in range(0, len(write_ascii) - 1, 2):
                        write_data.append(self._ascii_to_hex(write_ascii[i:i + 2]))
                    if behavior:
                        behavior.write_memory(device_code, start_addr, bytes(write_data))
                except (ValueError, IndexError):
                    break
                offset += 8
        resp = bytearray(b"D000")  # FIXED: ASCII 响应子头 D000
        resp += data[4:14]
        resp += self._hex_to_ascii(4)
        resp += b"0000"
        return bytes(resp)

    def _make_ascii_error_response(self, data: bytes, error_code: int) -> bytes:
        resp = bytearray(b"D000")  # FIXED: ASCII 响应子头 D000
        if len(data) >= 14:
            resp += data[4:14]
        resp += self._hex_to_ascii(4)
        resp += self._hex_to_ascii(error_code)
        return bytes(resp)

