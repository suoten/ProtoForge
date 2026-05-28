# -*- coding: utf-8 -*-
"""
predictor.phase_lock
~~~~~~~~~~~~~~~~~~~~
Phase-lock 相位对齐：在每次预测前动态校正周期和相位原点。

职责：
- 在基准周期附近搜索最优 (period, origin) 组合
- 最小化最近时间窗口内的预测 MAE
- 支持 target 级别的搜索范围配置（粗铣工位周期抖动大，需要更宽的范围）

依赖：predictor.template, predictor.config, predictor.models
"""

import logging
from typing import Dict, Optional, Tuple

import numpy as np

from . import config
from .models import BaselineState
from .template import (
    normalize_origin_near,
    predict_template_values,
    resample_template,
)

logger = logging.getLogger(__name__)


def phase_lock_recent(
    state: BaselineState,
    ts_grid: np.ndarray,
    ys_model: np.ndarray,
    target: Optional[Dict] = None,
) -> Tuple[int, int, np.ndarray, float]:
    """
    在最近时间窗口内搜索最优 (period, phase_origin) 组合。

    搜索策略：
    1. 确定搜索窗口（min/max 之间，约 2 倍周期）
    2. 在 [base_period * (1 - ratio), base_period * (1 + ratio)] 范围内枚举周期
    3. 对每个周期，在 origin ± origin_shift 范围内枚举相位原点
    4. 选择 MAE + 周期偏移惩罚最小的组合
       （惩罚项防止无谓地漂移到远离基准的周期）

    Args:
        state: 当前基线状态（提供基准 period、origin、template）
        ts_grid: 均匀 1 秒网格的时间戳数组
        ys_model: 平滑后的信号（用于计算 MAE）
        target: target dict，可包含 phase_lock_period_search_ratio /
                phase_lock_origin_search_ratio 覆盖默认搜索范围

    Returns:
        (best_period, best_origin, best_pred, best_mae) 元组：
        - best_period: 最优周期（整数秒）
        - best_origin: 最优相位原点（Unix 秒）
        - best_pred: 最优参数下的预测值数组（长度为搜索窗口大小）
        - best_mae: 最优 MAE
    """
    base_period = int(state.period)
    base_origin = int(state.phase_origin_ts)
    base_template = np.array(state.template, dtype=float)

    # 从 target 读取搜索范围，允许粗铣工位使用更宽的范围
    period_search_ratio = float(
        (target or {}).get("phase_lock_period_search_ratio", config.PHASE_LOCK_PERIOD_SEARCH_RATIO)
    )
    origin_search_ratio = float(
        (target or {}).get("phase_lock_origin_search_ratio", config.PHASE_LOCK_ORIGIN_SEARCH_RATIO)
    )

    # 数据不足时直接返回基准预测
    if base_period <= 1 or len(base_template) <= 1:
        ts_recent = ts_grid[-config.DETECT_WINDOW_SECONDS :].astype(int).tolist()
        pred = predict_template_values(base_template, base_period, base_origin, ts_recent)
        actual = ys_model[-len(ts_recent) :].astype(float)
        mae = float(np.mean(np.abs(actual - pred))) if len(actual) else 0.0
        return base_period, base_origin, pred, mae

    # 搜索窗口：约 2 倍周期，clip 到 [min, max]
    window_seconds = max(
        config.PHASE_LOCK_MIN_WINDOW_SECONDS,
        min(config.PHASE_LOCK_MAX_WINDOW_SECONDS, int(base_period * 2)),
    )

    cutoff = ts_grid[-1] - window_seconds
    mask = ts_grid >= cutoff
    ts_recent_arr = ts_grid[mask].astype(int)
    actual = ys_model[mask].astype(float)

    # 窗口内数据不足时退化到固定长度
    if len(ts_recent_arr) < max(10, config.DETECT_WINDOW_SECONDS):
        ts_recent_arr = ts_grid[-config.DETECT_WINDOW_SECONDS :].astype(int)
        actual = ys_model[-config.DETECT_WINDOW_SECONDS :].astype(float)

    ts_recent = ts_recent_arr.tolist()
    last_ts = int(ts_recent[-1])

    # 周期搜索范围
    p_min = max(
        int(config.MIN_PERIOD_SECONDS),
        int(round(base_period * (1.0 - period_search_ratio))),
    )
    p_max = min(
        int(config.MAX_PERIOD_SECONDS),
        int(round(base_period * (1.0 + period_search_ratio))),
    )

    # 初始化为基准参数
    best_period = base_period
    best_origin = normalize_origin_near(base_origin, base_period, last_ts)
    best_template = resample_template(base_template, best_period)
    best_pred = predict_template_values(
        template=best_template,
        period=best_period,
        phase_origin_ts=best_origin,
        ts_list=ts_recent,
    )
    best_mae = float(np.mean(np.abs(actual - best_pred)))

    for period in range(p_min, p_max + 1, config.PHASE_LOCK_PERIOD_STEP):
        template = resample_template(base_template, period)
        center_origin = normalize_origin_near(base_origin, period, last_ts)
        origin_shift = max(2, int(round(period * origin_search_ratio)))

        for shift in range(-origin_shift, origin_shift + 1, config.PHASE_LOCK_ORIGIN_STEP):
            origin = center_origin + shift
            pred = predict_template_values(
                template=template,
                period=period,
                phase_origin_ts=origin,
                ts_list=ts_recent,
            )
            mae = float(np.mean(np.abs(actual - pred)))

            # 惩罚项：偏离基准周期越远，惩罚越大（0.5 秒/秒偏差）
            # 防止在噪声中漂移到远离真实周期的位置
            penalty = abs(period - base_period) * 0.5
            score = mae + penalty
            best_score = best_mae + abs(best_period - base_period) * 0.5

            if score < best_score:
                best_period = period
                best_origin = origin
                best_pred = pred
                best_mae = mae

    # 规整化最终原点到最新时间戳附近
    best_origin = normalize_origin_near(best_origin, best_period, last_ts)

    return int(best_period), int(best_origin), best_pred, float(best_mae)
