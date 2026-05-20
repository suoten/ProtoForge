# -*- coding: utf-8 -*-
"""
ProtoForge 预测服务 v5

修复点：
1. 不再使用“单正弦拟合”作为主预测算法。
2. 主算法改为：周期模板预测（同相位历史值加权平均）。
3. 周期估计使用 FFT 粗估 + 自相关细化，比单纯 FFT 更稳。
4. 若可用完整周期不足，则降级为多谐波回归（而不是单正弦）。
5. 每轮只写入未来 min(HORIZON_SECONDS, POLL_INTERVAL) 秒，避免预测窗口重叠。
6. 不删除旧预测历史，避免历史预测消失。
"""

import logging
import math
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────────────────────────

VM_URL = "http://localhost:8428"

PREDICT_TARGETS = [
    ('feed_rate{device_id="fanuc-cnc"}', "feed_rate_predicted"),
    ('spindle_speed{device_id="fanuc-cnc"}', "spindle_speed_predicted"),
    ('spindle_current{device_id="fanuc-cnc"}', "spindle_current_predicted"),
    ('vibration_x{device_id="fanuc-cnc"}', "vibration_x_predicted"),
    ('vibration_y{device_id="fanuc-cnc"}', "vibration_y_predicted"),
    ('vibration_z{device_id="fanuc-cnc"}', "vibration_z_predicted"),
]

HISTORY_MINUTES = 30
HORIZON_SECONDS = 120
POLL_INTERVAL = 30
WRITE_HORIZON_SECONDS = min(HORIZON_SECONDS, POLL_INTERVAL)
MIN_POINTS = 120
QUERY_STEP = "1s"

# 至少要有多少个完整周期，才使用“周期模板预测”
MIN_FULL_CYCLES_FOR_TEMPLATE = 3
MAX_CYCLES_FOR_TEMPLATE = 6

# 周期范围
MIN_PERIOD_SECONDS = 5
MAX_PERIOD_SECONDS = 3600

# 多谐波回归最高阶数（降级模式）
MAX_HARMONICS = 4

EXTRA_PREDICT_LABELS = {
    "forecast": "seasonal_v1",
    "source": "protoforge",
}

# 进程内记录每条预测序列上次写到哪里，避免本进程运行时重复写
LAST_WRITTEN_UNTIL: Dict[str, int] = {}

# ─────────────────────────────────────────────────────────────────────────────


def fetch_history(query: str, minutes: int = HISTORY_MINUTES) -> Tuple[List[float], List[float]]:
    """从 VictoriaMetrics 拉取历史时序数据。"""
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
    """
    清洗历史数据：
    1. 时间戳整秒化
    2. 排序
    3. 同一秒多个点保留最后一个
    4. 按 1 秒插值补齐
    """
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


def estimate_period_by_fft(ys_arr: np.ndarray) -> float:
    """FFT 粗估周期。"""
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
    """
    用自相关在 init_period 附近细化周期估计。
    """
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


def estimate_period(ys_arr: np.ndarray) -> float:
    """FFT + 自相关 的组合周期估计。"""
    p_fft = estimate_period_by_fft(ys_arr)
    p_refined = refine_period_by_autocorr(ys_arr, p_fft)
    return p_refined


def seasonal_template_predict(
    ys_arr: np.ndarray,
    horizon: int,
    period: int,
    gap: int = 0,
    max_cycles: int = MAX_CYCLES_FOR_TEMPLATE,
) -> List[float]:
    """
    同相位历史值加权平均预测。
    对未来第 k 个点，取过去多个周期同相位点做加权平均：
        y[n-1+gap+k] ≈ avg(y[n-1+gap+k-p], y[n-1+gap+k-2p], ...)
    """
    n = len(ys_arr)
    preds = []

    for k in range(1, horizon + 1):
        target_idx = (n - 1) + gap + k

        values = []
        weights = []

        # m=1 表示最近一个周期；m 越大越久远
        for m in range(1, max_cycles + 1):
            hist_idx = target_idx - m * period
            if 0 <= hist_idx < n:
                # 越近权重越大
                w = 1.0 / m
                values.append(float(ys_arr[hist_idx]))
                weights.append(w)

        if not values:
            # 万一拿不到，退化为最后一个值
            preds.append(float(ys_arr[-1]))
        else:
            preds.append(float(np.average(values, weights=weights)))

    return preds


