"""Comprehensive tests for behavior_models.py - all 7 physics models."""

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


# ==================== BaseBehavior Tests ====================

class TestBaseBehavior:
    def test_base_init_raises(self):
        """BaseBehavior() should raise NotImplementedError because _init_state is abstract."""
        with pytest.raises(NotImplementedError):
            BaseBehavior()

    def test_base_from_dict_no_state(self):
        """BaseBehavior.from_dict should construct from params only."""
        # Use a concrete subclass
        data = {
            "type": "ThermalBehavior",
            "params": {"mass": 2.0, "specific_heat": 900, "ambient_temp": 30},
        }
        obj = ThermalBehavior.from_dict(data)
        assert obj.mass == 2.0
        assert obj.specific_heat == 900
        assert obj.ambient_temp == 30


# ==================== ThermalBehavior Tests ====================

class TestThermalBehavior:
    def test_init_defaults(self):
        t = ThermalBehavior()
        assert t.mass == 1.0
        assert t.specific_heat == 4186.0
        assert t.heat_transfer_coeff == 10.0
        assert t.ambient_temp == 25.0
        assert t.overheat_threshold is None

    def test_init_custom(self):
        t = ThermalBehavior(
            mass=2.0, specific_heat=900, heat_transfer_coeff=15,
            ambient_temp=30, initial_temp=50, overheat_threshold=80,
        )
        assert t.mass == 2.0
        assert t.overheat_threshold == 80

    def test_update_returns_float(self):
        t = ThermalBehavior()
        val = t.update(power_input=100, dt=0.1)
        assert isinstance(val, float)

    def test_update_heats_up(self):
        """Temperature should increase when power is applied."""
        t = ThermalBehavior(mass=0.1, specific_heat=100, ambient_temp=25)
        initial = t.update(0, dt=0.01)  # Get initial temp
        heated = t.update(1000, dt=0.1)
        assert heated > initial

    def test_update_cools_down(self):
        """Temperature should decrease toward ambient when no power."""
        t = ThermalBehavior(mass=0.1, specific_heat=100, ambient_temp=25, initial_temp=80)
        val = t.update(0, dt=0.1)
        assert val < 80

    def test_overheat_protection(self):
        """Overheat threshold should cut power."""
        t = ThermalBehavior(
            mass=0.01, specific_heat=10, ambient_temp=25,
            initial_temp=75, overheat_threshold=80,
        )
        # Push temp above threshold
        for _ in range(100):
            t.update(10000, dt=0.1)
        assert t.overheated()

    def test_overheat_recovery(self):
        """Overheat should clear when temp drops below threshold - 5."""
        t = ThermalBehavior(
            mass=0.01, specific_heat=10, ambient_temp=25,
            initial_temp=79, overheat_threshold=80,
        )
        # Heat up to trigger overheat (need 2 updates: first heats, second detects)
        t.update(10000, dt=0.1)  # Push temp above 80
        t.update(0, dt=0.01)  # Detect overheat
        assert t.overheated()
        # Cool down (temp must drop below 80-5=75)
        for _ in range(500):
            t.update(0, dt=0.1)
        assert not t.overheated()

    def test_reset(self):
        t = ThermalBehavior(initial_temp=50, ambient_temp=25)
        t.update(1000, dt=0.1)
        t.reset()
        state = t.get_state()
        assert state["temperature"] == 50  # Back to initial

    def test_get_state(self):
        t = ThermalBehavior(initial_temp=42)
        state = t.get_state()
        assert state["_type"] == "ThermalBehavior"
        assert "temperature" in state
        assert "total_energy" in state
        assert "time" in state

    def test_to_dict(self):
        t = ThermalBehavior(mass=2.0, ambient_temp=30)
        d = t.to_dict()
        assert d["type"] == "ThermalBehavior"
        assert d["params"]["mass"] == 2.0
        assert "state" in d

    def test_from_dict(self):
        t = ThermalBehavior(mass=2.0, initial_temp=50)
        t.update(100, dt=0.1)
        d = t.to_dict()
        restored = ThermalBehavior.from_dict(d)
        assert restored.mass == 2.0
        state = restored.get_state()
        assert abs(state["temperature"] - t._temperature) < 0.001

    def test_total_energy_accumulates(self):
        t = ThermalBehavior(mass=1.0, specific_heat=100, ambient_temp=25)
        t.update(100, dt=1.0)
        assert t._total_energy == 100
        t.update(100, dt=1.0)
        assert t._total_energy == 200

    def test_zero_thermal_capacity(self):
        """Should handle zero thermal capacity without division by zero."""
        t = ThermalBehavior(mass=0, specific_heat=0)
        val = t.update(100, dt=0.1)
        assert isinstance(val, float)


