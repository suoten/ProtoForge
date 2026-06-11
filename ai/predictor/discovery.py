# -*- coding: utf-8 -*-
"""
predictor.discovery
~~~~~~~~~~~~~~~~~~~
Layer 1：设备与指标发现。

职责：
- 从 VictoriaMetrics 查询所有在线设备（device_id 标签值）
- 探测指定设备上哪些指标名当前有数据

本模块只做网络查询，不包含任何预测或统计逻辑。

依赖：requests
"""

import logging
from typing import List

import requests

logger = logging.getLogger(__name__)


def discover_device_ids(vm_url: str) -> List[str]:
    """
    从 VictoriaMetrics 查询所有 device_id 标签值。

    调用 VM 的 label values 接口，返回当前存储中出现过的所有设备 ID。
    网络失败时返回空列表，不抛出异常，由调用方决定如何处理。

    Args:
        vm_url: VM HTTP 地址，如 "http://localhost:8428"

    Returns:
        设备 ID 字符串列表，空字符串已过滤。
        查询失败时返回空列表。
    """
    try:
        resp = requests.get(
            f"{vm_url}/api/v1/label/device_id/values",
            timeout=10,
        )
        resp.raise_for_status()
        return [v for v in resp.json().get("data", []) if v]
    except requests.RequestException as e:
        logger.error("发现 device_id 失败: %s", e)
        return []


def discover_metrics_for_device(
    vm_url: str,
    device_id: str,
    candidates: List[str],
) -> List[str]:
    """
    探测指定设备在 VictoriaMetrics 中实际存在且有近期数据的指标名。

    对 candidates 中的每个指标名发起即时查询（instant query），
    只有返回非空 result 的指标才被认为"存在"。

    Args:
        vm_url: VM HTTP 地址
        device_id: 设备标识，对应 VM 中的 device_id 标签值
        candidates: 待探测的指标名列表，如 ["feed_rate", "spindle_speed"]

    Returns:
        实际有数据的指标名列表（保持 candidates 中的顺序）。
        单个指标查询失败时静默跳过，不影响其他指标的探测。
    """
    found: List[str] = []
    for metric in candidates:
        try:
            resp = requests.get(
                f"{vm_url}/api/v1/query",
                params={"query": f'{metric}{{device_id="{device_id}"}}'},
                timeout=5,
            )
            resp.raise_for_status()
            if resp.json().get("data", {}).get("result"):
                found.append(metric)
        except requests.RequestException:
            # 单个指标查询失败不影响整体发现流程
            pass
    return found
