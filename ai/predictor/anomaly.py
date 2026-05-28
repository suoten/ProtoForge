# -*- coding: utf-8 -*-
"""
predictor.anomaly
~~~~~~~~~~~~~~~~~
异常检测：判断当前信号是否偏离健康基线。

职责：
- 计算预测边界（phase_point 用对称阈值，phase_band 用分位数带）
- 应用物理上下限兜底（来自 override 文件）
- 统计越界比例、连续越界秒数、最大越界倍数
- 综合三个条件判断是否触发异常

依赖：predictor.phase_lock, predictor.template, predictor.config, predictor.models
"""

from typing import Dict, Tuple

import numpy as np

from . import config
from .models import BaselineState
from .phase_lock import phase_lock_recent
from .template import predict_state_bundle


def max_consecutive_true(flags: np.ndarray) -> int:
    """
    计算布尔数组中最长连续 True 的长度。

    用于统计最长连续越界秒数，是异常判断的条件之一。

    Args:
        flags: 布尔数组（True 表示该点越界）

    Returns:
        最长连续 True 的长度（整数）。
    """
    max_count = 0
    current = 0
    for flag in flags:
        if bool(flag):
            current += 1
            max_count = max(max_count, current)
        else:
            current = 0
    return int(max_count)


def calc_point_bounds(
    pred: np.ndarray,
    abs_threshold: float,
    rel_threshold: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    计算 phase_point 策略的对称预测边界。

    边界宽度 = max(abs_threshold, |pred| * rel_threshold)，
    取两者较大值，保证在小值区域有最小绝对容忍度。

    Args:
        pred: 预测中值数组
        abs_threshold: 绝对误差阈值
        rel_threshold: 相对误差阈值（相对于预测值的比例）

    Returns:
        (lower, upper) 边界数组对。
    """
    threshold = np.maximum(abs_threshold, np.abs(pred) * rel_threshold)
    return pred - threshold, pred + threshold


def calc_final_bounds(
    state: BaselineState,
    pred: np.ndarray,
    lower_raw: np.ndarray,
    upper_raw: np.ndarray,
    target: Dict,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    计算最终预测边界，综合策略、动态填充和物理上下限。

    phase_band 策略：
        在分位数模板边界基础上，叠加动态填充（band_pad_abs 和相对填充取较大值），
        覆盖正常的尖峰波动，避免误报。

    phase_point 策略：
        直接用对称阈值计算边界。

    物理上下限（可选）：
        来自 override 文件的 hard_max / hard_min，对边界做最终 clip。

    Args:
        state: 当前基线状态（提供策略信息）
        pred: 预测中值数组
        lower_raw: 模板下界数组（phase_band 为分位数，phase_point 等于 pred）
        upper_raw: 模板上界数组
        target: target dict，包含阈值和物理上下限配置

    Returns:
        (lower, upper) 最终边界数组对。
    """
    strategy = target.get("strategy", "phase_point")
    abs_threshold = float(target.get("abs_threshold", 1.0))
    rel_threshold = float(target.get("rel_threshold", 0.25))

    if strategy == "phase_band":
        pad_abs = float(target.get("band_pad_abs", abs_threshold))
        # 动态填充：取绝对填充和相对填充（预测值的 25% * rel_threshold）的较大值
        dynamic_pad = np.maximum(pad_abs, np.abs(pred) * rel_threshold * 0.25)
        lower = lower_raw - dynamic_pad
        upper = upper_raw + dynamic_pad
    else:
        lower, upper = calc_point_bounds(pred, abs_threshold, rel_threshold)

    # 物理上下限兜底（来自 override 文件，可选）
    hard_max = target.get("hard_max")
    hard_min = target.get("hard_min")
    if hard_max is not None:
        upper = np.minimum(upper, float(hard_max))
    if hard_min is not None:
        lower = np.maximum(lower, float(hard_min))

    return lower, upper


def detect_anomaly(
    state: BaselineState,
    ts_grid: np.ndarray,
    ys_model: np.ndarray,
    ys_actual: np.ndarray,
    target: Dict,
) -> Tuple[bool, float, float, float, int, int, int, float]:
    """
    检测当前信号是否偏离健康基线，返回完整的诊断指标。

    流程：
    1. phase-lock 对齐：在最近窗口内找最优 (period, origin)
    2. 用对齐后的参数预测最近窗口的值
    3. 计算越界统计量
    4. 按三个条件判断是否异常：
       - 越界比例 >= outside_ratio_threshold
       - 连续越界秒数 >= min_consecutive_outside
       - 最大越界倍数 >= severe_exceed_ratio（单点严重越界立即报警）

    Args:
        state: 当前基线状态
        ts_grid: 均匀 1 秒网格的时间戳数组
        ys_model: 平滑后的信号（phase_point 用于比较）
        ys_actual: 原始信号（phase_band 用于比较）
        target: target dict，包含阈值配置

    Returns:
        (is_anomaly, outside_ratio, mean_abs_err, mean_rel_err,
         best_period, best_origin, max_outside_seconds, max_exceed_ratio)
    """
    best_period, best_origin, pred_recent, _ = phase_lock_recent(
        state=state,
        ts_grid=ts_grid,
        ys_model=ys_model,
        target=target,
    )

    recent_len = len(pred_recent)
    if recent_len <= 0:
        return False, 0.0, 0.0, 0.0, best_period, best_origin, 0, 0.0

    # phase_band 用原始信号比较（保留真实波动），phase_point 用平滑信号
    if target.get("strategy", "phase_point") == "phase_band":
        actual = ys_actual[-recent_len:].astype(float)
    else:
        actual = ys_model[-recent_len:].astype(float)

    # 用 phase-lock 后的最优参数重新预测（临时 state，不修改原始 state）
    tmp_state = BaselineState(
        period=best_period,
        phase_origin_ts=best_origin,
        template=state.template,
        lower_template=state.lower_template,
        upper_template=state.upper_template,
        strategy=state.strategy,
        status=state.status,
        clean_seconds=state.clean_seconds,
        last_update_ts=state.last_update_ts,
        last_seen_ts=state.last_seen_ts,
        y_min=state.y_min,
        y_max=state.y_max,
    )

    recent_ts = ts_grid[-recent_len:].astype(int).tolist()
    pred, lower_raw, upper_raw = predict_state_bundle(tmp_state, recent_ts)

    lower, upper = calc_final_bounds(
        state=tmp_state,
        pred=pred,
        lower_raw=lower_raw,
        upper_raw=upper_raw,
        target=target,
    )

    # 计算越界量（负值表示在边界内，clip 到 0）
    above_upper = actual - upper
    below_lower = lower - actual
    exceed = np.maximum(np.maximum(above_upper, below_lower), 0.0)
    outside = exceed > 0

    band_width = np.maximum(upper - lower, 1e-6)
    exceed_ratio = exceed / band_width  # 越界量相对于边界宽度的倍数

    abs_err = np.abs(actual - pred)
    outside_ratio = float(np.mean(outside))
    mean_abs_err = float(np.mean(abs_err))
    mean_rel_err = float(np.mean(abs_err / np.maximum(np.abs(pred), 1e-6)))
    max_outside_seconds = max_consecutive_true(outside)
    max_exceed_ratio = float(np.max(exceed_ratio)) if len(exceed_ratio) > 0 else 0.0

    # 从 target 读取阈值，允许每个指标独立配置
    outside_ratio_threshold = float(
        target.get("outside_ratio_threshold", config.OUTSIDE_RATIO_THRESHOLD)
    )
    min_consecutive_outside = int(
        target.get("min_consecutive_outside", config.MIN_CONSECUTIVE_OUTSIDE)
    )
    severe_exceed_ratio = float(
        target.get("severe_exceed_ratio", config.SEVERE_EXCEED_RATIO)
    )

    is_anomaly = (
        outside_ratio >= outside_ratio_threshold
        or max_outside_seconds >= min_consecutive_outside
        or max_exceed_ratio >= severe_exceed_ratio
    )

    return (
        is_anomaly,
        outside_ratio,
        mean_abs_err,
        mean_rel_err,
        int(best_period),
        int(best_origin),
        int(max_outside_seconds),
        float(max_exceed_ratio),
    )
