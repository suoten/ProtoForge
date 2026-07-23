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
        # 网络仿真器：用于模拟网络通信错误
        self._network_sim = None
        # 设备状态提供者：用于查询设备当前状态
        self._device_state_provider: Callable[[str], str] | None = None
        # 连接计数器
        self._active_connections: int = 0

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

    # -- 网络仿真集成 -------------------------------------------------------

    def set_network_sim(self, sim) -> None:
        """设置网络仿真器。"""
        self._network_sim = sim

    def should_drop_frame(self) -> bool:
        """检查当前帧是否应被丢弃（CRC错误或丢包）。"""
        if self._network_sim is None:
            return False
        # 优先检查 CRC 错误
        if hasattr(self._network_sim, 'should_inject_crc_error'):
            if self._network_sim.should_inject_crc_error():
                return True
        # 其次检查丢包
        if hasattr(self._network_sim, 'should_drop'):
            if self._network_sim.should_drop():
                return True
        return False

    def should_simulate_half_open(self) -> bool:
        """检查是否应模拟半开连接。"""
        if self._network_sim is None:
            return False
        if hasattr(self._network_sim, 'is_half_open'):
            return self._network_sim.is_half_open()
        return False

    # -- 设备状态提供者 -----------------------------------------------------

    def set_device_state_provider(self, provider: Callable[[str], str]) -> None:
        """设置设备状态查询回调。

        :param provider: 回调函数，接受 device_id，返回状态字符串
                        ("run"/"stop"/"starting"/"stopping"/"error"/"maintenance"/"program")
        """
        self._device_state_provider = provider

    def get_device_state_string(self, device_id: str) -> str:
        """获取设备的当前状态字符串。

        无状态提供者时默认返回 "run"（不阻止正常请求）。
        """
        if self._device_state_provider is None:
            return "run"
        try:
            return self._device_state_provider(device_id)
        except Exception:
            return "run"

    # -- 连接追踪 -----------------------------------------------------------

    @property
    def active_connections(self) -> int:
        """返回当前活跃连接数。"""
        return self._active_connections

    def on_client_connect(self) -> None:
        """客户端连接时的回调，递增连接计数。"""
        self._active_connections += 1

    def on_client_disconnect(self) -> None:
        """客户端断开时的回调，递减连接计数。"""
        self._active_connections = max(0, self._active_connections - 1)

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
