# -*- coding: utf-8 -*-
"""
ProtoForge 预测服务 v4

修复点：
1. 不再使用 VictoriaMetrics delete_series，避免预测历史被整条删除。
2. 不再每 30 秒写未来 120 秒，避免多轮预测窗口重叠导致 Grafana 出现竖线/毛刺。
3. 每轮只写未来 min(HORIZON_SECONDS, POLL_INTERVAL) 秒的数据。
4. 使用 forecast="rolling_v2" 新标签，避免和上一版 forecast="latest" 的旧预测数据混在一起。
5. 使用真实 timestamp 做拟合，不假设采样严格等间隔。
6. 拟合失败时不再简单写平直线，而是尽量重复最近一个周期的波形。
"""

import logging
import math
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import requests
from scipy.optimize import curve_fit


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

# 理论预测窗口
HORIZON_SECONDS = 120

# 轮询间隔
POLL_INTERVAL = 30

# 实际写入窗口。
# 关键点：实际写入窗口不要大于轮询间隔，否则不同批次预测会重叠。
WRITE_HORIZON_SECONDS = min(HORIZON_SECONDS, POLL_INTERVAL)

MIN_POINTS = 120
QUERY_STEP = "1s"

# 不要再清理旧预测，否则历史预测会被整条删除。
CLEAR_OLD_PREDICTIONS = False

# 使用新标签，避免和上一版 forecast="latest" 数据混在一起。
EXTRA_PREDICT_LABELS = {
    "forecast": "rolling_v2",
    "source": "protoforge",
}

MIN_PERIOD_SECONDS = 5.0
MAX_PERIOD_SECONDS = 3600.0

# 进程内记录每条预测序列上次写到哪里，避免本进程运行期间重复写同一时间段
LAST_WRITTEN_UNTIL: Dict[str, int] = {}

# ─────────────────────────────────────────────────────────────────────────────


def fetch_history(query: str, minutes: int = HISTORY_MINUTES) -> Tuple[List[float], List[float]]:
    """
    从 VictoriaMetrics 拉取历史时序数据。
    返回：
        timestamps: Unix 秒级时间戳
        values: float 数值
    """
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
    1. 时间戳转为整秒
    2. 排序
    3. 同一秒多个值时保留最后一个
    4. 插值补齐缺失秒
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


def _sine_model(t: np.ndarray, A: float, T: float, phi: float, C: float) -> np.ndarray:
    return A * np.sin(2.0 * np.pi / T * t + phi) + C


def estimate_period_by_fft(ys_arr: np.ndarray) -> float:
    """
    使用 FFT 估算主周期。
    ys_arr 默认已经是 1 秒间隔。
    """
    n = len(ys_arr)

    if n < 4:
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
    period = float(np.clip(period, MIN_PERIOD_SECONDS, MAX_PERIOD_SECONDS))

    return period


def repeat_last_period(
    ts_grid: np.ndarray,
    ys_grid: np.ndarray,
    ts_future_arr: np.ndarray,
    period_seconds: float,
) -> np.ndarray:
    """
    拟合失败时的降级策略：
    不直接写平直线，而是把未来时间映射回最近一个周期的历史波形。
    """
    if len(ts_grid) < 2:
        return np.full_like(ts_future_arr, float(ys_grid[-1]), dtype=float)

    period = max(int(round(period_seconds)), 1)

    y_pred = []

    hist_start = float(ts_grid[0])
    hist_end = float(ts_grid[-1])

    for future_ts in ts_future_arr:
        mapped_ts = float(future_ts)

        while mapped_ts > hist_end:
            mapped_ts -= period

        while mapped_ts < hist_start:
            mapped_ts += period

        val = float(np.interp(mapped_ts, ts_grid, ys_grid))
        y_pred.append(val)

    return np.array(y_pred, dtype=float)


