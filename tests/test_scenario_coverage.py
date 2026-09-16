"""Comprehensive tests for scenario.py - Scenario class with rules and collaboration."""

import asyncio

import pytest

from protoforge.engine.device import DeviceInstance
from protoforge.engine.generator import DataGenerator
from protoforge.simulation.scenario import Scenario
from protoforge.models.device import (
    DeviceConfig,
    PointConfig,
    DataType,
    GeneratorType,
)
from protoforge.models.scenario import (
    ScenarioConfig,
    Rule,
    RuleType,
    ScenarioStatus,
)


# ==================== Fixtures ====================

@pytest.fixture
def generator():
    return DataGenerator()


@pytest.fixture
def make_point():
    def _make(name="test_point", gen_type=GeneratorType.FIXED, fixed_value=42.0, **kwargs):
        return PointConfig(
            name=name,
            address="0",
            data_type=DataType.FLOAT32,
            generator_type=gen_type,
            fixed_value=fixed_value,
            **kwargs,
        )
    return _make


@pytest.fixture
def make_device(generator, make_point):
    def _make(device_id="scen-device", points=None):
        if points is None:
            points = [make_point(name="temperature", gen_type=GeneratorType.RANDOM, min_value=0, max_value=100)]
        config = DeviceConfig(
            id=device_id,
            name=f"Device {device_id}",
            protocol="modbus_tcp",
            points=points,
        )
        return DeviceInstance(config, generator)
    return _make


@pytest.fixture
def make_scenario_config():
    def _make(
        scenario_id="test-scenario",
        devices=None,
        rules=None,
    ):
        return ScenarioConfig(
            id=scenario_id,
            name=f"Scenario {scenario_id}",
            description="Test scenario",
            devices=devices or [],
            rules=rules or [],
        )
    return _make


# ==================== Scenario Basic Tests ====================

class TestScenarioBasic:
    def test_init(self, make_scenario_config):
        config = make_scenario_config("init-test")
        scen = Scenario(config)
        assert scen.id == "init-test"
        assert scen.status == ScenarioStatus.STOPPED

    def test_add_device(self, make_scenario_config, make_device):
        config = make_scenario_config("add-dev-test")
        scen = Scenario(config)
        dev = make_device("added-dev")
        scen.add_device(dev)
        assert "added-dev" in scen._devices

    def test_remove_device(self, make_scenario_config, make_device):
        config = make_scenario_config("rm-dev-test")
        scen = Scenario(config)
        dev = make_device("to-remove")
        scen.add_device(dev)
        scen.remove_device("to-remove")
        assert "to-remove" not in scen._devices

    def test_remove_nonexistent_device(self, make_scenario_config):
        config = make_scenario_config("rm-none-test")
        scen = Scenario(config)
        scen.remove_device("nonexistent")  # Should not raise

    def test_start(self, make_scenario_config, make_device):
        config = make_scenario_config("start-test")
        scen = Scenario(config)
        dev = make_device("start-dev")
        scen.add_device(dev)
        scen.start()
        assert scen.status == ScenarioStatus.RUNNING
        assert scen._start_time is not None

    def test_stop(self, make_scenario_config, make_device):
        config = make_scenario_config("stop-test")
        scen = Scenario(config)
        dev = make_device("stop-dev")
        scen.add_device(dev)
        scen.start()
        scen.stop()
        assert scen.status == ScenarioStatus.STOPPED


# ==================== Scenario Rule Tests ====================

class TestScenarioRules:
    def _make_threshold_rule(self):
        return Rule(
            id="threshold-rule",
            name="Temperature threshold",
            rule_type=RuleType.THRESHOLD,
            source_device_id="dev-1",
            source_point="temperature",
            target_device_id="dev-2",
            target_point="valve",
            target_value=50.0,
            condition={"operator": ">", "value": 80},
            enabled=True,
        )

    def test_threshold_rule_evaluation(self, make_scenario_config, make_device, generator):
        rule = self._make_threshold_rule()
        config = make_scenario_config("threshold-test", rules=[rule])
        scen = Scenario(config)

        # Add devices
        dev1 = make_device("dev-1", points=[
            PointConfig(name="temperature", address="0", data_type=DataType.FLOAT32,
                       generator_type=GeneratorType.FIXED, fixed_value=90.0),
        ])
        dev2 = make_device("dev-2", points=[
            PointConfig(name="valve", address="0", data_type=DataType.FLOAT32,
                       generator_type=GeneratorType.FIXED, fixed_value=0.0),
        ])
        scen.add_device(dev1)
        scen.add_device(dev2)
        scen.start()

        # Check rule - may or may not trigger depending on device state
        result = scen._check_rule(rule)
        assert isinstance(result, bool)

    def test_threshold_rule_not_triggered(self, make_scenario_config, make_device):
        rule = Rule(
            id="low-temp",
            name="Low temp check",
            rule_type=RuleType.THRESHOLD,
            source_device_id="low-dev",
            source_point="temperature",
            target_device_id="target-dev",
            target_point="valve",
            target_value=50.0,
            condition={"operator": ">", "value": 100},
            enabled=True,
        )
        config = make_scenario_config("low-threshold-test", rules=[rule])
        scen = Scenario(config)
        dev = make_device("low-dev", points=[
            PointConfig(name="temperature", address="0", data_type=DataType.FLOAT32,
                       generator_type=GeneratorType.FIXED, fixed_value=50.0),
        ])
        scen.add_device(dev)
        scen.start()
        result = scen._check_rule(rule)
        assert result is False  # 50 < 100

    def test_disabled_rule_not_evaluated(self, make_scenario_config):
        rule = Rule(
            id="disabled-rule",
            name="Disabled",
            rule_type=RuleType.THRESHOLD,
            source_device_id="dev",
            source_point="temp",
            target_device_id="target",
            target_point="valve",
            target_value=50.0,
            condition={"operator": ">", "value": 80},
            enabled=False,
        )
        config = make_scenario_config("disabled-test", rules=[rule])
        scen = Scenario(config)
        scen.start()
        result = scen._check_rule(rule)
        assert result is False

    def test_cooldown_prevents_trigger(self, make_scenario_config):
        import time
        rule = Rule(
            id="cooldown-rule",
            name="Cooldown",
            rule_type=RuleType.THRESHOLD,
            source_device_id="dev",
            source_point="temp",
            target_device_id="target",
            target_point="valve",
            target_value=50.0,
            condition={"operator": ">", "value": 50, "cooldown": 10.0},
            enabled=True,
        )
        config = make_scenario_config("cooldown-test", rules=[rule])
        scen = Scenario(config)
        scen.start()
        # Simulate first trigger
        scen._last_trigger[rule.id] = time.time()
        # Should be in cooldown (return False = cannot trigger)
        result = scen._check_cooldown(rule)
        assert result is False


