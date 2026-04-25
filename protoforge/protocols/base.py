from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue


class ProtocolStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class ProtocolServer(ABC):
    protocol_name: str
    protocol_display_name: str

    def __init__(self):
        self._status: ProtocolStatus = ProtocolStatus.STOPPED
        self._devices: dict[str, Any] = {}
        self._debug_callback = None

    def set_debug_callback(self, callback):
        self._debug_callback = callback

    def _log_debug(self, direction: str, msg_type: str, summary: str,
                   device_id: str = "", detail: dict = None):
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


class DeviceBehavior(ABC):
    @abstractmethod
    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        pass

    @abstractmethod
    async def on_write(self, point_name: str, value: Any) -> bool:
        pass
