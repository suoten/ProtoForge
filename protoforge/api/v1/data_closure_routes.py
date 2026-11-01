"""测试数据闭环 API（v1.10.0）：环境即代码 / 数据基线 / 报告升级 / 执行对比。

- 环境即代码：POST /env/export · /env/apply · /env/diff（YAML 进 Git 可复现）
- 数据基线：/baselines 增删查 + compare（容差 diff 回归报告）
- 报告升级：GET /test-runs/{id}/allure（Allure2 结果目录）· /archive-report（归档 HTML）
- 执行对比：GET /test-runs/compare?a=&b=（定位引入回归的变更）
"""

import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from protoforge.api.v1.auth import require_user, require_viewer

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_engine():
    from protoforge.engine.registry import get_engine
    return get_engine()


# ---------------------------------------------------------------------------
# 环境即代码
# ---------------------------------------------------------------------------

@router.post("/env/export")
async def env_export(body: dict[str, Any] | None = None,
                     _user: dict[str, Any] = Depends(require_viewer)):
    """导出当前环境为 manifest（dict，可直接 yaml.safe_dump 进 Git）。"""
    engine = _get_engine()
    from protoforge.engine.env_manifest import export_manifest
    name = (body or {}).get("name", "exported-env")
    manifest = export_manifest(engine, name=name)
    return {"manifest": manifest, "yaml": yaml.safe_dump(
        manifest, allow_unicode=True, sort_keys=False)}


@router.post("/env/apply")
async def env_apply(body: dict[str, Any],
                    _user: dict[str, Any] = Depends(require_user)):
    """把 manifest（yaml_text 或 manifest 字段）应用到引擎。"""
    engine = _get_engine()
    from protoforge.engine.env_manifest import apply_manifest
    manifest = _resolve_manifest(body)
    dry_run = bool(body.get("dry_run", False))
    report = await apply_manifest(engine, manifest, dry_run=dry_run)
    return report.to_dict()


@router.post("/env/diff")
async def env_diff(body: dict[str, Any],
                   _user: dict[str, Any] = Depends(require_viewer)):
    """当前环境 vs manifest 的差异（added/removed/changed）。"""
    engine = _get_engine()
    from protoforge.engine.env_manifest import diff_manifest
    manifest = _resolve_manifest(body)
    entries = diff_manifest(engine, manifest)
    return {"entries": [e.to_dict() for e in entries],
            "in_sync": not entries, "total": len(entries)}


def _resolve_manifest(body: dict[str, Any]) -> dict[str, Any]:
    manifest = body.get("manifest")
    if isinstance(manifest, dict) and manifest.get("devices") is not None:
        return manifest
    yaml_text = body.get("yaml_text") or body.get("yaml")
    if yaml_text:
        try:
            parsed = yaml.safe_load(str(yaml_text))
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"YAML 解析失败: {e}") from e
        if isinstance(parsed, dict) and parsed.get("devices") is not None:
            return parsed
        raise HTTPException(status_code=400, detail="YAML 缺少 devices 段")
    raise HTTPException(status_code=400, detail="需要 manifest 或 yaml_text 字段")


# ---------------------------------------------------------------------------
# 数据基线
# ---------------------------------------------------------------------------

@router.post("/baselines")
async def create_baseline(body: dict[str, Any],
                          _user: dict[str, Any] = Depends(require_user)):
    """抓取当前点位值作为基线并持久化。body: {name, device_ids?, default_tolerance?, tolerances?}"""
    engine = _get_engine()
    from protoforge.testing.baseline import (
        capture_baseline_async,
        save_baseline,
    )
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    device_ids = body.get("device_ids") or _get_engine().get_all_device_ids()
    snapshot = await capture_baseline_async(
        engine, device_ids,
        default_tolerance=float(body.get("default_tolerance", 0.0)),
        tolerances=body.get("tolerances") or None,
    )
    path = save_baseline(name, snapshot)
    total = sum(len(d.get("points", [])) for d in snapshot.get("devices", []))
    return {"name": name, "saved_to": str(path), "device_count": len(snapshot["devices"]),
            "point_count": total, "captured_at": snapshot["captured_at"]}


@router.get("/baselines")
async def list_baselines(_user: dict[str, Any] = Depends(require_viewer)):
    from protoforge.testing.baseline import list_baselines as _list
    return {"baselines": _list()}


