"""v1.8.0 按天漂移与演示场景资产测试。"""

import json
from pathlib import Path

from protoforge.simulation.fault_injection import FaultInjector

SCENARIOS = Path(__file__).parent.parent / "examples" / "scenarios"


# ---------------------------------------------------------------------------
# SENSOR_DRIFT 时间单位（v1.8.0：day/hour 语义）
# ---------------------------------------------------------------------------

class _FakeRuntime:
    def __init__(self, start):
        self.drift_start = start
        self.stuck_value = None
        self.stuck_value_set = False


# FIXED(flake): drift 断言精度 1e-6，而 start=time.time()-N 与 _apply_drift
# 内部的 time.time() 两次取样跨秒边界时 elapsed ≠ 整数 N（全量回归负载下
# 实测复现）。三个测试统一用冻结时钟：elapsed 恒等于 N。
class _FrozenClock:
    def __init__(self, now: float):
        self.now = now

    def time(self) -> float:
        return self.now


def test_drift_day_unit(monkeypatch):
    """drift_unit="day"：drift_rate 语义为每天漂移量。86400 秒 = 精确 +rate。"""
    import time
    frozen = _FrozenClock(1_800_000_000.0)
    monkeypatch.setattr(time, "time", frozen.time)
    mgr = FaultInjector()
    rt = _FakeRuntime(frozen.now - 86400.0)  # 恰好一天前
    out = mgr._apply_drift(rt, 100.0, {"drift_rate": 2.5, "drift_unit": "day"})
    assert abs(out - 102.5) < 1e-6


def test_drift_hour_unit(monkeypatch):
    import time
    frozen = _FrozenClock(1_800_000_000.0)
    monkeypatch.setattr(time, "time", frozen.time)
    mgr = FaultInjector()
    rt = _FakeRuntime(frozen.now - 3600.0)  # 一小时前
    out = mgr._apply_drift(rt, 10.0, {"drift_rate": 3.0, "drift_unit": "hour"})
    assert abs(out - 13.0) < 1e-6


def test_drift_default_second_backcompat(monkeypatch):
    """缺省（无 drift_unit）保持旧行为：drift_rate × 秒。"""
    import time
    frozen = _FrozenClock(1_800_000_000.0)
    monkeypatch.setattr(time, "time", frozen.time)
    mgr = FaultInjector()
    rt = _FakeRuntime(frozen.now - 10.0)
    out = mgr._apply_drift(rt, 100.0, {"drift_rate": 0.5})
    assert abs(out - 105.0) < 1e-6


# ---------------------------------------------------------------------------
# 演示场景资产（规划验收：官方 3 个演示场景随版本发布）
# ---------------------------------------------------------------------------

def test_three_demo_scenarios_exist_and_valid():
    """锅炉房/产线/泵站三个演示场景 JSON 可被 ScenarioConfig 加载。"""
    from protoforge.models.scenario import ScenarioConfig
    files = sorted(SCENARIOS.glob("demo-*.json"))
    assert len(files) == 3, [f.name for f in files]
    names = set()
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        cfg = ScenarioConfig(**data)  # 校验失败即抛
        names.add(cfg.id)
        assert cfg.devices, f"{f.name} 无设备"
    assert names == {"demo-boiler", "demo-line", "demo-pump"}


def test_demo_scenarios_have_lifecycle_rules():
    """每个演示场景至少 1 条联动规则（演示价值的核心）。"""
    for f in sorted(SCENARIOS.glob("demo-*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["rules"], f"{f.name} 缺少联动规则"
