import logging
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_engine, _get_log_bus, _trigger_webhook_safe, _get_database
from protoforge.models.device import DeviceConfig, DeviceInfo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/devices")
async def list_devices(protocol: Optional[str] = None, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    return {"devices": engine.list_devices(protocol=protocol)}


@router.post("/devices")
async def create_device(config: DeviceConfig, _user: dict = Depends(require_operator)):
    if not config.name or not config.name.strip():
        raise HTTPException(status_code=400, detail="Device name is required")
    if not config.id or not config.id.strip():
        raise HTTPException(status_code=400, detail="Device ID is required")
    if len(config.id) > 64:
        raise HTTPException(status_code=400, detail="Device ID must not exceed 64 characters")
    if len(config.name) > 128:
        raise HTTPException(status_code=400, detail="Device name must not exceed 128 characters")
    config.name = config.name.strip()
    config.id = config.id.strip()
    engine = _get_engine()
    db = _get_database()
    log_bus = _get_log_bus()

    try:
        result = await engine.create_device(config)
        db_ok = True
        db_err_msg = ""
        if db is not None:  # FIXED: 添加db空值检查，避免AttributeError
            try:
                await db.save_device(config)
            except Exception as db_err:
                db_ok = False
                db_err_msg = str(db_err)
                logger.error("Failed to save device %s to DB: %s", config.id, db_err)
                try:  # FIXED-P1: 持久化失败时回滚内存中的设备创建
                    await engine.remove_device(config.id)
                except Exception as rollback_err:
                    logger.error("Failed to rollback device %s after DB save failure: %s", config.id, rollback_err)
                raise HTTPException(status_code=500, detail=f"Device persistence failed: {db_err_msg}")
        try:
            await engine.start_device(config.id)
        except Exception as start_err:
            logger.warning("Device %s created but auto-start failed: %s", config.id, start_err)
        log_bus.emit(config.protocol, "system", config.id, "device_created", f"Device {config.name} created", {"device_id": config.id})
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump()) else result
        if not db_ok:
            resp["_persistence_warning"] = f"Device created in memory, but persistence failed: {db_err_msg}. Data will be lost after restart."
        return resp

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devices/quick-create")
async def quick_create_device(params: dict[str, Any], _user: dict = Depends(require_operator)):
    template_id = params.get("template_id", "")
    device_name = params.get("name", "")
    if not isinstance(template_id, str) or not isinstance(device_name, str):
        raise HTTPException(status_code=400, detail="template_id and name must be strings")
    template_id = template_id.strip()
    device_name = device_name.strip()
    device_id = params.get("id") or device_name.lower().replace(" ", "-").replace("(", "").replace(")", "") or str(uuid.uuid4())[:8]
    if not isinstance(device_id, str):
        raise HTTPException(status_code=400, detail="id must be a string")
    device_id = re.sub(r'[^a-zA-Z0-9_\-]', '-', device_id).strip('-') or str(uuid.uuid4())[:8]
    protocol_config = params.get("protocol_config", {})
    if not isinstance(protocol_config, dict):
        raise HTTPException(status_code=400, detail="protocol_config must be an object")

    if not template_id or not template_id.strip():
        raise HTTPException(status_code=400, detail="template_id is required")
    if not device_name or not device_name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    from protoforge.api.v1._helpers import _get_template_manager
    tm = _get_template_manager()
    template = tm.get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

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
        db_ok = True
        db_err_msg = ""
        if db is not None:  # FIXED: 添加db空值检查，避免AttributeError
            try:
                await db.save_device(config)
            except Exception as db_err:
                db_ok = False
                db_err_msg = str(db_err)
                logger.error("Failed to save device %s to DB (quick-create): %s", config.id, db_err)
        try:
            await engine.start_device(device_id)
        except Exception as start_err:
            logger.warning("quick-create: device %s created but start failed: %s", device_id, start_err)
        log_bus.emit(config.protocol, "system", config.id, "device_created", f"Device {device_name} created via quick-create", {"device_id": config.id})

        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump()) else result
        if not db_ok:
            resp["_persistence_warning"] = f"Device created in memory, but persistence failed: {db_err_msg}. Data will be lost after restart."
        return resp
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/devices/batch")
async def batch_create_devices(
    configs: list[DeviceConfig],
    atomic: bool = False,
    _user: dict = Depends(require_operator),
):
    """批量创建设备

    Args:
        atomic: 如果为 True，则所有设备要么全部创建成功，要么全部回滚
    """
    if not configs:
        raise HTTPException(status_code=400, detail="configs must not be empty")

    engine = _get_engine()
    db = _get_database()
    results = []
    created_devices = []  # 跟踪已创建的设备，用于回滚

    try:
        for config in configs:
            try:
                info = await engine.create_device(config)
                created_devices.append(config.id)
                db_ok = True
                if db:
                    try:
                        await db.save_device(config)
                    except Exception as db_err:
                        db_ok = False
                        logger.error("Failed to persist device %s: %s", config.id, db_err)
                try:
                    await engine.start_device(config.id)
                except Exception as start_err:
                    logger.warning("Device %s batch-created but auto-start failed: %s", config.id, start_err)
                item = info.model_dump() if hasattr(info, 'model_dump') and callable(info.model_dump()) else {"id": config.id, "name": config.name, "protocol": config.protocol}
                if not db_ok:
                    item["_persistence_warning"] = "Persistence failed, data will be lost after restart"
                results.append(item)
            except Exception as e:
                logger.warning("Batch create device %s failed: [%s] %s", config.id, type(e).__name__, e)

                # FIXED: 原子模式下，失败时回滚已创建的设备
                if atomic and created_devices:
                    logger.info("Atomic batch failed, rolling back %d devices", len(created_devices))
                    for dev_id in reversed(created_devices):
                        try:
                            await engine.remove_device(dev_id)
                            if db:
                                try:
                                    await db.delete_device(dev_id)
                                except Exception as e:
                                    logger.debug("Failed to delete device %s from DB during rollback: %s", dev_id, e)
                            logger.info("Rolled back device: %s", dev_id)
                        except Exception as rollback_err:
                            logger.error("Failed to rollback device %s: %s", dev_id, rollback_err)

                    return {
                        "status": "failed",
                        "reason": f"Device {config.id} creation failed: {str(e)}",
                        "rolled_back": len(created_devices),
                        "failed_at": config.id,
                        "error": str(e),
                    }

                results.append({"id": config.id, "error": str(e)})

        created_count = sum(1 for r in results if "error" not in r)
        return {"status": "ok", "created": created_count, "total": len(results), "devices": results}

    except Exception as e:
        # 捕获意外错误，确保回滚
        if atomic and created_devices:
            logger.info("Atomic batch failed with unexpected error, rolling back %d devices", len(created_devices))
            for dev_id in reversed(created_devices):
                try:
                    await engine.remove_device(dev_id)
                    if db:
                        try:
                            await db.delete_device(dev_id)
                        except Exception as e:
                            logger.debug("Failed to delete device %s from DB during rollback: %s", dev_id, e)
                except Exception as rollback_err:
                    logger.error("Failed to rollback device %s: %s", dev_id, rollback_err)

        raise HTTPException(status_code=500, detail=f"Batch creation failed: {str(e)}")