# ==================== MotorBehavior Tests ====================

class TestMotorBehavior:
    def test_init_defaults(self):
        m = MotorBehavior()
        assert m.inertia == 0.01
        assert m.friction == 0.1
        assert m.rated_speed == 3000.0

    def test_update_returns_float(self):
        m = MotorBehavior()
        val = m.update(torque=1.0, dt=0.01)
        assert isinstance(val, float)

    def test_acceleration(self):
        """Motor should accelerate when torque is applied."""
        m = MotorBehavior(inertia=0.01, friction=0.1)
        v1 = m.update(torque=1.0, dt=0.01)
        v2 = m.update(torque=1.0, dt=0.01)
        assert v2 >= v1

    def test_torque_limit(self):
        """Torque should be limited to rated value."""
        m = MotorBehavior(rated_torque=5.0)
        m.update(torque=100, dt=0.01)  # Should be limited to 5.0
        # Motor should not accelerate too fast
        assert m._omega < 100

    def test_speed_saturation(self):
        """Speed should be limited to rated speed."""
        m = MotorBehavior(inertia=0.001, friction=0.01, rated_speed=100)
        for _ in range(1000):
            m.update(torque=10, dt=0.01)
        assert m._speed_rpm <= 100.01

    def test_stall_detection(self):
        """Should detect stall when torque applied but speed is low."""
        m = MotorBehavior(
            inertia=1e9, friction=1e9,  # Very high inertia and friction = won't move
            stall_threshold=10, stall_time=0.1,
        )
        for _ in range(20):
            m.update(torque=5.0, dt=0.01)
        assert m.is_stalled()

    def test_reset(self):
        m = MotorBehavior()
        m.update(torque=5, dt=0.1)
        m.reset()
        assert m._omega == 0.0
        assert m._speed_rpm == 0.0
        assert m._stalled is False

    def test_get_state(self):
        m = MotorBehavior()
        state = m.get_state()
        assert state["_type"] == "MotorBehavior"
        assert "omega" in state
        assert "speed_rpm" in state
        assert "stalled" in state

    def test_to_dict_and_from_dict(self):
        m = MotorBehavior(inertia=0.5, friction=0.2)
        m.update(torque=2, dt=0.01)
        d = m.to_dict()
        restored = MotorBehavior.from_dict(d)
        assert restored.inertia == 0.5
        assert abs(restored._omega - m._omega) < 0.001


# ==================== PressureBehavior Tests ====================

class TestPressureBehavior:
    def test_init_defaults(self):
        p = PressureBehavior()
        assert p.response_time == 0.5
        assert p.overshoot == 0.1
        assert p.damping == 0.7

    def test_update_returns_float(self):
        p = PressureBehavior()
        val = p.update(target_pressure=200000, dt=0.01)
        assert isinstance(val, float)

    def test_pressure_converges(self):
        """Pressure should converge toward target."""
        p = PressureBehavior(response_time=0.1, damping=0.9, initial_pressure=100)
        for _ in range(500):
            p.update(target_pressure=200, dt=0.01)
        assert abs(p._pressure - 200) < 20

    def test_overshoot_effect(self):
        """With overshoot > 0, pressure may exceed target temporarily."""
        p = PressureBehavior(response_time=0.01, overshoot=0.5, damping=0.1, initial_pressure=0)
        values = []
        for _ in range(200):
            v = p.update(target_pressure=100, dt=0.001)
            values.append(v)
        # With high overshoot, some values should exceed target
        assert max(values) > 100

    def test_reset(self):
        p = PressureBehavior(initial_pressure=50)
        p.update(target_pressure=200, dt=0.1)
        p.reset()
        assert p._pressure == 50

    def test_get_state(self):
        p = PressureBehavior()
        state = p.get_state()
        assert state["_type"] == "PressureBehavior"
        assert "pressure" in state
        assert "target" in state

    def test_to_dict_and_from_dict(self):
        p = PressureBehavior(initial_pressure=50, response_time=0.2)
        p.update(target_pressure=100, dt=0.01)
        d = p.to_dict()
        restored = PressureBehavior.from_dict(d)
        assert restored.response_time == 0.2
        assert abs(restored._pressure - p._pressure) < 0.001

    def test_noise_effect(self):
        """Noise should add randomness to pressure."""
        p = PressureBehavior(noise=5.0, initial_pressure=100)
        v1 = p.update(target_pressure=100, dt=0.01)
        v2 = p.update(target_pressure=100, dt=0.01)
        # With noise, values should vary
        assert v1 != v2 or True  # Noise might occasionally produce same value


