import asyncio
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from protoforge.models.device import DeviceConfig, DeviceInfo, PointValue
from protoforge.models.scenario import ScenarioConfig, ScenarioInfo
from protoforge.models.template import TemplateDetail, TemplateInfo

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)

from protoforge.api.v1.integration import router as _integration_router
router.include_router(_integration_router)


def _get_engine():
    from protoforge.main import get_engine
    return get_engine()


def _get_template_manager():
    from protoforge.main import get_template_manager
    return get_template_manager()


def _get_log_bus():
    from protoforge.main import get_log_bus
    return get_log_bus()


def _get_database():
    from protoforge.main import get_database
    return get_database()


@router.get("/protocols")
async def list_protocols():
    engine = _get_engine()
    protocols = engine.get_protocols()
    from protoforge.core.defaults import get_protocol_defaults, PROTOCOL_DEFAULTS
    for p in protocols:
        defaults = get_protocol_defaults(p.get("name", ""))
        p["description"] = PROTOCOL_DEFAULTS.get(p.get("name", ""), {}).get("description", "")
        p["default_port"] = defaults.get("port", 0)
    return protocols


@router.get("/protocols/info")
async def get_protocols_info():
    from protoforge.core.defaults import get_all_protocol_info
    return get_all_protocol_info()


@router.get("/protocols/{protocol_name}/config")
async def get_protocol_config(protocol_name: str):
    engine = _get_engine()
    for p in engine.get_protocols():
        if p["name"] == protocol_name:
            return p["config_schema"]
    raise HTTPException(status_code=404, detail=f"Protocol not found: {protocol_name}")


@router.get("/devices/{device_id}/connection-guide")
async def get_device_connection_guide(device_id: str):
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    from protoforge.core.defaults import PROTOCOL_USAGE, get_protocol_defaults
    usage = PROTOCOL_USAGE.get(device.protocol, {})
    defaults = get_protocol_defaults(device.protocol)
    config = {**defaults, **(device.protocol_config or {})}
    if usage.get("code_example"):
        try:
            usage["code_example"] = usage["code_example"].format(**config)
        except KeyError:
            pass
    return {
        "protocol": device.protocol,
        "device_id": device_id,
        "device_name": device.name,
        "mode": usage.get("mode", "server"),
        "mode_label": usage.get("mode_label", ""),
        "mode_desc": usage.get("mode_desc", ""),
        "connect_hint": usage.get("connect_hint", ""),
        "code_example": usage.get("code_example", ""),
        "connection_info": config,
    }


@router.get("/protocols/{protocol_name}/device-config")
async def get_protocol_device_config(protocol_name: str):
    from protoforge.core.defaults import PROTOCOL_DEVICE_CONFIG
    from protoforge.core.edgelite import EDGELITE_PUSH_FIELDS
    config = list(PROTOCOL_DEVICE_CONFIG.get(protocol_name, []))
    if protocol_name not in ("gb28181", "video"):
        config.extend(EDGELITE_PUSH_FIELDS)
    return {"protocol": protocol_name, "fields": config}


@router.post("/protocols/{protocol_name}/start")
async def start_protocol(protocol_name: str, config: dict[str, Any] = None):
    engine = _get_engine()
    log_bus = _get_log_bus()
    from protoforge.core.defaults import get_protocol_defaults, get_friendly_error
    if not config:
        config = get_protocol_defaults(protocol_name)
    original_port = config.get("port") if config else None
    try:
        await engine.start_protocol(protocol_name, config)
        actual_port = config.get("port", original_port) if config else original_port
        port_changed = original_port and actual_port != original_port
        log_bus.emit(protocol_name, "system", "", "protocol_start",
                     f"Protocol {protocol_name} started on port {actual_port}", config or {})
        result = {"status": "ok"}
        if port_changed:
            result["port_changed"] = True
            result["original_port"] = original_port
            result["actual_port"] = actual_port
            result["message"] = f"端口 {original_port} 被占用，已自动切换到 {actual_port}"
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=get_friendly_error(str(e)))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=get_friendly_error(str(e)))
    except Exception as e:
        raise HTTPException(status_code=500, detail=get_friendly_error(str(e)))


@router.post("/protocols/{protocol_name}/stop")
async def stop_protocol(protocol_name: str):
    engine = _get_engine()
    log_bus = _get_log_bus()
    try:
        await engine.stop_protocol(protocol_name)
        log_bus.emit(protocol_name, "system", "", "protocol_stop",
                     f"Protocol {protocol_name} stopped")
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices", response_model=list[DeviceInfo])
async def list_devices(protocol: Optional[str] = None):
    engine = _get_engine()
    return engine.list_devices(protocol=protocol)


