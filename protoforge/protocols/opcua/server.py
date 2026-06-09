import asyncio
import ipaddress
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import ProtocolServer, ProtocolStatus
from protoforge.core.messages import msg, desc
from protoforge.protocols.behavior import StandardDeviceBehavior

logger = logging.getLogger(__name__)

try:
    from asyncua import Server, ua
    ASYNCUA_AVAILABLE = True
except ImportError:
    ASYNCUA_AVAILABLE = False
    logger.warning("asyncua not installed, OPC-UA protocol will not be available")


def _parse_node_id(address: str, default_ns: int) -> tuple[int, str]:
    """Bug2-FIX: 解析point.address中的ns=X;s=Y格式，返回(namespace_index, identifier)。

    支持的格式:
      - "ns=2;s=Node1"  -> (2, "Node1")
      - "ns=3;i=100"    -> (3, "100")
      - "Node1"          -> (default_ns, "Node1")
    """
    m = re.match(r'^ns=(\d+);[si]=(.+)$', address)
    if m:
        return int(m.group(1)), m.group(2)
    return default_ns, address


def _ensure_certificates(cert_dir: str | None = None, force: bool = False) -> tuple[str, str]:
    if cert_dir is None:
        cert_dir = str(Path.home() / ".protoforge" / "opcua_certs")
    cert_path = os.path.join(cert_dir, "server_cert.pem")
    key_path = os.path.join(cert_dir, "server_key.pem")

    if not force and os.path.isfile(cert_path) and os.path.isfile(key_path):
        logger.info("OPC-UA certificates already exist at %s", cert_dir)
        return cert_path, key_path

    os.makedirs(cert_dir, exist_ok=True)

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "ProtoForge OPC-UA Server"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ProtoForge"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPAddress("0.0.0.0")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))

        logger.info("OPC-UA self-signed certificate generated at %s", cert_dir)
    except ImportError:
        logger.warning(
            "cryptography package not installed. Cannot auto-generate OPC-UA certificates. "
            "Install with: pip install cryptography. "
            "You can manually provide certificates via certificate_path/private_key_path config."
        )
        return "", ""
    except Exception as e:
        logger.error("Failed to generate OPC-UA certificates: %s", e)
        return "", ""

    return cert_path, key_path


