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
        from asyncua import NodeId
        return NodeId.from_string(address)
    except Exception:
        try:
            from opcua import NodeId
            return NodeId.from_string(address)
        except Exception as exc:
            logger.debug("OPC-UA NodeId parse failed for '%s', using raw string: %s", address, exc)
            return address


class OpcUaClientProtocol(ProtocolServer):
    protocol_name = "opcua_client"
    protocol_display_name = "OPC-UA Client"

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
            logger.info("OPC-UA Client connected to %s (timeout=%.1fs, session_timeout=%dms)",
                        self._endpoint, self._request_timeout, self._session_timeout)
            self._log_debug("system", "client_connect",
                            f"OPC-UA client connected: {self._endpoint}")
        except Exception as e:
            self._connected = False
            self._client = None
            logger.warning("OPC-UA Client initial connect failed: %s, will retry in background (interval=%.1fs)", e, self._reconnect_interval)

        # Protocol is RUNNING once start() completes (reconnect loop handles connection)
        self._status = ProtocolStatus.RUNNING

        # Always start reconnect loop - handles both keepalive and initial connect retry
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

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
            # If already connected, just do keepalive check
            if self._connected and self._client:
                try:
                    if not ASYNCUA_SYNC and hasattr(self._client, 'uaclient'):
                        if hasattr(self._client.uaclient, 'keepalive') and callable(self._client.uaclient.keepalive):
                            await self._client.uaclient.keepalive()
                    continue
                except Exception as ka_err:
                    logger.warning("OPC-UA keepalive error: %s, will reconnect", ka_err)
                    self._connected = False
            # Check max reconnect attempts
            if self._max_reconnect_attempts > 0 and attempts >= self._max_reconnect_attempts:
                logger.error("OPC-UA Client max reconnect attempts (%d) reached, giving up",
                             self._max_reconnect_attempts)
                self._status = ProtocolStatus.ERROR
                break
            # Attempt reconnect
            attempts += 1
            log_level = logger.info if attempts <= 1 else logger.debug
            log_level("OPC-UA Client attempting reconnect #%d to %s", attempts, self._endpoint)
            try:
                # Only disconnect if previously connected to avoid
                # asyncua "disconnect_socket was called but transport is None" warnings
                if self._client and self._connected:
                    try:
                        if ASYNCUA_SYNC:
                            self._client.disconnect()
                        else:
                            await self._client.disconnect()
                    except Exception as disc_err:
                        logger.debug("OPC-UA disconnect error during reconnect: %s", disc_err)
                self._client = None
                await self._connect()
                attempts = 0
                logger.info("OPC-UA Client connected to %s", self._endpoint)
            except Exception as e:
                self._connected = False
                self._client = None
                logger.debug("OPC-UA Client reconnect failed (attempt %d): %s", attempts, e)

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
            was_connected = self._connected
            self._connected = False
            if self._client:
                try:
                    if ASYNCUA_SYNC:
                        self._client.disconnect()
                    else:
                        await self._client.disconnect()
                except Exception as e:
                    # Silently ignore disconnect errors (e.g. "transport is None" when never connected)
                    logger.debug("OPC-UA Client disconnect cleanup: %s", e)
                self._client = None
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("OPC-UA Client stopped (was_connected=%s)", was_connected)
            self._log_debug("system", "client_disconnect", "OPC-UA client disconnected")

    async def create_device(self, device_config: DeviceConfig) -> str:
        async with self._lock:  # FIXED: 添加锁保护，避免并发create/remove/read竞态
            self._device_configs[device_config.id] = device_config
            for point in device_config.points:
                node_id = parse_node_id(point.address)
                if node_id:
                    self._point_nodes[f"{device_config.id}.{point.name}"] = node_id

        logger.info("OPC-UA Client device created: %s (%d points)",
                    device_config.id, len(device_config.points))
        self._log_debug("system", "device_create",
                        f"Creating OPC-UA client device: {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._lock:  # FIXED: 添加锁保护，避免并发create/remove/read竞态
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
            logger.warning("OPC-UA Client connection lost, will attempt auto-reconnect")

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "default": "opc.tcp://localhost:4840",
                    "description": "OPC-UA server endpoint address",
                },
                "read_interval": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Data read interval (seconds)",
                },
                "request_timeout": {
                    "type": "number",
                    "default": 10.0,
                    "description": "Request timeout (seconds), increase to reduce channel renewal timeout errors",
                },
                "session_timeout": {
                    "type": "integer",
                    "default": 3600000,
                    "description": "Session timeout (ms), default 1 hour",
                },
                "reconnect_interval": {
                    "type": "number",
                    "default": 5.0,
                    "description": "Reconnect interval (seconds)",
                },
                "max_reconnect_attempts": {
                    "type": "integer",
                    "default": 0,
                    "description": "Max reconnect attempts, 0 for unlimited",
                },
            },
        }
