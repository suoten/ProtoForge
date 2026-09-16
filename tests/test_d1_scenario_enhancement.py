"""D.1 场景引擎增强集成测试.

覆盖：
1. 时间序列回放通过 Scenario 驱动设备点位（replay_config）
2. 回放值触发协同规则（回放 temp>80 → 联动风扇）
3. 故障注入链式（协同规则 → inject_fault 动作 → 设备故障激活）
4. 回放耗尽后场景继续运行不报错
"""

from __future__ import annotations

import os

os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_d1_scenario.db")

import pytest

from protoforge.engine.device import DeviceInstance
from protoforge.engine.generator import DataGenerator
from protoforge.simulation.scenario import Scenario
from protoforge.models.device import (
    DataType,
    DeviceConfig,
    GeneratorType,
    PointConfig,
)
from protoforge.models.scenario import (
    Rule,
    RuleType,
    ScenarioConfig,
)


def _gen() -> DataGenerator:
    return DataGenerator()


def _temp_sensor() -> DeviceInstance:
    cfg = DeviceConfig(
        id="temp-sensor",
        name="Temperature Sensor",
        protocol="modbus_tcp",
        protocol_config={"min_startup_time": 0},
        points=[
            PointConfig(
                name="temperature",
                address="10",
                data_type=DataType.FLOAT32,
                generator_type=GeneratorType.FIXED,
                fixed_value=25.0,
                access="rw",
            ),
        ],
    )
    return DeviceInstance(cfg, _gen())


def _fan() -> DeviceInstance:
    cfg = DeviceConfig(
        id="fan",
        name="Cooling Fan",
        protocol="modbus_tcp",
        protocol_config={"min_startup_time": 0},
        points=[
            PointConfig(
                name="speed",
                address="20",
                data_type=DataType.FLOAT32,
                generator_type=GeneratorType.FIXED,
                fixed_value=0.0,
                access="rw",
            ),
        ],
    )
    return DeviceInstance(cfg, _gen())


async def _bring_online(*devices: DeviceInstance) -> None:
    for d in devices:
        d.start()
    for d in devices:
        await d.tick()


def _read_value(device: DeviceInstance, point: str):
    pv = device.read_point(point)
    return pv.value if pv else None


