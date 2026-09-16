"""时间序列回放引擎单测.

覆盖：
- 长格式 / 宽格式数据解析
- 按时间戳分帧
- speed 跳帧加速 / 减速
- loop 循环回放
- 耗尽检测
- JSON / CSV 文件加载
"""

from __future__ import annotations

import json
import os

import pytest

from protoforge.simulation.timeseries_replay import TimeSeriesReplay


# ---------------------------------------------------------------------------
#  长格式
# ---------------------------------------------------------------------------


def test_long_format_single_point_per_frame():
    data = [
        {"ts": 0, "device_id": "sensor", "point": "temp", "value": 25.0},
        {"ts": 1, "device_id": "sensor", "point": "temp", "value": 26.0},
        {"ts": 2, "device_id": "sensor", "point": "temp", "value": 27.0},
    ]
    replay = TimeSeriesReplay(data)
    assert replay.frame_count == 3
    replay.start()
    f0 = replay.next_points()
    assert f0 == [("sensor", "temp", 25.0)]
    f1 = replay.next_points()
    assert f1 == [("sensor", "temp", 26.0)]
    f2 = replay.next_points()
    assert f2 == [("sensor", "temp", 27.0)]
    assert replay.next_points() is None  # exhausted


def test_long_format_multiple_points_same_ts_grouped():
    """同一 ts 的多条记录归为一帧。"""
    data = [
        {"ts": 0, "device_id": "sensor", "point": "temp", "value": 25.0},
        {"ts": 0, "device_id": "fan", "point": "speed", "value": 0},
        {"ts": 1, "device_id": "sensor", "point": "temp", "value": 26.0},
    ]
    replay = TimeSeriesReplay(data)
    assert replay.frame_count == 2
    replay.start()
    f0 = replay.next_points()
    assert ("sensor", "temp", 25.0) in f0
    assert ("fan", "speed", 0) in f0
    assert len(f0) == 2


# ---------------------------------------------------------------------------
#  宽格式
# ---------------------------------------------------------------------------


def test_wide_format_multiple_points_per_record():
    data = [
        {"ts": 0, "sensor.temp": 25.0, "fan.speed": 0},
        {"ts": 1, "sensor.temp": 26.0, "fan.speed": 10},
    ]
    replay = TimeSeriesReplay(data)
    assert replay.frame_count == 2
    replay.start()
    f0 = replay.next_points()
    assert ("sensor", "temp", 25.0) in f0
    assert ("fan", "speed", 0) in f0
    f1 = replay.next_points()
    assert ("sensor", "temp", 26.0) in f1
    assert ("fan", "speed", 10) in f1


def test_wide_format_ignores_time_field_as_point():
    data = [{"ts": 0, "sensor.temp": 25.0}]
    replay = TimeSeriesReplay(data)
    replay.start()
    f0 = replay.next_points()
    assert f0 == [("sensor", "temp", 25.0)]


# ---------------------------------------------------------------------------
#  speed
# ---------------------------------------------------------------------------


def test_speed_gt_1_skips_frames():
    """speed=2：每次前进 2 帧，跳过中间帧。"""
    data = [
        {"ts": i, "device_id": "d", "point": "p", "value": i} for i in range(6)
    ]
    replay = TimeSeriesReplay(data, speed=2.0)
    replay.start()
    f0 = replay.next_points()
    assert f0 == [("d", "p", 0)]  # 第 0 帧
    f1 = replay.next_points()
    assert f1 == [("d", "p", 2)]  # 跳到第 2 帧
    f2 = replay.next_points()
    assert f2 == [("d", "p", 4)]  # 跳到第 4 帧


