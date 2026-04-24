import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class OpcDaDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[dict]):
        self._points = {p["name"]: p for p in points}
        self._values: dict[str, Any] = {}
        self._quality: dict[str, int] = {}
        for p in points:
            self._values[p["name"]] = p.get("fixed_value", 0)
            self._quality[p["name"]] = 192

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._quality[point_name] = 192
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._quality[point_name] = 192

    def get_value(self, point_name: str) -> Any:
        return self._values.get(point_name, 0)

    def get_quality(self, point_name: str) -> int:
        return self._quality.get(point_name, 0)

    def get_all_tags(self) -> dict[str, Any]:
        return dict(self._values)


class OpcDaServer(ProtocolServer):
    protocol_name = "opcda"
    protocol_display_name = "OPC-DA"

    OPCDA_MAGIC = b"PFDA"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, OpcDaDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 51340
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 51340)
        self._status = ProtocolStatus.RUNNING
        self._server_running = True
        self._server_task = asyncio.create_task(self._serve())
        logger.info("OPC-DA server started on %s:%d (TCP bridge mode)", self._host, self._port)

    async def stop(self) -> None:
        self._server_running = False
        self._status = ProtocolStatus.STOPPED
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        logger.info("OPC-DA server stopped")

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
            logger.error("OPC-DA server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("OPC-DA connection from %s", addr)
        try:
            while self._server_running:
                header = await reader.readexactly(8)
                magic = header[0:4]
                if magic != self.OPCDA_MAGIC:
                    break
                body_len = struct.unpack("<I", header[4:8])[0]
                body = await reader.readexactly(body_len) if body_len > 0 else b""
                response = self._process_opcda(body)
                if response:
                    resp_header = self.OPCDA_MAGIC + struct.pack("<I", len(response))
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

    def _process_opcda(self, data: bytes) -> bytes | None:
        if len(data) < 4:
            return None

        cmd = struct.unpack("<I", data[0:4])[0]

        if cmd == 0x0001:
            return self._handle_browse(data)
        elif cmd == 0x0002:
            return self._handle_read(data)
        elif cmd == 0x0003:
            return self._handle_write(data)
        elif cmd == 0x0004:
            return self._handle_subscribe(data)
        elif cmd == 0x0005:
            return self._handle_get_status(data)

        return self._make_error(0x8000)

    def _handle_browse(self, data: bytes) -> bytes:
        tags = []
        for behavior in self._behaviors.values():
            tags.extend(behavior.get_all_tags().keys())
            break

        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", len(tags))
        for tag in tags:
            tag_bytes = tag.encode("utf-8")
            resp += struct.pack("<H", len(tag_bytes))
            resp += tag_bytes
        return bytes(resp)

    def _handle_read(self, data: bytes) -> bytes:
        if len(data) < 8:
            return self._make_error(0x8001)

        tag_len = struct.unpack("<H", data[4:6])[0]
        if len(data) < 6 + tag_len:
            return self._make_error(0x8001)

        tag_name = data[6:6 + tag_len].decode("utf-8", errors="replace")
        value = 0
        quality = 0
        for behavior in self._behaviors.values():
            value = behavior.get_value(tag_name)
            quality = behavior.get_quality(tag_name)
            break

        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<d", float(value))
        resp += struct.pack("<I", quality)
        resp += struct.pack("<d", time.time())
        return bytes(resp)

    def _handle_write(self, data: bytes) -> bytes:
        if len(data) < 16:
            return self._make_error(0x8002)

        tag_len = struct.unpack("<H", data[4:6])[0]
        if len(data) < 6 + tag_len + 8:
            return self._make_error(0x8002)

        tag_name = data[6:6 + tag_len].decode("utf-8", errors="replace")
        value = struct.unpack("<d", data[6 + tag_len:6 + tag_len + 8])[0]

        for behavior in self._behaviors.values():
            behavior.set_value(tag_name, value)
            break

        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        return bytes(resp)

    def _handle_subscribe(self, data: bytes) -> bytes:
        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", 1)
        return bytes(resp)

    def _handle_get_status(self, data: bytes) -> bytes:
        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", 1)
        resp += b"ProtoForge OPC-DA Bridge\x00"
        resp += struct.pack("<I", 8)
        return bytes(resp)

    def _make_error(self, code: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<I", code)
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = OpcDaDeviceBehavior([p.model_dump() for p in device_config.points])
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        logger.info("OPC-DA device created: %s", device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        logger.info("OPC-DA device removed: %s", device_id)

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
                "host": {"type": "string", "default": "0.0.0.0", "description": "OPC-DA 桥接服务器监听地址"},
                "port": {"type": "integer", "default": 51340, "description": "OPC-DA 桥接端口 (默认51340)"},
            },
        }
