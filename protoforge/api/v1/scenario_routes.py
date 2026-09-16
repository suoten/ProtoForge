"""Scenario management API routes (CRUD, start/stop)."""

import logging
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from protoforge.api.v1._helpers import _get_database, _get_engine, _trigger_webhook_safe
from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.models.device import DeviceConfig
from protoforge.models.scenario import ScenarioConfig, ScenarioConfigUpdate

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/scenarios")
async def list_scenarios(_user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_engine()
    return {"scenarios": engine.list_scenarios()}


@router.post("/scenarios")  # FIXED: 移除response_model=ScenarioInfo，避免过滤_persistence_warning
async def create_scenario(config: ScenarioConfig, _user: dict[str, Any] = Depends(require_operator)):
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
                logger.exception("Failed to persist scenario %s: %s", config.id, db_err)
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump) else result
        if not db_ok:
            resp["_persistence_warning"] = f"Scenario created in memory, but persistence failed: {db_err_msg}. Data will be lost after restart."  # FIXED: 中文→英文
        return resp
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to create scenario %s: %s", config.id, e)
        raise HTTPException(status_code=500, detail=f"Failed to create scenario: {e}") from e


@router.get("/scenarios/{scenario_id}")  # FIXED: 移除response_model=ScenarioDetail，与create/update保持一致
async def get_scenario(scenario_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_engine()
    try:
        return engine.get_scenario(scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/scenarios/{scenario_id}/start")
async def start_scenario(scenario_id: str, _user: dict[str, Any] = Depends(require_operator)):
    engine = _get_engine()
    from protoforge.api.v1._helpers import _get_log_bus
    log_bus = _get_log_bus()
    try:
        await engine.start_scenario(scenario_id)
        log_bus.emit("", "system", "", "scenario_start", f"Scenario {scenario_id} started", {"scenario_id": scenario_id})
        await _trigger_webhook_safe("scenario_start", {"scenario_id": scenario_id})
        return {"status": "ok"}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to start scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to start scenario: {e}") from e


@router.post("/scenarios/{scenario_id}/stop")
async def stop_scenario(scenario_id: str, _user: dict[str, Any] = Depends(require_operator)):
    engine = _get_engine()
    from protoforge.api.v1._helpers import _get_log_bus
    log_bus = _get_log_bus()

    try:
        await engine.stop_scenario(scenario_id)
        log_bus.emit("", "system", "", "scenario_stop", f"Scenario {scenario_id} stopped", {"scenario_id": scenario_id})
        await _trigger_webhook_safe("scenario_stop", {"scenario_id": scenario_id})
        return {"status": "ok"}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to stop scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to stop scenario: {e}") from e


@router.put("/scenarios/{scenario_id}")
async def update_scenario(scenario_id: str, update: ScenarioConfigUpdate, _user: dict[str, Any] = Depends(require_operator)):
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
                logger.exception("Failed to persist scenario %s: %s", scenario_id, db_err)
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump) else result
        if not db_ok:
            resp["_persistence_warning"] = f"Scenario updated in memory, but persistence failed: {db_err_msg}. Changes will be lost after restart."  # FIXED: 中文→英文
        return resp
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to update scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to update scenario: {e}") from e


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str, _user: dict[str, Any] = Depends(require_operator)):
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
                logger.exception("Failed to delete scenario %s from DB: %s", scenario_id, db_err)
        resp = {"status": "ok"}
        if not db_ok:
            resp["_persistence_warning"] = f"Scenario deleted from memory, but DB deletion failed: {db_err_msg}. Scenario may reappear after restart."  # FIXED: 中文→英文
        return resp
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to delete scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to delete scenario: {e}") from e