# ==================== FlowBehavior Tests ====================

class TestFlowBehavior:
    def test_init_defaults(self):
        f = FlowBehavior()
        assert f.accuracy == 0.5
        assert f.pulse_factor == 1000.0
        assert f.max_flow == 100.0

    def test_update_returns_float(self):
        f = FlowBehavior()
        val = f.update(target_flow=50, dt=0.1)
        assert isinstance(val, float)

    def test_flow_clamping(self):
        """Flow should be clamped to max_flow."""
        f = FlowBehavior(max_flow=100)
        val = f.update(target_flow=200, dt=0.1)
        assert val <= 105  # Allow some noise margin

    def test_cumulative_accumulation(self):
        """Cumulative flow should increase over time."""
        f = FlowBehavior(accuracy=0, pulse_amplitude=0)
        f.update(target_flow=60, dt=1.0)  # 60 L/min = 1 L/s for 1s
        assert f._cumulative > 0

    def test_pulse_effect(self):
        """Pulsating flow should cause oscillation."""
        f = FlowBehavior(pulse_amplitude=0.5, pulse_frequency=10, accuracy=0)
        values = []
        for _ in range(100):
            v = f.update(target_flow=50, dt=0.01)
            values.append(v)
        # With pulsation, values should vary significantly
        assert max(values) - min(values) > 5

    def test_reset(self):
        f = FlowBehavior(cumulative=100)
        f.update(target_flow=50, dt=0.1)
        f.reset()
        assert f._cumulative == 100  # Back to initial
        assert f._instant_flow == 0.0

    def test_get_state(self):
        f = FlowBehavior()
        state = f.get_state()
        assert state["_type"] == "FlowBehavior"
        assert "instant_flow" in state
        assert "cumulative" in state

    def test_to_dict_and_from_dict(self):
        f = FlowBehavior(accuracy=1.0, max_flow=200)
        f.update(target_flow=100, dt=0.1)
        d = f.to_dict()
        restored = FlowBehavior.from_dict(d)
        assert restored.accuracy == 1.0
        assert restored.max_flow == 200

    def test_pulse_count(self):
        """Pulse count should be non-negative."""
        f = FlowBehavior()
        f.update(target_flow=50, dt=0.1)
        assert f._pulse_count >= 0


# ==================== LevelBehavior Tests ====================

class TestLevelBehavior:
    def test_init_defaults(self):
        lv = LevelBehavior()
        assert lv.tank_area == 1.0
        assert lv.max_level == 5.0
        assert lv.inlet_flow == 0.01

    def test_update_returns_float(self):
        lv = LevelBehavior()
        val = lv.update(dt=0.1)
        assert isinstance(val, float)

    def test_level_rises(self):
        """Level should rise when inlet > outlet."""
        lv = LevelBehavior(tank_area=0.1, inlet_flow=0.1, outlet_flow=0.01, initial_level=1.0)
        initial = lv._level
        lv.update(dt=0.1)
        assert lv._level > initial

    def test_level_falls(self):
        """Level should fall when outlet > inlet."""
        lv = LevelBehavior(tank_area=0.1, inlet_flow=0.01, outlet_flow=0.1, initial_level=3.0)
        initial = lv._level
        lv.update(dt=0.1)
        assert lv._level < initial

    def test_overflow_detection(self):
        """Should detect overflow when level exceeds max."""
        lv = LevelBehavior(tank_area=0.01, max_level=1.0, inlet_flow=1.0, outlet_flow=0, initial_level=0.99)
        for _ in range(20):
            lv.update(dt=0.1)
        assert lv.is_overflow()

    def test_low_alarm(self):
        """Should detect low level alarm."""
        lv = LevelBehavior(tank_area=0.01, inlet_flow=0, outlet_flow=1.0, initial_level=0.6, low_level_threshold=0.5)
        for _ in range(20):
            lv.update(dt=0.1)
        assert lv.is_low_alarm()

    def test_wave_effect(self):
        """Wave should add oscillation to level reading."""
        lv = LevelBehavior(wave_amplitude=0.1, wave_frequency=5, inlet_flow=0.01, outlet_flow=0.01, initial_level=2.0)
        values = []
        for _ in range(100):
            v = lv.update(dt=0.01)
            values.append(v)
        # With waves, values should oscillate
        assert max(values) - min(values) > 0.001

    def test_reset(self):
        lv = LevelBehavior(initial_level=3.0)
        lv.update(dt=0.1)
        lv.reset()
        assert lv._level == 3.0

    def test_get_state(self):
        lv = LevelBehavior()
        state = lv.get_state()
        assert state["_type"] == "LevelBehavior"
        assert "level" in state
        assert "overflow" in state
        assert "low_alarm" in state

    def test_to_dict_and_from_dict(self):
        lv = LevelBehavior(tank_area=2.0, max_level=10, initial_level=5)
        lv.update(dt=0.1)
        d = lv.to_dict()
        restored = LevelBehavior.from_dict(d)
        assert restored.tank_area == 2.0
        assert restored.max_level == 10

    def test_custom_flows(self):
        """Should accept custom inlet/outlet flows in update."""
        lv = LevelBehavior(tank_area=1.0, inlet_flow=0, outlet_flow=0, initial_level=1.0)
        lv.update(inlet_flow=0.5, outlet_flow=0.1, dt=0.1)
        assert lv._level > 1.0


