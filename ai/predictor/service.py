# -*- coding: utf-8 -*-
"""
predictor.service
~~~~~~~~~~~~~~~~~
主服务类：组装所有模块，驱动预测主循环。

职责：
- 持有所有运行时状态（baseline_states、last_written、targets）
- 按 TARGETS_REFRESH_INTERVAL 定期重新发现设备和指标
- 每轮轮询：拉取历史数据 → 更新状态 → 预测 → 写入 VM
- 每轮结束后持久化状态到文件

依赖：所有其他 predictor 子模块
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from . import config
from .anomaly import calc_final_bounds
from .models import BaselineState
from .profiling import refresh_targets
from .signal import preprocess_values
from .state import maybe_update_state
from .storage import (
    fetch_history,
    load_state,
    merge_labels,
    normalize_history,
    parse_labels_from_query,
    save_state,
    series_key,
    write_prediction_bundle,
)
from .template import predict_state_bundle

logger = logging.getLogger(__name__)


class PredictorService:
    """
    预测服务主类。

    封装所有运行时状态，支持多实例部署（每个实例独立持有状态）。
    通过 run() 启动主循环，通过 run_once() 执行单轮预测。

    Attributes:
        _vm_url: VM HTTP 地址
        _state_file: 状态持久化文件路径
        _history_minutes: 拉取历史数据的时间窗口（分钟）
        _write_horizon: 实际写入 VM 的预测点数（秒）
        _poll_interval: 轮询间隔（秒）
        _targets_refresh_interval: 目标列表刷新间隔（秒）
        _monitored_metrics: 待监控的指标名列表
        _override_file: 人工上下限覆盖文件路径
        _extra_labels: 写入 VM 时附加的额外标签
        _states: key → BaselineState 的字典（运行时状态）
        _last_written: key → 上次写入的真实数据时间戳
        _targets: 当前目标列表
        _targets_last_refresh: 上次刷新目标列表的时间戳
    """

    def __init__(
        self,
        vm_url: str = config.VM_URL,
        state_file: str = config.STATE_FILE,
        history_minutes: int = config.HISTORY_MINUTES,
        write_horizon: int = config.WRITE_HORIZON_SECONDS,
        poll_interval: int = config.POLL_INTERVAL,
        targets_refresh_interval: int = config.TARGETS_REFRESH_INTERVAL,
        monitored_metrics: Optional[List[str]] = None,
        override_file: str = config.OVERRIDE_FILE,
        extra_labels: Optional[Dict[str, str]] = None,
    ) -> None:
        self._vm_url = vm_url
        self._state_file = state_file
        self._history_minutes = history_minutes
        self._write_horizon = write_horizon
        self._poll_interval = poll_interval
        self._targets_refresh_interval = targets_refresh_interval
        self._monitored_metrics = monitored_metrics or config.MONITORED_METRICS
        self._override_file = override_file
        self._extra_labels = extra_labels or config.EXTRA_PREDICT_LABELS

        self._states: Dict[str, BaselineState] = {}
        self._last_written: Dict[str, int] = {}
        self._targets: List[Dict] = []
        self._targets_last_refresh: float = 0.0

    # ------------------------------------------------------------------
    # 目标列表管理
    # ------------------------------------------------------------------

    def _refresh_targets_if_needed(self) -> None:
        """
        按 targets_refresh_interval 间隔重新发现设备和指标。

        首次调用时立即执行发现。发现失败时保留现有目标列表。
        """
        now = time.time()
        if now - self._targets_last_refresh < self._targets_refresh_interval and self._targets:
            return

        new_targets = refresh_targets(
            vm_url=self._vm_url,
            monitored_metrics=self._monitored_metrics,
            override_path=self._override_file,
        )

        if new_targets:
            self._targets = new_targets
            self._targets_last_refresh = now
        else:
            logger.warning("发现流程未产生任何有效目标，保持现有目标列表")

    # ------------------------------------------------------------------
    # 预测时间轴
    # ------------------------------------------------------------------

    def _build_prediction_timestamps(
        self,
        key: str,
        last_real_ts: int,
        now_sec: int,
    ) -> Optional[List[int]]:
        """
        构建预测时间戳列表（从 last_real_ts + 1 开始，共 write_horizon 个点）。

        两种情况下跳过写入：
        1. 真实数据延迟过大（数据管道异常）
        2. 真实数据时间戳未推进（重复写入同一批预测）

        Args:
            key: 序列标识符
            last_real_ts: 最新真实数据点的时间戳（Unix 秒）
            now_sec: 当前时间戳（Unix 秒）

        Returns:
            预测时间戳列表，跳过时返回 None。
        """
        data_lag = now_sec - last_real_ts

        if data_lag > config.MAX_DATA_LAG_SECONDS:
            logger.warning(
                "真实数据延迟过大，跳过预测 key=%s data_lag=%ss max=%ss",
                key, data_lag, config.MAX_DATA_LAG_SECONDS,
            )
            return None

        last_written_real_ts = self._last_written.get(key)
        if last_written_real_ts is not None and last_real_ts <= int(last_written_real_ts):
            logger.info(
                "真实数据时间戳未推进，跳过重复写入 key=%s last_real_ts=%s last_written=%s",
                key, last_real_ts, last_written_real_ts,
            )
            return None

        return [last_real_ts + i + 1 for i in range(self._write_horizon)]

    # ------------------------------------------------------------------
    # 单轮预测
    # ------------------------------------------------------------------

    def run_once(self) -> None:
        """
        执行一轮预测：遍历所有目标，拉取数据、更新状态、写入预测结果。

        每轮结束后将状态持久化到文件。
        """
        now_str = datetime.now().strftime("%H:%M:%S")

        self._refresh_targets_if_needed()

        if not self._targets:
            logger.warning("[%s] 目标列表为空，等待设备发现完成", now_str)
            return

        for target in self._targets:
            query = target["query"]
            pred_metric = target["pred_metric"]
            anomaly_metric = target["anomaly_metric"]
            strategy = target.get("strategy", "phase_point")
            smooth_window = int(target.get("smooth_window", 1))

            # 1. 拉取历史数据
            ts, ys = fetch_history(
                vm_url=self._vm_url,
                query=query,
                minutes=self._history_minutes,
            )

            if len(ys) < config.MIN_POINTS:
                logger.info("[%s] %s 数据不足（%d 点），跳过", now_str, query, len(ys))
                continue

            ts_grid, ys_grid_raw = normalize_history(ts, ys)

            if len(ys_grid_raw) < config.MIN_POINTS:
                logger.info(
                    "[%s] %s 清洗后数据不足（%d 点），跳过",
                    now_str, query, len(ys_grid_raw),
                )
                continue

            # 2. 预处理（平滑）
            ys_grid_model = preprocess_values(ys_grid_raw, strategy, smooth_window)

            # 3. 构建写入标签
            base_labels = parse_labels_from_query(query)
            write_labels = merge_labels(base_labels, self._extra_labels)
            key = series_key(pred_metric, write_labels)

            # 4. 更新状态（异常检测 + 模板学习）
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
                states=self._states,
            )

            if state is None:
                logger.info("[%s] %s 暂无可用健康模板，等待学习", now_str, query)
                continue

            # 5. 构建预测时间戳
            now_sec = int(time.time())
            last_real_ts = int(ts_grid[-1])
            data_lag = now_sec - last_real_ts

            ts_future = self._build_prediction_timestamps(
                key=key,
                last_real_ts=last_real_ts,
                now_sec=now_sec,
            )

            if not ts_future:
                continue

            # 6. 预测
            pred_values, lower_raw, upper_raw = predict_state_bundle(state, ts_future)
            lower_values, upper_values = calc_final_bounds(
                state=state,
                pred=pred_values,
                lower_raw=lower_raw,
                upper_raw=upper_raw,
                target=target,
            )

            # 7. 写入 VM
            ok = write_prediction_bundle(
                vm_url=self._vm_url,
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

            self._last_written[key] = last_real_ts

            # 8. 打印摘要日志
            future_start = datetime.fromtimestamp(ts_future[0]).strftime("%H:%M:%S")
            future_end = datetime.fromtimestamp(ts_future[-1]).strftime("%H:%M:%S")
            last_real_str = datetime.fromtimestamp(last_real_ts).strftime("%H:%M:%S")
            origin_str = datetime.fromtimestamp(state.phase_origin_ts).strftime("%H:%M:%S")

            logger.info(
                "[%s] %-50s → %-35s strategy=%s status=%s anomaly=%s "
                "outside=%.2f max_outside=%ss max_exceed=%.2f "
                "period=%ss origin=%s last_real=%s lag=%ss 写入 %d 点，预测区间 %s ~ %s",
                now_str, query, pred_metric,
                state.strategy, state.status, is_anomaly,
                outside_ratio, max_outside_seconds, max_exceed_ratio,
                state.period, origin_str, last_real_str, data_lag,
                len(ts_future), future_start, future_end,
            )

        save_state(self._state_file, self._states)

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        启动预测服务主循环。

        加载持久化状态后进入无限循环，每隔 poll_interval 秒执行一次 run_once()。
        """
        self._states = load_state(self._state_file)

        logger.info(
            "预测服务启动 VM=%s 历史窗口=%dmin 理论预测窗口=%ds 实际写入窗口=%ds "
            "轮询间隔=%ds state=%s forecast=%s override=%s refresh=%ds",
            self._vm_url,
            self._history_minutes,
            config.HORIZON_SECONDS,
            self._write_horizon,
            self._poll_interval,
            self._state_file,
            self._extra_labels.get("forecast", ""),
            self._override_file,
            self._targets_refresh_interval,
        )

        while True:
            self.run_once()
            time.sleep(self._poll_interval)
