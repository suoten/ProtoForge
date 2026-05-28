# -*- coding: utf-8 -*-
"""
predictor.state
~~~~~~~~~~~~~~~
状态生命周期管理：BaselineState 的创建、更新和 phase-lock 应用。

职责：
- 首次见到某指标时初始化健康基线
- 每轮轮询时运行异常检测，更新状态机（HEALTHY / ANOMALY / RECOVERING）
- 健康/恢复状态下用 EMA 渐进更新模板
- 将 phase-lock 结果写回 state

本模块不做任何 IO，states 字典由调用方（service.py）持有和传入。

依赖：predictor.template, predictor.anomaly, predictor.config, predictor.models
"""

import logging
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np

from . import config
from .anomaly import detect_anomaly
from .models import (
    BASELINE_STATUS_ANOMALY,
    BASELINE_STATUS_HEALTHY,
    BASELINE_STATUS_RECOVERING,
    BaselineState,
)
from .template import (
    build_current_baseline,
    merge_template,
    resample_template,
)

logger = logging.getLogger(__name__)


def create_initial_state(
    ts_grid: np.ndarray,
    ys_model: np.ndarray,
    ys_actual: np.ndarray,
    target: Dict,
    now_sec: int,
) -> Optional[BaselineState]:
    """
    从历史数据构建初始健康基线状态。

    首次见到某指标时调用，需要足够的历史数据（MIN_POINTS 个点）。

    Args:
        ts_grid: 均匀 1 秒网格的时间戳数组
        ys_model: 平滑后的信号（用于周期检测和中值模板）
        ys_actual: 原始信号（用于分位数模板和量程统计）
        target: target dict，包含策略和阈值配置
        now_sec: 当前时间戳（Unix 秒）

    Returns:
        初始化的 BaselineState，数据不足时返回 None。
    """
    strategy = str(target.get("strategy", "phase_point"))
    band_low_q = float(target.get("band_low_q", 5.0))
    band_high_q = float(target.get("band_high_q", 95.0))

    baseline = build_current_baseline(
        ts_grid=ts_grid,
        ys_mid_grid=ys_model,
        ys_band_grid=ys_actual,
        strategy=strategy,
        band_low_q=band_low_q,
        band_high_q=band_high_q,
    )

    if baseline is None:
        return None

    period, phase_origin_ts, template, lower_template, upper_template = baseline

    return BaselineState(
        period=int(period),
        phase_origin_ts=int(phase_origin_ts),
        template=template.astype(float).tolist(),
        lower_template=lower_template.astype(float).tolist(),
        upper_template=upper_template.astype(float).tolist(),
        strategy=strategy,
        status=BASELINE_STATUS_HEALTHY,
        # 初始 clean_seconds 设为多个完整周期，表示已有足够的健康历史
        clean_seconds=int(period * config.MAX_CYCLES_FOR_TEMPLATE),
        last_update_ts=now_sec,
        last_seen_ts=now_sec,
        y_min=float(np.min(ys_actual)),
        y_max=float(np.max(ys_actual)),
    )


def apply_phase_lock_to_state(
    state: BaselineState,
    best_period: int,
    best_origin: int,
) -> None:
    """
    将 phase-lock 搜索结果写回 state（原地修改）。

    若周期发生变化，同时对三条模板做重采样，保持长度一致。

    Args:
        state: 要更新的基线状态（原地修改）
        best_period: phase-lock 找到的最优周期（整数秒）
        best_origin: phase-lock 找到的最优相位原点（Unix 秒）
    """
    best_period = int(best_period)
    if best_period <= 1:
        return

    # 周期变化时重采样三条模板
    if len(state.template) != best_period:
        state.template = resample_template(
            np.array(state.template, dtype=float), best_period
        ).astype(float).tolist()

    if len(state.lower_template) != best_period:
        state.lower_template = resample_template(
            np.array(state.lower_template, dtype=float), best_period
        ).astype(float).tolist()

    if len(state.upper_template) != best_period:
        state.upper_template = resample_template(
            np.array(state.upper_template, dtype=float), best_period
        ).astype(float).tolist()

    state.period = best_period
    state.phase_origin_ts = int(best_origin)


