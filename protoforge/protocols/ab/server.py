import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DynamicValueGenerator

logger = logging.getLogger(__name__)

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


class AbDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        self._tags: dict[str, Any] = {}
        self._data_types: dict[str, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                data_type = str(p.data_type) if hasattr(p, 'data_type') else p.get("data_type", "int32")
                self._points[name] = p
                self._values[name] = fixed_val if fixed_val is not None else 0
                self._generators[name] = DynamicValueGenerator(p)
                self._tags[name] = fixed_val if fixed_val is not None else 0
                self._data_types[name] = data_type

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._tags[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._tags[point_name] = value

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)

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
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("AB EtherNet/IP server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"AB服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start AB server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logger.warning("AB server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("AB server stopped")
            self._log_debug("system", "server_stop", "AB服务停止")

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
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

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
            return self._make_eip_response(0x0066, session, b"")
        elif command == 0x006F:
            return self._handle_send_rr_data(data)
        elif command == 0x0070:
            return self._handle_send_unit_data(data)
        elif command == 0x0001:
            return self._handle_list_identity(data, session)

        return self._make_eip_error(command, session, 0x01)

    def _handle_list_identity(self, data: bytes, session: int) -> bytes:
        host = self._config.get("host", "0.0.0.0")
        port = self._config.get("port", 44818)
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
        device_name = self._config.get("device_name", "ProtoForge-AB").encode("utf-8")
        identity += struct.pack("<B", len(device_name))
        identity += device_name
        return self._make_eip_response(0x0001, session, bytes(identity))

    def _make_eip_response(self, command: int, session: int, payload: bytes) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", command)
        resp += struct.pack("<H", len(payload))
        resp += struct.pack("<I", session)
        resp += struct.pack("<I", 0x00000000)
        resp += bytes([0, 0, 0, 0, 0, 0, 0, 0])
        resp += struct.pack("<I", 0x00000000)
        resp += payload
        return bytes(resp)

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
        if len(data) < 40:
            return self._make_cip_error_response(session, 0x00, 0x00)
        timeout = struct.unpack("<B", data[14:15])[0] if len(data) > 14 else 10
        item_count = struct.unpack("<H", data[16:18])[0] if len(data) > 17 else 0
        if item_count < 2:
            return self._make_cip_error_response(session, 0x00, 0x00)
        t_o_conn_id = struct.unpack("<I", data[22:26])[0] if len(data) >= 26 else 0
        seq_num = struct.unpack("<H", data[30:32])[0] if len(data) >= 32 else 0
        cip_data = data[34:] if len(data) > 34 else b""
        if len(cip_data) > 2:
            service = cip_data[0]
            if service == 0x4C:
                cip_resp = self._handle_cip_read_tag(session, cip_data)
                return cip_resp
            elif service == 0x4D:
                cip_resp = self._handle_cip_write_tag(session, cip_data)
                return cip_resp
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

    @staticmethod
    def _pack_cip_value(data_type: str, value: Any) -> bytes:
        type_info = _CIP_TYPE_MAP.get(data_type, (0xC1, 4))
        type_code, size = type_info
        if data_type == "bool":
            return bytes([type_code, 0x00, 0x01, 0x00, 0x01 if value else 0x00])
        elif data_type == "string":
            s = str(value).encode("utf-8")
            return struct.pack("<BH", type_code, len(s)) + s + b"\x00"
        elif data_type in ("int16",):
            return struct.pack("<BHh", type_code, size, int(value))
        elif data_type in ("uint16",):
            return struct.pack("<BHH", type_code, size, int(value))
        elif data_type in ("int32",):
            return struct.pack("<BHi", type_code, size, int(value))
        elif data_type in ("uint32",):
            return struct.pack("<BHI", type_code, size, int(value))
        elif data_type in ("float32",):
            return struct.pack("<BHf", type_code, size, float(value))
        elif data_type in ("float64",):
            return struct.pack("<BHd", type_code, size, float(value))
        else:
            return struct.pack("<BHi", type_code, 4, int(value))

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
        offset = 2
        while offset < len(cip_data):
            segment_type = cip_data[offset]
            if segment_type == 0x91:
                offset += 1
                if offset >= len(cip_data):
                    break
                tag_len = cip_data[offset]
                offset += 1 + tag_len
                if tag_len % 2 != 0:
                    offset += 1
            elif segment_type == 0x28:
                offset += 2
            elif segment_type == 0x00:
                offset += 1
            else:
                offset += 1
        return offset

    def _handle_cip_read_tag(self, session: int, cip_data: bytes) -> bytes:
        tag_value = 0
        data_type = "int32"
        behavior = self._behaviors.get(self._default_device_id)
        tag_name = self._parse_cip_tag_path(cip_data)
        if tag_name and behavior:
            tag_value = behavior.get_tag(tag_name)
            if tag_value is None:
                tag_value = behavior.get_value(tag_name)
            data_type = behavior.get_data_type(tag_name)
        elif not tag_name:
            if behavior and behavior._values:
                data_type = "dint"
                tag_value = 0

        cip_resp = bytearray()
        cip_resp += bytes([0xD2])
        cip_resp += bytes([0x00])
        cip_resp += struct.pack("<I", 0x00000000)
        cip_resp += self._pack_cip_value(data_type, tag_value)
        return self._wrap_cip_response(session, cip_resp)

    def _handle_cip_write_tag(self, session: int, cip_data: bytes) -> bytes:
        tag_name = self._parse_cip_tag_path(cip_data)
        behavior = self._behaviors.get(self._default_device_id)
        if tag_name and behavior:
            path_end = self._get_path_end_offset(cip_data)
            if path_end + 2 <= len(cip_data):
                data_type = behavior.get_tag_type(tag_name)
                value_data = cip_data[path_end + 2:]
                write_value = self._unpack_cip_value(data_type, value_data)
                behavior.set_tag(tag_name, write_value)
                self._log_debug("recv", "cip_write",
                                f"写入标签 {tag_name}={write_value}",
                                detail={"tag": tag_name, "value": write_value})

        cip_resp = bytearray()
        cip_resp += bytes([0xCD])
        cip_resp += bytes([0x00])
        cip_resp += struct.pack("<I", 0x00000000)
        return self._wrap_cip_response(session, cip_resp)

    @staticmethod
    def _unpack_cip_value(data_type: str, data: bytes) -> Any:
        try:
            if data_type == "bool" and len(data) >= 5:
                return bool(data[4])
            elif data_type == "bool" and len(data) >= 1:
                return bool(data[0])
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
        except (struct.error, IndexError):
            pass
        return 0

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
        behavior = AbDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        self._device_slots[device_config.id] = proto_config.get("slot", 0)

        logger.info("AB device created: %s (slot=%d)",
                     device_config.id, self._device_slots[device_config.id])
        self._log_debug("system", "device_create",
                        f"创建AB设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._device_slots.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("AB device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除AB设备 {device_id}",
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
                "host": {"type": "string", "default": "0.0.0.0", "description": "EtherNet/IP 服务器监听地址"},
                "port": {"type": "integer", "default": 44818, "description": "EtherNet/IP 端口 (默认44818)"},
            },
        }
