import asyncio
import logging
import socket
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DynamicValueGenerator

logger = logging.getLogger(__name__)


class BACnetDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                self._points[name] = p
                self._values[name] = fixed_val if fixed_val is not None else 0
                self._generators[name] = DynamicValueGenerator(p)

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)


class BACnetServer(ProtocolServer):
    protocol_name = "bacnet"
    protocol_display_name = "BACnet"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, BACnetDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_objects: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 47808
        self._device_id_base = 100
        self._bbmd_enabled = False
        self._task: asyncio.Task | None = None
        self._sock: socket.socket | None = None

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 47808)
        self._device_id_base = config.get("device_id_base", 100)
        self._bbmd_enabled = config.get("bbmd_enabled", False)
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.setblocking(False)
            self._sock.bind((self._host, self._port))
            self._task = asyncio.create_task(self._serve_udp())
            self._status = ProtocolStatus.RUNNING
            logger.info("BACnet server started on %s:%d (BBMD: %s)",
                         self._host, self._port, self._bbmd_enabled)
            self._log_debug("system", "server_start",
                            f"BACnet服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start BACnet server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            if self._sock:
                try:
                    self._sock.close()
                except Exception as e:
                    logger.debug("Socket close error: %s", e)
                self._sock = None
        except Exception as e:
            logger.warning("BACnet server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("BACnet server stopped")
            self._log_debug("system", "server_stop", "BACnet服务停止")

    async def _serve_udp(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                data, addr = await loop.sock_recvfrom(self._sock, 2048)
                response = self._handle_bacnet_packet(data, addr)
                if response:
                    await loop.sock_sendto(self._sock, response, addr)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("BACnet UDP error: %s", e)
                await asyncio.sleep(0.01)

    def _handle_bacnet_packet(self, data: bytes, addr: tuple) -> bytes | None:
        if len(data) < 4:
            return None
        if data[0] == 0x81 and len(data) >= 6:
            msg_type = data[1]
            if msg_type == 0x00:
                control = data[2]
                if control & 0x08:
                    invoke_id = data[3] if len(data) > 3 else 0
                    service_choice = data[4] if len(data) > 4 else 0
                    if service_choice == 0x08:
                        return self._make_who_is_response(data, addr)
                    elif service_choice == 0x0C:
                        return self._handle_read_property(data, addr, invoke_id)
                    elif service_choice == 0x0F:
                        return self._handle_write_property(data, addr, invoke_id)
                    elif service_choice == 0x0E:
                        return self._handle_read_property_multiple(data, addr, invoke_id)
                    else:
                        return self._make_error_response(invoke_id, 0x0C, 2, 3)
            elif msg_type == 0x01:
                pass
            elif msg_type == 0x04:
                pass
        return None

    def _decode_object_identifier(self, raw_bytes: bytes) -> tuple[int, int]:
        if len(raw_bytes) < 4:
            return (0, 0)
        obj_id = struct.unpack(">I", raw_bytes)[0]
        obj_type = (obj_id >> 22) & 0x3FF
        obj_inst = obj_id & 0x3FFFFF
        return (obj_type, obj_inst)

    def _encode_object_identifier(self, obj_type: int, obj_inst: int) -> bytes:
        obj_id = ((obj_type & 0x3FF) << 22) | (obj_inst & 0x3FFFFF)
        return struct.pack(">I", obj_id)

    def _make_error_response(self, invoke_id: int, service_choice: int,
                              error_class: int, error_code: int) -> bytes:
        resp = bytearray()
        resp.append(0x81)
        resp.append(0x0A)
        resp.append(0x00)
        resp.append(0x00)
        resp.append(0x01)
        resp.append(0x04)
        resp.append(0x00)
        resp.append(invoke_id & 0xFF)
        resp.append(0x50)
        resp.append(service_choice & 0xFF)
        resp.append(0x91)
        resp.append(error_class & 0xFF)
        resp.append(0x91)
        resp.append(error_code & 0xFF)
        resp[3] = len(resp) - 4
        return bytes(resp)

    def _make_reject_response(self, invoke_id: int, reason: int) -> bytes:
        resp = bytearray()
        resp.append(0x81)
        resp.append(0x0A)
        resp.append(0x00)
        resp.append(0x00)
        resp.append(0x01)
        resp.append(0x04)
        resp.append(0x00)
        resp.append(invoke_id & 0xFF)
        resp.append(0x40)
        resp.append(reason & 0xFF)
        resp[3] = len(resp) - 4
        return bytes(resp)

    def _handle_read_property(self, data: bytes, addr: tuple, invoke_id: int) -> bytes | None:
        if len(data) < 10:
            return self._make_reject_response(invoke_id, 4)
        obj_id_bytes = data[5:9] if len(data) >= 9 else data[5:]
        obj_type, obj_inst = self._decode_object_identifier(obj_id_bytes[:4] if len(obj_id_bytes) >= 4 else obj_id_bytes)
        prop_id = data[9] if len(data) > 9 else 85

        for device_id, device_obj in self._device_objects.items():
            behavior = self._behaviors.get(device_id)
            if not behavior:
                continue
            for i, obj in enumerate(device_obj.get("objects", [])):
                obj_idx = i + 1
                if obj_inst == 0 or obj_inst == obj_idx:
                    if prop_id == 85 or prop_id == 0x55:
                        value = behavior.get_value(obj.get("object_name", ""))
                    elif prop_id == 77 or prop_id == 0x4D:
                        value = obj.get("object_name", "")
                    elif prop_id == 28 or prop_id == 0x1C:
                        value = obj.get("description", "")
                    elif prop_id == 96 or prop_id == 0x60:
                        value = obj.get("units", "")
                    else:
                        value = behavior.get_value(obj.get("object_name", ""))
                    resp = bytearray()
                    resp.append(0x81)
                    resp.append(0x0A)
                    resp.append(0x00)
                    resp.append(0x00)
                    resp.append(0x01)
                    resp.append(0x04)
                    resp.append(0x00)
                    resp.append(invoke_id & 0xFF)
                    resp.append(0x0C | 0x80)
                    resp += self._encode_object_identifier(obj_type, obj_idx)
                    resp.append(prop_id)
                    if isinstance(value, bool):
                        resp.append(0x19)
                        resp.append(0x01 if value else 0x00)
                    elif isinstance(value, float):
                        resp.append(0x44)
                        resp += struct.pack(">f", value)
                    elif isinstance(value, int):
                        resp.append(0x22)
                        resp += struct.pack(">H", value & 0xFFFF)
                    elif isinstance(value, str):
                        encoded = value.encode("utf-8")
                        resp.append(0x75)
                        resp += struct.pack(">H", len(encoded))
                        resp += encoded
                    else:
                        resp.append(0x44)
                        resp += struct.pack(">f", float(value) if value else 0.0)
                    resp[3] = len(resp) - 4
                    return bytes(resp)
        return self._make_error_response(invoke_id, 0x0C, 1, 31)

    def _handle_read_property_multiple(self, data: bytes, addr: tuple, invoke_id: int) -> bytes | None:
        if len(data) < 7:
            return self._make_reject_response(invoke_id, 4)
        resp = bytearray()
        resp.append(0x81)
        resp.append(0x0A)
        resp.append(0x00)
        resp.append(0x00)
        resp.append(0x01)
        resp.append(0x04)
        resp.append(0x00)
        resp.append(invoke_id & 0xFF)
        resp.append(0x0E | 0x80)
        offset = 5
        while offset + 4 <= len(data):
            obj_type, obj_inst = self._decode_object_identifier(data[offset:offset + 4])
            offset += 4
            if offset >= len(data):
                break
            prop_count = data[offset] if data[offset] != 0xFE else 1
            offset += 1
            obj_data = bytearray()
            obj_data += self._encode_object_identifier(obj_type, obj_inst)
            found = False
            for device_id, device_obj in self._device_objects.items():
                behavior = self._behaviors.get(device_id)
                if not behavior:
                    continue
                for i, obj in enumerate(device_obj.get("objects", [])):
                    obj_idx = i + 1
                    if obj_inst == 0 or obj_inst == obj_idx:
                        found = True
                        prop_list = bytearray()
                        prop_list.append(0x01)
                        p_offset = offset
                        for _ in range(min(prop_count, 10)):
                            if p_offset >= len(data):
                                break
                            pid = data[p_offset]
                            p_offset += 1
                            if pid == 85 or pid == 0x55:
                                value = behavior.get_value(obj.get("object_name", ""))
                            elif pid == 77:
                                value = obj.get("object_name", "")
                            elif pid == 28:
                                value = obj.get("description", "")
                            elif pid == 96:
                                value = obj.get("units", "")
                            else:
                                value = behavior.get_value(obj.get("object_name", ""))
                            prop_list.append(pid)
                            if isinstance(value, bool):
                                prop_list.append(0x19)
                                prop_list.append(0x01 if value else 0x00)
                            elif isinstance(value, float):
                                prop_list.append(0x44)
                                prop_list += struct.pack(">f", value)
                            elif isinstance(value, int):
                                prop_list.append(0x22)
                                prop_list += struct.pack(">H", value & 0xFFFF)
                            elif isinstance(value, str):
                                encoded = value.encode("utf-8")
                                prop_list.append(0x75)
                                prop_list += struct.pack(">H", len(encoded))
                                prop_list += encoded
                            else:
                                prop_list.append(0x44)
                                prop_list += struct.pack(">f", float(value) if value else 0.0)
                        obj_data += prop_list
                        break
                if found:
                    break
            if not found:
                obj_data += self._encode_object_identifier(obj_type, obj_inst)
                obj_data.append(0x01)
                obj_data.append(85)
                obj_data.append(0x91)
                obj_data.append(31)
            resp += obj_data
            while offset < len(data) and data[offset] not in (0x0C, 0x0E, 0x0F):
                offset += 1
                if offset >= len(data):
                    break
        resp[3] = len(resp) - 4
        return bytes(resp)

    def _handle_write_property(self, data: bytes, addr: tuple, invoke_id: int) -> bytes | None:
        if len(data) < 12:
            return None
        obj_type_raw = data[5] if len(data) > 5 else 0
        obj_inst = struct.unpack(">H", data[6:8])[0] if len(data) >= 8 else 0
        prop_id = data[8] if len(data) > 8 else 85

        for device_id, device_obj in self._device_objects.items():
            behavior = self._behaviors.get(device_id)
            if not behavior:
                continue
            for i, obj in enumerate(device_obj.get("objects", [])):
                obj_id = i + 1
                if obj_inst == 0 or obj_inst == obj_id:
                    tag = data[9] if len(data) > 9 else 0
                    if tag == 0x44 and len(data) >= 14:
                        value = struct.unpack(">f", data[10:14])[0]
                    elif tag == 0x55 and len(data) >= 18:
                        value = struct.unpack(">d", data[10:18])[0]
                    elif tag == 0x34 and len(data) >= 14:
                        value = struct.unpack(">i", data[10:14])[0]
                    elif tag == 0x22 and len(data) >= 12:
                        value = struct.unpack(">H", data[10:12])[0]
                    elif tag == 0x19 and len(data) >= 11:
                        value = bool(data[10])
                    else:
                        value = 0
                    point_name = obj.get("object_name", "")
                    behavior.set_value(point_name, value)
                    obj["present_value"] = value
                    resp = bytearray()
                    resp.append(0x81)
                    resp.append(0x0A)
                    resp.append(0x00)
                    resp.append(0x06)
                    resp.append(0x01)
                    resp.append(0x04)
                    resp.append(0x00)
                    resp.append(invoke_id & 0xFF)
                    resp.append(0x0F | 0x80)
                    return bytes(resp)
        return None

    def _make_who_is_response(self, data: bytes, addr: tuple) -> bytes:
        responses = b""
        for device_id, device_obj in self._device_objects.items():
            bacnet_id = device_obj.get("device_id", self._device_id_base)
            resp = bytearray([
                0x81, 0x0A,
                0x00, 0x0C,
            ])
            resp.append(0x01)
            resp.append(0x04)
            resp.append((bacnet_id >> 24) & 0xFF)
            resp.append((bacnet_id >> 16) & 0xFF)
            resp.append((bacnet_id >> 8) & 0xFF)
            resp.append(bacnet_id & 0xFF)
            responses += bytes(resp)
        return responses if responses else None

    async def create_device(self, device_config: DeviceConfig) -> str:
        device_id = device_config.id
        self._device_configs[device_id] = device_config

        behavior = BACnetDeviceBehavior(device_config.points)
        self._behaviors[device_id] = behavior
        self._update_default_device(device_id)

        proto_config = device_config.protocol_config or {}
        bacnet_device_id = proto_config.get("device_id", self._device_id_base + len(self._device_configs))
        bacnet_device_name = proto_config.get("device_name", device_config.name)

        objects = []
        for i, point in enumerate(device_config.points):
            object_type = self._get_bacnet_object_type(point)
            obj = {
                "object_identifier": f"{object_type},{i + 1}",
                "object_name": point.name,
                "object_type": object_type,
                "present_value": behavior.get_value(point.name),
                "description": point.description,
                "units": point.unit,
                "cov_increment": 0.1,
                "reliability": "no-fault-detected",
                "out_of_service": False,
            }
            objects.append(obj)

        self._device_objects[device_id] = {
            "device_id": bacnet_device_id,
            "device_name": bacnet_device_name,
            "vendor_name": "ProtoForge",
            "vendor_id": 999,
            "model_name": "PF-BAC-100",
            "firmware_revision": "1.0.0",
            "application_software_revision": "1.0.0",
            "protocol_version": 1,
            "protocol_revision": 24,
            "max_apdu_length_accepted": 1024,
            "segmentation_supported": "segmented-both",
            "apdu_timeout": 3000,
            "number_of_apdu_retries": 3,
            "objects": objects,
        }

        logger.info("BACnet device created: %s (BACnet ID: %d, name: %s, %d objects)",
                     device_id, bacnet_device_id, bacnet_device_name, len(objects))
        self._log_debug("system", "device_create",
                        f"创建BACnet设备 {device_config.name}",
                        device_id=device_id)
        return device_id

    async def remove_device(self, device_id: str) -> None:
        self._device_configs.pop(device_id, None)
        self._behaviors.pop(device_id, None)
        self._device_objects.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("BACnet device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除BACnet设备 {device_id}",
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
        success = behavior.on_write(point_name, value)
        if success:
            device_obj = self._device_objects.get(device_id, {})
            for obj in device_obj.get("objects", []):
                if obj.get("object_name") == point_name:
                    obj["present_value"] = value
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "default": "0.0.0.0",
                    "description": "BACnet 监听地址",
                },
                "port": {
                    "type": "integer",
                    "default": 47808,
                    "description": "BACnet UDP 端口 (默认47808)",
                },
                "device_id_base": {
                    "type": "integer",
                    "default": 100,
                    "description": "BACnet 设备ID起始值",
                },
                "bbmd_enabled": {
                    "type": "boolean",
                    "default": False,
                    "description": "启用BBMD广播管理",
                },
            },
        }

    def _get_bacnet_object_type(self, point) -> str:
        access = point.access if hasattr(point, "access") else "r"
        data_type = point.data_type if hasattr(point, "data_type") else "float32"
        dt_val = data_type.value if hasattr(data_type, "value") else str(data_type)
        if access == "r":
            if dt_val == "bool":
                return "binaryInput"
            return "analogInput"
        else:
            if dt_val == "bool":
                return "binaryOutput"
            return "analogOutput"
