# -*- coding: utf-8 -*-
"""
predictor.profiling
~~~~~~~~~~~~~~~~~~~
Layer 2：自适应配置推断。

职责：
- 从历史数据统计指标特征（p5/p95/IQR/cv/周期抖动率）
- 自动推断预测策略（phase_point vs phase_band）和阈值
- 加载人工上下限覆盖文件（override）
- 将 MetricProfile 转换为执行层 target dict
- 完整的发现 + 推断流程（refresh_targets）

依赖：predictor.storage, predictor.discovery, predictor.signal, predictor.models, predictor.config
"""

import json
import logging
import os
from typing import Dict, List, Optional

import numpy as np

from . import config
from .discovery import discover_device_ids, discover_metrics_for_device
from .models import MetricProfile
from .signal import estimate_period_rough, find_valley_indices
from .storage import fetch_history, normalize_history

logger = logging.getLogger(__name__)


def infer_metric_profile(
    vm_url: str,
    device_id: str,
    metric: str,
) -> Optional[MetricProfile]:
    """
    拉取历史数据，统计活跃段特征，自动推断预测策略和阈值。

    推断逻辑：
    - 空闲段过滤：排除 p10 以下的点，避免机床空闲时的零值拉低阈值
    - strategy 判断：cv < 0.15 → phase_point（稳定信号），否则 phase_band（波动信号）
    - abs_threshold：取 IQR * 0.8、量程 * 0.05、std * 2.0 三者最大值
    - rel_threshold：min(0.30, cv * 1.5)
    - band_pad_abs：max(IQR * 0.3, std)，覆盖正常尖峰
    - phase_lock_period_search_ratio：由周期抖动率动态决定，clip 到 [0.12, 0.25]

    Args:
        vm_url: VM HTTP 地址
        device_id: 设备标识
        metric: 指标名

    Returns:
        MetricProfile，数据不足时返回 None。
    """
    ts_raw, ys_raw = fetch_history(
        vm_url=vm_url,
        query=f'{metric}{{device_id="{device_id}"}}',
        minutes=config.HISTORY_MINUTES,
    )

    if len(ys_raw) < config.MIN_POINTS:
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

    # 策略自动判断：cv 衡量信号稳定性
    strategy = "phase_point" if cv < 0.15 else "phase_band"

    # 阈值自动计算
    abs_threshold = max(iqr * 0.8, (p95 - p5) * 0.05, std_val * 2.0)
    rel_threshold = min(0.30, cv * 1.5)

    # phase_band 容忍带宽度
    band_pad_abs = max(iqr * 0.3, std_val)

    # phase-lock 搜索范围：从历史数据估算周期抖动率
    ts_grid, ys_grid = normalize_history(ts_raw, ys_raw)
    period_search_ratio = config.PHASE_LOCK_PERIOD_SEARCH_RATIO  # 默认值

    if len(ys_grid) >= config.MIN_POINTS:
        rough_period = estimate_period_rough(ys_grid)
        if rough_period > config.MIN_PERIOD_SECONDS:
            valleys = find_valley_indices(ts_grid, ys_grid, rough_period)
            if len(valleys) >= 3:
                diffs = np.diff(ts_grid[valleys].astype(float))
                valid = diffs[
                    (diffs > rough_period * 0.5) & (diffs < rough_period * 2.0)
                ]
                if len(valid) >= 2:
                    # 周期变异系数 * 2 作为搜索范围，clip 到 [0.12, 0.25]
                    period_cv = float(np.std(valid) / max(np.mean(valid), 1e-6))
                    period_search_ratio = float(np.clip(period_cv * 2.0, 0.12, 0.25))

    logger.info(
        "推断指标特征 device=%s metric=%s cv=%.3f strategy=%s "
        "abs_thr=%.3f rel_thr=%.3f period_search=%.2f",
        device_id, metric, cv, strategy,
        abs_threshold, rel_threshold, period_search_ratio,
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


def load_overrides(path: str) -> Dict:
    """
    加载人工上下限覆盖文件，文件不存在时返回空字典。

    文件格式（JSON）：
        {
          "device-id": {
            "metric_name": {"hard_max": 35.0, "hard_min": 0.0}
          }
        }

    Args:
        path: 覆盖文件路径

    Returns:
        覆盖配置字典，文件不存在或解析失败时返回空字典。
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("加载 override 文件失败 %s: %s", path, e)
        return {}


def build_target(profile: MetricProfile, overrides: Dict) -> Dict:
    """
    将 MetricProfile 转换为预测执行层可用的 target dict。

    target dict 包含 run_once() 所需的全部配置：
    - query / pred_metric / anomaly_metric
    - strategy / 阈值 / 平滑窗口
    - phase-lock 搜索范围
    - 物理上下限（可选，来自 override 文件）

    Args:
        profile: 从历史数据推断出的指标特征
        overrides: 覆盖配置字典（来自 load_overrides）

    Returns:
        target dict。
    """
    device_overrides = overrides.get(profile.device_id, {}).get(profile.metric, {})

    target: Dict = {
        "query": f'{profile.metric}{{device_id="{profile.device_id}"}}',
        "pred_metric": f"{profile.metric}_predicted",
        "anomaly_metric": f"{profile.metric}_anomaly",
        "strategy": profile.strategy,
        "abs_threshold": profile.abs_threshold,
        "rel_threshold": profile.rel_threshold,
        # phase_band 用更大的平滑窗口抑制脉冲噪声
        "smooth_window": 5 if profile.strategy == "phase_band" else 2,
        "outside_ratio_threshold": 0.60,
        "min_consecutive_outside": 5,
        "severe_exceed_ratio": 1.8,
        "phase_lock_period_search_ratio": profile.phase_lock_period_search_ratio,
        # origin 搜索范围约为 period 搜索范围的 2.5 倍
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


def refresh_targets(
    vm_url: str,
    monitored_metrics: List[str],
    override_path: str,
) -> List[Dict]:
    """
    完整的发现 + 推断流程：发现所有设备，推断所有指标的配置，返回 target list。

    流程：
    1. 从 VM 发现所有 device_id
    2. 对每个设备探测哪些指标有数据
    3. 对每个有数据的指标推断 MetricProfile
    4. 将 MetricProfile 转换为 target dict

    若发现失败（无 device_id），返回空列表，由调用方决定是否保留旧列表。

    Args:
        vm_url: VM HTTP 地址
        monitored_metrics: 待探测的指标名候选列表
        override_path: 覆盖文件路径

    Returns:
        target dict 列表，每个元素对应一个 (device_id, metric) 对。
    """
    logger.info("开始发现设备和指标...")
    overrides = load_overrides(override_path)
    targets: List[Dict] = []

    device_ids = discover_device_ids(vm_url)
    if not device_ids:
        logger.warning("未发现任何 device_id")
        return []

    for device_id in device_ids:
        metrics = discover_metrics_for_device(vm_url, device_id, monitored_metrics)
        for metric in metrics:
            profile = infer_metric_profile(vm_url, device_id, metric)
            if profile is not None:
                targets.append(build_target(profile, overrides))

    logger.info(
        "目标列表已更新：%d 台设备，%d 个指标目标",
        len(device_ids),
        len(targets),
    )
    return targets
