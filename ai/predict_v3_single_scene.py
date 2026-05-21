# -*- coding: utf-8 -*-
"""
ProtoForge Predictor v10

修复重点：
1. 修复 lag=0 但预测线仍然相位漂移的问题。
2. 在谷底相位对齐基础上，增加 phase-lock 相位锁定。
3. 每轮使用最近 1~2 个周期真实数据，搜索最佳 period + phase_origin。
4. 预测起点仍然锚定最后一个真实点 last_real_ts，避免写入延迟。
5. 保留健康模板冻结逻辑：异常期间不学习故障数据。
6. 保留预测上下界和异常指标。
"""

import json
import logging
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests


# =============================================================================
# 日志配置
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# =============================================================================
# 基础配置
# =============================================================================

VM_URL = "http://localhost:8428"
STATE_FILE = "/tmp/protoforge_predictor_state_v10.json"

HISTORY_MINUTES = 30
HORIZON_SECONDS = 120
POLL_INTERVAL = 30

WRITE_HORIZON_SECONDS = min(HORIZON_SECONDS, POLL_INTERVAL)

QUERY_STEP = "1s"
MIN_POINTS = 120

MIN_PERIOD_SECONDS = 5
MAX_PERIOD_SECONDS = 3600

MIN_FULL_CYCLES_FOR_TEMPLATE = 3
MAX_CYCLES_FOR_TEMPLATE = 6

DETECT_WINDOW_SECONDS = 20
RECOVERY_MIN_SECONDS = 60

HEALTHY_EMA_ALPHA = 0.10
RECOVERY_EMA_ALPHA = 0.25

OUTSIDE_RATIO_THRESHOLD = 0.60

VALLEY_QUANTILE = 45

# phase-lock 配置
PHASE_LOCK_MIN_WINDOW_SECONDS = 45
PHASE_LOCK_MAX_WINDOW_SECONDS = 180
PHASE_LOCK_PERIOD_SEARCH_RATIO = 0.12
PHASE_LOCK_ORIGIN_SEARCH_RATIO = 0.35
PHASE_LOCK_PERIOD_STEP = 1
PHASE_LOCK_ORIGIN_STEP = 1

# 真实数据延迟超过这个值，就不继续预测
MAX_DATA_LAG_SECONDS = 180

# 预测锚定最后一个真实点
ALIGN_PREDICTION_TO_LAST_REAL_TS = True


# =============================================================================
# 指标配置
# =============================================================================

PREDICT_TARGETS = [
    {
        "query": 'feed_rate{device_id="fanuc-cnc"}',
        "pred_metric": "feed_rate_predicted",
        "anomaly_metric": "feed_rate_anomaly",
        "abs_threshold": 400.0,
        "rel_threshold": 0.25,
    },
    {
        "query": 'spindle_speed{device_id="fanuc-cnc"}',
        "pred_metric": "spindle_speed_predicted",
        "anomaly_metric": "spindle_speed_anomaly",
        "abs_threshold": 500.0,
        "rel_threshold": 0.25,
    },
    {
        "query": 'spindle_current{device_id="fanuc-cnc"}',
        "pred_metric": "spindle_current_predicted",
        "anomaly_metric": "spindle_current_anomaly",
        "abs_threshold": 5.0,
        "rel_threshold": 0.25,
    },
    {
        "query": 'vibration_x{device_id="fanuc-cnc"}',
        "pred_metric": "vibration_x_predicted",
        "anomaly_metric": "vibration_x_anomaly",
        "abs_threshold": 1.0,
        "rel_threshold": 0.30,
    },
    {
        "query": 'vibration_y{device_id="fanuc-cnc"}',
        "pred_metric": "vibration_y_predicted",
        "anomaly_metric": "vibration_y_anomaly",
        "abs_threshold": 1.0,
        "rel_threshold": 0.30,
    },
    {
        "query": 'vibration_z{device_id="fanuc-cnc"}',
        "pred_metric": "vibration_z_predicted",
        "anomaly_metric": "vibration_z_anomaly",
        "abs_threshold": 1.0,
        "rel_threshold": 0.30,
    },
]

EXTRA_PREDICT_LABELS = {
    "forecast": "phase_locked_health_v10",
    "source": "protoforge",
}

BASELINE_STATUS_HEALTHY = "healthy"
BASELINE_STATUS_ANOMALY = "anomaly"
BASELINE_STATUS_RECOVERING = "recovering"


# =============================================================================
# 状态结构
# =============================================================================

@dataclass
class BaselineState:
    period: int
    phase_origin_ts: int
    template: List[float]
    status: str
    clean_seconds: int
    last_update_ts: int
    last_seen_ts: int
    y_min: float
    y_max: float


BASELINE_STATES: Dict[str, BaselineState] = {}
LAST_REAL_TS_WRITTEN: Dict[str, int] = {}


