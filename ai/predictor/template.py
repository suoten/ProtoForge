# -*- coding: utf-8 -*-
"""
predictor.template
~~~~~~~~~~~~~~~~~~
模板的构建、预测、重采样与融合，不包含任何 IO 操作。

职责：
- 从历史谷底片段构建周期模板（中值/分位数）
- 基于模板和相位原点预测未来值
- 模板重采样（周期变化时对齐长度）
- EMA 融合新旧模板（渐进式学习）
- 相位原点规整化

依赖：numpy, predictor.signal, predictor.config, predictor.models
"""

import math
from typing import List, Optional, Tuple

import numpy as np

from . import config
from .models import BaselineState
from .signal import moving_average


# ---------------------------------------------------------------------------
# 模板构建
# ---------------------------------------------------------------------------

def build_templates_from_valleys(
    ts_grid: np.ndarray,
    ys_mid_grid: np.ndarray,
    ys_band_grid: np.ndarray,
    period: int,
    valleys: List[int],
    strategy: str,
    band_low_q: float,
    band_high_q: float,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """
    从历史谷底片段构建三条模板曲线（中值、下界、上界）。

    每个相邻谷底对定义一个周期片段，将其重采样到统一的 period 长度，
    再按策略聚合：
    - phase_point：加权平均（越近的周期权重越高）
    - phase_band：中位数 + 分位数（对异常周期鲁棒）

    Args:
        ts_grid: 均匀 1 秒网格的时间戳数组
        ys_mid_grid: 用于构建中值模板的平滑信号（phase_point 用）
        ys_band_grid: 用于构建分位数模板的原始信号（phase_band 用）
        period: 目标模板长度（秒）
        valleys: 谷底索引列表
        strategy: "phase_point" 或 "phase_band"
        band_low_q: phase_band 下界分位数（如 5.0）
        band_high_q: phase_band 上界分位数（如 95.0）

    Returns:
        (mid_template, lower_template, upper_template) 三个长度为 period 的数组。
        数据不足时返回 None。
    """
    if period <= 1 or len(valleys) < config.MIN_FULL_CYCLES_FOR_TEMPLATE + 1:
        return None

    # 筛选长度合理的周期片段（0.55~1.60 倍期望周期）
    pairs = [
        (a, b, float(ts_grid[b] - ts_grid[a]))
        for a, b in zip(valleys[:-1], valleys[1:])
        if period * 0.55 <= float(ts_grid[b] - ts_grid[a]) <= period * 1.60
    ]

    if len(pairs) < config.MIN_FULL_CYCLES_FOR_TEMPLATE:
        return None

    # 只取最近 MAX_CYCLES_FOR_TEMPLATE 个周期，防止过旧数据污染
    pairs = pairs[-config.MAX_CYCLES_FOR_TEMPLATE:]

    phase_grid = np.arange(period, dtype=float)
    mid_segments: List[np.ndarray] = []
    band_segments: List[np.ndarray] = []
    weights: List[float] = []

    for idx, (a, b, cycle_len) in enumerate(pairs):
        seg_ts = ts_grid[a : b + 1]
        seg_mid_y = ys_mid_grid[a : b + 1]
        seg_band_y = ys_band_grid[a : b + 1]

        if len(seg_mid_y) < 3 or len(seg_band_y) < 3:
            continue

        # 将片段的时间轴归一化到 [0, period)，再插值到统一相位网格
        x_old = (seg_ts - seg_ts[0]) / cycle_len * period
        mid_seg = np.interp(phase_grid, x_old, seg_mid_y)
        band_seg = np.interp(phase_grid, x_old, seg_band_y)

        mid_segments.append(mid_seg.astype(float))
        band_segments.append(band_seg.astype(float))
        # 越近的周期权重越高（线性递增，范围 0.5~1.0）
        weights.append(0.5 + 0.5 * ((idx + 1) / len(pairs)))

    if len(mid_segments) < config.MIN_FULL_CYCLES_FOR_TEMPLATE:
        return None

    mid_arr = np.vstack(mid_segments)
    band_arr = np.vstack(band_segments)
    w_arr = np.array(weights, dtype=float)

    if strategy == "phase_band":
        # 分位数聚合：对异常周期鲁棒，保留正常波动范围
        mid_template = np.percentile(mid_arr, 50, axis=0)
        lower_template = np.percentile(band_arr, band_low_q, axis=0)
        upper_template = np.percentile(band_arr, band_high_q, axis=0)
    else:
        # 加权平均：越近的周期贡献越大
        mid_template = np.average(mid_arr, axis=0, weights=w_arr)
        lower_template = mid_template.copy()
        upper_template = mid_template.copy()

    return (
        mid_template.astype(float),
        lower_template.astype(float),
        upper_template.astype(float),
    )


def build_current_baseline(
    ts_grid: np.ndarray,
    ys_mid_grid: np.ndarray,
    ys_band_grid: np.ndarray,
    strategy: str,
    band_low_q: float,
    band_high_q: float,
    tail_seconds: Optional[int] = None,
) -> Optional[Tuple[int, int, np.ndarray, np.ndarray, np.ndarray]]:
    """
    从历史数据构建当前基线（周期 + 相位原点 + 三条模板曲线）。

    可选 tail_seconds 参数限制只使用最近一段数据，
    用于健康状态下的增量模板更新（避免使用过旧的异常数据）。

    Args:
        ts_grid: 均匀 1 秒网格的时间戳数组
        ys_mid_grid: 平滑后的信号（用于周期检测和中值模板）
        ys_band_grid: 原始信号（用于分位数模板）
        strategy: "phase_point" 或 "phase_band"
        band_low_q: phase_band 下界分位数
        band_high_q: phase_band 上界分位数
        tail_seconds: 若指定，只使用最近 tail_seconds 秒的数据

    Returns:
        (period, phase_origin_ts, template, lower_template, upper_template)
        数据不足或无法检测到谷底时返回 None。
    """
    from .signal import detect_period_and_valleys

    if len(ys_mid_grid) < config.MIN_POINTS or len(ys_band_grid) < config.MIN_POINTS:
        return None

    if tail_seconds is not None and tail_seconds > 0:
        cutoff = ts_grid[-1] - int(tail_seconds)
        mask = ts_grid >= cutoff
        ts_use = ts_grid[mask]
        ys_mid_use = ys_mid_grid[mask]
        ys_band_use = ys_band_grid[mask]
    else:
        ts_use = ts_grid
        ys_mid_use = ys_mid_grid
        ys_band_use = ys_band_grid

    if len(ys_mid_use) < config.MIN_POINTS or len(ys_band_use) < config.MIN_POINTS:
        return None

    period, valleys = detect_period_and_valleys(ts_use, ys_mid_use)

    templates = build_templates_from_valleys(
        ts_grid=ts_use,
        ys_mid_grid=ys_mid_use,
        ys_band_grid=ys_band_use,
        period=period,
        valleys=valleys,
        strategy=strategy,
        band_low_q=band_low_q,
        band_high_q=band_high_q,
    )

    if templates is None or len(valleys) == 0:
        return None

    template, lower_template, upper_template = templates
    # 以最后一个谷底作为相位原点
    phase_origin_ts = int(round(float(ts_use[valleys[-1]])))

    return int(period), phase_origin_ts, template, lower_template, upper_template


# ---------------------------------------------------------------------------
# 模板预测
# ---------------------------------------------------------------------------

def circular_template_value(template: np.ndarray, phase: float) -> float:
    """
    从模板中读取指定相位处的值（线性插值，循环边界）。

    Args:
        template: 长度为 period 的模板数组
        phase: 相位（0 到 period 之间的浮点数）

    Returns:
        插值后的模板值。
    """
    period = len(template)
    if period == 0:
        return 0.0

    phase = float(phase) % period
    i0 = int(math.floor(phase)) % period
    i1 = (i0 + 1) % period
    frac = phase - math.floor(phase)

    return float((1.0 - frac) * template[i0] + frac * template[i1])


def resample_template(old_template: np.ndarray, new_period: int) -> np.ndarray:
    """
    将模板重采样到新的周期长度。

    当 phase-lock 检测到周期漂移时，需要将旧模板拉伸/压缩到新周期。
    使用循环扩展（拼接三份）保证边界处插值正确。

    Args:
        old_template: 原始模板数组
        new_period: 目标周期长度（秒）

    Returns:
        重采样后的模板数组，长度为 new_period。
    """
    old_period = len(old_template)
    if old_period == new_period:
        return old_template.astype(float)

    if old_period <= 1 or new_period <= 1:
        return np.full(new_period, float(np.mean(old_template)), dtype=float)

    # 归一化到 [0, 1) 相位空间，循环扩展保证边界插值正确
    old_x = np.linspace(0.0, 1.0, old_period, endpoint=False)
    new_x = np.linspace(0.0, 1.0, new_period, endpoint=False)

    old_x_ext = np.concatenate([old_x - 1.0, old_x, old_x + 1.0])
    old_y_ext = np.concatenate([old_template, old_template, old_template])

    return np.interp(new_x, old_x_ext, old_y_ext).astype(float)


def predict_template_values(
    template: np.ndarray,
    period: int,
    phase_origin_ts: int,
    ts_list: List[int],
) -> np.ndarray:
    """
    根据模板和相位原点，预测一组时间戳处的值。

    相位 = (ts - phase_origin_ts) mod period，
    再从模板中线性插值读取对应值。

    Args:
        template: 长度为 period 的模板数组
        period: 周期（秒）
        phase_origin_ts: 相位原点时间戳（Unix 秒）
        ts_list: 待预测的时间戳列表（Unix 秒）

    Returns:
        预测值数组，长度与 ts_list 相同。
    """
    if period <= 1:
        return np.zeros(len(ts_list), dtype=float)

    if len(template) != period:
        template = resample_template(template, period)

    values = [
        circular_template_value(template, (int(ts) - int(phase_origin_ts)) % period)
        for ts in ts_list
    ]
    return np.array(values, dtype=float)


def predict_state_bundle(
    state: BaselineState,
    ts_list: List[int],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    用 BaselineState 中的三条模板预测一组时间戳处的值。

    Args:
        state: 当前基线状态（包含 period、phase_origin_ts、三条模板）
        ts_list: 待预测的时间戳列表（Unix 秒）

    Returns:
        (mid, lower, upper) 三个预测数组，长度与 ts_list 相同。
    """
    period = int(state.period)
    origin = int(state.phase_origin_ts)

    mid = predict_template_values(
        template=np.array(state.template, dtype=float),
        period=period,
        phase_origin_ts=origin,
        ts_list=ts_list,
    )
    lower = predict_template_values(
        template=np.array(state.lower_template, dtype=float),
        period=period,
        phase_origin_ts=origin,
        ts_list=ts_list,
    )
    upper = predict_template_values(
        template=np.array(state.upper_template, dtype=float),
        period=period,
        phase_origin_ts=origin,
        ts_list=ts_list,
    )
    return mid, lower, upper


def normalize_origin_near(origin: int, period: int, near_ts: int) -> int:
    """
    将相位原点规整化到 near_ts 附近（使 origin <= near_ts < origin + period）。

    phase-lock 搜索时需要将原点移到最近的时间窗口内，
    避免因原点过旧导致相位计算溢出。

    Args:
        origin: 当前相位原点（Unix 秒）
        period: 周期（秒）
        near_ts: 目标时间戳（通常为最新数据点的时间戳）

    Returns:
        规整化后的相位原点（Unix 秒）。
    """
    if period <= 1:
        return origin

    origin = int(origin)
    period = int(period)
    near_ts = int(near_ts)

    while origin + period <= near_ts:
        origin += period

    while origin > near_ts:
        origin -= period

    return origin


def merge_template(
    old_template: np.ndarray,
    new_template: np.ndarray,
    alpha: float,
) -> np.ndarray:
    """
    用 EMA 融合旧模板和新模板。

    merged = (1 - alpha) * old + alpha * new

    若两者长度不同，先将旧模板重采样到新模板长度。
    alpha 越大，新模板权重越高（学习越激进）。

    Args:
        old_template: 旧模板数组
        new_template: 新模板数组
        alpha: EMA 步长，clip 到 [0, 1]

    Returns:
        融合后的模板数组，长度与 new_template 相同。
    """
    alpha = float(np.clip(alpha, 0.0, 1.0))

    if len(old_template) != len(new_template):
        old_template = resample_template(old_template, len(new_template))

    return ((1.0 - alpha) * old_template + alpha * new_template).astype(float)
