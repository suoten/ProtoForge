import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class FinsDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[dict]):
        self._points = {p["name"]: p for p in points}
        self._values: dict[str, Any] = {}
        self._memory_areas: dict[int, bytearray] = {}
        for p in points:
            self._values[p["name"]] = p.get("fixed_value", 0)

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        return self._values.get(point_name, 0)

    def read_area(self, area: int, offset: int, size: int) -> bytearray:
        if area not in self._memory_areas or len(self._memory_areas[area]) < offset + size:
            self._memory_areas[area] = bytearray(max(offset + size, 1024))
        return self._memory_areas[area][offset:offset + size]

    def write_area(self, area: int, offset: int, data: bytes) -> None:
        size = offset + len(data)
        if area not in self._memory_areas or len(self._memory_areas[area]) < size:
            self._memory_areas[area] = bytearray(max(size, 1024))
        buf = self._memory_areas[area]
        buf[offset:offset + len(data)] = data


class FinsServer(ProtocolServer):
    protocol_name = "fins"
    protocol_display_name = "Omron FINS"

    FINS_TCP_MAGIC = b"FINS"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, FinsDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 9600
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._sid_counter = 1

    async def start(self, config: dict[str, Any]) -> None:
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 9600)
        self._status = ProtocolStatus.RUNNING
        self._server_running = True
        self._server_task = asyncio.create_task(self._serve())
        logger.info("FINS server started on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        self._server_running = False
        self._status = ProtocolStatus.STOPPED
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        logger.info("FINS server stopped")

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("FINS server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("FINS connection from %s", addr)
        try:
            while self._server_running:
                header = await reader.readexactly(8)
                magic = header[0:4]
                if magic != self.FINS_TCP_MAGIC:
                    break
                body_len = struct.unpack(">I", header[4:8])[0]
                body = await reader.readexactly(body_len) if body_len > 0 else b""
                response = self._process_fins(body)
                if response:
                    resp_header = self.FINS_TCP_MAGIC + struct.pack(">I", len(response))
                    writer.write(resp_header + response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

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

        fins_frame = data[8:]
        if len(fins_frame) < 12:
            return self._make_fins_error(0x0204)

        mrc = fins_frame[10]
        src = fins_frame[11]

        if mrc == 0x01:
            return self._handle_memory_read(data, fins_frame)
        elif mrc == 0x02:
            return self._handle_memory_write(data, fins_frame)
        elif mrc == 0x05:
            return self._handle_controller_read(data, fins_frame)

        return self._make_fins_error(0x0204)

    def _handle_memory_read(self, data: bytes, fins_frame: bytes) -> bytes:
        if len(fins_frame) < 16:
            return self._make_fins_error(0x0204)

        area = fins_frame[12]
        word_addr = struct.unpack(">H", fins_frame[13:15])[0]
        bit_addr = fins_frame[15]
        word_count = struct.unpack(">H", fins_frame[16:18])[0] if len(fins_frame) >= 18 else 1

        read_size = word_count * 2
        read_data = bytearray(read_size)
        for behavior in self._behaviors.values():
            read_data = behavior.read_area(area, word_addr * 2, read_size)
            break

        resp = bytearray()
        resp += struct.pack(">H", 0x0002)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">I", 0x00000000)
        resp += fins_frame[0:10]
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
        for behavior in self._behaviors.values():
            behavior.write_area(area, word_addr * 2, write_data)
            break

        resp = bytearray()
        resp += struct.pack(">H", 0x0002)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">I", 0x00000000)
        resp += fins_frame[0:10]
        resp += struct.pack(">H", 0x0000)

        return bytes(resp)

    def _handle_controller_read(self, data: bytes, fins_frame: bytes) -> bytes:
        controller_data = bytearray(28)
        controller_data[0:2] = struct.pack(">H", 0x0000)
        controller_data[2:4] = struct.pack(">H", 0x0000)
        controller_data[4:6] = b"PF"
        controller_data[6:20] = b"ProtoForge-FINS\x00"
        controller_data[20:22] = struct.pack(">H", 0x0100)

        resp = bytearray()
        resp += struct.pack(">H", 0x0002)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">I", 0x00000000)
        resp += fins_frame[0:10]
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
        behavior = FinsDeviceBehavior([p.model_dump() for p in device_config.points])
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        logger.info("FINS device created: %s", device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        logger.info("FINS device removed: %s", device_id)

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
        return await behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "FINS 服务器监听地址"},
                "port": {"type": "integer", "default": 9600, "description": "FINS 端口 (默认9600)"},
            },
        }
