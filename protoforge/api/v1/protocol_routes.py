import logging

from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Optional

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_engine, _get_log_bus

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/protocols")
async def list_protocols(_user: dict = Depends(require_viewer)):
    engine = _get_engine()
    protocols = engine.get_protocols()
    from protoforge.core.defaults import get_protocol_defaults, PROTOCOL_DEFAULTS
    result = []
    for p in protocols:
        entry = dict(p)
        defaults = get_protocol_defaults(entry.get("name", ""))
        entry["description"] = PROTOCOL_DEFAULTS.get(entry.get("name", ""), {}).get("description", "")
        entry["default_port"] = defaults.get("port", 0)
        result.append(entry)
    return {"protocols": result}


@router.get("/protocols/info")
async def get_protocols_info(_user: dict = Depends(require_viewer)):
    from protoforge.core.defaults import get_all_protocol_info
    return {"protocols": get_all_protocol_info()}


@router.get("/protocols/{protocol_name}/config")
async def get_protocol_config(protocol_name: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    for p in engine.get_protocols():
        if p.get("name") == protocol_name:
            return p.get("config_schema", {})

    raise HTTPException(status_code=404, detail=f"Protocol not found: {protocol_name}")


@router.get("/protocols/{protocol_name}/device-config")
async def get_protocol_device_config(protocol_name: str, _user: dict = Depends(require_viewer)):
    from protoforge.core.defaults import PROTOCOL_DEVICE_CONFIG
    from protoforge.core.edgelite import EDGELITE_PUSH_FIELDS
    config = list(PROTOCOL_DEVICE_CONFIG.get(protocol_name, []))
    if protocol_name != "gb28181":
        config.extend(EDGELITE_PUSH_FIELDS)
    return {"protocol": protocol_name, "fields": config}


@router.post("/protocols/start-all")
async def start_all_protocols(_user: dict = Depends(require_operator)):
    engine = _get_engine()
    log_bus = _get_log_bus()
    from protoforge.core.defaults import get_protocol_defaults, get_friendly_error
    results = {"started": [], "failed": [], "skipped": [], "port_warnings": []}
    for p in engine.get_protocols():
        name = p.get("name", "")
        if p.get("status") == "running":
            results["skipped"].append(name)
            continue
        config = get_protocol_defaults(name)
        original_port = config.get("port")
        try:
            await engine.start_protocol(name, config)
            actual_port = config.get("port", original_port)
            port_changed = config.pop("_port_changed", False)
            config_original_port = config.pop("_original_port", None)
            if not port_changed and original_port and actual_port != original_port:
                port_changed = True
                config_original_port = original_port
            log_bus.emit(name, "system", "", "protocol_start", f"Protocol {name} started on port {actual_port}", config)
            results["started"].append(name)
            if port_changed:
                results["port_warnings"].append({
                    "protocol": name,
                    "original_port": config_original_port or original_port,
                    "actual_port": actual_port,
                    "message": f"Port {config_original_port or original_port} is in use, automatically switched to {actual_port}",  # FIXED: Chinese→English
                })
        except Exception as e:
            friendly = get_friendly_error(str(e))
            results["failed"].append({"protocol": name, "error": friendly})
            logger.warning("Failed to start protocol %s in start-all: %s", name, e)
    return results


@router.post("/protocols/stop-all")
async def stop_all_protocols(_user: dict = Depends(require_operator)):
    engine = _get_engine()
    log_bus = _get_log_bus()
    results = {"stopped": [], "failed": [], "skipped": []}
    for p in engine.get_protocols():
        name = p.get("name", "")
        if p.get("status") != "running":
            results["skipped"].append(name)
            continue
        try:
            await engine.stop_protocol(name)
            log_bus.emit(name, "system", "", "protocol_stop", f"Protocol {name} stopped")
            results["stopped"].append(name)
        except Exception as e:
            results["failed"].append({"protocol": name, "error": str(e)})
            logger.warning("Failed to stop protocol %s in stop-all: %s", name, e)
    return results


@router.post("/protocols/{protocol_name}/start")
async def start_protocol(protocol_name: str, config: Optional[dict[str, Any]] = None, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    log_bus = _get_log_bus()
    from protoforge.core.defaults import get_protocol_defaults, get_friendly_error
    if config is None:
        config = get_protocol_defaults(protocol_name)
    original_port = config.get("port")

    try:
        await engine.start_protocol(protocol_name, config)
        actual_port = config.get("port", original_port)
        port_changed = config.pop("_port_changed", False)
        config_original_port = config.pop("_original_port", None)
        if not port_changed and original_port and actual_port != original_port:
            port_changed = True
            config_original_port = original_port
        log_bus.emit(protocol_name, "system", "", "protocol_start", f"Protocol {protocol_name} started on port {actual_port}", config)
        result = {"status": "ok"}

        if port_changed:
            result["port_changed"] = True
            result["original_port"] = config_original_port or original_port
            result["actual_port"] = actual_port
            result["message"] = f"Port {config_original_port or original_port} is in use, automatically switched to {actual_port}"  # FIXED: Chinese→English

        return result

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        error_detail = str(e)
        friendly = get_friendly_error(error_detail)
        raise HTTPException(status_code=503, detail=friendly)
    except Exception as e:
        logger.error("Failed to start protocol %s: %s", protocol_name, e)
        raise HTTPException(status_code=500, detail=get_friendly_error(str(e)))


@router.post("/protocols/{protocol_name}/stop")
async def stop_protocol(protocol_name: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    log_bus = _get_log_bus()

    try:
        await engine.stop_protocol(protocol_name)
        log_bus.emit(protocol_name, "system", "", "protocol_stop", f"Protocol {protocol_name} stopped")
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        from protoforge.core.defaults import get_friendly_error
        raise HTTPException(status_code=500, detail=get_friendly_error(str(e)))
