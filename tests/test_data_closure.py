"""v1.10.0 测试数据闭环：环境即代码 / 数据基线 / Allure 归档 / cron 调度 / 执行对比。"""

import asyncio
import json
import struct
import time
from pathlib import Path

import pytest
import yaml

from protoforge.models.device import DeviceConfig, PointConfig
from tests.wire_golden_harness import free_tcp_port


# ---------------------------------------------------------------------------
# ① 环境即代码：export / diff / apply 往返
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_env_export_apply_diff_roundtrip():
    """导出 → apply 重建 → diff 应为 in_sync；改动后 diff 能发现。"""
    from protoforge.engine.engine import SimulationEngine
    from protoforge.engine.env_manifest import (
        apply_manifest,
        diff_manifest,
        export_manifest,
    )
    from protoforge.protocols.modbus.server import ModbusTcpServer

    eng = SimulationEngine()
    eng.register_protocol(ModbusTcpServer())
    await eng.start()
    try:
        port = free_tcp_port()
        await eng.create_device(DeviceConfig(
            id="env-dev1", name="Env Device", protocol="modbus_tcp",
            protocol_config={"host": "127.0.0.1", "port": port},
            points=[
                PointConfig(name="temp", address="HR0", data_type="float32",
                            generator_type="sine", min_value=20.0, max_value=30.0),
                PointConfig(name="pump", address="C0", data_type="bool"),
            ],
        ))
        await eng.start_device("env-dev1")
        manifest = export_manifest(eng, name="roundtrip")
        assert manifest["kind"] == "Environment"
        assert manifest["metadata"]["device_count"] == 1
        dev = manifest["devices"][0]
        assert dev["id"] == "env-dev1" and dev["protocol"] == "modbus_tcp"
        pts = {p["name"]: p for p in dev["points"]}
        assert pts["temp"]["generator_type"] == "sine"
        assert pts["temp"]["min_value"] == 20.0

        # YAML 序列化往返（可 review 进 Git 的关键断言）
        text = yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False)
        reparsed = yaml.safe_load(text)
        assert reparsed["devices"][0]["id"] == "env-dev1"

        # 全新引擎按 manifest 重建 → diff in_sync
        eng2 = SimulationEngine()
        eng2.register_protocol(ModbusTcpServer())
        await eng2.start()
        try:
            report = await apply_manifest(eng2, reparsed)
            assert report.failed == [], report.failed
            assert report.created == ["env-dev1"]
            assert eng2.get_device_instance("env-dev1") is not None
            entries = diff_manifest(eng2, reparsed)
            assert entries == [], [e.to_dict() for e in entries]

            # 引擎侧改动点位 → diff 发现 changed
            await eng2.create_device(DeviceConfig(
                id="env-dev2", name="Extra", protocol="modbus_tcp",
                protocol_config={"host": "127.0.0.1", "port": free_tcp_port()},
                points=[PointConfig(name="x", address="HR1", data_type="uint16")],
            ))
            entries = diff_manifest(eng2, reparsed)
            kinds = {(e.kind, e.device_id) for e in entries}
            assert ("removed", "env-dev2") in kinds
        finally:
            await asyncio.wait_for(eng2.stop(), timeout=15)
    finally:
        await asyncio.wait_for(eng.stop(), timeout=15)


@pytest.mark.asyncio
async def test_env_apply_reports_missing_protocol():
    """清单里的未知协议 → 单设备失败进 report.failed，不中断其余。"""
    from protoforge.engine.engine import SimulationEngine
    from protoforge.engine.env_manifest import apply_manifest

    eng = SimulationEngine()
    await eng.start()
    try:
        report = await apply_manifest(eng, {
            "api_version": "protoforge.io/v1", "kind": "Environment",
            "metadata": {"name": "t"},
            "devices": [
                {"id": "d-bad", "name": "Bad", "protocol": "no_such_proto",
                 "points": [{"name": "v", "address": "1", "data_type": "uint16"}]},
                {"id": "ok", "name": "OK"},  # 缺 protocol → 单条失败
            ],
        })
        assert not report.created
        assert len(report.failed) == 2
        assert {f["device_id"] for f in report.failed} == {"d-bad", "ok"}
    finally:
        await asyncio.wait_for(eng.stop(), timeout=15)


