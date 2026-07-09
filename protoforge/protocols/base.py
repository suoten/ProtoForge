"""Module: base."""

import asyncio
import threading
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
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
    protocol_description: str = ""
    protocol_version: str = "1.0.0"

    @staticmethod
    def _validate_port(port: int, name: str = "port") -> None:
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ValueError(f"{name} must be between 1 and 65535 (got {port})")

    def __init__(self):
        self._status: ProtocolStatus = ProtocolStatus.STOPPED
        self._debug_callback: Callable | None = None
        self._default_device_id: str | None = None
        self._default_device_lock = asyncio.Lock()  # FIXED: 添加锁保护_default_device_id的并发访问
        self._default_device_sync_lock = threading.Lock()  # FIXED-P1: 同步方法用的锁（asyncio.Lock不能在同步上下文使用）
        self._behaviors_lock = asyncio.Lock()  # FIXED: 添加锁保护_behaviors字典的并发访问
        self._behaviors_sync_lock = threading.Lock()  # FIXED: 同步方法用的锁（asyncio.Lock不能在同步上下文使用）
        # 写回调：当外部客户端通过协议写入时，通过此回调传播到 DeviceInstance
        self._on_write: Callable[[str, str, Any], Awaitable[bool]] | None = None

    def set_debug_callback(self, callback: Callable) -> None:
        self._debug_callback = callback

    def set_write_callback(self, callback: Callable[[str, str, Any], Awaitable[bool]]) -> None:
        """设置写回调，用于将协议层写入传播到 DeviceInstance。

        当外部客户端（如 Modbus master、OPC-UA client）通过协议写入数据时，
        协议 server 通过此回调将写入操作传播到引擎的 DeviceInstance，
        确保内部状态与协议数据一致。

        :param callback: 异步回调函数 ``async def(device_id, point_name, value) -> bool``
        """
        self._on_write = callback

    @property
    def on_write(self) -> Callable[[str, str, Any], Awaitable[bool]] | None:
        """返回当前设置的写回调函数（可为 None）。"""
        return self._on_write

    def _log_debug(self, direction: str, msg_type: str, summary: str,
                   device_id: str = "", detail: dict | None = None):
        if self._debug_callback:
            self._debug_callback(direction, msg_type, summary, device_id, detail)

    @property
    def status(self) -> ProtocolStatus:
        return self._status

    @abstractmethod
    async def start(self, config: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def create_device(self, device_config: DeviceConfig) -> str:
        raise NotImplementedError

    @abstractmethod
    async def remove_device(self, device_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def read_points(self, device_id: str) -> list[PointValue]:
        raise NotImplementedError

    @abstractmethod
    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        raise NotImplementedError

    def get_config_schema(self) -> dict[str, Any]:  # FIXED: 空实现→子类应覆写提供协议配置schema
        return {
            "type": "object",
            "properties": {},
        }

    def get_running_port(self) -> int | str | None:
        """Return the running port number (int) for TCP protocols,
        or serial port path (str) for serial protocols like Modbus RTU."""
        return getattr(self, "_port", None)

    def get_running_host(self) -> str:
        return getattr(self, "_host", "0.0.0.0")

    def _update_default_device(self, device_id: str) -> None:
        with self._default_device_sync_lock:  # FIXED-P1: 同步方法加锁保护_default_device_id
            self._default_device_id = device_id

    async def _update_default_device_async(self, device_id: str) -> None:
        # FIXED: 异步版本的默认设备更新，使用锁保护
        async with self._default_device_lock:
            self._default_device_id = device_id

    def _clear_default_device(self, device_id: str) -> None:
        with self._default_device_sync_lock:  # FIXED-P1: 同步方法加锁保护_default_device_id
            if self._default_device_id == device_id:
                self._default_device_id = None

    async def _clear_default_device_async(self, device_id: str) -> None:
        # FIXED: 异步版本的默认设备清除，使用锁保护
        async with self._default_device_lock:
            if self._default_device_id == device_id:
                self._default_device_id = None


class DeviceBehavior(ABC):
    @abstractmethod
    def generate_value(self, point_config: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def on_write(self, point_name: str, value: Any) -> bool:
        raise NotImplementedError