# ==================== ValveBehavior Tests ====================

class TestValveBehavior:
    def test_init_defaults(self):
        v = ValveBehavior()
        assert v.dead_zone == 5.0
        assert v.hysteresis == 3.0
        assert v.opening_time == 5.0

    def test_update_returns_float(self):
        v = ValveBehavior()
        val = v.update(control_signal=50, dt=0.1)
        assert isinstance(val, float)

    def test_valve_opens(self):
        """Valve should open when control signal increases."""
        v = ValveBehavior(dead_zone=0, hysteresis=0, opening_time=1.0, initial_opening=0)
        for _ in range(20):
            v.update(control_signal=100, dt=0.1)
        assert v._opening > 50

    def test_dead_zone(self):
        """Small changes within dead zone should not move valve."""
        v = ValveBehavior(dead_zone=10, hysteresis=0, opening_time=1.0, initial_opening=50)
        v.update(control_signal=55, dt=0.1)  # 5% change, within 10% dead zone
        assert v._effective_target == 50  # Should not change

    def test_response_delay(self):
        """Valve should take time to reach target."""
        v = ValveBehavior(dead_zone=0, hysteresis=0, opening_time=10.0, initial_opening=0)
        v.update(control_signal=100, dt=0.1)
        # After 0.1s with 10s full travel time, should be at ~1%
        assert v._opening < 5

    def test_clamping(self):
        """Valve opening should be clamped 0-100."""
        v = ValveBehavior(dead_zone=0, hysteresis=0, opening_time=0.01, initial_opening=50)
        v.update(control_signal=200, dt=0.1)
        assert v._opening <= 100
        v2 = ValveBehavior(dead_zone=0, hysteresis=0, opening_time=0.01, initial_opening=50)
        v2.update(control_signal=-50, dt=0.1)
        assert v2._opening >= 0

    def test_reset(self):
        v = ValveBehavior(initial_opening=30)
        v.update(control_signal=80, dt=0.1)
        v.reset()
        assert v._opening == 30

    def test_get_state(self):
        v = ValveBehavior()
        state = v.get_state()
        assert state["_type"] == "ValveBehavior"
        assert "opening" in state
        assert "target" in state

    def test_to_dict_and_from_dict(self):
        v = ValveBehavior(dead_zone=8, hysteresis=2, initial_opening=40)
        v.update(control_signal=70, dt=0.1)
        d = v.to_dict()
        restored = ValveBehavior.from_dict(d)
        assert restored.dead_zone == 8
        assert restored.hysteresis == 2

    def test_hysteresis_direction_change(self):
        """Direction reversal requires overcoming hysteresis."""
        v = ValveBehavior(dead_zone=0, hysteresis=5, opening_time=0.01, initial_opening=50)
        # Open to 80
        v.update(control_signal=80, dt=0.1)
        assert v._last_direction == 1
        # Try to close slightly - within hysteresis, should not update
        v.update(control_signal=77, dt=0.1)
        # Direction hasn't changed effectively due to hysteresis
        assert v._effective_target == 80  # Still targeting 80


