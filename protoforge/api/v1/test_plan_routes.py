"""Test plan management API routes.

Provides CRUD operations for test plans, execution, and report retrieval.
"""

import logging
import threading
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response

from protoforge.api.v1._helpers import _get_database, _get_engine
from protoforge.api.v1.auth import require_user, require_viewer

router = APIRouter()
logger = logging.getLogger(__name__)

_plan_manager = None
_plan_manager_lock = threading.Lock()
_plan_runner = None


def _get_plan_manager():
    global _plan_manager
    with _plan_manager_lock:
        if _plan_manager is None:
            from protoforge.testing.plan import TestPlanManager
            _plan_manager = TestPlanManager()
            try:
                db = _get_database()
                _plan_manager.set_database(db)
            except RuntimeError:
                pass
        return _plan_manager


def _get_plan_runner():
    global _plan_runner
    if _plan_runner is None:
        from protoforge.testing.runner import PlanRunner
        _plan_runner = PlanRunner(_get_plan_manager())
    return _plan_runner


async def _ensure_plans_loaded():
    """Load plans from DB on first access."""
    mgr = _get_plan_manager()
    if not mgr._plans and mgr._db:
        await mgr.load_from_db()


# ─── Test Plan CRUD ────────────────────────────────────────────────────


@router.post("/test-plans")
async def create_test_plan(plan_def: dict[str, Any], _user: dict[str, Any] = Depends(require_user)):
    """Create a new test plan."""
    if not plan_def.get("name"):
        raise HTTPException(status_code=400, detail="Plan name is required")
    await _ensure_plans_loaded()
    from protoforge.testing.plan import TestPlan
    plan = TestPlan.from_dict(plan_def)
    plan.created_by = _user.get("username", "admin")
    mgr = _get_plan_manager()
    await mgr.create_plan(plan)
    return plan.to_dict()


@router.get("/test-plans")
async def list_test_plans(
    status: str | None = None,
    _user: dict[str, Any] = Depends(require_viewer),
):
    """List all test plans, optionally filtered by status."""
    await _ensure_plans_loaded()
    mgr = _get_plan_manager()
    plans = mgr.list_plans(status=status)
    return {"plans": [p.to_dict() for p in plans]}


