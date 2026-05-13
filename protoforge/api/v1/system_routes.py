import json
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_admin, require_viewer
from protoforge.api.v1._helpers import _get_engine, _get_template_manager, _get_database

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/setup/demo")
async def setup_demo(_user: dict = Depends(require_admin)):
    engine = _get_engine()
    tm = _get_template_manager()
    from protoforge.core.demo import seed_demo_data
    try:
        await seed_demo_data(engine, tm)
        devices = engine.get_all_device_ids()
        scenarios = engine.get_all_scenario_configs()
        return {
            "status": "ok",
            "message": "Demo data created",  # FIXED: 中文→英文
            "device_count": len(devices),
            "scenario_count": len(scenarios),
        }
    except Exception as e:
        from protoforge.core.defaults import get_friendly_error
        raise HTTPException(status_code=500, detail=get_friendly_error(str(e)))


@router.get("/setup/status")
async def setup_status(_user: dict = Depends(require_viewer)):
    try:
        engine = _get_engine()
        devices = engine.get_all_device_ids()
        scenarios = engine.get_all_scenario_configs()
        protocols_running = sum(1 for p in engine.get_all_protocol_servers().values() if p.status.value == "running")
        return {
            "initialized": len(devices) > 0,
            "demo_initialized": len(devices) > 0,
            "device_count": len(devices),
            "scenario_count": len(scenarios),
            "protocols_running": protocols_running,
            "templates_available": len(_get_template_manager().list_templates()),
        }
    except Exception as e:
        logger.error("Failed to get setup status: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get system status: {e}") from e


@router.get("/settings")
async def get_settings(_user: dict = Depends(require_admin)):
    try:
        from protoforge.config import get_all_settings_dict
        return get_all_settings_dict()
    except Exception as e:
        logger.error("Failed to get settings: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {e}") from e


_ALLOWED_SETTINGS_KEYS = {  # FIXED: update_settings字段白名单，防止修改敏感配置
    "demo_mode", "log_level", "cors_origins", "min_password_length",
    "rate_limit_max_requests", "rate_limit_window_seconds",
    "rate_limit_auth_max_requests", "rate_limit_auth_window_seconds",
    "edgelite_url", "edgelite_username", "edgelite_password",
    "influxdb_url", "influxdb_token", "influxdb_org", "influxdb_bucket",
    "forward_enabled", "forward_interval",
}


@router.put("/settings")
async def update_settings(updates: dict[str, Any], _user: dict = Depends(require_admin)):
    filtered = {k: v for k, v in updates.items() if k in _ALLOWED_SETTINGS_KEYS}  # FIXED: 过滤非法字段
    if not filtered:
        raise HTTPException(status_code=400, detail="No valid settings keys provided")
    try:
        from protoforge.config import update_settings as _update_settings, get_all_settings_dict, ConfigValidationError
        changed = _update_settings(filtered)
        return {"status": "ok", "changed": changed, "current": get_all_settings_dict()}
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail="; ".join(e.errors)) from e
    except Exception as e:
        logger.error("Failed to update settings: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {e}") from e


@router.get("/audit")
async def query_audit_log(
    username: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = 100,
    offset: int = 0,
    _user: dict = Depends(require_admin),
):
    try:
        if limit < 1 or limit > 10000:
            limit = min(max(limit, 1), 10000)
        if offset < 0:
            offset = 0
        from protoforge.core.audit import audit_logger
        entries, total = await audit_logger.query(
            username=username, action=action, resource_type=resource_type,
            start_time=start_time, end_time=end_time,
            limit=limit, offset=offset,
        )
        return {"entries": entries, "total": total}
    except Exception as e:
        logger.error("Failed to query audit log: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to query audit log: {e}") from e


@router.get("/audit/stats")
async def get_audit_stats(_user: dict = Depends(require_admin)):
    try:
        from protoforge.core.audit import audit_logger
        return await audit_logger.get_stats()
    except Exception as e:
        logger.error("Failed to get audit stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get audit stats: {e}") from e


@router.delete("/audit/{entry_id}")
async def delete_audit_entry(entry_id: int, _user: dict = Depends(require_admin)):
    try:
        from protoforge.core.audit import audit_logger
        deleted = await audit_logger.delete_entry(entry_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Audit entry not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete audit entry: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to delete audit entry: {e}") from e


@router.delete("/audit")
async def clear_audit_log(
    before: Optional[float] = None,
    _user: dict = Depends(require_admin),
):
    try:
        from protoforge.core.audit import audit_logger
        count = await audit_logger.clear_entries(before_timestamp=before)
        return {"status": "ok", "deleted": count}
    except Exception as e:
        logger.error("Failed to clear audit log: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to clear audit log: {e}") from e


@router.get("/backup")
async def export_backup(_user: dict = Depends(require_admin)):
    try:
        from fastapi.responses import Response
        db = _get_database()
        data = await db.export_all()
        backup = {
            "version": getattr(__import__('protoforge'), '__version__', '0.1.0'),
            "timestamp": time.time(),
            "data": data,
        }
        content = json.dumps(backup, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=protoforge_backup_{int(time.time())}.json"},
        )
    except Exception as e:
        logger.error("Failed to export backup: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to export backup: {e}") from e


@router.post("/backup/restore")
async def import_backup(payload: dict[str, Any], _user: dict = Depends(require_admin)):
    try:
        db = _get_database()
        data = payload.get("data", {})
        if not isinstance(data, dict):  # FIXED: 校验data类型必须为dict
            raise HTTPException(status_code=400, detail="Backup 'data' must be a dictionary")
        if not data:
            raise HTTPException(status_code=400, detail="No data found in backup")
        restored = await db.import_all(data)
        return {"status": "ok", "restored": restored}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to import backup: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {e}") from e
