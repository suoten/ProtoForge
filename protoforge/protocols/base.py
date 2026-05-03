from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Optional

from protoforge.models.device import DeviceConfig, PointValue


class ProtocolStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class ProtocolServer(ABC):
    protocol_name: str
    protocol_display_name: str
    protocol_description: str = ""
    protocol_version: str = "1.0.0"

    def __init__(self):
        self._status: ProtocolStatus = ProtocolStatus.STOPPED
        self._debug_callback: Optional[Callable] = None
        self._default_device_id: Optional[str] = None

    def set_debug_callback(self, callback: Callable) -> None:
        self._debug_callback = callback

    def _log_debug(self, direction: str, msg_type: str, summary: str,
                   device_id: str = "", detail: Optional[dict] = None):
        if self._debug_callback:
            self._debug_callback(direction, msg_type, summary, device_id, detail)

    @property
    def status(self) -> ProtocolStatus:
        return self._status

    @abstractmethod
    async def start(self, config: dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def create_device(self, device_config: DeviceConfig) -> str:
        pass

    @abstractmethod
    async def remove_device(self, device_id: str) -> None:
        pass

    @abstractmethod
    async def read_points(self, device_id: str) -> list[PointValue]:
        pass

    @abstractmethod
    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        pass

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    def get_running_port(self) -> int | None:
        return getattr(self, "_port", None)

    def get_running_host(self) -> str:
        return getattr(self, "_host", "0.0.0.0")

    def _update_default_device(self, device_id: str) -> None:
        if self._default_device_id is None:
            self._default_device_id = device_id

    def _clear_default_device(self, device_id: str) -> None:
        if self._default_device_id == device_id:
            self._default_device_id = None


class DeviceBehavior(ABC):
    @abstractmethod
    def generate_value(self, point_config: dict[str, Any]) -> Any:
        pass

    @abstractmethod
    def on_write(self, point_name: str, value: Any) -> bool:
        pass
