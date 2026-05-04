import asyncio
import logging
import time
from typing import Any, Optional

from protoforge.core.device import DeviceInstance
from protoforge.core.generator import DataGenerator
from protoforge.models.device import DeviceStatus, PointValue
from protoforge.models.scenario import Rule, RuleType, ScenarioConfig, ScenarioStatus

logger = logging.getLogger(__name__)


class Scenario:
    def __init__(self, config: ScenarioConfig):
        self.config = config
        self._status: ScenarioStatus = ScenarioStatus.STOPPED
        self._devices: dict[str, DeviceInstance] = {}
        self._generator = DataGenerator()
        self._start_time: Optional[float] = None
        self._last_trigger: dict[str, float] = {}
        self._prev_values: dict[str, Any] = {}

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def status(self) -> ScenarioStatus:
        return self._status

    def add_device(self, device: DeviceInstance) -> None:
        self._devices[device.id] = device

    def remove_device(self, device_id: str) -> None:
        self._devices.pop(device_id, None)

    def start(self) -> None:
        self._status = ScenarioStatus.RUNNING
        self._start_time = time.time()
        self._last_trigger.clear()
        self._prev_values.clear()
        for device in self._devices.values():
            device.start()

    def stop(self) -> None:
        self._status = ScenarioStatus.STOPPED
        self._start_time = None
        for device in self._devices.values():
            device.stop()

    async def tick(self) -> None:
        if self._status != ScenarioStatus.RUNNING:
            return
        await self._evaluate_rules()

    async def _evaluate_rules(self) -> None:
        for rule in self.config.rules:
            if not rule.enabled:
                continue
            try:
                triggered = self._check_rule(rule)
                if triggered:
                    await self._execute_action(rule)
            except Exception as e:
                logger.warning("Rule %s evaluation error: %s", rule.id, e)

    def _check_rule(self, rule: Rule) -> bool:
        if rule.rule_type == RuleType.THRESHOLD:
            return self._check_threshold(rule)
        elif rule.rule_type == RuleType.VALUE_CHANGE:
            return self._check_value_change(rule)
        elif rule.rule_type == RuleType.TIMER:
            return self._check_timer(rule)
        elif rule.rule_type == RuleType.SCRIPT:
            return self._check_script(rule)
        return False

    def _check_threshold(self, rule: Rule) -> bool:
        source = self._devices.get(rule.source_device_id)
        if not source or source.status != DeviceStatus.ONLINE:
            return False
        point_value = source.read_point(rule.source_point)
        if not point_value:
            return False
        conditions = rule.condition.get("conditions", [rule.condition])
        operator = rule.condition.get("logic", "and")
        results = []
        for cond in conditions:
            op = cond.get("operator", ">")
            threshold = cond.get("value", 0)
            results.append(self._compare(point_value.value, op, threshold))
        if not results:
            return False
        result = all(results) if operator == "and" else any(results)
        if result:
            return self._check_cooldown(rule)
        return False

    def _check_value_change(self, rule: Rule) -> bool:
        source = self._devices.get(rule.source_device_id)
        if not source or source.status != DeviceStatus.ONLINE:
            return False
        point_value = source.read_point(rule.source_point)
        if not point_value:
            return False
        key = f"{rule.source_device_id}.{rule.source_point}"
        prev = self._prev_values.get(key)
        current = point_value.value
        self._prev_values[key] = current
        if prev is None:
            return False
        delta = rule.condition.get("delta", None)
        if delta is not None:
            try:
                if abs(float(current) - float(prev)) >= float(delta):
                    return self._check_cooldown(rule)
            except (ValueError, TypeError):
                logger.debug("Delta comparison failed for rule %s: current=%s prev=%s", rule.id, current, prev)
        elif current != prev:
            return self._check_cooldown(rule)
        return False

    def _check_timer(self, rule: Rule) -> bool:
        if not self._start_time:
            return False
        interval = rule.condition.get("interval", 60)
        elapsed = time.time() - self._start_time
        key = f"timer_{rule.id}"
        last = self._last_trigger.get(key, 0)
        if elapsed - last >= interval:
            self._last_trigger[key] = elapsed
            return True
        return False

    def _check_script(self, rule: Rule) -> bool:
        source = self._devices.get(rule.source_device_id)
        if not source or source.status != DeviceStatus.ONLINE:
            return False
        point_value = source.read_point(rule.source_point)
        if not point_value:
            return False
        script = rule.condition.get("expression", "")
        if not script:
            return False
        try:
            from protoforge.core.generator import SafeEval
            evaluator = SafeEval({"value": point_value.value, "point": point_value.value})
            result = evaluator.eval_expr(script)
            if result:
                return self._check_cooldown(rule)
        except Exception as e:
            logger.debug("Script rule %s error: %s", rule.id, e)
        return False

    def _check_cooldown(self, rule: Rule) -> bool:
        cooldown = rule.condition.get("cooldown", 0)
        if cooldown <= 0:
            return True
        now = time.time()
        last = self._last_trigger.get(rule.id, 0)
        if now - last < cooldown:
            return False
        self._last_trigger[rule.id] = now
        return True

    async def _execute_action(self, rule: Rule) -> None:
        if not rule.target_device_id or not rule.target_point:
            return
        target = self._devices.get(rule.target_device_id)
        if not target or target.status != DeviceStatus.ONLINE:
            return
        value = rule.target_value
        action_type = rule.condition.get("action", "set")
        if action_type == "toggle":
            current = target.read_point(rule.target_point)
            if current and isinstance(current.value, bool):
                value = not current.value
            elif current:
                logger.warning("Toggle action on non-boolean point %s.%s", rule.target_device_id, rule.target_point)
                return
            else:
                value = True
        elif action_type == "increment":
            current = target.read_point(rule.target_point)
            step = rule.condition.get("step", 1)
            try:
                value = (float(current.value) if current else 0) + step
            except (ValueError, TypeError):
                logger.warning("Increment action on non-numeric point %s.%s", rule.target_device_id, rule.target_point)
                return
        elif action_type == "decrement":
            current = target.read_point(rule.target_point)
            step = rule.condition.get("step", 1)
            try:
                value = (float(current.value) if current else 0) - step
            except (ValueError, TypeError):
                logger.warning("Decrement action on non-numeric point %s.%s", rule.target_device_id, rule.target_point)
                return
        success = await target.write_point(rule.target_point, value)
        if success:
            logger.info("Rule %s triggered: %s.%s = %s", rule.id, rule.target_device_id, rule.target_point, value)
            self._notify_webhook(rule, value)

    def _notify_webhook(self, rule: Rule, value: Any) -> None:
        try:
            from protoforge.core.webhook import webhook_manager
            payload = {
                "rule_id": rule.id, "rule_name": rule.name,
                "source_device": rule.source_device_id,
                "source_point": rule.source_point,
                "target_device": rule.target_device_id,
                "target_point": rule.target_point,
                "target_value": str(value),
                "scenario_id": self.id,
            }
            task = asyncio.get_running_loop().create_task(
                webhook_manager.trigger("rule_triggered", payload)
            )
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)
        except Exception as e:
            logger.debug("Webhook notify error: %s", e)

    @staticmethod
    def _compare(value: Any, operator: str, threshold: Any) -> bool:
        try:
            v = float(value)
            t = float(threshold)
        except (ValueError, TypeError):
            v, t = value, threshold
        if operator == ">":
            return v > t
        elif operator == ">=":
            return v >= t
        elif operator == "<":
            return v < t
        elif operator == "<=":
            return v <= t
        elif operator == "==":
            return v == t
        elif operator == "!=":
            return v != t
        return False
