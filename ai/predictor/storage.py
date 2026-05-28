# -*- coding: utf-8 -*-
"""
predictor.storage
~~~~~~~~~~~~~~~~~
VictoriaMetrics 读写层，封装所有网络 IO。

职责：
- 从 VM 拉取历史时序数据（query_range）
- 将预测结果和异常指标写入 VM（import/prometheus）
- 标签字符串的序列化与解析
- 状态文件的持久化读写

本模块不包含任何预测或异常检测逻辑，只负责数据的搬运和格式转换。

依赖：requests, numpy
"""

import json
import logging
import math
import os
import re
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

from .models import BaselineState

logger = logging.getLogger(__name__)

# 用于解析 PromQL 标签字符串的正则，匹配 key="value" 格式
_LABEL_PATTERN = re.compile(
    r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"((?:\\.|[^"])*)"\s*'
)


# ---------------------------------------------------------------------------
# 历史数据读取
# ---------------------------------------------------------------------------

def fetch_history(
    vm_url: str,
    query: str,
    minutes: int,
    step: str = "1s",
) -> Tuple[List[float], List[float]]:
    """
    从 VictoriaMetrics 拉取指定查询的历史时序数据。

    Args:
        vm_url: VM HTTP 地址，如 "http://localhost:8428"
        query: PromQL 查询表达式，如 'feed_rate{device_id="fanuc-cnc"}'
        minutes: 向前拉取多少分钟的历史数据
        step: 查询步长，默认 "1s"（每秒一个点）

    Returns:
        (timestamps, values) 两个列表，长度相同。
        如果查询失败或无数据，返回两个空列表。
    """
    now = datetime.now()
    start = now - timedelta(minutes=minutes)

    try:
        resp = requests.get(
            f"{vm_url}/api/v1/query_range",
            params={
                "query": query,
                "start": start.timestamp(),
                "end": now.timestamp(),
                "step": step,
            },
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("拉取历史数据失败 query=%s: %s", query, e)
        return [], []

    try:
        result = resp.json().get("data", {}).get("result", [])
    except Exception as e:
        logger.error("解析 VM 响应失败 query=%s: %s", query, e)
        return [], []

    if not result:
        return [], []

    ts_list: List[float] = []
    ys_list: List[float] = []

    for item in result[0].get("values", []):
        if len(item) < 2:
            continue
        try:
            t = float(item[0])
            y = float(item[1])
        except (TypeError, ValueError):
            continue
        # 过滤 NaN / Inf，防止后续 numpy 计算出错
        if math.isfinite(t) and math.isfinite(y):
            ts_list.append(t)
            ys_list.append(y)

    return ts_list, ys_list


def normalize_history(
    ts: List[float],
    ys: List[float],
) -> Tuple[np.ndarray, np.ndarray]:
    """
    将原始时序数据规整化为均匀 1 秒间隔的网格。

    处理步骤：
    1. 去重（同一秒内取最后一个值）
    2. 按时间戳排序
    3. 线性插值填充缺失秒

    Args:
        ts: 原始时间戳列表（Unix 秒，可以是浮点数）
        ys: 对应的值列表

    Returns:
        (ts_grid, ys_grid) 均匀 1 秒间隔的 numpy 数组。
        如果输入无效，返回两个空数组。
    """
    if not ts or not ys or len(ts) != len(ys):
        return np.array([]), np.array([])

    # 去重：同一秒取最后写入的值
    data: Dict[int, float] = {}
    for t, y in zip(ts, ys):
        try:
            sec = int(round(float(t)))
            val = float(y)
        except (TypeError, ValueError):
            continue
        if math.isfinite(sec) and math.isfinite(val):
            data[sec] = val

    if not data:
        return np.array([]), np.array([])

    sorted_items = sorted(data.items())
    ts_clean = np.array([x[0] for x in sorted_items], dtype=float)
    ys_clean = np.array([x[1] for x in sorted_items], dtype=float)

    if len(ts_clean) < 2:
        return ts_clean, ys_clean

    start_sec = int(ts_clean[0])
    end_sec = int(ts_clean[-1])

    if end_sec <= start_sec:
        return ts_clean, ys_clean

    # 构建均匀网格并插值
    ts_grid = np.arange(start_sec, end_sec + 1, 1, dtype=float)
    ys_grid = np.interp(ts_grid, ts_clean, ys_clean)

    return ts_grid, ys_grid


# ---------------------------------------------------------------------------
# 标签工具
# ---------------------------------------------------------------------------

def prom_escape_label_value(value: str) -> str:
    """对 Prometheus 标签值进行转义，处理反斜杠、换行符和双引号。"""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def labels_to_str(labels: Dict[str, str]) -> str:
    """
    将标签字典序列化为 Prometheus 格式的标签字符串。

    Example:
        {"device_id": "fanuc-cnc", "source": "protoforge"}
        → '{device_id="fanuc-cnc",source="protoforge"}'
    """
    if not labels:
        return ""
    parts = [
        f'{k}="{prom_escape_label_value(labels[k])}"'
        for k in sorted(labels)
    ]
    return "{" + ",".join(parts) + "}"


def parse_labels_from_query(query: str) -> Dict[str, str]:
    """
    从 PromQL 查询字符串中提取标签字典。

    Example:
        'feed_rate{device_id="fanuc-cnc"}' → {"device_id": "fanuc-cnc"}
    """
    labels: Dict[str, str] = {}

    if "{" not in query or "}" not in query:
        return labels

    try:
        label_part = query[query.index("{") + 1 : query.rindex("}")]
    except ValueError:
        return labels

    for match in _LABEL_PATTERN.finditer(label_part):
        key = match.group(1)
        value = (
            match.group(2)
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\\\", "\\")
        )
        labels[key] = value

    return labels


def merge_labels(*dicts: Dict[str, str]) -> Dict[str, str]:
    """合并多个标签字典，后面的字典覆盖前面的同名键。"""
    result: Dict[str, str] = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def series_key(metric_name: str, labels: Dict[str, str]) -> str:
    """生成唯一的序列标识符，用于 BaselineState 字典的键。"""
    return metric_name + labels_to_str(labels)


# ---------------------------------------------------------------------------
# 数据写入
# ---------------------------------------------------------------------------

def write_series(
    vm_url: str,
    metric_name: str,
    labels: Dict[str, str],
    ts_list: List[int],
    values: List[float],
) -> bool:
    """
    将一条时序数据写入 VictoriaMetrics（Prometheus remote write 格式）。

    Args:
        vm_url: VM HTTP 地址
        metric_name: 指标名
        labels: 标签字典
        ts_list: 时间戳列表（Unix 秒）
        values: 对应的值列表

    Returns:
        写入成功返回 True，否则返回 False。
    """
    if not ts_list or not values or len(ts_list) != len(values):
        return False

    label_str = labels_to_str(labels)
    lines: List[str] = []

    for t, y in zip(ts_list, values):
        try:
            ts_sec = int(round(float(t)))
            val = float(y)
        except (TypeError, ValueError):
            continue
        if math.isfinite(ts_sec) and math.isfinite(val):
            # VM 使用毫秒时间戳
            lines.append(f"{metric_name}{label_str} {val:.6f} {ts_sec * 1000}")

    if not lines:
        return False

    payload = "\n".join(lines) + "\n"

    try:
        resp = requests.post(
            f"{vm_url}/api/v1/import/prometheus",
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
    vm_url: str,
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
    """
    一次性写入一个指标的完整预测结果包，包含：
    - 预测中值曲线（pred_metric）
    - 预测下界曲线（pred_metric_lower）
    - 预测上界曲线（pred_metric_upper）
    - 异常标志（anomaly_metric，0 或 1）
    - 各项异常诊断指标（outside_ratio、mean_abs_error 等）

    Args:
        vm_url: VM HTTP 地址
        pred_metric: 预测指标名，如 "feed_rate_predicted"
        anomaly_metric: 异常指标名，如 "feed_rate_anomaly"
        labels: 写入时附加的标签
        ts_future: 预测时间戳列表（未来时刻，Unix 秒）
        pred_values: 预测中值数组
        lower_values: 预测下界数组
        upper_values: 预测上界数组
        is_anomaly: 当前是否判定为异常
        outside_ratio: 检测窗口内越界点比例
        mean_abs_err: 平均绝对误差
        mean_rel_err: 平均相对误差
        max_outside_seconds: 最长连续越界秒数
        max_exceed_ratio: 最大越界倍数（相对于边界宽度）
        event_ts: 异常诊断指标的时间戳（通常为最后一个真实数据点的时间戳）

    Returns:
        所有写入均成功返回 True，任意一个失败返回 False。
    """
    # 异常诊断指标附加 type 标签，便于在 Grafana 中过滤
    anomaly_labels = {**labels, "type": "prediction_deviation"}

    results = [
        write_series(vm_url, pred_metric, labels,
                     ts_future, pred_values.tolist()),
        write_series(vm_url, f"{pred_metric}_lower", labels,
                     ts_future, lower_values.tolist()),
        write_series(vm_url, f"{pred_metric}_upper", labels,
                     ts_future, upper_values.tolist()),
        write_series(vm_url, anomaly_metric, anomaly_labels,
                     [event_ts], [1.0 if is_anomaly else 0.0]),
        write_series(vm_url, f"{anomaly_metric}_outside_ratio", anomaly_labels,
                     [event_ts], [outside_ratio]),
        write_series(vm_url, f"{anomaly_metric}_mean_abs_error", anomaly_labels,
                     [event_ts], [mean_abs_err]),
        write_series(vm_url, f"{anomaly_metric}_mean_rel_error", anomaly_labels,
                     [event_ts], [mean_rel_err]),
        write_series(vm_url, f"{anomaly_metric}_max_consecutive_outside", anomaly_labels,
                     [event_ts], [float(max_outside_seconds)]),
        write_series(vm_url, f"{anomaly_metric}_max_exceed_ratio", anomaly_labels,
                     [event_ts], [float(max_exceed_ratio)]),
    ]

    return all(results)


# ---------------------------------------------------------------------------
# 状态持久化
# ---------------------------------------------------------------------------

def load_state(path: str) -> Dict[str, BaselineState]:
    """
    从 JSON 文件加载所有指标的基线状态。

    文件不存在时返回空字典（正常首次启动情况）。
    字段不完整的条目会被跳过，不会导致整体加载失败。

    Args:
        path: 状态文件路径

    Returns:
        key → BaselineState 的字典
    """
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning("加载状态文件失败，将重新学习: %s", e)
        return {}

    required_fields = {
        "period", "phase_origin_ts", "template", "lower_template",
        "upper_template", "strategy", "status", "clean_seconds",
        "last_update_ts", "last_seen_ts", "y_min", "y_max",
    }

    states: Dict[str, BaselineState] = {}
    for key, value in raw.get("baseline_states", {}).items():
        if required_fields.issubset(value.keys()):
            states[key] = BaselineState(**value)

    logger.info("已加载状态文件 %s，共 %d 条记录", path, len(states))
    return states


def save_state(path: str, states: Dict[str, BaselineState]) -> None:
    """
    将所有指标的基线状态原子写入 JSON 文件。

    使用临时文件 + os.replace 保证写入原子性，
    避免进程崩溃时产生损坏的状态文件。

    Args:
        path: 状态文件路径
        states: key → BaselineState 的字典
    """
    try:
        raw = {
            "baseline_states": {
                key: asdict(state)
                for key, state in states.items()
            }
        }
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning("保存状态文件失败: %s", e)
