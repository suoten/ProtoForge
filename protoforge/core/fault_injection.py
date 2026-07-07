"""故障注入引擎。

本模块实现了完整的工业设备故障注入系统，支持八种故障类型、
四种触发模式、故障传播链和故障场景编排。可嵌入 ProtoForge 的
数据生成流水线，对传感器读数、通信链路和设备行为施加可控故障，
用于测试上位机软件的容错能力和报警逻辑。

故障类型:
  - SENSOR_STUCK:      传感器卡死，持续返回首次值
  - SENSOR_DRIFT:      传感器漂移，值随时间线性偏移
  - SENSOR_NOISE:      噪声增大，叠加高斯噪声
  - COMM_INTERMITTENT: 间歇性断连，按概率返回 None
  - COMM_DELAY:        通信延迟，引入可配置的时间延迟
  - COMM_LOSS:         数据丢包，按概率丢弃数据
  - DEVICE_FAILURE:    设备完全失效，抛出异常
  - DATA_CORRUPTION:   数据篡改/损坏，按位翻转或数值偏移

典型用法::

    from protoforge.core.fault_injection import FaultInjector, FaultConfig, FaultType

    injector = FaultInjector()
    fid = injector.add_fault(FaultConfig(
        fault_type=FaultType.SENSOR_DRIFT,
        target_point="temperature",
        parameters={"drift_rate": 0.5, "duration": 60},
    ))
    injector.activate_fault(fid)
    modified, is_faulty = injector.apply("temperature", 25.0)
"""

from __future__ import annotations

import json
import logging
import random
import struct
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  异常定义
# ---------------------------------------------------------------------------

class DeviceFailureException(Exception):
    """设备完全失效异常。

    当 ``DEVICE_FAILURE`` 故障类型被激活时抛出，
    表示设备无法响应任何请求。
    """

    def __init__(self, device_id: str = "", point_name: str = "", reason: str = ""):
        self.device_id = device_id
        self.point_name = point_name
        self.reason = reason
        msg = f"Device failure: device={device_id}, point={point_name}"
        if reason:
            msg += f", reason={reason}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
#  枚举定义
# ---------------------------------------------------------------------------

class FaultType(str, Enum):
    """故障类型枚举。

    每种故障类型模拟不同的工业设备故障场景：

    - SENSOR_STUCK:      传感器卡死，保持第一次读到的值不变
    - SENSOR_DRIFT:      传感器漂移，读数随时间线性偏移
    - SENSOR_NOISE:      传感器噪声增大，叠加高斯白噪声
    - COMM_INTERMITTENT: 通信间歇性断连，按概率返回 None
    - COMM_DELAY:        通信延迟增大，引入可配置的时间延迟
    - COMM_LOSS:         数据丢包，按概率丢弃数据包
    - DEVICE_FAILURE:    设备完全失效，抛出 DeviceFailureException
    - DATA_CORRUPTION:   数据篡改/损坏，按位翻转或数值偏移
    """

    SENSOR_STUCK = "sensor_stuck"
    SENSOR_DRIFT = "sensor_drift"
    SENSOR_NOISE = "sensor_noise"
    COMM_INTERMITTENT = "comm_intermittent"
    COMM_DELAY = "comm_delay"
    COMM_LOSS = "comm_loss"
    DEVICE_FAILURE = "device_failure"
    DATA_CORRUPTION = "data_corruption"


class TriggerMode(str, Enum):
    """故障触发模式。

    - MANUAL:     手动触发，需调用 activate_fault()
    - RANDOM:     随机触发，按概率自动激活
    - SCHEDULED:  定时触发，在指定时间自动激活
    - CONDITIONAL:条件触发，满足条件回调时自动激活
    """

    MANUAL = "manual"
    RANDOM = "random"
    SCHEDULED = "scheduled"
    CONDITIONAL = "conditional"


# ---------------------------------------------------------------------------
#  故障配置
# ---------------------------------------------------------------------------

