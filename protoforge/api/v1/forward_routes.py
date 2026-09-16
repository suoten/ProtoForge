"""Data forwarding target management API routes."""

import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from protoforge.api.v1._helpers import _get_log_bus
from protoforge.api.v1.auth import require_operator, require_viewer

router = APIRouter()
logger = logging.getLogger(__name__)

_forward_engine = None
_forward_engine_lock = threading.Lock()


def _get_forward_engine():
    global _forward_engine
    if _forward_engine is None:
        with _forward_engine_lock:
            if _forward_engine is None:
                from protoforge.integrations.forward import ForwardEngine
                _forward_engine = ForwardEngine(_get_log_bus())
    return _forward_engine


@router.get("/forward/targets")
async def list_forward_targets(_user: dict[str, Any] = Depends(require_viewer)):
    try:
        engine = _get_forward_engine()
        return {"targets": engine.list_targets()}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to list forward targets: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list forward targets: {e}") from e


@router.post("/forward/targets")
async def add_forward_target(config: dict[str, Any], _user: dict[str, Any] = Depends(require_operator)):
    try:
        from protoforge.integrations.forward import create_target

        engine = _get_forward_engine()
        name = config.get("name", f"target-{int(time.time())}")
        if "host" in config and "url" not in config:
            host = config.get("host", "localhost")
            port = config.get("port", 8086)
            if not isinstance(port, int) or port < 1 or port > 65535:
                raise HTTPException(status_code=400, detail="port must be an integer between 1 and 65535")
            protocol = config.get("protocol", "http")
            if protocol in ("influxdb",):
                config["url"] = f"http://{host}:{port}"
                config.setdefault("type", "influxdb")
            else:
                config["url"] = f"http://{host}:{port}"
                config.setdefault("type", "http")
        target = create_target(config)
        engine.add_target(name, target)
        return {"status": "ok", "name": name}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to add forward target: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to add forward target: {e}") from e


@router.delete("/forward/targets/{name}")
async def remove_forward_target(name: str, _user: dict[str, Any] = Depends(require_operator)):
    try:
        engine = _get_forward_engine()
        engine.remove_target(name)
        return {"status": "ok"}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Forward target '{name}' not found") from None
    except Exception as e:
        logger.exception("Failed to remove forward target: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to remove forward target: {e}") from e


@router.post("/forward/start")
async def start_forward(_user: dict[str, Any] = Depends(require_operator)):
    engine = _get_forward_engine()
    try:
        await engine.start()
        return {"status": "ok"}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to start data forwarding: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to start data forwarding: {str(e)}") from e


@router.post("/forward/stop")
async def stop_forward(_user: dict[str, Any] = Depends(require_operator)):
    engine = _get_forward_engine()
    try:
        await engine.stop()
        return {"status": "ok"}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to stop data forwarding: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to stop data forwarding: {str(e)}") from e


@router.get("/forward/stats")
async def forward_stats(_user: dict[str, Any] = Depends(require_viewer)):
    try:
        engine = _get_forward_engine()
        return engine.get_stats()
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to get forward stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get forward stats: {e}") from e


# ---------------------------------------------------------------------------
# North-bound platform presets (ThingsBoard / Aliyun IoT / EMQX)
# ---------------------------------------------------------------------------

