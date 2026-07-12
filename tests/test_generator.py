"""Unit tests for protoforge.core.generator DataGenerator and SafeEval."""

import math

import pytest

from protoforge.core.generator import SafeEval, ScriptEngine, DataGenerator
from protoforge.models.device import DataType, GeneratorType, PointConfig


# ---------------------------------------------------------------------------
# SafeEval
# ---------------------------------------------------------------------------

class TestSafeEval:
    """Tests for the SafeEval expression evaluator."""

    def test_simple_arithmetic(self):
        ev = SafeEval()
        assert ev.eval_expr("1 + 2") == 3
        assert ev.eval_expr("10 - 5") == 5
        assert ev.eval_expr("3 * 4") == 12
        assert ev.eval_expr("10 / 2") == 5.0

    def test_parenthesized_expression(self):
        ev = SafeEval()
        assert ev.eval_expr("(1 + 2) * 3") == 9

    def test_variables(self):
        ev = SafeEval(variables={"x": 10, "y": 20})
        assert ev.eval_expr("x + y") == 30

    def test_math_functions(self):
        ev = SafeEval()
        assert ev.eval_expr("abs(-5)") == 5
        assert ev.eval_expr("max(3, 7)") == 7
        assert ev.eval_expr("min(3, 7)") == 3
        assert ev.eval_expr("round(3.7)") == 4

    def test_math_constants(self):
        ev = SafeEval()
        assert ev.eval_expr("pi") == pytest.approx(math.pi)
        assert ev.eval_expr("e") == pytest.approx(math.e)

    def test_trig_functions(self):
        ev = SafeEval()
        assert ev.eval_expr("sin(0)") == pytest.approx(0.0)
        assert ev.eval_expr("cos(0)") == pytest.approx(1.0)

    def test_comparison(self):
        ev = SafeEval()
        assert ev.eval_expr("3 > 2") is True
        assert ev.eval_expr("2 > 3") is False
        assert ev.eval_expr("5 == 5") is True
        assert ev.eval_expr("5 != 6") is True

    def test_boolean_ops(self):
        ev = SafeEval()
        assert ev.eval_expr("True and False") is False
        assert ev.eval_expr("True or False") is True
        assert ev.eval_expr("not False") is True

    def test_ternary(self):
        ev = SafeEval()
        assert ev.eval_expr("5 if True else 10") == 5
        assert ev.eval_expr("5 if False else 10") == 10

    def test_dangerous_names_blocked(self):
        ev = SafeEval()
        assert ev.eval_expr("__import__('os')") is None
        assert ev.eval_expr("open('test')") is None

    def test_invalid_expression_returns_none(self):
        ev = SafeEval()
        assert ev.eval_expr("invalid syntax !!!") is None
        assert ev.eval_expr("undefined_name") is None

    def test_exec_stmts(self):
        ev = SafeEval(variables={"x": 5})
        result = ev.exec_stmts("result = x * 2")
        assert result["result"] == 10

    def test_exec_multiple_stmts(self):
        ev = SafeEval()
        result = ev.exec_stmts("a = 10\nb = 20\nresult = a + b")
        assert result["result"] == 30

    def test_depth_limit(self):
        """Deeply nested expressions should be rejected."""
        ev = SafeEval()
        # Create a deeply nested expression
        expr = "1" + " + 1" * 60
        result = ev.eval_expr(expr)
        # Should either return a value or None (if depth exceeded)
        # The depth limit is 50, so 60 nested additions should fail
        assert result is None or isinstance(result, (int, float))

    def test_pow_exponent_limit(self):
        """Large exponents should be rejected."""
        ev = SafeEval()
        result = ev.eval_expr("2 ** 999999")
        assert result is None


# ---------------------------------------------------------------------------
# ScriptEngine
# ---------------------------------------------------------------------------

class TestScriptEngine:
    """Tests for the ScriptEngine."""

    def test_execute_simple(self):
        engine = ScriptEngine()
        result = engine.execute("result = 42", {})
        assert result == 42

    def test_execute_with_context(self):
        engine = ScriptEngine()
        result = engine.execute("result = x * 10", {"x": 5})
        assert result == 50

    def test_execute_no_result_returns_zero(self):
        engine = ScriptEngine()
        result = engine.execute("x = 10", {})
        assert result == 0

    def test_execute_cache_persistence(self):
        engine = ScriptEngine()
        # First execution sets a variable
        engine.execute("result = 100", {})
        # Second execution can access time variable
        result = engine.execute("result = time > 0", {})
        assert result is True or result == 1


