"""时间序列回放引擎（Time Series Replay）.

"真正的仿真"关键能力——从历史数据驱动仿真，而非随机生成。典型场景：

    - 回放昨天产线温度曲线，验证 EdgeLite 采集时序与异常检测
    - 回放 CSV 导出的 Modbus 寄存器历史值，复现现场故障
    - 加速回放（speed=10.0）快速验证长周期场景

支持两种数据格式：

1. **长格式**（一行一个点位）::

    [
      {"ts": 0, "device_id": "temp-sensor", "point": "temperature", "value": 25.0},
      {"ts": 0, "device_id": "fan", "point": "speed", "value": 0},
      {"ts": 1, "device_id": "temp-sensor", "point": "temperature", "value": 25.5}
    ]

2. **宽格式**（一行多个点位，键为 ``device_id.point``）::

    [
      {"ts": 0, "temp-sensor.temperature": 25.0, "fan.speed": 0},
      {"ts": 1, "temp-sensor.temperature": 25.5, "fan.speed": 0}
    ]

数据源可为内联 list[dict]、JSON 文件路径或 CSV 文件路径（按扩展名识别）。

回放采用拉取模式（pull-based）：``Scenario.tick()`` 每次调用 ``next_points()``
取一帧数据并写入设备点位。``speed`` 控制每次 tick 前进的帧数（>1 跳帧加速，
<1 多 tick 才前进一帧）。``loop=True`` 时到末尾后从头循环。
"""

from __future__ import annotations

import csv
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _coerce(value: str) -> Any:
    """CSV 字符串值类型推断：bool → int → float → str。"""
    if value is None:
        return None
    s = value.strip()
    if s == "":
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


class TimeSeriesReplay:
    """时间序列回放器。

    :param source: 内联数据列表 ``list[dict]`` 或文件路径（``.json``/``.csv``）。
    :param time_field: 时间戳字段名，默认 ``"ts"``。
    :param speed: 回放速度倍率，默认 ``1.0``。``>1`` 跳帧加速，``<1`` 减速。
    :param loop: 到末尾后是否循环，默认 ``False``。
    """

    def __init__(
        self,
        source: list[dict[str, Any]] | str,
        time_field: str = "ts",
        speed: float = 1.0,
        loop: bool = False,
    ):
        self._time_field = time_field
        self._speed = max(0.01, float(speed))
        self._loop = bool(loop)
        self._records: list[dict[str, Any]] = self._load(source)
        # 按时间戳分组（同一 ts 的记录归为一帧）
        self._frames: list[list[tuple[str, str, Any]]] = self._group_into_frames(self._records)
        self._index = 0
        self._step_accum = 0.0  # 累积小数步进，支持 speed<1

    def _load(self, source: list[dict[str, Any]] | str) -> list[dict[str, Any]]:
        if isinstance(source, list):
            return list(source)
        if not isinstance(source, str):
            raise ValueError(f"Unsupported replay source type: {type(source)}")
        if not os.path.isfile(source):
            raise FileNotFoundError(f"Replay source file not found: {source}")
        ext = os.path.splitext(source)[1].lower()
        if ext == ".json":
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError(f"JSON replay source must be a list, got {type(data)}")
            return data
        if ext == ".csv":
            with open(source, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                return [{k: _coerce(v) for k, v in row.items()} for row in reader]
        raise ValueError(f"Unsupported replay file extension: {ext} (use .json or .csv)")

    def _group_into_frames(self, records: list[dict[str, Any]]) -> list[list[tuple[str, str, Any]]]:
        """将记录按时间戳分组为帧，每帧是 ``[(device_id, point, value), ...]`` 列表。

        自动识别长格式（含 device_id/point/value 键）与宽格式（键含 ``.``）。
        """
        if not records:
            return []
        # 按时间戳排序
        sorted_records = sorted(records, key=lambda r: r.get(self._time_field, 0))
        frames: list[list[tuple[str, str, Any]]] = []
        current_ts: Any = None
        current_frame: list[tuple[str, str, Any]] = []
        for rec in sorted_records:
            ts = rec.get(self._time_field, 0)
            if current_ts is not None and ts != current_ts:
                if current_frame:
                    frames.append(current_frame)
                current_frame = []
            current_frame.extend(self._extract_points(rec))
            current_ts = ts
        if current_frame:
            frames.append(current_frame)
        logger.info("TimeSeriesReplay: loaded %d frames from %d records", len(frames), len(records))
        return frames

    def _extract_points(self, record: dict[str, Any]) -> list[tuple[str, str, Any]]:
        """从单条记录提取点位三元组 ``(device_id, point, value)``。"""
        points: list[tuple[str, str, Any]] = []
        # 长格式：device_id + point + value
        if "device_id" in record and "point" in record and "value" in record:
            dev = str(record["device_id"])
            pt = str(record["point"])
            points.append((dev, pt, record["value"]))
            return points
        # 宽格式：键含 "."，形如 "device_id.point"
        for key, value in record.items():
            if key == self._time_field:
                continue
            if "." in key:
                dev, pt = key.split(".", 1)
                points.append((dev, pt, value))
        return points

    def start(self) -> None:
        """初始化回放位置到起点。"""
        self._index = 0
        self._step_accum = 0.0
        logger.info("TimeSeriesReplay started: %d frames, speed=%.2f, loop=%s", len(self._frames), self._speed, self._loop)

    def next_points(self) -> list[tuple[str, str, Any]] | None:
        """取当前帧的点位列表，并按 speed 前进位置。

        :return: ``[(device_id, point, value), ...]`` 或 ``None``（已耗尽且不循环）。
        """
        if not self._frames:
            return None
        if self._index >= len(self._frames):
            if self._loop:
                self._index = 0
            else:
                return None
        frame = self._frames[self._index]
        # 累积步进：speed>=1 时每次前进 int(speed) 帧；speed<1 时累积才前进
        self._step_accum += self._speed
        advance = int(self._step_accum)
        self._step_accum -= advance
        self._index += max(1, advance) if advance == 0 else advance
        return frame

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def exhausted(self) -> bool:
        return not self._loop and self._index >= len(self._frames)
