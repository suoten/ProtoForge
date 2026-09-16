"""Tests for core modules to improve test coverage.

Covers: recorder, forward, webhook, generator, auth, fault_injection, state_machine.
"""

import asyncio
import time

import pytest

from protoforge.core.auth import (
    UserManager,
    create_token,
    verify_token,
    hash_password,
    verify_password,
    set_secret_key,
    create_refresh_token,
    verify_refresh_token,
)
from protoforge.simulation.fault.injector import FaultInjector
from protoforge.simulation.fault_injection import FaultType, TriggerMode, FaultConfig
from protoforge.integrations.forward import ForwardEngine, HTTPTarget, InfluxDBTarget
from protoforge.engine.generator import DataGenerator
from protoforge.observability.log_bus import LogBus
from protoforge.observability.recorder import Recorder
from protoforge.engine.state_machine import DeviceStateMachine, DeviceState, StateTransition
from protoforge.integrations.webhook import WebhookManager, WebhookConfig
from protoforge.models.device import PointConfig, GeneratorType, DataType


# ==================== Fixtures ====================

@pytest.fixture
def log_bus():
    """Create a LogBus instance for testing."""
    return LogBus(max_entries=100)


@pytest.fixture(autouse=True)
def setup_secret_key():
    """Set a test secret key for JWT operations."""
    set_secret_key("test_secret_key_for_pytest_only")


# ==================== Recorder Tests ====================

class TestRecorder:
    """Tests for the Recorder module."""

    def test_recorder_initialization(self, log_bus):
        """Test Recorder can be initialized."""
        recorder = Recorder(log_bus)
        assert recorder is not None

    def test_recorder_list_recordings(self, log_bus):
        """Test listing recordings."""
        recorder = Recorder(log_bus)
        recordings = recorder.list_recordings()
        assert isinstance(recordings, list)

    def test_recorder_get_stats(self, log_bus):
        """Test getting recorder stats."""
        recorder = Recorder(log_bus)
        stats = recorder.get_stats()
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_recorder_start_stop(self, log_bus):
        """Test recorder start and stop."""
        recorder = Recorder(log_bus)
        recording = await recorder.start_recording(
            name="test_recording",
            protocol="modbus",
            device_id="dev1",
        )
        assert recording is not None
        result = await recorder.stop_recording()
        assert result is not None

    def test_recorder_max_messages_config(self, log_bus):
        """Test recorder respects max messages config."""
        recorder = Recorder(log_bus)
        max_msgs = recorder._get_max_messages()
        assert isinstance(max_msgs, int)
        assert max_msgs > 0

    def test_recorder_max_message_size_config(self, log_bus):
        """Test recorder max message size config."""
        recorder = Recorder(log_bus)
        max_size = recorder._get_max_message_size()
        assert isinstance(max_size, int)
        assert max_size > 0


# ==================== ForwardEngine Tests ====================

class TestForwardEngine:
    """Tests for the ForwardEngine module."""

    def test_forward_engine_initialization(self, log_bus):
        """Test ForwardEngine can be initialized."""
        engine = ForwardEngine(log_bus)
        assert engine is not None
        assert not engine._running

    def test_forward_engine_add_remove_target(self, log_bus):
        """Test adding and removing targets."""
        engine = ForwardEngine(log_bus)
        target = HTTPTarget(url="http://example.com/ingest")
        engine.add_target("test_target", target)
        assert "test_target" in engine._targets
        engine.remove_target("test_target")
        assert "test_target" not in engine._targets

    def test_forward_engine_stats(self, log_bus):
        """Test getting forward stats."""
        engine = ForwardEngine(log_bus)
        stats = engine.get_stats()
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_forward_engine_start_stop(self, log_bus):
        """Test forward engine start/stop."""
        engine = ForwardEngine(log_bus)
        await engine.start()
        assert engine._running
        await engine.stop()
        assert not engine._running

    def test_influxdb_target_creation(self):
        """Test InfluxDBTarget can be created."""
        target = InfluxDBTarget(
            url="http://localhost:8086",
            token="test_token",
            org="test_org",
            bucket="test_bucket",
        )
        assert target is not None

    def test_http_target_creation(self):
        """Test HTTPTarget can be created."""
        target = HTTPTarget(url="http://example.com/ingest")
        assert target is not None


