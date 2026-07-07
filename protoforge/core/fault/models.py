"""故障数据模型。

定义故障类型枚举、故障严重级别枚举和故障数据类。

故障类型覆盖传感器故障、通信故障、设备故障和执行器故障四大类，
共九种故障类型，每种类型模拟不同的工业设备故障场景。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class FaultType(str, Enum):
    """故障类型枚举。

    每种故障类型模拟不同的工业设备故障场景：

    传感器故障:
      - SENSOR_STUCK:    传感器卡死，持续返回首次值
      - SENSOR_DRIFT:    传感器漂移，值随时间线性偏移
      - SENSOR_NOISE:    噪声增大，叠加高斯白噪声
      - SENSOR_FAILURE:  完全失效，返回超量程值或 None

    通信故障:
      - COMM_INTERMITTENT: 间歇性断连，按概率返回 None
      - COMM_DELAY:        通信延迟，引入可配置的时间延迟
      - COMM_LOSS:         丢包，按概率丢弃数据

    设备/执行器故障:
      - DEVICE_FAILURE:  设备故障，触发状态机 fault 事件
      - ACTUATOR_STUCK:  执行器卡死，忽略写操作
    """

    SENSOR_STUCK = "sensor_stuck"
    SENSOR_DRIFT = "sensor_drift"
    SENSOR_NOISE = "sensor_noise"
    SENSOR_FAILURE = "sensor_failure"
    COMM_INTERMITTENT = "comm_intermittent"
    COMM_DELAY = "comm_delay"
    COMM_LOSS = "comm_loss"
    DEVICE_FAILURE = "device_failure"
    ACTUATOR_STUCK = "actuator_stuck"


class FaultSeverity(str, Enum):
    """故障严重级别。

    - LOW:      轻微故障，数据质量降级为 uncertain
    - MEDIUM:   中等故障，数据质量降级为 uncertain
    - HIGH:     严重故障，数据质量降级为 bad
    - CRITICAL: 致命故障，数据质量降级为 bad，可能触发设备停机
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Fault:
    """故障实例定义。

    :param fault_id: 故障唯一标识（自动生成，也可手动指定）
    :param fault_type: 故障类型
    :param target: 目标标识，可以是 device_id 或 point_name
    :param start_time: 故障开始时间戳 (Unix epoch)，0 表示添加时立即生效
    :param duration: 故障持续时间 (s)，-1 表示永久故障
    :param severity: 故障严重级别
    :param parameters: 故障参数字典，内容因故障类型而异：
        - SENSOR_STUCK:      ``{"stuck_value": float}`` 卡死值，不指定则用首次值
        - SENSOR_DRIFT:      ``{"drift_rate": float, "dt": float}`` 漂移速率/s, 时间步长
        - SENSOR_NOISE:      ``{"noise_level": float}`` 噪声标准差
        - SENSOR_FAILURE:    ``{"failure_value": float}`` 超量程值，不指定返回 None
        - COMM_INTERMITTENT: ``{"probability": float}`` 断连概率 0~1
        - COMM_DELAY:        ``{"delay_ms": float}`` 延迟毫秒数
        - COMM_LOSS:         ``{"probability": float}`` 丢包概率 0~1
        - DEVICE_FAILURE:    ``{}`` 无额外参数
        - ACTUATOR_STUCK:    ``{"stuck_value": float}`` 执行器卡死值
    :param active: 是否处于活跃状态
    :param last_value: 卡死故障用的缓存值（运行时自动管理）
    :param drift_accumulated: 漂移故障累计偏移量（运行时自动管理）
    """

    fault_id: str = ""
    fault_type: FaultType = FaultType.SENSOR_STUCK
    target: str = "*"
    start_time: float = 0.0
    duration: float = -1.0
    severity: FaultSeverity = FaultSeverity.MEDIUM
    parameters: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    last_value: Any = None
    drift_accumulated: float = 0.0

    def __post_init__(self):
        if not self.fault_id:
            self.fault_id = uuid.uuid4().hex[:12]
        if isinstance(self.fault_type, str):
            self.fault_type = FaultType(self.fault_type)
        if isinstance(self.severity, str):
            self.severity = FaultSeverity(self.severity)

    # -- 时间检查 ---------------------------------------------------------

    def is_expired(self, now: float) -> bool:
        """检查故障是否已过期。

        :param now: 当前时间戳
        :return: True 表示已过期（duration > 0 且已超时）
        """
        if self.duration < 0:
            return False  # 永久故障
        if self.duration == 0:
            return False  # 持续时间为 0 也视为永久
        return now >= self.start_time + self.duration

    def is_active_now(self, now: float) -> bool:
        """检查故障在当前时间是否应处于活跃状态。

        :param now: 当前时间戳
        :return: True 表示故障应处于活跃状态
        """
        if not self.active:
            return False
        if self.start_time > 0 and now < self.start_time:
            return False  # 尚未到开始时间
        return not self.is_expired(now)

    # -- 严重级别映射 -----------------------------------------------------

    @property
    def quality_degradation(self) -> str:
        """根据严重级别返回数据质量降级标记。

        :return: "uncertain" (LOW/MEDIUM) 或 "bad" (HIGH/CRITICAL)
        """
        if self.severity in (FaultSeverity.HIGH, FaultSeverity.CRITICAL):
            return "bad"
        return "uncertain"

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "fault_id": self.fault_id,
            "fault_type": self.fault_type.value,
            "target": self.target,
            "start_time": self.start_time,
            "duration": self.duration,
            "severity": self.severity.value,
            "parameters": self.parameters,
            "active": self.active,
            "last_value": self.last_value,
            "drift_accumulated": self.drift_accumulated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fault:
        """从字典反序列化。"""
        return cls(
            fault_id=data.get("fault_id", ""),
            fault_type=FaultType(data.get("fault_type", "sensor_stuck")),
            target=data.get("target", "*"),
            start_time=data.get("start_time", 0.0),
            duration=data.get("duration", -1.0),
            severity=FaultSeverity(data.get("severity", "medium")),
            parameters=data.get("parameters", {}),
            active=data.get("active", True),
            last_value=data.get("last_value"),
            drift_accumulated=data.get("drift_accumulated", 0.0),
        )
