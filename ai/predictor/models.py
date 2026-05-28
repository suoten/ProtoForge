# -*- coding: utf-8 -*-
"""
predictor.models
~~~~~~~~~~~~~~~~
纯数据结构定义，不包含任何业务逻辑或 IO 操作。

包含：
- ``BaselineState``：单个指标的健康模板状态，记录周期、模板曲线、健康状态等
- ``MetricProfile``：从历史数据统计出的指标特征，驱动策略和阈值的自动推断
- 状态常量：HEALTHY / ANOMALY / RECOVERING
"""

from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------------------
# 基线状态常量
# ---------------------------------------------------------------------------

#: 正常运行，模板持续学习更新
BASELINE_STATUS_HEALTHY = "healthy"

#: 检测到异常，模板冻结，不学习故障数据
BASELINE_STATUS_ANOMALY = "anomaly"

#: 异常消失，等待稳定后恢复学习
BASELINE_STATUS_RECOVERING = "recovering"


# ---------------------------------------------------------------------------
# 基线状态
# ---------------------------------------------------------------------------

@dataclass
class BaselineState:
    """
    单个指标的健康基线状态。

    每个 (device_id, metric) 对应一个独立的 BaselineState 实例，
    存储该指标的周期模板和当前健康状态。

    Attributes:
        period: 检测到的加工周期长度（秒）
        phase_origin_ts: 相位原点时间戳（Unix 秒），用于计算当前相位
        template: 中位数模板曲线，长度等于 period，用于预测
        lower_template: 下界模板曲线（phase_band 策略时为分位数，否则等于 template）
        upper_template: 上界模板曲线（phase_band 策略时为分位数，否则等于 template）
        strategy: 预测策略，"phase_point" 或 "phase_band"
        status: 当前健康状态，取值为 BASELINE_STATUS_* 常量
        clean_seconds: 连续健康运行的秒数，用于判断是否可以更新模板
        last_update_ts: 上次模板更新的时间戳（Unix 秒）
        last_seen_ts: 上次处理该指标的时间戳（Unix 秒），用于计算 elapsed
        y_min: 最近一段时间内的最小值，用于量程参考
        y_max: 最近一段时间内的最大值，用于量程参考
    """

    period: int
    phase_origin_ts: int
    template: List[float]
    lower_template: List[float]
    upper_template: List[float]
    strategy: str
    status: str
    clean_seconds: int
    last_update_ts: int
    last_seen_ts: int
    y_min: float
    y_max: float


# ---------------------------------------------------------------------------
# 指标特征（自适应配置推断结果）
# ---------------------------------------------------------------------------

@dataclass
class MetricProfile:
    """
    从历史数据统计出的指标特征，用于自动推断预测策略和阈值。

    由 ``profiling.infer_metric_profile()`` 生成，
    再由 ``profiling.build_target()`` 转换为执行层 target dict。

    Attributes:
        device_id: 设备标识，对应 VM 中的 device_id 标签值
        metric: 指标名，如 "feed_rate"、"spindle_current"
        p5: 活跃段第 5 百分位数（过滤空闲零值后）
        p95: 活跃段第 95 百分位数
        iqr: p95 - p5，反映正常波动范围
        cv: 变异系数（std / mean），衡量信号稳定性
            cv < 0.15 → 稳定信号（精铣类）→ phase_point
            cv >= 0.15 → 波动信号（粗铣负载、振动类）→ phase_band
        strategy: 自动推断的预测策略，"phase_point" 或 "phase_band"
        abs_threshold: 绝对误差阈值（自动计算）
        rel_threshold: 相对误差阈值（自动计算）
        band_low_q: phase_band 下界分位数（默认 5）
        band_high_q: phase_band 上界分位数（默认 95）
        band_pad_abs: phase_band 额外填充宽度，覆盖正常尖峰
        phase_lock_period_search_ratio: phase-lock 周期搜索范围（相对比例）
            由实测周期抖动率动态决定，周期越不稳定则搜索范围越宽
    """

    device_id: str
    metric: str
    p5: float
    p95: float
    iqr: float
    cv: float
    strategy: str
    abs_threshold: float
    rel_threshold: float
    band_low_q: float
    band_high_q: float
    band_pad_abs: float
    phase_lock_period_search_ratio: float