def harmonic_regression_predict(
    ys_arr: np.ndarray,
    horizon: int,
    period: int,
    gap: int = 0,
    max_harmonics: int = MAX_HARMONICS,
) -> List[float]:
    """
    多谐波回归（降级模式）：
    y = c + Σ [a_k sin(2πkt/P) + b_k cos(2πkt/P)]
    相比单正弦，更能表达非标准正弦波形。
    """
    n = len(ys_arr)
    if n < 10 or period <= 1:
        return [float(ys_arr[-1])] * horizon

    # 周期太短时，谐波数不能太大
    K = min(max_harmonics, max(1, period // 4))

    t = np.arange(n, dtype=float)
    cols = [np.ones(n, dtype=float)]

    for k in range(1, K + 1):
        angle = 2.0 * np.pi * k * t / period
        cols.append(np.sin(angle))
        cols.append(np.cos(angle))

    X = np.column_stack(cols)

    try:
        coef, _, _, _ = np.linalg.lstsq(X, ys_arr, rcond=None)
    except Exception:
        return [float(ys_arr[-1])] * horizon

    t_future = np.arange(n + gap, n + gap + horizon, dtype=float)
    cols_future = [np.ones(horizon, dtype=float)]

    for k in range(1, K + 1):
        angle = 2.0 * np.pi * k * t_future / period
        cols_future.append(np.sin(angle))
        cols_future.append(np.cos(angle))

    X_future = np.column_stack(cols_future)
    y_pred = X_future @ coef

    return y_pred.astype(float).tolist()


def predict_next(
    ts: List[float],
    ys: List[float],
    horizon: int,
    base_ts: int,
) -> Tuple[List[float], List[float]]:
    """
    主预测函数：
    1. 周期估计
    2. 优先使用周期模板预测
    3. 周期不够时降级为多谐波回归
    """
    ts_grid, ys_grid = normalize_history(ts, ys)
    if len(ys_grid) < MIN_POINTS:
        return [], []

    y_min = float(np.min(ys_grid))
    y_max = float(np.max(ys_grid))
    y_range = y_max - y_min

    if y_range <= 1e-9:
        base_ts = max(int(base_ts), int(ts_grid[-1]))
        ts_future = [base_ts + i + 1 for i in range(horizon)]
        y_pred = [float(ys_grid[-1])] * horizon
        return ts_future, y_pred

    period_est = estimate_period(ys_grid)
    period = int(round(period_est))
    period = max(MIN_PERIOD_SECONDS, min(MAX_PERIOD_SECONDS, period))

    last_real_ts = int(ts_grid[-1])
    base_ts = max(int(base_ts), last_real_ts)

    # 如果当前时间已经超过最后一个真实点，gap 表示中间“空过去”的秒数
    gap = max(0, base_ts - last_real_ts)

    ts_future = [base_ts + i + 1 for i in range(horizon)]

    full_cycles = len(ys_grid) // period if period > 0 else 0

    if full_cycles >= MIN_FULL_CYCLES_FOR_TEMPLATE:
        y_pred = seasonal_template_predict(
            ys_arr=ys_grid,
            horizon=horizon,
            period=period,
            gap=gap,
            max_cycles=min(MAX_CYCLES_FOR_TEMPLATE, full_cycles),
        )
        model_name = "seasonal_template"
    else:
        y_pred = harmonic_regression_predict(
            ys_arr=ys_grid,
            horizon=horizon,
            period=period,
            gap=gap,
            max_harmonics=MAX_HARMONICS,
        )
        model_name = "harmonic_regression"

    # 合理裁剪，避免偶然外推过大
    margin = y_range * 0.15
    lower = y_min - margin
    upper = y_max + margin
    y_pred = np.clip(np.array(y_pred, dtype=float), lower, upper).astype(float).tolist()

    logger.debug(
        "predict_next model=%s period=%ss full_cycles=%s gap=%s",
        model_name, period, full_cycles, gap
    )

    return ts_future, y_pred


def prom_escape_label_value(value: str) -> str:
    """Prometheus label value 转义。"""
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


def write_predictions(
    ts_future: List[float],
    y_pred: List[float],
    metric_name: str,
    labels: Dict[str, str],
) -> bool:
    """将预测值以 Prometheus exposition 格式写入 VictoriaMetrics。"""
    if not ts_future or not y_pred or len(ts_future) != len(y_pred):
        logger.warning("预测数据为空或长度不一致 metric=%s", metric_name)
        return False

    label_str = labels_to_str(labels)
    lines = []

    for t, y in zip(ts_future, y_pred):
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
        logger.warning("没有可写入的预测点 metric=%s", metric_name)
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
        logger.error("写入预测数据失败 metric=%s: %s", metric_name, e)
        return False


_LABEL_PATTERN = re.compile(
    r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"((?:\\.|[^"])*)"\s*'
)


def _parse_labels(query: str) -> Dict[str, str]:
    """从查询表达式中解析标签。"""
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


def run_once():
    now_str = datetime.now().strftime("%H:%M:%S")

    for query, pred_metric in PREDICT_TARGETS:
        ts, ys = fetch_history(query)
        if len(ys) < MIN_POINTS:
            logger.info("[%s] %s 数据不足（%d 点），跳过", now_str, query, len(ys))
            continue

        base_labels = _parse_labels(query)
        write_labels = merge_labels(base_labels, EXTRA_PREDICT_LABELS)

        key = series_key(pred_metric, write_labels)

        now_sec = int(time.time())
        last_until = LAST_WRITTEN_UNTIL.get(key, 0)

        # 避免同一进程内写重叠时间段
        base_ts = max(now_sec, last_until)

        ts_future, y_pred = predict_next(
            ts=ts,
            ys=ys,
            horizon=WRITE_HORIZON_SECONDS,
            base_ts=base_ts,
        )

        if not ts_future or not y_pred:
            logger.warning("[%s] %s 预测结果为空，跳过", now_str, query)
            continue

        ok = write_predictions(
            ts_future=ts_future,
            y_pred=y_pred,
            metric_name=pred_metric,
            labels=write_labels,
        )
        if not ok:
            continue

        LAST_WRITTEN_UNTIL[key] = int(max(ts_future))

        future_start = datetime.fromtimestamp(ts_future[0]).strftime("%H:%M:%S")
        future_end = datetime.fromtimestamp(ts_future[-1]).strftime("%H:%M:%S")

        logger.info(
            "[%s] %-40s → %-35s 写入 %d 点，预测区间 %s ~ %s，标签=%s",
            now_str,
            query,
            pred_metric,
            len(y_pred),
            future_start,
            future_end,
            labels_to_str(write_labels),
        )


def main():
    logger.info(
        "预测服务启动 VM=%s 历史窗口=%dmin 理论预测窗口=%ds 实际写入窗口=%ds 轮询间隔=%ds",
        VM_URL,
        HISTORY_MINUTES,
        HORIZON_SECONDS,
        WRITE_HORIZON_SECONDS,
        POLL_INTERVAL,
    )

    while True:
        run_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()