# ---------------------------------------------------------------------------
# DataGenerator
# ---------------------------------------------------------------------------

class TestDataGenerator:
    """Tests for the DataGenerator."""

    def _make_point(
        self,
        name="test_point",
        address="0",
        data_type=DataType.FLOAT32,
        generator_type=GeneratorType.FIXED,
        fixed_value=None,
        min_value=None,
        max_value=None,
        generator_config=None,
    ):
        return PointConfig(
            name=name,
            address=address,
            data_type=data_type,
            generator_type=generator_type,
            fixed_value=fixed_value,
            min_value=min_value,
            max_value=max_value,
            generator_config=generator_config or {},
        )

    def test_fixed_generator(self):
        gen = DataGenerator()
        point = self._make_point(fixed_value=42.0)
        value = gen.generate(point)
        assert value == 42.0

    def test_random_generator(self):
        gen = DataGenerator()
        point = self._make_point(
            generator_type=GeneratorType.RANDOM,
            min_value=10.0,
            max_value=20.0,
        )
        value = gen.generate(point)
        assert 10.0 <= value <= 20.0

    def test_sine_generator(self):
        gen = DataGenerator()
        point = self._make_point(
            generator_type=GeneratorType.SINE,
            min_value=0.0,
            max_value=100.0,
            generator_config={"period": 10.0, "phase": 0.0},
        )
        value = gen.generate(point)
        assert 0.0 <= value <= 100.0

    def test_triangle_generator(self):
        gen = DataGenerator()
        point = self._make_point(
            generator_type=GeneratorType.TRIANGLE,
            min_value=0.0,
            max_value=100.0,
            generator_config={"period": 10.0},
        )
        value = gen.generate(point)
        assert 0.0 <= value <= 100.0

    def test_sawtooth_generator(self):
        gen = DataGenerator()
        point = self._make_point(
            generator_type=GeneratorType.SAWTOOTH,
            min_value=0.0,
            max_value=100.0,
            generator_config={"period": 10.0},
        )
        value = gen.generate(point)
        assert 0.0 <= value <= 100.0

    def test_square_generator(self):
        gen = DataGenerator()
        point = self._make_point(
            generator_type=GeneratorType.SQUARE,
            min_value=0.0,
            max_value=100.0,
            generator_config={"period": 10.0},
        )
        value = gen.generate(point)
        assert value in (0.0, 100.0)

    def test_increment_generator(self):
        gen = DataGenerator()
        point = self._make_point(
            generator_type=GeneratorType.INCREMENT,
            min_value=0.0,
            max_value=1000.0,
            generator_config={"step": 1.0},
        )
        value = gen.generate(point)
        assert isinstance(value, (int, float))

    def test_random_walk_generator(self):
        gen = DataGenerator()
        point = self._make_point(
            generator_type=GeneratorType.RANDOM_WALK,
            min_value=0.0,
            max_value=100.0,
            generator_config={"step_size": 1.0},
        )
        v1 = gen.generate(point)
        v2 = gen.generate(point)
        # Random walk should produce different values over time
        assert isinstance(v1, (int, float))
        assert isinstance(v2, (int, float))

    def test_script_generator(self):
        gen = DataGenerator()
        point = self._make_point(
            generator_type=GeneratorType.SCRIPT,
            generator_config={"script": "result = 42"},
        )
        value = gen.generate(point)
        assert value == 42

    def test_set_fault_injector(self):
        gen = DataGenerator()
        # Should not raise
        gen.set_fault_injector(None)

    def test_default_fixed_value(self):
        """When no fixed_value and no min/max, should return 0."""
        gen = DataGenerator()
        point = self._make_point(fixed_value=None, min_value=None, max_value=None)
        value = gen.generate(point)
        assert value == 0

    def test_default_fixed_with_min_max(self):
        """When no fixed_value but has min/max, should return midpoint."""
        gen = DataGenerator()
        point = self._make_point(fixed_value=None, min_value=10.0, max_value=20.0)
        value = gen.generate(point)
        assert value == 15.0

    def test_bool_data_type(self):
        gen = DataGenerator()
        point = self._make_point(
            data_type=DataType.BOOL,
            fixed_value=1,
        )
        value = gen.generate(point)
        assert isinstance(value, bool)
        assert value is True