# ==================== WebhookManager Tests ====================

class TestWebhookManager:
    """Tests for the WebhookManager module."""

    def _make_config_dict(self, **overrides):
        """Create a webhook config dict."""
        config = {
            "id": "wh_test",
            "name": "test_webhook",
            "url": "http://example.com/hook",
            "events": ["device_created"],
        }
        config.update(overrides)
        return config

    def test_webhook_manager_initialization(self):
        """Test WebhookManager can be initialized."""
        mgr = WebhookManager()
        assert mgr is not None

    def test_webhook_manager_add(self):
        """Test adding a webhook."""
        mgr = WebhookManager()
        config = self._make_config_dict(id="wh1")
        mgr.add_webhook(config)
        hooks = mgr.list_webhooks()
        assert any(h["id"] == "wh1" for h in hooks)

    def test_webhook_manager_remove(self):
        """Test removing a webhook."""
        mgr = WebhookManager()
        config = self._make_config_dict(id="wh_remove")
        mgr.add_webhook(config)
        mgr.remove_webhook("wh_remove")
        hooks = mgr.list_webhooks()
        assert not any(h["id"] == "wh_remove" for h in hooks)

    def test_webhook_manager_update(self):
        """Test updating a webhook."""
        mgr = WebhookManager()
        config = self._make_config_dict(id="wh_update", name="original")
        mgr.add_webhook(config)
        updated = self._make_config_dict(id="wh_update", name="updated", url="http://example.com/hook2")
        mgr.update_webhook("wh_update", updated)
        hooks = mgr.list_webhooks()
        wh = next(h for h in hooks if h["id"] == "wh_update")
        assert wh["name"] == "updated"

    def test_webhook_manager_stats(self):
        """Test getting webhook stats."""
        mgr = WebhookManager()
        stats = mgr.get_stats()
        assert isinstance(stats, dict)

    @pytest.mark.asyncio
    async def test_webhook_trigger(self):
        """Test triggering a webhook."""
        mgr = WebhookManager()
        config = self._make_config_dict(id="wh_trigger")
        mgr.add_webhook(config)
        await mgr.trigger("device_created", {"device_id": "test"})


# ==================== DataGenerator Tests ====================

class TestDataGenerator:
    """Tests for the DataGenerator module."""

    def _make_point(self, name="test_point", gen_type=GeneratorType.FIXED, fixed_value=42.0, **kwargs):
        """Helper to create a PointConfig."""
        return PointConfig(
            name=name,
            address="40001",
            data_type=DataType.FLOAT32,
            generator_type=gen_type,
            fixed_value=fixed_value,
            **kwargs,
        )

    def test_generator_initialization(self):
        """Test DataGenerator can be initialized."""
        gen = DataGenerator()
        assert gen is not None

    def test_generate_fixed(self):
        """Test generating a fixed value."""
        gen = DataGenerator()
        point = self._make_point(gen_type=GeneratorType.FIXED, fixed_value=42.5)
        value = gen.generate(point)
        assert value == 42.5

    def test_generate_random(self):
        """Test generating a random value."""
        gen = DataGenerator()
        point = self._make_point(
            gen_type=GeneratorType.RANDOM, min_value=0.0, max_value=100.0,
        )
        value = gen.generate(point)
        assert isinstance(value, (int, float))

    def test_generate_sine(self):
        """Test generating a sine wave value."""
        gen = DataGenerator()
        point = self._make_point(
            gen_type=GeneratorType.SINE,
            generator_config={"amplitude": 10.0, "frequency": 1.0, "phase": 0.0, "offset": 5.0},
        )
        value = gen.generate(point)
        assert isinstance(value, (int, float))

    def test_generate_square(self):
        """Test generating a square wave value."""
        gen = DataGenerator()
        point = self._make_point(
            gen_type=GeneratorType.SQUARE,
            generator_config={"amplitude": 10.0, "frequency": 1.0},
        )
        value = gen.generate(point)
        assert isinstance(value, (int, float))

    def test_generate_triangle(self):
        """Test generating a triangle wave value."""
        gen = DataGenerator()
        point = self._make_point(
            gen_type=GeneratorType.TRIANGLE,
            generator_config={"amplitude": 10.0, "frequency": 1.0},
        )
        value = gen.generate(point)
        assert isinstance(value, (int, float))

    def test_generate_increment(self):
        """Test generating an incrementing value."""
        gen = DataGenerator()
        point = self._make_point(
            gen_type=GeneratorType.INCREMENT,
            generator_config={"start_value": 0.0, "increment": 1.0},
        )
        v1 = gen.generate(point)
        v2 = gen.generate(point)
        assert v2 >= v1

    def test_generate_with_fault_injector(self):
        """Test that fault injector is applied to generated values."""
        injector = FaultInjector(device_id="test_dev")
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_STUCK,
            target_point="test_point",
            trigger_mode=TriggerMode.MANUAL,
        ))
        gen = DataGenerator(fault_injector=injector)
        point = self._make_point(gen_type=GeneratorType.FIXED, fixed_value=100.0)
        v1 = gen.generate(point)
        v2 = gen.generate(point)
        # SENSOR_STUCK should freeze the value after first read
        assert v1 == v2


