import asyncio
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)

try:
    from asyncua import Client, ua
    ASYNCUA_AVAILABLE = True
    ASYNCUA_SYNC = False
except ImportError:
    try:
        from opcua import Client, ua
        ASYNCUA_AVAILABLE = True
        ASYNCUA_SYNC = True
    except ImportError:
        ASYNCUA_AVAILABLE = False
        ASYNCUA_SYNC = False
        logger.warning("Neither asyncua nor opcua is installed. OPC-UA Client will not be available")


def parse_node_id(address: str):
    if not address:
        return None
    try:
        from opcua import NodeId
        return NodeId.from_string(address)
    except Exception as exc:
        logger.debug("OPC-UA NodeId parse failed for '%s', using raw string: %s", address, exc)
        return address


class OpcUaClientProtocol(ProtocolServer):
    protocol_name = "opcua_client"
    protocol_display_name = "OPC-UA 客户端"

    def __init__(self):
        super().__init__()
        self._client = None
        self._connected = False
        self._device_configs: dict[str, DeviceConfig] = {}
        self._point_nodes: dict[str, Any] = {}
        self._endpoint: str = ""
        self._connect_task: asyncio.Task | None = None
        self._read_interval: float = 1.0
        self._lock = asyncio.Lock()
        self._request_timeout: float = 10.0
        self._session_timeout: float = 3600000
        self._reconnect_interval: float = 5.0
        self._max_reconnect_attempts: int = 0
        self._reconnect_task: asyncio.Task | None = None
        self._stopping = False

    async def start(self, config: dict[str, Any]) -> None:
        if not ASYNCUA_AVAILABLE:
            raise RuntimeError("asyncua or opcua is not installed. Install with: pip install asyncua")

        self._status = ProtocolStatus.STARTING
        self._endpoint = config.get("endpoint", "opc.tcp://localhost:4840")
        self._read_interval = config.get("read_interval", 1.0)
        self._request_timeout = config.get("request_timeout", 10.0)
        self._session_timeout = config.get("session_timeout", 3600000)
        self._reconnect_interval = config.get("reconnect_interval", 5.0)
        self._max_reconnect_attempts = config.get("max_reconnect_attempts", 0)
        self._stopping = False

        try:
            await self._connect()
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())
            self._status = ProtocolStatus.RUNNING
            logger.info("OPC-UA Client connected to %s (timeout=%.1fs, session_timeout=%dms)",
                        self._endpoint, self._request_timeout, self._session_timeout)
            self._log_debug("system", "client_connect",
                            f"OPC-UA客户端连接 {self._endpoint}")
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to connect to OPC-UA server: %s", e)
            raise

    async def _connect(self) -> None:
        if ASYNCUA_SYNC:
            self._client = Client(self._endpoint)
            self._client.connect()
            self._connected = True
        else:
            self._client = Client(url=self._endpoint, timeout=self._request_timeout)
            await self._client.connect()
            if hasattr(self._client, 'session_timeout'):
                self._client.session_timeout = self._session_timeout
            self._connected = True

    async def _reconnect_loop(self) -> None:
        attempts = 0
        while not self._stopping:
            await asyncio.sleep(self._reconnect_interval)
            if self._stopping:
                break
            if self._connected and self._client:
                try:
                    if not ASYNCUA_SYNC and hasattr(self._client, 'uaclient'):
                        if hasattr(self._client.uaclient, 'keepalive') and callable(self._client.uaclient.keepalive):
                            await self._client.uaclient.keepalive()
                except Exception:
                    pass
                continue
            if self._max_reconnect_attempts > 0 and attempts >= self._max_reconnect_attempts:
                logger.error("OPC-UA Client max reconnect attempts (%d) reached, giving up",
                             self._max_reconnect_attempts)
                self._status = ProtocolStatus.ERROR
                break
            attempts += 1
            logger.info("OPC-UA Client attempting reconnect #%d to %s", attempts, self._endpoint)
            try:
                if self._client:
                    try:
                        if ASYNCUA_SYNC:
                            self._client.disconnect()
                        else:
                            await self._client.disconnect()
                    except Exception:
                        pass
                    self._client = None
                await self._connect()
                self._status = ProtocolStatus.RUNNING
                attempts = 0
                logger.info("OPC-UA Client reconnected to %s", self._endpoint)
                self._log_debug("system", "client_reconnect",
                                f"OPC-UA客户端重连成功 {self._endpoint}")
            except Exception as e:
                self._connected = False
                self._status = ProtocolStatus.ERROR
                logger.warning("OPC-UA Client reconnect failed (attempt %d): %s", attempts, e)

    async def stop(self) -> None:
        self._stopping = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None
        try:
            self._connected = False
            if self._client:
                try:
                    if ASYNCUA_SYNC:
                        self._client.disconnect()
                    else:
                        await self._client.disconnect()
                except Exception as e:
                    logger.warning("OPC-UA Client disconnect error: %s", e)
                self._client = None
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("OPC-UA Client disconnected")
            self._log_debug("system", "client_disconnect", "OPC-UA客户端断开连接")

    async def create_device(self, device_config: DeviceConfig) -> str:
        self._device_configs[device_config.id] = device_config

        for point in device_config.points:
            node_id = parse_node_id(point.address)
            if node_id:
                self._point_nodes[f"{device_config.id}.{point.name}"] = node_id

        logger.info("OPC-UA Client device created: %s (%d points)",
                    device_config.id, len(device_config.points))
        self._log_debug("system", "device_create",
                        f"创建OPC-UA客户端设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._device_configs.pop(device_id, None)
        keys_to_remove = [k for k in self._point_nodes.keys() if k.startswith(f"{device_id}.")]
        for k in keys_to_remove:
            self._point_nodes.pop(k, None)
        logger.info("OPC-UA Client device removed: %s", device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        config = self._device_configs.get(device_id)
        if not config:
            return []

        now = time.time()
        result = []

        if not self._connected or not self._client:
            for point in config.points:
                result.append(PointValue(name=point.name, value=None, timestamp=now))
            return result

        async with self._lock:
            for point in config.points:
                node_key = f"{device_id}.{point.name}"
                node_id = self._point_nodes.get(node_key)

                if not node_id:
                    result.append(PointValue(name=point.name, value=None, timestamp=now))
                    continue

                try:
                    node = self._client.get_node(node_id)
                    if ASYNCUA_SYNC:
                        value = node.get_value()
                    else:
                        value = await node.get_value()
                    result.append(PointValue(name=point.name, value=value, timestamp=now))
                except Exception as e:
                    logger.warning("Failed to read node %s: %s", node_id, e)
                    self._mark_disconnected()
                    result.append(PointValue(name=point.name, value=None, timestamp=now))

        return result

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        if not self._connected or not self._client:
            return False

        node_key = f"{device_id}.{point_name}"
        node_id = self._point_nodes.get(node_key)

        if not node_id:
            return False

        try:
            node = self._client.get_node(node_id)
            if ASYNCUA_SYNC:
                node.set_value(value)
            else:
                await node.set_value(value)
            return True
        except Exception as e:
            logger.warning("Failed to write node %s: %s", node_id, e)
            self._mark_disconnected()
            return False

    def _mark_disconnected(self) -> None:
        if self._connected:
            self._connected = False
            self._status = ProtocolStatus.ERROR
            logger.warning("OPC-UA Client connection lost, will attempt auto-reconnect")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "default": "opc.tcp://localhost:4840",
                    "description": "OPC-UA 服务器端点地址",
                },
                "read_interval": {
                    "type": "number",
                    "default": 1.0,
                    "description": "数据读取间隔(秒)",
                },
                "request_timeout": {
                    "type": "number",
                    "default": 10.0,
                    "description": "请求超时时间(秒)，增大此值可减少通道续期超时错误",
                },
                "session_timeout": {
                    "type": "integer",
                    "default": 3600000,
                    "description": "会话超时时间(毫秒)，默认1小时",
                },
                "reconnect_interval": {
                    "type": "number",
                    "default": 5.0,
                    "description": "断线重连间隔(秒)",
                },
                "max_reconnect_attempts": {
                    "type": "integer",
                    "default": 0,
                    "description": "最大重连次数，0表示无限重试",
                },
            },
        }
