import asyncio
import logging
import os
from typing import Any, Optional

import httpx

from protoforge.core.integration.protocol import (
    PROTOCOL_MAP_BASE,
    DATA_TYPE_MAP,
    DATA_TYPE_MAP_FALLBACK,
    ACCESS_MODE_MAP,
    ProtocolMapper,
    DataTypeMapper,
    ProtocolMappingResult,
    DataTypeMappingResult,
)

logger = logging.getLogger(__name__)

PROTOCOL_MAP: dict[str, str] = {
    k: v for k, v in PROTOCOL_MAP_BASE.items() if v is not None
}

EDGELITE_PUSH_FIELDS = [
    {"key": "edgelite_url", "label": "EdgeLite网关地址", "type": "string", "default": "",
     "description": "填写后设备创建时自动注册到EdgeLite网关，如 http://192.168.1.200:8100"},
    {"key": "edgelite_username", "label": "EdgeLite用户名", "type": "string", "default": "admin",
     "description": "EdgeLite网关登录用户名"},
    {"key": "edgelite_password", "label": "EdgeLite密码", "type": "string", "default": "",
     "description": "EdgeLite网关登录密码"},
    {"key": "collect_interval", "label": "采集间隔(秒)", "type": "number", "default": 5, "min": 1, "max": 3600,
     "description": "EdgeLite采集此设备数据的间隔秒数"},
]

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
    host = os.environ.get("PROTOFORGE_HOST", "0.0.0.0")
    if host in ("0.0.0.0", ""):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            host = s.getsockname()[0]
            s.close()
        except Exception:
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
) -> Optional[dict[str, Any]]:
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
    config = getattr(device, "protocol_config", {}) or {}
    url = config.get("edgelite_url", "")
    username = config.get("edgelite_username", "admin")
    password = config.get("edgelite_password", "")
    return {"url": url, "username": username, "password": password}


async def _login_edgelite(client: httpx.AsyncClient, url: str, username: str, password: str) -> str:
    login_resp = await client.post(
        f"{url.rstrip('/')}/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    if login_resp.status_code != 200:
        raise Exception(f"EdgeLite login failed: HTTP {login_resp.status_code}")
    data = login_resp.json()
    token = data.get("data", {}).get("access_token", "") or data.get("access_token", "")
    if not token:
        raise Exception("EdgeLite login succeeded but no token returned")
    return token


async def push_device_to_edgelite(device: Any, protoforge_host: str = "") -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured for this device"}

    payload = convert_device_to_edgelite(device, protoforge_host)
    if payload is None:
        return {"ok": False, "skipped": True, "reason": "Protocol not supported by EdgeLite"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except Exception as e:
            return {"ok": False, "error": str(e)}

        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            f"{el_config['url'].rstrip('/')}/api/v1/devices",
            json=payload, headers=headers,
        )
        if create_resp.status_code in (200, 201):
            logger.info("Device %s registered to EdgeLite, auto-collecting started", payload["device_id"])
            return {"ok": True, "action": "created", "device_id": payload["device_id"]}

        if create_resp.status_code == 409:
            update_payload = {k: v for k, v in payload.items() if k != "device_id"}
            update_resp = await client.put(
                f"{el_config['url'].rstrip('/')}/api/v1/devices/{payload['device_id']}",
                json=update_payload, headers=headers,
            )
            if update_resp.status_code == 200:
                logger.info("Device %s updated on EdgeLite", payload["device_id"])
                return {"ok": True, "action": "updated", "device_id": payload["device_id"]}
            return {"ok": False, "error": f"Update failed: HTTP {update_resp.status_code}"}

        return {"ok": False, "error": f"Create failed: HTTP {create_resp.status_code} {create_resp.text[:200]}"}


async def remove_device_from_edgelite(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

    device_id = getattr(device, "id", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except Exception as e:
            return {"ok": False, "error": str(e)}

        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.delete(
            f"{el_config['url'].rstrip('/')}/api/v1/devices/{device_id}",
            headers=headers,
        )
        if resp.status_code in (200, 204, 404):
            return {"ok": True, "action": "deleted", "device_id": device_id}
        return {"ok": False, "error": f"Delete failed: HTTP {resp.status_code}"}


async def get_edgelite_device_status(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True}

    device_id = getattr(device, "id", "")
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except Exception as e:
            return {"ok": False, "error": str(e)}

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
        return {"ok": False, "error": f"HTTP {resp.status_code}"}


async def read_edgelite_device_points(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True}

    device_id = getattr(device, "id", "")
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except Exception as e:
            return {"ok": False, "error": str(e)}

        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(
            f"{el_config['url'].rstrip('/')}/api/v1/devices/{device_id}/points",
            headers=headers,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", resp.json())
            return {"ok": True, "device_id": device_id, "points": data}
        if resp.status_code == 404:
            return {"ok": False, "error": "Device not found on EdgeLite"}
        return {"ok": False, "error": f"HTTP {resp.status_code}"}


async def verify_edgelite_pipeline(device: Any) -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured"}

    device_id = getattr(device, "id", "")
    result: dict[str, Any] = {"device_id": device_id, "steps": {}}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            token = await _login_edgelite(client, el_config["url"], el_config["username"], el_config["password"])
        except Exception as e:
            result["steps"]["auth"] = {"ok": False, "error": str(e)}
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
            result["steps"]["connect"] = {"ok": False, "error": "EdgeLite cannot connect to ProtoForge - check host/port and protocol server status"}
            result["ok"] = False
            return result
        result["steps"]["connect"] = {"ok": True, "status": el_status}

        points_resp = await client.get(
            f"{el_config['url'].rstrip('/')}/api/v1/devices/{device_id}/points",
            headers=headers,
        )
        if points_resp.status_code == 200:
            points_data = points_resp.json().get("data", points_resp.json())
            has_data = any(v is not None for v in points_data.values()) if isinstance(points_data, dict) else False
            result["steps"]["collect"] = {
                "ok": True,
                "data": points_data,
                "has_real_data": has_data,
            }
        else:
            result["steps"]["collect"] = {"ok": False, "error": f"HTTP {points_resp.status_code}"}

        all_ok = all(s.get("ok", False) for s in result["steps"].values())
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
            if resp.status_code == 401 and password:
                login_resp = await client.post(
                    f"{url.rstrip('/')}/api/v1/auth/login",
                    json={"username": username, "password": password},
                )
                if login_resp.status_code == 200:
                    return {"ok": True}
                return {"ok": False, "error": f"Auth failed: {login_resp.status_code}"}
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
        except httpx.ConnectError:
            return {"ok": False, "error": "Connection refused"}
        except httpx.TimeoutException:
            return {"ok": False, "error": "Connection timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
