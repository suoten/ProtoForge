"""测试计划两次执行的对比视图（v1.10.0）：定位引入回归的变更。

对比粒度：套件级状态迁移（passed→failed 等）+ 汇总数字增减；
套件用例级明细在 TestRunner 报告里，随 report_id 可下钻。
"""

from __future__ import annotations

from typing import Any


_STATUS_ORDER = {"passed": 0, "failed": 1, "error": 2, "aborted": 3}


def compare_runs(run_a: dict[str, Any], run_b: dict[str, Any]) -> dict[str, Any]:
    """对比两次执行（dict 形态）：b 相对 a 的变化。a=旧，b=新。"""
    sa = run_a.get("results_summary") or {}
    sb = run_b.get("results_summary") or {}
    suites_a = {
        s.get("suite_id") or s.get("suite_name", ""): s
        for s in (run_a.get("report_data") or {}).get("suites", [])
    }
    suites_b = {
        s.get("suite_id") or s.get("suite_name", ""): s
        for s in (run_b.get("report_data") or {}).get("suites", [])
    }

    suite_changes: list[dict[str, Any]] = []
    for key, s_b in suites_b.items():
        s_a = suites_a.get(key)
        status_a = str(s_a.get("status", "-")).lower() if s_a else "new"
        status_b = str(s_b.get("status", "-")).lower()
        if status_a != status_b:
            suite_changes.append({
                "suite_id": key,
                "suite_name": s_b.get("suite_name") or key,
                "status_before": status_a,
                "status_after": status_b,
                "regression": _is_regression(status_a, status_b),
            })
    for key, s_a in suites_a.items():
        if key not in suites_b:
            suite_changes.append({
                "suite_id": key,
                "suite_name": s_a.get("suite_name") or key,
                "status_before": str(s_a.get("status", "-")).lower(),
                "status_after": "removed",
                "regression": False,
            })

    metric_keys = ("total", "passed", "failed", "errors", "skipped", "duration_seconds")
    metrics = {
        k: {"before": sa.get(k, 0), "after": sb.get(k, 0),
            "delta": (sb.get(k, 0) or 0) - (sa.get(k, 0) or 0)}
        for k in metric_keys
    }

    regressions = [c for c in suite_changes if c["regression"]]
    return {
        "run_a": {"id": run_a.get("id"), "status": run_a.get("status"),
                  "end_time": run_a.get("end_time")},
        "run_b": {"id": run_b.get("id"), "status": run_b.get("status"),
                  "end_time": run_b.get("end_time")},
        "metrics": metrics,
        "suite_changes": suite_changes,
        "regressions": regressions,
        "has_regression": bool(regressions)
        or (metrics["failed"]["delta"] > 0)
        or (metrics["errors"]["delta"] > 0),
    }


def _is_regression(before: str, after: str) -> bool:
    return _STATUS_ORDER.get(after, 9) > _STATUS_ORDER.get(before, 9)
