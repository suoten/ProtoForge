"""v1.8.0 告警行为学测试（protoforge/simulation/alarm_behavior.py）。

覆盖规划验收的三个维度：告警风暴（吞吐/不丢失可测）、抖动 chattering
（防抖逻辑可测）、SOE 事件序列（时标排序可测）；另验证与
create_behavior 工厂（字典/字符串两种格式）的惰性分发接入。
"""

import pytest

from protoforge.simulation.alarm_behavior import (
    AlarmStormBehavior,
    ChatteringBehavior,
    SOESequenceBehavior,
)
from protoforge.simulation.behavior_models import create_behavior


# ---------------------------------------------------------------------------
# AlarmStorm
# ---------------------------------------------------------------------------

def test_storm_sustained_rate():
    """持续模式 100 条/秒 × 0.1s = 10 条（整数部分），余数累积不丢。"""
    storm = AlarmStormBehavior(mode="sustained", rate_per_second=100)
    b1 = storm.update(dt=0.1)
    assert len(b1) == 10
    b2 = storm.update(dt=0.1)
    assert len(b2) == 10
    assert b2[0]["index"] == 11  # 全局序号连续（不丢失）


def test_storm_burst_and_idle_cycle():
    """突发模式：burst 窗口内高频，idle 窗口静默。"""
    storm = AlarmStormBehavior(mode="burst", burst_rate_per_second=200,
                               burst_duration=1.0, idle_duration=9.0)
    burst_batch = storm.update(dt=0.5)   # 前半在 burst 窗口
    idle_batch = storm.update(dt=2.0)    # 已进入 idle
    assert len(burst_batch) == 100
    assert idle_batch == []


def test_storm_total_count_cap():
    storm = AlarmStormBehavior(mode="sustained", rate_per_second=50, total_count=23)
    total = 0
    for _ in range(10):
        total += len(storm.update(dt=1.0))
    assert total == 23  # 精确截断不超发


def test_storm_message_pool_and_validation():
    storm = AlarmStormBehavior(mode="sustained", rate_per_second=2,
                               messages=["高温", "低压"])
    batch = storm.update(dt=1.0)
    msgs = [a["message"] for a in batch]
    assert msgs == ["高温", "低压"]
    with pytest.raises(ValueError):
        AlarmStormBehavior(mode="nonsense")


# ---------------------------------------------------------------------------
# Chattering
# ---------------------------------------------------------------------------

def test_chattering_square_wave_flips():
    """period=1.0, duty=0.5：每秒翻转 1 次，2 秒共 1 次翻转+电平交替。"""
    chat = ChatteringBehavior(period=1.0, duty_cycle=0.5, start_on=True)
    levels = [chat.update(dt=0.25) for _ in range(8)]  # 2 秒
    assert chat.flip_count == 2
    assert levels[0] is True   # 高电平前 0.5s
    assert levels[4] is False  # 后 1s 进入低电平


def test_chattering_jitter_changes_flip_times():
    """jitter>0 时翻转时刻有随机偏移（两次运行翻转数可不同但量级一致）。"""
    strict = ChatteringBehavior(period=1.0, jitter=0.0, start_on=False)
    loose = ChatteringBehavior(period=1.0, jitter=0.9, start_on=False, seed=7)
    for _ in range(40):
        strict.update(dt=0.1)
        loose.update(dt=0.1)
    # period=1s 低电平占 0.5s：4s 内低->高翻转 4 次；jitter 使时刻偏移但量级一致
    assert strict.flip_count == 4
    assert 2 <= loose.flip_count <= 8


def test_chattering_param_validation():
    with pytest.raises(ValueError):
        ChatteringBehavior(period=0)
    with pytest.raises(ValueError):
        ChatteringBehavior(duty_cycle=1.5)


# ---------------------------------------------------------------------------
# SOE sequence
# ---------------------------------------------------------------------------

def test_soe_ordered_events_with_ms_resolution():
    """事件按 offset 升序到点；毫秒级时标分辨（15ms 间隔不并批丢失）。"""
    soe = SOESequenceBehavior(events=[
        {"name": "CB1_trip", "offset_ms": 0},
        {"name": "CB2_trip", "offset_ms": 15},
        {"name": "prot_relay", "offset_ms": 40},
    ])
    at5 = soe.update(dt=0.005)    # 5ms: 只有 CB1（offset 0）
    at25 = soe.update(dt=0.020)   # 25ms: CB2 到点
    at45 = soe.update(dt=0.020)   # 45ms: relay 到点
    assert [e["name"] for e in at5] == ["CB1_trip"]
    assert [e["name"] for e in at25] == ["CB2_trip"]
    assert [e["name"] for e in at45] == ["prot_relay"]
    # actual_ms 单调递增
    all_events = soe.fired_flat
    assert all(all_events[i]["actual_ms"] <= all_events[i + 1]["actual_ms"]
               for i in range(len(all_events) - 1))


def test_soe_unsorted_input_gets_sorted():
    """乱序输入自动按 offset 排序（顺序记录系统的输入鲁棒性）。"""
    soe = SOESequenceBehavior(events=[
        {"name": "late", "offset_ms": 100},
        {"name": "early", "offset_ms": 10},
    ])
    out = []
    out.extend(soe.update(dt=0.02))
    out.extend(soe.update(dt=0.2))
    assert [e["name"] for e in out] == ["early", "late"]


def test_soe_repeat_cycle():
    """repeat_interval 到期重播，lap 递增。"""
    soe = SOESequenceBehavior(events=[{"name": "E1", "offset_ms": 0}],
                              repeat_interval=1.0)
    first = soe.update(dt=0.5)
    soe.update(dt=0.6)            # 越过 1s 周期 → 重置
    second = soe.update(dt=0.1)
    assert first and second
    assert second[0]["lap"] == 1
    assert first[0]["lap"] == 0


def test_soe_time_scale():
    """time_scale=10 → 十倍速：真实 0.1s 推进 SOE 时标 1000ms。"""
    soe = SOESequenceBehavior(events=[{"name": "E", "offset_ms": 100}],
                              time_scale=10.0)
    out = soe.update(dt=0.1)
    assert out and out[0]["actual_ms"] >= 100


# ---------------------------------------------------------------------------
# 工厂接入（字典 / 字符串两种格式）
# ---------------------------------------------------------------------------

def test_factory_dict_and_string_forms():
    storm = create_behavior({"behavior": "alarm_storm",
                             "params": {"mode": "sustained", "rate_per_second": 10}})
    assert isinstance(storm, AlarmStormBehavior)
    chat = create_behavior("chattering:period=1.0")
    assert isinstance(chat, ChatteringBehavior)
    assert create_behavior("unknown_behavior:x=1") is None


def test_new_behaviors_serializable():
    """to_dict/from_dict 往返：params + 进度指针恢复（fired_flat 是运行期
    观测缓存，不属于持久化状态——恢复后从断点继续而非重放历史）。"""
    soe = SOESequenceBehavior(events=[
        {"name": "E1", "offset_ms": 0}, {"name": "E2", "offset_ms": 50}])
    soe.update(dt=0.01)          # 只有 E1 到点（10ms < 50ms）
    data = soe.to_dict()
    clone = SOESequenceBehavior.from_dict(data)
    assert clone.get_state()["fired"] == 1          # 进度指针恢复
    assert clone.get_state()["_type"] == "SOESequenceBehavior"
    # 从断点继续：再推进 100ms → E2 到点，不重发 E1
    tail = clone.update(dt=0.1)
    assert [e["name"] for e in tail] == ["E2"]
    assert all(e["name"] != "E1" for e in clone.fired_flat)
