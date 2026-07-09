import logging
import math
import random
import time
from collections.abc import Callable
from typing import Any

from protoforge.core.behavior_models import BaseBehavior, create_behavior, get_behavior_input
from protoforge.models.device import GeneratorType, PointConfig
from protoforge.protocols.base import (  # noqa: F401  # re-exported for protocol modules
    DeviceBehavior,
    ProtocolServer,
    ProtocolStatus,
)

logger = logging.getLogger(__name__)


class DynamicValueGenerator:
    def __init__(self, point: PointConfig):
        self._point = point
        self._start_time = time.time()
        self._last_value = point.fixed_value if point.fixed_value is not None else 0
        self._config = point.generator_config or {}
        self._min = point.min_value if point.min_value is not None else self._config.get("min", 0)
        self._max = point.max_value if point.max_value is not None else self._config.get("max", 100)
        self._amplitude = self._config.get("amplitude", (self._max - self._min) / 2)
        self._offset = self._config.get("offset", (self._max + self._min) / 2)
        self._frequency = self._config.get("frequency", 0.1)
        self._phase = self._config.get("phase", 0)
        self._noise = self._config.get("noise", 0)
        self._step_interval = self._config.get("step_interval", 5.0)
        self._step_values = self._config.get("step_values", [])
        self._step_index = 0
        self._last_step_time = self._start_time
        self._script_code = self._config.get("script", "")
        self._behavior: BaseBehavior | None = None  # PHYSICAL 行为模型实例
        self._behavior_input_key: str | None = None  # 耦合输入来源点位名
        self._physical_advanced: bool = False  # 当前 tick 内是否已推进过物理模型
        self._last_physical_time: float = 0.0  # 上次推进物理模型的墙钟时间
        self._value_provider: Callable[[str], Any] | None = None  # 耦合取值回调

    def begin_tick(self) -> None:
        """重置 tick 标志，允许物理模型在新 tick 中再次推进。

        应在设备 ``tick()`` 周期开始时调用，确保每个 tick 内物理模型
        最多只推进一次，避免 ``read_point()`` 多次调用导致重复推进。
        """
        self._physical_advanced = False

    def set_value_provider(self, provider: Callable[[str], Any]) -> None:
        """设置耦合取值回调，用于从其他点位读取最新值。

        :param provider: 接受点位名称、返回该点位当前值的回调函数
        """
        self._value_provider = provider

    def generate(self) -> Any:
        gt = self._point.generator_type
        if gt == GeneratorType.FIXED or gt == GeneratorType.CONSTANT:
            return self._generate_fixed()
        elif gt == GeneratorType.SINE:
            return self._generate_sine()
        elif gt == GeneratorType.RANDOM:
            return self._generate_random()
        elif gt == GeneratorType.TRIANGLE:
            return self._generate_triangle()
        elif gt == GeneratorType.SAWTOOTH:
            return self._generate_sawtooth()
        elif gt == GeneratorType.SQUARE:
            return self._generate_square()
        elif gt == GeneratorType.INCREMENT:
            return self._generate_increment()
        elif gt == GeneratorType.RANDOM_WALK:
            return self._generate_random_walk()  # FIXED-P1: 添加RANDOM_WALK支持
        elif gt == GeneratorType.SCRIPT:
            return self._generate_script()
        elif gt == GeneratorType.PHYSICAL:
            return self._generate_physical()
        return self._generate_fixed()

    def _clamp(self, value: float) -> Any:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            value = self._last_value if hasattr(self, '_last_value') else 0
        dt = self._point.data_type.value
        if dt == "bool":
            return bool(value)
        if self._point.min_value is not None or self._point.max_value is not None:
            value = max(self._min, min(self._max, value))
        if dt == "int16":
            value = int(max(-32768, min(32767, round(value))))
        elif dt == "int32":
            value = int(max(-2147483648, min(2147483647, round(value))))
        elif dt == "uint16":
            value = int(max(0, min(65535, round(value))))
        elif dt == "uint32":
            value = int(max(0, min(4294967295, round(value))))
        elif dt in ("float32", "float64"):
            value = round(value, 4)
        elif dt == "string":
            value = str(value)[:256]  # FIXED-L06: 限制字符串最大长度为256，防止超长字符串
        return value

    def _generate_fixed(self) -> Any:
        base = self._point.fixed_value if self._point.fixed_value is not None else self._offset
        if self._noise > 0:
            base = float(base) + random.gauss(0, self._noise)
        return self._clamp(base)

    def _generate_sine(self) -> Any:
        t = time.time() - self._start_time
        value = self._offset + self._amplitude * math.sin(2 * math.pi * self._frequency * t + self._phase)
        if self._noise > 0:
            value += random.gauss(0, self._noise)
        return self._clamp(value)

    def _generate_random(self) -> Any:
        value = random.uniform(self._min, self._max)
        if self._noise > 0:
            value += random.gauss(0, self._noise)
        return self._clamp(value)

    def _generate_triangle(self) -> Any:
        t = time.time() - self._start_time
        period = 1.0 / self._frequency if self._frequency > 0 else 10.0
        phase_t = ((t + self._phase / (2 * math.pi * max(self._frequency, 0.001))) % period) / period
        if phase_t < 0.5:
            value = self._min + (self._max - self._min) * (phase_t * 2)
        else:
            value = self._max - (self._max - self._min) * ((phase_t - 0.5) * 2)
        if self._noise > 0:
            value += random.gauss(0, self._noise)
        return self._clamp(value)

    def _generate_sawtooth(self) -> Any:
        t = time.time() - self._start_time
        period = 1.0 / self._frequency if self._frequency > 0 else 10.0
        phase_t = ((t + self._phase / (2 * math.pi * max(self._frequency, 0.001))) % period) / period
        value = self._min + (self._max - self._min) * phase_t
        if self._noise > 0:
            value += random.gauss(0, self._noise)
        return self._clamp(value)

    def _generate_square(self) -> Any:
        t = time.time() - self._start_time
        period = 1.0 / self._frequency if self._frequency > 0 else 10.0
        phase_t = ((t + self._phase / (2 * math.pi * max(self._frequency, 0.001))) % period) / period
        value = self._max if phase_t < 0.5 else self._min
        if self._noise > 0:
            value += random.gauss(0, self._noise)
        return self._clamp(value)

    def _generate_increment(self) -> Any:
        t = time.time() - self._start_time
        step = self._config.get("step", 1)
        period = 1.0 / self._frequency if self._frequency > 0 else 10.0
        count = int(t / period)
        value = self._min + step * count
        if self._max > self._min:
            value = self._min + (value - self._min) % (self._max - self._min)
        if self._noise > 0:
            value += random.gauss(0, self._noise)
        self._last_value = value  # FIXED-P1: 更新_last_value供SCRIPT引用
        return self._clamp(value)

    def _generate_random_walk(self) -> Any:  # FIXED-P1: 实现RANDOM_WALK生成器
        step_size = self._config.get("step_size", 1.0)
        delta = random.gauss(0, step_size)
        value = self._last_value + delta
        if self._max > self._min:
            value = max(self._min, min(self._max, value))
        if self._noise > 0:
            value += random.gauss(0, self._noise)
        self._last_value = value
        return self._clamp(value)

    def _generate_script(self) -> Any:
        if not self._script_code:
            return self._last_value
        try:
            from protoforge.core.generator import SafeEval
            evaluator = SafeEval({
                "t": time.time() - self._start_time,
                "value": self._last_value,
                "min_val": self._min,
                "max_val": self._max,
            })
            result = evaluator.eval_expr(self._script_code)
            if result is not None:
                self._last_value = result
            return self._clamp(self._last_value)
        except Exception as e:
            logger.warning("Script generator error: %s", e)
            return self._last_value

    def _generate_physical(self) -> Any:
        """使用物理行为模型生成值。

        generator_config 支持:
          - ``config_string``: 字符串配置，如 "thermal:mass=10,specific_heat=900"
          - ``behavior``: 行为类型名称，配合 ``params`` 字典使用
          - ``input``: 行为模型的输入参数（如功率、扭矩等）
          - ``dt``: 仿真时间步长 (s)，默认 0.1
          - ``coupling``: 多变量耦合列表，每个元素为
            ``{"source": "其他点位名", "param": "update参数名"}``，
            运行时从其他点位最新值读取输入

        tick 防重复推进机制:
          - ``_physical_advanced`` 标志在 ``begin_tick()`` 时重置
          - 本 tick 内已推进过且距上次推进不足一个 ``dt`` 时，
            直接返回缓存值，避免 ``read_point()`` 多次调用导致
            物理模型在同一 tick 内被重复推进
        """
        # ---- 懒初始化行为模型 ----
        if self._behavior is None:
            config_str = self._config.get("config_string")
            if config_str:
                self._behavior = create_behavior(config_str)
            else:
                self._behavior = create_behavior(self._config)
            if self._behavior is None:
                logger.warning(
                    "Failed to create behavior model for point %s, falling back to fixed",
                    self._point.name,
                )
                return self._generate_fixed()

        # ---- tick 防重复推进 ----
        # _physical_advanced 由 begin_tick() 在设备 tick 周期开始时重置。
        # 若本 tick 内已推进过，且距上次推进不足一个 dt，直接返回缓存值。
        dt = self._config.get("dt", 0.1)
        now = time.time()
        if self._physical_advanced and self._last_physical_time > 0:
            elapsed = now - self._last_physical_time
            if elapsed < dt:
                return self._clamp(self._last_value)

        # ---- 准备输入 ----
        coupling = self._config.get("coupling")
        if coupling and self._value_provider:
            # 多变量耦合模式：从其他点位最新值读取输入
            kwargs: dict[str, Any] = {}
            for c in coupling:
                source_point = c.get("source") or c.get("point", "")
                param_name = c.get("param") or c.get("as", "input")
                kwargs[param_name] = self._value_provider(source_point)
                if self._behavior_input_key is None:
                    self._behavior_input_key = source_point
            kwargs["dt"] = dt
            try:
                result = self._behavior.update(**kwargs)
            except Exception as e:
                logger.warning("Physical behavior coupling error for point %s: %s", self._point.name, e)
                return self._clamp(self._last_value)
        else:
            # 单输入模式：从 config 读取 input
            input_value, dt_val = get_behavior_input(self._config)
            if input_value == 0.0 and "input" not in self._config:
                input_value = self._offset
            try:
                result = self._behavior.update(input_value, dt=dt_val)
            except Exception as e:
                logger.warning("Physical behavior error for point %s: %s", self._point.name, e)
                return self._clamp(self._last_value)

        self._last_value = result
        self._physical_advanced = True
        self._last_physical_time = now
        return self._clamp(result)


class DefaultDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        self._written_values: dict[str, Any] = {}
        for p in points:
            init_val = p.fixed_value if p.fixed_value is not None else 0
            self._values[p.name] = init_val
            gen = DynamicValueGenerator(p)
            gen.set_value_provider(self._get_point_value)
            self._generators[p.name] = gen

    def _get_point_value(self, point_name: str) -> Any:
        """提供点位最新值，供物理模型多变量耦合取值使用。"""
        if point_name in self._written_values:
            return self._written_values[point_name]
        return self._values.get(point_name, 0)

    def tick(self) -> None:
        """重置所有生成器的 tick 标志，应在设备 tick 周期开始时调用。

        确保物理行为模型每个 tick 最多只推进一次，
        而非每次 ``read_point()`` 都推进。
        """
        for gen in self._generators.values():
            gen.begin_tick()

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        if name in self._written_values:
            return self._written_values[name]
        gen = self._generators.get(name)
        if gen:
            value = gen.generate()
            self._values[name] = value
            return value
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._written_values[point_name] = value
            self._values[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._written_values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen and self._points.get(point_name):
            pt = self._points[point_name]
            if point_name in self._written_values:
                return self._written_values[point_name]
            if pt.generator_type != GeneratorType.FIXED or gen._noise > 0:
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)

    def clear_written(self, point_name: str = "") -> None:
        if point_name:
            self._written_values.pop(point_name, None)
        else:
            self._written_values.clear()


