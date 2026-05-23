import logging
import os
import re
import threading
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from protoforge.config import get_settings
from protoforge.core.defaults import HTTP_TIMEOUT_DEFAULT, HTTP_TIMEOUT_SHORT
from protoforge.core.messages import desc
from protoforge.core.integration.protocol import (
    ACCESS_MODE_MAP,
    PROTOCOL_MAP_BASE,
    DataTypeMapper,
    ProtocolMapper,
)

logger = logging.getLogger(__name__)

PROTOCOL_MAP: dict[str, str] = {
    k: v for k, v in PROTOCOL_MAP_BASE.items() if v is not None
}

EDGELITE_DEVICE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")

# EdgeLite 驱动缺失依赖包的 pip 安装命令映射
EDGELITE_PIP_PACKAGES: dict[str, list[str]] = {
    "pymcprotocol": ["pymcprotocol"],
    "pylogix": ["pylogix"],
    "pyfanuc": ["pyfanuc"],
    "pyfins": ["pyfins"],
    "OpenOPC": ["OpenOPC-Python3"],
    "pymodbus": ["pymodbus"],
    "snap7": ["python-snap7"],
    "BACnet": ["bacpypes"],
}

# FIXED: 添加 token 缓存，避免每次 API 调用都重新登录
_token_cache: dict[str, dict[str, Any]] = {}  # url -> {token, expires_at, refresh_token}
_token_cache_lock = threading.Lock()
_TOKEN_REFRESH_MARGIN = 30  # token 过期前30秒视为需要刷新

# FIXED: 添加 HTTP 连接池，避免每次请求都创建新连接
_http_client: httpx.AsyncClient | None = None
_http_client_lock = threading.Lock()


def _get_http_client() -> httpx.AsyncClient:
    """获取全局 HTTP 客户端（带连接池）"""
    global _http_client
    with _http_client_lock:
        if _http_client is None:
            _http_client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0,
                ),
                timeout=HTTP_TIMEOUT_DEFAULT,
            )
        return _http_client


async def _close_http_client() -> None:
    """关闭全局 HTTP 客户端"""
    global _http_client
    with _http_client_lock:
        if _http_client is not None:
            await _http_client.aclose()
            _http_client = None


def _get_cached_token(url: str) -> str | None:
    """从缓存中获取有效的 access token，过期则返回 None"""
    url_key = url.rstrip("/")
    with _token_cache_lock:
        entry = _token_cache.get(url_key)
        if entry and time.time() < entry.get("expires_at", 0) - _TOKEN_REFRESH_MARGIN:
            return entry.get("token")
    return None


def _cache_token(url: str, token: str, expires_in: int = 86400, refresh_token: str = "") -> None:
    """缓存 access token"""
    url_key = url.rstrip("/")
    with _token_cache_lock:
        _token_cache[url_key] = {
            "token": token,
            "expires_at": time.time() + expires_in,
            "refresh_token": refresh_token,
        }


def _invalidate_token(url: str) -> None:
    """使缓存的 token 失效"""
    url_key = url.rstrip("/")
    with _token_cache_lock:
        _token_cache.pop(url_key, None)


def _normalize_device_id(device_id: str) -> str:
    """Convert device_id to EdgeLite-compatible format.

    EdgeLite requires device_id to match: ^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$
    - lowercase only
    - start and end with [a-z0-9]
    - only [a-z0-9_-] in between
    - length 2~64
    """
    if not device_id:
        return "device-0"

    # Lowercase
    result = device_id.lower()

    # Replace invalid chars with hyphens
    result = re.sub(r"[^a-z0-9_-]", "-", result)

    # Remove consecutive hyphens/underscores
    result = re.sub(r"[-_]{2,}", "-", result)

    # Strip leading/trailing non-alphanumeric
    result = result.strip("-_")

    # Ensure at least 2 chars
    if len(result) < 2:
        result = result + "0"

    # Truncate to 64 chars, then strip trailing non-alphanumeric
    if len(result) > 64:
        result = result[:64]
        result = result.rstrip("-_")

    # After truncation, ensure still at least 2 chars
    if len(result) < 2:
        result = result + "0"

    return result


EDGELITE_PUSH_FIELDS = [
    {"key": "edgelite_enabled", "label": "启用EdgeLite联调", "type": "boolean", "default": False,
     "description": "开启后此设备将自动注册到全局配置的EdgeLite网关"},
    {"key": "collect_interval", "label": "采集间隔(秒)", "type": "number", "default": 5, "min": 1, "max": 3600,
     "description": "EdgeLite采集此设备数据的间隔秒数"},
]


def get_global_edgelite_config() -> dict[str, str]:
    s = get_settings()
    return {
        "url": s.edgelite_url or "",
        "username": s.edgelite_username,
        "password": s.edgelite_password or "",
    }


def is_edgelite_enabled_for_device(device: Any) -> bool:
    config = getattr(device, "protocol_config", {}) or {}
    if isinstance(config, dict):
        return config.get("edgelite_enabled", False) is True
    return False

_DRIVER_CONFIG_KNOWN_KEYS: dict[str, set[str]] = {
    "modbus_tcp": {"host", "port", "slave_id", "timeout"},
    "modbus_rtu": {"port", "baudrate", "slave_id", "parity", "stopbits", "timeout"},
    "opcua": {"server_url", "username", "password", "security_mode", "use_subscription", "timeout"},
    "mqtt": {"broker", "port", "subscribe_topic", "publish_topic", "client_id", "username", "password", "tls_enabled", "tls_insecure", "timeout"},
    "http": {"push_url", "timeout"},
    "s7": {"ip", "rack", "slot"},
    "mc": {"ip", "port", "plc_type", "timeout"},
    "fins": {"ip", "port", "timeout"},
    "ab": {"ip", "slot", "micrologix", "timeout"},
    "fanuc": {"ip", "port", "timeout"},
    "mtconnect": {"url", "timeout"},
    "toledo": {"ip", "port", "serial_port", "baudrate", "protocol", "timeout"},
    "opcda": {"server", "host", "gateway", "timeout"},
    "onvif": {"ip", "port", "username", "password", "timeout"},
    "dlt645": {"port", "baud_rate", "parity", "timeout"},
    "iec104": {"host", "port", "asdu_addr", "heartbeat_interval", "timeout"},
    "kuka": {"ip", "port", "reconnect", "timeout"},
    "abb_robot": {"ip", "port", "username", "password", "timeout"},
    "sparkplug_b": {"broker", "port", "group_id", "edge_node_id", "device_id", "username", "password", "timeout"},
    "serial": {"port", "baudrate", "bytesize", "parity", "stopbits", "timeout", "protocol", "slave_id", "commands"},
    "database": {"db_type", "host", "port", "database", "username", "password", "queries", "write_queries", "pool_size"},
    "barcode_scanner": {"port", "baudrate", "prefix", "suffix"},
    "profinet": {"host", "port", "device_name", "vendor_id", "device_id", "timeout"},
    "ethercat": {"host", "port", "slave_address", "timeout"},
}


