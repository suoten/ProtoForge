import math
import random
import time
from typing import Any

from protoforge.models.device import DataType, GeneratorType, PointConfig


class ScriptEngine:
    _safe_builtins = {
        "abs": abs, "min": min, "max": max, "round": round,
        "int": int, "float": float, "bool": bool, "str": str,
        "len": len, "range": range, "list": list, "dict": dict,
        "math": math, "random": random,
        "True": True, "False": False, "None": None,
    }

    def __init__(self):
        self._cache: dict[str, Any] = {}

    def execute(self, script: str, context: dict[str, Any]) -> Any:
        namespace = dict(self._safe_builtins)
        namespace["context"] = context
        namespace["time"] = time.time()
        namespace["cache"] = self._cache
        try:
            exec(script, {"__builtins__": {}}, namespace)
            return namespace.get("result", 0)
        except Exception as e:
            return 0


class DataGenerator:
    def __init__(self):
        self._start_time: dict[str, float] = {}
        self._script_engine = ScriptEngine()

    def generate(self, point: PointConfig) -> Any:
        key = f"{point.name}_{point.address}"
        if key not in self._start_time:
            self._start_time[key] = time.time()

        elapsed = time.time() - self._start_time[key]

        if point.generator_type == GeneratorType.FIXED:
            return self._generate_fixed(point)
        elif point.generator_type == GeneratorType.RANDOM:
            return self._generate_random(point)
        elif point.generator_type == GeneratorType.SINE:
            return self._generate_sine(point, elapsed)
        elif point.generator_type == GeneratorType.TRIANGLE:
            return self._generate_triangle(point, elapsed)
        elif point.generator_type == GeneratorType.SAWTOOTH:
            return self._generate_sawtooth(point, elapsed)
        elif point.generator_type == GeneratorType.SCRIPT:
            return self._generate_script(point, elapsed)
        else:
            return self._generate_fixed(point)

    def _generate_fixed(self, point: PointConfig) -> Any:
        if point.fixed_value is not None:
            return self._cast_value(point.fixed_value, point.data_type)
        if point.min_value is not None and point.max_value is not None:
            mid = (point.min_value + point.max_value) / 2
            return self._cast_value(mid, point.data_type)
        return self._cast_value(0, point.data_type)

    def _generate_random(self, point: PointConfig) -> Any:
        lo = point.min_value if point.min_value is not None else 0
        hi = point.max_value if point.max_value is not None else 100
        value = random.uniform(lo, hi)
        return self._cast_value(value, point.data_type)

    def _generate_sine(self, point: PointConfig, elapsed: float) -> Any:
        lo = point.min_value if point.min_value is not None else 0
        hi = point.max_value if point.max_value is not None else 100
        period = point.generator_config.get("period", 10.0)
        phase = point.generator_config.get("phase", 0.0)
        mid = (lo + hi) / 2
        amp = (hi - lo) / 2
        value = mid + amp * math.sin(2 * math.pi * elapsed / period + phase)
        return self._cast_value(value, point.data_type)

    def _generate_triangle(self, point: PointConfig, elapsed: float) -> Any:
        lo = point.min_value if point.min_value is not None else 0
        hi = point.max_value if point.max_value is not None else 100
        period = point.generator_config.get("period", 10.0)
        mid = (lo + hi) / 2
        amp = (hi - lo) / 2
        t = (elapsed % period) / period
        value = mid + amp * (4 * abs(t - 0.5) - 1)
        return self._cast_value(value, point.data_type)

    def _generate_sawtooth(self, point: PointConfig, elapsed: float) -> Any:
        lo = point.min_value if point.min_value is not None else 0
        hi = point.max_value if point.max_value is not None else 100
        period = point.generator_config.get("period", 10.0)
        t = (elapsed % period) / period
        value = lo + (hi - lo) * t
        return self._cast_value(value, point.data_type)

    def _generate_script(self, point: PointConfig, elapsed: float) -> Any:
        script = point.generator_config.get("script", "result = 0")
        context = {
            "elapsed": elapsed,
            "min_value": point.min_value,
            "max_value": point.max_value,
            "point_name": point.name,
            "point_address": point.address,
        }
        value = self._script_engine.execute(script, context)
        return self._cast_value(value, point.data_type)

    def _cast_value(self, value: Any, data_type: DataType) -> Any:
        if data_type == DataType.BOOL:
            return bool(value)
        elif data_type in (DataType.INT16, DataType.INT32):
            return int(value)
        elif data_type in (DataType.UINT16, DataType.UINT32):
            return int(abs(value))
        elif data_type in (DataType.FLOAT32, DataType.FLOAT64):
            return float(value)
        elif data_type == DataType.STRING:
            return str(value)
        return value
