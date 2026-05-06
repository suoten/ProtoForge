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
    """解析 OPC-UA 节点 ID"""
    if not address:
        return None
    try:
        from opcua import NodeId
        return NodeId.from_string(address)
    except Exception:
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

    async def start(self, config: dict[str, Any]) -> None:
        if not ASYNCUA_AVAILABLE:
            raise RuntimeError("asyncua or opcua is not installed. Install with: pip install asyncua")

        self._status = ProtocolStatus.STARTING
        self._endpoint = config.get("endpoint", "opc.tcp://localhost:4840")
        self._read_interval = config.get("read_interval", 1.0)

        try:
            if ASYNCUA_SYNC:
                self._client = Client(self._endpoint)
                self._client.connect()
                self._connected = True
            else:
                self._client = Client(self._endpoint)
                await self._client.connect()
                self._connected = True

            self._status = ProtocolStatus.RUNNING
            logger.info("OPC-UA Client connected to %s", self._endpoint)
            self._log_debug("system", "client_connect",
                           f"OPC-UA客户端连接 {self._endpoint}")
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to connect to OPC-UA server: %s", e)
            raise

    async def stop(self) -> None:
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
            return False

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
            },
        }