@dataclass
class FaultConfig:
    """故障配置定义。

    :param fault_type: 故障类型
    :param target_point: 目标点位名称（"*" 表示所有点位）
    :param trigger_mode: 触发模式
    :param parameters: 故障参数字典，内容因故障类型而异：
        - SENSOR_STUCK:      {"duration": float}  持续时间 (s)
        - SENSOR_DRIFT:      {"drift_rate": float, "duration": float}  漂移速率/s, 持续时间
        - SENSOR_NOISE:      {"noise_std": float, "duration": float}  噪声标准差, 持续时间
        - COMM_INTERMITTENT: {"probability": float, "duration": float}  断连概率 0~1, 持续时间
        - COMM_DELAY:        {"delay_ms": float, "duration": float}  延迟毫秒, 持续时间
        - COMM_LOSS:         {"probability": float, "duration": float}  丢包概率 0~1, 持续时间
        - DEVICE_FAILURE:    {"duration": float}  持续时间
        - DATA_CORRUPTION:   {"corruption_rate": float, "mode": "bit_flip"|"offset", "offset_value": float, "duration": float}
    :param fault_id: 故障 ID（自动生成，也可手动指定）
    :param target_device: 目标设备 ID（可选，用于多设备场景）
    :param start_time: 定时触发的启动时间戳（SCHEDULED 模式）
    :param probability: 随机触发概率（RANDOM 模式，每次 tick 的激活概率）
    :param condition: 条件触发回调（CONDITIONAL 模式），签名为 condition(value) -> bool
    :param description: 故障描述
    """

    fault_type: FaultType
    target_point: str = "*"
    trigger_mode: TriggerMode = TriggerMode.MANUAL
    parameters: dict[str, Any] = field(default_factory=dict)
    fault_id: str = ""
    target_device: str = ""
    start_time: float | None = None
    probability: float = 0.0
    condition: Callable[[Any], bool] | None = None
    description: str = ""

    def __post_init__(self):
        if not self.fault_id:
            self.fault_id = uuid.uuid4().hex[:12]
        if isinstance(self.fault_type, str):
            self.fault_type = FaultType(self.fault_type)
        if isinstance(self.trigger_mode, str):
            self.trigger_mode = TriggerMode(self.trigger_mode)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（不含不可序列化的 condition 回调）。"""
        return {
            "fault_id": self.fault_id,
            "fault_type": self.fault_type.value,
            "target_point": self.target_point,
            "trigger_mode": self.trigger_mode.value,
            "parameters": self.parameters,
            "target_device": self.target_device,
            "start_time": self.start_time,
            "probability": self.probability,
            "description": self.description,
            "has_condition": self.condition is not None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FaultConfig:
        """从字典反序列化。"""
        return cls(
            fault_type=FaultType(data.get("fault_type", "sensor_stuck")),
            target_point=data.get("target_point", "*"),
            trigger_mode=TriggerMode(data.get("trigger_mode", "manual")),
            parameters=data.get("parameters", {}),
            fault_id=data.get("fault_id", ""),
            target_device=data.get("target_device", ""),
            start_time=data.get("start_time"),
            probability=data.get("probability", 0.0),
            description=data.get("description", ""),
        )


# ---------------------------------------------------------------------------
#  故障实例运行时状态
# ---------------------------------------------------------------------------

@dataclass
class _FaultRuntime:
    """故障实例的运行时状态（内部使用）。"""
    config: FaultConfig
    active: bool = False
    activated_at: float = 0.0
    deactivated_at: float = 0.0
    stuck_value: Any = None
    stuck_value_set: bool = False
    drift_start: float = 0.0
    call_count: int = 0

    @property
    def elapsed(self) -> float:
        """故障激活以来的经过时间 (s)。"""
        if not self.active:
            return 0.0
        return time.time() - self.activated_at

    @property
    def is_expired(self) -> bool:
        """故障是否已过期（超过持续时间）。"""
        duration = self.config.parameters.get("duration", 0)
        if duration <= 0:
            return False
        return self.active and self.elapsed >= duration


# ---------------------------------------------------------------------------
#  故障注入器
# ---------------------------------------------------------------------------

class FaultInjector:
    """故障注入器。

    管理多个故障配置，对数据值应用故障效果。

    线程安全，支持并发调用 ``apply()``。

    :param device_id: 关联的设备 ID（用于日志和异常）
    :param on_fault_activated: 故障激活时的回调，签名为
        ``callback(fault_config: FaultConfig) -> None``
    :param on_fault_deactivated: 故障解除时的回调
    """

    def __init__(
        self,
        device_id: str = "",
        on_fault_activated: Callable[[FaultConfig], None] | None = None,
        on_fault_deactivated: Callable[[FaultConfig], None] | None = None,
    ):
        self._device_id = device_id
        self._faults: dict[str, _FaultRuntime] = {}
        self._on_activated = on_fault_activated
        self._on_deactivated = on_fault_deactivated
        self._lock = threading.RLock()

    # -- 故障管理 ---------------------------------------------------------

    def add_fault(self, config: FaultConfig) -> str:
        """添加故障配置。

        :param config: 故障配置
        :return: 故障 ID
        """
        with self._lock:
            rt = _FaultRuntime(config=config)
            self._faults[config.fault_id] = rt
            logger.info(
                "Fault added: id=%s, type=%s, target=%s, device=%s",
                config.fault_id, config.fault_type.value, config.target_point, self._device_id,
            )

            # SCHEDULED 模式：检查是否应该立即激活
            if config.trigger_mode == TriggerMode.SCHEDULED and config.start_time:
                if time.time() >= config.start_time:
                    self._activate(rt)

            return config.fault_id

    def remove_fault(self, fault_id: str) -> bool:
        """移除故障配置。

        :param fault_id: 故障 ID
        :return: 是否成功移除
        """
        with self._lock:
            rt = self._faults.pop(fault_id, None)
            if rt is None:
                return False
            if rt.active:
                self._deactivate(rt)
            logger.info("Fault removed: id=%s, device=%s", fault_id, self._device_id)
            return True

    def activate_fault(self, fault_id: str) -> bool:
        """激活故障。

        :param fault_id: 故障 ID
        :return: 是否成功激活
        """
        with self._lock:
            rt = self._faults.get(fault_id)
            if rt is None:
                return False
            if rt.active:
                return True
            self._activate(rt)
            return True

    def deactivate_fault(self, fault_id: str) -> bool:
        """停用故障。

        :param fault_id: 故障 ID
        :return: 是否成功停用
        """
        with self._lock:
            rt = self._faults.get(fault_id)
            if rt is None:
                return False
            if not rt.active:
                return True
            self._deactivate(rt)
            return True

    def clear_all_faults(self) -> int:
        """清除所有故障。

        :return: 清除的故障数量
        """
        with self._lock:
            count = len(self._faults)
            for rt in self._faults.values():
                if rt.active:
                    self._deactivate(rt)
            self._faults.clear()
            logger.info("All faults cleared: count=%d, device=%s", count, self._device_id)
            return count

    def get_active_faults(self) -> list[FaultConfig]:
        """返回当前活跃的故障配置列表。"""
        with self._lock:
            return [rt.config for rt in self._faults.values() if rt.active]

    def get_all_faults(self) -> list[FaultConfig]:
        """返回所有故障配置列表。"""
        with self._lock:
            return [rt.config for rt in self._faults.values()]

    def get_fault(self, fault_id: str) -> FaultConfig | None:
        """返回指定故障配置。"""
        with self._lock:
            rt = self._faults.get(fault_id)
            return rt.config if rt else None

    # -- 内部激活/停用 ----------------------------------------------------

    def _activate(self, rt: _FaultRuntime) -> None:
        """激活故障（内部方法，调用者需持锁）。"""
        rt.active = True
        rt.activated_at = time.time()
        rt.drift_start = time.time()
        rt.stuck_value_set = False
        rt.call_count = 0
        logger.info(
            "Fault activated: id=%s, type=%s, target=%s, device=%s",
            rt.config.fault_id, rt.config.fault_type.value,
            rt.config.target_point, self._device_id,
        )
        if self._on_activated:
            try:
                self._on_activated(rt.config)
            except Exception as e:
                logger.error("Fault activated callback error: %s", e)

    def _deactivate(self, rt: _FaultRuntime) -> None:
        """停用故障（内部方法，调用者需持锁）。"""
        rt.active = False
        rt.deactivated_at = time.time()
        logger.info(
            "Fault deactivated: id=%s, type=%s, device=%s",
            rt.config.fault_id, rt.config.fault_type.value, self._device_id,
        )
        if self._on_deactivated:
            try:
                self._on_deactivated(rt.config)
            except Exception as e:
                logger.error("Fault deactivated callback error: %s", e)

    def _check_auto_triggers(self, rt: _FaultRuntime, value: Any) -> None:
        """检查自动触发条件（RANDOM / CONDITIONAL 模式）。"""
        if rt.active:
            return
        cfg = rt.config
        if cfg.trigger_mode == TriggerMode.RANDOM and cfg.probability > 0:
            if random.random() < cfg.probability:
                self._activate(rt)
        elif cfg.trigger_mode == TriggerMode.CONDITIONAL and cfg.condition is not None:
            try:
                if cfg.condition(value):
                    self._activate(rt)
            except Exception as e:
                logger.warning("Fault condition callback error: %s", e)
        elif cfg.trigger_mode == TriggerMode.SCHEDULED and cfg.start_time and time.time() >= cfg.start_time:
            self._activate(rt)

    def _check_expiry(self, rt: _FaultRuntime) -> None:
        """检查故障是否过期。"""
        if rt.is_expired:
            self._deactivate(rt)

    # -- 核心方法：应用故障效果 ---------------------------------------------

    def apply(self, point_name: str, value: Any) -> tuple[Any, bool]:
        """对数据值应用故障效果。

        遍历所有匹配的活跃故障，依次应用故障效果。
        如果多个故障同时作用于同一点位，效果叠加（DEVICE_FAILURE 优先）。

        :param point_name: 点位名称
        :param value: 原始数据值
        :return: (修改后的值, 是否被故障影响) 元组。
                 修改后的值可能为 None（表示通信断连/丢包）。
                 如果 DEVICE_FAILURE 被激活，抛出 DeviceFailureException。
        """
        with self._lock:
            is_faulty = False
            modified_value = value

            # 收集匹配此点位的所有故障
            matching_rts = []
            for rt in self._faults.values():
                cfg = rt.config
                # 检查点位是否匹配
                if cfg.target_point != "*" and cfg.target_point != point_name:
                    continue
                # 检查自动触发
                self._check_auto_triggers(rt, value)
                # 检查过期
                self._check_expiry(rt)
                if rt.active:
                    matching_rts.append(rt)

            if not matching_rts:
                return value, False

            # DEVICE_FAILURE 优先处理
            for rt in matching_rts:
                if rt.config.fault_type == FaultType.DEVICE_FAILURE:
                    raise DeviceFailureException(
                        device_id=self._device_id,
                        point_name=point_name,
                        reason=f"Fault {rt.config.fault_id}: {rt.config.description or 'device failure'}",
                    )

            # 依次应用其他故障效果
            for rt in matching_rts:
                rt.call_count += 1
                modified_value, was_applied = self._apply_single(rt, point_name, modified_value)
                if was_applied:
                    is_faulty = True

            return modified_value, is_faulty

    def _apply_single(self, rt: _FaultRuntime, point_name: str, value: Any) -> tuple[Any, bool]:
        """应用单个故障效果。

        :return: (修改后的值, 是否应用了故障效果)
        """
        ft = rt.config.fault_type
        params = rt.config.parameters

        try:
            if ft == FaultType.SENSOR_STUCK:
                return self._apply_stuck(rt, value), True

            elif ft == FaultType.SENSOR_DRIFT:
                return self._apply_drift(rt, value, params), True

            elif ft == FaultType.SENSOR_NOISE:
                return self._apply_noise(rt, value, params), True

            elif ft == FaultType.COMM_INTERMITTENT:
                return self._apply_intermittent(rt, value, params)

            elif ft == FaultType.COMM_DELAY:
                return self._apply_delay(rt, value, params)

            elif ft == FaultType.COMM_LOSS:
                return self._apply_loss(rt, value, params)

            elif ft == FaultType.DATA_CORRUPTION:
                return self._apply_corruption(rt, value, params)

            else:
                return value, False

        except Exception as e:
            logger.warning("Fault apply error (type=%s, id=%s): %s", ft.value, rt.config.fault_id, e)
            return value, False

    # -- 各故障类型的具体实现 -----------------------------------------------

    @staticmethod
    def _apply_stuck(rt: _FaultRuntime, value: Any) -> Any:
        """SENSOR_STUCK：传感器卡死，保持第一次的值。"""
        if not rt.stuck_value_set:
            rt.stuck_value = value
            rt.stuck_value_set = True
        return rt.stuck_value

    @staticmethod
    def _apply_drift(rt: _FaultRuntime, value: Any, params: dict[str, Any]) -> Any:
        """SENSOR_DRIFT：传感器漂移，value + drift_rate * elapsed_time。"""
        drift_rate = params.get("drift_rate", 0.1)
        elapsed = time.time() - rt.drift_start
        if isinstance(value, (int, float)):
            return value + drift_rate * elapsed
        return value

    @staticmethod
    def _apply_noise(rt: _FaultRuntime, value: Any, params: dict[str, Any]) -> Any:
        """SENSOR_NOISE：噪声增大，叠加高斯噪声。"""
        noise_std = params.get("noise_std", 1.0)
        if isinstance(value, (int, float)):
            return value + random.gauss(0, noise_std)
        return value

    @staticmethod
    def _apply_intermittent(rt: _FaultRuntime, value: Any, params: dict[str, Any]) -> tuple[Any, bool]:
        """COMM_INTERMITTENT：间歇性断连，按概率返回 None。"""
        probability = params.get("probability", 0.3)
        if random.random() < probability:
            return None, True
        return value, True

    @staticmethod
    def _apply_delay(rt: _FaultRuntime, value: Any, params: dict[str, Any]) -> tuple[Any, bool]:
        """COMM_DELAY：通信延迟增大。"""
        delay_ms = params.get("delay_ms", 100)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        return value, True

    @staticmethod
    def _apply_loss(rt: _FaultRuntime, value: Any, params: dict[str, Any]) -> tuple[Any, bool]:
        """COMM_LOSS：数据丢包，按概率丢弃数据包（返回 None）。"""
        probability = params.get("probability", 0.2)
        if random.random() < probability:
            return None, True
        return value, True

    @staticmethod
    def _apply_corruption(rt: _FaultRuntime, value: Any, params: dict[str, Any]) -> tuple[Any, bool]:
        """DATA_CORRUPTION：数据篡改/损坏，按位翻转或数值偏移。"""
        corruption_rate = params.get("corruption_rate", 0.5)
        if random.random() > corruption_rate:
            return value, True

        mode = params.get("mode", "offset")

        if mode == "bit_flip" and isinstance(value, (int, float)):
            # 将数值转为字节，翻转随机一位
            try:
                if isinstance(value, int):
                    packed = struct.pack(">i", int(value))
                    byte_arr = bytearray(packed)
                    bit_pos = random.randint(0, 31)
                    byte_idx = bit_pos // 8
                    bit_idx = bit_pos % 8
                    byte_arr[byte_idx] ^= (1 << bit_idx)
                    return struct.unpack(">i", bytes(byte_arr))[0], True
                elif isinstance(value, float):
                    packed = struct.pack(">d", float(value))
                    byte_arr = bytearray(packed)
                    bit_pos = random.randint(0, 63)
                    byte_idx = bit_pos // 8
                    bit_idx = bit_pos % 8
                    byte_arr[byte_idx] ^= (1 << bit_idx)
                    return struct.unpack(">d", bytes(byte_arr))[0], True
            except (struct.error, IndexError):
                pass

        elif mode == "offset" and isinstance(value, (int, float)):
            offset_value = params.get("offset_value", 10.0)
            return value + offset_value, True

        return value, True

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """序列化故障注入器状态为字典。"""
        with self._lock:
            faults_list = []
            for rt in self._faults.values():
                d = rt.config.to_dict()
                d["active"] = rt.active
                d["elapsed"] = round(rt.elapsed, 3)
                faults_list.append(d)
            return {
                "device_id": self._device_id,
                "faults": faults_list,
                "active_count": sum(1 for rt in self._faults.values() if rt.active),
                "total_count": len(self._faults),
            }


# ---------------------------------------------------------------------------
#  故障传播链
# ---------------------------------------------------------------------------

@dataclass
class PropagationRule:
    """故障传播规则。

    定义故障从源设备传播到目标设备的规则。

    :param source_device: 源设备 ID
    :param target_device: 目标设备 ID
    :param target_point: 目标点位名称
    :param fault_type: 传播后在目标设备上产生的故障类型
    :param delay: 传播延迟 (s)
    :param attenuation: 衰减系数 (0~1)，影响目标故障的强度
    :param parameters: 传播后的故障参数（会被 attenuation 调整）
    :param description: 传播规则描述
    """

    source_device: str
    target_device: str
    target_point: str = "*"
    fault_type: FaultType = FaultType.SENSOR_DRIFT
    delay: float = 0.0
    attenuation: float = 1.0
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_device": self.source_device,
            "target_device": self.target_device,
            "target_point": self.target_point,
            "fault_type": self.fault_type.value,
            "delay": self.delay,
            "attenuation": self.attenuation,
            "parameters": self.parameters,
            "description": self.description,
        }


class FaultPropagation:
    """故障传播链管理器。

    当源设备发生故障时，根据传播规则在目标设备上注入衍生故障，
    模拟工业系统中的级联故障效应。

    示例：泵故障 → 流量下降 → 液位异常

    :param rules: 传播规则列表
    :param injectors: 设备 ID → FaultInjector 的映射，用于在目标设备上注入故障
    """

    def __init__(
        self,
        injectors: dict[str, FaultInjector] | None = None,
    ):
        self._rules: list[PropagationRule] = []
        self._injectors: dict[str, FaultInjector] = injectors or {}
        self._pending: deque[dict[str, Any]] = deque()  # 待执行的传播任务
        self._lock = threading.RLock()

    def add_rule(self, rule: PropagationRule) -> None:
        """添加传播规则。"""
        with self._lock:
            self._rules.append(rule)
            logger.info(
                "Propagation rule added: %s → %s (%s → %s)",
                rule.source_device, rule.target_device,
                "fault", rule.fault_type.value,
            )

    def set_injector(self, device_id: str, injector: FaultInjector) -> None:
        """注册设备故障注入器。"""
        with self._lock:
            self._injectors[device_id] = injector

    def on_fault_activated(self, fault_config: FaultConfig, source_device_id: str) -> None:
        """故障激活回调：检查并触发传播规则。

        应注册为源设备 FaultInjector 的 on_fault_activated 回调。

        :param fault_config: 被激活的故障配置
        :param source_device_id: 源设备 ID
        """
        with self._lock:
            for rule in self._rules:
                if rule.source_device != source_device_id:
                    continue
                # 创建衍生故障配置
                propagated_params = dict(rule.parameters)
                # 应用衰减系数到数值参数
                for key in ("drift_rate", "noise_std", "offset_value"):
                    if key in propagated_params:
                        propagated_params[key] *= rule.attenuation
                for key in ("probability", "corruption_rate"):
                    if key in propagated_params:
                        propagated_params[key] = min(1.0, propagated_params[key] * rule.attenuation)

                propagated_config = FaultConfig(
                    fault_type=rule.fault_type,
                    target_point=rule.target_point,
                    trigger_mode=TriggerMode.MANUAL,
                    parameters=propagated_params,
                    target_device=rule.target_device,
                    description=f"Propagated from {source_device_id}: {rule.description}",
                )

                # 延迟执行
                if rule.delay > 0:
                    self._pending.append({
                        "config": propagated_config,
                        "target_device": rule.target_device,
                        "execute_at": time.time() + rule.delay,
                    })
                    logger.info(
                        "Propagation scheduled: %s → %s, delay=%.1fs",
                        source_device_id, rule.target_device, rule.delay,
                    )
                else:
                    self._inject_fault(rule.target_device, propagated_config)

    def tick(self) -> None:
        """处理待执行的传播任务（应在引擎 tick 循环中调用）。"""
        with self._lock:
            now = time.time()
            remaining = deque()
            while self._pending:
                task = self._pending.popleft()
                if now >= task["execute_at"]:
                    self._inject_fault(task["target_device"], task["config"])
                else:
                    remaining.append(task)
            self._pending = remaining

    def _inject_fault(self, device_id: str, config: FaultConfig) -> None:
        """在目标设备上注入故障。"""
        injector = self._injectors.get(device_id)
        if injector is None:
            logger.warning("No injector found for device %s, cannot propagate fault", device_id)
            return
        fid = injector.add_fault(config)
        injector.activate_fault(fid)
        logger.info(
            "Fault propagated to device %s: fault_id=%s, type=%s",
            device_id, fid, config.fault_type.value,
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化传播链状态为字典。"""
        with self._lock:
            return {
                "rules": [r.to_dict() for r in self._rules],
                "pending_count": len(self._pending),
                "registered_devices": list(self._injectors.keys()),
            }


