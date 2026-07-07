"""工业物理设备行为模型库。

本模块提供七种常见的工业设备物理行为仿真模型，每个模型基于
经典物理方程（热传导、牛顿第二定律、二阶系统响应等）实现，
可嵌入 ProtoForge 的数据生成流水线，为工业协议仿真提供
高保真的物理动态值。

所有模型均继承 BaseBehavior，统一支持:
  - reset()           重置到初始状态
  - get_state()       返回当前全部状态变量
  - to_dict()         序列化为可存储/传输的字典
  - from_dict(cls, d) 反序列化重建实例

典型用法::

    from protoforge.core.behavior_models import ThermalBehavior

    thermal = ThermalBehavior(mass=2.0, specific_heat=900,
                              heat_transfer_coeff=15, ambient_temp=25)
    for _ in range(100):
        temp = thermal.update(power_input=500, dt=0.1)
        print(temp)
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  基类
# ---------------------------------------------------------------------------

class BaseBehavior:
    """所有物理行为模型的抽象基类。

    子类必须实现:
      - ``_init_state()``   初始化内部状态变量
      - ``update(*args, **kwargs)`` 推进一个时间步并返回主输出值

    通用接口方法 ``reset`` / ``get_state`` / ``to_dict`` / ``from_dict``
    在此提供默认实现，子类可通过覆写 ``_params()`` 和 ``_state()``
    来定制序列化内容。
    """

    def __init__(self, **kwargs: Any):
        self._params: dict[str, Any] = dict(kwargs)
        self._init_state()

    # -- 子类需覆写 -------------------------------------------------------

    def _init_state(self) -> None:
        """初始化 / 重置内部状态变量。子类必须实现。"""
        raise NotImplementedError

    def update(self, *args: Any, **kwargs: Any) -> Any:
        """推进一个仿真步并返回主输出值。子类必须实现。"""
        raise NotImplementedError

    # -- 通用接口 ---------------------------------------------------------

    def reset(self) -> None:
        """重置到初始状态。"""
        self._init_state()

    def get_state(self) -> dict[str, Any]:
        """返回当前所有状态变量。"""
        state = self._state()
        state["_type"] = self.__class__.__name__
        return state

    def to_dict(self) -> dict[str, Any]:
        """序列化为可存储的字典。"""
        return {
            "type": self.__class__.__name__,
            "params": dict(self._params),
            "state": self._state(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseBehavior:
        """从字典反序列化重建实例。

        如果 ``data`` 中包含 ``state``，则恢复状态；否则仅用参数构造。
        """
        params = data.get("params", data)
        obj = cls(**params)
        state = data.get("state")
        if state:
            obj._restore_state(state)
        return obj

    # -- 子类可选覆写 -----------------------------------------------------

    def _state(self) -> dict[str, Any]:
        """返回内部状态变量字典（不含 _type）。子类应覆写。"""
        return {}

    def _restore_state(self, state: dict[str, Any]) -> None:
        """从状态字典恢复内部状态。子类应覆写。"""
        pass


# ---------------------------------------------------------------------------
#  1. 热力学模型
# ---------------------------------------------------------------------------

class ThermalBehavior(BaseBehavior):
    """热力学（温度）行为模型。

    基于一阶热传导方程模拟物体温度变化::

        dT/dt = (P_in - h * (T - T_ambient)) / (m * c)

    其中:
      - P_in  为输入功率 (W)
      - h     为热传导系数 (W/K)
      - T     为物体当前温度 (°C)
      - T_ambient 为环境温度 (°C)
      - m     为物体质量 (kg)
      - c     为比热容 (J/(kg·K))

    物理意义：物体温度受加热功率和环境散热共同影响，存在热惯性
    （m·c 越大升温越慢），当温度超过过热保护阈值时自动切断输入。

    :param mass: 物体质量 (kg)
    :param specific_heat: 比热容 (J/(kg·K))
    :param heat_transfer_coeff: 热传导系数 (W/K)
    :param ambient_temp: 环境温度 (°C)
    :param initial_temp: 初始温度 (°C)，默认等于环境温度
    :param overheat_threshold: 过热保护阈值 (°C)，默认 None 不启用
    """

    def __init__(
        self,
        mass: float = 1.0,
        specific_heat: float = 4186.0,
        heat_transfer_coeff: float = 10.0,
        ambient_temp: float = 25.0,
        initial_temp: float | None = None,
        overheat_threshold: float | None = None,
    ):
        self.mass = mass
        self.specific_heat = specific_heat
        self.heat_transfer_coeff = heat_transfer_coeff
        self.ambient_temp = ambient_temp
        self.overheat_threshold = overheat_threshold
        self._initial_temp = initial_temp if initial_temp is not None else ambient_temp
        super().__init__(
            mass=mass,
            specific_heat=specific_heat,
            heat_transfer_coeff=heat_transfer_coeff,
            ambient_temp=ambient_temp,
            initial_temp=self._initial_temp,
            overheat_threshold=overheat_threshold,
        )

    def _init_state(self) -> None:
        self._temperature: float = self._initial_temp
        self._overheated: bool = False
        self._total_energy: float = 0.0
        self._time: float = 0.0

    def update(self, power_input: float, dt: float = 0.1) -> float:
        """推进一个时间步。

        :param power_input: 当前输入功率 (W)
        :param dt: 时间步长 (s)
        :return: 更新后的温度 (°C)
        """
        # 过热保护：超过阈值时切断输入功率
        effective_power = power_input
        if self.overheated():
            effective_power = 0.0
            self._overheated = True

        if self.overheat_threshold is not None and self._temperature >= self.overheat_threshold:
            effective_power = 0.0
            self._overheated = True
        elif self.overheat_threshold is not None and self._temperature < self.overheat_threshold - 5.0:
            # 温度回落到阈值以下 5°C 时解除保护（滞回）
            self._overheated = False

        # 热传导方程: dT = (P_in - h*(T - T_amb)) / (m * c) * dt
        thermal_capacity = self.mass * self.specific_heat
        if thermal_capacity <= 0:
            thermal_capacity = 1e-9  # 防止除零

        dT = (effective_power - self.heat_transfer_coeff * (self._temperature - self.ambient_temp)) / thermal_capacity * dt
        self._temperature += dT
        self._total_energy += effective_power * dt
        self._time += dt
        return round(self._temperature, 6)

    def overheated(self) -> bool:
        """返回是否处于过热保护状态。"""
        return self._overheated

    def _state(self) -> dict[str, Any]:
        return {
            "temperature": self._temperature,
            "overheated": self._overheated,
            "total_energy": self._total_energy,
            "time": self._time,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._temperature = state.get("temperature", self._initial_temp)
        self._overheated = state.get("overheated", False)
        self._total_energy = state.get("total_energy", 0.0)
        self._time = state.get("time", 0.0)


# ---------------------------------------------------------------------------
#  2. 电机模型
# ---------------------------------------------------------------------------

class MotorBehavior(BaseBehavior):
    """电机（旋转运动）行为模型。

    基于牛顿第二定律旋转形式::

        J * dω/dt = T - b * ω

    其中:
      - J 为转动惯量 (kg·m²)
      - ω 为角速度 (rad/s)
      - T 为驱动扭矩 (N·m)
      - b 为粘性摩擦系数 (N·m·s/rad)

    物理意义：电机在扭矩驱动下加速，摩擦力产生阻尼，最终稳态转速
    ω_ss = T / b。当额定转速饱和时，输出被限制在额定值。
    堵转检测：当施加扭矩但转速持续低于阈值时判定为堵转。

    :param inertia: 转动惯量 (kg·m²)
    :param friction: 粘性摩擦系数 (N·m·s/rad)
    :param rated_speed: 额定转速 (rpm)
    :param rated_torque: 额定扭矩 (N·m)
    :param stall_threshold: 堵转转速阈值 (rpm)，低于此值且施加扭矩时判定堵转
    :param stall_time: 堵转持续时间阈值 (s)，超过此时间才确认堵转
    """

    def __init__(
        self,
        inertia: float = 0.01,
        friction: float = 0.1,
        rated_speed: float = 3000.0,
        rated_torque: float = 5.0,
        stall_threshold: float = 10.0,
        stall_time: float = 2.0,
    ):
        self.inertia = inertia
        self.friction = friction
        self.rated_speed = rated_speed
        self.rated_torque = rated_torque
        self.stall_threshold = stall_threshold
        self.stall_time = stall_time
        super().__init__(
            inertia=inertia,
            friction=friction,
            rated_speed=rated_speed,
            rated_torque=rated_torque,
            stall_threshold=stall_threshold,
            stall_time=stall_time,
        )

    def _init_state(self) -> None:
        self._omega: float = 0.0          # 角速度 rad/s
        self._speed_rpm: float = 0.0      # 转速 rpm
        self._stalled: bool = False
        self._stall_timer: float = 0.0
        self._time: float = 0.0

    def update(self, torque: float, dt: float = 0.01) -> float:
        """推进一个时间步。

        :param torque: 驱动扭矩 (N·m)，超过额定扭矩将被限制
        :param dt: 时间步长 (s)
        :return: 更新后的转速 (rpm)
        """
        # 扭矩限幅
        effective_torque = max(-self.rated_torque, min(self.rated_torque, torque))

        # 堵转检测
        current_rpm = self._omega * 60.0 / (2.0 * math.pi)
        if abs(effective_torque) > 0.1 and abs(current_rpm) < self.stall_threshold:
            self._stall_timer += dt
            if self._stall_timer >= self.stall_time:
                self._stalled = True
        else:
            self._stall_timer = max(0.0, self._stall_timer - dt * 0.5)
            if abs(current_rpm) > self.stall_threshold * 2:
                self._stalled = False

        # 堵转时不加速
        if self._stalled:
            effective_torque = 0.0

        # 牛顿第二定律旋转形式: J * dω/dt = T - b * ω
        J = self.inertia if self.inertia > 0 else 1e-9
        d_omega = (effective_torque - self.friction * self._omega) / J * dt
        self._omega += d_omega

        # 额定转速饱和
        rated_omega = self.rated_speed * 2.0 * math.pi / 60.0
        self._omega = max(-rated_omega, min(rated_omega, self._omega))

        self._speed_rpm = self._omega * 60.0 / (2.0 * math.pi)
        self._time += dt
        return round(self._speed_rpm, 6)

    def is_stalled(self) -> bool:
        """返回是否处于堵转状态。"""
        return self._stalled

    def _state(self) -> dict[str, Any]:
        return {
            "omega": self._omega,
            "speed_rpm": self._speed_rpm,
            "stalled": self._stalled,
            "stall_timer": self._stall_timer,
            "time": self._time,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._omega = state.get("omega", 0.0)
        self._speed_rpm = state.get("speed_rpm", 0.0)
        self._stalled = state.get("stalled", False)
        self._stall_timer = state.get("stall_timer", 0.0)
        self._time = state.get("time", 0.0)


# ---------------------------------------------------------------------------
#  3. 压力传感器模型
# ---------------------------------------------------------------------------

class PressureBehavior(BaseBehavior):
    """压力传感器行为模型。

    基于二阶阻尼系统模拟压力传感器的动态响应::

        对阶跃输入的响应近似二阶系统:
        p(t) = p_target * (1 - (1 + δ) * e^(-ζωₙt) * cos(ωd·t))
        其中 ωd = ωₙ√(1-ζ²), δ 与过冲相关

    物理意义：压力传感器对目标压力变化的响应存在延迟和过冲，
    阻尼系数决定振荡衰减速度。

    :param response_time: 响应时间 (s)，即一阶时间常数 τ
    :param overshoot: 过冲比例 (0.0~1.0)，如 0.2 表示 20% 过冲
    :param damping: 阻尼系数 ζ (0~1)，0 为无阻尼，1 为临界阻尼
    :param initial_pressure: 初始压力 (Pa 或任意单位)
    :param noise: 压力波动噪声幅值
    """

    def __init__(
        self,
        response_time: float = 0.5,
        overshoot: float = 0.1,
        damping: float = 0.7,
        initial_pressure: float = 101325.0,
        noise: float = 0.0,
    ):
        self.response_time = response_time
        self.overshoot = overshoot
        self.damping = max(0.01, min(0.999, damping))
        self.initial_pressure = initial_pressure
        self.noise = noise
        super().__init__(
            response_time=response_time,
            overshoot=overshoot,
            damping=damping,
            initial_pressure=initial_pressure,
            noise=noise,
        )

    def _init_state(self) -> None:
        self._pressure: float = self.initial_pressure
        self._target: float = self.initial_pressure
        self._prev_rate: float = 0.0  # 用于二阶系统数值积分
        self._time: float = 0.0

    def update(self, target_pressure: float, dt: float = 0.01) -> float:
        """推进一个时间步。

        :param target_pressure: 目标压力值
        :param dt: 时间步长 (s)
        :return: 更新后的压力读数
        """
        self._target = target_pressure
        tau = max(self.response_time, 1e-6)
        zeta = self.damping

        # 二阶系统: τ²·d²p/dt² + 2ζτ·dp/dt + p = p_target
        # 转换为一阶方程组:
        #   dp/dt = v
        #   dv/dt = (p_target - p - 2ζτ·v) / τ²
        v = self._prev_rate
        error = self._target - self._pressure
        dv = (error - 2.0 * zeta * tau * v) / (tau * tau) * dt
        v += dv
        dp = v * dt

        self._pressure += dp
        self._prev_rate = v
        self._time += dt

        # 过冲效应：在响应初期叠加一个指数衰减的过冲项
        if self.overshoot > 0:
            # 计算与目标的偏差比例，仅在还在趋近目标时产生过冲
            total_error = abs(self._target - self.initial_pressure)
            if total_error > 1e-6:
                remaining = abs(self._target - self._pressure) / total_error
                if remaining > 0.01:
                    overshoot_component = self.overshoot * total_error * remaining * math.exp(-self._time / (tau * 3))
                    if self._target > self.initial_pressure:
                        self._pressure += overshoot_component * 0.1
                    else:
                        self._pressure -= overshoot_component * 0.1

        # 噪声波动
        if self.noise > 0:
            import random as _rng
            self._pressure += _rng.gauss(0, self.noise)

        return round(self._pressure, 6)

    def set_target(self, target: float) -> None:
        """直接设置目标压力（用于阶跃响应测试）。"""
        self._target = target

    def _state(self) -> dict[str, Any]:
        return {
            "pressure": self._pressure,
            "target": self._target,
            "prev_rate": self._prev_rate,
            "time": self._time,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._pressure = state.get("pressure", self.initial_pressure)
        self._target = state.get("target", self.initial_pressure)
        self._prev_rate = state.get("prev_rate", 0.0)
        self._time = state.get("time", 0.0)


# ---------------------------------------------------------------------------
#  4. 流量计模型
# ---------------------------------------------------------------------------

class FlowBehavior(BaseBehavior):
    """流量计行为模型。

    模拟工业流量计的动态响应，支持脉动流、累积计算和精度误差。

    物理意义：
      - 瞬时流量跟随目标流量，叠加脉动波动
      - 累积流量随时间积分
      - 输出值包含精度误差（量程百分比）

    :param accuracy: 测量精度 (%)，如 0.5 表示 ±0.5% 量程误差
    :param pulse_factor: 脉冲系数 (pulses/L)，用于脉冲输出模式
    :param cumulative: 初始累积流量 (L)
    :param pulse_amplitude: 脉动流幅值比例 (0~1)
    :param pulse_frequency: 脉动流频率 (Hz)
    :param max_flow: 最大量程 (L/min)
    """

    def __init__(
        self,
        accuracy: float = 0.5,
        pulse_factor: float = 1000.0,
        cumulative: float = 0.0,
        pulse_amplitude: float = 0.0,
        pulse_frequency: float = 2.0,
        max_flow: float = 100.0,
    ):
        self.accuracy = accuracy
        self.pulse_factor = pulse_factor
        self.cumulative_init = cumulative
        self.pulse_amplitude = pulse_amplitude
        self.pulse_frequency = pulse_frequency
        self.max_flow = max_flow
        super().__init__(
            accuracy=accuracy,
            pulse_factor=pulse_factor,
            cumulative=cumulative,
            pulse_amplitude=pulse_amplitude,
            pulse_frequency=pulse_frequency,
            max_flow=max_flow,
        )

    def _init_state(self) -> None:
        self._instant_flow: float = 0.0       # 瞬时流量 L/min
        self._cumulative: float = self.cumulative_init  # 累积流量 L
        self._pulse_count: int = 0            # 脉冲计数
        self._time: float = 0.0

    def update(self, target_flow: float, dt: float = 0.1) -> float:
        """推进一个时间步。

        :param target_flow: 目标瞬时流量 (L/min)
        :param dt: 时间步长 (s)
        :return: 更新后的瞬时流量读数 (L/min)
        """
        # 限幅
        target_flow = max(0.0, min(self.max_flow, target_flow))

        # 脉动流叠加
        instant = target_flow
        if self.pulse_amplitude > 0 and target_flow > 0:
            pulse = target_flow * self.pulse_amplitude * math.sin(2.0 * math.pi * self.pulse_frequency * self._time)
            instant += pulse
            instant = max(0.0, instant)

        # 精度误差: 基于量程的固定偏差 + 随机噪声
        error_range = self.max_flow * (self.accuracy / 100.0)
        import random as _rng
        systematic_error = error_range * 0.3 * (1.0 if _rng.random() > 0.5 else -1.0)
        random_error = _rng.gauss(0, error_range * 0.1)
        measured = instant + systematic_error + random_error
        measured = max(0.0, measured)

        # 累积流量: L/min -> L/s -> L
        delta_volume = measured / 60.0 * dt
        self._cumulative += delta_volume

        # 脉冲计数
        self._pulse_count += int(delta_volume * self.pulse_factor)

        self._instant_flow = measured
        self._time += dt
        return round(self._instant_flow, 6)

    def get_cumulative(self) -> float:
        """返回累积流量 (L)。"""
        return self._cumulative

    def get_pulse_count(self) -> int:
        """返回脉冲计数。"""
        return self._pulse_count

    def _state(self) -> dict[str, Any]:
        return {
            "instant_flow": self._instant_flow,
            "cumulative": self._cumulative,
            "pulse_count": self._pulse_count,
            "time": self._time,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._instant_flow = state.get("instant_flow", 0.0)
        self._cumulative = state.get("cumulative", self.cumulative_init)
        self._pulse_count = state.get("pulse_count", 0)
        self._time = state.get("time", 0.0)


# ---------------------------------------------------------------------------
#  5. 液位模型
# ---------------------------------------------------------------------------

class LevelBehavior(BaseBehavior):
    """液位（储罐）行为模型。

    基于质量守恒::

        dL/dt = (Q_in - Q_out) / A

    其中:
      - L  为液位高度 (m)
      - Q_in  为入口流量 (m³/s)
      - Q_out 为出口流量 (m³/s)
      - A  为储罐截面积 (m²)

    物理意义：液位随进出流量差线性变化，达到最大液位时溢出报警，
    低于低液位阈值时报警。支持液面波动模拟。

    :param tank_area: 储罐截面积 (m²)
    :param max_level: 最大液位 (m)
    :param inlet_flow: 默认入口流量 (m³/s)
    :param outlet_flow: 默认出口流量 (m³/s)
    :param initial_level: 初始液位 (m)
    :param low_level_threshold: 低液位报警阈值 (m)
    :param wave_amplitude: 液面波动幅值 (m)
    :param wave_frequency: 液面波动频率 (Hz)
    """

    def __init__(
        self,
        tank_area: float = 1.0,
        max_level: float = 5.0,
        inlet_flow: float = 0.01,
        outlet_flow: float = 0.008,
        initial_level: float = 2.0,
        low_level_threshold: float = 0.5,
        wave_amplitude: float = 0.0,
        wave_frequency: float = 0.5,
    ):
        self.tank_area = tank_area
        self.max_level = max_level
        self.inlet_flow = inlet_flow
        self.outlet_flow = outlet_flow
        self.initial_level = initial_level
        self.low_level_threshold = low_level_threshold
        self.wave_amplitude = wave_amplitude
        self.wave_frequency = wave_frequency
        super().__init__(
            tank_area=tank_area,
            max_level=max_level,
            inlet_flow=inlet_flow,
            outlet_flow=outlet_flow,
            initial_level=initial_level,
            low_level_threshold=low_level_threshold,
            wave_amplitude=wave_amplitude,
            wave_frequency=wave_frequency,
        )

    def _init_state(self) -> None:
        self._level: float = self.initial_level
        self._overflow: bool = False
        self._low_alarm: bool = False
        self._time: float = 0.0

    def update(
        self,
        inlet_flow: float | None = None,
        outlet_flow: float | None = None,
        dt: float = 0.1,
    ) -> float:
        """推进一个时间步。

        :param inlet_flow: 入口流量 (m³/s)，None 则使用默认值
        :param outlet_flow: 出口流量 (m³/s)，None 则使用默认值
        :param dt: 时间步长 (s)
        :return: 更新后的液位 (m)
        """
        q_in = inlet_flow if inlet_flow is not None else self.inlet_flow
        q_out = outlet_flow if outlet_flow is not None else self.outlet_flow

        A = self.tank_area if self.tank_area > 0 else 1e-9

        # 液位变化: dL = (Q_in - Q_out) / A * dt
        dL = (q_in - q_out) / A * dt
        self._level += dL

        # 溢出检测
        if self._level >= self.max_level:
            self._level = self.max_level
            self._overflow = True
        else:
            self._overflow = False

        # 低液位报警
        if self._level <= self.low_level_threshold:
            self._low_alarm = True
        else:
            self._low_alarm = False

        # 液位不能为负
        if self._level < 0:
            self._level = 0.0

        self._time += dt

        # 液面波动
        display_level = self._level
        if self.wave_amplitude > 0:
            display_level += self.wave_amplitude * math.sin(2.0 * math.pi * self.wave_frequency * self._time)

        return round(display_level, 6)

    def is_overflow(self) -> bool:
        """返回是否溢出。"""
        return self._overflow

    def is_low_alarm(self) -> bool:
        """返回是否低液位报警。"""
        return self._low_alarm

    def _state(self) -> dict[str, Any]:
        return {
            "level": self._level,
            "overflow": self._overflow,
            "low_alarm": self._low_alarm,
            "time": self._time,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._level = state.get("level", self.initial_level)
        self._overflow = state.get("overflow", False)
        self._low_alarm = state.get("low_alarm", False)
        self._time = state.get("time", 0.0)


# ---------------------------------------------------------------------------
#  6. 阀门模型
# ---------------------------------------------------------------------------

class ValveBehavior(BaseBehavior):
    """阀门行为模型。

    模拟工业调节阀的死区非线性、滞回特性和开度响应延迟。

    物理意义：
      - 死区：控制信号在死区范围内时阀门不动作
      - 滞回：开阀和关阀路径不同，存在机械间隙
      - 开度响应延迟：阀门从当前开度到目标开度需要时间（一阶滞后）

    :param dead_zone: 死区百分比 (0~100)，如 5.0 表示 ±5% 死区
    :param hysteresis: 滞回百分比 (0~100)，如 3.0 表示 3% 滞回
    :param opening_time: 全行程时间 (s)，从 0% 到 100% 所需时间
    :param initial_opening: 初始开度 (%)
    """

    def __init__(
        self,
        dead_zone: float = 5.0,
        hysteresis: float = 3.0,
        opening_time: float = 5.0,
        initial_opening: float = 0.0,
    ):
        self.dead_zone = dead_zone
        self.hysteresis = hysteresis
        self.opening_time = opening_time
        self.initial_opening = initial_opening
        super().__init__(
            dead_zone=dead_zone,
            hysteresis=hysteresis,
            opening_time=opening_time,
            initial_opening=initial_opening,
        )

    def _init_state(self) -> None:
        self._opening: float = self.initial_opening    # 实际开度 %
        self._target: float = self.initial_opening     # 目标开度 %
        self._last_direction: int = 0                   # 上次动作方向: +1 开, -1 关, 0 停
        self._effective_target: float = self.initial_opening  # 经过死区/滞回处理后的有效目标
        self._time: float = 0.0

    def update(self, control_signal: float, dt: float = 0.1) -> float:
        """推进一个时间步。

        :param control_signal: 控制信号 / 目标开度 (%)，0~100
        :param dt: 时间步长 (s)
        :return: 更新后的实际开度 (%)
        """
        control_signal = max(0.0, min(100.0, control_signal))

        # --- 死区处理 ---
        # 如果控制信号与当前有效目标的差值在死区内，则不更新目标
        diff_from_effective = control_signal - self._effective_target
        dead_zone_abs = self.dead_zone
        if abs(diff_from_effective) < dead_zone_abs:
            # 在死区内，保持有效目标不变
            pass
        else:
            # 超出死区，更新有效目标（扣除死区宽度）
            current_direction = 1 if diff_from_effective > 0 else -1

            # --- 滞回处理 ---
            # 如果方向改变，需要额外越过滞回宽度才更新
            if self._last_direction != 0 and current_direction != self._last_direction:
                # 方向反转，需要额外越过滞回
                hysteresis_abs = self.hysteresis
                if abs(diff_from_effective) < dead_zone_abs + hysteresis_abs:
                    # 还没越过滞回，不更新
                    pass
                else:
                    self._effective_target = control_signal
                    self._last_direction = current_direction
            else:
                self._effective_target = control_signal
                self._last_direction = current_direction

        self._target = control_signal

        # --- 开度响应延迟（一阶滞后）---
        # 阀门以恒定速度移动：100% / opening_time 秒
        if self.opening_time > 0:
            max_rate = 100.0 / self.opening_time  # %/s
        else:
            max_rate = float("inf")

        diff = self._effective_target - self._opening
        max_change = max_rate * dt

        if abs(diff) <= max_change:
            self._opening = self._effective_target
        else:
            self._opening += max_change if diff > 0 else -max_change

        self._opening = max(0.0, min(100.0, self._opening))
        self._time += dt
        return round(self._opening, 6)

    def _state(self) -> dict[str, Any]:
        return {
            "opening": self._opening,
            "target": self._target,
            "effective_target": self._effective_target,
            "last_direction": self._last_direction,
            "time": self._time,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._opening = state.get("opening", self.initial_opening)
        self._target = state.get("target", self.initial_opening)
        self._effective_target = state.get("effective_target", self.initial_opening)
        self._last_direction = state.get("last_direction", 0)
        self._time = state.get("time", 0.0)


# ---------------------------------------------------------------------------
#  7. PID 控制器
# ---------------------------------------------------------------------------

class PIDController(BaseBehavior):
    """PID 控制器行为模型。

    经典 PID 控制算法，支持抗积分饱和、微分先行和输出限幅。

    控制方程::

        u(t) = Kp·e + Ki·∫e dt + Kd·de/dt

    其中 e = setpoint - measurement (偏差)

    特性：
      - 抗积分饱和（anti-windup）：当输出达到限幅时停止积分累加
      - 微分先行（derivative on measurement）：对测量值而非偏差求微分，
        避免设定值跳变引起微分冲击
      - 输出限幅：限制控制输出范围

    :param Kp: 比例增益
    :param Ki: 积分增益
    :param Kd: 微分增益
    :param setpoint: 设定值
    :param output_limit: 输出限幅 (min, max) 元组，None 表示不限幅
    :param initial_output: 初始输出值
    """

    def __init__(
        self,
        Kp: float = 1.0,
        Ki: float = 0.1,
        Kd: float = 0.01,
        setpoint: float = 50.0,
        output_limit: tuple[float, float] | None = (0.0, 100.0),
        initial_output: float = 0.0,
    ):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.setpoint = setpoint
        self.output_limit = output_limit
        self.initial_output = initial_output
        super().__init__(
            Kp=Kp,
            Ki=Ki,
            Kd=Kd,
            setpoint=setpoint,
            output_limit=output_limit,
            initial_output=initial_output,
        )

    def _init_state(self) -> None:
        self._integral: float = 0.0
        self._prev_measurement: float | None = None  # 微分先行：跟踪测量值
        self._output: float = self.initial_output
        self._error: float = 0.0
        self._time: float = 0.0
        self._saturated: bool = False  # 是否处于饱和状态

    def update(self, measurement: float, dt: float = 0.1) -> float:
        """推进一个时间步。

        :param measurement: 当前过程测量值 (PV)
        :param dt: 时间步长 (s)
        :return: 控制输出 (CV)
        """
        if dt <= 0:
            dt = 1e-6

        error = self.setpoint - measurement
        self._error = error

        # 比例项
        p_term = self.Kp * error

        # 积分项（抗积分饱和）
        # 仅当未饱和或饱和方向与误差方向相反时才累加积分
        prospective_integral = self._integral + error * dt
        p_term + self.Ki * prospective_integral

        if self.output_limit is not None:
            out_min, out_max = self.output_limit
            # 预计算含微分项的输出
            d_term = 0.0
            if self._prev_measurement is not None:
                # 微分先行：对测量值求负微分
                d_term = -self.Kd * (measurement - self._prev_measurement) / dt
            prospective_output_full = p_term + self.Ki * prospective_integral + d_term

            if prospective_output_full > out_max and error > 0:
                # 正向饱和且误差为正 → 不积分（抗饱和）
                self._saturated = True
            elif prospective_output_full < out_min and error < 0:
                # 负向饱和且误差为负 → 不积分（抗饱和）
                self._saturated = True
            else:
                self._integral = prospective_integral
                self._saturated = False
        else:
            self._integral = prospective_integral
            self._saturated = False

        # 微分项（微分先行：对测量值求导）
        d_term = 0.0
        if self._prev_measurement is not None:
            d_term = -self.Kd * (measurement - self._prev_measurement) / dt

        # 总输出
        output = p_term + self.Ki * self._integral + d_term

        # 输出限幅
        if self.output_limit is not None:
            out_min, out_max = self.output_limit
            output = max(out_min, min(out_max, output))

        self._output = output
        self._prev_measurement = measurement
        self._time += dt
        return round(output, 6)

    def set_setpoint(self, setpoint: float) -> None:
        """更新设定值。"""
        self.setpoint = setpoint

    def is_saturated(self) -> bool:
        """返回是否处于饱和状态。"""
        return self._saturated

    def _state(self) -> dict[str, Any]:
        return {
            "integral": self._integral,
            "prev_measurement": self._prev_measurement,
            "output": self._output,
            "error": self._error,
            "setpoint": self.setpoint,
            "saturated": self._saturated,
            "time": self._time,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        self._integral = state.get("integral", 0.0)
        self._prev_measurement = state.get("prev_measurement")
        self._output = state.get("output", self.initial_output)
        self._error = state.get("error", 0.0)
        self.setpoint = state.get("setpoint", self.setpoint)
        self._saturated = state.get("saturated", False)
        self._time = state.get("time", 0.0)

    def to_dict(self) -> dict[str, Any]:
        """序列化，处理 output_limit 元组。"""
        data = super().to_dict()
        if self.output_limit is not None:
            data["params"]["output_limit"] = list(self.output_limit)
        else:
            data["params"]["output_limit"] = None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PIDController:
        """反序列化，处理 output_limit 列表转元组。"""
        params = dict(data.get("params", data))
        ol = params.get("output_limit")
        if ol is not None and isinstance(ol, list):
            params["output_limit"] = tuple(ol)
        obj = cls(**params)
        state = data.get("state")
        if state:
            obj._restore_state(state)
        return obj


# ---------------------------------------------------------------------------
#  工厂注册表
# ---------------------------------------------------------------------------

#: 行为模型类型注册表，名称 → 类对象
BEHAVIOR_REGISTRY: dict[str, type[BaseBehavior]] = {
    "thermal": ThermalBehavior,
    "motor": MotorBehavior,
    "pressure": PressureBehavior,
    "flow": FlowBehavior,
    "level": LevelBehavior,
    "valve": ValveBehavior,
    "pid": PIDController,
}


def create_behavior(config: dict[str, Any] | str) -> BaseBehavior | None:
    """根据配置创建行为模型实例。

    支持两种配置格式：

    1. 字典格式::

        {"behavior": "thermal", "params": {"mass": 10, ...}, "input": 500, "dt": 0.1}

    2. 字符串格式::

        "thermal:mass=10,specific_heat=900,heat_transfer_coeff=15,ambient_temp=25"

    :param config: 配置字典或字符串
    :return: 行为模型实例，配置无效时返回 None
    """
    if isinstance(config, str):
        return _create_from_string(config)

    if not isinstance(config, dict):
        logger.warning("Invalid behavior config type: %s", type(config))
        return None

    behavior_type = config.get("behavior", "").lower()
    cls = BEHAVIOR_REGISTRY.get(behavior_type)
    if cls is None:
        logger.warning("Unknown behavior type: '%s'. Available: %s", behavior_type, list(BEHAVIOR_REGISTRY.keys()))
        return None

    params = config.get("params", {})
    # 过滤掉非构造参数，避免 TypeError
    try:
        return cls(**params)
    except TypeError as e:
        logger.warning("Failed to create behavior '%s' with params %s: %s", behavior_type, params, e)
        # 尝试只用基本参数
        return cls()


def _create_from_string(config_str: str) -> BaseBehavior | None:
    """从字符串配置创建行为模型。

    格式: ``behavior_type:param1=value1,param2=value2,...``

    例如: ``thermal:mass=10,specific_heat=900,ambient_temp=25``
    """
    try:
        parts = config_str.split(":", 1)
        behavior_type = parts[0].strip().lower()
        cls = BEHAVIOR_REGISTRY.get(behavior_type)
        if cls is None:
            logger.warning("Unknown behavior type in string: '%s'", behavior_type)
            return None

        params: dict[str, Any] = {}
        if len(parts) > 1:
            for pair in parts[1].split(","):
                pair = pair.strip()
                if "=" not in pair:
                    continue
                key, value = pair.split("=", 1)
                key = key.strip()
                value = value.strip()
                # 尝试转换为数值
                try:
                    if "." in value or "e" in value.lower():
                        params[key] = float(value)
                    else:
                        params[key] = int(value)
                except ValueError:
                    # 布尔值
                    if value.lower() in ("true", "false"):
                        params[key] = value.lower() == "true"
                    else:
                        params[key] = value

        return cls(**params)
    except Exception as e:
        logger.warning("Failed to parse behavior config string '%s': %s", config_str, e)
        return None


def get_behavior_input(config: dict[str, Any]) -> tuple[Any, float]:
    """从配置中提取行为模型的输入参数和时间步长。

    :param config: 行为配置字典
    :return: (input_value, dt) 元组
    """
    input_value = config.get("input", 0.0)
    dt = config.get("dt", 0.1)

    # 支持 input 作为不同类型
    if isinstance(input_value, (list, tuple)):
        # 如果是列表/元组，取第一个作为输入（适用于多参数模型）
        return input_value[0] if input_value else 0.0, dt

    return input_value, dt
