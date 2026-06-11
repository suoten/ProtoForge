# -*- coding: utf-8 -*-
"""
predictor.config
~~~~~~~~~~~~~~~~
所有运行时配置常量，集中在此处管理。

大部分参数支持通过环境变量覆盖，方便容器化部署时无需修改代码。
环境变量前缀统一为 ``PROTOFORGE_``。
"""

import os
from typing import List

# ---------------------------------------------------------------------------
# VictoriaMetrics 连接
# ---------------------------------------------------------------------------

#: VM HTTP 地址，默认本机
VM_URL: str = os.environ.get("PROTOFORGE_VM_URL", "http://localhost:8428")

# ---------------------------------------------------------------------------
# 状态持久化
# ---------------------------------------------------------------------------

#: 健康模板状态文件路径（JSON），重启后可恢复学习进度
STATE_FILE: str = os.environ.get(
    "PROTOFORGE_STATE_FILE",
    "/tmp/protoforge_predictor_state_v14.json",
)

# ---------------------------------------------------------------------------
# 轮询与预测时间窗口
# ---------------------------------------------------------------------------

#: 拉取历史数据的时间窗口（分钟）
HISTORY_MINUTES: int = int(os.environ.get("PROTOFORGE_HISTORY_MINUTES", "30"))

#: 理论预测时间跨度（秒）
HORIZON_SECONDS: int = int(os.environ.get("PROTOFORGE_HORIZON_SECONDS", "120"))

#: 轮询间隔（秒）
POLL_INTERVAL: int = int(os.environ.get("PROTOFORGE_POLL_INTERVAL", "30"))

#: 实际写入 VM 的预测点数 = min(HORIZON_SECONDS, POLL_INTERVAL)
#: 避免写入过多未来点导致 Grafana 图表出现"预测跳跃"
WRITE_HORIZON_SECONDS: int = min(HORIZON_SECONDS, POLL_INTERVAL)

#: VM 查询步长
QUERY_STEP: str = "1s"

#: 最少需要多少个历史点才能开始建模
MIN_POINTS: int = 120

# ---------------------------------------------------------------------------
# 周期检测范围
# ---------------------------------------------------------------------------

#: 允许的最短周期（秒）
MIN_PERIOD_SECONDS: int = 5

#: 允许的最长周期（秒）
MAX_PERIOD_SECONDS: int = 3600

# ---------------------------------------------------------------------------
# 模板学习参数
# ---------------------------------------------------------------------------

#: 构建模板至少需要多少个完整周期
MIN_FULL_CYCLES_FOR_TEMPLATE: int = 3

#: 最多使用最近多少个周期来构建模板（防止过旧数据污染）
MAX_CYCLES_FOR_TEMPLATE: int = 8

#: 谷底检测时，低于此百分位的点才被视为谷底候选
VALLEY_QUANTILE: int = 45

#: 健康状态下模板 EMA 更新步长（越小越保守，变化越慢）
HEALTHY_EMA_ALPHA: float = 0.10

#: 恢复状态下模板 EMA 更新步长（比健康状态更激进，加速追赶）
RECOVERY_EMA_ALPHA: float = 0.25

# ---------------------------------------------------------------------------
# 异常检测默认阈值
# ---------------------------------------------------------------------------

#: 检测窗口（秒）：只看最近这段时间的数据来判断是否异常
DETECT_WINDOW_SECONDS: int = 30

#: 恢复期最短持续时间（秒）：异常消失后至少稳定这么久才恢复学习
RECOVERY_MIN_SECONDS: int = 60

#: 越界比例阈值：窗口内超过此比例的点越界则报警
OUTSIDE_RATIO_THRESHOLD: float = 0.60

#: 连续越界阈值（秒）：连续越界超过此秒数则报警
MIN_CONSECUTIVE_OUTSIDE: int = 5

#: 严重越界倍数：单点超出边界宽度的此倍数则立即报警
SEVERE_EXCEED_RATIO: float = 1.8

#: 真实数据最大允许延迟（秒）：超过此值认为数据管道异常，跳过预测
MAX_DATA_LAG_SECONDS: int = 180

# ---------------------------------------------------------------------------
# Phase-lock 搜索参数
# ---------------------------------------------------------------------------

#: phase-lock 使用的最短历史窗口（秒）
PHASE_LOCK_MIN_WINDOW_SECONDS: int = 45

#: phase-lock 使用的最长历史窗口（秒）
PHASE_LOCK_MAX_WINDOW_SECONDS: int = 180

#: 周期搜索范围（相对于基准周期的比例），由 infer_metric_profile 动态覆盖
PHASE_LOCK_PERIOD_SEARCH_RATIO: float = 0.12

#: 相位原点搜索范围（相对于周期的比例）
PHASE_LOCK_ORIGIN_SEARCH_RATIO: float = 0.35

#: 周期搜索步长（秒）
PHASE_LOCK_PERIOD_STEP: int = 1

#: 相位原点搜索步长（秒）
PHASE_LOCK_ORIGIN_STEP: int = 1

# ---------------------------------------------------------------------------
# 监控指标白名单
# ---------------------------------------------------------------------------

#: 默认监控的指标名列表
_DEFAULT_MONITORED_METRICS: List[str] = [
    "feed_rate",
    "spindle_speed",
    "spindle_current",
    "spindle_load",
    "vibration_x",
    "vibration_y",
    "vibration_z",
]

#: 实际使用的监控指标列表，可通过环境变量 PROTOFORGE_MONITORED_METRICS 覆盖
#: 格式：逗号分隔的指标名，例如 "feed_rate,spindle_speed"
MONITORED_METRICS: List[str] = [
    m.strip()
    for m in os.environ.get(
        "PROTOFORGE_MONITORED_METRICS",
        ",".join(_DEFAULT_MONITORED_METRICS),
    ).split(",")
    if m.strip()
]

# ---------------------------------------------------------------------------
# 人工上下限覆盖文件
# ---------------------------------------------------------------------------

#: 覆盖文件路径，文件不存在时忽略（不报错）
#: 文件格式（JSON）：
#:   {
#:     "device-id": {
#:       "metric_name": {"hard_max": 35.0, "hard_min": 0.0}
#:     }
#:   }
OVERRIDE_FILE: str = os.environ.get(
    "PROTOFORGE_PREDICTOR_OVERRIDE",
    "/etc/protoforge/predictor_override.json",
)

# ---------------------------------------------------------------------------
# 目标列表刷新间隔
# ---------------------------------------------------------------------------

#: 每隔多少秒重新发现设备和指标（秒）
TARGETS_REFRESH_INTERVAL: int = int(
    os.environ.get("PROTOFORGE_TARGETS_REFRESH", "60")
)

# ---------------------------------------------------------------------------
# 写入 VM 时附加的额外标签
# ---------------------------------------------------------------------------

#: 附加到所有预测指标上的标签，用于在 Grafana 中区分预测数据和原始数据
EXTRA_PREDICT_LABELS = {
    "forecast": "phase_band_health_v14",
    "source": "protoforge",
}
