# -*- coding: utf-8 -*-
"""
ProtoForge 预测服务 v3

修复点：
1. 解决 HORIZON_SECONDS > POLL_INTERVAL 时，多轮预测窗口重叠导致 Grafana 出现毛刺/竖线问题。
2. 每轮写入新预测前，删除同一个预测 metric 的旧预测序列，只保留最新一轮预测。
3. 预测时间戳按整秒写入，避免毫秒时间戳和 Grafana step 不对齐。
4. 拟合使用真实 timestamp 相对时间，不再假设历史数据严格 1 秒等间隔。
5. 对历史数据做排序、去重、NaN/Inf 清洗。
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
HORIZON_SECONDS = 120
POLL_INTERVAL = 30
MIN_POINTS = 120
QUERY_STEP = "1s"

# 关键修复：每轮写入前删除旧预测，避免 120s 预测窗口和 30s 轮询周期重叠
CLEAR_OLD_PREDICTIONS = True

# 如果删除旧预测失败，是否跳过本轮写入。
# 建议 True，避免继续叠加脏数据。
SKIP_WRITE_IF_CLEAR_FAILED = True

# 给新预测数据加一个稳定标签，方便 Grafana 查询过滤。
# Grafana 可以查询：feed_rate_predicted{device_id="fanuc-cnc",forecast="latest"}
EXTRA_PREDICT_LABELS = {
    "forecast": "latest",
    "source": "protoforge",
}

# 正弦周期限制
MIN_PERIOD_SECONDS = 5.0
MAX_PERIOD_SECONDS = 3600.0

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
    1. 转换为整秒时间戳
    2. 排序
    3. 同一秒多个值时保留最后一个
    4. 插值补齐中间缺失秒
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

    # 统一为 1 秒网格，减少 query_range 缺点、抖动、缺失点对 FFT 的影响
    ts_grid = np.arange(start_sec, end_sec + 1, 1, dtype=float)
    ys_grid = np.interp(ts_grid, ts_clean, ys_clean)

    return ts_grid, ys_grid


def _sine_model(t: np.ndarray, A: float, T: float, phi: float, C: float) -> np.ndarray:
    return A * np.sin(2.0 * np.pi / T * t + phi) + C


def estimate_period_by_fft(ys_arr: np.ndarray) -> float:
    """
    使用 FFT 估算主周期。
    ys_arr 默认是 1 秒间隔。
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

    # 跳过直流分量 index 0
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


def predict_next(
    ts: List[float],
    ys: List[float],
    horizon: int = HORIZON_SECONDS,
    start_from_now: bool = True,
) -> Tuple[List[float], List[float]]:
    """
    用 FFT 检测主频，拟合正弦波，外推未来 horizon 秒。
    返回：
        future_timestamps: 未来整秒时间戳
        predicted_values: 预测值
    """
    ts_grid, ys_grid = normalize_history(ts, ys)

    if len(ys_grid) < MIN_POINTS:
        return [], []

    n = len(ys_grid)

    y_min = float(np.min(ys_grid))
    y_max = float(np.max(ys_grid))
    y_mean = float(np.mean(ys_grid))
    y_range = y_max - y_min

    # 数据几乎不波动时，直接使用最后一个值保持
    if y_range <= 1e-9:
        base_ts = int(time.time()) if start_from_now else int(ts_grid[-1])
        base_ts = max(base_ts, int(ts_grid[-1]))

        ts_future = [base_ts + i + 1 for i in range(horizon)]
        y_pred = [float(ys_grid[-1])] * horizon
        return ts_future, y_pred

    period = estimate_period_by_fft(ys_grid)

    # 用真实时间戳做相对时间，而不是 np.arange(n)
    t_fit = ts_grid - ts_grid[0]

    amplitude = y_range / 2.0
    offset = y_mean

    # 预测起点统一对齐到整秒
    if start_from_now:
        base_ts = int(time.time())
    else:
        base_ts = int(ts_grid[-1])

    # 避免因为 VM 查询延迟导致预测点落在最后一个真实点之前
    base_ts = max(base_ts, int(ts_grid[-1]))

    ts_future_arr = np.arange(base_ts + 1, base_ts + 1 + horizon, 1, dtype=float)
    t_future = ts_future_arr - ts_grid[0]

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

        # 裁剪到合理范围，避免拟合异常时飞出去
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
        logger.warning("正弦拟合失败，降级为最近值平滑外推: %s", e)

        # 降级策略：用最近 10 个点的均值保持，避免线性外推越走越偏
        tail = min(10, n)
        last_value = float(np.mean(ys_grid[-tail:]))

        ts_future = ts_future_arr.tolist()
        y_pred = [last_value] * horizon

        return ts_future, y_pred


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


