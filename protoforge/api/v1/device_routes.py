import logging
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_engine, _get_log_bus, _trigger_webhook_safe, _get_database
from protoforge.models.device import DeviceConfig, DeviceInfo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/devices")
async def list_devices(protocol: Optional[str] = None, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    return {"devices": engine.list_devices(protocol=protocol)}


@router.post("/devices")  # FIXED: 移除response_model=DeviceInfo，避免过滤_persistence_warning
async def create_device(config: DeviceConfig, _user: dict = Depends(require_operator)):
    if not config.name or not config.name.strip():
        raise HTTPException(status_code=400, detail="设备名称不能为空")
    if not config.id or not config.id.strip():
        raise HTTPException(status_code=400, detail="设备ID不能为空")
    if len(config.id) > 64:
        raise HTTPException(status_code=400, detail="设备ID长度不能超过64个字符")
    if len(config.name) > 128:
        raise HTTPException(status_code=400, detail="设备名称长度不能超过128个字符")
    config.name = config.name.strip()
    config.id = config.id.strip()
    engine = _get_engine()
    db = _get_database()
    log_bus = _get_log_bus()

    try:
        result = await engine.create_device(config)
        db_ok = True
        db_err_msg = ""
        try:
            await db.save_device(config)
        except Exception as db_err:
            db_ok = False
            db_err_msg = str(db_err)
            logger.error("Failed to save device %s to DB: %s", config.id, db_err)
        try:
            await engine.start_device(config.id)
        except Exception as start_err:
            logger.warning("Device %s created but auto-start failed: %s", config.id, start_err)
        log_bus.emit(config.protocol, "system", config.id, "device_created", f"Device {config.name} created", {"device_id": config.id})
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump()) else result
        if not db_ok:
            resp["_persistence_warning"] = f"设备已在内存中创建，但数据持久化失败: {db_err_msg}。重启后数据将丢失。"
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
        raise HTTPException(status_code=400, detail="template_id 和 name 必须为字符串")
    template_id = template_id.strip()
    device_name = device_name.strip()
    device_id = params.get("id") or device_name.lower().replace(" ", "-").replace("(", "").replace(")", "") or str(uuid.uuid4())[:8]
    if not isinstance(device_id, str):  # FIXED: 校验id类型
        raise HTTPException(status_code=400, detail="id must be a string")
    device_id = re.sub(r'[^a-zA-Z0-9_\-]', '-', device_id).strip('-') or str(uuid.uuid4())[:8]
    protocol_config = params.get("protocol_config", {})
    if not isinstance(protocol_config, dict):
        raise HTTPException(status_code=400, detail="protocol_config 必须为对象")

    if not template_id or not template_id.strip():
        raise HTTPException(status_code=400, detail="template_id 为必填项")
    if not device_name or not device_name.strip():
        raise HTTPException(status_code=400, detail="name 为必填项")
    from protoforge.api.v1._helpers import _get_template_manager
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
        db_ok = True
        db_err_msg = ""
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
            resp["_persistence_warning"] = f"设备已在内存中创建，但数据持久化失败: {db_err_msg}。重启后数据将丢失。"
        return resp
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/devices/batch")
async def batch_create_devices(configs: list[DeviceConfig], _user: dict = Depends(require_operator)):
    if not configs:
        raise HTTPException(status_code=400, detail="configs 不能为空")
    engine = _get_engine()
    db = _get_database()
    results = []

    for config in configs:
        try:
            info = await engine.create_device(config)
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
                item["_persistence_warning"] = "数据持久化失败，重启后数据将丢失"
            results.append(item)
        except Exception as e:
            logger.warning("Batch create device %s failed: [%s] %s", config.id, type(e).__name__, e)  # FIXED: 记录异常类型
            results.append({"id": config.id, "error": str(e)})

    created_count = sum(1 for r in results if "error" not in r)
    return {"status": "ok", "created": created_count, "total": len(results), "devices": results}


@router.delete("/devices/batch")
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
                    errors.append({"id": device_id, "error": f"内存已删除但数据库删除失败: {db_err}"})
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


@router.get("/devices/{device_id}", response_model=DeviceInfo)
async def get_device(device_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    try:
        return engine.get_device(device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/devices/{device_id}/config", response_model=DeviceConfig)
async def get_device_config(device_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    return instance.config


@router.get("/devices/{device_id}/connection-guide")
async def get_device_connection_guide(device_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    device = engine.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    from protoforge.core.defaults import PROTOCOL_USAGE, get_protocol_defaults
    usage = PROTOCOL_USAGE.get(device.protocol, {})
    defaults = get_protocol_defaults(device.protocol)
    config = {**defaults, **(device.protocol_config or {})}
    code_examples = {}

    if usage.get("code_examples"):
        for lang, code in usage["code_examples"].items():
            try:
                code_examples[lang] = code.format(**config)
            except KeyError:
                code_examples[lang] = code

    code_example = ""
    if code_examples:
        code_example = code_examples.get("python", list(code_examples.values())[0])
    elif usage.get("code_example"):
        try:
            code_example = usage["code_example"].format(**config)
        except KeyError:
            code_example = usage["code_example"]

    return {
        "protocol": device.protocol,
        "device_id": device_id,
        "device_name": device.name,
        "mode": usage.get("mode", "server"),
        "mode_label": usage.get("mode_label", ""),
        "mode_desc": usage.get("mode_desc", ""),
        "connect_hint": usage.get("connect_hint", ""),
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
        await engine.remove_device(device_id)
        db_ok = True
        db_err_msg = ""
        try:
            await db.delete_device(device_id)
        except Exception as db_err:
            db_ok = False
            db_err_msg = str(db_err)
            logger.error("Failed to delete device %s from DB: %s", device_id, db_err)
        log_bus.emit(info.protocol, "system", device_id, "device_removed", f"Device {info.name} removed")
        resp = {"status": "ok"}
        if not db_ok:
            resp["_persistence_warning"] = f"设备已从内存中删除，但数据库删除失败: {db_err_msg}。重启后设备可能重新出现。"
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
        try:
            await db.save_device(config)
        except Exception as db_err:
            db_ok = False
            db_err_msg = str(db_err)
            logger.error("Failed to update device %s in DB: %s", device_id, db_err)
        log_bus.emit(config.protocol, "system", device_id, "device_updated", f"Device {config.name} updated")
        response = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump()) else {"id": device_id, "name": config.name, "protocol": config.protocol}
        if not db_ok:
            response["_persistence_warning"] = f"设备已在内存中更新，但数据持久化失败: {db_err_msg}。重启后更改将丢失。"
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{device_id}/points")
async def get_device_points(device_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()

    try:
        return {"points": await engine.read_device_points(device_id)}
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


@router.put("/devices/{device_id}/points/{point_name}")
async def write_device_point(device_id: str, point_name: str, body: dict[str, Any] | None = None, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    log_bus = _get_log_bus()
    value = body.get("value") if body else None
    if value is None:
        raise HTTPException(status_code=400, detail="Missing 'value' in request body")

    try:
        success = await engine.write_device_point(device_id, point_name, value)
        if not success:
            raise HTTPException(status_code=400, detail="Write failed")
        log_bus.emit(instance.protocol if (instance := engine.get_device_instance(device_id)) else "", "write", device_id, "point_write", f"Write {point_name}={value}", {"point": point_name, "value": value})
        await _trigger_webhook_safe("data_change", {"device_id": device_id, "point": point_name, "value": value})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