@router.post("/devices", response_model=DeviceInfo)
async def create_device(config: DeviceConfig):
    engine = _get_engine()
    db = _get_database()
    log_bus = _get_log_bus()
    try:
        result = await engine.create_device(config)
        try:
            await db.save_device(config)
        except Exception as db_err:
            logger.warning("Failed to save device to DB: %s", db_err)
        log_bus.emit(config.protocol, "system", config.id, "device_created",
                     f"Device {config.name} created", {"device_id": config.id})
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devices/quick-create")
async def quick_create_device(params: dict[str, Any]):
    template_id = params.get("template_id", "")
    device_name = params.get("name", "")
    device_id = params.get("id") or device_name.lower().replace(" ", "-").replace("（", "(").replace("）", ")") or str(uuid.uuid4())[:8]
    protocol_config = params.get("protocol_config", {})
    if not template_id or not device_name:
        raise HTTPException(status_code=400, detail="template_id 和 name 为必填项")
    tm = _get_template_manager()
    template = tm.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    merged_config = {**(template.protocol_config or {}), **protocol_config}
    config = DeviceConfig(
        id=device_id, name=device_name,
        protocol=template.protocol, template_id=template_id,
        points=template.points or [], protocol_config=merged_config,
    )
    engine = _get_engine()
    db = _get_database()
    log_bus = _get_log_bus()
    try:
        result = await engine.create_device(config)
        try:
            await db.save_device(config)
        except Exception as db_err:
            logger.warning("Failed to save device to DB: %s", db_err)
        try:
            await engine.start_device(device_id)
        except Exception as start_err:
            logger.warning("quick-create: device %s created but start failed: %s", device_id, start_err)
        log_bus.emit(config.protocol, "system", config.id, "device_created",
                     f"Device {device_name} created via quick-create", {"device_id": config.id})
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/devices/batch")
async def batch_create_devices(configs: list[DeviceConfig]):
    engine = _get_engine()
    results = []
    for config in configs:
        try:
            info = await engine.create_device(config)
            results.append(info.model_dump() if hasattr(info, 'model_dump') else {"id": config.id, "name": config.name})
        except Exception as e:
            results.append({"id": config.id, "error": str(e)})
    return {"status": "ok", "created": len(results), "devices": results}


@router.delete("/devices/batch")
async def batch_delete_devices(device_ids: list[str]):
    engine = _get_engine()
    db = _get_database()
    deleted = 0
    errors = []
    for device_id in device_ids:
        try:
            await engine.remove_device(device_id)
            await db.delete_device(device_id)
            deleted += 1
        except ValueError as e:
            errors.append({"id": device_id, "error": str(e)})
    return {"status": "ok", "deleted": deleted, "errors": errors}


@router.post("/devices/batch/start")
async def batch_start_devices(device_ids: list[str]):
    engine = _get_engine()
    started = 0
    errors = []
    for device_id in device_ids:
        try:
            await engine.start_device(device_id)
            started += 1
        except Exception as e:
            errors.append({"id": device_id, "error": str(e)})
    return {"status": "ok", "started": started, "errors": errors}


@router.post("/devices/batch/stop")
async def batch_stop_devices(device_ids: list[str]):
    engine = _get_engine()
    stopped = 0
    errors = []
    for device_id in device_ids:
        try:
            await engine.stop_device(device_id)
            stopped += 1
        except Exception as e:
            errors.append({"id": device_id, "error": str(e)})
    return {"status": "ok", "stopped": stopped, "errors": errors}