# ---------------------------------------------------------------------------
#  时间序列回放驱动
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_drives_device_points():
    """回放数据写入设备点位：温度从 25 → 30 → 35。"""
    sensor = _temp_sensor()
    replay_data = [
        {"ts": 0, "device_id": "temp-sensor", "point": "temperature", "value": 25.0},
        {"ts": 1, "device_id": "temp-sensor", "point": "temperature", "value": 30.0},
        {"ts": 2, "device_id": "temp-sensor", "point": "temperature", "value": 35.0},
    ]
    config = ScenarioConfig(
        id="scn-replay",
        name="Replay",
        replay_config={"source": replay_data, "speed": 1.0, "loop": False},
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    await _bring_online(sensor)
    scenario.start()

    assert _read_value(sensor, "temperature") == 25.0  # 初始 fixed_value
    await scenario.tick()
    assert _read_value(sensor, "temperature") == 25.0  # 第 0 帧
    await scenario.tick()
    assert _read_value(sensor, "temperature") == 30.0  # 第 1 帧
    await scenario.tick()
    assert _read_value(sensor, "temperature") == 35.0  # 第 2 帧


@pytest.mark.asyncio
async def test_replay_triggers_collaboration_rule():
    """回放温度 > 80 时触发协同规则联动风扇。

    回放序列：75(不触发) → 85(触发) → 90(触发但 cooldown 抑制)
    """
    sensor = _temp_sensor()
    fan = _fan()
    replay_data = [
        {"ts": 0, "device_id": "temp-sensor", "point": "temperature", "value": 75.0},
        {"ts": 1, "device_id": "temp-sensor", "point": "temperature", "value": 85.0},
        {"ts": 2, "device_id": "temp-sensor", "point": "temperature", "value": 90.0},
    ]
    config = ScenarioConfig(
        id="scn-replay-collab",
        name="Replay Collab",
        replay_config={"source": replay_data, "speed": 1.0, "loop": False},
        rules=[
            Rule(
                id="rule-fan",
                name="Fan on high temp",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "set", "value": 100}
                ],
                cooldown=10.0,  # 大 cooldown 防止重复触发
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    # 帧0: temp=75, 不触发
    await scenario.tick()
    assert _read_value(fan, "speed") == 0.0

    # 帧1: temp=85, 触发
    await scenario.tick()
    assert _read_value(fan, "speed") == 100

    # 帧2: temp=90, cooldown 抑制（fan.speed 仍为 100，未被重新设置）
    await scenario.tick()
    assert _read_value(fan, "speed") == 100


@pytest.mark.asyncio
async def test_replay_exhausted_scenario_continues():
    """回放耗尽后，场景继续运行不报错。"""
    sensor = _temp_sensor()
    replay_data = [
        {"ts": 0, "device_id": "temp-sensor", "point": "temperature", "value": 40.0},
    ]
    config = ScenarioConfig(
        id="scn-replay-exhaust",
        name="Replay Exhaust",
        replay_config={"source": replay_data, "speed": 1.0, "loop": False},
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    await _bring_online(sensor)
    scenario.start()

    await scenario.tick()  # 消费唯一一帧
    assert _read_value(sensor, "temperature") == 40.0
    # 耗尽后再 tick，不应抛异常
    await scenario.tick()
    await scenario.tick()
    assert _read_value(sensor, "temperature") == 40.0  # 值保持


@pytest.mark.asyncio
async def test_replay_loop_continuously_feeds():
    """loop=True 回放循环喂入数据。"""
    sensor = _temp_sensor()
    replay_data = [
        {"ts": 0, "device_id": "temp-sensor", "point": "temperature", "value": 10.0},
        {"ts": 1, "device_id": "temp-sensor", "point": "temperature", "value": 20.0},
    ]
    config = ScenarioConfig(
        id="scn-replay-loop",
        name="Replay Loop",
        replay_config={"source": replay_data, "speed": 1.0, "loop": True},
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    await _bring_online(sensor)
    scenario.start()

    await scenario.tick()
    assert _read_value(sensor, "temperature") == 10.0
    await scenario.tick()
    assert _read_value(sensor, "temperature") == 20.0
    await scenario.tick()
    assert _read_value(sensor, "temperature") == 10.0  # 循环回第一帧
    await scenario.tick()
    assert _read_value(sensor, "temperature") == 20.0


# ---------------------------------------------------------------------------
#  故障注入链式
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collaboration_inject_fault_action():
    """协同规则触发 inject_fault 动作：temp>80 → 向 temp-sensor 注入 sensor_noise 故障。"""
    sensor = _temp_sensor()
    config = ScenarioConfig(
        id="scn-fault-inject",
        name="Fault Inject",
        rules=[
            Rule(
                id="rule-inject",
                name="Inject noise on high temp",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {
                        "target_device_id": "temp-sensor",
                        "target_point": "temperature",
                        "action_type": "inject_fault",
                        "value": {
                            "fault_type": "sensor_noise",
                            "parameters": {"noise_std": 2.0, "duration": 60.0},
                        },
                    }
                ],
                cooldown=5.0,
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    await _bring_online(sensor)
    scenario.start()

    # 初始无活跃故障
    assert len(sensor.get_active_faults()) == 0

    # 升温触发故障注入
    await sensor.write_point("temperature", 85.0)
    await scenario.tick()

    active_faults = sensor.get_active_faults()
    assert len(active_faults) >= 1, f"Expected fault injected, got {len(active_faults)}"
    assert active_faults[0].fault_type.value == "sensor_noise"


@pytest.mark.asyncio
async def test_collaboration_inject_fault_without_target_point():
    """inject_fault 动作 target_point 为空时，默认 target_point='*'。"""
    sensor = _temp_sensor()
    config = ScenarioConfig(
        id="scn-fault-nopoint",
        name="Fault NoPoint",
        rules=[
            Rule(
                id="rule-inject-nopoint",
                name="Inject device failure",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {
                        "target_device_id": "temp-sensor",
                        "action_type": "inject_fault",
                        "value": {
                            "fault_type": "sensor_stuck",
                            "parameters": {"duration": 30.0},
                        },
                    }
                ],
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    await _bring_online(sensor)
    scenario.start()

    await sensor.write_point("temperature", 90.0)
    await scenario.tick()

    active_faults = sensor.get_active_faults()
    assert len(active_faults) >= 1
    assert active_faults[0].fault_type.value == "sensor_stuck"


@pytest.mark.asyncio
async def test_collaboration_inject_fault_chain_with_set():
    """链式：inject_fault → set 另一设备点位。"""
    sensor = _temp_sensor()
    fan = _fan()
    config = ScenarioConfig(
        id="scn-fault-chain",
        name="Fault Chain",
        rules=[
            Rule(
                id="rule-fault-chain",
                name="Inject fault then set fan",
                rule_type=RuleType.COLLABORATION,
                source_device_id="temp-sensor",
                source_point="temperature",
                condition={"operator": ">", "value": 80},
                actions=[
                    {
                        "target_device_id": "temp-sensor",
                        "target_point": "temperature",
                        "action_type": "inject_fault",
                        "value": {"fault_type": "sensor_drift", "parameters": {"drift_rate": 0.5, "duration": 60.0}},
                    },
                    {"target_device_id": "fan", "target_point": "speed", "action_type": "set", "value": 100},
                ],
                cooldown=5.0,
            )
        ],
    )
    scenario = Scenario(config)
    scenario.add_device(sensor)
    scenario.add_device(fan)
    await _bring_online(sensor, fan)
    scenario.start()

    await sensor.write_point("temperature", 85.0)
    await scenario.tick()

    # 故障已注入
    assert len(sensor.get_active_faults()) >= 1
    assert sensor.get_active_faults()[0].fault_type.value == "sensor_drift"
    # 风扇已联动
    assert _read_value(fan, "speed") == 100
