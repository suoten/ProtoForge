import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_engine, _get_database
from protoforge.models.scenario import ScenarioConfig, ScenarioConfigUpdate, ScenarioDetail, ScenarioInfo

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/scenarios", response_model=list[ScenarioInfo])
async def list_scenarios(_user: dict = Depends(require_viewer)):
    engine = _get_engine()
    return engine.list_scenarios()


@router.post("/scenarios", response_model=ScenarioInfo)
async def create_scenario(config: ScenarioConfig, _user: dict = Depends(require_operator)):
    if not config.name or not config.name.strip():
        raise HTTPException(status_code=400, detail="场景名称不能为空")
    if not config.id or not config.id.strip():
        raise HTTPException(status_code=400, detail="场景ID不能为空")
    engine = _get_engine()
    db = _get_database()

    try:
        result = engine.create_scenario(config)
        try:
            await db.save_scenario(config)
        except Exception as db_err:
            logger.warning("Failed to persist scenario %s: %s", config.id, db_err)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/scenarios/{scenario_id}", response_model=ScenarioDetail)
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
        from protoforge.core.webhook import webhook_manager
        await webhook_manager.trigger("scenario_start", {"scenario_id": scenario_id})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/scenarios/{scenario_id}/stop")
async def stop_scenario(scenario_id: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    from protoforge.api.v1._helpers import _get_log_bus
    log_bus = _get_log_bus()

    try:
        await engine.stop_scenario(scenario_id)
        log_bus.emit("", "system", "", "scenario_stop", f"Scenario {scenario_id} stopped", {"scenario_id": scenario_id})
        from protoforge.core.webhook import webhook_manager
        await webhook_manager.trigger("scenario_stop", {"scenario_id": scenario_id})
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/scenarios/{scenario_id}", response_model=ScenarioInfo)
async def update_scenario(scenario_id: str, update: ScenarioConfigUpdate, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()

    try:
        existing = engine.get_scenario_config(scenario_id)
        if not existing:
            raise ValueError(f"Scenario not found: {scenario_id}")
        merged = ScenarioConfig(
            id=scenario_id,
            name=update.name if update.name is not None else existing.name,
            description=update.description if update.description is not None else existing.description,
            devices=update.devices if update.devices is not None else existing.devices,
            rules=update.rules if update.rules is not None else existing.rules,
        )
        result = engine.update_scenario(scenario_id, merged)
        if db:
            try:
                await db.save_scenario(merged)
            except Exception as db_err:
                logger.warning("Failed to persist scenario %s: %s", scenario_id, db_err)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()

    try:
        engine.remove_scenario(scenario_id)
        if db:
            try:
                await db.delete_scenario(scenario_id)
            except Exception as db_err:
                logger.warning("Failed to delete scenario %s from DB: %s", scenario_id, db_err)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/scenarios/{scenario_id}/export")
async def export_scenario(scenario_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    db = _get_database()

    try:
        config = await db.load_scenario(scenario_id)
        if not config:
            config = engine.get_scenario_config(scenario_id)
        if not config:
            raise HTTPException(status_code=404, detail="Scenario not found")
        return config.model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to export scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail="导出场景失败")


@router.post("/scenarios/import")
async def import_scenario(config: ScenarioConfig, _user: dict = Depends(require_operator)):
    engine = _get_engine()
    db = _get_database()

    try:
        result = engine.create_scenario(config)
        if db:
            try:
                await db.save_scenario(config)
            except Exception as db_err:
                logger.warning("Failed to persist scenario %s: %s", config.id, db_err)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to import scenario: %s", e)
        raise HTTPException(status_code=500, detail="导入场景失败")


@router.get("/scenarios/{scenario_id}/snapshot")
async def get_scenario_snapshot(scenario_id: str, _user: dict = Depends(require_viewer)):
    engine = _get_engine()
    config = engine.get_scenario_config(scenario_id)
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
            points = instance.read_all_points()
            snapshot["devices"].append({
                "id": device_config.id,
                "name": device_config.name,
                "protocol": device_config.protocol,
                "status": instance.status.value,
                "points": [{"name": p.name, "value": p.value, "timestamp": p.timestamp} for p in points],
            })
    return snapshot