class OpcUaDeviceBehavior(StandardDeviceBehavior):  # FIXED: 改继承StandardDeviceBehavior，复用_points/_values/_generators初始化
    def __init__(self, points: list[PointConfig]):
        super().__init__(points)  # FIXED: 调用super().__init__()初始化父类属性
        logger.debug("OpcUaDeviceBehavior initialized with points: %s", list(self._points.keys()))

    # FIXED-P1: 删除有缺陷的 generate_value 覆写，继承 StandardDeviceBehavior 已修复的实现

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            logger.debug("OpcUaDeviceBehavior.on_write success: %s = %s", point_name, value)
            return True
        logger.warning("OpcUaDeviceBehavior.on_write failed: point '%s' not found in _values. Available keys: %s", point_name, list(self._values.keys()))
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
        self._point_types: dict[str, str] = {}  # FIXED: 存储每个点位的数据类型
        self._device_namespaces: dict[str, str] = {}
        self._endpoint = "opc.tcp://0.0.0.0:4840/protoforge"
        self._host = "0.0.0.0"
        self._port = 4840
        self._requested_port = 4840
        self._server_task: asyncio.Task | None = None
        self._sync_task: asyncio.Task | None = None  # FIXED-P0: 动态值同步到OPC-UA节点的后台任务
        self._sync_interval: float = 1.0

    @property
    def actual_port(self) -> int:
        """返回协议服务器实际监听的端口"""
        return self._port

    @property
    def requested_port(self) -> int:
        """返回用户配置的端口"""
        return self._requested_port

    def _on_server_task_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("OPC-UA server task failed: %s", e)
            self._status = ProtocolStatus.ERROR

    async def start(self, config: dict[str, Any]) -> None:
        if not ASYNCUA_AVAILABLE:
            raise RuntimeError("asyncua is not installed. Install with: pip install protoforge[opcua]")

        self._status = ProtocolStatus.STARTING
        host = config.get("host", "0.0.0.0")
        self._requested_port = config.get("port", 4840)
        self._validate_port(self._requested_port)
        port = self._requested_port
        self._host = host
        self._port = port
        # Bug3-FIX: 当host为0.0.0.0时，endpoint使用127.0.0.1替代，避免部分客户端拒绝连接
        endpoint_host = "127.0.0.1" if host == "0.0.0.0" else host
        self._endpoint = f"opc.tcp://{endpoint_host}:{port}/protoforge"

        try:
            self._server = Server()
            await self._server.init()
            self._server.set_endpoint(self._endpoint)

            first_config = next(iter(self._device_configs.values()), None)
            security_mode = "None"
            security_policy = "None"
            if first_config:
                proto_config = first_config.protocol_config or {}
                server_name = proto_config.get("server_name", "ProtoForge OPC-UA Server")
                security_mode = proto_config.get("security_mode", "None")
                security_policy = proto_config.get("security_policy", "None")
            else:
                server_name = "ProtoForge OPC-UA Server"
            self._server.set_server_name(server_name)

            # FIXED: 显式设置安全策略，避免 asyncua 内部注册非开放端点时发出警告
            if ASYNCUA_AVAILABLE:
                try:
                    from asyncua import ua
                    if security_mode == "None":
                        # 仅允许无安全策略，避免 asyncua 尝试注册加密端点
                        self._server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
                    else:
                        # FIXED-P0: 增强安全策略支持 Modern 级别策略（兼容 OPC Foundation 最新规范）
                        policy_map = {
                            "None": ua.SecurityPolicyType.NoSecurity,
                            "Basic128Rsa15": ua.SecurityPolicyType.Basic128Rsa15,
                            "Basic256Sha256": ua.SecurityPolicyType.Basic256Sha256,
                            "Aes128Sha256RsaOaep": ua.SecurityPolicyType.Aes128Sha256RsaOaep,
                            "Aes256Sha256RsaPss": ua.SecurityPolicyType.Aes256Sha256RsaPss,
                        }
                        mode_map = {
                            "None": ua.MessageSecurityMode.None_,
                            "Sign": ua.MessageSecurityMode.Sign,
                            "SignAndEncrypt": ua.MessageSecurityMode.SignAndEncrypt,
                        }
                        try:
                            cert_path = proto_config.get("certificate_path", "")
                            key_path = proto_config.get("private_key_path", "")
                            if not cert_path or not key_path:
                                cert_path, key_path = _ensure_certificates(
                                    proto_config.get("cert_dir")
                                )
                            if cert_path and key_path:
                                await self._server.load_certificate(cert_path)
                                await self._server.load_private_key(key_path)
                                logger.info("OPC-UA certificates loaded")
                            # FIXED-P1: 同时注册NoSecurity和用户选择的策略，让客户端选择兼容的策略连接
                            selected_policy = policy_map.get(security_policy, ua.SecurityPolicyType.NoSecurity)
                            policies = [ua.SecurityPolicyType.NoSecurity]
                            if selected_policy != ua.SecurityPolicyType.NoSecurity:
                                policies.append(selected_policy)
                            self._server.set_security_policy(policies)
                            if security_policy != "None":
                                self._server.set_security_mode(mode_map.get(security_mode, ua.MessageSecurityMode.SignAndEncrypt))
                            logger.info("OPC-UA security: mode=%s, policy=%s", security_mode, security_policy)
                        except Exception as se:
                            logger.warning("Failed to set OPC-UA security policy: %s, falling back to None", se)
                            self._server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
                except Exception as e:
                    logger.warning("OPC-UA security configuration error: %s", e)

            uri = "urn:protoforge:simulation"
            try:
                self._idx = await self._server.register_namespace(uri)
            except AttributeError:
                try:
                    self._idx = await self._server.nodes.namespace.add(uri)
                except AttributeError:
                    self._idx = await self._server.get_namespace_index(uri)

            # Bug5-FIX: 服务启动后，为所有已注册设备补建OPC-UA节点
            for dev_id, dev_config in list(self._device_configs.items()):
                if dev_id not in self._device_nodes:
                    try:
                        await self._create_opcua_device(dev_config)
                    except Exception as e:
                        logger.warning("Failed to create OPC-UA device nodes for %s on start: %s", dev_id, e)

            self._status = ProtocolStatus.RUNNING
            self._server_task = asyncio.create_task(self._server.start())
            self._server_task.add_done_callback(self._on_server_task_done)
            self._sync_task = asyncio.create_task(self._sync_values_loop())  # FIXED-P0: 启动动态值同步任务
            logger.info("OPC-UA server starting at %s", self._endpoint)
            self._log_debug("system", "server_start",
                            msg("opcua", "service_started", host=self._host, port=self._port))
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start OPC-UA server: %s", e)
            raise

    async def stop(self) -> None:
        # FIXED: W10 - 先cancel task再stop server，避免先stop再cancel导致的冲突
        try:
            if self._sync_task:  # FIXED-P0: 取消动态值同步任务
                self._sync_task.cancel()
                try:
                    await self._sync_task
                except asyncio.CancelledError:
                    logger.debug("OPC-UA sync task cancelled")
                except Exception as e:
                    logger.warning("OPC-UA sync task error: %s", e)
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("OPC-UA task cancelled")
                except Exception as e:
                    logger.warning("OPC-UA server task error: %s", e)
            if self._server:
                try:
                    await self._server.stop()
                except Exception as e:
                    logger.warning("OPC-UA server stop error: %s", e)
        except Exception as e:
            logger.warning("OPC-UA stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("OPC-UA server stopped")
            self._log_debug("system", "server_stop", msg("opcua", "service_stopped"))

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = OpcUaDeviceBehavior(device_config.points)
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
        await self._update_default_device_async(device_config.id)

        proto_config = device_config.protocol_config or {}
        ns = proto_config.get("namespace", "protoforge")
        self._device_namespaces[device_config.id] = ns

        if self._status == ProtocolStatus.RUNNING and self._server:
            await self._create_opcua_device(device_config)

        logger.info("OPC-UA device created: %s (namespace=%s)", device_config.id, ns)
        self._log_debug("system", "device_create",
                        msg("opcua", "device_created", name=device_config.name),
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        # FIXED-P1: 将所有共享字典的 pop 操作移入 _behaviors_lock 内，避免与 OPC-UA 回调并发时 RuntimeError
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)
            self._device_namespaces.pop(device_id, None)
            nodes = self._device_nodes.pop(device_id, None)
            if nodes:
                point_nodes = nodes.get("points", {})
                for point_name in list(point_nodes.keys()):
                    point_node_key = f"{device_id}.{point_name}"
                    self._point_nodes.pop(point_node_key, None)
        await self._clear_default_device_async(device_id)
        # 节点删除操作（网络IO）在锁外执行，避免持锁时间过长
        if nodes:
            point_nodes = nodes.get("points", {})
            for point_name, point_node in point_nodes.items():
                try:
                    await point_node.delete()
                except Exception as e:
                    logger.warning("OPC-UA point node delete error: %s", e)
            folder_node = nodes.get("folder")
            if folder_node:
                try:
                    await folder_node.delete()
                except Exception as e:
                    logger.warning("OPC-UA folder node delete error: %s", e)
        logger.info("OPC-UA device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        msg("opcua", "device_removed", id=device_id),
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
            logger.warning("OPC-UA write_point: behavior not found for device %s", device_id)
            return False
        success = behavior.on_write(point_name, value)
        if success:
            point_node_key = f"{device_id}.{point_name}"
            node = self._point_nodes.get(point_node_key)
            if node:
                try:
                    # FIXED: 使用 asyncua Variant 明确指定类型，避免 BadTypeMismatch 错误
                    from asyncua import ua as asyncua_ua
                    data_type = self._point_types.get(point_node_key, "float32")
                    type_map = {
                        "bool": asyncua_ua.VariantType.Boolean,
                        "int16": asyncua_ua.VariantType.Int16,
                        "uint16": asyncua_ua.VariantType.UInt16,
                        "int32": asyncua_ua.VariantType.Int32,
                        "uint32": asyncua_ua.VariantType.UInt32,
                        "float32": asyncua_ua.VariantType.Float,
                        "float64": asyncua_ua.VariantType.Double,
                        "string": asyncua_ua.VariantType.String,
                    }
                    variant_type = type_map.get(data_type, asyncua_ua.VariantType.Double)
                    await node.set_value(asyncua_ua.Variant(value, variant_type))
                except Exception as e:
                    logger.warning("OPC-UA write node value error for %s.%s: %s", device_id, point_name, e)
                    return False
        else:
            logger.warning("OPC-UA write_point: behavior.on_write returned False for %s.%s (value=%s)", device_id, point_name, value)
        return success

    async def _sync_values_loop(self) -> None:  # FIXED-P0: 动态值同步到OPC-UA节点，使订阅客户端能收到数据变更通知
        from asyncua import ua as asyncua_ua
        type_map = {
            "bool": asyncua_ua.VariantType.Boolean,
            "int16": asyncua_ua.VariantType.Int16,
            "uint16": asyncua_ua.VariantType.UInt16,
            "int32": asyncua_ua.VariantType.Int32,
            "uint32": asyncua_ua.VariantType.UInt32,
            "float32": asyncua_ua.VariantType.Float,
            "float64": asyncua_ua.VariantType.Double,
            "string": asyncua_ua.VariantType.String,
        }
        while self._status == ProtocolStatus.RUNNING:
            try:
                for device_id, behavior in dict(self._behaviors).items():
                    config = self._device_configs.get(device_id)
                    if not config:
                        continue
                    for point in config.points:
                        if hasattr(point, 'generator_type') and point.generator_type.value == "fixed":
                            continue
                        point_node_key = f"{device_id}.{point.name}"
                        node = self._point_nodes.get(point_node_key)
                        if not node:
                            continue
                        try:
                            value = behavior.get_value(point.name)
                            data_type = self._point_types.get(point_node_key, "float32")
                            variant_type = type_map.get(data_type, asyncua_ua.VariantType.Double)
                            await node.set_value(asyncua_ua.Variant(value, variant_type))
                        except Exception as e:
                            logger.debug("OPC-UA sync value error for %s.%s: %s", device_id, point.name, e)
            except Exception as e:
                logger.warning("OPC-UA sync loop error: %s", e)
            await asyncio.sleep(self._sync_interval)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "default": "0.0.0.0",
                    "description": desc("listen_address")},
                "port": {
                    "type": "integer",
                    "default": 4840,
                    "description": desc("listen_port")},
                "security_mode": {
                    "type": "string",
                    "default": "None",
                    "enum": ["None", "Sign", "SignAndEncrypt"],
                    "description": desc("security_mode")},
                "security_policy": {
                    "type": "string",
                    "default": "None",
                    # FIXED-P0: 扩展支持 Modern 安全策略
                    "enum": ["None", "Basic128Rsa15", "Basic256Sha256", "Aes128Sha256RsaOaep", "Aes256Sha256RsaPss"],
                    "description": desc("security_policy", "OPC-UA security policy: None/Sign/SignAndEncrypt")},
                "certificate_path": {
                    "type": "string",
                    "default": "",
                    "description": desc("server_cert_path")},
                "private_key_path": {
                    "type": "string",
                    "default": "",
                    "description": desc("server_key_path")},
                "cert_dir": {
                    "type": "string",
                    "default": "",
                    "description": desc("cert_store_dir")},
            },
        }

    async def _create_opcua_device(self, config: DeviceConfig) -> None:
        if not self._server:
            return
        behavior = self._behaviors.get(config.id)

        # Bug1-FIX: 根据设备配置的namespace注册独立命名空间索引，而非使用全局self._idx
        ns_uri = self._device_namespaces.get(config.id, "protoforge")
        try:
            device_idx = await self._server.register_namespace(ns_uri)
        except AttributeError:
            try:
                device_idx = await self._server.nodes.namespace.add(ns_uri)
            except AttributeError:
                device_idx = await self._server.get_namespace_index(ns_uri)

        try:
            device_folder = await self._server.nodes.objects.add_object(
                device_idx, config.name
            )
        except Exception as e:
            logger.error("Failed to create OPC-UA device folder for %s: %s", config.id, e)
            return
        point_nodes = {}
        if not ASYNCUA_AVAILABLE:
            logger.warning("asyncua not available, cannot create OPC-UA device nodes")
            return
        from asyncua import ua
        type_map = {
            "bool": ua.VariantType.Boolean,
            "int16": ua.VariantType.Int16,
            "uint16": ua.VariantType.UInt16,
            "int32": ua.VariantType.Int32,
            "uint32": ua.VariantType.UInt32,
            "float32": ua.VariantType.Float,
            "float64": ua.VariantType.Double,
            "string": ua.VariantType.String,
        }
        for point in config.points:
            try:
                value = behavior.get_value(point.name) if behavior else 0
                variant_type = type_map.get(point.data_type.value, None)
                if variant_type:
                    # FIXED-P1: 优先使用point.address作为NodeId，客户端可按模板定义的NodeId寻址
                    node_id_str = point.address if point.address else point.name
                    # Bug2-FIX: 解析point.address中的ns=X;s=Y格式
                    parsed_ns, parsed_id = _parse_node_id(node_id_str, device_idx)
                    try:
                        node = await device_folder.add_variable(
                            parsed_ns, parsed_id, ua.Variant(value, variant_type)
                        )
                    except Exception:
                        try:
                            node = await device_folder.add_variable(
                                parsed_ns, point.name, ua.Variant(value, variant_type)
                            )
                        except Exception:
                            node = await device_folder.add_variable(
                                device_idx, point.name, ua.Variant(value, variant_type)
                            )
                else:
                    node_id_str = point.address if point.address else point.name
                    # Bug2-FIX: 解析point.address中的ns=X;s=Y格式
                    parsed_ns, parsed_id = _parse_node_id(node_id_str, device_idx)
                    try:
                        node = await device_folder.add_variable(
                            parsed_ns, parsed_id, value
                        )
                    except Exception:
                        try:
                            node = await device_folder.add_variable(
                                parsed_ns, point.name, value
                            )
                        except Exception:
                            node = await device_folder.add_variable(
                                device_idx, point.name, value
                            )
                if point.access and "w" in point.access:
                    await node.set_writable()
                try:
                    await node.set_historized(True)  # FIXED-P1: 启用历史数据存储，客户端可通过HistoryRead读取
                except Exception:
                    pass
                point_nodes[point.name] = node
                self._point_nodes[f"{config.id}.{point.name}"] = node
                self._point_types[f"{config.id}.{point.name}"] = point.data_type.value  # FIXED: 保存点位数据类型
            except Exception as e:
                logger.warning("Failed to create OPC-UA point %s.%s: %s", config.id, point.name, e)
        self._device_nodes[config.id] = {"folder": device_folder, "points": point_nodes}
