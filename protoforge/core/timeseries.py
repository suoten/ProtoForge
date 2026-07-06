"""时间序列模式生成器。

模拟真实工业生产中的时间序列数据特征，包括：
  - 日变化模式（白天生产、夜晚停机）
  - 周变化模式（工作日 vs 周末）
  - 季节性变化（年度周期）
  - 批次生产模式（升温→保温→降温→清洗）
  - 设备老化模型（性能随时间缓慢衰减）

这些模式可以叠加在基础数据生成器之上，为仿真数据增加
时间维度的真实性。

典型用法::

    from protoforge.core.timeseries import TimeSeriesPattern

    pattern = TimeSeriesPattern(
        pattern_type="daily",
        production_value=80.0,
        standby_value=20.0,
    )
    multiplier = pattern.get_multiplier()
    # multiplier 在工作时间(8-18)为 1.0 (production_value/base)，
    # 其他时间为 0.25 (standby_value/base)
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PatternType(str, Enum):
    """时间序列模式类型。"""

    DAILY = "daily"
    WEEKLY = "weekly"
    SEASONAL = "seasonal"
    BATCH = "batch"
    AGING = "aging"
    COMPOSITE = "composite"


@dataclass
class BatchPhase:
    """批次生产阶段定义。

    :param name: 阶段名称
    :param start_value: 阶段开始值
    :param end_value: 阶段结束值
    :param duration: 阶段持续时间 (s)
    """

    name: str
    start_value: float
    end_value: float
    duration: float


class TimeSeriesPattern:
    """时间序列模式生成器。

    根据当前时间返回一个乘数或偏移量，可叠加在基础生成值之上。

    :param pattern_type: 模式类型
    :param production_value: 生产时段的目标值
    :param standby_value: 待机时段的目标值
    :param base_value: 基准值（用于计算乘数），默认 100.0
    :param work_start_hour: 工作开始小时 (0-23)，默认 8
    :param work_end_hour: 工作结束小时 (0-23)，默认 18
    :param weekend_production: 周末是否生产，默认 False
    :param seasonal_amplitude: 季节性波动幅度 (0-1)，默认 0.2
    :param aging_rate: 老化速率（每年性能衰减比例），默认 0.02 (2%/年)
    :param install_time: 设备安装时间戳，默认为实例创建时间
    :param batch_phases: 批次生产阶段列表
    :param batch_cycle_time: 批次总周期时间 (s)
    :param offset_mode: 偏移模式 (True=加偏移, False=乘系数)，默认 False
    """

    def __init__(
        self,
        pattern_type: PatternType | str = PatternType.DAILY,
        production_value: float = 80.0,
        standby_value: float = 20.0,
        base_value: float = 100.0,
        work_start_hour: int = 8,
        work_end_hour: int = 18,
        weekend_production: bool = False,
        seasonal_amplitude: float = 0.2,
        aging_rate: float = 0.02,
        install_time: float | None = None,
        batch_phases: list[dict[str, Any]] | None = None,
        batch_cycle_time: float = 14400.0,
        offset_mode: bool = False,
    ):
        if isinstance(pattern_type, str):
            pattern_type = PatternType(pattern_type)
        self.pattern_type = pattern_type
        self.production_value = production_value
        self.standby_value = standby_value
        self.base_value = base_value if base_value != 0 else 100.0
        self.work_start_hour = work_start_hour
        self.work_end_hour = work_end_hour
        self.weekend_production = weekend_production
        self.seasonal_amplitude = seasonal_amplitude
        self.aging_rate = aging_rate
        self.install_time = install_time or time.time()
        self.batch_cycle_time = batch_cycle_time
        self.offset_mode = offset_mode

        # 解析批次阶段
        self._batch_phases: list[BatchPhase] = []
        if batch_phases:
            for p in batch_phases:
                self._batch_phases.append(BatchPhase(
                    name=p.get("name", ""),
                    start_value=float(p.get("start_value", 0)),
                    end_value=float(p.get("end_value", 0)),
                    duration=float(p.get("duration", 3600)),
                ))
            # 计算总周期
            total = sum(p.duration for p in self._batch_phases)
            if total > 0:
                self.batch_cycle_time = total

    def get_value(self, now: float | None = None) -> float:
        """返回当前时间的模式值（乘数或偏移量）。

        :param now: 当前时间戳，None 表示 time.time()
        :return: 模式值
        """
        if now is None:
            now = time.time()

        if self.pattern_type == PatternType.DAILY:
            return self._daily_value(now)
        elif self.pattern_type == PatternType.WEEKLY:
            return self._weekly_value(now)
        elif self.pattern_type == PatternType.SEASONAL:
            return self._seasonal_value(now)
        elif self.pattern_type == PatternType.BATCH:
            return self._batch_value(now)
        elif self.pattern_type == PatternType.AGING:
            return self._aging_value(now)
        elif self.pattern_type == PatternType.COMPOSITE:
            return self._composite_value(now)
        else:
            return 1.0 if not self.offset_mode else 0.0

    def get_multiplier(self, now: float | None = None) -> float:
        """返回乘数（始终为乘法模式）。"""
        if self.offset_mode:
            val = self.get_value(now)
            return (self.base_value + val) / self.base_value
        return self.get_value(now)

    def apply(self, base_value: float, now: float | None = None) -> float:
        """将模式效果应用到基础值上。

        :param base_value: 基础生成值
        :param now: 当前时间戳
        :return: 应用模式后的值
        """
        if self.offset_mode:
            return base_value + self.get_value(now)
        else:
            return base_value * self.get_multiplier(now)

    # -- 各模式实现 ---------------------------------------------------------

    def _daily_value(self, now: float) -> float:
        """日变化模式。"""
        import datetime
        dt = datetime.datetime.fromtimestamp(now)
        hour = dt.hour

        if self.work_start_hour <= hour < self.work_end_hour:
            target = self.production_value
        else:
            target = self.standby_value

        if self.offset_mode:
            return target - self.base_value
        return target / self.base_value

    def _weekly_value(self, now: float) -> float:
        """周变化模式。"""
        import datetime
        dt = datetime.datetime.fromtimestamp(now)
        weekday = dt.weekday()  # 0=Monday, 6=Sunday

        is_workday = weekday < 5  # 周一到周五
        if not is_workday and not self.weekend_production:
            target = self.standby_value
        else:
            target = self.production_value

        if self.offset_mode:
            return target - self.base_value
        return target / self.base_value

    def _seasonal_value(self, now: float) -> float:
        """季节性变化模式。"""
        import datetime
        dt = datetime.datetime.fromtimestamp(now)
        month = dt.month  # 1-12

        # 正弦波季节性：夏季高峰，冬季低谷
        seasonal_factor = 1.0 + self.seasonal_amplitude * math.sin(2 * math.pi * (month - 3) / 12)

        target = self.production_value * seasonal_factor

        if self.offset_mode:
            return target - self.base_value
        return target / self.base_value

    def _batch_value(self, now: float) -> float:
        """批次生产模式。"""
        if not self._batch_phases:
            return 1.0 if not self.offset_mode else 0.0

        elapsed = (now - self.install_time) % self.batch_cycle_time
        cumulative = 0.0

        for phase in self._batch_phases:
            cumulative += phase.duration
            if elapsed < cumulative:
                # 在当前阶段内
                phase_elapsed = elapsed - (cumulative - phase.duration)
                progress = phase_elapsed / phase.duration if phase.duration > 0 else 1.0
                # 线性插值
                value = phase.start_value + (phase.end_value - phase.start_value) * progress

                if self.offset_mode:
                    return value - self.base_value
                return value / self.base_value

        # 兜底
        last = self._batch_phases[-1]
        target = last.end_value
        if self.offset_mode:
            return target - self.base_value
        return target / self.base_value

    def _aging_value(self, now: float) -> float:
        """设备老化模型。

        性能随时间线性衰减，每年衰减 aging_rate。
        """
        years_elapsed = (now - self.install_time) / (365.25 * 24 * 3600)
        performance = max(0.1, 1.0 - self.aging_rate * years_elapsed)

        target = self.production_value * performance

        if self.offset_mode:
            return target - self.base_value
        return target / self.base_value

    def _composite_value(self, now: float) -> float:
        """组合模式：日 × 周 × 季节 × 老化。"""
        daily_mult = self._daily_value(now)
        weekly_mult = self._weekly_value(now)
        seasonal_mult = self._seasonal_value(now)
        aging_mult = self._aging_value(now)

        # 组合方式：取平均再乘以基准
        composite = (daily_mult + weekly_mult) / 2 * seasonal_mult * aging_mult

        if self.offset_mode:
            return composite * self.base_value - self.base_value
        return composite

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_type": self.pattern_type.value,
            "production_value": self.production_value,
            "standby_value": self.standby_value,
            "base_value": self.base_value,
            "work_start_hour": self.work_start_hour,
            "work_end_hour": self.work_end_hour,
            "weekend_production": self.weekend_production,
            "seasonal_amplitude": self.seasonal_amplitude,
            "aging_rate": self.aging_rate,
            "install_time": self.install_time,
            "batch_cycle_time": self.batch_cycle_time,
            "offset_mode": self.offset_mode,
            "batch_phases": [
                {"name": p.name, "start_value": p.start_value, "end_value": p.end_value, "duration": p.duration}
                for p in self._batch_phases
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimeSeriesPattern":
        return cls(
            pattern_type=PatternType(data.get("pattern_type", "daily")),
            production_value=data.get("production_value", 80.0),
            standby_value=data.get("standby_value", 20.0),
            base_value=data.get("base_value", 100.0),
            work_start_hour=data.get("work_start_hour", 8),
            work_end_hour=data.get("work_end_hour", 18),
            weekend_production=data.get("weekend_production", False),
            seasonal_amplitude=data.get("seasonal_amplitude", 0.2),
            aging_rate=data.get("aging_rate", 0.02),
            install_time=data.get("install_time"),
            batch_phases=data.get("batch_phases"),
            batch_cycle_time=data.get("batch_cycle_time", 14400.0),
            offset_mode=data.get("offset_mode", False),
        )


class TimeSeriesManager:
    """时间序列模式管理器。

    管理设备级别的时间序列模式，在数据生成时自动应用。

    用法::

        manager = TimeSeriesManager()
        manager.add_pattern("temperature", TimeSeriesPattern(
            pattern_type="daily",
            production_value=85.0,
            standby_value=25.0,
        ))
        # 在 tick 中
        raw_value = generator.generate(point)
        value = manager.apply(point.name, raw_value)
    """

    def __init__(self):
        self._patterns: dict[str, TimeSeriesPattern] = {}

    def add_pattern(self, point_name: str, pattern: TimeSeriesPattern) -> None:
        """为指定点位添加时间序列模式。"""
        self._patterns[point_name] = pattern
        logger.info("Time series pattern added for point %s: type=%s", point_name, pattern.pattern_type.value)

    def remove_pattern(self, point_name: str) -> bool:
        """移除点位的时间序列模式。"""
        if point_name in self._patterns:
            del self._patterns[point_name]
            return True
        return False

    def apply(self, point_name: str, base_value: float, now: float | None = None) -> float:
        """对点位值应用时间序列模式。

        如果点位没有配置模式，返回原始值。

        :param point_name: 点位名称
        :param base_value: 基础生成值
        :param now: 当前时间戳
        :return: 应用模式后的值
        """
        pattern = self._patterns.get(point_name)
        if pattern is None:
            return base_value
        try:
            return pattern.apply(base_value, now)
        except Exception as e:
            logger.warning("Time series pattern error for point %s: %s", point_name, e)
            return base_value

    def has_pattern(self, point_name: str) -> bool:
        """检查点位是否配置了时间序列模式。"""
        return point_name in self._patterns

    def get_pattern(self, point_name: str) -> TimeSeriesPattern | None:
        """获取点位的时间序列模式。"""
        return self._patterns.get(point_name)

    def get_all_patterns(self) -> dict[str, TimeSeriesPattern]:
        """返回所有时间序列模式。"""
        return dict(self._patterns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_count": len(self._patterns),
            "patterns": {k: v.to_dict() for k, v in self._patterns.items()},
        }