def get_protoforge_host() -> str:
    s = get_settings()
    if s.protoforge_public_host:
        return s.protoforge_public_host

    host = s.host
    if host in ("0.0.0.0", ""):
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(2)
                s.connect(("8.8.8.8", 80))
                host = s.getsockname()[0]
        except Exception as e:
            logger.debug("Failed to detect local IP via UDP: %s", e)
            try:
                host = socket.gethostbyname(socket.gethostname())
            except Exception as e2:
                logger.debug("Failed to detect local IP via hostname: %s, using 127.0.0.1", e2)
                host = "127.0.0.1"
    return host


def _is_edgelite_local(el_config: dict[str, str]) -> bool:
    url = (el_config.get("url") or "").strip().rstrip("/")
    if not url:
        return False
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        return hostname in ("127.0.0.1", "localhost", "[::1]", "::1", "")
    except Exception as e:
        logger.debug("Failed to parse URL for local check: %s", e)
        return "127.0.0.1" in url or "localhost" in url


def _get_protocol_status(protocol: str) -> str:
    """Get the running status of a protocol server. Returns 'running', 'stopped', or 'unknown'."""
    try:
        from protoforge.main import get_engine
        from protoforge.protocols.base import ProtocolStatus
        engine = get_engine()
        server = engine._protocol_servers.get(protocol)
        if server is None:
            return "stopped"
        return "running" if server.status == ProtocolStatus.RUNNING else "stopped"
    except Exception:
        return "unknown"


def _format_driver_config_for_display(config: dict) -> str:
    """Format driver_config as human-readable connection info for error messages."""
    if not config:
        return ""
    # 提取关键连接参数，隐藏密码
    parts = []
    for key in ("server_url", "url", "push_url", "broker"):
        if config.get(key):
            parts.append(key)
    host = config.get("host") or config.get("ip")
    port = config.get("port")
    if host:
        parts.append(f"host/ip={host}")
    if port:
        parts.append(f"port={port}")
    if not parts:
        return str(config)
    display = ", ".join(f"{k}={config[k]}" for k in ("server_url", "url", "push_url", "broker") if config.get(k))
    if host:
        display += f", host={host}"
    if port:
        display += f", port={port}"
    # 隐藏密码
    if config.get("password"):
        display += ", password=***"
    return display


def _get_protocol_actual_port(protocol: str, protocol_config: dict[str, Any]) -> int | None:
    device_port = protocol_config.get("port")
    if device_port is not None:
        try:
            return int(device_port)
        except (ValueError, TypeError):
            logger.warning("Invalid port value %r for protocol %s, ignoring", device_port, protocol)
    try:
        from protoforge.main import get_engine
        engine = get_engine()
        running_port = engine.get_protocol_running_port(protocol)
        if running_port is not None:
            return running_port
    except Exception as e:
        logger.debug("Failed to get protocol running port for %s: %s", protocol, e)
    from protoforge.config import get_protocol_port_map
    port_map = get_protocol_port_map()
    proto_info = port_map.get(protocol)
    if proto_info and isinstance(proto_info.get("port"), int):
        return proto_info["port"]
    return None


