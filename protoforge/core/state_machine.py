"""设备状态机引擎。

本模块实现了工业设备的标准状态机模型，支持七种设备状态和
可配置的状态转换规则。状态机负责管理设备生命周期（启动→运行→
停止）、故障处理（故障→复位）、维护模式切换和编程模式切换，
并在每次状态转换时记录历史日志、触发回调通知。

状态转换图（简化）::

    STOP ──start──→ STARTING ──startup_complete──→ RUN
     ↑                                        │
     │                                        ├── stop ──→ STOPPING ──stop_complete──→ STOP
     │                                        │
     │                                        └── fault ──→ ERROR ──reset──→ STOP
     │                                                          │
     └────────────── maintenance_complete ── MAINTENANCE ←──────┘ (任意→MAINTENANCE)
     │
     └────────────── program_mode ──→ PROGRAM (任意→PROGRAM)

状态对数据质量的影响：
  - STOP        → quality="uncertain", 输出保持最后值或归零
  - RUN         → quality="good", 正常数据生成
  - ERROR       → quality="bad", 输出安全值
  - MAINTENANCE → quality="out_of_service"
  - PROGRAM     → quality="uncertain", 不响应外部读请求
  - STARTING    → quality="uncertain"
  - STOPPING    → quality="uncertain"
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  枚举定义
# ---------------------------------------------------------------------------

class DeviceState(str, Enum):
    """设备状态枚举。

    每个状态对应工业设备的特定运行阶段：

    - STOP:        设备已停止，输出保持最后值或归零
    - RUN:         设备正常运行，数据正常生成
    - ERROR:       设备故障，数据质量标记为 Bad，输出安全值
    - PROGRAM:     编程模式，不响应外部读请求或返回特定错误码
    - MAINTENANCE: 维护模式，数据质量标记为 OutOfService
    - STARTING:    启动过程中，尚未达到正常运行状态
    - STOPPING:    停止过程中，正在执行停机序列
    """

    STOP = "stop"
    RUN = "run"
    ERROR = "error"
    PROGRAM = "program"
    MAINTENANCE = "maintenance"
    STARTING = "starting"
    STOPPING = "stopping"


# ---------------------------------------------------------------------------
#  状态转换定义
# ---------------------------------------------------------------------------

@dataclass
class StateTransition:
    """状态转换规则定义。

    定义从 ``from_state`` 到 ``to_state`` 的转换，由 ``trigger`` 事件触发。
    可选的 ``condition`` 回调和 ``guard`` 守卫条件用于在触发时进行额外校验。

    :param from_state: 起始状态（使用 ``None`` 表示任意状态）
    :param to_state: 目标状态
    :param trigger: 触发事件名称（如 "start", "fault", "stop"）
    :param condition: 可选的条件回调，签名为 ``condition(**kwargs) -> bool``，
                      返回 False 时阻止转换
    :param guard: 可选的守卫条件描述字符串（仅用于日志/文档，不参与逻辑）
    :param action: 可选的转换动作回调，签名为 ``action(**kwargs) -> None``，
                   在转换完成时执行
    """

    from_state: DeviceState | None
    to_state: DeviceState
    trigger: str
    condition: Callable[..., bool] | None = None
    guard: str = ""
    action: Callable[..., None] | None = None

    def matches(self, current_state: DeviceState, trigger: str) -> bool:
        """检查此转换是否匹配当前状态和触发事件。

        :param current_state: 当前设备状态
        :param trigger: 触发事件名称
        :return: 是否匹配
        """
        if self.trigger != trigger:
            return False
        if self.from_state is None:
            return True  # None 表示任意状态
        return self.from_state == current_state


# ---------------------------------------------------------------------------
#  状态历史记录
# ---------------------------------------------------------------------------

@dataclass
class StateHistoryEntry:
    """状态转换历史记录条目。"""
    timestamp: float
    from_state: DeviceState
    to_state: DeviceState
    trigger: str
    reason: str = ""
    duration_in_previous: float = 0.0  # 在前一状态的持续时间 (s)


# ---------------------------------------------------------------------------
#  状态机
# ---------------------------------------------------------------------------

class DeviceStateMachine:
    """设备状态机引擎。

    管理设备状态转换的有限状态机，支持：

    - 可配置的转换规则（``add_transition``）
    - 手动触发事件（``trigger``）
    - 转换前条件检查（``can_trigger``）
    - 状态进入/退出回调钩子（``on_enter_state`` / ``on_exit_state``）
    - 状态持续时间追踪（``get_state_duration``）
    - 状态转换历史记录（``get_history``）
    - WebSocket 事件通知回调（``on_transition``）

    内置标准工业设备状态转换规则，覆盖启动、停止、故障、
    维护和编程模式的完整生命周期。

    :param initial_state: 初始状态，默认为 STOP
    :param min_startup_time: 最小启动时间 (s)，STARTING→RUN 需满足此条件
    :param device_id: 关联的设备 ID（用于日志和事件通知）
    :param max_history: 最大历史记录条数
    """

    def __init__(
        self,
        initial_state: DeviceState = DeviceState.STOP,
        min_startup_time: float = 2.0,
        device_id: str = "",
        max_history: int = 500,
    ):
        self._state: DeviceState = initial_state
        self._min_startup_time = min_startup_time
        self._device_id = device_id
        self._max_history = max_history

        self._transitions: list[StateTransition] = []
        self._enter_callbacks: list[Callable[[DeviceState, dict[str, Any]], Any]] = []
        self._exit_callbacks: list[Callable[[DeviceState, dict[str, Any]], Any]] = []
        self._transition_callbacks: list[Callable[[StateHistoryEntry], Any]] = []

        self._state_enter_time: float = time.time()
        self._history: deque[StateHistoryEntry] = deque(maxlen=max_history)
        self._lock = threading.RLock()

        # 注册内置标准转换规则
        self._register_default_transitions()

    # -- 内置转换规则 -----------------------------------------------------

    def _register_default_transitions(self) -> None:
        """注册标准工业设备状态转换规则。"""
        # STOP → STARTING（trigger="start"）
        self.add_transition(StateTransition(
            from_state=DeviceState.STOP,
            to_state=DeviceState.STARTING,
            trigger="start",
            guard="设备从停止状态启动",
        ))

        # STARTING → RUN（trigger="startup_complete"，条件：启动时间 > 最小启动时间）
        self.add_transition(StateTransition(
            from_state=DeviceState.STARTING,
            to_state=DeviceState.RUN,
            trigger="startup_complete",
            condition=self._check_startup_time,
            guard=f"启动时间需大于 {self._min_startup_time}s",
        ))

        # RUN → STOPPING（trigger="stop"）
        self.add_transition(StateTransition(
            from_state=DeviceState.RUN,
            to_state=DeviceState.STOPPING,
            trigger="stop",
            guard="运行中设备停止",
        ))

        # STARTING → STOP（trigger="stop"，启动过程中也可以停止）
        self.add_transition(StateTransition(
            from_state=DeviceState.STARTING,
            to_state=DeviceState.STOPPING,
            trigger="stop",
            guard="启动过程中停止",
        ))

        # STOPPING → STOP（trigger="stop_complete"）
        self.add_transition(StateTransition(
            from_state=DeviceState.STOPPING,
            to_state=DeviceState.STOP,
            trigger="stop_complete",
            guard="停止完成",
        ))

        # RUN → ERROR（trigger="fault"）
        self.add_transition(StateTransition(
            from_state=DeviceState.RUN,
            to_state=DeviceState.ERROR,
            trigger="fault",
            guard="运行中发生故障",
        ))

        # STARTING → ERROR（trigger="fault"，启动过程也可能故障）
        self.add_transition(StateTransition(
            from_state=DeviceState.STARTING,
            to_state=DeviceState.ERROR,
            trigger="fault",
            guard="启动过程中发生故障",
        ))

        # STOPPING → ERROR（trigger="fault"，停止过程也可能故障）
        self.add_transition(StateTransition(
            from_state=DeviceState.STOPPING,
            to_state=DeviceState.ERROR,
            trigger="fault",
            guard="停止过程中发生故障",
        ))

        # 任意 → ERROR（trigger="device_failure"，故障注入引擎的 DEVICE_FAILURE 可在任何状态触发）
        self.add_transition(StateTransition(
            from_state=None,  # 任意状态
            to_state=DeviceState.ERROR,
            trigger="device_failure",
            guard="设备完全失效（故障注入触发）",
        ))

        # ERROR → STOP（trigger="reset"，条件：故障已清除）
        self.add_transition(StateTransition(
            from_state=DeviceState.ERROR,
            to_state=DeviceState.STOP,
            trigger="reset",
            condition=self._check_fault_cleared,
            guard="故障已清除后复位",
        ))

        # 任意 → MAINTENANCE（trigger="maintenance"）
        self.add_transition(StateTransition(
            from_state=None,  # 任意状态
            to_state=DeviceState.MAINTENANCE,
            trigger="maintenance",
            guard="进入维护模式",
        ))

        # MAINTENANCE → STOP（trigger="maintenance_complete"）
        self.add_transition(StateTransition(
            from_state=DeviceState.MAINTENANCE,
            to_state=DeviceState.STOP,
            trigger="maintenance_complete",
            guard="维护完成，回到停止状态",
        ))

        # 任意 → PROGRAM（trigger="program_mode"）
        self.add_transition(StateTransition(
            from_state=None,  # 任意状态
            to_state=DeviceState.PROGRAM,
            trigger="program_mode",
            guard="进入编程模式",
        ))

        # PROGRAM → STOP（trigger="program_exit"）
        self.add_transition(StateTransition(
            from_state=DeviceState.PROGRAM,
            to_state=DeviceState.STOP,
            trigger="program_exit",
            guard="退出编程模式",
        ))

    # -- 内置条件检查 -----------------------------------------------------

    def _check_startup_time(self, **kwargs: Any) -> bool:
        """检查启动时间是否满足最小启动时间要求。"""
        return self.get_state_duration() >= self._min_startup_time

    def _check_fault_cleared(self, **kwargs: Any) -> bool:
        """检查故障是否已清除。

        可通过 kwargs 中的 ``fault_cleared`` 参数显式指定，
        也可通过 ``_fault_cleared`` 标志位判断。
        """
        if "fault_cleared" in kwargs:
            return bool(kwargs["fault_cleared"])
        return getattr(self, "_fault_cleared", False)

    # -- 公开接口 ---------------------------------------------------------

    @property
    def state(self) -> DeviceState:
        """当前设备状态。"""
        with self._lock:
            return self._state

    def get_state(self) -> DeviceState:
        """返回当前设备状态。"""
        with self._lock:
            return self._state

    def get_state_duration(self) -> float:
        """返回当前状态的持续时间 (s)。"""
        with self._lock:
            return time.time() - self._state_enter_time

    def get_history(self, count: int = 50) -> list[StateHistoryEntry]:
        """返回状态转换历史记录。

        :param count: 返回最近 N 条记录
        :return: 历史记录列表（按时间倒序）
        """
        with self._lock:
            entries = list(self._history)
        return entries[-count:][::-1]

    def add_transition(self, transition: StateTransition) -> None:
        """添加一条状态转换规则。

        :param transition: 状态转换定义
        """
        with self._lock:
            self._transitions.append(transition)

    def can_trigger(self, event: str, **kwargs: Any) -> bool:
        """检查指定事件是否可以触发状态转换。

        :param event: 触发事件名称
        :param kwargs: 传递给条件回调的额外参数
        :return: 是否可以触发
        """
        with self._lock:
            for t in self._transitions:
                if t.matches(self._state, event):
                    if t.condition is not None:
                        try:
                            if not t.condition(**kwargs):
                                return False
                        except Exception as e:
                            logger.warning("Transition condition error for '%s': %s", event, e)
                            return False
                    return True
            return False

    def get_available_transitions(self) -> list[StateTransition]:
        """返回当前状态下所有可触发的转换规则。

        :return: 可用转换列表
        """
        with self._lock:
            available = []
            for t in self._transitions:
                if t.matches(self._state, t.trigger):
                    available.append(t)
            return available

    def trigger(self, event: str, **kwargs: Any) -> bool:
        """触发状态转换。

        查找匹配的转换规则，检查条件，执行状态转换，
        调用退出/进入/转换回调，记录历史日志。

        :param event: 触发事件名称
        :param kwargs: 传递给条件回调和动作回调的额外参数
                       （``reason`` 用于日志记录）
        :return: 是否成功触发转换
        """
        reason = kwargs.pop("reason", "")

        with self._lock:
            # 查找匹配的转换
            matched: StateTransition | None = None
            for t in self._transitions:
                if t.matches(self._state, event):
                    if t.condition is not None:
                        try:
                            if not t.condition(**kwargs):
                                logger.info(
                                    "Transition '%s' blocked by condition for device %s (state=%s)",
                                    event, self._device_id, self._state.value,
                                )
                                return False
                        except Exception as e:
                            logger.warning("Transition condition error for '%s': %s", event, e)
                            return False
                    matched = t
                    break

            if matched is None:
                logger.warning(
                    "No valid transition for event '%s' from state '%s' (device %s)",
                    event, self._state.value, self._device_id,
                )
                return False

            old_state = self._state
            old_duration = time.time() - self._state_enter_time

            # 调用退出回调
            exit_kwargs = {"event": event, "to_state": matched.to_state, **kwargs}
            for cb in self._exit_callbacks:
                try:
                    cb(old_state, exit_kwargs)
                except Exception as e:
                    logger.error("Exit callback error: %s", e)

            # 执行状态转换
            self._state = matched.to_state
            self._state_enter_time = time.time()

            # 记录历史
            entry = StateHistoryEntry(
                timestamp=time.time(),
                from_state=old_state,
                to_state=matched.to_state,
                trigger=event,
                reason=reason,
                duration_in_previous=old_duration,
            )
            self._history.append(entry)

            logger.info(
                "Device %s state transition: %s → %s (trigger=%s, reason=%s)",
                self._device_id, old_state.value, matched.to_state.value, event, reason,
            )

            # 执行转换动作
            if matched.action is not None:
                try:
                    matched.action(**kwargs)
                except Exception as e:
                    logger.error("Transition action error for '%s': %s", event, e)

            # 调用进入回调
            enter_kwargs = {"event": event, "from_state": old_state, **kwargs}
            for cb in self._enter_callbacks:
                try:
                    cb(matched.to_state, enter_kwargs)
                except Exception as e:
                    logger.error("Enter callback error: %s", e)

            # 调用转换通知回调（用于 WebSocket 事件广播）
            for cb in self._transition_callbacks:
                try:
                    cb(entry)
                except Exception as e:
                    logger.error("Transition callback error: %s", e)

            return True

    # -- 回调注册 ---------------------------------------------------------

    def on_enter_state(self, callback: Callable[[DeviceState, dict[str, Any]], Any]) -> None:
        """注册状态进入回调。

        回调签名: ``callback(state: DeviceState, context: dict) -> Any``
        ``context`` 包含 ``event`` (触发事件), ``from_state`` (前一状态) 等。

        :param callback: 回调函数
        """
        with self._lock:
            self._enter_callbacks.append(callback)

    def on_exit_state(self, callback: Callable[[DeviceState, dict[str, Any]], Any]) -> None:
        """注册状态退出回调。

        回调签名: ``callback(state: DeviceState, context: dict) -> Any``
        ``context`` 包含 ``event`` (触发事件), ``to_state`` (目标状态) 等。

        :param callback: 回调函数
        """
        with self._lock:
            self._exit_callbacks.append(callback)

    def on_transition(self, callback: Callable[[StateHistoryEntry], Any]) -> None:
        """注册状态转换通知回调（用于 WebSocket 事件广播）。

        回调签名: ``callback(entry: StateHistoryEntry) -> Any``
        回调可以是同步或异步函数。

        :param callback: 回调函数
        """
        with self._lock:
            self._transition_callbacks.append(callback)

    def remove_callback(self, callback: Callable) -> None:
        """移除已注册的回调函数。"""
        with self._lock:
            for lst in (self._enter_callbacks, self._exit_callbacks, self._transition_callbacks):
                if callback in lst:
                    lst.remove(callback)

    # -- 故障管理 ---------------------------------------------------------

    def set_fault_cleared(self, cleared: bool = True) -> None:
        """设置故障清除标志。"""
        self._fault_cleared = cleared

    def fault(self, reason: str = "") -> bool:
        """快捷方法：触发故障事件。"""
        self._fault_cleared = False
        return self.trigger("fault", reason=reason)

    def device_failure(self, reason: str = "") -> bool:
        """快捷方法：触发设备完全失效事件（从任意状态进入 ERROR）。

        用于故障注入引擎的 DEVICE_FAILURE 类型。

        :param reason: 故障原因描述
        :return: 是否成功触发
        """
        self._fault_cleared = False
        return self.trigger("device_failure", reason=reason)

    def reset(self, fault_cleared: bool = True, reason: str = "") -> bool:
        """快捷方法：触发复位事件。"""
        self._fault_cleared = fault_cleared
        return self.trigger("reset", reason=reason, fault_cleared=fault_cleared)

    # -- 状态对数据的影响 --------------------------------------------------

    @staticmethod
    def get_quality_for_state(state: DeviceState) -> str:
        """根据设备状态返回对应的数据质量标记。

        :param state: 设备状态
        :return: 质量标记字符串
                 - "good"            (RUN)
                 - "bad"             (ERROR)
                 - "out_of_service"  (MAINTENANCE)
                 - "uncertain"       (STOP, STARTING, STOPPING, PROGRAM)
        """
        quality_map = {
            DeviceState.RUN: "good",
            DeviceState.ERROR: "bad",
            DeviceState.MAINTENANCE: "out_of_service",
            DeviceState.STOP: "uncertain",
            DeviceState.STARTING: "uncertain",
            DeviceState.STOPPING: "uncertain",
            DeviceState.PROGRAM: "uncertain",
        }
        return quality_map.get(state, "uncertain")

    def get_quality(self) -> str:
        """返回当前状态对应的数据质量标记。"""
        return self.get_quality_for_state(self._state)

    @staticmethod
    def should_generate_data(state: DeviceState) -> bool:
        """判断当前状态是否应正常生成数据。

        只有 RUN 状态下才正常生成数据。
        """
        return state == DeviceState.RUN

    @staticmethod
    def should_respond_read(state: DeviceState) -> bool:
        """判断当前状态是否应响应外部读请求。

        PROGRAM 模式下不响应外部读请求。
        """
        return state != DeviceState.PROGRAM

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """序列化状态机状态为字典。"""
        with self._lock:
            return {
                "device_id": self._device_id,
                "state": self._state.value,
                "state_duration": round(time.time() - self._state_enter_time, 3),
                "min_startup_time": self._min_startup_time,
                "quality": self.get_quality(),
                "available_transitions": [
                    {"trigger": t.trigger, "to_state": t.to_state.value}
                    for t in self.get_available_transitions()
                ],
                "history_count": len(self._history),
            }

    def get_history_dict(self, count: int = 50) -> list[dict[str, Any]]:
        """返回状态转换历史的字典形式。"""
        entries = self.get_history(count)
        return [
            {
                "timestamp": e.timestamp,
                "from_state": e.from_state.value,
                "to_state": e.to_state.value,
                "trigger": e.trigger,
                "reason": e.reason,
                "duration_in_previous": round(e.duration_in_previous, 3),
            }
            for e in entries
        ]


# ---------------------------------------------------------------------------
#  DeviceStatus 兼容映射
# ---------------------------------------------------------------------------

def device_state_to_status(state: DeviceState):
    """将 DeviceState 映射为 DeviceStatus（向后兼容）。

    映射规则：
      - RUN         → ONLINE
      - ERROR       → ERROR
      - STOP, STARTING, STOPPING, MAINTENANCE, PROGRAM → OFFLINE

    :param state: 设备状态机状态
    :return: DeviceStatus 枚举值
    """
    from protoforge.models.device import DeviceStatus

    mapping = {
        DeviceState.RUN: DeviceStatus.ONLINE,
        DeviceState.ERROR: DeviceStatus.ERROR,
        DeviceState.STOP: DeviceStatus.OFFLINE,
        DeviceState.STARTING: DeviceStatus.OFFLINE,
        DeviceState.STOPPING: DeviceStatus.OFFLINE,
        DeviceState.MAINTENANCE: DeviceStatus.OFFLINE,
        DeviceState.PROGRAM: DeviceStatus.OFFLINE,
    }
    return mapping.get(state, DeviceStatus.OFFLINE)