@router.post("/scenarios/{scenario_id}/clone")
async def clone_scenario(scenario_id: str, params: dict[str, Any] = Body(default={}),
                          _user: dict[str, Any] = Depends(require_operator)):
    """Clone an existing scenario with a new ID and name.

    Body params (all optional):
      - new_id: new scenario ID (auto-generated if not provided)
      - new_name: new scenario name (defaults to "{original} Copy")
      - clone_devices: whether to clone all devices in the scenario (default True)
    """
    import re
    import uuid

    engine = _get_engine()
    db = _get_database()

    # Get original scenario config
    try:
        original = engine.get_scenario_config(scenario_id)
    except ValueError:
        original = None
    if not original:
        # Try loading from DB
        if db:
            try:
                original = await db.load_scenario(scenario_id)
            except Exception:
                pass
    if not original:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {scenario_id}")

    new_id = params.get("new_id") or f"{scenario_id}-copy-{uuid.uuid4().hex[:6]}"
    new_name = params.get("new_name") or f"{original.name} Copy"
    clone_devices = params.get("clone_devices", True)

    new_id = re.sub(r'[^a-zA-Z0-9_\-]', '-', new_id).strip('-') or f"scenario-copy-{uuid.uuid4().hex[:6]}"

    # Check if new ID already exists
    existing_scenarios = engine.list_scenarios()
    for s in existing_scenarios:
        if s.id == new_id:
            raise HTTPException(status_code=409, detail=f"Scenario ID already exists: {new_id}")

    # Clone devices if requested
    cloned_device_ids: list[str] = []
    if clone_devices and original.devices:
        for dev_cfg in original.devices:
            old_dev_id = dev_cfg.id
            new_dev_id = f"{old_dev_id}-copy-{uuid.uuid4().hex[:4]}"
            # Ensure uniqueness
            while new_dev_id in engine._devices:
                new_dev_id = f"{old_dev_id}-copy-{uuid.uuid4().hex[:4]}"

            cloned_dev = DeviceConfig(
                id=new_dev_id,
                name=f"{dev_cfg.name} Copy",
                protocol=dev_cfg.protocol,
                template_id=dev_cfg.template_id,
                points=[p.model_copy() for p in dev_cfg.points],
                protocol_config=dict(dev_cfg.protocol_config) if dev_cfg.protocol_config else {},
            )
            try:
                await engine.create_device(cloned_dev)
                if db:
                    try:
                        await db.save_device(cloned_dev)
                    except Exception as db_err:
                        logger.warning("Failed to persist cloned device %s: %s", new_dev_id, db_err)
                cloned_device_ids.append(new_dev_id)
            except Exception as dev_err:
                logger.warning("Failed to clone device %s: %s", old_dev_id, dev_err)

    # Create cloned scenario config
    from protoforge.models.device import DeviceConfig as DC
    cloned_devices = []
    if clone_devices and original.devices:
        for i, dev_cfg in enumerate(original.devices):
            if i < len(cloned_device_ids):
                cloned_devices.append(DC(
                    id=cloned_device_ids[i],
                    name=f"{dev_cfg.name} Copy",
                    protocol=dev_cfg.protocol,
                    template_id=dev_cfg.template_id,
                    points=[p.model_copy() for p in dev_cfg.points],
                    protocol_config=dict(dev_cfg.protocol_config) if dev_cfg.protocol_config else {},
                ))

    cloned_config = ScenarioConfig(
        id=new_id,
        name=new_name,
        description=original.description,
        devices=cloned_devices,
        rules=[r.model_copy() if hasattr(r, 'model_copy') else r for r in original.rules],
    )

    try:
        result = await engine.create_scenario(cloned_config)
        if db:
            try:
                await db.save_scenario(cloned_config)
            except Exception as db_err:
                logger.exception("Failed to persist cloned scenario %s: %s", new_id, db_err)
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump) else result
        resp["cloned_from"] = scenario_id
        resp["cloned_device_ids"] = cloned_device_ids
        return resp
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to clone scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to clone scenario: {e}") from e


@router.get("/scenarios/{scenario_id}/export")
async def export_scenario(scenario_id: str, _user: dict[str, Any] = Depends(require_viewer)):
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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to export scenario %s: %s", scenario_id, e)
        raise HTTPException(status_code=500, detail="Failed to export scenario") from e  # FIXED: 中文→英文 from e


@router.post("/scenarios/import")
async def import_scenario(config: ScenarioConfig, _user: dict[str, Any] = Depends(require_operator)):
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
                logger.exception("Failed to persist imported scenario %s: %s", config.id, db_err)
        resp = result.model_dump() if hasattr(result, 'model_dump') and callable(result.model_dump) else result
        if not db_ok:
            resp["_persistence_warning"] = f"Scenario imported to memory, but persistence failed: {db_err_msg}. Data will be lost after restart."  # FIXED: 中文→英文
        return resp
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to import scenario: %s", e)
        raise HTTPException(status_code=500, detail="Failed to import scenario") from e  # FIXED: 中文→英文 from e


@router.get("/scenarios/{scenario_id}/snapshot")
async def get_scenario_snapshot(scenario_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_engine()
    try:
        config = engine.get_scenario_config(scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
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
