# -*- coding: utf-8 -*-
"""
predictor.signal
~~~~~~~~~~~~~~~~
纯信号处理与周期估计，不包含任何 IO 操作。

职责：
- 滚动中位数、移动平均等平滑算法
- 基于 FFT + 自相关的周期估计
- 谷底检测（用于模板构建的相位对齐）
- 原始数据预处理（根据策略选择平滑方式）

本模块所有函数均为纯函数，输入 numpy 数组，输出 numpy 数组或基本类型。

依赖：numpy
"""

import math
from typing import Dict, List, Tuple

import numpy as np

from . import config


def rolling_median(arr: np.ndarray, window: int) -> np.ndarray:
    """
    对数组做滚动中位数平滑（边缘用 edge 填充）。

    中位数对脉冲噪声鲁棒，适合 phase_band 策略的粗铣负载信号。
    window 自动调整为奇数，保证对称填充。

    Args:
        arr: 输入数组
        window: 滑动窗口大小（秒），<=1 时直接返回原数组

    Returns:
        平滑后的数组，长度与输入相同。
    """
    if window <= 1 or len(arr) < window:
        return arr.astype(float)

    # 保证奇数窗口，使填充对称
    if window % 2 == 0:
        window += 1

    pad = window // 2
    padded = np.pad(arr.astype(float), (pad, pad), mode="edge")

    result = [float(np.median(padded[i : i + window])) for i in range(len(arr))]
    return np.array(result, dtype=float)


def moving_average(arr: np.ndarray, window: int) -> np.ndarray:
    """
    对数组做均匀权重移动平均（边缘用 edge 填充）。

    比滚动中位数快，适合 phase_point 策略的稳定信号。
    window 自动调整为奇数，保证对称填充。

    Args:
        arr: 输入数组
        window: 滑动窗口大小（秒），<=1 时直接返回原数组

    Returns:
        平滑后的数组，长度与输入相同。
    """
    if window <= 1 or len(arr) < window:
        return arr.astype(float)

    if window % 2 == 0:
        window += 1

    kernel = np.ones(window, dtype=float) / window
    pad = window // 2
    padded = np.pad(arr.astype(float), (pad, pad), mode="edge")

    return np.convolve(padded, kernel, mode="valid")


def preprocess_values(
    ys_grid: np.ndarray,
    strategy: str,
    smooth_window: int,
) -> np.ndarray:
    """
    根据预测策略对原始数据进行预处理平滑。

    - phase_band：使用滚动中位数（对脉冲噪声鲁棒）
    - phase_point：使用移动平均（保留趋势，计算更快）

    Args:
        ys_grid: 均匀 1 秒网格上的原始值数组
        strategy: "phase_point" 或 "phase_band"
        smooth_window: 平滑窗口大小（秒），<=1 时不平滑

    Returns:
        平滑后的数组，长度与输入相同。
    """
    if strategy == "phase_band":
        return rolling_median(ys_grid, smooth_window)

    if smooth_window > 1:
        return moving_average(ys_grid, smooth_window)

    return ys_grid.astype(float)


# ---------------------------------------------------------------------------
# 周期估计
# ---------------------------------------------------------------------------

def estimate_period_by_fft(ys_arr: np.ndarray) -> float:
    """
    用 FFT 粗估信号的主周期（秒）。

    取去均值后的功率谱中能量最大的频率分量，转换为周期。
    结果被 clip 到 [MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS]。

    Args:
        ys_arr: 均匀采样的值数组（1 秒间隔）

    Returns:
        估计的周期（秒），浮点数。数据不足或全零时返回 60.0。
    """
    n = len(ys_arr)
    if n < 8:
        return 60.0

    centered = ys_arr - np.mean(ys_arr)
    if np.allclose(centered, 0):
        return 60.0

    fft_vals = np.fft.rfft(centered)
    freqs = np.fft.rfftfreq(n, d=1.0)

    if len(freqs) <= 1:
        return 60.0

    # 跳过直流分量（index 0），找功率最大的频率
    power = np.abs(fft_vals[1:])
    if len(power) == 0 or np.max(power) <= 0:
        return 60.0

    dominant_idx = int(np.argmax(power)) + 1
    dominant_freq = float(freqs[dominant_idx])

    if dominant_freq <= 0:
        return 60.0

    period = 1.0 / dominant_freq
    return float(np.clip(period, config.MIN_PERIOD_SECONDS, config.MAX_PERIOD_SECONDS))