@router.get("/devices/{device_id}", response_model=DeviceInfo)
async def get_device(device_id: str):
    engine = _get_engine()
    try:
        return engine.get_device(device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str):
    engine = _get_engine()
    db = _get_database()
    log_bus = _get_log_bus()
    try:
        info = engine.get_device(device_id)
        await engine.remove_device(device_id)
        try:
            await db.delete_device(device_id)
        except Exception as db_err:
            logger.warning("Failed to delete device from DB: %s", db_err)
        log_bus.emit(info.protocol, "system", device_id, "device_removed",
                     f"Device {info.name} removed")
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/devices/{device_id}", response_model=DeviceInfo)
async def update_device(device_id: str, config: DeviceConfig):
    engine = _get_engine()
    db = _get_database()
    log_bus = _get_log_bus()
    try:
        result = await engine.update_device(device_id, config)
        try:
            await db.save_device(config)
        except Exception as db_err:
            logger.warning("Failed to update device in DB: %s", db_err)
        log_bus.emit(config.protocol, "system", device_id, "device_updated",
                     f"Device {config.name} updated")
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{device_id}/points", response_model=list[PointValue])
async def get_device_points(device_id: str):
    engine = _get_engine()
    try:
        return await engine.read_device_points(device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/devices/{device_id}/start")
async def start_device(device_id: str):
    engine = _get_engine()
    try:
        await engine.start_device(device_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/devices/{device_id}/stop")
async def stop_device(device_id: str):
    engine = _get_engine()
    try:
        await engine.stop_device(device_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/devices/{device_id}/points/{point_name}")
async def write_device_point(device_id: str, point_name: str, value: Any = None):
    engine = _get_engine()
    log_bus = _get_log_bus()
    try:
        success = await engine.write_device_point(device_id, point_name, value)
        if not success:
            raise HTTPException(status_code=400, detail="Write failed")
        log_bus.emit("", "write", device_id, "point_write",
                     f"Write {point_name}={value}", {"point": point_name, "value": value})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/scenarios", response_model=list[ScenarioInfo])
async def list_scenarios():
    engine = _get_engine()
    return engine.list_scenarios()


@router.post("/scenarios", response_model=ScenarioInfo)
async def create_scenario(config: ScenarioConfig):
    engine = _get_engine()
    db = _get_database()
    try:
        result = engine.create_scenario(config)
        await db.save_scenario(config)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/scenarios/{scenario_id}", response_model=ScenarioInfo)
async def get_scenario(scenario_id: str):
    engine = _get_engine()
    try:
        return engine.get_scenario(scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/scenarios/{scenario_id}/start")
async def start_scenario(scenario_id: str):
    engine = _get_engine()
    log_bus = _get_log_bus()
    try:
        await engine.start_scenario(scenario_id)
        log_bus.emit("", "system", "", "scenario_start",
                     f"Scenario {scenario_id} started", {"scenario_id": scenario_id})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/scenarios/{scenario_id}/stop")
async def stop_scenario(scenario_id: str):
    engine = _get_engine()
    log_bus = _get_log_bus()
    try:
        await engine.stop_scenario(scenario_id)
        log_bus.emit("", "system", "", "scenario_stop",
                     f"Scenario {scenario_id} stopped", {"scenario_id": scenario_id})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/scenarios/{scenario_id}", response_model=ScenarioInfo)
async def update_scenario(scenario_id: str, config: ScenarioConfig):
    engine = _get_engine()
    try:
        return engine.update_scenario(scenario_id, config)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str):
    engine = _get_engine()
    db = _get_database()
    try:
        engine.remove_scenario(scenario_id)
        await db.delete_scenario(scenario_id)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/scenarios/{scenario_id}/export")
async def export_scenario(scenario_id: str):
    engine = _get_engine()
    db = _get_database()
    try:
        config = await db.load_scenario(scenario_id)
        if not config:
            config = engine._scenarios.get(scenario_id)
        if not config:
            raise HTTPException(status_code=404, detail="Scenario not found")
        return config.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/scenarios/import")
async def import_scenario(config: ScenarioConfig):
    engine = _get_engine()
    db = _get_database()
    try:
        await db.save_scenario(config)
        return engine.create_scenario(config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/templates", response_model=list[TemplateInfo])
async def list_templates(protocol: Optional[str] = None):
    tm = _get_template_manager()
    return tm.list_templates(protocol=protocol)


@router.get("/templates/search")
async def search_templates(q: str = "", protocol: Optional[str] = None, tag: Optional[str] = None):
    tm = _get_template_manager()
    templates = tm.list_templates(protocol=protocol)
    if q:
        q_lower = q.lower()
        templates = [t for t in templates if
                     q_lower in t.name.lower() or
                     q_lower in (t.description or "").lower() or
                     any(q_lower in tag_item.lower() for tag_item in (t.tags or []))]
    if tag:
        templates = [t for t in templates if tag in (t.tags or [])]
    return templates


@router.get("/templates/tags")
async def list_template_tags():
    tm = _get_template_manager()
    templates = tm.list_templates()
    tags = set()
    for t in templates:
        for tag in (t.tags or []):
            tags.add(tag)
    return sorted(list(tags))


@router.get("/templates/{template_id}", response_model=TemplateDetail)
async def get_template(template_id: str):
    tm = _get_template_manager()
    try:
        return tm.get_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/templates", response_model=TemplateDetail)
async def create_template(template: TemplateDetail):
    tm = _get_template_manager()
    db = _get_database()
    tm.add_template(template)
    await db.save_template(template)
    return template


@router.post("/templates/{template_id}/instantiate", response_model=DeviceConfig)
async def instantiate_template(
    template_id: str,
    device_id: str,
    device_name: str,
    protocol_config: Optional[dict[str, Any]] = None,
):
    tm = _get_template_manager()
    try:
        return tm.create_device_from_template(template_id, device_id, device_name, protocol_config)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/logs")
async def get_logs(
    count: int = 100,
    protocol: Optional[str] = None,
    device_id: Optional[str] = None,
    direction: Optional[str] = None,
    message_type: Optional[str] = None,
):
    log_bus = _get_log_bus()
    entries = log_bus.get_recent(count=count * 5, protocol=protocol, device_id=device_id)
    if direction:
        entries = [e for e in entries if e.get("direction") == direction]
    if message_type:
        entries = [e for e in entries if message_type in e.get("message_type", "")]
    return entries[-count:]


@router.delete("/logs")
async def clear_logs():
    log_bus = _get_log_bus()
    log_bus.clear()
    return {"status": "ok", "message": "日志已清空"}


@router.websocket("/ws/devices")
async def ws_devices(websocket: WebSocket):
    await websocket.accept()
    engine = _get_engine()
    try:
        while True:
            devices = engine.list_devices()
            data = []
            for d in devices:
                try:
                    data.append(d.model_dump())
                except Exception:
                    data.append({"id": d.id, "name": d.name, "protocol": d.protocol, "status": d.status.value})
            await websocket.send_json({"type": "devices", "data": data})
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        logger.debug("WebSocket /ws/devices disconnected")
    except Exception as e:
        logger.warning("WebSocket /ws/devices error: %s", e)


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    log_bus = _get_log_bus()
    queue = log_bus.subscribe()
    try:
        while True:
            entry = await queue.get()
            await websocket.send_json({
                "type": "log",
                "data": {
                    "timestamp": entry.timestamp,
                    "protocol": entry.protocol,
                    "direction": entry.direction,
                    "device_id": entry.device_id,
                    "message_type": entry.message_type,
                    "summary": entry.summary,
                    "detail": entry.detail,
                },
            })
    except WebSocketDisconnect:
        logger.debug("WebSocket /ws/logs disconnected")
    except Exception as e:
        logger.warning("WebSocket /ws/logs error: %s", e)
    finally:
        log_bus.unsubscribe(queue)


@router.post("/integration/edgelite")
async def import_edgelite(config: dict[str, Any]):
    from protoforge.core.integration import import_edgelite_config
    engine = _get_engine()
    try:
        devices = import_edgelite_config(config)
        results = []
        for dev in devices:
            info = await engine.create_device(dev)
            results.append(info.model_dump())
        return {"status": "ok", "imported": len(results), "devices": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/integration/edgelite/push/{device_id}")
async def push_device_to_edgelite(device_id: str):
    from protoforge.core.edgelite import push_device_to_edgelite as _push
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        result = await _push(device)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"EdgeLite push failed: {e}")


@router.post("/integration/edgelite/test")
async def test_edgelite_connection(config: dict[str, Any] = None):
    from protoforge.core.edgelite import test_edgelite_connection as _test
    if not config:
        config = {}
    url = config.get("url", "")
    username = config.get("username", "admin")
    password = config.get("password", "")
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    return await _test(url, username, password)


@router.get("/integration/edgelite/status/{device_id}")
async def get_edgelite_device_status(device_id: str):
    from protoforge.core.edgelite import get_edgelite_device_status as _status
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        return await _status(device)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"EdgeLite status check failed: {e}")


@router.get("/integration/edgelite/points/{device_id}")
async def read_edgelite_device_points(device_id: str):
    from protoforge.core.edgelite import read_edgelite_device_points as _read
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        return await _read(device)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"EdgeLite read points failed: {e}")


@router.get("/integration/edgelite/pipeline/{device_id}")
async def verify_edgelite_pipeline(device_id: str):
    from protoforge.core.edgelite import verify_edgelite_pipeline as _verify
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        result = await _verify(device)
        if result.get("ok") and "collect" in result.get("steps", {}):
            collect_step = result["steps"]["collect"]
            if collect_step.get("ok") and collect_step.get("has_real_data"):
                try:
                    local_points = await engine.read_device_points(device_id)
                    local_map = {p.name: p.value for p in local_points}
                    edgelite_data = collect_step.get("data", {})
                    comparison = []
                    for name, local_val in local_map.items():
                        el_val = edgelite_data.get(name)
                        comparison.append({
                            "point": name,
                            "protoforge_value": local_val,
                            "edgelite_value": el_val,
                            "match": str(local_val) == str(el_val) if el_val is not None else None,
                        })
                    result["data_comparison"] = comparison
                except Exception:
                    pass
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"EdgeLite pipeline verification failed: {e}")


@router.delete("/integration/edgelite/push/{device_id}")
async def remove_device_from_edgelite(device_id: str):
    from protoforge.core.edgelite import remove_device_from_edgelite as _remove
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        return await _remove(device)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"EdgeLite remove device failed: {e}")


