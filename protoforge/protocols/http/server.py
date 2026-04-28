import asyncio
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class HttpDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        for p in points:
            self._values[p.name] = p.fixed_value if p.fixed_value is not None else 0

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


class HttpSimulatorServer(ProtocolServer):
    protocol_name = "http"
    protocol_display_name = "HTTP REST"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, HttpDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_prefixes: dict[str, str] = {}

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        try:
            self._status = ProtocolStatus.RUNNING
            logger.info("HTTP Simulator started (uses main FastAPI server)")
            self._log_debug("system", "server_start", "HTTP服务启动")
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start HTTP server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            pass
        except Exception as e:
            logger.warning("HTTP server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("HTTP Simulator stopped")
            self._log_debug("system", "server_stop", "HTTP服务停止")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = HttpDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        api_prefix = proto_config.get("api_prefix", "/api")
        self._device_prefixes[device_config.id] = api_prefix

        logger.info("HTTP device created: %s (api_prefix=%s)", device_config.id, api_prefix)
        self._log_debug("system", "device_create",
                        f"创建HTTP设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._device_prefixes.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("HTTP device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除HTTP设备 {device_id}",
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        config = self._device_configs.get(device_id)
        if not config:
            return []
        now = time.time()
        result = []
        for point in config.points:
            value = behavior.get_value(point.name)
            result.append(PointValue(name=point.name, value=value, timestamp=now))
        return result

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        return await behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "api_prefix": {"type": "string", "default": "/api", "description": "API路径前缀"},
            },
        }
