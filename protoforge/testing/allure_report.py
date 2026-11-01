"""报告体系升级（v1.10.0）：Allure2 结果导出 + 自包含归档 HTML 报告。

- Allure2：生成 ``allure-results/`` 目录（每 suite 一个 result JSON +
  environment.properties + categories.json），``allure generate`` 直接可用，
  接入 QA 看板生态。
- 归档 HTML：自包含单文件（内联样式、打印友好 @media print——浏览器
  "打印 → 另存为 PDF" 即得企业归档 PDF），可直接作回归结论附件。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

_STATUS_MAP = {
    "passed": "passed",
    "failed": "failed",
    "error": "broken",
    "aborted": "broken",
    "skipped": "skipped",
}


def generate_allure_results(run: dict[str, Any], out_dir: str | Path) -> Path:
    """把一次 TestRun（dict 形态）导出为 Allure2 results 目录。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    summary = run.get("results_summary") or {}
    suites = (run.get("report_data") or {}).get("suites") \
        or summary.get("suite_reports") or []
    env = run.get("environment") or {}

    # environment.properties（Allure 环境面板）
    env_lines = []
    for k, v in env.items():
        if isinstance(v, (str, int, float, bool)):
            env_lines.append(f"{k}={v}")
    if env_lines:
        (out / "environment.properties").write_text(
            "\n".join(env_lines) + "\n", encoding="utf-8")

    # categories（把 failed/broken 归类，看板按类别聚合）
    (out / "categories.json").write_text(json.dumps([
        {"name": "Product defects", "matchedStatuses": ["failed"]},
        {"name": "Test defects", "matchedStatuses": ["broken"]},
    ], ensure_ascii=False), encoding="utf-8")

    start_ms = int(float(run.get("start_time") or time.time()) * 1000)
    end_ms = int(float(run.get("end_time") or time.time()) * 1000)
    stop_ms = max(start_ms, end_ms)

    result = {
        "uuid": uuid.uuid4().hex,
        "historyId": f"{run.get('plan_id', 'plan')}-{run.get('plan_version', '')}",
        "name": f"{run.get('plan_name') or run.get('plan_id', 'test plan')}",
        "fullName": f"protoforge.plan.{run.get('plan_id', 'plan')}",
        "status": _STATUS_MAP.get(str(run.get("status", "error")).lower(), "broken"),
        "start": start_ms,
        "stop": stop_ms,
        "duration": max(0, stop_ms - start_ms),
        "description": f"Test run {run.get('id', '')} "
                       f"(total={summary.get('total', 0)}, "
                       f"passed={summary.get('passed', 0)}, "
                       f"failed={summary.get('failed', 0)}, "
                       f"errors={summary.get('errors', 0)}, "
                       f"skipped={summary.get('skipped', 0)})",
        "labels": [
            {"name": "suite", "value": "ProtoForge Test Plan"},
            {"name": "plan", "value": str(run.get("plan_name") or run.get("plan_id", ""))},
            {"name": "plan_version", "value": str(run.get("plan_version", ""))},
            {"name": "trigger", "value": str(run.get("trigger_source", "manual"))},
        ],
        "steps": [],
        "attachments": [],
        "parameters": [],
        "links": [],
    }

    steps = []
    for s in suites:
        status = _STATUS_MAP.get(str(s.get("status", "skipped")).lower(), "broken")
        step = {
            "name": s.get("suite_name") or s.get("suite_id", "suite"),
            "status": status,
            "stage": "finished",
            "start": start_ms,
            "stop": stop_ms,
            "duration": max(0, stop_ms - start_ms),
        }
        if s.get("error"):
            step["statusDetails"] = {"message": str(s["error"])[:2000]}
        else:
            step["statusDetails"] = {
                "message": f"total={s.get('total', 0)} passed={s.get('passed', 0)} "
                           f"failed={s.get('failed', 0)} errors={s.get('errors', 0)} "
                           f"skipped={s.get('skipped', 0)}"}
        steps.append(step)
    result["steps"] = steps

    (out / f"{result['uuid']}-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # container 文件让 allure CLI 的测试用例树按 plan 聚合
    container = {
        "uuid": uuid.uuid4().hex,
        "children": [result["uuid"]],
    }
    (out / f"{container['uuid']}-container.json").write_text(
        json.dumps(container, ensure_ascii=False), encoding="utf-8")
    return out


_ARCHIVE_CSS = """
body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;margin:24px;color:#1a1a2e;}
h1{border-bottom:3px solid #2563eb;padding-bottom:8px;}
.badge{display:inline-block;padding:2px 12px;border-radius:12px;font-size:13px;color:#fff;}
.passed{background:#16a34a;} .failed{background:#dc2626;} .error,.aborted{background:#d97706;}
table{border-collapse:collapse;width:100%;margin:12px 0;}
th,td{border:1px solid #d1d5db;padding:6px 10px;text-align:left;font-size:14px;}
th{background:#f3f4f6;} tr:nth-child(even){background:#f9fafb;}
.kv{margin:6px 0;} .kv b{display:inline-block;min-width:140px;}
footer{margin-top:32px;color:#6b7280;font-size:12px;border-top:1px solid #e5e7eb;padding-top:8px;}
@media print{body{margin:8mm;font-size:12px;} h1{font-size:20px;}}
"""


def generate_archive_html(run: dict[str, Any]) -> str:
    """生成自包含归档 HTML（打印→PDF 友好）。run 为 TestRun.to_dict()。"""
    summary = run.get("results_summary") or {}
    suites = (run.get("report_data") or {}).get("suites") \
        or summary.get("suite_reports") or []
    env = run.get("environment") or {}
    status = str(run.get("status", "error")).lower()

    def _esc(x: Any) -> str:
        return (str(x).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    rows = []
    for s in suites:
        rows.append(
            f"<tr><td>{_esc(s.get('suite_name') or s.get('suite_id'))}</td>"
            f"<td><span class='badge {_esc(s.get('status'))}'>{_esc(s.get('status'))}</span></td>"
            f"<td>{_esc(s.get('total', '-'))}</td><td>{_esc(s.get('passed', '-'))}</td>"
            f"<td>{_esc(s.get('failed', '-'))}</td><td>{_esc(s.get('errors', '-'))}</td>"
            f"<td>{_esc(s.get('skipped', '-'))}</td>"
            f"<td>{_esc(s.get('error', '') or '')}</td></tr>")

    env_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
        for k, v in env.items() if isinstance(v, (str, int, float, bool)))

    start_ts = float(run.get("start_time") or 0)
    end_ts = float(run.get("end_time") or 0)
    generated = time.strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>ProtoForge 回归归档报告 - {_esc(run.get('plan_name') or run.get('id'))}</title>
<style>{_ARCHIVE_CSS}</style></head><body>
<h1>ProtoForge 回归归档报告</h1>
<p>
<span class='badge {status}'>{_esc(status)}</span>&nbsp;
测试计划 <b>{_esc(run.get('plan_name') or run.get('plan_id'))}</b>
（版本 {_esc(run.get('plan_version') or '-')}，Run {_esc(run.get('id'))}）
</p>
<div class='kv'><b>执行时间</b>{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_ts))}
　→　{time.strftime('%H:%M:%S', time.localtime(end_ts))}</div>
<div class='kv'><b>触发方式</b>{_esc(run.get('trigger_source') or run.get('triggered_by') or 'manual')}</div>
<div class='kv'><b>结果汇总</b>总计 {summary.get('total', 0)} ｜ 通过 {summary.get('passed', 0)}
｜ 失败 {summary.get('failed', 0)} ｜ 错误 {summary.get('errors', 0)}
｜ 跳过 {summary.get('skipped', 0)} ｜ 用时 {summary.get('duration_seconds', '-')}s</div>

<h2>测试套件明细</h2>
<table><tr><th>套件</th><th>状态</th><th>总计</th><th>通过</th><th>失败</th>
<th>错误</th><th>跳过</th><th>备注</th></tr>{''.join(rows)}</table>

<h2>执行环境</h2>
<table><tr><th>项</th><th>值</th></tr>{env_rows}</table>

<footer>Generated by ProtoForge v-archive on {generated} ·
本文件自包含，可直接归档或经浏览器"打印→另存为 PDF"生成 PDF 归档件</footer>
</body></html>"""
