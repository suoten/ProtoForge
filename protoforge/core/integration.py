import json
import logging
from pathlib import Path
from typing import Any

from protoforge.models.device import DataType, DeviceConfig, GeneratorType, PointConfig

logger = logging.getLogger(__name__)


def import_edgelite_config(config_data: dict[str, Any] | str) -> list[DeviceConfig]:
    if isinstance(config_data, str):
        try:
            config_data = json.loads(config_data)
        except json.JSONDecodeError as e:  # FIXED: JSON解析无异常保护
            raise ValueError(f"Invalid JSON in EdgeLite config: {e}") from e

    if not isinstance(config_data, dict):
        raise ValueError(f"EdgeLite config must be a dict, got {type(config_data).__name__}")

    devices = []
    device_list = config_data.get("devices", [])
    if not device_list and "device_id" in config_data:
        device_list = [config_data]

    for dev in device_list:
        if not isinstance(dev, dict):  # FIXED: device_list元素无类型校验
            logger.warning("Skipping non-dict device entry in EdgeLite config: %s", type(dev).__name__)
            continue
        protocol = dev.get("protocol", "modbus_tcp")
        points = []
        for pt in dev.get("points", []):
            if not isinstance(pt, dict):  # FIXED: points元素无类型校验
                logger.warning("Skipping non-dict point entry: %s", type(pt).__name__)
                continue
            try:
                data_type = DataType(pt.get("data_type", "float32"))
            except ValueError:
                data_type = DataType.FLOAT32
            try:
                gen_type = GeneratorType(pt.get("generator_type", "random"))
            except ValueError:
                gen_type = GeneratorType.RANDOM
            point = PointConfig(
                name=pt.get("name", ""),
                address=str(pt.get("address", "0")),
                data_type=data_type,
                unit=pt.get("unit", ""),
                description=pt.get("description", ""),
                access=pt.get("access", "rw"),
                generator_type=gen_type,
                min_value=pt.get("min_value"),
                max_value=pt.get("max_value"),
                fixed_value=pt.get("fixed_value"),
                generator_config=pt.get("generator_config", {}),
            )
            points.append(point)

        device = DeviceConfig(
            id=dev.get("id", dev.get("device_id", "")),
            name=dev.get("name", dev.get("device_name", "")),
            protocol=protocol,
            template_id=dev.get("template_id"),
            points=points,
            protocol_config=dev.get("protocol_config", {}),
        )
        devices.append(device)

    return devices


def import_edgelite_file(file_path: str) -> list[DeviceConfig]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError) as e:  # FIXED: 文件IO无异常保护
        raise ValueError(f"Failed to read config file '{file_path}': {e}") from e
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:  # FIXED: JSON解析无异常保护
        raise ValueError(f"Invalid JSON in file '{file_path}': {e}") from e
    return import_edgelite_config(data)


def import_pygbsentry_config(config_data: dict[str, Any] | str) -> list[DeviceConfig]:
    if isinstance(config_data, str):
        try:
            config_data = json.loads(config_data)
        except json.JSONDecodeError as e:  # FIXED: JSON解析无异常保护
            raise ValueError(f"Invalid JSON in PyGBSentry config: {e}") from e

    if not isinstance(config_data, dict):
        raise ValueError(f"PyGBSentry config must be a dict, got {type(config_data).__name__}")

    devices = []
    sip_servers = config_data.get("sip_servers", [])
    cameras = config_data.get("cameras", config_data.get("devices", []))

    for cam in cameras:
        if not isinstance(cam, dict):  # FIXED: cameras元素无类型校验
            logger.warning("Skipping non-dict camera entry in PyGBSentry config: %s", type(cam).__name__)
            continue
        device_id = cam.get("device_id", cam.get("id", ""))
        device_name = cam.get("name", cam.get("device_name", f"Camera-{device_id}"))
        sip_server = cam.get("sip_server", sip_servers[0] if sip_servers else "127.0.0.1")
        sip_port = cam.get("sip_port", 5060)

        points = [
            PointConfig(name="online", address="status", data_type=DataType.BOOL,
                        generator_type=GeneratorType.FIXED, fixed_value=True, access="r"),
            PointConfig(name="recording", address="recording", data_type=DataType.BOOL,
                        generator_type=GeneratorType.FIXED, fixed_value=False, access="rw"),
            PointConfig(name="resolution", address="resolution", data_type=DataType.STRING,
                        generator_type=GeneratorType.FIXED, fixed_value="1920x1080", access="r"),
        ]

        device = DeviceConfig(
            id=device_id,
            name=device_name,
            protocol="gb28181",
            points=points,
            protocol_config={
                "device_host": sip_server,
                "device_port": sip_port,
                "username": cam.get("username", ""),
                "password": cam.get("password", ""),
            },
        )
        devices.append(device)

    return devices
