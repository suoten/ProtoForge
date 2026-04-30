import asyncio
import contextlib
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior
from protoforge.protocols.behavior import DynamicValueGenerator, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class OpcDaDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        self._quality: dict[str, int] = {}
        self._data_types: dict[str, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                data_type = str(p.data_type) if hasattr(p, 'data_type') else p.get("data_type", "float64")
                self._points[name] = p
                self._values[name] = fixed_val if fixed_val is not None else 0
                self._generators[name] = DynamicValueGenerator(p)
                self._quality[name] = 192
                self._data_types[name] = data_type

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._quality[point_name] = 192
            return True
        self._values[point_name] = value
        self._quality[point_name] = 192
        return True

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._quality[point_name] = 192

    def set_quality(self, point_name: str, quality: int) -> None:
        self._quality[point_name] = quality

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)

    def get_quality(self, point_name: str) -> int:
        return self._quality.get(point_name, 0)

    def get_data_type(self, point_name: str) -> str:
        return self._data_types.get(point_name, "float64")

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
        self._device_params: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 51340
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._subscriptions: dict[int, dict] = {}
        self._next_sub_id: int = 1
        self._sub_clients: dict[int, asyncio.StreamWriter] = {}
        self._sub_push_task: asyncio.Task | None = None

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 51340)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._sub_push_task = asyncio.create_task(self._subscription_push_loop())
            self._status = ProtocolStatus.RUNNING
            logger.info("OPC-DA server started on %s:%d (TCP bridge mode)", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"OPC-DA服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start OPC-DA server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._sub_push_task:
                self._sub_push_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._sub_push_task
            if self._server_task:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task
            for _sid, writer in list(self._sub_clients.items()):
                try:
                    writer.close()
                except Exception as e:
                    logger.debug("OPC-DA subscription writer close error: %s", e)
            self._sub_clients.clear()
            self._subscriptions.clear()
        except Exception as e:
            logger.warning("OPC-DA server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("OPC-DA server stopped")
            self._log_debug("system", "server_stop", "OPC-DA服务停止")

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
        client_sub_ids = []
        try:
            while self._server_running:
                header = await reader.readexactly(8)
                magic = header[0:4]
                if magic != self.OPCDA_MAGIC:
                    break
                body_len = struct.unpack("<I", header[4:8])[0]
                body = await reader.readexactly(body_len) if body_len > 0 else b""
                response, sub_id = self._process_opcda_with_sub(body, writer)
                if response:
                    resp_header = self.OPCDA_MAGIC + struct.pack("<I", len(response))
                    writer.write(resp_header + response)
                    await writer.drain()
                if sub_id:
                    client_sub_ids.append(sub_id)
        except (ConnectionResetError, asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        finally:
            for sid in client_sub_ids:
                self._sub_clients.pop(sid, None)
                self._subscriptions.pop(sid, None)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_opcda_with_sub(self, data: bytes, writer: asyncio.StreamWriter) -> tuple[bytes | None, int | None]:
        if len(data) < 4:
            return self._make_error(0x8000), None
        cmd = struct.unpack("<I", data[0:4])[0]
        if cmd == 0x0004:
            resp, sub_id = self._handle_subscribe_with_client(data, writer)
            return resp, sub_id
        return self._process_opcda(data), None

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
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            tags.extend(behavior.get_all_tags().keys())

        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", len(tags))
        for tag in tags:
            tag_bytes = tag.encode("utf-8")
            resp += struct.pack("<H", len(tag_bytes))
            resp += tag_bytes
        return bytes(resp)

    @staticmethod
    def _pack_typed_value(data_type: str, value: Any) -> bytes:
        if data_type == "bool":
            return struct.pack("<BB", 0, 1 if value else 0)
        elif data_type == "int16":
            return struct.pack("<Bh", 1, int(value))
        elif data_type == "uint16":
            return struct.pack("<BH", 2, int(value))
        elif data_type == "int32":
            return struct.pack("<Bi", 3, int(value))
        elif data_type == "uint32":
            return struct.pack("<BI", 4, int(value))
        elif data_type == "float32":
            return struct.pack("<Bf", 5, float(value))
        elif data_type == "string":
            s = str(value).encode("utf-8")
            return struct.pack("<BH", 7, len(s)) + s
        else:
            return struct.pack("<Bd", 6, float(value))

    def _handle_read(self, data: bytes) -> bytes:
        if len(data) < 8:
            return self._make_error(0x8001)

        tag_len = struct.unpack("<H", data[4:6])[0]
        if len(data) < 6 + tag_len:
            return self._make_error(0x8001)

        tag_name = data[6:6 + tag_len].decode("utf-8", errors="replace")
        value = 0
        quality = 0
        data_type = "float64"
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            value = behavior.get_value(tag_name)
            quality = behavior.get_quality(tag_name)
            data_type = behavior.get_data_type(tag_name)

        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        resp += self._pack_typed_value(data_type, value)
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
        behavior = self._behaviors.get(self._default_device_id)
        if not behavior:
            return self._make_error(0x8001)
        data_type = behavior.get_data_type(tag_name)
        value_data = data[6 + tag_len:]
        value = self._unpack_typed_value(data_type, value_data)
        behavior.set_value(tag_name, value)
        self._log_debug("recv", "opcda_write",
                        f"写入标签 {tag_name}={value}",
                        detail={"tag": tag_name, "value": value})

        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        return bytes(resp)

    @staticmethod
    def _unpack_typed_value(data_type: str, data: bytes) -> Any:
        try:
            if data_type == "bool" and len(data) >= 1:
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
            elif data_type == "float64" and len(data) >= 8 or len(data) >= 8:
                return struct.unpack("<d", data[:8])[0]
        except (struct.error, IndexError) as e:
            logger.warning("OPC-DA value unpack error: %s", e)
        return 0.0

    def _handle_subscribe(self, data: bytes) -> bytes:
        sub_id = self._next_sub_id
        self._next_sub_id += 1
        requested_rate = struct.unpack("<f", data[:4])[0] if len(data) >= 4 else 1000.0
        actual_rate = max(requested_rate, 100.0)
        tag_count = struct.unpack("<I", data[4:8])[0] if len(data) >= 8 else 0
        tags = []
        offset = 8
        for _ in range(tag_count):
            if offset + 4 > len(data):
                break
            tag_len = struct.unpack("<I", data[offset:offset + 4])[0]
            offset += 4
            if offset + tag_len > len(data):
                break
            tag_name = data[offset:offset + tag_len].decode("utf-8", errors="replace").rstrip("\x00")
            tags.append(tag_name)
            offset += tag_len
        self._subscriptions[sub_id] = {"rate": actual_rate, "tags": tags}
        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", sub_id)
        resp += struct.pack("<f", actual_rate)
        return bytes(resp)

    def _handle_subscribe_with_client(self, data: bytes, writer: asyncio.StreamWriter) -> tuple[bytes, int]:
        resp = self._handle_subscribe(data)
        sub_id = self._next_sub_id - 1
        self._sub_clients[sub_id] = writer
        logger.info("OPC-DA subscription %d created with %d tags", sub_id, len(self._subscriptions[sub_id]["tags"]))
        return resp, sub_id

    async def _subscription_push_loop(self) -> None:
        try:
            last_values: dict[int, dict[str, Any]] = {}
            while self._server_running:
                await asyncio.sleep(0.5)
                dead_subs = []
                for sub_id, sub_info in list(self._subscriptions.items()):
                    writer = self._sub_clients.get(sub_id)
                    if not writer or writer.is_closing():
                        dead_subs.append(sub_id)
                        continue
                    rate = sub_info.get("rate", 1000.0)
                    last_push = sub_info.get("last_push", 0)
                    now = time.time()
                    if (now - last_push) * 1000 < rate:
                        continue
                    tags = sub_info.get("tags", [])
                    behavior = self._behaviors.get(self._default_device_id)
                    if not behavior:
                        continue
                    prev = last_values.get(sub_id, {})
                    data_changes = []
                    has_change = False
                    for tag in tags:
                        value = behavior.get_value(tag)
                        quality = behavior.get_quality(tag)
                        data_type = behavior.get_data_type(tag)
                        prev_state = prev.get(tag)
                        if prev_state is None or prev_state["value"] != value or prev_state["quality"] != quality:
                            has_change = True
                        data_changes.append({
                            "tag": tag, "value": value,
                            "quality": quality, "timestamp": now,
                            "data_type": data_type,
                        })
                        prev[tag] = {"value": value, "quality": quality}
                    last_values[sub_id] = prev
                    if not has_change and prev:
                        continue
                    sub_info["last_push"] = now
                    if not data_changes:
                        continue
                    resp = bytearray()
                    resp += struct.pack("<I", 0x00000004)
                    resp += struct.pack("<I", sub_id)
                    resp += struct.pack("<I", len(data_changes))
                    for dc in data_changes:
                        tag_bytes = dc["tag"].encode("utf-8")
                        resp += struct.pack("<H", len(tag_bytes))
                        resp += tag_bytes
                        resp += self._pack_typed_value(dc["data_type"], dc["value"])
                        resp += struct.pack("<I", dc["quality"])
                        resp += struct.pack("<d", dc["timestamp"])
                    try:
                        msg_header = self.OPCDA_MAGIC + struct.pack("<I", len(resp))
                        writer.write(msg_header + bytes(resp))
                        await writer.drain()
                    except (ConnectionResetError, OSError):
                        dead_subs.append(sub_id)
                for sid in dead_subs:
                    self._sub_clients.pop(sid, None)
                    self._subscriptions.pop(sid, None)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("OPC-DA subscription push error: %s", e)

    def _handle_get_status(self, data: bytes) -> bytes:
        resp = bytearray()
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", 1)
        resp += b"ProtoForge OPC-DA Bridge\x00"
        server_state = 1
        resp += struct.pack("<I", server_state)
        vendor_info = b"ProtoForge\x00"
        resp += struct.pack("<I", len(vendor_info))
        resp += vendor_info
        return bytes(resp)

    def _make_error(self, code: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<I", code)
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = OpcDaDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        self._device_params[device_config.id] = {
            "prog_id": proto_config.get("prog_id", "ProtoForge.SimServer"),
            "clsid": proto_config.get("clsid", ""),
        }

        logger.info("OPC-DA device created: %s (ProgID=%s)",
                     device_config.id, self._device_params[device_config.id]["prog_id"])
        self._log_debug("system", "device_create",
                        f"创建OPC-DA设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._device_params.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("OPC-DA device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除OPC-DA设备 {device_id}",
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
                "host": {"type": "string", "default": "0.0.0.0", "description": "OPC-DA 桥接服务器监听地址"},
                "port": {"type": "integer", "default": 51340, "description": "OPC-DA 桥接端口 (默认51340)"},
            },
        }
