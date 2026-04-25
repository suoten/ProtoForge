import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

PROTOCOL_MAP: dict[str, str] = {
    "modbus_tcp": "modbus_tcp",
    "modbus_rtu": "modbus_rtu",
    "opcua": "opcua",
    "mqtt": "mqtt",
    "http": "http",
    "s7": "s7",
    "mc": "mc",
    "fins": "fins",
    "ab": "allen_bradley",
    "bacnet": "bacnet",
    "fanuc": "fanuc",
    "mtconnect": "mtconnect",
    "toledo": "toledo",
    "opcda": "opc_da",
}

DATA_TYPE_MAP: dict[str, str] = {
    "bool": "bool",
    "int16": "int16",
    "int32": "int32",
    "uint16": "uint16",
    "uint32": "uint32",
    "float32": "float32",
    "float64": "float32",
    "string": "string",
}

ACCESS_MODE_MAP: dict[str, str] = {
    "r": "r", "w": "w", "rw": "rw", "ro": "r", "wo": "w",
}

EDGELITE_PUSH_FIELDS = [
    {"key": "edgelite_url", "label": "EdgeLite网关地址", "type": "string", "default": "",
     "description": "填写后设备创建时自动注册到EdgeLite网关，如 http://192.168.1.200:8100"},
    {"key": "edgelite_username", "label": "EdgeLite用户名", "type": "string", "default": "admin",
     "description": "EdgeLite网关登录用户名"},
    {"key": "edgelite_password", "label": "EdgeLite密码", "type": "string", "default": "",
     "description": "EdgeLite网关登录密码"},
]


def _build_driver_config(protocol: str, protocol_config: dict[str, Any], protoforge_host: str = "127.0.0.1") -> dict[str, Any]:
    host = protocol_config.get("host", protoforge_host)
    port = protocol_config.get("port")

    if protocol == "modbus_tcp":
        return {"host": host, "port": port or 5020, "slave_id": protocol_config.get("slave_id", 1), "timeout": 5.0}
    elif protocol == "modbus_rtu":
        return {"port": protocol_config.get("serial_port", "/dev/ttyUSB0"), "baudrate": protocol_config.get("baudrate", 9600),
                "slave_id": protocol_config.get("slave_id", 1), "timeout": 5.0}
    elif protocol == "opcua":
        return {"endpoint": protocol_config.get("endpoint", f"opc.tcp://{host}:{port or 4840}"),
                "security_mode": protocol_config.get("security_mode", "None"), "timeout": 5.0}
    elif protocol == "mqtt":
        return {"broker": host, "port": port or 1883, "timeout": 5.0}
    elif protocol == "http":
        return {"url": protocol_config.get("url", f"http://{host}:{port or 8080}"), "timeout": 5.0}
    elif protocol == "s7":
        return {"host": host, "port": port or 102, "rack": protocol_config.get("rack", 0),
                "slot": protocol_config.get("slot", 1), "timeout": 5.0}
    elif protocol == "mc":
        return {"host": host, "port": port or 5000, "timeout": 5.0}
    elif protocol == "fins":
        return {"host": host, "port": port or 9600, "timeout": 5.0}
    elif protocol == "ab":
        return {"host": host, "port": port or 44818, "timeout": 5.0}
    elif protocol == "bacnet":
        return {"host": host, "port": port or 47808, "timeout": 5.0}
    elif protocol == "fanuc":
        return {"host": host, "port": port or 8193, "timeout": 5.0}
    elif protocol == "mtconnect":
        return {"url": protocol_config.get("url", f"http://{host}:{port or 7878}"), "timeout": 5.0}
    elif protocol == "toledo":
        return {"host": host, "port": port or 1701, "timeout": 5.0}
    elif protocol == "opcda":
        return {"prog_id": protocol_config.get("prog_id", ""), "timeout": 5.0}
    return {"host": host, "port": port, "timeout": 5.0}


def _build_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for p in points:
        point_def: dict[str, Any] = {
            "name": p.get("name", ""),
            "data_type": DATA_TYPE_MAP.get(p.get("data_type", "float32"), "float32"),
            "unit": p.get("unit", ""),
            "address": p.get("address", "0"),
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


def convert_device_to_edgelite(device: Any, protoforge_host: str = "127.0.0.1") -> Optional[dict[str, Any]]:
    protocol = getattr(device, "protocol", "") or ""
    if protocol in ("gb28181", "video"):
        return None

    edgelite_protocol = PROTOCOL_MAP.get(protocol)
    if not edgelite_protocol:
        return None

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
    edgelite_points = _build_points(points_data)

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


async def push_device_to_edgelite(device: Any, protoforge_host: str = "127.0.0.1") -> dict[str, Any]:
    el_config = get_edgelite_config_from_device(device)
    if not el_config["url"]:
        return {"ok": False, "skipped": True, "reason": "edgelite_url not configured for this device"}

    payload = convert_device_to_edgelite(device, protoforge_host)
    if payload is None:
        return {"ok": False, "skipped": True, "reason": "Protocol not supported by EdgeLite"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        token = ""
        try:
            login_resp = await client.post(
                f"{el_config['url'].rstrip('/')}/api/v1/auth/login",
                json={"username": el_config["username"], "password": el_config["password"]},
            )
            if login_resp.status_code != 200:
                return {"ok": False, "error": f"EdgeLite login failed: {login_resp.status_code}"}
            token = login_resp.json().get("access_token", "")
        except Exception as e:
            return {"ok": False, "error": f"EdgeLite connection failed: {e}"}

        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            f"{el_config['url'].rstrip('/')}/api/v1/devices",
            json=payload, headers=headers,
        )
        if create_resp.status_code in (200, 201):
            return {"ok": True, "device": create_resp.json()}

        if create_resp.status_code == 409:
            update_payload = {k: v for k, v in payload.items() if k != "device_id"}
            update_resp = await client.put(
                f"{el_config['url'].rstrip('/')}/api/v1/devices/{payload['device_id']}",
                json=update_payload, headers=headers,
            )
            if update_resp.status_code == 200:
                return {"ok": True, "updated": True, "device": update_resp.json()}
            return {"ok": False, "error": f"Update failed: {update_resp.status_code}"}

        return {"ok": False, "error": f"Create failed: {create_resp.status_code} {create_resp.text}"}


async def test_edgelite_connection(url: str, username: str = "admin", password: str = "") -> dict[str, Any]:
    if not url:
        return {"ok": False, "error": "URL is empty"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{url.rstrip('/')}/api/v1/system/status")
            if resp.status_code == 200:
                return {"ok": True}
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
