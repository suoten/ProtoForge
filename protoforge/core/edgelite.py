import logging
import os
from typing import Any

import httpx

from protoforge.config import get_settings
from protoforge.core.integration.protocol import (
    ACCESS_MODE_MAP,
    DATA_TYPE_MAP,
    PROTOCOL_MAP_BASE,
    DataTypeMapper,
    ProtocolMapper,
)

logger = logging.getLogger(__name__)

PROTOCOL_MAP: dict[str, str] = {
    k: v for k, v in PROTOCOL_MAP_BASE.items() if v is not None
}

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
        "username": s.edgelite_username or "admin",
        "password": s.edgelite_password or "",
    }


def is_edgelite_enabled_for_device(device: Any) -> bool:
    config = getattr(device, "protocol_config", {}) or {}
    if isinstance(config, dict):
        return config.get("edgelite_enabled", False) is True
    return False

_DRIVER_CONFIG_KNOWN_KEYS: dict[str, set[str]] = {
    "modbus_tcp": {"host", "port", "slave_id", "timeout"},
    "modbus_rtu": {"serial_port", "baudrate", "slave_id", "parity", "stop_bits", "timeout"},
    "opcua": {"endpoint", "security_mode", "timeout"},
    "mqtt": {"broker", "port", "timeout"},
    "http": {"url", "method", "timeout"},
    "s7": {"host", "port", "rack", "slot", "timeout"},
    "mc": {"host", "port", "timeout"},
    "fins": {"host", "port", "timeout"},
    "ab": {"host", "port", "timeout"},
    "bacnet": {"host", "port", "device_id", "timeout"},
    "fanuc": {"host", "port", "timeout"},
    "mtconnect": {"url", "timeout"},
    "toledo": {"host", "port", "timeout"},
    "opcda": {"prog_id", "timeout"},
    "profinet": {"host", "port", "device_name", "vendor_id", "device_id", "timeout"},
    "ethercat": {"host", "port", "slave_address", "timeout"},
}


def get_protoforge_host() -> str:
    s = get_settings()
    if s.protoforge_public_host:
        return s.protoforge_public_host

    host = os.environ.get("PROTOFORGE_HOST", "0.0.0.0")
    if host in ("0.0.0.0", ""):
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                host = s.getsockname()[0]
        except Exception:
            logger.debug("Failed to detect local IP, using 127.0.0.1")
            host = "127.0.0.1"
    return host