@router.post("/integration/pygbsentry")
async def import_pygbsentry(config: dict[str, Any]):
    from protoforge.core.integration import import_pygbsentry_config
    engine = _get_engine()
    try:
        devices = import_pygbsentry_config(config)
        results = []
        for dev in devices:
            info = await engine.create_device(dev)
            results.append(info.model_dump())
        return {"status": "ok", "imported": len(results), "devices": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


_test_runner = None
_internal_client = None


def _get_test_runner():
    global _test_runner
    if _test_runner is None:
        from protoforge.core.testing import TestRunner
        _test_runner = TestRunner()
        try:
            db = _get_database()
            _test_runner.set_database(db)
        except RuntimeError:
            pass
    return _test_runner


async def _get_internal_client():
    global _internal_client
    if _internal_client is not None:
        return _internal_client
    from httpx import ASGITransport, AsyncClient
    from protoforge.main import app
    transport = ASGITransport(app=app)
    _internal_client = AsyncClient(transport=transport, base_url="http://localhost")
    return _internal_client


@router.post("/tests/cases")
async def create_test_case(case_def: dict[str, Any]):
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    tc = TestCase.from_dict(case_def)
    await runner.save_test_case(tc)
    return tc.to_dict()


@router.get("/tests/cases")
async def list_test_cases(tag: Optional[str] = None):
    runner = _get_test_runner()
    cases = runner.list_test_cases(tag=tag)
    return [c.to_dict() for c in cases]


@router.get("/tests/cases/{case_id}")
async def get_test_case(case_id: str):
    runner = _get_test_runner()
    tc = runner.get_test_case(case_id)
    if not tc:
        raise HTTPException(status_code=404, detail="Test case not found")
    return tc.to_dict()


@router.put("/tests/cases/{case_id}")
async def update_test_case(case_id: str, case_def: dict[str, Any]):
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    existing = runner.get_test_case(case_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Test case not found")
    tc = TestCase.from_dict(case_def)
    tc.id = case_id
    await runner.save_test_case(tc)
    return tc.to_dict()


@router.delete("/tests/cases/{case_id}")
async def delete_test_case(case_id: str):
    runner = _get_test_runner()
    if not await runner.delete_test_case(case_id):
        raise HTTPException(status_code=404, detail="Test case not found")
    return {"status": "ok"}


@router.post("/tests/suites")
async def create_test_suite(suite_def: dict[str, Any]):
    import time as _time
    from protoforge.core.testing import TestSuite
    runner = _get_test_runner()
    suite = TestSuite(
        id=suite_def.get("id") or uuid.uuid4().hex[:12],
        name=suite_def.get("name", ""),
        description=suite_def.get("description", ""),
        test_case_ids=suite_def.get("test_case_ids", []),
        tags=suite_def.get("tags", []),
        created_at=_time.time(),
        updated_at=_time.time(),
    )
    await runner.save_test_suite(suite)
    return suite.to_dict()


@router.get("/tests/suites")
async def list_test_suites():
    runner = _get_test_runner()
    suites = runner.list_test_suites()
    return [s.to_dict() for s in suites]


@router.get("/tests/suites/{suite_id}")
async def get_test_suite(suite_id: str):
    runner = _get_test_runner()
    suite = runner.get_test_suite(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Test suite not found")
    return suite.to_dict()


@router.delete("/tests/suites/{suite_id}")
async def delete_test_suite(suite_id: str):
    runner = _get_test_runner()
    if not await runner.delete_test_suite(suite_id):
        raise HTTPException(status_code=404, detail="Test suite not found")
    return {"status": "ok"}


@router.post("/tests/run")
async def run_test(test_cases: list[dict[str, Any]]):
    from protoforge.core.testing import TestCase
    runner = _get_test_runner()
    cases = []
    for tc_def in test_cases:
        tc = TestCase.from_dict(tc_def)
        cases.append(tc)
    api_client = await _get_internal_client()
    report = await runner.run_test_suite("API Test", cases, api_client=api_client)
    return report.to_dict()


@router.post("/tests/run/case/{case_id}")
async def run_test_case_by_id(case_id: str):
    runner = _get_test_runner()
    tc = runner.get_test_case(case_id)
    if not tc:
        raise HTTPException(status_code=404, detail="Test case not found")
    api_client = await _get_internal_client()
    report = await runner.run_test_suite(f"Single: {tc.name}", [tc], api_client=api_client)
    return report.to_dict()


@router.post("/tests/run/suite/{suite_id}")
async def run_test_suite_by_id(suite_id: str):
    runner = _get_test_runner()
    api_client = await _get_internal_client()
    try:
        report = await runner.run_test_suite_by_id(suite_id, api_client=api_client)
        return report.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/tests/reports")
async def list_test_reports():
    runner = _get_test_runner()
    return runner.get_reports()


@router.get("/tests/reports/trend")
async def get_report_trend(count: int = 20):
    runner = _get_test_runner()
    return runner.get_report_trend(count=count)


@router.get("/tests/reports/{report_id}")
async def get_test_report(report_id: str):
    runner = _get_test_runner()
    report = runner.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/tests/reports/{report_id}/html")
async def get_test_report_html(report_id: str):
    from fastapi.responses import HTMLResponse
    runner = _get_test_runner()
    html = runner.get_report_html(report_id)
    if not html:
        raise HTTPException(status_code=404, detail="Report not found")
    return HTMLResponse(content=html)


@router.post("/tests/quick-test")
async def quick_test(scope: str = "all", target_id: Optional[str] = None):
    engine = _get_engine()
    from protoforge.core.testing import TestCase, TestStep, Assertion, AssertionType
    cases = []

    if scope == "all" or scope == "device":
        for dev_id, dev in engine._devices.items():
            if target_id and dev_id != target_id:
                continue
            steps = [
                TestStep(
                    name=f"读取 {dev.name} 测点",
                    action="read_points",
                    params={"device_id": dev_id},
                    assertions=[Assertion(type=AssertionType.LENGTH_GREATER, expected=0, message=f"{dev.name} 应有测点数据")],
                ),
            ]
            writable_points = [p for p in dev.config.points if getattr(p, 'access', 'rw') != "r"]
            if writable_points:
                wp = writable_points[0]
                steps.append(TestStep(
                    name=f"写入 {dev.name}/{wp.name}",
                    action="write_point",
                    params={"device_id": dev_id, "point_name": wp.name, "value": 42.5},
                    assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message=f"写入 {wp.name} 应成功")],
                ))
            cases.append(TestCase(
                id=f"qt-{dev_id}", name=f"设备测试: {dev.name}",
                tags=["quick-test", "device"], steps=steps,
            ))

    if scope == "all" or scope == "scenario":
        for sc_id, sc_config in engine._scenarios.items():
            if target_id and sc_id != target_id:
                continue
            sc_steps = [
                TestStep(name=f"验证场景 {sc_config.name} 状态", action="http_request",
                         params={"method": "GET", "url": f"/api/v1/scenarios/{sc_id}"},
                         assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message="场景应可访问")]),
            ]
            cases.append(TestCase(
                id=f"qt-scene-{sc_id}", name=f"场景测试: {sc_config.name}",
                tags=["quick-test", "scenario"],
                steps=sc_steps,
            ))

    if scope == "all" or scope == "protocol":
        for proto_name, proto_server in engine._protocol_servers.items():
            cases.append(TestCase(
                id=f"qt-proto-{proto_name}", name=f"协议测试: {proto_name}",
                tags=["quick-test", "protocol"],
                steps=[
                    TestStep(name=f"验证协议 {proto_name} 运行中", action="http_request",
                             params={"method": "GET", "url": "/api/v1/protocols"},
                             assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message=f"协议列表应可访问")]),
                ],
            ))

    if not cases:
        cases.append(TestCase(
            id="qt-empty", name="基础连通性测试", tags=["quick-test"],
            steps=[
                TestStep(name="API健康检查", action="http_request",
                         params={"method": "GET", "url": "/api/v1/health"},
                         assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200, message="API应可访问")]),
            ],
        ))

    api_client = await _get_internal_client()
    report = await _get_test_runner().run_test_suite("一键测试", cases, api_client=api_client)
    return report.to_dict()


