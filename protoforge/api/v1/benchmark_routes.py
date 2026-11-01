"""性能基准 API（v1.11.0）：场景执行（后台任务）/ 结果列表 / 对比门禁。

POST /benchmarks/run 立即返回 bench_id（后台执行，防大场景阻塞事件循环），
GET /benchmarks/{id} 查询状态与结果；GET /benchmarks/compare?a=&b= 做同场景
两次结果的回退判定（延迟/时长类回退 >10% 记 regression，供 CI 门禁）。
"""

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_user, require_viewer
from protoforge.benchmark.runner import BenchmarkRunner, compare_by_ids
from protoforge.benchmark.scenarios import BUILTIN_SCENARIOS, SCENARIO_REGISTRY

router = APIRouter()
logger = logging.getLogger(__name__)

_runner = BenchmarkRunner()
_tasks: dict[str, dict[str, Any]] = {}  # bench_id -> {"status", "result", "error", "started"}

_MAX_CONCURRENT_RUNS = 1  # 基准独占资源：同时只跑一个，避免互相污染数字


@router.get("/benchmarks/scenarios")
async def list_scenarios(_user: dict[str, Any] = Depends(require_viewer)):
    return {"scenarios": BUILTIN_SCENARIOS()}


@router.post("/benchmarks/run")
async def run_benchmark(body: dict[str, Any],
                        _user: dict[str, Any] = Depends(require_user)):
    """后台执行基准场景。body: {scenario, params?, label?} → {id, status}"""
    scenario = str(body.get("scenario", "")).strip()
    if scenario not in SCENARIO_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario: {scenario}. "
                   f"Available: {', '.join(sorted(SCENARIO_REGISTRY))}")
    running = [t for t in _tasks.values() if t["status"] == "running"]
    if len(running) >= _MAX_CONCURRENT_RUNS:
        raise HTTPException(status_code=409,
                            detail="另一个基准正在执行（基准独占资源，请稍后再试）")
    params = body.get("params") or {}
    label = str(body.get("label", ""))

    async def _job():
        entry = _tasks[bench_id]
        try:
            result = await _runner.run(scenario, params=params, save=True, label=label)
            entry["result"] = result
            entry["status"] = "completed"
        except Exception as e:
            logger.exception("benchmark %s failed: %s", bench_id, e)
            entry["status"] = "failed"
            entry["error"] = f"{type(e).__name__}: {e}"

    bench_id = time.strftime("%Y%m%d%H%M%S") + "-" + scenario.replace("_", "-")[:20]
    _tasks[bench_id] = {"status": "running", "result": None, "error": None,
                        "started": time.time(), "scenario": scenario}
    asyncio.create_task(_job(), name=f"benchmark-{bench_id}")
    return {"id": bench_id, "status": "running", "scenario": scenario}


@router.get("/benchmarks")
async def list_benchmarks(scenario: str = "",
                          _user: dict[str, Any] = Depends(require_viewer)):
    """历史结果（data/benchmarks/ 持久化，含内存/延迟/吞吐）。"""
    return {"benchmarks": _runner.list_results(scenario or None)}


@router.get("/benchmarks/{bench_id}")
async def get_benchmark(bench_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    """查询单次结果；后台任务未完成时返回当前状态。"""
    entry = _tasks.get(bench_id)
    if entry and entry["status"] == "running":
        return {"id": bench_id, "status": "running",
                "elapsed": round(time.time() - entry["started"], 1)}
    if entry and entry["status"] == "failed":
        return {"id": bench_id, "status": "failed", "error": entry["error"]}
    try:
        result = _runner.load(bench_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404,
                            detail=f"Benchmark not found: {bench_id}") from None
    return {"id": bench_id, "status": "completed", "result": result}


@router.delete("/benchmarks/{bench_id}")
async def delete_benchmark(bench_id: str, _user: dict[str, Any] = Depends(require_user)):
    from protoforge.benchmark.runner import benchmark_results_dir
    path = benchmark_results_dir() / f"{bench_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Benchmark not found: {bench_id}")
    path.unlink()
    return {"deleted": True}


@router.get("/benchmarks/compare")
async def compare_benchmarks(a: str, b: str,
                             _user: dict[str, Any] = Depends(require_viewer)):
    """同场景两次结果对比：回退 >10% 的延迟/时长类指标记 regression。"""
    try:
        return compare_by_ids(a, b)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