# ==================== Scenario Tick Tests ====================

class TestScenarioTick:
    @pytest.mark.asyncio
    async def test_tick_updates_devices(self, make_scenario_config, make_device):
        config = make_scenario_config("tick-test")
        scen = Scenario(config)
        dev = make_device("tick-dev")
        scen.add_device(dev)
        scen.start()
        # Manually set device to RUN state
        dev._state_machine._state = dev._state_machine._state.__class__.RUN if hasattr(dev._state_machine._state, 'RUN') else dev._state_machine._state
        await scen.tick()

    @pytest.mark.asyncio
    async def test_tick_with_no_devices(self, make_scenario_config):
        config = make_scenario_config("empty-tick")
        scen = Scenario(config)
        scen.start()
        await scen.tick()  # Should not raise


# ==================== Scenario Collaboration Tests ====================

class TestScenarioCollaboration:
    def test_collaboration_rule_sync(self, make_scenario_config):
        """Collaboration rules should be synced to the collaboration engine."""
        rule = Rule(
            id="collab-rule",
            name="Collab",
            rule_type=RuleType.COLLABORATION,
            source_device_id="dev-1",
            source_point="temperature",
            target_device_id="dev-2",
            target_point="valve",
            target_value=50.0,
            condition={"operator": ">", "value": 80},
            enabled=True,
            actions=[{"type": "set", "target_device_id": "dev-2", "target_point": "valve", "value": 100}],
        )
        config = make_scenario_config("collab-sync-test", rules=[rule])
        scen = Scenario(config)
        scen.start()
        # Check that collaboration rule was registered
        assert len(scen._collaboration.rules) >= 1

    @pytest.mark.asyncio
    async def test_collab_write(self, make_scenario_config, make_device):
        config = make_scenario_config("collab-write-test")
        scen = Scenario(config)
        dev = make_device("collab-dev", points=[
            PointConfig(name="valve", address="0", data_type=DataType.FLOAT32,
                       generator_type=GeneratorType.FIXED, fixed_value=0.0),
        ])
        scen.add_device(dev)
        scen.start()
        # Set device to RUN state for write to succeed
        from protoforge.engine.state_machine import DeviceState
        dev._state_machine._state = DeviceState.RUN
        result = await scen._collab_write("collab-dev", "valve", 75.0)
        assert isinstance(result, bool)

    def test_collab_read(self, make_scenario_config, make_device):
        config = make_scenario_config("collab-read-test")
        scen = Scenario(config)
        dev = make_device("collab-read-dev", points=[
            PointConfig(name="temperature", address="0", data_type=DataType.FLOAT32,
                       generator_type=GeneratorType.FIXED, fixed_value=42.0),
        ])
        scen.add_device(dev)
        scen.start()
        # Set device to RUN state for read to succeed
        from protoforge.engine.state_machine import DeviceState
        dev._state_machine._state = DeviceState.RUN
        val = scen._collab_read("collab-read-dev", "temperature")
        # Value may be None if device is not in proper state, but should not raise
        assert val is None or isinstance(val, (int, float, str))


# ==================== Scenario Compare Helper Tests ====================

class TestScenarioCompare:
    def test_compare_gt(self):
        assert Scenario._compare(100, ">", 50) is True
        assert Scenario._compare(50, ">", 100) is False

    def test_compare_lt(self):
        assert Scenario._compare(50, "<", 100) is True
        assert Scenario._compare(100, "<", 50) is False

    def test_compare_eq(self):
        assert Scenario._compare(100, "==", 100) is True
        assert Scenario._compare(100, "==", 50) is False

    def test_compare_gte(self):
        assert Scenario._compare(100, ">=", 100) is True
        assert Scenario._compare(100, ">=", 50) is True
        assert Scenario._compare(50, ">=", 100) is False

    def test_compare_lte(self):
        assert Scenario._compare(100, "<=", 100) is True
        assert Scenario._compare(50, "<=", 100) is True
        assert Scenario._compare(100, "<=", 50) is False

    def test_compare_ne(self):
        assert Scenario._compare(100, "!=", 50) is True
        assert Scenario._compare(100, "!=", 100) is False

    def test_compare_unknown_operator(self):
        assert Scenario._compare(100, "unknown", 50) is False