@router.get("/test-plans/{plan_id}")
async def get_test_plan(plan_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """Get a specific test plan by ID."""
    await _ensure_plans_loaded()
    mgr = _get_plan_manager()
    plan = mgr.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Test plan not found: {plan_id}")
    return plan.to_dict()


@router.put("/test-plans/{plan_id}")
async def update_test_plan(
    plan_id: str,
    updates: dict[str, Any],
    _user: dict[str, Any] = Depends(require_user),
):
    """Update an existing test plan."""
    await _ensure_plans_loaded()
    mgr = _get_plan_manager()
    try:
        plan = await mgr.update_plan(plan_id, updates)
        return plan.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/test-plans/{plan_id}")
async def delete_test_plan(plan_id: str, _user: dict[str, Any] = Depends(require_user)):
    """Delete a test plan."""
    await _ensure_plans_loaded()
    mgr = _get_plan_manager()
    if not await mgr.delete_plan(plan_id):
        raise HTTPException(status_code=404, detail=f"Test plan not found: {plan_id}")
    return {"status": "ok"}


@router.post("/test-plans/{plan_id}/clone")
async def clone_test_plan(
    plan_id: str,
    body: dict[str, Any] | None = None,
    _user: dict[str, Any] = Depends(require_user),
):
    """Clone a test plan with a new ID."""
    await _ensure_plans_loaded()
    mgr = _get_plan_manager()
    new_name = (body or {}).get("name")
    try:
        cloned = mgr.clone_plan(plan_id, new_name)
        await mgr.create_plan(cloned)
        return cloned.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ─── Test Plan Execution ──────────────────────────────────────────────


@router.post("/test-plans/{plan_id}/run")
async def run_test_plan(
    plan_id: str,
    body: dict[str, Any] | None = None,
    _user: dict[str, Any] = Depends(require_user),
):
    """Execute a test plan and return the test run result."""
    await _ensure_plans_loaded()
    mgr = _get_plan_manager()
    plan = mgr.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Test plan not found: {plan_id}")

    cfg = body or {}
    trigger_source = cfg.get("trigger_source", "manual")

    # Get test runner for executing suites
    from protoforge.api.v1.test_routes import _get_test_runner, _get_internal_client
    test_runner = _get_test_runner()
    api_client = await _get_internal_client()

    runner = _get_plan_runner()
    run = await runner.execute_plan(
        plan,
        triggered_by=_user.get("username", "admin"),
        trigger_source=trigger_source,
        test_runner=test_runner,
        api_client=api_client,
    )
    return run.to_dict()


@router.post("/test-runs/{run_id}/abort")
async def abort_test_run(run_id: str, _user: dict[str, Any] = Depends(require_user)):
    """Abort a running test plan execution."""
    mgr = _get_plan_manager()
    if not mgr.request_abort(run_id):
        raise HTTPException(status_code=404, detail=f"Test run not found or already completed: {run_id}")
    return {"status": "ok", "message": "Abort requested"}


@router.get("/test-plans/{plan_id}/runs")
async def list_plan_runs(
    plan_id: str,
    limit: int = Query(20, ge=1, le=200),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """List execution history for a test plan."""
    mgr = _get_plan_manager()
    runs = mgr.list_runs(plan_id=plan_id, limit=limit)
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/test-runs/{run_id}")
async def get_test_run(run_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """Get details of a specific test run."""
    mgr = _get_plan_manager()
    run = mgr.get_run(run_id)
    if not run:
        # Try loading from DB
        db = _get_database()
        try:
            data = await db.load_test_run(run_id)
            if data:
                from protoforge.testing.plan import TestRun
                run = TestRun.from_dict(data)
        except Exception:
            pass
    if not run:
        raise HTTPException(status_code=404, detail=f"Test run not found: {run_id}")
    return run.to_dict()


@router.get("/test-runs/{run_id}/report")
async def get_test_run_report(
    run_id: str,
    format: str = Query("json", pattern="^(json|junit|html)$"),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """Get test run report in various formats (json/junit/html)."""
    mgr = _get_plan_manager()
    run = mgr.get_run(run_id)
    if not run:
        db = _get_database()
        try:
            data = await db.load_test_run(run_id)
            if data:
                from protoforge.testing.plan import TestRun
                run = TestRun.from_dict(data)
        except Exception:
            pass
    if not run:
        raise HTTPException(status_code=404, detail=f"Test run not found: {run_id}")

    runner = _get_plan_runner()

    if format == "junit":
        xml = runner.generate_junit_xml(run)
        return Response(content=xml, media_type="application/xml", headers={
            "Content-Disposition": f'attachment; filename="test-results-{run_id}.xml"'
        })
    elif format == "html":
        return _generate_html_report(run)
    else:
        return runner.generate_json_report(run)


def _generate_html_report(run) -> dict:
    """Generate a simple HTML report."""
    from fastapi.responses import HTMLResponse
    summary = run.results_summary
    suites = run.report_data.get("suites", [])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Test Report - {run.plan_name}</title>
<style>
body {{ font-family: sans-serif; margin: 40px; background: #f5f5f5; }}
.header {{ background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
.summary {{ display: flex; gap: 20px; margin: 20px 0; }}
.card {{ background: #fff; padding: 16px 24px; border-radius: 8px; text-align: center; min-width: 100px; }}
.card.total {{ border-left: 4px solid #2080f0; }}
.card.passed {{ border-left: 4px solid #18a058; }}
.card.failed {{ border-left: 4px solid #d03050; }}
.card.errors {{ border-left: 4px solid #f0a020; }}
.card .num {{ font-size: 28px; font-weight: bold; }}
.card .label {{ font-size: 12px; color: #666; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; }}
th, td {{ padding: 10px 16px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #f0f0f0; font-weight: 600; }}
.status-passed {{ color: #18a058; font-weight: bold; }}
.status-failed {{ color: #d03050; font-weight: bold; }}
.status-error {{ color: #f0a020; font-weight: bold; }}
.status-skipped {{ color: #999; }}
</style></head><body>
<div class="header">
<h1>Test Report: {run.plan_name}</h1>
<p>Plan ID: {run.plan_id} | Version: {run.plan_version} | Run ID: {run.id}</p>
<p>Triggered by: {run.triggered_by} via {run.trigger_source}</p>
<p>Status: <strong>{run.status}</strong> | Duration: {summary.get('duration_seconds', 0)}s</p>
</div>
<div class="summary">
<div class="card total"><div class="num">{summary.get('total', 0)}</div><div class="label">Total</div></div>
<div class="card passed"><div class="num">{summary.get('passed', 0)}</div><div class="label">Passed</div></div>
<div class="card failed"><div class="num">{summary.get('failed', 0)}</div><div class="label">Failed</div></div>
<div class="card errors"><div class="num">{summary.get('errors', 0)}</div><div class="label">Errors</div></div>
</div>
<h2>Test Suites</h2>
<table>
<tr><th>Suite</th><th>Status</th><th>Total</th><th>Passed</th><th>Failed</th><th>Errors</th></tr>
"""
    for s in suites:
        status = s.get("status", "unknown")
        html += f"""<tr>
<td>{s.get('suite_name', 'Unknown')}</td>
<td class="status-{status}">{status}</td>
<td>{s.get('total', 0)}</td>
<td>{s.get('passed', 0)}</td>
<td>{s.get('failed', 0)}</td>
<td>{s.get('errors', 0)}</td>
</tr>"""
    html += "</table></body></html>"
    return HTMLResponse(content=html)