@router.get("/tests/suggestions")
async def get_test_suggestions():
    engine = _get_engine()
    suggestions = []

    for dev_id, dev in engine._devices.items():
        suggestions.append({
            "type": "device",
            "title": f"测试设备 {dev.name}",
            "description": f"验证 {dev.name} ({dev.protocol}) 的测点读写功能",
            "scope": "device",
            "target_id": dev_id,
            "priority": "high" if dev.status.value == "online" else "medium",
        })

    for sc_id, sc_config in engine._scenarios.items():
        suggestions.append({
            "type": "scenario",
            "title": f"测试场景 {sc_config.name}",
            "description": f"验证场景 {sc_config.name} 的启停和规则触发",
            "scope": "scenario",
            "target_id": sc_id,
            "priority": "medium",
        })

    running_protocols = [name for name, p in engine._protocol_servers.items() if p.status.value == "running"]
    if running_protocols:
        suggestions.append({
            "type": "protocol",
            "title": f"测试 {len(running_protocols)} 个运行中协议",
            "description": "验证所有运行中协议的连通性",
            "scope": "protocol",
            "target_id": None,
            "priority": "low",
        })

    if not suggestions:
        suggestions.append({
            "type": "basic",
            "title": "基础连通性测试",
            "description": "系统暂无设备，先测试API连通性",
            "scope": "all",
            "target_id": None,
            "priority": "high",
        })

    return suggestions


