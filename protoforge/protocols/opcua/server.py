import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior
from protoforge.protocols.behavior import DynamicValueGenerator

logger = logging.getLogger(__name__)

try:
    from asyncua import Server, ua
    ASYNCUA_AVAILABLE = True
except ImportError:
    ASYNCUA_AVAILABLE = False
    logger.warning("asyncua not installed, OPC-UA protocol will not be available")


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
                    x509.IPAddress(__import__("ipaddress").IPAddress("127.0.0.1")),
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


class OpcUaDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        for p in points:
            self._values[p.name] = p.fixed_value if p.fixed_value is not None else 0
            self._generators[p.name] = DynamicValueGenerator(p)

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

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

            if security_mode != "None" and ASYNCUA_AVAILABLE:
                try:
                    from asyncua import ua
                    mode_map = {
                        "None": ua.MessageSecurityMode.None_,
                        "Sign": ua.MessageSecurityMode.Sign,
                        "SignAndEncrypt": ua.MessageSecurityMode.SignAndEncrypt,
                    }
                    policy_map = {
                        "None": ua.SecurityPolicyType.NoSecurity,
                        "Basic256Sha256": ua.SecurityPolicyType.Basic256Sha256,
                    }
                    if security_mode in mode_map:
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
                            self._server.set_security_policy([policy_map.get(security_policy, ua.SecurityPolicyType.NoSecurity)])
                            self._server.set_security_mode(mode_map[security_mode])
                            logger.info("OPC-UA security: mode=%s, policy=%s", security_mode, security_policy)
                        except Exception as se:
                            logger.warning("Failed to set OPC-UA security policy: %s, falling back to None", se)
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
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning("OPC-UA server task error: %s", e)
        except Exception as e:
            logger.warning("OPC-UA server stop error: %s", e)
        finally:
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
            point_nodes = nodes.get("points", {})
            for point_name, point_node in point_nodes.items():
                point_node_key = f"{device_id}.{point_name}"
                self._point_nodes.pop(point_node_key, None)
                try:
                    await point_node.delete()
                except Exception as e:
                    logger.debug("OPC-UA point node delete error: %s", e)
            folder_node = nodes.get("folder")
            if folder_node:
                try:
                    await folder_node.delete()
                except Exception as e:
                    logger.debug("OPC-UA folder node delete error: %s", e)
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
        success = behavior.on_write(point_name, value)
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
                "security_mode": {
                    "type": "string",
                    "default": "None",
                    "enum": ["None", "Sign", "SignAndEncrypt"],
                    "description": "安全模式",
                },
                "security_policy": {
                    "type": "string",
                    "default": "None",
                    "enum": ["None", "Basic256Sha256"],
                    "description": "安全策略",
                },
                "certificate_path": {
                    "type": "string",
                    "default": "",
                    "description": "服务器证书路径（PEM格式，留空自动生成）",
                },
                "private_key_path": {
                    "type": "string",
                    "default": "",
                    "description": "服务器私钥路径（PEM格式，留空自动生成）",
                },
                "cert_dir": {
                    "type": "string",
                    "default": "",
                    "description": "证书存储目录（默认 ~/.protoforge/opcua_certs）",
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
            value = behavior.get_value(point.name) if behavior else 0
            variant_type = type_map.get(point.data_type.value, None)
            if variant_type:
                node = await device_folder.add_variable(
                    self._idx, point.name, ua.Variant(value, variant_type)
                )
            else:
                node = await device_folder.add_variable(
                    self._idx, point.name, value
                )
            if point.access and "w" in point.access:
                await node.set_writable()
            point_nodes[point.name] = node
            self._point_nodes[f"{config.id}.{point.name}"] = node
        self._device_nodes[config.id] = {"folder": device_folder, "points": point_nodes}
