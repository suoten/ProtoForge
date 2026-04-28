import asyncio
import logging
import socket
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class BACnetDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                self._points[name] = p
                self._values[name] = fixed_val if fixed_val is not None else 0

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
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._sock:
            self._sock.close()
            self._sock = None
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
            resp.append(bacnet_id & 0xFF)
            resp.append((bacnet_id >> 8) & 0xFF)
            resp.append((bacnet_id >> 16) & 0xFF)
            resp.append((bacnet_id >> 24) & 0xFF)
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
        return await behavior.on_write(point_name, value)

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
        if access == "r":
            if data_type == "bool":
                return "binaryInput"
            return "analogInput"
        else:
            if data_type == "bool":
                return "binaryOutput"
            return "analogOutput"