def predict_next(
    ts: List[float],
    ys: List[float],
    horizon: int,
    base_ts: int,
) -> Tuple[List[float], List[float]]:
    """
    用 FFT 检测主频，拟合正弦波，外推未来 horizon 秒。

    base_ts:
        从 base_ts + 1 开始写预测。
    """
    ts_grid, ys_grid = normalize_history(ts, ys)

    if len(ys_grid) < MIN_POINTS:
        return [], []

    y_min = float(np.min(ys_grid))
    y_max = float(np.max(ys_grid))
    y_mean = float(np.mean(ys_grid))
    y_range = y_max - y_min

    base_ts = max(int(base_ts), int(ts_grid[-1]))

    ts_future_arr = np.arange(
        base_ts + 1,
        base_ts + 1 + horizon,
        1,
        dtype=float,
    )

    if y_range <= 1e-9:
        y_pred_arr = np.full_like(ts_future_arr, float(ys_grid[-1]), dtype=float)
        return ts_future_arr.tolist(), y_pred_arr.tolist()

    period = estimate_period_by_fft(ys_grid)

    t_fit = ts_grid - ts_grid[0]
    t_future = ts_future_arr - ts_grid[0]

    amplitude = y_range / 2.0
    offset = y_mean

    try:
        popt, _ = curve_fit(
            _sine_model,
            t_fit,
            ys_grid,
            p0=[amplitude, period, 0.0, offset],
            bounds=(
                [0.0, MIN_PERIOD_SECONDS, -2.0 * np.pi, y_min - y_range],
                [np.inf, MAX_PERIOD_SECONDS, 2.0 * np.pi, y_max + y_range],
            ),
            maxfev=12000,
        )

        y_pred_arr = _sine_model(t_future, *popt)

        margin = y_range * 0.2
        lower = y_min - margin
        upper = y_max + margin
        y_pred_arr = np.clip(y_pred_arr, lower, upper)

        if not np.all(np.isfinite(y_pred_arr)):
            raise ValueError("预测结果包含 NaN/Inf")

        logger.debug(
            "正弦拟合成功 period=%.2fs amplitude=%.4f offset=%.4f",
            popt[1],
            popt[0],
            popt[3],
        )

        return ts_future_arr.tolist(), y_pred_arr.astype(float).tolist()

    except Exception as e:
        logger.warning("正弦拟合失败，降级为最近周期波形复制: %s", e)

        y_pred_arr = repeat_last_period(
            ts_grid=ts_grid,
            ys_grid=ys_grid,
            ts_future_arr=ts_future_arr,
            period_seconds=period,
        )

        margin = y_range * 0.2
        lower = y_min - margin
        upper = y_max + margin
        y_pred_arr = np.clip(y_pred_arr, lower, upper)

        return ts_future_arr.tolist(), y_pred_arr.astype(float).tolist()


def prom_escape_label_value(value: str) -> str:
    """
    Prometheus exposition label value 转义。
    """
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
    """
    将预测值以 Prometheus exposition 格式写入 VictoriaMetrics。
    时间戳为毫秒级 Unix timestamp。
    """
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
            headers={
                "Content-Type": "text/plain; version=0.0.4; charset=utf-8",
            },
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
    """
    从查询表达式中解析标签。

    示例：
        feed_rate{device_id="fanuc-cnc"} -> {"device_id": "fanuc-cnc"}
    """
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
        if not d:
            continue
        result.update(d)

    return result


def series_key(metric_name: str, labels: Dict[str, str]) -> str:
    """
    构造进程内唯一 key，用于记录上次写到哪个时间点。
    """
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

        # 防止同一进程内重复写入已经预测过的时间段
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
        "预测服务启动 VM=%s 历史窗口=%dmin 理论预测窗口=%ds 实际写入窗口=%ds 轮询间隔=%ds 清理旧预测=%s",
        VM_URL,
        HISTORY_MINUTES,
        HORIZON_SECONDS,
        WRITE_HORIZON_SECONDS,
        POLL_INTERVAL,
        CLEAR_OLD_PREDICTIONS,
    )

    while True:
        run_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()