import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_template_manager, _get_database
from protoforge.models.template import TemplateDetail
from protoforge.models.device import DeviceConfig

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/templates")
async def list_templates(protocol: Optional[str] = None, _user: dict = Depends(require_viewer)):
    tm = _get_template_manager()
    return {"templates": tm.list_templates(protocol=protocol)}


@router.get("/templates/search")
async def search_templates(q: str = "", protocol: Optional[str] = None, tag: Optional[str] = None, _user: dict = Depends(require_viewer)):
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
    return {"templates": templates}


@router.get("/templates/tags")
async def list_template_tags(_user: dict = Depends(require_viewer)):
    tm = _get_template_manager()
    templates = tm.list_templates()
    tags = set()

    for t in templates:
        for tag in (t.tags or []):
            tags.add(tag)
    return {"tags": sorted(list(tags))}


@router.get("/templates/{template_id}", response_model=TemplateDetail)
async def get_template(template_id: str, _user: dict = Depends(require_viewer)):
    tm = _get_template_manager()

    try:
        return tm.get_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/templates")  # FIXED: 移除response_model=TemplateDetail，避免过滤_persistence_warning
async def create_template(template: TemplateDetail, _user: dict = Depends(require_operator)):
    tm = _get_template_manager()
    db = _get_database()
    try:  # FIXED: 添加异常处理
        tm.add_template(template)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    db_ok = True
    db_err_msg = ""
    if db:
        try:
            await db.save_template(template)
        except Exception as db_err:
            db_ok = False
            db_err_msg = str(db_err)
            logger.error("Failed to persist template %s: %s", template.id, db_err)
    resp = template.model_dump() if hasattr(template, 'model_dump') and callable(template.model_dump()) else template
    if not db_ok:
        resp["_persistence_warning"] = f"模板已创建，但数据持久化失败: {db_err_msg}。重启后数据将丢失。"
    return resp


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, _user: dict = Depends(require_operator)):
    tm = _get_template_manager()
    db = _get_database()
    try:
        tm.get_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:  # FIXED: 添加异常处理
        tm.remove_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db_ok = True
    db_err_msg = ""
    if db:
        try:
            await db.delete_template(template_id)
        except Exception as db_err:
            db_ok = False
            db_err_msg = str(db_err)
            logger.error("Failed to delete template %s from DB: %s", template_id, db_err)
    resp = {"status": "ok"}
    if not db_ok:
        resp["_persistence_warning"] = f"模板已从内存中删除，但数据库删除失败: {db_err_msg}。重启后模板可能重新出现。"
    return resp


@router.put("/templates/{template_id}")
async def update_template(template_id: str, data: dict[str, Any], _user: dict = Depends(require_operator)):
    tm = _get_template_manager()
    db = _get_database()
    try:
        tm.get_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    data["id"] = template_id
    updated = tm.update_template(template_id, data)
    db_ok = True
    db_err_msg = ""
    if db:
        try:
            await db.save_template(updated)
        except Exception as db_err:
            db_ok = False
            db_err_msg = str(db_err)
            logger.error("Failed to update template %s in DB: %s", template_id, db_err)
    resp = updated.model_dump() if hasattr(updated, 'model_dump') and callable(updated.model_dump()) else updated
    if not db_ok:
        resp["_persistence_warning"] = f"模板已在内存中更新，但数据持久化失败: {db_err_msg}。重启后更改将丢失。"
    return resp


@router.post("/templates/{template_id}/instantiate", response_model=DeviceConfig)
async def instantiate_template(
    template_id: str,
    device_id: str = Query(...),
    device_name: str = Query(...),
    body: Optional[dict[str, Any]] = None,
    _user: dict = Depends(require_operator),
):
    protocol_config = None
    if body:
        protocol_config = body.get("protocol_config")
    tm = _get_template_manager()

    try:
        return tm.create_device_from_template(template_id, device_id, device_name, protocol_config)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
