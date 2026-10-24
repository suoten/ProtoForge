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


def test_drift_day_unit():
    """drift_unit="day"：drift_rate 语义为每天漂移量。86400 秒 = 精确 +rate。"""
    import time
    mgr = FaultInjector()
    start = time.time() - 86400.0  # 恰好一天前
    rt = _FakeRuntime(start)
    out = mgr._apply_drift(rt, 100.0, {"drift_rate": 2.5, "drift_unit": "day"})
    assert abs(out - 102.5) < 1e-6


def test_drift_hour_unit():
    import time
    mgr = FaultInjector()
    rt = _FakeRuntime(time.time() - 3600.0)  # 一小时前
    out = mgr._apply_drift(rt, 10.0, {"drift_rate": 3.0, "drift_unit": "hour"})
    assert abs(out - 13.0) < 1e-6


def test_drift_default_second_backcompat():
    """缺省（无 drift_unit）保持旧行为：drift_rate × 秒。"""
    import time
    mgr = FaultInjector()
    rt = _FakeRuntime(time.time() - 10.0)
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
