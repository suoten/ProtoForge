"""故障传播链管理。

当源点位值满足指定条件时，自动在目标点位上触发衍生故障，
模拟工业系统中的级联故障效应。

传播规则格式::

    {
        "source_point": "bearing_temp",    # 源点位名称
        "target_point": "vibration",       # 目标点位名称
        "condition": ">80",                # 触发条件（支持 >, <, >=, <=, ==, !=）
        "delay": 30,                       # 传播延迟 (s)
        "effect_type": "sensor_noise",     # 衍生故障类型
        "effect_params": {"noise_level": 5.0},  # 衍生故障参数
        "severity": "high",                # 衍生故障严重级别
    }

典型用法::

    propagation = FaultPropagation()
    propagation.add_rule(
        source="bearing_temp",
        target="vibration",
        condition=">80",
        delay=30,
        effect_type="sensor_noise",
        effect_params={"noise_level": 5.0},
    )
    # 在 tick 循环中检查传播
    triggers = propagation.check_propagation({"bearing_temp": 85.0})
    for t in triggers:
        injector.add_fault(Fault(**t))
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from protoforge.core.fault.models import Fault, FaultSeverity, FaultType

logger = logging.getLogger(__name__)

# 条件解析正则：匹配 ">=80", "> 80", "<= 0.5", "== 100" 等
_CONDITION_RE = re.compile(r"^\s*(>=|<=|==|!=|>|<)\s*(-?[\d.]+)\s*$")


class FaultPropagation:
    """故障传播链管理器。

    管理传播规则，检查源点位值是否满足触发条件，
    返回需要触发的衍生故障列表。

    线程安全，支持并发调用。
    """

    def __init__(self):
        self.propagation_rules: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        # 记录已触发的规则，避免重复触发（条件恢复后重置）
        self._triggered: dict[str, float] = {}  # rule_key -> triggered_time

    def add_rule(
        self,
        source: str,
        target: str,
        condition: str,
        delay: float = 0.0,
        effect_type: str = "sensor_noise",
        effect_params: dict[str, Any] | None = None,
        severity: str = "medium",
        duration: float = -1.0,
    ) -> int:
        """添加传播规则。

        :param source: 源点位名称
        :param target: 目标点位名称
        :param condition: 触发条件字符串，如 ">80", "<=0.5", "==100"
        :param delay: 传播延迟 (s)，0 表示立即触发
        :param effect_type: 衍生故障类型 (FaultType 枚举值字符串)
        :param effect_params: 衍生故障参数字典
        :param severity: 衍生故障严重级别 (FaultSeverity 枚举值字符串)
        :param duration: 衍生故障持续时间 (s)，-1 表示永久
        :return: 规则索引
        """
        rule = {
            "source_point": source,
            "target_point": target,
            "condition": condition,
            "delay": delay,
            "effect_type": effect_type,
            "effect_params": effect_params or {},
            "severity": severity,
            "duration": duration,
        }
        with self._lock:
            self.propagation_rules.append(rule)
            idx = len(self.propagation_rules) - 1
            logger.info(
                "Propagation rule added: %s → %s (condition=%s, effect=%s)",
                source, target, condition, effect_type,
            )
            return idx

    def remove_rule(self, index: int) -> bool:
        """移除传播规则。

        :param index: 规则索引
        :return: 是否成功移除
        """
        with self._lock:
            if 0 <= index < len(self.propagation_rules):
                self.propagation_rules.pop(index)
                return True
            return False

    def clear_rules(self) -> int:
        """清除所有传播规则。

        :return: 清除的规则数量
        """
        with self._lock:
            count = len(self.propagation_rules)
            self.propagation_rules.clear()
            self._triggered.clear()
            return count

    def check_propagation(self, point_values: dict[str, Any]) -> list[dict[str, Any]]:
        """检查是否有故障需要传播。

        遍历所有传播规则，检查源点位值是否满足触发条件。
        如果满足且该规则尚未触发（或已恢复后重新满足），则生成衍生故障。

        :param point_values: 当前所有点位值的字典 ``{point_name: value}``
        :return: 需要触发的故障列表，每个元素为可直接传给 ``Fault()`` 的关键字参数字典
        """
        results: list[dict[str, Any]] = []
        now = time.time()

        with self._lock:
            for i, rule in enumerate(self.propagation_rules):
                source = rule["source_point"]
                condition = rule["condition"]
                rule_key = f"{i}_{source}_{rule['target_point']}"

                # 获取源点位值
                source_value = point_values.get(source)
                if source_value is None:
                    continue

                # 检查条件
                if not self._check_condition(condition, source_value):
                    # 条件不满足，重置触发状态
                    self._triggered.pop(rule_key, None)
                    continue

                # 条件满足，检查是否已触发
                if rule_key in self._triggered:
                    continue  # 已触发，等待条件恢复后才能再次触发

                # 标记为已触发
                self._triggered[rule_key] = now

                # 构造衍生故障参数
                fault_params: dict[str, Any] = {
                    "fault_type": FaultType(rule["effect_type"]),
                    "target": rule["target_point"],
                    "severity": FaultSeverity(rule["severity"]),
                    "parameters": dict(rule["effect_params"]),
                    "duration": rule["duration"],
                }

                # 处理延迟
                delay = rule.get("delay", 0.0)
                if delay > 0:
                    fault_params["start_time"] = now + delay
                    logger.info(
                        "Propagation scheduled: %s → %s, delay=%.1fs",
                        source, rule["target_point"], delay,
                    )
                else:
                    fault_params["start_time"] = now
                    logger.info(
                        "Propagation triggered: %s → %s (condition %s %s met)",
                        source, rule["target_point"], condition, source_value,
                    )

                results.append(fault_params)

        return results

    @staticmethod
    def _check_condition(condition: str, value: Any) -> bool:
        """检查条件是否满足。

        :param condition: 条件字符串，如 ">80", "<=0.5"
        :param value: 待检查的值
        :return: True 表示条件满足
        """
        match = _CONDITION_RE.match(condition)
        if not match:
            logger.warning("Invalid condition format: %s", condition)
            return False

        op_str = match.group(1)
        threshold = float(match.group(2))

        try:
            val = float(value)
        except (ValueError, TypeError):
            return False

        if op_str == ">":
            return val > threshold
        elif op_str == ">=":
            return val >= threshold
        elif op_str == "<":
            return val < threshold
        elif op_str == "<=":
            return val <= threshold
        elif op_str == "==":
            return abs(val - threshold) < 1e-9
        elif op_str == "!=":
            return abs(val - threshold) >= 1e-9
        return False

    def to_dict(self) -> dict[str, Any]:
        """序列化传播链状态为字典。"""
        with self._lock:
            return {
                "rules": list(self.propagation_rules),
                "triggered_count": len(self._triggered),
                "rule_count": len(self.propagation_rules),
            }