def build_selector(metric_name: str, labels: Dict[str, str]) -> str:
    """
    构造 PromQL selector，用于 delete_series。

    示例：
        feed_rate_predicted{device_id="fanuc-cnc"}
    """
    if not labels:
        return metric_name

    parts = []
    for k in sorted(labels.keys()):
        v = prom_escape_label_value(labels[k])
        parts.append(f'{k}="{v}"')

    return f'{metric_name}' + "{" + ",".join(parts) + "}"


def delete_old_predictions(metric_name: str, base_labels: Dict[str, str]) -> bool:
    """
    删除旧预测序列，避免多轮预测窗口重叠。

    注意：
    这里故意只用 base_labels，比如 device_id。
    不带 forecast/source 标签，是为了兼容旧版本脚本写入的无 forecast 标签数据。
    """
    selector = build_selector(metric_name, base_labels)

    try:
        resp = requests.post(
            f"{VM_URL}/api/v1/admin/tsdb/delete_series",
            params=[("match[]", selector)],
            timeout=10,
        )

        if resp.status_code not in (200, 204):
            logger.error(
                "删除旧预测数据失败 metric=%s selector=%s status=%s body=%s",
                metric_name,
                selector,
                resp.status_code,
                resp.text[:500],
            )
            return False

        logger.debug("已删除旧预测数据 selector=%s", selector)
        return True

    except requests.RequestException as e:
        logger.error("删除旧预测数据异常 metric=%s selector=%s: %s", metric_name, selector, e)
        return False


def write_predictions(
    ts_future: List[float],
    y_pred: List[float],
    metric_name: str,
    labels: Dict[str, str] = None,
) -> bool:
    """
    将预测值以 Prometheus exposition 格式写入 VictoriaMetrics。
    时间戳为毫秒级 Unix timestamp。
    """
    if labels is None:
        labels = {}

    if not ts_future or not y_pred or len(ts_future) != len(y_pred):
        logger.warning("预测数据为空或长度不一致 metric=%s", metric_name)
        return False

    label_str = ""
    if labels:
        parts = []
        for k in sorted(labels.keys()):
            v = prom_escape_label_value(labels[k])
            parts.append(f'{k}="{v}"')
        label_str = "{" + ",".join(parts) + "}"

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


_LABEL_PATTERN = re.compile(r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"((?:\\.|[^"])*)"\s*')


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


def run_once():
    now_str = datetime.now().strftime("%H:%M:%S")

    for query, pred_metric in PREDICT_TARGETS:
        ts, ys = fetch_history(query)

        if len(ys) < MIN_POINTS:
            logger.info("[%s] %s 数据不足（%d 点），跳过", now_str, query, len(ys))
            continue

        ts_future, y_pred = predict_next(
            ts,
            ys,
            horizon=HORIZON_SECONDS,
            start_from_now=True,
        )

        if not ts_future or not y_pred:
            logger.warning("[%s] %s 预测结果为空，跳过", now_str, query)
            continue

        base_labels = _parse_labels(query)

        # 先删除旧预测，再写入新预测。
        # 删除条件只带 base_labels，兼容老版本无 forecast/source 标签的脏数据。
        if CLEAR_OLD_PREDICTIONS:
            clear_ok = delete_old_predictions(pred_metric, base_labels)

            if not clear_ok and SKIP_WRITE_IF_CLEAR_FAILED:
                logger.error(
                    "[%s] %s 删除旧预测失败，为避免继续制造重叠数据，本轮跳过写入",
                    now_str,
                    pred_metric,
                )
                continue

        write_labels = merge_labels(base_labels, EXTRA_PREDICT_LABELS)

        ok = write_predictions(
            ts_future=ts_future,
            y_pred=y_pred,
            metric_name=pred_metric,
            labels=write_labels,
        )

        if not ok:
            continue

        future_start = datetime.fromtimestamp(ts_future[0]).strftime("%H:%M:%S")
        future_end = datetime.fromtimestamp(ts_future[-1]).strftime("%H:%M:%S")

        logger.info(
            "[%s] %-40s → %-35s 写入 %d 点，预测区间 %s ~ %s",
            now_str,
            query,
            pred_metric,
            len(y_pred),
            future_start,
            future_end,
        )


def main():
    logger.info(
        "预测服务启动 VM=%s 历史窗口=%dmin 预测窗口=%ds 轮询间隔=%ds 清理旧预测=%s",
        VM_URL,
        HISTORY_MINUTES,
        HORIZON_SECONDS,
        POLL_INTERVAL,
        CLEAR_OLD_PREDICTIONS,
    )

    while True:
        run_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()