_PLATFORM_PRESETS: list[dict[str, Any]] = [
    {
        "id": "thingsboard",
        "name": "ThingsBoard",
        "description": "ThingsBoard IoT 平台 - HTTP API 透传",
        "type": "http",
        "fields": [
            {"key": "host", "label": "ThingsBoard 地址", "placeholder": "demo.thingsboard.io", "required": True},
            {"key": "port", "label": "端口", "placeholder": "8080", "required": True, "default": "8080"},
            {"key": "access_token", "label": "设备 Access Token", "placeholder": "your-device-access-token", "required": True},
        ],
        "template": {
            "type": "http",
            "url": "http://{host}:{port}/api/v1/{access_token}/telemetry",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "data_format": "thingsboard",
        },
    },
    {
        "id": "aliyun_iot",
        "name": "阿里云IoT",
        "description": "阿里云物联网平台 - MQTT 主题透传",
        "type": "http",
        "fields": [
            {"key": "host", "label": "API 网关地址", "placeholder": "iot.cn-shanghai.aliyuncs.com", "required": True},
            {"key": "port", "label": "端口", "placeholder": "443", "required": True, "default": "443"},
            {"key": "product_key", "label": "Product Key", "placeholder": "your-product-key", "required": True},
            {"key": "device_name", "label": "Device Name", "placeholder": "your-device-name", "required": True},
            {"key": "device_secret", "label": "Device Secret", "placeholder": "your-device-secret", "required": True},
        ],
        "template": {
            "type": "http",
            "url": "https://{host}:{port}/topic/sys/{product_key}/{device_name}/thing/event/property/post",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "data_format": "aliyun_iot",
        },
    },
    {
        "id": "emqx",
        "name": "EMQX",
        "description": "EMQX MQTT Broker - HTTP API 推送",
        "type": "http",
        "fields": [
            {"key": "host", "label": "EMQX API 地址", "placeholder": "localhost", "required": True},
            {"key": "port", "label": "API 端口", "placeholder": "8081", "required": True, "default": "8081"},
            {"key": "api_key", "label": "API Key", "placeholder": "your-api-key", "required": True},
            {"key": "api_secret", "label": "API Secret", "placeholder": "your-api-secret", "required": True},
            {"key": "topic", "label": "推送主题", "placeholder": "protoforge/data", "required": True, "default": "protoforge/data"},
        ],
        "template": {
            "type": "http",
            "url": "http://{host}:{port}/api/v5/publish",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "data_format": "emqx",
        },
    },
    {
        "id": "influxdb_cloud",
        "name": "InfluxDB Cloud",
        "description": "InfluxDB Cloud 时序数据库",
        "type": "influxdb",
        "fields": [
            {"key": "host", "label": "InfluxDB 地址", "placeholder": "localhost", "required": True},
            {"key": "port", "label": "端口", "placeholder": "8086", "required": True, "default": "8086"},
            {"key": "database", "label": "数据库/Bucket", "placeholder": "protoforge", "required": True},
        ],
        "template": {
            "type": "influxdb",
            "host": "{host}",
            "port": "{port}",
            "database": "{database}",
        },
    },
    {
        "id": "custom_webhook",
        "name": "自定义 Webhook",
        "description": "自定义 HTTP Webhook 推送",
        "type": "http",
        "fields": [
            {"key": "url", "label": "Webhook URL", "placeholder": "https://your-server.com/api/data", "required": True},
            {"key": "headers", "label": "请求头 (JSON)", "placeholder": '{"Authorization": "Bearer xxx"}', "required": False},
        ],
        "template": {
            "type": "http",
            "url": "{url}",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "data_format": "generic",
        },
    },
]


@router.get("/forward/presets")
async def list_forward_presets(_user: dict[str, Any] = Depends(require_viewer)):
    """List available north-bound platform preset templates."""
    return {"presets": _PLATFORM_PRESETS}


@router.post("/forward/presets/{preset_id}/apply")
async def apply_forward_preset(preset_id: str, params: dict[str, Any] = Body(default={}),
                               _user: dict[str, Any] = Depends(require_operator)):
    """Apply a platform preset with user-provided parameters."""
    from fastapi import Body as _Body

    preset = None
    for p in _PLATFORM_PRESETS:
        if p["id"] == preset_id:
            preset = p
            break
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset not found: {preset_id}")

    template = preset["template"]
    # Replace placeholders in template with actual values
    resolved = {}
    for key, val in template.items():
        if isinstance(val, str):
            try:
                resolved[key] = val.format(**params)
            except KeyError as e:
                raise HTTPException(status_code=400, detail=f"Missing required parameter: {e.args[0]}") from e
        elif isinstance(val, dict):
            resolved[key] = val
        else:
            resolved[key] = val

    # For InfluxDB presets, construct URL
    if preset["type"] == "influxdb":
        host = params.get("host", "localhost")
        port = params.get("port", 8086)
        resolved["url"] = f"http://{host}:{port}"
        resolved.setdefault("type", "influxdb")

    # Set target name
    target_name = params.get("name") or f"{preset['id']}-{int(time.time())}"
    resolved["name"] = target_name

    try:
        from protoforge.integrations.forward import create_target

        engine = _get_forward_engine()
        target = create_target(resolved)
        engine.add_target(target_name, target)
        return {"status": "ok", "name": target_name, "preset_id": preset_id}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to apply forward preset: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to apply preset: {e}") from e