@router.post("/devices/batch/delete")
async def batch_delete_devices(device_ids: list[str] = Body(..., embed=True), _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()
    deleted = 0
    errors = []

    for device_id in device_ids:
        try:
            await engine.remove_device(device_id)
            if db:
                try:
                    await db.delete_device(device_id)
                except Exception as db_err:
                    logger.error("Failed to delete device %s from DB: %s", device_id, db_err)
                    errors.append({"id": device_id, "error": f"Deleted from memory but DB deletion failed: {db_err}"})
                    deleted += 1
                    continue
            deleted += 1
        except ValueError as e:
            errors.append({"id": device_id, "error": str(e)})
    return {"status": "ok", "deleted": deleted, "errors": errors}


@router.post("/devices/batch/start")
async def batch_start_devices(device_ids: list[str] = Body(..., embed=True), _user: dict = Depends(require_operator)):
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
async def batch_stop_devices(device_ids: list[str] = Body(..., embed=True), _user: dict = Depends(require_operator)):
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


@router.get("/devices/{device_id}")
async def get_device(device_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    try:
        return engine.get_device(device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{device_id}/config")
async def get_device_config(device_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    return instance.config


@router.get("/devices/{device_id}/connection-guide")
async def get_device_connection_guide(device_id: str, request: Request, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    from protoforge.core.defaults import PROTOCOL_USAGE, get_protocol_defaults
    from protoforge.core.messages import get_lang_from_request, desc
    from protoforge.core.edgelite import get_protoforge_host
    lang = get_lang_from_request(request)
    usage = PROTOCOL_USAGE.get(device.protocol, {})
    defaults = get_protocol_defaults(device.protocol, lang=lang)
    config = {**defaults, **(device.protocol_config or {})}

    # Replace 0.0.0.0 (server listen address) with actual reachable host
    if config.get("host") in ("0.0.0.0", ""):
        config["host"] = get_protoforge_host()
    code_examples = {}

    if usage.get("code_examples"):
        for code_lang, code in usage["code_examples"].items():
            try:
                code_examples[code_lang] = code.format(**config)
            except KeyError:
                code_examples[code_lang] = code

    code_example = ""
    if code_examples:
        code_example = code_examples.get("python", list(code_examples.values())[0])
    elif usage.get("code_example"):
        try:
            code_example = usage["code_example"].format(**config)
        except KeyError:
            code_example = usage["code_example"]

    protocol = device.protocol
    return {
        "protocol": protocol,
        "device_id": device_id,
        "device_name": device.name,
        "mode": usage.get("mode", "server"),
        "mode_label": desc(f"protocol.{protocol}.usage.mode_label", lang, usage.get("mode_label", "")),
        "mode_desc": desc(f"protocol.{protocol}.usage.mode_desc", lang, usage.get("mode_desc", "")),
        "connect_hint": desc(f"protocol.{protocol}.usage.connect_hint", lang, usage.get("connect_hint", "")),
        "code_example": code_example,
        "code_examples": code_examples,
        "connection_info": config,
    }


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()
    log_bus = _get_log_bus()

    try:
        info = engine.get_device(device_id)
        referencing_scenarios = []
        for sid, sconfig in engine.get_all_scenario_configs().items():
            if any(d.id == device_id for d in sconfig.devices):
                referencing_scenarios.append(sid)
        if referencing_scenarios:
            raise HTTPException(
                status_code=409,
                detail=f"Device '{device_id}' is referenced by scenario(s): {', '.join(referencing_scenarios)}. Remove the device from the scenario first, or delete the scenario.",
            )
        await engine.remove_device(device_id)
        db_ok = True
        db_err_msg = ""
        try:
            if db is not None:
                await db.delete_device(device_id)
            else:
                db_ok = False
                db_err_msg = "Database not initialized"
        except Exception as db_err:
            db_ok = False
            db_err_msg = str(db_err)
            logger.error("Failed to delete device %s from DB: %s", device_id, db_err)
        log_bus.emit(info.protocol, "system", device_id, "device_removed", f"Device {info.name} removed")
        resp = {"status": "ok"}
        if not db_ok:
            resp["_persistence_warning"] = f"Device deleted from memory, but DB deletion failed: {db_err_msg}. Device may reappear after restart."
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/devices/{device_id}")
async def update_device(device_id: str, config: DeviceConfig, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()
    log_bus = _get_log_bus()

    try:
        result = await engine.update_device(device_id, config)
        db_ok = True
        db_err_msg = ""
        if db is not None:  # FIXED: 添加db空值检查，避免AttributeError
            try:
                await db.save_device(config)
            except Exception as db_err:
                db_ok = False
                db_err_msg = str(db_err)
                logger.error("Failed to update device %s in DB: %s", device_id, db_err)
        log_bus.emit(config.protocol, "system", device_id, "device_updated", f"Device {config.name} updated")
        response = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump()) else {"id": device_id, "name": config.name, "protocol": config.protocol}
        if not db_ok:
            response["_persistence_warning"] = f"Device updated in memory, but persistence failed: {db_err_msg}. Changes will be lost after restart."
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{device_id}/points")
async def get_device_points(device_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()

    try:
        points = await engine.read_device_points(device_id)
        instance = engine.get_device_instance(device_id)
        protocol_active = False
        if instance:
            protocol_active = engine.is_protocol_running(instance.protocol)
        return {
            "points": points,
            "protocol_active": protocol_active,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/devices/{device_id}/start")
async def start_device(device_id: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()

    try:
        await engine.start_device(device_id)
        await _trigger_webhook_safe("device_online", {"device_id": device_id})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to start device %s: %s", device_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/devices/{device_id}/stop")
async def stop_device(device_id: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    try:
        await engine.stop_device(device_id)
        await _trigger_webhook_safe("device_offline", {"device_id": device_id})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to stop device %s: %s", device_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/devices/{device_id}/points/{point_name}")  # FIXED: 添加try-except保护
async def write_device_point(device_id: str, point_name: str, body: dict[str, Any] | None = None, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    log_bus = _get_log_bus()
    value = body.get("value") if body else None
    if value is None:
        raise HTTPException(status_code=400, detail="Missing 'value' in request body")

    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        success = await engine.write_device_point(device_id, point_name, value)
        if not success:
            raise HTTPException(status_code=400, detail="Write failed")
        log_bus.emit(instance.protocol if instance else "", "write", device_id, "point_write", f"Write {point_name}={value}", {"point": point_name, "value": value})
        await _trigger_webhook_safe("data_change", {"device_id": device_id, "point": point_name, "value": value})
        resp = {"status": "ok"}
        if instance:
            resp["protocol_active"] = engine.is_protocol_running(instance.protocol)
            if not resp["protocol_active"]:
                resp["warning"] = f"Protocol {instance.protocol} is not running - write only affects memory, not visible to external clients"
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Write device point failed for %s/%s: %s", device_id, point_name, e)
        raise HTTPException(status_code=500, detail=f"Write device point failed: {e}")