def maybe_update_state(
    key: str,
    ts_grid: np.ndarray,
    ys_model: np.ndarray,
    ys_actual: np.ndarray,
    target: Dict,
    states: Dict[str, BaselineState],
) -> Tuple[Optional[BaselineState], bool, float, float, float, int, float]:
    """
    核心状态更新函数：检测异常并按状态机规则更新基线。

    状态机转换：
    - 无状态 → 初始化 → HEALTHY（返回，本轮不做异常检测）
    - HEALTHY + 异常 → ANOMALY（冻结模板）
    - ANOMALY + 正常 → RECOVERING（开始计时）
    - RECOVERING + 正常 + 足够时间 → HEALTHY（恢复学习）
    - HEALTHY/RECOVERING + 正常 + 足够时间 → 更新模板（EMA）

    Args:
        key: 序列唯一标识符（用于 states 字典的键）
        ts_grid: 均匀 1 秒网格的时间戳数组
        ys_model: 平滑后的信号
        ys_actual: 原始信号
        target: target dict，包含策略和阈值配置
        states: 所有指标的状态字典（由 PredictorService 持有，原地修改）

    Returns:
        (state, is_anomaly, outside_ratio, mean_abs_err, mean_rel_err,
         max_outside_seconds, max_exceed_ratio)
        state 为 None 表示数据不足，本轮跳过。
    """
    now_sec = int(time.time())
    state = states.get(key)

    # 首次见到该指标：初始化健康基线
    if state is None:
        state = create_initial_state(
            ts_grid=ts_grid,
            ys_model=ys_model,
            ys_actual=ys_actual,
            target=target,
            now_sec=now_sec,
        )

        if state is None:
            return None, False, 0.0, 0.0, 0.0, 0, 0.0

        states[key] = state
        logger.info(
            "初始化健康模板 key=%s strategy=%s period=%ss origin=%s clean=%ss",
            key,
            state.strategy,
            state.period,
            datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S"),
            state.clean_seconds,
        )
        return state, False, 0.0, 0.0, 0.0, 0, 0.0

    # 计算距上次处理的时间（秒），用于累加 clean_seconds
    elapsed = max(1, now_sec - int(state.last_seen_ts))
    elapsed = min(elapsed, config.POLL_INTERVAL * 2)  # 防止长时间停机后 clean_seconds 暴增
    state.last_seen_ts = now_sec

    (
        is_anomaly,
        outside_ratio,
        mean_abs_err,
        mean_rel_err,
        best_period,
        best_origin,
        max_outside_seconds,
        max_exceed_ratio,
    ) = detect_anomaly(
        state=state,
        ts_grid=ts_grid,
        ys_model=ys_model,
        ys_actual=ys_actual,
        target=target,
    )

    # 异常：冻结模板，不学习故障数据
    if is_anomaly:
        state.status = BASELINE_STATUS_ANOMALY
        state.clean_seconds = 0
        states[key] = state
        logger.warning(
            "检测到异常，冻结模板 key=%s outside_ratio=%.2f max_outside=%ss "
            "max_exceed_ratio=%.2f mean_abs_err=%.4f mean_rel_err=%.4f",
            key, outside_ratio, max_outside_seconds,
            max_exceed_ratio, mean_abs_err, mean_rel_err,
        )
        return state, True, outside_ratio, mean_abs_err, mean_rel_err, max_outside_seconds, max_exceed_ratio

    # 正常：应用 phase-lock 结果
    old_period = int(state.period)
    old_origin = int(state.phase_origin_ts)
    apply_phase_lock_to_state(state, best_period, best_origin)

    if old_period != state.period or old_origin != state.phase_origin_ts:
        logger.info(
            "phase-lock key=%s period %s -> %s origin %s -> %s",
            key, old_period, state.period,
            datetime.fromtimestamp(old_origin).strftime("%H:%M:%S"),
            datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S"),
        )

    # 异常刚消失：进入恢复期，等待稳定后再恢复学习
    if state.status == BASELINE_STATUS_ANOMALY:
        state.status = BASELINE_STATUS_RECOVERING
        state.clean_seconds = elapsed
        states[key] = state
        logger.info("异常开始恢复 key=%s clean_seconds=%ss", key, state.clean_seconds)
        return state, False, outside_ratio, mean_abs_err, mean_rel_err, max_outside_seconds, max_exceed_ratio

    # 累加健康时间
    if state.status == BASELINE_STATUS_RECOVERING:
        state.clean_seconds += elapsed
    else:
        state.status = BASELINE_STATUS_HEALTHY
        state.clean_seconds += elapsed

    # 健康时间不足：不更新模板
    min_clean_for_update = max(
        config.RECOVERY_MIN_SECONDS,
        int(state.period) * config.MIN_FULL_CYCLES_FOR_TEMPLATE,
    )
    if state.clean_seconds < min_clean_for_update:
        states[key] = state
        return state, False, outside_ratio, mean_abs_err, mean_rel_err, max_outside_seconds, max_exceed_ratio

    # 健康时间足够：用最近数据更新模板（EMA）
    tail_seconds = min(
        int(state.clean_seconds),
        int(state.period) * config.MAX_CYCLES_FOR_TEMPLATE,
    )

    strategy = str(target.get("strategy", "phase_point"))
    band_low_q = float(target.get("band_low_q", 5.0))
    band_high_q = float(target.get("band_high_q", 95.0))

    baseline = build_current_baseline(
        ts_grid=ts_grid,
        ys_mid_grid=ys_model,
        ys_band_grid=ys_actual,
        strategy=strategy,
        band_low_q=band_low_q,
        band_high_q=band_high_q,
        tail_seconds=tail_seconds,
    )

    if baseline is None:
        states[key] = state
        return state, False, outside_ratio, mean_abs_err, mean_rel_err, max_outside_seconds, max_exceed_ratio

    new_period, new_origin, new_template, new_lower_template, new_upper_template = baseline

    # 恢复期用更激进的 alpha，加速追赶真实信号
    alpha = config.RECOVERY_EMA_ALPHA if state.status == BASELINE_STATUS_RECOVERING else config.HEALTHY_EMA_ALPHA

    state.template = merge_template(
        np.array(state.template, dtype=float), new_template, alpha
    ).astype(float).tolist()
    state.lower_template = merge_template(
        np.array(state.lower_template, dtype=float), new_lower_template, alpha
    ).astype(float).tolist()
    state.upper_template = merge_template(
        np.array(state.upper_template, dtype=float), new_upper_template, alpha
    ).astype(float).tolist()

    state.period = int(new_period)
    state.phase_origin_ts = int(new_origin)
    state.status = BASELINE_STATUS_HEALTHY
    state.last_update_ts = now_sec

    # 更新量程统计（用于 Grafana 展示）
    if tail_seconds > 0 and len(ys_actual) >= tail_seconds:
        state.y_min = float(np.min(ys_actual[-tail_seconds:]))
        state.y_max = float(np.max(ys_actual[-tail_seconds:]))
    else:
        state.y_min = float(np.min(ys_actual))
        state.y_max = float(np.max(ys_actual))

    states[key] = state
    logger.info(
        "更新健康模板 key=%s strategy=%s period=%ss origin=%s clean=%ss alpha=%.2f",
        key, state.strategy, state.period,
        datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S"),
        state.clean_seconds, alpha,
    )

    return state, False, outside_ratio, mean_abs_err, mean_rel_err, max_outside_seconds, max_exceed_ratio
