"""闭环控制回路框架。

将 PIDController 集成到设备仿真中，支持三种工业常见控制结构：

  - **简单回路** (simple): 单一 PID 控制器，测量值 → PID → 输出
  - **串级回路** (cascade): 主回路输出作为副回路设定值，适用于大滞后系统
  - **前馈回路** (feedforward): 在 PID 输出上叠加扰动前馈补偿

控制回路通过 ``protocol_config["control_loops"]`` 列表配置，在
``DeviceInstance.tick()`` 中每个周期自动执行，输出写入对应点位。

典型配置示例::

    {
        "control_loops": [
            {
                "loop_id": "temp_control",
                "loop_type": "simple",
                "setpoint_point": "temp_setpoint",
                "measurement_point": "temp_pv",
                "output_point": "heater_output",
                "pid_params": {"Kp": 2.0, "Ki": 0.5, "Kd": 0.1},
                "output_limit": [0.0, 100.0]
            },
            {
                "loop_id": "flow_cascade_inner",
                "loop_type": "cascade",
                "primary_loop_id": "flow_cascade_outer",
                "setpoint_point": "",   # 副回路设定值来自主回路输出
                "measurement_point": "flow_pv",
                "output_point": "valve_cmd",
                "pid_params": {"Kp": 1.5, "Ki": 0.2, "Kd": 0.0},
                "output_limit": [0.0, 100.0]
            }
        ]
    }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from protoforge.core.behavior_models import PIDController

if TYPE_CHECKING:
    from protoforge.core.device import DeviceInstance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  配置数据类
# ---------------------------------------------------------------------------

@dataclass
class ControlLoopConfig:
    """控制回路配置。

    :param loop_id: 回路唯一标识
    :param loop_type: 回路类型 ("simple" | "cascade" | "feedforward")
    :param setpoint_point: 设定值点位名（串级副回路可为空，由主回路输出提供）
    :param measurement_point: 测量值点位名 (PV)
    :param output_point: 输出点位名 (CV，写入执行器)
    :param pid_params: PID 参数 ``{"Kp": float, "Ki": float, "Kd": float}``
    :param output_limit: 输出限幅 ``(min, max)``，默认 (0.0, 100.0)
    :param primary_loop_id: 主回路 ID（仅 cascade 副回路使用）
    :param disturbance_point: 扰动量点位名（仅 feedforward 回路使用）
    :param feedforward_gain: 前馈补偿增益
    :param enabled: 是否启用此回路
    :param auto_track: 串级副回路无主回路输出时是否跟踪测量值（无扰动切换）
    """

    loop_id: str
    loop_type: str = "simple"
    setpoint_point: str = ""
    measurement_point: str = ""
    output_point: str = ""
    pid_params: dict[str, float] = field(default_factory=lambda: {"Kp": 1.0, "Ki": 0.1, "Kd": 0.01})
    output_limit: tuple[float, float] = (0.0, 100.0)
    primary_loop_id: Optional[str] = None
    disturbance_point: Optional[str] = None
    feedforward_gain: float = 0.0
    enabled: bool = True
    auto_track: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControlLoopConfig":
        """从字典创建配置，处理 output_limit 列表转元组。"""
        d = dict(data)
        ol = d.get("output_limit")
        if ol is not None and isinstance(ol, (list, tuple)):
            d["output_limit"] = (float(ol[0]), float(ol[1]))
        return cls(
            loop_id=d["loop_id"],
            loop_type=d.get("loop_type", "simple"),
            setpoint_point=d.get("setpoint_point", ""),
            measurement_point=d.get("measurement_point", ""),
            output_point=d.get("output_point", ""),
            pid_params=d.get("pid_params", {"Kp": 1.0, "Ki": 0.1, "Kd": 0.01}),
            output_limit=d.get("output_limit", (0.0, 100.0)),
            primary_loop_id=d.get("primary_loop_id"),
            disturbance_point=d.get("disturbance_point"),
            feedforward_gain=float(d.get("feedforward_gain", 0.0)),
            enabled=d.get("enabled", True),
            auto_track=d.get("auto_track", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "loop_id": self.loop_id,
            "loop_type": self.loop_type,
            "setpoint_point": self.setpoint_point,
            "measurement_point": self.measurement_point,
            "output_point": self.output_point,
            "pid_params": dict(self.pid_params),
            "output_limit": list(self.output_limit),
            "primary_loop_id": self.primary_loop_id,
            "disturbance_point": self.disturbance_point,
            "feedforward_gain": self.feedforward_gain,
            "enabled": self.enabled,
            "auto_track": self.auto_track,
        }


# ---------------------------------------------------------------------------
#  控制回路实例
# ---------------------------------------------------------------------------

class ControlLoop:
    """单个控制回路实例。

    封装 PIDController，管理设定值更新、前馈补偿和输出限幅。

    :param config: 回路配置
    """

    def __init__(self, config: ControlLoopConfig):
        self.config = config
        self._pid = PIDController(
            Kp=config.pid_params.get("Kp", 1.0),
            Ki=config.pid_params.get("Ki", 0.1),
            Kd=config.pid_params.get("Kd", 0.01),
            setpoint=0.0,
            output_limit=config.output_limit,
        )
        self._last_output: float = 0.0
        self._last_setpoint: float = 0.0
        self._tick_count: int = 0

    def execute(
        self,
        measurement: float,
        setpoint: float,
        dt: float,
        disturbance: Optional[float] = None,
    ) -> float:
        """执行一个控制周期，返回控制输出。

        :param measurement: 过程测量值 (PV)
        :param setpoint: 设定值 (SP)
        :param dt: 时间步长 (s)
        :param disturbance: 扰动量（前馈控制用），None 表示无前馈
        :return: 控制输出 (CV)，已限幅
        """
        self._pid.set_setpoint(setpoint)
        self._last_setpoint = setpoint

        output = self._pid.update(measurement, dt)

        # 前馈补偿
        if disturbance is not None and self.config.feedforward_gain != 0.0:
            output += self.config.feedforward_gain * disturbance
            # 前馈补偿后再次限幅
            out_min, out_max = self.config.output_limit
            output = max(out_min, min(out_max, output))

        self._last_output = output
        self._tick_count += 1
        return output

    @property
    def last_output(self) -> float:
        """返回上一个周期的输出值。"""
        return self._last_output

    @property
    def last_setpoint(self) -> float:
        """返回上一个周期的设定值。"""
        return self._last_setpoint

    def is_saturated(self) -> bool:
        """返回 PID 是否处于饱和状态。"""
        return self._pid.is_saturated()

    def reset(self) -> None:
        """重置 PID 控制器内部状态（积分项、微分项等）。"""
        self._pid.reset()
        self._last_output = 0.0
        self._last_setpoint = 0.0
        self._tick_count = 0

    def get_state(self) -> dict[str, Any]:
        """返回回路状态字典。"""
        return {
            "loop_id": self.config.loop_id,
            "loop_type": self.config.loop_type,
            "setpoint": self._last_setpoint,
            "output": self._last_output,
            "saturated": self.is_saturated(),
            "tick_count": self._tick_count,
            "pid_state": self._pid.get_state(),
        }


# ---------------------------------------------------------------------------
#  控制回路管理器
# ---------------------------------------------------------------------------

class ControlLoopManager:
    """控制回路管理器。

    管理设备上的多个控制回路，按类型和依赖关系有序执行。

    执行顺序：
      1. 简单回路 (simple) 和前馈回路 (feedforward) — 独立执行
      2. 串级主回路 (cascade, primary) — 先执行
      3. 串级副回路 (cascade, secondary) — 主回路输出作为副回路设定值

    用法::

        manager = ControlLoopManager()
        manager.add_loop(config1)
        manager.add_loop(config2)
        # 在设备 tick 中
        outputs = manager.tick(device, dt=0.1)
        for point_name, value in outputs.items():
            device._point_values[point_name] = value
    """

    def __init__(self):
        self._loops: dict[str, ControlLoop] = {}
        self._configs: dict[str, ControlLoopConfig] = {}

    # -- 回路管理 ---------------------------------------------------------

    def add_loop(self, config: ControlLoopConfig) -> str:
        """添加控制回路。

        :param config: 回路配置
        :return: 回路 ID
        """
        loop = ControlLoop(config)
        self._loops[config.loop_id] = loop
        self._configs[config.loop_id] = config
        logger.info(
            "Control loop added: id=%s, type=%s, sp=%s, pv=%s, cv=%s",
            config.loop_id, config.loop_type,
            config.setpoint_point, config.measurement_point, config.output_point,
        )
        return config.loop_id

    def remove_loop(self, loop_id: str) -> bool:
        """移除控制回路。

        :param loop_id: 回路 ID
        :return: 是否成功移除
        """
        if loop_id in self._loops:
            del self._loops[loop_id]
            del self._configs[loop_id]
            logger.info("Control loop removed: id=%s", loop_id)
            return True
        return False

    def get_loop(self, loop_id: str) -> Optional[ControlLoop]:
        """获取回路实例。"""
        return self._loops.get(loop_id)

    def get_all_loops(self) -> dict[str, ControlLoop]:
        """返回所有回路实例。"""
        return dict(self._loops)

    def get_loop_states(self) -> dict[str, dict[str, Any]]:
        """返回所有回路的状态字典。"""
        return {lid: loop.get_state() for lid, loop in self._loops.items()}

    def reset_all(self) -> None:
        """重置所有回路。"""
        for loop in self._loops.values():
            loop.reset()

    @property
    def loop_count(self) -> int:
        """返回回路数量。"""
        return len(self._loops)

    # -- 核心执行 ---------------------------------------------------------

    def tick(self, device: DeviceInstance, dt: float) -> dict[str, float]:
        """执行所有控制回路一个周期。

        读取设备点位值作为测量值和设定值，计算 PID 输出，
        返回需要写入设备点位的输出值字典。

        执行顺序：
          1. 简单回路和前馈回路
          2. 串级主回路（无 primary_loop_id 的 cascade 回路）
          3. 串级副回路（有 primary_loop_id 的 cascade 回路）

        :param device: 设备实例，用于读取点位值
        :param dt: 时间步长 (s)
        :return: ``{output_point_name: value}`` 字典
        """
        outputs: dict[str, float] = {}

        # 分类回路
        simple_loops: list[tuple[str, ControlLoop, ControlLoopConfig]] = []
        cascade_primary: list[tuple[str, ControlLoop, ControlLoopConfig]] = []
        cascade_secondary: list[tuple[str, ControlLoop, ControlLoopConfig]] = []

        for lid, loop in self._loops.items():
            cfg = self._configs[lid]
            if not cfg.enabled:
                continue
            if cfg.loop_type == "cascade":
                if cfg.primary_loop_id:
                    cascade_secondary.append((lid, loop, cfg))
                else:
                    cascade_primary.append((lid, loop, cfg))
            else:
                # simple 和 feedforward 一起处理
                simple_loops.append((lid, loop, cfg))

        # 1. 执行简单回路和前馈回路
        for _lid, loop, cfg in simple_loops:
            try:
                output = self._execute_single(loop, cfg, device, dt)
                if output is not None:
                    outputs[cfg.output_point] = output
            except Exception as e:
                logger.warning("Control loop %s execution error: %s", cfg.loop_id, e)

        # 2. 执行串级主回路
        # 主回路的输出缓存，供副回路使用
        primary_outputs: dict[str, float] = {}
        for _lid, loop, cfg in cascade_primary:
            try:
                output = self._execute_single(loop, cfg, device, dt)
                if output is not None:
                    outputs[cfg.output_point] = output
                    primary_outputs[cfg.loop_id] = output
            except Exception as e:
                logger.warning("Cascade primary loop %s execution error: %s", cfg.loop_id, e)

        # 3. 执行串级副回路
        for _lid, loop, cfg in cascade_secondary:
            try:
                # 副回路设定值来自主回路输出
                primary_id = cfg.primary_loop_id
                if primary_id and primary_id in primary_outputs:
                    setpoint = primary_outputs[primary_id]
                elif cfg.setpoint_point:
                    # 有备份设定值点位
                    setpoint = self._read_point(device, cfg.setpoint_point)
                elif cfg.auto_track:
                    # 无主回路输出时跟踪测量值（无扰动切换）
                    setpoint = self._read_point(device, cfg.measurement_point)
                else:
                    logger.debug(
                        "Cascade secondary %s: no setpoint source, skipping", cfg.loop_id,
                    )
                    continue

                measurement = self._read_point(device, cfg.measurement_point)
                output = loop.execute(measurement, setpoint, dt)
                outputs[cfg.output_point] = output
            except Exception as e:
                logger.warning("Cascade secondary loop %s execution error: %s", cfg.loop_id, e)

        return outputs

    # -- 内部方法 ---------------------------------------------------------

    def _execute_single(
        self,
        loop: ControlLoop,
        cfg: ControlLoopConfig,
        device: DeviceInstance,
        dt: float,
    ) -> Optional[float]:
        """执行单个简单/前馈回路。

        :return: 控制输出，None 表示跳过
        """
        measurement = self._read_point(device, cfg.measurement_point)
        setpoint = self._read_point(device, cfg.setpoint_point) if cfg.setpoint_point else 0.0

        disturbance = None
        if cfg.loop_type == "feedforward" and cfg.disturbance_point:
            disturbance = self._read_point(device, cfg.disturbance_point)

        return loop.execute(measurement, setpoint, dt, disturbance)

    @staticmethod
    def _read_point(device: DeviceInstance, point_name: str) -> float:
        """从设备实例读取点位值并转换为 float。

        :param device: 设备实例
        :param point_name: 点位名称
        :return: 点位值 (float)
        :raises ValueError: 点位不存在或值不可转换为 float
        """
        if not point_name:
            raise ValueError("Point name is empty")
        value = device._point_values.get(point_name)
        if value is None:
            raise ValueError(f"Point '{point_name}' not found on device '{device.config.id}'")
        try:
            return float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Point '{point_name}' value '{value}' is not numeric on device '{device.config.id}'"
            ) from e

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """序列化管理器状态为字典。"""
        return {
            "loop_count": len(self._loops),
            "loops": [cfg.to_dict() for cfg in self._configs.values()],
            "loop_states": self.get_loop_states(),
        }
