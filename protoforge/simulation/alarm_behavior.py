"""告警行为学模型（v1.8.0）：告警风暴 / 抖动 / SOE 事件序列。

测告警系统是 SCADA/组态 QA 的独立需求——现有故障注入能制造"设备故障"，
但制造不了"告警行为学"这个维度：

  - :class:`AlarmStormBehavior`   告警风暴：按可配速率产生告警（突发/持续两种
    模式），测告警处理链路的吞吐与不丢失能力；
  - :class:`ChatteringBehavior`   告警抖动（chattering）：信号在阈值附近快速
    翻转，测报警抑制/死区/防抖逻辑（工业现场最烦人的告警质量问题）；
  - :class:`SOESequenceBehavior`  SOE 事件序列：按毫秒时标产生有序事件流
    （跳闸顺序记录），测 SOE/顺序记录系统的分辨率与排序正确性。

与 behavior_models.py 的物理模型同构：继承 BaseBehavior，update() 推进一步
返回当前输出，get_state()/to_dict() 可序列化。
"""

from __future__ import annotations

import random
import time
from typing import Any

from protoforge.simulation.behavior_models import BaseBehavior


class AlarmStormBehavior(BaseBehavior):
    """告警风暴发生器。

    :param mode: "burst"（突发：短时间高频）或 "sustained"（持续：恒定速率）
    :param rate_per_second: 持续模式的告警速率（条/秒）
    :param burst_rate_per_second: 突发模式峰值速率（条/秒）
    :param burst_duration: 突发持续时长（秒），之后进入 idle_duration 的静默
    :param idle_duration: 突发间静默时长（秒）
    :param total_count: 产生的告警总数上限；None 不限
    :param messages: 告警文本池（循环取用）；为空时用 "ALARM-<序号>"
    """

    def __init__(
        self,
        mode: str = "sustained",
        rate_per_second: float = 10.0,
        burst_rate_per_second: float = 100.0,
        burst_duration: float = 5.0,
        idle_duration: float = 10.0,
        total_count: int | None = None,
        messages: list[str] | None = None,
        seed: int | None = None,
    ):
        if mode not in ("burst", "sustained"):
            raise ValueError(f"mode must be 'burst' or 'sustained', got {mode!r}")
        self.mode = mode
        self.rate_per_second = max(0.0, rate_per_second)
        self.burst_rate_per_second = max(0.0, burst_rate_per_second)
        self.burst_duration = max(0.0, burst_duration)
        self.idle_duration = max(0.0, idle_duration)
        self.total_count = total_count
        self.messages = list(messages) if messages else []
        self._rng = random.Random(seed)
        super().__init__(
            mode=mode,
            rate_per_second=rate_per_second,
            burst_rate_per_second=burst_rate_per_second,
            burst_duration=burst_duration,
            idle_duration=idle_duration,
            total_count=total_count,
            messages=self.messages,
        )

    def _init_state(self) -> None:
        self._elapsed = 0.0
        self._carry = 0.0        # 不足一条的分数部分累积
        self._emitted = 0        # 已产生总数
        self._seq = 0            # 消息池序号
        self._cycle_pos = 0.0    # burst 周期内位置（秒）

    def update(self, dt: float = 1.0, **kwargs: Any) -> list[dict[str, Any]]:
        """推进 dt 秒，返回这一步产生的告警列表（0..n 条）。

        每条告警形如 ``{"index", "message", "timestamp", "severity"}``。
        """
        dt = max(0.0, dt)
        self._elapsed += dt

        if self.total_count is not None and self._emitted >= self.total_count:
            return []

        if self.mode == "sustained":
            rate = self.rate_per_second
        else:
            cycle = self.burst_duration + self.idle_duration
            self._cycle_pos = (self._cycle_pos + dt) % cycle if cycle > 0 else 0.0
            in_burst = self._cycle_pos <= self.burst_duration
            rate = self.burst_rate_per_second if in_burst else 0.0

        count_f = rate * dt + self._carry
        count = int(count_f)
        self._carry = count_f - count

        if self.total_count is not None:
            count = min(count, self.total_count - self._emitted)

        alarms: list[dict[str, Any]] = []
        for _ in range(count):
            self._seq += 1
            self._emitted += 1
            msg = (self.messages[(self._seq - 1) % len(self.messages)]
                   if self.messages else f"ALARM-{self._seq}")
            alarms.append({
                "index": self._emitted,
                "message": msg,
                "timestamp": time.time(),
                "severity": self._rng.choice(["warning", "critical"]) if self._rng else "warning",
            })
        return alarms

    def _state(self) -> dict[str, Any]:
        return {"elapsed": self._elapsed, "emitted": self._emitted,
                "seq": self._seq, "carry": self._carry, "cycle_pos": self._cycle_pos}

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._elapsed = state.get("elapsed", 0.0)
        self._emitted = state.get("emitted", 0)
        self._seq = state.get("seq", 0)
        self._carry = state.get("carry", 0.0)
        self._cycle_pos = state.get("cycle_pos", 0.0)


