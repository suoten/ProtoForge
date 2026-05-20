# -*- coding: utf-8 -*-
"""
ProtoForge 预测服务 v2
从 VictoriaMetrics 拉取历史数据，用 FFT + 正弦拟合预测未来值，写回 VM。
预测值时间戳为未来时间，Grafana 中预测线出现在实测线右侧延伸处。
"""

import logging
import time
from datetime import datetime, timedelta

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

# 要预测的指标列表，每项：(查询表达式, 写回指标名)
PREDICT_TARGETS = [
    ('feed_rate{device_id="fanuc-cnc"}',       "feed_rate_predicted"),
    ('spindle_speed{device_id="fanuc-cnc"}',    "spindle_speed_predicted"),
    ('spindle_current{device_id="fanuc-cnc"}',  "spindle_current_predicted"),
    ('vibration_x{device_id="fanuc-cnc"}',      "vibration_x_predicted"),
    ('vibration_y{device_id="fanuc-cnc"}',      "vibration_y_predicted"),
    ('vibration_z{device_id="fanuc-cnc"}',      "vibration_z_predicted"),
]

HISTORY_MINUTES = 30   # 拉取多少分钟历史数据用于拟合
HORIZON_SECONDS = 120  # 预测未来多少秒
POLL_INTERVAL   = 30   # 每隔多少秒重新预测一次
MIN_POINTS      = 120  # 至少需要多少个历史点才开始预测
# ─────────────────────────────────────────────────────────────────────────────


def fetch_history(query: str, minutes: int = HISTORY_MINUTES):
    """从 VictoriaMetrics 拉取历史时序数据，返回 (timestamps, values)。"""
    now = datetime.now()
    start = now - timedelta(minutes=minutes)
    try:
        resp = requests.get(
            f"{VM_URL}/api/v1/query_range",
            params={
                "query": query,
                "start": start.timestamp(),
                "end":   now.timestamp(),
                "step":  "1s",
            },
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("拉取数据失败 query=%s: %s", query, e)
        return [], []

    result = resp.json().get("data", {}).get("result", [])
    if not result:
        return [], []

    values = result[0]["values"]
    ts = [float(v[0]) for v in values]
    ys = [float(v[1]) for v in values]
    return ts, ys


def _sine_model(t, A, T, phi, C):
    return A * np.sin(2 * np.pi / T * t + phi) + C


def predict_next(ts: list, ys: list, horizon: int = HORIZON_SECONDS):
    """
    用 FFT 检测主频，拟合正弦波，外推未来 horizon 秒。
    返回 (future_timestamps, predicted_values)，时间戳均在最后一个真实点之后。
    降级策略：拟合失败时用最近 10 点线性外推。
    """
    ys_arr = np.array(ys)
    n = len(ys_arr)

    # ── FFT 找主频 ────────────────────────────────────────────────────────────
    fft_vals = np.fft.rfft(ys_arr - ys_arr.mean())
    freqs = np.fft.rfftfreq(n, d=1.0)  # d=1 表示 1 秒采样间隔
    # 跳过直流分量（index 0）
    dominant_idx = int(np.argmax(np.abs(fft_vals[1:]))) + 1
    dominant_freq = freqs[dominant_idx]
    period = 1.0 / dominant_freq if dominant_freq > 0 else 60.0
    period = float(np.clip(period, 5.0, 3600.0))  # 限制在合理范围

    # ── 正弦拟合 ──────────────────────────────────────────────────────────────
    t_rel = np.arange(n, dtype=float)
    amplitude = (ys_arr.max() - ys_arr.min()) / 2.0
    offset = float(ys_arr.mean())

    # 最后一个真实数据点的 Unix 时间戳（秒）
    last_ts = ts[-1]

    try:
        popt, _ = curve_fit(
            _sine_model,
            t_rel,
            ys_arr,
            p0=[amplitude, period, 0.0, offset],
            bounds=(
                [0,       5.0,    -np.pi, ys_arr.min()],
                [np.inf,  3600.0,  np.pi, ys_arr.max()],
            ),
            maxfev=8000,
        )
        t_future = np.arange(n, n + horizon, dtype=float)
        y_pred = _sine_model(t_future, *popt)
        # 裁剪到历史数据值域，避免外推飞出合理范围
        y_pred = np.clip(y_pred, ys_arr.min() * 0.5, ys_arr.max() * 1.5)

        # 未来时间戳：last_ts + 1s, +2s, ..., +horizon s
        ts_future = [last_ts + i + 1 for i in range(horizon)]
        logger.debug("正弦拟合成功 period=%.1fs amplitude=%.2f", popt[1], popt[0])
        return ts_future, y_pred.tolist()

    except Exception as e:
        logger.warning("正弦拟合失败，降级为线性外推: %s", e)
        tail = min(10, n)
        slope = (ys_arr[-1] - ys_arr[-tail]) / tail
        ts_future = [last_ts + i + 1 for i in range(horizon)]
        y_pred = [float(ys_arr[-1] + slope * (i + 1)) for i in range(horizon)]
        return ts_future, y_pred


def write_predictions(ts_future: list, y_pred: list, metric_name: str, extra_labels: dict = None):
    """
    将预测值以 Prometheus exposition 格式写入 VictoriaMetrics。
    时间戳为毫秒级 Unix 时间戳，对应未来时间点。
    """
    label_str = ""
    if extra_labels:
        parts = [f'{k}="{v}"' for k, v in extra_labels.items()]
        label_str = "{" + ",".join(parts) + "}"

    lines = []
    for t, y in zip(ts_future, y_pred):
        ts_ms = int(t * 1000)
        lines.append(f"{metric_name}{label_str} {y:.4f} {ts_ms}")

    payload = "\n".join(lines)
    try:
        resp = requests.post(
            f"{VM_URL}/api/v1/import/prometheus",
            data=payload,
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("写入预测数据失败 metric=%s: %s", metric_name, e)


def _parse_labels(query: str) -> dict:
    """从查询表达式中解析标签，如 feed_rate{device_id="fanuc-cnc"} → {"device_id": "fanuc-cnc"}"""
    labels = {}
    if "{" not in query:
        return labels
    label_part = query[query.index("{") + 1: query.index("}")]
    for item in label_part.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            labels[k.strip()] = v.strip().strip('"')
    return labels


def run_once():
    now_str = datetime.now().strftime("%H:%M:%S")
    for query, pred_metric in PREDICT_TARGETS:
        ts, ys = fetch_history(query)
        if len(ys) < MIN_POINTS:
            logger.info("[%s] %s 数据不足（%d 点），跳过", now_str, query, len(ys))
            continue

        ts_future, y_pred = predict_next(ts, ys, horizon=HORIZON_SECONDS)
        if not ts_future:
            continue

        extra_labels = _parse_labels(query)
        write_predictions(ts_future, y_pred, pred_metric, extra_labels)

        future_time = datetime.fromtimestamp(ts_future[-1]).strftime("%H:%M:%S")
        logger.info(
            "[%s] %-40s → %-35s 写入 %d 点，预测至 %s",
            now_str, query, pred_metric, len(y_pred), future_time,
        )


def main():
    logger.info(
        "预测服务启动  VM=%s  预测窗口=%ds  轮询间隔=%ds",
        VM_URL, HORIZON_SECONDS, POLL_INTERVAL,
    )
    while True:
        run_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
