"""基准执行器与结果持久化（v1.11.0）。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 回退判定阈值（同指标相对回退超过该比例记 WARNING，供 CI 门禁）
REGRESSION_THRESHOLD = 0.10

# 指标语义：True=越高越好（吞吐类），False=越低越好（延迟/时长类）
_METRIC_LOWER_IS_BETTER = {
    "latency_p50_ms": True, "latency_p95_ms": True, "latency_p99_ms": True,
    "latency_avg_ms": True, "latency_max_ms": True,
    "tick_avg_ms": True, "tick_max_ms": True,
    "memory_rss_delta_mb": True, "errors": True,
}


def benchmark_results_dir() -> Path:
    from protoforge.core.paths import app_root
    d = app_root() / "data" / "benchmarks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def percentiles(samples_ms: list[float]) -> dict[str, float]:
    """P50/P95/P99/avg/max（毫秒）。空样本返回全 0。"""
    if not samples_ms:
        return {"latency_p50_ms": 0.0, "latency_p95_ms": 0.0,
                "latency_p99_ms": 0.0, "latency_avg_ms": 0.0,
                "latency_max_ms": 0.0}
    ordered = sorted(samples_ms)

    def _pct(p: float) -> float:
        # 线性插值分位（与 numpy 默认一致的简化版）
        idx = p / 100 * (len(ordered) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(ordered) - 1)
        frac = idx - lo
        return ordered[lo] * (1 - frac) + ordered[hi] * frac

    return {
        "latency_p50_ms": round(_pct(50), 3),
        "latency_p95_ms": round(_pct(95), 3),
        "latency_p99_ms": round(_pct(99), 3),
        "latency_avg_ms": round(sum(ordered) / len(ordered), 3),
        "latency_max_ms": round(ordered[-1], 3),
    }


def _env_fingerprint() -> dict[str, Any]:
    from protoforge import __version__
    env: dict[str, Any] = {
        "protoforge_version": __version__,
        "python": _python_version(),
        "platform": _platform_name(),
        "timestamp": time.time(),
    }
    try:
        import psutil
        env["cpu_count"] = psutil.cpu_count(logical=True)
        env["memory_rss_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024, 2)
    except Exception as e:  # psutil 缺失时降级（不阻塞基准）
        logger.debug("psutil unavailable for env fingerprint: %s", e)
    return env


def _python_version() -> str:
    import sys
    return sys.version.split()[0]


def _platform_name() -> str:
    import platform
    return f"{platform.system()}/{platform.machine()}"


class BenchmarkRunner:
    """执行场景 → 结构化结果 → 持久化（data/benchmarks/）。"""

    def __init__(self, results_dir: Path | None = None):
        self._dir = results_dir

    def _results_dir(self) -> Path:
        return self._dir if self._dir is not None else benchmark_results_dir()

    async def run(self, scenario: str, params: dict[str, Any] | None = None,
                  save: bool = True, label: str = "") -> dict[str, Any]:
        from protoforge.benchmark.scenarios import SCENARIO_REGISTRY

        params = dict(params or {})
        fn = SCENARIO_REGISTRY.get(scenario)
        if fn is None:
            raise ValueError(
                f"Unknown benchmark scenario: {scenario}. "
                f"Available: {', '.join(sorted(SCENARIO_REGISTRY))}")
        started = time.time()
        metrics = await fn(**params)
        result = {
            "id": uuid.uuid4().hex[:12],
            "scenario": scenario,
            "label": label or "",
            "params": params,
            "metrics": metrics,
            "duration_seconds": round(time.time() - started, 2),
            "env": _env_fingerprint(),
        }
        if save:
            self.save(result)
        return result

    def save(self, result: dict[str, Any]) -> Path:
        d = self._results_dir()
        path = d / f"{result['id']}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

    def list_results(self, scenario: str | None = None) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self._results_dir().glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                logger.debug("skip malformed benchmark result %s: %s", p.name, e)
                continue
            if scenario and data.get("scenario") != scenario:
                continue
            out.append({
                "id": data.get("id"),
                "scenario": data.get("scenario"),
                "label": data.get("label", ""),
                "timestamp": (data.get("env") or {}).get("timestamp", 0),
                "metrics": data.get("metrics", {}),
                "params": data.get("params", {}),
            })
        return sorted(out, key=lambda x: x.get("timestamp") or 0)

    def load(self, bench_id: str) -> dict[str, Any]:
        path = self._results_dir() / f"{bench_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def compare(result_a: dict[str, Any], result_b: dict[str, Any]) -> dict[str, Any]:
        """b 相对 a 的变化；延迟/时长类回退 >10% 记 regression（WARNING 级门禁）。"""
        ma, mb = result_a.get("metrics", {}), result_b.get("metrics", {})
        changes: list[dict[str, Any]] = []
        regressions: list[dict[str, Any]] = []
        for key, b_val in mb.items():
            a_val = ma.get(key)
            if not isinstance(b_val, (int, float)) or not isinstance(a_val, (int, float)):
                continue
            if a_val == b_val:
                continue
            lower_better = _METRIC_LOWER_IS_BETTER.get(key, False)
            base = abs(a_val) if a_val else None
            delta_pct = (b_val - a_val) / base if base else None
            change: dict[str, Any] = {
                "metric": key, "before": a_val, "after": b_val,
                "delta_pct": round(delta_pct, 4) if delta_pct is not None else None,
            }
            if delta_pct is not None and lower_better and delta_pct > REGRESSION_THRESHOLD:
                change["verdict"] = f"REGRESSION >{REGRESSION_THRESHOLD:.0%}"
                regressions.append(change)
            changes.append(change)
        return {
            "scenario": result_b.get("scenario"),
            "a": result_a.get("id"), "b": result_b.get("id"),
            "threshold": REGRESSION_THRESHOLD,
            "changes": changes,
            "regressions": regressions,
            "ok": not regressions,
        }


def compare_by_ids(bench_a: str, bench_b: str) -> dict[str, Any]:
    """按 id 加载两个结果并对比（API/CLI 用）。"""
    runner = BenchmarkRunner()
    return BenchmarkRunner.compare(runner.load(bench_a), runner.load(bench_b))
