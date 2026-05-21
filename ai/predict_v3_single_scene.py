# -*- coding: utf-8 -*-
"""
ProtoForge 预测服务 v6

核心能力：
1. 周期模板预测：适合 CNC 这类强周期、非标准正弦波形。
2. 健康基线冻结：检测到异常后，不再用故障数据更新预测模板。
3. 恢复冷却机制：故障恢复后，需要连续稳定多个周期，才恢复学习。
4. 预测上下界：写入 predicted_upper / predicted_lower，方便 Grafana 展示预测带。
5. 异常标记：写入 xxx_anomaly，1 表示异常，0 表示正常。
6. 不删除历史预测，不使用 delete_series。
"""

"""
场景：不考虑物料、不考虑跨程序场景算法预测
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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ── 基础配置 ──────────────────────────────────────────────────────────────────

VM_URL = "http://localhost:8428"

STATE_FILE = "/tmp/protoforge_predictor_state.json"

HISTORY_MINUTES = 30
HORIZON_SECONDS = 120
POLL_INTERVAL = 30

# 实际每轮写入未来多少秒。
# 不要大于 POLL_INTERVAL，否则多轮预测会重叠。
WRITE_HORIZON_SECONDS = min(HORIZON_SECONDS, POLL_INTERVAL)

QUERY_STEP = "1s"
MIN_POINTS = 120

MIN_PERIOD_SECONDS = 5
MAX_PERIOD_SECONDS = 3600

# 至少多少个完整周期才允许构建健康模板
MIN_FULL_CYCLES_FOR_TEMPLATE = 3

# 构建模板最多使用最近多少个周期
MAX_CYCLES_FOR_TEMPLATE = 6

# 检测异常使用最近多少秒实际数据
DETECT_WINDOW_SECONDS = 15

# 恢复后，至少连续正常多少秒才考虑恢复学习
RECOVERY_MIN_SECONDS = 60

# 健康状态下模板更新速度，越小越保守
HEALTHY_EMA_ALPHA = 0.15

# 故障恢复后第一次重新学习时的更新速度
RECOVERY_EMA_ALPHA = 0.35

# 最近窗口里有多少比例的点超过阈值，才认为异常
OUTSIDE_RATIO_THRESHOLD = 0.60

# 最近窗口里有多少比例的点回到阈值内，才认为恢复正常
RECOVERY_INSIDE_RATIO_THRESHOLD = 0.80


# ── 指标配置 ──────────────────────────────────────────────────────────────────
# abs_threshold / rel_threshold 需要按指标单位调。
# feed_rate 单位 mm/min，这里先给 400 和 25%。

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
    "forecast": "health_gated_v1",
    "source": "protoforge",
}

BASELINE_STATUS_HEALTHY = "healthy"
BASELINE_STATUS_ANOMALY = "anomaly"
BASELINE_STATUS_RECOVERING = "recovering"
BASELINE_STATUS_LEARNING = "learning"


# ── 状态结构 ──────────────────────────────────────────────────────────────────

@dataclass
class BaselineState:
    period: int
    template: List[float]
    status: str
    clean_seconds: int
    last_update_ts: int
    last_seen_ts: int
    y_min: float
    y_max: float


BASELINE_STATES: Dict[str, BaselineState] = {}
LAST_WRITTEN_UNTIL: Dict[str, int] = {}


# ── VM 读取 ───────────────────────────────────────────────────────────────────

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
    if not values:
        return [], []

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


# ── 周期估计 ──────────────────────────────────────────────────────────────────

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
    left = max(MIN_PERIOD_SECONDS, int(max(2, p0 * 0.7)))
    right = min(n // 2, int(max(left + 1, p0 * 1.3)))

    if right <= left:
        return float(np.clip(init_period, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))

    search = corr[left:right + 1]

    if len(search) == 0:
        return float(np.clip(init_period, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))

    best_lag = left + int(np.argmax(search))

    return float(np.clip(best_lag, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))


def estimate_period(ys_arr: np.ndarray) -> int:
    p_fft = estimate_period_by_fft(ys_arr)
    p_refined = refine_period_by_autocorr(ys_arr, p_fft)

    period = int(round(p_refined))
    period = max(MIN_PERIOD_SECONDS, min(MAX_PERIOD_SECONDS, period))

    return int(period)


# ── 模板构建与预测 ─────────────────────────────────────────────────────────────

def fill_template_nan(template: np.ndarray) -> np.ndarray:
    period = len(template)

    if period == 0:
        return template

    idx = np.arange(period)
    valid = np.isfinite(template)

    if not np.any(valid):
        return np.zeros(period, dtype=float)

    if np.all(valid):
        return template

    x_valid = idx[valid]
    y_valid = template[valid]

    # 环形插值，处理 phase 0 附近缺口
    x_ext = np.concatenate([x_valid - period, x_valid, x_valid + period])
    y_ext = np.concatenate([y_valid, y_valid, y_valid])

    filled = np.interp(idx, x_ext, y_ext)

    return filled.astype(float)


def build_phase_template(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    period: int,
    max_cycles: int = MAX_CYCLES_FOR_TEMPLATE,
    tail_seconds: Optional[int] = None,
) -> Optional[np.ndarray]:
    if period <= 1 or len(ys_grid) < period * MIN_FULL_CYCLES_FOR_TEMPLATE:
        return None

    max_seconds = period * max_cycles

    if tail_seconds is not None:
        max_seconds = min(max_seconds, int(tail_seconds))

    max_seconds = max(period * MIN_FULL_CYCLES_FOR_TEMPLATE, max_seconds)

    if len(ys_grid) < max_seconds:
        start_idx = 0
    else:
        start_idx = len(ys_grid) - max_seconds

    ts_tail = ts_grid[start_idx:]
    ys_tail = ys_grid[start_idx:]

    if len(ys_tail) < period * MIN_FULL_CYCLES_FOR_TEMPLATE:
        return None

    sums = np.zeros(period, dtype=float)
    weights = np.zeros(period, dtype=float)

    total = len(ys_tail)

    for i, (t, y) in enumerate(zip(ts_tail, ys_tail)):
        phase = int(t) % period

        # 越近的数据权重越高
        recency = (i + 1) / total
        weight = 0.3 + 0.7 * recency

        sums[phase] += float(y) * weight
        weights[phase] += weight

    template = np.full(period, np.nan, dtype=float)

    valid = weights > 0
    template[valid] = sums[valid] / weights[valid]

    template = fill_template_nan(template)

    return template


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


def merge_template(
    old_template: np.ndarray,
    new_template: np.ndarray,
    alpha: float,
) -> np.ndarray:
    alpha = float(np.clip(alpha, 0.0, 1.0))

    if len(old_template) != len(new_template):
        old_template = resample_template(old_template, len(new_template))

    return ((1.0 - alpha) * old_template + alpha * new_template).astype(float)


def predict_by_state(state: BaselineState, ts_list: List[int]) -> np.ndarray:
    template = np.array(state.template, dtype=float)
    period = int(state.period)

    if period <= 1 or len(template) != period:
        return np.zeros(len(ts_list), dtype=float)

    values = []

    for ts in ts_list:
        phase = int(ts) % period
        values.append(float(template[phase]))

    return np.array(values, dtype=float)


def calc_threshold(pred: np.ndarray, abs_threshold: float, rel_threshold: float) -> np.ndarray:
    return np.maximum(abs_threshold, np.abs(pred) * rel_threshold)


def calc_bounds(pred: np.ndarray, abs_threshold: float, rel_threshold: float) -> Tuple[np.ndarray, np.ndarray]:
    threshold = calc_threshold(pred, abs_threshold, rel_threshold)
    lower = pred - threshold
    upper = pred + threshold
    return lower, upper


# ── 异常检测与状态更新 ────────────────────────────────────────────────────────

def detect_anomaly(
    state: BaselineState,
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    abs_threshold: float,
    rel_threshold: float,
) -> Tuple[bool, float, float, float]:
    if len(ys_grid) < DETECT_WINDOW_SECONDS:
        return False, 0.0, 0.0, 0.0

    ts_recent = ts_grid[-DETECT_WINDOW_SECONDS:].astype(int).tolist()
    actual = ys_grid[-DETECT_WINDOW_SECONDS:].astype(float)

    pred = predict_by_state(state, ts_recent)
    threshold = calc_threshold(pred, abs_threshold, rel_threshold)

    abs_err = np.abs(actual - pred)
    outside = abs_err > threshold

    outside_ratio = float(np.mean(outside))
    mean_abs_err = float(np.mean(abs_err))
    mean_rel_err = float(np.mean(abs_err / np.maximum(np.abs(pred), 1.0)))

    is_anomaly = outside_ratio >= OUTSIDE_RATIO_THRESHOLD

    return is_anomaly, outside_ratio, mean_abs_err, mean_rel_err


def is_recovered(
    state: BaselineState,
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    abs_threshold: float,
    rel_threshold: float,
) -> Tuple[bool, float]:
    if len(ys_grid) < DETECT_WINDOW_SECONDS:
        return False, 0.0

    ts_recent = ts_grid[-DETECT_WINDOW_SECONDS:].astype(int).tolist()
    actual = ys_grid[-DETECT_WINDOW_SECONDS:].astype(float)

    pred = predict_by_state(state, ts_recent)
    threshold = calc_threshold(pred, abs_threshold, rel_threshold)

    abs_err = np.abs(actual - pred)
    inside = abs_err <= threshold

    inside_ratio = float(np.mean(inside))

    return inside_ratio >= RECOVERY_INSIDE_RATIO_THRESHOLD, inside_ratio


def create_initial_state(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    now_sec: int,
) -> Optional[BaselineState]:
    if len(ys_grid) < MIN_POINTS:
        return None

    period = estimate_period(ys_grid)

    template = build_phase_template(
        ts_grid=ts_grid,
        ys_grid=ys_grid,
        period=period,
        max_cycles=MAX_CYCLES_FOR_TEMPLATE,
        tail_seconds=period * MAX_CYCLES_FOR_TEMPLATE,
    )

    if template is None:
        return None

    return BaselineState(
        period=int(period),
        template=template.astype(float).tolist(),
        status=BASELINE_STATUS_HEALTHY,
        clean_seconds=int(period * MAX_CYCLES_FOR_TEMPLATE),
        last_update_ts=now_sec,
        last_seen_ts=now_sec,
        y_min=float(np.min(ys_grid)),
        y_max=float(np.max(ys_grid)),
    )


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
            "初始化健康模板 key=%s period=%ss clean_seconds=%ss",
            key,
            state.period,
            state.clean_seconds,
        )
        return state, False, 0.0, 0.0, 0.0

    elapsed = max(1, now_sec - int(state.last_seen_ts))
    elapsed = min(elapsed, POLL_INTERVAL * 2)
    state.last_seen_ts = now_sec

    is_anom, outside_ratio, mean_abs_err, mean_rel_err = detect_anomaly(
        state=state,
        ts_grid=ts_grid,
        ys_grid=ys_grid,
        abs_threshold=abs_threshold,
        rel_threshold=rel_threshold,
    )

    if is_anom:
        state.status = BASELINE_STATUS_ANOMALY
        state.clean_seconds = 0

        logger.warning(
            "检测到异常，冻结模板 key=%s outside_ratio=%.2f mean_abs_err=%.2f mean_rel_err=%.2f",
            key,
            outside_ratio,
            mean_abs_err,
            mean_rel_err,
        )

        BASELINE_STATES[key] = state
        return state, True, outside_ratio, mean_abs_err, mean_rel_err

    recovered, inside_ratio = is_recovered(
        state=state,
        ts_grid=ts_grid,
        ys_grid=ys_grid,
        abs_threshold=abs_threshold,
        rel_threshold=rel_threshold,
    )

    if state.status == BASELINE_STATUS_ANOMALY:
        if recovered:
            state.status = BASELINE_STATUS_RECOVERING
            state.clean_seconds = elapsed
            logger.info(
                "异常开始恢复 key=%s inside_ratio=%.2f clean_seconds=%ss",
                key,
                inside_ratio,
                state.clean_seconds,
            )
        else:
            state.clean_seconds = 0
            BASELINE_STATES[key] = state
            return state, True, outside_ratio, mean_abs_err, mean_rel_err

    elif state.status == BASELINE_STATUS_RECOVERING:
        if recovered:
            state.clean_seconds += elapsed
        else:
            state.status = BASELINE_STATUS_ANOMALY
            state.clean_seconds = 0
            BASELINE_STATES[key] = state
            return state, True, outside_ratio, mean_abs_err, mean_rel_err

    else:
        state.status = BASELINE_STATUS_HEALTHY
        state.clean_seconds += elapsed

    # 故障恢复后，不要立刻学习。
    # 必须至少连续正常：max(RECOVERY_MIN_SECONDS, 3 个周期)
    min_clean_for_update = max(
        RECOVERY_MIN_SECONDS,
        int(state.period) * MIN_FULL_CYCLES_FOR_TEMPLATE,
    )

    if state.clean_seconds < min_clean_for_update:
        BASELINE_STATES[key] = state
        return state, False, outside_ratio, mean_abs_err, mean_rel_err

    # 只使用最近 clean_seconds 这段连续正常数据来更新模板，避免历史故障污染。
    new_period = estimate_period(ys_grid)
    tail_seconds = min(
        int(state.clean_seconds),
        int(new_period) * MAX_CYCLES_FOR_TEMPLATE,
    )

    new_template = build_phase_template(
        ts_grid=ts_grid,
        ys_grid=ys_grid,
        period=new_period,
        max_cycles=MAX_CYCLES_FOR_TEMPLATE,
        tail_seconds=tail_seconds,
    )

    if new_template is None:
        BASELINE_STATES[key] = state
        return state, False, outside_ratio, mean_abs_err, mean_rel_err

    old_template = np.array(state.template, dtype=float)

    if state.status == BASELINE_STATUS_RECOVERING:
        alpha = RECOVERY_EMA_ALPHA
        state.status = BASELINE_STATUS_HEALTHY
    else:
        alpha = HEALTHY_EMA_ALPHA

    merged = merge_template(
        old_template=old_template,
        new_template=new_template,
        alpha=alpha,
    )

    state.period = int(new_period)
    state.template = merged.astype(float).tolist()
    state.last_update_ts = now_sec
    state.y_min = float(np.min(ys_grid[-tail_seconds:]))
    state.y_max = float(np.max(ys_grid[-tail_seconds:]))

    BASELINE_STATES[key] = state

    logger.info(
        "更新健康模板 key=%s period=%ss status=%s clean_seconds=%ss alpha=%.2f",
        key,
        state.period,
        state.status,
        state.clean_seconds,
        alpha,
    )

    return state, False, outside_ratio, mean_abs_err, mean_rel_err


# ── Prometheus 格式写入 ───────────────────────────────────────────────────────

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
        v = prom_escape_label_value(labels[k])
        parts.append(f'{k}="{v}"')

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

        ts_ms = ts_sec * 1000
        lines.append(f"{metric_name}{label_str} {val:.6f} {ts_ms}")

    if not lines:
        return False

    payload = "\n".join(lines) + "\n"

    try:
        resp = requests.post(
            f"{VM_URL}/api/v1/import/prometheus",
            data=payload.encode("utf-8"),
            headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
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

    now_sec = int(time.time())

    anomaly_labels = dict(labels)
    anomaly_labels["type"] = "prediction_deviation"

    ok4 = write_series(
        metric_name=anomaly_metric,
        labels=anomaly_labels,
        ts_list=[now_sec],
        values=[1.0 if is_anomaly else 0.0],
    )

    ok5 = write_series(
        metric_name=f"{anomaly_metric}_outside_ratio",
        labels=anomaly_labels,
        ts_list=[now_sec],
        values=[outside_ratio],
    )

    ok6 = write_series(
        metric_name=f"{anomaly_metric}_mean_abs_error",
        labels=anomaly_labels,
        ts_list=[now_sec],
        values=[mean_abs_err],
    )

    ok7 = write_series(
        metric_name=f"{anomaly_metric}_mean_rel_error",
        labels=anomaly_labels,
        ts_list=[now_sec],
        values=[mean_rel_err],
    )

    return ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7


# ── 标签解析 ──────────────────────────────────────────────────────────────────

_LABEL_PATTERN = re.compile(
    r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"((?:\\.|[^"])*)"\s*'
)


def _parse_labels(query: str) -> Dict[str, str]:
    labels = {}

    if "{" not in query or "}" not in query:
        return labels

    try:
        label_part = query[query.index("{") + 1: query.rindex("}")]
    except Exception:
        return labels

    for match in _LABEL_PATTERN.finditer(label_part):
        key = match.group(1)
        value = match.group(2)
        value = value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
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


# ── 状态持久化 ────────────────────────────────────────────────────────────────

def load_state():
    global BASELINE_STATES

    if not os.path.exists(STATE_FILE):
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        states = {}

        for key, value in raw.get("baseline_states", {}).items():
            states[key] = BaselineState(**value)

        BASELINE_STATES = states

        logger.info("已加载预测状态文件 %s，状态数量=%d", STATE_FILE, len(BASELINE_STATES))

    except Exception as e:
        logger.warning("加载预测状态文件失败，将重新学习: %s", e)


def save_state():
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


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

def run_once():
    now_str = datetime.now().strftime("%H:%M:%S")

    for target in PREDICT_TARGETS:
        query = target["query"]
        pred_metric = target["pred_metric"]
        anomaly_metric = target["anomaly_metric"]
        abs_threshold = float(target["abs_threshold"])
        rel_threshold = float(target["rel_threshold"])

        ts, ys = fetch_history(query)

        if len(ys) < MIN_POINTS:
            logger.info("[%s] %s 数据不足（%d 点），跳过", now_str, query, len(ys))
            continue

        ts_grid, ys_grid = normalize_history(ts, ys)

        if len(ys_grid) < MIN_POINTS:
            logger.info("[%s] %s 清洗后数据不足（%d 点），跳过", now_str, query, len(ys_grid))
            continue

        base_labels = _parse_labels(query)
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
            logger.info("[%s] %s 暂无可用健康模板，等待学习", now_str, query)
            continue

        now_sec = int(time.time())
        last_until = LAST_WRITTEN_UNTIL.get(key, 0)
        last_real_ts = int(ts_grid[-1])

        base_ts = max(now_sec, last_until, last_real_ts)

        ts_future = [
            base_ts + i + 1
            for i in range(WRITE_HORIZON_SECONDS)
        ]

        pred_values = predict_by_state(state, ts_future)

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
        )

        if not ok:
            continue

        LAST_WRITTEN_UNTIL[key] = int(max(ts_future))

        future_start = datetime.fromtimestamp(ts_future[0]).strftime("%H:%M:%S")
        future_end = datetime.fromtimestamp(ts_future[-1]).strftime("%H:%M:%S")

        logger.info(
            "[%s] %-40s → %-35s status=%s anomaly=%s period=%ss clean=%ss 写入 %d 点，预测区间 %s ~ %s",
            now_str,
            query,
            pred_metric,
            state.status,
            is_anomaly,
            state.period,
            state.clean_seconds,
            len(ts_future),
            future_start,
            future_end,
        )

    save_state()


def main():
    load_state()

    logger.info(
        "预测服务启动 VM=%s 历史窗口=%dmin 理论预测窗口=%ds 实际写入窗口=%ds 轮询间隔=%ds state=%s",
        VM_URL,
        HISTORY_MINUTES,
        HORIZON_SECONDS,
        WRITE_HORIZON_SECONDS,
        POLL_INTERVAL,
        STATE_FILE,
    )

    while True:
        run_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()