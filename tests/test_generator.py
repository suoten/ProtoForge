import pytest

from protoforge.core.generator import DataGenerator
from protoforge.models.device import DataType, GeneratorType, PointConfig


@pytest.fixture
def generator():
    return DataGenerator()


def test_fixed_generator(generator):
    point = PointConfig(
        name="test",
        address="0",
        data_type=DataType.FLOAT32,
        generator_type=GeneratorType.FIXED,
        fixed_value=42.5,
    )
    value = generator.generate(point)
    assert value == 42.5


def test_random_generator(generator):
    point = PointConfig(
        name="test",
        address="0",
        data_type=DataType.FLOAT32,
        generator_type=GeneratorType.RANDOM,
        min_value=10.0,
        max_value=20.0,
    )
    for _ in range(100):
        value = generator.generate(point)
        assert 10.0 <= value <= 20.0


def test_sine_generator(generator):
    point = PointConfig(
        name="test",
        address="0",
        data_type=DataType.FLOAT32,
        generator_type=GeneratorType.SINE,
        min_value=0.0,
        max_value=100.0,
        generator_config={"period": 10.0},
    )
    for _ in range(50):
        value = generator.generate(point)
        assert 0.0 <= value <= 100.0


def test_int_cast(generator):
    point = PointConfig(
        name="test",
        address="0",
        data_type=DataType.INT32,
        generator_type=GeneratorType.RANDOM,
        min_value=0,
        max_value=100,
    )
    value = generator.generate(point)
    assert isinstance(value, int)


def test_bool_cast(generator):
    point = PointConfig(
        name="test",
        address="0",
        data_type=DataType.BOOL,
        generator_type=GeneratorType.FIXED,
        fixed_value=1,
    )
    value = generator.generate(point)
    assert isinstance(value, bool)


def test_script_generator(generator):
    point = PointConfig(
        name="test",
        address="0",
        data_type=DataType.FLOAT32,
        generator_type=GeneratorType.SCRIPT,
        generator_config={"script": "result = context['elapsed'] * 2"},
    )
    value = generator.generate(point)
    assert isinstance(value, float)
    assert value >= 0


def test_script_generator_with_math(generator):
    point = PointConfig(
        name="test",
        address="0",
        data_type=DataType.FLOAT32,
        generator_type=GeneratorType.SCRIPT,
        min_value=0.0,
        max_value=100.0,
        generator_config={"script": "result = min_value + (max_value - min_value) * (0.5 + 0.5 * math.sin(context['elapsed']))"},
    )
    for _ in range(20):
        value = generator.generate(point)
        assert 0.0 <= value <= 100.0


def test_script_generator_error_fallback(generator):
    point = PointConfig(
        name="test",
        address="0",
        data_type=DataType.FLOAT32,
        generator_type=GeneratorType.SCRIPT,
        generator_config={"script": "result = 1 / 0"},
    )
    value = generator.generate(point)
    assert value == 0