def _build_driver_config(protocol: str, protocol_config: dict[str, Any], protoforge_host: str = "") -> dict[str, Any]:
    if not protoforge_host:
        protoforge_host = get_protoforge_host()
    host = protoforge_host
    port = protocol_config.get("port")

    if protocol == "modbus_tcp":
        base = {"host": host, "port": port or 5020, "slave_id": protocol_config.get("slave_id", 1), "timeout": 5.0}
    elif protocol == "modbus_rtu":
        base = {
            "port": protocol_config.get("serial_port", "/dev/ttyUSB0"),
            "baudrate": protocol_config.get("baudrate", 9600),
            "slave_id": protocol_config.get("slave_id", 1),
            "parity": protocol_config.get("parity", "N"),
            "stop_bits": protocol_config.get("stop_bits", 1),
            "timeout": 5.0,
        }
    elif protocol == "opcua":
        base = {"endpoint": protocol_config.get("endpoint", f"opc.tcp://{host}:{port or 4840}"),
                "security_mode": protocol_config.get("security_mode", "None"), "timeout": 5.0}
    elif protocol == "mqtt":
        base = {"broker": host, "port": port or 1883, "timeout": 5.0}
    elif protocol == "http":
        base = {"url": protocol_config.get("url", f"http://{host}:{port or 8080}"),
                "method": protocol_config.get("method", "GET"), "timeout": 5.0}
    elif protocol == "s7":
        base = {"host": host, "port": port or 102, "rack": protocol_config.get("rack", 0),
                "slot": protocol_config.get("slot", 1), "timeout": 5.0}
    elif protocol == "mc":
        base = {"host": host, "port": port or 5000, "timeout": 5.0}
    elif protocol == "fins":
        base = {"host": host, "port": port or 9600, "timeout": 5.0}
    elif protocol == "ab":
        base = {"host": host, "port": port or 44818, "timeout": 5.0}
    elif protocol == "bacnet":
        base = {"host": host, "port": port or 47808,
                "device_id": protocol_config.get("device_id", 0), "timeout": 5.0}
    elif protocol == "fanuc":
        base = {"host": host, "port": port or 8193, "timeout": 5.0}
    elif protocol == "mtconnect":
        base = {"url": protocol_config.get("url", f"http://{host}:{port or 7878}"), "timeout": 5.0}
    elif protocol == "toledo":
        base = {"host": host, "port": port or 1701, "timeout": 5.0}
    elif protocol == "opcda":
        base = {"prog_id": protocol_config.get("prog_id", ""), "timeout": 5.0}
    elif protocol == "profinet":
        base = {"host": host, "port": port or 34964,
                "device_name": protocol_config.get("device_name", "protoforge-device"),
                "vendor_id": protocol_config.get("vendor_id", 266),
                "device_id": protocol_config.get("device_id", 256), "timeout": 5.0}
    elif protocol == "ethercat":
        base = {"host": host, "port": port or 34980,
                "slave_address": protocol_config.get("slave_address", 4097), "timeout": 5.0}
    else:
        base = {"host": host, "port": port, "timeout": 5.0}

    known = _DRIVER_CONFIG_KNOWN_KEYS.get(protocol, set())
    for k, v in protocol_config.items():
        if k not in known and k not in base and k not in (
            "edgelite_url", "edgelite_username", "edgelite_password", "collect_interval"
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

    driver_config = _build_driver_config(protocol, config, protoforge_host)
    edgelite_points = _build_points(points_data, data_type_mapper)

    return {
        "device_id": getattr(device, "id", ""),
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
    try:
        login_resp = await client.post(
            f"{url.rstrip('/')}/api/v1/auth/login",
            json={"username": username, "password": password},
        )
    except httpx.ConnectError as e:
        raise EdgeLiteError("connection", f"无法连接到 EdgeLite 网关: {e}", "请检查网关地址是否正确、网络是否通畅")
    except httpx.TimeoutException:
        raise EdgeLiteError("timeout", "连接 EdgeLite 网关超时", "请检查网关是否在线、网络延迟是否过高")

    if login_resp.status_code == 401:
        raise EdgeLiteError("auth", "EdgeLite 用户名或密码错误", "请检查系统设置中的 EdgeLite 用户名和密码")
    if login_resp.status_code != 200:
        raise EdgeLiteError("http", f"EdgeLite 登录失败: HTTP {login_resp.status_code}", f"网关返回错误状态码 {login_resp.status_code}")

    data = login_resp.json()
    token = data.get("data", {}).get("access_token", "") or data.get("access_token", "")
    if not token:
        raise EdgeLiteError("token", "EdgeLite 登录成功但未返回 Token", "请检查 EdgeLite 网关版本是否兼容")
    return token


def _extract_token(login_resp: httpx.Response) -> str:
    data = login_resp.json()
    return data.get("data", {}).get("access_token", "") or data.get("access_token", "")


async def push_device_to_edgelite(device: Any, protoforge_host: str = "") -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {
            "ok": False, "skipped": True,
            "reason": "edgelite_url not configured",
            "error_type": "not_configured",
            "suggestion": "请先在「系统设置」中配置 EdgeLite 网关地址，或在设备协议配置中填写 edgelite_url",
        }

    payload = convert_device_to_edgelite(device, protoforge_host)
    if payload is None:
        return {
            "ok": False, "skipped": True,
            "reason": "Protocol not supported by EdgeLite",
            "error_type": "unsupported",
            "suggestion": "该协议暂不支持 EdgeLite 联调",
        }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except EdgeLiteError as e:
            return {
                "ok": False,
                "error": str(e),
                "error_type": e.error_type,
                "suggestion": e.suggestion,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": "unknown", "suggestion": "请检查网络连接和网关配置"}

        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            f"{el_config['url'].rstrip('/')}/api/v1/devices",
            json=payload, headers=headers,
        )
        if create_resp.status_code in (200, 201):
            logger.info("Device %s registered to EdgeLite, auto-collecting started", payload["device_id"])
            return {"ok": True, "action": "created", "device_id": payload["device_id"], "driver_config": payload.get("config", {})}

        if create_resp.status_code == 409:
            update_payload = {k: v for k, v in payload.items() if k != "device_id"}
            update_resp = await client.put(
                f"{el_config['url'].rstrip('/')}/api/v1/devices/{payload['device_id']}",
                json=update_payload, headers=headers,
            )
            if update_resp.status_code == 200:
                logger.info("Device %s updated on EdgeLite", payload["device_id"])
                return {"ok": True, "action": "updated", "device_id": payload["device_id"], "driver_config": payload.get("config", {})}
            return {"ok": False, "error": f"Update failed: HTTP {update_resp.status_code}", "error_type": "update_failed"}

        if create_resp.status_code == 422:
            return {
                "ok": False,
                "error": f"EdgeLite 拒绝推送: {create_resp.text[:300]}",
                "error_type": "validation_error",
                "suggestion": "设备配置可能存在不兼容字段，请检查协议类型和测点配置",
            }

        if create_resp.status_code >= 500:
            return {
                "ok": False,
                "error": f"EdgeLite 服务器错误: HTTP {create_resp.status_code}",
                "error_type": "edgelite_error",
                "suggestion": f"EdgeLite ({el_config['url']}) 内部错误。请检查 EdgeLite 日志，确认已注册的协议驱动类型: {payload['protocol']}",
            }

        return {"ok": False, "error": f"Create failed: HTTP {create_resp.status_code}", "error_type": "create_failed"}


async def remove_device_from_edgelite(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

    device_id = getattr(device, "id", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except EdgeLiteError as e:
            return {"ok": False, "error": str(e), "error_type": e.error_type, "suggestion": e.suggestion}
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": "unknown", "suggestion": "请检查网络连接和网关配置"}

        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.delete(
            f"{el_config['url'].rstrip('/')}/api/v1/devices/{device_id}",
            headers=headers,
        )
        if resp.status_code in (200, 204, 404):
            return {"ok": True, "action": "deleted", "device_id": device_id}
        return {"ok": False, "error": f"Delete failed: HTTP {resp.status_code}", "error_type": "delete_failed"}


async def get_edgelite_device_status(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

    device_id = getattr(device, "id", "")
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except EdgeLiteError as e:
            return {"ok": False, "error": str(e), "error_type": e.error_type, "suggestion": e.suggestion}
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": "unknown", "suggestion": "请检查网络连接和网关配置"}

        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(
            f"{el_config['url'].rstrip('/')}/api/v1/devices/{device_id}",
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", resp.json())
            return {
                "ok": True,
                "device_id": device_id,
                "status": data.get("status", "unknown"),
                "name": data.get("name", ""),
                "protocol": data.get("protocol", ""),
                "collect_interval": data.get("collect_interval", 0),
            }
        if resp.status_code == 404:
            return {"ok": True, "device_id": device_id, "status": "not_registered"}
        return {"ok": False, "error": f"HTTP {resp.status_code}", "error_type": "http_error"}


async def read_edgelite_device_points(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

    device_id = getattr(device, "id", "")
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except EdgeLiteError as e:
            return {"ok": False, "error": str(e), "error_type": e.error_type, "suggestion": e.suggestion}
        except Exception as e:
            return {"ok": False, "error": str(e), "error_type": "unknown", "suggestion": "请检查网络连接和网关配置"}

        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(
            f"{el_config['url'].rstrip('/')}/api/v1/devices/{device_id}/points",
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", resp.json())
            return {"ok": True, "device_id": device_id, "points": data}
        if resp.status_code == 404:
            return {"ok": False, "error": "Device not found on EdgeLite", "error_type": "not_found"}
        return {"ok": False, "error": f"HTTP {resp.status_code}", "error_type": "http_error"}


_PROTOCOL_DISPLAY = {
    "modbus_tcp": "Modbus TCP", "modbus_rtu": "Modbus RTU", "opcua": "OPC-UA",
    "mqtt": "MQTT", "http": "HTTP REST", "s7": "S7", "mc": "MC协议",
    "fins": "FINS", "ab": "EtherNet/IP", "bacnet": "BACnet",
    "fanuc": "FOCAS", "mtconnect": "MTConnect", "toledo": "Toledo",
    "profinet": "PROFINET", "ethercat": "EtherCAT",
}

_PROTOCOL_DEFAULT_PORTS = {
    "modbus_tcp": 5020, "opcua": 4840, "mqtt": 1883, "http": 8080,
    "s7": 102, "mc": 5000, "fins": 9600, "ab": 44818, "bacnet": 47808,
    "fanuc": 8193, "mtconnect": 7878, "toledo": 1701,
    "profinet": 34964, "ethercat": 34980,
}


def _extract_driver_host_port(driver_config: dict, protocol: str = "") -> tuple[str, str]:
    if not isinstance(driver_config, dict):
        return ("", "")
    host = ""
    port = ""
    if protocol == "mqtt":
        host = driver_config.get("broker", "")
        port = str(driver_config.get("port", ""))
    elif protocol == "http":
        url = driver_config.get("url", "")
        if url:
            import urllib.parse
            try:
                parsed = urllib.parse.urlparse(url)
                host = parsed.hostname or ""
                port = str(parsed.port) if parsed.port else ""
            except Exception:
                host = url
        else:
            host = driver_config.get("host", "")
            port = str(driver_config.get("port", ""))
    elif protocol == "opcua":
        endpoint = driver_config.get("endpoint", "")
        if endpoint:
            try:
                import re
                m = re.search(r'opc\.tcp://([^:]+):?(\d+)?', endpoint)
                if m:
                    host = m.group(1) or ""
                    port = m.group(2) or ""
            except Exception:
                host = endpoint
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
            except Exception:
                host = url
        else:
            host = driver_config.get("host", "")
            port = str(driver_config.get("port", ""))
    else:
        host = driver_config.get("host", driver_config.get("ip", ""))
        port = str(driver_config.get("port", ""))
    return (host, port)


def _build_connect_error(driver_config: dict, protocol: str, protoforge_running: bool) -> dict[str, Any]:
    driver_host, driver_port = _extract_driver_host_port(driver_config, protocol)
    proto_name = _PROTOCOL_DISPLAY.get(protocol, protocol.upper())
    default_port = _PROTOCOL_DEFAULT_PORTS.get(protocol, "")

    parts = []
    if not protoforge_running:
        parts.append(f"ProtoForge 的 {proto_name} 协议服务未启动。请先在「协议管理」中启动 {proto_name} 服务")
    elif not driver_host:
        parts.append(f"driver_config 中未指定 ProtoForge 的 IP 地址。请在「系统设置 > EdgeLite配置 > ProtoForge地址」中填写 EdgeLite 可达的 IP")
    else:
        parts.append(f"EdgeLite 的 {proto_name} 驱动无法连接 ProtoForge ({driver_host}:{driver_port})")

        if driver_port and default_port and str(driver_port) != str(default_port):
            parts.append(f"端口 {driver_port} 不是 {proto_name} 的默认端口 ({default_port})，请确认 EdgeLite 侧 {proto_name} 服务是否在端口 {driver_port} 上运行")

        parts.append(f"请检查：1) {proto_name} 协议服务是否在运行  2) IP {driver_host} 从 EdgeLite 是否可达  3) 端口 {driver_port} 是否正确")
        parts.append(f"如果 IP 不正确，请在「系统设置 > EdgeLite配置 > ProtoForge地址」中填写 EdgeLite 可达的 IP")

    host_info = f" ({driver_host}:{driver_port})" if driver_host or driver_port else ""
    return {
        "ok": False,
        "error": "\n".join(parts),
        "driver_config": driver_config,
        "driver_host": driver_host,
        "driver_port": driver_port,
    }


async def verify_edgelite_pipeline(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {
            "ok": False, "skipped": True,
            "reason": "edgelite_url not configured",
            "error_type": "not_configured",
            "suggestion": "请先在「系统设置」中配置 EdgeLite 网关地址，或在设备协议配置中填写 edgelite_url",
        }

    device_id = getattr(device, "id", "")
    result: dict[str, Any] = {"device_id": device_id, "steps": {}}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except EdgeLiteError as e:
            result["steps"]["auth"] = {"ok": False, "error": str(e), "error_type": e.error_type, "suggestion": e.suggestion}
            result["ok"] = False
            return result
        except Exception as e:
            result["steps"]["auth"] = {"ok": False, "error": str(e), "error_type": "unknown", "suggestion": "请检查网络连接和网关配置"}
            result["ok"] = False
            return result
        result["steps"]["auth"] = {"ok": True}
        headers = {"Authorization": f"Bearer {token}"}

        dev_resp = await client.get(
            f"{el_config['url'].rstrip('/')}/api/v1/devices/{device_id}",
            headers=headers,
        )
        if dev_resp.status_code == 404:
            result["steps"]["register"] = {"ok": False, "error": "Device not registered on EdgeLite"}
            result["ok"] = False
            return result
        if dev_resp.status_code != 200:
            result["steps"]["register"] = {"ok": False, "error": f"HTTP {dev_resp.status_code}"}
            result["ok"] = False
            return result

        dev_data = dev_resp.json().get("data", dev_resp.json())
        el_status = dev_data.get("status", "unknown")
        result["steps"]["register"] = {"ok": True, "status": el_status}

        if el_status == "offline":
            driver_config = dev_data.get("config", dev_data.get("driver_config", {}))
            device_protocol = getattr(device, "protocol", "") or ""
            protoforge_running = False
            try:
                from protoforge.main import get_engine
                engine = get_engine()
                protoforge_running = engine.is_protocol_running(device_protocol)
            except Exception:
                pass
            connect_error = _build_connect_error(driver_config if isinstance(driver_config, dict) else {}, device_protocol, protoforge_running)
            result["steps"]["connect"] = connect_error
            result["ok"] = False
            return result
        result["steps"]["connect"] = {"ok": True, "status": el_status}

        points_resp = await client.get(
            f"{el_config['url'].rstrip('/')}/api/v1/devices/{device_id}/points",
            headers=headers,
        )
        if points_resp.status_code == 200:
            points_data = points_resp.json().get("data", points_resp.json())
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


async def test_edgelite_connection(url: str, username: str = "admin", password: str = "") -> dict[str, Any]:
    if not url:
        return {"ok": False, "error": "URL is empty"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{url.rstrip('/')}/api/v1/system/status")
            if resp.status_code == 200:
                data = resp.json().get("data", resp.json())
                return {"ok": True, "version": data.get("version", ""), "devices": data.get("device_total", 0)}

            needs_auth = resp.status_code in (401, 403)
            if not needs_auth:
                return {"ok": False, "error": f"HTTP {resp.status_code}"}

            if not password:
                return {"ok": False, "error": "EdgeLite 需要认证，请输入用户名和密码"}

            login_resp = await client.post(
                f"{url.rstrip('/')}/api/v1/auth/login",
                json={"username": username, "password": password},
            )
            if login_resp.status_code == 200:
                token = _extract_token(login_resp)
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                try:
                    status_resp = await client.get(f"{url.rstrip('/')}/api/v1/system/status", headers=headers)
                    if status_resp.status_code == 200:
                        data = status_resp.json().get("data", status_resp.json())
                        return {"ok": True, "version": data.get("version", ""), "devices": data.get("device_total", 0)}
                except Exception as e:
                    logger.debug("EdgeLite connection test after auth failed: %s", e)
                return {"ok": True, "version": "未知", "devices": 0}

            if login_resp.status_code == 401:
                return {"ok": False, "error": "EdgeLite 用户名或密码错误"}
            if login_resp.status_code == 403:
                return {"ok": False, "error": f"EdgeLite 拒绝登录 (HTTP {login_resp.status_code})，请检查账号权限"}
            return {"ok": False, "error": f"EdgeLite 登录失败: HTTP {login_resp.status_code}"}

        except httpx.ConnectError:
            return {"ok": False, "error": "Connection refused"}
        except httpx.TimeoutException:
            return {"ok": False, "error": "Connection timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