class ChatteringBehavior(BaseBehavior):
    """告警抖动（chattering）发生器：信号在阈值附近快速翻转。

    模拟现场最常见的告警质量问题——测量值在设定点附近抖动导致告警反复
    触发/恢复。输出布尔量序列，翻转频率、占空比、随机抖动可配：
    测被测系统的防抖（debounce）/死区/告警抑制逻辑。

    :param period: 一个完整翻转周期（秒），0.5 = 每秒 2 次
    :param duty_cycle: 高电平占空比 0..1，默认 0.5
    :param jitter: 每次翻转时刻的随机抖动比例 0..1（0=完美方波）
    :param start_on: 初始电平
    :param seed: 随机种子
    """

    def __init__(
        self,
        period: float = 0.5,
        duty_cycle: float = 0.5,
        jitter: float = 0.0,
        start_on: bool = True,
        seed: int | None = None,
    ):
        if period <= 0:
            raise ValueError(f"period must be > 0, got {period}")
        if not 0.0 <= duty_cycle <= 1.0:
            raise ValueError(f"duty_cycle must be within [0,1], got {duty_cycle}")
        self.period = period
        self.duty_cycle = min(1.0, max(0.0, duty_cycle))
        self.jitter = min(1.0, max(0.0, jitter))
        self._start_on = start_on
        self._rng = random.Random(seed)
        super().__init__(
            period=period,
            duty_cycle=self.duty_cycle,
            jitter=self.jitter,
            start_on=start_on,
        )

    def _init_state(self) -> None:
        self._value = self._start_on
        self._elapsed = 0.0
        self._flips = 0
        self._next_flip = self.period * (1.0 - self.duty_cycle) if not self._start_on \
            else self.period * self.duty_cycle

    def update(self, dt: float = 1.0, **kwargs: Any) -> bool:
        """推进 dt 秒，返回当前布尔电平（跨过翻转时刻即翻转）。"""
        self._elapsed += dt
        while self._elapsed >= self._next_flip:
            self._value = not self._value
            self._flips += 1
            jittered = self.period * (1.0 + self._rng.uniform(-self.jitter, self.jitter)) \
                if self.jitter else self.period
            self._next_flip += max(1e-6, jittered)
        return self._value

    @property
    def flip_count(self) -> int:
        """已发生翻转次数（防抖测试的断言依据）。"""
        return self._flips

    def _state(self) -> dict[str, Any]:
        return {"value": self._value, "elapsed": self._elapsed,
                "flips": self._flips, "next_flip": self._next_flip}

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._value = state.get("value", self._start_on)
        self._elapsed = state.get("elapsed", 0.0)
        self._flips = state.get("flips", 0)
        self._next_flip = state.get("next_flip", 0.0)


class SOESequenceBehavior(BaseBehavior):
    """SOE（Sequence of Events）事件序列发生器：按毫秒时标产生有序事件流。

    :param events: 事件定义列表，每项 ``{"name", "offset_ms", "payload"}``；
                   offset_ms 为相对序列起点的毫秒时标（应升序，乱序会被排序）
    :param repeat_interval: 整个序列循环周期（秒）；None 只播一遍
    :param time_scale: 时标缩放（1.0=真实毫秒；0.1=十倍速回放）
    """

    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        repeat_interval: float | None = None,
        time_scale: float = 1.0,
    ):
        self.time_scale = max(1e-6, time_scale)
        evs = sorted(events or [], key=lambda e: float(e.get("offset_ms", 0)))
        self.events = evs
        self.repeat_interval = repeat_interval
        super().__init__(
            events=self.events,
            repeat_interval=repeat_interval,
            time_scale=self.time_scale,
        )

    def _init_state(self) -> None:
        self._elapsed_ms = 0.0
        self._fired = 0            # 已触发事件指针
        self._lap = 0              # 完成轮数
        self._emitted: list[dict[str, Any]] = []

    def update(self, dt: float = 1.0, **kwargs: Any) -> list[dict[str, Any]]:
        """推进 dt 秒，返回这步到点的 SOE 事件（按 offset 升序）。

        每条事件： ``{"name", "offset_ms", "actual_ms", "lap", "payload"}``。
        """
        self._elapsed_ms += dt * 1000.0 * self.time_scale
        out: list[dict[str, Any]] = []
        while self._fired < len(self.events):
            ev = self.events[self._fired]
            offset = float(ev.get("offset_ms", 0))
            if offset <= self._elapsed_ms:
                out.append({
                    "name": ev.get("name", f"EVT-{self._fired + 1}"),
                    "offset_ms": offset,
                    "actual_ms": round(self._elapsed_ms, 3),
                    "lap": self._lap,
                    "payload": ev.get("payload"),
                })
                self._fired += 1
            else:
                break

        # 序列播完且允许循环 → 进入下一轮
        if self._fired >= len(self.events) and self.events:
            if self.repeat_interval is not None:
                cycle_ms = self.repeat_interval * 1000.0
                if self._elapsed_ms >= cycle_ms:
                    self._elapsed_ms -= cycle_ms
                    self._fired = 0
                    self._lap += 1
        self._emitted.extend(out)
        return out

    @property
    def fired_flat(self) -> list[dict[str, Any]]:
        """历史全部已触发事件（跨轮累计）。"""
        return self._emitted

    def _state(self) -> dict[str, Any]:
        return {"elapsed_ms": self._elapsed_ms, "fired": self._fired, "lap": self._lap}

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._elapsed_ms = state.get("elapsed_ms", 0.0)
        self._fired = state.get("fired", 0)
        self._lap = state.get("lap", 0)