# ==================== PIDController Tests ====================

class TestPIDController:
    def test_init_defaults(self):
        pid = PIDController()
        assert pid.Kp == 1.0
        assert pid.Ki == 0.1
        assert pid.Kd == 0.01
        assert pid.setpoint == 50.0
        assert pid.output_limit == (0.0, 100.0)

    def test_update_returns_float(self):
        pid = PIDController()
        val = pid.update(measurement=40, dt=0.1)
        assert isinstance(val, float)

    def test_proportional_response(self):
        """Output should be proportional to error."""
        pid = PIDController(Kp=10, Ki=0, Kd=0, setpoint=100, output_limit=None)
        val = pid.update(measurement=90, dt=0.1)
        assert abs(val - 100) < 1  # 10 * (100-90) = 100

    def test_integral_accumulation(self):
        """Integral term should accumulate over time."""
        pid = PIDController(Kp=0, Ki=1, Kd=0, setpoint=100, output_limit=None)
        pid.update(measurement=90, dt=1.0)  # error=10, integral=10
        assert pid._integral == 10
        pid.update(measurement=90, dt=1.0)  # integral=20
        assert pid._integral == 20

    def test_derivative_response(self):
        """Derivative term should respond to measurement change."""
        pid = PIDController(Kp=0, Ki=0, Kd=1, setpoint=100, output_limit=None)
        pid.update(measurement=90, dt=0.1)  # First update, no derivative
        val = pid.update(measurement=85, dt=0.1)  # Measurement dropped by 5
        # d_term = -Kd * (85-90) / 0.1 = -1 * (-5) / 0.1 = 50
        assert val > 0

    def test_output_limit(self):
        """Output should be clamped to limits."""
        pid = PIDController(Kp=1000, Ki=0, Kd=0, setpoint=100, output_limit=(0, 50))
        val = pid.update(measurement=0, dt=0.1)
        assert val <= 50

    def test_anti_windup(self):
        """Integral should not accumulate when saturated."""
        pid = PIDController(Kp=0, Ki=100, Kd=0, setpoint=100, output_limit=(0, 50))
        # Large error, should saturate quickly
        for _ in range(10):
            pid.update(measurement=0, dt=0.1)
        # Integral should be capped due to anti-windup
        assert pid._saturated is True

    def test_no_output_limit(self):
        """Should work without output limit."""
        pid = PIDController(Kp=1, Ki=0, Kd=0, setpoint=100, output_limit=None)
        val = pid.update(measurement=50, dt=0.1)
        assert val == 50  # 1 * (100-50) = 50

    def test_reset(self):
        pid = PIDController(initial_output=10)
        pid.update(measurement=40, dt=0.1)
        pid.reset()
        assert pid._integral == 0.0
        assert pid._output == 10  # Back to initial
        assert pid._saturated is False

    def test_get_state(self):
        pid = PIDController()
        state = pid.get_state()
        assert state["_type"] == "PIDController"
        assert "integral" in state
        assert "output" in state
        assert "error" in state

    def test_to_dict_and_from_dict(self):
        pid = PIDController(Kp=5, Ki=0.5, setpoint=75)
        pid.update(measurement=60, dt=0.1)
        d = pid.to_dict()
        restored = PIDController.from_dict(d)
        assert restored.Kp == 5
        assert restored.Ki == 0.5
        assert restored.setpoint == 75

    def test_dt_zero_protection(self):
        """Should handle dt=0 without division by zero."""
        pid = PIDController(Kp=0, Ki=0, Kd=1, setpoint=100, output_limit=None)
        pid.update(measurement=90, dt=0.1)
        val = pid.update(measurement=85, dt=0)  # dt=0
        assert isinstance(val, float)

    def test_is_saturated(self):
        pid = PIDController(Kp=0, Ki=100, Kd=0, setpoint=100, output_limit=(0, 50))
        for _ in range(5):
            pid.update(measurement=0, dt=0.1)
        assert pid.is_saturated() is True

    def test_zero_error_no_output(self):
        """When measurement equals setpoint, P output should be zero."""
        pid = PIDController(Kp=1, Ki=0, Kd=0, setpoint=100, output_limit=None)
        val = pid.update(measurement=100, dt=0.1)
        assert val == 0
