import ast
import math
import random
import time
import logging
import operator
from typing import Any

from protoforge.models.device import DataType, GeneratorType, PointConfig

logger = logging.getLogger(__name__)

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.And: lambda a, b: a and b,
    ast.Or: lambda a, b: a or b,
    ast.Not: operator.not_,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_SAFE_NAMES = {
    "True": True, "False": False, "None": None,
    "abs": abs, "min": min, "max": max, "round": round,
    "int": int, "float": float, "bool": bool, "str": str,
    "len": len, "range": range, "list": list, "dict": dict,
    "pi": math.pi, "e": math.e,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
    "ceil": math.ceil, "floor": math.floor, "fabs": math.fabs,
}

_DANGEROUS_NAMES = {
    "__import__", "__builtins__", "__class__", "__globals__", "__locals__",
    "open", "file", "input", "exec", "eval", "compile", "reload",
    "breakpoint", "exit", "quit", "help", "copyright", "credits", "license",
}


class SafeEval:
    _MAX_DEPTH = 50
    _MAX_CALL_ARGS = 10
    _MAX_STR_LEN = 10000

    def __init__(self, variables: dict[str, Any] | None = None):
        self._variables = variables or {}
        self._depth = 0

    def eval_expr(self, expr: str) -> Any:
        try:
            tree = ast.parse(expr, mode="eval")
            self._depth = 0
            return self._eval_node(tree.body)
        except Exception as e:
            logger.debug("SafeEval error: %s", e)
            return 0

    def exec_stmts(self, code: str) -> dict[str, Any]:
        try:
            tree = ast.parse(code, mode="exec")
            local_vars = dict(self._variables)
            self._depth = 0
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    value = self._eval_node(node.value)
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            local_vars[target.id] = value
                        else:
                            raise ValueError(f"Unsupported assignment target: {type(target).__name__}")
                elif isinstance(node, ast.Expr):
                    self._eval_node(node.value)
                else:
                    raise ValueError(f"Unsupported statement: {type(node).__name__}")
            return local_vars
        except Exception as e:
            logger.debug("SafeEval exec error: %s", e)
            return dict(self._variables)

    def _eval_node(self, node: ast.AST) -> Any:
        self._depth += 1
        if self._depth > self._MAX_DEPTH:
            raise RecursionError(f"Expression too deeply nested (max {self._MAX_DEPTH})")
        try:
            return self._eval_node_inner(node)
        finally:
            self._depth -= 1

    def _eval_node_inner(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            if node.id in _DANGEROUS_NAMES:
                raise NameError(f"Name '{node.id}' is not allowed (potentially dangerous)")
            if node.id in _SAFE_NAMES:
                return _SAFE_NAMES[node.id]
            if node.id in self._variables:
                return self._variables[node.id]
            raise NameError(f"Name '{node.id}' is not allowed")
        elif isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            result = op(self._eval_node(node.left), self._eval_node(node.right))
            if isinstance(result, str) and len(result) > self._MAX_STR_LEN:
                raise ValueError(f"String too long (max {self._MAX_STR_LEN})")
            return result
        elif isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op(self._eval_node(node.operand))
        elif isinstance(node, ast.Compare):
            left = self._eval_node(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                op_func = _SAFE_OPS.get(type(op))
                if op_func is None:
                    raise ValueError(f"Unsupported comparison: {type(op).__name__}")
                right = self._eval_node(comparator)
                if not op_func(left, right):
                    return False
                left = right
            return True
        elif isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result = True
                for val in node.values:
                    result = self._eval_node(val)
                    if not result:
                        return result
                return result
            elif isinstance(node.op, ast.Or):
                result = False
                for val in node.values:
                    result = self._eval_node(val)
                    if result:
                        return result
                return result
        elif isinstance(node, ast.IfExp):
            test = self._eval_node(node.test)
            return self._eval_node(node.body) if test else self._eval_node(node.orelse)
        elif isinstance(node, ast.Call):
            func = self._eval_node(node.func)
            if isinstance(node.func, ast.Name) and node.func.id in _DANGEROUS_NAMES:
                raise NameError(f"Calling '{node.func.id}' is not allowed")
            if len(node.args) > self._MAX_CALL_ARGS:
                raise ValueError(f"Too many call arguments (max {self._MAX_CALL_ARGS})")
            args = [self._eval_node(a) for a in node.args]
            return func(*args)
        elif isinstance(node, ast.Attribute):
            value = self._eval_node(node.value)
            if isinstance(value, math.__class__):
                allowed = {"pi", "e", "sin", "cos", "tan", "sqrt", "log", "log10", "ceil", "floor", "fabs"}
                if node.attr in allowed:
                    return getattr(value, node.attr)
            if node.attr.startswith("__") or node.attr in _DANGEROUS_NAMES:
                raise AttributeError(f"Attribute access '{node.attr}' is not allowed")
            raise AttributeError(f"Attribute access '{node.attr}' is not allowed")
        elif isinstance(node, ast.Subscript):
            value = self._eval_node(node.value)
            slice_val = self._eval_node(node.slice) if isinstance(node.slice, ast.AST) else node.slice
            return value[slice_val]
        raise ValueError(f"Unsupported expression: {type(node).__name__}")


class ScriptEngine:
    def __init__(self):
        self._cache: dict[str, Any] = {}

    def execute(self, script: str, context: dict[str, Any]) -> Any:
        variables = dict(context)
        variables["cache"] = self._cache
        variables["time"] = time.time()
        evaluator = SafeEval(variables)
        result_vars = evaluator.exec_stmts(script)
        return result_vars.get("result", 0)


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
        period = point.generator_config.get("period", 10.0) or 10.0
        if period <= 0:
            period = 10.0
        phase = point.generator_config.get("phase", 0.0)
        mid = (lo + hi) / 2
        amp = (hi - lo) / 2
        value = mid + amp * math.sin(2 * math.pi * elapsed / period + phase)
        return self._cast_value(value, point.data_type)

    def _generate_triangle(self, point: PointConfig, elapsed: float) -> Any:
        lo = point.min_value if point.min_value is not None else 0
        hi = point.max_value if point.max_value is not None else 100
        period = point.generator_config.get("period", 10.0) or 10.0
        if period <= 0:
            period = 10.0
        mid = (lo + hi) / 2
        amp = (hi - lo) / 2
        t = (elapsed % period) / period
        value = mid + amp * (4 * abs(t - 0.5) - 1)
        return self._cast_value(value, point.data_type)

    def _generate_sawtooth(self, point: PointConfig, elapsed: float) -> Any:
        lo = point.min_value if point.min_value is not None else 0
        hi = point.max_value if point.max_value is not None else 100
        period = point.generator_config.get("period", 10.0) or 10.0
        if period <= 0:
            period = 10.0
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
        elif data_type == DataType.UINT16:
            return int(abs(value)) & 0xFFFF
        elif data_type == DataType.UINT32:
            return int(abs(value)) & 0xFFFFFFFF
        elif data_type in (DataType.FLOAT32, DataType.FLOAT64):
            return float(value)
        elif data_type == DataType.STRING:
            return str(value)
        return value
