import asyncio
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DynamicValueGenerator

logger = logging.getLogger(__name__)

try:
    from amqtt.broker import Broker
    from amqtt.contexts import Action
    from amqtt.session import Session
    ASYNC_MQTT_AVAILABLE = True
except ImportError:
    ASYNC_MQTT_AVAILABLE = False
    logger.warning("amqtt not installed, MQTT Broker will not be available. Install with: pip install protoforge[mqtt]")


class MqttDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        for p in points:
            self._values[p.name] = p.fixed_value if p.fixed_value is not None else 0
                self._generators[p.name] = DynamicValueGenerator(p)

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
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)


class MqttBroker(ProtocolServer):
    protocol_name = "mqtt"
    protocol_display_name = "MQTT Broker"

    def __init__(self):
        super().__init__()
        self._broker: Any = None
        self._behaviors: dict[str, MqttDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 1883
        self._publish_task: asyncio.Task | None = None
        self._auth_required = False
        self._auth_username = ""
        self._auth_password = ""

    async def start(self, config: dict[str, Any]) -> None:
        if not ASYNC_MQTT_AVAILABLE:
            raise RuntimeError("amqtt is not installed. Install with: pip install protoforge[mqtt]")

        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 1883)
        publish_interval = config.get("publish_interval", 5)
        self._auth_required = config.get("auth_required", False)
        self._auth_username = config.get("auth_username", "")
        self._auth_password = config.get("auth_password", "")

        try:
            auth_plugins = {
                "amqtt.plugins.authentication.AnonymousAuthPlugin": {
                    "allow_anonymous": not self._auth_required,
                },
            }
            if self._auth_required and self._auth_username:
                auth_plugins["amqtt.plugins.authentication.AnonymousAuthPlugin"]["allow_anonymous"] = False
            broker_config = {
                "listeners": {
                    "default": {
                        "type": "tcp",
                        "bind": f"{self._host}:{self._port}",
                    }
                },
                "plugins": {
                    **auth_plugins,
                    "amqtt.plugins.sys.broker.BrokerSysPlugin": {
                        "sys_interval": 20,
                    },
                },
            }
            if config.get("tls_enabled", False):
                import ssl
                tls_cert_path = config.get("tls_cert_path", "")
                tls_key_path = config.get("tls_key_path", "")
                if tls_cert_path and tls_key_path:
                    try:
                        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                        ssl_context.load_cert_chain(tls_cert_path, tls_key_path)
                        broker_config["listeners"]["default"]["ssl"] = ssl_context
                        logger.info("MQTT TLS enabled with cert: %s", tls_cert_path)
                    except Exception as e:
                        logger.error("Failed to load MQTT TLS certificate: %s", e)
                        raise RuntimeError(f"MQTT TLS certificate error: {e}")
                else:
                    logger.warning(
                        "MQTT TLS is enabled but tls_cert_path or tls_key_path is not configured. "
                        "TLS will not be activated. Provide both paths to enable TLS."
                    )
            self._broker = Broker(broker_config)
            await self._broker.start()

            self._status = ProtocolStatus.RUNNING
            self._publish_task = asyncio.create_task(self._publish_loop(publish_interval))
            logger.info("MQTT Broker starting on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"MQTT Broker启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start MQTT Broker: %s", e)
            raise

    async def stop(self) -> None:
        try:
            if self._publish_task:
                self._publish_task.cancel()
                try:
                    await self._publish_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning("MQTT publish task error: %s", e)
            if self._broker:
                await self._broker.shutdown()
        except Exception as e:
            logger.warning("MQTT broker stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("MQTT broker stopped")
            self._log_debug("system", "server_stop", "MQTT服务停止")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = MqttDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)
        logger.info("MQTT device created: %s", device_config.id)
        self._log_debug("system", "device_create",
                        f"创建MQTT设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("MQTT device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除MQTT设备 {device_id}",
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
        success = await behavior.on_write(point_name, value)
        if success:
            await self._publish_device(device_id)
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
                    "default": 1883,
                    "description": "监听端口",
                },
                "publish_interval": {
                    "type": "integer",
                    "default": 5,
                    "description": "数据发布间隔（秒）",
                },
                "auth_required": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否启用用户名/密码认证",
                },
                "auth_username": {
                    "type": "string",
                    "default": "",
                    "description": "认证用户名",
                },
                "auth_password": {
                    "type": "string",
                    "default": "",
                    "description": "认证密码",
                },
                "tls_enabled": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否启用TLS加密",
                },
                "tls_cert_path": {
                    "type": "string",
                    "default": "",
                    "description": "TLS 证书文件路径（PEM格式）",
                },
                "tls_key_path": {
                    "type": "string",
                    "default": "",
                    "description": "TLS 私钥文件路径（PEM格式）",
                },
            },
        }

    async def _publish_loop(self, interval: int) -> None:
        import json as json_lib

        while self._status == ProtocolStatus.RUNNING:
            for device_id, config in self._device_configs.items():
                behavior = self._behaviors.get(device_id)
                if not behavior:
                    continue
                proto_config = config.protocol_config or {}
                topic_prefix = proto_config.get("topic_prefix", "protoforge")
                for point in config.points:
                    value = behavior.get_value(point.name)
                    topic = f"{topic_prefix}/{device_id}/{point.name}"
                    payload = json_lib.dumps({
                        "device_id": device_id,
                        "point": point.name,
                        "value": value,
                        "timestamp": time.time(),
                        "unit": point.unit,
                    })
                    try:
                        if self._broker and hasattr(self._broker, 'internal_publish'):
                            await self._broker.internal_publish(
                                topic=topic,
                                data=payload.encode("utf-8"),
                            )
                    except Exception as e:
                        logger.debug("MQTT publish failed for %s: %s", topic, e)
            await asyncio.sleep(interval)

    async def _publish_device(self, device_id: str) -> None:
        import json as json_lib

        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return
        proto_config = config.protocol_config or {}
        topic_prefix = proto_config.get("topic_prefix", "protoforge")
        for point in config.points:
            value = behavior.get_value(point.name)
            topic = f"{topic_prefix}/{device_id}/{point.name}"
            payload = json_lib.dumps({
                "device_id": device_id,
                "point": point.name,
                "value": value,
                "timestamp": time.time(),
                "unit": point.unit,
            })
            try:
                if self._broker and hasattr(self._broker, 'internal_publish'):
                    await self._broker.internal_publish(
                        topic=topic,
                        data=payload.encode("utf-8"),
                    )
            except Exception as e:
                logger.debug("MQTT publish failed for %s: %s", topic, e)
