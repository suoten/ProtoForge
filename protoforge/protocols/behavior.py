import math
import random
import time
from typing import Any

from protoforge.models.device import PointConfig, GeneratorType
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus


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
        self._script_globals = {"math": math, "random": random, "time": time, "abs": abs, "min": min, "max": max}

    def generate(self) -> Any:
        gt = self._point.generator_type
        if gt == GeneratorType.FIXED:
            return self._generate_fixed()
        elif gt == GeneratorType.SINE:
            return self._generate_sine()
        elif gt == GeneratorType.RANDOM:
            return self._generate_random()
        elif gt == GeneratorType.TRIANGLE:
            return self._generate_triangle()
        elif gt == GeneratorType.SAWTOOTH:
            return self._generate_sawtooth()
        elif gt == GeneratorType.SCRIPT:
            return self._generate_script()
        return self._generate_fixed()

    def _clamp(self, value: float) -> Any:
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
            value = str(value)
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

    def _generate_script(self) -> Any:
        if not self._script_code:
            return self._last_value
        try:
            local_vars = {"t": time.time() - self._start_time, "value": self._last_value,
                          "min_val": self._min, "max_val": self._max, "result": None}
            exec(self._script_code, self._script_globals, local_vars)
            result = local_vars.get("result", self._last_value)
            if result is not None:
                self._last_value = result
            return self._clamp(self._last_value)
        except Exception:
            return self._last_value


class DefaultDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        self._written_values: dict[str, Any] = {}
        for p in points:
            init_val = p.fixed_value if p.fixed_value is not None else 0
            self._values[p.name] = init_val
            self._generators[p.name] = DynamicValueGenerator(p)

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        if name in self._written_values:
            return self._written_values[name]
        gen = self._generators.get(name)
        if gen:
            value = gen.generate()
            self._values[name] = value
            return value
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
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
            if pt.generator_type != GeneratorType.FIXED:
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)

    def clear_written(self, point_name: str = "") -> None:
        if point_name:
            self._written_values.pop(point_name, None)
        else:
            self._written_values.clear()
