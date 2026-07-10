"""Module: scenario."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from protoforge.core.collaboration import (
    CollaborationAction,
    CollaborationRule,
    DeviceCollaboration,
)
from protoforge.core.device import DeviceInstance
from protoforge.core.generator import DataGenerator
from protoforge.core.timeseries_replay import TimeSeriesReplay
from protoforge.models.device import DeviceStatus
from protoforge.models.scenario import Rule, RuleType, ScenarioConfig, ScenarioStatus

logger = logging.getLogger(__name__)


class Scenario:
    def __init__(self, config: ScenarioConfig, on_write_point: Callable[[str, str, Any], Any] | None = None):
        self.config = config
        self._status: ScenarioStatus = ScenarioStatus.STOPPED
        self._devices: dict[str, DeviceInstance] = {}
        self._generator = DataGenerator()
        self._start_time: float | None = None
        self._last_trigger: dict[str, float] = {}
        self._prev_values: dict[str, Any] = {}
        self._on_write_point = on_write_point
        # 多设备协同联动引擎（绑定本场景的设备读写回调 + 故障注入回调）
        self._collaboration = DeviceCollaboration(
            on_write_point=self._collab_write,
            on_read_point=self._collab_read,
            on_inject_fault=self._collab_inject_fault,
        )
        # 时间序列回放器（可选，由 replay_config 启用）
        self._replay: TimeSeriesReplay | None = None
        if config.replay_config:
            rc = config.replay_config
            self._replay = TimeSeriesReplay(
                source=rc.get("source", []),
                time_field=rc.get("time_field", "ts"),
                speed=rc.get("speed", 1.0),
                loop=rc.get("loop", False),
            )

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
        # 同步协同规则到协同引擎（清空旧规则后重新注册）
        self._sync_collaboration_rules()
        # 启动时间序列回放器（若配置）
        if self._replay:
            self._replay.start()
        for device in self._devices.values():
            device.start()

    def _sync_collaboration_rules(self) -> None:
        """将 config.rules 中 rule_type==COLLABORATION 的规则转换并注册到协同引擎。"""
        # 清空已注册规则
        for rule in list(self._collaboration.rules):
            self._collaboration.remove_rule(rule.id)
        for rule in self.config.rules:
            if rule.rule_type != RuleType.COLLABORATION or not rule.enabled:
                continue
            collab_rule = self._convert_to_collaboration_rule(rule)
            if collab_rule:
                self._collaboration.add_rule(collab_rule)

    def _convert_to_collaboration_rule(self, rule: Rule) -> CollaborationRule | None:
        """将场景 Rule 转换为协同引擎的 CollaborationRule。

        actions 来源优先级:
          1. rule.actions（显式多动作链，每项为 dict）
          2. 由 rule.target_device_id/target_point/target_value 合成单个 set 动作
        condition 直接透传（含 operator/value），cooldown 取 rule.cooldown。
        """
        actions: list[CollaborationAction] = []
        for act in rule.actions:
            try:
                actions.append(CollaborationAction(**act))
            except Exception as e:
                logger.warning("Rule %s: invalid action %s skipped: %s", rule.id, act, e)
        if not actions and rule.target_device_id and rule.target_point:
            action_type = (rule.condition or {}).get("action", "set")
            actions.append(CollaborationAction(
                target_device_id=rule.target_device_id,
                target_point=rule.target_point,
                action_type=action_type if action_type in ("set", "toggle", "increment", "decrement", "delay") else "set",
                value=rule.target_value,
            ))
        if not actions:
            logger.debug("Rule %s has no collaboration actions, skipping", rule.id)
            return None
        return CollaborationRule(
            id=rule.id,
            name=rule.name,
            source_device_id=rule.source_device_id,
            source_point=rule.source_point,
            condition=rule.condition,
            actions=actions,
            cooldown=rule.cooldown,
            enabled=rule.enabled,
        )

    def _collab_read(self, device_id: str, point_name: str) -> Any:
        """协同引擎读回调：返回设备点位当前值，失败返回 None。"""
        device = self._devices.get(device_id)
        if not device or device.status != DeviceStatus.ONLINE:
            return None
        pv = device.read_point(point_name)
        return pv.value if pv else None

    async def _collab_write(self, device_id: str, point_name: str, value: Any) -> bool:
        """协同引擎写回调：写入设备点位并传播到协议服务器。

        优先通过 on_write_point（引擎 write_device_point）写入，确保协议客户端
        立即可见；若未配置则回退到 DeviceInstance 内存写入。
        """
        device = self._devices.get(device_id)
        if not device or device.status != DeviceStatus.ONLINE:
            return False
        if self._on_write_point:
            try:
                result = self._on_write_point(device_id, point_name, value)
                if asyncio.iscoroutine(result):
                    return await result
                return bool(result)
            except Exception as e:
                logger.warning("Collaboration write via engine failed for %s.%s: %s", device_id, point_name, e)
                return False
        return await device.write_point(point_name, value)

    async def _collab_inject_fault(self, device_id: str, fault_cfg: dict[str, Any]) -> str | None:
        """协同引擎故障注入回调：向设备注入故障并立即激活。

        ``fault_cfg`` 结构兼容 ``FaultConfig`` 关键字段：
        ``fault_type``（默认 sensor_noise）、``target_point``（默认 "*"）、
        ``parameters``（默认空 dict）、``trigger_mode``（默认 manual）。
        """
        device = self._devices.get(device_id)
        if not device or device.status != DeviceStatus.ONLINE:
            logger.warning("inject_fault: device %s not online", device_id)
            return None
        try:
            from protoforge.core.fault_injection import FaultConfig, FaultType, TriggerMode
            ft_raw = fault_cfg.get("fault_type", "sensor_noise")
            ft = FaultType(ft_raw) if isinstance(ft_raw, str) else ft_raw
            tm_raw = fault_cfg.get("trigger_mode", "manual")
            tm = TriggerMode(tm_raw) if isinstance(tm_raw, str) else tm_raw
            config = FaultConfig(
                fault_type=ft,
                target_point=fault_cfg.get("target_point", "*"),
                trigger_mode=tm,
                parameters=fault_cfg.get("parameters", {}),
                target_device=device_id,
                probability=fault_cfg.get("probability", 0.0),
                start_time=fault_cfg.get("start_time"),
                description=fault_cfg.get("description", f"Collaboration-injected: {ft.value}"),
            )
            fault_id = device.inject_fault(config)
            device.activate_fault(fault_id)
            logger.info("Collaboration injected fault %s on device %s (type=%s)", fault_id, device_id, ft.value)
            return fault_id
        except Exception as e:
            logger.warning("inject_fault failed on device %s: %s", device_id, e)
            return None

    def stop(self) -> None:
        self._status = ScenarioStatus.STOPPED
        self._start_time = None
        for device in self._devices.values():
            try:
                device.stop()
            except Exception as e:
                logger.error("Failed to stop device %s: %s", device.id, e)

    async def tick(self) -> None:
        if self._status != ScenarioStatus.RUNNING:
            return
        # 时间序列回放：取当前帧数据写入设备点位（在规则评估前，使规则可响应回放值）
        if self._replay:
            await self._pump_replay_frame()
        await self._evaluate_rules()
        # 协同规则由 DeviceCollaboration 引擎统一评估（支持多动作链+cooldown）
        try:
            await self._collaboration.tick()
        except Exception as e:
            logger.warning("Collaboration tick error in scenario %s: %s", self.id, e)

    async def _pump_replay_frame(self) -> None:
        """从回放器取一帧数据并写入对应设备点位。"""
        if not self._replay:
            return
        frame = self._replay.next_points()
        if frame is None:
            logger.debug("Scenario %s: replay exhausted", self.id)
            return
        for device_id, point_name, value in frame:
            device = self._devices.get(device_id)
            if not device or device.status != DeviceStatus.ONLINE:
                continue
            try:
                if self._on_write_point:
                    result = self._on_write_point(device_id, point_name, value)
                    if asyncio.iscoroutine(result):
                        await result
                else:
                    await device.write_point(point_name, value)
            except Exception as e:
                logger.debug("Replay write failed for %s.%s: %s", device_id, point_name, e)

    async def _evaluate_rules(self) -> None:
        for rule in self.config.rules:
            if not rule.enabled:
                continue
            # COLLABORATION 规则由协同引擎处理，此处跳过避免重复评估
            if rule.rule_type == RuleType.COLLABORATION:
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
        if not point_value or point_value.value is None:
            return False
        if not rule.condition or not isinstance(rule.condition, dict):
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
        if not rule.condition or not isinstance(rule.condition, dict):
            return False
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
        if not rule.condition or not isinstance(rule.condition, dict):
            return False
        if not self._start_time:
            return False
        interval = rule.condition.get("interval", 60)
        if not isinstance(interval, (int, float)) or interval <= 0:
            interval = 60
        elapsed = time.time() - self._start_time
        key = f"timer_{rule.id}"
        last = self._last_trigger.get(key, 0)
        if elapsed - last >= interval:
            self._last_trigger[key] = elapsed
            return True
        return False

    def _check_script(self, rule: Rule) -> bool:
        if not rule.condition or not isinstance(rule.condition, dict):
            return False
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
            if result is not None and result:
                return self._check_cooldown(rule)
        except Exception as e:
            logger.debug("Script rule %s error: %s", rule.id, e)
        return False

    def _check_cooldown(self, rule: Rule) -> bool:
        if not rule.condition or not isinstance(rule.condition, dict):
            return True
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
            logger.debug("Rule %s has no target_device_id or target_point, skipping action", rule.id)
            return
        target = self._devices.get(rule.target_device_id)
        if not target or target.status != DeviceStatus.ONLINE:
            return
        value = rule.target_value
        action_type = (rule.condition or {}).get("action", "set")
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
            step = (rule.condition or {}).get("step", 1)
            try:
                value = (float(current.value) if current else 0) + step
            except (ValueError, TypeError):
                logger.warning("Increment action on non-numeric point %s.%s", rule.target_device_id, rule.target_point)
                return
        elif action_type == "decrement":
            current = target.read_point(rule.target_point)
            step = (rule.condition or {}).get("step", 1)
            try:
                value = (float(current.value) if current else 0) - step
            except (ValueError, TypeError):
                logger.warning("Decrement action on non-numeric point %s.%s", rule.target_device_id, rule.target_point)
                return
        success = await target.write_point(rule.target_point, value)
        if success:
            logger.info("Rule %s triggered: %s.%s = %s", rule.id, rule.target_device_id, rule.target_point, value)
            if self._on_write_point:
                try:
                    await self._on_write_point(rule.target_device_id, rule.target_point, value)
                except Exception as e:
                    logger.warning(
                        "Rule %s: failed to propagate write to protocol server for %s.%s: %s",
                        rule.id, rule.target_device_id, rule.target_point, e,
                    )
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

            def _on_webhook_done(t: asyncio.Task) -> None:
                if t.cancelled():
                    return
                exc = t.exception()
                if exc:
                    logger.warning("Webhook trigger failed for rule %s: %s", rule.id, exc)

            task.add_done_callback(_on_webhook_done)
        except Exception as e:
            logger.warning("Webhook notify error for rule %s: %s", rule.id, e)

    @staticmethod
    def _compare(value: Any, operator: str, threshold: Any) -> bool:
        try:
            v = float(value)
            t = float(threshold)
        except (ValueError, TypeError):
            v, t = value, threshold
        try:
            _ops = {
                ">": lambda a, b: a > b,
                ">=": lambda a, b: a >= b,
                "<": lambda a, b: a < b,
                "<=": lambda a, b: a <= b,
                "==": lambda a, b: a == b,
                "!=": lambda a, b: a != b,
            }
            if operator in _ops:
                return _ops[operator](v, t)
        except TypeError:
            return False
        return False
