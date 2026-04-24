import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class AbDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[dict]):
        self._points = {p["name"]: p for p in points}
        self._values: dict[str, Any] = {}
        self._tags: dict[str, Any] = {}
        for p in points:
            self._values[p["name"]] = p.get("fixed_value", 0)
            self._tags[p["name"]] = p.get("fixed_value", 0)

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._tags[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._tags[point_name] = value

    def get_value(self, point_name: str) -> Any:
        return self._values.get(point_name, 0)

    def get_tag(self, tag_name: str) -> Any:
        return self._tags.get(tag_name, 0)

    def set_tag(self, tag_name: str, value: Any) -> None:
        self._tags[tag_name] = value
        self._values[tag_name] = value


class AbServer(ProtocolServer):
    protocol_name = "ab"
    protocol_display_name = "Rockwell AB"

    EIP_HEADER_SIZE = 24

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, AbDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 44818
        self._session_handle = 1
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 44818)
        self._status = ProtocolStatus.RUNNING
        self._server_running = True
        self._server_task = asyncio.create_task(self._serve())
        logger.info("AB EtherNet/IP server started on %s:%d", self._host, self._port)

    async def stop(self) -> None:
        self._server_running = False
        self._status = ProtocolStatus.STOPPED
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        logger.info("AB server stopped")

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
            logger.error("AB server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("AB connection from %s", addr)
        try:
            while self._server_running:
                data = await reader.read(4096)
                if not data:
                    break
                response = self._process_eip(data)
                if response:
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _process_eip(self, data: bytes) -> bytes | None:
        if len(data) < self.EIP_HEADER_SIZE:
            return None

        command = struct.unpack("<H", data[0:2])[0]
        length = struct.unpack("<H", data[2:4])[0]
        session = struct.unpack("<I", data[4:8])[0]
        status = struct.unpack("<I", data[8:12])[0]

        if command == 0x0065:
            return self._handle_register_session(data)
        elif command == 0x0066:
            return None
        elif command == 0x006F:
            return self._handle_send_rr_data(data)
        elif command == 0x0070:
            return self._handle_send_unit_data(data)
        elif command == 0x0001:
            return None

        return self._make_eip_error(command, session, 0x01)

    def _handle_register_session(self, data: bytes) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0x0065)
        resp += struct.pack("<H", 0x0004)
        new_session = self._session_handle
        self._session_handle += 1
        resp += struct.pack("<I", new_session)
        resp += struct.pack("<I", 0x00000000)
        resp += bytes([0, 0, 0, 0, 0, 0, 0, 0])
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", 0x0001)
        resp += struct.pack("<H", 0x0000)
        return bytes(resp)

    def _handle_send_rr_data(self, data: bytes) -> bytes:
        if len(data) < self.EIP_HEADER_SIZE + 6:
            return self._make_eip_error(0x006F, struct.unpack("<I", data[4:8])[0], 0x01)

        session = struct.unpack("<I", data[4:8])[0]

        cip_offset = 30
        if len(data) <= cip_offset + 2:
            return self._make_eip_error(0x006F, session, 0x01)

        cip_service = data[cip_offset]
        cip_data = data[cip_offset:]

        if cip_service == 0x0E:
            return self._handle_cip_forward_open(session, cip_data)
        elif cip_service == 0x4C:
            return self._handle_cip_forward_close(session, cip_data)
        elif cip_service == 0x52:
            return self._handle_cip_read_tag(session, cip_data)
        elif cip_service == 0x4D:
            return self._handle_cip_write_tag(session, cip_data)

        return self._make_cip_error_response(session, cip_service, 0x01)

    def _handle_send_unit_data(self, data: bytes) -> bytes:
        session = struct.unpack("<I", data[4:8])[0]
        return self._make_cip_error_response(session, 0x00, 0x00)

    def _handle_cip_forward_open(self, session: int, cip_data: bytes) -> bytes:
        cip_resp = bytearray()
        cip_resp += bytes([0xD6])
        cip_resp += bytes([0x00])
        cip_resp += struct.pack("<I", 0x00000000)
        cip_resp += struct.pack("<H", 0x0100)
        cip_resp += struct.pack("<H", 0x0002)
        cip_resp += struct.pack("<I", 0x00000042)
        cip_resp += struct.pack("<I", 0x00000042)
        return self._wrap_cip_response(session, cip_resp)

    def _handle_cip_forward_close(self, session: int, cip_data: bytes) -> bytes:
        cip_resp = bytearray()
        cip_resp += bytes([0xCE])
        cip_resp += bytes([0x00])
        cip_resp += struct.pack("<I", 0x00000000)
        return self._wrap_cip_response(session, cip_resp)

    def _handle_cip_read_tag(self, session: int, cip_data: bytes) -> bytes:
        tag_value = 0
        if len(cip_data) > 6:
            tag_len = struct.unpack("<H", cip_data[2:4])[0]
            if len(cip_data) >= 4 + tag_len:
                tag_name = cip_data[4:4 + tag_len].decode("ascii", errors="replace").rstrip("\x00")
                for behavior in self._behaviors.values():
                    tag_value = behavior.get_tag(tag_name)
                    if tag_value is None:
                        tag_value = behavior.get_value(tag_name)
                    break
        else:
            for behavior in self._behaviors.values():
                if behavior._values:
                    first_key = list(behavior._values.keys())[0]
                    tag_value = behavior.get_value(first_key)
                break

        cip_resp = bytearray()
        cip_resp += bytes([0xD2])
        cip_resp += bytes([0x00])
        cip_resp += struct.pack("<I", 0x00000000)
        cip_resp += bytes([0xC1, 0x00])
        cip_resp += struct.pack("<H", 4)
        cip_resp += struct.pack("<i", int(tag_value))
        return self._wrap_cip_response(session, cip_resp)

    def _handle_cip_write_tag(self, session: int, cip_data: bytes) -> bytes:
        if len(cip_data) > 6:
            tag_len = struct.unpack("<H", cip_data[2:4])[0]
            if len(cip_data) >= 4 + tag_len + 6:
                tag_name = cip_data[4:4 + tag_len].decode("ascii", errors="replace").rstrip("\x00")
                write_value = struct.unpack("<i", cip_data[4 + tag_len + 2:4 + tag_len + 6])[0]
                for behavior in self._behaviors.values():
                    behavior.set_tag(tag_name, write_value)
                    break

        cip_resp = bytearray()
        cip_resp += bytes([0xCD])
        cip_resp += bytes([0x00])
        cip_resp += struct.pack("<I", 0x00000000)
        return self._wrap_cip_response(session, cip_resp)

    def _wrap_cip_response(self, session: int, cip_data: bytes) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0x006F)
        resp += struct.pack("<H", len(cip_data) + 16)
        resp += struct.pack("<I", session)
        resp += struct.pack("<I", 0x00000000)
        resp += bytes([0, 0, 0, 0, 0, 0, 0, 0])
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", 0x0000)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<H", 0x0000)
        resp += struct.pack("<H", 0x0000)
        resp += struct.pack("<H", 0x00B2)
        resp += struct.pack("<H", len(cip_data))
        resp += cip_data
        return bytes(resp)

    def _make_cip_error_response(self, session: int, service: int, error: int) -> bytes:
        cip_resp = bytearray()
        cip_resp += bytes([(service | 0x80) & 0xFF])
        cip_resp += bytes([0x00])
        cip_resp += struct.pack("<I", 0x00000000)
        cip_resp += bytes([error])
        return self._wrap_cip_response(session, cip_resp)

    def _make_eip_error(self, command: int, session: int, status: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", command)
        resp += struct.pack("<H", 0x0000)
        resp += struct.pack("<I", session)
        resp += struct.pack("<I", status)
        resp += bytes([0, 0, 0, 0, 0, 0, 0, 0])
        resp += struct.pack("<I", 0x00000000)
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = AbDeviceBehavior([p.model_dump() for p in device_config.points])
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        logger.info("AB device created: %s", device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        logger.info("AB device removed: %s", device_id)

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
                "host": {"type": "string", "default": "0.0.0.0", "description": "EtherNet/IP 服务器监听地址"},
                "port": {"type": "integer", "default": 44818, "description": "EtherNet/IP 端口 (默认44818)"},
            },
        }
