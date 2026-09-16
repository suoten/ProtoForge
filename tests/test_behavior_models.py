"""Unit tests for protoforge.simulation.behavior_models physics simulation models."""

import math

import pytest

from protoforge.simulation.behavior_models import (
    BaseBehavior,
    ThermalBehavior,
    MotorBehavior,
    PressureBehavior,
    FlowBehavior,
    LevelBehavior,
    ValveBehavior,
    PIDController,
)


# ---------------------------------------------------------------------------
# BaseBehavior
# ---------------------------------------------------------------------------

class TestBaseBehavior:
    """Tests for the abstract BaseBehavior class."""

    def test_cannot_instantiate_directly(self):
        """BaseBehavior._init_state raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            BaseBehavior()

    def test_base_to_dict_returns_params(self):
        """to_dict should return type and params."""
        class Dummy(BaseBehavior):
            def _init_state(self):
                self._val = 0
            def update(self, x=0, dt=0.1):
                self._val += x
                return self._val
            def _state(self):
                return {"val": self._val}

        d = Dummy(foo=1, bar="baz")
        result = d.to_dict()
        assert result["type"] == "Dummy"
        assert result["params"]["foo"] == 1
        assert result["params"]["bar"] == "baz"

    def test_base_from_dict_roundtrip(self):
        """from_dict should reconstruct object from to_dict output."""
        class Dummy(BaseBehavior):
            def _init_state(self):
                self._val = 0
            def update(self, x=0, dt=0.1):
                self._val += x
                return self._val
            def _state(self):
                return {"val": self._val}
            def _restore_state(self, state):
                self._val = state.get("val", 0)

        d = Dummy(foo=42)
        d.update(x=10)
        serialized = d.to_dict()
        d2 = Dummy.from_dict(serialized)
        assert d2._val == 10

    def test_reset_calls_init_state(self):
        """reset should reinitialize state."""
        class Dummy(BaseBehavior):
            def _init_state(self):
                self._val = 100
            def update(self, x=0, dt=0.1):
                self._val += x
                return self._val

        d = Dummy()
        d.update(x=5)
        assert d._val == 105
        d.reset()
        assert d._val == 100

    def test_get_state_adds_type(self):
        """get_state should include _type field."""
        class Dummy(BaseBehavior):
            def _init_state(self):
                pass
            def update(self, *args, **kwargs):
                return 0

        d = Dummy()
        state = d.get_state()
        assert state["_type"] == "Dummy"


# ---------------------------------------------------------------------------
# ThermalBehavior
# ---------------------------------------------------------------------------

class TestThermalBehavior:
    """Tests for the thermal (temperature) physics model."""

    def test_initial_temperature_defaults_to_ambient(self):
        t = ThermalBehavior(mass=1.0, specific_heat=1000, ambient_temp=25.0)
        assert t._temperature == 25.0

    def test_initial_temperature_custom(self):
        t = ThermalBehavior(mass=1.0, specific_heat=1000, ambient_temp=25.0, initial_temp=50.0)
        assert t._temperature == 50.0

    def test_temperature_rises_with_power(self):
        """Temperature should increase when power is applied."""
        t = ThermalBehavior(mass=1.0, specific_heat=1000, heat_transfer_coeff=0, ambient_temp=25.0)
        initial = t._temperature
        t.update(power_input=1000, dt=1.0)
        assert t._temperature > initial

    def test_temperature_cools_without_power(self):
        """Temperature should move toward ambient when no power is applied."""
        t = ThermalBehavior(
            mass=1.0, specific_heat=1000, heat_transfer_coeff=10.0,
            ambient_temp=25.0, initial_temp=80.0,
        )
        t.update(power_input=0, dt=1.0)
        assert t._temperature < 80.0

    def test_overheat_protection(self):
        """Overheat protection should cut power when threshold is reached."""
        t = ThermalBehavior(
            mass=0.1, specific_heat=100, heat_transfer_coeff=0,
            ambient_temp=25.0, initial_temp=95.0, overheat_threshold=100.0,
        )
        # Apply power to push temperature over threshold
        t.update(power_input=10000, dt=1.0)
        # Temperature is now above threshold; second call should trigger overheat
        t.update(power_input=10000, dt=1.0)
        assert t.overheated()

    def test_overheat_hysteresis(self):
        """Overheat should clear when temperature drops 5°C below threshold."""
        t = ThermalBehavior(
            mass=0.1, specific_heat=100, heat_transfer_coeff=50.0,
            ambient_temp=20.0, initial_temp=100.0, overheat_threshold=100.0,
        )
        # Force overheat
        t._overheated = True
        # Cool down well below threshold
        for _ in range(100):
            t.update(power_input=0, dt=1.0)
        assert not t.overheated()

    def test_thermal_state_dict(self):
        t = ThermalBehavior(mass=2.0, specific_heat=500, ambient_temp=30.0)
        t.update(power_input=100, dt=0.5)
        state = t.get_state()
        assert "temperature" in state
        assert "overheated" in state
        assert "total_energy" in state
        assert "time" in state
        assert state["_type"] == "ThermalBehavior"

    def test_thermal_serialization_roundtrip(self):
        t = ThermalBehavior(mass=1.5, specific_heat=800, ambient_temp=22.0, initial_temp=60.0)
        for _ in range(10):
            t.update(power_input=500, dt=0.1)
        serialized = t.to_dict()
        t2 = ThermalBehavior.from_dict(serialized)
        assert t2._temperature == pytest.approx(t._temperature)
        assert t2._total_energy == pytest.approx(t._total_energy)

    def test_thermal_reset(self):
        t = ThermalBehavior(mass=1.0, specific_heat=1000, ambient_temp=25.0, initial_temp=25.0)
        t.update(power_input=1000, dt=1.0)
        assert t._temperature != 25.0
        t.reset()
        assert t._temperature == 25.0
        assert t._total_energy == 0.0


# ---------------------------------------------------------------------------
# MotorBehavior
# ---------------------------------------------------------------------------

class TestMotorBehavior:
    """Tests for the motor (rotational) physics model."""

    def test_motor_starts_from_zero(self):
        m = MotorBehavior()
        assert m._speed_rpm == 0.0

    def test_motor_accelerates_with_torque(self):
        m = MotorBehavior(inertia=0.01, friction=0.1, rated_speed=3000)
        initial = m._speed_rpm
        m.update(torque=5.0, dt=0.01)
        assert m._speed_rpm > initial

    def test_motor_steady_state(self):
        """Motor should approach steady-state speed T/b."""
        m = MotorBehavior(inertia=0.01, friction=0.1, rated_speed=10000)
        for _ in range(1000):
            m.update(torque=1.0, dt=0.01)
        # Steady state: omega = T/b = 1/0.1 = 10 rad/s -> rpm = 10*60/(2*pi) ≈ 95.5
        expected_rpm = 10.0 * 60.0 / (2.0 * math.pi)
        assert m._speed_rpm == pytest.approx(expected_rpm, rel=0.05)

    def test_motor_torque_limit(self):
        """Torque should be clamped to rated_torque."""
        m = MotorBehavior(rated_torque=5.0, inertia=0.01, friction=0.1)
        # Apply torque well above rated
        m.update(torque=100.0, dt=0.01)
        # The effective torque should have been limited
        # omega = T/J * dt = 5/0.01 * 0.01 = 5 rad/s
        assert m._omega == pytest.approx(5.0, rel=0.1)

    def test_motor_stall_detection(self):
        """Stall should be detected when torque is applied but speed stays low."""
        m = MotorBehavior(
            inertia=1.0, friction=10.0, rated_torque=2.0,
            stall_threshold=10.0, stall_time=0.5,
        )
        # Apply torque but high friction keeps speed low (steady state ~1.9 rpm)
        for _ in range(200):
            m.update(torque=2.0, dt=0.01)
        assert m._stalled

    def test_motor_state_dict(self):
        m = MotorBehavior()
        m.update(torque=1.0, dt=0.01)
        state = m.get_state()
        assert "omega" in state
        assert "speed_rpm" in state
        assert "stalled" in state
        assert state["_type"] == "MotorBehavior"

    def test_motor_serialization_roundtrip(self):
        m = MotorBehavior(inertia=0.05, friction=0.2, rated_speed=2000)
        for _ in range(50):
            m.update(torque=3.0, dt=0.01)
        serialized = m.to_dict()
        m2 = MotorBehavior.from_dict(serialized)
        assert m2._omega == pytest.approx(m._omega)

    def test_motor_reset(self):
        m = MotorBehavior()
        m.update(torque=5.0, dt=0.1)
        assert m._omega != 0
        m.reset()
        assert m._omega == 0.0
        assert m._speed_rpm == 0.0


# ---------------------------------------------------------------------------
# PressureBehavior
# ---------------------------------------------------------------------------

class TestPressureBehavior:
    """Tests for the pressure sensor physics model."""

    def test_pressure_initial(self):
        p = PressureBehavior(initial_pressure=5000.0)
        assert p._pressure == 5000.0

    def test_pressure_responds_to_target(self):
        """Pressure should move toward target pressure."""
        p = PressureBehavior(initial_pressure=1000.0, response_time=0.1)
        initial = p._pressure
        p.update(target_pressure=5000.0, dt=0.01)
        # Pressure should have moved toward target
        assert p._pressure != initial

    def test_pressure_converges_to_target(self):
        """Pressure should converge to target over time."""
        p = PressureBehavior(initial_pressure=1000.0, response_time=0.5, damping=0.7)
        for _ in range(500):
            p.update(target_pressure=5000.0, dt=0.01)
        assert p._pressure == pytest.approx(5000.0, rel=0.05)

    def test_pressure_state_dict(self):
        p = PressureBehavior()
        state = p.get_state()
        assert "pressure" in state
        assert state["_type"] == "PressureBehavior"

    def test_pressure_reset(self):
        p = PressureBehavior(initial_pressure=3000.0)
        p.update(target_pressure=5000.0, dt=0.1)
        assert p._pressure != 3000.0
        p.reset()
        assert p._pressure == 3000.0

    def test_pressure_serialization_roundtrip(self):
        p = PressureBehavior(initial_pressure=2000.0, response_time=0.3)
        p.update(target_pressure=5000.0, dt=0.1)
        serialized = p.to_dict()
        p2 = PressureBehavior.from_dict(serialized)
        assert p2._pressure == pytest.approx(p._pressure)


# ---------------------------------------------------------------------------
# FlowBehavior
# ---------------------------------------------------------------------------

class TestFlowBehavior:
    """Tests for the flow meter physics model."""

    def test_flow_initial(self):
        f = FlowBehavior(cumulative=10.0)
        assert f._cumulative == 10.0

    def test_flow_responds_to_target(self):
        """Flow rate should move toward target flow."""
        f = FlowBehavior(accuracy=0.0, pulse_amplitude=0.0)
        f.update(target_flow=50.0, dt=0.1)
        # Flow should be close to target (with no accuracy error)
        assert f._instant_flow > 0

    def test_flow_state_dict(self):
        f = FlowBehavior()
        state = f.get_state()
        assert "instant_flow" in state
        assert state["_type"] == "FlowBehavior"

    def test_flow_reset(self):
        f = FlowBehavior(cumulative=5.0)
        f.update(target_flow=10.0, dt=0.1)
        f.reset()
        assert f._instant_flow == 0.0
        assert f._cumulative == 5.0  # cumulative_init

    def test_flow_cumulative_increases(self):
        """Cumulative flow should increase over time."""
        f = FlowBehavior(accuracy=0.0, pulse_amplitude=0.0)
        initial_cum = f._cumulative
        f.update(target_flow=60.0, dt=0.1)  # 60 L/min = 1 L/s, 0.1s -> 0.1 L
        assert f._cumulative > initial_cum


# ---------------------------------------------------------------------------
# LevelBehavior
# ---------------------------------------------------------------------------

class TestLevelBehavior:
    """Tests for the tank level physics model."""

    def test_level_initial(self):
        lv = LevelBehavior(initial_level=3.0)
        assert lv._level == 3.0

    def test_level_rises_with_inflow(self):
        """Level should increase when inflow > outflow."""
        lv = LevelBehavior(initial_level=1.0, tank_area=1.0, max_level=10.0)
        initial = lv._level
        lv.update(inlet_flow=0.1, outlet_flow=0.0, dt=0.1)
        assert lv._level > initial

    def test_level_falls_with_outflow(self):
        """Level should decrease when outflow > inflow."""
        lv = LevelBehavior(initial_level=5.0, tank_area=1.0, max_level=10.0)
        initial = lv._level
        lv.update(inlet_flow=0.0, outlet_flow=0.1, dt=0.1)
        assert lv._level < initial

    def test_level_overflow_protection(self):
        """Level should be clamped to max_level."""
        lv = LevelBehavior(initial_level=4.9, tank_area=0.1, max_level=5.0)
        lv.update(inlet_flow=1.0, outlet_flow=0.0, dt=1.0)
        assert lv._level <= 5.0
        assert lv.is_overflow()

    def test_level_low_alarm(self):
        """Low alarm should trigger when level drops below threshold."""
        lv = LevelBehavior(
            initial_level=0.6, tank_area=1.0, max_level=5.0,
            low_level_threshold=0.5,
        )
        lv.update(inlet_flow=0.0, outlet_flow=0.1, dt=1.0)
        assert lv.is_low_alarm()

    def test_level_state_dict(self):
        lv = LevelBehavior()
        state = lv.get_state()
        assert "level" in state
        assert state["_type"] == "LevelBehavior"

    def test_level_reset(self):
        lv = LevelBehavior(initial_level=2.0)
        lv.update(inlet_flow=0.1, outlet_flow=0.0, dt=0.1)
        assert lv._level != 2.0
        lv.reset()
        assert lv._level == 2.0

    def test_level_serialization_roundtrip(self):
        lv = LevelBehavior(initial_level=1.5, tank_area=0.5, max_level=10.0)
        lv.update(inlet_flow=0.2, outlet_flow=0.05, dt=0.1)
        serialized = lv.to_dict()
        lv2 = LevelBehavior.from_dict(serialized)
        assert lv2._level == pytest.approx(lv._level)


# ---------------------------------------------------------------------------
# ValveBehavior
# ---------------------------------------------------------------------------

class TestValveBehavior:
    """Tests for the valve actuator model."""

    def test_valve_initial(self):
        v = ValveBehavior(initial_opening=50.0)
        assert v._opening == 50.0

    def test_valve_opens(self):
        """Valve opening should increase when control signal increases."""
        v = ValveBehavior(initial_opening=0.0, opening_time=1.0, dead_zone=0.0, hysteresis=0.0)
        v.update(control_signal=100.0, dt=0.5)
        assert v._opening > 0.0

    def test_valve_closes(self):
        """Valve opening should decrease when control signal decreases."""
        v = ValveBehavior(initial_opening=100.0, opening_time=1.0, dead_zone=0.0, hysteresis=0.0)
        v.update(control_signal=0.0, dt=0.5)
        assert v._opening < 100.0

    def test_valve_position_clamped(self):
        """Valve opening should be clamped to [0, 100]."""
        v = ValveBehavior(initial_opening=0.0, opening_time=0.01, dead_zone=0.0, hysteresis=0.0)
        v.update(control_signal=100.0, dt=1.0)
        assert v._opening <= 100.0
        v2 = ValveBehavior(initial_opening=100.0, opening_time=0.01, dead_zone=0.0, hysteresis=0.0)
        v2.update(control_signal=0.0, dt=1.0)
        assert v2._opening >= 0.0

    def test_valve_dead_zone(self):
        """Valve should not move when control signal is within dead zone."""
        v = ValveBehavior(initial_opening=50.0, dead_zone=10.0, hysteresis=0.0, opening_time=0.1)
        v.update(control_signal=55.0, dt=0.1)
        # 55 - 50 = 5 < 10 (dead zone), so no movement
        assert v._opening == 50.0

    def test_valve_state_dict(self):
        v = ValveBehavior()
        state = v.get_state()
        assert "opening" in state
        assert state["_type"] == "ValveBehavior"

    def test_valve_reset(self):
        v = ValveBehavior(initial_opening=30.0)
        v.update(control_signal=100.0, dt=1.0)
        assert v._opening != 30.0
        v.reset()
        assert v._opening == 30.0

    def test_valve_serialization_roundtrip(self):
        v = ValveBehavior(initial_opening=20.0, opening_time=2.0)
        v.update(control_signal=80.0, dt=0.5)
        serialized = v.to_dict()
        v2 = ValveBehavior.from_dict(serialized)
        assert v2._opening == pytest.approx(v._opening)


# ---------------------------------------------------------------------------
# PIDController
# ---------------------------------------------------------------------------

class TestPIDController:
    """Tests for the PID controller model."""

    def test_pid_initial_output_zero(self):
        pid = PIDController(Kp=1.0, Ki=0.1, Kd=0.01, initial_output=0.0)
        assert pid._output == 0.0

    def test_pid_proportional_response(self):
        """PID should produce output proportional to error."""
        pid = PIDController(Kp=2.0, Ki=0.0, Kd=0.0, setpoint=100.0, output_limit=None)
        output = pid.update(measurement=90.0, dt=0.1)
        # Error = 10, output = Kp * error = 20
        assert output == pytest.approx(20.0, rel=0.01)

    def test_pid_integral_accumulates(self):
        """Integral term should accumulate over time."""
        pid = PIDController(Kp=0.0, Ki=1.0, Kd=0.0, setpoint=100.0, output_limit=None)
        pid.update(measurement=90.0, dt=0.1)
        pid.update(measurement=90.0, dt=0.1)
        # Integral = error * dt * 2 = 10 * 0.1 * 2 = 2.0
        assert pid._integral == pytest.approx(2.0, rel=0.01)

    def test_pid_derivative_response(self):
        """Derivative term should respond to rate of change."""
        pid = PIDController(Kp=0.0, Ki=0.0, Kd=1.0, setpoint=100.0, output_limit=None)
        pid.update(measurement=90.0, dt=0.1)
        # First step: derivative = -(90 - None) -> 0 for first step
        # Second step with different measurement
        output = pid.update(measurement=85.0, dt=0.1)
        # d_term = -Kd * (85 - 90) / 0.1 = -1 * (-5) / 0.1 = 50
        assert output > 0

    def test_pid_output_clamping(self):
        """PID output should be clamped to output_limit."""
        pid = PIDController(Kp=1000.0, Ki=0.0, Kd=0.0, setpoint=1000.0, output_limit=(0.0, 100.0))
        output = pid.update(measurement=0.0, dt=0.1)
        assert output <= 100.0

    def test_pid_reset(self):
        pid = PIDController(Kp=1.0, Ki=0.1, Kd=0.01, setpoint=100.0)
        pid.update(measurement=50.0, dt=0.1)
        assert pid._integral != 0.0
        pid.reset()
        assert pid._integral == 0.0
        assert pid._prev_measurement is None

    def test_pid_state_dict(self):
        pid = PIDController(Kp=1.0, Ki=0.1, Kd=0.01, setpoint=100.0)
        pid.update(measurement=90.0, dt=0.1)
        state = pid.get_state()
        assert "output" in state
        assert "integral" in state
        assert state["_type"] == "PIDController"

    def test_pid_serialization_roundtrip(self):
        pid = PIDController(Kp=2.0, Ki=0.5, Kd=0.1, setpoint=100.0)
        for _ in range(10):
            pid.update(measurement=90.0, dt=0.1)
        serialized = pid.to_dict()
        pid2 = PIDController.from_dict(serialized)
        assert pid2._integral == pytest.approx(pid._integral)
        assert pid2._output == pytest.approx(pid._output)

    def test_pid_anti_windup(self):
        """Integral should not grow unbounded when output is saturated."""
        pid = PIDController(
            Kp=0.0, Ki=100.0, Kd=0.0,
            setpoint=1000.0, output_limit=(0.0, 50.0),
        )
        for _ in range(100):
            pid.update(measurement=0.0, dt=0.1)
        # With anti-windup, output should be clamped
        assert pid._output <= 50.0