@router.get("/tests/action-types")
async def get_test_action_types():
    return [
        {"value": "create_device", "label": "创建设备", "category": "设备", "params": ["id", "name", "protocol", "points"]},
        {"value": "get_device", "label": "获取设备", "category": "设备", "params": ["device_id"]},
        {"value": "delete_device", "label": "删除设备", "category": "设备", "params": ["device_id"]},
        {"value": "read_points", "label": "读取测点", "category": "设备", "params": ["device_id"]},
        {"value": "write_point", "label": "写入测点", "category": "设备", "params": ["device_id", "point_name", "value"]},
        {"value": "list_devices", "label": "设备列表", "category": "设备", "params": []},
        {"value": "batch_create_devices", "label": "批量创建", "category": "设备", "params": ["devices"]},
        {"value": "batch_delete_devices", "label": "批量删除", "category": "设备", "params": ["device_ids"]},
        {"value": "start_protocol", "label": "启动协议", "category": "协议", "params": ["protocol", "config"]},
        {"value": "stop_protocol", "label": "停止协议", "category": "协议", "params": ["protocol"]},
        {"value": "create_scenario", "label": "创建场景", "category": "场景", "params": ["id", "name", "devices", "rules"]},
        {"value": "start_scenario", "label": "启动场景", "category": "场景", "params": ["scenario_id"]},
        {"value": "stop_scenario", "label": "停止场景", "category": "场景", "params": ["scenario_id"]},
        {"value": "delete_scenario", "label": "删除场景", "category": "场景", "params": ["scenario_id"]},
        {"value": "list_templates", "label": "模板列表", "category": "模板", "params": []},
        {"value": "instantiate_template", "label": "实例化模板", "category": "模板", "params": ["template_id"]},
        {"value": "http_request", "label": "HTTP请求", "category": "通用", "params": ["method", "url", "headers", "body"]},
        {"value": "wait", "label": "等待", "category": "通用", "params": ["seconds"]},
        {"value": "assert_value", "label": "断言值", "category": "通用", "params": []},
    ]


