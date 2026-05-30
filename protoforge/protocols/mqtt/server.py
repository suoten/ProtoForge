import asyncio
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import StandardDeviceBehavior, ProtocolServer, ProtocolStatus
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
        self._requested_port = 1883
        self._publish_task: asyncio.Task | None = None
        self._auth_required = False
        self._auth_username = ""
        self._auth_password = ""
        self._clean_session = True
        self._registered_client_ids: set[str] = set()

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
        self._validate_port(self._requested_port)
        self._port = self._requested_port
        publish_interval = config.get("publish_interval", 5)
        self._auth_required = config.get("auth_required", False)
        self._auth_username = config.get("auth_username", "")
        self._auth_password = config.get("auth_password", "")
        self._clean_session = config.get("clean_session", True)  # FIXED-P0: 读取Clean Session配置
        self._auth_users: dict[str, str] = {}  # FIXED-P1: 多用户认证字典
        auth_users_str = config.get("auth_users", "")
        if auth_users_str:
            try:
                import json as _json
                parsed = _json.loads(auth_users_str)
                if isinstance(parsed, dict):
                    self._auth_users = {str(k): str(v) for k, v in parsed.items()}
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("MQTT auth_users config parse error, ignoring")

        try:
            auth_plugins = {}
            if self._auth_required and (self._auth_username or self._auth_users):
                auth_plugins["amqtt.plugins.authentication.AnonymousAuthPlugin"] = {
                    "allow_anonymous": False,
                }
                auth_plugin_config = {
                    "username": self._auth_username,
                    "password": self._auth_password,
                }
                if self._auth_users:  # FIXED-P1: 传递多用户配置到认证插件
                    auth_plugin_config["users"] = self._auth_users
                auth_plugins["protoforge.mqtt_auth.MqttAuthPlugin"] = auth_plugin_config
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
        for device_id in list(self._behaviors.keys()):  # FIXED-P0: 停止前发布所有设备的遗嘱消息
            await self._publish_will(device_id)
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
        proto_config = device_config.protocol_config or {}
        client_id = proto_config.get("client_id", "")
        if client_id:
            if client_id in self._registered_client_ids:
                raise ValueError(
                    f"MQTT ClientID '{client_id}' is already in use by another device. "
                    "ClientID must be unique within the same broker."
                )
            self._registered_client_ids.add(client_id)
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config
        await self._update_default_device_async(device_config.id)
        logger.info("MQTT device created: %s", device_config.id)
        self._log_debug("system", "device_create",
                        f"MQTT device created: {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        await self._publish_will(device_id)
        async with self._behaviors_lock:
            config = self._device_configs.pop(device_id, None)
            self._behaviors.pop(device_id, None)
            if config:
                proto_config = config.protocol_config or {}
                client_id = proto_config.get("client_id", "")
                if client_id:
                    self._registered_client_ids.discard(client_id)
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
                "auth_users": {
                    "type": "string",
                    "default": "",
                    "description": desc("mqtt_auth_users", 'Multi-user auth JSON, e.g. {"user1":"pass1","user2":"pass2"}'),
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
                "qos": {
                    "type": "integer",
                    "default": 0,
                    "enum": [0, 1, 2],
                    "description": desc("mqtt_qos", "MQTT QoS level (0=At most once, 1=At least once, 2=Exactly once)"),
                },
                "retain": {
                    "type": "boolean",
                    "default": False,
                    "description": desc("mqtt_retain", "Enable MQTT retain messages"),
                },
                "will_topic": {
                    "type": "string",
                    "default": "",
                    "description": desc("mqtt_will_topic", "Will message topic (supports {device_id} placeholder)"),
                },
                "will_message": {
                    "type": "string",
                    "default": "",
                    "description": desc("mqtt_will_message", "Will message payload (supports {device_id} placeholder)"),
                },
                "will_qos": {
                    "type": "integer",
                    "default": 0,
                    "enum": [0, 1, 2],
                    "description": desc("mqtt_will_qos", "Will message QoS level"),
                },
                "will_retain": {
                    "type": "boolean",
                    "default": True,
                    "description": desc("mqtt_will_retain", "Will message retain flag"),
                },
                "clean_session": {
                    "type": "boolean",
                    "default": True,
                    "description": desc("mqtt_clean_session", "Clean session flag (True=no persistent state, False=persistent session)"),
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
                qos = proto_config.get("qos", 0)  # FIXED-P0: QoS参数移到外层
                retain = proto_config.get("retain", False)  # FIXED-P0: Retain参数移到外层
                for point in config.points:
                    value = behavior.get_value(point.name)
                    # FIXED-P1: 优先使用point.address并替换{device_id}占位符，回退到默认格式
                    if point.address and '{device_id}' in point.address:
                        topic = point.address.replace('{device_id}', device_id)
                    elif point.address:
                        topic = point.address
                    else:
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
                            # FIXED-P0: 添加qos和retain参数，支持MQTT QoS 0/1/2 和 Retain 消息
                            await self._broker.internal_publish(
                                topic=topic,
                                data=payload.encode("utf-8"),
                                qos=qos,
                                retain=retain,
                            )
                    except Exception as e:
                        logger.warning("MQTT publish failed for %s: %s", topic, e)  # FIXED-P1: QoS 1/2发布失败应warning级别
            await asyncio.sleep(interval)

    async def _publish_device(self, device_id: str) -> None:
        import json as json_lib

        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return
        proto_config = config.protocol_config or {}
        topic_prefix = proto_config.get("topic_prefix", "protoforge")
        qos = proto_config.get("qos", 0)  # FIXED-P0: 添加QoS支持
        retain = proto_config.get("retain", False)  # FIXED-P0: 添加Retain支持
        for point in config.points:
            value = behavior.get_value(point.name)
            # FIXED-P1: 优先使用point.address并替换{device_id}占位符，回退到默认格式
            if point.address and '{device_id}' in point.address:
                topic = point.address.replace('{device_id}', device_id)
            elif point.address:
                topic = point.address
            else:
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
                        qos=qos,
                        retain=retain,
                    )
            except Exception as e:
                logger.warning("MQTT publish failed for %s: %s", topic, e)  # FIXED-P1: QoS 1/2发布失败应warning级别

    async def _publish_will(self, device_id: str) -> None:  # FIXED-P0: 发布遗嘱消息，通知订阅者设备离线
        config = self._device_configs.get(device_id)
        if not config:
            return
        proto_config = config.protocol_config or {}
        will_topic = proto_config.get("will_topic", "")
        if not will_topic:
            return
        will_message = proto_config.get("will_message", "")
        will_qos = proto_config.get("will_qos", 0)
        will_retain = proto_config.get("will_retain", True)
        will_topic = will_topic.replace("{device_id}", device_id)
        will_message = will_message.replace("{device_id}", device_id)
        try:
            if self._broker and hasattr(self._broker, 'internal_publish'):
                await self._broker.internal_publish(
                    topic=will_topic,
                    data=will_message.encode("utf-8"),
                    qos=will_qos,
                    retain=will_retain,
                )
                logger.info("MQTT will message published for device %s to %s", device_id, will_topic)
        except Exception as e:
            logger.warning("MQTT will message publish failed for %s: %s", device_id, e)

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
        except Exception as e:
            logger.debug("Failed to get actual port from broker listener: %s", e)

        # Fallback: 尝试连接检测 — 先检查配置端口是否在监听
        for port in [self._port, self._requested_port, self._requested_port + 1, self._requested_port - 1]:
            if port <= 0:
                continue
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    result = s.connect_ex((self._host if self._host != "0.0.0.0" else "127.0.0.1", port))
                    if result == 0:
                        return port
            except Exception as e:
                logger.debug("Port probe failed for %d: %s", port, e)

        return self._port  # 返回配置的端口作为默认值