def refine_period_by_autocorr(ys_arr: np.ndarray, init_period: float) -> float:
    """
    用自相关函数在 FFT 粗估周期附近精化周期。

    在 [init_period * 0.7, init_period * 1.3] 范围内搜索自相关峰值，
    比 FFT 对非整数周期和噪声更鲁棒。

    Args:
        ys_arr: 均匀采样的值数组
        init_period: FFT 粗估的初始周期（秒）

    Returns:
        精化后的周期（秒），clip 到合法范围。
    """
    n = len(ys_arr)
    if n < 20:
        return float(np.clip(init_period, config.MIN_PERIOD_SECONDS, config.MAX_PERIOD_SECONDS))

    centered = ys_arr - np.mean(ys_arr)
    if np.allclose(centered, 0):
        return float(np.clip(init_period, config.MIN_PERIOD_SECONDS, config.MAX_PERIOD_SECONDS))

    # 全相关，取正半轴（lag >= 0）
    corr = np.correlate(centered, centered, mode="full")[n - 1:]

    p0 = int(round(init_period))
    left = max(int(config.MIN_PERIOD_SECONDS), int(max(2, p0 * 0.7)))
    right = min(n // 2, int(max(left + 1, p0 * 1.3)))

    if right <= left:
        return float(np.clip(init_period, config.MIN_PERIOD_SECONDS, config.MAX_PERIOD_SECONDS))

    search = corr[left : right + 1]
    if len(search) == 0:
        return float(np.clip(init_period, config.MIN_PERIOD_SECONDS, config.MAX_PERIOD_SECONDS))

    best_lag = left + int(np.argmax(search))
    return float(np.clip(best_lag, config.MIN_PERIOD_SECONDS, config.MAX_PERIOD_SECONDS))


def estimate_period_rough(ys_arr: np.ndarray) -> int:
    """
    FFT + 自相关两步法估计信号周期，返回整数秒。

    先用 FFT 粗估，再用自相关精化，最后 clip 到合法范围。

    Args:
        ys_arr: 均匀采样的值数组

    Returns:
        估计的周期（整数秒）。
    """
    p_fft = estimate_period_by_fft(ys_arr)
    p_refined = refine_period_by_autocorr(ys_arr, p_fft)
    period = int(round(p_refined))
    period = max(int(config.MIN_PERIOD_SECONDS), min(int(config.MAX_PERIOD_SECONDS), period))
    return int(period)


# ---------------------------------------------------------------------------
# 谷底检测
# ---------------------------------------------------------------------------

def find_valley_indices(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    expected_period: int,
) -> List[int]:
    """
    在时序数据中检测周期性谷底（加工周期的起始点）。

    算法步骤：
    1. 对信号做轻度移动平均平滑，抑制高频噪声
    2. 找低于 VALLEY_QUANTILE 百分位的局部极小值作为候选
    3. 若候选不足，放宽条件（不限百分位）
    4. 按最小间距过滤，同一间距内保留最低点
    5. 按周期合理性（0.55~1.60 倍期望周期）清洗

    Args:
        ts_grid: 均匀 1 秒网格的时间戳数组
        ys_grid: 对应的值数组
        expected_period: 预期周期（秒），用于设置最小间距和合理性检查

    Returns:
        谷底在数组中的索引列表（已排序）。
        数据不足时返回空列表。
    """
    n = len(ys_grid)
    if n < max(10, expected_period * 2):
        return []

    period = max(3, int(expected_period))
    # 平滑窗口约为周期的 8%，最大 21 秒，避免过度平滑
    smooth_window = min(max(3, int(round(period * 0.08))), 21)
    ys_smooth = moving_average(ys_grid, smooth_window)

    threshold = float(np.percentile(ys_smooth, config.VALLEY_QUANTILE))

    # 第一轮：只取低于阈值的局部极小值
    candidates = [
        i for i in range(1, n - 1)
        if (
            ys_smooth[i] <= ys_smooth[i - 1]
            and ys_smooth[i] < ys_smooth[i + 1]
            and ys_smooth[i] <= threshold
        )
    ]

    # 候选不足时放宽：取所有局部极小值
    if len(candidates) < config.MIN_FULL_CYCLES_FOR_TEMPLATE:
        candidates = [
            i for i in range(1, n - 1)
            if ys_smooth[i] <= ys_smooth[i - 1] and ys_smooth[i] < ys_smooth[i + 1]
        ]

    if not candidates:
        return []

    # 按最小间距过滤：同一间距内保留最低点
    min_distance = max(2, int(round(period * 0.55)))
    selected: List[int] = []
    for idx in candidates:
        if not selected:
            selected.append(idx)
        elif idx - selected[-1] >= min_distance:
            selected.append(idx)
        elif ys_smooth[idx] < ys_smooth[selected[-1]]:
            selected[-1] = idx

    if len(selected) < 2:
        return selected

    # 按周期合理性清洗：间距过小则保留更低点，间距过大则直接接受
    cleaned = [selected[0]]
    for idx in selected[1:]:
        diff = int(ts_grid[idx] - ts_grid[cleaned[-1]])
        if int(period * 0.55) <= diff <= int(period * 1.60):
            cleaned.append(idx)
        elif diff < int(period * 0.55):
            # 间距太小，保留更低的那个
            if ys_smooth[idx] < ys_smooth[cleaned[-1]]:
                cleaned[-1] = idx
        else:
            # 间距过大（可能漏检了一个谷底），直接接受
            cleaned.append(idx)

    return cleaned


def detect_period_and_valleys(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
) -> Tuple[int, List[int]]:
    """
    综合估计周期并检测谷底。

    先粗估周期，再检测谷底，最后用谷底间距的中位数修正周期。
    谷底间距的中位数比 FFT 更能反映实际加工节拍。

    Args:
        ts_grid: 均匀 1 秒网格的时间戳数组
        ys_grid: 对应的值数组

    Returns:
        (period, valley_indices) 元组：
        - period: 修正后的周期（整数秒）
        - valley_indices: 谷底索引列表
    """
    rough = estimate_period_rough(ys_grid)
    valleys = find_valley_indices(ts_grid, ys_grid, rough)

    if len(valleys) >= 3:
        diffs = np.diff(ts_grid[valleys])
        # 只取合理范围内的间距参与中位数计算
        good = diffs[(diffs >= rough * 0.55) & (diffs <= rough * 1.60)]
        period = int(round(float(np.median(good)))) if len(good) > 0 else rough
    else:
        period = rough

    period = max(int(config.MIN_PERIOD_SECONDS), min(int(config.MAX_PERIOD_SECONDS), period))
    return int(period), valleys
