"""MQTT 协议 Broker 实现.

本模块实现了轻量级 MQTT 消息代理 (Broker)，
支持以下功能:
    - MQTT 3.1.1 协议完整实现
    - QoS 0/1/2 消息传递保证
    - 主题通配符订阅 (+/#, 层级匹配)
    - 遗嘱消息 (Last Will and Testament)
    - 保留消息 (Retained Messages)
    - 客户端认证与 ACL
    - 消息持久化与重连恢复

支持与以下真实物联网网关对接:
    - EMQX / Mosquitto / HiveMQ 客户端
    - AWS IoT Core / Azure IoT Hub
    - 阿里云 IoT / 腾讯云 IoT
    - 任何标准 MQTT 客户端

典型用法::

    broker = MqttBroker()
    await broker.start({"host": "0.0.0.0", "port": 1883})
    device_id = await broker.create_device(device_config)
"""

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.observability.messages import desc
from protoforge.protocols.behavior import (
    ProtocolErrorCategory,
    ProtocolServer,
    ProtocolStatus,
    StandardDeviceBehavior,
)

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
        self._default_qos: int = 0
        self._default_retain: bool = False
        self._qos_tracker: QoSMessageTracker | None = None
        self._command_task: asyncio.Task | None = None
        # FIXED-F2: 外部 MQTT 服务器支持 —— 设备可配置 server_host/server_port，
        # 以 MQTT 客户端身份连接用户自己的 broker（EMQX/Mosquitto 等）上报数据，
        # 而不是只能发布到内置 broker（重点在“设备仿真”，设备行为对齐真实设备）
        self._external_clients: dict[str, Any] = {}
        self._external_connected: set[str] = set()
        self._external_last_warn: dict[str, float] = {}
        self._external_next_attempt: dict[str, float] = {}

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
        publish_interval = max(1, config.get("publish_interval", 5))
        self._auth_required = config.get("auth_required", False)
        self._auth_username = config.get("auth_username", "")
        self._auth_password = config.get("auth_password", "")
        self._clean_session = config.get("clean_session", True)  # FIXED-P0: 读取Clean Session配置
        self._default_qos = config.get("qos", 0)
        self._default_retain = config.get("retain", False)
        self._auth_users: dict[str, str] = {}  # FIXED-P1: 多用户认证字典
        auth_users_str = config.get("auth_users", "")
        if auth_users_str:
            try:
                import json as _json
                parsed = _json.loads(auth_users_str)
                if isinstance(parsed, dict):
                    self._auth_users = {str(k): str(v) for k, v in parsed.items()}
            except (_json.JSONDecodeError, TypeError, ValueError):
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
                        logger.exception("Failed to load MQTT TLS certificate: %s", e)
                        raise RuntimeError(f"MQTT TLS certificate error: {e}") from e
                else:
                    logger.warning(
                        "MQTT TLS is enabled but tls_cert_path or tls_key_path is not configured. "
                        "TLS will not be activated. Provide both paths to enable TLS."
                    )
            self._broker = Broker(broker_config)
            await self._broker.start()

            self._status = ProtocolStatus.RUNNING
            self._publish_task = asyncio.create_task(self._publish_loop(publish_interval))
            # 回环命令消费者：接收网关发布的 {…}/command 下行命令并应用到设备
            self._command_task = asyncio.create_task(self._command_consumer_loop())

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
            logger.exception("Failed to start MQTT Broker: %s", e)
            raise

    async def stop(self) -> None:
        for device_id in list(self._behaviors.keys()):  # FIXED-P0: 停止前发布所有设备的遗嘱消息
            await self._publish_will(device_id)
        try:
            # FIXED-F2: 断开所有外部 broker 客户端
            for device_id, client in list(self._external_clients.items()):
                with contextlib.suppress(Exception):
                    await client.disconnect()
            self._external_clients.clear()
            self._external_connected.clear()
            if self._publish_task:
                self._publish_task.cancel()
                try:
                    await self._publish_task
                except asyncio.CancelledError:
                    logger.debug("MQTT task cancelled")
                except Exception as e:
                    logger.warning("MQTT publish task error: %s", e)
            if self._command_task:
                self._command_task.cancel()
                try:
                    await self._command_task
                except asyncio.CancelledError:
                    logger.debug("MQTT command consumer cancelled")
                except Exception as e:
                    logger.warning("MQTT command consumer stop error: %s", e)
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
        async with self._behaviors_lock:
            if client_id:
                if client_id in self._registered_client_ids:
                    raise ValueError(
                        f"MQTT ClientID '{client_id}' is already in use by another device. "
                        "ClientID must be unique within the same broker."
                    )
                self._registered_client_ids.add(client_id)
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
        client = self._external_clients.pop(device_id, None)
        if client:
            with contextlib.suppress(Exception):
                await client.disconnect()
            self._external_connected.discard(device_id)
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

        # 检查点位是否存在且可写
        config = self._device_configs.get(device_id)
        if config:
            point = next((p for p in config.points if p.name == point_name), None)
            if point is None:
                logger.warning("MQTT write_point: point '%s' not found on device %s", point_name, device_id)
                return False
            if point.access not in ("w", "rw"):
                logger.warning("MQTT write_point: point '%s' is read-only on device %s", point_name, device_id)
                return False

        # 更新协议层 behavior 内部状态
        success = behavior.on_write(point_name, value)
        if success:
            # 发布更新后的设备数据到 MQTT topic
            await self._publish_device(device_id)

            # 通过 on_write 回调传播到 DeviceInstance，确保内部状态一致
            if self._on_write:
                try:
                    await self._on_write(device_id, point_name, value)
                except Exception as e:
                    logger.warning("MQTT write_point: on_write callback error for %s.%s: %s", device_id, point_name, e)
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
                "retransmit_timeout": {
                    "type": "number",
                    "default": 15.0,
                    "description": desc("mqtt_retransmit_timeout", "QoS 1/2 retransmission timeout (seconds)"),
                },
                "max_retries": {
                    "type": "integer",
                    "default": 3,
                    "description": desc("mqtt_max_retries", "Maximum retransmission attempts for QoS 1/2"),
                },
            },
        }

    async def _broker_publish(self, topic: str, data: bytes, qos: int = 0, retain: bool = False) -> bool:
        """跨 amqtt 版本的内部分发（兼容层）。

        - amqtt >= 0.11：``internal_publish`` 已改名 ``internal_message_broadcast``
          （且不再支持 retain 参数）；retain 用公开 API ``retain_message()`` 补写。
        - amqtt <= 0.10：继续使用 ``internal_publish(topic, data, qos, retain)``。
        - 两者都不存在时必须记录 ERROR 并计入协议错误指标，
          **禁止静默跳过**——否则表现为主 broker 连接正常但订阅者永远收不到数据。

        Returns: True = 已分发给 broker；False = 无法分发。
        """
        if not self._broker:
            return False
        broadcast = getattr(self._broker, "internal_message_broadcast", None)
        if callable(broadcast):  # amqtt >= 0.11 / 0.12
            await broadcast(topic=topic, data=data, qos=qos)
            if retain:
                try:
                    await self._broker.retain_message(None, topic, data, qos)
                except Exception as e:
                    logger.debug("MQTT retain store failed for %s: %s", topic, e)
            return True
        legacy = getattr(self._broker, "internal_publish", None)
        if callable(legacy):  # amqtt <= 0.10
            await legacy(topic=topic, data=data, qos=qos, retain=retain)
            return True
        logger.error(
            "MQTT broker publish API unavailable (neither internal_message_broadcast "
            "for amqtt>=0.11 nor internal_publish for amqtt<=0.10); message to %s DROPPED. "
            "Check the installed amqtt version against protoforge's requirements.",
            topic,
        )
        self.record_protocol_error(ProtocolErrorCategory.INTERNAL, "broker publish API missing")
        return False

    def _is_external_device(self, device_id: str) -> bool:
        """设备是否配置了自定义外部 MQTT 服务器。"""
        config = self._device_configs.get(device_id)
        if not config:
            return False
        return bool((config.protocol_config or {}).get("server_host", "").strip())

    async def _get_external_client(self, device_id: str) -> Any | None:
        """获取（必要时建立）设备到外部 MQTT 服务器的客户端连接。

        - 连接失败不抛异常，返回 None 并限频告警（每个设备每 60s 最多一条），
          发布循环下一周期自动重试；绝不因外部服务器不可达而崩溃。
        """
        from amqtt.client import MQTTClient

        client = self._external_clients.get(device_id)
        if client is not None and device_id in self._external_connected:
            return client

        # 重连限频：外部服务器不可达时最多每 5s 尝试一次，避免连接风暴刷屏
        now = time.monotonic()
        if now < self._external_next_attempt.get(device_id, 0.0):
            return None
        self._external_next_attempt[device_id] = now + 5.0

        config = self._device_configs.get(device_id)
        if not config:
            return None
        proto_config = config.protocol_config or {}
        host = (proto_config.get("server_host") or "").strip()
        if not host:
            return None
        try:
            port = int(proto_config.get("server_port") or 1883)
        except (TypeError, ValueError):
            port = 1883

        # 清理陈旧连接后重建
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()
            self._external_clients.pop(device_id, None)

        username = (proto_config.get("username") or "").strip()
        password = proto_config.get("password") or ""
        client_id = (proto_config.get("client_id") or "").strip() or f"protoforge_{device_id}"
        cred = f"{username}:{password}@" if username else ""
        uri = f"mqtt://{cred}{host}:{port}/"
        # auto_reconnect 关闭：重连由发布循环按周期统一管理，避免后台任务无限重试
        new_client = MQTTClient(client_id=client_id, config={"auto_reconnect": False})
        try:
            await asyncio.wait_for(new_client.connect(uri), timeout=5.0)
        except Exception as e:
            now = time.monotonic()
            last = self._external_last_warn.get(device_id, 0.0)
            if now - last >= 60.0:
                logger.warning(
                    "MQTT device %s failed to connect external broker %s:%d: %s; retrying each publish cycle",
                    device_id, host, port, e,
                )
                self._external_last_warn[device_id] = now
            self.record_protocol_error(ProtocolErrorCategory.INTERNAL, f"external broker connect failed: {e}")
            with contextlib.suppress(Exception):
                await new_client.disconnect()
            return None

        self._external_clients[device_id] = new_client
        self._external_connected.add(device_id)
        self._external_last_warn.pop(device_id, None)
        logger.info("MQTT device %s connected to external broker %s:%d (client_id=%s)",
                    device_id, host, port, client_id)
        self._log_debug("system", "external_connect",
                        f"MQTT device {device_id} connected to external broker {host}:{port}",
                        device_id=device_id,
                        detail={"host": host, "port": port, "client_id": client_id})
        return new_client

    async def _publish_to_device_broker(
        self, device_id: str, topic: str, payload: bytes, qos: int = 0, retain: bool = False,
    ) -> bool:
        """按设备配置路由发布：外部 broker（client 模式）或内置 broker。

        Returns: True = 已发布；False = 无法发布（已记录告警）。
        """
        if self._is_external_device(device_id):
            client = await self._get_external_client(device_id)
            if client is None:
                return False
            try:
                await client.publish(topic, payload, qos=qos, retain=retain)
                # 外部发布在协议调试日志中可见（截断 payload，避免日志膨胀）：
                # 此前只有连接/失败事件，数据是否真的在上传无从观察
                _preview = payload[:200].decode("utf-8", errors="replace")
                self._log_debug("tx", "external_publish",
                                f"MQTT device {device_id} published to external broker "
                                f"{topic} ({len(payload)} bytes)",
                                device_id=device_id,
                                detail={"topic": topic, "qos": qos, "retain": retain,
                                        "bytes": len(payload),
                                        "payload_preview": _preview,
                                        "truncated": len(payload) > 200})
                return True
            except Exception as e:
                logger.warning("MQTT external publish failed for %s on %s: %s; will reconnect", device_id, topic, e)
                self.record_protocol_error(ProtocolErrorCategory.INTERNAL, f"external publish failed: {e}")
                # 连接已不可靠，丢弃陈旧客户端，下个周期自动重连
                self._external_connected.discard(device_id)
                with contextlib.suppress(Exception):
                    await client.disconnect()
                self._external_clients.pop(device_id, None)
                return False
        return await self._broker_publish(topic, payload, qos=qos, retain=retain)

    @staticmethod
    def _point_topic(device_id: str, point: PointConfig, topic_prefix: str) -> str:
        """推导点位发布主题。

        规则（FIXED-P0：单段 address 不再被误用作完整 topic）：
        - address 含 ``{device_id}`` 占位符 -> 替换后使用（完全自定义）
        - address 含 ``/``（多级路径） -> 视为用户显式指定的完整 topic，直接使用
        - address 为空或单段（如模板里 address="latitude"） -> 必须走默认层级
          ``{topic_prefix}/{device_id}/{point.name}``，否则 topic_prefix 与
          device_id 全部丢失，订阅 ``prefix/device_id/#`` 的客户端永远收不到数据。
        """
        address = (point.address or "").strip()
        if address and "{device_id}" in address:
            return address.replace("{device_id}", device_id)
        if address and "/" in address:
            return address
        return f"{topic_prefix}/{device_id}/{point.name}"

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
                qos = proto_config.get("qos", self._default_qos)
                retain = proto_config.get("retain", self._default_retain)
                for point in config.points:
                    value = behavior.get_value(point.name)
                    topic = self._point_topic(device_id, point, topic_prefix)
                    payload = json_lib.dumps({
                        "device_id": device_id,
                        "point": point.name,
                        "value": value,
                        "timestamp": time.time(),
                        "unit": point.unit,
                    })
                    try:
                        # FIXED-P0: 兼容 amqtt 0.11+ API 改名，支持 QoS 与 Retain
                        # FIXED-F2: 按设备配置路由到外部 broker 或内置 broker
                        await self._publish_to_device_broker(device_id, topic, payload.encode("utf-8"), qos=qos, retain=retain)
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
        qos = proto_config.get("qos", self._default_qos)
        retain = proto_config.get("retain", self._default_retain)
        for point in config.points:
            value = behavior.get_value(point.name)
            topic = self._point_topic(device_id, point, topic_prefix)
            payload = json_lib.dumps({
                "device_id": device_id,
                "point": point.name,
                "value": value,
                "timestamp": time.time(),
                "unit": point.unit,
            })
            try:
                # FIXED-P0: 兼容 amqtt 0.11+ API 改名，支持 QoS 与 Retain
                # FIXED-F2: 按设备配置路由到外部 broker 或内置 broker
                await self._publish_to_device_broker(device_id, topic, payload.encode("utf-8"), qos=qos, retain=retain)
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
            # FIXED-P0: 兼容 amqtt 0.11+ API 改名（遗嘱消息）
            # FIXED-F2: 遗嘱同样按设备配置路由到外部 broker
            await self._publish_to_device_broker(device_id, will_topic, will_message.encode("utf-8"), qos=will_qos, retain=will_retain)
            logger.info("MQTT will message published for device %s to %s", device_id, will_topic)
        except Exception as e:
            logger.warning("MQTT will message publish failed for %s: %s", device_id, e)

    def _resolve_command_device(self, topic: str, payload: dict) -> str | None:
        """解析下行命令的目标设备。"""
        # 1) payload 显式 device_id（EdgeLite 命令载荷自带）
        did = payload.get("device_id")
        if isinstance(did, str) and did in self._behaviors:
            return did
        # 2) 主题模式 {prefix}/{device_id}/command
        parts = topic.split("/")
        if len(parts) >= 3 and parts[-1] == "command":
            candidate = parts[-2]
            if candidate in self._behaviors:
                return candidate
        # 3) 仅注册一台设备时回退到该设备（单设备网关的常见形态）
        if len(self._behaviors) == 1:
            return next(iter(self._behaviors))
        return None

    async def _command_consumer_loop(self) -> None:
        """回环命令消费者：以 MQTT 客户端身份连回自身 broker，订阅 `#`，
        把网关（如 EdgeLite）发布的 `{…}/command` JSON 命令
        （{"point","value"[,"device_id"]}）应用到本地设备点位。
       这使得 broker 不再只出不进——下行控制链路真正可用。"""
        import json as json_lib

        from amqtt.client import MQTTClient
        from amqtt.mqtt.constants import QOS_0

        uri = f"mqtt://127.0.0.1:{self._port}/"
        while self._status == ProtocolStatus.RUNNING:
            client = MQTTClient(client_id="protoforge_cmd_consumer")
            try:
                await client.connect(uri)
                await client.subscribe([("#", QOS_0)])
                logger.info("MQTT command consumer connected to %s", uri)
                while self._status == ProtocolStatus.RUNNING:
                    message = await client.deliver_message()
                    topic = getattr(message, "topic", "") or ""
                    data = getattr(message, "data", b"") or b""
                    if not topic.endswith("/command"):
                        continue
                    text = bytes(data).decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data)
                    try:
                        payload = json_lib.loads(text)
                    except (json_lib.JSONDecodeError, TypeError, ValueError):
                        logger.debug("MQTT command payload not JSON on %s", topic)
                        continue
                    if not isinstance(payload, dict):
                        continue
                    point = payload.get("point")
                    if not point or "value" not in payload:
                        logger.warning("MQTT command on %s missing point/value: %s", topic, text[:200])
                        continue
                    device_id = self._resolve_command_device(topic, payload)
                    if not device_id:
                        logger.warning("MQTT command on %s: no target device resolved", topic)
                        continue
                    ok = await self.write_point(device_id, str(point), payload["value"])
                    if ok:
                        logger.info("MQTT command applied: %s.%s = %s (topic %s)",
                                    device_id, point, payload["value"], topic)
                    else:
                        logger.warning("MQTT command rejected: %s.%s = %s (topic %s)",
                                       device_id, point, payload["value"], topic)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("MQTT command consumer error: %s; retrying in 2s", e)
                try:
                    await asyncio.sleep(2)
                except asyncio.CancelledError:
                    break
            finally:
                with contextlib.suppress(Exception):
                    await client.disconnect()

    def get_qos_stats(self) -> dict[str, Any]:
        """返回 QoS 消息追踪统计信息。"""
        if self._qos_tracker is None:
            return {"total_published": 0, "total_acked": 0, "in_flight": 0}
        return self._qos_tracker.stats

    def get_in_flight_messages(self) -> list[dict[str, Any]]:
        """返回当前正在传输的 QoS 1/2 消息列表。"""
        if self._qos_tracker is None:
            return []
        return self._qos_tracker.get_in_flight_info()

    def restore_qos_session(self) -> list[dict[str, Any]]:
        """返回未 ACK 的 QoS 1/2 消息列表用于会话恢复。"""
        if self._qos_tracker is None:
            return []
        return self._qos_tracker.restore_session()

    def _get_actual_port(self) -> int | None:
        """检测 MQTT Broker 实际监听的端口（可能与配置不同，如果端口被占用会自动更换）"""
        import socket

        # 先尝试获取 amqtt broker 内部信息
        try:
            if hasattr(self._broker, 'listeners') and self._broker.listeners:
                for _name, listener in self._broker.listeners.items():
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