# ---------------------------------------------------------------------------
#  故障场景
# ---------------------------------------------------------------------------

@dataclass
class TimelineEvent:
    """故障场景时间线事件。

    :param time: 事件触发时间 (s)，相对于场景启动
    :param action: 动作类型 ("activate" | "deactivate" | "add" | "remove")
    :param fault_config: 故障配置（add/activate 时需要）
    :param fault_id: 故障 ID（deactivate/remove 时需要）
    :param description: 事件描述
    """

    time: float
    action: str  # "activate" | "deactivate" | "add" | "remove"
    fault_config: FaultConfig | None = None
    fault_id: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "time": self.time,
            "action": self.action,
            "fault_id": self.fault_id,
            "description": self.description,
        }
        if self.fault_config:
            d["fault_config"] = self.fault_config.to_dict()
        return d


class FaultScenario:
    """故障场景编排器。

    组合多个故障配置，按时间线编排故障的激活和解除。

    典型用法::

        scenario = FaultScenario("pump_failure_test", injector)
        scenario.add_timeline_event(0, "add", config=drift_fault)
        scenario.add_timeline_event(5, "activate", fault_id=drift_fault.fault_id)
        scenario.add_timeline_event(30, "deactivate", fault_id=drift_fault.fault_id)
        scenario.start()
        # ... 运行 35 秒后 ...
        scenario.stop()

    :param scenario_id: 场景 ID
    :param injector: 故障注入器实例
    :param name: 场景名称
    :param description: 场景描述
    """

    def __init__(
        self,
        scenario_id: str,
        injector: FaultInjector,
        name: str = "",
        description: str = "",
    ):
        self.scenario_id = scenario_id
        self.injector = injector
        self.name = name or scenario_id
        self.description = description

        self._timeline: list[TimelineEvent] = []
        self._started: bool = False
        self._start_time: float = 0.0
        self._executed_indices: set[int] = set()
        self._added_fault_ids: list[str] = []
        self._lock = threading.RLock()

    def add_timeline_event(
        self,
        time_offset: float,
        action: str,
        config: FaultConfig | None = None,
        fault_id: str = "",
        description: str = "",
    ) -> int:
        """添加时间线事件。

        :param time_offset: 事件触发时间 (s)，相对于场景启动
        :param action: 动作类型 ("activate" | "deactivate" | "add" | "remove")
        :param config: 故障配置（add/activate 时需要）
        :param fault_id: 故障 ID（deactivate/remove 时需要）
        :param description: 事件描述
        :return: 事件索引
        """
        with self._lock:
            event = TimelineEvent(
                time=time_offset,
                action=action,
                fault_config=config,
                fault_id=fault_id,
                description=description,
            )
            self._timeline.append(event)
            # 保持按时间排序
            self._timeline.sort(key=lambda e: e.time)
            return self._timeline.index(event)

    def start(self) -> None:
        """启动故障场景。"""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._start_time = time.time()
            self._executed_indices.clear()
            self._added_fault_ids.clear()
            logger.info("Fault scenario started: %s (%s)", self.scenario_id, self.name)

    def stop(self) -> None:
        """停止故障场景，清理所有由场景添加的故障。"""
        with self._lock:
            if not self._started:
                return
            self._started = False
            # 清理场景添加的故障
            for fid in self._added_fault_ids:
                self.injector.remove_fault(fid)
            self._added_fault_ids.clear()
            logger.info("Fault scenario stopped: %s (%s)", self.scenario_id, self.name)

    def tick(self) -> None:
        """处理时间线事件（应在引擎 tick 循环中调用）。"""
        with self._lock:
            if not self._started:
                return
            elapsed = time.time() - self._start_time
            for i, event in enumerate(self._timeline):
                if i in self._executed_indices:
                    continue
                if elapsed >= event.time:
                    self._execute_event(event)
                    self._executed_indices.add(i)

    def _execute_event(self, event: TimelineEvent) -> None:
        """执行单个时间线事件。"""
        action = event.action
        try:
            if action == "add" and event.fault_config:
                fid = self.injector.add_fault(event.fault_config)
                self._added_fault_ids.append(fid)
                logger.info("Scenario %s: fault added at t=%.1f: %s", self.scenario_id, event.time, fid)
            elif action == "activate":
                if event.fault_config:
                    # 先确保故障已添加
                    if event.fault_config.fault_id not in [f.fault_id for f in self.injector.get_all_faults()]:
                        fid = self.injector.add_fault(event.fault_config)
                        self._added_fault_ids.append(fid)
                    else:
                        fid = event.fault_config.fault_id
                else:
                    fid = event.fault_id
                self.injector.activate_fault(fid)
                logger.info("Scenario %s: fault activated at t=%.1f: %s", self.scenario_id, event.time, fid)
            elif action == "deactivate":
                self.injector.deactivate_fault(event.fault_id)
                logger.info("Scenario %s: fault deactivated at t=%.1f: %s", self.scenario_id, event.time, event.fault_id)
            elif action == "remove":
                self.injector.remove_fault(event.fault_id)
                if event.fault_id in self._added_fault_ids:
                    self._added_fault_ids.remove(event.fault_id)
                logger.info("Scenario %s: fault removed at t=%.1f: %s", self.scenario_id, event.time, event.fault_id)
        except Exception as e:
            logger.error("Scenario %s: event execution error: %s", self.scenario_id, e)

    def get_timeline(self) -> list[dict[str, Any]]:
        """返回时间线事件列表。"""
        with self._lock:
            elapsed = time.time() - self._start_time if self._started else 0
            return [
                {
                    **e.to_dict(),
                    "executed": i in self._executed_indices,
                    "elapsed": elapsed,
                }
                for i, e in enumerate(self._timeline)
            ]

    @property
    def is_running(self) -> bool:
        """场景是否正在运行。"""
        return self._started

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """序列化场景为字典。"""
        with self._lock:
            return {
                "scenario_id": self.scenario_id,
                "name": self.name,
                "description": self.description,
                "is_running": self._started,
                "timeline": [e.to_dict() for e in self._timeline],
            }

    def to_json(self) -> str:
        """序列化场景为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any], injector: FaultInjector) -> FaultScenario:
        """从字典反序列化场景。"""
        scenario = cls(
            scenario_id=data.get("scenario_id", ""),
            injector=injector,
            name=data.get("name", ""),
            description=data.get("description", ""),
        )
        for e_data in data.get("timeline", []):
            config = None
            if e_data.get("fault_config"):
                config = FaultConfig.from_dict(e_data["fault_config"])
            scenario.add_timeline_event(
                time_offset=e_data.get("time", 0),
                action=e_data.get("action", "add"),
                config=config,
                fault_id=e_data.get("fault_id", ""),
                description=e_data.get("description", ""),
            )
        return scenario

    @classmethod
    def from_json(cls, json_str: str, injector: FaultInjector) -> FaultScenario:
        """从 JSON 字符串反序列化场景。"""
        return cls.from_dict(json.loads(json_str), injector)