# ==================== Auth Tests ====================

class TestAuth:
    """Tests for the auth module."""

    def test_hash_and_verify_password(self):
        """Test password hashing and verification."""
        password = "test_password_123"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed)
        assert not verify_password("wrong_password", hashed)

    def test_create_and_verify_token(self):
        """Test JWT token creation and verification."""
        token = create_token("user_123", "testuser", "admin")
        assert token is not None
        payload = verify_token(token)
        assert payload is not None
        assert payload["username"] == "testuser"
        assert payload["role"] == "admin"

    def test_verify_invalid_token(self):
        """Test that invalid tokens are rejected."""
        assert verify_token("invalid.token.here") is None

    def test_verify_expired_token(self):
        """Test that expired tokens are rejected."""
        token = create_token("user_123", "user", "viewer", expires_in=-1)
        assert verify_token(token) is None

    def test_create_and_verify_refresh_token(self):
        """Test refresh token creation and verification."""
        token = create_refresh_token("user_123")
        assert token is not None
        user_id = verify_refresh_token(token)
        assert user_id == "user_123"

    def test_user_manager_initialization(self):
        """Test UserManager can be initialized."""
        mgr = UserManager()
        assert mgr is not None
        assert "admin" in mgr._users

    @pytest.mark.asyncio
    async def test_user_manager_authenticate(self):
        """Test UserManager authenticate method."""
        mgr = UserManager()
        await mgr.create_user("testuser", "TestPass123!", role="viewer")
        user, _ = await mgr.authenticate("testuser", "TestPass123!")
        assert user is not None

    @pytest.mark.asyncio
    async def test_user_manager_create_user(self):
        """Test UserManager user creation."""
        mgr = UserManager()
        await mgr.create_user("newuser", "TestPass123!", role="viewer")
        user, _ = await mgr.authenticate("newuser", "TestPass123!")
        assert user is not None

    @pytest.mark.asyncio
    async def test_user_manager_wrong_password(self):
        """Test that wrong password is rejected."""
        mgr = UserManager()
        await mgr.create_user("authuser", "CorrectPass123!", role="viewer")
        user, _ = await mgr.authenticate("authuser", "WrongPass123!")
        assert user is None

    @pytest.mark.asyncio
    async def test_user_manager_change_password(self):
        """Test UserManager password change."""
        mgr = UserManager()
        await mgr.create_user("pwduser", "OldPass123!", role="viewer")
        ok, _ = await mgr.change_password("pwduser", "OldPass123!", "NewPass123!")
        assert ok
        user, _ = await mgr.authenticate("pwduser", "NewPass123!")
        assert user is not None
        user, _ = await mgr.authenticate("pwduser", "OldPass123!")
        assert user is None

    @pytest.mark.asyncio
    async def test_user_manager_delete_user(self):
        """Test UserManager user deletion."""
        mgr = UserManager()
        await mgr.create_user("deleteuser", "Delete123!", role="viewer")
        await mgr.delete_user("deleteuser")
        user, _ = await mgr.authenticate("deleteuser", "Delete123!")
        assert user is None

    @pytest.mark.asyncio
    async def test_user_manager_update_role(self):
        """Test UserManager role update."""
        mgr = UserManager()
        await mgr.create_user("roleuser", "Role123!", role="viewer")
        await mgr.update_user_role("roleuser", "operator")
        user = mgr.get_user_by_username("roleuser")
        assert user is not None
        assert user.role == "operator"

    def test_user_manager_list_users(self):
        """Test listing users."""
        mgr = UserManager()
        users = mgr.list_users()
        assert isinstance(users, list)
        assert len(users) >= 1  # At least admin


