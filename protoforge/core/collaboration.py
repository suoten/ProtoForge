"""多设备协同联动引擎（Device Collaboration）.

实现设备间的链式联动——"真正的仿真"关键能力。典型场景：

    温度传感器 > 80°C → 触发风扇（set speed=100）→ 风扇转速反馈到主设备
    压力 < 1.0MPa   → 触发报警灯（toggle）→ 报警灯状态联动到 SCADA

核心概念:
    - ``CollaborationRule``: 源设备点位满足条件时，触发一组链式动作
    - ``CollaborationAction``: 对目标设备点位的操作（set/toggle/increment/decrement/delay）
    - ``DeviceCollaboration``: 引擎，评估规则并触发动作链；支持 cooldown 抑制重复触发

设计要点:
    - 与 DeviceInstance 解耦：通过 ``on_write_point`` / ``on_read_point`` 回调交互，
      便于单测（无需启动完整引擎）
    - 延迟动作用 ``asyncio.sleep``，不阻塞其他规则评估
    - cooldown 按规则维度计时，防止同一规则在一个周期内重复触发

典型用法::

    collab = DeviceCollaboration(
        on_write_point=engine.write_device_point,
        on_read_point=_read_fn,
    )
    collab.add_rule(CollaborationRule(
        id="fan-control",
        source_device_id="temp-sensor",
        source_point="temperature",
        condition={"operator": ">", "value": 80},
        actions=[CollaborationAction(
            target_device_id="fan", target_point="speed",
            action_type="set", value=100,
        )],
        cooldown=5.0,
    ))
    await collab.tick()  # 在引擎 tick 循环中调用
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 回调类型
WritePointCallback = Callable[[str, str, Any], Awaitable[bool]]
ReadPointCallback = Callable[[str, str], Any]
InjectFaultCallback = Callable[[str, dict[str, Any]], Awaitable[str | None]]  # (device_id, fault_config) -> fault_id


# ---------------------------------------------------------------------------
#  数据模型
# ---------------------------------------------------------------------------


class CollaborationAction(BaseModel):
    """协同动作：对目标设备点位的一次操作。"""

    target_device_id: str
    target_point: str = ""  # inject_fault 动作可为空（作用于整个设备）
    action_type: Literal["set", "toggle", "increment", "decrement", "delay", "inject_fault"] = "set"
    value: Any = None  # set 的目标值 / increment&decrement 的步长（默认 1）/ inject_fault 的故障配置 dict
    delay: float = 0.0  # 秒；>0 时在该动作前等待，用于链式延迟


class CollaborationRule(BaseModel):
    """协同规则：源点位满足条件 → 触发链式动作。"""

    id: str
    name: str = ""
    source_device_id: str
    source_point: str
    condition: dict[str, Any] = Field(default_factory=dict)
    actions: list[CollaborationAction] = Field(default_factory=list)
    cooldown: float = 0.0  # 秒；>0 时两次触发间至少间隔该时长
    enabled: bool = True


# ---------------------------------------------------------------------------
#  条件评估
# ---------------------------------------------------------------------------


def evaluate_condition(value: Any, condition: dict[str, Any]) -> bool:
    """评估点位值是否满足条件。

    支持的 operator:
        ``>`` ``<`` ``>=`` ``<=`` ``==`` ``!=`` ``between`` ``in`` ``not_in``

    condition 示例::

        {"operator": ">", "value": 80}
        {"operator": "between", "value": [10, 50]}
        {"operator": "in", "value": [1, 2, 3]}
    """
    if not condition:
        return False
    op = str(condition.get("operator", "")).strip().lower()
    target = condition.get("value")

    try:
        if op == ">":
            return value is not None and value > target
        if op == "<":
            return value is not None and value < target
        if op == ">=":
            return value is not None and value >= target
        if op == "<=":
            return value is not None and value <= target
        if op == "==":
            return value == target
        if op == "!=":
            return value != target
        if op == "between":
            if not isinstance(target, (list, tuple)) or len(target) != 2:
                return False
            return value is not None and target[0] <= value <= target[1]
        if op == "in":
            return value in (target or [])
        if op == "not_in":
            return value not in (target or [])
    except TypeError:
        # 类型不兼容的比较（如 None > 80）→ 不满足
        return False

    logger.warning("Unknown collaboration operator: %s", op)
    return False


# ---------------------------------------------------------------------------
#  协同引擎
# ---------------------------------------------------------------------------


class DeviceCollaboration:
    """多设备协同联动引擎。

    :param on_write_point: 异步回调 ``(device_id, point_name, value) -> bool``，
        用于写入目标设备点位（通常绑定 ``engine.write_device_point``）。
    :param on_read_point: 同步回调 ``(device_id, point_name) -> Any``，
        用于读取源设备点位值。返回 None 表示读取失败/设备不存在。
    """

    def __init__(
        self,
        on_write_point: WritePointCallback,
        on_read_point: ReadPointCallback,
        on_inject_fault: InjectFaultCallback | None = None,
    ):
        self._on_write = on_write_point
        self._on_read = on_read_point
        self._on_inject_fault = on_inject_fault
        self._rules: list[CollaborationRule] = []
        self._last_trigger: dict[str, float] = {}  # rule_id -> last trigger timestamp

    def add_rule(self, rule: CollaborationRule) -> None:
        self._rules.append(rule)
        logger.info("Collaboration rule added: %s (%s)", rule.id, rule.name)

    def remove_rule(self, rule_id: str) -> None:
        self._rules = [r for r in self._rules if r.id != rule_id]
        self._last_trigger.pop(rule_id, None)

    @property
    def rules(self) -> list[CollaborationRule]:
        return list(self._rules)

    async def tick(self) -> int:
        """评估所有规则并触发满足条件的动作链。

        :return: 本次 tick 触发的规则数量。
        """
        if not self._rules:
            return 0

        triggered = 0
        now = time.time()
        for rule in self._rules:
            if not rule.enabled:
                continue
            # cooldown 检查
            if rule.cooldown > 0:
                last = self._last_trigger.get(rule.id, 0.0)
                if now - last < rule.cooldown:
                    continue

            try:
                source_value = self._on_read(rule.source_device_id, rule.source_point)
            except Exception as e:
                logger.debug("Collaboration read failed for %s.%s: %s", rule.source_device_id, rule.source_point, e)
                continue

            if source_value is None:
                continue

            if not evaluate_condition(source_value, rule.condition):
                continue

            # 满足条件 → 触发动作链
            self._last_trigger[rule.id] = now
            triggered += 1
            logger.info(
                "Collaboration rule %s triggered: %s.%s=%s %s",
                rule.id, rule.source_device_id, rule.source_point, source_value, rule.condition,
            )
            try:
                await self._trigger_chain(rule)
            except Exception as e:
                logger.warning("Collaboration rule %s chain error: %s", rule.id, e)

        return triggered

    async def _trigger_chain(self, rule: CollaborationRule) -> None:
        """顺序执行规则的动作链。delay 动作用 asyncio.sleep 实现链式延迟。"""
        for action in rule.actions:
            if action.delay > 0:
                await asyncio.sleep(action.delay)

            if action.action_type == "delay":
                # 纯延迟动作，不写点位
                continue

            if action.action_type == "inject_fault":
                # 故障注入链式：调用 on_inject_fault 回调注入并激活故障
                await self._do_inject_fault(action, rule)
                continue

            try:
                current = self._on_read(action.target_device_id, action.target_point)
            except Exception:
                current = None

            new_value = self._compute_action_value(action, current)
            try:
                ok = await self._on_write(action.target_device_id, action.target_point, new_value)
                if not ok:
                    logger.warning(
                        "Collaboration write rejected: %s.%s = %s (rule %s)",
                        action.target_device_id, action.target_point, new_value, rule.id,
                    )
            except Exception as e:
                logger.warning(
                    "Collaboration write error: %s.%s (rule %s): %s",
                    action.target_device_id, action.target_point, rule.id, e,
                )

    async def _do_inject_fault(self, action: CollaborationAction, rule: CollaborationRule) -> None:
        """执行故障注入动作。``action.value`` 为故障配置 dict。"""
        if not self._on_inject_fault:
            logger.warning(
                "Collaboration inject_fault action skipped (no callback): rule=%s device=%s",
                rule.id, action.target_device_id,
            )
            return
        fault_cfg = action.value if isinstance(action.value, dict) else {}
        # 允许 action.target_point 作为 target_point（故障作用点位）
        if action.target_point and "target_point" not in fault_cfg:
            fault_cfg = {**fault_cfg, "target_point": action.target_point}
        try:
            fault_id = await self._on_inject_fault(action.target_device_id, fault_cfg)
            if fault_id:
                logger.info(
                    "Collaboration inject_fault: device=%s fault_id=%s (rule %s)",
                    action.target_device_id, fault_id, rule.id,
                )
            else:
                logger.warning(
                    "Collaboration inject_fault returned no fault_id: device=%s (rule %s)",
                    action.target_device_id, rule.id,
                )
        except Exception as e:
            logger.warning(
                "Collaboration inject_fault error: device=%s (rule %s): %s",
                action.target_device_id, rule.id, e,
            )

    @staticmethod
    def _compute_action_value(action: CollaborationAction, current: Any) -> Any:
        """根据动作类型计算要写入的新值。"""
        if action.action_type == "set":
            return action.value
        if action.action_type == "toggle":
            # 布尔翻转；非布尔当前值按 falsy 处理
            return not bool(current)
        if action.action_type == "increment":
            step = action.value if action.value is not None else 1
            try:
                return (current or 0) + step
            except TypeError:
                return step
        if action.action_type == "decrement":
            step = action.value if action.value is not None else 1
            try:
                return (current or 0) - step
            except TypeError:
                return -step
        # 不应到达此处（delay 已在前面处理）
        return action.value