@router.get("/tests/assertion-types")
async def get_test_assertion_types():
    return [
        {"value": "status_code", "label": "请求应成功", "description": "验证HTTP状态码", "simple": True},
        {"value": "not_null", "label": "值不应为空", "description": "验证返回值非空", "simple": True},
        {"value": "length_greater", "label": "列表不应为空", "description": "验证列表长度>0", "simple": True},
        {"value": "equals", "label": "值应等于", "description": "验证值等于期望值", "simple": True},
        {"value": "contains", "label": "应包含", "description": "验证包含指定内容", "simple": True},
        {"value": "greater_than", "label": "值应大于", "description": "验证数值大于阈值", "simple": False},
        {"value": "less_than", "label": "值应小于", "description": "验证数值小于阈值", "simple": False},
        {"value": "not_equals", "label": "值不应等于", "description": "验证值不等于指定值", "simple": False},
        {"value": "not_contains", "label": "不应包含", "description": "验证不包含指定内容", "simple": False},
        {"value": "regex_match", "label": "正则匹配", "description": "验证匹配正则表达式", "simple": False},
        {"value": "json_path", "label": "JSON路径取值", "description": "从JSON中提取值验证", "simple": False},
        {"value": "type_check", "label": "类型检查", "description": "验证值的类型", "simple": False},
        {"value": "length_equals", "label": "长度等于", "description": "验证列表长度等于指定值", "simple": False},
        {"value": "length_less", "label": "长度小于", "description": "验证列表长度小于指定值", "simple": False},
    ]


@router.get("/scenarios/{scenario_id}/snapshot")
async def get_scenario_snapshot(scenario_id: str):
    engine = _get_engine()
    config = engine._scenarios.get(scenario_id)
    if not config:
        raise HTTPException(status_code=404, detail="Scenario not found")
    snapshot = {
        "scenario_id": scenario_id,
        "scenario_name": config.name,
        "timestamp": time.time(),
        "devices": [],
    }
    for device_config in config.devices:
        instance = engine._devices.get(device_config.id)
        if instance:
            points = instance.read_all_points()
            snapshot["devices"].append({
                "id": device_config.id,
                "name": device_config.name,
                "protocol": device_config.protocol,
                "status": instance.status.value,
                "points": [{"name": p.name, "value": p.value, "timestamp": p.timestamp} for p in points],
            })
    return snapshot


@router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics():
    from protoforge.core.metrics import metrics
    try:
        engine = _get_engine()
        metrics.collect_from_engine(engine)
    except RuntimeError:
        pass
    try:
        runner = _get_test_runner()
        metrics.collect_from_test_runner(runner)
    except RuntimeError:
        pass
    return metrics.generate_prometheus_output()


@router.post("/auth/login")
async def login(credentials: dict[str, Any]):
    from protoforge.core.auth import user_manager, create_token
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    user = user_manager.authenticate(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user.id, user.username, user.role)
    return {"access_token": token, "token_type": "bearer", "username": user.username, "role": user.role}


@router.post("/auth/register")
async def register(user_data: dict[str, Any]):
    from protoforge.core.auth import user_manager
    username = user_data.get("username", "")
    password = user_data.get("password", "")
    role = user_data.get("role", "user")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    user = await user_manager.create_user(username, password, role)
    if not user:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/auth/users")
async def list_users():
    from protoforge.core.auth import user_manager
    return user_manager.list_users()


