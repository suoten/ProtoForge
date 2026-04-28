import asyncio
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)

try:
    from asyncua import Server, ua
    ASYNCUA_AVAILABLE = True
except ImportError:
    ASYNCUA_AVAILABLE = False
    logger.warning("asyncua not installed, OPC-UA protocol will not be available")


class OpcUaDeviceBehavior(DeviceBehavior):
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


class OpcUaServer(ProtocolServer):
    protocol_name = "opcua"
    protocol_display_name = "OPC-UA"

    def __init__(self):
        super().__init__()
        self._server: Any = None
        self._idx: int = 0
        self._behaviors: dict[str, OpcUaDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_nodes: dict[str, Any] = {}
        self._point_nodes: dict[str, Any] = {}
        self._device_namespaces: dict[str, str] = {}
        self._endpoint = "opc.tcp://0.0.0.0:4840/protoforge"
        self._server_task: asyncio.Task | None = None

    async def start(self, config: dict[str, Any]) -> None:
        if not ASYNCUA_AVAILABLE:
            raise RuntimeError("asyncua is not installed. Install with: pip install protoforge[opcua]")

        self._status = ProtocolStatus.STARTING
        host = config.get("host", "0.0.0.0")
        port = config.get("port", 4840)
        self._endpoint = f"opc.tcp://{host}:{port}/protoforge"

        try:
            self._server = Server()
            await self._server.init()
            self._server.set_endpoint(self._endpoint)

            first_config = next(iter(self._device_configs.values()), None)
            if first_config:
                proto_config = first_config.protocol_config or {}
                server_name = proto_config.get("server_name", "ProtoForge OPC-UA Server")
            else:
                server_name = "ProtoForge OPC-UA Server"
            self._server.set_server_name(server_name)

            uri = "urn:protoforge:simulation"
            try:
                self._idx = await self._server.register_namespace(uri)
            except AttributeError:
                try:
                    self._idx = await self._server.nodes.namespace.add(uri)
                except AttributeError:
                    self._idx = await self._server.get_namespace_index(uri)

            for device_config in self._device_configs.values():
                await self._create_opcua_device(device_config)

            self._status = ProtocolStatus.RUNNING
            self._server_task = asyncio.create_task(self._server.start())
            logger.info("OPC-UA server starting at %s", self._endpoint)
            self._log_debug("system", "server_start",
                            f"OPC-UA服务启动 {self._endpoint}")
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start OPC-UA server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            if self._server:
                await self._server.stop()
        except Exception as e:
            logger.warning("OPC-UA server stop error: %s", e)
        if self._server_task:
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("OPC-UA server task error: %s", e)
        self._status = ProtocolStatus.STOPPED
        logger.info("OPC-UA server stopped")
        self._log_debug("system", "server_stop", "OPC-UA服务停止")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = OpcUaDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        ns = proto_config.get("namespace", "protoforge")
        self._device_namespaces[device_config.id] = ns

        if self._status == ProtocolStatus.RUNNING and self._server:
            await self._create_opcua_device(device_config)

        logger.info("OPC-UA device created: %s (namespace=%s)", device_config.id, ns)
        self._log_debug("system", "device_create",
                        f"创建OPC-UA设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._device_namespaces.pop(device_id, None)
        self._clear_default_device(device_id)
        nodes = self._device_nodes.pop(device_id, None)
        if nodes and self._server:
            for node in nodes.values():
                try:
                    await node.delete()
                except Exception as e:
                    logger.debug("OPC-UA node delete error: %s", e)
        logger.info("OPC-UA device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除OPC-UA设备 {device_id}",
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
            point_node_key = f"{device_id}.{point.name}"
            node = self._point_nodes.get(point_node_key)
            if node:
                try:
                    value = await node.get_value()
                except Exception as e:
                    logger.debug("OPC-UA read node value error: %s", e)
            result.append(PointValue(name=point.name, value=value, timestamp=now))
        return result

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        success = await behavior.on_write(point_name, value)
        if success:
            point_node_key = f"{device_id}.{point_name}"
            node = self._point_nodes.get(point_node_key)
            if node:
                try:
                    await node.set_value(value)
                except Exception as e:
                    logger.debug("OPC-UA write node value error: %s", e)
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "default": "0.0.0.0",
                    "description": "监听地址",
                },
                "port": {
                    "type": "integer",
                    "default": 4840,
                    "description": "监听端口",
                },
            },
        }

    async def _create_opcua_device(self, config: DeviceConfig) -> None:
        if not self._server:
            return
        behavior = self._behaviors.get(config.id)
        device_folder = await self._server.nodes.objects.add_object(
            self._idx, config.name
        )
        point_nodes = {}
        for point in config.points:
            value = behavior.get_value(point.name) if behavior else 0
            node = await device_folder.add_variable(
                self._idx, point.name, value
            )
            if point.access and "w" in point.access:
                await node.set_writable()
            point_nodes[point.name] = node
            self._point_nodes[f"{config.id}.{point.name}"] = node
        self._device_nodes[config.id] = {"folder": device_folder, "points": point_nodes}