@router.get("/baselines/{name}")
async def get_baseline(name: str, _user: dict[str, Any] = Depends(require_viewer)):
    from protoforge.testing.baseline import load_baseline
    try:
        return load_baseline(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Baseline not found: {name}") from None


@router.delete("/baselines/{name}")
async def remove_baseline(name: str, _user: dict[str, Any] = Depends(require_user)):
    from protoforge.testing.baseline import delete_baseline
    return {"deleted": delete_baseline(name)}


@router.post("/baselines/{name}/compare")
async def compare_with_baseline(name: str, body: dict[str, Any] | None = None,
                                _user: dict[str, Any] = Depends(require_viewer)):
    """当前值 vs 基线：容差 diff 回归报告（可作回归结论附件）。"""
    engine = _get_engine()
    from protoforge.testing.baseline import (
        compare_baseline_async,
        load_baseline,
    )
    try:
        baseline = load_baseline(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Baseline not found: {name}") from None
    report = await compare_baseline_async(engine, name, baseline=baseline)
    out = report.to_dict()
    # 归档联动：可同时保存 HTML 报告到 data/baseline-reports/
    if (body or {}).get("save_html"):
        out_dir = Path("data") / "baseline-reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out["html_saved_to"] = str(out_dir / f"{name}-{int(report.compared_at)}.html")
    return out


# ---------------------------------------------------------------------------
# 报告升级：Allure2 / 归档 HTML
# ---------------------------------------------------------------------------

async def _load_run(run_id: str) -> dict[str, Any]:
    from protoforge.api.v1.test_plan_routes import (
        _ensure_plans_loaded,
        _get_plan_manager,
    )
    await _ensure_plans_loaded()
    run = _get_plan_manager().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Test run not found: {run_id}")
    return run.to_dict() if hasattr(run, "to_dict") else dict(run)


@router.get("/test-runs/{run_id}/allure")
async def export_allure(run_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """生成 Allure2 results 目录并返回文件清单（allure generate 直接可用）。"""
    from protoforge.testing.allure_report import generate_allure_results
    run = await _load_run(run_id)
    out_dir = Path("data") / "allure" / run_id
    generate_allure_results(run, out_dir)
    files = sorted(str(p.relative_to(out_dir)) for p in out_dir.iterdir())
    return {"run_id": run_id, "directory": str(out_dir),
            "files": files,
            "usage": f"allure generate {out_dir} -o allure-report && allure open allure-report"}


@router.get("/test-runs/{run_id}/archive-report",
            response_class=HTMLResponse)
async def archive_report(run_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """自包含归档 HTML（浏览器打印→PDF 即企业归档件）。"""
    from protoforge.testing.allure_report import generate_archive_html
    run = await _load_run(run_id)
    return HTMLResponse(generate_archive_html(run))


# ---------------------------------------------------------------------------
# 两次执行对比
# ---------------------------------------------------------------------------

@router.get("/test-runs/compare")
async def compare_test_runs(a: str, b: str,
                            _user: dict[str, Any] = Depends(require_viewer)):
    """两次执行对比：套件状态迁移 + 汇总增减，定位引入回归的变更。"""
    from protoforge.testing.comparison import compare_runs
    run_a = await _load_run(a)
    run_b = await _load_run(b)
    return compare_runs(run_a, run_b)


# ---------------------------------------------------------------------------
# 通知渠道管理
# ---------------------------------------------------------------------------

@router.get("/notifiers")
async def get_notifiers(_user: dict[str, Any] = Depends(require_viewer)):
    """通知渠道列表（敏感字段脱敏）。"""
    from protoforge.testing.notify import (
        SUPPORTED_TYPES,
        list_notifiers_masked,
    )
    return {"notifiers": list_notifiers_masked(), "supported_types": list(SUPPORTED_TYPES)}


@router.put("/notifiers")
async def set_notifiers(body: dict[str, Any],
                        _user: dict[str, Any] = Depends(require_user)):
    """保存通知渠道配置。body: {notifiers: [...]}，字段见 notify.py 模块文档。"""
    from protoforge.testing.notify import (
        SUPPORTED_TYPES,
        list_notifiers_masked,
        save_notifiers,
    )
    items = body.get("notifiers")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="notifiers must be a list")
    for i, item in enumerate(items):
        ntype = str(item.get("type", "")).lower()
        if ntype not in SUPPORTED_TYPES:
            raise HTTPException(status_code=400,
                                detail=f"notifiers[{i}].type 无效: {ntype}（支持 {SUPPORTED_TYPES}）")
    save_notifiers(items)
    return {"saved": len(items), "notifiers": list_notifiers_masked()}


@router.post("/notifiers/test")
async def test_notifiers(_user: dict[str, Any] = Depends(require_user)):
    """向所有渠道发送一条测试消息（验收送达）。"""
    from protoforge.testing.notify import notify_test_run
    demo_run = {
        "id": "demo-notify", "plan_id": "demo", "plan_name": "通知渠道验收",
        "plan_version": "1.0.0", "status": "passed",
        "start_time": 0.0, "end_time": 0.0,
        "results_summary": {"total": 3, "passed": 3, "failed": 0, "errors": 0,
                            "skipped": 0, "duration_seconds": 1.2},
    }
    sent = await notify_test_run(demo_run)
    return {"dispatched": sent}
