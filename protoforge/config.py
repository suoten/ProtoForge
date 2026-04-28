import json
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    db_path: str = "data/protoforge.db"
    jwt_secret: str = ""
    demo_mode: bool = False
    log_level: str = "info"
    cors_origins: str = "*"

    influxdb_url: str = ""
    influxdb_token: str = ""
    influxdb_org: str = "default"
    influxdb_bucket: str = "protoforge"

    modbus_tcp_port: int = 5020
    modbus_rtu_port: str = "/dev/ttyUSB0"
    opcua_port: int = 4840
    mqtt_port: int = 1883
    http_port: int = 8080
    gb28181_port: int = 5060
    bacnet_port: int = 47808
    s7_port: int = 102
    mc_port: int = 5000
    fins_port: int = 9600
    ab_port: int = 44818
    opcda_port: int = 51340
    fanuc_port: int = 8193
    mtconnect_port: int = 7878
    toledo_port: int = 1701
    profinet_port: int = 34964
    ethercat_port: int = 34980

    model_config = {
        "env_prefix": "PROTOFORGE_",
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


_settings: Settings | None = None
_settings_overrides: dict[str, Any] = {}


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        if _settings_overrides:
            for key, value in _settings_overrides.items():
                if hasattr(_settings, key):
                    setattr(_settings, key, value)
    return _settings


def update_settings(updates: dict[str, Any]) -> dict[str, Any]:
    global _settings, _settings_overrides
    s = get_settings()
    changed = {}
    for key, value in updates.items():
        if key.endswith("_port") or key in ("host", "port", "db_path", "jwt_secret"):
            _settings_overrides[key] = value
            if hasattr(s, key):
                old_val = getattr(s, key)
                if old_val != value:
                    setattr(s, key, value)
                    changed[key] = {"old": old_val, "new": value}
    _save_env()
    return changed


def _save_env() -> None:
    prefix = "PROTOFORGE_"
    lines = []
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                field_name = key[len(prefix):].lower() if key.startswith(prefix) else key.lower()
                if field_name in _settings_overrides:
                    lines.append(f"{key}={_settings_overrides[field_name]}")
                else:
                    lines.append(line)
            else:
                lines.append(line)

    existing_keys = set()
    for line in lines:
        if "=" in line:
            existing_keys.add(line.split("=", 1)[0].strip())

    for key, value in _settings_overrides.items():
        env_key = f"{prefix}{key.upper()}"
        if env_key not in existing_keys:
            lines.append(f"{env_key}={value}")

    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_protocol_port_map() -> dict[str, Any]:
    s = get_settings()
    return {
        "modbus_tcp": {"port": s.modbus_tcp_port, "host": "0.0.0.0"},
        "modbus_rtu": {"port": s.modbus_rtu_port, "host": "/dev/ttyUSB0"},
        "opcua": {"port": s.opcua_port, "host": "0.0.0.0"},
        "mqtt": {"port": s.mqtt_port, "host": "0.0.0.0"},
        "http": {"port": s.http_port, "host": "0.0.0.0"},
        "gb28181": {"port": s.gb28181_port, "host": "0.0.0.0"},
        "bacnet": {"port": s.bacnet_port, "host": "0.0.0.0"},
        "s7": {"port": s.s7_port, "host": "0.0.0.0"},
        "mc": {"port": s.mc_port, "host": "0.0.0.0"},
        "fins": {"port": s.fins_port, "host": "0.0.0.0"},
        "ab": {"port": s.ab_port, "host": "0.0.0.0"},
        "opcda": {"port": s.opcda_port, "host": "0.0.0.0"},
        "fanuc": {"port": s.fanuc_port, "host": "0.0.0.0"},
        "mtconnect": {"port": s.mtconnect_port, "host": "0.0.0.0"},
        "toledo": {"port": s.toledo_port, "host": "0.0.0.0"},
        "profinet": {"port": s.profinet_port, "host": "0.0.0.0"},
        "ethercat": {"port": s.ethercat_port, "host": "0.0.0.0"},
    }


def get_all_settings_dict() -> dict[str, Any]:
    s = get_settings()
    return {
        "host": s.host,
        "port": s.port,
        "db_path": s.db_path,
        "demo_mode": s.demo_mode,
        "protocol_ports": {
            "modbus_tcp": s.modbus_tcp_port,
            "modbus_rtu": s.modbus_rtu_port,
            "opcua": s.opcua_port,
            "mqtt": s.mqtt_port,
            "http": s.http_port,
            "gb28181": s.gb28181_port,
            "bacnet": s.bacnet_port,
            "s7": s.s7_port,
            "mc": s.mc_port,
            "fins": s.fins_port,
            "ab": s.ab_port,
            "opcda": s.opcda_port,
            "fanuc": s.fanuc_port,
            "mtconnect": s.mtconnect_port,
            "toledo": s.toledo_port,
            "profinet": s.profinet_port,
            "ethercat": s.ethercat_port,
        },
    }