@router.post("/auth/change-password")
async def change_password(data: dict[str, Any]):
    from protoforge.core.auth import user_manager
    username = data.get("username", "")
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")
    ok, msg = await user_manager.change_password(username, old_password, new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok"}


@router.post("/auth/admin/reset-password")
async def admin_reset_password(data: dict[str, Any]):
    from protoforge.core.auth import user_manager
    username = data.get("username", "")
    new_password = data.get("new_password", "")
    if not username or not new_password:
        raise HTTPException(status_code=400, detail="username and new_password required")
    ok, msg = await user_manager.admin_reset_password(username, new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok"}


@router.put("/auth/users/{username}/role")
async def update_user_role(username: str, data: dict[str, Any]):
    from protoforge.core.auth import user_manager
    new_role = data.get("role", "")
    if not new_role:
        raise HTTPException(status_code=400, detail="role is required")
    if not await user_manager.update_user_role(username, new_role):
        raise HTTPException(status_code=400, detail="Failed to update role")
    return {"status": "ok"}


@router.post("/auth/admin/unlock/{username}")
async def admin_unlock_user(username: str):
    from protoforge.core.auth import user_manager
    if not await user_manager.reset_login_attempts(username):
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "ok"}


@router.delete("/auth/users/{username}")
async def delete_user(username: str):
    from protoforge.core.auth import user_manager
    if not await user_manager.delete_user(username):
        raise HTTPException(status_code=400, detail="Cannot delete this user")
    return {"status": "ok"}


_forward_engine = None


def _get_forward_engine():
    global _forward_engine
    if _forward_engine is None:
        from protoforge.core.forward import ForwardEngine
        _forward_engine = ForwardEngine(_get_log_bus())
    return _forward_engine


@router.get("/forward/targets")
async def list_forward_targets():
    engine = _get_forward_engine()
    return engine.list_targets()


@router.post("/forward/targets")
async def add_forward_target(config: dict[str, Any]):
    from protoforge.core.forward import create_target
    engine = _get_forward_engine()
    name = config.get("name", f"target-{int(time.time())}")
    target = create_target(config)
    engine.add_target(name, target)
    return {"status": "ok", "name": name}


@router.delete("/forward/targets/{name}")
async def remove_forward_target(name: str):
    engine = _get_forward_engine()
    engine.remove_target(name)
    return {"status": "ok"}


@router.post("/forward/start")
async def start_forward():
    engine = _get_forward_engine()
    await engine.start()
    return {"status": "ok"}


@router.post("/forward/stop")
async def stop_forward():
    engine = _get_forward_engine()
    await engine.stop()
    return {"status": "ok"}


@router.get("/forward/stats")
async def forward_stats():
    engine = _get_forward_engine()
    return engine.get_stats()


_recorder = None


def _get_recorder():
    global _recorder
    if _recorder is None:
        from protoforge.core.recorder import Recorder
        _recorder = Recorder(_get_log_bus())
    return _recorder


@router.post("/recorder/start")
async def start_recording(config: dict[str, Any]):
    recorder = _get_recorder()
    rec = await recorder.start_recording(
        name=config.get("name", "Untitled"),
        protocol=config.get("protocol"),
        device_id=config.get("device_id"),
        metadata=config.get("metadata"),
    )
    return rec.to_dict()


@router.post("/recorder/stop")
async def stop_recording():
    recorder = _get_recorder()
    rec = await recorder.stop_recording()
    if not rec:
        raise HTTPException(status_code=400, detail="No active recording")
    return rec.to_dict()


@router.get("/recorder/recordings")
async def list_recordings():
    recorder = _get_recorder()
    return recorder.list_recordings()


@router.get("/recorder/recordings/{rec_id}")
async def get_recording(rec_id: str):
    recorder = _get_recorder()
    rec = recorder.get_recording(rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    return rec.to_full_dict()


@router.delete("/recorder/recordings/{rec_id}")
async def delete_recording(rec_id: str):
    recorder = _get_recorder()
    if not recorder.delete_recording(rec_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return {"status": "ok"}


@router.post("/recorder/recordings/{rec_id}/replay")
async def replay_recording(rec_id: str, config: dict[str, Any]):
    recorder = _get_recorder()
    speed = config.get("speed", 1.0)
    try:
        result = await recorder.replay_recording(rec_id, speed=speed, target_engine=_get_engine())
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/recorder/recordings/{rec_id}/export")
async def export_recording(rec_id: str):
    recorder = _get_recorder()
    rec = recorder.get_recording(rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    from fastapi.responses import JSONResponse
    return JSONResponse(content=rec.to_full_dict())


@router.get("/recorder/stats")
async def recorder_stats():
    recorder = _get_recorder()
    return recorder.get_stats()


@router.get("/webhooks")
async def list_webhooks():
    from protoforge.core.webhook import webhook_manager
    return webhook_manager.list_webhooks()


@router.post("/webhooks")
async def add_webhook(config: dict[str, Any]):
    from protoforge.core.webhook import webhook_manager
    if "url" not in config:
        raise HTTPException(status_code=400, detail="url is required")
    webhook = webhook_manager.add_webhook(config)
    return webhook.to_dict()


@router.put("/webhooks/{wh_id}")
async def update_webhook(wh_id: str, config: dict[str, Any]):
    from protoforge.core.webhook import webhook_manager
    webhook = webhook_manager.update_webhook(wh_id, config)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return webhook.to_dict()


@router.delete("/webhooks/{wh_id}")
async def delete_webhook(wh_id: str):
    from protoforge.core.webhook import webhook_manager
    if not webhook_manager.remove_webhook(wh_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"status": "ok"}


@router.post("/webhooks/{wh_id}/test")
async def test_webhook(wh_id: str):
    from protoforge.core.webhook import webhook_manager
    webhook = webhook_manager.get_webhook(wh_id)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await webhook_manager.trigger("test", {"message": "Test webhook from ProtoForge", "webhook_id": wh_id})
    return {"status": "ok"}


@router.get("/webhooks/stats")
async def webhook_stats():
    from protoforge.core.webhook import webhook_manager
    return webhook_manager.get_stats()


@router.post("/setup/demo")
async def setup_demo():
    engine = _get_engine()
    tm = _get_template_manager()
    from protoforge.core.demo import seed_demo_data
    try:
        await seed_demo_data(engine, tm)
        return {"status": "ok", "message": "演示数据已创建：4个设备 + 1个场景"}
    except Exception as e:
        from protoforge.core.defaults import get_friendly_error
        raise HTTPException(status_code=500, detail=get_friendly_error(str(e)))


@router.get("/setup/status")
async def setup_status():
    engine = _get_engine()
    devices = engine.get_all_device_ids()
    protocols_running = sum(1 for p in engine._protocol_servers.values() if p.status.value == "running")
    return {
        "initialized": len(devices) > 0,
        "device_count": len(devices),
        "protocols_running": protocols_running,
        "templates_available": len(_get_template_manager().list_templates()),
    }


@router.get("/settings")
async def get_settings():
    from protoforge.config import get_all_settings_dict
    return get_all_settings_dict()


@router.put("/settings")
async def update_settings(updates: dict[str, Any]):
    from protoforge.config import update_settings, get_all_settings_dict
    changed = update_settings(updates)
    return {"status": "ok", "changed": changed, "current": get_all_settings_dict()}
