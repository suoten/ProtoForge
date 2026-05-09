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
            "message": "演示数据已创建",
            "device_count": len(devices),
            "scenario_count": len(scenarios),
        }
    except Exception as e:
        from protoforge.core.defaults import get_friendly_error
        raise HTTPException(status_code=500, detail=get_friendly_error(str(e)))


@router.get("/setup/status")
async def setup_status(_user: dict = Depends(require_viewer)):
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


@router.get("/settings")
async def get_settings(_user: dict = Depends(require_admin)):
    from protoforge.config import get_all_settings_dict
    return get_all_settings_dict()


@router.put("/settings")
async def update_settings(updates: dict[str, Any], _user: dict = Depends(require_admin)):
    from protoforge.config import update_settings, get_all_settings_dict
    changed = update_settings(updates)
    return {"status": "ok", "changed": changed, "current": get_all_settings_dict()}


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
    from protoforge.core.audit import audit_logger
    entries = await audit_logger.query(
        username=username, action=action, resource_type=resource_type,
        start_time=start_time, end_time=end_time,
        limit=limit, offset=offset,
    )
    return {"entries": entries}


@router.get("/audit/stats")
async def get_audit_stats(_user: dict = Depends(require_admin)):
    from protoforge.core.audit import audit_logger
    return await audit_logger.get_stats()


@router.delete("/audit/{entry_id}")
async def delete_audit_entry(entry_id: int, _user: dict = Depends(require_admin)):
    from protoforge.core.audit import audit_logger
    deleted = await audit_logger.delete_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Audit entry not found")
    return {"status": "ok"}


@router.delete("/audit")
async def clear_audit_log(
    before: Optional[float] = None,
    _user: dict = Depends(require_admin),
):
    from protoforge.core.audit import audit_logger
    count = await audit_logger.clear_entries(before_timestamp=before)
    return {"status": "ok", "deleted": count}


@router.get("/backup")
async def export_backup(_user: dict = Depends(require_admin)):
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


@router.post("/backup/restore")
async def import_backup(payload: dict[str, Any], _user: dict = Depends(require_admin)):
    db = _get_database()
    data = payload.get("data", {})
    if not data:
        raise HTTPException(status_code=400, detail="No data found in backup")
    restored = await db.import_all(data)
    return {"status": "ok", "restored": restored}
