"""v1.11.0 性能基准模块测试（小参数快速跑，不做耗时断言）。"""

import asyncio
import json

import pytest

from protoforge.benchmark import BUILTIN_SCENARIOS, SCENARIO_REGISTRY, run_scenario
from protoforge.benchmark.runner import (
    BenchmarkRunner,
    percentiles,
    REGRESSION_THRESHOLD,
)


def test_scenarios_registered():
    names = {s["name"] for s in BUILTIN_SCENARIOS()}
    assert names == set(SCENARIO_REGISTRY)
    assert "engine_tick_generation" in names
    assert "modbus_wire_read" in names


def test_unknown_scenario_raises():
    with pytest.raises(ValueError, match="Unknown benchmark scenario"):
        asyncio.get_event_loop  # noqa: B018 - 占位避免误删 import
        asyncio.run(run_scenario("no_such_scenario"))


def test_percentiles_shapes():
    assert percentiles([])["latency_p50_ms"] == 0.0
    p = percentiles([1.0] * 98 + [100.0, 200.0])
    assert p["latency_p50_ms"] == 1.0
    assert p["latency_max_ms"] == 200.0
    assert p["latency_p99_ms"] > 1.0


@pytest.mark.asyncio
async def test_engine_tick_scenario_small():
    result = await run_scenario("engine_tick_generation",
                                devices=5, points_per_device=5, ticks=2)
    assert result["devices"] == 5
    assert result["points_total"] == 25
    assert result["tick_avg_ms"] >= 0
    assert "memory_rss_delta_mb" in result


@pytest.mark.asyncio
async def test_modbus_wire_scenario_small():
    result = await run_scenario("modbus_wire_read", reads=20)
    assert result["reads"] == 20
    assert result["errors"] == 0
    assert result["latency_p50_ms"] > 0
    assert result["throughput_rps"] > 0


@pytest.mark.asyncio
async def test_modbus_concurrent_scenario_small():
    result = await run_scenario("modbus_concurrent_read",
                                clients=2, reads_per_client=10)
    assert result["reads_completed"] == 20
    assert result["errors"] == 0


def test_runner_save_list_load_compare(tmp_path):
    runner = BenchmarkRunner(results_dir=tmp_path)
    base = {
        "id": "aaa", "scenario": "modbus_wire_read", "label": "base",
        "params": {}, "metrics": {"latency_p95_ms": 1.0, "throughput_rps": 100},
        "duration_seconds": 1, "env": {"timestamp": 1, "python": "3", "platform": "t"},
    }
    same = dict(base, id="bbb", label="same")
    worse = dict(base, id="ccc", metrics={"latency_p95_ms": 2.0,
                                          "throughput_rps": 100})
    for r in (base, same, worse):
        runner.save(r)

    listed = runner.list_results("modbus_wire_read")
    assert [x["id"] for x in listed] == ["aaa", "bbb", "ccc"]

    # 持平 → ok
    cmp_same = BenchmarkRunner.compare(runner.load("aaa"), runner.load("bbb"))
    assert cmp_same["ok"] is True

    # 延迟翻倍 → regression（吞吐不参与回退判定：越高越好）
    cmp_bad = BenchmarkRunner.compare(runner.load("aaa"), runner.load("ccc"))
    assert cmp_bad["ok"] is False
    assert len(cmp_bad["regressions"]) == 1
    assert cmp_bad["regressions"][0]["metric"] == "latency_p95_ms"
    assert cmp_bad["regressions"][0]["delta_pct"] == pytest.approx(1.0)
    assert REGRESSION_THRESHOLD == 0.10


def test_compare_ignores_non_numeric():
    a = {"metrics": {"scenario_name": "x"}, "id": "a", "scenario": "s"}
    b = {"metrics": {"scenario_name": "y"}, "id": "b", "scenario": "s"}
    assert BenchmarkRunner.compare(a, b)["changes"] == []
