"""模板市场 v1（v1.16.0）：社区提交 + 管理员审核。

设计：批准的模板复用 v1.15 插件机制持久化——落盘
``<app_root>/data/plugins/contributed-templates/``（一个由市场自动维护的
template-pack），重启后由插件系统自动加载，无需独立持久层。

端点：
- POST /templates/contribute            社区提交（校验 + 查重 + 地址重叠检查）
- GET  /templates/contributions         提交清单（pending/approved/rejected/all）
- POST /templates/contributions/{cid}/approve   管理员批准（即刻生效 + 落盘）
- POST /templates/contributions/{cid}/reject    管理员拒绝（保留记录）
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1._helpers import (
    _get_template_manager,
    ensure_no_point_overlap,
)
from protoforge.api.v1.auth import require_admin, require_user, require_viewer
from protoforge.models.template import TemplateDetail

router = APIRouter()
logger = logging.getLogger(__name__)

_PLUGIN_DIR_NAME = "contributed-templates"


def _contrib_dir() -> Path:
    try:
        from protoforge.core.paths import app_root
        return Path(app_root()) / "data" / "template_contributions"
    except Exception:
        return Path("data") / "template_contributions"


def _approved_plugin_dir() -> Path:
    try:
        from protoforge.core.paths import app_root
        root = Path(app_root()) / "data" / "plugins" / _PLUGIN_DIR_NAME
    except Exception:
        root = Path("data") / "plugins" / _PLUGIN_DIR_NAME
    return root


def _ensure_approved_manifest() -> None:
    manifest = _approved_plugin_dir() / "plugin.json"
    if not manifest.exists():
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({
            "id": "contributed-templates",
            "name": "社区贡献模板",
            "version": "1.0.0",
            "kind": "template-pack",
            "description": "经管理员审核批准的社区提交模板（模板市场自动维护）",
            "templates": ["templates"],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_entry(cid: str) -> tuple[Path, dict[str, Any]]:
    f = _contrib_dir() / f"{cid}.json"
    if not f.exists() or not re.fullmatch(r"[a-zA-Z0-9._\-]+", cid):
        raise HTTPException(status_code=404, detail=f"提交不存在: {cid}")
    try:
        return f, json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交记录损坏: {e}")


@router.post("/templates/contribute")
async def contribute_template(body: dict[str, Any],
                              _user: dict[str, Any] = Depends(require_user)):
    """社区提交模板：结构校验、查重、点位重叠检查通过后进入待审队列。"""
    data = body.get("template") if isinstance(body.get("template"), dict) else body
    submitter = str(body.get("submitter") or _user.get("username") or "anonymous").strip()[:64]
    note = str(body.get("note", "")).strip()[:300]
    try:
        template = TemplateDetail(**data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"模板定义不合法: {e}")
    if not template.id or not template.protocol:
        raise HTTPException(status_code=422, detail="id 与 protocol 必填")
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", template.id):
        raise HTTPException(status_code=422, detail="id 仅允许字母/数字/下划线/连字符")
    tm = _get_template_manager()
    try:
        tm.get_template(template.id)
        raise HTTPException(status_code=409, detail=f"模板 id 已存在: {template.id}（请换一个 id）")
    except ValueError:
        pass
    try:
        ensure_no_point_overlap(template.protocol, template.points)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"点位地址重叠: {e}")

    _contrib_dir().mkdir(parents=True, exist_ok=True)
    cid = f"{time.strftime('%Y%m%d-%H%M%S')}-{template.id[:40]}"
    entry = {
        "id": cid, "status": "pending", "submitted_by": submitter,
        "submitted_at": time.time(), "note": note, "template": template.model_dump(),
    }
    (_contrib_dir() / f"{cid}.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Template contribution %s submitted by %s (%s, %d points)",
                cid, submitter, template.protocol, len(template.points))
    return {"ok": True, "contribution_id": cid, "status": "pending",
            "hint": "等待管理员审核；批准后模板即刻生效并随插件机制持久加载"}


@router.get("/templates/contributions")
async def list_contributions(status: str = "pending",
                             _user: dict[str, Any] = Depends(require_viewer)):
    """列出社区提交（status: pending | approved | rejected | all）。"""
    entries = []
    for f in sorted(_contrib_dir().glob("*.json")):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status != "all" and e.get("status") != status:
            continue
        tpl = e.get("template") or {}
        entries.append({
            "id": e.get("id"), "status": e.get("status"),
            "submitted_by": e.get("submitted_by"), "submitted_at": e.get("submitted_at"),
            "note": e.get("note"), "template_id": tpl.get("id"),
            "template_name": tpl.get("name"), "protocol": tpl.get("protocol"),
            "point_count": len(tpl.get("points") or []),
        })
    return {"contributions": entries, "total": len(entries)}


@router.post("/templates/contributions/{cid}/approve")
async def approve_contribution(cid: str, _user: dict[str, Any] = Depends(require_admin)):
    """管理员批准：模板即刻生效（add_template）并落盘到插件目录持久化。"""
    f, e = _load_entry(cid)
    if e.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"提交 {cid} 已处理（{e.get('status')}）")
    template = TemplateDetail(**e["template"])
    tm = _get_template_manager()
    try:
        tm.get_template(template.id)
        raise HTTPException(status_code=409, detail=f"模板 id 已存在: {template.id}")
    except ValueError:
        pass
    try:
        ensure_no_point_overlap(template.protocol, template.points)
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=f"点位地址重叠: {ex}")

    tm.add_template(template)
    _ensure_approved_manifest()
    out_dir = _approved_plugin_dir() / "templates" / template.protocol
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{template.id}.json").write_text(
        json.dumps(template.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    e["status"] = "approved"
    e["approved_by"] = _user.get("username", "")
    e["approved_at"] = time.time()
    f.write_text(json.dumps(e, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Template contribution %s approved -> %s", cid, template.id)
    return {"ok": True, "status": "approved", "template_id": template.id,
            "persisted_to_plugin": _PLUGIN_DIR_NAME}


@router.post("/templates/contributions/{cid}/reject")
async def reject_contribution(cid: str, _user: dict[str, Any] = Depends(require_admin)):
    """管理员拒绝：仅置状态（保留记录供提交者参考）。"""
    f, e = _load_entry(cid)
    if e.get("status") != "pending":
        raise HTTPException(status_code=409, detail=f"提交 {cid} 已处理（{e.get('status')}）")
    e["status"] = "rejected"
    e["approved_by"] = _user.get("username", "")
    e["approved_at"] = time.time()
    f.write_text(json.dumps(e, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "status": "rejected"}