class StandardDeviceBehavior(DeviceBehavior):
    """Intermediate base class for protocol-specific behaviors.

    FIXED: 8个协议(BACnet/AB/FANUC/FINS/MC/MTConnect/OPC-DA/Toledo)重复
    _points/_values/_generators初始化和generate_value/on_write/set_value/get_value模式。
    提取为中间基类，协议特定Behavior只需添加特有字段和覆写特有方法。
    """
    def __init__(self, points: list | None = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        self._written_values: dict[str, Any] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                self._points[name] = p
                self._values[name] = fixed_val if fixed_val is not None else 0
                gen = DynamicValueGenerator(p)
                gen.set_value_provider(self._get_point_value)
                self._generators[name] = gen

    def _get_point_value(self, point_name: str) -> Any:
        """提供点位最新值，供物理模型多变量耦合取值使用。"""
        if point_name in self._written_values:
            return self._written_values[point_name]
        return self._values.get(point_name, 0)

    def tick(self) -> None:
        """重置所有生成器的 tick 标志，应在设备 tick 周期开始时调用。

        确保物理行为模型每个 tick 最多只推进一次，
        而非每次 ``read_point()`` 都推进。
        """
        for gen in self._generators.values():
            gen.begin_tick()

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        # FIXED-P1: 使用生成器产生动态值，与 get_value() 和 DefaultDeviceBehavior 保持一致
        name = point_config.get("name", "")
        gen = self._generators.get(name)
        if gen:
            pt = self._points.get(name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[name] = value
                return value
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._written_values[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        self._written_values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type"):
                # PHYSICAL 类型：优先返回引擎同步的写入值，
                # 避免每次读取都推进物理模型
                if pt.generator_type == GeneratorType.PHYSICAL and point_name in self._written_values:
                    return self._written_values[point_name]
                if pt.generator_type.value != "fixed":
                    value = gen.generate()
                    self._values[point_name] = value
                    return value
        return self._values.get(point_name, 0)

    def clear_written(self, point_name: str = "") -> None:
        if point_name:
            self._written_values.pop(point_name, None)
        else:
            self._written_values.clear()