# =============================================================================
# VictoriaMetrics 读取
# =============================================================================

def fetch_history(query: str, minutes: int = HISTORY_MINUTES) -> Tuple[List[float], List[float]]:
    now = datetime.now()
    start = now - timedelta(minutes=minutes)

    try:
        resp = requests.get(
            f"{VM_URL}/api/v1/query_range",
            params={
                "query": query,
                "start": start.timestamp(),
                "end": now.timestamp(),
                "step": QUERY_STEP,
            },
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("拉取数据失败 query=%s: %s", query, e)
        return [], []

    try:
        result = resp.json().get("data", {}).get("result", [])
    except Exception as e:
        logger.error("解析 VM 返回失败 query=%s: %s", query, e)
        return [], []

    if not result:
        return [], []

    values = result[0].get("values", [])

    ts = []
    ys = []

    for item in values:
        if len(item) < 2:
            continue

        try:
            t = float(item[0])
            y = float(item[1])
        except Exception:
            continue

        if not math.isfinite(t) or not math.isfinite(y):
            continue

        ts.append(t)
        ys.append(y)

    return ts, ys


def normalize_history(ts: List[float], ys: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    if not ts or not ys or len(ts) != len(ys):
        return np.array([]), np.array([])

    data = {}

    for t, y in zip(ts, ys):
        try:
            sec = int(round(float(t)))
            val = float(y)
        except Exception:
            continue

        if not math.isfinite(sec) or not math.isfinite(val):
            continue

        data[sec] = val

    if not data:
        return np.array([]), np.array([])

    sorted_items = sorted(data.items(), key=lambda x: x[0])

    ts_clean = np.array([x[0] for x in sorted_items], dtype=float)
    ys_clean = np.array([x[1] for x in sorted_items], dtype=float)

    if len(ts_clean) < 2:
        return ts_clean, ys_clean

    start_sec = int(ts_clean[0])
    end_sec = int(ts_clean[-1])

    if end_sec <= start_sec:
        return ts_clean, ys_clean

    ts_grid = np.arange(start_sec, end_sec + 1, 1, dtype=float)
    ys_grid = np.interp(ts_grid, ts_clean, ys_clean)

    return ts_grid, ys_grid


# =============================================================================
# 周期估计
# =============================================================================

def moving_average(arr: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(arr) < window:
        return arr.astype(float)

    window = int(window)

    if window % 2 == 0:
        window += 1

    kernel = np.ones(window, dtype=float) / window
    pad = window // 2
    padded = np.pad(arr.astype(float), (pad, pad), mode="edge")

    return np.convolve(padded, kernel, mode="valid")


def estimate_period_by_fft(ys_arr: np.ndarray) -> float:
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

    power = np.abs(fft_vals[1:])

    if len(power) == 0 or np.max(power) <= 0:
        return 60.0

    dominant_idx = int(np.argmax(power)) + 1
    dominant_freq = float(freqs[dominant_idx])

    if dominant_freq <= 0:
        return 60.0

    period = 1.0 / dominant_freq

    return float(np.clip(period, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))


def refine_period_by_autocorr(ys_arr: np.ndarray, init_period: float) -> float:
    n = len(ys_arr)

    if n < 20:
        return float(np.clip(init_period, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))

    centered = ys_arr - np.mean(ys_arr)

    if np.allclose(centered, 0):
        return float(np.clip(init_period, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))

    corr = np.correlate(centered, centered, mode="full")[n - 1:]

    p0 = int(round(init_period))
    left = max(int(MIN_PERIOD_SECONDS), int(max(2, p0 * 0.7)))
    right = min(n // 2, int(max(left + 1, p0 * 1.3)))

    if right <= left:
        return float(np.clip(init_period, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))

    search = corr[left:right + 1]

    if len(search) == 0:
        return float(np.clip(init_period, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))

    best_lag = left + int(np.argmax(search))

    return float(np.clip(best_lag, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))


def estimate_period_rough(ys_arr: np.ndarray) -> int:
    p_fft = estimate_period_by_fft(ys_arr)
    p_refined = refine_period_by_autocorr(ys_arr, p_fft)

    period = int(round(p_refined))
    period = max(int(MIN_PERIOD_SECONDS), min(int(MAX_PERIOD_SECONDS), period))

    return int(period)


# =============================================================================
# 谷底检测与模板构建
# =============================================================================

def find_valley_indices(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    expected_period: int,
) -> List[int]:
    n = len(ys_grid)

    if n < max(10, expected_period * 2):
        return []

    period = max(3, int(expected_period))

    smooth_window = max(3, int(round(period * 0.08)))
    smooth_window = min(smooth_window, 21)

    ys_smooth = moving_average(ys_grid, smooth_window)
    threshold = float(np.percentile(ys_smooth, VALLEY_QUANTILE))

    candidates = []

    for i in range(1, n - 1):
        if (
            ys_smooth[i] <= ys_smooth[i - 1]
            and ys_smooth[i] < ys_smooth[i + 1]
            and ys_smooth[i] <= threshold
        ):
            candidates.append(i)

    if len(candidates) < MIN_FULL_CYCLES_FOR_TEMPLATE:
        candidates = []

        for i in range(1, n - 1):
            if ys_smooth[i] <= ys_smooth[i - 1] and ys_smooth[i] < ys_smooth[i + 1]:
                candidates.append(i)

    if not candidates:
        return []

    min_distance = max(2, int(round(period * 0.55)))
    selected = []

    for idx in candidates:
        if not selected:
            selected.append(idx)
            continue

        if idx - selected[-1] >= min_distance:
            selected.append(idx)
            continue

        if ys_smooth[idx] < ys_smooth[selected[-1]]:
            selected[-1] = idx

    if len(selected) < 2:
        return selected

    cleaned = [selected[0]]

    for idx in selected[1:]:
        diff = int(ts_grid[idx] - ts_grid[cleaned[-1]])

        if int(period * 0.55) <= diff <= int(period * 1.60):
            cleaned.append(idx)
            continue

        if diff < int(period * 0.55):
            if ys_smooth[idx] < ys_smooth[cleaned[-1]]:
                cleaned[-1] = idx
            continue

        cleaned.append(idx)

    return cleaned


def detect_period_and_valleys(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
) -> Tuple[int, List[int]]:
    rough = estimate_period_rough(ys_grid)
    valleys = find_valley_indices(ts_grid, ys_grid, rough)

    if len(valleys) >= 3:
        diffs = np.diff(ts_grid[valleys])
        good = diffs[(diffs >= rough * 0.55) & (diffs <= rough * 1.60)]

        if len(good) > 0:
            period = int(round(float(np.median(good))))
        else:
            period = rough
    else:
        period = rough

    period = max(int(MIN_PERIOD_SECONDS), min(int(MAX_PERIOD_SECONDS), period))

    return int(period), valleys


def build_template_from_valleys(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    period: int,
    valleys: List[int],
    max_cycles: int = MAX_CYCLES_FOR_TEMPLATE,
) -> Optional[np.ndarray]:
    if period <= 1 or len(valleys) < MIN_FULL_CYCLES_FOR_TEMPLATE + 1:
        return None

    pairs = []

    for a, b in zip(valleys[:-1], valleys[1:]):
        cycle_len = float(ts_grid[b] - ts_grid[a])

        if period * 0.55 <= cycle_len <= period * 1.60:
            pairs.append((a, b, cycle_len))

    if len(pairs) < MIN_FULL_CYCLES_FOR_TEMPLATE:
        return None

    pairs = pairs[-max_cycles:]

    phase_grid = np.arange(period, dtype=float)
    segments = []
    weights = []

    for idx, (a, b, cycle_len) in enumerate(pairs):
        seg_ts = ts_grid[a:b + 1]
        seg_y = ys_grid[a:b + 1]

        if len(seg_y) < 3:
            continue

        x_old = (seg_ts - seg_ts[0]) / cycle_len * period
        seg = np.interp(phase_grid, x_old, seg_y)

        segments.append(seg.astype(float))

        weight = 0.5 + 0.5 * ((idx + 1) / len(pairs))
        weights.append(weight)

    if len(segments) < MIN_FULL_CYCLES_FOR_TEMPLATE:
        return None

    arr = np.vstack(segments)
    w_arr = np.array(weights, dtype=float)

    template = np.average(arr, axis=0, weights=w_arr)

    return template.astype(float)


def build_current_baseline(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    tail_seconds: Optional[int] = None,
) -> Optional[Tuple[int, int, np.ndarray]]:
    if len(ys_grid) < MIN_POINTS:
        return None

    if tail_seconds is not None and tail_seconds > 0:
        cutoff = ts_grid[-1] - int(tail_seconds)
        mask = ts_grid >= cutoff
        ts_use = ts_grid[mask]
        ys_use = ys_grid[mask]
    else:
        ts_use = ts_grid
        ys_use = ys_grid

    if len(ys_use) < MIN_POINTS:
        return None

    period, valleys = detect_period_and_valleys(ts_use, ys_use)

    template = build_template_from_valleys(
        ts_grid=ts_use,
        ys_grid=ys_use,
        period=period,
        valleys=valleys,
    )

    if template is None or len(valleys) == 0:
        return None

    phase_origin_ts = int(round(float(ts_use[valleys[-1]])))

    return int(period), phase_origin_ts, template


# =============================================================================
# 模板预测与重采样
# =============================================================================

def circular_template_value(template: np.ndarray, phase: float) -> float:
    period = len(template)

    if period == 0:
        return 0.0

    phase = float(phase) % period

    i0 = int(math.floor(phase)) % period
    i1 = (i0 + 1) % period
    frac = phase - math.floor(phase)

    return float((1.0 - frac) * template[i0] + frac * template[i1])


def resample_template(old_template: np.ndarray, new_period: int) -> np.ndarray:
    old_period = len(old_template)

    if old_period == new_period:
        return old_template.astype(float)

    if old_period <= 1 or new_period <= 1:
        return np.full(new_period, float(np.mean(old_template)), dtype=float)

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
    if period <= 1:
        return np.zeros(len(ts_list), dtype=float)

    if len(template) != period:
        template = resample_template(template, period)

    values = []

    for ts in ts_list:
        phase = (int(ts) - int(phase_origin_ts)) % period
        values.append(circular_template_value(template, phase))

    return np.array(values, dtype=float)


def predict_with_state(state: BaselineState, ts_list: List[int]) -> np.ndarray:
    template = np.array(state.template, dtype=float)

    return predict_template_values(
        template=template,
        period=int(state.period),
        phase_origin_ts=int(state.phase_origin_ts),
        ts_list=ts_list,
    )


def normalize_origin_near(origin: int, period: int, near_ts: int) -> int:
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


def align_new_template_to_old(
    old_template: np.ndarray,
    new_template: np.ndarray,
) -> np.ndarray:
    if len(old_template) != len(new_template):
        old_template = resample_template(old_template, len(new_template))

    period = len(new_template)

    if period <= 2:
        return new_template.astype(float)

    max_shift = max(1, int(round(period * 0.10)))
    old_norm = old_template - np.mean(old_template)

    best_score = None
    best_template = new_template

    for shift in range(-max_shift, max_shift + 1):
        shifted = np.roll(new_template, shift)
        shifted_norm = shifted - np.mean(shifted)
        score = float(np.dot(old_norm, shifted_norm))

        if best_score is None or score > best_score:
            best_score = score
            best_template = shifted

    return best_template.astype(float)


def merge_template(
    old_template: np.ndarray,
    new_template: np.ndarray,
    alpha: float,
) -> np.ndarray:
    alpha = float(np.clip(alpha, 0.0, 1.0))

    if len(old_template) != len(new_template):
        old_template = resample_template(old_template, len(new_template))

    new_template = align_new_template_to_old(old_template, new_template)

    merged = (1.0 - alpha) * old_template + alpha * new_template

    return merged.astype(float)


# =============================================================================
# Phase Lock
# =============================================================================

def phase_lock_recent(
    state: BaselineState,
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
) -> Tuple[int, int, np.ndarray, float]:
    base_period = int(state.period)
    base_origin = int(state.phase_origin_ts)
    base_template = np.array(state.template, dtype=float)

    if base_period <= 1 or len(base_template) <= 1:
        ts_recent = ts_grid[-DETECT_WINDOW_SECONDS:].astype(int).tolist()
        pred = predict_with_state(state, ts_recent)
        actual = ys_grid[-len(ts_recent):].astype(float)
        mae = float(np.mean(np.abs(actual - pred))) if len(actual) else 0.0
        return base_period, base_origin, pred, mae

    window_seconds = max(
        PHASE_LOCK_MIN_WINDOW_SECONDS,
        min(PHASE_LOCK_MAX_WINDOW_SECONDS, int(base_period * 2)),
    )

    cutoff = ts_grid[-1] - window_seconds
    mask = ts_grid >= cutoff

    ts_recent_arr = ts_grid[mask].astype(int)
    actual = ys_grid[mask].astype(float)

    if len(ts_recent_arr) < max(10, DETECT_WINDOW_SECONDS):
        ts_recent_arr = ts_grid[-DETECT_WINDOW_SECONDS:].astype(int)
        actual = ys_grid[-DETECT_WINDOW_SECONDS:].astype(float)

    ts_recent = ts_recent_arr.tolist()
    last_ts = int(ts_recent[-1])

    p_min = max(int(MIN_PERIOD_SECONDS), int(round(base_period * (1.0 - PHASE_LOCK_PERIOD_SEARCH_RATIO))))
    p_max = min(int(MAX_PERIOD_SECONDS), int(round(base_period * (1.0 + PHASE_LOCK_PERIOD_SEARCH_RATIO))))

    if p_max < p_min:
        p_min = p_max = base_period

    best_period = base_period
    best_origin = normalize_origin_near(base_origin, base_period, last_ts)
    best_template = resample_template(base_template, best_period)
    best_pred = predict_template_values(best_template, best_period, best_origin, ts_recent)
    best_mae = float(np.mean(np.abs(actual - best_pred)))

    for period in range(p_min, p_max + 1, PHASE_LOCK_PERIOD_STEP):
        template = resample_template(base_template, period)
        center_origin = normalize_origin_near(base_origin, period, last_ts)

        origin_shift = max(2, int(round(period * PHASE_LOCK_ORIGIN_SEARCH_RATIO)))

        for shift in range(-origin_shift, origin_shift + 1, PHASE_LOCK_ORIGIN_STEP):
            origin = center_origin + shift

            pred = predict_template_values(
                template=template,
                period=period,
                phase_origin_ts=origin,
                ts_list=ts_recent,
            )

            mae = float(np.mean(np.abs(actual - pred)))

            # 轻微惩罚周期变化，避免过拟合抖动
            penalty = abs(period - base_period) * 0.5
            score = mae + penalty

            best_score = best_mae + abs(best_period - base_period) * 0.5

            if score < best_score:
                best_period = period
                best_origin = origin
                best_pred = pred
                best_mae = mae

    best_origin = normalize_origin_near(best_origin, best_period, last_ts)

    return int(best_period), int(best_origin), best_pred, float(best_mae)


# =============================================================================
# 异常检测
# =============================================================================

def calc_threshold(
    pred: np.ndarray,
    abs_threshold: float,
    rel_threshold: float,
) -> np.ndarray:
    return np.maximum(abs_threshold, np.abs(pred) * rel_threshold)


def calc_bounds(
    pred: np.ndarray,
    abs_threshold: float,
    rel_threshold: float,
) -> Tuple[np.ndarray, np.ndarray]:
    threshold = calc_threshold(pred, abs_threshold, rel_threshold)

    return pred - threshold, pred + threshold


def detect_anomaly(
    state: BaselineState,
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    abs_threshold: float,
    rel_threshold: float,
) -> Tuple[bool, float, float, float, int, int]:
    best_period, best_origin, pred_recent, _ = phase_lock_recent(
        state=state,
        ts_grid=ts_grid,
        ys_grid=ys_grid,
    )

    recent_len = len(pred_recent)

    if recent_len <= 0:
        return False, 0.0, 0.0, 0.0, best_period, best_origin

    actual = ys_grid[-recent_len:].astype(float)

    threshold = calc_threshold(pred_recent, abs_threshold, rel_threshold)

    abs_err = np.abs(actual - pred_recent)
    outside = abs_err > threshold

    outside_ratio = float(np.mean(outside))
    mean_abs_err = float(np.mean(abs_err))
    mean_rel_err = float(np.mean(abs_err / np.maximum(np.abs(pred_recent), 1.0)))

    is_anomaly = outside_ratio >= OUTSIDE_RATIO_THRESHOLD

    return (
        is_anomaly,
        outside_ratio,
        mean_abs_err,
        mean_rel_err,
        int(best_period),
        int(best_origin),
    )


# =============================================================================
# 健康基线状态管理
# =============================================================================

def create_initial_state(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    now_sec: int,
) -> Optional[BaselineState]:
    baseline = build_current_baseline(ts_grid, ys_grid)

    if baseline is None:
        return None

    period, phase_origin_ts, template = baseline

    return BaselineState(
        period=int(period),
        phase_origin_ts=int(phase_origin_ts),
        template=template.astype(float).tolist(),
        status=BASELINE_STATUS_HEALTHY,
        clean_seconds=int(period * MAX_CYCLES_FOR_TEMPLATE),
        last_update_ts=now_sec,
        last_seen_ts=now_sec,
        y_min=float(np.min(ys_grid)),
        y_max=float(np.max(ys_grid)),
    )


def apply_phase_lock_to_state(
    state: BaselineState,
    best_period: int,
    best_origin: int,
) -> None:
    best_period = int(best_period)

    if best_period <= 1:
        return

    template = np.array(state.template, dtype=float)

    if len(template) != best_period:
        template = resample_template(template, best_period)

    state.period = best_period
    state.phase_origin_ts = int(best_origin)
    state.template = template.astype(float).tolist()


def maybe_update_state(
    key: str,
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    abs_threshold: float,
    rel_threshold: float,
) -> Tuple[Optional[BaselineState], bool, float, float, float]:
    now_sec = int(time.time())
    state = BASELINE_STATES.get(key)

    if state is None:
        state = create_initial_state(ts_grid, ys_grid, now_sec)

        if state is None:
            return None, False, 0.0, 0.0, 0.0

        BASELINE_STATES[key] = state

        logger.info(
            "初始化健康模板 key=%s period=%ss origin=%s clean=%ss",
            key,
            state.period,
            datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S"),
            state.clean_seconds,
        )

        return state, False, 0.0, 0.0, 0.0

    elapsed = max(1, now_sec - int(state.last_seen_ts))
    elapsed = min(elapsed, POLL_INTERVAL * 2)
    state.last_seen_ts = now_sec

    (
        is_anomaly,
        outside_ratio,
        mean_abs_err,
        mean_rel_err,
        best_period,
        best_origin,
    ) = detect_anomaly(
        state=state,
        ts_grid=ts_grid,
        ys_grid=ys_grid,
        abs_threshold=abs_threshold,
        rel_threshold=rel_threshold,
    )

    if is_anomaly:
        state.status = BASELINE_STATUS_ANOMALY
        state.clean_seconds = 0

        BASELINE_STATES[key] = state

        logger.warning(
            "检测到异常，冻结模板 key=%s outside_ratio=%.2f mean_abs_err=%.2f mean_rel_err=%.2f",
            key,
            outside_ratio,
            mean_abs_err,
            mean_rel_err,
        )

        return state, True, outside_ratio, mean_abs_err, mean_rel_err

    old_period = int(state.period)
    old_origin = int(state.phase_origin_ts)

    apply_phase_lock_to_state(state, best_period, best_origin)

    if old_period != state.period or old_origin != state.phase_origin_ts:
        logger.info(
            "phase-lock key=%s period %s -> %s origin %s -> %s",
            key,
            old_period,
            state.period,
            datetime.fromtimestamp(old_origin).strftime("%H:%M:%S"),
            datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S"),
        )

    if state.status == BASELINE_STATUS_ANOMALY:
        state.status = BASELINE_STATUS_RECOVERING
        state.clean_seconds = elapsed

        BASELINE_STATES[key] = state

        logger.info(
            "异常开始恢复 key=%s clean_seconds=%ss",
            key,
            state.clean_seconds,
        )

        return state, False, outside_ratio, mean_abs_err, mean_rel_err

    if state.status == BASELINE_STATUS_RECOVERING:
        state.clean_seconds += elapsed
    else:
        state.status = BASELINE_STATUS_HEALTHY
        state.clean_seconds += elapsed

    min_clean_for_update = max(
        RECOVERY_MIN_SECONDS,
        int(state.period) * MIN_FULL_CYCLES_FOR_TEMPLATE,
    )

    if state.clean_seconds < min_clean_for_update:
        BASELINE_STATES[key] = state
        return state, False, outside_ratio, mean_abs_err, mean_rel_err

    tail_seconds = min(
        int(state.clean_seconds),
        int(state.period) * MAX_CYCLES_FOR_TEMPLATE,
    )

    baseline = build_current_baseline(
        ts_grid=ts_grid,
        ys_grid=ys_grid,
        tail_seconds=tail_seconds,
    )

    if baseline is None:
        BASELINE_STATES[key] = state
        return state, False, outside_ratio, mean_abs_err, mean_rel_err

    new_period, new_origin, new_template = baseline

    old_template = np.array(state.template, dtype=float)

    alpha = RECOVERY_EMA_ALPHA if state.status == BASELINE_STATUS_RECOVERING else HEALTHY_EMA_ALPHA

    merged = merge_template(
        old_template=old_template,
        new_template=new_template,
        alpha=alpha,
    )

    state.period = int(new_period)
    state.phase_origin_ts = int(new_origin)
    state.template = merged.astype(float).tolist()
    state.status = BASELINE_STATUS_HEALTHY
    state.last_update_ts = now_sec

    if tail_seconds > 0 and len(ys_grid) >= tail_seconds:
        state.y_min = float(np.min(ys_grid[-tail_seconds:]))
        state.y_max = float(np.max(ys_grid[-tail_seconds:]))
    else:
        state.y_min = float(np.min(ys_grid))
        state.y_max = float(np.max(ys_grid))

    BASELINE_STATES[key] = state

    logger.info(
        "更新健康模板 key=%s period=%ss origin=%s clean=%ss alpha=%.2f",
        key,
        state.period,
        datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S"),
        state.clean_seconds,
        alpha,
    )

    return state, False, outside_ratio, mean_abs_err, mean_rel_err


# =============================================================================
# Prometheus Exposition 写入
# =============================================================================

def prom_escape_label_value(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def labels_to_str(labels: Dict[str, str]) -> str:
    if not labels:
        return ""

    parts = []

    for k in sorted(labels.keys()):
        parts.append(f'{k}="{prom_escape_label_value(labels[k])}"')

    return "{" + ",".join(parts) + "}"


def write_series(
    metric_name: str,
    labels: Dict[str, str],
    ts_list: List[int],
    values: List[float],
) -> bool:
    if not ts_list or not values or len(ts_list) != len(values):
        return False

    label_str = labels_to_str(labels)
    lines = []

    for t, y in zip(ts_list, values):
        try:
            ts_sec = int(round(float(t)))
            val = float(y)
        except Exception:
            continue

        if not math.isfinite(ts_sec) or not math.isfinite(val):
            continue

        lines.append(f"{metric_name}{label_str} {val:.6f} {ts_sec * 1000}")

    if not lines:
        return False

    payload = "\n".join(lines) + "\n"

    try:
        resp = requests.post(
            f"{VM_URL}/api/v1/import/prometheus",
            data=payload.encode("utf-8"),
            headers={
                "Content-Type": "text/plain; version=0.0.4; charset=utf-8",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True

    except requests.RequestException as e:
        logger.error("写入数据失败 metric=%s: %s", metric_name, e)
        return False


def write_prediction_bundle(
    pred_metric: str,
    anomaly_metric: str,
    labels: Dict[str, str],
    ts_future: List[int],
    pred_values: np.ndarray,
    lower_values: np.ndarray,
    upper_values: np.ndarray,
    is_anomaly: bool,
    outside_ratio: float,
    mean_abs_err: float,
    mean_rel_err: float,
    event_ts: int,
) -> bool:
    ok1 = write_series(
        metric_name=pred_metric,
        labels=labels,
        ts_list=ts_future,
        values=pred_values.astype(float).tolist(),
    )

    ok2 = write_series(
        metric_name=f"{pred_metric}_lower",
        labels=labels,
        ts_list=ts_future,
        values=lower_values.astype(float).tolist(),
    )

    ok3 = write_series(
        metric_name=f"{pred_metric}_upper",
        labels=labels,
        ts_list=ts_future,
        values=upper_values.astype(float).tolist(),
    )

    anomaly_labels = dict(labels)
    anomaly_labels["type"] = "prediction_deviation"

    ok4 = write_series(
        metric_name=anomaly_metric,
        labels=anomaly_labels,
        ts_list=[event_ts],
        values=[1.0 if is_anomaly else 0.0],
    )

    ok5 = write_series(
        metric_name=f"{anomaly_metric}_outside_ratio",
        labels=anomaly_labels,
        ts_list=[event_ts],
        values=[outside_ratio],
    )

    ok6 = write_series(
        metric_name=f"{anomaly_metric}_mean_abs_error",
        labels=anomaly_labels,
        ts_list=[event_ts],
        values=[mean_abs_err],
    )

    ok7 = write_series(
        metric_name=f"{anomaly_metric}_mean_rel_error",
        labels=anomaly_labels,
        ts_list=[event_ts],
        values=[mean_rel_err],
    )

    return ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7


# =============================================================================
# 标签解析
# =============================================================================

_LABEL_PATTERN = re.compile(
    r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"((?:\\.|[^"])*)"\s*'
)


def parse_labels_from_query(query: str) -> Dict[str, str]:
    labels = {}

    if "{" not in query or "}" not in query:
        return labels

    try:
        label_part = query[query.index("{") + 1:query.rindex("}")]
    except Exception:
        return labels

    for match in _LABEL_PATTERN.finditer(label_part):
        key = match.group(1)
        value = match.group(2)

        value = (
            value
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\\\", "\\")
        )

        labels[key] = value

    return labels


def merge_labels(*dicts: Dict[str, str]) -> Dict[str, str]:
    result = {}

    for d in dicts:
        if d:
            result.update(d)

    return result


def series_key(metric_name: str, labels: Dict[str, str]) -> str:
    return metric_name + labels_to_str(labels)


# =============================================================================
# 状态持久化
# =============================================================================

def load_state() -> None:
    global BASELINE_STATES

    if not os.path.exists(STATE_FILE):
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        states = {}

        for key, value in raw.get("baseline_states", {}).items():
            required_fields = {
                "period",
                "phase_origin_ts",
                "template",
                "status",
                "clean_seconds",
                "last_update_ts",
                "last_seen_ts",
                "y_min",
                "y_max",
            }

            if not required_fields.issubset(set(value.keys())):
                continue

            states[key] = BaselineState(**value)

        BASELINE_STATES = states

        logger.info(
            "已加载预测状态文件 %s，状态数量=%d",
            STATE_FILE,
            len(BASELINE_STATES),
        )

    except Exception as e:
        logger.warning("加载预测状态文件失败，将重新学习: %s", e)


def save_state() -> None:
    try:
        raw = {
            "baseline_states": {
                key: asdict(value)
                for key, value in BASELINE_STATES.items()
            }
        }

        tmp_file = STATE_FILE + ".tmp"

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        os.replace(tmp_file, STATE_FILE)

    except Exception as e:
        logger.warning("保存预测状态文件失败: %s", e)


# =============================================================================
# 时间轴
# =============================================================================

def build_prediction_timestamps(
    key: str,
    last_real_ts: int,
    now_sec: int,
) -> Optional[List[int]]:
    data_lag = now_sec - last_real_ts

    if data_lag > MAX_DATA_LAG_SECONDS:
        logger.warning(
            "真实数据延迟过大，跳过预测 key=%s data_lag=%ss max=%ss",
            key,
            data_lag,
            MAX_DATA_LAG_SECONDS,
        )
        return None

    last_written_real_ts = LAST_REAL_TS_WRITTEN.get(key)

    if last_written_real_ts is not None and last_real_ts <= int(last_written_real_ts):
        logger.info(
            "真实数据时间戳未推进，跳过重复写入 key=%s last_real_ts=%s last_written_real_ts=%s",
            key,
            last_real_ts,
            last_written_real_ts,
        )
        return None

    if ALIGN_PREDICTION_TO_LAST_REAL_TS:
        base_ts = last_real_ts
    else:
        base_ts = now_sec

    return [
        base_ts + i + 1
        for i in range(WRITE_HORIZON_SECONDS)
    ]


# =============================================================================
# 主流程
# =============================================================================

def run_once() -> None:
    now_str = datetime.now().strftime("%H:%M:%S")

    for target in PREDICT_TARGETS:
        query = target["query"]
        pred_metric = target["pred_metric"]
        anomaly_metric = target["anomaly_metric"]
        abs_threshold = float(target["abs_threshold"])
        rel_threshold = float(target["rel_threshold"])

        ts, ys = fetch_history(query)

        if len(ys) < MIN_POINTS:
            logger.info(
                "[%s] %s 数据不足（%d 点），跳过",
                now_str,
                query,
                len(ys),
            )
            continue

        ts_grid, ys_grid = normalize_history(ts, ys)

        if len(ys_grid) < MIN_POINTS:
            logger.info(
                "[%s] %s 清洗后数据不足（%d 点），跳过",
                now_str,
                query,
                len(ys_grid),
            )
            continue

        base_labels = parse_labels_from_query(query)
        write_labels = merge_labels(base_labels, EXTRA_PREDICT_LABELS)

        key = series_key(pred_metric, write_labels)

        state, is_anomaly, outside_ratio, mean_abs_err, mean_rel_err = maybe_update_state(
            key=key,
            ts_grid=ts_grid,
            ys_grid=ys_grid,
            abs_threshold=abs_threshold,
            rel_threshold=rel_threshold,
        )

        if state is None:
            logger.info(
                "[%s] %s 暂无可用健康模板，等待学习",
                now_str,
                query,
            )
            continue

        now_sec = int(time.time())
        last_real_ts = int(ts_grid[-1])
        data_lag = now_sec - last_real_ts

        ts_future = build_prediction_timestamps(
            key=key,
            last_real_ts=last_real_ts,
            now_sec=now_sec,
        )

        if not ts_future:
            continue

        pred_values = predict_with_state(state, ts_future)

        lower_values, upper_values = calc_bounds(
            pred=pred_values,
            abs_threshold=abs_threshold,
            rel_threshold=rel_threshold,
        )

        ok = write_prediction_bundle(
            pred_metric=pred_metric,
            anomaly_metric=anomaly_metric,
            labels=write_labels,
            ts_future=ts_future,
            pred_values=pred_values,
            lower_values=lower_values,
            upper_values=upper_values,
            is_anomaly=is_anomaly,
            outside_ratio=outside_ratio,
            mean_abs_err=mean_abs_err,
            mean_rel_err=mean_rel_err,
            event_ts=last_real_ts,
        )

        if not ok:
            logger.error(
                "[%s] %s 写入预测数据失败",
                now_str,
                query,
            )
            continue

        LAST_REAL_TS_WRITTEN[key] = last_real_ts

        future_start = datetime.fromtimestamp(ts_future[0]).strftime("%H:%M:%S")
        future_end = datetime.fromtimestamp(ts_future[-1]).strftime("%H:%M:%S")
        last_real_str = datetime.fromtimestamp(last_real_ts).strftime("%H:%M:%S")
        origin_str = datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S")

        logger.info(
            "[%s] %-40s → %-35s status=%s anomaly=%s period=%ss origin=%s last_real=%s lag=%ss 写入 %d 点，预测区间 %s ~ %s",
            now_str,
            query,
            pred_metric,
            state.status,
            is_anomaly,
            state.period,
            origin_str,
            last_real_str,
            data_lag,
            len(ts_future),
            future_start,
            future_end,
        )

    save_state()


def main() -> None:
    load_state()

    logger.info(
        "预测服务启动 VM=%s 历史窗口=%dmin 理论预测窗口=%ds 实际写入窗口=%ds 轮询间隔=%ds state=%s forecast=%s align_to_last_real=%s",
        VM_URL,
        HISTORY_MINUTES,
        HORIZON_SECONDS,
        WRITE_HORIZON_SECONDS,
        POLL_INTERVAL,
        STATE_FILE,
        EXTRA_PREDICT_LABELS["forecast"],
        ALIGN_PREDICTION_TO_LAST_REAL_TS,
    )

    while True:
        run_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()