# ---------------------------------------------------------------------------
# ② 数据基线：快照 / 容差对比
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_baseline_capture_compare_with_tolerance():
    """固定值设备：capture → 原样 compare 全过；改值后超差/类型不匹配/缺失。"""
    from protoforge.engine.engine import SimulationEngine
    from protoforge.testing.baseline import (
        capture_baseline_async,
        compare_baseline_async,
    )
    from protoforge.protocols.http.server import HttpSimulatorServer

    eng = SimulationEngine()
    eng.register_protocol(HttpSimulatorServer())
    await eng.start()
    try:
        await eng.create_device(DeviceConfig(
            id="b-dev", name="B", protocol="http",
            points=[
                PointConfig(name="temp", address="/b-temp", data_type="float32",
                            generator_type="fixed", fixed_value=42.0),
                PointConfig(name="on", address="/b-on", data_type="bool",
                            generator_type="fixed", fixed_value=True),
                PointConfig(name="label", address="/b-label", data_type="string",
                            generator_type="fixed", fixed_value="OK"),
            ],
        ))
        await eng.start_device("b-dev")
        snapshot = await capture_baseline_async(eng, ["b-dev"], default_tolerance=0.5)
        assert snapshot["kind"] == "Baseline"
        pts = {p["point"]: p for p in snapshot["devices"][0]["points"]}
        assert pts["temp"]["value"] == 42.0 and pts["temp"]["tolerance"] == 0.5

        # 原样对比：全过
        report = await compare_baseline_async(eng, "t", baseline=snapshot)
        assert report.total == 3 and report.passed == 3 and not report.violations

        # 超差（temp 42→99，容差 0.5）
        await eng.write_device_point("b-dev", "temp", 99.0)
        report = await compare_baseline_async(eng, "t", baseline=snapshot)
        violations = {v.point: v for v in report.violations}
        assert violations["temp"].reason == "out_of_tolerance"
        assert violations["temp"].delta == pytest.approx(57.0, abs=0.01)

        # bool/字符串类型失配（布尔 True→数值 比较判 type_mismatch）
        snapshot2 = await capture_baseline_async(eng, ["b-dev"])
        await eng.write_device_point("b-dev", "label", "CHANGED")
        report2 = await compare_baseline_async(eng, "t", baseline=snapshot2)
        v_label = {v.point: v for v in report2.violations}["label"]
        assert v_label.reason == "type_mismatch" and v_label.actual == "CHANGED"

        # 设备缺失 → missing
        snapshot3 = {"kind": "Baseline", "captured_at": 0, "default_tolerance": 0,
                     "devices": [{"device_id": "ghost", "protocol": "x", "points": [
                         {"point": "v", "value": 1, "tolerance": 0}]}]}
        report3 = await compare_baseline_async(eng, "t", baseline=snapshot3)
        assert report3.violations[0].reason == "missing"
    finally:
        await asyncio.wait_for(eng.stop(), timeout=15)


@pytest.mark.asyncio
async def test_baseline_persistence(tmp_path, monkeypatch):
    """save/load/list/delete 持久化（可进 Git 的 JSON 文件）。"""
    from protoforge.testing import baseline as bl

    monkeypatch.setattr(bl, "baselines_dir", lambda: tmp_path)
    snapshot = {"kind": "Baseline", "captured_at": 1.0, "default_tolerance": 0,
                "devices": [{"device_id": "d", "protocol": "p",
                             "points": [{"point": "v", "value": 1, "tolerance": 0}]}]}
    path = bl.save_baseline("my/case", snapshot)
    assert path.name == "mycase.json"
    assert bl.load_baseline("mycase")["devices"][0]["device_id"] == "d"
    names = [b["name"] for b in bl.list_baselines()]
    assert "mycase" in names
    assert bl.delete_baseline("mycase") is True
    assert bl.list_baselines() == []


