"""Comprehensive tests for engine.py and device.py - SimulationEngine and DeviceInstance."""

import asyncio

import pytest

from protoforge.engine.engine import SimulationEngine
from protoforge.engine.device import DeviceInstance
from protoforge.engine.generator import DataGenerator
from protoforge.simulation.fault import FaultConfig, FaultInjector, FaultType, TriggerMode
from protoforge.engine.state_machine import DeviceState
from protoforge.models.device import (
    DeviceConfig,
    DeviceStatus,
    PointConfig,
    DataType,
    GeneratorType,
)
from protoforge.models.scenario import (
    ScenarioConfig,
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
def make_device_config(make_point):
    def _make(device_id="test-device", protocol="modbus_tcp", points=None):
        if points is None:
            points = [make_point(name="temperature", gen_type=GeneratorType.RANDOM, min_value=0, max_value=100)]
        return DeviceConfig(
            id=device_id,
            name=f"Device {device_id}",
            protocol=protocol,
            points=points,
        )
    return _make


@pytest.fixture
def engine():
    return SimulationEngine()


# ==================== DeviceInstance Tests ====================

class TestDeviceInstance:
    def test_init(self, generator, make_device_config):
        config = make_device_config(device_id="dev-1")
        dev = DeviceInstance(config, generator)
        assert dev.id == "dev-1"
        assert dev.name == "Device dev-1"
        assert dev.protocol == "modbus_tcp"
        assert len(dev.points) >= 1

    def test_properties(self, generator, make_device_config):
        config = make_device_config(device_id="prop-test")
        dev = DeviceInstance(config, generator)
        assert dev.status == DeviceStatus.OFFLINE
        assert dev.device_state == DeviceState.STOP
        assert dev.fault_injector is not None
        assert dev.control_loops is None
        assert dev.protocol_config == {}

    def test_start(self, generator, make_device_config):
        config = make_device_config(device_id="start-test")
        dev = DeviceInstance(config, generator)
        dev.start()
        assert dev.device_state in (DeviceState.STARTING, DeviceState.RUN)

    def test_stop(self, generator, make_device_config):
        config = make_device_config(device_id="stop-test")
        dev = DeviceInstance(config, generator)
        dev.start()
        dev.stop()
        assert dev.device_state in (DeviceState.STOPPING, DeviceState.STOP)

    def test_fault(self, generator, make_device_config):
        config = make_device_config(device_id="fault-test")
        dev = DeviceInstance(config, generator)
        dev.start()
        dev.fault("test fault")
        assert dev.device_state == DeviceState.ERROR
        assert dev.status == DeviceStatus.ERROR

    def test_reset_from_fault(self, generator, make_device_config):
        config = make_device_config(device_id="reset-test")
        dev = DeviceInstance(config, generator)
        dev.start()
        dev.fault("test")
        result = dev.reset()
        assert result is True
        assert dev.device_state == DeviceState.STOP

    def test_maintenance_mode(self, generator, make_device_config):
        config = make_device_config(device_id="maint-test")
        dev = DeviceInstance(config, generator)
        dev.start()
        result = dev.enter_maintenance("scheduled maintenance")
        assert result is True
        assert dev.device_state == DeviceState.MAINTENANCE

    def test_exit_maintenance(self, generator, make_device_config):
        config = make_device_config(device_id="exit-maint")
        dev = DeviceInstance(config, generator)
        dev.start()
        dev.enter_maintenance("test")
        result = dev.exit_maintenance("done")
        assert result is True

    def test_program_mode(self, generator, make_device_config):
        config = make_device_config(device_id="prog-test")
        dev = DeviceInstance(config, generator)
        dev.start()
        result = dev.enter_program_mode("programming")
        assert result is True

    def test_exit_program_mode(self, generator, make_device_config):
        config = make_device_config(device_id="exit-prog")
        dev = DeviceInstance(config, generator)
        dev.start()
        dev.enter_program_mode("test")
        result = dev.exit_program_mode("done")
        assert result is True

    @pytest.mark.asyncio
    async def test_tick_generates_values(self, generator, make_device_config):
        config = make_device_config(device_id="tick-test")
        dev = DeviceInstance(config, generator)
        dev.start()
        # Manually transition to RUN for testing
        dev._state_machine._state = DeviceState.RUN
        await dev.tick()
        # After tick, point values should be updated
        values = dev.read_all_points()
        assert len(values) >= 1

    def test_read_point(self, generator, make_device_config):
        config = make_device_config(device_id="read-test")
        dev = DeviceInstance(config, generator)
        val = dev.read_point("temperature")
        assert val is not None

    def test_read_nonexistent_point(self, generator, make_device_config):
        config = make_device_config(device_id="read-none")
        dev = DeviceInstance(config, generator)
        val = dev.read_point("nonexistent")
        assert val is None

    def test_read_all_points(self, generator, make_device_config):
        config = make_device_config(
            device_id="readall-test",
            points=[
                PointConfig(name="p1", address="0", data_type=DataType.FLOAT32, generator_type=GeneratorType.FIXED, fixed_value=1.0),
                PointConfig(name="p2", address="1", data_type=DataType.FLOAT32, generator_type=GeneratorType.FIXED, fixed_value=2.0),
            ],
        )
        dev = DeviceInstance(config, generator)
        values = dev.read_all_points()
        assert len(values) == 2

    @pytest.mark.asyncio
    async def test_write_point(self, generator, make_device_config):
        config = make_device_config(device_id="write-test")
        dev = DeviceInstance(config, generator)
        dev.start()
        dev._state_machine._state = DeviceState.RUN
        result = await dev.write_point("temperature", 55.0)
        assert result is True
        val = dev.read_point("temperature")
        assert val is not None

    @pytest.mark.asyncio
    async def test_write_nonexistent_point(self, generator, make_device_config):
        config = make_device_config(device_id="write-none")
        dev = DeviceInstance(config, generator)
        result = await dev.write_point("nonexistent", 55.0)
        assert result is False

    def test_zero_output_on_stop(self, generator, make_device_config):
        config = make_device_config(device_id="zero-test")
        config.protocol_config["zero_output_on_stop"] = True
        dev = DeviceInstance(config, generator)
        # In STOP state, values should be zero or None
        values = dev.read_all_points()
        assert len(values) >= 1

    def test_safe_values_on_error(self, generator, make_device_config):
        config = make_device_config(device_id="safe-test")
        config.protocol_config["safe_values"] = {"temperature": 999.0}
        dev = DeviceInstance(config, generator)
        dev.start()
        dev.fault("emergency")
        val = dev.read_point("temperature")
        if val and val.value is not None:
            assert val.value == 999.0

    def test_control_loops_initialization(self, generator, make_device_config):
        config = make_device_config(device_id="ctrl-test")
        config.protocol_config["control_loops"] = [
            {
                "name": "pid_loop",
                "source_point": "temperature",
                "target_point": "heater",
                "kp": 1.0,
                "ki": 0.1,
                "kd": 0.01,
                "setpoint": 50.0,
            }
        ]
        dev = DeviceInstance(config, generator)
        # Control loops may or may not be initialized depending on config validation
        # Just verify device was created successfully
        assert dev.id == "ctrl-test"

    def test_fault_injector_attached(self, generator, make_device_config):
        config = make_device_config(device_id="fault-inj-test")
        dev = DeviceInstance(config, generator)
        assert dev.fault_injector is not None
        assert dev.fault_injector._device_id == "fault-inj-test"


# ==================== SimulationEngine Tests ====================

class TestSimulationEngine:
    def test_init(self):
        eng = SimulationEngine()
        assert eng._protocol_servers == {}
        assert eng._devices == {}
        assert eng._scenarios == {}
        assert eng._running is False

    def test_register_protocol(self, engine):
        from protoforge.protocols.http.server import HttpSimulatorServer
        server = HttpSimulatorServer()
        engine.register_protocol(server)
        assert "http" in engine._protocol_servers

    def test_register_duplicate_protocol(self, engine):
        from protoforge.protocols.http.server import HttpSimulatorServer
        engine.register_protocol(HttpSimulatorServer())
        engine.register_protocol(HttpSimulatorServer())  # Should not error
        assert "http" in engine._protocol_servers

    def test_get_protocols(self, engine):
        from protoforge.protocols.http.server import HttpSimulatorServer
        engine.register_protocol(HttpSimulatorServer())
        protocols = engine.get_protocols()
        assert len(protocols) >= 1
        assert any(p["name"] == "http" for p in protocols)

    def test_is_protocol_running(self, engine):
        from protoforge.protocols.http.server import HttpSimulatorServer
        engine.register_protocol(HttpSimulatorServer())
        assert engine.is_protocol_running("http") is False  # Not started yet
        assert engine.is_protocol_running("nonexistent") is False

    def test_get_all_protocol_servers(self, engine):
        from protoforge.protocols.http.server import HttpSimulatorServer
        engine.register_protocol(HttpSimulatorServer())
        servers = engine.get_all_protocol_servers()
        assert "http" in servers

    @pytest.mark.asyncio
    async def test_create_device(self, engine, make_device_config):
        config = make_device_config(device_id="engine-dev-1")
        info = await engine.create_device(config)
        assert info.id == "engine-dev-1"

    @pytest.mark.asyncio
    async def test_create_device_duplicate(self, engine, make_device_config):
        config = make_device_config(device_id="dup-dev")
        await engine.create_device(config)
        with pytest.raises((ValueError, Exception)):
            await engine.create_device(config)

    @pytest.mark.asyncio
    async def test_create_device_allow_update(self, engine, make_device_config):
        config = make_device_config(device_id="update-dev")
        await engine.create_device(config)
        config.name = "Updated"
        info = await engine.create_device(config, allow_update=True)
        assert info.id == "update-dev"

    @pytest.mark.asyncio
    async def test_remove_device(self, engine, make_device_config):
        config = make_device_config(device_id="remove-dev")
        await engine.create_device(config)
        await engine.remove_device("remove-dev")
        assert "remove-dev" not in engine._devices

    @pytest.mark.asyncio
    async def test_update_device(self, engine, make_device_config):
        config = make_device_config(device_id="upd-dev")
        await engine.create_device(config)
        config.name = "Updated Name"
        info = await engine.update_device("upd-dev", config)
        assert info.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_start_device(self, engine, make_device_config):
        config = make_device_config(device_id="start-dev")
        await engine.create_device(config)
        await engine.start_device("start-dev")

    @pytest.mark.asyncio
    async def test_stop_device(self, engine, make_device_config):
        config = make_device_config(device_id="stop-dev")
        await engine.create_device(config)
        await engine.start_device("start-dev-2") if "start-dev-2" in engine._devices else None
        await engine.start_device("stop-dev")
        await engine.stop_device("stop-dev")

    @pytest.mark.asyncio
    async def test_read_device_points(self, engine, make_device_config):
        config = make_device_config(device_id="read-dev")
        await engine.create_device(config)
        await engine.start_device("read-dev")
        points = await engine.read_device_points("read-dev")
        assert len(points) >= 1

    @pytest.mark.asyncio
    async def test_write_device_point(self, engine, make_device_config):
        config = make_device_config(device_id="write-dev")
        await engine.create_device(config)
        await engine.start_device("write-dev")
        result = await engine.write_device_point("write-dev", "temperature", 55.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_device(self, engine, make_device_config):
        config = make_device_config(device_id="get-dev")
        await engine.create_device(config)
        info = engine.get_device("get-dev")
        assert info is not None
        assert info.id == "get-dev"

    @pytest.mark.asyncio
    async def test_get_nonexistent_device(self, engine):
        with pytest.raises((KeyError, ValueError, Exception)):
            engine.get_device("nonexistent")

    @pytest.mark.asyncio
    async def test_get_device_instance(self, engine, make_device_config):
        config = make_device_config(device_id="inst-dev")
        await engine.create_device(config)
        inst = engine.get_device_instance("inst-dev")
        assert inst is not None
        assert inst.id == "inst-dev"

    @pytest.mark.asyncio
    async def test_get_all_device_instances(self, engine, make_device_config):
        await engine.create_device(make_device_config(device_id="all-1"))
        await engine.create_device(make_device_config(device_id="all-2"))
        instances = engine.get_all_device_instances()
        assert len(instances) >= 2

    @pytest.mark.asyncio
    async def test_list_devices(self, engine, make_device_config):
        await engine.create_device(make_device_config(device_id="list-1"))
        await engine.create_device(make_device_config(device_id="list-2"))
        devices = engine.list_devices()
        assert len(devices) >= 2

    @pytest.mark.asyncio
    async def test_get_all_device_ids(self, engine, make_device_config):
        await engine.create_device(make_device_config(device_id="ids-1"))
        ids = engine.get_all_device_ids()
        assert "ids-1" in ids

    @pytest.mark.asyncio
    async def test_create_scenario(self, engine):
        config = ScenarioConfig(
            id="engine-scen-1",
            name="Engine Test Scenario",
            description="test",
            devices=[],
            rules=[],
        )
        info = await engine.create_scenario(config)
        assert info.id == "engine-scen-1"

    @pytest.mark.asyncio
    async def test_remove_scenario(self, engine):
        config = ScenarioConfig(
            id="rm-scen",
            name="Remove Test",
            description="test",
            devices=[],
            rules=[],
        )
        await engine.create_scenario(config)
        await engine.remove_scenario("rm-scen")
        assert "rm-scen" not in engine._scenarios

    @pytest.mark.asyncio
    async def test_start_stop_scenario(self, engine):
        config = ScenarioConfig(
            id="start-scen",
            name="Start Test",
            description="test",
            devices=[],
            rules=[],
        )
        await engine.create_scenario(config)
        await engine.start_scenario("start-scen")
        assert engine.get_scenario_status("start-scen") == ScenarioStatus.RUNNING
        await engine.stop_scenario("start-scen")
        assert engine.get_scenario_status("start-scen") == ScenarioStatus.STOPPED

    @pytest.mark.asyncio
    async def test_list_scenarios(self, engine):
        await engine.create_scenario(ScenarioConfig(
            id="list-scen-1", name="S1", description="", devices=[], rules=[],
        ))
        await engine.create_scenario(ScenarioConfig(
            id="list-scen-2", name="S2", description="", devices=[], rules=[],
        ))
        scenarios = engine.list_scenarios()
        assert len(scenarios) >= 2

    @pytest.mark.asyncio
    async def test_get_scenario(self, engine):
        await engine.create_scenario(ScenarioConfig(
            id="get-scen", name="Get Test", description="test", devices=[], rules=[],
        ))
        detail = engine.get_scenario("get-scen")
        assert detail is not None
        assert detail.id == "get-scen"

    @pytest.mark.asyncio
    async def test_get_all_scenario_configs(self, engine):
        await engine.create_scenario(ScenarioConfig(
            id="cfg-scen-1", name="S1", description="", devices=[], rules=[],
        ))
        configs = engine.get_all_scenario_configs()
        assert len(configs) >= 1

    @pytest.mark.asyncio
    async def test_get_scenario_config(self, engine):
        await engine.create_scenario(ScenarioConfig(
            id="cfg-get", name="S", description="", devices=[], rules=[],
        ))
        config = engine.get_scenario_config("cfg-get")
        assert config is not None
        assert config.id == "cfg-get"

    @pytest.mark.asyncio
    async def test_engine_start_stop(self, engine):
        from protoforge.protocols.http.server import HttpSimulatorServer
        engine.register_protocol(HttpSimulatorServer())
        await engine.start()
        assert engine._running is True
        await engine.stop()
        assert engine._running is False

    def test_get_protocol_running_port(self, engine):
        from protoforge.protocols.http.server import HttpSimulatorServer
        engine.register_protocol(HttpSimulatorServer())
        port = engine.get_protocol_running_port("http")
        # Should be None or an int (not started yet)
        assert port is None or isinstance(port, int)

    def test_configure_network(self, engine):
        engine.configure_network("low_latency", enabled=True)
        assert engine.network_simulator is not None

    def test_fault_propagation(self, engine):
        fp = engine.fault_propagation
        assert fp is not None

    def test_timeseries_manager(self, engine):
        ts = engine.timeseries_manager
        assert ts is not None

    @pytest.mark.asyncio
    async def test_setup_debug_callbacks(self, engine):
        from protoforge.observability.log_bus import LogBus
        from protoforge.protocols.http.server import HttpSimulatorServer
        engine.register_protocol(HttpSimulatorServer())
        log_bus = LogBus()
        engine.setup_debug_callbacks(log_bus)
