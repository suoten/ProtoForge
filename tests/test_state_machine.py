"""Unit tests for protoforge.engine.state_machine device state machine."""

import pytest

from protoforge.engine.state_machine import (
    DeviceState,
    DeviceStateMachine,
    StateTransition,
    device_state_to_status,
)


class TestDeviceState:
    """Tests for the DeviceState enum."""

    def test_state_values(self):
        assert DeviceState.STOP.value == "stop"
        assert DeviceState.RUN.value == "run"
        assert DeviceState.ERROR.value == "error"
        assert DeviceState.PROGRAM.value == "program"
        assert DeviceState.MAINTENANCE.value == "maintenance"
        assert DeviceState.STARTING.value == "starting"
        assert DeviceState.STOPPING.value == "stopping"

    def test_state_is_string(self):
        """DeviceState should be a string enum."""
        assert isinstance(DeviceState.STOP, str)
        assert DeviceState.STOP == "stop"


class TestStateTransition:
    """Tests for StateTransition dataclass."""

    def test_matches_specific_from_state(self):
        t = StateTransition(from_state=DeviceState.STOP, to_state=DeviceState.STARTING, trigger="start")
        assert t.matches(DeviceState.STOP, "start")
        assert not t.matches(DeviceState.RUN, "start")

    def test_matches_any_from_state(self):
        """None as from_state should match any state."""
        t = StateTransition(from_state=None, to_state=DeviceState.MAINTENANCE, trigger="maintenance_mode")
        assert t.matches(DeviceState.STOP, "maintenance_mode")
        assert t.matches(DeviceState.RUN, "maintenance_mode")
        assert t.matches(DeviceState.ERROR, "maintenance_mode")

    def test_does_not_match_wrong_trigger(self):
        t = StateTransition(from_state=DeviceState.STOP, to_state=DeviceState.STARTING, trigger="start")
        assert not t.matches(DeviceState.STOP, "fault")


class TestDeviceStateMachine:
    """Tests for the DeviceStateMachine."""

    def test_initial_state_is_stop(self):
        sm = DeviceStateMachine()
        assert sm.state == DeviceState.STOP

    def test_custom_initial_state(self):
        sm = DeviceStateMachine(initial_state=DeviceState.RUN)
        assert sm.state == DeviceState.RUN

    def test_start_transition(self):
        """STOP → STARTING via 'start' trigger."""
        sm = DeviceStateMachine()
        result = sm.trigger("start")
        assert result is True
        assert sm.state == DeviceState.STARTING

    def test_startup_complete_transition(self):
        """STARTING → RUN via 'startup_complete' trigger."""
        sm = DeviceStateMachine(initial_state=DeviceState.STARTING, min_startup_time=0.0)
        sm.trigger("startup_complete")
        assert sm.state == DeviceState.RUN

    def test_stop_from_run(self):
        """RUN → STOPPING via 'stop' trigger."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN)
        sm.trigger("stop")
        assert sm.state == DeviceState.STOPPING

    def test_stop_complete_transition(self):
        """STOPPING → STOP via 'stop_complete' trigger."""
        sm = DeviceStateMachine(initial_state=DeviceState.STOPPING)
        sm.trigger("stop_complete")
        assert sm.state == DeviceState.STOP

    def test_fault_from_run(self):
        """RUN → ERROR via 'fault' trigger."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN)
        sm.trigger("fault")
        assert sm.state == DeviceState.ERROR

    def test_reset_from_error(self):
        """ERROR → STOP via 'reset' trigger with fault_cleared=True."""
        sm = DeviceStateMachine(initial_state=DeviceState.ERROR)
        sm.trigger("reset", fault_cleared=True)
        assert sm.state == DeviceState.STOP

    def test_maintenance_mode(self):
        """Any state → MAINTENANCE via 'maintenance' trigger."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN)
        sm.trigger("maintenance")
        assert sm.state == DeviceState.MAINTENANCE

    def test_maintenance_complete(self):
        """MAINTENANCE → STOP via 'maintenance_complete' trigger."""
        sm = DeviceStateMachine(initial_state=DeviceState.MAINTENANCE)
        sm.trigger("maintenance_complete")
        assert sm.state == DeviceState.STOP

    def test_program_mode(self):
        """Any state → PROGRAM via 'program_mode' trigger."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN)
        sm.trigger("program_mode")
        assert sm.state == DeviceState.PROGRAM

    def test_invalid_transition_returns_false(self):
        """Invalid transition should return False, not raise."""
        sm = DeviceStateMachine(initial_state=DeviceState.STOP)
        # 'stop' from STOP is invalid
        result = sm.trigger("stop")
        assert result is False
        assert sm.state == DeviceState.STOP

    def test_history_recorded(self):
        """State transitions should be recorded in history."""
        sm = DeviceStateMachine(min_startup_time=0.0)
        sm.trigger("start")
        sm.trigger("startup_complete")
        history = sm.get_history(count=10)
        assert len(history) >= 2

    def test_callback_on_transition(self):
        """Callbacks should be invoked on state transitions."""
        called = []
        sm = DeviceStateMachine(initial_state=DeviceState.STOP)
        sm.on_transition(lambda entry: called.append(entry))
        sm.trigger("start")
        assert len(called) >= 1

    def test_full_lifecycle(self):
        """Test full device lifecycle: STOP → STARTING → RUN → STOPPING → STOP."""
        sm = DeviceStateMachine(min_startup_time=0.0)
        assert sm.state == DeviceState.STOP

        sm.trigger("start")
        assert sm.state == DeviceState.STARTING

        sm.trigger("startup_complete")
        assert sm.state == DeviceState.RUN

        sm.trigger("stop")
        assert sm.state == DeviceState.STOPPING

        sm.trigger("stop_complete")
        assert sm.state == DeviceState.STOP

    def test_fault_and_reset_lifecycle(self):
        """Test fault lifecycle: RUN → ERROR → STOP → STARTING → RUN."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN, min_startup_time=0.0)
        sm.trigger("fault")
        assert sm.state == DeviceState.ERROR
        sm.trigger("reset", fault_cleared=True)
        assert sm.state == DeviceState.STOP
        sm.trigger("start")
        assert sm.state == DeviceState.STARTING

    def test_get_state_duration(self):
        """get_state_duration should return a positive float."""
        sm = DeviceStateMachine()
        duration = sm.get_state_duration()
        assert isinstance(duration, float)
        assert duration >= 0.0

    def test_get_quality(self):
        """get_quality should return a quality string."""
        sm = DeviceStateMachine(initial_state=DeviceState.RUN)
        quality = sm.get_quality()
        assert isinstance(quality, str)

    def test_should_generate_data(self):
        """should_generate_data should return True for RUN state."""
        assert DeviceStateMachine.should_generate_data(DeviceState.RUN) is True
        assert DeviceStateMachine.should_generate_data(DeviceState.STOP) is False


class TestDeviceStateToStatus:
    """Tests for the device_state_to_status helper function."""

    def test_stop_to_status(self):
        status = device_state_to_status(DeviceState.STOP)
        assert status is not None

    def test_run_to_status(self):
        status = device_state_to_status(DeviceState.RUN)
        assert status is not None

    def test_error_to_status(self):
        status = device_state_to_status(DeviceState.ERROR)
        assert status is not None

    def test_all_states_have_status(self):
        """All device states should have a corresponding status."""
        for state in DeviceState:
            status = device_state_to_status(state)
            assert status is not None, f"No status for state {state}"
