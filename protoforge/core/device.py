"""Device simulation model with state machine and point management."""

import asyncio
import logging
import time
from typing import Any

from protoforge.core.control_loop import ControlLoopConfig, ControlLoopManager
from protoforge.core.fault import (
    DeviceFailureException,
    FaultConfig,
    FaultInjector,
    FaultType,
)
from protoforge.core.generator import DataGenerator
from protoforge.core.quality import QualitySystem
from protoforge.core.state_machine import DeviceState, DeviceStateMachine, device_state_to_status
from protoforge.models.device import DeviceConfig, DeviceStatus, GeneratorType, PointConfig, PointValue

logger = logging.getLogger(__name__)


class DeviceInstance:
    """设备实例，集成状态机管理设备生命周期。

    内部使用 DeviceStateMachine 替代原来的简单 OFFLINE/ONLINE/ERROR 三态，
    同时通过 ``status`` 属性保持对 DeviceStatus 的向后兼容。

    状态机流程:
      - ``start()``: 触发 "start" 事件 (STOP → STARTING)
      - ``tick()``:  在 STARTING 状态下达到最小启动时间后自动完成启动 (STARTING → RUN)
      - ``stop()``:  触发 "stop" 事件 (RUN → STOPPING → STOP)
      - ``fault()``: 触发 "fault" 事件 (任意运行态 → ERROR)

    状态对数据的影响:
      - STOP / STARTING / STOPPING: 数据质量为 "uncertain"
      - RUN:                        数据质量为 "good"，正常生成数据
      - ERROR:                      数据质量为 "bad"，输出安全值
      - MAINTENANCE:                数据质量为 "out_of_service"
      - PROGRAM:                    不响应外部读请求
    """

    def __init__(self, config: DeviceConfig, generator: DataGenerator):
        self.config = config
        self._generator = generator
        self._point_values: dict[str, Any] = {}
        self._point_configs: dict[str, PointConfig] = {}
        self._lock = asyncio.Lock()

        # 初始化状态机
        self._state_machine = DeviceStateMachine(
            initial_state=DeviceState.STOP,
            min_startup_time=config.protocol_config.get("min_startup_time", 2.0),
            device_id=config.id,
        )
        self._start_time: float | None = None

        # 配置：STOP 状态下输出是否归零
        self._zero_output_on_stop: bool = config.protocol_config.get("zero_output_on_stop", False)
        # ERROR 状态下的安全值
        self._safe_values: dict[str, Any] = config.protocol_config.get("safe_values", {})

        # 故障注入器：设备级故障管理
        self._fault_injector = FaultInjector(
            device_id=config.id,
            on_fault_activated=self._on_fault_activated,
            on_fault_deactivated=self._on_fault_deactivated,
        )
        # 将故障注入器关联到数据生成器
        if hasattr(generator, "set_fault_injector"):
            generator.set_fault_injector(self._fault_injector)

        # 控制回路管理器：从 protocol_config["control_loops"] 初始化
        self._control_loops: ControlLoopManager | None = None
        loop_configs_raw = config.protocol_config.get("control_loops")
        if loop_configs_raw and isinstance(loop_configs_raw, list):
            self._control_loops = ControlLoopManager()
            for lc in loop_configs_raw:
                try:
                    cfg = ControlLoopConfig.from_dict(lc) if isinstance(lc, dict) else lc
                    self._control_loops.add_loop(cfg)
                except Exception as e:
                    logger.warning("Failed to add control loop on device %s: %s", config.id, e)
            logger.info(
                "Device %s: initialized %d control loop(s)",
                config.id, self._control_loops.loop_count,
            )

        # 注册状态机回调
        self._register_state_callbacks()

        # 初始化点位
        for point in config.points:
            self._point_configs[point.name] = point
            if point.fixed_value is not None:
                self._point_values[point.name] = point.fixed_value
            else:
                self._point_values[point.name] = self._generator.generate(point)

    def _register_state_callbacks(self) -> None:
        """注册状态机内部回调。"""
        def on_enter_starting(state: DeviceState, context: dict[str, Any]) -> None:
            self._start_time = time.time()
            logger.info("Device %s entering STARTING state", self.config.id)

        def on_enter_run(state: DeviceState, context: dict[str, Any]) -> None:
            self._start_time = time.time()
            logger.info("Device %s entered RUN state", self.config.id)

        def on_enter_stop(state: DeviceState, context: dict[str, Any]) -> None:
            self._start_time = None
            if self._zero_output_on_stop:
                for name in self._point_values:
                    self._point_values[name] = 0
            logger.info("Device %s entered STOP state", self.config.id)

        def on_enter_error(state: DeviceState, context: dict[str, Any]) -> None:
            # 设置安全值
            for name, safe_val in self._safe_values.items():
                if name in self._point_values:
                    self._point_values[name] = safe_val
            logger.warning("Device %s entered ERROR state: %s", self.config.id, context.get("reason", ""))

        self._state_machine.on_enter_state(on_enter_starting)
        self._state_machine.on_enter_state(on_enter_run)
        self._state_machine.on_enter_state(on_enter_stop)
        self._state_machine.on_enter_state(on_enter_error)

    def _on_fault_activated(self, fault) -> None:
        """故障激活回调：DEVICE_FAILURE 自动触发状态机 fault 事件。

        兼容 Fault 和 FaultConfig 两种类型。
        """
        ft = fault.fault_type
        desc = getattr(fault, "description", "") or fault.fault_id
        if ft == FaultType.DEVICE_FAILURE:
            logger.warning(
                "Device %s: DEVICE_FAILURE fault activated, triggering state machine fault",
                self.config.id,
            )
            self._state_machine.fault(reason=f"Fault injection: {desc}")

    def _on_fault_deactivated(self, fault) -> None:
        """故障解除回调：DEVICE_FAILURE 解除时自动复位。

        兼容 Fault 和 FaultConfig 两种类型。
        """
        if fault.fault_type == FaultType.DEVICE_FAILURE:
            logger.info(
                "Device %s: DEVICE_FAILURE fault deactivated, auto-resetting",
                self.config.id,
            )
            self._state_machine.set_fault_cleared(True)
            self._state_machine.trigger("reset", reason="Device failure fault cleared")

    # -- 属性 -------------------------------------------------------------

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def protocol(self) -> str:
        return self.config.protocol

    @property
    def points(self) -> list[PointConfig]:
        return self.config.points

    @property
    def protocol_config(self) -> dict[str, Any]:
        return self.config.protocol_config

    @property
    def status(self) -> DeviceStatus:
        """向后兼容：将状态机状态映射为 DeviceStatus。"""
        return device_state_to_status(self._state_machine.get_state())

    @property
    def device_state(self) -> DeviceState:
        """返回状态机的详细设备状态。"""
        return self._state_machine.get_state()

    @property
    def state_machine(self) -> DeviceStateMachine:
        """返回状态机实例（用于高级操作和查询）。"""
        return self._state_machine

    @property
    def fault_injector(self) -> FaultInjector:
        """返回故障注入器实例。"""
        return self._fault_injector

    @property
    def control_loops(self) -> ControlLoopManager | None:
        """返回控制回路管理器实例（未配置时为 None）。"""
        return self._control_loops

    # -- 状态控制 ---------------------------------------------------------

    def start(self) -> None:
        """启动设备：触发状态机 "start" 事件 (STOP → STARTING)。

        启动后设备进入 STARTING 状态，在 ``tick()`` 中
        达到最小启动时间后自动转为 RUN 状态。
        """
        if not self._state_machine.trigger("start", reason="manual start"):
            # 可能已经在 STARTING 或 RUN 状态，记录但不报错
            logger.debug(
                "Device %s start trigger ignored (current state: %s)",
                self.config.id, self._state_machine.get_state().value,
            )

    def stop(self) -> None:
        """停止设备：触发状态机停止流程。

        如果设备在 RUN/STARTING 状态，先转为 STOPPING，
        然后立即完成停止转为 STOP。
        """
        current = self._state_machine.get_state()
        if current in (DeviceState.RUN, DeviceState.STARTING):
            self._state_machine.trigger("stop", reason="manual stop")
            # 立即完成停止过程
            self._state_machine.trigger("stop_complete", reason="stop completed")
        elif current == DeviceState.STOPPING:
            self._state_machine.trigger("stop_complete", reason="stop completed")
        elif current == DeviceState.ERROR:
            # 错误状态下直接归位 STOP
            self._state_machine.set_fault_cleared(True)
            self._state_machine.trigger("reset", reason="reset from error on stop")
        elif current in (DeviceState.MAINTENANCE, DeviceState.PROGRAM):
            # 维护/编程模式下直接回到 STOP
            if current == DeviceState.MAINTENANCE:
                self._state_machine.trigger("maintenance_complete", reason="maintenance ended on stop")
            else:
                self._state_machine.trigger("program_exit", reason="program exit on stop")

    def fault(self, reason: str = "") -> None:
        """触发设备故障：触发状态机 "fault" 事件。

        :param reason: 故障原因描述
        """
        self._state_machine.fault(reason=reason)

    def reset(self, reason: str = "") -> bool:
        """复位故障：触发状态机 "reset" 事件。

        :param reason: 复位原因描述
        :return: 是否成功复位
        """
        return self._state_machine.reset(fault_cleared=True, reason=reason)

    def enter_maintenance(self, reason: str = "") -> bool:
        """进入维护模式。"""
        return self._state_machine.trigger("maintenance", reason=reason)

    def exit_maintenance(self, reason: str = "") -> bool:
        """退出维护模式。"""
        return self._state_machine.trigger("maintenance_complete", reason=reason)

    def enter_program_mode(self, reason: str = "") -> bool:
        """进入编程模式。"""
        return self._state_machine.trigger("program_mode", reason=reason)

    def exit_program_mode(self, reason: str = "") -> bool:
        """退出编程模式。"""
        return self._state_machine.trigger("program_exit", reason=reason)

    # -- 数据生成与读取 ---------------------------------------------------

    async def tick(self) -> None:
        """设备 tick：处理状态机自动转换和数据生成。

        - 在 STARTING 状态下，达到最小启动时间后自动转为 RUN
        - 在 RUN 状态下，正常生成数据
        - 数据生成后执行控制回路，将输出写入对应点位
        - 数据生成时捕获 DeviceFailureException，自动触发故障事件
        - 其他状态不生成新数据
        """
        current = self._state_machine.get_state()

        # STARTING → RUN 自动转换
        if current == DeviceState.STARTING and self._state_machine.can_trigger("startup_complete"):
            self._state_machine.trigger("startup_complete", reason="startup time reached")
            current = DeviceState.RUN

        # 只有 RUN 状态下才生成数据
        if not DeviceStateMachine.should_generate_data(current):
            return

        async with self._lock:
            for name, point in self._point_configs.items():
                if point.generator_type != GeneratorType.FIXED:
                    try:
                        self._point_values[name] = self._generator.generate(point)
                    except DeviceFailureException:
                        # DEVICE_FAILURE 故障：数据生成失败，触发状态机故障
                        logger.warning(
                            "Device %s: DeviceFailureException during tick for point %s",
                            self.config.id, name,
                        )
                        # 确保只触发一次 fault
                        if self._state_machine.get_state() != DeviceState.ERROR:
                            self._state_machine.fault(reason=f"Device failure on point {name}")
                        # 设置安全值
                        if name in self._safe_values:
                            self._point_values[name] = self._safe_values[name]
                        break  # 跳出循环，不再生成后续点位

            # 执行控制回路：在数据生成之后，将 PID 输出写入对应点位
            if self._control_loops is not None and self._control_loops.loop_count > 0:
                dt = self.config.protocol_config.get("control_loop_dt", 0.1)
                try:
                    outputs = self._control_loops.tick(self, dt)
                    for point_name, value in outputs.items():
                        if point_name in self._point_values:
                            self._point_values[point_name] = value
                        else:
                            # 控制输出点位不在预设点位中，动态添加
                            self._point_values[point_name] = value
                            logger.debug(
                                "Device %s: control loop wrote to new point %s = %.4f",
                                self.config.id, point_name, value,
                            )
                except Exception as e:
                    logger.warning("Device %s: control loop tick error: %s", self.config.id, e)

    def read_point(self, point_name: str) -> PointValue | None:
        """读取单个点位值。

        根据状态机状态返回不同质量标记：
        - RUN: quality="good"（被故障注入器覆盖时可能降级）
        - ERROR: quality="bad"
        - MAINTENANCE: quality="out_of_service"
        - PROGRAM: 返回 None（不响应读请求）
        - STOP/STARTING/STOPPING: quality="uncertain"

        读取时应用故障注入器效果：
        - 故障注入器的 ``apply()`` 返回修改后的值和质量标记
        - 质量标记取状态机质量和故障质量中更严重的一个
        - 使用 QualitySystem.compute() 计算 OPC UA 质量码

        :param point_name: 点位名称
        :return: PointValue 或 None（PROGRAM 模式下）
        """
        current = self._state_machine.get_state()

        # PROGRAM 模式不响应外部读请求
        if not DeviceStateMachine.should_respond_read(current):
            return None

        if point_name not in self._point_values:
            return None

        raw_value = self._point_values.get(point_name)
        state_quality = self._state_machine.get_quality()

        # 检查通信故障
        comm_disconnected, _delay = self._fault_injector.check_comm_fault(self.config.id)
        comm_status = "timeout" if comm_disconnected else "ok"

        # 应用故障注入器效果
        fault_active = False
        sensor_stuck = False
        try:
            faulted_value, fault_quality = self._fault_injector.apply(point_name, raw_value)
            if fault_quality != "good":
                fault_active = True
            # 检查是否有 SENSOR_STUCK 故障
            for f in self._fault_injector.active_faults:
                if f.is_active_now(time.time()) and f.fault_type == FaultType.SENSOR_STUCK and (f.target == "*" or f.target == point_name):
                        sensor_stuck = True
                        break
        except DeviceFailureException:
            # DEVICE_FAILURE 故障：返回安全值，质量为 bad
            safe_val = self._safe_values.get(point_name, raw_value)
            qcode = QualitySystem.compute(
                device_state=current.value, comm_status=comm_status,
                fault_active=True, sensor_stuck=False,
            )
            return PointValue(
                name=point_name,
                value=safe_val,
                timestamp=time.time(),
                quality="bad",
                quality_code=int(qcode),
            )

        # 质量降级：取状态机质量和故障质量中更严重的一个
        final_quality = self._worst_quality(state_quality, fault_quality)

        # 使用 QualitySystem 计算 OPC UA 质量码
        qcode = QualitySystem.compute(
            device_state=current.value,
            comm_status=comm_status,
            fault_active=fault_active,
            sensor_stuck=sensor_stuck,
        )
        # 如果状态机或故障质量更严重，降级质量码
        qcode_str = QualitySystem.to_string(qcode)
        if QualitySystem._SEVERITY.get(final_quality, 0) > QualitySystem._SEVERITY.get(qcode_str, 0):
            qcode = QualitySystem.from_string(final_quality)

        return PointValue(
            name=point_name,
            value=faulted_value,
            timestamp=time.time(),
            quality=final_quality,
            quality_code=int(qcode),
        )

    def read_all_points(self) -> list[PointValue]:
        """读取所有点位值。

        读取时应用故障注入器效果，与 ``read_point()`` 一致。
        使用 QualitySystem.compute() 计算每个点位的 OPC UA 质量码。

        :return: PointValue 列表（PROGRAM 模式下返回空列表）
        """
        current = self._state_machine.get_state()

        # PROGRAM 模式不响应外部读请求
        if not DeviceStateMachine.should_respond_read(current):
            return []

        # 检查通信故障
        comm_disconnected, _delay = self._fault_injector.check_comm_fault(self.config.id)
        comm_status = "timeout" if comm_disconnected else "ok"

        result = []
        now = time.time()
        state_quality = self._state_machine.get_quality()

        # 预计算所有活跃的 SENSOR_STUCK 目标
        stuck_targets: set[str] = set()
        for f in self._fault_injector.active_faults:
            if f.is_active_now(now) and f.fault_type == FaultType.SENSOR_STUCK:
                stuck_targets.add(f.target)

        for name, value in list(self._point_values.items()):  # FIXED-H08: 使用list()快照避免迭代时字典被修改
            fault_active = False
            sensor_stuck = name in stuck_targets or "*" in stuck_targets
            # 应用故障注入器效果
            try:
                faulted_value, fault_quality = self._fault_injector.apply(name, value)
                if fault_quality != "good":
                    fault_active = True
            except DeviceFailureException:
                faulted_value = self._safe_values.get(name, value)
                fault_quality = "bad"
                fault_active = True
            final_quality = self._worst_quality(state_quality, fault_quality)

            # 使用 QualitySystem 计算 OPC UA 质量码
            qcode = QualitySystem.compute(
                device_state=current.value,
                comm_status=comm_status,
                fault_active=fault_active,
                sensor_stuck=sensor_stuck,
            )
            qcode_str = QualitySystem.to_string(qcode)
            if QualitySystem._SEVERITY.get(final_quality, 0) > QualitySystem._SEVERITY.get(qcode_str, 0):
                qcode = QualitySystem.from_string(final_quality)

            result.append(
                PointValue(
                    name=name,
                    value=faulted_value,
                    timestamp=now,
                    quality=final_quality,
                    quality_code=int(qcode),
                )
            )
        return result

    def get_point_config(self, point_name: str):  # FIXED-M07: 提供公开方法访问点配置，避免直接访问私有属性
        return self._point_configs.get(point_name)

    def get_point_values_snapshot(self) -> dict[str, Any]:
        """返回点位值的快照字典（浅拷贝）。

        供引擎 tick 循环和控制回路等内部模块使用，
        避免直接访问 ``_point_values`` 私有属性。

        :return: 点位名称→值的字典副本
        """
        return dict(self._point_values)

    def get_raw_point_value(self, point_name: str) -> Any:
        """获取点位的原始值（未经故障注入处理）。

        供控制回路读取测量值和设定值使用，
        避免直接访问 ``_point_values`` 私有属性。

        :param point_name: 点位名称
        :return: 原始值，点位不存在时返回 ``None``
        """
        return self._point_values.get(point_name)

    def set_point_value_internal(self, point_name: str, value: Any) -> None:
        """直接设置点位值（内部控制回路输出专用）。

        供控制回路管理器在 ``tick()`` 中将控制器输出写回设备使用，
        避免直接访问 ``_point_values`` 私有属性。
        此方法不经过状态机检查和写入范围校验，
        **仅供内部模块使用**，外部写入应通过 ``write_point()``。

        :param point_name: 点位名称
        :param value: 要设置的值
        """
        if point_name in self._point_values:
            self._point_values[point_name] = value

    async def write_point(self, point_name: str, value: Any) -> bool:
        """写入点位值。

        在 ERROR、MAINTENANCE 和 PROGRAM 状态下拒绝写入。
        如果点位有物理模型（PHYSICAL 生成器），写入值会更新物理模型的输入参数。
        如果点位是某个控制回路的设定值点位，写入值会更新控制回路的目标设定值。
        """
        current = self._state_machine.get_state()

        # ERROR、MAINTENANCE 和 PROGRAM 状态下拒绝写入
        if current in (DeviceState.ERROR, DeviceState.MAINTENANCE, DeviceState.PROGRAM):
            logger.warning(
                "Write rejected for point %s on device %s (state=%s)",
                point_name, self.config.id, current.value,
            )
            return False

        if point_name not in self._point_configs:
            return False
        point = self._point_configs[point_name]
        if point.access not in ("w", "rw"):
            return False
        if point.min_value is not None and point.max_value is not None:
            try:
                num_val = float(value)
                if num_val < point.min_value or num_val > point.max_value:
                    logger.warning(
                        "Write value %s out of range [%s, %s] for point %s, clamping",
                        value, point.min_value, point.max_value, point_name,
                    )
                    value = max(point.min_value, min(point.max_value, num_val))
            except (ValueError, TypeError):
                logger.debug("Range check skipped for point %s: value=%s is not numeric", point_name, value)
        async with self._lock:
            self._point_values[point_name] = value

            # 如果有物理模型（PHYSICAL 生成器），更新输入参数
            if point.generator_type == GeneratorType.PHYSICAL:
                try:
                    if point.generator_config is None:
                        point.generator_config = {}
                    point.generator_config["input"] = float(value)
                    logger.debug(
                        "Updated physical model input for point %s on device %s: %s",
                        point_name, self.config.id, value,
                    )
                except (ValueError, TypeError):
                    logger.debug(
                        "Physical model input update skipped for point %s: value=%s is not numeric",
                        point_name, value,
                    )

            # 如果有控制回路设定值，更新设定值
            if self._control_loops is not None:
                for loop in self._control_loops.get_all_loops().values():
                    if loop.config.setpoint_point == point_name:
                        try:
                            sp = float(value)
                            loop._pid.set_setpoint(sp)
                            loop._last_setpoint = sp
                            logger.debug(
                                "Updated control loop %s setpoint to %s (point=%s)",
                                loop.config.loop_id, sp, point_name,
                            )
                        except (ValueError, TypeError):
                            logger.debug(
                                "Control loop setpoint update skipped for point %s: value=%s is not numeric",
                                point_name, value,
                            )
        return True

    # -- 状态查询 ---------------------------------------------------------

    def get_state_info(self) -> dict[str, Any]:
        """返回状态机的详细信息（用于 API 响应）。"""
        return self._state_machine.to_dict()

    def get_state_history(self, count: int = 50) -> list[dict[str, Any]]:
        """返回状态转换历史。"""
        return self._state_machine.get_history_dict(count)

    # -- 故障管理 ---------------------------------------------------------

    def inject_fault(self, config: FaultConfig) -> str:
        """注入故障。

        :param config: 故障配置
        :return: 故障 ID
        """
        if not config.target_device:
            config.target_device = self.config.id
        return self._fault_injector.add_fault(config)

    def remove_fault(self, fault_id: str) -> bool:
        """移除故障。"""
        return self._fault_injector.remove_fault(fault_id)

    def activate_fault(self, fault_id: str) -> bool:
        """激活故障。"""
        return self._fault_injector.activate_fault(fault_id)

    def deactivate_fault(self, fault_id: str) -> bool:
        """停用故障。"""
        return self._fault_injector.deactivate_fault(fault_id)

    def clear_all_faults(self) -> int:
        """清除所有故障。"""
        return self._fault_injector.clear_all_faults()

    def get_active_faults(self) -> list[FaultConfig]:
        """返回活跃故障列表。"""
        return self._fault_injector.get_active_faults()

    def get_all_faults(self) -> list[FaultConfig]:
        """返回所有故障列表。"""
        return self._fault_injector.get_all_faults()

    def get_fault_info(self) -> dict[str, Any]:
        """返回故障注入器状态信息。"""
        return self._fault_injector.to_dict()

    def check_comm_fault(self) -> tuple[bool, float]:
        """检查通信故障，返回 (是否断连, 延迟毫秒)。

        协议服务器在响应请求前可调用此方法判断是否应答。

        :return: (is_disconnected, delay_ms)
        """
        return self._fault_injector.check_comm_fault(self.config.id)

    @staticmethod
    def _worst_quality(q1: str, q2: str) -> str:
        """取两个质量标记中更严重的一个。

        严重程度: bad > out_of_service > uncertain > good
        """
        return QualitySystem.worst_str(q1, q2)

    # -- 控制回路管理 -----------------------------------------------------

    def add_control_loop(self, config: ControlLoopConfig) -> str:
        """添加控制回路。

        如果设备尚未初始化控制回路管理器，会自动创建。

        :param config: 回路配置
        :return: 回路 ID
        """
        if self._control_loops is None:
            self._control_loops = ControlLoopManager()
        return self._control_loops.add_loop(config)

    def remove_control_loop(self, loop_id: str) -> bool:
        """移除控制回路。

        :param loop_id: 回路 ID
        :return: 是否成功移除
        """
        if self._control_loops is None:
            return False
        return self._control_loops.remove_loop(loop_id)

    def get_control_loop_info(self) -> dict[str, Any]:
        """返回控制回路状态信息（用于 API 响应）。"""
        if self._control_loops is None:
            return {"loop_count": 0, "loops": [], "loop_states": {}}
        return self._control_loops.to_dict()
