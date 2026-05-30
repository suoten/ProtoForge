import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_engine, _get_database, _trigger_webhook_safe
from protoforge.models.scenario import ScenarioConfig, ScenarioConfigUpdate, ScenarioDetail, ScenarioInfo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/scenarios")
async def list_scenarios(_user: dict = Depends(require_viewer)):
    engine = _get_engine()
    return {"scenarios": engine.list_scenarios()}


@router.post("/scenarios")  # FIXED: 移除response_model=ScenarioInfo，避免过滤_persistence_warning
async def create_scenario(config: ScenarioConfig, _user: dict = Depends(require_operator)):
    if not config.name or not config.name.strip():
        raise HTTPException(status_code=400, detail="Scenario name is required")  # FIXED: 中文→英文
    if not config.id or not config.id.strip():
        raise HTTPException(status_code=400, detail="Scenario ID is required")  # FIXED: 中文→英文
    engine = _get_engine()
    db = _get_database()

    try:
        result = await engine.create_scenario(config)  # FIXED-P1: create_scenario是async，需await
        db_ok = True
        db_err_msg = ""
        if db is not None:  # FIXED: 添加db空值检查，避免AttributeError
            try:
                await db.save_scenario(config)
            except Exception as db_err:
                db_ok = False
                db_err_msg = str(db_err)
                logger.error("Failed to persist scenario %s: %s", config.id, db_err)
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump()) else result
        if not db_ok:
            resp["_persistence_warning"] = f"Scenario created in memory, but persistence failed: {db_err_msg}. Data will be lost after restart."  # FIXED: 中文→英文
        return resp
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/scenarios/{scenario_id}")  # FIXED: 移除response_model=ScenarioDetail，与create/update保持一致
async def get_scenario(scenario_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    try:
        return engine.get_scenario(scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/scenarios/{scenario_id}/start")
async def start_scenario(scenario_id: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    from protoforge.api.v1._helpers import _get_log_bus
    log_bus = _get_log_bus()
    try:
        await engine.start_scenario(scenario_id)
        log_bus.emit("", "system", "", "scenario_start", f"Scenario {scenario_id} started", {"scenario_id": scenario_id})
        await _trigger_webhook_safe("scenario_start", {"scenario_id": scenario_id})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to start scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scenarios/{scenario_id}/stop")
async def stop_scenario(scenario_id: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    from protoforge.api.v1._helpers import _get_log_bus
    log_bus = _get_log_bus()

    try:
        await engine.stop_scenario(scenario_id)
        log_bus.emit("", "system", "", "scenario_stop", f"Scenario {scenario_id} stopped", {"scenario_id": scenario_id})
        await _trigger_webhook_safe("scenario_stop", {"scenario_id": scenario_id})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to stop scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/scenarios/{scenario_id}")
async def update_scenario(scenario_id: str, update: ScenarioConfigUpdate, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()

    try:
        existing = engine.get_scenario_config(scenario_id)
        if not existing:
            raise ValueError(f"Scenario not found: {scenario_id}")
        status_info = engine.get_scenario_status(scenario_id)
        if status_info and status_info.value in ("running", "starting"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot update a running or starting scenario (current status: {status_info.value}). Stop it first.",
            )
        merged = ScenarioConfig(
            id=scenario_id,
            name=update.name if update.name is not None else existing.name,
            description=update.description if update.description is not None else existing.description,
            devices=update.devices if update.devices is not None else existing.devices,
            rules=update.rules if update.rules is not None else existing.rules,
        )
        result = await engine.update_scenario(scenario_id, merged)  # FIXED-P1: update_scenario是async，需await
        db_ok = True
        db_err_msg = ""
        if db:
            try:
                await db.save_scenario(merged)
            except Exception as db_err:
                db_ok = False
                db_err_msg = str(db_err)
                logger.error("Failed to persist scenario %s: %s", scenario_id, db_err)
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump()) else result
        if not db_ok:
            resp["_persistence_warning"] = f"Scenario updated in memory, but persistence failed: {db_err_msg}. Changes will be lost after restart."  # FIXED: 中文→英文
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()

    try:
        config = engine.get_scenario_config(scenario_id)
        if config and config.devices:
            for device_cfg in config.devices:
                try:
                    await engine.remove_device(device_cfg.id)
                except Exception as dev_err:
                    logger.warning("Failed to remove device %s during scenario %s cleanup: %s", device_cfg.id, scenario_id, dev_err)
        await engine.remove_scenario(scenario_id)
        db_ok = True
        db_err_msg = ""
        if db:
            try:
                await db.delete_scenario(scenario_id)
            except Exception as db_err:
                db_ok = False
                db_err_msg = str(db_err)
                logger.error("Failed to delete scenario %s from DB: %s", scenario_id, db_err)
        resp = {"status": "ok"}
        if not db_ok:
            resp["_persistence_warning"] = f"Scenario deleted from memory, but DB deletion failed: {db_err_msg}. Scenario may reappear after restart."  # FIXED: 中文→英文
        return resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/scenarios/{scenario_id}/export")
async def export_scenario(scenario_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    db = _get_database()

    try:
        config = None
        try:
            config = await db.load_scenario(scenario_id) if db else None  # FIXED: 添加空值检查和异常降级
        except Exception as db_err:
            logger.warning("Failed to load scenario %s from DB, falling back to engine: %s", scenario_id, db_err)
        if not config:
            config = engine.get_scenario_config(scenario_id)
        if not config:
            raise HTTPException(status_code=404, detail="Scenario not found")
        result = config.model_dump() if hasattr(config, 'model_dump') and callable(config.model_dump) else config
        # FIXED: 场景导出JSON无版本标识 — 添加schema_version为未来兼容性预留
        result["schema_version"] = "1.0"
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to export scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail="Failed to export scenario")  # FIXED: 中文→英文


@router.post("/scenarios/import")
async def import_scenario(config: ScenarioConfig, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()

    try:
        result = await engine.create_scenario(config)  # FIXED-P1: create_scenario是async，需await
        db_ok = True
        db_err_msg = ""
        if db:
            try:
                await db.save_scenario(config)
            except Exception as db_err:
                db_ok = False
                db_err_msg = str(db_err)
                logger.error("Failed to persist imported scenario %s: %s", config.id, db_err)
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump()) else result
        if not db_ok:
            resp["_persistence_warning"] = f"Scenario imported to memory, but persistence failed: {db_err_msg}. Data will be lost after restart."  # FIXED: 中文→英文
        return resp
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to import scenario: %s", e)
        raise HTTPException(status_code=500, detail="Failed to import scenario")  # FIXED: 中文→英文


@router.get("/scenarios/{scenario_id}/snapshot")
async def get_scenario_snapshot(scenario_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    try:
        config = engine.get_scenario_config(scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not config:
        raise HTTPException(status_code=404, detail="Scenario not found")

    snapshot = {
        "scenario_id": scenario_id,
        "scenario_name": config.name,
        "timestamp": time.time(),
        "devices": [],
    }

    for device_config in config.devices:
        instance = engine.get_device_instance(device_config.id)
        if instance:
            try:
                points = instance.read_all_points()
                snapshot["devices"].append({
                    "id": device_config.id,
                    "name": device_config.name,
                    "protocol": device_config.protocol,
                    "status": instance.status.value,
                    "points": [{"name": p.name, "value": p.value, "timestamp": p.timestamp} for p in points],
                })
            except Exception as e:
                logger.warning("Failed to read points for device %s in snapshot: %s", device_config.id, e)
                snapshot["devices"].append({
                    "id": device_config.id,
                    "name": device_config.name,
                    "protocol": device_config.protocol,
                    "status": "error",
                    "points": [],
                })
    return snapshot