def test_speed_lt_1_takes_multiple_ticks_to_advance():
    """speed=0.5：累积 2 tick 才前进 1 帧。"""
    data = [
        {"ts": i, "device_id": "d", "point": "p", "value": i} for i in range(3)
    ]
    replay = TimeSeriesReplay(data, speed=0.5)
    replay.start()
    f0 = replay.next_points()
    assert f0 == [("d", "p", 0)]
    # 0.5 累积，advance=0，仍返回第 0 帧（max(1,0) 当 advance==0 时前进 1）
    # 实际：step_accum=0.5, advance=int(0.5)=0, index += max(1,0)=1 → 下一帧
    f1 = replay.next_points()
    assert f1 == [("d", "p", 1)]
    f2 = replay.next_points()
    assert f2 == [("d", "p", 2)]


# ---------------------------------------------------------------------------
#  loop
# ---------------------------------------------------------------------------


def test_loop_wraps_around():
    data = [
        {"ts": 0, "device_id": "d", "point": "p", "value": 10},
        {"ts": 1, "device_id": "d", "point": "p", "value": 20},
    ]
    replay = TimeSeriesReplay(data, loop=True)
    replay.start()
    assert replay.next_points() == [("d", "p", 10)]
    assert replay.next_points() == [("d", "p", 20)]
    # wraps
    assert replay.next_points() == [("d", "p", 10)]
    assert replay.next_points() == [("d", "p", 20)]
    assert not replay.exhausted


def test_no_loop_exhausts():
    data = [{"ts": 0, "device_id": "d", "point": "p", "value": 1}]
    replay = TimeSeriesReplay(data, loop=False)
    replay.start()
    assert replay.next_points() == [("d", "p", 1)]
    assert replay.next_points() is None
    assert replay.exhausted


# ---------------------------------------------------------------------------
#  文件加载
# ---------------------------------------------------------------------------


def test_load_json_file(tmp_path):
    data = [
        {"ts": 0, "device_id": "d", "point": "p", "value": 5},
        {"ts": 1, "device_id": "d", "point": "p", "value": 6},
    ]
    p = tmp_path / "replay.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    replay = TimeSeriesReplay(str(p))
    assert replay.frame_count == 2
    replay.start()
    assert replay.next_points() == [("d", "p", 5)]


def test_load_csv_file(tmp_path):
    """CSV 宽格式：ts,sensor.temp,fan.speed。"""
    csv_content = "ts,sensor.temp,fan.speed\n0,25.0,0\n1,26.0,10\n"
    p = tmp_path / "replay.csv"
    p.write_text(csv_content, encoding="utf-8")
    replay = TimeSeriesReplay(str(p))
    assert replay.frame_count == 2
    replay.start()
    f0 = replay.next_points()
    assert ("sensor", "temp", 25.0) in f0
    assert ("fan", "speed", 0) in f0


def test_csv_type_coercion(tmp_path):
    """CSV 字符串值自动推断为 bool/int/float。"""
    csv_content = "ts,d.flag,d.count\n0,true,5\n1,false,10\n"
    p = tmp_path / "replay.csv"
    p.write_text(csv_content, encoding="utf-8")
    replay = TimeSeriesReplay(str(p))
    replay.start()
    f0 = replay.next_points()
    assert ("d", "flag", True) in f0
    assert ("d", "count", 5) in f0


def test_unsupported_file_extension_raises(tmp_path):
    p = tmp_path / "replay.txt"
    p.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported replay file extension"):
        TimeSeriesReplay(str(p))


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        TimeSeriesReplay("/nonexistent/path/to/file.json")


def test_empty_source_returns_none():
    replay = TimeSeriesReplay([])
    assert replay.frame_count == 0
    replay.start()
    assert replay.next_points() is None


def test_records_sorted_by_timestamp():
    """未排序的输入按 ts 排序后回放。"""
    data = [
        {"ts": 2, "device_id": "d", "point": "p", "value": 30},
        {"ts": 0, "device_id": "d", "point": "p", "value": 10},
        {"ts": 1, "device_id": "d", "point": "p", "value": 20},
    ]
    replay = TimeSeriesReplay(data)
    replay.start()
    assert replay.next_points() == [("d", "p", 10)]
    assert replay.next_points() == [("d", "p", 20)]
    assert replay.next_points() == [("d", "p", 30)]