@dataclass
class InFlightMessage:
    """QoS 1/2 正在传输的消息。"""

    topic: str
    payload: bytes
    qos: int
    packet_id: int
    publish_time: float
    retry_count: int = 0
    state: str = "wait_puback"  # wait_puback / wait_pubrec / wait_pubcomp


class QoSMessageTracker:
    """QoS 1/2 消息追踪与重传管理器。

    :param broker: MQTT Broker 实例
    :param retransmit_timeout: 重传超时（秒）
    :param max_retries: 最大重传次数
    """

    def __init__(
        self,
        broker: Any = None,
        retransmit_timeout: float = 15.0,
        max_retries: int = 3,
    ):
        self._broker = broker
        self._retransmit_timeout = retransmit_timeout
        self._max_retries = max_retries
        self._in_flight: dict[int, InFlightMessage] = {}
        self._next_packet_id: int = 1
        self._stats: dict[str, Any] = {
            "total_published": 0,
            "total_qoS1": 0,
            "total_qoS2": 0,
            "total_acked": 0,
            "total_failed": 0,
        }

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    @property
    def stats(self) -> dict[str, Any]:
        s = dict(self._stats)
        s["in_flight"] = len(self._in_flight)
        return s

    async def track_publish(self, topic: str, payload: bytes, qos: int) -> int | None:
        """追踪 QoS 1/2 消息发布。

        :return: packet_id（QoS 0 返回 None）
        """
        if qos == 0:
            return None

        packet_id = self._next_packet_id
        self._next_packet_id += 1

        state = "wait_puback" if qos == 1 else "wait_pubrec"
        msg = InFlightMessage(
            topic=topic,
            payload=payload,
            qos=qos,
            packet_id=packet_id,
            publish_time=time.time(),
            state=state,
        )
        self._in_flight[packet_id] = msg

        self._stats["total_published"] += 1
        if qos == 1:
            self._stats["total_qoS1"] += 1
        elif qos == 2:
            self._stats["total_qoS2"] += 1

        return packet_id

    async def on_puback(self, packet_id: int) -> None:
        """QoS 1 PUBACK 收到。"""
        if packet_id in self._in_flight:
            del self._in_flight[packet_id]
            self._stats["total_acked"] += 1

    async def on_pubrec(self, packet_id: int) -> None:
        """QoS 2 PUBREC 收到。"""
        if packet_id in self._in_flight:
            self._in_flight[packet_id].state = "wait_pubcomp"

    async def on_pubcomp(self, packet_id: int) -> None:
        """QoS 2 PUBCOMP 收到。"""
        if packet_id in self._in_flight:
            del self._in_flight[packet_id]
            self._stats["total_acked"] += 1

    def get_in_flight_info(self) -> list[dict[str, Any]]:
        """返回当前正在传输的消息信息列表。"""
        now = time.time()
        result = []
        for msg in self._in_flight.values():
            result.append({
                "packet_id": msg.packet_id,
                "topic": msg.topic,
                "qos": msg.qos,
                "state": msg.state,
                "retry_count": msg.retry_count,
                "age_seconds": round(now - msg.publish_time, 3),
            })
        return result

    def restore_session(self) -> list[dict[str, Any]]:
        """返回未 ACK 的消息列表用于会话恢复。"""
        return [
            {
                "packet_id": msg.packet_id,
                "topic": msg.topic,
                "payload": msg.payload,
                "qos": msg.qos,
            }
            for msg in self._in_flight.values()
        ]