async def _get_edgelite_device_config(client: httpx.AsyncClient, el_url: str, headers: dict, device_id: str) -> dict[str, Any] | None:
    """查询 EdgeLite 设备配置，返回设备详情（包含实际使用的端口）"""
    try:
        resp = await client.get(
            f"{el_url.rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}",
            headers=headers,
            timeout=HTTP_TIMEOUT_SHORT,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", data)
    except Exception as e:
        logger.debug("Failed to get EdgeLite device %s config: %s", device_id, e)
    return None


async def _get_edgelite_protocol_port_from_existing_device(
    client: httpx.AsyncClient,
    el_url: str,
    headers: dict,
    protocol: str,
    protoforge_device_id: str,
) -> int | None:
    """从 EdgeLite 已有的同协议设备中提取端口配置（EdgeLite 可能修改了默认端口）"""
    try:
        resp = await client.get(
            f"{el_url.rstrip('/')}/api/v1/devices",
            headers=headers,
            params={"protocol": PROTOCOL_MAP.get(protocol, protocol), "limit": 10},
            timeout=HTTP_TIMEOUT_SHORT,
        )
        if resp.status_code == 200:
            data = resp.json()
            devices = data.get("data", data.get("devices", []))
            for dev in devices:
                config = dev.get("config", {})
                if protocol == "mqtt":
                    return config.get("port")
                elif protocol in ("modbus_tcp", "s7", "mc", "opcua", "fins", "ab"):
                    return config.get("port")
                elif protocol == "http":
                    return config.get("server_port") or config.get("port")
    except Exception as e:
        logger.debug("Failed to get EdgeLite existing devices for port detection: %s", e)
    return None


def _build_driver_config(protocol: str, protocol_config: dict[str, Any], protoforge_host: str = "", el_config: dict[str, str] | None = None) -> dict[str, Any]:
    if not protoforge_host:
        protoforge_host = get_protoforge_host()
    if el_config and _is_edgelite_local(el_config):
        protoforge_host = "127.0.0.1"
    host = protoforge_host
    port = _get_protocol_actual_port(protocol, protocol_config)
    timeout = protocol_config.get("timeout", 5.0)

    if protocol == "modbus_tcp":
        base = {"host": host, "port": port or 5020, "slave_id": protocol_config.get("slave_id", 1), "timeout": timeout}
    elif protocol == "modbus_rtu":
        base = {
            "port": protocol_config.get("serial_port", "/dev/ttyUSB0"),
            "baudrate": protocol_config.get("baudrate", 9600),
            "slave_id": protocol_config.get("slave_id", 1),
            "parity": protocol_config.get("parity", "N"),
            "stopbits": protocol_config.get("stopbits", protocol_config.get("stop_bits", 1)),
            "timeout": timeout,
        }
    elif protocol == "opcua":
        ua_port = port or 4840
        base = {"server_url": protocol_config.get("server_url", protocol_config.get("endpoint", f"opc.tcp://{host}:{ua_port}")),
                "username": protocol_config.get("username", ""),
                "password": protocol_config.get("password", ""),
                "security_mode": protocol_config.get("security_mode", "None"),
                "use_subscription": protocol_config.get("use_subscription", True)}
    elif protocol == "mqtt":
        mqtt_port = port or 1883
        base = {
            "broker": host,
            "port": mqtt_port,
            "subscribe_topic": protocol_config.get("subscribe_topic", protocol_config.get("topic", "protoforge/data")),
            "publish_topic": protocol_config.get("publish_topic", "protoforge/command"),
            "client_id": protocol_config.get("client_id", f"protoforge-mqtt-{uuid.uuid4().hex[:8]}"),
        }
        if protocol_config.get("username"):
            base["username"] = protocol_config.get("username")
            base["password"] = protocol_config.get("password", "")
        if protocol_config.get("tls_enabled"):
            base["tls_enabled"] = True
            base["tls_insecure"] = protocol_config.get("tls_insecure", False)
    elif protocol == "http":
        http_port = port or 8080
        base = {"push_url": f"http://{host}:{http_port}/webhook/data",
                "timeout": timeout}
    elif protocol == "s7":
        base = {"ip": host,
                "rack": protocol_config.get("rack", 0),
                "slot": protocol_config.get("slot", 1)}
    elif protocol == "mc":
        base = {"ip": host, "port": port or 5000, "plc_type": protocol_config.get("plc_type", "iQ-R"), "timeout": timeout}
    elif protocol == "fins":
        base = {"ip": host, "port": port or 9600, "timeout": timeout}
    elif protocol == "ab":
        base = {"ip": host, "slot": protocol_config.get("slot", 0),
                "micrologix": protocol_config.get("micrologix", False), "timeout": timeout}
    elif protocol == "fanuc":
        base = {"ip": host, "port": port or 8193, "timeout": timeout}
    elif protocol == "mtconnect":
        base = {"url": protocol_config.get("url", f"http://{host}:{port or 7878}"), "timeout": timeout}
    elif protocol == "toledo":
        base = {"ip": host, "port": port or 1701, "timeout": timeout}
    elif protocol == "opcda":
        base = {"server": protocol_config.get("server", protocol_config.get("prog_id", "")),
                "host": protocol_config.get("host", host), "timeout": timeout}
    elif protocol == "onvif":
        base = {"ip": host, "port": port or 80,
                "username": protocol_config.get("username", "admin"),
                "password": protocol_config.get("password", ""), "timeout": timeout}
    elif protocol == "dlt645":
        base = {"port": protocol_config.get("serial_port", "/dev/ttyUSB0"),
                "baud_rate": protocol_config.get("baud_rate", 2400),
                "parity": protocol_config.get("parity", "E"), "timeout": timeout}
    elif protocol == "iec104":
        base = {"host": host, "port": port or 2404,
                "asdu_addr": protocol_config.get("asdu_addr", 1),
                "heartbeat_interval": protocol_config.get("heartbeat_interval", 30.0), "timeout": timeout}
    elif protocol == "kuka":
        base = {"ip": host, "port": port or 54600,
                "reconnect": protocol_config.get("reconnect", True), "timeout": timeout}
    elif protocol == "abb_robot":
        base = {"ip": host, "port": port or 80,
                "username": protocol_config.get("username", "Default"),
                "password": protocol_config.get("password", ""), "timeout": timeout}
    elif protocol == "sparkplug_b":
        sparkplug_port = port or 1883
        base = {
            "broker": host,
            "port": sparkplug_port,
            "group_id": protocol_config.get("group_id", "protoforge"),
            "edge_node_id": protocol_config.get("edge_node_id", "pf-node"),
            "device_id": protocol_config.get("device_id", "pf-device"),
        }
        if protocol_config.get("username"):
            base["username"] = protocol_config.get("username")
            base["password"] = protocol_config.get("password", "")
    elif protocol == "serial":
        base = {
            "port": protocol_config.get("serial_port", "/dev/ttyUSB0"),
            "baudrate": protocol_config.get("baudrate", 9600),
            "bytesize": protocol_config.get("bytesize", 8),
            "parity": protocol_config.get("parity", "N"),
            "stopbits": protocol_config.get("stopbits", protocol_config.get("stop_bits", 1)),
            "timeout": 5.0,
            "protocol": protocol_config.get("serial_protocol", "raw"),
        }
    elif protocol == "database":
        base = {
            "db_type": protocol_config.get("db_type", "mysql"),
            "host": host, "port": port or 3306,
            "database": protocol_config.get("database", ""),
            "username": protocol_config.get("username", ""),
            "password": protocol_config.get("password", ""),
            "queries": protocol_config.get("queries", []),
            "write_queries": protocol_config.get("write_queries", []),
            "pool_size": protocol_config.get("pool_size", 5),
        }
    elif protocol == "barcode_scanner":
        base = {
            "port": protocol_config.get("serial_port", "/dev/ttyUSB0"),
            "baudrate": protocol_config.get("baudrate", 9600),
            "prefix": protocol_config.get("prefix", ""),
            "suffix": protocol_config.get("suffix", "\r"),
        }
    elif protocol == "profinet":
        base = {"host": host, "port": port or 34964,
                "device_name": protocol_config.get("device_name", "protoforge-device"),
                "vendor_id": protocol_config.get("vendor_id", 266),
                "device_id": protocol_config.get("device_id", 256), "timeout": 5.0}
    elif protocol == "ethercat":
        base = {"host": host, "port": port or 34980,
                "slave_address": protocol_config.get("slave_address", 4097), "timeout": 5.0}
    else:
        base = {"host": host, "ip": host, "port": port, "timeout": 5.0}

    known = _DRIVER_CONFIG_KNOWN_KEYS.get(protocol, set())
    for k, v in protocol_config.items():
        if k not in known and k not in base and k not in (
            "edgelite_url", "edgelite_username", "edgelite_password", "collect_interval",
            "edgelite_enabled", "port",
        ):
            base[k] = v

    return base


def _build_points(
    points: list[dict[str, Any]],
    data_type_mapper: DataTypeMapper | None = None,
) -> list[dict[str, Any]]:
    mapper = data_type_mapper or DataTypeMapper()
    result = []
    for p in points:
        source_dt = p.get("data_type", "float32")
        dt_result = mapper.map(source_dt)
        point_def: dict[str, Any] = {
            "name": p.get("name", ""),
            "data_type": dt_result.target_type,
            "unit": p.get("unit", ""),
            "address": str(p.get("address", "0")),
            "access_mode": ACCESS_MODE_MAP.get(p.get("access", "rw"), "rw"),
        }
        min_val = p.get("min_value") or p.get("min")
        max_val = p.get("max_value") or p.get("max")
        if min_val is not None:
            point_def["min"] = min_val
        if max_val is not None:
            point_def["max"] = max_val
        result.append(point_def)
    return result


def convert_device_to_edgelite(
    device: Any,
    protoforge_host: str = "",
    protocol_mapper: ProtocolMapper | None = None,
    data_type_mapper: DataTypeMapper | None = None,
    el_config: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    protocol = getattr(device, "protocol", "") or ""

    p_mapper = protocol_mapper or ProtocolMapper()
    proto_result = p_mapper.map(protocol)

    if proto_result.status in ("unsupported", "unknown"):
        return None
    if proto_result.status != "ok":
        logger.warning("Protocol mapping issue for %s: %s", protocol, proto_result.warning)
        return None

    edgelite_protocol = proto_result.edgelite_protocol
    config = getattr(device, "protocol_config", {}) or {}
    points = getattr(device, "points", []) or []
    points_data = []
    for p in points:
        if hasattr(p, "model_dump"):
            points_data.append(p.model_dump())
        elif hasattr(p, "__dict__"):
            points_data.append(p.__dict__)
        else:
            points_data.append(p)

    driver_config = _build_driver_config(protocol, config, protoforge_host, el_config)
    edgelite_points = _build_points(points_data, data_type_mapper)

    raw_device_id = getattr(device, "id", "")
    normalized_id = _normalize_device_id(raw_device_id)
    if raw_device_id != normalized_id:
        logger.info("Device ID normalized for EdgeLite: %s -> %s", raw_device_id, normalized_id)

    return {
        "device_id": normalized_id,
        "name": getattr(device, "name", ""),
        "protocol": edgelite_protocol,
        "config": driver_config,
        "points": edgelite_points,
        "collect_interval": config.get("collect_interval", 5),
    }


def get_edgelite_config_from_device(device: Any) -> dict[str, str]:
    global_config = get_global_edgelite_config()
    device_config = getattr(device, "protocol_config", {}) or {}

    if device_config.get("edgelite_url"):
        return {
            "url": device_config.get("edgelite_url", ""),
            "username": device_config.get("edgelite_username", global_config["username"]),
            "password": device_config.get("edgelite_password", global_config["password"]),
        }

    return global_config


class EdgeLiteError(Exception):
    def __init__(self, error_type: str, message: str, suggestion: str = ""):
        self.error_type = error_type
        self.suggestion = suggestion
        super().__init__(message)


async def _login_edgelite(client: httpx.AsyncClient, url: str, username: str, password: str) -> str:
    # FIXED: 优先使用缓存的 token，避免每次请求都重新登录
    cached = _get_cached_token(url)
    if cached:
        return cached

    try:
        login_resp = await client.post(
            f"{url.rstrip('/')}/api/v1/auth/login",
            json={"username": username, "password": password},
        )
    except httpx.ConnectError as e:
        raise EdgeLiteError("connection", desc("edgelite.error.connection").format(error=e), desc("edgelite.suggestion.verify_gateway"))
    except httpx.TimeoutException:
        raise EdgeLiteError("timeout", desc("edgelite.error.timeout"), desc("edgelite.suggestion.check_online_latency"))

    if login_resp.status_code == 401:
        raise EdgeLiteError("auth", desc("edgelite.error.auth"), desc("edgelite.suggestion.check_credentials"))
    if login_resp.status_code != 200:
        raise EdgeLiteError("http", desc("edgelite.error.http_login").format(status=login_resp.status_code), desc("edgelite.suggestion.gateway_status_code").format(status=login_resp.status_code))

    try:
        data = login_resp.json()
    except Exception as e:
        raise EdgeLiteError("parse_error", desc("edgelite.error.parse_error").format(error=e), desc("edgelite.suggestion.check_version"))
    inner = data.get("data")
    token = (inner.get("access_token", "") if isinstance(inner, dict) else "") or data.get("access_token", "")
    if not token:
        raise EdgeLiteError("token", desc("edgelite.error.token_missing"), desc("edgelite.suggestion.check_version"))

    # FIXED: 缓存获取到的 token，默认24小时过期
    expires_in = 86400
    if isinstance(inner, dict):
        try:
            expires_in = int(inner.get("expires_in", inner.get("exp", 86400)))
        except (ValueError, TypeError):
            pass
    refresh_token = (inner.get("refresh_token", "") if isinstance(inner, dict) else "") or data.get("refresh_token", "")
    _cache_token(url, token, expires_in, refresh_token)

    return token


def _extract_token(login_resp: httpx.Response) -> str:
    try:
        data = login_resp.json()
    except Exception as e:
        raise EdgeLiteError("token", desc("edgelite.error.token_format").format(error=e), desc("edgelite.suggestion.check_version")) from e
    inner = data.get("data")
    return (inner.get("access_token", "") if isinstance(inner, dict) else "") or data.get("access_token", "")


async def _get_auth_headers(
    client: httpx.AsyncClient, url: str, username: str, password: str
) -> tuple[dict[str, str], None] | tuple[dict[str, str], EdgeLiteError]:
    """获取认证头，优先使用缓存 token。返回 (headers, error)，error 为 None 表示成功。"""
    try:
        token = await _login_edgelite(client, url, username, password)
    except EdgeLiteError as e:
        return {}, e
    except Exception as e:
        return {}, EdgeLiteError("unknown", str(e), desc("edgelite.suggestion.check_network"))
    return {"Authorization": f"Bearer {token}"}, None


async def _relogin_on_401(
    client: httpx.AsyncClient, url: str, username: str, password: str
) -> dict[str, str]:
    """当缓存的 token 失效（API 返回 401）时，清除缓存并重新登录。返回新的 headers。"""
    _invalidate_token(url)
    token = await _login_edgelite(client, url, username, password)
    return {"Authorization": f"Bearer {token}"}


async def push_device_to_edgelite(device: Any, protoforge_host: str = "") -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config.get("url"):
        return {
            "ok": False, "skipped": True,
            "reason": "edgelite_url not configured",
            "error_type": "not_configured",
            "suggestion": desc("edgelite.suggestion.configure_url"),
        }

    payload = convert_device_to_edgelite(device, protoforge_host, el_config=el_config)
    if payload is None:
        return {
            "ok": False, "skipped": True,
            "reason": "Protocol not supported by EdgeLite",
            "error_type": "unsupported",
            "suggestion": desc("edgelite.suggestion.unsupported_protocol"),
        }

    # FIXED: 尝试从 EdgeLite 已有的同协议设备获取端口（EdgeLite 可能修改了默认端口）
    protocol = getattr(device, "protocol", "") or ""
    driver_config = payload.get("config", {})

    # FIXED: 使用全局 HTTP 连接池，避免每次请求创建新连接
    client = _get_http_client()
    # FIXED: 使用带缓存的认证，避免每次重新登录
    headers, auth_err = await _get_auth_headers(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
    if auth_err:
        return {"ok": False, "error": str(auth_err), "error_type": auth_err.error_type, "suggestion": auth_err.suggestion}

    # 尝试获取 EdgeLite 已有的同协议设备端口
    el_device_port = await _get_edgelite_protocol_port_from_existing_device(
        client, el_config.get("url", ""), headers, protocol, payload.get("device_id", "")
    )
    if el_device_port is not None:
        # 用 EdgeLite 的端口覆盖驱动配置
        logger.info("Detected EdgeLite %s port %d, using it instead of ProtoForge's config", protocol, el_device_port)
        driver_config["port"] = el_device_port
        if protocol == "mqtt":
            driver_config["broker_port"] = el_device_port
        payload["config"] = driver_config

    # FIXED-P1: Push前检查协议服务器是否运行，避免EdgeLite驱动连接失败后回滚
    protocol_status = _get_protocol_status(protocol)
    if protocol_status != "running":
        return {
            "ok": False,
            "error": f"Protocol {protocol} is not running (status: {protocol_status})",
            "error_type": "protocol_not_running",
            "suggestion": desc("edgelite.suggestion.protocol_not_running"),
            "driver_config": driver_config,
        }

    try:
        create_resp = await client.post(
            f"{el_config.get('url', '').rstrip('/')}/api/v1/devices",
            json=payload, headers=headers,
        )
    except httpx.ConnectError:  # FIXED-P0: except需与try体同级；原代码except缩进进if块导致外层try无except
        return {"ok": False, "error": "Cannot connect to EdgeLite during device creation", "error_type": "connection"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Device creation request timed out", "error_type": "timeout"}
    except Exception as e:
        return {"ok": False, "error": f"Device creation request exception: {e}", "error_type": "unknown"}

    # FIXED: 缓存 token 失效时自动重新登录重试
    if create_resp.status_code == 401:
        headers = await _relogin_on_401(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
        try:
            create_resp = await client.post(
                f"{el_config.get('url', '').rstrip('/')}/api/v1/devices",
                json=payload, headers=headers,
            )
        except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
            return {"ok": False, "error": str(e), "error_type": "unknown"}

        if create_resp.status_code in (200, 201):
            logger.info("Device %s registered to EdgeLite, auto-collecting started", payload["device_id"])
            return {"ok": True, "action": "created", "device_id": payload["device_id"], "driver_config": payload.get("config", {})}

        if create_resp.status_code == 409:
            # FIXED-P1: 区分EdgeLite 409的两种原因：
            # 1. device_id主键冲突(ERR_REPO_DEVICE_EXISTS) → 设备已存在，应PUT更新
            # 2. 驱动启动失败(Device driver start failed) → 设备已被回滚删除，应重试POST
            conflict_detail = ""
            try:
                conflict_data = create_resp.json()
                if isinstance(conflict_data, dict):
                    conflict_detail = str(conflict_data.get("detail", ""))
            except Exception:
                pass

            is_driver_failure = "driver" in conflict_detail.lower() or "start failed" in conflict_detail.lower() or "connection" in conflict_detail.lower()

            # FIXED: 从错误消息中提取缺失的pip包名，给出pip install提示
            pip_hint = ""
            missing_packages = []
            try:
                import re as _re
                # 匹配多种格式:
                # 1. "xxx未安装，请执行: pip install xxx"
                # 2. "xxx not installed. Run: pip install xxx"
                # 3. "pip install xxx" (直接提取包名)
                patterns = [
                    r"(?:未安装[，,]?\s*请执行|not installed[.,]?\s*(?:Run|run)[.:]?\s*)pip install\s+(\S+)",
                    r"pip install\s+(\S+)",
                    r"(\w+(?:-\w+)?(?:-\w+)?)\s+未安装",
                ]
                for pattern in patterns:
                    for m in _re.finditer(pattern, conflict_detail):
                        pkg = m.group(1).strip().rstrip('.')
                        # 过滤掉非包名的匹配
                        if pkg and len(pkg) > 2 and not pkg.startswith("http"):
                            # 映射到正确的 pip 包名
                            correct_pkg = EDGELITE_PIP_PACKAGES.get(pkg.lower(), [pkg])[0]
                            if correct_pkg not in missing_packages:
                                missing_packages.append(correct_pkg)
            except Exception:
                pass

            if missing_packages:
                pip_hint = "pip install " + " ".join(missing_packages)

            if is_driver_failure:
                # 驱动启动失败，设备已被EdgeLite回滚删除，返回失败信息
                # FIXED-P1: 包含实际连接参数，方便用户排查IP/端口问题
                # FIXED: 包含pip安装提示
                logger.warning("EdgeLite device %s driver start failed: %s", payload["device_id"], conflict_detail)
                conn_info = _format_driver_config_for_display(payload.get("config", {}))
                suggestion = desc("edgelite.suggestion.check_driver_config")
                if pip_hint:
                    suggestion = f"{suggestion}\n\n安装缺失依赖: {pip_hint}"
                return {
                    "ok": False,
                    "error": f"EdgeLite driver start failed: {conflict_detail}",
                    "error_type": "driver_failed",
                    "suggestion": suggestion,
                    "driver_config": payload.get("config", {}),
                    "connection_info": conn_info,
                    "pip_hint": pip_hint if pip_hint else None,
                }

            # device_id冲突，设备已存在，通过GET确认存在后再PUT更新
            # FIXED: rtu-plc等设备EdgeLite返回409后设备已被回滚删除，PUT会返回404
            # 改为：先用GET确认设备存在；如404则重新POST（设备已被服务器删除）
            remote_device_id = payload["device_id"]
            try:
                dev_resp = await client.get(
                    f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(remote_device_id), safe='')}",
                    headers=headers,
                )
                if dev_resp.status_code == 404:
                    # 设备已被服务器删除，直接重新POST创建
                    logger.info("Device %s not found on EdgeLite (deleted server-side), re-creating...", remote_device_id)
                    try:
                        create_resp2 = await client.post(
                            f"{el_config.get('url', '').rstrip('/')}/api/v1/devices",
                            json=payload, headers=headers,
                        )
                    except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
                        return {"ok": False, "error": str(e), "error_type": "unknown"}
                    if create_resp2.status_code in (200, 201):
                        logger.info("Device %s re-created on EdgeLite", payload["device_id"])
                        return {"ok": True, "action": "created", "device_id": payload["device_id"], "driver_config": payload.get("config", {})}
                    # 即使再次失败也不走PUT路径，直接返回
                    try:
                        err_data = create_resp2.json()
                        err_detail = err_data.get("detail", str(create_resp2.text[:200]))
                    except Exception:
                        err_detail = str(create_resp2.text[:200])
                    return {"ok": False, "error": f"Re-create failed: HTTP {create_resp2.status_code} - {err_detail}", "error_type": "create_failed"}
                elif dev_resp.status_code == 200:
                    # 设备确实存在，提取真实device_id并PUT更新
                    try:
                        dev_data = dev_resp.json()
                        dev_data_inner = dev_data.get("data", dev_data)
                        remote_device_id = dev_data_inner.get("device_id", remote_device_id)
                    except Exception:
                        pass
                # 其他状态码不处理，继续走PUT流程
            except httpx.ConnectError:
                pass  # 网络错误时跳过此检查，继续尝试PUT
            except httpx.TimeoutException:
                pass

            update_payload = {k: v for k, v in payload.items() if k != "device_id"}
            try:
                update_resp = await client.put(
                    f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(remote_device_id), safe='')}",
                    json=update_payload, headers=headers,
                )
            except httpx.ConnectError:
                return {"ok": False, "error": "Cannot connect to EdgeLite during update, please check if gateway is online", "error_type": "connection"}
            except httpx.TimeoutException:
                return {"ok": False, "error": "Update request timed out, EdgeLite responded too slowly", "error_type": "timeout"}
            except Exception as e:
                return {"ok": False, "error": f"Update request exception: {e}", "error_type": "unknown"}
            if update_resp.status_code == 200:
                logger.info("Device %s updated on EdgeLite", payload["device_id"])
                return {"ok": True, "action": "updated", "device_id": payload["device_id"], "driver_config": payload.get("config", {})}
            return {"ok": False, "error": f"Update failed: HTTP {update_resp.status_code}", "error_type": "update_failed"}

        if create_resp.status_code == 422:
            return {
                "ok": False,
                "error": f"EdgeLite rejected push: {create_resp.text[:300]}", "error_type": "validation_error",
                "suggestion": desc("edgelite.suggestion.check_config"),
            }

        if create_resp.status_code >= 500:
            return {
                "ok": False,
                "error": f"EdgeLite server error: HTTP {create_resp.status_code}", "error_type": "edgelite_error",
                "suggestion": f"EdgeLite ({el_config.get('url', '')}) 内部错误。请检查 EdgeLite 日志，确认已注册的协议驱动类型: {payload['protocol']}",
            }

        return {"ok": False, "error": f"Create failed: HTTP {create_resp.status_code}", "error_type": "create_failed"}


async def remove_device_from_edgelite(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config.get("url"):
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

    device_id = _normalize_device_id(getattr(device, "id", ""))

    # FIXED: 使用全局 HTTP 连接池
    client = _get_http_client()
    # FIXED: 使用带缓存的认证
    headers, auth_err = await _get_auth_headers(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
    if auth_err:
        return {"ok": False, "error": str(auth_err), "error_type": auth_err.error_type, "suggestion": auth_err.suggestion}

    try:
        resp = await client.delete(
            f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}",
            headers=headers,
        )
    except httpx.ConnectError:  # FIXED-P0: except需与try体同级，否则except块脱离try变为死代码
        return {"ok": False, "error": "Cannot connect to EdgeLite during removal", "error_type": "connection"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Removal request timed out", "error_type": "timeout"}
    except Exception as e:
        return {"ok": False, "error": f"Removal request exception: {e}", "error_type": "unknown"}

    # FIXED: 缓存 token 失效时自动重新登录重试
    if resp.status_code == 401:
        headers = await _relogin_on_401(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
        try:
            resp = await client.delete(
                f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}",
                headers=headers,
            )
        except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
            return {"ok": False, "error": str(e), "error_type": "unknown"}

    if resp.status_code in (200, 204, 404):
        return {"ok": True, "action": "deleted", "device_id": device_id}
    return {"ok": False, "error": f"Delete failed: HTTP {resp.status_code}", "error_type": "delete_failed"}


async def get_edgelite_device_status(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config.get("url"):
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

    device_id = _normalize_device_id(getattr(device, "id", ""))

    # FIXED: 使用全局 HTTP 连接池
    client = _get_http_client()
    # FIXED: 使用带缓存的认证
    headers, auth_err = await _get_auth_headers(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
    if auth_err:
        return {"ok": False, "error": str(auth_err), "error_type": auth_err.error_type}


async def read_edgelite_device_points(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config.get("url"):
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

    device_id = _normalize_device_id(getattr(device, "id", ""))

    # FIXED: 使用全局 HTTP 连接池
    client = _get_http_client()
    # FIXED: 使用带缓存的认证
    headers, auth_err = await _get_auth_headers(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
    if auth_err:
        return {"ok": False, "error": str(auth_err), "error_type": auth_err.error_type, "suggestion": auth_err.suggestion}

    try:
        resp = await client.get(
            f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}/points",
            headers=headers,
        )
    except httpx.ConnectError:  # FIXED-P0: except需与try体同级，否则except块脱离try变为死代码
        return {"ok": False, "error": "Cannot connect to EdgeLite while reading points", "error_type": "connection"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Read points request timed out", "error_type": "timeout"}
    except Exception as e:
        return {"ok": False, "error": f"Read points request exception: {e}", "error_type": "unknown"}

    # FIXED: 缓存 token 失效时自动重新登录重试
    if resp.status_code == 401:
        headers = await _relogin_on_401(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
        try:
            resp = await client.get(
                f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}/points",
                headers=headers,
            )
        except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
            return {"ok": False, "error": str(e), "error_type": "unknown"}

    if resp.status_code == 200:
        try:
            raw = resp.json()
        except Exception as e:
            return {"ok": False, "error": f"EdgeLite returned invalid JSON: {e}", "error_type": "parse_error"}
        data = raw.get("data", raw)
        return {"ok": True, "device_id": device_id, "points": data}
    if resp.status_code == 404:
        return {"ok": False, "error": "Device not found on EdgeLite", "error_type": "not_found"}
    return {"ok": False, "error": f"HTTP {resp.status_code}", "error_type": "http_error"}


_PROTOCOL_DISPLAY = {
    "modbus_tcp": "Modbus TCP", "modbus_rtu": "Modbus RTU", "opcua": "OPC-UA",
    "mqtt": "MQTT", "http": "HTTP Webhook", "s7": "S7", "mc": "MC Protocol",
    "fins": "FINS", "ab": "EtherNet/IP", "fanuc": "FOCAS", "mtconnect": "MTConnect",
    "toledo": "Toledo", "opcda": "OPC DA", "onvif": "ONVIF", "dlt645": "DL/T 645",
    "iec104": "IEC 104", "kuka": "KUKA EKRL", "abb_robot": "ABB RWS",
    "sparkplug_b": "Sparkplug B", "serial": "Serial Device", "database": "Database",
    "barcode_scanner": "Barcode Scanner", "profinet": "PROFINET", "ethercat": "EtherCAT",
}

_PROTOCOL_DEFAULT_PORTS = {
    "modbus_tcp": 5020, "opcua": 4840, "mqtt": 1883, "http": 8080,
    "s7": 102, "mc": 5000, "fins": 9600, "ab": 44818, "fanuc": 8193,
    "mtconnect": 7878, "toledo": 1701, "opcda": 51340, "onvif": 80,
    "dlt645": 0, "iec104": 2404, "kuka": 54600, "abb_robot": 80,
    "sparkplug_b": 1883, "serial": 0, "database": 3306, "barcode_scanner": 0,
    "profinet": 34964, "ethercat": 34980, "bacnet": 47808, "gb28181": 5060,
}


def _get_default_port(protocol: str) -> int:
    try:
        from protoforge.config import get_protocol_port_map
        port_map = get_protocol_port_map()
        if protocol in port_map:
            return port_map[protocol].get("port", _PROTOCOL_DEFAULT_PORTS.get(protocol, 0))
    except Exception as e:
        logger.debug("Failed to get protocol port map for %s: %s", protocol, e)
    return _PROTOCOL_DEFAULT_PORTS.get(protocol, 0)


def _extract_driver_host_port(driver_config: dict, protocol: str = "") -> tuple[str, str]:
    if not isinstance(driver_config, dict):
        return ("", "")
    host = ""
    port = ""
    if protocol == "mqtt" or protocol == "sparkplug_b":
        host = driver_config.get("broker", "")
        port = str(driver_config.get("port", ""))
    elif protocol == "http":
        push_url = driver_config.get("push_url", driver_config.get("url", ""))
        if push_url:
            import urllib.parse
            try:
                parsed = urllib.parse.urlparse(push_url)
                host = parsed.hostname or ""
                port = str(parsed.port) if parsed.port else ""
            except Exception as e:
                logger.debug("Failed to parse HTTP push URL: %s", e)
                host = push_url
        else:
            host = driver_config.get("host", driver_config.get("ip", ""))
            port = str(driver_config.get("port", ""))
    elif protocol == "opcua":
        server_url = driver_config.get("server_url", driver_config.get("endpoint", ""))
        if server_url:
            try:
                import re
                m = re.search(r'opc\.tcp://([^:]+):?(\d+)?', server_url)
                if m:
                    host = m.group(1) or ""
                    port = m.group(2) or ""
            except Exception as e:
                logger.debug("Failed to parse OPC-UA server URL: %s", e)
                host = server_url
        else:
            host = driver_config.get("host", "")
            port = str(driver_config.get("port", ""))
    elif protocol == "mtconnect":
        url = driver_config.get("url", "")
        if url:
            import urllib.parse
            try:
                parsed = urllib.parse.urlparse(url)
                host = parsed.hostname or ""
                port = str(parsed.port) if parsed.port else ""
            except Exception as e:
                logger.debug("Failed to parse MTConnect URL: %s", e)
                host = url
        else:
            host = driver_config.get("host", "")
            port = str(driver_config.get("port", ""))
    elif protocol in ("iec104", "modbus_tcp", "database", "opcda", "profinet", "ethercat"):
        host = driver_config.get("host", driver_config.get("ip", ""))
        port = str(driver_config.get("port", ""))
    else:
        host = driver_config.get("ip", driver_config.get("host", ""))
        port = str(driver_config.get("port", ""))
    return (host, port)


def _build_connect_error(driver_config: dict, protocol: str, protoforge_running: bool, same_server: bool = False) -> dict[str, Any]:
    driver_host, driver_port = _extract_driver_host_port(driver_config, protocol)
    proto_name = _PROTOCOL_DISPLAY.get(protocol, protocol.upper())
    default_port = _get_default_port(protocol)

    parts = []
    if not protoforge_running:
        parts.append(desc("edgelite.connect.service_not_running").format(proto=proto_name))
    elif not driver_host:
        if same_server:
            parts.append(desc("edgelite.connect.address_not_specified_same_server"))
        else:
            parts.append(desc("edgelite.connect.ip_not_specified"))
    else:
        if protocol == "s7":
            parts.append(desc("edgelite.connect.cannot_connect_no_port").format(proto=proto_name, host=driver_host))
            parts.append(desc("edgelite.connect.s7_fixed_port"))
            parts.append(desc("edgelite.connect.s7_check_port"))
            if same_server and driver_host not in ("127.0.0.1", "localhost"):
                parts.append(desc("edgelite.connect.same_server_set_localhost"))
        elif protocol == "http":
            parts.append(desc("edgelite.connect.cannot_connect").format(proto=proto_name, host=driver_host, port=driver_port))
            parts.append(desc("edgelite.connect.http_passive_mode"))
            parts.append(desc("edgelite.connect.check_service_ip_port").format(proto=proto_name, host=driver_host, port=driver_port))
            if same_server and driver_host not in ("127.0.0.1", "localhost"):
                parts.append(desc("edgelite.connect.same_server_set_localhost"))
        elif protocol == "mqtt":
            parts.append(desc("edgelite.connect.cannot_connect").format(proto=proto_name, host=driver_host, port=driver_port))
            if same_server and driver_host not in ("127.0.0.1", "localhost"):
                parts.append(desc("edgelite.connect.important_same_server").format(host=driver_host))
            parts.append(desc("edgelite.connect.confirm_mqtt_broker"))
            if driver_port and default_port and str(driver_port) != str(default_port):
                parts.append(desc("edgelite.connect.port_not_default").format(port=driver_port, default_port=default_port))
            else:
                parts.append(desc("edgelite.connect.confirm_mqtt_port").format(port=driver_port or 1883))
            parts.append(desc("edgelite.connect.test_network_telnet").format(host=driver_host, port=driver_port or 1883))
            if same_server:
                parts.append(desc("edgelite.connect.check_process"))
        elif protocol == "sparkplug_b":
            parts.append(desc("edgelite.connect.cannot_connect").format(proto=proto_name, host=driver_host, port=driver_port))
            if same_server and driver_host not in ("127.0.0.1", "localhost"):
                parts.append(desc("edgelite.connect.important_same_server").format(host=driver_host))
            parts.append(desc("edgelite.connect.sparkplug_b_mqtt"))
            parts.append(desc("edgelite.connect.confirm_port").format(port=driver_port or 1883))
            parts.append(desc("edgelite.connect.test_network_telnet").format(host=driver_host, port=driver_port or 1883))
        else:
            if same_server:
                parts.append(desc("edgelite.connect.cannot_connect").format(proto=proto_name, host=driver_host, port=driver_port))
                if driver_host not in ("127.0.0.1", "localhost"):
                    parts.append(desc("edgelite.connect.same_server_set_localhost_current").format(host=driver_host))
                if driver_port and default_port and str(driver_port) != str(default_port):
                    parts.append(desc("edgelite.connect.port_not_default_proto").format(port=driver_port, proto=proto_name, default_port=default_port))
                parts.append(desc("edgelite.connect.check_service_port").format(proto=proto_name, port=driver_port))
            else:
                parts.append(desc("edgelite.connect.cannot_connect").format(proto=proto_name, host=driver_host, port=driver_port))
                if driver_port and default_port and str(driver_port) != str(default_port):
                    parts.append(desc("edgelite.connect.port_not_default_proto").format(port=driver_port, proto=proto_name, default_port=default_port))
                parts.append(desc("edgelite.connect.check_service_ip_port").format(proto=proto_name, host=driver_host, port=driver_port))
                parts.append(desc("edgelite.connect.enter_reachable_ip"))

    return {
        "ok": False,
        "error": "\n".join(parts),
        "driver_config": driver_config,
        "driver_host": driver_host,
        "driver_port": driver_port,
    }


async def verify_edgelite_pipeline(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config.get("url"):
        return {
            "ok": False, "skipped": True,
            "reason": "edgelite_url not configured",
            "error_type": "not_configured",
            "suggestion": "Please configure the EdgeLite gateway URL in System Settings, or set edgelite_url in the device protocol config",
        }

    device_id = _normalize_device_id(getattr(device, "id", ""))
    result: dict[str, Any] = {"device_id": device_id, "steps": {}}

    # FIXED: 使用全局 HTTP 连接池
    client = _get_http_client()
    # FIXED: 使用带缓存的认证
    headers, auth_err = await _get_auth_headers(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
    if auth_err:
        result["steps"]["auth"] = {"ok": False, "error": str(auth_err), "error_type": auth_err.error_type, "suggestion": auth_err.suggestion}
        result["ok"] = False
        return result
    result["steps"]["auth"] = {"ok": True}

    try:
        dev_resp = await client.get(
            f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}",
            headers=headers,
        )
    except httpx.ConnectError:  # FIXED-P0: 字典字面量末尾多余逗号创建tuple而非dict
        result["steps"]["register"] = {"ok": False, "error": desc("edgelite.error.query_device_connection")}
        result["ok"] = False
        return result
    except httpx.TimeoutException:
        result["steps"]["register"] = {"ok": False, "error": desc("edgelite.error.query_device_timeout")}
        result["ok"] = False
        return result
    except Exception as e:
        result["steps"]["register"] = {"ok": False, "error": desc("edgelite.error.query_device_exception").format(error=e)}
        result["ok"] = False
        return result

    # FIXED: 缓存 token 失效时自动重新登录重试
    if dev_resp.status_code == 401:
        headers = await _relogin_on_401(client, el_config.get("url", ""), el_config.get("username", ""), el_config.get("password", ""))
        try:
            dev_resp = await client.get(
                f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}",
                headers=headers,
            )
        except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
            result["steps"]["register"] = {"ok": False, "error": str(e)}
            result["ok"] = False
            return result

        if dev_resp.status_code == 404:
            result["steps"]["register"] = {"ok": False, "error": "Device not registered on EdgeLite"}
            result["ok"] = False
            return result
        if dev_resp.status_code != 200:
            result["steps"]["register"] = {"ok": False, "error": f"HTTP {dev_resp.status_code}"}
            result["ok"] = False
            return result

        try:
            dev_data_raw = dev_resp.json()
        except Exception as e:  # FIXED-P0: 字典字面量末尾多余逗号创建tuple而非dict
            result["steps"]["register"] = {"ok": False, "error": desc("edgelite.error.response_not_json").format(error=e)}
            result["ok"] = False
            return result
        dev_data = dev_data_raw.get("data", dev_data_raw)
        el_status = dev_data.get("status", "unknown")
        result["steps"]["register"] = {"ok": True, "status": el_status}

        if el_status == "offline":
            driver_config = dev_data.get("config", dev_data.get("driver_config", {}))
            if isinstance(driver_config, str):
                try:
                    import json
                    driver_config = json.loads(driver_config)
                except Exception as e:
                    logger.debug("Failed to parse driver_config JSON: %s", e)
                    driver_config = {}
            device_protocol = getattr(device, "protocol", "") or ""
            protoforge_running = False
            try:
                from protoforge.main import get_engine
                engine = get_engine()
                protoforge_running = engine.is_protocol_running(device_protocol)
            except Exception as e:
                logger.debug("Failed to check protocol running status for %s: %s", device_protocol, e)
            same_server = _is_edgelite_local(el_config)
            connect_error = _build_connect_error(driver_config if isinstance(driver_config, dict) else {}, device_protocol, protoforge_running, same_server)
            result["steps"]["connect"] = connect_error
            result["ok"] = False
            return result
        result["steps"]["connect"] = {"ok": True, "status": el_status}

        try:
            points_resp = await client.get(
                f"{el_config.get('url', '').rstrip('/')}/api/v1/devices/{quote(str(device_id), safe='')}/points",
                headers=headers,
            )
        except httpx.ConnectError:  # FIXED-P0: 字典字面量末尾多余逗号创建tuple而非dict
            result["steps"]["collect"] = {"ok": False, "error": desc("edgelite.error.read_points_connection")}
            result["ok"] = False
            return result
        except httpx.TimeoutException:
            result["steps"]["collect"] = {"ok": False, "error": desc("edgelite.error.read_points_timeout")}
            result["ok"] = False
            return result
        except Exception as e:
            result["steps"]["collect"] = {"ok": False, "error": desc("edgelite.error.read_points_exception").format(error=e)}
            result["ok"] = False
            return result
        if points_resp.status_code == 200:
            try:
                raw_points = points_resp.json()
            except Exception as e:  # FIXED-P0: 字典字面量末尾多余逗号创建tuple而非dict
                result["steps"]["collect"] = {"ok": False, "error": desc("edgelite.error.invalid_json").format(error=e)}
                result["ok"] = False
                return result
            points_data = raw_points.get("data", raw_points)
            if isinstance(points_data, list):
                has_data = len(points_data) > 0
                points_dict = {}
                for item in points_data:
                    if isinstance(item, dict):
                        key = item.get("name") or item.get("point_name") or item.get("id", "")
                        points_dict[key] = item.get("value")
                if points_dict:
                    points_data = points_dict
            elif isinstance(points_data, dict):
                has_data = any(v is not None for v in points_data.values())
            else:
                has_data = False
            result["steps"]["collect"] = {
                "ok": True,
                "data": points_data,
                "has_real_data": has_data,
            }
        else:
            result["steps"]["collect"] = {"ok": False, "error": f"HTTP {points_resp.status_code}"}

        all_ok = all(s.get("ok", False) for s in result["steps"].values())
        collect_step = result["steps"].get("collect", {})
        if all_ok and not collect_step.get("has_real_data"):
            all_ok = False
        result["ok"] = all_ok

    return result


async def test_edgelite_connection(url: str, username: str = "", password: str = "") -> dict[str, Any]:
    if not url:
        return {"ok": False, "error": desc("edgelite.error.url_empty")}
    if not url.startswith("http://") and not url.startswith("https://"):
        return {"ok": False, "error": desc("edgelite.error.url_invalid")}

    # FIXED: 使用全局 HTTP 连接池
    client = _get_http_client()
    try:
        resp = await client.get(f"{url.rstrip('/')}/api/v1/system/status")
    except httpx.ConnectError:  # FIXED-P0: except必须与try同级；原代码except缩进与if同级导致except被吞进try内部
        return {"ok": False, "error": desc("edgelite.error.cannot_connect")}
    except httpx.TimeoutException:
        return {"ok": False, "error": desc("edgelite.error.connect_timeout")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if resp.status_code == 200:
        try:
            raw = resp.json()
        except Exception:
            return {"ok": False, "error": "EdgeLite returned non-JSON response"}
        data = raw.get("data", raw)
        return {"ok": True, "version": data.get("version", ""), "devices": data.get("device_total", data.get("devices", 0))}

    needs_auth = resp.status_code in (401, 403)
    if not needs_auth:
        return {"ok": False, "error": f"HTTP {resp.status_code}"}

    if not password:
        return {"ok": False, "error": desc("edgelite.error.auth_required")}

    try:
        login_resp = await client.post(
            f"{url.rstrip('/')}/api/v1/auth/login",
            json={"username": username, "password": password},
        )
    except httpx.ConnectError:
        return {"ok": False, "error": desc("edgelite.error.auth_connection")}
    except httpx.TimeoutException:
        return {"ok": False, "error": desc("edgelite.error.auth_timeout")}

    if login_resp.status_code == 200:
        token = _extract_token(login_resp)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            status_resp = await client.get(f"{url.rstrip('/')}/api/v1/system/status", headers=headers)
        except httpx.ConnectError:
            return {"ok": False, "error": desc("edgelite.error.auth_lost_connection")}
        except httpx.TimeoutException:
            return {"ok": False, "error": desc("edgelite.error.auth_status_timeout")}
        except Exception as e:
            logger.debug("EdgeLite status query after auth failed: %s", e)
            return {"ok": False, "error": f"Status query failed after auth: {e}"}
        if status_resp.status_code == 200:
            try:
                raw = status_resp.json()
            except Exception:
                return {"ok": False, "error": "EdgeLite returned non-JSON response after auth"}
            data = raw.get("data", raw)
            return {"ok": True, "version": data.get("version", ""), "devices": data.get("device_total", data.get("devices", 0))}
        return {"ok": False, "error": f"EdgeLite status returned HTTP {status_resp.status_code}"}

    if login_resp.status_code == 401:
        return {"ok": False, "error": desc("edgelite.error.auth_failed")}
    if login_resp.status_code == 403:
        return {"ok": False, "error": desc("edgelite.error.login_denied").format(status=login_resp.status_code)}
    return {"ok": False, "error": desc("edgelite.error.login_http_failed").format(status=login_resp.status_code)}
