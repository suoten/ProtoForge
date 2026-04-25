import asyncio
import logging
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class BACnetDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[dict]):
        self._points = {p["name"]: p for p in points}
        self._values: dict[str, Any] = {}
        for p in points:
            self._values[p["name"]] = p.get("fixed_value") if p.get("fixed_value") is not None else 0

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

    async def start(self, config: dict[str, Any]) -> None:
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 47808)
        self._device_id_base = config.get("device_id_base", 100)
        self._bbmd_enabled = config.get("bbmd_enabled", False)
        self._status = ProtocolStatus.RUNNING
        logger.info("BACnet server started on %s:%d (BBMD: %s)",
                     self._host, self._port, self._bbmd_enabled)

    async def stop(self) -> None:
        self._status = ProtocolStatus.STOPPED
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("BACnet server stopped")

    async def create_device(self, device_config: DeviceConfig) -> str:
        device_id = device_config.id
        self._device_configs[device_id] = device_config

        behavior = BACnetDeviceBehavior(
            [p.model_dump() for p in device_config.points]
        )
        self._behaviors[device_id] = behavior

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
                "description": point.description if hasattr(point, "description") else "",
                "units": point.unit if hasattr(point, "unit") else "",
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
            "model_name": device_config.model if hasattr(device_config, "model") else "PF-BAC-100",
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
        return device_id

    async def remove_device(self, device_id: str) -> None:
        self._device_configs.pop(device_id, None)
        self._behaviors.pop(device_id, None)
        self._device_objects.pop(device_id, None)
        logger.info("BACnet device removed: %s", device_id)

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
                timestamp=asyncio.get_event_loop().time(),
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