# ==================== Fault Injection Tests ====================

class TestFaultInjection:
    """Tests for the fault injection module."""

    def test_fault_type_values(self):
        """Test FaultType enum values."""
        assert FaultType.SENSOR_STUCK.value == "sensor_stuck"
        assert FaultType.SENSOR_NOISE.value == "sensor_noise"
        assert FaultType.SENSOR_DRIFT.value == "sensor_drift"
        assert FaultType.DEVICE_FAILURE.value == "device_failure"

    def test_trigger_mode_values(self):
        """Test TriggerMode enum values."""
        assert TriggerMode.MANUAL.value == "manual"
        assert TriggerMode.RANDOM.value == "random"
        assert TriggerMode.SCHEDULED.value == "scheduled"
        assert TriggerMode.CONDITIONAL.value == "conditional"

    def test_fault_config_creation(self):
        """Test FaultConfig can be created."""
        config = FaultConfig(
            fault_type=FaultType.SENSOR_STUCK,
            target_point="temperature",
            trigger_mode=TriggerMode.MANUAL,
            parameters={"threshold": 100},
        )
        assert config.fault_type == FaultType.SENSOR_STUCK
        assert config.target_point == "temperature"

    def test_fault_injector_initialization(self):
        """Test FaultInjector can be initialized."""
        injector = FaultInjector(device_id="test_device")
        assert injector is not None

    def test_fault_injector_add_and_get(self):
        """Test adding and getting faults."""
        injector = FaultInjector(device_id="test_device")
        config = FaultConfig(
            fault_type=FaultType.SENSOR_STUCK,
            target_point="temperature",
            trigger_mode=TriggerMode.MANUAL,
        )
        fault_id = injector.add_fault(config)
        assert fault_id is not None
        faults = injector.get_active_faults()
        assert len(faults) >= 1

    def test_fault_injector_remove(self):
        """Test removing a fault."""
        injector = FaultInjector(device_id="test_device")
        config = FaultConfig(
            fault_type=FaultType.SENSOR_NOISE,
            target_point="pressure",
            trigger_mode=TriggerMode.MANUAL,
            parameters={"amplitude": 5.0},
        )
        fault_id = injector.add_fault(config)
        injector.remove_fault(fault_id)
        faults = injector.get_active_faults()
        assert len(faults) == 0

    def test_fault_injector_clear_all(self):
        """Test clearing all faults."""
        injector = FaultInjector(device_id="test_device")
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_STUCK, target_point="temp1",
            trigger_mode=TriggerMode.MANUAL,
        ))
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_DRIFT, target_point="temp2",
            trigger_mode=TriggerMode.MANUAL, parameters={"rate": 0.1},
        ))
        injector.clear_all_faults()
        assert len(injector.get_active_faults()) == 0

    def test_fault_injector_apply_stuck(self):
        """Test applying sensor stuck fault."""
        injector = FaultInjector(device_id="test_device")
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_STUCK, target_point="temperature",
            trigger_mode=TriggerMode.MANUAL,
        ))
        val1, faulty1 = injector.apply("temperature", 42.0)
        val2, faulty2 = injector.apply("temperature", 99.0)
        # SENSOR_STUCK should freeze at the first value
        assert val1 == val2 == 42.0
        assert faulty1 == "uncertain"
        assert faulty2 == "uncertain"

    def test_fault_injector_apply_noise(self):
        """Test applying sensor noise fault."""
        injector = FaultInjector(device_id="test_device")
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_NOISE, target_point="flow",
            trigger_mode=TriggerMode.MANUAL, parameters={"noise_std": 5.0},
        ))
        val, faulty = injector.apply("flow", 100.0)
        # FIXED: apply() returns quality string ("good"/"uncertain"/"bad"), not bool
        assert faulty == "uncertain"
        # noise_std=5.0 → value = 100 + gauss(0, 5); allow ±3σ for statistical robustness
        assert 85.0 <= val <= 115.0

    def test_fault_injector_apply_drift(self):
        """Test applying sensor drift fault."""
        injector = FaultInjector(device_id="test_device")
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_DRIFT, target_point="pressure",
            trigger_mode=TriggerMode.MANUAL, parameters={"rate": 0.5},
        ))
        val, faulty = injector.apply("pressure", 50.0)
        assert faulty == "uncertain"

    def test_fault_injector_no_fault(self):
        """Test that apply returns original value when no fault is active."""
        injector = FaultInjector(device_id="test_device")
        val, faulty = injector.apply("temperature", 42.0)
        assert val == 42.0
        assert faulty == "good"

    def test_fault_injector_get_all_faults(self):
        """Test getting all faults."""
        injector = FaultInjector(device_id="test_device")
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_STUCK, target_point="temp",
            trigger_mode=TriggerMode.MANUAL,
        ))
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_NOISE, target_point="pressure",
            trigger_mode=TriggerMode.MANUAL, parameters={"amplitude": 2.0},
        ))
        all_faults = injector.get_all_faults()
        assert len(all_faults) >= 2

    def test_fault_injector_activate_deactivate(self):
        """Test activating and deactivating faults."""
        injector = FaultInjector(device_id="test_device")
        fault_id = injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_STUCK, target_point="temp",
            trigger_mode=TriggerMode.MANUAL,
        ))
        injector.deactivate_fault(fault_id)
        # Deactivated fault should not apply
        val, faulty = injector.apply("temp", 100.0)
        assert faulty == "good"
        injector.activate_fault(fault_id)
        val, faulty = injector.apply("temp", 100.0)
        assert faulty == "uncertain"

    def test_fault_injector_to_dict(self):
        """Test fault injector serialization."""
        injector = FaultInjector(device_id="test_device")
        injector.add_fault(FaultConfig(
            fault_type=FaultType.SENSOR_STUCK, target_point="temp",
            trigger_mode=TriggerMode.MANUAL,
        ))
        data = injector.to_dict()
        assert isinstance(data, dict)


