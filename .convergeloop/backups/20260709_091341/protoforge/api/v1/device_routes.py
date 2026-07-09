import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from protoforge.api.v1._helpers import _get_database, _get_engine, _get_log_bus, _trigger_webhook_safe
from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.models.device import DeviceConfig

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/devices")
async def list_devices(protocol: str | None = None, _user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_engine()
    return {"devices": engine.list_devices(protocol=protocol)}


@router.post("/devices")
async def create_device(config: DeviceConfig, _user: dict[str, Any] = Depends(require_operator)):
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
async def quick_create_device(params: dict[str, Any], _user: dict[str, Any] = Depends(require_operator)):
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
    _user: dict[str, Any] = Depends(require_operator),
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
async def batch_delete_devices(device_ids: list[str] = Body(..., embed=True), _user: dict[str, Any] = Depends(require_operator)):
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
async def batch_start_devices(device_ids: list[str] = Body(..., embed=True), _user: dict[str, Any] = Depends(require_operator)):
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
async def batch_stop_devices(device_ids: list[str] = Body(..., embed=True), _user: dict[str, Any] = Depends(require_operator)):
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
async def get_device(device_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_engine()
    try:
        return engine.get_device(device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{device_id}/config")
async def get_device_config(device_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    return instance.config


@router.get("/devices/{device_id}/connection-guide")
async def get_device_connection_guide(device_id: str, request: Request, _user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    from protoforge.core.defaults import PROTOCOL_USAGE, get_protocol_defaults
    from protoforge.core.edgelite import get_protoforge_host
    from protoforge.core.messages import desc, get_lang_from_request
    lang = get_lang_from_request(request)
    usage = PROTOCOL_USAGE.get(device.protocol, {})
    defaults = get_protocol_defaults(device.protocol, lang=lang)
    config = {**defaults, **(device.protocol_config or {})}

    # Replace 0.0.0.0 (server listen address) with actual reachable host
    if config.get("host") in ("0.0.0.0", ""):
        config["host"] = get_protoforge_host()

    # Filter connection_info to only show relevant connection parameters
    _irrelevant_keys = {"display_name", "description", "icon", "config"}
    connection_info = {k: v for k, v in config.items() if k not in _irrelevant_keys and not isinstance(v, (dict, list))}

    # Check if protocol service is running
    protocol_status = None
    try:
        server = engine.get_protocol_server(device.protocol)
        if server:
            protocol_status = server.status.value if hasattr(server.status, 'value') else str(server.status)
    except Exception as e:
        logger.debug("获取协议服务状态失败: %s", e)

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
        "connection_info": connection_info,
        "protocol_status": protocol_status,
    }


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, _user: dict[str, Any] = Depends(require_operator)):
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
async def update_device(device_id: str, config: DeviceConfig, _user: dict[str, Any] = Depends(require_operator)):
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
async def get_device_points(device_id: str, _user: dict[str, Any] = Depends(require_viewer)):
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
async def start_device(device_id: str, _user: dict[str, Any] = Depends(require_operator)):
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
async def stop_device(device_id: str, _user: dict[str, Any] = Depends(require_operator)):
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
async def write_device_point(device_id: str, point_name: str, body: dict[str, Any] | None = None, _user: dict[str, Any] = Depends(require_operator)):
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


# ===========================================================================
#  故障注入 API
# ===========================================================================

class InjectFaultRequest(BaseModel):
    """注入故障请求。"""
    fault_type: str = Field(..., description="故障类型，如 sensor_drift, sensor_stuck, comm_loss 等")
    target: str = Field("*", description="目标点位名称，'*' 表示所有点位")
    duration: float = Field(-1, description="故障持续时间 (s)，-1 表示永久")
    severity: str = Field("medium", description="故障严重程度: low/medium/high/critical")
    parameters: dict[str, Any] = Field(default_factory=dict, description="故障参数")
    trigger_mode: str = Field("manual", description="触发模式: manual/random/scheduled/conditional")
    probability: float = Field(0.0, description="随机触发概率 (RANDOM 模式)")
    start_time: float | None = Field(None, description="定时触发时间戳 (SCHEDULED 模式)")
    description: str = Field("", description="故障描述")
    auto_activate: bool = Field(True, description="创建后是否自动激活")


@router.post("/devices/{device_id}/faults")
async def inject_device_fault(device_id: str, req: InjectFaultRequest, _user: dict[str, Any] = Depends(require_operator)):
    """注入故障到指定设备。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    from protoforge.core.fault_injection import FaultConfig, FaultType, TriggerMode

    try:
        fault_type = FaultType(req.fault_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fault type: {req.fault_type}. Valid types: {[t.value for t in FaultType]}",
        )

    try:
        trigger_mode = TriggerMode(req.trigger_mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trigger mode: {req.trigger_mode}. Valid modes: {[m.value for m in TriggerMode]}",
        )

    params = dict(req.parameters)
    if req.duration != -1 and "duration" not in params:
        params["duration"] = req.duration

    config = FaultConfig(
        fault_type=fault_type,
        target_point=req.target,
        trigger_mode=trigger_mode,
        parameters=params,
        target_device=device_id,
        probability=req.probability,
        start_time=req.start_time,
        description=req.description or f"{fault_type.value} on {req.target}",
    )

    fault_id = instance.inject_fault(config)

    # FaultInjector 默认将故障添加为活跃状态。
    # 如果 auto_activate=False，需要显式停用。
    if not req.auto_activate:
        instance.deactivate_fault(fault_id)

    await _trigger_webhook_safe("fault.activated", {
        "device_id": device_id,
        "fault_id": fault_id,
        "fault_type": fault_type.value,
        "target_point": req.target,
    })

    logger.info("Fault injected: device=%s, fault_id=%s, type=%s", device_id, fault_id, fault_type.value)

    return {
        "fault_id": fault_id,
        "device_id": device_id,
        "fault_type": fault_type.value,
        "target": req.target,
        "severity": req.severity,
        "trigger_mode": trigger_mode.value,
        "active": req.auto_activate,
        "parameters": params,
    }


@router.get("/devices/{device_id}/faults")
async def list_device_faults(
    device_id: str,
    active_only: bool = Query(False, description="仅返回活跃故障"),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """列出设备上的故障。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    faults = instance.get_active_faults() if active_only else instance.get_all_faults()

    return {
        "device_id": device_id,
        "faults": [f.to_dict() for f in faults],
        "count": len(faults),
    }


@router.delete("/devices/{device_id}/faults/{fault_id}")
async def remove_device_fault(device_id: str, fault_id: str, _user: dict[str, Any] = Depends(require_operator)):
    """移除指定故障。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    success = instance.remove_fault(fault_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Fault not found: {fault_id}")

    await _trigger_webhook_safe("fault.deactivated", {
        "device_id": device_id,
        "fault_id": fault_id,
    })

    return {"status": "ok", "fault_id": fault_id, "device_id": device_id}


@router.delete("/devices/{device_id}/faults")
async def clear_device_faults(device_id: str, _user: dict[str, Any] = Depends(require_operator)):
    """清除设备上的所有故障。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    count = instance.clear_all_faults()

    await _trigger_webhook_safe("fault.cleared", {"device_id": device_id, "count": count})

    return {"status": "ok", "device_id": device_id, "cleared": count}


# ===========================================================================
#  状态控制 API
# ===========================================================================

class StateTransitionRequest(BaseModel):
    """状态转换请求。"""
    event: str = Field(..., description="触发事件: start/stop/startup_complete/stop_complete/fault/reset/maintenance/maintenance_complete/program_mode/program_exit/device_failure")
    reason: str = Field("", description="转换原因")


@router.post("/devices/{device_id}/state/transition")
async def trigger_state_transition(
    device_id: str, req: StateTransitionRequest, _user: dict[str, Any] = Depends(require_operator),
):
    """触发设备状态转换。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    old_state = instance.device_state.value
    success = instance.state_machine.trigger(req.event, reason=req.reason)

    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"State transition '{req.event}' not allowed from state '{old_state}'",
        )

    new_state = instance.device_state.value
    log_bus = _get_log_bus()
    log_bus.emit(instance.protocol, "system", device_id, "state_transition",
                 f"State transition: {old_state} → {new_state} (event={req.event})",
                 {"event": req.event, "from": old_state, "to": new_state, "reason": req.reason})

    await _trigger_webhook_safe("device.state_changed", {
        "device_id": device_id,
        "event": req.event,
        "from_state": old_state,
        "to_state": new_state,
        "reason": req.reason,
    })

    return {
        "device_id": device_id,
        "event": req.event,
        "from_state": old_state,
        "to_state": new_state,
        "reason": req.reason,
    }


@router.get("/devices/{device_id}/state")
async def get_device_state(device_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """获取设备当前状态。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    return instance.get_state_info()


@router.get("/devices/{device_id}/state/history")
async def get_device_state_history(
    device_id: str,
    count: int = Query(50, ge=1, le=500, description="返回的历史记录数量"),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """获取设备状态转换历史。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    return {
        "device_id": device_id,
        "history": instance.get_state_history(count),
        "count": len(instance.get_state_history(count)),
    }


# ===========================================================================
#  控制回路 API
# ===========================================================================

class CreateControlLoopRequest(BaseModel):
    """创建控制回路请求。"""
    loop_id: str = Field(..., description="回路唯一标识")
    loop_type: str = Field("simple", description="回路类型: simple/cascade/feedforward")
    setpoint_point: str = Field("", description="设定值点位名")
    measurement_point: str = Field("", description="测量值点位名 (PV)")
    output_point: str = Field("", description="输出点位名 (CV)")
    pid_params: dict[str, float] = Field(
        default_factory=lambda: {"Kp": 1.0, "Ki": 0.1, "Kd": 0.01},
        description="PID 参数",
    )
    output_limit: list[float] = Field(
        [0.0, 100.0], description="输出限幅 [min, max]",
    )
    primary_loop_id: str | None = Field(None, description="主回路 ID (串级副回路用)")
    disturbance_point: str | None = Field(None, description="扰动量点位名 (前馈控制用)")
    feedforward_gain: float = Field(0.0, description="前馈补偿增益")
    enabled: bool = Field(True, description="是否启用此回路")
    auto_track: bool = Field(True, description="串级副回路无主回路输出时是否跟踪测量值")


@router.post("/devices/{device_id}/control-loops")
async def add_device_control_loop(
    device_id: str, req: CreateControlLoopRequest, _user: dict[str, Any] = Depends(require_operator),
):
    """添加控制回路到设备。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    from protoforge.core.control_loop import ControlLoopConfig

    loop_data = req.model_dump()
    if loop_data.get("output_limit") and isinstance(loop_data["output_limit"], list):
        ol = loop_data["output_limit"]
        if len(ol) != 2:
            raise HTTPException(status_code=400, detail="output_limit must be a list of [min, max]")
        loop_data["output_limit"] = (float(ol[0]), float(ol[1]))

    try:
        config = ControlLoopConfig.from_dict(loop_data)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid control loop config: {e}")

    try:
        loop_id = instance.add_control_loop(config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to add control loop: {e}")

    logger.info("Control loop added: device=%s, loop_id=%s", device_id, loop_id)

    return {
        "status": "ok",
        "device_id": device_id,
        "loop_id": loop_id,
        "loop_type": config.loop_type,
    }


@router.delete("/devices/{device_id}/control-loops/{loop_id}")
async def remove_device_control_loop(
    device_id: str, loop_id: str, _user: dict[str, Any] = Depends(require_operator),
):
    """移除控制回路。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    success = instance.remove_control_loop(loop_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Control loop not found: {loop_id}")

    logger.info("Control loop removed: device=%s, loop_id=%s", device_id, loop_id)

    return {"status": "ok", "device_id": device_id, "loop_id": loop_id}


@router.get("/devices/{device_id}/control-loops")
async def list_device_control_loops(device_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """列出设备上的控制回路。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    return instance.get_control_loop_info()


# ---------------------------------------------------------------------------
#  设备详情 & 网络仿真 & 时间序列 & 故障传播 API
# ---------------------------------------------------------------------------

@router.get("/devices/{device_id}/detail")
async def get_device_detail(device_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """获取设备详细信息，包含状态机、故障和控制回路信息。"""
    engine = _get_engine()
    try:
        return engine.get_device_detail(device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class ConfigureNetworkRequest(BaseModel):
    """配置网络仿真请求。"""
    profile: str | dict[str, Any] = Field(..., description="预定义名称或配置字典")
    enabled: bool = Field(True, description="是否启用")


@router.post("/network/configure")
async def configure_network(req: ConfigureNetworkRequest, _user: dict[str, Any] = Depends(require_operator)):
    """配置网络仿真参数。"""
    engine = _get_engine()
    engine.configure_network(req.profile, req.enabled)
    return {"status": "ok", "network_sim": engine.network_simulator.to_dict()}


@router.get("/network/status")
async def get_network_status(_user: dict[str, Any] = Depends(require_viewer)):
    """获取网络仿真状态。"""
    engine = _get_engine()
    return engine.network_simulator.to_dict()


class AddFaultPropagationRuleRequest(BaseModel):
    """添加故障传播规则请求。"""
    source_point: str = Field(..., description="源点位名称")
    target_point: str = Field(..., description="目标点位名称")
    condition: str = Field(..., description='触发条件，如 ">80"')
    delay: float = Field(0.0, description="传播延迟 (s)")
    effect_type: str = Field("sensor_noise", description="衍生故障类型")
    effect_params: dict[str, Any] = Field(default_factory=dict, description="衍生故障参数")
    severity: str = Field("medium", description="衍生故障严重级别")
    duration: float = Field(-1.0, description="衍生故障持续时间 (s)")


@router.post("/faults/propagation/rules")
async def add_fault_propagation_rule(req: AddFaultPropagationRuleRequest, _user: dict[str, Any] = Depends(require_operator)):
    """添加故障传播规则。"""
    engine = _get_engine()
    idx = engine.fault_propagation.add_rule(
        source=req.source_point,
        target=req.target_point,
        condition=req.condition,
        delay=req.delay,
        effect_type=req.effect_type,
        effect_params=req.effect_params,
        severity=req.severity,
        duration=req.duration,
    )
    return {"status": "ok", "rule_index": idx}


@router.get("/faults/propagation/rules")
async def list_fault_propagation_rules(_user: dict[str, Any] = Depends(require_viewer)):
    """列出故障传播规则。"""
    engine = _get_engine()
    return engine.fault_propagation.to_dict()


@router.delete("/faults/propagation/rules/{index}")
async def remove_fault_propagation_rule(index: int, _user: dict[str, Any] = Depends(require_operator)):
    """移除故障传播规则。"""
    engine = _get_engine()
    success = engine.fault_propagation.remove_rule(index)
    if not success:
        raise HTTPException(status_code=404, detail=f"Propagation rule {index} not found")
    return {"status": "ok", "removed_index": index}


class AddTimeSeriesPatternRequest(BaseModel):
    """添加时间序列模式请求。"""
    point_name: str = Field(..., description="点位名称")
    pattern_type: str = Field("daily", description="模式类型: daily/weekly/seasonal/batch/aging/composite")
    production_value: float = Field(80.0, description="生产时段目标值")
    standby_value: float = Field(20.0, description="待机时段目标值")
    base_value: float = Field(100.0, description="基准值")
    work_start_hour: int = Field(8, description="工作开始小时")
    work_end_hour: int = Field(18, description="工作结束小时")
    weekend_production: bool = Field(False, description="周末是否生产")
    seasonal_amplitude: float = Field(0.2, description="季节性波动幅度")
    aging_rate: float = Field(0.02, description="老化速率")
    offset_mode: bool = Field(False, description="偏移模式")


@router.post("/timeseries/patterns")
async def add_timeseries_pattern(req: AddTimeSeriesPatternRequest, _user: dict[str, Any] = Depends(require_operator)):
    """添加时间序列模式。"""
    engine = _get_engine()
    from protoforge.core.timeseries import TimeSeriesPattern
    pattern = TimeSeriesPattern(
        pattern_type=req.pattern_type,
        production_value=req.production_value,
        standby_value=req.standby_value,
        base_value=req.base_value,
        work_start_hour=req.work_start_hour,
        work_end_hour=req.work_end_hour,
        weekend_production=req.weekend_production,
        seasonal_amplitude=req.seasonal_amplitude,
        aging_rate=req.aging_rate,
        offset_mode=req.offset_mode,
    )
    engine.timeseries_manager.add_pattern(req.point_name, pattern)
    return {"status": "ok", "point_name": req.point_name, "pattern_type": req.pattern_type}


@router.get("/timeseries/patterns")
async def list_timeseries_patterns(_user: dict[str, Any] = Depends(require_viewer)):
    """列出所有时间序列模式。"""
    engine = _get_engine()
    return engine.timeseries_manager.to_dict()


@router.delete("/timeseries/patterns/{point_name}")
async def remove_timeseries_pattern(point_name: str, _user: dict[str, Any] = Depends(require_operator)):
    """移除时间序列模式。"""
    engine = _get_engine()
    success = engine.timeseries_manager.remove_pattern(point_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Pattern for point '{point_name}' not found")
    return {"status": "ok", "removed_point": point_name}
