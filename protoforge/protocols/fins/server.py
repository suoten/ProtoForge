import asyncio
import logging
import re
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import StandardDeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.core.messages import msg, desc

logger = logging.getLogger(__name__)


class FinsDeviceBehavior(StandardDeviceBehavior):
    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._memory_areas: dict[int, bytearray] = {}
        self._point_addresses: dict[str, tuple[int, int]] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                address = getattr(p, 'address', '0') or '0'
                area, offset = self._parse_fins_address(str(address))
                self._point_addresses[name] = (area, offset)
                self._sync_value_to_area(name, self._values.get(name, 0))

    # FIXED-P0: FINS标准符号地址到区域代码映射
    _FINS_AREA_MAP = {
        'CIO': 0xB0, 'WR': 0xB1, 'W': 0xB1, 'HR': 0xB2, 'H': 0xB2,
        'AR': 0xB3, 'A': 0xB3, 'DM': 0x82, 'D': 0x82,
        'EM': 0x90, 'E': 0x90, 'TIM': 0x09, 'T': 0x09,
        'CNT': 0x08, 'C': 0x08,
    }

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

    def _sync_value_to_area(self, point_name: str, value: Any) -> None:
        if point_name not in self._point_addresses:
            return
        area, offset = self._point_addresses[point_name]
        try:
            point = self._points.get(point_name)
            dt = str(point.data_type) if point and hasattr(point, 'data_type') else ""
            if dt in ("float32",) or (not dt and isinstance(value, float)):
                data = struct.pack(">f", float(value))
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
                data = str(value).encode("utf-8")
            else:
                data = struct.pack(">h", int(value) & 0xFFFF)
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
            logger.error("Failed to start FINS server: %s", e)
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
            self._handle_connection, self._host, self._port
        )
        transport, _ = await loop.create_datagram_endpoint(
            lambda: FinsUdpProtocol(self), local_addr=(self._host, self._port)
        )
        self._udp_transport = transport
        try:
            async with tcp_server:
                await tcp_server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("FINS server task cancelled")
        except Exception as e:
            logger.error("FINS server error: %s", e)
            self._status = ProtocolStatus.ERROR
        finally:
            if self._udp_transport:
                self._udp_transport.close()

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("FINS connection from %s", addr)
        _READ_TIMEOUT = 30  # FIXED: Slowloris防护—无超时reader.readexactly可被恶意连接永久阻塞
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
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_fins(self, data: bytes) -> bytes | None:
        if len(data) < 8:
            return None

        command = struct.unpack(">H", data[0:2])[0]
        if command == 0x0000:
            return self._handle_fins_init(data)
        elif command == 0x0001:
            return self._handle_fins_init(data)
        elif command == 0x0002:
            return self._handle_fins_send(data)
        elif command == 0x0003:
            return self._handle_fins_send(data)

        return self._make_fins_error(0x0204)

    def _handle_fins_init(self, data: bytes) -> bytes:
        client_node = 0
        if len(data) >= 8:
            client_node = data[7]

        server_node = 1
        resp = bytearray()
        resp += struct.pack(">H", 0x0001)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">I", 0x00000000)
        resp += bytes([client_node, server_node])
        return bytes(resp)

    def _handle_fins_send(self, data: bytes) -> bytes:
        if len(data) < 12:
            return self._make_fins_error(0x0204)

        # FINS TCP命令帧body: Command(2)+Reserved(2)+Error(4)+DestAddr(2)=10字节前缀
        # FINS帧从data[10]开始，帧头10字节: ICF+RSV+GW+DNA+DA1+DA2+SNA+SA1+SA2+SID
        fins_frame = data[10:]
        if len(fins_frame) < 12:
            return self._make_fins_error(0x0204)

        mrc = fins_frame[10]
        src = fins_frame[11]

        if mrc == 0x01 and src == 0x01:  # FIXED-P1: 同时检查MRC和SRC，0x0101=内存区读取
            return self._handle_memory_read(data, fins_frame)
        elif mrc == 0x01 and src == 0x02:  # FIXED-P1: 0x0102=内存区写入
            return self._handle_memory_write(data, fins_frame)
        elif mrc == 0x02 and src == 0x01:  # 0x0201=内存区写入(旧格式)
            return self._handle_memory_write(data, fins_frame)
        elif mrc == 0x05 and src == 0x01:  # 0x0501=控制器读取
            return self._handle_controller_read(data, fins_frame)

        return self._make_fins_error(0x0204)

    def _swap_fins_header(self, fins_header: bytes) -> bytearray:
        """交换FINS帧头中的源/目标地址，用于构造响应帧"""
        resp_header = bytearray(fins_header)
        # DNA(3) <-> SNA(6), DA1(4) <-> SA1(7), DA2(5) <-> SA2(8)
        resp_header[3], resp_header[6] = resp_header[6], resp_header[3]  # DNA <-> SNA
        resp_header[4], resp_header[7] = resp_header[7], resp_header[4]  # DA1 <-> SA1
        resp_header[5], resp_header[8] = resp_header[8], resp_header[5]  # DA2 <-> SA2
        return resp_header

    def _handle_memory_read(self, data: bytes, fins_frame: bytes) -> bytes:
        if len(fins_frame) < 16:
            return self._make_fins_error(0x0204)

        area = fins_frame[12]
        word_addr = struct.unpack(">H", fins_frame[13:15])[0]
        bit_addr = fins_frame[15]
        word_count = struct.unpack(">H", fins_frame[16:18])[0] if len(fins_frame) >= 18 else 1

        read_size = word_count * 2
        read_data = bytearray(read_size)
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            read_data = behavior.read_area(area, word_addr * 2, read_size)

        resp = bytearray()
        resp += struct.pack(">H", 0x0002)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">I", 0x00000000)
        resp += bytes(self._swap_fins_header(fins_frame[0:10]))
        resp += struct.pack(">H", 0x0000)
        resp += read_data

        return bytes(resp)

    def _handle_memory_write(self, data: bytes, fins_frame: bytes) -> bytes:
        if len(fins_frame) < 16:
            return self._make_fins_error(0x0204)

        area = fins_frame[12]
        word_addr = struct.unpack(">H", fins_frame[13:15])[0]
        bit_addr = fins_frame[15]
        word_count = struct.unpack(">H", fins_frame[16:18])[0] if len(fins_frame) >= 18 else 1

        write_data = fins_frame[18:18 + word_count * 2] if len(fins_frame) >= 18 + word_count * 2 else b""
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            behavior.write_area(area, word_addr * 2, write_data)
            for name, (p_area, p_offset) in behavior._point_addresses.items():
                if p_area == area and p_offset == word_addr * 2:
                    try:
                        pt = behavior._points.get(name)
                        dt = str(pt.data_type) if pt and hasattr(pt, 'data_type') else ""
                        if dt in ("float32",) and len(write_data) >= 4:
                            behavior._values[name] = struct.unpack(">f", write_data[:4])[0]
                        elif dt in ("float64",) and len(write_data) >= 8:
                            behavior._values[name] = struct.unpack(">d", write_data[:8])[0]
                        elif dt in ("int16",) and len(write_data) >= 2:
                            behavior._values[name] = struct.unpack(">h", write_data[:2])[0]
                        elif dt in ("uint16",) and len(write_data) >= 2:
                            behavior._values[name] = struct.unpack(">H", write_data[:2])[0]
                        elif dt in ("int32", "dint") and len(write_data) >= 4:
                            behavior._values[name] = struct.unpack(">i", write_data[:4])[0]
                        elif dt in ("uint32",) and len(write_data) >= 4:
                            behavior._values[name] = struct.unpack(">I", write_data[:4])[0]
                        elif dt in ("bool",) and len(write_data) >= 1:
                            behavior._values[name] = bool(write_data[0])
                        elif len(write_data) >= 4:
                            behavior._values[name] = struct.unpack(">f", write_data[:4])[0]
                        elif len(write_data) >= 2:
                            behavior._values[name] = struct.unpack(">h", write_data[:2])[0]
                    except (struct.error, IndexError) as e:
                        logger.warning("FINS write value sync error for %s: %s", name, e)
                    break
            self._log_debug("recv", "fins_write",
                            f"Write area {area} offset {word_addr}",
                            detail={"area": area, "offset": word_addr, "len": len(write_data)})

        resp = bytearray()
        resp += struct.pack(">H", 0x0002)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">I", 0x00000000)
        resp += bytes(self._swap_fins_header(fins_frame[0:10]))
        resp += struct.pack(">H", 0x0000)

        return bytes(resp)

    def _handle_controller_read(self, data: bytes, fins_frame: bytes) -> bytes:
        device_config = self._device_configs.get(self._default_device_id)
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
        resp += struct.pack(">H", 0x0002)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">I", 0x00000000)
        resp += bytes(self._swap_fins_header(fins_frame[0:10]))
        resp += struct.pack(">H", 0x0000)
        resp += controller_data

        return bytes(resp)

    def _make_fins_error(self, error_code: int) -> bytes:
        resp = bytearray()
        resp += struct.pack(">H", 0x0002)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">I", error_code)
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
        bit_addr = data[3]
        word_count = struct.unpack(">H", data[4:6])[0]
        behavior = server._behaviors.get(server._default_device_id)
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
        bit_addr = data[3]
        word_count = struct.unpack(">H", data[4:6])[0]
        write_data = data[6:6 + word_count * 2] if len(data) >= 6 + word_count * 2 else data[6:]
        behavior = server._behaviors.get(server._default_device_id)
        if behavior:
            behavior.write_area(area, word_addr * 2, write_data)
        return bytes(self._swap_fins_header(header)) + bytes([0x02, 0x01]) + struct.pack(">H", 0)

    def _handle_controller_read_udp(self, data: bytes, header: bytes) -> bytes:
        server = self._server
        device_config = server._device_configs.get(server._default_device_id)
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
