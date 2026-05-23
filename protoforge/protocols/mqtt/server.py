import asyncio
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import StandardDeviceBehavior, ProtocolServer, ProtocolStatus  # FIXED: 改继承StandardDeviceBehavior
from protoforge.protocols.behavior import DynamicValueGenerator
from protoforge.core.messages import msg, desc

logger = logging.getLogger(__name__)

try:
    from amqtt.broker import Broker
    from amqtt.contexts import Action
    from amqtt.session import Session
    ASYNC_MQTT_AVAILABLE = True
except ImportError:
    ASYNC_MQTT_AVAILABLE = False
    logger.warning("amqtt not installed, MQTT Broker will not be available. Install with: pip install protoforge[mqtt]")


class MqttDeviceBehavior(StandardDeviceBehavior):  # FIXED: 改继承StandardDeviceBehavior，复用_points/_values/_generators初始化
    def __init__(self, points: list[PointConfig]):
        super().__init__(points)  # FIXED: 调用super().__init__()初始化父类属性

    # FIXED-P1: 删除有缺陷的 generate_value 覆写，继承 StandardDeviceBehavior 已修复的实现

    def on_write(self, point_name: str, value: Any) -> bool:
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
        self._requested_port = 1883  # 用户请求的端口
        self._publish_task: asyncio.Task | None = None
        self._auth_required = False
        self._auth_username = ""
        self._auth_password = ""

    @property
    def actual_port(self) -> int:
        """返回 MQTT Broker 实际监听的端口（可能与配置不同）"""
        return self._port

    @property
    def requested_port(self) -> int:
        """返回用户配置的端口"""
        return self._requested_port

    async def start(self, config: dict[str, Any]) -> None:
        if not ASYNC_MQTT_AVAILABLE:
            raise RuntimeError("amqtt is not installed. Install with: pip install protoforge[mqtt]")

        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._requested_port = config.get("port", 1883)
        self._port = self._requested_port
        publish_interval = config.get("publish_interval", 5)
        self._auth_required = config.get("auth_required", False)
        self._auth_username = config.get("auth_username", "")
        self._auth_password = config.get("auth_password", "")

        try:
            auth_plugins = {}
            if self._auth_required and self._auth_username:
                auth_plugins["amqtt.plugins.authentication.AnonymousAuthPlugin"] = {
                    "allow_anonymous": False,
                }
                auth_plugins["protoforge.mqtt_auth.MqttAuthPlugin"] = {
                    "username": self._auth_username,
                    "password": self._auth_password,
                }
            else:
                auth_plugins["amqtt.plugins.authentication.AnonymousAuthPlugin"] = {
                    "allow_anonymous": True,
                }
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

            # FIXED: 检测端口是否被自动更换（EdgeLite社区版会处理端口冲突）
            actual_port = self._get_actual_port()
            if actual_port and actual_port != self._requested_port:
                self._port = actual_port  # 更新为实际端口
                config["port"] = actual_port  # 写回config，让engine能获取
                config["_port_changed"] = True
                config["_original_port"] = self._requested_port
                logger.warning(
                    "MQTT Broker requested port %d but is running on port %d. "
                    "EdgeLite may need to connect to port %d instead of %d",
                    self._requested_port, actual_port, actual_port, self._requested_port
                )
                self._log_debug("system", "port_changed",
                                f"MQTT Broker port changed from {self._requested_port} to {actual_port}",
                                detail={"requested_port": self._requested_port, "actual_port": actual_port})

            logger.info("MQTT Broker starting on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"MQTT Broker started {self._host}:{self._port}",
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
                    logger.debug("MQTT task cancelled")
                except Exception as e:
                    logger.warning("MQTT publish task error: %s", e)
            if self._broker:
                await self._broker.shutdown()
        except Exception as e:
            logger.warning("MQTT broker stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("MQTT broker stopped")
            self._log_debug("system", "server_stop", "MQTT broker stopped")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = MqttDeviceBehavior(device_config.points)
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
        await self._update_default_device_async(device_config.id)
        logger.info("MQTT device created: %s", device_config.id)
        self._log_debug("system", "device_create",
                        f"MQTT device created: {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
        await self._clear_default_device_async(device_id)
        logger.info("MQTT device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"MQTT device removed: {device_id}",
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
        success = behavior.on_write(point_name, value)
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
                    "description": desc("listen_address", "Listen address"),
                },
                "port": {
                    "type": "integer",
                    "default": 1883,
                    "description": desc("listen_port", "Listen port"),
                },
                "publish_interval": {
                    "type": "integer",
                    "default": 5,
                    "description": desc("mqtt_publish_interval", "Data publish interval (seconds)"),
                },
                "auth_required": {
                    "type": "boolean",
                    "default": False,
                    "description": desc("mqtt_auth_required", "Enable username/password authentication"),
                },
                "auth_username": {
                    "type": "string",
                    "default": "",
                    "description": desc("mqtt_auth_username", "Authentication username"),
                },
                "auth_password": {
                    "type": "string",
                    "default": "",
                    "description": desc("mqtt_auth_password", "Authentication password"),
                },
                "tls_enabled": {
                    "type": "boolean",
                    "default": False,
                    "description": desc("mqtt_tls_enabled", "Enable TLS encryption"),
                },
                "tls_cert_path": {
                    "type": "string",
                    "default": "",
                    "description": desc("mqtt_tls_cert_path", "TLS certificate file path (PEM format)"),
                },
                "tls_key_path": {
                    "type": "string",
                    "default": "",
                    "description": desc("mqtt_tls_key_path", "TLS private key file path (PEM format)"),
                },
            },
        }

    async def _publish_loop(self, interval: int) -> None:
        import json as json_lib

        while self._status == ProtocolStatus.RUNNING:
            # FIXED-P1: 使用快照迭代，避免与 create_device/remove_device 并发修改时 RuntimeError
            for device_id, config in dict(self._device_configs).items():
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

    def _get_actual_port(self) -> int | None:
        """检测 MQTT Broker 实际监听的端口（可能与配置不同，如果端口被占用会自动更换）"""
        import socket

        # 先尝试获取 amqtt broker 内部信息
        try:
            if hasattr(self._broker, 'listeners') and self._broker.listeners:
                for name, listener in self._broker.listeners.items():
                    if hasattr(listener, 'server') and listener.server:
                        sock = getattr(listener.server, 'socket', None)
                        if sock:
                            addr = sock.getsockname()
                            if addr:
                                return addr[1]
        except Exception:
            pass

        # Fallback: 尝试连接检测
        for port in [self._requested_port, self._requested_port + 1, self._requested_port - 1]:
            if port == self._port:
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    result = s.connect_ex((self._host, port))
                    if result == 0:
                        return port
            except Exception:
                pass

        # 如果请求的端口正在监听，返回它
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                result = s.connect_ex((self._host, self._requested_port))
                if result == 0:
                    return self._requested_port
        except Exception:
            pass

        return self._port  # 返回配置的端口作为默认值