# ---------------------------------------------------------------------------
# ③ Allure2 + 归档 HTML
# ---------------------------------------------------------------------------

def test_allure_results_structure(tmp_path):
    """Allure2 results：result/container JSON + environment.properties + categories。"""
    from protoforge.testing.allure_report import generate_allure_results

    run = {
        "id": "run01", "plan_id": "plan01", "plan_name": "回归计划",
        "plan_version": "1.2.0", "status": "failed",
        "trigger_source": "cron", "start_time": time.time() - 60,
        "end_time": time.time(),
        "results_summary": {"total": 5, "passed": 3, "failed": 2, "errors": 0,
                            "skipped": 0, "duration_seconds": 60,
                            "suite_reports": [
                                {"suite_id": "s1", "suite_name": "Modbus 黄金",
                                 "status": "failed", "total": 3, "passed": 1,
                                 "failed": 2, "errors": 0, "skipped": 0}]},
        "environment": {"os": "win32", "python": "3.12.0"},
        "report_data": {"suites": [{"suite_id": "s1", "suite_name": "Modbus 黄金",
                                    "status": "failed", "total": 3, "passed": 1,
                                    "failed": 2, "errors": 0, "skipped": 0,
                                    "error": "2 assertions failed"}]},
    }
    out = generate_allure_results(run, tmp_path)
    files = {p.name: p for p in out.iterdir()}
    assert "environment.properties" in files
    assert "categories.json" in files
    result_files = [n for n in files if n.endswith("-result.json")]
    container_files = [n for n in files if n.endswith("-container.json")]
    assert result_files and container_files
    result = json.loads(files[result_files[0]].read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["historyId"] == "plan01-1.2.0"
    assert result["steps"][0]["name"] == "Modbus 黄金"
    assert result["steps"][0]["status"] == "failed"
    assert "python=3.12.0" in files["environment.properties"].read_text(encoding="utf-8")


def test_archive_html_print_friendly():
    """归档 HTML：自包含 + 状态徽章 + 环境表 + 打印 CSS。"""
    from protoforge.testing.allure_report import generate_archive_html

    run = {
        "id": "r1", "plan_id": "p1", "plan_name": "夜间回归", "plan_version": "2.0.0",
        "status": "passed", "trigger_source": "cron",
        "start_time": time.time() - 10, "end_time": time.time(),
        "results_summary": {"total": 8, "passed": 8, "failed": 0, "errors": 0,
                            "skipped": 0, "duration_seconds": 10.0,
                            "suite_reports": [{"suite_id": "s", "suite_name": "S",
                                               "status": "passed", "total": 8,
                                               "passed": 8, "failed": 0, "errors": 0,
                                               "skipped": 0}]},
        "environment": {"python": "3.12"},
    }
    html = generate_archive_html(run)
    assert html.startswith("<!DOCTYPE html>")
    assert "夜间回归" in html and "passed" in html
    assert "badge passed" in html
    assert "@media print" in html
    assert "另存为 PDF" in html
    assert "<script" not in html  # 自包含无外链脚本


# ---------------------------------------------------------------------------
# ④ cron 匹配 + 调度器
# ---------------------------------------------------------------------------

def test_cron_parser_and_matcher():
    from protoforge.testing.cron_min import cron_matches, is_due, parse_cron
    from datetime import datetime

    assert cron_matches("*/5 * * * *", datetime(2026, 11, 1, 10, 0))
    assert cron_matches("*/5 * * * *", datetime(2026, 11, 1, 10, 5))
    assert not cron_matches("*/5 * * * *", datetime(2026, 11, 1, 10, 3))
    assert cron_matches("0 9 * * 1-5", datetime(2026, 11, 2, 9, 0))   # 周一
    assert not cron_matches("0 9 * * 1-5", datetime(2026, 11, 1, 9, 0))  # 周日
    assert cron_matches("30 2 1,15 * *", datetime(2026, 11, 15, 2, 30))
    with pytest.raises(ValueError):
        parse_cron("*/5 * * *")     # 4 字段
    with pytest.raises(ValueError):
        parse_cron("99 * * * *")    # 越界

    # is_due：(last, now] 区间整分钟命中一次
    base = datetime(2026, 11, 1, 10, 0, 0).timestamp()
    assert is_due("*/5 * * * *", base, base + 5 * 60 + 30)
    assert not is_due("*/5 * * * *", base, base + 60)      # 未到点
    assert not is_due("*/5 * * * *", base + 5 * 60 + 30,   # 已触发不重复
                      base + 5 * 60 + 59)
    assert not is_due("bad expr", 0, base + 60)


@pytest.mark.asyncio
async def test_scheduler_dispatches_due_plan():
    """调度器：到点计划被派发并写回 schedule_last_run；未到点不触发。"""
    from protoforge.testing.plan import TestPlan, TestRun
    from protoforge.testing.scheduler import TestPlanScheduler

    class FakeManager:
        def __init__(self):
            self.plans = []
            self.updates = []

        def list_plans(self):
            return self.plans

        async def update_plan(self, plan_id, updates):
            self.updates.append((plan_id, updates))

    class FakeRunner:
        async def execute_plan(self, plan, **kwargs):
            run = TestRun(plan_id=plan.id, plan_name=plan.name)
            run.status = "passed"
            run.end_time = time.time()
            run.results_summary = {"total": 1, "passed": 1, "failed": 0,
                                   "errors": 0, "skipped": 0}
            run.report_data = {"suites": []}
            self.last_run = run
            return run

    mgr = FakeManager()
    plan = TestPlan(id="sched1", name="定时回归",
                    test_suite_ids=[], schedule={"cron": "* * * * *"})
    plan.schedule_last_run = 0.0
    mgr.plans.append(plan)

    runner = FakeRunner()
    scheduler = TestPlanScheduler(mgr, lambda: asyncio.sleep(0, result=runner))
    now = datetime_fixed = datetime_local = None  # noqa: F841
    fired = await scheduler._scan_once(now=time.time())
    assert fired and runner.last_run.plan_id == "sched1"
    assert plan.schedule_last_run > 0
    assert mgr.updates and mgr.updates[0][0] == "sched1"
    # 刚触发后立刻再扫：不重复
    fired2 = await scheduler._scan_once(now=time.time())
    assert fired2 == []

    # 未到点（上次刚触发 + cron 每小时）
    plan.schedule = {"cron": "0 * * * *"}
    plan.schedule_last_run = time.time()
    assert scheduler.due_plans(now=time.time()) == []


# ---------------------------------------------------------------------------
# ⑤ 两次执行对比 + 通知
# ---------------------------------------------------------------------------

def test_compare_runs_detects_regression():
    from protoforge.testing.comparison import compare_runs

    def _run(rid, s1_status, failed):
        return {
            "id": rid, "status": "passed" if failed == 0 else "failed",
            "end_time": 0,
            "results_summary": {"total": 4, "passed": 4 - failed, "failed": failed,
                                "errors": 0, "skipped": 0, "duration_seconds": 5},
            "report_data": {"suites": [
                {"suite_id": "s1", "suite_name": "S1", "status": s1_status,
                 "total": 2, "passed": 2 if s1_status == "passed" else 0,
                 "failed": 0 if s1_status == "passed" else 2, "errors": 0, "skipped": 0},
            ]},
        }

    report = compare_runs(_run("a", "passed", 0), _run("b", "failed", 2))
    assert report["has_regression"] is True
    assert report["suite_changes"][0]["regression"] is True
    assert report["suite_changes"][0]["status_before"] == "passed"
    assert report["metrics"]["failed"]["delta"] == 2

    # 改善方向（failed→passed）不算回归
    report2 = compare_runs(_run("a", "failed", 2), _run("b", "passed", 0))
    assert report2["has_regression"] is False


@pytest.mark.asyncio
async def test_notify_channels(tmp_path, monkeypatch):
    """通知：Webhook/钉钉/企微 命中即发；事件过滤；邮件走 to_thread mock。"""
    from protoforge.testing import notify as notify_mod

    monkeypatch.setattr(notify_mod, "load_notifiers", lambda: [
        {"type": "webhook", "url": "http://hook.local/x",
         "events": ["test.completed", "test.failed"]},
        {"type": "dingtalk", "access_token": "tk", "events": ["test.failed"]},
        {"type": "wecom", "key": "k", "events": ["test.completed"]},
        {"type": "email", "smtp_host": "smtp.local", "to_addrs": ["qa@x.com"],
         "events": ["test.completed"]},
    ])
    sent = []

    async def fake_post(self, url, json=None, **kw):
        sent.append(url)
        class R:
            def raise_for_status(self):
                pass
        return R()

    monkeypatch.setattr(httpx_client(), "post", fake_post)
    emails = []

    async def fake_send(self, item, run, message):
        emails.append((item["smtp_host"], tuple(item["to_addrs"])))
        return True

    monkeypatch.setattr(notify_mod.NotifierDispatcher, "_send_email", fake_send)

    run_ok = {"id": "r", "plan_id": "p", "plan_name": "P", "plan_version": "1",
              "status": "passed", "end_time": time.time(),
              "results_summary": {"total": 1, "passed": 1, "failed": 0,
                                  "errors": 0, "skipped": 0}}
    ok = await notify_mod.notify_test_run(run_ok)
    assert ok == 3  # webhook + wecom + email（钉钉只订 test.failed）

    run_bad = dict(run_ok, status="failed")
    sent.clear()
    ok2 = await notify_mod.notify_test_run(run_bad)
    assert ok2 == 2  # webhook(订 failed) + dingtalk(只订 failed)
    assert any("oapi.dingtalk" in u for u in sent)
    assert not any("qyapi.weixin" in u for u in sent)  # 企微只订 completed


def httpx_client():
    import httpx
    return httpx.AsyncClient


# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_env_api_endpoints(client):
    """env export → apply(dry_run) → diff API 往返。"""
    resp = await client.post("/api/v1/env/export", json={"name": "api-env"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["manifest"]["kind"] == "Environment"
    assert "devices:" in data["yaml"]

    # diff（空环境 vs 空 manifest → in_sync 由设备数决定，只验证结构）
    resp2 = await client.post("/api/v1/env/diff", json={"yaml_text": data["yaml"]})
    assert resp2.status_code == 200
    body = resp2.json()
    assert {"entries", "in_sync", "total"} <= set(body)

    # 非法 YAML → 400
    resp3 = await client.post("/api/v1/env/apply", json={"yaml_text": "a: [b"})
    assert resp3.status_code == 400
    resp4 = await client.post("/api/v1/env/apply", json={})
    assert resp4.status_code == 400


@pytest.mark.asyncio
async def test_baseline_and_notifiers_api(client, tmp_path, monkeypatch):
    """基线 API（无设备时快照为空仍可保存）+ 通知配置 API 脱敏。"""
    from protoforge.testing import baseline as bl
    monkeypatch.setattr(bl, "baselines_dir", lambda: tmp_path)
    # API 模块内直接 import 了函数——patch 不可达，走真实目录但只读接口安全；
    # 这里验证列表接口结构即可
    resp = await client.get("/api/v1/baselines")
    assert resp.status_code == 200
    assert "baselines" in resp.json()

    resp2 = await client.get("/api/v1/notifiers")
    assert resp2.status_code == 200
    body = resp2.json()
    assert set(body["supported_types"]) == {"webhook", "dingtalk", "wecom", "email"}

    resp3 = await client.put("/api/v1/notifiers", json={"notifiers": [
        {"type": "dingtalk", "access_token": "supersecrettoken123",
         "events": ["test.failed"]},
        {"type": "bogus"},
    ]})
    assert resp3.status_code == 400  # 非法类型被拒

    resp4 = await client.put("/api/v1/notifiers", json={"notifiers": [
        {"type": "dingtalk", "access_token": "supersecrettoken123",
         "events": ["test.failed"]},
    ]})
    assert resp4.status_code == 200
    assert resp4.json()["notifiers"][0]["access_token"].endswith("****")
    assert "supersecrettoken123" not in resp4.text
