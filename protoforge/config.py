import json
import logging
import secrets
import threading
from pathlib import Path
from typing import Any

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
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    no_auth: bool = False
    admin_password: str = ""
    grpc_port: int = 50051
    failover_role: str = ""
    failover_primary: str = ""
    failover_standby: str = ""
    failover_interval: int = 10

    influxdb_url: str = ""
    influxdb_token: str = ""
    influxdb_org: str = "default"
    influxdb_bucket: str = "protoforge"

    edgelite_url: str = ""
    edgelite_username: str = "admin"
    edgelite_password: str = ""
    protoforge_public_host: str = ""
    tick_interval: float = 1.0

    access_token_expires: int = 86400
    refresh_token_expires: int = 604800
    max_login_attempts: int = 5
    lockout_duration: int = 300
    min_password_length: int = 8

    http_timeout: float = 10.0
    http_timeout_short: float = 5.0
    http_timeout_long: float = 30.0

    audit_max_entries: int = 50000
    event_bus_max_history: int = 5000
    event_bus_subscriber_queue: int = 1000
    log_bus_max_entries: int = 10000
    log_bus_subscriber_queue: int = 1000
    recorder_max_messages: int = 100000
    recorder_queue_size: int = 50000
    webhook_queue_size: int = 5000
    webhook_rate_limit_seconds: float = 5.0
    webhook_auto_disable_threshold: int = 50
    forward_queue_size: int = 10000
    forward_batch_size: int = 100
    forward_flush_interval: float = 5.0
    forward_retry_count: int = 3
    failover_max_failures: int = 3
    test_max_reports: int = 1000
    rate_limit_max_requests: int = 100
    rate_limit_window_seconds: int = 60
    rate_limit_auth_max_requests: int = 10
    rate_limit_auth_window_seconds: int = 60

    modbus_tcp_port: int = 5020
    modbus_rtu_port: str = "/dev/ttyUSB0"
    modbus_rtu_host: str = "/dev/ttyUSB0"
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

    @property
    def protocol_ports(self) -> dict[str, Any]:
        return {
            "modbus_tcp": {"port": self.modbus_tcp_port, "host": self.host or "0.0.0.0"},
            "modbus_rtu": {"port": self.modbus_rtu_port, "host": self.modbus_rtu_host},
            "opcua": {"port": self.opcua_port, "host": self.host or "0.0.0.0"},
            "mqtt": {"port": self.mqtt_port, "host": self.host or "0.0.0.0"},
            "http": {"port": self.http_port, "host": self.host or "0.0.0.0"},
            "gb28181": {"port": self.gb28181_port, "host": self.host or "0.0.0.0"},
            "bacnet": {"port": self.bacnet_port, "host": self.host or "0.0.0.0"},
            "s7": {"port": self.s7_port, "host": self.host or "0.0.0.0"},
            "mc": {"port": self.mc_port, "host": self.host or "0.0.0.0"},
            "fins": {"port": self.fins_port, "host": self.host or "0.0.0.0"},
            "ab": {"port": self.ab_port, "host": self.host or "0.0.0.0"},
            "opcda": {"port": self.opcda_port, "host": self.host or "0.0.0.0"},
            "fanuc": {"port": self.fanuc_port, "host": self.host or "0.0.0.0"},
            "mtconnect": {"port": self.mtconnect_port, "host": self.host or "0.0.0.0"},
            "toledo": {"port": self.toledo_port, "host": self.host or "0.0.0.0"},
            "profinet": {"port": self.profinet_port, "host": self.host or "0.0.0.0"},
            "ethercat": {"port": self.ethercat_port, "host": self.host or "0.0.0.0"},
        }

    model_config = {
        "env_prefix": "PROTOFORGE_",
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


_settings: Settings | None = None
_settings_overrides: dict[str, Any] = {}
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    global _settings
    with _settings_lock:
        if _settings is None:
            _settings = Settings()
            if not _settings.jwt_secret:
                _settings.jwt_secret = secrets.token_urlsafe(32)
                logger.warning("JWT secret not configured, auto-generated. Set PROTOFORGE_JWT_SECRET for production.")
            if _settings_overrides:
                for key, value in _settings_overrides.items():
                    if hasattr(_settings, key):
                        setattr(_settings, key, value)
    return _settings


def _validate_setting(key: str, value: Any) -> str | None:
    if key == "port" or key == "http_port":
        try:
            p = int(value)
            if not (1 <= p <= 65535):
                return f"端口号必须在 1-65535 之间，当前值: {p}"
        except (ValueError, TypeError):
            return f"端口号必须为整数，当前值: {value}"
    if key.endswith("_port") and key != "modbus_rtu_port":
        try:
            p = int(value)
            if not (1 <= p <= 65535):
                return f"端口号必须在 1-65535 之间，当前值: {p}"
        except (ValueError, TypeError):
            return f"端口号必须为整数，当前值: {value}"
    if key == "log_level":
        valid_levels = {"debug", "info", "warning", "error", "critical"}
        if str(value).lower() not in valid_levels:
            return f"日志级别必须为 {', '.join(valid_levels)} 之一，当前值: {value}"
    if key == "host" and value:
        if not isinstance(value, str) or not value.strip():
            return "主机地址不能为空"
    return None


class ConfigValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def update_settings(updates: dict[str, Any]) -> dict[str, Any]:
    global _settings, _settings_overrides
    s = get_settings()
    changed = {}
    errors = []
    allowed_keys = {
        "host", "port", "db_path", "demo_mode",
        "log_level", "cors_origins",
        "influxdb_url", "influxdb_token", "influxdb_org", "influxdb_bucket",
        "edgelite_url", "edgelite_username", "edgelite_password",
        "protoforge_public_host",
    }
    for key, value in updates.items():
        if key.endswith("_port") or key in allowed_keys:
            if value == "***":
                continue
            validation_error = _validate_setting(key, value)
            if validation_error:
                errors.append(validation_error)
                continue
            _settings_overrides[key] = value
            if hasattr(s, key):
                old_val = getattr(s, key)
                if old_val != value:
                    setattr(s, key, value)
                    changed[key] = {"old": old_val, "new": value}
    if errors:
        raise ConfigValidationError(errors)
    _save_env()
    return changed


def _save_env() -> None:
    prefix = "PROTOFORGE_"
    lines = []
    try:
        if _ENV_FILE.exists():
            content = _ENV_FILE.read_text(encoding="utf-8")
            content = content.replace("\r\n", "\n")
            for line in content.splitlines():
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

        _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except (OSError, PermissionError) as e:
        logger.warning("Failed to save .env file: %s", e)


def get_protocol_port_map() -> dict[str, Any]:
    return get_settings().protocol_ports


def get_all_settings_dict() -> dict[str, Any]:
    s = get_settings()
    return {
        "host": s.host,
        "port": s.port,
        "db_path": s.db_path,
        "demo_mode": s.demo_mode,
        "log_level": s.log_level,
        "cors_origins": s.cors_origins,
        "influxdb_url": s.influxdb_url,
        "influxdb_token": "***" if s.influxdb_token else "",
        "influxdb_org": s.influxdb_org,
        "influxdb_bucket": s.influxdb_bucket,
        "edgelite_url": s.edgelite_url,
        "edgelite_username": s.edgelite_username,
        "edgelite_password": "***" if s.edgelite_password else "",
        "protoforge_public_host": s.protoforge_public_host or "",
        "protocol_ports": {k: v["port"] for k, v in s.protocol_ports.items()},
    }
