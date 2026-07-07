"""故障注入器。

管理故障实例，对数据值应用故障效果，检测通信故障。

核心方法:
  - ``apply(point_name, value)``: 对数据值应用故障效果，返回 (修改后的值, 质量标记)
  - ``check_comm_fault(device_id)``: 检查通信故障，返回 (是否断连, 延迟毫秒)

质量标记遵循 OPC UA 规范:
  - "good":       无故障
  - "uncertain":  轻微/中等故障 (SENSOR_STUCK, SENSOR_DRIFT, SENSOR_NOISE)
  - "bad":        严重/致命故障 (SENSOR_FAILURE, DEVICE_FAILURE)

线程安全，支持并发调用。
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import Any

from protoforge.core.fault.models import Fault, FaultSeverity, FaultType
from protoforge.core.fault_injection import (
    FaultConfig,
    TriggerMode,
)

logger = logging.getLogger(__name__)


class FaultInjector:
    """故障注入器。

    管理多个故障实例，对数据值应用故障效果。

    :param device_id: 关联的设备 ID（用于日志和通信故障检查）
    :param on_fault_activated: 故障激活时的回调，签名为
        ``callback(fault: Fault) -> None``
    :param on_fault_deactivated: 故障解除时的回调
    """

    def __init__(
        self,
        device_id: str = "",
        on_fault_activated: Callable[[Fault], None] | None = None,
        on_fault_deactivated: Callable[[Fault], None] | None = None,
    ):
        self._device_id = device_id
        self._on_activated = on_fault_activated
        self._on_deactivated = on_fault_deactivated
        self.active_faults: list[Fault] = []
        self.fault_history: list[Fault] = []
        self._lock = threading.RLock()

    # -- 故障管理 ---------------------------------------------------------

    def add_fault(self, fault: Fault | FaultConfig) -> str:
        """添加故障。

        兼容 ``Fault`` 和旧版 ``FaultConfig`` 两种参数类型。

        :param fault: 故障实例 (Fault) 或旧版故障配置 (FaultConfig)
        :return: 故障 ID
        """
        # 如果传入的是旧版 FaultConfig，转换为 Fault
        if isinstance(fault, FaultConfig):
            fault = self._convert_config_to_fault(fault)
        with self._lock:
            # 如果 start_time 为 0，设为当前时间
            if fault.start_time == 0.0:
                fault.start_time = time.time()
            self.active_faults.append(fault)
            logger.info(
                "Fault added: id=%s, type=%s, target=%s, device=%s",
                fault.fault_id, fault.fault_type.value, fault.target, self._device_id,
            )
            if fault.active and self._on_activated:
                try:
                    self._on_activated(fault)
                except Exception as e:
                    logger.error("Fault activated callback error: %s", e)
            return fault.fault_id

    def remove_fault(self, fault_id: str) -> bool:
        """移除故障。

        :param fault_id: 故障 ID
        :return: 是否成功移除
        """
        with self._lock:
            for i, f in enumerate(self.active_faults):
                if f.fault_id == fault_id:
                    f.active = False
                    self.fault_history.append(f)
                    self.active_faults.pop(i)
                    logger.info("Fault removed: id=%s, device=%s", fault_id, self._device_id)
                    if self._on_deactivated:
                        try:
                            self._on_deactivated(f)
                        except Exception as e:
                            logger.error("Fault deactivated callback error: %s", e)
                    return True
            return False

    def clear_faults(self, target: str | None = None) -> int:
        """清除故障。

        :param target: 目标标识 (device_id 或 point_name)，None 表示清除所有
        :return: 清除的故障数量
        """
        with self._lock:
            if target is None:
                count = len(self.active_faults)
                for f in self.active_faults:
                    f.active = False
                    self.fault_history.append(f)
                    if self._on_deactivated:
                        try:
                            self._on_deactivated(f)
                        except Exception as e:
                            logger.error("Fault deactivated callback error: %s", e)
                self.active_faults.clear()
            else:
                to_remove = [f for f in self.active_faults if f.target == target or f.target == "*"]
                for f in to_remove:
                    f.active = False
                    self.fault_history.append(f)
                    self.active_faults.remove(f)
                    if self._on_deactivated:
                        try:
                            self._on_deactivated(f)
                        except Exception as e:
                            logger.error("Fault deactivated callback error: %s", e)
                count = len(to_remove)
            logger.info("Faults cleared: count=%d, device=%s", count, self._device_id)
            return count

    def list_faults(self, target: str | None = None) -> list[Fault]:
        """列出故障。

        :param target: 目标标识过滤，None 表示返回所有
        :return: 故障列表
        """
        with self._lock:
            if target is None:
                return list(self.active_faults)
            return [f for f in self.active_faults if f.target == target or f.target == "*"]

    # -- 向后兼容方法 (FaultConfig API) ------------------------------------

    @staticmethod
    def _convert_config_to_fault(config: FaultConfig) -> Fault:
        """将旧版 FaultConfig 转换为 Fault。"""
        severity = FaultSeverity.MEDIUM
        if config.fault_type in (FaultType.DEVICE_FAILURE, FaultType.SENSOR_FAILURE):
            severity = FaultSeverity.CRITICAL

        return Fault(
            fault_id=config.fault_id,
            fault_type=config.fault_type,
            target=config.target_point,
            start_time=config.start_time or 0.0,
            duration=config.parameters.get("duration", -1.0),
            severity=severity,
            parameters=config.parameters,
        )

    def activate_fault(self, fault_id: str) -> bool:
        """激活故障（向后兼容）。"""
        with self._lock:
            for f in self.active_faults:
                if f.fault_id == fault_id:
                    if not f.active:
                        f.active = True
                        if self._on_activated:
                            try:
                                self._on_activated(f)
                            except Exception as e:
                                logger.error("Fault activated callback error: %s", e)
                    return True
            return False

    def deactivate_fault(self, fault_id: str) -> bool:
        """停用故障（向后兼容）。"""
        with self._lock:
            for f in self.active_faults:
                if f.fault_id == fault_id:
                    f.active = False
                    if self._on_deactivated:
                        try:
                            self._on_deactivated(f)
                        except Exception as e:
                            logger.error("Fault deactivated callback error: %s", e)
                    return True
            return False

    def clear_all_faults(self) -> int:
        """清除所有故障（向后兼容）。"""
        return self.clear_faults(None)

    def get_active_faults(self) -> list[FaultConfig]:
        """返回活跃故障列表（向后兼容，返回 FaultConfig 列表）。"""
        with self._lock:
            return [self._convert_fault_to_config(f) for f in self.active_faults if f.active]

    def get_all_faults(self) -> list[FaultConfig]:
        """返回所有故障列表（向后兼容，返回 FaultConfig 列表）。"""
        with self._lock:
            return [self._convert_fault_to_config(f) for f in self.active_faults]

    @staticmethod
    def _convert_fault_to_config(fault: Fault) -> FaultConfig:
        """将 Fault 转换为旧版 FaultConfig。"""
        return FaultConfig(
            fault_type=fault.fault_type,
            target_point=fault.target,
            trigger_mode=TriggerMode.MANUAL,
            parameters=fault.parameters,
            fault_id=fault.fault_id,
            description=f"severity={fault.severity.value}",
        )

    # -- 核心方法：应用故障效果 ---------------------------------------------

    def apply(self, point_name: str, value: Any) -> tuple[Any, str]:
        """对数据值应用故障效果。

        遍历所有匹配的活跃故障，依次应用故障效果。
        多个故障同时作用时，质量标记取最严重的一个。

        :param point_name: 点位名称
        :param value: 原始数据值
        :return: (修改后的值, 质量标记) 元组。
                 质量标记: "good" / "uncertain" / "bad"
                 修改后的值可能为 None（表示通信断连/丢包/传感器失效）。
        """
        with self._lock:
            now = time.time()
            modified_value = value
            worst_quality = "good"

            # 收集匹配此点位的活跃故障
            matching_faults = []
            for f in self.active_faults:
                # 检查目标匹配
                if f.target != "*" and f.target != point_name:
                    continue
                # 检查是否过期
                if f.is_expired(now):
                    self._deactivate_fault(f)
                    continue
                # 检查是否到达开始时间
                if not f.is_active_now(now):
                    continue
                matching_faults.append(f)

            if not matching_faults:
                return value, "good"

            # 依次应用故障效果
            for fault in matching_faults:
                modified_value, quality = self._apply_single(fault, point_name, modified_value, now)
                # 取最严重的质量标记
                if quality == "bad":
                    worst_quality = "bad"
                elif quality == "uncertain" and worst_quality != "bad":
                    worst_quality = "uncertain"

            return modified_value, worst_quality

    def _apply_single(self, fault: Fault, point_name: str, value: Any, now: float) -> tuple[Any, str]:
        """应用单个故障效果。

        :return: (修改后的值, 质量标记)
        """
        ft = fault.fault_type
        params = fault.parameters
        quality = fault.quality_degradation

        try:
            if ft == FaultType.SENSOR_STUCK:
                return self._apply_stuck(fault, value), quality

            elif ft == FaultType.SENSOR_DRIFT:
                return self._apply_drift(fault, value, params), quality

            elif ft == FaultType.SENSOR_NOISE:
                return self._apply_noise(fault, value, params), quality

            elif ft == FaultType.SENSOR_FAILURE:
                return self._apply_failure(fault, value, params), "bad"

            elif ft == FaultType.COMM_INTERMITTENT:
                return self._apply_intermittent(fault, value, params), quality

            elif ft == FaultType.COMM_DELAY:
                # 通信延迟在 check_comm_fault 中处理，此处不阻塞
                return value, quality

            elif ft == FaultType.COMM_LOSS:
                return self._apply_loss(fault, value, params), quality

            elif ft == FaultType.DEVICE_FAILURE:
                # 设备故障在 check_device_fault 中处理
                return value, "bad"

            elif ft == FaultType.ACTUATOR_STUCK:
                # 执行器卡死影响写操作，读操作返回卡死值
                stuck_val = params.get("stuck_value", fault.last_value)
                if stuck_val is not None:
                    return stuck_val, quality
                return value, quality

            else:
                return value, "good"

        except Exception as e:
            logger.warning("Fault apply error (type=%s, id=%s): %s", ft.value, fault.fault_id, e)
            return value, "good"

    # -- 各故障类型的具体实现 -----------------------------------------------

    @staticmethod
    def _apply_stuck(fault: Fault, value: Any) -> Any:
        """SENSOR_STUCK：传感器卡死，保持第一次的值或指定值。"""
        stuck_val = fault.parameters.get("stuck_value")
        if stuck_val is not None:
            return stuck_val
        if fault.last_value is None:
            fault.last_value = value
        return fault.last_value

    @staticmethod
    def _apply_drift(fault: Fault, value: Any, params: dict[str, Any]) -> Any:
        """SENSOR_DRIFT：传感器漂移，值随时间线性偏移。"""
        drift_rate = params.get("drift_rate", 0.1)
        dt = params.get("dt", 0.1)
        fault.drift_accumulated += drift_rate * dt
        if isinstance(value, (int, float)):
            return value + fault.drift_accumulated
        return value

    @staticmethod
    def _apply_noise(fault: Fault, value: Any, params: dict[str, Any]) -> Any:
        """SENSOR_NOISE：噪声增大，叠加高斯噪声。"""
        noise_level = params.get("noise_level", params.get("noise_std", 1.0))
        if isinstance(value, (int, float)):
            return value + random.gauss(0, noise_level)
        return value

    @staticmethod
    def _apply_failure(fault: Fault, value: Any, params: dict[str, Any]) -> Any:
        """SENSOR_FAILURE：完全失效，返回超量程值或 None。"""
        failure_value = params.get("failure_value")
        if failure_value is not None:
            return failure_value
        return None

    @staticmethod
    def _apply_intermittent(fault: Fault, value: Any, params: dict[str, Any]) -> tuple[Any, str]:
        """COMM_INTERMITTENT：间歇性断连，按概率返回 None。"""
        probability = params.get("probability", 0.3)
        if random.random() < probability:
            return None, "uncertain"
        return value, "good"

    @staticmethod
    def _apply_loss(fault: Fault, value: Any, params: dict[str, Any]) -> tuple[Any, str]:
        """COMM_LOSS：数据丢包，按概率丢弃数据（返回 None）。"""
        probability = params.get("probability", 0.2)
        if random.random() < probability:
            return None, "uncertain"
        return value, "good"

    # -- 通信故障检查 ------------------------------------------------------

    def check_comm_fault(self, device_id: str) -> tuple[bool, float]:
        """检查通信故障。

        遍历所有活跃的通信故障（COMM_INTERMITTENT, COMM_DELAY, COMM_LOSS），
        返回综合通信状态。

        :param device_id: 设备 ID
        :return: (是否断连, 延迟毫秒) 元组。
                 断连为 True 时，延迟无意义。
        """
        with self._lock:
            now = time.time()
            is_disconnected = False
            total_delay_ms = 0.0

            for fault in self.active_faults:
                if not fault.is_active_now(now):
                    continue
                # 检查目标匹配（通信故障的 target 可以是 device_id 或 "*"）
                if fault.target != "*" and fault.target != device_id:
                    continue

                ft = fault.fault_type
                params = fault.parameters

                if ft == FaultType.COMM_INTERMITTENT:
                    probability = params.get("probability", 0.3)
                    if random.random() < probability:
                        is_disconnected = True

                elif ft == FaultType.COMM_DELAY:
                    delay_ms = params.get("delay_ms", 0)
                    total_delay_ms = max(total_delay_ms, delay_ms)

                elif ft == FaultType.COMM_LOSS:
                    probability = params.get("probability", 0.2)
                    if random.random() < probability:
                        is_disconnected = True

                elif ft == FaultType.DEVICE_FAILURE:
                    # 设备故障也导致通信断连
                    is_disconnected = True

            return is_disconnected, total_delay_ms

    def check_device_fault(self, device_id: str) -> bool:
        """检查是否存在设备级故障 (DEVICE_FAILURE)。

        :param device_id: 设备 ID
        :return: True 表示存在活跃的设备故障
        """
        with self._lock:
            now = time.time()
            for fault in self.active_faults:
                if fault.fault_type != FaultType.DEVICE_FAILURE:
                    continue
                if not fault.is_active_now(now):
                    continue
                if fault.target == "*" or fault.target == device_id:
                    return True
            return False

    # -- 内部方法 ---------------------------------------------------------

    def _deactivate_fault(self, fault: Fault) -> None:
        """停用过期故障（内部方法，调用者需持锁）。"""
        fault.active = False
        self.fault_history.append(fault)
        if fault in self.active_faults:
            self.active_faults.remove(fault)
        logger.info(
            "Fault expired: id=%s, type=%s, device=%s",
            fault.fault_id, fault.fault_type.value, self._device_id,
        )
        if self._on_deactivated:
            try:
                self._on_deactivated(fault)
            except Exception as e:
                logger.error("Fault deactivated callback error: %s", e)

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """序列化故障注入器状态为字典。"""
        with self._lock:
            return {
                "device_id": self._device_id,
                "active_faults": [f.to_dict() for f in self.active_faults],
                "fault_history_count": len(self.fault_history),
                "active_count": len(self.active_faults),
            }