# ==================== State Machine Tests ====================

class TestDeviceStateMachine:
    """Tests for the DeviceStateMachine module."""

    def test_state_machine_creation(self):
        """Test DeviceStateMachine can be created."""
        sm = DeviceStateMachine(device_id="test_device")
        assert sm is not None
        assert sm._state == DeviceState.STOP

    def test_state_machine_initial_running(self):
        """Test DeviceStateMachine with initial running state."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN, device_id="test_device")
        assert sm._state == DeviceState.RUN

    def test_state_machine_trigger_start(self):
        """Test triggering start transition."""
        sm = DeviceStateMachine(device_id="test_device")
        result = sm.trigger("start")
        assert result is True
        assert sm._state in (DeviceState.STARTING, DeviceState.RUN)

    def test_state_machine_trigger_stop(self):
        """Test triggering stop transition."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN, device_id="test_device")
        result = sm.trigger("stop")
        assert result is True
        assert sm._state in (DeviceState.STOPPING, DeviceState.STOP)

    def test_state_machine_trigger_error(self):
        """Test triggering error transition."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN, device_id="test_device")
        result = sm.trigger("fault")
        assert result is True
        assert sm._state == DeviceState.ERROR

    def test_state_machine_history(self):
        """Test state history."""
        sm = DeviceStateMachine(device_id="test_device")
        sm.trigger("start")
        history = sm.get_history()
        assert len(history) >= 1

    def test_state_machine_state_duration(self):
        """Test state duration tracking."""
        sm = DeviceStateMachine(device_id="test_device")
        duration = sm.get_state_duration()
        assert isinstance(duration, float)
        assert duration >= 0

    def test_state_machine_can_trigger(self):
        """Test can_trigger method."""
        sm = DeviceStateMachine(device_id="test_device")
        assert sm.can_trigger("start") is True

    def test_device_state_enum(self):
        """Test DeviceState enum values."""
        assert DeviceState.STOP.value == "stop"
        assert DeviceState.RUN.value == "run"
        assert DeviceState.ERROR.value == "error"

    def test_state_transition_dataclass(self):
        """Test StateTransition data class."""
        transition = StateTransition(
            from_state=DeviceState.STOP,
            to_state=DeviceState.STARTING,
            trigger="start",
            guard="user request",
        )
        assert transition.from_state == DeviceState.STOP
        assert transition.to_state == DeviceState.STARTING
        assert transition.trigger == "start"
