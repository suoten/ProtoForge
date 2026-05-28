# -*- coding: utf-8 -*-
"""
ProtoForge Predictor v13

核心能力：
1. 支持三个独立 CNC 工位：粗铣(fanuc-cnc)、半精铣(fanuc-cnc-semi-finish)、精铣(fanuc-cnc-finish)
2. 覆盖指标：feed_rate / spindle_speed / spindle_current / spindle_load
3. feed_rate / spindle_speed / spindle_current 使用 phase-lock 点预测。
4. spindle_load 使用 phase_band 预测带（多频漂移容忍）。
5. vibration_x / vibration_y / vibration_z 使用 phase-band 预测带。
6. 各工位独立阈值配置，匹配实际量程差异：
   - 粗铣：spindle_speed~2000RPM, feed_rate~800mm/min, spindle_current~21A, spindle_load~56%
   - 半精铣：spindle_speed~4000RPM, feed_rate~500mm/min, spindle_current~14.5A, spindle_load~38%
   - 精铣：spindle_speed~6000RPM, feed_rate~300mm/min, spindle_current~8.5A, spindle_load~22%
7. 粗铣周期含随机抖动(±10s)，phase-lock 搜索范围扩大至 ±18%。
8. 预测起点锚定最后一个真实点 last_real_ts，避免时间错位。
9. 异常期间冻结健康模板，不学习故障数据。
10. 故障恢复后等待稳定，再恢复模板学习。
11. 写入：
    - xxx_predicted
    - xxx_predicted_upper
    - xxx_predicted_lower
    - xxx_anomaly
    - xxx_anomaly_outside_ratio
    - xxx_anomaly_mean_abs_error
    - xxx_anomaly_mean_rel_error
    - xxx_anomaly_max_consecutive_outside
    - xxx_anomaly_max_exceed_ratio
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
STATE_FILE = "/tmp/protoforge_predictor_state_v14.json"

HISTORY_MINUTES = 30
HORIZON_SECONDS = 120
POLL_INTERVAL = 30

WRITE_HORIZON_SECONDS = min(HORIZON_SECONDS, POLL_INTERVAL)

QUERY_STEP = "1s"
MIN_POINTS = 120

MIN_PERIOD_SECONDS = 5
MAX_PERIOD_SECONDS = 3600

MIN_FULL_CYCLES_FOR_TEMPLATE = 3
MAX_CYCLES_FOR_TEMPLATE = 8

DETECT_WINDOW_SECONDS = 30
RECOVERY_MIN_SECONDS = 60

HEALTHY_EMA_ALPHA = 0.10
RECOVERY_EMA_ALPHA = 0.25

OUTSIDE_RATIO_THRESHOLD = 0.60
MIN_CONSECUTIVE_OUTSIDE = 5
SEVERE_EXCEED_RATIO = 1.8

VALLEY_QUANTILE = 45

MAX_DATA_LAG_SECONDS = 180

# 默认 phase-lock 搜索参数（精铣/半精铣：固定周期，搜索范围窄）
PHASE_LOCK_MIN_WINDOW_SECONDS = 45
PHASE_LOCK_MAX_WINDOW_SECONDS = 180
PHASE_LOCK_PERIOD_SEARCH_RATIO = 0.12
PHASE_LOCK_ORIGIN_SEARCH_RATIO = 0.35
PHASE_LOCK_PERIOD_STEP = 1
PHASE_LOCK_ORIGIN_STEP = 1


# =============================================================================
# 监控指标白名单（可通过环境变量 PROTOFORGE_MONITORED_METRICS 覆盖）
# =============================================================================

_DEFAULT_MONITORED_METRICS = [
    "feed_rate",
    "spindle_speed",
    "spindle_current",
    "spindle_load",
    "vibration_x",
    "vibration_y",
    "vibration_z",
]

MONITORED_METRICS: List[str] = [
    m.strip()
    for m in os.environ.get(
        "PROTOFORGE_MONITORED_METRICS",
        ",".join(_DEFAULT_MONITORED_METRICS),
    ).split(",")
    if m.strip()
]

# 人工上下限覆盖文件（可选，不存在则忽略）
# 格式：{"device-id": {"metric_name": {"hard_max": 35.0, "hard_min": 0.0}}}
OVERRIDE_FILE = os.environ.get(
    "PROTOFORGE_PREDICTOR_OVERRIDE",
    "/etc/protoforge/predictor_override.json",
)

# 目标列表刷新间隔（秒）
TARGETS_REFRESH_INTERVAL = int(os.environ.get("PROTOFORGE_TARGETS_REFRESH", "60"))

# 运行时目标缓存
_TARGETS_CACHE: List[Dict] = []
_TARGETS_LAST_REFRESH: float = 0.0


# =============================================================================
# Layer 1: 设备与指标发现
# =============================================================================

def discover_device_ids() -> List[str]:
    """查询 VM 中所有 device_id 标签值。"""
    try:
        resp = requests.get(
            f"{VM_URL}/api/v1/label/device_id/values",
            timeout=10,
        )
        resp.raise_for_status()
        return [v for v in resp.json().get("data", []) if v]
    except requests.RequestException as e:
        logger.error("发现 device_id 失败: %s", e)
        return []


def discover_metrics_for_device(device_id: str) -> List[str]:
    """查询该设备在 VM 中实际存在且有近期数据的指标名。"""
    found = []
    for metric in MONITORED_METRICS:
        try:
            resp = requests.get(
                f"{VM_URL}/api/v1/query",
                params={"query": f'{metric}{{device_id="{device_id}"}}'},
                timeout=5,
            )
            resp.raise_for_status()
            if resp.json().get("data", {}).get("result"):
                found.append(metric)
        except requests.RequestException:
            pass
    return found


# =============================================================================
# Layer 2: 自适应配置推断
# =============================================================================

@dataclass
class MetricProfile:
    """从历史数据统计出的指标特征，驱动策略和阈值的自动推断。"""
    device_id: str
    metric: str
    p5: float           # 活跃段 5th percentile
    p95: float          # 活跃段 95th percentile
    iqr: float          # p95 - p5
    cv: float           # 变异系数 std/mean（衡量稳定性）
    strategy: str       # "phase_point" 或 "phase_band"
    abs_threshold: float
    rel_threshold: float
    band_low_q: float
    band_high_q: float
    band_pad_abs: float
    phase_lock_period_search_ratio: float


def infer_metric_profile(device_id: str, metric: str) -> Optional["MetricProfile"]:
    """
    拉取历史数据，统计活跃段特征，自动推断预测策略和阈值。

    空闲段过滤：排除 p10 以下的点，避免机床空闲时的零值拉低阈值。
    strategy 判断：cv < 0.15 → phase_point（稳定信号），否则 phase_band（波动信号）。
    phase_lock 搜索范围：由周期长度的变异系数动态决定，周期抖动大则搜索范围宽。
    """
    ts_raw, ys_raw = fetch_history(f'{metric}{{device_id="{device_id}"}}')
    if len(ys_raw) < MIN_POINTS:
        return None

    arr = np.array(ys_raw, dtype=float)

    # 过滤空闲段：只保留活跃值（高于 p10）
    p10_val = float(np.percentile(arr, 10))
    active = arr[arr > p10_val]
    if len(active) < 30:
        active = arr  # 数据全是活跃段，不过滤

    mean_val = float(np.mean(active))
    std_val = float(np.std(active))
    cv = std_val / max(abs(mean_val), 1e-6)
    p5 = float(np.percentile(active, 5))
    p95 = float(np.percentile(active, 95))
    iqr = p95 - p5

    # 策略自动判断
    strategy = "phase_point" if cv < 0.15 else "phase_band"

    # 阈值自动计算：取 IQR 的 80%、量程的 5%、2倍标准差 三者最大值
    abs_threshold = max(iqr * 0.8, (p95 - p5) * 0.05, std_val * 2.0)
    rel_threshold = min(0.30, cv * 1.5)

    # phase_band 容忍带宽度：IQR 的 30% 或 1 倍标准差，取较大值
    band_pad_abs = max(iqr * 0.3, std_val)

    # phase-lock 搜索范围：从历史数据估算周期抖动率
    # 用 FFT 粗估周期，再用自相关精化，最后计算多周期长度的变异系数
    ts_grid, ys_grid = normalize_history(ts_raw, ys_raw)
    period_search_ratio = PHASE_LOCK_PERIOD_SEARCH_RATIO  # 默认值
    if len(ys_grid) >= MIN_POINTS:
        rough_period = estimate_period_rough(ys_grid)
        if rough_period > MIN_PERIOD_SECONDS:
            # 用谷底间距估算周期抖动
            valleys = find_valley_indices(ts_grid, ys_grid, rough_period)
            if len(valleys) >= 3:
                diffs = np.diff(ts_grid[valleys].astype(float))
                valid = diffs[(diffs > rough_period * 0.5) & (diffs < rough_period * 2.0)]
                if len(valid) >= 2:
                    period_cv = float(np.std(valid) / max(np.mean(valid), 1e-6))
                    period_search_ratio = float(np.clip(period_cv * 2.0, 0.12, 0.25))

    logger.info(
        "推断指标特征 device=%s metric=%s cv=%.3f strategy=%s abs_thr=%.3f rel_thr=%.3f period_search=%.2f",
        device_id, metric, cv, strategy, abs_threshold, rel_threshold, period_search_ratio,
    )

    return MetricProfile(
        device_id=device_id,
        metric=metric,
        p5=p5,
        p95=p95,
        iqr=iqr,
        cv=cv,
        strategy=strategy,
        abs_threshold=abs_threshold,
        rel_threshold=rel_threshold,
        band_low_q=5.0,
        band_high_q=95.0,
        band_pad_abs=band_pad_abs,
        phase_lock_period_search_ratio=period_search_ratio,
    )


def load_overrides() -> Dict:
    """加载人工上下限覆盖文件，文件不存在时返回空字典。"""
    if not os.path.exists(OVERRIDE_FILE):
        return {}
    try:
        with open(OVERRIDE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("加载 override 文件失败 %s: %s", OVERRIDE_FILE, e)
        return {}


def build_target(profile: MetricProfile, overrides: Dict) -> Dict:
    """将 MetricProfile 转换为预测执行层可用的 target dict。"""
    device_overrides = overrides.get(profile.device_id, {}).get(profile.metric, {})

    target: Dict = {
        "query": f'{profile.metric}{{device_id="{profile.device_id}"}}',
        "pred_metric": f"{profile.metric}_predicted",
        "anomaly_metric": f"{profile.metric}_anomaly",
        "strategy": profile.strategy,
        "abs_threshold": profile.abs_threshold,
        "rel_threshold": profile.rel_threshold,
        "smooth_window": 5 if profile.strategy == "phase_band" else 2,
        "outside_ratio_threshold": 0.60,
        "min_consecutive_outside": 5,
        "severe_exceed_ratio": 1.8,
        "phase_lock_period_search_ratio": profile.phase_lock_period_search_ratio,
        "phase_lock_origin_search_ratio": min(
            0.45, profile.phase_lock_period_search_ratio * 2.5
        ),
        # 物理上下限（可选，来自 override 文件）
        "hard_max": device_overrides.get("hard_max"),
        "hard_min": device_overrides.get("hard_min"),
    }

    if profile.strategy == "phase_band":
        target.update({
            "band_low_q": profile.band_low_q,
            "band_high_q": profile.band_high_q,
            "band_pad_abs": profile.band_pad_abs,
        })

    return target


def refresh_targets_if_needed() -> None:
    """
    按 TARGETS_REFRESH_INTERVAL 间隔重新发现设备和指标，动态更新目标列表。
    首次调用时立即执行发现。
    """
    global _TARGETS_CACHE, _TARGETS_LAST_REFRESH

    now = time.time()
    if now - _TARGETS_LAST_REFRESH < TARGETS_REFRESH_INTERVAL and _TARGETS_CACHE:
        return

    logger.info("开始发现设备和指标...")
    overrides = load_overrides()
    targets: List[Dict] = []

    device_ids = discover_device_ids()
    if not device_ids:
        logger.warning("未发现任何 device_id，保持现有目标列表")
        return

    for device_id in device_ids:
        metrics = discover_metrics_for_device(device_id)
        for metric in metrics:
            profile = infer_metric_profile(device_id, metric)
            if profile is not None:
                targets.append(build_target(profile, overrides))

    if targets:
        _TARGETS_CACHE = targets
        _TARGETS_LAST_REFRESH = now
        logger.info(
            "目标列表已更新：%d 台设备，%d 个指标目标",
            len(device_ids),
            len(targets),
        )
    else:
        logger.warning("发现流程未产生任何有效目标，保持现有目标列表")


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
    lower_template: List[float]
    upper_template: List[float]
    strategy: str
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
# 平滑与预处理
# =============================================================================

def rolling_median(arr: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(arr) < window:
        return arr.astype(float)

    if window % 2 == 0:
        window += 1

    pad = window // 2
    padded = np.pad(arr.astype(float), (pad, pad), mode="edge")

    result = []

    for i in range(len(arr)):
        result.append(float(np.median(padded[i:i + window])))

    return np.array(result, dtype=float)


def moving_average(arr: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(arr) < window:
        return arr.astype(float)

    if window % 2 == 0:
        window += 1

    kernel = np.ones(window, dtype=float) / window
    pad = window // 2
    padded = np.pad(arr.astype(float), (pad, pad), mode="edge")

    return np.convolve(padded, kernel, mode="valid")


def preprocess_values(ys_grid: np.ndarray, target: Dict) -> np.ndarray:
    strategy = target.get("strategy", "phase_point")
    smooth_window = int(target.get("smooth_window", 1))

    if strategy == "phase_band":
        return rolling_median(ys_grid, smooth_window)

    if smooth_window > 1:
        return moving_average(ys_grid, smooth_window)

    return ys_grid.astype(float)


# =============================================================================
# 周期估计
# =============================================================================

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
# 谷底检测
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


# =============================================================================
# 模板构建
# =============================================================================

def build_templates_from_valleys(
    ts_grid: np.ndarray,
    ys_mid_grid: np.ndarray,
    ys_band_grid: np.ndarray,
    period: int,
    valleys: List[int],
    target: Dict,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    if period <= 1 or len(valleys) < MIN_FULL_CYCLES_FOR_TEMPLATE + 1:
        return None

    strategy = target.get("strategy", "phase_point")
    low_q = float(target.get("band_low_q", 10))
    high_q = float(target.get("band_high_q", 90))

    pairs = []

    for a, b in zip(valleys[:-1], valleys[1:]):
        cycle_len = float(ts_grid[b] - ts_grid[a])

        if period * 0.55 <= cycle_len <= period * 1.60:
            pairs.append((a, b, cycle_len))

    if len(pairs) < MIN_FULL_CYCLES_FOR_TEMPLATE:
        return None

    pairs = pairs[-MAX_CYCLES_FOR_TEMPLATE:]

    phase_grid = np.arange(period, dtype=float)
    mid_segments = []
    band_segments = []
    weights = []

    for idx, (a, b, cycle_len) in enumerate(pairs):
        seg_ts = ts_grid[a:b + 1]
        seg_mid_y = ys_mid_grid[a:b + 1]
        seg_band_y = ys_band_grid[a:b + 1]

        if len(seg_mid_y) < 3 or len(seg_band_y) < 3:
            continue

        x_old = (seg_ts - seg_ts[0]) / cycle_len * period

        mid_seg = np.interp(phase_grid, x_old, seg_mid_y)
        band_seg = np.interp(phase_grid, x_old, seg_band_y)

        mid_segments.append(mid_seg.astype(float))
        band_segments.append(band_seg.astype(float))
        weights.append(0.5 + 0.5 * ((idx + 1) / len(pairs)))

    if len(mid_segments) < MIN_FULL_CYCLES_FOR_TEMPLATE:
        return None

    mid_arr = np.vstack(mid_segments)
    band_arr = np.vstack(band_segments)
    w_arr = np.array(weights, dtype=float)

    if strategy == "phase_band":
        mid_template = np.percentile(mid_arr, 50, axis=0)
        lower_template = np.percentile(band_arr, low_q, axis=0)
        upper_template = np.percentile(band_arr, high_q, axis=0)
    else:
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
    target: Dict,
    tail_seconds: Optional[int] = None,
) -> Optional[Tuple[int, int, np.ndarray, np.ndarray, np.ndarray]]:
    if len(ys_mid_grid) < MIN_POINTS or len(ys_band_grid) < MIN_POINTS:
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

    if len(ys_mid_use) < MIN_POINTS or len(ys_band_use) < MIN_POINTS:
        return None

    period, valleys = detect_period_and_valleys(ts_use, ys_mid_use)

    templates = build_templates_from_valleys(
        ts_grid=ts_use,
        ys_mid_grid=ys_mid_use,
        ys_band_grid=ys_band_use,
        period=period,
        valleys=valleys,
        target=target,
    )

    if templates is None or len(valleys) == 0:
        return None

    template, lower_template, upper_template = templates
    phase_origin_ts = int(round(float(ts_use[valleys[-1]])))

    return int(period), phase_origin_ts, template, lower_template, upper_template


# =============================================================================
# 模板预测
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


def predict_state_bundle(
    state: BaselineState,
    ts_list: List[int],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
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
    alpha = float(np.clip(alpha, 0.0, 1.0))

    if len(old_template) != len(new_template):
        old_template = resample_template(old_template, len(new_template))

    merged = (1.0 - alpha) * old_template + alpha * new_template

    return merged.astype(float)


# =============================================================================
# Phase Lock
# 支持 target 级别的 phase_lock_period_search_ratio / phase_lock_origin_search_ratio
# 粗铣工位周期含随机抖动(±10s)，需要更宽的搜索范围
# =============================================================================

def phase_lock_recent(
    state: BaselineState,
    ts_grid: np.ndarray,
    ys_model: np.ndarray,
    target: Optional[Dict] = None,
) -> Tuple[int, int, np.ndarray, float]:
    base_period = int(state.period)
    base_origin = int(state.phase_origin_ts)
    base_template = np.array(state.template, dtype=float)

    # 从 target 读取搜索范围，允许粗铣工位使用更宽的范围
    period_search_ratio = float(
        (target or {}).get("phase_lock_period_search_ratio", PHASE_LOCK_PERIOD_SEARCH_RATIO)
    )
    origin_search_ratio = float(
        (target or {}).get("phase_lock_origin_search_ratio", PHASE_LOCK_ORIGIN_SEARCH_RATIO)
    )

    if base_period <= 1 or len(base_template) <= 1:
        ts_recent = ts_grid[-DETECT_WINDOW_SECONDS:].astype(int).tolist()
        pred = predict_template_values(base_template, base_period, base_origin, ts_recent)
        actual = ys_model[-len(ts_recent):].astype(float)
        mae = float(np.mean(np.abs(actual - pred))) if len(actual) else 0.0
        return base_period, base_origin, pred, mae

    window_seconds = max(
        PHASE_LOCK_MIN_WINDOW_SECONDS,
        min(PHASE_LOCK_MAX_WINDOW_SECONDS, int(base_period * 2)),
    )

    cutoff = ts_grid[-1] - window_seconds
    mask = ts_grid >= cutoff

    ts_recent_arr = ts_grid[mask].astype(int)
    actual = ys_model[mask].astype(float)

    if len(ts_recent_arr) < max(10, DETECT_WINDOW_SECONDS):
        ts_recent_arr = ts_grid[-DETECT_WINDOW_SECONDS:].astype(int)
        actual = ys_model[-DETECT_WINDOW_SECONDS:].astype(float)

    ts_recent = ts_recent_arr.tolist()
    last_ts = int(ts_recent[-1])

    p_min = max(
        int(MIN_PERIOD_SECONDS),
        int(round(base_period * (1.0 - period_search_ratio))),
    )
    p_max = min(
        int(MAX_PERIOD_SECONDS),
        int(round(base_period * (1.0 + period_search_ratio))),
    )

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

    for period in range(p_min, p_max + 1, PHASE_LOCK_PERIOD_STEP):
        template = resample_template(base_template, period)
        center_origin = normalize_origin_near(base_origin, period, last_ts)
        origin_shift = max(2, int(round(period * origin_search_ratio)))

        for shift in range(-origin_shift, origin_shift + 1, PHASE_LOCK_ORIGIN_STEP):
            origin = center_origin + shift

            pred = predict_template_values(
                template=template,
                period=period,
                phase_origin_ts=origin,
                ts_list=ts_recent,
            )

            mae = float(np.mean(np.abs(actual - pred)))
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

def max_consecutive_true(flags: np.ndarray) -> int:
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
    threshold = np.maximum(abs_threshold, np.abs(pred) * rel_threshold)
    return pred - threshold, pred + threshold


def calc_final_bounds(
    state: BaselineState,
    pred: np.ndarray,
    lower_raw: np.ndarray,
    upper_raw: np.ndarray,
    target: Dict,
) -> Tuple[np.ndarray, np.ndarray]:
    strategy = target.get("strategy", "phase_point")
    abs_threshold = float(target.get("abs_threshold", 1.0))
    rel_threshold = float(target.get("rel_threshold", 0.25))

    if strategy == "phase_band":
        pad_abs = float(target.get("band_pad_abs", abs_threshold))

        dynamic_pad = np.maximum(
            pad_abs,
            np.abs(pred) * rel_threshold * 0.25,
        )

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
    best_period, best_origin, pred_recent, _ = phase_lock_recent(
        state=state,
        ts_grid=ts_grid,
        ys_model=ys_model,
        target=target,
    )

    recent_len = len(pred_recent)

    if recent_len <= 0:
        return False, 0.0, 0.0, 0.0, best_period, best_origin, 0, 0.0

    if target.get("strategy", "phase_point") == "phase_band":
        actual = ys_actual[-recent_len:].astype(float)
    else:
        actual = ys_model[-recent_len:].astype(float)

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

    above_upper = actual - upper
    below_lower = lower - actual

    exceed = np.maximum(above_upper, below_lower)
    exceed = np.maximum(exceed, 0.0)

    outside = exceed > 0

    band_width = np.maximum(upper - lower, 1e-6)
    exceed_ratio = exceed / band_width

    abs_err = np.abs(actual - pred)

    outside_ratio = float(np.mean(outside))
    mean_abs_err = float(np.mean(abs_err))
    mean_rel_err = float(np.mean(abs_err / np.maximum(np.abs(pred), 1e-6)))

    max_outside_seconds = max_consecutive_true(outside)
    max_exceed_ratio = float(np.max(exceed_ratio)) if len(exceed_ratio) > 0 else 0.0

    outside_ratio_threshold = float(
        target.get("outside_ratio_threshold", OUTSIDE_RATIO_THRESHOLD)
    )
    min_consecutive_outside = int(
        target.get("min_consecutive_outside", MIN_CONSECUTIVE_OUTSIDE)
    )
    severe_exceed_ratio = float(
        target.get("severe_exceed_ratio", SEVERE_EXCEED_RATIO)
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


# =============================================================================
# 状态管理
# =============================================================================

def create_initial_state(
    ts_grid: np.ndarray,
    ys_model: np.ndarray,
    ys_actual: np.ndarray,
    target: Dict,
    now_sec: int,
) -> Optional[BaselineState]:
    baseline = build_current_baseline(
        ts_grid=ts_grid,
        ys_mid_grid=ys_model,
        ys_band_grid=ys_actual,
        target=target,
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
        strategy=str(target.get("strategy", "phase_point")),
        status=BASELINE_STATUS_HEALTHY,
        clean_seconds=int(period * MAX_CYCLES_FOR_TEMPLATE),
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
    best_period = int(best_period)

    if best_period <= 1:
        return

    if len(state.template) != best_period:
        state.template = resample_template(
            np.array(state.template, dtype=float),
            best_period,
        ).astype(float).tolist()

    if len(state.lower_template) != best_period:
        state.lower_template = resample_template(
            np.array(state.lower_template, dtype=float),
            best_period,
        ).astype(float).tolist()

    if len(state.upper_template) != best_period:
        state.upper_template = resample_template(
            np.array(state.upper_template, dtype=float),
            best_period,
        ).astype(float).tolist()

    state.period = best_period
    state.phase_origin_ts = int(best_origin)


def maybe_update_state(
    key: str,
    ts_grid: np.ndarray,
    ys_model: np.ndarray,
    ys_actual: np.ndarray,
    target: Dict,
) -> Tuple[Optional[BaselineState], bool, float, float, float, int, float]:
    now_sec = int(time.time())
    state = BASELINE_STATES.get(key)

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

        BASELINE_STATES[key] = state

        logger.info(
            "初始化健康模板 key=%s strategy=%s period=%ss origin=%s clean=%ss",
            key,
            state.strategy,
            state.period,
            datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S"),
            state.clean_seconds,
        )

        return state, False, 0.0, 0.0, 0.0, 0, 0.0

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
        max_outside_seconds,
        max_exceed_ratio,
    ) = detect_anomaly(
        state=state,
        ts_grid=ts_grid,
        ys_model=ys_model,
        ys_actual=ys_actual,
        target=target,
    )

    if is_anomaly:
        state.status = BASELINE_STATUS_ANOMALY
        state.clean_seconds = 0
        BASELINE_STATES[key] = state

        logger.warning(
            "检测到异常，冻结模板 key=%s outside_ratio=%.2f max_outside=%ss max_exceed_ratio=%.2f mean_abs_err=%.4f mean_rel_err=%.4f",
            key,
            outside_ratio,
            max_outside_seconds,
            max_exceed_ratio,
            mean_abs_err,
            mean_rel_err,
        )

        return (
            state,
            True,
            outside_ratio,
            mean_abs_err,
            mean_rel_err,
            max_outside_seconds,
            max_exceed_ratio,
        )

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

        return (
            state,
            False,
            outside_ratio,
            mean_abs_err,
            mean_rel_err,
            max_outside_seconds,
            max_exceed_ratio,
        )

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
        return (
            state,
            False,
            outside_ratio,
            mean_abs_err,
            mean_rel_err,
            max_outside_seconds,
            max_exceed_ratio,
        )

    tail_seconds = min(
        int(state.clean_seconds),
        int(state.period) * MAX_CYCLES_FOR_TEMPLATE,
    )

    baseline = build_current_baseline(
        ts_grid=ts_grid,
        ys_mid_grid=ys_model,
        ys_band_grid=ys_actual,
        target=target,
        tail_seconds=tail_seconds,
    )

    if baseline is None:
        BASELINE_STATES[key] = state
        return (
            state,
            False,
            outside_ratio,
            mean_abs_err,
            mean_rel_err,
            max_outside_seconds,
            max_exceed_ratio,
        )

    new_period, new_origin, new_template, new_lower_template, new_upper_template = baseline

    alpha = RECOVERY_EMA_ALPHA if state.status == BASELINE_STATUS_RECOVERING else HEALTHY_EMA_ALPHA

    state.template = merge_template(
        np.array(state.template, dtype=float),
        new_template,
        alpha,
    ).astype(float).tolist()

    state.lower_template = merge_template(
        np.array(state.lower_template, dtype=float),
        new_lower_template,
        alpha,
    ).astype(float).tolist()

    state.upper_template = merge_template(
        np.array(state.upper_template, dtype=float),
        new_upper_template,
        alpha,
    ).astype(float).tolist()

    state.period = int(new_period)
    state.phase_origin_ts = int(new_origin)
    state.status = BASELINE_STATUS_HEALTHY
    state.last_update_ts = now_sec

    if tail_seconds > 0 and len(ys_actual) >= tail_seconds:
        state.y_min = float(np.min(ys_actual[-tail_seconds:]))
        state.y_max = float(np.max(ys_actual[-tail_seconds:]))
    else:
        state.y_min = float(np.min(ys_actual))
        state.y_max = float(np.max(ys_actual))

    BASELINE_STATES[key] = state

    logger.info(
        "更新健康模板 key=%s strategy=%s period=%ss origin=%s clean=%ss alpha=%.2f",
        key,
        state.strategy,
        state.period,
        datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S"),
        state.clean_seconds,
        alpha,
    )

    return (
        state,
        False,
        outside_ratio,
        mean_abs_err,
        mean_rel_err,
        max_outside_seconds,
        max_exceed_ratio,
    )


# =============================================================================
# Prometheus 写入
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
    max_outside_seconds: int,
    max_exceed_ratio: float,
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

    ok8 = write_series(
        metric_name=f"{anomaly_metric}_max_consecutive_outside",
        labels=anomaly_labels,
        ts_list=[event_ts],
        values=[float(max_outside_seconds)],
    )

    ok9 = write_series(
        metric_name=f"{anomaly_metric}_max_exceed_ratio",
        labels=anomaly_labels,
        ts_list=[event_ts],
        values=[float(max_exceed_ratio)],
    )

    return ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8 and ok9


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
                "lower_template",
                "upper_template",
                "strategy",
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

    base_ts = last_real_ts

    return [
        base_ts + i + 1
        for i in range(WRITE_HORIZON_SECONDS)
    ]


# =============================================================================
# 主流程
# =============================================================================

def run_once() -> None:
    now_str = datetime.now().strftime("%H:%M:%S")

    refresh_targets_if_needed()

    if not _TARGETS_CACHE:
        logger.warning("[%s] 目标列表为空，等待设备发现完成", now_str)
        return

    for target in _TARGETS_CACHE:
        query = target["query"]
        pred_metric = target["pred_metric"]
        anomaly_metric = target["anomaly_metric"]

        ts, ys = fetch_history(query)

        if len(ys) < MIN_POINTS:
            logger.info("[%s] %s 数据不足（%d 点），跳过", now_str, query, len(ys))
            continue

        ts_grid, ys_grid_raw = normalize_history(ts, ys)

        if len(ys_grid_raw) < MIN_POINTS:
            logger.info("[%s] %s 清洗后数据不足（%d 点），跳过", now_str, query, len(ys_grid_raw))
            continue

        ys_grid_model = preprocess_values(ys_grid_raw, target)

        base_labels = parse_labels_from_query(query)
        write_labels = merge_labels(base_labels, EXTRA_PREDICT_LABELS)

        key = series_key(pred_metric, write_labels)

        (
            state,
            is_anomaly,
            outside_ratio,
            mean_abs_err,
            mean_rel_err,
            max_outside_seconds,
            max_exceed_ratio,
        ) = maybe_update_state(
            key=key,
            ts_grid=ts_grid,
            ys_model=ys_grid_model,
            ys_actual=ys_grid_raw,
            target=target,
        )

        if state is None:
            logger.info("[%s] %s 暂无可用健康模板，等待学习", now_str, query)
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

        pred_values, lower_raw, upper_raw = predict_state_bundle(state, ts_future)

        lower_values, upper_values = calc_final_bounds(
            state=state,
            pred=pred_values,
            lower_raw=lower_raw,
            upper_raw=upper_raw,
            target=target,
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
            max_outside_seconds=max_outside_seconds,
            max_exceed_ratio=max_exceed_ratio,
            event_ts=last_real_ts,
        )

        if not ok:
            logger.error("[%s] %s 写入预测数据失败", now_str, query)
            continue

        LAST_REAL_TS_WRITTEN[key] = last_real_ts

        future_start = datetime.fromtimestamp(ts_future[0]).strftime("%H:%M:%S")
        future_end = datetime.fromtimestamp(ts_future[-1]).strftime("%H:%M:%S")
        last_real_str = datetime.fromtimestamp(last_real_ts).strftime("%H:%M:%S")
        origin_str = datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S")

        logger.info(
            "[%s] %-50s → %-35s strategy=%s status=%s anomaly=%s outside=%.2f max_outside=%ss max_exceed=%.2f period=%ss origin=%s last_real=%s lag=%ss 写入 %d 点，预测区间 %s ~ %s",
            now_str,
            query,
            pred_metric,
            state.strategy,
            state.status,
            is_anomaly,
            outside_ratio,
            max_outside_seconds,
            max_exceed_ratio,
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
        "预测服务启动 VM=%s 历史窗口=%dmin 理论预测窗口=%ds 实际写入窗口=%ds 轮询间隔=%ds state=%s forecast=%s override=%s refresh=%ds",
        VM_URL,
        HISTORY_MINUTES,
        HORIZON_SECONDS,
        WRITE_HORIZON_SECONDS,
        POLL_INTERVAL,
        STATE_FILE,
        EXTRA_PREDICT_LABELS["forecast"],
        OVERRIDE_FILE,
        TARGETS_REFRESH_INTERVAL,
    )

    while True:
        run_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
